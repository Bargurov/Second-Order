"""Tests for compose_confidence_rationale."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from low_information_gate import (
    calibrate_confidence,
    compose_confidence_rationale,
    evidence_quality_tier,
)


CONCRETE_MECHANISM = (
    "Saudi Aramco cuts liftings by 1mbd, tightening Gulf Coast "
    "refinery feedstock and widening the WCS-WTI heavy-sour discount."
)

PROOF_ITEM = {
    "observation": "WCS-WTI heavy-sour discount widens 2pp within 5 trading days",
    "channel":     "commodities",
    "threshold":   "2pp",
    "timing":      "1-5d",
}

FALSIFIER_STR = (
    "Saudi Aramco reverses the lifting cut within 5 trading days, "
    "WCS discount tightens back below 1pp."
)


def _actionable_event(**overrides):
    """A clean actionable-tier event with proof + falsifier coverage."""
    base = {
        "headline":           "OPEC surprise cut",
        "what_changed":       (
            "Saudi Aramco cut crude liftings by 1mbd from August "
            "contract volumes, tightening Gulf Coast feedstock supply."
        ),
        "mechanism_summary":  CONCRETE_MECHANISM,
        "mechanism_family":   "commodity_squeeze",
        "beneficiaries":      ["XOM", "CVX"],
        "losers":              ["DAL", "AAL"],
        "assets_to_watch":    ["CL"],
        "beneficiary_tickers": ["XOM", "CVX"],
        "loser_tickers":       ["DAL", "AAL"],
        "expected_first_order_channels":  ["commodities"],
        "expected_second_order_channels": ["equities"],
        "transmission_path": [
            {
                "hop":     "Saudi Aramco cuts crude liftings by 1mbd from August contracts.",
                "action":  "Saudi Aramco cuts crude liftings by 1mbd from August contracts.",
                "actor":   "Saudi Aramco",
                "channel": "supply",
                "expected_market_effect": (
                    "WCS-WTI heavy-sour spread widens >=2pp; "
                    "Brent crude curve steepens."
                ),
                "timing":  "1-5d",
            },
            {
                "hop":     "Gulf Coast refiners reprice heavy-sour feedstock margin.",
                "action":  "Gulf Coast refiners reprice heavy-sour feedstock margin.",
                "actor":   "Gulf Coast refiners",
                "channel": "pricing_power",
                "expected_market_effect": (
                    "XOM and CVX equity prices rally on widened "
                    "feedstock margin; SPY underperforms."
                ),
                "timing":  "1-5d",
            },
        ],
        "primary_assets": [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct Saudi crude beneficiary via Gulf Coast feedstock margin."},
        ],
        "competing_thesis": {
            "primary_thesis": (
                "Saudi lifting cut tightens Gulf Coast heavy-sour "
                "feedstock, widening WCS-WTI discount and lifting XOM/CVX."
            ),
        },
        "minimum_proof_set":  [PROOF_ITEM],
        "key_falsifiers":     [FALSIFIER_STR],
    }
    base.update(overrides)
    return base


class TestConfidenceRationaleHigh(unittest.TestCase):
    def test_actionable_with_full_coverage_returns_high_rationale(self):
        ev = _actionable_event()
        self.assertEqual(evidence_quality_tier(ev), "actionable")
        self.assertEqual(calibrate_confidence(ev), "high")
        rationale = compose_confidence_rationale(ev)
        self.assertTrue(rationale.startswith("Confidence high:"))
        # Must reference proof + falsifier (the two that earn high).
        self.assertIn("proof", rationale.lower())
        self.assertIn("falsifier", rationale.lower())


class TestConfidenceRationaleMedium(unittest.TestCase):
    def test_actionable_with_only_proof_caps_at_medium(self):
        ev = _actionable_event(key_falsifiers=[])
        self.assertEqual(calibrate_confidence(ev), "medium")
        rationale = compose_confidence_rationale(ev)
        self.assertTrue(rationale.startswith("Confidence medium:"))
        self.assertIn("falsifier set empty", rationale)

    def test_actionable_with_only_falsifier_caps_at_medium(self):
        ev = _actionable_event(minimum_proof_set=[])
        self.assertEqual(calibrate_confidence(ev), "medium")
        rationale = compose_confidence_rationale(ev)
        self.assertTrue(rationale.startswith("Confidence medium:"))
        self.assertIn("proof set empty", rationale)

    def test_watch_only_with_missing_asset_rationale_is_named(self):
        # Clear primary_assets[].rationale to land in watch_only via
        # the missing_asset_rationale path (5/5 causal prongs but no
        # concrete asset rationale → capped at watch_only).
        ev = _actionable_event(
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": ""},
            ],
        )
        rationale = compose_confidence_rationale(ev)
        self.assertTrue(rationale.startswith("Confidence medium:"))
        # The composer must surface the actual cap reason.
        self.assertIn("rationale", rationale)


class TestConfidenceRationaleLow(unittest.TestCase):
    def test_filler_mechanism_names_filler_input(self):
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        self.assertEqual(calibrate_confidence(ev), "low")
        rationale = compose_confidence_rationale(ev)
        self.assertTrue(rationale.startswith("Confidence low:"))
        self.assertIn("filler", rationale.lower())

    def test_no_concrete_asset_names_missing_input(self):
        ev = _actionable_event(
            beneficiary_tickers=[], loser_tickers=[], assets_to_watch=[],
            primary_assets=[],
        )
        self.assertEqual(calibrate_confidence(ev), "low")
        rationale = compose_confidence_rationale(ev)
        self.assertIn("concrete tickerable asset", rationale)

    def test_non_dict_input_returns_empty(self):
        self.assertEqual(compose_confidence_rationale(None), "")
        self.assertEqual(compose_confidence_rationale("not a dict"), "")


class TestConfidenceRationaleConcision(unittest.TestCase):
    def test_rationale_stays_within_two_sentences(self):
        # Compose for actionable / watch_only / low-info shapes and
        # assert each rationale fits the 1-2 sentence contract.
        for ev in (
            _actionable_event(),
            _actionable_event(key_falsifiers=[]),
            _actionable_event(mechanism_summary="N/A insufficient evidence."),
        ):
            rationale = compose_confidence_rationale(ev)
            self.assertTrue(rationale, "expected a non-empty rationale")
            sentence_count = sum(
                1 for ch in rationale.rstrip(".") if ch == "."
            ) + 1
            self.assertLessEqual(
                sentence_count, 2,
                f"rationale exceeded 2 sentences: {rationale!r}",
            )


if __name__ == "__main__":
    unittest.main()
