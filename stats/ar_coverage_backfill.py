"""V2B — gated exposed-name AR coverage backfill into a DB COPY.

Fetches daily closes for the V2A planner's worklist windows into a COPY of the
archive's ``price_cache``, so the previously-uncomputable exposed-name event
studies become computable.

HARD GATES (enforced here, not by convention):
  * ``confirm_paid=True`` is REQUIRED — without it the function raises before any
    provider call or cache write (V2B Gate 1).
  * the target path may NOT be the live archive (``db.LIVE_DB_FILE``); callers
    must pass a copy. The live archive is never written and never promoted by
    this module (promotion to live is the separate, operator-approved Gate 2).

Mechanics: the executor rebinds ``db.DB_FILE`` to the copy for the duration (so
the existing read-through cache writer targets the copy), then restores it; the
active market-data provider is swappable (tests inject a fake — no network). The
existing ``price_cache._write_rows`` already scrubs non-finite closes to NULL, so
NaN/inf never lands as a finite cache value.

This improves coverage / representativeness only. It makes no statistical-
significance, edge, or directional claim, and it changes no research conclusion.
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Optional

import db as _db


def _count_price_rows(path: str) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]
    except sqlite3.Error:
        return 0
    finally:
        con.close()


def backfill_into_copy(
    copy_path: str,
    windows: list[dict],
    *,
    confirm_paid: bool,
    provider: Optional[Any] = None,
    max_requests: Optional[int] = None,
    auto_adjust_flags: tuple = (False, True),
) -> dict:
    """Backfill ``windows`` (``{symbol, start, end}``) into ``copy_path``'s cache.

    Returns a summary dict: symbols, requests, rows_before/after/written, failures.
    Raises ``PermissionError`` without ``confirm_paid``, ``ValueError`` if asked
    to target the live archive. Never writes the live DB; never promotes.
    """
    if not confirm_paid:
        raise PermissionError(
            "backfill_into_copy requires confirm_paid=True — this is the gated "
            "paid provider/cache-write step (V2B Gate 1)."
        )
    if os.path.realpath(copy_path) == os.path.realpath(_db.LIVE_DB_FILE):
        raise ValueError(
            f"refusing to backfill into the live archive ({copy_path}); pass a DB copy."
        )
    if not os.path.exists(copy_path):
        raise FileNotFoundError(copy_path)

    # Late imports: keep module import side-effect-free and let tests inject a
    # fake provider before the first fetch.
    import market_data
    import price_cache

    rows_before = _count_price_rows(copy_path)
    summary: dict[str, Any] = {
        "symbols": 0,
        "requests": 0,
        "failures": [],
        "rows_before": rows_before,
        "rows_after": rows_before,
        "rows_written": 0,
    }

    orig_db = _db.DB_FILE
    orig_provider = market_data.get_provider()
    try:
        _db.DB_FILE = copy_path
        if provider is not None:
            market_data.set_provider(provider)
        for w in windows:
            if max_requests is not None and summary["requests"] >= max_requests:
                break
            sym, start, end = w.get("symbol"), w.get("start"), w.get("end")
            if not sym or not start or not end:
                continue
            summary["symbols"] += 1
            for flag in auto_adjust_flags:
                if max_requests is not None and summary["requests"] >= max_requests:
                    break
                summary["requests"] += 1
                try:
                    price_cache.fetch_daily_cached(sym, start=start, end=end, auto_adjust=flag)
                except Exception as exc:  # provider/DB errors must not abort the run
                    summary["failures"].append({"symbol": sym, "flag": flag, "error": str(exc)})
    finally:
        _db.DB_FILE = orig_db
        market_data.set_provider(orig_provider)

    summary["rows_after"] = _count_price_rows(copy_path)
    summary["rows_written"] = summary["rows_after"] - rows_before
    return summary
