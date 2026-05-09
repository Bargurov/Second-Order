#!/usr/bin/env python3
"""Repaired-cohort short-horizon (1d/5d) statistical validation runner.

Sibling of :mod:`scripts.manual_repaired_cohort_validation_run`,
restricted to the 1d and 5d event-study horizons so an operator can
read short-horizon evidence from the SAME repaired cohort while the
20d-horizon cache backfill is still in flight.

Operating model
---------------

The runner is a thin wrapper.  It does not duplicate the temp-copy /
apply / price-backfill pipeline — it lets the existing full repaired-
cohort runner build that temp DB, then runs the existing short-horizon
archive validation runner against the SAME temp DB::

    full = run_manual_repaired_cohort_validation(...)
        ├── copies backup -> temp DB
        ├── applies operator CSV exclusions / retags / mf decisions
        ├── backfills price_cache for retag tickers
        ├── runs full 1d/5d/20d statistical validation
        └── leaks the temp DB path through warnings

    short = run_archive_short_horizon_stat_validation(db_path=temp_db)
        ├── reads the SAME temp DB (read-only)
        └── runs 1d/5d-only validation against the relaxed readiness
            predicate

The two runs see identical operator repairs by construction.  The
short-horizon records are then filtered to the cohort the full run
identified as ``repaired_clean_event_ids``.

Conservative language is mandatory.  Every surfaced number is short-
horizon statistical evidence under FDR control — a candidate, never
causal, never framed as a primary trading signal.  ``top_abs_sar``
is the largest absolute SAR observed in the repaired cohort; it is
NOT framed as a top performer or a tradable signal.

Output contract::

    {
      "ok":                        bool,
      "repaired_clean_event_ids":  [int, ...],
      "events_evaluated":          int,        # short-horizon
      "records_count":             int,        # short-horizon (1d+5d)
      "significant_count":         int,        # short-horizon
      "top_abs_sar": {
        "event_id":                int | None,
        "primary_ticker":          str | None,
        "horizon":                 int | None,
        "sar":                     float | None,
        "abs_sar":                 float | None,
        "p_value":                 float | None,
        "fdr_q":                   float | None,
        "interpretation":          str | None,
        "statistically_significant": bool | None,
      },
      "by_horizon":           {"1": {...}, "5": {...}},
      "by_mechanism_family":  {family: {...}, ...},
      "examples":             [{...}, ...],
      "excluded_event_ids":   [int, ...],      # passthrough from full
      "remaining_blockers":   {str: [str, ...]},   # passthrough
      "comparison_to_full_repaired_run": {
        "full_events_evaluated":   int,
        "full_records_count":      int,
        "full_significant_count":  int,
        "full_horizons":           [1, 5, 20],
        "short_horizons":          [1, 5],
        "events_evaluated_delta":  int,           # short - full
        "records_count_delta":     int,
        "significant_count_delta": int,
        "events_in_full_only":     [int, ...],
        "events_in_short_only":    [int, ...],
      },
      "live_db_unchanged":      bool,
      "input_backup_unchanged": bool,
      "errors":                 [str, ...],
      "warnings":               [str, ...],     # carries the leaked
                                                # ``Temp copy at <path>``
                                                # so operators can clean
                                                # up the temp DB
    }

Patchable seams (local to this module so tests patch a single
surface)::

    * ``_run_full_repaired_cohort``                  — wraps
      ``run_manual_repaired_cohort_validation``.
    * ``_run_short_horizon_validation_on_temp_db``   — wraps
      ``run_archive_short_horizon_stat_validation``, enriching its
      slimmed examples back into rich records (mechanism_family,
      statistically_significant) the same way the full repaired-cohort
      runner does for its underlying validation pipeline.

Out of scope (deliberately)
---------------------------
* Live DB never opened for writes — inherited invariant.
* Input backup never opened for writes — inherited invariant.
* No LLM, no FastAPI surface — never imports ``api`` or ``routes.*``.
* No write flag — temp-copy is implicit; the wrapper's purpose is to
  read evidence under the relaxed short-horizon predicate.

Usage::

    python scripts/manual_repaired_cohort_short_horizon_validation_run.py \\
        --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --limit 50
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Constants — pinned in tests.
# ---------------------------------------------------------------------------


_DEFAULT_LIMIT:    int               = 50
_BENCHMARK_TICKER: str               = "SPY"
_SHORT_HORIZONS:   tuple[int, ...]   = (1, 5)
_FULL_HORIZONS:    tuple[int, ...]   = (1, 5, 20)
_TEMP_COPY_PREFIX: str               = "Temp copy at "


# ---------------------------------------------------------------------------
# Patchable seams.
#
# The full and short-horizon imports are deferred to the un-patched
# code path so importing this module does NOT pull yfinance / FastAPI /
# price_cache transitively.  Tests patch BOTH seams, so the underlying
# imports never fire under unit test.
# ---------------------------------------------------------------------------


def _run_full_repaired_cohort(
    *,
    backup_path:        str | None,
    high_priority_csv:  str | None,
    medium_csv:         str | None,
    db_path:            str | None,
    limit:              int,
) -> dict[str, Any]:
    """Invoke the existing full (1d/5d/20d) repaired-cohort runner.

    Tests patch this seam — production calls
    :func:`scripts.manual_repaired_cohort_validation_run.run_manual_repaired_cohort_validation`.
    """
    from scripts.manual_repaired_cohort_validation_run import (
        run_manual_repaired_cohort_validation,
    )
    return run_manual_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=limit,
    )


def _run_short_horizon_validation_on_temp_db(
    *, db_path: str | None, limit: int,
) -> dict[str, Any]:
    """Invoke the read-only short-horizon archive validation runner
    against ``db_path`` and return its payload enriched with a parallel
    ``records`` list the wrapper consumes for filtering / aggregation.

    The underlying short-horizon runner emits ``examples`` (slimmed,
    capped at its own ``--limit``).  Its examples carry neither
    ``mechanism_family`` nor ``statistically_significant``.  Mirror the
    pattern used by the full repaired-cohort runner's
    ``_run_validation_on_temp_db``:

    * pass ``limit = 10**9`` so EVERY (event, horizon) record lands in
      ``examples`` (no truncation);
    * look up ``mechanism_family`` from the temp DB events table;
    * re-derive ``statistically_significant`` from ``fdr_q`` and the
      pipeline's default alpha.

    Tests patch this seam directly, so the enrichment runs only on the
    un-patched path.
    """
    from scripts.archive_stat_validation_short_horizon_run import (
        run_archive_short_horizon_stat_validation,
    )
    from scripts.manual_repaired_cohort_validation_run import (
        _mechanism_family_by_event_id,
    )
    from stats.stat_validation import (
        DEFAULT_ALPHA, is_statistically_significant,
    )

    payload = run_archive_short_horizon_stat_validation(
        db_path=db_path, limit=10**9,
    )
    examples = payload.get("examples") or []
    family_by_id = _mechanism_family_by_event_id(db_path)

    records: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        ev_id = ex.get("event_id")
        records.append({
            "event_id":         ev_id,
            "headline":         ex.get("headline"),
            "primary_ticker":   ex.get("primary_ticker") or ex.get("ticker"),
            "benchmark":        ex.get("benchmark") or _BENCHMARK_TICKER,
            "mechanism_family": (
                family_by_id.get(ev_id) if isinstance(ev_id, int) else None
            ),
            "horizon":          ex.get("horizon"),
            "abnormal_return":  ex.get("abnormal_return"),
            "sar":              ex.get("sar"),
            "ci_low":           ex.get("ci_low"),
            "ci_high":          ex.get("ci_high"),
            "p_value":          ex.get("p_value"),
            "fdr_q":            ex.get("fdr_q"),
            "interpretation":   ex.get("interpretation"),
            "statistically_significant": is_statistically_significant(
                ex.get("fdr_q"), alpha=DEFAULT_ALPHA,
            ),
        })

    enriched = dict(payload)
    enriched["records"] = records
    return enriched


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_manual_repaired_cohort_short_horizon_validation(
    *,
    backup_path:        str | None     = None,
    high_priority_csv:  str | None     = None,
    medium_csv:         str | None     = None,
    db_path:            str | None     = None,
    limit:              int            = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the short-horizon (1d / 5d) validation on the same repaired
    cohort the full repaired-cohort runner produced.  Returns the
    16-key payload described in the module docstring.
    """
    capped_limit = max(int(limit), 0)

    # Pass a high inner limit to the full run so its `examples` are not
    # truncated — this wrapper consumes the full payload structurally
    # (event_id set for the comparison block), not visually.  The user-
    # supplied `--limit` still caps the SHORT-horizon `examples` this
    # wrapper emits.  Without this, cohorts of >limit/3 events would
    # silently undercount full's evaluated set in
    # ``events_in_short_only`` / ``events_in_full_only``.
    full = _run_full_repaired_cohort(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=10**9,
    )
    full = full if isinstance(full, dict) else {}

    full_warnings = list(full.get("warnings") or [])
    full_errors   = list(full.get("errors")   or [])

    repaired_ids   = _ids_from_payload(full.get("repaired_clean_event_ids"))
    repaired_set   = set(repaired_ids)
    full_events_ev = _safe_int(full.get("events_evaluated"))
    full_records_c = _safe_int(full.get("records_count"))
    full_signif_c  = _safe_int(full.get("significant_count"))
    full_event_ids_evaluated = _full_evaluated_event_ids(full)

    excluded_ids       = _ids_from_payload(full.get("excluded_event_ids"))
    remaining_blockers = full.get("remaining_blockers") or {}
    if not isinstance(remaining_blockers, dict):
        remaining_blockers = {}

    live_unchanged   = bool(full.get("live_db_unchanged",      True))
    backup_unchanged = bool(full.get("input_backup_unchanged", True))

    errors:   list[str] = list(full_errors)
    warnings: list[str] = list(full_warnings)

    # Fail-closed precedence: full run failed → propagate.
    if not bool(full.get("ok", False)):
        return _build_envelope(
            ok=False, repaired_clean_event_ids=repaired_ids,
            events_evaluated=0, records_count=0, significant_count=0,
            top_abs_sar=_empty_top_abs_sar(),
            by_horizon={}, by_mechanism_family={}, examples=[],
            excluded_event_ids=excluded_ids,
            remaining_blockers=remaining_blockers,
            comparison=_comparison_block(
                full_events_evaluated=full_events_ev,
                full_records_count=full_records_c,
                full_significant_count=full_signif_c,
                short_events_evaluated=0, short_records_count=0,
                short_significant_count=0,
                full_event_ids=full_event_ids_evaluated,
                short_event_ids=set(),
            ),
            live_db_unchanged=live_unchanged,
            input_backup_unchanged=backup_unchanged,
            errors=errors, warnings=warnings,
        )

    # Extract the temp DB path from the leaked warning.
    temp_db_path = _extract_temp_db_path(full_warnings)
    if not temp_db_path:
        errors.append(
            "Could not extract temp DB path from full repaired-cohort "
            "run warnings — short-horizon validation cannot proceed"
        )
        return _build_envelope(
            ok=False, repaired_clean_event_ids=repaired_ids,
            events_evaluated=0, records_count=0, significant_count=0,
            top_abs_sar=_empty_top_abs_sar(),
            by_horizon={}, by_mechanism_family={}, examples=[],
            excluded_event_ids=excluded_ids,
            remaining_blockers=remaining_blockers,
            comparison=_comparison_block(
                full_events_evaluated=full_events_ev,
                full_records_count=full_records_c,
                full_significant_count=full_signif_c,
                short_events_evaluated=0, short_records_count=0,
                short_significant_count=0,
                full_event_ids=full_event_ids_evaluated,
                short_event_ids=set(),
            ),
            live_db_unchanged=live_unchanged,
            input_backup_unchanged=backup_unchanged,
            errors=errors, warnings=warnings,
        )

    # Run short-horizon validation against the SAME temp DB.
    try:
        short = _run_short_horizon_validation_on_temp_db(
            db_path=temp_db_path, limit=capped_limit,
        )
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"Short-horizon validation failed: {e}")
        return _build_envelope(
            ok=False, repaired_clean_event_ids=repaired_ids,
            events_evaluated=0, records_count=0, significant_count=0,
            top_abs_sar=_empty_top_abs_sar(),
            by_horizon={}, by_mechanism_family={}, examples=[],
            excluded_event_ids=excluded_ids,
            remaining_blockers=remaining_blockers,
            comparison=_comparison_block(
                full_events_evaluated=full_events_ev,
                full_records_count=full_records_c,
                full_significant_count=full_signif_c,
                short_events_evaluated=0, short_records_count=0,
                short_significant_count=0,
                full_event_ids=full_event_ids_evaluated,
                short_event_ids=set(),
            ),
            live_db_unchanged=live_unchanged,
            input_backup_unchanged=backup_unchanged,
            errors=errors, warnings=warnings,
        )
    short = short if isinstance(short, dict) else {}

    # Surface short-horizon errors so the operator sees them.
    for e in short.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(f"short-horizon: {e}")

    short_records_all = list(short.get("records") or [])

    # Drop any defensive horizon-not-in-{1,5} record AND filter to the
    # repaired cohort.
    repaired_records: list[dict[str, Any]] = []
    short_event_ids: set[int] = set()
    for rec in short_records_all:
        if not isinstance(rec, dict):
            continue
        ev_id = rec.get("event_id")
        if not isinstance(ev_id, int):
            continue
        h = rec.get("horizon")
        if h not in _SHORT_HORIZONS:
            continue
        if ev_id not in repaired_set:
            continue
        repaired_records.append(rec)
        short_event_ids.add(ev_id)

    # ---- Aggregations -----------------------------------------------------
    events_evaluated  = len(short_event_ids)
    records_count     = len(repaired_records)
    significant_count = sum(
        1 for r in repaired_records
        if r.get("statistically_significant")
    )

    by_horizon = _aggregate_by_horizon(repaired_records)
    by_mechanism_family = _aggregate_by_mechanism_family(repaired_records)
    top_abs_sar = _compute_top_abs_sar(repaired_records)

    # ---- Examples (capped) ------------------------------------------------
    sorted_records = sorted(
        repaired_records,
        key=lambda r: (
            _safe_int(r.get("event_id")), _safe_int(r.get("horizon")),
        ),
    )
    examples: list[dict[str, Any]] = []
    for rec in sorted_records[:capped_limit]:
        examples.append({
            "event_id":         rec.get("event_id"),
            "headline":         rec.get("headline"),
            "primary_ticker":   rec.get("primary_ticker"),
            "benchmark":        rec.get("benchmark") or _BENCHMARK_TICKER,
            "mechanism_family": rec.get("mechanism_family"),
            "horizon":          rec.get("horizon"),
            "abnormal_return":  rec.get("abnormal_return"),
            "sar":              rec.get("sar"),
            "ci_low":           rec.get("ci_low"),
            "ci_high":          rec.get("ci_high"),
            "p_value":          rec.get("p_value"),
            "fdr_q":            rec.get("fdr_q"),
            "interpretation":   rec.get("interpretation"),
        })

    comparison = _comparison_block(
        full_events_evaluated=full_events_ev,
        full_records_count=full_records_c,
        full_significant_count=full_signif_c,
        short_events_evaluated=events_evaluated,
        short_records_count=records_count,
        short_significant_count=significant_count,
        full_event_ids=full_event_ids_evaluated,
        short_event_ids=short_event_ids,
    )

    return _build_envelope(
        ok=not errors,
        repaired_clean_event_ids=repaired_ids,
        events_evaluated=events_evaluated,
        records_count=records_count,
        significant_count=significant_count,
        top_abs_sar=top_abs_sar,
        by_horizon=by_horizon,
        by_mechanism_family=by_mechanism_family,
        examples=examples,
        excluded_event_ids=excluded_ids,
        remaining_blockers=remaining_blockers,
        comparison=comparison,
        live_db_unchanged=live_unchanged,
        input_backup_unchanged=backup_unchanged,
        errors=errors, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Helpers — pure
# ---------------------------------------------------------------------------


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _ids_from_payload(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        if isinstance(v, int) and not isinstance(v, bool):
            out.append(v)
    return out


def _full_evaluated_event_ids(full: dict[str, Any]) -> set[int]:
    """Best-effort extraction of the events the full run evaluated.

    The full repaired-cohort runner doesn't emit a parallel
    ``records`` list; its ``examples`` carry the per-(event, horizon)
    rows.  We treat the union of example event_ids as "events evaluated
    by full run".  When that's empty (e.g. zero records), fall back to
    the empty set; the comparison block will reflect that honestly.
    """
    out: set[int] = set()
    examples = full.get("examples")
    if isinstance(examples, list):
        for ex in examples:
            if not isinstance(ex, dict):
                continue
            ev_id = ex.get("event_id")
            if isinstance(ev_id, int) and not isinstance(ev_id, bool):
                out.add(ev_id)
    return out


def _extract_temp_db_path(warnings: list[str]) -> str | None:
    """Scan warnings for the leaked ``Temp copy at <path>`` line; take
    the LAST match so a stale message from an earlier run can't pin
    the wrong file.  Strip surrounding whitespace.  Return None if no
    match.
    """
    last: str | None = None
    for w in warnings:
        if not isinstance(w, str):
            continue
        idx = w.find(_TEMP_COPY_PREFIX)
        if idx < 0:
            continue
        candidate = w[idx + len(_TEMP_COPY_PREFIX):].strip()
        if candidate:
            last = candidate
    return last


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, int]] = {}
    for rec in records:
        h = rec.get("horizon")
        if h not in _SHORT_HORIZONS:
            continue
        block = out.setdefault(str(h), {
            "records_count":     0,
            "significant_count": 0,
        })
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, int]] = {}
    seen_events: dict[str, set[int]] = {}
    for rec in records:
        family = rec.get("mechanism_family")
        if not isinstance(family, str) or not family:
            continue
        block = out.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        ev_id = rec.get("event_id")
        if isinstance(ev_id, int):
            seen = seen_events.setdefault(family, set())
            if ev_id not in seen:
                seen.add(ev_id)
                block["events_evaluated"] += 1
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _empty_top_abs_sar() -> dict[str, Any]:
    return {
        "event_id":                  None,
        "primary_ticker":            None,
        "horizon":                   None,
        "sar":                       None,
        "abs_sar":                   None,
        "p_value":                   None,
        "fdr_q":                     None,
        "interpretation":            None,
        "statistically_significant": None,
    }


def _compute_top_abs_sar(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the record with the largest finite ``|SAR|`` observed in
    the repaired cohort.  Conservative wording: this is the largest
    absolute SAR observed — never framed as a top performer or a
    tradable signal.  All-None on empty / all-None inputs.
    """
    best: dict[str, Any] | None = None
    best_abs: float = -1.0
    for rec in records:
        sar = rec.get("sar")
        if not isinstance(sar, (int, float)):
            continue
        sar_f = float(sar)
        if not math.isfinite(sar_f):
            continue
        abs_v = abs(sar_f)
        if abs_v > best_abs:
            best_abs = abs_v
            best = rec
    if best is None:
        return _empty_top_abs_sar()
    sar_val = best.get("sar")
    sar_f = float(sar_val) if isinstance(sar_val, (int, float)) else None
    return {
        "event_id":                  best.get("event_id"),
        "primary_ticker":            best.get("primary_ticker"),
        "horizon":                   best.get("horizon"),
        "sar":                       sar_f,
        "abs_sar":                   abs(sar_f) if sar_f is not None else None,
        "p_value":                   best.get("p_value"),
        "fdr_q":                     best.get("fdr_q"),
        "interpretation":            best.get("interpretation"),
        "statistically_significant": best.get("statistically_significant"),
    }


def _comparison_block(
    *,
    full_events_evaluated:    int,
    full_records_count:       int,
    full_significant_count:   int,
    short_events_evaluated:   int,
    short_records_count:      int,
    short_significant_count:  int,
    full_event_ids:           set[int],
    short_event_ids:          set[int],
) -> dict[str, Any]:
    return {
        "full_events_evaluated":   full_events_evaluated,
        "full_records_count":      full_records_count,
        "full_significant_count":  full_significant_count,
        "full_horizons":           list(_FULL_HORIZONS),
        "short_horizons":          list(_SHORT_HORIZONS),
        "events_evaluated_delta":  short_events_evaluated  - full_events_evaluated,
        "records_count_delta":     short_records_count     - full_records_count,
        "significant_count_delta": short_significant_count - full_significant_count,
        "events_in_full_only":     sorted(full_event_ids - short_event_ids),
        "events_in_short_only":    sorted(short_event_ids - full_event_ids),
    }


def _build_envelope(
    *,
    ok:                       bool,
    repaired_clean_event_ids: list[int],
    events_evaluated:         int,
    records_count:            int,
    significant_count:        int,
    top_abs_sar:              dict[str, Any],
    by_horizon:               dict[str, Any],
    by_mechanism_family:      dict[str, Any],
    examples:                 list[dict[str, Any]],
    excluded_event_ids:       list[int],
    remaining_blockers:       dict[str, Any],
    comparison:               dict[str, Any],
    live_db_unchanged:        bool,
    input_backup_unchanged:   bool,
    errors:                   list[str],
    warnings:                 list[str],
) -> dict[str, Any]:
    return {
        "ok":                              ok,
        "repaired_clean_event_ids":        repaired_clean_event_ids,
        "events_evaluated":                events_evaluated,
        "records_count":                   records_count,
        "significant_count":               significant_count,
        "top_abs_sar":                     top_abs_sar,
        "by_horizon":                      by_horizon,
        "by_mechanism_family":             by_mechanism_family,
        "examples":                        examples,
        "excluded_event_ids":              excluded_event_ids,
        "remaining_blockers":              remaining_blockers,
        "comparison_to_full_repaired_run": comparison,
        "live_db_unchanged":               live_db_unchanged,
        "input_backup_unchanged":          input_backup_unchanged,
        "errors":                          errors,
        "warnings":                        warnings,
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
    lines: list[str] = [
        "Manual repaired cohort short-horizon (1d/5d) validation run", "",
    ]
    lines.append(f"OK:                         {report['ok']}")
    lines.append(
        f"Repaired clean event_ids:   "
        f"{report['repaired_clean_event_ids']}"
    )
    lines.append(f"Events evaluated:           {report['events_evaluated']}")
    lines.append(f"Records count:              {report['records_count']}")
    lines.append(f"Significant count:          {report['significant_count']}")
    lines.append(
        f"Excluded event_ids:         {report['excluded_event_ids']}"
    )
    lines.append(
        f"Live DB unchanged:          {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:     {report['input_backup_unchanged']}"
    )

    top = report.get("top_abs_sar") or {}
    if top.get("event_id") is not None:
        lines.append("")
        lines.append("Largest absolute SAR observed in repaired cohort:")
        lines.append(
            f"  id={top.get('event_id')} h={_fmt(top.get('horizon'))} "
            f"{top.get('primary_ticker') or '-'} "
            f"SAR={_fmt(top.get('sar'))} "
            f"|SAR|={_fmt(top.get('abs_sar'))} "
            f"p={_fmt(top.get('p_value'))} "
            f"fdr_q={_fmt(top.get('fdr_q'))} "
            f"interp={top.get('interpretation')}"
        )

    by_h = report.get("by_horizon") or {}
    if by_h:
        lines.append("")
        lines.append("Per horizon (1d / 5d):")
        for h_key in sorted(by_h.keys(), key=lambda x: int(x)):
            block = by_h[h_key]
            lines.append(
                f"  h={h_key:>3}  records={block.get('records_count', 0):>4} "
                f"significant={block.get('significant_count', 0):>4}"
            )

    fam_block = report.get("by_mechanism_family") or {}
    if fam_block:
        lines.append("")
        lines.append("Per mechanism_family (1d / 5d):")
        for family in sorted(fam_block.keys()):
            stats = fam_block[family]
            lines.append(
                f"  {family:<30} events={stats.get('events_evaluated', 0):>3} "
                f"records={stats.get('records_count', 0):>4} "
                f"significant={stats.get('significant_count', 0):>4}"
            )

    cmp = report.get("comparison_to_full_repaired_run") or {}
    if cmp:
        lines.append("")
        lines.append("Comparison to full (1d / 5d / 20d) repaired run:")
        lines.append(
            f"  full:  events={cmp.get('full_events_evaluated', 0):>3} "
            f"records={cmp.get('full_records_count', 0):>4} "
            f"significant={cmp.get('full_significant_count', 0):>4}"
        )
        lines.append(
            f"  delta (short - full): "
            f"events={cmp.get('events_evaluated_delta', 0):>+3} "
            f"records={cmp.get('records_count_delta', 0):>+4} "
            f"significant={cmp.get('significant_count_delta', 0):>+4}"
        )
        if cmp.get("events_in_full_only"):
            lines.append(
                f"  events_in_full_only:  {cmp['events_in_full_only']}"
            )
        if cmp.get("events_in_short_only"):
            lines.append(
                f"  events_in_short_only: {cmp['events_in_short_only']}"
            )

    examples = report.get("examples") or []
    if examples:
        lines.append("")
        lines.append(f"Examples ({len(examples)}):")
        for ex in examples:
            headline = (ex.get("headline") or "").strip() or "-"
            if len(headline) > 70:
                headline = headline[:67] + "..."
            lines.append(
                f"  id={ex.get('event_id')} h={_fmt(ex.get('horizon'))} "
                f"{ex.get('primary_ticker') or '-'}/{ex.get('benchmark') or '-'} "
                f"family={ex.get('mechanism_family') or '-'} "
                f"AR={_fmt(ex.get('abnormal_return'))} "
                f"SAR={_fmt(ex.get('sar'))} "
                f"CI=[{_fmt(ex.get('ci_low'))}, {_fmt(ex.get('ci_high'))}] "
                f"p={_fmt(ex.get('p_value'))} fdr_q={_fmt(ex.get('fdr_q'))} "
                f"interp={ex.get('interpretation')}"
            )
            lines.append(f"      headline: {headline}")

    if report.get("remaining_blockers"):
        lines.append("")
        lines.append("Remaining blockers:")
        for ev_id_str, flags in sorted(report["remaining_blockers"].items()):
            lines.append(f"  id={ev_id_str}  flags={flags}")

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
            "Repaired-cohort short-horizon (1d / 5d) statistical "
            "validation runner.  Wraps the existing full repaired-"
            "cohort runner and the existing short-horizon archive "
            "validation runner.  Live DB and input backup are byte-"
            "identical before and after the run.  Conservative "
            "language only — short-horizon statistical evidence on "
            "the repaired cohort, not proof, not causal."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None, required=False,
        help="Path to a backup of the events DB.  Required.",
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv",
        default=None, required=False,
        help=(
            "Path to the high-priority manual ticker repair CSV "
            "(``manual_ticker_repair_high_priority.csv``)."
        ),
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None, required=False,
        help=(
            "Path to the medium-batch manual ticker repair CSV "
            "(``manual_ticker_repair_medium_production_like.csv``)."
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
            f"Cap the surfaced examples list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect every "
            f"evaluated repaired event."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_manual_repaired_cohort_short_horizon_validation(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        db_path=args.db_path,
        limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
