"""
tests/test_fallback_provider.py

Focused tests for FallbackProvider failover and clean fallback behavior.

  1) Primary succeeds → secondary never called, last_source = "primary".
  2) Primary fails → secondary called, data returned, last_source = "fallback".
  3) Both fail → None returned cleanly.
  4) No secondary configured → primary-only, no crash on None.
  5) fetch_info follows the same pattern.
  6) Unsupported symbols (^-prefix) handled safely through the chain.
"""

from __future__ import annotations

import os
import sys
import unittest
from typing import Optional
from unittest.mock import MagicMock

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data import FallbackProvider, MarketDataProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _df(values: list[float]) -> pd.DataFrame:
    """Build a minimal DataFrame matching the provider contract."""
    idx = pd.date_range("2026-04-01", periods=len(values), freq="B")
    return pd.DataFrame({"Close": values, "Volume": [1e6] * len(values)}, index=idx)


class _StubProvider:
    """Minimal test provider that records calls and returns canned data."""

    def __init__(
        self,
        daily_result: Optional[pd.DataFrame] = None,
        info_result: Optional[dict] = None,
    ):
        self._daily_result = daily_result
        self._info_result = info_result or {
            "symbol": "STUB", "name": None, "sector": None,
            "industry": None, "market_cap": None, "avg_volume": None,
        }
        self.daily_calls: list[str] = []
        self.info_calls: list[str] = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        self.daily_calls.append(ticker)
        return self._daily_result

    def fetch_info(self, ticker):
        self.info_calls.append(ticker)
        return dict(self._info_result)


# ---------------------------------------------------------------------------
# 1) Primary succeeds
# ---------------------------------------------------------------------------

class TestPrimarySucceeds(unittest.TestCase):

    def test_secondary_not_called(self):
        primary = _StubProvider(daily_result=_df([100, 101, 102]))
        secondary = _StubProvider(daily_result=_df([200, 201, 202]))
        fp = FallbackProvider(primary, secondary)

        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(len(primary.daily_calls), 1)
        self.assertEqual(len(secondary.daily_calls), 0)

    def test_last_source_is_primary(self):
        primary = _StubProvider(daily_result=_df([100, 101]))
        fp = FallbackProvider(primary, _StubProvider())

        fp.fetch_daily("AAPL", period="3mo")
        self.assertEqual(fp.last_source, "primary")

    def test_returns_primary_data(self):
        primary_df = _df([100, 101, 102])
        primary = _StubProvider(daily_result=primary_df)
        fp = FallbackProvider(primary, _StubProvider())

        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertEqual(len(result), 3)
        self.assertAlmostEqual(float(result["Close"].iloc[0]), 100.0)


# ---------------------------------------------------------------------------
# 2) Primary fails → fallback
# ---------------------------------------------------------------------------

class TestPrimaryFailsFallback(unittest.TestCase):

    def test_secondary_called_on_primary_none(self):
        primary = _StubProvider(daily_result=None)
        secondary = _StubProvider(daily_result=_df([200, 201]))
        fp = FallbackProvider(primary, secondary)

        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(len(primary.daily_calls), 1)
        self.assertEqual(len(secondary.daily_calls), 1)

    def test_last_source_is_fallback(self):
        primary = _StubProvider(daily_result=None)
        secondary = _StubProvider(daily_result=_df([200, 201]))
        fp = FallbackProvider(primary, secondary)

        fp.fetch_daily("AAPL", period="3mo")
        self.assertEqual(fp.last_source, "fallback")

    def test_returns_secondary_data(self):
        secondary_df = _df([200, 201, 202])
        fp = FallbackProvider(
            _StubProvider(daily_result=None),
            _StubProvider(daily_result=secondary_df),
        )

        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertAlmostEqual(float(result["Close"].iloc[0]), 200.0)


# ---------------------------------------------------------------------------
# 3) Both fail
# ---------------------------------------------------------------------------

class TestBothFail(unittest.TestCase):

    def test_returns_none(self):
        fp = FallbackProvider(
            _StubProvider(daily_result=None),
            _StubProvider(daily_result=None),
        )
        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)

    def test_both_called(self):
        primary = _StubProvider(daily_result=None)
        secondary = _StubProvider(daily_result=None)
        fp = FallbackProvider(primary, secondary)

        fp.fetch_daily("AAPL", period="3mo")
        self.assertEqual(len(primary.daily_calls), 1)
        self.assertEqual(len(secondary.daily_calls), 1)


# ---------------------------------------------------------------------------
# 4) No secondary configured
# ---------------------------------------------------------------------------

class TestNoSecondary(unittest.TestCase):

    def test_primary_only_succeeds(self):
        fp = FallbackProvider(_StubProvider(daily_result=_df([100])), None)
        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(fp.last_source, "primary")

    def test_primary_fails_returns_none(self):
        fp = FallbackProvider(_StubProvider(daily_result=None), None)
        result = fp.fetch_daily("AAPL", period="3mo")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5) fetch_info follows the same pattern
# ---------------------------------------------------------------------------

class TestFetchInfoFallback(unittest.TestCase):

    def test_primary_info_has_name_no_fallback(self):
        primary = _StubProvider(info_result={
            "symbol": "AAPL", "name": "Apple Inc.", "sector": "Tech",
            "industry": None, "market_cap": None, "avg_volume": None,
        })
        secondary = _StubProvider(info_result={
            "symbol": "AAPL", "name": "Apple", "sector": None,
            "industry": None, "market_cap": None, "avg_volume": None,
        })
        fp = FallbackProvider(primary, secondary)
        info = fp.fetch_info("AAPL")
        self.assertEqual(info["name"], "Apple Inc.")
        self.assertEqual(fp.last_source, "primary")
        self.assertEqual(len(secondary.info_calls), 0)

    def test_primary_info_no_name_falls_back(self):
        primary = _StubProvider(info_result={
            "symbol": "AAPL", "name": None, "sector": None,
            "industry": None, "market_cap": None, "avg_volume": None,
        })
        secondary = _StubProvider(info_result={
            "symbol": "AAPL", "name": "Apple via fallback", "sector": None,
            "industry": None, "market_cap": None, "avg_volume": None,
        })
        fp = FallbackProvider(primary, secondary)
        info = fp.fetch_info("AAPL")
        self.assertEqual(info["name"], "Apple via fallback")
        self.assertEqual(fp.last_source, "fallback")

    def test_both_info_empty_returns_primary(self):
        primary = _StubProvider()
        secondary = _StubProvider()
        fp = FallbackProvider(primary, secondary)
        info = fp.fetch_info("AAPL")
        self.assertIsNone(info["name"])


# ---------------------------------------------------------------------------
# 6) Unsupported symbols handled safely
# ---------------------------------------------------------------------------

class TestUnsupportedSymbols(unittest.TestCase):

    def test_caret_ticker_both_return_none(self):
        """^-prefixed tickers should not crash the fallback chain."""
        fp = FallbackProvider(
            _StubProvider(daily_result=None),
            _StubProvider(daily_result=None),
        )
        result = fp.fetch_daily("^VIX", period="3mo")
        self.assertIsNone(result)

    def test_caret_ticker_secondary_success(self):
        """If secondary handles the caret ticker, fallback works."""
        fp = FallbackProvider(
            _StubProvider(daily_result=None),
            _StubProvider(daily_result=_df([20, 21, 22])),
        )
        result = fp.fetch_daily("^VIX", period="3mo")
        self.assertIsNotNone(result)
        self.assertEqual(fp.last_source, "fallback")

    def test_empty_ticker(self):
        fp = FallbackProvider(_StubProvider(daily_result=None), None)
        result = fp.fetch_daily("", period="3mo")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 7) last_source updates correctly across calls
# ---------------------------------------------------------------------------

class TestLastSourceTracking(unittest.TestCase):

    def test_alternating_sources(self):
        """last_source reflects the most recent call, not the first."""
        primary_df = _df([100])
        primary = _StubProvider(daily_result=primary_df)
        secondary = _StubProvider(daily_result=_df([200]))
        fp = FallbackProvider(primary, secondary)

        # First call: primary succeeds
        fp.fetch_daily("AAPL", period="3mo")
        self.assertEqual(fp.last_source, "primary")

        # Now make primary fail
        primary._daily_result = None
        fp.fetch_daily("MSFT", period="3mo")
        self.assertEqual(fp.last_source, "fallback")

        # Primary recovers
        primary._daily_result = primary_df
        fp.fetch_daily("GOOG", period="3mo")
        self.assertEqual(fp.last_source, "primary")


if __name__ == "__main__":
    unittest.main()
