#!/usr/bin/env python3
"""Section C — Daily mechanism-enrichment implementation proposal.

A read-only planner that consumes the existing Daily
mechanism-enrichment diagnostic
(:mod:`scripts.section_c_daily_mechanism_enrichment_diagnostic`) and
proposes how a Daily Market headline (sourced from
``news_inbox.json``) could carry a ``mechanism_family`` value
BEFORE it is promoted into Section C.

The planner does not apply anything.  It surfaces a study report
intended to be reviewed and turned into a worksheet before any
production change is made.

Context (recap of the diagnostic's finding)
-------------------------------------------

* ``news_inbox.json`` carries no ``mechanism_family`` field today —
  the inbox schema is ``{title, source, published_at, url}``.
* The live events DB exposes a ``mechanism_family`` column on
  ``events`` and on ``curated_candidates``, but the diagnostic
  reports zero rows with a usable value or a sparse, unreliable
  set.  There is no other enrichment source the diagnostic could
  find in this repository.
* Exact and normalised headline matching from the inbox into the
  events table therefore lands every Daily candidate in the
  diagnostic's ``enrichment_gaps`` list — the match path is
  insufficient on its own as of today.

This planner proposes which forward path the operator could adopt
to close that gap without introducing fuzzy / LLM matching as the
default and without changing Daily production filters yet.

Read-only by construction
-------------------------

* Single upstream source: the diagnostic's
  :func:`run_section_c_daily_mechanism_enrichment_diagnostic`,
  reached through a thin lazy seam so tests patch the call
  directly and the planner never depends on a live inbox or DB.
* No DB writes anywhere.  No ``yfinance``, ``market_data``, LLM,
  or paid provider call.  No FastAPI surface (never imports
  ``api`` or ``routes.*``).
* No mutation of ``news_inbox``, ``events``, ``curated_candidates``,
  or any artifact file.  ``--output`` writes a single JSON file
  only when explicitly passed; the inbox / DB / cache stay
  untouched.
* No new ``mechanism_family`` value is assigned anywhere in this
  script.  Every path described is a description of what an
  operator workflow would do; the planner does not perform the
  workflow.
* The planner never recommends fuzzy LLM matching as the default;
  ``fuzzy_llm_matching`` is listed in ``infeasible_paths`` by
  construction with an explicit reason.

Conservative wording
--------------------

Banned tokens in emitted prose: ``proof``, ``proven``, ``broken``,
``wrong``, ``must fix``, ``guaranteed``, ``automatically``,
``definitely``, ``causes``, ``causation``, ``will assign``,
``will enrich``, ``correct mechanism``, ``rule guarantees``.  The
planner says "would" and "could" — never "will".

Output contract (JSON)::

    {
      "ok":                       bool,
      "candidates_checked":       int,
      "enrichment_source_status": [
        {"source": str, "present": bool, "rows_with_value": int},
        ...
      ],
      "feasible_paths": [
        {
          "path_id":              str,
          "description":          str,
          "trigger_conditions":   [str, ...],
        },
        ...
      ],
      "infeasible_paths": [
        {
          "path_id":              str,
          "description":          str,
          "reason_infeasible":    str,
        },
        ...
      ],
      "recommended_path":         str,
      "required_schema_changes":  [
        {"surface": str, "field_or_file": str, "rationale": str},
        ...
      ],
      "false_positive_risks":     [str, ...],
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
    }

Usage::

    python scripts/section_c_daily_mechanism_enrichment_plan.py --json
    python scripts/section_c_daily_mechanism_enrichment_plan.py --json \\
        --inbox-path news_inbox.json --db-path events.db \\
        --output artifacts/section_c_daily_mechanism_enrichment_plan.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_INBOX_PATH: str = "news_inbox.json"


# ---------------------------------------------------------------------------
# Path catalogue.
#
# Each candidate path the planner reasons about is named here once.
# Tests pin the catalogue so a future drift gets caught.  Every
# path_id used in `feasible_paths` or `infeasible_paths` is drawn
# from this constant.
# ---------------------------------------------------------------------------


_PATH_EXACT_MATCH:          str = "exact_or_normalized_event_match"
_PATH_INGESTION_ALLOW_LIST: str = "enrich_at_ingestion_via_curated_allow_list"
_PATH_ARTIFACT_GATE:        str = (
    "require_analyzed_event_artifact_before_section_c_inclusion"
)
_PATH_MANUAL_REVIEW_QUEUE:  str = "manual_operator_review_queue"
_PATH_FUZZY_LLM:            str = "fuzzy_llm_matching"


_PATH_DESCRIPTIONS: dict[str, str] = {
    _PATH_EXACT_MATCH: (
        "For each inbox row, look for an event in the DB whose "
        "headline exactly equals (or normalises to the same string "
        "as) the inbox title and whose mechanism_family is set to a "
        "usable value.  When the match exists, surface that "
        "mechanism_family as a candidate enrichment for the inbox "
        "row.  The diagnostic implements exactly this match path "
        "today."
    ),
    _PATH_INGESTION_ALLOW_LIST: (
        "Extend the news ingestion path so each inbox row is "
        "checked against a small operator-curated allow-list of "
        "(source_url_prefix, mechanism_family) entries at ingestion "
        "time.  Rows that match the allow-list carry "
        "mechanism_family forward; rows that do not match are "
        "queued for operator review rather than promoted to "
        "Section C without one."
    ),
    _PATH_ARTIFACT_GATE: (
        "Require an analyzed-event artifact (a small JSON file "
        "carrying candidate_id, headline, event_date, "
        "mechanism_family and an operator signature) to exist on "
        "disk before any Daily candidate is promoted into Section "
        "C.  The Section C boundary check would refuse to surface "
        "a row whose artifact is missing.  No artifact, no "
        "promotion."
    ),
    _PATH_MANUAL_REVIEW_QUEUE: (
        "Add a per-inbox-row operator review queue (analogous to "
        "the existing manual_event_intake_worksheet.py output) "
        "that the operator fills with mechanism_family by hand "
        "before the row is promoted.  The queue would be a "
        "JSON or CSV file the operator edits; the planner does "
        "not propose a write-back path."
    ),
    _PATH_FUZZY_LLM: (
        "Use an LLM (or other fuzzy matcher) to guess a "
        "mechanism_family for each inbox row from the headline "
        "alone, without an operator confirmation step."
    ),
}


# ---------------------------------------------------------------------------
# False-positive risks — short, conservative bullets.  Each risk
# names the path it relates to so the operator can map a risk back
# to a candidate path during review.
# ---------------------------------------------------------------------------


_FP_RISKS: tuple[str, ...] = (
    "exact_or_normalized_event_match risk: an inbox headline that "
    "happens to match an older, unrelated event sharing the same "
    "string would surface a mechanism_family that does not "
    "describe the new story; the diagnostic's caution field "
    "already calls for operator review of every match.",
    "enrich_at_ingestion_via_curated_allow_list risk: an allow-list "
    "scoped to source_url_prefix would miss novel headlines from "
    "the same source whose mechanism_family differs from the "
    "source's usual coverage; the allow-list should not over-fit "
    "to source identity alone.",
    "require_analyzed_event_artifact_before_section_c_inclusion "
    "risk: a backlog in operator artifact production would block "
    "real news from surfacing in Section C; the planner suggests "
    "the artifact carry a freshness window so the operator sees "
    "stale gates rather than silently dropped rows.",
    "manual_operator_review_queue risk: the queue depends on "
    "operator availability; stale queue entries would produce a "
    "stale Section C surface.  An audit timestamp on the queue "
    "entry would let an operator spot stale rows during review.",
    "fuzzy_llm_matching risk: assigning a mechanism_family from a "
    "headline alone, without operator confirmation, would produce "
    "an enrichment that looks confident but is not auditable; the "
    "planner lists this path as infeasible as a default for that "
    "reason.",
)


# ---------------------------------------------------------------------------
# Schema changes the recommended path would require.  Each entry
# names a real surface in the repo and a concrete field or file
# the operator would need to add.  The planner does not write any
# of these surfaces.
# ---------------------------------------------------------------------------


_SCHEMA_CHANGES_ARTIFACT_GATE: tuple[dict[str, str], ...] = (
    {
        "surface":        "artifacts/",
        "field_or_file":  "analyzed_event_artifact.<candidate_id>.json",
        "rationale": (
            "One small JSON file per Daily candidate carrying "
            "candidate_id, headline, event_date, mechanism_family, "
            "and an operator signature.  Section C's boundary "
            "check would refuse promotion when this file is "
            "missing for the candidate."
        ),
    },
    {
        "surface":        "news_inbox.json",
        "field_or_file":  "candidate_id",
        "rationale": (
            "The inbox row would carry a stable candidate_id so "
            "the Section C gate could look up the matching "
            "analyzed-event artifact deterministically.  The "
            "planner does not propose a candidate_id allocation "
            "scheme here."
        ),
    },
    {
        "surface":        "routes/movers.py",
        "field_or_file":  "Section C promotion boundary",
        "rationale": (
            "The Section C surface would gate promotion behind "
            "the artifact's existence and the artifact's "
            "mechanism_family value.  The gate would carry a "
            "freshness check so an aged artifact is surfaced as "
            "a stale row rather than as a fresh one."
        ),
    },
    {
        "surface":        "scripts/manual_event_intake_worksheet.py",
        "field_or_file":  "analyzed-event artifact emission mode",
        "rationale": (
            "The existing worksheet generator already carries the "
            "mechanism_family field in its row shape.  An "
            "emission mode that writes one artifact per filled "
            "worksheet row would feed the Section C gate without "
            "a separate operator surface."
        ),
    },
)


_SCHEMA_CHANGES_INGESTION: tuple[dict[str, str], ...] = (
    {
        "surface":        "news_inbox.json",
        "field_or_file":  "mechanism_family",
        "rationale": (
            "The inbox row would carry mechanism_family directly, "
            "filled at ingestion time from the curated allow-list.  "
            "Today the inbox schema does not include this field."
        ),
    },
    {
        "surface":        "news_fetch.py",
        "field_or_file":  "allow_list lookup at ingestion",
        "rationale": (
            "A small lookup against an operator-curated "
            "(source_url_prefix, mechanism_family) table would "
            "attach a mechanism_family to inbox rows whose source "
            "URL falls inside an allow-list entry.  Misses are "
            "queued for operator review rather than promoted."
        ),
    },
    {
        "surface":        "artifacts/",
        "field_or_file":  "mechanism_family_allow_list.json",
        "rationale": (
            "An operator-edited JSON file holding the allow-list "
            "entries.  The planner does not propose the entries "
            "themselves; the operator owns the allow-list."
        ),
    },
)


_SCHEMA_CHANGES_MANUAL_QUEUE: tuple[dict[str, str], ...] = (
    {
        "surface":        "artifacts/",
        "field_or_file":  "daily_mechanism_review_queue.csv",
        "rationale": (
            "An operator-edited CSV (or JSON) file carrying one "
            "row per pending inbox candidate with "
            "candidate_id, headline, mechanism_family, "
            "review_timestamp, and operator_notes.  The Section "
            "C surface would refuse to promote rows whose "
            "mechanism_family field in this queue is blank."
        ),
    },
    {
        "surface":        "news_inbox.json",
        "field_or_file":  "candidate_id",
        "rationale": (
            "A stable candidate_id on each inbox row so the "
            "queue and the inbox stay referentially aligned "
            "across regenerations."
        ),
    },
)


# Reason strings used when surfacing infeasibility.  Stored as
# constants so tests can pin the prose and so the planner stays
# consistent across runs.


_REASON_EXACT_MATCH_NO_SOURCES: str = (
    "the diagnostic reports zero rows in any enrichment source "
    "(events.mechanism_family and curated_candidates.mechanism_family "
    "are empty or set to 'none'); the exact / normalised match path "
    "has nothing to match against today."
)
_REASON_EXACT_MATCH_NO_HITS: str = (
    "the diagnostic ran the exact and normalised match path against "
    "every inbox candidate and surfaced zero possible_event_matches; "
    "every candidate landed in enrichment_gaps, so the match path "
    "is insufficient as a default today."
)
_REASON_EXACT_MATCH_PARTIAL: str = (
    "the diagnostic surfaced some exact / normalised matches but "
    "also produced enrichment_gaps for the remaining candidates; "
    "the match path is insufficient as the sole default and the "
    "diagnostic already requires operator review for each match."
)
_REASON_FUZZY_LLM_ALWAYS: str = (
    "fuzzy / LLM matching from a headline alone, without an "
    "operator confirmation step, would attach a mechanism_family "
    "that looks confident but is not auditable; the planner "
    "excludes this path as a default by construction."
)


# ---------------------------------------------------------------------------
# Patchable seam — lazy import of the upstream diagnostic.
# ---------------------------------------------------------------------------


def _build_enrichment_diagnostic(
    *,
    inbox_path: str,
    db_path:    str | None,
) -> dict[str, Any]:
    """Call the existing Daily mechanism-enrichment diagnostic and
    return its full report.

    Lazy-imports the diagnostic so the planner's top-level import
    surface stays narrow.  Tests patch this seam directly with a
    synthetic payload so they never depend on a live inbox / DB.
    """
    from scripts.section_c_daily_mechanism_enrichment_diagnostic import (
        run_section_c_daily_mechanism_enrichment_diagnostic,
    )
    return run_section_c_daily_mechanism_enrichment_diagnostic(
        inbox_path=inbox_path,
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_daily_mechanism_enrichment_plan(
    *,
    inbox_path:  str = _DEFAULT_INBOX_PATH,
    db_path:     str | None = None,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Run the read-only enrichment planner.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    try:
        diagnostic = _build_enrichment_diagnostic(
            inbox_path=inbox_path,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"daily mechanism-enrichment diagnostic raised: "
            f"{type(exc).__name__}: {exc}"
        )
        diagnostic = {}

    for w in diagnostic.get("warnings") or []:
        if isinstance(w, str) and w:
            warnings.append(f"upstream diagnostic: {w}")
    for e in diagnostic.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(f"upstream diagnostic: {e}")

    candidates_checked = diagnostic.get("daily_candidates_checked")
    if not isinstance(candidates_checked, int) or candidates_checked < 0:
        candidates_checked = 0

    enrichment_source_status = _coerce_sources(
        raw=diagnostic.get("enrichment_sources_available"),
        warnings=warnings,
    )

    possible_matches = diagnostic.get("possible_event_matches") or []
    if not isinstance(possible_matches, list):
        possible_matches = []
    enrichment_gaps = diagnostic.get("enrichment_gaps") or []
    if not isinstance(enrichment_gaps, list):
        enrichment_gaps = []

    has_any_source = any(
        s.get("present") is True and int(s.get("rows_with_value") or 0) > 0
        for s in enrichment_source_status
    )
    has_any_match = len(possible_matches) > 0
    has_any_gap = len(enrichment_gaps) > 0

    feasible, infeasible = _classify_paths(
        has_any_source=has_any_source,
        has_any_match=has_any_match,
        has_any_gap=has_any_gap,
    )

    recommended = _recommend_path(feasible=feasible)

    required_schema_changes = _schema_changes_for(recommended)

    envelope: dict[str, Any] = {
        "ok":                       not errors,
        "candidates_checked":       candidates_checked,
        "enrichment_source_status": enrichment_source_status,
        "feasible_paths":           feasible,
        "infeasible_paths":         infeasible,
        "recommended_path":         recommended,
        "required_schema_changes":  required_schema_changes,
        "false_positive_risks":     list(_FP_RISKS),
        "warnings":                 warnings,
        "errors":                   errors,
    }

    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh, indent=2, sort_keys=True, default=str)
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_sources(
    *, raw: Any, warnings: list[str],
) -> list[dict[str, Any]]:
    """Normalise the diagnostic's ``enrichment_sources_available``
    list into a stable, JSON-safe shape.  When the diagnostic
    returns nothing usable, surface a single warning and emit the
    two known source names with zero counts so downstream
    consumers always see the same key set.
    """
    out: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            if not isinstance(source, str) or not source:
                continue
            rows = entry.get("rows_with_value")
            if not isinstance(rows, int) or isinstance(rows, bool):
                rows = 0
            present = bool(entry.get("present")) and rows > 0
            out.append({
                "source":          source,
                "present":         present,
                "rows_with_value": int(rows),
            })
    if out:
        return out

    # Diagnostic returned an unusable shape — surface the two
    # canonical source names with zero counts so the envelope is
    # still well formed.  Warn so the operator notices.
    warnings.append(
        "upstream diagnostic returned no enrichment_sources_available "
        "entries; the planner emits the two canonical source names "
        "with zero counts so the envelope stays well formed"
    )
    for source in (
        "events.mechanism_family",
        "curated_candidates.mechanism_family",
    ):
        out.append({
            "source":          source,
            "present":         False,
            "rows_with_value": 0,
        })
    return out


def _classify_paths(
    *,
    has_any_source: bool,
    has_any_match:  bool,
    has_any_gap:    bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Walk the path catalogue and return ``(feasible, infeasible)``.

    The three forward-looking paths
    (``enrich_at_ingestion_via_curated_allow_list``,
    ``require_analyzed_event_artifact_before_section_c_inclusion``,
    ``manual_operator_review_queue``) are listed as feasible
    regardless of the diagnostic's current state — they describe
    operator workflows that could close the gap.

    The exact / normalised match path is listed as feasible only
    when the diagnostic shows an enrichment source AND at least one
    match AND no remaining gaps.  Any partial-coverage or no-source
    state lands the path in ``infeasible_paths`` with a reason.

    Fuzzy / LLM matching is listed in ``infeasible_paths`` always,
    by construction.
    """
    feasible:   list[dict[str, Any]] = []
    infeasible: list[dict[str, Any]] = []

    # --- exact / normalised match path -----------------------------
    if not has_any_source:
        infeasible.append({
            "path_id":          _PATH_EXACT_MATCH,
            "description":      _PATH_DESCRIPTIONS[_PATH_EXACT_MATCH],
            "reason_infeasible": _REASON_EXACT_MATCH_NO_SOURCES,
        })
    elif not has_any_match:
        infeasible.append({
            "path_id":          _PATH_EXACT_MATCH,
            "description":      _PATH_DESCRIPTIONS[_PATH_EXACT_MATCH],
            "reason_infeasible": _REASON_EXACT_MATCH_NO_HITS,
        })
    elif has_any_gap:
        infeasible.append({
            "path_id":          _PATH_EXACT_MATCH,
            "description":      _PATH_DESCRIPTIONS[_PATH_EXACT_MATCH],
            "reason_infeasible": _REASON_EXACT_MATCH_PARTIAL,
        })
    else:
        feasible.append({
            "path_id":     _PATH_EXACT_MATCH,
            "description": _PATH_DESCRIPTIONS[_PATH_EXACT_MATCH],
            "trigger_conditions": [
                "the diagnostic reports at least one enrichment "
                "source with rows_with_value > 0",
                "every inbox candidate produces an exact or "
                "normalised match against an event whose "
                "mechanism_family is set to a usable value",
                "operator review still confirms each match before "
                "promotion (the diagnostic's caution field is "
                "honoured)",
            ],
        })

    # --- forward-looking feasible paths ----------------------------
    feasible.append({
        "path_id":     _PATH_INGESTION_ALLOW_LIST,
        "description": _PATH_DESCRIPTIONS[_PATH_INGESTION_ALLOW_LIST],
        "trigger_conditions": [
            "operator curates a (source_url_prefix, "
            "mechanism_family) allow-list",
            "news_inbox.json carries a mechanism_family field at "
            "ingestion time",
            "inbox rows that do not match the allow-list are "
            "queued for operator review rather than promoted",
        ],
    })
    feasible.append({
        "path_id":     _PATH_ARTIFACT_GATE,
        "description": _PATH_DESCRIPTIONS[_PATH_ARTIFACT_GATE],
        "trigger_conditions": [
            "each Daily candidate has a stable candidate_id",
            "an analyzed-event artifact exists on disk under "
            "artifacts/ for the candidate, carrying "
            "mechanism_family and an operator signature",
            "the Section C boundary check looks up the artifact "
            "by candidate_id and refuses promotion when the "
            "artifact is missing or stale",
        ],
    })
    feasible.append({
        "path_id":     _PATH_MANUAL_REVIEW_QUEUE,
        "description": _PATH_DESCRIPTIONS[_PATH_MANUAL_REVIEW_QUEUE],
        "trigger_conditions": [
            "operator maintains a review queue (CSV or JSON) "
            "carrying mechanism_family per candidate",
            "Section C refuses to promote rows whose "
            "mechanism_family in the queue is blank",
            "queue entries carry a review_timestamp so stale "
            "entries are visible during operator audit",
        ],
    })

    # --- fuzzy / LLM matching is always infeasible ----------------
    infeasible.append({
        "path_id":          _PATH_FUZZY_LLM,
        "description":      _PATH_DESCRIPTIONS[_PATH_FUZZY_LLM],
        "reason_infeasible": _REASON_FUZZY_LLM_ALWAYS,
    })

    return feasible, infeasible


def _recommend_path(*, feasible: list[dict[str, Any]]) -> str:
    """Pick a recommended path id from ``feasible``.

    The recommendation is conservative: the planner always
    suggests
    ``require_analyzed_event_artifact_before_section_c_inclusion``
    as the safest forward path.  Even when exact match is
    technically feasible, the artifact gate is still recommended
    because the diagnostic's match path requires per-row operator
    review anyway and the artifact gate materialises that review.
    Falls back to the manual review queue, then to the first
    feasible entry, then to the artifact gate sentinel when the
    catalogue has been pruned to nothing.
    """
    feasible_ids = {f["path_id"] for f in feasible}
    if _PATH_ARTIFACT_GATE in feasible_ids:
        return _PATH_ARTIFACT_GATE
    # Defensive — the artifact gate is always feasible per
    # _classify_paths.  If the catalogue is ever pruned, fall back
    # to the manual review queue, then to whatever feasible path
    # remains.
    if _PATH_MANUAL_REVIEW_QUEUE in feasible_ids:
        return _PATH_MANUAL_REVIEW_QUEUE
    if feasible:
        return feasible[0]["path_id"]
    # No feasible path at all — should not happen because the
    # forward-looking paths are always feasible.  Surface a stable
    # sentinel so downstream consumers see a value.
    return _PATH_ARTIFACT_GATE


def _schema_changes_for(path_id: str) -> list[dict[str, str]]:
    """Return the schema-change list the recommended path would
    require.  Each entry is a small dict with a real surface and a
    concrete field-or-file the operator would need to add.
    """
    if path_id == _PATH_ARTIFACT_GATE:
        return [dict(c) for c in _SCHEMA_CHANGES_ARTIFACT_GATE]
    if path_id == _PATH_INGESTION_ALLOW_LIST:
        return [dict(c) for c in _SCHEMA_CHANGES_INGESTION]
    if path_id == _PATH_MANUAL_REVIEW_QUEUE:
        return [dict(c) for c in _SCHEMA_CHANGES_MANUAL_QUEUE]
    # exact_or_normalized_event_match needs no new schema; the
    # diagnostic already exercises the path.  Return an empty list
    # rather than fabricating an entry.
    return []


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Section C daily mechanism-enrichment plan", "",
    ]
    lines.append(f"OK:                           {report['ok']}")
    lines.append(f"Candidates checked:           {report['candidates_checked']}")
    lines.append(f"Recommended path:             {report['recommended_path']}")
    lines.append("")
    lines.append(
        f"Enrichment source status "
        f"({len(report['enrichment_source_status'])}):"
    )
    for s in report["enrichment_source_status"]:
        if isinstance(s, dict):
            lines.append(
                f"  - {s.get('source'):<48} present={s.get('present')} "
                f"rows={s.get('rows_with_value')}"
            )
    lines.append("")
    lines.append(f"Feasible paths ({len(report['feasible_paths'])}):")
    for p in report["feasible_paths"]:
        if isinstance(p, dict):
            lines.append(f"  - {p.get('path_id')}")
            for tc in p.get("trigger_conditions") or []:
                lines.append(f"      * {tc}")
    lines.append("")
    lines.append(f"Infeasible paths ({len(report['infeasible_paths'])}):")
    for p in report["infeasible_paths"]:
        if isinstance(p, dict):
            lines.append(f"  - {p.get('path_id')}")
            lines.append(f"      reason: {p.get('reason_infeasible')}")
    lines.append("")
    lines.append(
        f"Required schema changes ({len(report['required_schema_changes'])}):"
    )
    for c in report["required_schema_changes"]:
        if isinstance(c, dict):
            lines.append(
                f"  - {c.get('surface')}: {c.get('field_or_file')}"
            )
            lines.append(f"      rationale: {c.get('rationale')}")
    lines.append("")
    lines.append(
        f"False-positive risks ({len(report['false_positive_risks'])}):"
    )
    for risk in report["false_positive_risks"]:
        lines.append(f"  - {risk}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only Section C Daily mechanism-enrichment "
            "implementation planner.  Consumes the existing Daily "
            "mechanism-enrichment diagnostic and proposes which "
            "forward path could attach a mechanism_family to a "
            "Daily candidate before Section C inclusion.  Does NOT "
            "mutate news_inbox, events, curated_candidates, or any "
            "artifact.  Does NOT assign mechanism_family.  Does NOT "
            "recommend fuzzy / LLM matching as a default."
        ),
    )
    parser.add_argument(
        "--inbox-path", dest="inbox_path",
        default=_DEFAULT_INBOX_PATH,
        help=(
            f"Path to the inbox file the upstream diagnostic reads "
            f"(default {_DEFAULT_INBOX_PATH!r}).  Read-only."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the events DB the upstream diagnostic "
            "reads.  Defaults to db.DB_FILE.  Read-only by "
            "construction."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text plan.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the planner has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_section_c_daily_mechanism_enrichment_plan(
        inbox_path=args.inbox_path,
        db_path=args.db_path,
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_daily_mechanism_enrichment_plan",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
