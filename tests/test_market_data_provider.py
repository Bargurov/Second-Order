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
import sys
import tempfile
import unittest
import uuid
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


def _make_df(closes, volumes=None):
    n = len(closes)
    if volumes is None:
        volumes = [1_000_000.0] * n
    dates = pd.date_range("2026-03-01", periods=n, freq="B")
    return pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)


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

class TestMarketCheckDelegation(unittest.TestCase):
    """market_check._fetch and friends should call the active provider."""

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

    def test_fetch_uses_provider(self):
        df = _make_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
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
        """Once a value is cached, the provider should not be called again."""
        df = _make_df([100.0] * 10)
        fake = _FakeProvider(daily_response=df)
        set_provider(fake)
        market_check._fetch("AAPL")
        market_check._fetch("AAPL")
        market_check._fetch("AAPL")
        self.assertEqual(len(fake.daily_calls), 1, "Provider was called more than once")


if __name__ == "__main__":
    unittest.main()
