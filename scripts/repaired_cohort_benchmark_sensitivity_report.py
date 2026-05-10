#!/usr/bin/env python3
"""Repaired-cohort benchmark sensitivity report.

A read-only sensitivity check answering one narrow question: would
the 5-event repaired cohort's SAR / p / FDR change if we ran the
validation pipeline with each event's operator-proposed benchmark
instead of the universal SPY benchmark?

The report is **not** a re-validation, an alpha claim, or proof.  It
is a side-by-side comparison: SPY result vs operator-benchmark
result, per (event_id, horizon).  Conservative wording only.

Read-only by construction
-------------------------

* Operates on a copied backup via the existing manual-aware repaired
  cohort validation runner — never mutates the live DB or input
  backup.  Both are hashed before/after the run; drift is surfaced as
  an error.
* No DB writes anywhere; no LLM seam; no FastAPI surface; no
  ``yfinance`` or ``market_check`` import in this module's import
  graph.

Order of operations::

    1. Validate inputs (--backup-path + both required CSVs must exist).
    2. Hash live DB + input backup.
    3. Parse all three CSVs to extract per-event proposed_benchmark.
    4. Invoke baseline (SPY) validation via _run_baseline_validation.
    5. If baseline returns ok=False, propagate ok=False and surface
       its errors verbatim — no operator-benchmark run.
    6. Build benchmark_by_event_id from CSV proposed_benchmark cells,
       skipping events whose proposed value is blank or equals SPY.
    7. If at least one event carries a non-SPY alternative, invoke
       _run_operator_benchmark_validation for those events.  When no
       event proposes an alternative the operator-benchmark run is
       skipped and every record surfaces no_alternative_proposed.
    8. Build per-record comparisons, joining on (event_id, horizon).
    9. Re-hash live + backup; surface drift as errors.

Output contract::

    {
      "ok":                       bool,
      "records": [                # one entry per (event_id, horizon)
        {
          "event_id":                  int,
          "ticker":                    str,
          "mechanism_family":          str | None,
          "horizon":                   int,
          "spy_result": {
            "sar":         float | None,
            "p_value":     float | None,
            "fdr_q":       float | None,
            "significant": bool,
          },
          "operator_benchmark_result": null | {
            "benchmark":   str,
            "sar":         float | None,
            "p_value":     float | None,
            "fdr_q":       float | None,
            "significant": bool,
          },
          "verdict_change":            str,    # see below
          "fdr_change":                float | None,
          "recommended_next_action":   str,    # conservative
        },
        ...
      ],
      "repaired_clean_event_ids": list[int],
      "summary": {
        "events_in_cohort":                  int,
        "events_with_alternative_benchmark": int,
        "events_with_verdict_change":        int,
      },
      "live_db_unchanged":        bool,
      "input_backup_unchanged":   bool,
      "errors":                   list[str],
      "warnings":                 list[str],
    }

``verdict_change`` vocabulary
-----------------------------

* ``no_alternative_proposed`` — the operator did not propose a
  benchmark different from SPY (no row, blank cell, or proposed cell
  equals SPY).  ``operator_benchmark_result`` is null and
  ``fdr_change`` is null.
* ``no_change`` — both runs agree on the FDR-significance label.
* ``flip_to_significant`` — SPY was non-significant, operator
  benchmark is significant.
* ``flip_to_nonsignificant`` — SPY was significant, operator
  benchmark is not.

Significance is read from the underlying runner's per-example
``statistically_significant`` flag when present, else derived from
``fdr_q <= alpha`` with the project's default alpha.  No hand-rolled
thresholding lives in this module.

Patchable seams (local to this module)
--------------------------------------

* ``_run_baseline_validation``         — wraps the SPY-baseline run.
* ``_run_operator_benchmark_validation`` — wraps the per-event
  operator-benchmark run.

Tests patch these seams directly with synthetic payloads so the test
suite never invokes the real validation pipeline; the live CLI path
delegates to the existing manual-aware runner.

Usage::

    python scripts/repaired_cohort_benchmark_sensitivity_report.py \\
        --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --mechanism-family-csv mechanism_family_repair_packet.csv \\
        --limit 50
"""
from __future__ import annotations

import argparse
import csv as csv_module
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT:    int   = 50
_DEFAULT_ALPHA:    float = 0.05
_BENCHMARK_TICKER: str   = "SPY"


_VERDICT_NO_ALT:        str = "no_alternative_proposed"
_VERDICT_NO_CHANGE:     str = "no_change"
_VERDICT_FLIP_TO_SIG:   str = "flip_to_significant"
_VERDICT_FLIP_TO_NOSIG: str = "flip_to_nonsignificant"
_VERDICT_UNCOMPUTABLE:  str = "alternative_proposed_but_uncomputable"


# ---------------------------------------------------------------------------
# Patchable seams — local to this module so tests patch a single
# surface.  Lazy imports fire only on the un-patched path.
# ---------------------------------------------------------------------------


def _run_baseline_validation(
    *,
    backup_path:          str | None,
    high_priority_csv:    str | None,
    medium_csv:           str | None,
    mechanism_family_csv: str | None,
    db_path:              str | None,
    limit:                int,
) -> dict[str, Any]:
    """Run the existing manual-aware repaired-cohort validation with
    the SPY benchmark default.  Returns its full 14-key payload.

    The lazy import keeps the test suite's import-isolation contract:
    importing this module never pulls the validation runner in unless
    the live path is exercised.  Tests patch the seam directly.
    """
    from scripts.manual_repaired_cohort_validation_run import (
        run_manual_repaired_cohort_validation,
    )

    return run_manual_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=limit,
    )


def _run_operator_benchmark_validation(
    *,
    backup_path:          str | None,
    high_priority_csv:    str | None,
    medium_csv:           str | None,
    mechanism_family_csv: str | None,
    db_path:              str | None,
    limit:                int,
    benchmark_by_event_id: dict[int, str],
) -> dict[str, Any]:
    """Run the manual-aware repaired-cohort validation with each
    event's operator-proposed benchmark substituted.

    The live implementation runs the underlying validation runner once
    per unique alternative benchmark, monkey-patching the readiness
    module's benchmark constant for the duration of each call, then
    merges the per-event examples back into a single payload.  Tests
    patch this seam directly so the suite never exercises the
    monkey-patch path.

    ``benchmark_by_event_id`` maps event_id → operator-proposed
    benchmark ticker (already filtered to non-SPY values).  When the
    map is empty the seam returns an empty payload — callers should
    short-circuit before invoking it.
    """
    if not benchmark_by_event_id:
        return _empty_runner_payload()

    # Lazy imports — kept under the seam so the import-isolation test
    # remains green.
    from scripts.manual_repaired_cohort_validation_run import (
        run_manual_repaired_cohort_validation,
    )

    # Group events by their proposed benchmark so we issue one
    # underlying run per benchmark variant rather than one per event.
    events_by_benchmark: dict[str, set[int]] = {}
    for ev_id, bench in benchmark_by_event_id.items():
        events_by_benchmark.setdefault(bench, set()).add(ev_id)

    merged_examples: list[dict[str, Any]] = []
    merged_errors:   list[str]            = []
    merged_warnings: list[str]            = []
    repaired_set:    set[int]             = set()

    # Both the readiness module and the archive runner copy
    # _BENCHMARK_TICKER at import time (``from … import _BENCHMARK_TICKER``).
    # To make the substitution take effect in the live event-study
    # path we MUST patch both module-level constants for the duration
    # of each call.
    import scripts.stat_validation_readiness_report as _readiness
    import scripts.archive_stat_validation_run as _archive
    saved_readiness = getattr(_readiness, "_BENCHMARK_TICKER",
                              _BENCHMARK_TICKER)
    saved_archive   = getattr(_archive,   "_BENCHMARK_TICKER",
                              _BENCHMARK_TICKER)
    try:
        for benchmark, event_ids in events_by_benchmark.items():
            _readiness._BENCHMARK_TICKER = benchmark
            _archive._BENCHMARK_TICKER   = benchmark
            sub = run_manual_repaired_cohort_validation(
                backup_path=backup_path,
                high_priority_csv=high_priority_csv,
                medium_csv=medium_csv,
                mechanism_family_csv=mechanism_family_csv,
                db_path=db_path,
                limit=limit,
            )
            if not isinstance(sub, dict):
                continue
            for ex in (sub.get("examples") or []):
                if not isinstance(ex, dict):
                    continue
                if ex.get("event_id") in event_ids:
                    enriched = dict(ex)
                    enriched["benchmark"] = benchmark
                    merged_examples.append(enriched)
            merged_errors.extend(sub.get("errors") or [])
            merged_warnings.extend(sub.get("warnings") or [])
            repaired_set.update(int(i) for i in (sub.get("repaired_clean_event_ids") or [])
                                if isinstance(i, int))
    finally:
        _readiness._BENCHMARK_TICKER = saved_readiness
        _archive._BENCHMARK_TICKER   = saved_archive

    return {
        "ok":                       not merged_errors,
        "repaired_clean_event_ids": sorted(repaired_set),
        "events_evaluated":         len({e.get("event_id") for e in merged_examples}),
        "records_count":            len(merged_examples),
        "significant_count":        0,
        "by_horizon":               {},
        "by_mechanism_family":      {},
        "examples":                 merged_examples,
        "excluded_event_ids":       [],
        "remaining_blockers":       {},
        "live_db_unchanged":        True,
        "input_backup_unchanged":   True,
        "errors":                   merged_errors,
        "warnings":                 merged_warnings,
    }


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_repaired_cohort_benchmark_sensitivity(
    *,
    backup_path:          str | None = None,
    high_priority_csv:    str | None = None,
    medium_csv:           str | None = None,
    mechanism_family_csv: str | None = None,
    db_path:              str | None = None,
    limit:                int        = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the read-only repaired-cohort benchmark sensitivity
    check.  Returns the envelope dict described in the module
    docstring.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    # Step 1: validate inputs.
    if not backup_path:
        errors.append("--backup-path is required")
    elif not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
    if not high_priority_csv:
        errors.append("--high-priority-csv is required")
    elif not Path(high_priority_csv).exists():
        errors.append(
            f"--high-priority-csv does not exist: {high_priority_csv}"
        )
    if not medium_csv:
        errors.append("--medium-csv is required")
    elif not Path(medium_csv).exists():
        errors.append(f"--medium-csv does not exist: {medium_csv}")
    if mechanism_family_csv and not Path(mechanism_family_csv).exists():
        errors.append(
            f"--mechanism-family-csv does not exist: "
            f"{mechanism_family_csv}"
        )
    if errors:
        return _final_envelope(
            ok=False, records=[], repaired_clean_event_ids=[],
            summary=_summary(0, 0, 0),
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    # Step 3: parse CSVs for proposed-benchmark hints.
    benchmark_by_event_id = _extract_proposed_benchmarks(
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        warnings=warnings,
    )

    # Step 4: baseline (SPY).
    baseline_payload = _safe_dict(_run_baseline_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        mechanism_family_csv=mechanism_family_csv,
        db_path=db_path,
        limit=10**9,  # baseline must surface every per-(event,horizon)
                      # record so the comparison is exhaustive; we cap
                      # the FINAL records list ourselves below.
    ))

    # Step 5: propagate baseline failure verbatim.
    if not baseline_payload.get("ok", False):
        for e in baseline_payload.get("errors") or []:
            if isinstance(e, str) and e:
                errors.append(f"baseline: {e}")
        for w in baseline_payload.get("warnings") or []:
            if isinstance(w, str) and w:
                warnings.append(f"baseline: {w}")
        return _final_envelope(
            ok=False, records=[],
            repaired_clean_event_ids=list(
                baseline_payload.get("repaired_clean_event_ids") or []
            ),
            summary=_summary(0, 0, 0),
            db_path=db_path, backup_path=backup_path,
            live_hash_before=live_hash_before,
            backup_hash_before=backup_hash_before,
            errors=errors, warnings=warnings,
        )

    repaired_event_ids: list[int] = sorted({
        i for i in baseline_payload.get("repaired_clean_event_ids") or []
        if isinstance(i, int)
    })

    # Restrict the proposed-benchmark hints to events that actually
    # entered the repaired cohort — events that fell out of the cohort
    # (e.g., excluded via CSV) carry no comparison.
    benchmark_by_event_id = {
        ev: b for ev, b in benchmark_by_event_id.items()
        if ev in repaired_event_ids
    }

    baseline_examples: list[dict[str, Any]] = [
        e for e in (baseline_payload.get("examples") or [])
        if isinstance(e, dict)
    ]

    # Step 6/7: operator-benchmark variant.
    if benchmark_by_event_id:
        operator_payload = _safe_dict(_run_operator_benchmark_validation(
            backup_path=backup_path,
            high_priority_csv=high_priority_csv,
            medium_csv=medium_csv,
            mechanism_family_csv=mechanism_family_csv,
            db_path=db_path,
            limit=10**9,
            benchmark_by_event_id=benchmark_by_event_id,
        ))
        for e in operator_payload.get("errors") or []:
            if isinstance(e, str) and e:
                errors.append(f"operator_benchmark: {e}")
        for w in operator_payload.get("warnings") or []:
            if isinstance(w, str) and w:
                warnings.append(f"operator_benchmark: {w}")
        operator_examples = [
            e for e in (operator_payload.get("examples") or [])
            if isinstance(e, dict)
        ]
    else:
        operator_examples = []

    # Step 8: per-record comparison.
    operator_index: dict[tuple[int, int], dict[str, Any]] = {}
    for ex in operator_examples:
        key = _example_key(ex)
        if key is not None:
            operator_index[key] = ex

    records: list[dict[str, Any]] = []
    for ex in baseline_examples:
        key = _example_key(ex)
        if key is None:
            continue
        ev_id, horizon = key
        proposed_bench = benchmark_by_event_id.get(ev_id)
        spy_result = _result_dict(ex, alpha=_DEFAULT_ALPHA)
        if proposed_bench is None:
            # No alternative proposed for this event.
            verdict = _VERDICT_NO_ALT
            op_result: dict[str, Any] | None = None
            fdr_change: float | None = None
        else:
            op_ex = operator_index.get(key)
            if op_ex is None:
                # Operator did propose an alternative, but the
                # underlying pipeline could not evaluate it for this
                # (event, horizon) — typically because the alternative
                # benchmark is missing from the price_cache.  Surface
                # a distinct verdict so operators can see the gap.
                verdict = _VERDICT_UNCOMPUTABLE
                op_result = None
                fdr_change = None
                warnings.append(
                    f"operator-benchmark variant missing record for "
                    f"event_id={ev_id} horizon={horizon} "
                    f"(proposed={proposed_bench})"
                )
            else:
                op_result = _result_dict(
                    op_ex, alpha=_DEFAULT_ALPHA,
                    benchmark=proposed_bench,
                )
                verdict = _classify_verdict(spy_result, op_result)
                fdr_change = _safe_diff(
                    op_result.get("fdr_q"), spy_result.get("fdr_q"),
                )

        records.append({
            "event_id":                  ev_id,
            "ticker":                    ex.get("primary_ticker")
                                          or ex.get("ticker"),
            "mechanism_family":          ex.get("mechanism_family"),
            "horizon":                   horizon,
            "spy_result":                spy_result,
            "operator_benchmark_result": op_result,
            "verdict_change":            verdict,
            "fdr_change":                fdr_change,
            "recommended_next_action":   _recommended_next_action(verdict),
        })

    # Cap the surfaced records list at the user-supplied limit; sort
    # for deterministic output.
    records.sort(key=lambda r: (r["event_id"], r["horizon"]))
    capped = records[:max(int(limit), 0)] if limit else records

    summary = _summary(
        events_in_cohort=len(repaired_event_ids),
        events_with_alternative_benchmark=len(benchmark_by_event_id),
        events_with_verdict_change=len({
            r["event_id"] for r in records
            if r["verdict_change"] in (_VERDICT_FLIP_TO_SIG,
                                       _VERDICT_FLIP_TO_NOSIG)
        }),
        events_with_uncomputable_alternative=len({
            r["event_id"] for r in records
            if r["verdict_change"] == _VERDICT_UNCOMPUTABLE
        }),
    )

    return _final_envelope(
        ok=not errors, records=capped,
        repaired_clean_event_ids=repaired_event_ids,
        summary=summary,
        db_path=db_path, backup_path=backup_path,
        live_hash_before=live_hash_before,
        backup_hash_before=backup_hash_before,
        errors=errors, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# CSV parsing — extract per-event proposed_benchmark hints.
#
# Three CSVs:
#   high + medium share the manual-ticker schema (proposed_benchmark
#   column).
#   mechanism_family carries no proposed_benchmark column; events that
#   only appear there have no operator alternative.
#
# Conflict resolution: medium wins over high, mirroring the existing
# runner's merge order.  Family CSV cannot contribute a benchmark hint.
# ---------------------------------------------------------------------------


_HM_BENCH_COLUMN = "proposed_benchmark"


def _extract_proposed_benchmarks(
    *, high_priority_csv: str | None,
    medium_csv: str | None,
    mechanism_family_csv: str | None,
    warnings: list[str],
) -> dict[int, str]:
    out: dict[int, str] = {}
    for path in (high_priority_csv, medium_csv):
        if not path:
            continue
        for ev_id, bench in _read_hm_proposed_benchmarks(path, warnings):
            if bench and bench.strip().upper() != _BENCHMARK_TICKER:
                out[ev_id] = bench.strip()
            else:
                # Operator either left it blank or confirmed SPY —
                # remove any prior hint so the latest write wins.
                out.pop(ev_id, None)
    # mechanism_family CSV deliberately ignored: no proposed_benchmark.
    _ = mechanism_family_csv
    return out


def _read_hm_proposed_benchmarks(
    path: str, warnings: list[str],
) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            reader = csv_module.DictReader(fh)
            for raw in reader:
                try:
                    ev_id = int((raw.get("event_id") or "").strip())
                except (TypeError, ValueError):
                    continue
                bench = (raw.get(_HM_BENCH_COLUMN) or "").strip()
                rows.append((ev_id, bench))
    except OSError as e:
        warnings.append(f"failed reading proposed_benchmark from {path}: {e}")
    return rows


# ---------------------------------------------------------------------------
# Per-record helpers
# ---------------------------------------------------------------------------


def _example_key(ex: dict[str, Any]) -> tuple[int, int] | None:
    ev_id = ex.get("event_id")
    horizon = ex.get("horizon")
    if not isinstance(ev_id, int) or not isinstance(horizon, int):
        return None
    return ev_id, horizon


def _result_dict(
    ex: dict[str, Any], *, alpha: float,
    benchmark: str | None = None,
) -> dict[str, Any]:
    fdr_q = ex.get("fdr_q")
    p_value = ex.get("p_value")
    sar = ex.get("sar")
    significant = bool(ex.get("statistically_significant", False))
    if not significant and isinstance(fdr_q, (int, float)):
        significant = float(fdr_q) <= alpha
    out = {
        "sar":         _coerce_float(sar),
        "p_value":     _coerce_float(p_value),
        "fdr_q":       _coerce_float(fdr_q),
        "significant": bool(significant),
    }
    if benchmark is not None:
        out = {"benchmark": benchmark, **out}
    return out


def _coerce_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_diff(a: Any, b: Any) -> float | None:
    af = _coerce_float(a)
    bf = _coerce_float(b)
    if af is None or bf is None:
        return None
    return af - bf


def _classify_verdict(
    spy_result: dict[str, Any],
    op_result: dict[str, Any],
) -> str:
    spy_sig = bool(spy_result.get("significant"))
    op_sig  = bool(op_result.get("significant"))
    if spy_sig == op_sig:
        return _VERDICT_NO_CHANGE
    if op_sig and not spy_sig:
        return _VERDICT_FLIP_TO_SIG
    return _VERDICT_FLIP_TO_NOSIG


_RECOMMENDATIONS: dict[str, str] = {
    _VERDICT_NO_ALT: (
        "no alternative benchmark proposed; SPY-only sensitivity "
        "not applicable"
    ),
    _VERDICT_NO_CHANGE: (
        "sensitivity check inconclusive — significance label stable "
        "across SPY and operator benchmark"
    ),
    _VERDICT_FLIP_TO_SIG: (
        "operator review recommended — alternative benchmark "
        "increases nominal significance for this record"
    ),
    _VERDICT_FLIP_TO_NOSIG: (
        "operator review recommended — alternative benchmark "
        "decreases nominal significance for this record"
    ),
    _VERDICT_UNCOMPUTABLE: (
        "alternative benchmark proposed but pipeline could not "
        "evaluate it; backfill price_cache for the proposed "
        "benchmark and re-run"
    ),
}


def _recommended_next_action(verdict: str) -> str:
    return _RECOMMENDATIONS.get(verdict, _RECOMMENDATIONS[_VERDICT_NO_ALT])


def _summary(
    events_in_cohort: int,
    events_with_alternative_benchmark: int,
    events_with_verdict_change: int,
    events_with_uncomputable_alternative: int = 0,
) -> dict[str, int]:
    return {
        "events_in_cohort":                  events_in_cohort,
        "events_with_alternative_benchmark": events_with_alternative_benchmark,
        "events_with_verdict_change":        events_with_verdict_change,
        "events_with_uncomputable_alternative":
            events_with_uncomputable_alternative,
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _empty_runner_payload() -> dict[str, Any]:
    return {
        "ok":                       True,
        "repaired_clean_event_ids": [],
        "events_evaluated":         0,
        "records_count":            0,
        "significant_count":        0,
        "by_horizon":               {},
        "by_mechanism_family":      {},
        "examples":                 [],
        "excluded_event_ids":       [],
        "remaining_blockers":       {},
        "live_db_unchanged":        True,
        "input_backup_unchanged":   True,
        "errors":                   [],
        "warnings":                 [],
    }


# ---------------------------------------------------------------------------
# Hash helpers (mirror scripts.manual_ticker_repair_full_smoke for
# consistency).
# ---------------------------------------------------------------------------


def _hash_file_safe(path: str | None) -> str | None:
    if not path:
        return None
    try:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _hashes_match(
    *, before: str | None, after: str | None, path: str | None,
) -> bool:
    if not path:
        return True
    if before is None or after is None:
        return False
    return before == after


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _final_envelope(
    *, ok: bool,
    records: list[dict[str, Any]],
    repaired_clean_event_ids: list[int],
    summary: dict[str, int],
    db_path: str | None, backup_path: str | None,
    live_hash_before: str | None,
    backup_hash_before: str | None,
    errors: list[str], warnings: list[str],
) -> dict[str, Any]:
    live_hash_after   = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)
    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after,
        path=backup_path,
    )
    if not live_db_unchanged:
        errors.append(
            f"LIVE DB BYTES CHANGED during sensitivity run — "
            f"investigate: {db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during sensitivity run — "
            f"investigate: {backup_path}"
        )
    return {
        "ok":                       ok and not errors,
        "records":                  records,
        "repaired_clean_event_ids": repaired_clean_event_ids,
        "summary":                  summary,
        "live_db_unchanged":        live_db_unchanged,
        "input_backup_unchanged":   input_backup_unchanged,
        "errors":                   errors,
        "warnings":                 warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Repaired-cohort benchmark sensitivity report", ""]
    lines.append(f"OK:                         {report['ok']}")
    lines.append(
        f"Repaired clean event_ids:   "
        f"{report['repaired_clean_event_ids']}"
    )
    summary = report.get("summary") or {}
    lines.append(
        f"Events in cohort:           "
        f"{summary.get('events_in_cohort', 0)}"
    )
    lines.append(
        f"Events with alt benchmark:  "
        f"{summary.get('events_with_alternative_benchmark', 0)}"
    )
    lines.append(
        f"Events with verdict change: "
        f"{summary.get('events_with_verdict_change', 0)}"
    )
    lines.append(
        f"Events uncomputable alt:    "
        f"{summary.get('events_with_uncomputable_alternative', 0)}"
    )
    lines.append(
        f"Live DB unchanged:          {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:     {report['input_backup_unchanged']}"
    )

    records = report.get("records") or []
    if records:
        lines.append("")
        lines.append(f"Records ({len(records)}):")
        for r in records:
            spy = r.get("spy_result") or {}
            op  = r.get("operator_benchmark_result") or {}
            op_bench = op.get("benchmark") if op else "-"
            lines.append(
                f"  id={r.get('event_id')} h={_fmt(r.get('horizon'))} "
                f"{r.get('ticker') or '-'} "
                f"family={r.get('mechanism_family') or '-'} "
                f"verdict={r.get('verdict_change')}"
            )
            lines.append(
                f"    SPY  : SAR={_fmt(spy.get('sar'))} "
                f"p={_fmt(spy.get('p_value'))} "
                f"fdr_q={_fmt(spy.get('fdr_q'))} "
                f"sig={spy.get('significant')}"
            )
            if op:
                lines.append(
                    f"    {op_bench:<5}: SAR={_fmt(op.get('sar'))} "
                    f"p={_fmt(op.get('p_value'))} "
                    f"fdr_q={_fmt(op.get('fdr_q'))} "
                    f"sig={op.get('significant')} "
                    f"Δfdr={_fmt(r.get('fdr_change'))}"
                )
            lines.append(f"    next: {r.get('recommended_next_action')}")

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
            "Repaired-cohort benchmark sensitivity report.  Compares "
            "SAR / p / FDR for the manual-aware repaired cohort under "
            "the SPY benchmark vs each event's operator-proposed "
            "benchmark.  Read-only / temp-copy only — never mutates "
            "the live DB or input backup.  Conservative wording: this "
            "is a sensitivity check, not proof."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help="Path to a backup of the events DB (required).",
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv", default=None,
        help=(
            "Path to manual_ticker_repair_high_priority.csv (required)."
        ),
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None,
        help=(
            "Path to manual_ticker_repair_medium_production_like.csv "
            "(required)."
        ),
    )
    parser.add_argument(
        "--mechanism-family-csv", dest="mechanism_family_csv",
        default=None,
        help=(
            "Optional path to mechanism_family_repair_packet.csv.  "
            "When supplied its mechanism-family decisions and "
            "exclusion rows are applied to the same temp DB before "
            "the sensitivity check runs."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Hashed read-only "
            "before and after the run; never opened for writes."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap surfaced records at N entries (default "
            f"{_DEFAULT_LIMIT}).  Summary counts always reflect every "
            f"evaluated repaired event."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_default_db_path() -> str | None:
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    db_path = args.db_path if args.db_path else _resolve_default_db_path()

    report = run_repaired_cohort_benchmark_sensitivity(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        mechanism_family_csv=args.mechanism_family_csv,
        db_path=db_path,
        limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
