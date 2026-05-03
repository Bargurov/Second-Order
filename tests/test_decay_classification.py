"""
tests/test_decay_classification.py

Focused tests for classify_decay edge cases.

  1) 0/0 flat case
  2) Tiny-noise pairs
  3) Small sign flips (noisy leg below de-minimis)
  4) Normal accelerating/fading regressions
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_check import classify_decay, DECAY_DE_MINIMIS


def label(r5, r20):
    return classify_decay(r5, r20)["label"]


# ---------------------------------------------------------------------------
# 1) 0/0 flat case
# ---------------------------------------------------------------------------

class TestFlatZeroZero(unittest.TestCase):

    def test_both_exactly_zero(self):
        self.assertEqual(label(0.0, 0.0), "Negligible")

    def test_both_none(self):
        self.assertEqual(label(None, None), "Unknown")

    def test_one_none(self):
        self.assertEqual(label(None, 5.0), "Unknown")
        self.assertEqual(label(5.0, None), "Unknown")


# ---------------------------------------------------------------------------
# 2) Tiny-noise pairs
# ---------------------------------------------------------------------------

class TestTinyNoisePairs(unittest.TestCase):

    def test_both_below_de_minimis_same_sign(self):
        self.assertEqual(label(0.1, 0.1), "Negligible")
        self.assertEqual(label(-0.1, -0.2), "Negligible")

    def test_both_below_de_minimis_opposite_sign(self):
        """Mirror-tiny noise should be Negligible, not Reversed."""
        self.assertEqual(label(0.1, -0.1), "Negligible")
        self.assertEqual(label(-0.15, 0.15), "Negligible")

    def test_at_boundary(self):
        """Both at exactly DECAY_DE_MINIMIS are NOT negligible."""
        r = classify_decay(DECAY_DE_MINIMIS, DECAY_DE_MINIMIS)
        self.assertNotEqual(r["label"], "Negligible")

    def test_tiny_5d_zero_20d(self):
        self.assertEqual(label(0.1, 0.0), "Negligible")

    def test_zero_5d_tiny_20d(self):
        self.assertEqual(label(0.0, 0.1), "Negligible")


# ---------------------------------------------------------------------------
# 3) Small sign flips — noisy leg below de-minimis
# ---------------------------------------------------------------------------

class TestSmallSignFlips(unittest.TestCase):

    def test_noise_5d_real_20d_is_fading_not_reversed(self):
        """r5=-0.15, r20=+8.89 — the 5d is noise. Should be Fading."""
        self.assertEqual(label(-0.15, 8.89), "Fading")

    def test_noise_5d_moderate_20d_is_fading(self):
        self.assertEqual(label(-0.2, 1.5), "Fading")

    def test_real_5d_noise_20d_is_accelerating(self):
        """r5=+1.80, r20=-0.06 — the 20d is noise. 5d is a new move."""
        self.assertEqual(label(1.80, -0.06), "Accelerating")

    def test_just_below_noise_flip_is_fading(self):
        """Smaller leg at 0.29 (just below 0.3) → not reversed."""
        self.assertEqual(label(-0.29, 3.0), "Fading")

    def test_just_above_noise_flip_is_reversed(self):
        """Smaller leg at 0.31 (just above 0.3) → reversed."""
        self.assertEqual(label(-0.31, 3.0), "Reversed")

    def test_real_5d_zero_20d_is_accelerating(self):
        """Strong 5d move vs flat 20d → new/accelerating move."""
        self.assertEqual(label(5.0, 0.0), "Accelerating")
        self.assertEqual(label(-3.0, 0.0), "Accelerating")

    def test_zero_5d_real_20d_is_fading(self):
        """Flat 5d vs real 20d → the move faded."""
        self.assertEqual(label(0.0, 5.0), "Fading")
        self.assertEqual(label(0.0, -3.0), "Fading")

    def test_clear_sign_flip_both_above_noise(self):
        """Both legs above noise → genuine Reversed."""
        self.assertEqual(label(-0.5, 1.5), "Reversed")
        self.assertEqual(label(2.0, -5.0), "Reversed")
        self.assertEqual(label(-3.0, 8.0), "Reversed")


# ---------------------------------------------------------------------------
# 4) Normal accelerating/fading regressions
# ---------------------------------------------------------------------------

class TestNormalRegressions(unittest.TestCase):

    def test_accelerating_5d_close_to_20d(self):
        """5d retains ≥80% of 20d magnitude → Accelerating."""
        self.assertEqual(label(4.5, 5.0), "Accelerating")
        self.assertEqual(label(-4.0, -5.0), "Accelerating")

    def test_holding_5d_retains_40_to_80_pct(self):
        """5d retains 40-80% of 20d magnitude → Holding."""
        self.assertEqual(label(2.5, 5.0), "Holding")
        self.assertEqual(label(-2.0, -5.0), "Holding")

    def test_fading_5d_below_40_pct(self):
        """5d retains <40% of 20d magnitude → Fading."""
        self.assertEqual(label(1.0, 5.0), "Fading")
        self.assertEqual(label(0.5, 5.0), "Fading")
        self.assertEqual(label(-0.5, -5.0), "Fading")

    def test_strong_reversal(self):
        self.assertEqual(label(-5.0, 10.0), "Reversed")
        self.assertEqual(label(7.0, -6.0), "Reversed")

    def test_evidence_string_present(self):
        """Every classify_decay result has a non-empty evidence string."""
        cases = [
            (0, 0), (0.1, 0.1), (5, 10), (2, 5), (0.5, 5),
            (-5, 10), (None, None), (-0.1, 5.0), (5.0, 0.0),
        ]
        for r5, r20 in cases:
            r = classify_decay(r5, r20)
            self.assertIn("label", r)
            self.assertIn("evidence", r)
            self.assertTrue(len(r["evidence"]) > 0, f"Empty evidence for ({r5}, {r20})")


if __name__ == "__main__":
    unittest.main()
