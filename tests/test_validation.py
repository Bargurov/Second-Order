"""
tests/test_validation.py

Unit tests for _validate_result() in analyze_event.py.
Pure function tests — no API calls, no mocks needed.
"""

import sys
import unittest

sys.path.insert(0, ".")
from analyze_event import _validate_result, is_mock, _mock, _normalize_if_persists


def _good_result() -> dict:
    """A baseline result that passes all validation rules.

    Includes a populated transmission_chain and disjoint ticker lists so
    the contradiction-aware validator leaves it untouched at confidence=high.
    """
    return {
        "what_changed": "Something happened.",
        "mechanism_summary": "This is a meaningful summary that is clearly longer than twenty characters.",
        "beneficiaries": ["US LNG exporters"],
        "losers": ["European gas buyers"],
        "beneficiary_tickers": ["LNG", "XLE"],
        "loser_tickers": ["FXI"],
        "assets_to_watch": ["LNG", "XLE", "FXI"],
        "confidence": "medium",
        "transmission_chain": [
            "EU approves a gas-export policy change",
            "US LNG flows become the marginal substitute",
            "European gas buyers face higher delivered cost",
            "LNG exporters gain margin; buyers lose pricing power",
        ],
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


class TestNormalizeIfPersists(unittest.TestCase):
    """Tests for _normalize_if_persists — LLM output sanitization."""

    def test_populated_dict_passes_through(self):
        raw = {
            "substitution": "Alternative suppliers gain share.",
            "delayed_winners": ["CompanyC"],
            "delayed_losers": ["CompanyD"],
            "horizon": "months",
        }
        out = _normalize_if_persists(raw)
        self.assertEqual(out["substitution"], "Alternative suppliers gain share.")
        self.assertEqual(out["delayed_winners"], ["CompanyC"])
        self.assertEqual(out["delayed_losers"], ["CompanyD"])
        self.assertEqual(out["horizon"], "months")

    def test_none_input_returns_empty_dict(self):
        self.assertEqual(_normalize_if_persists(None), {})

    def test_non_dict_input_returns_empty_dict(self):
        self.assertEqual(_normalize_if_persists("not a dict"), {})
        self.assertEqual(_normalize_if_persists([1, 2]), {})

    def test_null_substitution_stripped(self):
        out = _normalize_if_persists({"substitution": None})
        self.assertNotIn("substitution", out)

    def test_string_null_substitution_stripped(self):
        out = _normalize_if_persists({"substitution": "null"})
        self.assertNotIn("substitution", out)

    def test_empty_string_substitution_stripped(self):
        out = _normalize_if_persists({"substitution": ""})
        self.assertNotIn("substitution", out)

    def test_empty_arrays_stripped(self):
        out = _normalize_if_persists({
            "substitution": "Something.",
            "delayed_winners": [],
            "delayed_losers": [],
        })
        self.assertNotIn("delayed_winners", out)
        self.assertNotIn("delayed_losers", out)
        self.assertIn("substitution", out)

    def test_all_null_returns_empty_dict(self):
        out = _normalize_if_persists({
            "substitution": None,
            "delayed_winners": [],
            "delayed_losers": [],
            "horizon": "null",
        })
        self.assertEqual(out, {})

    def test_horizon_null_stripped(self):
        out = _normalize_if_persists({"substitution": "x.", "horizon": "None"})
        self.assertNotIn("horizon", out)


if __name__ == "__main__":
    unittest.main()
