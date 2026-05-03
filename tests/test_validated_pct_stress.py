"""
tests/test_validated_pct_stress.py

Focused tests for _validated_pct replacing _safe_pct in compute_stress_regime.

Goal: corrupt/stub price rows (e.g. HYG at $0.50 from a bad cache row) must
not produce false stress signals.  Normal live data behavior must be unchanged.

Four scenarios:
  1) Credit inputs: corrupt HYG/SHY start prices → signal does not fire
  2) Safe-haven inputs: corrupt GLD/DXY/TLT start prices → signal does not fire
  3) Breadth inputs: corrupt RSP/SPY start prices → signal does not fire
  4) Regression: normal plausible data produces correct values unchanged
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_df(prices):
    dates = pd.date_range("2026-01-01", periods=len(prices), freq="B")
    return pd.DataFrame({"Close": prices, "Volume": [1e6] * len(prices)}, index=dates)


_DEFAULTS = {
    "^VIX":     [18.0] * 25,
    "^VIX3M":   [20.0] * 25,
    "HYG":      [75.0] * 25,
    "SHY":      [82.0] * 25,
    "GLD":      [230.0] * 25,
    "DX-Y.NYB": [104.0] * 25,
    "TLT":      [92.0] * 25,
    "RSP":      [170.0] * 25,
    "SPY":      [530.0] * 25,
}


def _side(overrides):
    def _fn(sym, *a, **kw):
        prices = overrides.get(sym) or _DEFAULTS.get(sym) or [100.0] * 25
        return _make_df(prices)
    return _fn


# ---------------------------------------------------------------------------
# 1) Credit inputs: corrupt start prices are rejected
# ---------------------------------------------------------------------------

class TestCreditCorruptRejected(unittest.TestCase):

    @patch("market_check._fetch")
    def test_corrupt_hyg_start_gives_none(self, mock_fetch):
        """HYG start price of $0.50 (below 40.0 floor) → hyg_5d = None → no signal."""
        # Build series where the start price (index -6) is $0.50 (corrupt),
        # end price is $1.50 — would give +200% under _safe_pct but must be None.
        corrupt = [0.50] * 19 + [0.50, 0.80, 1.00, 1.20, 1.40, 1.50]
        mock_fetch.side_effect = _side({"HYG": corrupt})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        # Signal must not fire from corrupt data
        self.assertFalse(result["signals"]["credit_widening"],
                         "corrupt HYG start price must not trigger credit_widening")
        # raw should have no credit_spread_5d (or None)
        self.assertIsNone(result["raw"].get("credit_spread_5d"))

    @patch("market_check._fetch")
    def test_corrupt_shy_start_gives_none(self, mock_fetch):
        """SHY start price of $200 (above 110.0 ceiling) → shy_5d = None → no false spread."""
        corrupt_shy = [200.0] * 19 + [200.0, 198.0, 197.0, 196.0, 195.0, 194.0]
        # HYG is normal — fell slightly (would create a real credit stress signal if SHY were valid)
        hyg_stress = [75.0] * 19 + [75.0, 74.5, 74.0, 73.5, 73.0, 73.5]
        mock_fetch.side_effect = _side({"SHY": corrupt_shy, "HYG": hyg_stress})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        # shy_5d = None because start is out of range → spread = None → no signal
        self.assertFalse(result["signals"]["credit_widening"],
                         "corrupt SHY start price must not trigger credit_widening")
        self.assertIsNone(result["raw"].get("credit_spread_5d"))

    @patch("market_check._fetch")
    def test_normal_credit_range_accepted(self, mock_fetch):
        """HYG start $75 (in range), SHY start $82 (in range) → spread computed normally."""
        mock_fetch.side_effect = _side({
            "HYG": [75.0] * 19 + [75.0, 74.7, 74.4, 74.2, 73.9, 73.88],
            "SHY": [82.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        spread = result["raw"].get("credit_spread_5d")
        self.assertIsNotNone(spread, "normal price range must produce a spread value")
        self.assertLess(abs(spread), 10.0)


# ---------------------------------------------------------------------------
# 2) Safe-haven inputs: corrupt start prices are rejected
# ---------------------------------------------------------------------------

class TestSafeHavenCorruptRejected(unittest.TestCase):

    @patch("market_check._fetch")
    def test_corrupt_gld_start_rejected(self, mock_fetch):
        """GLD start $5 (below 80.0 floor) → return = None → not counted as inflow."""
        corrupt_gld = [5.0] * 19 + [5.0, 6.0, 7.0, 8.0, 9.0, 10.0]  # +100% if not blocked
        mock_fetch.side_effect = _side({"GLD": corrupt_gld})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        assets = result["detail"]["safe_haven"]["assets"]
        self.assertIsNone(assets.get("Gold"),
                          "corrupt GLD start must yield None, not a +100% inflow")
        # All other havens are flat → no safe_haven_bid
        self.assertFalse(result["signals"]["safe_haven_bid"])

    @patch("market_check._fetch")
    def test_corrupt_tlt_start_rejected(self, mock_fetch):
        """TLT start $300 (above 200.0 ceiling) → return = None → not counted."""
        corrupt_tlt = [300.0] * 19 + [300.0, 295.0, 292.0, 290.0, 288.0, 285.0]
        mock_fetch.side_effect = _side({"TLT": corrupt_tlt})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        assets = result["detail"]["safe_haven"]["assets"]
        self.assertIsNone(assets.get("Long Bonds"),
                          "corrupt TLT start must yield None, not a large return")

    @patch("market_check._fetch")
    def test_corrupt_dxy_start_rejected(self, mock_fetch):
        """DXY start $10 (below 60.0 floor) → return = None."""
        corrupt_dxy = [10.0] * 19 + [10.0, 11.0, 12.0, 12.5, 13.0, 14.0]
        mock_fetch.side_effect = _side({"DX-Y.NYB": corrupt_dxy})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        assets = result["detail"]["safe_haven"]["assets"]
        self.assertIsNone(assets.get("Dollar"),
                          "corrupt DXY start must yield None, not +40% inflow")

    @patch("market_check._fetch")
    def test_all_haven_corrupt_no_signal(self, mock_fetch):
        """All three haven tickers corrupt → no safe_haven_bid signal."""
        mock_fetch.side_effect = _side({
            "GLD":      [5.0] * 19 + [5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
            "DX-Y.NYB": [10.0] * 19 + [10.0, 11.0, 12.0, 13.0, 14.0, 15.0],
            "TLT":      [300.0] * 19 + [300.0, 295.0, 290.0, 285.0, 280.0, 285.0],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertFalse(result["signals"]["safe_haven_bid"],
                         "all corrupt haven prices must not fire safe_haven_bid")
        # haven_avg_5d should be absent or None (no valid returns to average)
        self.assertIsNone(result["raw"].get("haven_avg_5d"))

    @patch("market_check._fetch")
    def test_normal_haven_range_accepted(self, mock_fetch):
        """All haven tickers in normal range → returns computed and signal can fire."""
        mock_fetch.side_effect = _side({
            "GLD":      [230.0] * 19 + [230.0, 231.0, 232.0, 233.0, 234.0, 232.3],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.2, 104.4, 104.5, 104.6, 104.52],
            "TLT":      [92.0] * 19 + [92.0, 92.2, 92.4, 92.5, 92.6, 92.46],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        assets = result["detail"]["safe_haven"]["assets"]
        for name in ("Gold", "Dollar", "Long Bonds"):
            self.assertIsNotNone(assets.get(name),
                                 f"{name} should be computed with normal price range")


# ---------------------------------------------------------------------------
# 3) Breadth inputs: corrupt start prices are rejected
# ---------------------------------------------------------------------------

class TestBreadthCorruptRejected(unittest.TestCase):

    @patch("market_check._fetch")
    def test_corrupt_rsp_start_rejected(self, mock_fetch):
        """RSP start $10 (below 50.0 floor) → rsp_5d = None → no breadth signal."""
        corrupt_rsp = [10.0] * 19 + [10.0, 9.0, 8.5, 8.0, 7.5, 7.0]  # −30% if not blocked
        mock_fetch.side_effect = _side({"RSP": corrupt_rsp})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertFalse(result["signals"]["breadth_deterioration"],
                         "corrupt RSP start must not fire breadth_deterioration")
        self.assertIsNone(result["raw"].get("breadth_gap_5d"))

    @patch("market_check._fetch")
    def test_corrupt_spy_start_rejected(self, mock_fetch):
        """SPY start $50 (below 150.0 floor) → spy_5d = None → no gap computed."""
        corrupt_spy = [50.0] * 19 + [50.0, 51.0, 52.0, 53.0, 54.0, 55.0]
        # RSP normal but slightly down — would look like deterioration if SPY were valid
        rsp_normal = [170.0] * 19 + [170.0, 169.5, 169.0, 168.5, 168.0, 168.3]
        mock_fetch.side_effect = _side({"SPY": corrupt_spy, "RSP": rsp_normal})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertFalse(result["signals"]["breadth_deterioration"],
                         "corrupt SPY start must not produce a false breadth gap")
        self.assertIsNone(result["raw"].get("breadth_gap_5d"))

    @patch("market_check._fetch")
    def test_normal_breadth_range_accepted(self, mock_fetch):
        """RSP $170 and SPY $530 both in range → gap computed normally."""
        mock_fetch.side_effect = _side({
            "RSP": [170.0] * 19 + [170.0, 169.5, 169.0, 168.5, 168.0, 168.3],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        gap = result["raw"].get("breadth_gap_5d")
        self.assertIsNotNone(gap, "normal price range must produce a gap value")
        self.assertLess(abs(gap), 10.0)


# ---------------------------------------------------------------------------
# 4) Regression: normal plausible data behavior unchanged
# ---------------------------------------------------------------------------

class TestNormalDataRegression(unittest.TestCase):
    """All clean data with plausible prices must produce correct signals,
    identical to the old _safe_pct behavior (no regression)."""

    @patch("market_check._fetch")
    def test_credit_widening_fires_on_clean_data(self, mock_fetch):
        """HYG down 1.3%, SHY flat → spread > 0.5 → signal fires."""
        mock_fetch.side_effect = _side({
            "HYG": [75.0] * 19 + [75.0, 74.7, 74.5, 74.3, 74.1, 74.0],
            "SHY": [82.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        spread = result["raw"].get("credit_spread_5d")
        self.assertIsNotNone(spread)
        self.assertGreater(spread, 0.5)
        self.assertTrue(result["signals"]["credit_widening"])

    @patch("market_check._fetch")
    def test_safe_haven_bid_fires_on_clean_data(self, mock_fetch):
        """All three havens avg ~1.83% → safe_haven_bid fires (threshold 1.5pp)."""
        mock_fetch.side_effect = _side({
            "GLD":      [230.0] * 19 + [230.0, 231.5, 233.0, 235.0, 237.0, 238.05],
            "DX-Y.NYB": [104.0] * 19 + [104.0, 104.1, 104.2, 104.3, 104.4, 104.52],
            "TLT":      [92.0] * 19 + [92.0, 92.3, 92.5, 92.8, 93.1, 93.38],
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertIsNotNone(result["raw"].get("haven_avg_5d"))
        self.assertGreater(result["raw"]["haven_avg_5d"], 1.5)
        self.assertTrue(result["signals"]["safe_haven_bid"])

    @patch("market_check._fetch")
    def test_breadth_deterioration_fires_on_clean_data(self, mock_fetch):
        """RSP -2.0%, SPY flat → gap < -1.5 → signal fires (threshold raised from -0.5)."""
        mock_fetch.side_effect = _side({
            "RSP": [170.0] * 19 + [170.0, 169.0, 168.0, 167.0, 166.4, 166.6],
            "SPY": [530.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        gap = result["raw"].get("breadth_gap_5d")
        self.assertIsNotNone(gap)
        self.assertLess(gap, -1.5)
        self.assertTrue(result["signals"]["breadth_deterioration"])

    @patch("market_check._fetch")
    def test_all_flat_stays_calm(self, mock_fetch):
        """All tickers flat → no stress signals → Calm regime."""
        mock_fetch.side_effect = _side({})
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertFalse(result["signals"]["credit_widening"])
        self.assertFalse(result["signals"]["safe_haven_bid"])
        self.assertFalse(result["signals"]["breadth_deterioration"])
        self.assertEqual(result["regime"], "Calm")

    @patch("market_check._fetch")
    def test_boundary_price_accepted(self, mock_fetch):
        """Start price exactly at floor boundary must be accepted, not rejected."""
        # HYG floor is 40.0 — start price of exactly 40.0 should pass
        mock_fetch.side_effect = _side({
            "HYG": [40.0] * 19 + [40.0, 39.8, 39.6, 39.4, 39.2, 39.0],
            "SHY": [82.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        # With start=40.0 exactly on the boundary, _validated_pct should accept it
        # (40.0 <= start <= 120.0 is True)
        spread = result["raw"].get("credit_spread_5d")
        self.assertIsNotNone(spread, "start price at exact floor boundary must be accepted")

    @patch("market_check._fetch")
    def test_price_just_below_floor_rejected(self, mock_fetch):
        """Start price just below floor (39.9 < 40.0) must be rejected."""
        mock_fetch.side_effect = _side({
            "HYG": [39.9] * 19 + [39.9, 40.5, 41.0, 41.5, 42.0, 43.0],
            "SHY": [82.0] * 25,
        })
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertIsNone(result["raw"].get("credit_spread_5d"),
                          "start price 39.9 just below HYG floor must be rejected")


if __name__ == "__main__":
    unittest.main()
