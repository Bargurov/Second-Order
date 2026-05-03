"""Counterfactual / actionability symmetry — when an event is
tradable/actionable only because proof exists, the counterfactual
block must not be empty.  When no concrete counterfactual is
observable from any source (falsifiers, breakpoints, proof inversion),
the actionability block caps to watch_only / non-tradable.

Mirrors the audit recommendation: the two derived blocks shared
proof-inversion language but only ``actionability_check`` actually
fell back to it; ``counterfactual_check`` returned empty
``evidence_to_watch`` for proof-only events.  These tests guard the
symmetric contract.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from low_information_gate import (
    _has_observable_counterfactual,
    _proof_inversion_strings,
    compose_actionability_check,
    compose_counterfactual_check,
    evidence_quality_tier,
)


CONCRETE_MECHANISM = (
    "Saudi Aramco cuts liftings by 1mbd, tightening Gulf Coast "
    "refinery feedstock and widening the WCS-WTI heavy-sour discount."
)

PROOF_OBS = (
    "WCS-WTI heavy-sour discount widens 2pp within 5 trading days"
)

PROOF_ITEM = {
    "observation": PROOF_OBS,
    "channel":     "commodities",
    "threshold":   "2pp",
    "timing":      "1-5d",
}

FALSIFIER_STR = (
    "Saudi Aramco reverses the lifting cut within 5 trading days, "
    "WCS discount tightens back below 1pp."
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
        "key_falsifiers":     [FALSIFIER_STR],
    }
    base.update(overrides)
    return base


class TestProofInversionStrings(unittest.TestCase):
    def test_proof_inversion_emits_inverted_strings(self):
        ev = _actionable_event()
        out = _proof_inversion_strings(ev)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0].startswith("Expected proof fails to print:"))
        self.assertIn(PROOF_OBS, out[0])

    def test_proof_inversion_skips_short_items(self):
        ev = _actionable_event(minimum_proof_set=[
            {"observation": "x", "channel": "commodities"},  # too short
            {"observation": PROOF_OBS, "channel": "commodities"},
        ])
        out = _proof_inversion_strings(ev)
        self.assertEqual(len(out), 1)

    def test_proof_inversion_handles_empty_proof_set(self):
        ev = _actionable_event(minimum_proof_set=[])
        self.assertEqual(_proof_inversion_strings(ev), [])

    def test_proof_inversion_handles_non_dict_input(self):
        self.assertEqual(_proof_inversion_strings(None), [])
        self.assertEqual(_proof_inversion_strings("nope"), [])


class TestObservableCounterfactualHelper(unittest.TestCase):
    def test_falsifier_present_is_observable(self):
        ev = _actionable_event()
        self.assertTrue(_has_observable_counterfactual(ev))

    def test_proof_only_is_observable(self):
        ev = _actionable_event(key_falsifiers=[], hidden_mechanism={})
        self.assertTrue(_has_observable_counterfactual(ev))

    def test_no_falsifier_no_proof_is_not_observable(self):
        ev = _actionable_event(
            key_falsifiers=[], hidden_mechanism={}, minimum_proof_set=[],
        )
        self.assertFalse(_has_observable_counterfactual(ev))

    def test_non_dict_input_is_not_observable(self):
        self.assertFalse(_has_observable_counterfactual(None))


class TestCounterfactualSymmetryWithProofOnly(unittest.TestCase):
    """When proof exists but falsifiers are empty, counterfactual_check
    must derive evidence from proof inversion — closing the historical
    asymmetry with actionability_check."""

    def test_proof_only_event_emits_populated_counterfactual(self):
        ev = _actionable_event(key_falsifiers=[], hidden_mechanism={})
        block = compose_counterfactual_check(ev)
        self.assertGreaterEqual(len(block["evidence_to_watch"]), 1)
        self.assertTrue(
            block["evidence_to_watch"][0].startswith(
                "Expected proof fails to print:"
            ),
        )

    def test_proof_only_actionability_still_tradable(self):
        ev = _actionable_event(key_falsifiers=[], hidden_mechanism={})
        block = compose_actionability_check(ev)
        # Proof exists → counterfactual is observable via inversion →
        # actionability stays tradable.
        self.assertTrue(block["tradable"])
        self.assertNotEqual(block["invalidation_trigger"], "")

    def test_proof_only_blocks_share_proof_inversion_language(self):
        # Both derived blocks fall back to "Expected proof fails to
        # print: <obs>" wording, so consumers reading both see linked
        # phrasing.
        ev = _actionable_event(key_falsifiers=[], hidden_mechanism={})
        cf = compose_counterfactual_check(ev)
        ac = compose_actionability_check(ev)
        self.assertIn(
            "Expected proof fails to print:", cf["evidence_to_watch"][0],
        )
        self.assertIn(
            "Expected proof fails to print:", ac["invalidation_trigger"],
        )

    def test_falsifier_present_does_not_use_proof_inversion(self):
        # Falsifier explicitly committed → use it; proof inversion is
        # the fallback only.
        ev = _actionable_event()
        block = compose_counterfactual_check(ev)
        self.assertIn(FALSIFIER_STR, block["evidence_to_watch"])
        self.assertFalse(
            block["evidence_to_watch"][0].startswith(
                "Expected proof fails to print:"
            ),
        )


class TestActionabilityCapWhenNoCounterfactual(unittest.TestCase):
    """Defensive cap — when an event would otherwise be actionable but
    no counterfactual is observable from any source, demote to
    watch_only-without-trigger."""

    def test_no_counterfactual_caps_to_non_tradable(self):
        # Construct an event with no falsifier, no breakpoint, no
        # proof.  This rarely passes the actionable tier gate today,
        # but the cap is the safety net for any future tier-rule
        # change that would let it through.
        ev = _actionable_event(
            key_falsifiers=[], hidden_mechanism={}, minimum_proof_set=[],
        )
        # Sanity: the event won't actually be actionable today; just
        # confirm the actionability block stays non-tradable when no
        # counterfactual is observable.
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        self.assertEqual(block["risk_level"], "high")
        self.assertEqual(block["invalidation_trigger"], "")
        self.assertEqual(block["required_confirmation"], [])

    def test_low_information_remains_non_tradable(self):
        # Independent of the cap, low_information events stay
        # non-tradable with the existing low-info shape.
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        self.assertEqual(evidence_quality_tier(ev), "low_information")
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        self.assertEqual(block["max_confidence_before_confirmation"], "low")

    def test_response_shape_stable_under_cap(self):
        # The capped block must carry the full 7-key shape so consumers
        # don't branch on field presence.
        ev = _actionable_event(
            key_falsifiers=[], hidden_mechanism={}, minimum_proof_set=[],
        )
        block = compose_actionability_check(ev)
        for key in (
            "tradable", "why_tradable_or_not", "required_confirmation",
            "sizing_caveat", "risk_level",
            "max_confidence_before_confirmation", "invalidation_trigger",
        ):
            self.assertIn(key, block)


if __name__ == "__main__":
    unittest.main()
