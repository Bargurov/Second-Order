"""
tests/test_narrative_divergence.py

Unit tests for narrative_divergence.compute_narrative_divergence().
"""

import sys
import unittest

sys.path.insert(0, ".")
from narrative_divergence import (
    compute_narrative_divergence,
    _role_signal,
    _SHARP_GAP,
    _MILD_GAP,
    _MIN_CAL_N,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ticker(role: str, direction_tag: str | None, return_5d: float = 1.0) -> dict:
    return {"symbol": "X", "role": role, "direction_tag": direction_tag, "return_5d": return_5d}


def _calibration(confidence: str, hit_rate: float, n: int = 20) -> dict:
    return {confidence: {"hit_rate": hit_rate, "n": n}}


# ---------------------------------------------------------------------------
# 1. No eligible tickers → unavailable
# ---------------------------------------------------------------------------

class TestNoEligibleTickers(unittest.TestCase):
    def test_empty_tickers(self):
        result = compute_narrative_divergence([], "medium", {"medium": {"hit_rate": 0.5, "n": 20}})
        self.assertFalse(result["available"])

    def test_tickers_with_no_direction_tag(self):
        tickers = [
            _ticker("beneficiary", None),
            _ticker("loser", None),
        ]
        result = compute_narrative_divergence(tickers, "medium", {"medium": {"hit_rate": 0.5, "n": 20}})
        self.assertFalse(result["available"])


# ---------------------------------------------------------------------------
# 2. Insufficient calibration data → raw signal, no gap
# ---------------------------------------------------------------------------

class TestInsufficientCalibration(unittest.TestCase):
    def _make(self, hit_rate: float, n: int, supporting: int, contradicting: int) -> dict:
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * supporting
            + [_ticker("loser", "contradicts ↓")] * contradicting
        )
        return compute_narrative_divergence(tickers, "high", {"high": {"hit_rate": hit_rate, "n": n}})

    def test_n_below_min_returns_no_gap(self):
        result = self._make(0.7, _MIN_CAL_N - 1, 3, 1)
        self.assertTrue(result["available"])
        self.assertIsNone(result["gap"])
        self.assertIsNone(result["expected_rate"])

    def test_missing_calibration_bucket(self):
        tickers = [_ticker("beneficiary", "supports ↑")]
        result = compute_narrative_divergence(tickers, "high", {})
        self.assertTrue(result["available"])
        self.assertIsNone(result["gap"])

    def test_label_validated_when_majority_supports(self):
        result = self._make(0.7, 1, 3, 1)  # n=1, below MIN_CAL_N
        self.assertEqual(result["label"], "validated")

    def test_label_contradicted_when_minority_supports(self):
        result = self._make(0.7, 1, 1, 3)
        self.assertEqual(result["label"], "contradicted")


# ---------------------------------------------------------------------------
# 3. Confident miss (sharp negative gap)
# ---------------------------------------------------------------------------

class TestConfidentMiss(unittest.TestCase):
    def _make(self, supporting: int, contradicting: int, confidence: str = "high") -> dict:
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * supporting
            + [_ticker("loser", "contradicts ↓")] * contradicting
        )
        # expected rate = 0.7, n = 20
        return compute_narrative_divergence(tickers, confidence, _calibration(confidence, 0.7))

    def test_zero_validation_is_sharp_miss(self):
        result = self._make(0, 5)
        self.assertEqual(result["label"], "confident_miss")
        self.assertEqual(result["severity"], "sharp")

    def test_gap_is_below_negative_threshold(self):
        result = self._make(0, 5)
        self.assertLessEqual(result["gap"], -_SHARP_GAP)

    def test_rationale_mentions_confidence_level(self):
        result = self._make(0, 5)
        self.assertIn("High", result["rationale"])

    def test_actual_rate_zero(self):
        result = self._make(0, 4)
        self.assertAlmostEqual(result["actual_rate"], 0.0)


# ---------------------------------------------------------------------------
# 4. Surprise validation (sharp positive gap)
# ---------------------------------------------------------------------------

class TestSurpriseValidation(unittest.TestCase):
    def test_all_supporting_with_low_expected(self):
        tickers = [_ticker("beneficiary", "supports ↑")] * 5
        result = compute_narrative_divergence(tickers, "low", _calibration("low", 0.3))
        self.assertEqual(result["label"], "surprise_validation")
        self.assertEqual(result["severity"], "sharp")
        self.assertGreaterEqual(result["gap"], _SHARP_GAP)

    def test_rationale_mentions_outperforming(self):
        tickers = [_ticker("beneficiary", "supports ↑")] * 5
        result = compute_narrative_divergence(tickers, "low", _calibration("low", 0.3))
        self.assertIn("outperforming", result["rationale"].lower())


# ---------------------------------------------------------------------------
# 5. Aligned (gap within _MILD_GAP)
# ---------------------------------------------------------------------------

class TestAligned(unittest.TestCase):
    def test_exact_match_is_aligned(self):
        # 10 supporting, 10 contradicting → actual 0.5; expected 0.5
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * 10
            + [_ticker("loser", "contradicts ↓")] * 10
        )
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["label"], "aligned")
        self.assertEqual(result["severity"], "none")

    def test_small_positive_gap_is_aligned(self):
        # actual = 0.6, expected = 0.5 → gap = 0.1 < _MILD_GAP
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * 6
            + [_ticker("loser", "contradicts ↓")] * 4
        )
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["label"], "aligned")

    def test_small_negative_gap_is_aligned(self):
        # actual = 0.4, expected = 0.5 → gap = -0.1 > -_MILD_GAP
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * 4
            + [_ticker("loser", "contradicts ↓")] * 6
        )
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["label"], "aligned")


# ---------------------------------------------------------------------------
# 6. Mixed (gap in mild band)
# ---------------------------------------------------------------------------

class TestMixed(unittest.TestCase):
    def test_gap_in_mild_range_positive(self):
        # actual = 0.7, expected = 0.5 → gap = 0.2, inside [_MILD_GAP, _SHARP_GAP)
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * 7
            + [_ticker("loser", "contradicts ↓")] * 3
        )
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["label"], "mixed")
        self.assertEqual(result["severity"], "mild")

    def test_gap_in_mild_range_negative(self):
        # actual = 0.3, expected = 0.5 → gap = -0.2
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * 3
            + [_ticker("loser", "contradicts ↓")] * 7
        )
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["label"], "mixed")
        self.assertEqual(result["severity"], "mild")


# ---------------------------------------------------------------------------
# 7. Role signal breakdown
# ---------------------------------------------------------------------------

class TestRoleSignal(unittest.TestCase):
    def test_all_aligned_beneficiaries(self):
        tickers = [_ticker("beneficiary", "supports ↑")] * 3
        self.assertEqual(_role_signal(tickers, "beneficiary"), "aligned")

    def test_all_contra_losers(self):
        tickers = [_ticker("loser", "contradicts ↓")] * 3
        self.assertEqual(_role_signal(tickers, "loser"), "contra")

    def test_mixed_role_group(self):
        tickers = [
            _ticker("beneficiary", "supports ↑"),
            _ticker("beneficiary", "contradicts ↑"),
        ]
        self.assertEqual(_role_signal(tickers, "beneficiary"), "mixed")

    def test_no_tickers_for_role(self):
        tickers = [_ticker("beneficiary", "supports ↑")]
        self.assertEqual(_role_signal(tickers, "loser"), "no_data")

    def test_no_direction_tags_in_group(self):
        tickers = [_ticker("beneficiary", None)]
        self.assertEqual(_role_signal(tickers, "beneficiary"), "no_data")

    def test_role_signals_in_full_output(self):
        tickers = [
            _ticker("beneficiary", "supports ↑"),
            _ticker("beneficiary", "supports ↓"),
            _ticker("loser", "contradicts ↓"),
        ]
        result = compute_narrative_divergence(tickers, "medium", _calibration("medium", 0.5))
        self.assertEqual(result["beneficiary_signal"], "aligned")
        self.assertEqual(result["loser_signal"], "contra")


# ---------------------------------------------------------------------------
# 8. Threshold boundary cases
# ---------------------------------------------------------------------------

class TestThresholdBoundaries(unittest.TestCase):
    """Verify exact boundary values fall on the correct side of each label."""

    def _result(self, actual: float, expected: float, confidence: str = "medium") -> dict:
        # Build tickers to produce exact actual rate using fractions of 100
        n = 100
        n_sup = round(actual * n)
        n_con = n - n_sup
        tickers = (
            [_ticker("beneficiary", "supports ↑")] * n_sup
            + [_ticker("loser", "contradicts ↓")] * n_con
        )
        return compute_narrative_divergence(tickers, confidence, _calibration(confidence, expected))

    def test_gap_exactly_mild_threshold_is_mixed(self):
        # actual = 0.65, expected = 0.5 → gap = 0.15 = _MILD_GAP exactly
        # abs(gap) < _MILD_GAP is False, so must be mixed not aligned
        result = self._result(0.65, 0.5)
        self.assertEqual(result["label"], "mixed")

    def test_gap_below_mild_threshold_is_aligned(self):
        # gap < _MILD_GAP
        result = self._result(0.64, 0.5)
        self.assertEqual(result["label"], "aligned")

    def test_gap_exactly_sharp_threshold_is_surprise_validation(self):
        # actual = 0.8, expected = 0.5 → gap = 0.30 >= _SHARP_GAP
        result = self._result(0.8, 0.5)
        self.assertEqual(result["label"], "surprise_validation")

    def test_gap_just_below_sharp_threshold_is_mixed(self):
        # actual = 0.79, expected = 0.5 → gap = 0.29 < _SHARP_GAP
        result = self._result(0.79, 0.5)
        self.assertEqual(result["label"], "mixed")


if __name__ == "__main__":
    unittest.main()
