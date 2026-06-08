#!/usr/bin/env python3
"""Z1C (Gate 1) — targeted SPY interior-gap densifier (copy-only, FREE provider).

The Z1B measurement left 6 candidates not event-study-ready, blocked SOLELY by
benchmark (SPY) coverage: their dense asset caches intersect a SPARSE SPY series,
so no contiguous 60+20 aligned window exists.  Root cause (read in
``price_cache._plan_fetch_ranges``): the read-through cache fills prefix/suffix
gaps only — a wide SPY span sitting inside SPY's global cache never densifies an
interior hole.

This helper fixes exactly that, on a COPY only.  For each candidate event date it
computes the required window, finds the PURE-EMPTY missing sub-ranges (prefix /
interior gaps wider than the event-study contiguity tolerance / suffix), and
fetches ONLY those SPY sub-ranges with the FREE yfinance provider.  Because each
fetched sub-range holds no cached rows, ``fetch_daily_cached`` issues a full fetch
that fills the hole — additively, never overwriting an existing row.

Gates: REFUSES the live archive, REQUIRES an explicit copy path, fetches/writes
ONLY SPY, pins the free provider (refuses any non-free), never promotes, and makes
no billed call.  No directional / significance claim — coverage only.

Usage::

    python scripts/z1c_spy_gap_densify.py \\
        --candidates data/candidates/z1a_multi_regime_candidates.yaml \\
        --copy-path backups/z1b_working_copy.db
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

BENCHMARK = "SPY"
# Window must comfortably contain the event-study estimation window (60 business
# days) before the event plus the 20-business-day forward horizon, with buffer.
DEFAULT_DAYS_BEFORE = 130
DEFAULT_DAYS_AFTER = 40
# Mirror event_study_validation._MAX_GAP_CALENDAR_DAYS: only holes WIDER than this
# break a contiguous aligned window, so only those need filling.
MAX_GAP_DAYS = 5
_FREE_PROVIDER_NAME = "yfinance"


def _assert_copy_target(copy_path: Optional[str]) -> None:
    if not copy_path:
        raise ValueError("an explicit copy_path is required; refusing to default to the live archive")
    if os.path.realpath(copy_path) == os.path.realpath(db.LIVE_DB_FILE):
        raise ValueError(f"refusing to target the live archive ({copy_path}); pass a DB copy")


def _event_dates(candidates_path: str) -> list[str]:
    import yaml
    with open(candidates_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    rows = data.get("candidates") if isinstance(data, dict) else data
    out = []
    for c in rows or []:
        ed = str((c or {}).get("event_date") or "")[:10]
        if ed:
            out.append(ed)
    return out


def _window(event_date: str, days_before: int, days_after: int) -> tuple[str, str]:
    e = date.fromisoformat(event_date)
    return ((e - timedelta(days=days_before)).isoformat(),
            (e + timedelta(days=days_after)).isoformat())


def _cached_spy_dates(copy_path: str, start: str, end: str, auto_adjust: int) -> list[str]:
    con = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute(
            "SELECT date FROM price_cache WHERE ticker=? AND auto_adjust=? AND close IS NOT NULL "
            "AND date BETWEEN ? AND ? ORDER BY date", (BENCHMARK, auto_adjust, start, end))]
    finally:
        con.close()


def _missing_runs(cached: list[str], window_start: str, window_end: str,
                  max_gap_days: int) -> list[tuple[str, str]]:
    """Maximal PURE-EMPTY sub-ranges (prefix / interior>gap / suffix) to fetch.

    Each returned range contains NO cached SPY row, so a read-through fetch over
    it fills the hole instead of no-op-ing on a prefix/suffix-only plan.
    """
    ws, we = date.fromisoformat(window_start), date.fromisoformat(window_end)
    if not cached:
        return [(window_start, window_end)]
    first, last = date.fromisoformat(cached[0]), date.fromisoformat(cached[-1])
    runs: list[tuple[str, str]] = []
    if (first - ws).days > max_gap_days:
        runs.append((window_start, (first - timedelta(days=1)).isoformat()))
    for a, b in zip(cached, cached[1:]):
        da, db_ = date.fromisoformat(a), date.fromisoformat(b)
        if (db_ - da).days > max_gap_days:
            runs.append(((da + timedelta(days=1)).isoformat(), (db_ - timedelta(days=1)).isoformat()))
    if (we - last).days > max_gap_days:
        runs.append(((last + timedelta(days=1)).isoformat(), window_end))
    return runs


def _count_spy(copy_path: str) -> int:
    con = sqlite3.connect(f"file:{copy_path}?mode=ro", uri=True)
    try:
        return con.execute("SELECT COUNT(*) FROM price_cache WHERE ticker=?", (BENCHMARK,)).fetchone()[0]
    finally:
        con.close()


def densify_spy(
    *,
    copy_path: str,
    candidates_path: str,
    provider: Optional[Any] = None,
    days_before: int = DEFAULT_DAYS_BEFORE,
    days_after: int = DEFAULT_DAYS_AFTER,
    max_gap_days: int = MAX_GAP_DAYS,
    auto_adjust_flags: tuple = (False, True),
    max_requests: Optional[int] = None,
) -> dict:
    """Densify SPY interior gaps for each candidate event window, on the copy only."""
    _assert_copy_target(copy_path)
    if not os.path.exists(copy_path):
        raise FileNotFoundError(copy_path)

    import market_data
    import price_cache

    prov = provider if provider is not None else market_data.YFinanceProvider()
    if getattr(prov, "provider_name", None) != _FREE_PROVIDER_NAME:
        raise ValueError(
            "refusing a non-free provider; this densifier uses the free yfinance adapter only "
            f"(got provider_name={getattr(prov, 'provider_name', None)!r})"
        )

    event_dates = _event_dates(candidates_path)
    rows_before = _count_spy(copy_path)
    summary: dict[str, Any] = {
        "copy_only": True, "not_promoted": True,
        "events": len(event_dates), "requests": 0, "failures": [],
        "spy_rows_before": rows_before, "spy_rows_after": rows_before, "rows_written": 0,
        "per_event": [], "remaining_gaps": [],
    }

    orig_db = db.DB_FILE
    orig_prov = market_data.get_provider()
    try:
        db.DB_FILE = copy_path
        market_data.set_provider(prov)
        for ed in event_dates:
            ws, we = _window(ed, days_before, days_after)
            filled = 0
            for flag in auto_adjust_flags:
                cached = _cached_spy_dates(copy_path, ws, we, 1 if flag else 0)
                for run_start, run_end in _missing_runs(cached, ws, we, max_gap_days):
                    if max_requests is not None and summary["requests"] >= max_requests:
                        break
                    summary["requests"] += 1
                    try:
                        price_cache.fetch_daily_cached(BENCHMARK, start=run_start, end=run_end, auto_adjust=flag)
                        filled += 1
                    except Exception as exc:  # never abort the run
                        summary["failures"].append({"event": ed, "range": [run_start, run_end], "error": str(exc)})
            summary["per_event"].append({"event_date": ed, "runs_fetched": filled})
    finally:
        db.DB_FILE = orig_db
        market_data.set_provider(orig_prov)

    summary["spy_rows_after"] = _count_spy(copy_path)
    summary["rows_written"] = summary["spy_rows_after"] - rows_before
    summary["remaining_gaps"] = remaining_gaps(copy_path, candidates_path,
                                               days_before=days_before, days_after=days_after,
                                               max_gap_days=max_gap_days)
    return summary


def remaining_gaps(copy_path: str, candidates_path: str, *,
                   days_before: int = DEFAULT_DAYS_BEFORE, days_after: int = DEFAULT_DAYS_AFTER,
                   max_gap_days: int = MAX_GAP_DAYS) -> list[dict]:
    """Read-only: SPY (aa=0) gaps wider than tolerance still present per event window."""
    out = []
    for ed in _event_dates(candidates_path):
        ws, we = _window(ed, days_before, days_after)
        cached = _cached_spy_dates(copy_path, ws, we, 0)
        runs = _missing_runs(cached, ws, we, max_gap_days)
        if runs:
            out.append({"event_date": ed, "gaps": runs})
    return out


def summarize(summary: dict) -> str:
    L = [
        "Z1C SPY interior-gap densification (COPY ONLY, NOT promoted to live; SPY-only, additive)",
        "  Coverage repair only — no directional, predictive, or statistical-importance claim.",
        f"  events: {summary.get('events')} | requests: {summary.get('requests')} | "
        f"SPY rows {summary.get('spy_rows_before')} -> {summary.get('spy_rows_after')} "
        f"(+{summary.get('rows_written')})",
        f"  failures: {len(summary.get('failures') or [])} | "
        f"event windows with residual >{MAX_GAP_DAYS}d SPY gaps: {len(summary.get('remaining_gaps') or [])}",
        "  Copy-only result. Not promoted to live.",
    ]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Z1C copy-only targeted SPY interior-gap densifier (free provider).")
    p.add_argument("--candidates", required=True)
    p.add_argument("--copy-path", dest="copy_path", required=True)
    p.add_argument("--days-before", dest="days_before", type=int, default=DEFAULT_DAYS_BEFORE)
    p.add_argument("--days-after", dest="days_after", type=int, default=DEFAULT_DAYS_AFTER)
    p.add_argument("--max-requests", dest="max_requests", type=int, default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        _assert_copy_target(args.copy_path)
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    summary = densify_spy(copy_path=args.copy_path, candidates_path=args.candidates,
                          days_before=args.days_before, days_after=args.days_after,
                          max_requests=args.max_requests)
    print(json.dumps(summary, indent=2, default=str) if args.json else summarize(summary))
    return 0


__all__ = ("densify_spy", "remaining_gaps", "summarize", "main", "BENCHMARK")


if __name__ == "__main__":
    raise SystemExit(main())
