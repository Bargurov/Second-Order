"""
Tests for sanity caps on macro overlay values.

Covers:
- TIP 5d percent change capped at ±10% (prevents +1750% from corrupt data)
- VIX 5d percent change capped at ±200% (prevents +220% from stub rows)
- Haven assets (GLD, DXY, TLT) capped at ±20%
- Normal values pass through unchanged
- Breakeven proxy inherits TIP cap (nominal_pp + tip_pct/duration)
"""

import os
import sys
import unittest
from unittest.mock import patch

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _make_df(prices, start="2026-01-01", length=None):
    if length is None:
        length = len(prices)
    dates = pd.date_range(start, periods=length, freq="B")
    return pd.DataFrame({
        "Close": prices[:length],
        "Volume": [1e6] * length,
    }, index=dates)


class TestTipSanityCap(unittest.TestCase):
    """TIP 5d percent change beyond ±10% is discarded."""

    @patch("market_check._fetch")
    def test_tip_implausible_move_discarded(self, mock_fetch):
        """TIP going from 0.06 to 1.11 would produce +1750% — must be None."""
        # Simulate corrupt cache: 25 bars, last 6 show huge jump
        prices = [0.06] * 19 + [0.06, 0.2, 0.5, 0.8, 1.0, 1.11]
        tnx_prices = [4.5] * 25  # stable TNX

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(tnx_prices)
            if sym == "TIP":
                return _make_df(prices)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        tip_5d = (result.get("real_proxy") or {}).get("change_5d")
        self.assertIsNone(tip_5d, f"TIP 5d should be None for implausible move, got {tip_5d}")

    @patch("market_check._fetch")
    def test_tip_normal_move_passes(self, mock_fetch):
        """Normal TIP move (~0.5%) passes through."""
        prices = [107.0 + i * 0.01 for i in range(25)]  # tiny trend
        tnx_prices = [4.5] * 25

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(tnx_prices)
            if sym == "TIP":
                return _make_df(prices)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        tip_5d = (result.get("real_proxy") or {}).get("change_5d")
        self.assertIsNotNone(tip_5d)
        self.assertLess(abs(tip_5d), 10.0)


class TestVixSanityCap(unittest.TestCase):
    """VIX 5d change beyond ±200% is discarded."""

    @patch("market_check._fetch")
    def test_vix_implausible_spike_discarded(self, mock_fetch):
        """VIX from 5 to 20 = +300% — must be discarded."""
        prices = [5.0] * 19 + [5.0, 8.0, 12.0, 16.0, 18.0, 20.0]

        mock_fetch.return_value = _make_df(prices)
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        vix_5d = result.get("raw", {}).get("vix_change_5d")
        self.assertIsNone(vix_5d, f"VIX 5d should be None for +300% move, got {vix_5d}")

    @patch("market_check._fetch")
    def test_vix_normal_spike_passes(self, mock_fetch):
        """VIX from 15 to 25 = +66% — should pass (2020-level spike)."""
        prices = [15.0] * 19 + [15.0, 17.0, 19.0, 21.0, 23.0, 25.0]

        mock_fetch.return_value = _make_df(prices)
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        vix_5d = result.get("raw", {}).get("vix_change_5d")
        self.assertIsNotNone(vix_5d)
        self.assertAlmostEqual(vix_5d, 66.67, places=0)


class TestHavenSanityCap(unittest.TestCase):
    """Haven asset 5d moves beyond ±20% are discarded."""

    @patch("market_check._fetch")
    def test_haven_corrupt_start_discarded(self, mock_fetch):
        """GLD start price 1.0 is below _PRICE_FLOORS["GLD"][0] = 80 —
        _validated_pct rejects it and the return is None."""
        def _side(sym, *a, **kw):
            if sym == "GLD":
                prices = [1.0] * 19 + [1.0, 2.0, 4.0, 6.0, 8.0, 10.0]
                return _make_df(prices)
            # Normal data for others
            prices = [100.0 + i * 0.05 for i in range(25)]
            return _make_df(prices)

        mock_fetch.side_effect = _side
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        haven = result.get("detail", {}).get("safe_haven", {})
        assets = haven.get("assets", {})
        self.assertIsNone(assets.get("Gold"),
                          "GLD start price 1.0 is below _PRICE_FLOORS floor — should be None")

    @patch("market_check._fetch")
    def test_haven_normal_move_passes(self, mock_fetch):
        """GLD +2% is normal and should pass through."""
        def _side(sym, *a, **kw):
            if sym == "GLD":
                prices = [180.0] * 19 + [180.0, 181.0, 182.0, 183.0, 183.5, 183.6]
                return _make_df(prices)
            prices = [100.0 + i * 0.05 for i in range(25)]
            return _make_df(prices)

        mock_fetch.side_effect = _side
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        haven = result.get("detail", {}).get("safe_haven", {})
        assets = haven.get("assets", {})
        gold = assets.get("Gold")
        self.assertIsNotNone(gold)
        self.assertLess(abs(gold), 20.0)


class TestBreakevenProxyCap(unittest.TestCase):
    """Breakeven proxy = nominal_pp + tip_pct — if TIP is capped, BE is clean."""

    @patch("market_check._fetch")
    def test_be_proxy_clean_when_tip_capped(self, mock_fetch):
        """When TIP move is implausible, breakeven proxy should be None."""
        corrupt_tip = [0.06] * 19 + [0.06, 0.2, 0.5, 0.8, 1.0, 1.11]
        normal_tnx = [4.50] * 25

        def _side(sym, *a, **kw):
            if sym == "^TNX":
                return _make_df(normal_tnx)
            if sym == "TIP":
                return _make_df(corrupt_tip)
            return None

        mock_fetch.side_effect = _side
        from market_check import compute_rates_context
        result = compute_rates_context()

        be_5d = (result.get("breakeven_proxy") or {}).get("change_5d")
        # TIP was capped to None, so breakeven = nominal + None = None
        self.assertIsNone(be_5d)


if __name__ == "__main__":
    unittest.main()
