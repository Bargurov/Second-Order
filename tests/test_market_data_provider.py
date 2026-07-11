"""
tests/test_market_data_provider.py

Tests for the MarketDataProvider seam introduced in market_data.py.

Covers:
  - The Protocol/runtime_checkable interface
  - YFinanceProvider.fetch_daily and fetch_info happy paths and failures
  - get_provider() / set_provider() singleton swap
  - market_check._fetch / _fetch_since delegate to the active provider
  - Graceful failure when yfinance raises or returns empty data
"""

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from typing import Optional
from unittest.mock import patch, MagicMock

import pandas as pd

sys.path.insert(0, ".")

import db
import market_check
import market_data
import price_cache
from market_data import (
    MarketDataProvider,
    YFinanceProvider,
    get_provider,
    set_provider,
)


# ---------------------------------------------------------------------------
# Helper: a fake provider for tests that don't want to mock yfinance
# ---------------------------------------------------------------------------

class _FakeProvider:
    """Records calls and returns canned responses."""

    def __init__(self, daily_response=None, info_response=None):
        self.daily_response = daily_response
        self.info_response = info_response or {
            "symbol": "FAKE", "name": None, "sector": None,
            "industry": None, "market_cap": None, "avg_volume": None,
        }
        self.daily_calls: list[dict] = []
        self.info_calls: list[str] = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        self.daily_calls.append({
            "ticker": ticker, "period": period, "start": start,
            "end": end, "auto_adjust": auto_adjust,
        })
        return self.daily_response

    def fetch_info(self, ticker):
        self.info_calls.append(ticker)
        return self.info_response


def _make_df(closes, volumes=None, start_date="2026-03-01"):
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    dates = pd.date_range(start_date, periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)


# One controlled cache clock for every rolling-period test.  A Monday, so
# ``price_cache._last_weekday(_CACHE_TODAY) == _CACHE_TODAY`` and the
# resolved 3mo window is exactly [_CACHE_TODAY - 93d, _CACHE_TODAY].
# Rolling-window fixtures must derive BOTH the patched cache clock and the
# provider DataFrame dates from this anchor: a fixed historical frame with
# an unpatched real clock ages out of the 93-day request window, gets
# persisted but re-read as empty, returns None (never hot-cached), and the
# provider is honestly retried — which broke the old cache-hit assertion.
_CACHE_TODAY = date(2026, 4, 20)


def _cache_clock_df(closes, *, anchor=_CACHE_TODAY, days_before=30):
    """Provider frame anchored ``days_before`` days before the cache clock."""
    start = anchor - timedelta(days=days_before)
    return _make_df(closes, start_date=start.isoformat())


def _patched_clock(anchor=_CACHE_TODAY):
    """Patch the SQLite cache layer's date seam to a fixed anchor."""
    return patch("price_cache._today", return_value=anchor)


# ---------------------------------------------------------------------------
# Protocol structural conformance
# ---------------------------------------------------------------------------

class TestProtocolConformance(unittest.TestCase):
    """The Protocol should accept any class with the right method signatures."""

    def test_yfinance_provider_satisfies_protocol(self):
        provider = YFinanceProvider()
        self.assertIsInstance(provider, MarketDataProvider)

    def test_fake_provider_satisfies_protocol(self):
        fake = _FakeProvider()
        self.assertIsInstance(fake, MarketDataProvider)


# ---------------------------------------------------------------------------
# get_provider / set_provider singleton management
# ---------------------------------------------------------------------------

class TestProviderSingleton(unittest.TestCase):

    def setUp(self):
        self._original = get_provider()

    def tearDown(self):
        set_provider(self._original)

    def test_default_is_yfinance(self):
        self.assertIsInstance(get_provider(), YFinanceProvider)

    def test_set_and_get(self):
        fake = _FakeProvider()
        set_provider(fake)
        self.assertIs(get_provider(), fake)

    def test_swap_isolation(self):
        fake1 = _FakeProvider()
        fake2 = _FakeProvider()
        set_provider(fake1)
        self.assertIs(get_provider(), fake1)
        set_provider(fake2)
        self.assertIs(get_provider(), fake2)


# ---------------------------------------------------------------------------
# YFinanceProvider.fetch_daily — happy path and failures
# ---------------------------------------------------------------------------

class TestYFinanceFetchDaily(unittest.TestCase):

    def test_period_mode(self):
        df = _make_df([100.0, 101.0, 102.0])
        with patch("yfinance.download", return_value=df) as mock_dl:
            result = YFinanceProvider().fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        # Verify correct kwargs forwarded
        kwargs = mock_dl.call_args.kwargs
        self.assertEqual(kwargs["period"], "3mo")
        self.assertEqual(kwargs["interval"], "1d")
        self.assertEqual(kwargs["progress"], False)
        self.assertTrue(kwargs["auto_adjust"])

    def test_start_only(self):
        df = _make_df([100.0, 101.0])
        with patch("yfinance.download", return_value=df) as mock_dl:
            result = YFinanceProvider().fetch_daily("AAPL", start="2026-03-01")
        self.assertIsNotNone(result)
        kwargs = mock_dl.call_args.kwargs
        self.assertEqual(kwargs["start"], "2026-03-01")
        self.assertNotIn("end", kwargs)

    def test_start_and_end(self):
        df = _make_df([100.0, 101.0])
        with patch("yfinance.download", return_value=df) as mock_dl:
            result = YFinanceProvider().fetch_daily(
                "AAPL", start="2026-03-01", end="2026-03-15"
            )
        self.assertIsNotNone(result)
        kwargs = mock_dl.call_args.kwargs
        self.assertEqual(kwargs["start"], "2026-03-01")
        self.assertEqual(kwargs["end"], "2026-03-15")

    def test_auto_adjust_false_passed_through(self):
        df = _make_df([100.0, 101.0])
        with patch("yfinance.download", return_value=df) as mock_dl:
            YFinanceProvider().fetch_daily("AAPL", start="2026-03-01", auto_adjust=False)
        self.assertFalse(mock_dl.call_args.kwargs["auto_adjust"])

    def test_no_period_or_start_raises(self):
        with self.assertRaises(ValueError):
            YFinanceProvider().fetch_daily("AAPL")

    def test_empty_dataframe_returns_none(self):
        empty = pd.DataFrame()
        with patch("yfinance.download", return_value=empty):
            result = YFinanceProvider().fetch_daily("ZZZ", period="3mo")
        self.assertIsNone(result)

    def test_yfinance_raises_returns_none(self):
        """Network errors must NOT propagate; provider must return None."""
        with patch("yfinance.download", side_effect=ConnectionError("network down")):
            result = YFinanceProvider().fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_multiindex_columns_flattened(self):
        """yfinance sometimes returns MultiIndex columns; provider flattens them."""
        idx = pd.date_range("2026-03-01", periods=3, freq="B")
        cols = pd.MultiIndex.from_tuples([("Close", "AAPL"), ("Volume", "AAPL")])
        df = pd.DataFrame(
            [[100.0, 1e6], [101.0, 1e6], [102.0, 1e6]], index=idx, columns=cols
        )
        with patch("yfinance.download", return_value=df):
            result = YFinanceProvider().fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        # Columns should be a flat Index now
        self.assertIn("Close", result.columns)
        self.assertIn("Volume", result.columns)

    def test_adj_close_fallback(self):
        """When auto_adjust=False, yfinance may return Adj Close not Close."""
        idx = pd.date_range("2026-03-01", periods=3, freq="B")
        df = pd.DataFrame(
            {"Adj Close": [100.0, 101.0, 102.0], "Volume": [1e6, 1e6, 1e6]},
            index=idx,
        )
        with patch("yfinance.download", return_value=df):
            result = YFinanceProvider().fetch_daily("AAPL", start="2026-03-01", auto_adjust=False)
        self.assertIsNotNone(result)
        self.assertIn("Close", result.columns)


# ---------------------------------------------------------------------------
# YFinanceProvider.fetch_info — happy path and failures
# ---------------------------------------------------------------------------

class TestYFinanceFetchInfo(unittest.TestCase):

    def test_fetch_info_happy_path(self):
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "longName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3_000_000_000_000,
            "averageVolume": 50_000_000,
        }
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = YFinanceProvider().fetch_info("aapl")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertEqual(result["name"], "Apple Inc.")
        self.assertEqual(result["sector"], "Technology")
        self.assertEqual(result["industry"], "Consumer Electronics")
        self.assertEqual(result["market_cap"], 3_000_000_000_000)
        self.assertEqual(result["avg_volume"], 50_000_000)

    def test_fetch_info_short_name_fallback(self):
        """If longName is missing, fall back to shortName."""
        mock_ticker = MagicMock()
        mock_ticker.info = {"shortName": "AAPL"}
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = YFinanceProvider().fetch_info("AAPL")
        self.assertEqual(result["name"], "AAPL")

    def test_fetch_info_yfinance_raises(self):
        """If yfinance raises, fetch_info returns the fallback dict, not None."""
        with patch("yfinance.Ticker", side_effect=ConnectionError("down")):
            result = YFinanceProvider().fetch_info("AAPL")
        self.assertEqual(result["symbol"], "AAPL")
        self.assertIsNone(result["name"])
        self.assertIsNone(result["sector"])
        self.assertIsNone(result["market_cap"])

    def test_fetch_info_empty_info_dict(self):
        """When the .info dict is empty, all fields default to None."""
        mock_ticker = MagicMock()
        mock_ticker.info = {}
        with patch("yfinance.Ticker", return_value=mock_ticker):
            result = YFinanceProvider().fetch_info("ZZZ")
        self.assertEqual(result["symbol"], "ZZZ")
        self.assertIsNone(result["name"])
        self.assertIsNone(result["sector"])


# ---------------------------------------------------------------------------
# market_check delegates to the active provider
# ---------------------------------------------------------------------------

class _ProviderCacheBase(unittest.TestCase):
    """Shared isolation: temp SQLite DB, provider singleton restore,
    table-ready reset, and hot-cache clear — nothing leaks across tests."""

    def setUp(self):
        self._original = get_provider()
        # Point the SQLite price cache at a temp file so each test runs
        # against a clean slate and we don't touch the real events.db.
        self._original_db_file = db.DB_FILE
        self._tmp_db = os.path.join(
            tempfile.gettempdir(), f"test_price_cache_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        price_cache._reset_table_ready_for_tests()
        market_check._cache_clear()

    def tearDown(self):
        set_provider(self._original)
        market_check._cache_clear()
        db.DB_FILE = self._original_db_file
        price_cache._reset_table_ready_for_tests()
        if os.path.exists(self._tmp_db):
            try:
                os.remove(self._tmp_db)
            except PermissionError:
                pass

    def _sqlite_rows(self, ticker: str, auto_adjust: int):
        with sqlite3.connect(self._tmp_db) as conn:
            return conn.execute(
                "SELECT MIN(date), MAX(date), COUNT(*) FROM price_cache "
                "WHERE ticker = ? AND auto_adjust = ?",
                (ticker, auto_adjust),
            ).fetchone()


class TestMarketCheckDelegation(_ProviderCacheBase):
    """market_check._fetch and friends should call the active provider."""

    def test_fetch_uses_provider(self):
        # Rolling-period test: fixture dates and the cache clock derive
        # from the same _CACHE_TODAY anchor so all 10 bars are in-window
        # on any calendar date (AB1 Lane E repaired this with wall-clock-
        # relative dates; T3F pins it to the injected cache clock).
        df = _cache_clock_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            result = market_check._fetch("AAPL")
        # The cache layer re-reads rows from SQLite, so identity won't
        # match, but the Close column must round-trip unchanged.
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 10)
        self.assertEqual(len(fake.daily_calls), 1)
        call = fake.daily_calls[0]
        self.assertEqual(call["ticker"], "AAPL")
        # Cache layer translates period="3mo" into a concrete start/end
        # window before calling the provider.
        self.assertIsNone(call["period"])
        self.assertIsNotNone(call["start"])
        self.assertIsNotNone(call["end"])
        self.assertTrue(call["auto_adjust"])

    def test_fetch_since_uses_provider_no_lookahead(self):
        df = _make_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        # Use a weekday so date clamping doesn't shift it
        result = market_check._fetch_since("AAPL", "2026-03-02")  # Monday
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 10)
        call = fake.daily_calls[0]
        self.assertEqual(call["ticker"], "AAPL")
        self.assertIsNone(call["period"])
        self.assertEqual(call["start"], "2026-03-02")
        # Critical: backtest path must request unadjusted prices
        self.assertFalse(call["auto_adjust"])

    def test_fetch_returns_none_when_provider_returns_none(self):
        fake = _FakeProvider(daily_response=None)
        set_provider(fake)
        self.assertIsNone(market_check._fetch("ZZZ"))

    def test_fetch_since_returns_none_when_provider_returns_none(self):
        fake = _FakeProvider(daily_response=None)
        set_provider(fake)
        self.assertIsNone(market_check._fetch_since("ZZZ", "2026-03-01"))

    def test_ticker_info_uses_provider(self):
        info = {
            "symbol": "AAPL", "name": "Apple", "sector": "Tech",
            "industry": "Hardware", "market_cap": 3e12, "avg_volume": 5e7,
        }
        fake = _FakeProvider(info_response=info)
        set_provider(fake)
        result = market_check.ticker_info("AAPL")
        self.assertEqual(result["name"], "Apple")
        self.assertEqual(fake.info_calls, ["AAPL"])

    def test_ticker_chart_uses_provider(self):
        df = _make_df([100.0, 101.0, 102.0, 103.0, 104.0])
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        result = market_check.ticker_chart("AAPL", "2026-03-01", window=5)
        self.assertIsInstance(result, list)
        self.assertGreater(len(result), 0)
        # Each entry has date and close
        for entry in result:
            self.assertIn("date", entry)
            self.assertIn("close", entry)

    def test_ticker_chart_empty_when_provider_returns_none(self):
        fake = _FakeProvider(daily_response=None)
        set_provider(fake)
        result = market_check.ticker_chart("ZZZ", "2026-03-01")
        self.assertEqual(result, [])

    def test_cache_avoids_repeat_provider_call(self):
        """Once a VALID in-window value is cached, the provider is not
        called again — proven on both cache layers.

        The pre-T3F fixture used the default 2026-03-01 frame with the
        real cache clock; by July 2026 the frame sat entirely before the
        rolling 93-day request window, so rows persisted but the
        requested-window re-read was empty, the public result was None
        (correctly not hot-cached), and every call honestly retried the
        provider (3 calls, not 1).
        """
        df = _cache_clock_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            first = market_check._fetch("AAPL")
            # A valid in-window frame is actually returned...
            self.assertIsNotNone(first)
            self.assertEqual(len(first), 10)
            self.assertEqual(len(fake.daily_calls), 1)
            # ...persisted on the requested basis in SQLite...
            min_d, max_d, n = self._sqlite_rows("AAPL", 1)
            self.assertEqual(n, 10)
            window_start = _CACHE_TODAY - timedelta(days=93)
            self.assertGreaterEqual(date.fromisoformat(min_d), window_start)
            self.assertLessEqual(date.fromisoformat(max_d), _CACHE_TODAY)
            # ...and hot-cached in memory.
            self.assertGreaterEqual(market_check._cache_len(), 1)
            second = market_check._fetch("AAPL")
            third = market_check._fetch("AAPL")
        self.assertEqual(len(fake.daily_calls), 1,
                         "Provider was called more than once")
        # Same logical result after the SQLite round trip (not identity).
        self.assertEqual(list(first["Close"]), list(second["Close"]))
        self.assertEqual(list(first["Close"]), list(third["Close"]))


# ---------------------------------------------------------------------------
# T3F — rolling-window cache contract under one controlled clock
# ---------------------------------------------------------------------------

class TestRollingWindowCacheContract(_ProviderCacheBase):
    """The rolling 3mo request window and every provider frame derive
    from the same injected cache clock; only in-window same-basis rows
    are returned and hot-cached, and honest retry behavior is preserved
    for out-of-window responses."""

    def test_provider_request_boundaries(self):
        """Provider gets the resolved gap start, and an ``end`` one
        calendar day AFTER the inclusive request end (yfinance-exclusive);
        the public window itself stays inclusive."""
        df = _cache_clock_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            market_check._fetch("AAPL")
        call = fake.daily_calls[0]
        # The gap planner requests only fetchable trading days: the raw
        # window start (a Saturday for this anchor) snaps forward to the
        # next weekday.  Read the policy from the module's own helper
        # rather than re-encoding calendar logic here.
        window_start = _CACHE_TODAY - timedelta(days=93)
        expected_start = price_cache._next_weekday(window_start)
        self.assertEqual(call["start"], expected_start.isoformat())
        self.assertEqual(
            call["end"], (_CACHE_TODAY + timedelta(days=1)).isoformat(),
        )
        self.assertTrue(call["auto_adjust"])
        self.assertIsNone(call["period"])

    def test_out_of_window_response_stays_unavailable(self):
        """A frame entirely before request_start persists but is honestly
        re-read as empty: None result, no hot-cache entry, and a retry on
        the next call — the exact behavior the stale fixture tripped."""
        df = _cache_clock_df([100.0] * 10, days_before=150)  # ends ~-136d
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            first = market_check._fetch("AAPL")
            self.assertIsNone(first)
            self.assertEqual(market_check._cache_len(), 0)
            _min_d, _max_d, n = self._sqlite_rows("AAPL", 1)
            self.assertEqual(n, 10)  # persisted, just out of window
            second = market_check._fetch("AAPL")
            self.assertIsNone(second)
        self.assertEqual(len(fake.daily_calls), 2,
                         "None results must not be cached")

    def test_partial_overlap_filters_to_window(self):
        """Rows before the window are dropped; only the in-window suffix
        is returned, sorted, with no out-of-range leak."""
        df = _cache_clock_df([100.0 + i for i in range(20)], days_before=100)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            result = market_check._fetch("AAPL")
        self.assertIsNotNone(result)
        window_start = _CACHE_TODAY - timedelta(days=93)
        in_window = [d for d in df.index if d.date() >= window_start]
        self.assertEqual(len(result), len(in_window))
        self.assertLess(len(result), len(df))
        returned_dates = [pd.Timestamp(d).date() for d in result.index]
        self.assertEqual(returned_dates, sorted(returned_dates))
        self.assertGreaterEqual(returned_dates[0], window_start)
        self.assertLessEqual(returned_dates[-1], _CACHE_TODAY)

    def test_basis_separation_adjusted_cannot_satisfy_raw(self):
        """(ticker, date, auto_adjust) is the cache identity: adjusted
        rows never satisfy a raw request, so the raw path reaches the
        provider with auto_adjust=False."""
        df = _cache_clock_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        with _patched_clock():
            adjusted = market_check._fetch("AAPL")            # aa=1
            self.assertIsNotNone(adjusted)
            self.assertEqual(len(fake.daily_calls), 1)
            start_iso = (_CACHE_TODAY - timedelta(days=30)).isoformat()
            raw = market_check._fetch_since("AAPL", start_iso)  # aa=0
            self.assertIsNotNone(raw)
        self.assertEqual(len(fake.daily_calls), 2)
        self.assertTrue(fake.daily_calls[0]["auto_adjust"])
        self.assertFalse(fake.daily_calls[1]["auto_adjust"])
        _min1, _max1, n_adj = self._sqlite_rows("AAPL", 1)
        _min0, _max0, n_raw = self._sqlite_rows("AAPL", 0)
        self.assertEqual(n_adj, 10)
        self.assertEqual(n_raw, 10)

    def test_clock_shift_invariance(self):
        """The same relative scenario at two Monday anchors years apart
        yields identical call counts, row counts, cache behavior, and
        relative request-window geometry."""
        anchors = (date(2026, 4, 20), date(2030, 4, 22))  # both Mondays
        observed = []
        extra_tmp = None
        try:
            for i, anchor in enumerate(anchors):
                if i > 0:
                    # Fresh SQLite + hot cache for the second anchor.
                    extra_tmp = os.path.join(
                        tempfile.gettempdir(),
                        f"test_price_cache_{uuid.uuid4().hex}.db",
                    )
                    db.DB_FILE = extra_tmp
                    price_cache._reset_table_ready_for_tests()
                    market_check._cache_clear()
                df = _cache_clock_df([100.0] * 10, anchor=anchor)
                fake = _FakeProvider(daily_response=df)
                set_provider(fake)
                with _patched_clock(anchor):
                    r1 = market_check._fetch("AAPL")
                    r2 = market_check._fetch("AAPL")
                call = fake.daily_calls[0]
                observed.append({
                    "rows": None if r1 is None else len(r1),
                    "rows_repeat": None if r2 is None else len(r2),
                    "provider_calls": len(fake.daily_calls),
                    "hot_cache": market_check._cache_len() >= 1,
                    "basis": call["auto_adjust"],
                    "start_offset_days":
                        (anchor - date.fromisoformat(call["start"])).days,
                    "end_offset_days":
                        (date.fromisoformat(call["end"]) - anchor).days,
                })
        finally:
            if extra_tmp and os.path.exists(extra_tmp):
                db.DB_FILE = self._tmp_db
                price_cache._reset_table_ready_for_tests()
                try:
                    os.remove(extra_tmp)
                except PermissionError:
                    pass
        self.assertEqual(observed[0], observed[1])
        self.assertEqual(observed[0]["rows"], 10)
        self.assertEqual(observed[0]["provider_calls"], 1)
        self.assertTrue(observed[0]["hot_cache"])

    def test_shared_state_not_leaked_between_tests(self):
        """The clock seam and provider singleton arrive unpatched, and
        the patch context restores the real seam on exit."""
        self.assertNotIsInstance(price_cache._today, MagicMock)
        with _patched_clock():
            self.assertEqual(price_cache._today(), _CACHE_TODAY)
        self.assertNotIsInstance(price_cache._today, MagicMock)
        self.assertIsNotNone(get_provider())


if __name__ == "__main__":
    unittest.main()
