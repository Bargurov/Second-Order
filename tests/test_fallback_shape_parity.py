"""Shape parity tests — _mock and _degraded_fallback must return the
same shaped derived blocks (actionability_check, counterfactual_check,
confidence_rationale) as the compose_* low_information outputs.

The composers are the single source of truth.  The fallback paths
construct base dicts and then call the composers, so by construction
the keys must match.  These tests guard against drift if anyone
re-introduces a literal in a fallback path or changes a composer
without updating the fallbacks.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analyze_event import _degraded_fallback, _mock
from low_information_gate import (
    compose_actionability_check,
    compose_confidence_rationale,
    compose_counterfactual_check,
    evidence_quality_tier,
)


_ACTIONABILITY_KEYS = {
    "tradable",
    "why_tradable_or_not",
    "required_confirmation",
    "sizing_caveat",
    "risk_level",
    "max_confidence_before_confirmation",
    "invalidation_trigger",
}

_COUNTERFACTUAL_KEYS = {
    "what_should_not_happen",
    "why_it_would_break_thesis",
    "evidence_to_watch",
}


class TestMockShapeParity(unittest.TestCase):
    """_mock derived blocks match composer low_information shapes."""

    def setUp(self):
        self.mock = _mock("missing api key")

    def test_mock_lands_in_low_information_tier(self):
        # Sanity: the mock event must classify as low_information so
        # the parity comparison is against the right composer branch.
        self.assertEqual(evidence_quality_tier(self.mock), "low_information")

    def test_actionability_check_is_not_empty_dict(self):
        # Shape rule: low-info / mock outputs must NOT return {} for
        # shaped blocks.
        self.assertNotEqual(self.mock["actionability_check"], {})

    def test_actionability_check_keys_match_composer(self):
        composer_block = compose_actionability_check(self.mock)
        self.assertEqual(
            set(self.mock["actionability_check"].keys()),
            set(composer_block.keys()),
        )
        self.assertEqual(
            set(self.mock["actionability_check"].keys()),
            _ACTIONABILITY_KEYS,
        )

    def test_counterfactual_check_is_not_empty_dict(self):
        self.assertNotEqual(self.mock["counterfactual_check"], {})

    def test_counterfactual_check_keys_match_composer(self):
        composer_block = compose_counterfactual_check(self.mock)
        self.assertEqual(
            set(self.mock["counterfactual_check"].keys()),
            set(composer_block.keys()),
        )
        self.assertEqual(
            set(self.mock["counterfactual_check"].keys()),
            _COUNTERFACTUAL_KEYS,
        )

    def test_confidence_rationale_is_non_empty_string(self):
        rationale = self.mock["confidence_rationale"]
        self.assertIsInstance(rationale, str)
        self.assertTrue(rationale.strip())

    def test_confidence_rationale_matches_composer(self):
        # Composer is the single source of truth — _mock must produce
        # the same string the composer would for the same event.
        self.assertEqual(
            self.mock["confidence_rationale"],
            compose_confidence_rationale(self.mock),
        )


class TestDegradedFallbackShapeParity(unittest.TestCase):
    """_degraded_fallback derived blocks match composer shapes."""

    def setUp(self):
        self.fallback = _degraded_fallback(
            headline="Some headline",
            stage="reaction",
            persistence="",
            reason="thin mechanism + no chain + no entities",
        )

    def test_fallback_lands_in_low_information_tier(self):
        self.assertEqual(
            evidence_quality_tier(self.fallback), "low_information",
        )

    def test_actionability_check_is_not_empty_dict(self):
        self.assertNotEqual(self.fallback["actionability_check"], {})

    def test_actionability_check_keys_match_composer(self):
        composer_block = compose_actionability_check(self.fallback)
        self.assertEqual(
            set(self.fallback["actionability_check"].keys()),
            set(composer_block.keys()),
        )
        self.assertEqual(
            set(self.fallback["actionability_check"].keys()),
            _ACTIONABILITY_KEYS,
        )

    def test_counterfactual_check_is_not_empty_dict(self):
        self.assertNotEqual(self.fallback["counterfactual_check"], {})

    def test_counterfactual_check_keys_match_composer(self):
        composer_block = compose_counterfactual_check(self.fallback)
        self.assertEqual(
            set(self.fallback["counterfactual_check"].keys()),
            set(composer_block.keys()),
        )
        self.assertEqual(
            set(self.fallback["counterfactual_check"].keys()),
            _COUNTERFACTUAL_KEYS,
        )

    def test_confidence_rationale_matches_composer(self):
        self.assertEqual(
            self.fallback["confidence_rationale"],
            compose_confidence_rationale(self.fallback),
        )

    def test_degraded_flag_and_validation_warnings_present(self):
        # AnalysisResult TypedDict now declares both fields — assert
        # the degraded path actually populates them.
        self.assertTrue(self.fallback["degraded"])
        self.assertIsInstance(self.fallback["validation_warnings"], list)
        self.assertTrue(self.fallback["validation_warnings"])


class TestMockAndFallbackAgreeOnShape(unittest.TestCase):
    """Shape agreement across all three sources for the same tier."""

    def test_actionability_check_keys_identical(self):
        m = _mock("no api key")["actionability_check"]
        f = _degraded_fallback("h", "reaction", "", "thin")[
            "actionability_check"
        ]
        c = compose_actionability_check(_mock("x"))
        self.assertEqual(set(m.keys()), set(f.keys()))
        self.assertEqual(set(m.keys()), set(c.keys()))

    def test_counterfactual_check_keys_identical(self):
        m = _mock("no api key")["counterfactual_check"]
        f = _degraded_fallback("h", "reaction", "", "thin")[
            "counterfactual_check"
        ]
        c = compose_counterfactual_check(_mock("x"))
        self.assertEqual(set(m.keys()), set(f.keys()))
        self.assertEqual(set(m.keys()), set(c.keys()))


if __name__ == "__main__":
    unittest.main()
