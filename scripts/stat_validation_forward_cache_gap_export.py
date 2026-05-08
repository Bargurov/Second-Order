#!/usr/bin/env python3
"""Read-only export of statistical-readiness 20d forward-cache gaps.

One row per (event, primary_ticker) pair whose forward price-cache
window does not yet reach ``event_date + 20 business days``.  This is
the export-shaped drilldown for the ``missing_forward_cache_20d``
blocker surfaced by :mod:`scripts.stat_validation_readiness_report`.

Two blocker reasons are surfaced::

    ticker_cache_missing      no price_cache rows for the primary
                              ticker at all (max date undefined).
    ticker_cache_window_gap   price_cache rows exist but the latest
                              cached date is strictly before the 20-
                              business-day horizon.

Output fields (CSV header order, JSON ``fields`` order)::

    event_id, event_date, primary_ticker,
    horizon, target_date,
    ticker_cache_max_date,
    benchmark, benchmark_cache_max_date,
    blocker_reason

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT / UPDATE
  / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Events without a parseable ``event_date`` or without a primary
  ticker are dropped: the export's purpose is "what 20d gaps could a
  refresh close" — without those two anchors there is nothing
  actionable to surface.  The companion
  :mod:`scripts.stat_validation_blocker_report` covers the broader
  ``missing_forward_cache_20d`` count which includes those events.

Usage::

    python scripts/stat_validation_forward_cache_gap_export.py
    python scripts/stat_validation_forward_cache_gap_export.py --json
    python scripts/stat_validation_forward_cache_gap_export.py --json --limit 20
    python scripts/stat_validation_forward_cache_gap_export.py --csv  --limit 50
    python scripts/stat_validation_forward_cache_gap_export.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Reuse the readiness report's pure helpers so the business-day
# calendar, ticker parser, and ISO date parser stay in lockstep
# between the readiness check and this export.  These are pure
# functions — no SQLite open, no project DB import, no provider seam.
from scripts.stat_validation_readiness_report import (  # noqa: E402
    _business_day_offset,
    _parse_iso_date,
    _primary_ticker,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_DEFAULT_LIMIT       = 100
_HORIZON_BDAYS:  int = 20
_BENCHMARK:      str = "SPY"

_REASON_TICKER_MISSING:    str = "ticker_cache_missing"
_REASON_TICKER_WINDOW_GAP: str = "ticker_cache_window_gap"

_VALID_BLOCKER_REASONS: tuple[str, ...] = (
    _REASON_TICKER_MISSING,
    _REASON_TICKER_WINDOW_GAP,
)

# Field order pinned by the task brief.  CSV header and JSON ``fields``
# both use this tuple; adding a new field = one entry here + one
# population line in :func:`_load_export_rows`.
_FIELD_NAMES: tuple[str, ...] = (
    "event_id",
    "event_date",
    "primary_ticker",
    "horizon",
    "target_date",
    "ticker_cache_max_date",
    "benchmark",
    "benchmark_cache_max_date",
    "blocker_reason",
)


# ---------------------------------------------------------------------------
# Production seam — read-only SQLite scan.  Tests patch this attribute
# directly to inject synthetic rows; the patched-seam path never opens
# SQLite.
# ---------------------------------------------------------------------------


def _load_export_rows(*, db_path: str | None = None) -> list[dict]:
    """Return one export row per (event, primary_ticker) pair whose
    20bd forward-cache window does not reach the horizon.

    Pure read.  Resolves the DB path the same way the readiness
    report does — the explicit ``db_path`` arg wins, else
    ``db.DB_FILE``.  Issues exactly two SELECTs (events scan +
    per-ticker MAX(date) group-by) and closes the connection cleanly.
    Returns ``[]`` on a missing or unreadable archive instead of
    raising, matching the readiness report's degraded-input contract.
    """
    path = _resolve_db_path(db_path)
    if path is None:
        return []

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return []

    try:
        try:
            event_rows = conn.execute(
                "SELECT id, event_date, market_tickers "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []

        try:
            cache_max_rows = conn.execute(
                "SELECT ticker, MAX(date) FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date   IS NOT NULL AND date   != '' "
                "GROUP BY ticker"
            ).fetchall()
        except sqlite3.Error:
            cache_max_rows = []
    finally:
        conn.close()

    cache_max_by_ticker: dict[str, str] = {}
    for ticker, max_d in cache_max_rows:
        if not isinstance(ticker, str) or not isinstance(max_d, str):
            continue
        if not ticker or not max_d:
            continue
        cache_max_by_ticker[ticker.upper()] = max_d[:10]

    benchmark_max = cache_max_by_ticker.get(_BENCHMARK)

    out: list[dict] = []
    for raw_id, raw_event_date, raw_market_tickers in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        event_d = _parse_iso_date(raw_event_date)
        if event_d is None:
            continue

        primary = _primary_ticker(raw_market_tickers)
        if primary is None:
            continue

        target = _business_day_offset(event_d, _HORIZON_BDAYS)
        target_iso = target.isoformat()
        ticker_max = cache_max_by_ticker.get(primary.upper())

        if ticker_max is None:
            reason = _REASON_TICKER_MISSING
        elif ticker_max < target_iso:
            # ISO ``YYYY-MM-DD`` strings sort lexicographically the
            # same as chronological order, so a string compare is
            # exactly the chronological "earlier than" check.
            reason = _REASON_TICKER_WINDOW_GAP
        else:
            # Cache reaches or exceeds the 20bd horizon — this event
            # is NOT a missing_forward_cache_20d blocker.  Skip.
            continue

        out.append({
            "event_id":                 event_id,
            "event_date":               raw_event_date[:10],
            "primary_ticker":           primary,
            "horizon":                  _HORIZON_BDAYS,
            "target_date":              target_iso,
            "ticker_cache_max_date":    ticker_max,
            "benchmark":                _BENCHMARK,
            "benchmark_cache_max_date": benchmark_max,
            "blocker_reason":           reason,
        })

    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    """Mirror the readiness report's resolution rule.

    The explicit ``db_path`` arg wins.  When omitted, resolve via
    ``db.DB_FILE`` so the export follows the project's configured
    archive without importing it eagerly at module top-level.
    """
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Defense-in-depth filter — the seam already restricts to the two
# missing-20d reasons, but a future refactor or a mocked test row could
# slip a different reason through.  Strip those at the export boundary.
# ---------------------------------------------------------------------------


def _filter_to_missing_20d(rows: Sequence[Any]) -> list[dict]:
    return [
        r for r in rows
        if isinstance(r, dict)
        and r.get("blocker_reason") in _VALID_BLOCKER_REASONS
    ]


# ---------------------------------------------------------------------------
# Row normalisation + rendering
# ---------------------------------------------------------------------------


def _normalise_row(row: dict) -> dict:
    """Flatten one seam row to the pinned 9-field export shape.

    Missing keys collapse to ``None`` so the CSV / JSON columns stay
    populated even when an upstream patched seam returns a partial row.
    """
    return {field: row.get(field) for field in _FIELD_NAMES}


def _render_json(rows: Sequence[dict]) -> str:
    payload = {
        "ok":     True,
        "count":  len(rows),
        "fields": list(_FIELD_NAMES),
        "rows":   [_normalise_row(r) for r in rows],
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def _render_csv(rows: Sequence[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=list(_FIELD_NAMES),
        lineterminator="\n",
    )
    writer.writeheader()
    for r in rows:
        writer.writerow(_normalise_row(r))
    # ``print`` adds the trailing newline; rstrip avoids a double newline
    # on the last data row when the renderer is piped through ``print``.
    return buf.getvalue().rstrip("\n")


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only export of statistical-readiness 20d forward-cache "
            "gaps.  One row per (event, primary_ticker) pair whose 20-"
            "business-day forward window is empty or short.  No "
            "INSERT/UPDATE/DELETE, no provider, no LLM, no FastAPI "
            "surface."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--csv",
        action="store_true",
        help="Emit CSV (default).",
    )
    fmt.add_argument(
        "--json",
        action="store_true",
        help="Emit a structured JSON envelope instead of CSV.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Maximum number of rows to emit.  Default: {_DEFAULT_LIMIT}.  "
            "Applied AFTER the missing-20d filter; negative values "
            "clamp to 0."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the export follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    limit = max(int(args.limit), 0)

    raw_rows = _load_export_rows(db_path=args.db_path)
    filtered = _filter_to_missing_20d(raw_rows)
    rows = filtered[:limit]

    if args.json:
        print(_render_json(rows), file=output)
    else:
        print(_render_csv(rows), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
