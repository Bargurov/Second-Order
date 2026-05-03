"""Tests for compose_counterfactual_check."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from low_information_gate import (
    compose_counterfactual_check,
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

FALSIFIER_A = (
    "Saudi Aramco reverses the lifting cut within 5 trading days, "
    "WCS discount tightens back below 1pp."
)

FALSIFIER_B = (
    "XOM and CVX underperform Gulf Coast peers despite cut — "
    "feedstock margin spread fails to widen."
)


def _actionable_event(**overrides):
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
        "key_falsifiers":     [FALSIFIER_A, FALSIFIER_B],
    }
    base.update(overrides)
    return base


class TestCounterfactualActionable(unittest.TestCase):
    def test_actionable_event_emits_full_block(self):
        ev = _actionable_event()
        self.assertEqual(evidence_quality_tier(ev), "actionable")
        block = compose_counterfactual_check(ev)
        self.assertIn("what_should_not_happen", block)
        self.assertIn("why_it_would_break_thesis", block)
        self.assertIn("evidence_to_watch", block)

    def test_evidence_to_watch_preserves_falsifier_strings(self):
        # Linkage to key_falsifiers is structural — exact strings must
        # round-trip so consumers can match an evidence item back to
        # the source falsifier list.
        ev = _actionable_event()
        block = compose_counterfactual_check(ev)
        evidence = block["evidence_to_watch"]
        self.assertIn(FALSIFIER_A, evidence)
        self.assertIn(FALSIFIER_B, evidence)

    def test_what_should_not_happen_is_concrete(self):
        ev = _actionable_event()
        block = compose_counterfactual_check(ev)
        # Must be a non-empty observable string drawn from the falsifier set.
        self.assertTrue(block["what_should_not_happen"])
        self.assertGreaterEqual(len(block["what_should_not_happen"]), 15)

    def test_why_anchors_on_primary_thesis_when_present(self):
        ev = _actionable_event()
        block = compose_counterfactual_check(ev)
        # Anchor pulls from competing_thesis.primary_thesis when set,
        # so the why line must contain a token from that thesis prose.
        self.assertIn("Saudi", block["why_it_would_break_thesis"])

    def test_evidence_capped_at_three(self):
        many = [
            f"WCS-WTI heavy-sour discount fails to widen above {n}bp threshold within 5 trading days"
            for n in range(10, 20)
        ]
        ev = _actionable_event(key_falsifiers=many)
        block = compose_counterfactual_check(ev)
        self.assertLessEqual(len(block["evidence_to_watch"]), 3)


class TestCounterfactualWatchOnly(unittest.TestCase):
    def test_watch_only_event_still_emits_block(self):
        # Watch_only is fine — counterfactual must still surface when
        # falsifier evidence exists.  Drop the asset rationale so the
        # tier classifier caps at watch_only without breaking the
        # falsifier set.
        ev = _actionable_event(
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
        )
        tier = evidence_quality_tier(ev)
        self.assertEqual(tier, "watch_only")
        block = compose_counterfactual_check(ev)
        self.assertTrue(block)
        self.assertEqual(block["evidence_to_watch"][0], FALSIFIER_A)


class TestCounterfactualEmpty(unittest.TestCase):
    _SHAPE_KEYS = {
        "what_should_not_happen",
        "why_it_would_break_thesis",
        "evidence_to_watch",
    }

    def test_low_information_returns_populated_shape(self):
        # Low_information no longer returns {} — every analyzable event
        # gets the same 3-key shape with an empty evidence_to_watch.
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        self.assertEqual(evidence_quality_tier(ev), "low_information")
        block = compose_counterfactual_check(ev)
        self.assertEqual(set(block.keys()), self._SHAPE_KEYS)
        self.assertEqual(block["evidence_to_watch"], [])
        self.assertIn("low_information", block["why_it_would_break_thesis"])

    def test_no_falsifiers_or_breakpoints_falls_back_to_proof_inversion(self):
        # When falsifiers AND breakpoints are empty BUT minimum_proof_set
        # is committed, the counterfactual derives from proof inversion
        # so the block stays populated — closes the historical asymmetry
        # where actionability_check used proof inversion and
        # counterfactual_check returned empty evidence.
        ev = _actionable_event(key_falsifiers=[], hidden_mechanism={})
        block = compose_counterfactual_check(ev)
        self.assertEqual(set(block.keys()), self._SHAPE_KEYS)
        self.assertGreaterEqual(len(block["evidence_to_watch"]), 1)
        self.assertTrue(
            block["evidence_to_watch"][0].startswith(
                "Expected proof fails to print:"
            ),
        )
        # Why-line signals the proof-inversion source so consumers don't
        # read the entry as an analyst-committed falsifier.
        self.assertIn("proof", block["why_it_would_break_thesis"].lower())

    def test_no_falsifiers_breakpoints_or_proof_returns_empty_evidence(self):
        # Truly no observable counterfactual — falsifiers empty,
        # breakpoints empty, proof empty.  Block stays in shape but
        # evidence_to_watch is empty.
        ev = _actionable_event(
            key_falsifiers=[], hidden_mechanism={}, minimum_proof_set=[],
        )
        block = compose_counterfactual_check(ev)
        self.assertEqual(set(block.keys()), self._SHAPE_KEYS)
        self.assertEqual(block["evidence_to_watch"], [])

    def test_falls_back_to_critical_breakpoints(self):
        ev = _actionable_event(
            key_falsifiers=[],
            hidden_mechanism={
                "critical_breakpoints": [
                    {"observation": (
                        "WCS-WTI heavy-sour discount tightens back inside "
                        "1pp within 5 trading days"
                    ), "channel": "commodities", "timing": "1-5d"},
                ],
            },
        )
        block = compose_counterfactual_check(ev)
        self.assertTrue(block)
        self.assertEqual(len(block["evidence_to_watch"]), 1)
        self.assertIn("WCS-WTI", block["evidence_to_watch"][0])

    def test_non_dict_input_returns_empty(self):
        self.assertEqual(compose_counterfactual_check(None), {})
        self.assertEqual(compose_counterfactual_check("nope"), {})


if __name__ == "__main__":
    unittest.main()
