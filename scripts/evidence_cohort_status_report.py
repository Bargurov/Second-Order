#!/usr/bin/env python3
"""Read-only evidence cohort status report.

Composes existing local report scripts into a single 10-key envelope so
a reviewer can see demo-readiness truth in one place: where the repaired
cohort actually stands, what curated candidates are staged, what
short-horizon expansion candidates remain, and whether the benchmark-
sensitivity check is unblocked.

Read-only by construction
-------------------------

* No DB writes.  No LLM, no FastAPI, no provider call.
* The repaired-cohort summary is only invoked when the operator
  explicitly supplies ``--backup-path`` plus both worksheet CSVs.
  Without them the block surfaces ``status="not_sourced"`` and a hint
  in ``next_best_action`` — the default invocation does not run any
  validation pipeline.
* The curated-candidate status block runs a lightweight SELECT-only
  query over the live ``curated_candidates`` table.
* The short-horizon expansion block runs the existing repair packet
  builder which itself is read-only.
* The benchmark-sensitivity block is sourced one-for-one from the
  upstream :mod:`scripts.benchmark_sensitivity_preflight` runner.  The
  preflight is the authoritative readiness signal: when it reports any
  blocked event the block surfaces ``status="blocked"`` (waiting on a
  cache backfill); when it raises or returns ``ok=False`` the block
  surfaces ``status="unknown"``.  The block never flips into a negative
  significance claim — readiness reflects the cache state alone.

Output contract::

    {
      "ok":                            bool,
      "current_repaired_cohort":       {...},
      "curated_candidate_status":      {...},
      "short_horizon_expansion_status":{...},
      "benchmark_sensitivity_status":  {...},
      "evidence_claim_allowed":        [str, ...],
      "evidence_claim_not_allowed":    [str, ...],
      "next_best_action":              str,
      "warnings":                      [str, ...],
      "errors":                        [str, ...],
    }

Conservative wording
--------------------

Banned tokens (``proof``, ``alpha``, ``automatic``, ``predictive``,
``causal``) appear nowhere in any string the report emits, except in
``evidence_claim_not_allowed`` — which must enumerate exactly those
reserved claim kinds.

Patchable seams
---------------

* ``_run_repaired_cohort_summary``       — wraps
  :func:`scripts.manual_repaired_cohort_validation_summary.summarize_repaired_cohort_validation`.
* ``_run_curated_candidate_status``      — wraps
  :func:`scripts.curated_candidate_status.compute_status`.
* ``_run_short_horizon_repair_packet``   — wraps
  :func:`scripts.short_horizon_repair_packet.summarize_short_horizon_repair_packet`.
* ``_run_benchmark_sensitivity_preflight`` — wraps
  :func:`scripts.benchmark_sensitivity_preflight.summarize_benchmark_sensitivity_preflight`
  and is the readiness source of truth for the benchmark block.

Usage::

    python scripts/evidence_cohort_status_report.py
    python scripts/evidence_cohort_status_report.py --json
    python scripts/evidence_cohort_status_report.py --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv
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


# Ticker name surfaced in the benchmark block's ``benchmark_ticker_probed``
# field.  This mirrors the default benchmark of
# :mod:`scripts.benchmark_sensitivity_preflight`; readiness itself is
# sourced from that preflight, not from a local probe.
_BENCHMARK_TICKER_FOR_BLOCK: str = "XLE"


# Project root used by the local-input discovery seam.  Module-level so
# tests patch it directly rather than reaching into ``Path(__file__)``.
_PROJECT_ROOT: str = str(ROOT)


# Canonical CSV filenames the discovery seam looks for under the project
# root.  Names mirror the worksheets the prior repair tasks produced.
_CANONICAL_HIGH_PRIORITY_CSV: str = "manual_ticker_repair_high_priority.csv"
_CANONICAL_MEDIUM_CSV: str = "manual_ticker_repair_medium_production_like.csv"
_CANONICAL_MECHANISM_FAMILY_CSV: str = "mechanism_family_repair_packet.csv"


# Backup files live under ``backups/`` and follow the
# ``events-YYYYMMDDTHHMMSS.db`` naming convention.  ISO timestamps in
# filenames sort lexicographically the same way they sort
# chronologically, so picking ``max()`` of the matched names yields
# the most recent backup without filesystem mtime calls.
_CANONICAL_BACKUP_DIR: str = "backups"
_CANONICAL_BACKUP_GLOB: str = "events-*.db"


# Conservative claim vocabulary — surfaced literally in the report so
# reviewers see exactly what the evidence supports and what it does not.
_CLAIM_ALLOWED: tuple[str, ...] = (
    "Operator-repaired cohort evidence at the per-event level — "
    "values reflect the small repaired pilot the operator has staged.",
    "Counts of staged curated candidates and pending manual review "
    "candidates — these are operator-facing inventories, not validation "
    "outcomes.",
    "Per-(event, horizon) sensitivity comparisons surface as evidence "
    "only when the underlying benchmark cache is populated; comparisons "
    "are descriptive, not confirmatory.",
)


# Reserved claim kinds the report explicitly does NOT make.  This list
# is the only place the banned vocabulary may appear, because the report
# must enumerate exactly what it refuses to claim.
_CLAIM_NOT_ALLOWED: tuple[str, ...] = (
    "no proof claim — repaired cohort evidence is exploratory, not "
    "confirmatory.",
    "no alpha-generation claim — the report never asserts the strategy "
    "produces alpha.",
    "no predictive-edge claim — sample size and design do not support "
    "an out-of-sample predictive claim.",
    "no causal claim — operator-repaired cohort evidence cannot be "
    "framed as causal.",
)


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  The lazy imports resolve only on the un-patched path so the
# default-run import isolation is preserved.
# ---------------------------------------------------------------------------


def _discover_local_repaired_inputs() -> dict[str, Any]:
    """Probe the project root for canonical repaired-cohort inputs.

    Returns a dict with four input slots and a ``missing`` list naming
    the required slots that could not be resolved.  The probe is purely
    read-only (``os.path.exists`` + a single directory listing) and
    never raises — when the project root is missing, every slot reads
    as missing.

    Required slots (a missing one means the discovery cannot satisfy
    the no-args auto-source path):

      * ``backup_path``       — most recent ``backups/events-*.db``.
      * ``high_priority_csv`` — canonical high-priority CSV.
      * ``medium_csv``        — canonical medium-batch CSV.

    Optional:

      * ``mechanism_family_csv`` — only listed when present.

    Tests patch this attribute directly with synthetic payloads.
    """
    root = Path(_PROJECT_ROOT)
    out: dict[str, Any] = {
        "backup_path":          None,
        "high_priority_csv":    None,
        "medium_csv":           None,
        "mechanism_family_csv": None,
        "missing":              [],
    }

    # Backup discovery — pick the lex-greatest matching filename so the
    # ISO-timestamped naming convention surfaces the most recent backup.
    try:
        backups_dir = root / _CANONICAL_BACKUP_DIR
        if backups_dir.is_dir():
            matches = sorted(p for p in backups_dir.glob(_CANONICAL_BACKUP_GLOB)
                             if p.is_file())
            if matches:
                out["backup_path"] = str(matches[-1])
    except OSError:
        pass

    # CSV discovery — exact-name probe in the project root.
    for slot, fname in (
        ("high_priority_csv",    _CANONICAL_HIGH_PRIORITY_CSV),
        ("medium_csv",           _CANONICAL_MEDIUM_CSV),
        ("mechanism_family_csv", _CANONICAL_MECHANISM_FAMILY_CSV),
    ):
        try:
            candidate = root / fname
            if candidate.is_file():
                out[slot] = str(candidate)
        except OSError:
            continue

    # ``mechanism_family_csv`` is optional, so it never lands in
    # ``missing``.  The other three are required for auto-source.
    for slot in ("backup_path", "high_priority_csv", "medium_csv"):
        if not out[slot]:
            out["missing"].append(slot)

    return out


def _run_repaired_cohort_summary(
    *,
    backup_path:          str | None,
    high_priority_csv:    str | None,
    medium_csv:           str | None,
    mechanism_family_csv: str | None,
    db_path:              str | None,
    limit:                int,
) -> dict[str, Any]:
    from scripts.manual_repaired_cohort_validation_summary import (
        summarize_repaired_cohort_validation,
    )

    return summarize_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=limit,
    )


def _run_curated_candidate_status() -> dict[str, Any]:
    from scripts.curated_candidate_status import compute_status

    return compute_status()


def _run_short_horizon_repair_packet(
    *, db_path: str | None, limit: int,
) -> dict[str, Any]:
    from scripts.short_horizon_repair_packet import (
        summarize_short_horizon_repair_packet,
    )

    return summarize_short_horizon_repair_packet(
        db_path=db_path, limit=limit,
    )


def _run_benchmark_sensitivity_preflight(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Run the read-only upstream benchmark-sensitivity preflight and
    return its full payload.

    The preflight is the readiness source of truth for the benchmark
    block: it inspects ``price_cache`` for both the primary tickers and
    the alternative benchmark, checks forward horizons and the
    estimation window, and returns a ready/blocked count plus per-row
    blocker reasons.  Using its defaults verbatim keeps the status
    report's --json output one-for-one with
    ``benchmark_sensitivity_preflight.py --json``.

    Tests patch this attribute directly so the import only resolves on
    the un-patched path.
    """
    from scripts.benchmark_sensitivity_preflight import (
        summarize_benchmark_sensitivity_preflight,
    )

    return summarize_benchmark_sensitivity_preflight(db_path=db_path)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


_DEFAULT_REPAIRED_LIMIT:        int = 50
_DEFAULT_SHORT_HORIZON_LIMIT:   int = 50


def build_evidence_cohort_status(
    *,
    backup_path:          str | None = None,
    high_priority_csv:    str | None = None,
    medium_csv:           str | None = None,
    mechanism_family_csv: str | None = None,
    db_path:              str | None = None,
    repaired_limit:       int        = _DEFAULT_REPAIRED_LIMIT,
    short_horizon_limit:  int        = _DEFAULT_SHORT_HORIZON_LIMIT,
) -> dict[str, Any]:
    """Build the read-only evidence cohort status envelope.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    repaired_block = _build_repaired_cohort_block(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=max(int(repaired_limit), 0),
    )
    curated_block, curated_errors = _build_curated_candidate_block()
    errors.extend(curated_errors)
    short_horizon_block = _build_short_horizon_block(
        db_path=db_path, limit=max(int(short_horizon_limit), 0),
    )
    benchmark_block = _build_benchmark_sensitivity_block(db_path=db_path)

    next_best_action = _build_next_best_action(
        repaired=repaired_block,
        curated=curated_block,
        short_horizon=short_horizon_block,
        benchmark=benchmark_block,
    )

    return {
        "ok":                             not errors,
        "current_repaired_cohort":        repaired_block,
        "curated_candidate_status":       curated_block,
        "short_horizon_expansion_status": short_horizon_block,
        "benchmark_sensitivity_status":   benchmark_block,
        "evidence_claim_allowed":         list(_CLAIM_ALLOWED),
        "evidence_claim_not_allowed":     list(_CLAIM_NOT_ALLOWED),
        "next_best_action":               next_best_action,
        "warnings":                       warnings,
        "errors":                         errors,
    }


# ---------------------------------------------------------------------------
# Per-section builders
# ---------------------------------------------------------------------------


def _build_repaired_cohort_block(
    *,
    backup_path:          str | None,
    high_priority_csv:    str | None,
    medium_csv:           str | None,
    mechanism_family_csv: str | None,
    db_path:              str | None,
    limit:                int,
) -> dict[str, Any]:
    """Materialize the current_repaired_cohort block.

    Source precedence (no-args demo must just work):

      1. Operator-supplied CLI args (when ``backup_path`` and BOTH
         worksheet CSVs are passed) win — ``source_mode="explicit_args"``.
      2. Otherwise, probe the local project root for the canonical
         worksheet CSVs and the most recent ``backups/events-*.db``.
         When all three required inputs are present, auto-source —
         ``source_mode="auto_sourced"``.
      3. Otherwise, surface a lightweight ``status="not_sourced"`` /
         ``source_mode="not_sourced"`` block listing the missing
         required inputs verbatim.

    The heavy summary seam is only invoked on the first two paths;
    ``not_sourced`` is a structural skip so the no-args run stays
    cheap on machines without local fixtures.
    """
    explicit_complete = bool(
        backup_path and high_priority_csv and medium_csv
    )

    source_mode: str
    final_backup_path: str | None
    final_high_priority_csv: str | None
    final_medium_csv: str | None
    final_mechanism_family_csv: str | None
    discovered_missing: list[str] = []

    if explicit_complete:
        source_mode               = "explicit_args"
        final_backup_path         = backup_path
        final_high_priority_csv   = high_priority_csv
        final_medium_csv          = medium_csv
        final_mechanism_family_csv = mechanism_family_csv
    else:
        discovered = _safe_dict(_discover_local_repaired_inputs())
        discovered_missing = [
            m for m in (discovered.get("missing") or [])
            if isinstance(m, str)
        ]
        if not discovered_missing:
            source_mode = "auto_sourced"
            final_backup_path = (
                backup_path or discovered.get("backup_path")
            )
            final_high_priority_csv = (
                high_priority_csv or discovered.get("high_priority_csv")
            )
            final_medium_csv = (
                medium_csv or discovered.get("medium_csv")
            )
            final_mechanism_family_csv = (
                mechanism_family_csv
                or discovered.get("mechanism_family_csv")
            )
        else:
            return {
                "status":                       "not_sourced",
                "source_mode":                  "not_sourced",
                "repaired_clean_event_count":   0,
                "repaired_clean_event_ids":     [],
                "records_count":                0,
                "fdr_significant_count":        0,
                "by_event_verdict":             {},
                "missing_inputs":               list(discovered_missing),
                "note": (
                    "Repaired cohort summary not run.  Supply "
                    "--backup-path, --high-priority-csv, and "
                    "--medium-csv (and optionally --mechanism-family-"
                    "csv), or place the canonical worksheet CSVs and a "
                    "backups/events-*.db file under the project root "
                    "for auto-sourcing."
                ),
            }

    summary = _safe_dict(_run_repaired_cohort_summary(
        backup_path=final_backup_path,
        high_priority_csv=final_high_priority_csv,
        medium_csv=final_medium_csv,
        mechanism_family_csv=final_mechanism_family_csv,
        db_path=db_path,
        limit=limit,
    ))

    repaired_ids = _coerce_int_list(
        summary.get("repaired_clean_event_ids") or [],
    )
    return {
        "status":                       "sourced",
        "source_mode":                  source_mode,
        "repaired_clean_event_count":   len(repaired_ids),
        "repaired_clean_event_ids":     list(repaired_ids),
        "records_count":                _coerce_int(
            summary.get("records_count"),
        ),
        "fdr_significant_count":        _coerce_int(
            summary.get("significant_count"),
        ),
        "by_event_verdict":             {
            str(k): str(v)
            for k, v in (summary.get("by_event_verdict") or {}).items()
        },
        "note": (
            "Repaired cohort sourced from manual_repaired_cohort_validation_"
            "summary.  Counts reflect the small operator-repaired pilot — "
            "this is per-event evidence, not an aggregate validation "
            "outcome."
        ),
    }


def _build_curated_candidate_block() -> tuple[dict[str, Any], list[str]]:
    """Lightweight wrapper over ``curated_candidate_status.compute_status``
    that surfaces the staged candidate count plus operator-facing
    breakdowns.  Errors propagate up to the envelope's ``errors`` list."""
    payload = _safe_dict(_run_curated_candidate_status())
    upstream_errors = [
        e for e in (payload.get("errors") or []) if isinstance(e, str)
    ]
    total = _coerce_int(payload.get("total"))
    block: dict[str, Any] = {
        "staged_candidate_count":      total,
        "counts_by_status":            dict(
            payload.get("counts_by_status") or {}
        ),
        "counts_by_mechanism_family":  dict(
            payload.get("counts_by_mechanism_family") or {}
        ),
        "counts_by_ticker":            dict(
            payload.get("counts_by_ticker") or {}
        ),
        "missing_field_counts":        dict(
            payload.get("missing_field_counts") or {}
        ),
    }
    if total <= 0:
        block["note"] = (
            "No curated candidates staged yet.  Use the curated_candidate_"
            "stage_smoke / curated_event_loader path to stage operator-"
            "selected candidates before invoking the curated-candidate "
            "validation run."
        )
    else:
        block["note"] = (
            "Curated candidates staged for operator review.  Staging is "
            "an inventory state, not a validation outcome — the curated-"
            "candidate validation run must clear FDR multiple-testing "
            "correction before any aggregate claim is appropriate."
        )
    return block, upstream_errors


def _build_short_horizon_block(
    *, db_path: str | None, limit: int,
) -> dict[str, Any]:
    """Run the short-horizon repair packet builder and surface the
    candidate count plus an operator-review-required flag."""
    payload = _safe_dict(_run_short_horizon_repair_packet(
        db_path=db_path, limit=limit,
    ))
    candidate_count = _coerce_int(
        payload.get("total_candidates_after_filter"),
    )
    operator_review = candidate_count > 0
    if operator_review:
        note = (
            f"{candidate_count} short-horizon (1d/5d) repair candidate(s) "
            "remain in the operator review queue.  Each row needs manual "
            "review before it can join a clean short-horizon repaired "
            "cohort — operator review is required."
        )
    else:
        note = (
            "No short-horizon (1d/5d) repair candidates remain in the "
            "operator review queue.  Re-run the upstream short-horizon "
            "contamination scan after the next archive ingestion to "
            "surface new candidates."
        )
    return {
        "candidate_count":               candidate_count,
        "operator_review_required":      operator_review,
        "total_short_ready":             _coerce_int(
            payload.get("total_short_ready"),
        ),
        "delta_vs_full_ready":           _coerce_int(
            payload.get("delta_vs_full_ready"),
        ),
        "reviewed_exclusion_set_count":  _coerce_int(
            payload.get("reviewed_exclusion_set_count"),
        ),
        "note":                          note,
    }


def _build_benchmark_sensitivity_block(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Surface the benchmark-sensitivity readiness block sourced
    one-for-one from ``benchmark_sensitivity_preflight``.

    State machine::

        upstream raised OR ok=False OR errors          -> "unknown"
        blocked_count > 0                              -> "blocked"
        blocked_count == 0 and checked_events > 0      -> "ready"
        otherwise (0 events checked, no errors)        -> "unknown"

    The block deliberately never asserts anything about significance:
    a preflight blocker is a missing-data condition, not a finding.
    """
    errors: list[str] = []
    try:
        payload = _safe_dict(
            _run_benchmark_sensitivity_preflight(db_path=db_path),
        )
    except Exception as exc:  # noqa: BLE001 — defensive seam wrapper
        payload = {}
        errors.append(
            f"benchmark sensitivity preflight raised: {exc!r}"
        )

    upstream_errors = [
        e for e in (payload.get("errors") or []) if isinstance(e, str)
    ]
    if payload and not payload.get("ok"):
        errors.append(
            "; ".join(upstream_errors) if upstream_errors
            else "benchmark sensitivity preflight returned ok=False"
        )
    elif upstream_errors:
        errors.extend(upstream_errors)

    checked_events = _coerce_int(payload.get("checked_events"))
    ready_count    = _coerce_int(payload.get("ready_count"))
    blocked_count  = _coerce_int(payload.get("blocked_count"))

    rows: list[dict[str, Any]] = []
    for r in payload.get("rows") or []:
        if not isinstance(r, dict):
            continue
        rows.append({
            "event_id":            _coerce_int(r.get("event_id")),
            "primary_ticker":      str(r.get("primary_ticker") or ""),
            "benchmark_ticker":    str(r.get("benchmark_ticker") or ""),
            "can_run_sensitivity": bool(r.get("can_run_sensitivity")),
            "blocker_reason":      str(r.get("blocker_reason") or ""),
        })

    if errors:
        status = "unknown"
        note = (
            "Benchmark sensitivity preflight could not be evaluated; "
            "inspect benchmark_sensitivity_status.errors and re-run "
            "scripts/benchmark_sensitivity_preflight.py --json to see "
            "the underlying cache state."
        )
    elif blocked_count > 0:
        status = "blocked"
        note = (
            f"Benchmark sensitivity check is blocked — "
            f"benchmark_sensitivity_preflight reports {blocked_count} of "
            f"{checked_events} checked event(s) missing price_cache "
            f"coverage for the primary or benchmark ticker.  This is a "
            f"missing-data blocker awaiting a cache backfill, not a "
            f"finding about the cohort's behaviour."
        )
    elif checked_events > 0:
        status = "ready"
        note = (
            f"Benchmark sensitivity preflight reports {ready_count} of "
            f"{checked_events} checked event(s) have sufficient cache "
            f"coverage for the operator's proposed alternative "
            f"benchmark.  Sensitivity comparisons are descriptive only."
        )
    else:
        status = "unknown"
        note = (
            "Benchmark sensitivity preflight checked 0 events.  Supply "
            "event ids and re-run benchmark_sensitivity_preflight.py "
            "before treating this block as authoritative."
        )

    return {
        "status":                  status,
        "benchmark_ticker_probed": _BENCHMARK_TICKER_FOR_BLOCK,
        "checked_events":          checked_events,
        "ready_count":             ready_count,
        "blocked_count":           blocked_count,
        "rows":                    rows,
        "errors":                  errors,
        "note":                    note,
    }


# ---------------------------------------------------------------------------
# next_best_action
# ---------------------------------------------------------------------------


def _build_next_best_action(
    *,
    repaired:      dict[str, Any],
    curated:       dict[str, Any],
    short_horizon: dict[str, Any],
    benchmark:     dict[str, Any],
) -> str:
    """Pick the single highest-leverage next step for the operator.

    Order:
      1. Source the repaired cohort if it has not been sourced yet.
      2. Stage curated candidates if none are staged.
      3. Unblock the benchmark sensitivity check if its cache is missing.
      4. Triage the short-horizon repair queue if candidates remain.
      5. Otherwise, report there is no urgent action.
    """
    if repaired.get("status") != "sourced":
        return (
            "Source the repaired cohort summary by re-running with "
            "--backup-path / --high-priority-csv / --medium-csv (and "
            "optionally --mechanism-family-csv) so the demo state can "
            "cite the 5-event repaired cohort directly."
        )
    if _coerce_int(curated.get("staged_candidate_count")) == 0:
        return (
            "Stage operator-selected curated candidates via the curated_"
            "event_loader / curated_candidate_stage_smoke path before "
            "invoking the curated-candidate validation run."
        )
    if benchmark.get("status") == "blocked":
        blocked = _coerce_int(benchmark.get("blocked_count"))
        checked = _coerce_int(benchmark.get("checked_events"))
        return (
            f"Backfill price_cache for the operator's proposed "
            f"alternative benchmark (probed ticker: "
            f"{benchmark.get('benchmark_ticker_probed')}) so the "
            f"{blocked} of {checked} event(s) flagged by "
            f"benchmark_sensitivity_preflight are no longer blocked.  "
            f"This is a missing-data blocker, not a finding."
        )
    if benchmark.get("status") == "unknown":
        return (
            "Benchmark sensitivity preflight could not be evaluated; "
            "inspect benchmark_sensitivity_status.errors and re-run "
            "scripts/benchmark_sensitivity_preflight.py --json to "
            "surface the underlying cache state."
        )
    if _coerce_int(short_horizon.get("candidate_count")) > 0:
        return (
            f"Triage the {short_horizon.get('candidate_count')} short-"
            f"horizon (1d/5d) repair candidate(s) by hand — operator "
            f"review is required before any candidate can join a clean "
            f"short-horizon repaired cohort."
        )
    return (
        "No urgent demo-readiness blocker remains; consider expanding "
        "the repaired cohort beyond the current pilot or pre-registering "
        "directional hypotheses before broadening the validation surface."
    )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            out.append(v)
            continue
        if isinstance(v, str) and v.strip():
            try:
                out.append(int(v.strip()))
            except ValueError:
                continue
    return sorted(set(out))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["=== Evidence cohort status report ===", ""]
    lines.append(f"OK:                             {report['ok']}")
    lines.append("")

    rep = report.get("current_repaired_cohort") or {}
    lines.append("Current repaired cohort")
    lines.append("-----------------------")
    lines.append(f"  status:                       {rep.get('status')}")
    lines.append(
        f"  repaired_clean_event_count:   "
        f"{rep.get('repaired_clean_event_count')}"
    )
    lines.append(
        f"  repaired_clean_event_ids:     "
        f"{rep.get('repaired_clean_event_ids')}"
    )
    lines.append(
        f"  records_count:                {rep.get('records_count')}"
    )
    lines.append(
        f"  fdr_significant_count:        "
        f"{rep.get('fdr_significant_count')}"
    )
    if rep.get("note"):
        lines.append(f"  note:                         {rep['note']}")
    lines.append("")

    cur = report.get("curated_candidate_status") or {}
    lines.append("Curated candidate status")
    lines.append("------------------------")
    lines.append(
        f"  staged_candidate_count:       "
        f"{cur.get('staged_candidate_count')}"
    )
    if cur.get("counts_by_status"):
        lines.append(f"  counts_by_status:             {cur['counts_by_status']}")
    if cur.get("note"):
        lines.append(f"  note:                         {cur['note']}")
    lines.append("")

    sh = report.get("short_horizon_expansion_status") or {}
    lines.append("Short-horizon expansion status")
    lines.append("------------------------------")
    lines.append(
        f"  candidate_count:              {sh.get('candidate_count')}"
    )
    lines.append(
        f"  operator_review_required:     "
        f"{sh.get('operator_review_required')}"
    )
    lines.append(
        f"  total_short_ready:            {sh.get('total_short_ready')}"
    )
    if sh.get("note"):
        lines.append(f"  note:                         {sh['note']}")
    lines.append("")

    bench = report.get("benchmark_sensitivity_status") or {}
    lines.append("Benchmark sensitivity status")
    lines.append("----------------------------")
    lines.append(f"  status:                       {bench.get('status')}")
    lines.append(
        f"  benchmark_ticker_probed:      "
        f"{bench.get('benchmark_ticker_probed')}"
    )
    lines.append(
        f"  checked_events:               {bench.get('checked_events')}"
    )
    lines.append(
        f"  ready_count:                  {bench.get('ready_count')}"
    )
    lines.append(
        f"  blocked_count:                {bench.get('blocked_count')}"
    )
    if bench.get("note"):
        lines.append(f"  note:                         {bench['note']}")
    for err in bench.get("errors") or []:
        lines.append(f"  error:                        {err}")
    lines.append("")

    lines.append("Evidence claims allowed")
    lines.append("-----------------------")
    for claim in report.get("evidence_claim_allowed") or []:
        lines.append(f"  + {claim}")
    lines.append("")

    lines.append("Evidence claims NOT allowed")
    lines.append("---------------------------")
    for claim in report.get("evidence_claim_not_allowed") or []:
        lines.append(f"  - {claim}")
    lines.append("")

    lines.append(f"Next best action: {report.get('next_best_action')}")

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
            "Read-only evidence cohort status report.  Composes the "
            "repaired-cohort validation summary, the curated_candidates "
            "staging table, the short-horizon repair packet, and a "
            "price_cache benchmark presence probe into a single 10-key "
            "JSON envelope.  Conservative wording only — never claims "
            "alpha, predictive edge, or causal effect.  Read-only: no "
            "DB writes, no provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help=(
            "Optional path to the events DB backup.  Required (along "
            "with both worksheet CSVs) to materialize the repaired-"
            "cohort section; absent inputs surface as not_sourced."
        ),
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv", default=None,
        help="Optional path to the high-priority manual ticker repair CSV.",
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None,
        help="Optional path to the medium-batch manual ticker repair CSV.",
    )
    parser.add_argument(
        "--mechanism-family-csv", dest="mechanism_family_csv",
        default=None,
        help="Optional path to the mechanism-family repair packet CSV.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Used by the upstream "
            "scripts and by the XLE price-cache presence probe; never "
            "opened for writes."
        ),
    )
    parser.add_argument(
        "--repaired-limit", type=int, default=_DEFAULT_REPAIRED_LIMIT,
        dest="repaired_limit",
        help=(
            f"Cap forwarded to the repaired-cohort summary "
            f"(default {_DEFAULT_REPAIRED_LIMIT})."
        ),
    )
    parser.add_argument(
        "--short-horizon-limit", type=int,
        default=_DEFAULT_SHORT_HORIZON_LIMIT,
        dest="short_horizon_limit",
        help=(
            f"Cap forwarded to the short-horizon repair packet "
            f"(default {_DEFAULT_SHORT_HORIZON_LIMIT})."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of compact text.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_evidence_cohort_status(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        mechanism_family_csv=args.mechanism_family_csv,
        db_path=args.db_path,
        repaired_limit=int(args.repaired_limit),
        short_horizon_limit=int(args.short_horizon_limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
