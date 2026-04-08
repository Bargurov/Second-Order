"""
tests/test_price_cache.py

Focused tests for the persistent SQLite ticker price cache.

Required scenarios:
  * Cache hit avoids provider call
  * Partial-date miss fetches only the missing window and persists it
  * Restart-persistent behaviour via SQLite (simulated by clearing the
    in-memory TTL cache and re-opening the DB file)
  * Unchanged output contract for existing readers (_fetch / _fetch_since
    / ticker_chart)
"""

from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import unittest
import uuid
from datetime import date as _date
from typing import Optional

import pandas as pd

sys.path.insert(0, ".")

import db
import market_check
import price_cache
from market_data import MarketDataProvider, get_provider, set_provider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_df(
    closes: list[float],
    start_date: str = "2026-03-02",
    volumes: Optional[list[float]] = None,
) -> pd.DataFrame:
    """Return a Close/Volume DataFrame with a business-day index."""
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    idx = pd.date_range(start_date, periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=idx)


class _RecordingProvider:
    """Provider that returns a canned DataFrame and records every call.

    Optionally narrows the returned frame to the requested ``start``/``end``
    window so partial-gap tests can see exactly which rows came back.
    """

    def __init__(
        self,
        df: Optional[pd.DataFrame] = None,
        *,
        trim_to_range: bool = False,
    ):
        self._df = df
        self.calls: list[dict] = []
        self._trim = trim_to_range

    def fetch_daily(
        self,
        ticker: str,
        *,
        period: Optional[str] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        auto_adjust: bool = True,
    ) -> Optional[pd.DataFrame]:
        self.calls.append({
            "ticker": ticker, "period": period, "start": start,
            "end": end, "auto_adjust": auto_adjust,
        })
        if self._df is None:
            return None
        if not self._trim or (start is None and end is None):
            return self._df
        lo = pd.Timestamp(start) if start else self._df.index.min()
        hi = pd.Timestamp(end) if end else self._df.index.max()
        mask = (self._df.index >= lo) & (self._df.index < hi)
        sub = self._df.loc[mask]
        if sub.empty:
            return None
        return sub

    def fetch_info(self, ticker: str) -> dict:
        return {
            "symbol": ticker.upper(),
            "name": None, "sector": None, "industry": None,
            "market_cap": None, "avg_volume": None,
        }


# ---------------------------------------------------------------------------
# Base fixture — every test runs against a fresh temp SQLite file
# ---------------------------------------------------------------------------

class _CacheTestBase(unittest.TestCase):

    def setUp(self) -> None:
        self._saved_provider = get_provider()
        self._saved_db_file = db.DB_FILE
        self._tmp_db = os.path.join(
            tempfile.gettempdir(), f"test_price_cache_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        price_cache._reset_table_ready_for_tests()
        market_check._cache_clear()

    def tearDown(self) -> None:
        set_provider(self._saved_provider)
        market_check._cache_clear()
        db.DB_FILE = self._saved_db_file
        price_cache._reset_table_ready_for_tests()
        if os.path.exists(self._tmp_db):
            try:
                os.remove(self._tmp_db)
            except PermissionError:
                pass


# ---------------------------------------------------------------------------
# Cache hit avoids provider call
# ---------------------------------------------------------------------------

class TestCacheHitAvoidsProviderCall(_CacheTestBase):

    def test_warm_cache_no_provider_call(self) -> None:
        """After one fetch, the persistent cache alone should satisfy a
        follow-up read even when the in-memory TTL cache is cleared."""
        df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0])
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        # First call — cold cache, provider is hit.
        first = price_cache.fetch_daily_cached(
            "AAPL", start="2026-03-02", end="2026-03-06", auto_adjust=False,
        )
        self.assertIsNotNone(first)
        self.assertEqual(len(provider.calls), 1)

        # Drop the in-memory TTL cache so we force a SQLite read.
        market_check._cache_clear()

        # Second call — SQLite should satisfy it entirely, no new provider hit.
        second = price_cache.fetch_daily_cached(
            "AAPL", start="2026-03-02", end="2026-03-06", auto_adjust=False,
        )
        self.assertIsNotNone(second)
        self.assertEqual(len(provider.calls), 1, "provider was re-hit on warm cache")
        # Round-trips the same closes.
        self.assertEqual(
            list(second["Close"].round(2)),
            [100.0, 101.0, 102.0, 103.0, 104.0],
        )

    def test_market_check_fetch_since_hits_cache(self) -> None:
        """_fetch_since goes through the cache layer for auto_adjust=False."""
        df = _make_df([50.0] * 8)
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        market_check._fetch_since("CL=F", "2026-03-02")
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(provider.calls[0]["auto_adjust"])
        self.assertEqual(provider.calls[0]["start"], "2026-03-02")

        # Second _fetch_since call — in-memory TTL cache should absorb it
        # before we ever reach the SQLite layer.
        market_check._fetch_since("CL=F", "2026-03-02")
        self.assertEqual(len(provider.calls), 1)

    def test_bounded_request_satisfied_by_sqlite_alone(self) -> None:
        """A bounded-start/end request that the cache fully covers should
        never touch the provider, even after the in-memory TTL is cleared.

        This is the property that matters across restarts: historical
        backtest windows never need a second provider round-trip."""
        df = _make_df([50.0] * 8, start_date="2026-03-02")
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        first = price_cache.fetch_daily_cached(
            "CL=F", start="2026-03-02", end="2026-03-11", auto_adjust=False,
        )
        self.assertIsNotNone(first)
        self.assertEqual(len(provider.calls), 1)

        # Simulated restart: drop the in-memory TTL cache and re-probe
        # the SQLite table.
        market_check._cache_clear()
        price_cache._reset_table_ready_for_tests()

        second = price_cache.fetch_daily_cached(
            "CL=F", start="2026-03-02", end="2026-03-11", auto_adjust=False,
        )
        self.assertIsNotNone(second)
        self.assertEqual(
            len(provider.calls), 1,
            "SQLite price cache should have absorbed the re-read",
        )


# ---------------------------------------------------------------------------
# Partial-date miss fetches only missing range
# ---------------------------------------------------------------------------

class TestPartialMissFetchesOnlyGap(_CacheTestBase):

    def test_suffix_gap_fetched_and_persisted(self) -> None:
        """Pre-seed the cache with an early window, then request a longer
        window that extends past the cached end.  Only the missing suffix
        should be fetched, and the combined result must reach all the way
        to the new end date."""
        # Pre-seed with days 2..6 (5 rows).
        early = _make_df([100.0, 101.0, 102.0, 103.0, 104.0],
                         start_date="2026-03-02")
        price_cache._write_rows("AAPL", early, auto_adjust=False)

        # Provider will return a frame covering the full requested window,
        # but with trim enabled so we can verify it was asked only for the
        # suffix gap.
        full = _make_df(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0, 109.0],
            start_date="2026-03-02",
        )
        provider = _RecordingProvider(df=full, trim_to_range=True)
        set_provider(provider)

        result = price_cache.fetch_daily_cached(
            "AAPL", start="2026-03-02", end="2026-03-13", auto_adjust=False,
        )
        self.assertIsNotNone(result)
        # Combined frame must cover every business day in the window.
        self.assertEqual(len(result), 10)
        self.assertEqual(list(result["Close"].round(2)),
                         [100.0, 101.0, 102.0, 103.0, 104.0,
                          105.0, 106.0, 107.0, 108.0, 109.0])

        # Exactly one provider call for the suffix gap, starting after
        # the last cached day.
        self.assertEqual(len(provider.calls), 1)
        call = provider.calls[0]
        self.assertEqual(call["ticker"], "AAPL")
        self.assertGreaterEqual(call["start"], "2026-03-07")
        self.assertLessEqual(call["start"], "2026-03-09")

    def test_prefix_gap_fetched(self) -> None:
        """Pre-seed the cache with late days only, then request a wider
        window.  Only the prefix gap should be fetched."""
        late = _make_df([200.0, 201.0, 202.0], start_date="2026-03-09")
        price_cache._write_rows("XOM", late, auto_adjust=False)

        full = _make_df(
            [100.0, 101.0, 102.0, 103.0, 104.0,
             200.0, 201.0, 202.0],
            start_date="2026-03-02",
        )
        provider = _RecordingProvider(df=full, trim_to_range=True)
        set_provider(provider)

        result = price_cache.fetch_daily_cached(
            "XOM", start="2026-03-02", end="2026-03-11", auto_adjust=False,
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 8)
        self.assertEqual(len(provider.calls), 1)
        call = provider.calls[0]
        self.assertEqual(call["start"], "2026-03-02")
        # Provider end is exclusive (yfinance convention), so it must be
        # on or before the earliest cached day.
        self.assertLessEqual(call["end"], "2026-03-10")

    def test_full_coverage_no_provider_call(self) -> None:
        """When the cache covers the entire request, the provider is
        never called."""
        df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0],
                      start_date="2026-03-02")
        price_cache._write_rows("GC=F", df, auto_adjust=False)

        provider = _RecordingProvider(df=df)
        set_provider(provider)

        result = price_cache.fetch_daily_cached(
            "GC=F", start="2026-03-02", end="2026-03-06", auto_adjust=False,
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(provider.calls), 0)


# ---------------------------------------------------------------------------
# Restart-persistent behaviour
# ---------------------------------------------------------------------------

class TestRestartPersistence(_CacheTestBase):

    def test_rows_survive_fresh_connection(self) -> None:
        """Write rows with one module-level connection path, then reset
        the ``_table_ready`` flag and re-read.  Rows must still be there.

        This simulates the process-restart case: a new run reopens the
        same DB file and expects the cache to still be populated.
        """
        df = _make_df([10.0, 11.0, 12.0, 13.0, 14.0])
        price_cache._write_rows("SPY", df, auto_adjust=False)

        # Simulate restart: force the module to re-probe the table and
        # drop any in-process state.
        price_cache._reset_table_ready_for_tests()
        market_check._cache_clear()

        # Confirm the rows are actually on disk via a direct DB read.
        with sqlite3.connect(db.DB_FILE) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM price_cache WHERE ticker = ?",
                ("SPY",),
            ).fetchone()[0]
        self.assertEqual(count, 5)

        # And that fetch_daily_cached returns them without calling the
        # provider.
        provider = _RecordingProvider(df=None)
        set_provider(provider)
        result = price_cache.fetch_daily_cached(
            "SPY", start="2026-03-02", end="2026-03-06", auto_adjust=False,
        )
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 5)
        self.assertEqual(len(provider.calls), 0)

    def test_auto_adjust_flag_is_part_of_key(self) -> None:
        """Raw and adjusted closes for the same ticker must not collide."""
        raw = _make_df([100.0, 101.0, 102.0])
        adj = _make_df([110.0, 111.0, 112.0])
        price_cache._write_rows("MSFT", raw, auto_adjust=False)
        price_cache._write_rows("MSFT", adj, auto_adjust=True)

        with sqlite3.connect(db.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT auto_adjust, close FROM price_cache "
                "WHERE ticker='MSFT' ORDER BY auto_adjust, date",
            ).fetchall()

        # Three raw + three adjusted = six rows.
        self.assertEqual(len(rows), 6)
        raw_rows = [r for r in rows if r[0] == 0]
        adj_rows = [r for r in rows if r[0] == 1]
        self.assertEqual([r[1] for r in raw_rows], [100.0, 101.0, 102.0])
        self.assertEqual([r[1] for r in adj_rows], [110.0, 111.0, 112.0])

    def test_upsert_refreshes_existing_row(self) -> None:
        """Re-writing the same (ticker, date, auto_adjust) key should
        overwrite the close, not duplicate the row."""
        v1 = _make_df([100.0], start_date="2026-03-02")
        price_cache._write_rows("QQQ", v1, auto_adjust=False)
        v2 = _make_df([105.0], start_date="2026-03-02")
        price_cache._write_rows("QQQ", v2, auto_adjust=False)

        with sqlite3.connect(db.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT date, close FROM price_cache WHERE ticker='QQQ'",
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0][1], 105.0)


# ---------------------------------------------------------------------------
# Output contract — existing readers still return the expected shape
# ---------------------------------------------------------------------------

class TestOutputContractUnchanged(_CacheTestBase):

    def test_market_check_fetch_returns_close_and_volume(self) -> None:
        df = _make_df([100.0] * 8)
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        result = market_check._fetch("AAPL")
        self.assertIsNotNone(result)
        self.assertIn("Close", result.columns)
        self.assertIn("Volume", result.columns)
        self.assertEqual(len(result), 8)

    def test_market_check_fetch_since_returns_close_and_volume(self) -> None:
        df = _make_df([100.0] * 8)
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        result = market_check._fetch_since("AAPL", "2026-03-02")
        self.assertIsNotNone(result)
        self.assertIn("Close", result.columns)
        self.assertIn("Volume", result.columns)
        self.assertEqual(len(result), 8)

    def test_ticker_chart_returns_expected_shape(self) -> None:
        df = _make_df(
            [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
            start_date="2026-02-23",
        )
        provider = _RecordingProvider(df=df)
        set_provider(provider)

        out = market_check.ticker_chart("AAPL", "2026-02-27", window=5)
        self.assertIsInstance(out, list)
        self.assertGreater(len(out), 0)
        for entry in out:
            self.assertIn("date", entry)
            self.assertIn("close", entry)
            self.assertIsInstance(entry["close"], float)


# ---------------------------------------------------------------------------
# Gap planner helper
# ---------------------------------------------------------------------------

class TestPlanFetchRanges(unittest.TestCase):
    """_plan_fetch_ranges encodes the cache-gap policy — lock it down."""

    def _df(self, start: str, n: int) -> pd.DataFrame:
        idx = pd.date_range(start, periods=n, freq="B")
        return pd.DataFrame(
            {"Close": [100.0] * n, "Volume": [1_000_000.0] * n},
            index=idx,
        )

    def test_empty_cache_yields_full_range(self) -> None:
        gaps = price_cache._plan_fetch_ranges(
            _date(2026, 3, 2), _date(2026, 3, 13),
            pd.DataFrame(columns=["Close", "Volume"]),
            auto_adjust=False,
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0], (_date(2026, 3, 2), _date(2026, 3, 13)))

    def test_full_coverage_yields_no_gaps(self) -> None:
        cached = self._df("2026-03-02", 10)  # covers 2026-03-02..2026-03-13
        gaps = price_cache._plan_fetch_ranges(
            _date(2026, 3, 2), _date(2026, 3, 13), cached,
            auto_adjust=False,
        )
        self.assertEqual(gaps, [])

    def test_prefix_only_gap(self) -> None:
        cached = self._df("2026-03-09", 5)  # covers 2026-03-09..2026-03-13
        gaps = price_cache._plan_fetch_ranges(
            _date(2026, 3, 2), _date(2026, 3, 13), cached,
            auto_adjust=False,
        )
        self.assertEqual(len(gaps), 1)
        g_start, g_end = gaps[0]
        self.assertEqual(g_start, _date(2026, 3, 2))
        self.assertLess(g_end, _date(2026, 3, 9))

    def test_suffix_only_gap(self) -> None:
        cached = self._df("2026-03-02", 5)  # covers 2026-03-02..2026-03-06
        gaps = price_cache._plan_fetch_ranges(
            _date(2026, 3, 2), _date(2026, 3, 13), cached,
            auto_adjust=False,
        )
        self.assertEqual(len(gaps), 1)
        g_start, g_end = gaps[0]
        self.assertGreater(g_start, _date(2026, 3, 6))
        self.assertEqual(g_end, _date(2026, 3, 13))

    def test_live_refresh_trims_trailing_days(self) -> None:
        """auto_adjust=True forces a refetch of the trailing _LIVE_REFRESH_DAYS
        business days so today's bar always lands in the cache."""
        cached = self._df("2026-03-02", 10)  # covers 2026-03-02..2026-03-13
        gaps = price_cache._plan_fetch_ranges(
            _date(2026, 3, 2), _date(2026, 3, 13), cached,
            auto_adjust=True,
        )
        # Not empty: the trailing window is always pulled back.
        self.assertEqual(len(gaps), 1)
        g_start, _g_end = gaps[0]
        # Gap starts at most 1 business day before the cached tail
        self.assertLessEqual(g_start, _date(2026, 3, 13))
        self.assertGreaterEqual(g_start, _date(2026, 3, 12))


if __name__ == "__main__":
    unittest.main()
