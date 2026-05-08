#!/usr/bin/env python3
"""Read-only statistical benchmark-cache gap report.

Walks the events archive once and surfaces, per event whose
benchmark-proxy readiness check is failing, *how short* the SPY
price cache is relative to the 20-business-day forward horizon the
event-study engine needs.

This is the operator follow-up to
:mod:`scripts.stat_validation_blocker_report`'s
``missing_benchmark_proxy`` count.  The blocker report tells you
*how many* events are blocked; this report tells you, for each
blocked event, the target date the cache is missing, the latest
date the cache currently holds for SPY, and the calendar-day gap
between the two — i.e., the size of the cache top-up.

A row is included in ``rows`` iff the event is a
``missing_benchmark_proxy`` blocker, defined exactly as in
:mod:`scripts.stat_validation_readiness_report`: the price cache
holds no SPY row with ``date >= event_date + 20 business days``.
The three degraded paths are honoured explicitly:

  * Event with no parsable ``event_date`` — target_20d cannot be
    computed and the readiness check returns ``False``.  The row
    appears with ``benchmark_target_20d_date=None`` and
    ``gap_days=None``.
  * SPY has no rows in the cache at all — every event with an
    event_date is blocked.  The rows appear with
    ``benchmark_cache_max_date=None`` and ``gap_days=None``.
  * SPY's latest cached date is strictly before target_20d — row
    is included with ``gap_days = (target_20d -
    benchmark_cache_max_date).days`` (calendar days, not business
    days, so the figure reads as "this many more days of data must
    be fetched to clear the blocker").

Events whose SPY cache already covers ``event_date + 20bd`` are
NOT blockers and do NOT appear in ``rows``.  The boundary case
(SPY max date exactly equal to target_20d) is treated as covered,
matching the readiness check's ``>=`` semantics.

Output contract::

    {
      "total_events":                    int,
      "events_missing_benchmark_proxy":  int,
      "benchmark_symbol":                str,    # "SPY"
      "rows": [                          # capped at --limit, id asc
        {
          "event_id":                  int,
          "event_date":                str | None,
          "primary_ticker":            str | None,
          "benchmark_symbol":          str,
          "benchmark_target_20d_date": str | None,
          "benchmark_cache_max_date":  str | None,
          "gap_days":                  int | None,
        },
        ...
      ],
      "recommended_next_action": str,
    }

``benchmark_cache_max_date`` is a single global max over every SPY
row in the cache — it does not vary per event.  It is repeated on
each row so the JSON consumer can join target ↔ max ↔ gap on a
single line without an extra lookup.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No event-study compute — this report only measures *cache
  shortfall*, not abnormal returns.
* Benchmark symbol is not configurable via CLI — the readiness
  report itself hardcodes ``SPY`` as ``_BENCHMARK_TICKER`` and the
  gap report imports the same constant so the two surfaces stay
  aligned automatically.

Usage::

    python scripts/stat_validation_benchmark_gap_report.py
    python scripts/stat_validation_benchmark_gap_report.py --json
    python scripts/stat_validation_benchmark_gap_report.py --json --limit 20
    python scripts/stat_validation_benchmark_gap_report.py --db-path ./events.db --json
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

# Reuse the readiness report's benchmark constant + ISO/business-day
# helpers so the two surfaces share a single source of truth.  If
# readiness ever changes its benchmark assumption or its business-day
# calendar, this report follows automatically — no silent drift.
from scripts.stat_validation_readiness_report import (  # noqa: E402
    _BENCHMARK_TICKER,
    _business_day_offset,
    _parse_iso_date,
    _primary_ticker,
)


_DEFAULT_LIMIT:        int = 25
_BENCHMARK_HORIZON_BD: int = 20


_RECOMMENDED_NO_EVENTS = (
    "Archive is empty — no events to validate.  Seed events before "
    "running benchmark-cache gap diagnostics."
)
_RECOMMENDED_OK = (
    f"Every event has a {_BENCHMARK_TICKER} cache row at or after the "
    f"20-business-day forward horizon.  No benchmark-cache gap to "
    f"close."
)
_RECOMMENDED_GAPS = (
    f"Some events lack {_BENCHMARK_TICKER} cache coverage at the "
    f"20-business-day forward horizon.  Refresh the price cache for "
    f"{_BENCHMARK_TICKER} through the latest "
    f"benchmark_target_20d_date listed below, then re-run."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_benchmark_gaps(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the benchmark-cache gap report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Cap the surfaced ``rows`` list at N entries.  The aggregate
        ``events_missing_benchmark_proxy`` count always reflects every
        blocked event in the archive — only the listed sample is
        truncated.  Negative values clamp to ``0``.
    """
    capped_limit = max(int(limit), 0)
    empty: dict[str, Any] = _empty_report()

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty

    try:
        try:
            event_rows = conn.execute(
                "SELECT id, event_date, market_tickers FROM events "
                "ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []

        try:
            benchmark_dates = [
                d for (d,) in conn.execute(
                    "SELECT date FROM price_cache "
                    "WHERE ticker = ? "
                    "  AND date IS NOT NULL AND date != ''",
                    (_BENCHMARK_TICKER,),
                ).fetchall()
                if isinstance(d, str) and d
            ]
        except sqlite3.Error:
            benchmark_dates = []
    finally:
        conn.close()

    # Single global max — same across every event.  ISO ``YYYY-MM-DD``
    # strings sort lexicographically the same as chronologically, so
    # ``max(...)`` is the chronological latest.
    benchmark_cache_max_date: str | None = (
        max(benchmark_dates) if benchmark_dates else None
    )

    blocked_rows: list[dict[str, Any]] = []
    total_events = 0
    for raw_id, raw_event_date, raw_market_tickers in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        total_events += 1

        event_date_str = (
            raw_event_date if isinstance(raw_event_date, str) and raw_event_date
            else None
        )
        primary_ticker = _primary_ticker(raw_market_tickers)
        event_d = _parse_iso_date(event_date_str)

        target_iso: str | None
        if event_d is None:
            target_iso = None
        else:
            target_iso = _business_day_offset(
                event_d, _BENCHMARK_HORIZON_BD,
            ).isoformat()

        # Blocker filter: include the event iff the readiness check
        # for this benchmark/event pair would return False.  The check
        # is "any cache date >= target_iso"; if there's no event_date
        # or no SPY rows at all, it can't be satisfied.
        is_blocker = _is_benchmark_proxy_blocker(
            target_iso=target_iso,
            benchmark_dates=benchmark_dates,
        )
        if not is_blocker:
            continue

        gap_days = _gap_days(target_iso, benchmark_cache_max_date)
        blocked_rows.append({
            "event_id":                  event_id,
            "event_date":                event_date_str,
            "primary_ticker":            primary_ticker,
            "benchmark_symbol":          _BENCHMARK_TICKER,
            "benchmark_target_20d_date": target_iso,
            "benchmark_cache_max_date":  benchmark_cache_max_date,
            "gap_days":                  gap_days,
        })

    blocked_count = len(blocked_rows)
    truncated = blocked_rows[:capped_limit]

    return {
        "total_events":                   total_events,
        "events_missing_benchmark_proxy": blocked_count,
        "benchmark_symbol":               _BENCHMARK_TICKER,
        "rows":                           truncated,
        "recommended_next_action":        _recommend(
            total_events=total_events, blocked_count=blocked_count,
        ),
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":                   0,
        "events_missing_benchmark_proxy": 0,
        "benchmark_symbol":               _BENCHMARK_TICKER,
        "rows":                           [],
        "recommended_next_action":        _RECOMMENDED_NO_EVENTS,
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def _is_benchmark_proxy_blocker(
    *, target_iso: str | None, benchmark_dates: Sequence[str],
) -> bool:
    """True iff the readiness benchmark check would fail.

    Mirrors :func:`scripts.stat_validation_readiness_report._has_forward_cache_row`
    for the SPY/20bd pair.  The three failure paths collapse cleanly:

      * ``target_iso is None`` (no event_date)  → blocker.
      * empty cache for SPY                      → blocker.
      * every cache date strictly before target  → blocker.
    """
    if target_iso is None:
        return True
    if not benchmark_dates:
        return True
    return not any(d >= target_iso for d in benchmark_dates)


def _gap_days(
    target_iso: str | None, benchmark_cache_max_date: str | None,
) -> int | None:
    """Return ``(target - max).days`` (calendar days) or ``None``.

    Both inputs must be ISO ``YYYY-MM-DD`` strings.  Returns ``None``
    when either side is missing — the operator still sees the row
    (event is blocked) but the numeric gap is undefined.
    """
    if target_iso is None or benchmark_cache_max_date is None:
        return None
    target_d = _parse_iso_date(target_iso)
    max_d = _parse_iso_date(benchmark_cache_max_date)
    if target_d is None or max_d is None:
        return None
    return (target_d - max_d).days


def _recommend(*, total_events: int, blocked_count: int) -> str:
    if total_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if blocked_count == 0:
        return _RECOMMENDED_OK
    return _RECOMMENDED_GAPS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Statistical benchmark-cache gap report", ""]
    lines.append(
        f"Benchmark symbol:                "
        f"{report['benchmark_symbol']}"
    )
    lines.append(
        f"Total events:                    "
        f"{report['total_events']}"
    )
    lines.append(
        f"  missing benchmark proxy (20d): "
        f"{report['events_missing_benchmark_proxy']}"
    )
    lines.append("")

    rows = report.get("rows") or []
    lines.append(f"Rows listed ({len(rows)}):")
    if rows:
        for entry in rows:
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"target_20d={entry.get('benchmark_target_20d_date') or '-'} "
                f"cache_max={entry.get('benchmark_cache_max_date') or '-'} "
                f"gap_days={entry.get('gap_days') if entry.get('gap_days') is not None else '-'}"
            )
    else:
        lines.append("  -")
    lines.append("")
    lines.append(
        f"Recommended next action: {report['recommended_next_action']}"
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only statistical benchmark-cache gap report.  For "
            "every event whose readiness check flags a missing "
            "benchmark proxy, surfaces the 20bd target date, the "
            "latest cached SPY date, and the calendar-day gap.  "
            "Read-only: no INSERT/UPDATE/DELETE, no provider, no "
            "LLM, no FastAPI surface."
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
            f"Cap the surfaced ``rows`` list at N entries (default "
            f"{_DEFAULT_LIMIT}).  The aggregate count always reflects "
            f"every blocked event."
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

    report = summarize_benchmark_gaps(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
