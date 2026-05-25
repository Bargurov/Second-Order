#!/usr/bin/env python3
"""Section C — Daily artifact-gated inclusion implementation design.

A read-only planner that converts the
``require_analyzed_event_artifact_before_section_c_inclusion`` path
proposed by
:mod:`scripts.section_c_daily_mechanism_enrichment_plan` into an
implementation-ready design.

The upstream plan recommended the artifact-gate path because:

* ``news_inbox.json`` carries no ``mechanism_family`` field, so a
  Daily candidate has no reliable handle on the four fields Section
  C actually needs (``mechanism_family``, ``primary_ticker``,
  ``benchmark_ticker``, ``market_relevance``);
* ``events.db`` is not a reliable enrichment source — exact and
  normalised headline matching surfaces partial / zero hits;
* fuzzy headline matching from a headline alone, without an operator
  confirmation step, would attach a label that looks confident but
  is not auditable.

This planner describes the gate the operator would wire to close
that gap: Daily Section C would refuse to promote an inbox row that
does not point at a reviewed analyzed-event artifact carrying the
four required fields.  No artifact, no Section C promotion — the
row is *held for review or enrichment* on the operator's worklist
rather than surfaced.

Read-only by construction
-------------------------

* The planner emits a stable design.  It does not read the events
  DB, the inbox, or any artifact file at runtime; the design is the
  output.  This keeps the planner's surface narrow and avoids
  binding it to live state that would shift across runs.
* No DB writes anywhere.  No ``yfinance``, ``market_data``, LLM, or
  paid provider call.  No FastAPI surface (never imports ``api`` or
  ``routes.*``).
* No mutation of ``news_inbox``, ``events``, ``curated_candidates``,
  or any artifact file.  ``--output`` writes a single JSON file
  only when explicitly passed; the inbox / DB / cache stay
  untouched.
* No new ``mechanism_family`` value is assigned anywhere in this
  script.  Every path the planner describes is an operator workflow
  the operator would adopt; the planner does not perform the
  workflow.
* No production filter is changed.  ``implementation_targets``
  describes which files the operator would touch in a follow-up
  worksheet; the planner itself only describes them.
* Fuzzy headline matching is rejected by construction.  The
  ``rejected_sources`` block always lists ``fuzzy_headline_matching``
  with an explicit reason, regardless of the diagnostic's current
  state.

Conservative wording
--------------------

Banned tokens in emitted prose: ``proof``, ``proven``, ``broken``,
``wrong``, ``must fix``, ``guaranteed``, ``automatically``,
``definitely``, ``causes``, ``causation``, ``will assign``,
``will enrich``, ``correct mechanism``, ``rule guarantees``,
``alpha generated``, ``correct ticker``.  The planner says "would"
and "could" — never "will".

Output contract (JSON)::

    {
      "ok":                    bool,
      "proposed_gate": {
        "gate_id":                       str,
        "scope":                         str,
        "behavior":                      str,
        "required_artifact_kind":        str,
        "required_field_names":          [str, ...],
        "held_for_review_behavior":      str,
        "fuzzy_matching_default":        str,
        "promotion_criteria":            [str, ...],
      },
      "required_fields": [
        {"field": str, "type": str, "rationale": str},
        ...
      ],
      "candidate_sources": [
        {
          "source_id":                str,
          "surface":                  str,
          "description":              str,
          "operator_review_required": bool,
        },
        ...
      ],
      "rejected_sources": [
        {
          "source_id":         str,
          "description":       str,
          "reason_rejected":   str,
        },
        ...
      ],
      "implementation_targets": [
        {"path": str, "responsibility": str, "note": str},
        ...
      ],
      "example_allowed_case": {
        "inbox_headline":          str,
        "artifact_present":        bool,
        "artifact_fields_present": [str, ...],
        "promotion_outcome":       "admitted",
        "rationale":               str,
      },
      "example_blocked_case": {
        "inbox_headline":          str,
        "artifact_present":        bool,
        "missing_fields":          [str, ...],
        "promotion_outcome":       "held_for_review",
        "rationale":               str,
      },
      "false_positive_risks":   [str, ...],
      "warnings":               [str, ...],
      "errors":                 [str, ...],
    }

Usage::

    python scripts/section_c_daily_artifact_gate_plan.py --json
    python scripts/section_c_daily_artifact_gate_plan.py --json \\
        --output artifacts/section_c_daily_artifact_gate_plan.json
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


# ---------------------------------------------------------------------------
# Gate identity — pinned in tests so future drift is caught.
# ---------------------------------------------------------------------------

_GATE_ID: str = "daily_section_c_requires_analyzed_event_artifact"
_GATE_SCOPE: str = (
    "Daily Section C surface — the promotion boundary that admits a "
    "row sourced from news_inbox.json into the live Daily view."
)
_GATE_BEHAVIOR: str = (
    "Section C would refuse to promote a Daily candidate when no "
    "reviewed analyzed-event artifact exists on disk for the "
    "candidate, or when the artifact is present but does not "
    "carry the four required fields.  The check would run at the "
    "Section C promotion boundary, not at ingestion — the inbox "
    "loader continues to write rows; the gate only governs which "
    "of those rows surface in Section C."
)
_GATE_REQUIRED_ARTIFACT_KIND: str = (
    "analyzed_event_artifact (one JSON file per Daily candidate, "
    "produced by the operator-driven manual_event_intake_worksheet "
    "workflow or an equivalent operator-reviewed source — see "
    "candidate_sources for the catalogue)."
)
_GATE_HELD_FOR_REVIEW: str = (
    "An inbox row that has no matching artifact (or whose artifact "
    "is missing one of the four required fields) would be HELD on "
    "the operator review queue rather than surfaced.  The Daily "
    "Section C panel would not show the row; the operator's review "
    "worklist would.  This keeps the limitation visible without "
    "letting a low-information row enter the live surface."
)
_GATE_FUZZY_DEFAULT: str = (
    "Fuzzy or LLM-based headline matching is rejected as the gate's "
    "default source.  A mechanism_family attached to a headline by "
    "an unconfirmed fuzzy match would look confident but would not "
    "be auditable; the gate insists on a reviewed artifact instead."
)


# ---------------------------------------------------------------------------
# Required fields — the four the gate would key on, plus the
# candidate_id used to link an inbox row to its artifact.  The four
# spec-pinned fields appear first, in the order the spec lists them.
# ---------------------------------------------------------------------------


_REQUIRED_FIELDS: tuple[dict[str, str], ...] = (
    {
        "field":     "mechanism_family",
        "type":      "string (non-empty, not 'none')",
        "rationale": (
            "Section C is mechanism-keyed by construction; without "
            "a mechanism label the surface cannot describe why the "
            "row belongs there.  The Daily mechanism-enrichment "
            "diagnostic already documents that the inbox carries no "
            "mechanism_family today."
        ),
    },
    {
        "field":     "primary_ticker",
        "type":      "string (non-empty, uppercase)",
        "rationale": (
            "The Section C row needs a single-name ticker so the "
            "downstream Still Moving check can reason about price "
            "behaviour; the inbox row carries no ticker today."
        ),
    },
    {
        "field":     "benchmark_ticker",
        "type":      "string (non-empty, uppercase)",
        "rationale": (
            "Benchmark-adjusted evidence is the contract the Still "
            "Moving diagnostic enforces; admitting a Section C row "
            "without a benchmark would leave the downstream check "
            "with no comparator."
        ),
    },
    {
        "field":     "market_relevance",
        "type":      "float in [0.0, 1.0] (operator-supplied)",
        "rationale": (
            "An explicit operator-supplied relevance score replaces "
            "the inbox's coarse keyword-derived score, which the "
            "Daily quality diagnostic flagged as too noisy on its "
            "own; the operator's score is the audit trail."
        ),
    },
    {
        "field":     "candidate_id",
        "type":      "string (stable across regenerations)",
        "rationale": (
            "A stable candidate_id on each inbox row and on the "
            "matching artifact lets the gate look up the artifact "
            "by id rather than by headline string.  The planner "
            "does not propose an allocation scheme here; that is "
            "an operator decision."
        ),
    },
)


_REQUIRED_FIELD_NAMES: tuple[str, ...] = tuple(
    f["field"] for f in _REQUIRED_FIELDS
)


# ---------------------------------------------------------------------------
# Candidate sources — operator-reviewed artifact producers the gate
# would draw from.  Every entry names a real file in the repo or a
# real existing workflow.  No fuzzy / LLM source appears here.
# ---------------------------------------------------------------------------


_CANDIDATE_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "source_id":  "manual_event_intake_worksheet_artifact",
        "surface":    "scripts/manual_event_intake_worksheet.py",
        "description": (
            "The existing operator-filled worksheet already carries "
            "mechanism_family, primary_ticker, benchmark_ticker, "
            "and a candidate_id column.  An emission mode that "
            "writes one analyzed_event_artifact JSON per filled "
            "worksheet row would feed the gate directly.  The "
            "operator owns the worksheet rows; the planner does "
            "not propose row content."
        ),
        "operator_review_required": True,
    },
    {
        "source_id":  "freeze_candidate_evidence_artifact",
        "surface":    "scripts/freeze_candidate_evidence_artifact.py",
        "description": (
            "The freeze-candidate evidence artifact already carries "
            "event_id, headline, primary_ticker, benchmark_ticker "
            "and benchmark-adjusted statistics.  A small extension "
            "that pinned mechanism_family per record would let the "
            "artifact double as a gate input for events that "
            "appear on the freeze list.  The planner does not "
            "rewrite this script."
        ),
        "operator_review_required": True,
    },
    {
        "source_id":  "curated_event_yaml",
        "surface":    "examples/curated_events.example.yaml",
        "description": (
            "The curated-event YAML the Still Moving diagnostic "
            "already reads carries the same four fields.  An "
            "operator-curated entry in this file would qualify as "
            "a gate input when an inbox row's candidate_id "
            "matches a YAML entry's id.  The planner suggests "
            "this as a third candidate source, not a default."
        ),
        "operator_review_required": True,
    },
)


# ---------------------------------------------------------------------------
# Rejected sources — paths the planner refuses to recommend.  The
# fuzzy_headline_matching entry is pinned by construction so a future
# drift toward an unconfirmed LLM match is caught in tests.
# ---------------------------------------------------------------------------


_REJECTED_SOURCES: tuple[dict[str, str], ...] = (
    {
        "source_id":  "fuzzy_headline_matching",
        "description": (
            "Use an LLM or other fuzzy matcher to guess "
            "mechanism_family / primary_ticker / benchmark_ticker "
            "from the inbox headline alone, without an operator "
            "confirmation step."
        ),
        "reason_rejected": (
            "An unconfirmed fuzzy match would attach fields that "
            "look confident but are not auditable.  Section C "
            "would inherit an unreviewable label.  The gate "
            "insists on a reviewed artifact and lists fuzzy "
            "matching as a rejected default by construction."
        ),
    },
    {
        "source_id":  "events_table_headline_lookup_only",
        "description": (
            "Promote a row by looking up the inbox headline in the "
            "events table and copying that row's mechanism_family "
            "verbatim, with no operator confirmation."
        ),
        "reason_rejected": (
            "The Daily mechanism-enrichment diagnostic reports the "
            "events table is a sparse / unreliable enrichment "
            "source — exact and normalised lookups land most "
            "candidates in enrichment_gaps.  Even when a lookup "
            "hits, the diagnostic already calls for operator "
            "review of every match; the gate keeps that review "
            "step explicit instead of bypassing it."
        ),
    },
    {
        "source_id":  "inbox_keyword_heuristic",
        "description": (
            "Derive mechanism_family from a keyword-pattern match "
            "against the inbox headline (regex bank of "
            "sector / policy / supply terms)."
        ),
        "reason_rejected": (
            "A keyword heuristic would produce a label without an "
            "operator signature; the gate's audit story requires "
            "the field come from a reviewed artifact, not from a "
            "headline pattern."
        ),
    },
)


# ---------------------------------------------------------------------------
# Implementation targets — real files in the repo the operator would
# touch in a follow-up worksheet.  The planner names each file and a
# concrete responsibility; it does NOT propose code.
# ---------------------------------------------------------------------------


_IMPLEMENTATION_TARGETS: tuple[dict[str, str], ...] = (
    {
        "path":         "news_fetch.py",
        "responsibility": "inbox loader",
        "note": (
            "An inbox-loader extension would attach a stable "
            "candidate_id to each loaded row.  The planner does "
            "not propose an allocation scheme; the operator "
            "decides whether the id is a hash of (source, url, "
            "published_at) or an operator-assigned key.  No "
            "filter logic lives here — only the id tag."
        ),
    },
    {
        "path":         "news_inbox.json",
        "responsibility": "operator-visible inbox file",
        "note": (
            "The inbox schema would gain a candidate_id field so "
            "the gate can look up the matching artifact "
            "deterministically.  No mechanism_family field is "
            "proposed here; the gate reads mechanism_family from "
            "the artifact, not from the inbox."
        ),
    },
    {
        "path":         "routes/movers.py",
        "responsibility": "Daily Section C promotion boundary",
        "note": (
            "The Daily branch of the movers route would gate "
            "promotion behind the artifact's existence and the "
            "artifact's four required fields.  Rows whose artifact "
            "is missing or incomplete would be hidden from the "
            "Section C panel and surfaced on the review worklist "
            "instead.  No production change is proposed here; the "
            "planner names the file as the location of the gate."
        ),
    },
    {
        "path":         "scripts/manual_event_intake_worksheet.py",
        "responsibility": "analyzed-event artifact emitter",
        "note": (
            "An emission mode that writes one "
            "analyzed_event_artifact JSON per filled worksheet "
            "row would feed the gate without a separate operator "
            "surface.  The worksheet already carries the four "
            "required fields plus candidate_id."
        ),
    },
    {
        "path":         "artifacts/",
        "responsibility": "artifact storage location",
        "note": (
            "The gate would read analyzed_event_artifact files "
            "from a subdirectory under artifacts/ keyed by "
            "candidate_id.  A freshness window on the artifact "
            "would let the operator see a stale gate as a stale "
            "row rather than as a silently-dropped one."
        ),
    },
    {
        "path":         "scripts/section_c_daily_quality_diagnostic.py",
        "responsibility": "diagnostic surface (read-only)",
        "note": (
            "The existing diagnostic would gain an "
            "artifact_present / artifact_fields_complete column "
            "per inbox row so the operator can read, at a glance, "
            "which rows the gate would admit and which it would "
            "hold for review.  Descriptive only — the diagnostic "
            "does not enforce the gate."
        ),
    },
)


# ---------------------------------------------------------------------------
# Worked examples.  Each example pins a real-shape inbox row against
# the gate's behavior.  The examples are illustrative and stable —
# they are not derived from live inbox state.
# ---------------------------------------------------------------------------


_EXAMPLE_ALLOWED: dict[str, Any] = {
    "inbox_headline": (
        "OPEC members agree to extend voluntary oil output cuts "
        "through next quarter"
    ),
    "artifact_present":        True,
    "artifact_fields_present": list(_REQUIRED_FIELD_NAMES),
    "promotion_outcome":       "admitted",
    "rationale": (
        "Inbox row carries a stable candidate_id; an "
        "analyzed_event_artifact under artifacts/ keyed by that "
        "candidate_id exists and carries mechanism_family "
        "('supply_shock'), primary_ticker ('XOM'), benchmark_ticker "
        "('XLE'), and an operator-supplied market_relevance "
        "(0.85).  The gate would admit the row into Section C "
        "because every required field is present on a reviewed "
        "artifact."
    ),
}


_EXAMPLE_BLOCKED: dict[str, Any] = {
    "inbox_headline":   (
        "Market wrap: stocks edge higher on quiet trading day"
    ),
    "artifact_present": False,
    "missing_fields": list(_REQUIRED_FIELD_NAMES),
    "promotion_outcome":       "held_for_review",
    "rationale": (
        "No analyzed_event_artifact exists for the row.  The "
        "headline is a generic market-wrap phrase the Daily "
        "quality diagnostic already classifies as vague.  The "
        "gate would not promote the row to Section C; the row "
        "would appear on the operator review worklist so the "
        "operator can either fill an artifact (if the row "
        "describes a real event) or drop it (if it is a "
        "generic wrap).  The limitation is held in view, not "
        "hidden."
    ),
}


# ---------------------------------------------------------------------------
# False-positive risks — short bullets the operator should weigh.
# ---------------------------------------------------------------------------


_FP_RISKS: tuple[str, ...] = (
    "an operator backlog in artifact production would hold real "
    "news off the Section C surface; the gate should pair with a "
    "freshness window so stale-or-missing artifacts are surfaced "
    "as a stale row rather than as a silently-dropped one.",
    "a candidate_id collision (two inbox rows hashing to the same "
    "id) would attach one artifact to two rows; the planner "
    "suggests the operator pick an allocation scheme that is "
    "stable across regenerations but unique per row before any "
    "production change.",
    "an artifact carrying a stale benchmark_ticker (e.g. the "
    "benchmark changed sector category) could surface a row whose "
    "Still Moving check then degrades; an artifact-level review "
    "timestamp would let the operator spot stale benchmark "
    "choices during audit.",
    "an over-restrictive gate during early roll-out could starve "
    "Section C; the planner suggests staging the gate behind an "
    "operator-visible feature flag so the rollback path is "
    "obvious and the empty-Section-C case is a surfaced limitation "
    "rather than a silent regression.",
    "a candidate source that ships mechanism_family without an "
    "operator signature would re-introduce the audit gap the gate "
    "exists to close; the candidate_sources catalogue keeps "
    "operator_review_required True on every entry by construction.",
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_section_c_daily_artifact_gate_plan(
    *,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Build the Daily artifact-gate implementation design.

    See module docstring for the full output contract.
    """
    warnings: list[str] = []
    errors:   list[str] = []

    proposed_gate: dict[str, Any] = {
        "gate_id":                  _GATE_ID,
        "scope":                    _GATE_SCOPE,
        "behavior":                 _GATE_BEHAVIOR,
        "required_artifact_kind":   _GATE_REQUIRED_ARTIFACT_KIND,
        "required_field_names":     list(_REQUIRED_FIELD_NAMES),
        "held_for_review_behavior": _GATE_HELD_FOR_REVIEW,
        "fuzzy_matching_default":   _GATE_FUZZY_DEFAULT,
        "promotion_criteria": [
            "the inbox row carries a stable candidate_id",
            "an analyzed_event_artifact keyed by that candidate_id "
            "exists on disk under artifacts/",
            "the artifact carries non-empty values for "
            "mechanism_family, primary_ticker, benchmark_ticker, "
            "and an operator-supplied market_relevance in [0.0, 1.0]",
            "the artifact's review timestamp is inside the operator-"
            "configured freshness window",
            "operator review of the artifact is on file — the "
            "artifact carries the operator's signature",
        ],
    }

    envelope: dict[str, Any] = {
        "ok":                     not errors,
        "proposed_gate":          proposed_gate,
        "required_fields":        [dict(f) for f in _REQUIRED_FIELDS],
        "candidate_sources":      [dict(s) for s in _CANDIDATE_SOURCES],
        "rejected_sources":       [dict(s) for s in _REJECTED_SOURCES],
        "implementation_targets": [dict(t) for t in _IMPLEMENTATION_TARGETS],
        "example_allowed_case":   dict(_EXAMPLE_ALLOWED),
        "example_blocked_case":   dict(_EXAMPLE_BLOCKED),
        "false_positive_risks":   list(_FP_RISKS),
        "warnings":               warnings,
        "errors":                 errors,
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
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Section C daily artifact-gate implementation design", "",
    ]
    lines.append(f"OK: {report['ok']}")
    lines.append("")
    gate = report["proposed_gate"]
    lines.append(f"Gate id:                {gate['gate_id']}")
    lines.append(f"Scope:                  {gate['scope']}")
    lines.append(f"Required artifact kind: {gate['required_artifact_kind']}")
    lines.append(
        f"Required field names:   "
        f"{', '.join(gate['required_field_names'])}"
    )
    lines.append("")
    lines.append(f"Required fields ({len(report['required_fields'])}):")
    for f in report["required_fields"]:
        if isinstance(f, dict):
            lines.append(f"  - {f.get('field')!s:<20} {f.get('type')}")
            lines.append(f"      rationale: {f.get('rationale')}")
    lines.append("")
    lines.append(
        f"Candidate sources ({len(report['candidate_sources'])}):"
    )
    for s in report["candidate_sources"]:
        if isinstance(s, dict):
            lines.append(
                f"  - {s.get('source_id')!s:<48} "
                f"surface={s.get('surface')!r}"
            )
    lines.append("")
    lines.append(
        f"Rejected sources ({len(report['rejected_sources'])}):"
    )
    for s in report["rejected_sources"]:
        if isinstance(s, dict):
            lines.append(f"  - {s.get('source_id')}")
            lines.append(f"      reason: {s.get('reason_rejected')}")
    lines.append("")
    lines.append(
        f"Implementation targets "
        f"({len(report['implementation_targets'])}):"
    )
    for t in report["implementation_targets"]:
        if isinstance(t, dict):
            lines.append(
                f"  - {t.get('path')!s:<48} "
                f"{t.get('responsibility')}"
            )
            lines.append(f"      {t.get('note')}")
    lines.append("")
    allowed = report["example_allowed_case"]
    lines.append("Example allowed case:")
    lines.append(f"  headline: {allowed.get('inbox_headline')}")
    lines.append(f"  outcome:  {allowed.get('promotion_outcome')}")
    lines.append("")
    blocked = report["example_blocked_case"]
    lines.append("Example blocked case:")
    lines.append(f"  headline: {blocked.get('inbox_headline')}")
    lines.append(f"  outcome:  {blocked.get('promotion_outcome')}")
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
            "Read-only Section C Daily artifact-gate implementation "
            "design.  Converts the "
            "'require_analyzed_event_artifact_before_section_c_"
            "inclusion' path from the upstream enrichment plan into "
            "a concrete, implementation-ready design.  Does NOT "
            "mutate news_inbox, events, curated_candidates, or any "
            "artifact.  Does NOT assign mechanism_family.  Does NOT "
            "recommend fuzzy / LLM matching as a default."
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
    report = run_section_c_daily_artifact_gate_plan(
        output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_section_c_daily_artifact_gate_plan",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
