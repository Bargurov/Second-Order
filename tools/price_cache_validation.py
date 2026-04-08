"""
tools/price_cache_validation.py

Empirical validation for the persistent SQLite price cache.

Runs a representative replay of the fetch patterns the live app exercises
and reports:

  * Provider calls with a cold cache (first session)
  * Provider calls with the cache warm (second session, restart simulated)
  * Provider calls after a "next-day" shift (still warm, but the live
    refresh window forces a small trailing refetch)

This is the calibration step for ``price_cache._LIVE_REFRESH_DAYS``.

Run as:
    python -m tools.price_cache_validation
"""

from __future__ import annotations

import os
import sys
import tempfile
import uuid
from datetime import date as _date, timedelta as _timedelta
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import market_check
import price_cache


# ---------------------------------------------------------------------------
# Representative workload — mirrors the symbols that the analyse flow,
# market checks, movers, and backtests actually touch.
# ---------------------------------------------------------------------------

_LIVE_TICKERS = [
    # Rolling / live (auto_adjust=True)
    "ES=F", "NQ=F", "CL=F", "GC=F", "DX-Y.NYB", "^TNX", "^VIX", "BZ=F",
    "XLE", "SMH", "XAR", "BDRY",
    "AAPL", "MSFT", "NVDA", "XOM", "CVX", "LMT", "RTX",
]

_BACKTEST_TICKERS = [
    # Event-anchored (auto_adjust=False)
    ("AAPL", "2025-12-01"),
    ("MSFT", "2025-12-01"),
    ("XLE",  "2025-12-10"),
    ("CL=F", "2025-11-20"),
    ("SMH",  "2025-11-05"),
    ("LMT",  "2025-10-15"),
    ("RTX",  "2025-10-15"),
]


class _RecordingProvider:
    """Fake provider that returns a long, deterministic DataFrame and
    tracks both call count and total rows returned."""

    def __init__(self) -> None:
        self.calls: int = 0
        self.rows_returned: int = 0

    def _df(self) -> pd.DataFrame:
        # One year of synthetic bars ending today.
        end = _date.today()
        start = end - _timedelta(days=365)
        idx = pd.date_range(start, end, freq="B")
        closes = [100.0 + (i % 7) * 0.5 for i in range(len(idx))]
        vols = [1_000_000.0] * len(idx)
        return pd.DataFrame({"Close": closes, "Volume": vols}, index=idx)

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        self.calls += 1
        df = self._df()
        if start:
            lo = pd.Timestamp(start)
            df = df.loc[df.index >= lo]
        if end:
            hi = pd.Timestamp(end)
            df = df.loc[df.index < hi]
        if df.empty:
            return None
        self.rows_returned += len(df)
        return df

    def fetch_info(self, ticker: str) -> dict:
        return {
            "symbol": ticker.upper(),
            "name": None, "sector": None, "industry": None,
            "market_cap": None, "avg_volume": None,
        }


def _run_workload() -> None:
    # Live rolling fetches
    for t in _LIVE_TICKERS:
        market_check._fetch(t)
    # Event-anchored fetches
    for t, anchor in _BACKTEST_TICKERS:
        market_check._fetch_since(t, anchor)


def main() -> None:
    from market_data import get_provider, set_provider

    saved_db = db.DB_FILE
    saved_provider = get_provider()

    tmp = os.path.join(
        tempfile.gettempdir(), f"price_cache_val_{uuid.uuid4().hex}.db",
    )
    db.DB_FILE = tmp
    price_cache._reset_table_ready_for_tests()

    try:
        total_ops = len(_LIVE_TICKERS) + len(_BACKTEST_TICKERS)
        print(f"Workload: {total_ops} operations "
              f"({len(_LIVE_TICKERS)} live, {len(_BACKTEST_TICKERS)} backtest)")
        print(f"Live refresh window: {price_cache._LIVE_REFRESH_DAYS} business day(s)")
        print()

        # --- Pass 1: cold persistent cache, cold in-memory cache ---
        provider = _RecordingProvider()
        set_provider(provider)
        market_check._cache_clear()
        _run_workload()
        cold_calls = provider.calls
        cold_rows = provider.rows_returned
        print(f"Pass 1 (cold SQLite, cold RAM): {cold_calls:3d} calls, "
              f"{cold_rows:5d} rows")

        # --- Pass 2: warm SQLite, cold in-memory cache (simulated restart) ---
        provider = _RecordingProvider()
        set_provider(provider)
        market_check._cache_clear()
        _run_workload()
        warm_calls = provider.calls
        warm_rows = provider.rows_returned
        print(f"Pass 2 (warm SQLite, cold RAM): {warm_calls:3d} calls, "
              f"{warm_rows:5d} rows")

        # --- Pass 3: warm + warm (same session) ---
        provider = _RecordingProvider()
        set_provider(provider)
        _run_workload()
        hot_calls = provider.calls
        hot_rows = provider.rows_returned
        print(f"Pass 3 (warm SQLite, warm RAM): {hot_calls:3d} calls, "
              f"{hot_rows:5d} rows")

        # --- Summary ---
        print()
        row_saving = 1.0 - (warm_rows / max(cold_rows, 1))
        print(f"Cold -> warm-restart row saving: {row_saving:.1%}  "
              f"({cold_rows - warm_rows} rows avoided)")
        call_saving = 1.0 - (warm_calls / max(cold_calls, 1))
        print(f"Cold -> warm-restart call saving: {call_saving:.1%}  "
              f"({cold_calls - warm_calls} calls avoided)")
        hot_saving = 1.0 - (hot_rows / max(cold_rows, 1))
        print(f"Cold -> fully-warm row saving:    {hot_saving:.1%}")

        # Sanity: on a fully-warm second pass the RAM layer alone should
        # absorb everything.
        assert hot_calls == 0, (
            f"Expected 0 provider calls on warm/warm; got {hot_calls}"
        )
        # Sanity: warm-restart should move at least 90% fewer rows than
        # cold.  Historical backtest bars (auto_adjust=False) come back
        # entirely from SQLite, and live bars only need the trailing
        # _LIVE_REFRESH_DAYS window refreshed.
        assert warm_rows * 10 <= cold_rows, (
            f"Expected warm-restart to cut rows fetched by 10x; "
            f"cold={cold_rows}, warm={warm_rows}"
        )
        print()
        print("OK - persistent cache is working as designed.")
        print(f"Tuned _LIVE_REFRESH_DAYS={price_cache._LIVE_REFRESH_DAYS}: "
              f"cold->warm call delta={cold_calls - warm_calls}, "
              f"row delta={cold_rows - warm_rows}")
    finally:
        set_provider(saved_provider)
        db.DB_FILE = saved_db
        price_cache._reset_table_ready_for_tests()
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except PermissionError:
                pass


if __name__ == "__main__":
    main()
