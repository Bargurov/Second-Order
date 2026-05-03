"""Tests for compose_actionability_check."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from low_information_gate import (
    compose_actionability_check,
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


class TestActionabilityActionable(unittest.TestCase):
    def test_actionable_event_is_tradable(self):
        ev = _actionable_event()
        self.assertEqual(evidence_quality_tier(ev), "actionable")
        block = compose_actionability_check(ev)
        self.assertTrue(block["tradable"])
        self.assertIn("actionable", block["why_tradable_or_not"])

    def test_actionable_names_what_to_monitor(self):
        # Per task: "Actionable outputs must name what still needs monitoring."
        ev = _actionable_event()
        block = compose_actionability_check(ev)
        self.assertGreaterEqual(len(block["required_confirmation"]), 1)

    def test_required_confirmation_preserves_proof_strings(self):
        ev = _actionable_event()
        block = compose_actionability_check(ev)
        # Linkage: exact string from minimum_proof_set must appear.
        self.assertIn(PROOF_OBS, block["required_confirmation"])

    def test_block_has_all_four_keys(self):
        ev = _actionable_event()
        block = compose_actionability_check(ev)
        for key in (
            "tradable", "why_tradable_or_not",
            "required_confirmation", "sizing_caveat",
        ):
            self.assertIn(key, block)


class TestActionabilityWatchOnly(unittest.TestCase):
    def test_watch_only_with_concrete_proof_is_tradable(self):
        # Drop primary_assets rationale to land in watch_only — proof
        # set still populated, so per task watch_only is tradable when
        # required_confirmation is concrete.
        ev = _actionable_event(
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
        )
        self.assertEqual(evidence_quality_tier(ev), "watch_only")
        block = compose_actionability_check(ev)
        self.assertTrue(block["tradable"])
        self.assertIn(PROOF_OBS, block["required_confirmation"])
        self.assertIn("watch_only", block["why_tradable_or_not"])

    def test_watch_only_without_observable_trigger_is_not_tradable(self):
        # Watch_only AND empty proof + falsifier → no concrete trigger,
        # so tradable must be False per the gate rule.
        ev = _actionable_event(
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
            minimum_proof_set=[],
            key_falsifiers=[],
        )
        # Tier remains watch_only because the mechanism still passes.
        # (Some events might land at low_information here; we only
        # care about the actionability behavior when tier == watch_only.)
        if evidence_quality_tier(ev) != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        self.assertEqual(block["required_confirmation"], [])


class TestActionabilityLowInformation(unittest.TestCase):
    def test_low_information_is_never_tradable(self):
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        self.assertEqual(evidence_quality_tier(ev), "low_information")
        block = compose_actionability_check(ev)
        # Per task: tradable MUST be False for low_information.
        self.assertFalse(block["tradable"])
        self.assertEqual(block["required_confirmation"], [])

    def test_low_information_why_names_reason(self):
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        block = compose_actionability_check(ev)
        self.assertIn("low_information", block["why_tradable_or_not"])

    def test_no_concrete_asset_low_info_path(self):
        ev = _actionable_event(
            beneficiary_tickers=[], loser_tickers=[], assets_to_watch=[],
            primary_assets=[],
        )
        self.assertEqual(evidence_quality_tier(ev), "low_information")
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        # Reason mentions either the missing asset or a low-info phrase.
        self.assertIn("low_information", block["why_tradable_or_not"])


class TestActionabilityShape(unittest.TestCase):
    def test_non_dict_input_returns_empty(self):
        self.assertEqual(compose_actionability_check(None), {})
        self.assertEqual(compose_actionability_check("nope"), {})

    def test_required_confirmation_capped_at_three(self):
        many_proof = [
            {"observation": (
                f"Heavy-sour spread widens at least {n}bp within 5 trading days"
            ), "channel": "commodities", "threshold": f"{n}bp", "timing": "1-5d"}
            for n in range(10, 20)
        ]
        ev = _actionable_event(minimum_proof_set=many_proof)
        block = compose_actionability_check(ev)
        self.assertLessEqual(len(block["required_confirmation"]), 3)


class TestActionabilityRiskDiscipline(unittest.TestCase):
    """Risk/sizing discipline fields — risk_level,
    max_confidence_before_confirmation, invalidation_trigger."""

    def test_block_has_risk_discipline_keys(self):
        block = compose_actionability_check(_actionable_event())
        for key in (
            "risk_level",
            "max_confidence_before_confirmation",
            "invalidation_trigger",
        ):
            self.assertIn(key, block)

    def test_low_information_is_high_risk_and_non_tradable(self):
        ev = _actionable_event(mechanism_summary="N/A insufficient evidence.")
        self.assertEqual(evidence_quality_tier(ev), "low_information")
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        self.assertEqual(block["risk_level"], "high")
        self.assertEqual(block["max_confidence_before_confirmation"], "low")
        self.assertEqual(block["invalidation_trigger"], "")

    def test_watch_only_caps_confidence_before_confirmation(self):
        ev = _actionable_event(
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
        )
        if evidence_quality_tier(ev) != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        block = compose_actionability_check(ev)
        self.assertTrue(block["tradable"])
        # Cap pre-confirmation: cannot claim medium/high confidence.
        self.assertEqual(block["max_confidence_before_confirmation"], "low")
        self.assertEqual(block["risk_level"], "elevated")

    def test_watch_only_without_trigger_is_high_risk(self):
        ev = _actionable_event(
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
            minimum_proof_set=[],
            key_falsifiers=[],
        )
        if evidence_quality_tier(ev) != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        block = compose_actionability_check(ev)
        self.assertFalse(block["tradable"])
        self.assertEqual(block["risk_level"], "high")
        self.assertEqual(block["invalidation_trigger"], "")

    def test_actionable_names_concrete_invalidation_trigger(self):
        # Per task: actionable outputs MUST name a concrete
        # invalidation trigger.
        ev = _actionable_event()
        self.assertEqual(evidence_quality_tier(ev), "actionable")
        block = compose_actionability_check(ev)
        self.assertEqual(block["risk_level"], "standard")
        self.assertNotEqual(block["invalidation_trigger"], "")
        # Linkage: trigger string is drawn from key_falsifiers.
        self.assertEqual(block["invalidation_trigger"], FALSIFIER_STR)

    def test_actionable_does_not_cap_confidence(self):
        ev = _actionable_event()
        block = compose_actionability_check(ev)
        # Ceiling unrestricts at "high" so consumers don't null-check.
        self.assertEqual(block["max_confidence_before_confirmation"], "high")

    def test_invalidation_trigger_falls_back_to_proof_inversion(self):
        # Actionable shape with a falsifier-shaped string list of empty
        # entries — falls back to proof inversion so the field stays
        # non-empty for actionable consumers.
        ev = _actionable_event(key_falsifiers=[])
        if evidence_quality_tier(ev) != "actionable":
            self.skipTest("fixture didn't land at actionable")
        block = compose_actionability_check(ev)
        self.assertIn("Expected proof fails to print", block["invalidation_trigger"])
        self.assertIn(PROOF_OBS, block["invalidation_trigger"])

    def test_risk_level_is_closed_set(self):
        # All three tiers must emit a value from the closed set.
        for ev in (
            _actionable_event(),
            _actionable_event(
                primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": ""}],
            ),
            _actionable_event(mechanism_summary="N/A insufficient evidence."),
        ):
            block = compose_actionability_check(ev)
            self.assertIn(block["risk_level"], {"high", "elevated", "standard"})


if __name__ == "__main__":
    unittest.main()
