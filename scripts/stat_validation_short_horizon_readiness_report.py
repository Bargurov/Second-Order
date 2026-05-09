#!/usr/bin/env python3
"""Read-only short-horizon (1d/5d) statistical-readiness coverage report.

Sibling of :mod:`scripts.stat_validation_readiness_report`.  Walks the
events archive once and answers a narrowly-scoped question::

    *If we drop the 20d horizon, how much does the candidate cohort
    expand?*

Each event is checked against a relaxed predicate that requires only
1d and 5d forward cache for the primary ticker, a SPY benchmark row at
**+5 business days** (NOT +20bd, which is what the full report
demands), and the same 60-day pre-event estimation window the full
report uses.  ``ready_1d5d`` is the AND of every check.

``delta_vs_full_ready`` counts the events that pass the short-horizon
predicate but FAIL the full-readiness predicate from
:mod:`scripts.stat_validation_readiness_report` — i.e. the cohort
expansion gained by relaxing the 20d horizon requirement.  Because
``fully_ready`` implies ``ready_1d5d`` once the benchmark horizon is
relaxed, the delta is identical to
``events_ready_1d5d - events_fully_ready``.

Conservative language
---------------------
Events flipped ``ready_1d5d`` are **short-horizon candidates**, not
"validated", "proven", or carriers of statistical evidence.  This
report only measures cache coverage; the event-study compute path
lives in :mod:`scripts.archive_stat_validation_run`.

Output contract::

    {
      "total_events":                          int,
      "events_ready_1d5d":                     int,
      "delta_vs_full_ready":                   int,
      "missing_tickers_count":                 int,
      "missing_benchmark_count":               int,
      "insufficient_estimation_window_count":  int,
      "examples": [                       # capped at --limit, id asc
        {
          "event_id":         int,
          "event_date":       str | None,
          "primary_ticker":   str | None,
          "checks": {
            "has_event_date":               bool,
            "has_market_tickers":           bool,
            "forward_cache_1d":             bool,
            "forward_cache_5d":             bool,
            "benchmark_proxy_available_5d": bool,
            "estimation_window_sufficient": bool,
          },
          "ready_1d5d":      bool,
          "delta_eligible":  bool,   # ready_1d5d but NOT fully_ready
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, no ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No event-study compute — this report only measures *readiness*,
  not the abnormal returns themselves.

Usage::

    python scripts/stat_validation_short_horizon_readiness_report.py
    python scripts/stat_validation_short_horizon_readiness_report.py --json
    python scripts/stat_validation_short_horizon_readiness_report.py --json --limit 50
    python scripts/stat_validation_short_horizon_readiness_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the pure helpers from the full-readiness report so the two
# reports stay aligned by construction (no duplicated business-day
# math, no duplicated cache-row predicates).  All imported names are
# pure functions; none touch the DB or the network.
from scripts.stat_validation_readiness_report import (  # noqa: E402
    _BENCHMARK_TICKER,
    _ESTIMATION_WINDOW,
    _business_day_offset,
    _group_cache_dates,
    _has_estimation_window,
    _has_forward_cache_row,
    _parse_iso_date,
    _primary_ticker,
)

_DEFAULT_LIMIT = 25

# Short-horizon variant: the benchmark check is anchored to +5bd, not
# +20bd.  This is the one place this report's predicate diverges from
# the full report — a reader comparing missing_benchmark_count here
# with events_missing_benchmark_proxy in the full report should
# expect this report's number to be smaller (a row that satisfies
# +5bd may not satisfy +20bd).
_SHORT_HORIZONS:           tuple[int, ...] = (1, 5)
_SHORT_BENCHMARK_HORIZON:  int = max(_SHORT_HORIZONS)  # 5
_FULL_BENCHMARK_HORIZON:   int = 20  # mirrors max() in the full report.


_REC_EMPTY = (
    "Archive is empty; no short-horizon candidates to surface."
)
_REC_NO_READY = (
    "No events meet the short-horizon (1d/5d) candidate predicate.  "
    "Refresh the price cache for the primary tickers and SPY at +5bd, "
    "then re-run."
)
_REC_NO_DELTA = (
    "Dropping the 20d horizon does not expand the short-horizon "
    "candidate cohort relative to the full readiness predicate; the "
    "20d-required cache backfill is not the active blocker."
)
_REC_DELTA_POSITIVE = (
    "Dropping the 20d horizon would add {n} short-horizon candidate "
    "events not currently surfaced by the full readiness predicate.  "
    "Treat them as candidates only — this report measures cache "
    "coverage, not statistical evidence."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_short_horizon_readiness(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the short-horizon readiness coverage report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Maximum number of per-event entries surfaced under
        ``examples``.  The aggregate counts always reflect every event
        in the archive — only the listed examples are truncated.
        Negative values are clamped to ``0``.
    """
    capped_limit = max(int(limit), 0)

    path = _resolve_db_path(db_path)
    if path is None:
        return _empty_report()

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return _empty_report()

    try:
        try:
            event_rows = conn.execute(
                "SELECT id, event_date, market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []

        try:
            cache_rows = conn.execute(
                "SELECT ticker, date FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date IS NOT NULL AND date != ''"
            ).fetchall()
        except sqlite3.Error:
            cache_rows = []
    finally:
        conn.close()

    cache_dates_by_ticker = _group_cache_dates(cache_rows)

    # Per-event compute -------------------------------------------------------
    per_event: list[dict[str, Any]] = []
    for raw_id, raw_event_date, raw_market_tickers in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        event_date_str = raw_event_date if isinstance(raw_event_date, str) else None
        primary_ticker = _primary_ticker(raw_market_tickers)
        event_d = _parse_iso_date(event_date_str)
        has_event_date = event_d is not None
        has_market_tickers = primary_ticker is not None

        forward_1d = _has_forward_cache_row(
            cache_dates_by_ticker, primary_ticker, event_d, 1,
        )
        forward_5d = _has_forward_cache_row(
            cache_dates_by_ticker, primary_ticker, event_d, 5,
        )
        benchmark_5d = _has_forward_cache_row(
            cache_dates_by_ticker, _BENCHMARK_TICKER, event_d,
            _SHORT_BENCHMARK_HORIZON,
        )
        est_ok = _has_estimation_window(
            cache_dates_by_ticker, primary_ticker, event_d,
            window=_ESTIMATION_WINDOW,
        )

        checks = {
            "has_event_date":               has_event_date,
            "has_market_tickers":           has_market_tickers,
            "forward_cache_1d":             forward_1d,
            "forward_cache_5d":             forward_5d,
            "benchmark_proxy_available_5d": benchmark_5d,
            "estimation_window_sufficient": est_ok,
        }
        ready_1d5d = all(checks.values())

        # Delta eligibility — ready_1d5d AND not fully_ready under
        # the full predicate.  The full predicate adds two checks
        # this report intentionally drops: forward_cache_20d for the
        # primary ticker and benchmark_proxy_available at +20bd.  An
        # event passes the short predicate but fails the full one
        # iff it's short-horizon ready AND lacks one of those two
        # 20d-anchored cache rows.
        if ready_1d5d:
            forward_20d = _has_forward_cache_row(
                cache_dates_by_ticker, primary_ticker, event_d, 20,
            )
            benchmark_20d = _has_forward_cache_row(
                cache_dates_by_ticker, _BENCHMARK_TICKER, event_d,
                _FULL_BENCHMARK_HORIZON,
            )
            delta_eligible = not (forward_20d and benchmark_20d)
        else:
            delta_eligible = False

        per_event.append({
            "event_id":       event_id,
            "event_date":     event_date_str if isinstance(event_date_str, str) and event_date_str else None,
            "primary_ticker": primary_ticker,
            "checks":         checks,
            "ready_1d5d":     ready_1d5d,
            "delta_eligible": delta_eligible,
        })

    # Aggregates --------------------------------------------------------------
    total_events = len(per_event)
    n_ready_1d5d        = sum(1 for e in per_event if e["ready_1d5d"])
    n_delta             = sum(1 for e in per_event if e["delta_eligible"])
    n_missing_tickers   = sum(
        1 for e in per_event if not e["checks"]["has_market_tickers"]
    )
    n_missing_benchmark = sum(
        1 for e in per_event if not e["checks"]["benchmark_proxy_available_5d"]
    )
    n_insuff_est        = sum(
        1 for e in per_event if not e["checks"]["estimation_window_sufficient"]
    )

    truncated = per_event[:capped_limit]

    return {
        "total_events":                          total_events,
        "events_ready_1d5d":                     n_ready_1d5d,
        "delta_vs_full_ready":                   n_delta,
        "missing_tickers_count":                 n_missing_tickers,
        "missing_benchmark_count":               n_missing_benchmark,
        "insufficient_estimation_window_count":  n_insuff_est,
        "examples":                              truncated,
        "recommended_next_action":               _recommend(
            total_events=total_events,
            n_ready=n_ready_1d5d,
            n_delta=n_delta,
        ),
    }


def _recommend(*, total_events: int, n_ready: int, n_delta: int) -> str:
    if total_events == 0:
        return _REC_EMPTY
    if n_ready == 0:
        return _REC_NO_READY
    if n_delta == 0:
        return _REC_NO_DELTA
    return _REC_DELTA_POSITIVE.format(n=n_delta)


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":                          0,
        "events_ready_1d5d":                     0,
        "delta_vs_full_ready":                   0,
        "missing_tickers_count":                 0,
        "missing_benchmark_count":               0,
        "insufficient_estimation_window_count":  0,
        "examples":                              [],
        "recommended_next_action":               _REC_EMPTY,
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Archive short-horizon (1d/5d) readiness coverage report",
        "",
    ]
    lines.append(f"Total events:                                  {report['total_events']}")
    lines.append(f"  ready (1d/5d):                               {report['events_ready_1d5d']}")
    lines.append(f"  delta vs. full readiness:                    {report['delta_vs_full_ready']}")
    lines.append(f"  missing tickers:                             {report['missing_tickers_count']}")
    lines.append(f"  missing benchmark ({_BENCHMARK_TICKER} +5bd):                {report['missing_benchmark_count']}")
    lines.append(f"  insufficient estimation window (<{_ESTIMATION_WINDOW}d):       {report['insufficient_estimation_window_count']}")
    lines.append("")

    examples = report["examples"]
    lines.append(f"Examples listed ({len(examples)}):")
    if examples:
        for entry in examples:
            checks = entry.get("checks") or {}
            failed = sorted(k for k, v in checks.items() if v is False)
            failed_str = ", ".join(failed) if failed else "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"ready_1d5d={entry.get('ready_1d5d')} "
                f"delta_eligible={entry.get('delta_eligible')}"
            )
            lines.append(f"      failed_checks: {failed_str}")
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only short-horizon (1d/5d) readiness coverage "
            "report.  Walks the events archive once and counts how "
            "many rows would be candidate-ready if the 20d horizon "
            "requirement were dropped.  Read-only: no INSERT / "
            "UPDATE / DELETE, no provider call, no LLM, no FastAPI "
            "surface."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-event examples list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every event in the archive."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_short_horizon_readiness(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
