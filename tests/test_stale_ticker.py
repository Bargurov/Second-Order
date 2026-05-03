"""
tests/test_stale_ticker.py

Focused tests for the stale/delisted ticker detection in _check_one_ticker
and its propagation through market_check().

Three scenarios:
  1) Fresh ticker data       → no stale flag
  2) Stale/delisted ticker   → stale=True + last_trade_date
  3) Mixed batch             → only stale tickers flagged, healthy unchanged
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check


# ---------------------------------------------------------------------------
# Helpers — build synthetic DataFrames with controllable last-bar date
# ---------------------------------------------------------------------------

def _make_price_df(last_bar_date: date, n_bars: int = 30,
                   base_price: float = 100.0) -> pd.DataFrame:
    """Build a minimal OHLCV DataFrame whose final row lands on last_bar_date.

    Rows are spaced one calendar day apart (no weekend skipping — test data,
    not real calendar).  Returns are small and realistic.
    """
    dates = pd.date_range(end=last_bar_date, periods=n_bars)
    rng = np.random.default_rng(42)
    closes = base_price + np.cumsum(rng.normal(0, 0.5, n_bars))
    closes = np.maximum(closes, 1.0)  # avoid zero/negative
    df = pd.DataFrame({
        "Open":   closes * 0.999,
        "High":   closes * 1.005,
        "Low":    closes * 0.995,
        "Close":  closes,
        "Volume": rng.integers(1_000_000, 5_000_000, n_bars).astype(float),
    }, index=dates)
    return df


# ---------------------------------------------------------------------------
# 1) Fresh ticker
# ---------------------------------------------------------------------------

class TestFreshTicker(unittest.TestCase):
    """A ticker whose latest bar is today (or yesterday) must not be flagged."""

    def test_fresh_ticker_no_stale_flag(self):
        fresh_df = _make_price_df(last_bar_date=date.today(), base_price=150.0)

        with patch.object(market_check, "_fetch", return_value=fresh_df), \
             patch.object(market_check, "_fetch_since", return_value=fresh_df):
            result = market_check._check_one_ticker("AAPL", role="beneficiary")

        self.assertNotIn("stale", result)
        self.assertNotIn("last_trade_date", result)
        # Direction logic should work normally
        self.assertIn(result["label"],
                      {"notable move", "in motion", "flat", "needs more evidence"})

    def test_fresh_ticker_yesterday(self):
        """One day old is well within the threshold."""
        yesterday = date.today() - timedelta(days=1)
        df = _make_price_df(last_bar_date=yesterday, base_price=200.0)

        with patch.object(market_check, "_fetch", return_value=df):
            result = market_check._check_one_ticker("MSFT", role="beneficiary")

        self.assertNotIn("stale", result)


# ---------------------------------------------------------------------------
# 2) Stale / delisted ticker
# ---------------------------------------------------------------------------

class TestStaleTicker(unittest.TestCase):
    """A ticker whose latest bar is weeks old must be flagged stale."""

    def test_stale_ticker_flagged(self):
        old_date = date.today() - timedelta(days=30)
        df = _make_price_df(last_bar_date=old_date, base_price=50.0)

        with patch.object(market_check, "_fetch", return_value=df):
            result = market_check._check_one_ticker("DLIST", role="beneficiary")

        self.assertTrue(result.get("stale"))
        self.assertEqual(result["last_trade_date"], str(old_date))

    def test_stale_ticker_returns_still_computed(self):
        """Stale flag is additive — return fields should still be present."""
        old_date = date.today() - timedelta(days=15)
        df = _make_price_df(last_bar_date=old_date, n_bars=30, base_price=80.0)

        with patch.object(market_check, "_fetch", return_value=df):
            result = market_check._check_one_ticker("OLD", role="loser")

        self.assertTrue(result.get("stale"))
        # Returns computed from the available data — not nulled
        self.assertIsNotNone(result.get("return_5d"))
        self.assertIsNotNone(result.get("return_1d"))

    def test_stale_at_boundary(self):
        """Exactly at the threshold (5 days) should NOT be stale (> not >=)."""
        boundary_date = date.today() - timedelta(days=market_check._STALE_TICKER_CALENDAR_DAYS)
        df = _make_price_df(last_bar_date=boundary_date, base_price=100.0)

        with patch.object(market_check, "_fetch", return_value=df):
            result = market_check._check_one_ticker("EDGE", role="beneficiary")

        self.assertNotIn("stale", result)

    def test_stale_one_day_past_boundary(self):
        """One day past the threshold should be stale."""
        past_boundary = date.today() - timedelta(
            days=market_check._STALE_TICKER_CALENDAR_DAYS + 1,
        )
        df = _make_price_df(last_bar_date=past_boundary, base_price=100.0)

        with patch.object(market_check, "_fetch", return_value=df):
            result = market_check._check_one_ticker("PAST", role="beneficiary")

        self.assertTrue(result.get("stale"))


# ---------------------------------------------------------------------------
# 3) Mixed batch — market_check() propagation
# ---------------------------------------------------------------------------

class TestMixedBatch(unittest.TestCase):
    """market_check() with a mix of fresh and stale tickers."""

    def _run_mixed(self):
        # Each ticker gets a distinct base_price so _suppress_duplicate_tickers
        # doesn't flag them as cross-contaminated (identical spark + return_5d).
        aapl_df = _make_price_df(last_bar_date=date.today(), base_price=150.0)
        goog_df = _make_price_df(last_bar_date=date.today(), base_price=2800.0)
        stale_df = _make_price_df(
            last_bar_date=date.today() - timedelta(days=30),
            base_price=50.0,
        )

        def fake_fetch(ticker):
            t = ticker.upper()
            if t == "AAPL":
                return aapl_df
            if t == "GOOG":
                return goog_df
            if t == "DLIST":
                return stale_df
            return None

        with patch.object(market_check, "_fetch", side_effect=fake_fetch), \
             patch.object(market_check, "_fetch_since", side_effect=fake_fetch):
            return market_check.market_check(
                beneficiary_tickers=["AAPL"],
                loser_tickers=["GOOG", "DLIST"],
            )

    def test_stale_propagated_to_ticker_list(self):
        mkt = self._run_mixed()
        dlist = next(
            (t for t in mkt["tickers"] if t["symbol"] == "DLIST"), None,
        )
        self.assertIsNotNone(dlist, "DLIST should be in tickers list")
        self.assertTrue(dlist.get("stale"))
        self.assertIsNotNone(dlist.get("last_trade_date"))

    def test_fresh_tickers_unaffected(self):
        mkt = self._run_mixed()
        aapl = next(
            (t for t in mkt["tickers"] if t["symbol"] == "AAPL"), None,
        )
        self.assertIsNotNone(aapl)
        self.assertNotIn("stale", aapl)
        # Returns should be populated for a fresh ticker
        self.assertIsNotNone(aapl.get("return_5d"))

    def test_fresh_ticker_returns_intact(self):
        """Stale ticker in the batch must not corrupt healthy ticker returns."""
        mkt = self._run_mixed()
        goog = next(
            (t for t in mkt["tickers"] if t["symbol"] == "GOOG"), None,
        )
        self.assertIsNotNone(goog)
        self.assertIsNotNone(goog.get("return_5d"))
        self.assertNotIn("stale", goog)


if __name__ == "__main__":
    unittest.main()
