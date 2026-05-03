"""Tests for credit_regime.classify_credit_regime — the HY/IG/SHY regime classifier."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from credit_regime import classify_credit_regime, REGIME_LABELS


class TestClassifyCreditRegime(unittest.TestCase):
    """Core regime cases over HY/IG/SHY 5d percent moves."""

    def test_both_inputs_missing_is_unavailable(self):
        res = classify_credit_regime(hy_5d=None, ig_5d=None)
        self.assertEqual(res["regime"], "unavailable")
        self.assertFalse(res["available"])
        self.assertIsNone(res["hy_ig_differential_5d"])

    def test_default_risk_widening_when_hy_underperforms_ig(self):
        """HY falls a lot, IG falls a little → default-risk widening."""
        res = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        self.assertEqual(res["regime"], "default_risk_widening")
        self.assertEqual(res["default_risk_signal"], "widening")
        self.assertAlmostEqual(res["hy_ig_differential_5d"], -1.2)

    def test_duration_widening_when_both_fall_together(self):
        """HY and IG fall together with a small gap → rate-driven widening."""
        res = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)
        self.assertEqual(res["regime"], "duration_widening")
        self.assertEqual(res["default_risk_signal"], "quiet")
        self.assertEqual(res["duration_signal"], "rising_rates")

    def test_risk_on_when_hy_outperforms_ig(self):
        res = classify_credit_regime(hy_5d=+1.1, ig_5d=+0.2)
        self.assertEqual(res["regime"], "default_risk_tightening")
        self.assertEqual(res["default_risk_signal"], "tightening")

    def test_decoupled_when_hy_and_ig_oppose(self):
        """HY up, IG down (or vice versa) beyond the decouple floor."""
        res = classify_credit_regime(hy_5d=+0.8, ig_5d=-0.6)
        self.assertEqual(res["regime"], "decoupled")
        self.assertEqual(res["default_risk_signal"], "quiet")

    def test_quiet_when_both_under_noise_floor(self):
        res = classify_credit_regime(hy_5d=0.1, ig_5d=-0.1)
        self.assertEqual(res["regime"], "quiet")

    def test_hy_only_falls_back_to_risk_on_off(self):
        """Missing IG → classifier degrades to a HY-only read."""
        res = classify_credit_regime(hy_5d=-1.0, ig_5d=None)
        self.assertEqual(res["regime"], "risk_off")
        self.assertTrue(res["stale"])
        self.assertTrue(res["available"])

    def test_ig_only_reports_duration(self):
        res = classify_credit_regime(hy_5d=None, ig_5d=-1.0)
        self.assertEqual(res["regime"], "duration_widening")
        self.assertTrue(res["stale"])

    def test_nan_inputs_sanitized(self):
        res = classify_credit_regime(hy_5d=float("nan"), ig_5d=float("inf"))
        self.assertEqual(res["regime"], "unavailable")
        self.assertIsNone(res["hy_5d"])
        self.assertIsNone(res["ig_5d"])

    def test_every_regime_has_a_label(self):
        for regime_id in REGIME_LABELS:
            self.assertTrue(REGIME_LABELS[regime_id])


class TestDurationSignal(unittest.TestCase):
    """duration_signal is derived from the IG (LQD) leg only."""

    def test_ig_down_is_rising_rates(self):
        res = classify_credit_regime(hy_5d=-0.1, ig_5d=-1.0)
        self.assertEqual(res["duration_signal"], "rising_rates")

    def test_ig_up_is_falling_rates(self):
        res = classify_credit_regime(hy_5d=+0.1, ig_5d=+1.0)
        self.assertEqual(res["duration_signal"], "falling_rates")

    def test_ig_missing_is_unavailable(self):
        res = classify_credit_regime(hy_5d=-0.5, ig_5d=None)
        self.assertEqual(res["duration_signal"], "unavailable")


if __name__ == "__main__":
    unittest.main()
