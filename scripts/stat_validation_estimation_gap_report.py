#!/usr/bin/env python3
"""Read-only drill-in on the ``insufficient_estimation_window`` blocker.

Companion to :mod:`scripts.stat_validation_blocker_report`.  The
blocker report says *which* events are blocked and how many; this
report answers the natural follow-up for the estimation-window
blocker specifically — *how short* is each event's pre-event price
cache, what's the earliest/latest date the cache currently holds,
and how many distinct business-day closes the operator still has to
backfill before that event clears the 60-day estimation window.

Per-event fields (per spec)::

    event_id                       : int
    event_date                     : str  (ISO YYYY-MM-DD)
    primary_ticker                 : str  (uppercased first non-empty
                                            symbol in market_tickers)
    pre_event_cached_days          : int  (distinct cached dates with
                                            d < event_date for ticker)
    required_days                  : 60   (mirrors event_study)
    missing_days                   : int  (max(0, 60 - pre))
    earliest_cache_date            : str | None  (any-direction min)
    latest_pre_event_cache_date    : str | None  (max d < event_date)

Output contract::

    {
      "total_events":          int,   # every row in events
      "events_evaluable":      int,   # have event_date AND primary_ticker
      "events_with_gap":       int,   # of evaluable, pre < 60
      "required_days":         60,
      "events": [...],                # capped at --limit, id asc.
                                      # Only evaluable + gapped events
                                      # appear here.
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.

Usage::

    python scripts/stat_validation_estimation_gap_report.py
    python scripts/stat_validation_estimation_gap_report.py --json
    python scripts/stat_validation_estimation_gap_report.py --json --limit 20
    python scripts/stat_validation_estimation_gap_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25

# Mirrors ``stats.event_study._DEFAULT_ESTIMATION_WINDOW`` — inlined to
# keep the SELECT path's import surface tight (matches the readiness
# and blocker reports' convention).
_REQUIRED_DAYS: int = 60


_RECOMMENDED_NO_EVENTS = (
    "Archive is empty — no events to evaluate."
)
_RECOMMENDED_NO_GAPS = (
    "Every evaluable event in the archive has at least the required "
    f"{_REQUIRED_DAYS} pre-event cached business days for the "
    "estimation window.  No gaps to backfill."
)
_RECOMMENDED_GAPS = (
    "Backfill the price cache for the listed primary tickers so each "
    "carries at least the required pre-event cached days, then re-run "
    "this report."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_estimation_gaps(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the estimation-window gap report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Cap the surfaced ``events`` list at N entries.  Aggregate
        counts always reflect every row in the archive.  Negative
        values clamp to ``0``.
    """
    capped_limit = max(int(limit), 0)
    empty = _empty_report()

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

    total_events = 0
    evaluable    = 0
    gap_entries: list[dict[str, Any]] = []

    for raw_id, raw_event_date, raw_market_tickers in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        total_events += 1

        event_d = _parse_iso_date(raw_event_date)
        primary = _primary_ticker(raw_market_tickers)
        if event_d is None or primary is None:
            continue
        evaluable += 1

        ticker_dates = cache_dates_by_ticker.get(primary, set())
        event_iso = event_d.isoformat()
        pre_dates = sorted(d for d in ticker_dates if d < event_iso)
        pre_count = len(pre_dates)

        if pre_count >= _REQUIRED_DAYS:
            continue  # ready — outside this report's focus

        if ticker_dates:
            earliest_cache_date = min(ticker_dates)
        else:
            earliest_cache_date = None
        latest_pre = pre_dates[-1] if pre_dates else None

        # Surface the canonical event_date string as stored (trim a
        # datetime suffix down to the ISO date so a downstream renderer
        # always sees ``YYYY-MM-DD``, mirroring _parse_iso_date).
        event_date_iso = event_d.isoformat()

        gap_entries.append({
            "event_id":                    event_id,
            "event_date":                  event_date_iso,
            "primary_ticker":              primary,
            "pre_event_cached_days":       pre_count,
            "required_days":               _REQUIRED_DAYS,
            "missing_days":                _missing_days(pre_count),
            "earliest_cache_date":         earliest_cache_date,
            "latest_pre_event_cache_date": latest_pre,
        })

    # Event rows came out of SQL in id-ascending order, so gap_entries
    # is already sorted by event_id.  Cap at the requested limit.
    truncated = gap_entries[:capped_limit]

    return {
        "total_events":            total_events,
        "events_evaluable":        evaluable,
        "events_with_gap":         len(gap_entries),
        "required_days":           _REQUIRED_DAYS,
        "events":                  truncated,
        "recommended_next_action": _recommend(
            total_events=total_events, gap_count=len(gap_entries),
        ),
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":            0,
        "events_evaluable":        0,
        "events_with_gap":         0,
        "required_days":           _REQUIRED_DAYS,
        "events":                  [],
        "recommended_next_action": _RECOMMENDED_NO_EVENTS,
    }


def _missing_days(pre_event_cached_days: int) -> int:
    """Clamp ``required_days - pre_event_cached_days`` at 0."""
    diff = _REQUIRED_DAYS - int(pre_event_cached_days)
    return diff if diff > 0 else 0


def _recommend(*, total_events: int, gap_count: int) -> str:
    if total_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if gap_count == 0:
        return _RECOMMENDED_NO_GAPS
    return _RECOMMENDED_GAPS


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure helpers — duplicated locally (small, isolated) so the SELECT
# path keeps a tight import surface.  Mirrors the readiness report.
# ---------------------------------------------------------------------------


def _group_cache_dates(rows: Sequence[tuple]) -> dict[str, set[str]]:
    """Collect ``{ticker_upper: {iso_date, ...}}`` from raw price_cache rows.

    Both ``auto_adjust`` flags' dates are unioned via ``set`` so the
    same calendar date stored under flag=0 and flag=1 counts once.
    """
    out: dict[str, set[str]] = {}
    for raw_ticker, raw_date in rows:
        if not isinstance(raw_ticker, str) or not raw_ticker:
            continue
        if not isinstance(raw_date, str) or not raw_date:
            continue
        out.setdefault(raw_ticker.upper(), set()).add(raw_date)
    return out


def _parse_iso_date(value: Any) -> _date | None:
    """Return ``date`` for ISO ``YYYY-MM-DD`` strings; else ``None``.

    Accepts datetime-suffixed strings by trimming to the first 10
    characters (matches ``price_cache.read_window_no_fetch`` and the
    readiness report).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _primary_ticker(raw_market_tickers: Any) -> str | None:
    """Return the first non-empty ``symbol`` in the JSON list, or ``None``."""
    if raw_market_tickers is None:
        return None
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if not isinstance(sym, str):
            continue
        sym = sym.strip().upper()
        if sym:
            return sym
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        "Statistical estimation-window gap report",
        "",
    ]
    lines.append(f"Total events:            {report['total_events']}")
    lines.append(f"  evaluable:             {report['events_evaluable']}")
    lines.append(f"  with gap (< {report['required_days']}d):       "
                 f"{report['events_with_gap']}")
    lines.append(f"Required days:           {report['required_days']}")
    lines.append("")

    events = report.get("events") or []
    lines.append(f"Events listed ({len(events)}):")
    if events:
        for entry in events:
            lines.append(
                f"  id={entry['event_id']} "
                f"date={entry['event_date']} "
                f"ticker={entry['primary_ticker']}"
            )
            lines.append(
                f"      pre_event_cached_days:       "
                f"{entry['pre_event_cached_days']}"
            )
            lines.append(
                f"      required_days:               "
                f"{entry['required_days']}"
            )
            lines.append(
                f"      missing_days:                "
                f"{entry['missing_days']}"
            )
            lines.append(
                f"      earliest_cache_date:         "
                f"{entry['earliest_cache_date'] or '-'}"
            )
            lines.append(
                f"      latest_pre_event_cache_date: "
                f"{entry['latest_pre_event_cache_date'] or '-'}"
            )
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
            "Read-only drill-in on the insufficient_estimation_window "
            "blocker.  For each evaluable event whose primary ticker "
            "has fewer than 60 distinct pre-event cached business days "
            "in the price cache, report the gap size plus the cache "
            "boundary dates.  Read-only: no INSERT/UPDATE/DELETE, no "
            "provider call, no LLM, no FastAPI surface."
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
            f"Cap the surfaced events list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every event in the archive."
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

    report = summarize_estimation_gaps(
        db_path=args.db_path, limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
