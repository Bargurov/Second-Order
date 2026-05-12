#!/usr/bin/env python3
"""Read-only combined reviewed-evidence report.

Stitches four on-disk JSON validation artifacts plus the three
short-horizon worksheet CSVs into a single operator-facing
inspection view so we can look at the current evidence state and
review-cycle completion in one place:

Validation artifacts (one source each):

  * ``artifacts/curated_stage_validation_evidence.json``           (required)
  * ``artifacts/short_horizon_review_validation_top10.json``       (required)
  * ``artifacts/short_horizon_review_validation_next10.json``      (required)
  * ``artifacts/short_horizon_review_validation_final8.json``      (OPTIONAL)

Review worksheet CSVs (feed the ``short_horizon_review_completion``
block; all three are optional and contribute zero counts when
missing):

  * ``artifacts/short_horizon_review_top10.csv``
  * ``artifacts/short_horizon_review_next10.csv``
  * ``artifacts/short_horizon_review_final8.csv``

The report is intentionally conservative — it never silently
deduplicates, never recomputes statistics differently, and never
permits a ``validated`` claim unless at least one record cleared the
FDR bar.  A missing ``final8`` validation artifact (or a missing
worksheet CSV) lands in ``warnings`` and never flips ``ok`` to
False.

Read-only by construction
-------------------------

* Pure builder + CLI — no DB, no provider, no LLM, no FastAPI.
* The three artifacts are read once each and their bytes are never
  rewritten.
* Each record's ``raw_p_candidate`` / ``fdr_significant`` /
  ``verdict`` is re-derived from ``p_value`` / ``fdr_q`` using the
  canonical :data:`stats.stat_validation.DEFAULT_ALPHA` threshold,
  so the three sources speak the same vocabulary even when the
  upstream artifact JSON did not carry the verdict fields (the
  short-horizon review runs predate the verdict-field rollout).

Counts contract
---------------

  * ``total_records``               — sum of ``examples`` across the
    three sources.
  * ``total_event_sources``         — number of (event_id, source)
    appearances; an event appearing in two sources counts twice.
  * ``fdr_significant_count``       — records with
    :func:`stats.stat_validation.is_statistically_significant`
    ``True``.  Strictly the FDR bar — never raised by raw-p signal.
  * ``raw_p_candidate_count``       — records with
    ``raw_p_candidate=True`` OR ``verdict=validated_raw_only``.
    (These are the same population by construction.)
  * ``verdict_counts``              — dict over the four verdict
    labels; every key is present even with a zero count.
  * ``by_source``                   — per-source breakdown of the
    above plus ``unique_event_ids``.
  * ``by_horizon``                  — per-horizon breakdown.
  * ``by_mechanism_family``         — per-family breakdown including
    ``events_evaluated`` (unique events per family).
  * ``duplicate_event_ids``         — list of
    ``{event_id, sources, appearances}`` for event_ids that appear
    in records from more than one source.  The report never silently
    dedupes.
  * ``strongest_raw_p_candidates``  — raw-p records sorted by
    ``p_value`` ascending, capped at 10.
  * ``null_or_inconclusive_examples`` — representative
    inconclusive / not_evaluable rows across sources, capped at 10.
  * ``evidence_claim_allowed`` / ``evidence_claim_not_allowed`` —
    lists of strings stating what the current evidence can and cannot
    support.  When ``fdr_significant_count == 0`` the allowed list is
    "methodology / demo" only; FDR-validated cohort claims sit in the
    not_allowed list.

Conservative wording
--------------------

Banned tokens never appear in ``errors`` / ``warnings`` /
``recommended_next_action`` / ``evidence_claim_*``::

    proof, proves, alpha, guaranteed, automatically, is proven,
    alpha generated, definitely validated.

The literal word ``validated`` is permitted (e.g. "not yet
FDR-validated" is the conservative meta-statement we DO want to
surface) — over-claims are what we ban.

Usage::

    python scripts/combined_reviewed_evidence_report.py --json
    python scripts/combined_reviewed_evidence_report.py --json \\
        --curated-stage artifacts/curated_stage_validation_evidence.json \\
        --review-top10  artifacts/short_horizon_review_validation_top10.json \\
        --review-next10 artifacts/short_horizon_review_validation_next10.json
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_CURATED_PATH: str = "artifacts/curated_stage_validation_evidence.json"
_DEFAULT_TOP10_PATH:   str = "artifacts/short_horizon_review_validation_top10.json"
_DEFAULT_NEXT10_PATH:  str = "artifacts/short_horizon_review_validation_next10.json"
_DEFAULT_FINAL8_PATH:  str = "artifacts/short_horizon_review_validation_final8.json"

_DEFAULT_WORKSHEET_TOP10_PATH:  str = "artifacts/short_horizon_review_top10.csv"
_DEFAULT_WORKSHEET_NEXT10_PATH: str = "artifacts/short_horizon_review_next10.csv"
_DEFAULT_WORKSHEET_FINAL8_PATH: str = "artifacts/short_horizon_review_final8.csv"


_STRONGEST_DEFAULT_LIMIT:    int = 10
_INCONCLUSIVE_DEFAULT_LIMIT: int = 10


# Verdict vocabulary — same labels the curated runner emits.  Every
# verdict_counts key is always present (zero when no record matches)
# so downstream consumers can rely on a stable shape.
_VERDICT_FDR_SIGNIFICANT:    str = "fdr_significant"
_VERDICT_VALIDATED_RAW_ONLY: str = "validated_raw_only"
_VERDICT_INCONCLUSIVE_FDR:   str = "inconclusive_fdr"
_VERDICT_NOT_EVALUABLE:      str = "not_evaluable"
_VERDICT_VALUES: tuple[str, ...] = (
    _VERDICT_FDR_SIGNIFICANT,
    _VERDICT_VALIDATED_RAW_ONLY,
    _VERDICT_INCONCLUSIVE_FDR,
    _VERDICT_NOT_EVALUABLE,
)


# Source labels — stable identifiers carried in ``sources`` and used
# throughout aggregates so a consumer can join the breakdown back to
# the input artifact unambiguously.
_SOURCE_CURATED: str = "curated_stage_validation_evidence"
_SOURCE_TOP10:   str = "short_horizon_review_validation_top10"
_SOURCE_NEXT10:  str = "short_horizon_review_validation_next10"
_SOURCE_FINAL8:  str = "short_horizon_review_validation_final8"


# Worksheet labels — stable identifiers for the
# ``short_horizon_review_completion.by_worksheet`` block.
_WS_TOP10:  str = "short_horizon_review_top10"
_WS_NEXT10: str = "short_horizon_review_next10"
_WS_FINAL8: str = "short_horizon_review_final8"

# Canonical worksheet gate column — same name used across the
# validator / apply / validate triple.
_WORKSHEET_GATE_COLUMN: str = "include_in_short_horizon_validation"


# Conservative phrasing for evidence-claim guards.  Both lists are
# returned to the caller verbatim; banned over-claim tokens never
# appear here by construction.
_CLAIM_ALLOWED_NO_FDR: tuple[str, ...] = (
    "methodology demonstration of the stage-then-validate flow",
    "raw-p signal review (record-by-record only; not a cohort claim)",
    "operator demo of the read-only evidence pipeline",
)
_CLAIM_NOT_ALLOWED_NO_FDR: tuple[str, ...] = (
    "FDR-validated cohort claim",
    "production validation claim",
    "predictive performance claim",
    "cohort-level significance claim",
)
_CLAIM_ALLOWED_HAS_FDR: tuple[str, ...] = (
    "FDR-significant record-level observation for inspected events",
    "methodology demonstration of the stage-then-validate flow",
    "raw-p signal review (record-by-record only)",
)
_CLAIM_NOT_ALLOWED_HAS_FDR: tuple[str, ...] = (
    "cohort-level significance claim without further review",
    "production validation claim",
    "predictive performance claim",
)


_RECOMMENDED_EMPTY_FDR: str = (
    "Zero records cleared the FDR bar.  Treat the combined cohort as "
    "useful for methodology / demo only, not for a validation claim.  "
    "Surface more reviewed candidates and re-run before drawing any "
    "cohort-level conclusion."
)
_RECOMMENDED_HAS_FDR: str = (
    "{n} record(s) cleared the FDR bar.  Inspect each row in "
    "strongest_raw_p_candidates and the source-specific breakdown "
    "before promoting any claim beyond a record-level observation."
)
# Live state: short-horizon review is complete (no pending rows)
# across all three worksheets, no record cleared the FDR bar.  The
# recommendation surfaces the two next-step options the operator
# now has to choose between.
_RECOMMENDED_QUEUE_FULLY_REVIEWED_NO_FDR: str = (
    "Short-horizon review is complete "
    "({total} rows reviewed across top10/next10/final8; "
    "{included} included, {excluded} excluded; 0 pending).  Zero "
    "records cleared the FDR bar.  Next choice: archive the current "
    "state as a freeze-candidate evidence artifact, or proceed with "
    "the XLE online backfill before any further review."
)
# Less common: short-horizon review complete AND at least one
# FDR-significant record present.  Still call out the review
# completion while making clear the FDR signal needs record-level
# inspection before any cohort claim.
_RECOMMENDED_QUEUE_FULLY_REVIEWED_HAS_FDR: str = (
    "Short-horizon review is complete "
    "({total} rows reviewed across top10/next10/final8; "
    "{included} included, {excluded} excluded; 0 pending).  "
    "{n} record(s) cleared the FDR bar — inspect each row in "
    "strongest_raw_p_candidates before promoting any claim beyond "
    "a record-level observation.  Next choice: archive the current "
    "state as a freeze-candidate evidence artifact, or proceed with "
    "the XLE online backfill before any further review."
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_combined_evidence_report(
    *,
    curated_stage_path: str | None,
    review_top10_path:  str | None,
    review_next10_path: str | None,
    review_final8_path: str | None = None,
    worksheet_top10_path:  str | None = None,
    worksheet_next10_path: str | None = None,
    worksheet_final8_path: str | None = None,
    strongest_limit:    int = _STRONGEST_DEFAULT_LIMIT,
    inconclusive_limit: int = _INCONCLUSIVE_DEFAULT_LIMIT,
    now_iso:            str | None = None,
) -> dict[str, Any]:
    """Build the combined reviewed-evidence JSON report.  See the
    module docstring for the full output contract.

    The first three validation artifacts (``curated_stage``, ``top10``,
    ``next10``) are required — missing artifact paths land in
    ``errors`` and flip ``ok`` to False.  The fourth validation
    artifact (``final8``) and all three worksheet CSVs are optional —
    missing inputs surface in ``warnings`` only.
    """
    from stats.stat_validation import DEFAULT_ALPHA

    errors:   list[str] = []
    warnings: list[str] = []

    source_specs = (
        (_SOURCE_CURATED, curated_stage_path, False),
        (_SOURCE_TOP10,   review_top10_path,  False),
        (_SOURCE_NEXT10,  review_next10_path, False),
        (_SOURCE_FINAL8,  review_final8_path, True),
    )

    sources_meta: list[dict[str, Any]] = []
    all_records: list[dict[str, Any]] = []

    for label, path, optional in source_specs:
        records, load_error, load_warning = _load_source_records(
            path, label=label, optional=optional,
        )
        sources_meta.append({
            "label":   label,
            "path":    str(path) if path is not None else None,
            "loaded":  load_error is None and load_warning is None,
            "records_loaded": len(records),
            "error":   load_error,
            "warning": load_warning,
        })
        if load_error is not None:
            errors.append(load_error)
        if load_warning is not None:
            warnings.append(load_warning)
        if records:
            all_records.extend(
                _normalise_record(r, source=label, alpha=DEFAULT_ALPHA)
                for r in records
            )

    # ---- aggregates ----
    fdr_significant_count = sum(
        1 for r in all_records if r["fdr_significant"]
    )
    raw_p_candidate_count = sum(
        1 for r in all_records
        if r["raw_p_candidate"]
        or r["verdict"] == _VERDICT_VALIDATED_RAW_ONLY
    )
    verdict_counts = {v: 0 for v in _VERDICT_VALUES}
    for r in all_records:
        v = r["verdict"]
        if v in verdict_counts:
            verdict_counts[v] += 1

    loaded_source_labels = [
        meta["label"] for meta in sources_meta if meta["loaded"]
    ]
    by_source = _aggregate_by_source(
        all_records, loaded_labels=loaded_source_labels,
    )
    by_horizon = _aggregate_by_horizon(all_records)
    by_mechanism_family = _aggregate_by_mechanism_family(all_records)
    duplicate_event_ids = _build_duplicate_event_ids(all_records)
    total_event_sources = _count_event_sources(all_records)
    strongest = _build_strongest_raw_p(
        all_records, limit=max(int(strongest_limit), 0),
    )
    inconclusive = _build_inconclusive_examples(
        all_records, limit=max(int(inconclusive_limit), 0),
    )

    # ---- short-horizon review completion (from worksheet CSVs) ----
    completion, completion_warnings = _build_review_completion(
        worksheet_top10_path=worksheet_top10_path,
        worksheet_next10_path=worksheet_next10_path,
        worksheet_final8_path=worksheet_final8_path,
    )
    warnings.extend(completion_warnings)

    # ---- claim guard + recommendation ----
    queue_fully_reviewed = _queue_fully_reviewed(completion)
    if fdr_significant_count > 0:
        evidence_claim_allowed = list(_CLAIM_ALLOWED_HAS_FDR)
        evidence_claim_not_allowed = list(_CLAIM_NOT_ALLOWED_HAS_FDR)
        if queue_fully_reviewed:
            recommended = _RECOMMENDED_QUEUE_FULLY_REVIEWED_HAS_FDR.format(
                n=fdr_significant_count,
                total=completion["total_reviewed_rows"],
                included=completion["included_count"],
                excluded=completion["excluded_count"],
            )
        else:
            recommended = _RECOMMENDED_HAS_FDR.format(n=fdr_significant_count)
    else:
        evidence_claim_allowed = list(_CLAIM_ALLOWED_NO_FDR)
        evidence_claim_not_allowed = list(_CLAIM_NOT_ALLOWED_NO_FDR)
        if queue_fully_reviewed:
            recommended = _RECOMMENDED_QUEUE_FULLY_REVIEWED_NO_FDR.format(
                total=completion["total_reviewed_rows"],
                included=completion["included_count"],
                excluded=completion["excluded_count"],
            )
        else:
            recommended = _RECOMMENDED_EMPTY_FDR

    generated_at = now_iso if now_iso is not None else (
        _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    )

    return {
        "ok":                              not errors,
        "generated_at":                    generated_at,
        "sources":                         sources_meta,
        "total_event_sources":             total_event_sources,
        "total_records":                   len(all_records),
        "fdr_significant_count":           fdr_significant_count,
        "raw_p_candidate_count":           raw_p_candidate_count,
        "verdict_counts":                  verdict_counts,
        "by_source":                       by_source,
        "by_horizon":                      by_horizon,
        "by_mechanism_family":             by_mechanism_family,
        "duplicate_event_ids":             duplicate_event_ids,
        "strongest_raw_p_candidates":      strongest,
        "null_or_inconclusive_examples":   inconclusive,
        "short_horizon_review_completion": completion,
        "evidence_claim_allowed":          evidence_claim_allowed,
        "evidence_claim_not_allowed":      evidence_claim_not_allowed,
        "recommended_next_action":         recommended,
        "warnings":                        warnings,
        "errors":                          errors,
    }


def _queue_fully_reviewed(completion: dict[str, Any]) -> bool:
    """True iff all three worksheets loaded, at least one row was
    surfaced, and no row remains pending.  Conservative — when any
    worksheet is missing or any row is still pending we never claim
    the queue is fully reviewed.
    """
    if completion.get("total_reviewed_rows", 0) <= 0:
        return False
    if completion.get("pending_count", 0) > 0:
        return False
    by_ws = completion.get("by_worksheet") or {}
    for label in (_WS_TOP10, _WS_NEXT10, _WS_FINAL8):
        entry = by_ws.get(label)
        if not isinstance(entry, dict) or not entry.get("loaded"):
            return False
    return True


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------


def _load_source_records(
    path: str | None, *, label: str, optional: bool = False,
) -> tuple[list[dict[str, Any]], str | None, str | None]:
    """Load a single artifact's ``examples`` list.

    Returns ``(records, error, warning)``.  Missing / unreadable
    artifacts land in ``error`` when ``optional=False`` and in
    ``warning`` when ``optional=True``; the caller surfaces each in
    the appropriate envelope list.  Parse failures on an existing but
    malformed file always go to ``error`` regardless of ``optional``
    — a present-but-broken artifact is a real fault.
    """
    if path is None or not str(path).strip():
        msg = f"{label}: no path supplied"
        return [], (None if optional else msg), (msg if optional else None)
    p = Path(path)
    if not p.exists():
        msg = f"{label} artifact does not exist: {path}"
        return [], (None if optional else msg), (msg if optional else None)
    try:
        blob = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], f"{label} artifact unreadable: {exc}", None
    if not isinstance(blob, dict):
        return [], f"{label} artifact root is not an object", None
    examples = blob.get("examples")
    if not isinstance(examples, list):
        return [], (
            f"{label} artifact has no ``examples`` list "
            f"(got {type(examples).__name__})"
        ), None
    return [ex for ex in examples if isinstance(ex, dict)], None, None


# ---------------------------------------------------------------------------
# Short-horizon review completion — read directly from the worksheet
# CSVs.  No DB, no LLM, no provider; the CSVs are the operator's
# source of truth for the yes / no / pending split.
# ---------------------------------------------------------------------------


def _build_review_completion(
    *,
    worksheet_top10_path:  str | None,
    worksheet_next10_path: str | None,
    worksheet_final8_path: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Build the ``short_horizon_review_completion`` envelope block
    from the three worksheet CSVs.  Returns ``(block, warnings)``.

    Each worksheet is optional — a missing path surfaces a warning
    (never an error) and contributes zero counts to the aggregate.
    """
    warnings: list[str] = []
    by_worksheet: dict[str, dict[str, Any]] = {}
    total_rows = 0
    total_included = 0
    total_excluded = 0
    total_pending = 0

    specs = (
        (_WS_TOP10,  worksheet_top10_path),
        (_WS_NEXT10, worksheet_next10_path),
        (_WS_FINAL8, worksheet_final8_path),
    )
    for label, path in specs:
        block, warning = _load_worksheet_counts(path, label=label)
        by_worksheet[label] = block
        if warning is not None:
            warnings.append(warning)
        if block["loaded"]:
            total_rows     += block["total_rows"]
            total_included += block["included_count"]
            total_excluded += block["excluded_count"]
            total_pending  += block["pending_count"]

    return {
        "total_reviewed_rows": total_rows,
        "included_count":      total_included,
        "excluded_count":      total_excluded,
        "pending_count":       total_pending,
        "by_worksheet":        by_worksheet,
    }, warnings


def _load_worksheet_counts(
    path: str | None, *, label: str,
) -> tuple[dict[str, Any], str | None]:
    """Count yes / no / pending rows in a single worksheet CSV.

    Returns ``(block, warning)``.  Missing path / file produces a
    warning; the block carries zero counts and ``loaded=False`` so
    aggregate code can skip it without a special case.  Present-but-
    malformed CSVs (missing required columns / unreadable) also
    surface as warnings rather than errors — the completion block is
    informational, not gating.
    """
    empty_block: dict[str, Any] = {
        "path":            str(path) if path is not None else None,
        "loaded":          False,
        "total_rows":      0,
        "included_count":  0,
        "excluded_count":  0,
        "pending_count":   0,
    }
    if path is None or not str(path).strip():
        return empty_block, f"worksheet {label}: no path supplied"
    p = Path(path)
    if not p.exists():
        return empty_block, (
            f"worksheet {label} does not exist: {path}"
        )
    try:
        with open(p, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            if _WORKSHEET_GATE_COLUMN not in fieldnames:
                return empty_block, (
                    f"worksheet {label} missing required column "
                    f"{_WORKSHEET_GATE_COLUMN!r}"
                )
            rows = list(reader)
    except OSError as exc:
        return empty_block, f"worksheet {label} unreadable: {exc}"
    included = excluded = pending = 0
    for r in rows:
        gate = _normalise_gate(r.get(_WORKSHEET_GATE_COLUMN))
        if gate == "yes":
            included += 1
        elif gate == "no":
            excluded += 1
        else:
            # Blank or unrecognised → pending.  No banned-token
            # over-claim here; the report's downstream wording test
            # passes the warnings list through the banned-token guard.
            pending += 1
    return {
        "path":            str(p),
        "loaded":          True,
        "total_rows":      len(rows),
        "included_count":  included,
        "excluded_count":  excluded,
        "pending_count":   pending,
    }, None


def _normalise_gate(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip().lower()
    return str(raw).strip().lower()


# ---------------------------------------------------------------------------
# Record normalisation — speak the same vocabulary across sources
# ---------------------------------------------------------------------------


def _normalise_record(
    raw: dict[str, Any], *, source: str, alpha: float,
) -> dict[str, Any]:
    """Project an artifact example into the combined record shape.

    Re-derives ``raw_p_candidate`` / ``fdr_significant`` / ``verdict``
    using the canonical alpha threshold so every source speaks the
    same vocabulary even when the upstream artifact did not carry
    the verdict fields.
    """
    event_id = raw.get("source_event_id")
    if event_id is None:
        event_id = raw.get("event_id")
    p_value = raw.get("p_value")
    fdr_q   = raw.get("fdr_q")
    raw_p_candidate = _is_raw_p_candidate(p_value, alpha=alpha)
    fdr_significant = _safe_fdr_significant(fdr_q, alpha=alpha)
    verdict = _classify_verdict(
        p_value=p_value, fdr_q=fdr_q,
        raw_p_candidate=raw_p_candidate,
        fdr_significant=fdr_significant,
    )
    return {
        "source":            source,
        "event_id":          event_id,
        "horizon":           raw.get("horizon"),
        "p_value":           p_value,
        "fdr_q":             fdr_q,
        "abnormal_return":   raw.get("abnormal_return"),
        "sar":               raw.get("sar"),
        "ci_low":            raw.get("ci_low"),
        "ci_high":           raw.get("ci_high"),
        "primary_ticker":    raw.get("primary_ticker"),
        # Curated artifact uses ``benchmark_ticker``; review artifacts
        # use ``benchmark``.  Carry whichever is present.
        "benchmark_ticker":  raw.get("benchmark_ticker") or raw.get("benchmark"),
        "mechanism_family":  raw.get("mechanism_family"),
        "headline":          raw.get("headline"),
        "interpretation":    raw.get("interpretation"),
        "raw_p_candidate":   raw_p_candidate,
        "fdr_significant":   fdr_significant,
        "verdict":           verdict,
    }


# ---------------------------------------------------------------------------
# Per-record statistical helpers — same alpha threshold as the curated
# runner.  No new statistic is computed.
# ---------------------------------------------------------------------------


def _is_finite_number(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    f = float(value)
    return not (math.isnan(f) or math.isinf(f))


def _is_raw_p_candidate(p_value: Any, *, alpha: float) -> bool:
    if not _is_finite_number(p_value):
        return False
    return float(p_value) <= alpha


def _safe_fdr_significant(fdr_q: Any, *, alpha: float) -> bool:
    from stats.stat_validation import is_statistically_significant

    if not _is_finite_number(fdr_q):
        return False
    try:
        return is_statistically_significant(fdr_q, alpha=alpha)
    except (TypeError, ValueError):
        return False


def _classify_verdict(
    *, p_value: Any, fdr_q: Any,
    raw_p_candidate: bool, fdr_significant: bool,
) -> str:
    if fdr_significant:
        return _VERDICT_FDR_SIGNIFICANT
    if raw_p_candidate:
        return _VERDICT_VALIDATED_RAW_ONLY
    if _is_finite_number(p_value) or _is_finite_number(fdr_q):
        return _VERDICT_INCONCLUSIVE_FDR
    return _VERDICT_NOT_EVALUABLE


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------


def _aggregate_by_source(
    records: list[dict[str, Any]],
    *,
    loaded_labels: Sequence[str] = (),
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    # Seed an entry for every loaded source so a loaded-but-empty
    # source (e.g., the final8 validation artifact with zero records)
    # is still visible in the breakdown rather than silently absent.
    for label in loaded_labels:
        out[label] = {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
            "verdict_counts":        {v: 0 for v in _VERDICT_VALUES},
            "unique_event_ids":      0,
        }
    seen_events: dict[str, set[Any]] = {}
    for r in records:
        block = out.setdefault(r["source"], {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
            "verdict_counts":        {v: 0 for v in _VERDICT_VALUES},
            "unique_event_ids":      0,
        })
        block["records_count"] += 1
        if r["fdr_significant"]:
            block["fdr_significant_count"] += 1
        if r["raw_p_candidate"] or r["verdict"] == _VERDICT_VALIDATED_RAW_ONLY:
            block["raw_p_candidate_count"] += 1
        v = r["verdict"]
        if v in block["verdict_counts"]:
            block["verdict_counts"][v] += 1
        ev_id = r.get("event_id")
        if ev_id is not None:
            seen = seen_events.setdefault(r["source"], set())
            seen.add(ev_id)
    for src, ids in seen_events.items():
        out[src]["unique_event_ids"] = len(ids)
    return out


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, int]] = {}
    for r in records:
        h = r.get("horizon")
        if not isinstance(h, int):
            continue
        block = out.setdefault(str(h), {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
        })
        block["records_count"] += 1
        if r["fdr_significant"]:
            block["fdr_significant_count"] += 1
        if r["raw_p_candidate"] or r["verdict"] == _VERDICT_VALIDATED_RAW_ONLY:
            block["raw_p_candidate_count"] += 1
    return out


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    seen_events: dict[str, set[Any]] = {}
    for r in records:
        family = r.get("mechanism_family")
        if not isinstance(family, str) or not family.strip():
            continue
        block = out.setdefault(family, {
            "records_count":         0,
            "fdr_significant_count": 0,
            "raw_p_candidate_count": 0,
            "events_evaluated":      0,
        })
        block["records_count"] += 1
        if r["fdr_significant"]:
            block["fdr_significant_count"] += 1
        if r["raw_p_candidate"] or r["verdict"] == _VERDICT_VALIDATED_RAW_ONLY:
            block["raw_p_candidate_count"] += 1
        ev_id = r.get("event_id")
        if ev_id is not None:
            seen = seen_events.setdefault(family, set())
            if ev_id not in seen:
                seen.add(ev_id)
                block["events_evaluated"] += 1
    return out


def _build_duplicate_event_ids(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Detect event_ids that appear in records from more than one
    source.  Never silently dedupes — the report surfaces every
    duplicate so the operator can decide whether the appearance in
    multiple sources is a real signal or a fixture leak.
    """
    by_event: dict[Any, set[str]] = {}
    for r in records:
        ev_id = r.get("event_id")
        if ev_id is None:
            continue
        by_event.setdefault(ev_id, set()).add(r["source"])
    duplicates: list[dict[str, Any]] = []
    for ev_id, sources in by_event.items():
        if len(sources) >= 2:
            duplicates.append({
                "event_id":    ev_id,
                "sources":     sorted(sources),
                "appearances": len(sources),
            })
    duplicates.sort(key=lambda d: _safe_sort_key(d["event_id"]))
    return duplicates


def _count_event_sources(records: list[dict[str, Any]]) -> int:
    """Count distinct (event_id, source) appearances.  An event in
    two sources contributes 2; an event in three sources contributes
    3.  This is the "event-source appearance" count the spec asks for.
    """
    seen: set[tuple[Any, str]] = set()
    for r in records:
        ev_id = r.get("event_id")
        if ev_id is None:
            continue
        seen.add((ev_id, r["source"]))
    return len(seen)


def _build_strongest_raw_p(
    records: list[dict[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    """Pick the raw-p records and surface them sorted by p_value
    ascending.  Cap at ``limit`` so a noisy cohort doesn't bloat the
    report.
    """
    candidates = [
        r for r in records
        if r["raw_p_candidate"]
        or r["verdict"] == _VERDICT_VALIDATED_RAW_ONLY
    ]
    candidates.sort(
        key=lambda r: (
            r["p_value"] if _is_finite_number(r["p_value"]) else float("inf"),
            _safe_sort_key(r.get("event_id")),
            _safe_sort_key(r.get("horizon")),
            r["source"],
        )
    )
    return [_record_to_surfaced_entry(r) for r in candidates[:limit]]


def _build_inconclusive_examples(
    records: list[dict[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    """Pick representative inconclusive / not_evaluable records,
    deliberately excluding ``fdr_significant`` and ``validated_raw_only``
    so the operator can read the surfaced rows as "nothing here yet"
    examples.  Spread across sources by interleaving.
    """
    by_source: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        if r["verdict"] not in (_VERDICT_INCONCLUSIVE_FDR,
                                _VERDICT_NOT_EVALUABLE):
            continue
        by_source.setdefault(r["source"], []).append(r)
    # Stable sort within each source bucket so we surface a
    # deterministic ordering.
    for src in by_source:
        by_source[src].sort(
            key=lambda r: (
                _safe_sort_key(r.get("event_id")),
                _safe_sort_key(r.get("horizon")),
            )
        )
    out: list[dict[str, Any]] = []
    while len(out) < limit:
        progressed = False
        for src in (_SOURCE_CURATED, _SOURCE_TOP10, _SOURCE_NEXT10):
            bucket = by_source.get(src)
            if not bucket:
                continue
            out.append(_record_to_surfaced_entry(bucket.pop(0)))
            progressed = True
            if len(out) >= limit:
                break
        if not progressed:
            break
    return out


def _record_to_surfaced_entry(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "source":           r["source"],
        "event_id":         r.get("event_id"),
        "horizon":          r.get("horizon"),
        "headline":         r.get("headline"),
        "primary_ticker":   r.get("primary_ticker"),
        "benchmark_ticker": r.get("benchmark_ticker"),
        "mechanism_family": r.get("mechanism_family"),
        "p_value":          r.get("p_value"),
        "fdr_q":            r.get("fdr_q"),
        "abnormal_return":  r.get("abnormal_return"),
        "sar":              r.get("sar"),
        "interpretation":   r.get("interpretation"),
        "raw_p_candidate":  r["raw_p_candidate"],
        "fdr_significant":  r["fdr_significant"],
        "verdict":          r["verdict"],
    }


def _safe_sort_key(value: Any) -> tuple[int, Any]:
    """Sort key that survives mixed-type and ``None`` inputs without
    raising.  Tuple-first ordering pushes ``None`` to the end.
    """
    if value is None:
        return (1, 0)
    if isinstance(value, bool):
        return (0, int(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (0, str(value))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only combined reviewed-evidence report.  Stitches "
            "the curated stage validation evidence + the short-"
            "horizon review top10 / next10 validation artifacts into "
            "one JSON inspection view.  Conservative wording: no "
            "validation claim unless at least one record cleared FDR. "
            "No DB / provider / LLM / FastAPI surface."
        ),
    )
    parser.add_argument(
        "--curated-stage", dest="curated_stage",
        default=_DEFAULT_CURATED_PATH,
        help=(
            f"Path to the curated stage validation evidence JSON.  "
            f"Defaults to {_DEFAULT_CURATED_PATH}."
        ),
    )
    parser.add_argument(
        "--review-top10", dest="review_top10",
        default=_DEFAULT_TOP10_PATH,
        help=(
            f"Path to the short-horizon review top10 validation JSON.  "
            f"Defaults to {_DEFAULT_TOP10_PATH}."
        ),
    )
    parser.add_argument(
        "--review-next10", dest="review_next10",
        default=_DEFAULT_NEXT10_PATH,
        help=(
            f"Path to the short-horizon review next10 validation JSON.  "
            f"Defaults to {_DEFAULT_NEXT10_PATH}."
        ),
    )
    parser.add_argument(
        "--review-final8", dest="review_final8",
        default=_DEFAULT_FINAL8_PATH,
        help=(
            f"Path to the short-horizon review final8 validation JSON.  "
            f"OPTIONAL — missing file produces a warning, not an "
            f"error.  Defaults to {_DEFAULT_FINAL8_PATH}."
        ),
    )
    parser.add_argument(
        "--worksheet-top10", dest="worksheet_top10",
        default=_DEFAULT_WORKSHEET_TOP10_PATH,
        help=(
            f"Path to the top10 review worksheet CSV (feeds the "
            f"short_horizon_review_completion block).  Defaults to "
            f"{_DEFAULT_WORKSHEET_TOP10_PATH}."
        ),
    )
    parser.add_argument(
        "--worksheet-next10", dest="worksheet_next10",
        default=_DEFAULT_WORKSHEET_NEXT10_PATH,
        help=(
            f"Path to the next10 review worksheet CSV.  Defaults to "
            f"{_DEFAULT_WORKSHEET_NEXT10_PATH}."
        ),
    )
    parser.add_argument(
        "--worksheet-final8", dest="worksheet_final8",
        default=_DEFAULT_WORKSHEET_FINAL8_PATH,
        help=(
            f"Path to the final8 review worksheet CSV.  Defaults to "
            f"{_DEFAULT_WORKSHEET_FINAL8_PATH}."
        ),
    )
    parser.add_argument(
        "--strongest-limit", type=int,
        default=_STRONGEST_DEFAULT_LIMIT,
        help=(
            f"Cap the strongest_raw_p_candidates list at N rows "
            f"(default {_STRONGEST_DEFAULT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--inconclusive-limit", type=int,
        default=_INCONCLUSIVE_DEFAULT_LIMIT,
        help=(
            f"Cap the null_or_inconclusive_examples list at N rows "
            f"(default {_INCONCLUSIVE_DEFAULT_LIMIT})."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help=(
            "Accepted for ergonomic parity with sibling scripts.  "
            "Output is always JSON."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = build_combined_evidence_report(
        curated_stage_path=args.curated_stage,
        review_top10_path=args.review_top10,
        review_next10_path=args.review_next10,
        review_final8_path=args.review_final8,
        worksheet_top10_path=args.worksheet_top10,
        worksheet_next10_path=args.worksheet_next10,
        worksheet_final8_path=args.worksheet_final8,
        strongest_limit=int(args.strongest_limit),
        inconclusive_limit=int(args.inconclusive_limit),
    )
    print(_render_json(report), file=output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
