"""
Tests for NaN/non-finite guards in market_check.py.

Covers:
- _safe_pct returns None (not NaN) when series contains NaN values
- _pct and _pct_forward return None for NaN inputs
- _direction_tag returns None for NaN/non-finite r5
- _is_finite correctly classifies edge cases
- compute_stress_regime doesn't leak NaN into raw/signals/detail
- Clean numeric inputs still produce correct results (regression)
"""

import math
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_check import (
    _is_finite,
    _pct,
    _pct_forward,
    _safe_pct,
    _direction_tag,
)


# ---------------------------------------------------------------------------
# _is_finite
# ---------------------------------------------------------------------------

class TestIsFinite(unittest.TestCase):

    def test_normal_float(self):
        self.assertTrue(_is_finite(3.14))

    def test_zero(self):
        self.assertTrue(_is_finite(0.0))

    def test_negative(self):
        self.assertTrue(_is_finite(-42.0))

    def test_nan(self):
        self.assertFalse(_is_finite(float("nan")))

    def test_inf(self):
        self.assertFalse(_is_finite(float("inf")))

    def test_neg_inf(self):
        self.assertFalse(_is_finite(float("-inf")))

    def test_none(self):
        self.assertFalse(_is_finite(None))

    def test_string(self):
        self.assertFalse(_is_finite("abc"))

    def test_numpy_nan(self):
        self.assertFalse(_is_finite(np.nan))

    def test_numpy_inf(self):
        self.assertFalse(_is_finite(np.inf))


# ---------------------------------------------------------------------------
# _pct
# ---------------------------------------------------------------------------

class TestPct(unittest.TestCase):

    def _series(self, values):
        return pd.Series(values, dtype=float)

    def test_clean_5d_change(self):
        # 100 -> 110 = +10%
        s = self._series([100, 101, 102, 103, 104, 110])
        result = _pct(s, 5)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 10.0, places=2)

    def test_nan_at_end(self):
        s = self._series([100, 101, 102, 103, 104, float("nan")])
        self.assertIsNone(_pct(s, 5))

    def test_nan_at_start(self):
        s = self._series([float("nan"), 101, 102, 103, 104, 110])
        self.assertIsNone(_pct(s, 5))

    def test_inf_at_end(self):
        s = self._series([100, 101, 102, 103, 104, float("inf")])
        self.assertIsNone(_pct(s, 5))

    def test_zero_start(self):
        s = self._series([0, 1, 2, 3, 4, 5])
        self.assertIsNone(_pct(s, 5))

    def test_insufficient_data(self):
        s = self._series([100, 110])
        self.assertIsNone(_pct(s, 5))


# ---------------------------------------------------------------------------
# _pct_forward
# ---------------------------------------------------------------------------

class TestPctForward(unittest.TestCase):

    def _series(self, values):
        return pd.Series(values, dtype=float)

    def test_clean_forward_change(self):
        # 100 -> 115 = +15%
        s = self._series([100, 105, 110, 112, 114, 115])
        result = _pct_forward(s, 5)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 15.0, places=2)

    def test_nan_at_anchor(self):
        s = self._series([float("nan"), 105, 110, 112, 114, 115])
        self.assertIsNone(_pct_forward(s, 5))

    def test_nan_at_target(self):
        s = self._series([100, 105, 110, 112, 114, float("nan")])
        self.assertIsNone(_pct_forward(s, 5))

    def test_inf_at_anchor(self):
        s = self._series([float("inf"), 105, 110, 112, 114, 115])
        self.assertIsNone(_pct_forward(s, 5))


# ---------------------------------------------------------------------------
# _safe_pct
# ---------------------------------------------------------------------------

class TestSafePct(unittest.TestCase):

    def _series(self, values):
        return pd.Series(values, dtype=float)

    def test_clean_change(self):
        s = self._series([100, 101, 102, 103, 104, 105])
        result = _safe_pct(s, 5)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 5.0, places=2)

    def test_nan_at_end_returns_none(self):
        """The core regression: _safe_pct must return None, not NaN."""
        s = self._series([100, 101, 102, 103, 104, float("nan")])
        result = _safe_pct(s, 5)
        self.assertIsNone(result, "_safe_pct must return None when end value is NaN")

    def test_nan_at_start_returns_none(self):
        s = self._series([float("nan"), 101, 102, 103, 104, 105])
        result = _safe_pct(s, 5)
        self.assertIsNone(result)

    def test_inf_returns_none(self):
        s = self._series([100, 101, 102, 103, 104, float("inf")])
        result = _safe_pct(s, 5)
        self.assertIsNone(result)

    def test_neg_inf_returns_none(self):
        s = self._series([float("-inf"), 101, 102, 103, 104, 105])
        result = _safe_pct(s, 5)
        self.assertIsNone(result)

    def test_zero_start_returns_none(self):
        s = self._series([0, 1, 2, 3, 4, 5])
        result = _safe_pct(s, 5)
        self.assertIsNone(result)

    def test_numpy_nan_returns_none(self):
        s = self._series([100, 101, 102, 103, 104, np.nan])
        result = _safe_pct(s, 5)
        self.assertIsNone(result)

    def test_none_series(self):
        self.assertIsNone(_safe_pct(None, 5))

    def test_insufficient_data(self):
        s = self._series([100])
        self.assertIsNone(_safe_pct(s, 5))

    def test_negative_change(self):
        s = self._series([200, 190, 180, 170, 160, 150])
        result = _safe_pct(s, 5)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, -25.0, places=2)


# ---------------------------------------------------------------------------
# _direction_tag
# ---------------------------------------------------------------------------

class TestDirectionTag(unittest.TestCase):

    def test_beneficiary_positive_supports(self):
        self.assertEqual(_direction_tag(5.0, "beneficiary"), "supports ↑")

    def test_beneficiary_negative_contradicts(self):
        self.assertEqual(_direction_tag(-5.0, "beneficiary"), "contradicts ↓")

    def test_loser_negative_supports(self):
        self.assertEqual(_direction_tag(-5.0, "loser"), "supports ↓")

    def test_loser_positive_contradicts(self):
        self.assertEqual(_direction_tag(5.0, "loser"), "contradicts ↑")

    def test_flat_returns_none(self):
        self.assertIsNone(_direction_tag(0.3, "beneficiary"))

    def test_none_returns_none(self):
        self.assertIsNone(_direction_tag(None, "beneficiary"))

    def test_nan_returns_none(self):
        """NaN must NOT produce a contradicts tag."""
        result = _direction_tag(float("nan"), "beneficiary")
        self.assertIsNone(result, "NaN should return None, not a direction tag")

    def test_inf_returns_none(self):
        result = _direction_tag(float("inf"), "beneficiary")
        self.assertIsNone(result)

    def test_neg_inf_returns_none(self):
        result = _direction_tag(float("-inf"), "loser")
        self.assertIsNone(result)

    def test_numpy_nan_returns_none(self):
        result = _direction_tag(np.nan, "beneficiary")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# compute_stress_regime — NaN isolation
# ---------------------------------------------------------------------------

class TestStressRegimeNanIsolation(unittest.TestCase):
    """Verify that NaN from yfinance doesn't leak into stress regime output."""

    def _make_nan_data(self, length=25):
        """Build a DataFrame whose Close column is all NaN."""
        dates = pd.date_range("2026-01-01", periods=length)
        return pd.DataFrame({
            "Close": [float("nan")] * length,
            "Volume": [0] * length,
        }, index=dates)

    def _make_clean_data(self, base=20.0, length=25):
        """Build a DataFrame with clean ascending prices."""
        dates = pd.date_range("2026-01-01", periods=length)
        return pd.DataFrame({
            "Close": [base + i * 0.1 for i in range(length)],
            "Volume": [1000000] * length,
        }, index=dates)

    @patch("market_check._fetch")
    def test_all_nan_data_produces_no_nan_in_raw(self, mock_fetch):
        """When every ticker returns NaN data, raw dict must not contain NaN."""
        mock_fetch.return_value = self._make_nan_data()
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        for key, val in result.get("raw", {}).items():
            if isinstance(val, float):
                self.assertFalse(
                    math.isnan(val),
                    f"raw['{key}'] is NaN — must be None or omitted",
                )

    @patch("market_check._fetch")
    def test_all_nan_data_signals_all_false(self, mock_fetch):
        """NaN data must not accidentally trigger any stress signal."""
        mock_fetch.return_value = self._make_nan_data()
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        for sig_name, sig_val in result.get("signals", {}).items():
            self.assertFalse(
                sig_val,
                f"Signal '{sig_name}' should be False when data is NaN",
            )

    @patch("market_check._fetch")
    def test_clean_data_still_works(self, mock_fetch):
        """Clean data must still produce a valid regime dict."""
        mock_fetch.return_value = self._make_clean_data()
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertIn("regime", result)
        self.assertIn("signals", result)
        self.assertIn("detail", result)
        self.assertIsInstance(result["regime"], str)

    @patch("market_check._fetch")
    def test_mixed_nan_and_clean_no_nan_leak(self, mock_fetch):
        """When some tickers return NaN and some clean, no NaN in output."""
        nan_data = self._make_nan_data()
        clean_data = self._make_clean_data()

        def _side_effect(sym, *a, **kw):
            # VIX gets NaN, everything else clean
            if sym == "^VIX":
                return nan_data
            return clean_data

        mock_fetch.side_effect = _side_effect
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        for key, val in result.get("raw", {}).items():
            if isinstance(val, float):
                self.assertFalse(
                    math.isnan(val),
                    f"raw['{key}'] is NaN in mixed scenario",
                )

    @patch("market_check._fetch")
    def test_nan_vix_falls_to_except_branch(self, mock_fetch):
        """NaN VIX data should cause the volatility signal to fail gracefully."""
        mock_fetch.return_value = self._make_nan_data()
        from market_check import compute_stress_regime
        result = compute_stress_regime()
        # Volatility detail should exist (from except or data-unavailable branch)
        self.assertIn("volatility", result.get("detail", {}))


# ---------------------------------------------------------------------------
# Partial-failure isolation & logging in compute_stress_regime
# ---------------------------------------------------------------------------

class TestStressRegimePartialFailure(unittest.TestCase):
    """One broken signal must not kill the entire stress computation."""

    def _make_clean_data(self, base=20.0, length=25):
        dates = pd.date_range("2026-01-01", periods=length)
        return pd.DataFrame({
            "Close": [base + i * 0.1 for i in range(length)],
            "Volume": [1000000] * length,
        }, index=dates)

    @patch("market_check._fetch")
    def test_vix_failure_does_not_kill_other_signals(self, mock_fetch):
        """If ^VIX raises, the other 4 signals should still compute."""
        clean = self._make_clean_data()

        def _side(sym, *a, **kw):
            if sym in ("^VIX", "^VIX3M"):
                raise ConnectionError("yfinance timeout")
            return clean

        mock_fetch.side_effect = _side
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        # Volatility and term structure should be in failed/fallback state
        self.assertIn("volatility", result["detail"])
        self.assertIn("term_structure", result["detail"])
        # Credit, safe haven, breadth should still have computed values
        self.assertIn("credit", result["detail"])
        self.assertIn("safe_haven", result["detail"])
        self.assertIn("breadth", result["detail"])
        # Overall result is still a valid dict
        self.assertIn("regime", result)

    @patch("market_check._fetch")
    def test_credit_failure_isolated(self, mock_fetch):
        """If HYG/SHY fail, other signals proceed."""
        clean = self._make_clean_data()

        def _side(sym, *a, **kw):
            if sym in ("HYG", "SHY"):
                raise RuntimeError("data unavailable")
            return clean

        mock_fetch.side_effect = _side
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        self.assertIn("credit", result["detail"])
        # VIX should still work
        vol_detail = result["detail"].get("volatility", {})
        self.assertIsNotNone(vol_detail.get("value"))

    @patch("market_check._fetch")
    def test_failed_signals_logged(self, mock_fetch):
        """Failed signals must be logged, not silently swallowed."""
        def _side(sym, *a, **kw):
            raise ConnectionError(f"mock failure for {sym}")

        mock_fetch.side_effect = _side
        from market_check import compute_stress_regime

        with self.assertLogs("second_order.market", level="ERROR") as cm:
            result = compute_stress_regime()

        # Should have logged errors for each failed signal
        log_text = "\n".join(cm.output)
        self.assertIn("volatility", log_text)
        self.assertIn("credit", log_text)

    @patch("market_check._fetch")
    def test_all_detail_keys_present_on_total_failure(self, mock_fetch):
        """Even if every fetch fails, all 5 detail keys must be present."""
        mock_fetch.side_effect = ConnectionError("total failure")
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        for key in ("volatility", "term_structure", "credit", "safe_haven", "breadth"):
            self.assertIn(key, result["detail"], f"detail['{key}'] missing on total failure")

    @patch("market_check._fetch")
    def test_all_signals_false_on_total_failure(self, mock_fetch):
        """Total failure should not accidentally trigger any signal."""
        mock_fetch.side_effect = ConnectionError("total failure")
        from market_check import compute_stress_regime
        result = compute_stress_regime()

        for sig, val in result["signals"].items():
            self.assertFalse(val, f"Signal '{sig}' should be False on total failure")


if __name__ == "__main__":
    unittest.main()
