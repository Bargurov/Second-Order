"""
tests/test_unit_aware_move.py

Focused tests for the unit-aware move layer.

Validates that:
  - UNIT_YIELD tickers (^TNX) compute absolute pp change, not % change.
  - UNIT_PRICE tickers (TIP, GLD) compute standard % change.
  - UNIT_LEVEL tickers (^VIX) compute standard % change.
  - ticker_unit maps known tickers correctly and defaults to UNIT_PRICE.
  - Representative real-world values produce the right magnitudes.
"""

from __future__ import annotations

import os
import sys
import unittest

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_check import (
    compute_move,
    compute_move_forward,
    ticker_unit,
    UNIT_PRICE,
    UNIT_YIELD,
    UNIT_LEVEL,
)


def _series(values: list[float]) -> pd.Series:
    """Build a simple pandas Series from a list."""
    return pd.Series(values, dtype=float)


# ---------------------------------------------------------------------------
# ticker_unit mapping
# ---------------------------------------------------------------------------

class TestTickerUnit(unittest.TestCase):

    def test_yield_tickers(self):
        self.assertEqual(ticker_unit("^TNX"), UNIT_YIELD)
        self.assertEqual(ticker_unit("^FVX"), UNIT_YIELD)
        self.assertEqual(ticker_unit("^TYX"), UNIT_YIELD)
        self.assertEqual(ticker_unit("^IRX"), UNIT_YIELD)

    def test_level_tickers(self):
        self.assertEqual(ticker_unit("^VIX"), UNIT_LEVEL)
        self.assertEqual(ticker_unit("^VIX3M"), UNIT_LEVEL)

    def test_price_tickers_default(self):
        self.assertEqual(ticker_unit("TIP"), UNIT_PRICE)
        self.assertEqual(ticker_unit("GLD"), UNIT_PRICE)
        self.assertEqual(ticker_unit("SPY"), UNIT_PRICE)
        self.assertEqual(ticker_unit("XOM"), UNIT_PRICE)

    def test_case_insensitive(self):
        self.assertEqual(ticker_unit("^tnx"), UNIT_YIELD)
        self.assertEqual(ticker_unit("^vix"), UNIT_LEVEL)


# ---------------------------------------------------------------------------
# compute_move: UNIT_YIELD (^TNX-style)
# ---------------------------------------------------------------------------

class TestComputeMoveYield(unittest.TestCase):
    """Yield series: move is absolute pp change (end − start)."""

    def test_tnx_15bps_move(self):
        """^TNX from 4.30 to 4.45 = +0.15 pp, NOT +3.49%."""
        # 6 values: start at index -6, end at index -1
        s = _series([4.30, 4.32, 4.35, 4.38, 4.42, 4.45])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_tnx_negative_move(self):
        """^TNX from 4.50 to 4.35 = −0.15 pp."""
        s = _series([4.50, 4.48, 4.45, 4.42, 4.38, 4.35])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertAlmostEqual(result, -0.15, places=4)

    def test_tnx_zero_start_still_works(self):
        """Yield at 0.05% (COVID era) to 0.10% = +0.05 pp, not division error."""
        s = _series([0.05, 0.06, 0.07, 0.08, 0.09, 0.10])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.05, places=4)

    def test_tnx_zero_start_price_would_divide_by_zero(self):
        """A yield of exactly 0.00 should still compute (0.10 - 0.00 = 0.10 pp)."""
        s = _series([0.00, 0.02, 0.04, 0.06, 0.08, 0.10])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 0.10, places=4)

    def test_yield_magnitude_sane(self):
        """Representative 5d yield move should be <1.0 pp, not 3-4%."""
        s = _series([4.30, 4.32, 4.35, 4.38, 4.42, 4.45])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertLess(abs(result), 1.0,
                        "Yield move >1.0 pp in 5 days would be extreme")


# ---------------------------------------------------------------------------
# compute_move: UNIT_PRICE (ETF-style)
# ---------------------------------------------------------------------------

class TestComputeMovePrice(unittest.TestCase):
    """Price series: move is standard percent change."""

    def test_tip_pct_change(self):
        """TIP from 110.0 to 111.1 = +1.0%."""
        s = _series([110.0, 110.2, 110.4, 110.6, 110.8, 111.1])
        result = compute_move(s, 5, UNIT_PRICE)
        self.assertAlmostEqual(result, 1.0, places=1)

    def test_gld_negative(self):
        """GLD from 200 to 194 = −3.0%."""
        s = _series([200.0, 199.0, 198.0, 197.0, 196.0, 194.0])
        result = compute_move(s, 5, UNIT_PRICE)
        self.assertAlmostEqual(result, -3.0, places=1)

    def test_zero_start_returns_none(self):
        """Price of 0 should return None (division by zero)."""
        s = _series([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
        result = compute_move(s, 5, UNIT_PRICE)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# compute_move: UNIT_LEVEL (VIX-style)
# ---------------------------------------------------------------------------

class TestComputeMoveLevel(unittest.TestCase):
    """Level series: move is standard percent change (same as price)."""

    def test_vix_spike(self):
        """VIX from 15 to 22.5 = +50%."""
        s = _series([15.0, 16.0, 18.0, 19.5, 21.0, 22.5])
        result = compute_move(s, 5, UNIT_LEVEL)
        self.assertAlmostEqual(result, 50.0, places=1)


# ---------------------------------------------------------------------------
# compute_move_forward (event-anchored mode)
# ---------------------------------------------------------------------------

class TestComputeMoveForward(unittest.TestCase):

    def test_yield_forward(self):
        s = _series([4.30, 4.32, 4.35, 4.38, 4.42, 4.45])
        result = compute_move_forward(s, 5, UNIT_YIELD)
        self.assertAlmostEqual(result, 0.15, places=4)

    def test_price_forward(self):
        s = _series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
        result = compute_move_forward(s, 5, UNIT_PRICE)
        self.assertAlmostEqual(result, 5.0, places=1)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases(unittest.TestCase):

    def test_insufficient_data(self):
        self.assertIsNone(compute_move(_series([1.0]), 5, UNIT_PRICE))
        self.assertIsNone(compute_move(_series([1.0]), 5, UNIT_YIELD))

    def test_none_series(self):
        self.assertIsNone(compute_move(None, 5, UNIT_PRICE))
        self.assertIsNone(compute_move_forward(None, 5, UNIT_YIELD))

    def test_nan_in_series(self):
        s = _series([float("nan"), 1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertIsNone(compute_move(s, 5, UNIT_PRICE))


# ---------------------------------------------------------------------------
# Integration: yield vs price magnitude comparison
# ---------------------------------------------------------------------------

class TestMagnitudeComparison(unittest.TestCase):
    """The whole point: yield and price moves for the same underlying
    data produce different magnitudes, and yield moves are much smaller."""

    def test_tnx_yield_vs_wrong_pct(self):
        """Demonstrate the bug that compute_move prevents.

        ^TNX from 4.30 to 4.45:
          WRONG (_safe_pct / UNIT_PRICE): (4.45-4.30)/4.30 * 100 = +3.49%
          RIGHT (UNIT_YIELD):             4.45 - 4.30             = +0.15 pp

        The wrong value is 23× too large.
        """
        s = _series([4.30, 4.32, 4.35, 4.38, 4.42, 4.45])
        wrong = compute_move(s, 5, UNIT_PRICE)
        right = compute_move(s, 5, UNIT_YIELD)
        self.assertGreater(abs(wrong), abs(right) * 10,
                           "Price-unit result should be >10× the yield-unit result")
        self.assertAlmostEqual(right, 0.15, places=4)

    def test_covid_era_tnx_no_explosion(self):
        """^TNX near zero (0.50 → 0.65 pp) should be +0.15 pp, not +30%."""
        s = _series([0.50, 0.53, 0.55, 0.58, 0.62, 0.65])
        result = compute_move(s, 5, UNIT_YIELD)
        self.assertAlmostEqual(result, 0.15, places=4)
        self.assertLess(abs(result), 1.0)

        # The wrong (price) computation would give +30%
        wrong = compute_move(s, 5, UNIT_PRICE)
        self.assertGreater(abs(wrong), 20.0)


if __name__ == "__main__":
    unittest.main()
