"""
tests/test_validation.py

Unit tests for _validate_result() in analyze_event.py.
Pure function tests — no API calls, no mocks needed.
"""

import sys
import unittest

sys.path.insert(0, ".")
from analyze_event import _validate_result, is_mock, _mock


def _good_result() -> dict:
    """A baseline result that passes all validation rules."""
    return {
        "what_changed": "Something happened.",
        "mechanism_summary": "This is a meaningful summary that is clearly longer than twenty characters.",
        "beneficiaries": ["US LNG exporters"],
        "losers": ["European gas buyers"],
        "beneficiary_tickers": ["LNG", "XLE"],
        "loser_tickers": ["FXI"],
        "assets_to_watch": ["LNG", "XLE", "FXI"],
        "confidence": "medium",
    }


class TestValidateResult(unittest.TestCase):

    def test_clean_result_has_no_warnings(self):
        # A fully compliant result should come back unchanged and without
        # the validation_warnings key.
        result = _validate_result(_good_result(), stage="realized")
        self.assertNotIn("validation_warnings", result)

    def test_empty_beneficiary_tickers_adds_warning(self):
        result = _good_result()
        result["beneficiary_tickers"] = []
        result = _validate_result(result, stage="realized")
        self.assertIn("validation_warnings", result)
        self.assertTrue(
            any("beneficiary_tickers" in w for w in result["validation_warnings"])
        )

    def test_short_mechanism_summary_adds_warning(self):
        result = _good_result()
        result["mechanism_summary"] = "Too short."   # 10 chars, well under 20
        result = _validate_result(result, stage="realized")
        self.assertIn("validation_warnings", result)
        self.assertTrue(
            any("mechanism_summary" in w for w in result["validation_warnings"])
        )

    def test_anticipation_high_confidence_is_downgraded(self):
        result = _good_result()
        result["confidence"] = "high"
        result = _validate_result(result, stage="anticipation")
        self.assertEqual(result["confidence"], "medium")
        self.assertIn("validation_warnings", result)
        self.assertTrue(
            any("downgraded" in w for w in result["validation_warnings"])
        )

    def test_realized_high_confidence_is_not_downgraded(self):
        # Rule 3 only applies to anticipation — a realized event with a clear
        # causal chain is allowed to keep high confidence.
        result = _good_result()
        result["confidence"] = "high"
        result = _validate_result(result, stage="realized")
        self.assertEqual(result["confidence"], "high")
        self.assertNotIn("validation_warnings", result)

    def test_multiple_issues_produce_multiple_warnings(self):
        # All three rules fire at once
        result = _good_result()
        result["beneficiary_tickers"] = []
        result["mechanism_summary"] = "Short."
        result["confidence"] = "high"
        result = _validate_result(result, stage="anticipation")
        self.assertEqual(len(result["validation_warnings"]), 3)
        self.assertEqual(result["confidence"], "medium")


class TestIsMock(unittest.TestCase):
    """Tests for is_mock() — detects mock/fallback analysis results."""

    def test_mock_output_detected(self):
        self.assertTrue(is_mock(_mock("no API key")))

    def test_mock_json_parse_error_detected(self):
        self.assertTrue(is_mock(_mock("JSON parse error")))

    def test_real_result_not_flagged(self):
        self.assertFalse(is_mock(_good_result()))

    def test_empty_what_changed_not_flagged(self):
        result = _good_result()
        result["what_changed"] = ""
        self.assertFalse(is_mock(result))

    def test_missing_what_changed_not_flagged(self):
        result = _good_result()
        del result["what_changed"]
        self.assertFalse(is_mock(result))


if __name__ == "__main__":
    unittest.main()
