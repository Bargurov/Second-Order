"""A2-1 — the shared finalized-analysis fixture IS real finalizer output.

``frontend/src/lib/__tests__/fixtures/finalized-analysis-readout.json`` is the
cross-layer contract fixture the Mechanism & Resolution Readout regression
imports.  Its honesty rests on one property: it must BE what
``analyze_event._finalize_analysis`` — the shared normalization pipeline used
by the live API path — actually produces, not a hand-authored approximation in
frontend shape.

This module regenerates the fixture from the exact raw input below and
deep-equals the result against the committed file, so the two layers cannot
drift apart silently.  No provider is called (the finalizer is a pure offline
pipeline) and no database is touched.
"""

import json
import os
import unittest

from analyze_event import _finalize_analysis

FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "frontend", "src", "lib", "__tests__",
    "fixtures", "finalized-analysis-readout.json",
)

HEADLINE = ("US Treasury issues 6-month licence restoring Chevron "
            "Venezuelan heavy-sour crude liftings")
STAGE = "realized"
PERSISTENCE = "structural"

# The raw parsed-LLM dict the fixture is captured from.  Deliberately rich:
# it exercises every structure the readout repair renders — typed hops with
# actors / channels / market landings / timing, counterforce and blocker
# kinds with a chain_hop link, typed and unclassified barrier kinds,
# structured breakpoints with a proof/falsifier cross-link, structured
# minimum proof and confirming evidence, ranked asset objects, the canonical
# horizon checkpoints, the monitor plan, regime caveats and source quality.
RAW: dict = {
    "what_changed": ("The US Treasury issued a 6-month OFAC licence allowing "
                     "Chevron to resume lifting Venezuelan heavy-sour crude "
                     "for delivery to US Gulf Coast refiners."),
    "mechanism_summary": (
        "The primary transmission channel is a regulatory gate: the OFAC "
        "licence reopens a physical heavy-sour crude supply line into US Gulf "
        "Coast coking refineries. Gulf Coast cokers such as Valero and PBF "
        "gain feedstock optionality and margin, while Canadian heavy "
        "producers Suncor and Cenovus lose captive discount pricing on WCS "
        "barrels. The second-order repricing is a substitution effect: the "
        "WCS-WTI differential narrows as Gulf Coast buyers rotate to "
        "Venezuelan grades, compressing the discount Canadian sellers must "
        "offer to clear volumes."),
    "beneficiaries": ["Valero Energy", "PBF Energy"],
    "losers": ["Suncor Energy", "Cenovus Energy"],
    "beneficiary_tickers": ["VLO", "PBF"],
    "loser_tickers": ["SU", "CVE"],
    "assets_to_watch": [],
    "confidence": "medium",
    "confidence_rationale": ("Licence terms are published; volume ramp "
                             "timing is the main uncertainty."),
    "transmission_chain": [
        "OFAC licence issued",
        "Gulf Coast cokers rotate feedstock",
        "WCS-WTI differential narrows",
    ],
    "transmission_path": [
        {"action": ("US Treasury OFAC issues a 6-month specific licence "
                    "authorising Chevron Venezuelan crude liftings"),
         "hop": ("US Treasury OFAC issues a 6-month specific licence "
                 "authorising Chevron Venezuelan crude liftings"),
         "channel": "regulatory",
         "actor": "US Treasury OFAC",
         "expected_market_effect": ("Heavy-sour feedstock supply to the US "
                                    "Gulf Coast increases within the licence "
                                    "window"),
         "timing": "1-5d"},
        {"action": ("Gulf Coast coking refiners Valero and PBF rotate "
                    "feedstock slates toward discounted Venezuelan "
                    "heavy-sour grades"),
         "hop": ("Gulf Coast coking refiners Valero and PBF rotate "
                 "feedstock slates toward discounted Venezuelan "
                 "heavy-sour grades"),
         "channel": "supply",
         "actor": "Valero, PBF",
         "expected_market_effect": ("Coking margins for VLO and PBF widen "
                                    "on cheaper feedstock"),
         "timing": "5-20d"},
        {"action": ("Canadian heavy-sour sellers cut the WCS discount to "
                    "keep Gulf Coast outlet share against Venezuelan "
                    "barrels"),
         "hop": ("Canadian heavy-sour sellers cut the WCS discount to keep "
                 "Gulf Coast outlet share against Venezuelan barrels"),
         "channel": "pricing_power",
         "actor": "Suncor, Cenovus",
         "expected_market_effect": ("WCS-WTI discount narrows; SU and CVE "
                                    "realised pricing weakens"),
         "timing": "5-20d"},
    ],
    "substitution_barriers": [
        {"barrier": ("Gulf Coast coking units are configured for API 8-16 "
                     "heavy-sour crude; light-sweet grades are not a 1:1 "
                     "substitute"),
         "kind": "physical_sole_source", "severity": "high"},
        {"barrier": ("Jones Act tanker availability limits how quickly "
                     "alternative domestic barrels can reach Gulf Coast "
                     "berths"),
         "kind": "logistics", "severity": "medium"},
    ],
    "counterforces": [
        {"force": ("OPEC+ raises heavy-sour export quotas, restoring "
                   "alternative supply and compressing the licence "
                   "advantage"),
         "actor": "OPEC+", "likelihood": "medium", "kind": "counterforce"},
        {"force": ("OFAC revokes or declines to renew the licence before "
                   "meaningful liftings resume"),
         "actor": "US Treasury OFAC", "likelihood": "medium",
         "kind": "blocker",
         "chain_hop": ("cuts off step 1: the licence is the regulatory gate "
                       "the whole chain passes through")},
    ],
    "adversarial_challenge": (
        "The licence advantage may already be priced: VLO and PBF crack-"
        "spread proxies rallied on the initial licence headline, and the "
        "WCS-WTI discount narrowed 1.2pp before any physical lifting "
        "resumed. If the volume ramp disappoints, the margin repricing "
        "reverses."),
    "competing_thesis": {
        "primary_thesis": (
            "OFAC licence restores Chevron Venezuelan heavy-sour liftings; "
            "cheaper API 8-16 feedstock reaches Gulf Coast cokers; VLO and "
            "PBF refining margins lift while WCS sellers SU and CVE lose "
            "outlet share; confirmed if the WCS-WTI discount narrows >=1.5pp "
            "within 5d."),
        "alternative_thesis": (
            "Licence volumes stay token-sized; Gulf Coast slates barely "
            "change and the WCS-WTI discount re-widens as Canadian supply "
            "growth dominates."),
        "discriminator": {
            "observation": ("WCS-WTI discount versus the pre-licence level "
                            "after five sessions"),
            "favors_primary_if": "discount narrows >=1.5pp within 5d",
            "favors_alternative_if": "discount unchanged or wider after 5d",
            "timing": "5d",
        },
    },
    "monitor_plan": {
        "first_decisive_tell": {
            "observation": ("First reported Venezuelan cargo fixture for a "
                            "US Gulf Coast discharge port"),
            "channel": "commodities",
            "what_it_means": ("Physical liftings are actually resuming, not "
                              "just headline optionality"),
        },
        "no_call_signals": [
            {"observation": ("WCS-WTI discount and VLO/PBF crack proxies "
                             "both flat for ten sessions"),
             "channel": "commodities",
             "why_no_call": ("Neither the primary nor the alternative "
                             "reading is transmitting; the licence is "
                             "market-irrelevant so far")},
        ],
    },
    "hidden_mechanism": {
        "bottleneck_type": "commodity_quality_mismatch",
        "transmission_type": "physical_flow",
        "channel_domain": "supply_chain",
        "forensic_note": ("Gulf Coast coking refineries are configured for "
                          "heavy-sour API 8-16 crude; light-sweet is not a "
                          "1:1 substitute."),
        "asset_rationales": {
            "VLO": ("Largest Gulf Coast coking capacity configured for the "
                    "heavy-sour grades the licence restores"),
            "PBF": ("Chalmette and Torrance cokers run the exact heavy "
                    "slate Venezuelan barrels feed"),
        },
        "minimum_proof_set": [
            {"observation": "WCS-WTI discount versus pre-licence level",
             "channel": "commodities", "threshold": ">=1.5pp narrower",
             "timing": "1-5d"},
            {"observation": "VLO 5d relative move versus XLE",
             "channel": "equities", "threshold": ">= +2% relative",
             "timing": "1-5d"},
        ],
        "optional_confirming_evidence": [
            {"observation": ("US Gulf Coast heavy crude import volumes in "
                             "the weekly EIA print"),
             "channel": "commodities"},
        ],
        "critical_breakpoints": [
            {"signal": ("OFAC licence revoked or renewal denied before "
                        "first liftings"),
             "channel": "commodities", "timing": "1-5d",
             "condition": ("Treasury reverses the licence under sanctions "
                           "pressure"),
             "threshold_or_observation": ("OFAC public notice withdrawing "
                                          "or suspending the licence"),
             "why_it_changes_thesis": ("The licence is the regulatory gate; "
                                       "without it no barrel moves and the "
                                       "margin thesis dies"),
             "linked_proof_or_falsifier": "key_falsifiers:0"},
        ],
        "substitution_escape_path": ("Canadian sellers reroute WCS barrels "
                                     "to West Coast and Asian buyers via "
                                     "TMX, bypassing the Gulf Coast "
                                     "competition."),
        "regime_caveats": [
            {"condition": ("Crude demand holds near current levels through "
                           "the licence window"),
             "effect_on_thesis": ("A demand downturn would compress all "
                                  "coking margins and swamp the feedstock "
                                  "advantage"),
             "evidence_to_revisit": ("US refinery utilisation printing "
                                     "below 85% for two consecutive weeks"),
             "domain": "credit"},
        ],
        "source_quality": {
            "source_type": "policy_action",
            "specificity": "high",
            "uncertainty_level": "low",
            "evidence_limitations": ("Licence volume caps and renewal "
                                     "conditions are not yet published."),
        },
    },
    "primary_assets": [
        {"symbol": "VLO", "rank": 1,
         "rationale": ("Largest Gulf Coast coking capacity for the restored "
                       "heavy-sour feedstock")},
        {"symbol": "PBF", "rank": 2,
         "rationale": ("Highest margin sensitivity to heavy-sour feedstock "
                       "cost among Gulf refiners")},
    ],
    "secondary_assets": [
        {"symbol": "SU", "rank": 1,
         "rationale": ("Loses captive Gulf Coast outlet pricing as "
                       "Venezuelan barrels return")},
    ],
    "hedge_or_signal_assets": [
        {"symbol": "XLE", "rank": 1,
         "rationale": ("Sector control: separates refiner-specific margin "
                       "effect from broad energy beta")},
    ],
    "key_falsifiers": [
        "OFAC licence revoked or suspended before first liftings resume",
        "WCS-WTI discount unchanged or wider after five sessions",
        "VLO and PBF underperform XLE over the first five sessions",
    ],
    "minimum_proof_set": [
        {"observation": "WCS-WTI discount versus pre-licence level",
         "channel": "commodities", "threshold": ">=1.5pp narrower",
         "timing": "1-5d"},
        {"observation": "VLO 5d relative move versus XLE",
         "channel": "equities", "threshold": ">= +2% relative",
         "timing": "1-5d"},
    ],
    "horizon_checkpoints": {
        "timing_profile": "delayed_pass_through",
        "horizons": [
            {"horizon": "1d",
             "expected": ["Refiner equities open firmer on licence headline"],
             "confirms_if": ["VLO and PBF outperform XLE on the day"],
             "falsifies_if": ["No refiner reaction despite the licence"]},
            {"horizon": "5d",
             "expected": ["WCS-WTI discount starts narrowing"],
             "confirms_if": ["Discount narrows >=1.5pp versus pre-licence"],
             "falsifies_if": ["Discount unchanged or wider"]},
            {"horizon": "20d",
             "expected": ["First Venezuelan cargoes discharge at Gulf ports"],
             "confirms_if": ["EIA shows rising Gulf heavy-sour imports"],
             "falsifies_if": ["No physical liftings within the window"]},
        ],
    },
    "expected_first_order_channels": ["commodities", "equities"],
    "expected_second_order_channels": ["credit"],
    "regime_conditioned_caveat": (
        "Holds while US refinery utilisation stays above the mid-80s; a "
        "demand-led margin downturn would swamp the feedstock advantage."),
    "if_persists": {},
    "currency_channel": {},
}


def _generate() -> dict:
    """Run the real finalizer over a deep copy of the raw input."""
    return _finalize_analysis(
        json.loads(json.dumps(RAW)), HEADLINE, STAGE, PERSISTENCE)


class TestFinalizedFixtureFidelity(unittest.TestCase):

    def test_the_committed_fixture_is_exactly_the_finalizer_output(self):
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            fixture = json.load(fh)
        generated = json.loads(json.dumps(_generate(), default=str))
        self.assertEqual(
            generated, fixture,
            "real finalizer output drifted from the shared cross-layer "
            "fixture the frontend readout regression imports — recapture "
            "the fixture from this module's RAW input")

    def test_the_finalizer_is_deterministic_over_this_input(self):
        a = json.dumps(_generate(), sort_keys=True, default=str)
        b = json.dumps(_generate(), sort_keys=True, default=str)
        self.assertEqual(a, b)

    def test_the_fixture_exercises_every_repaired_structure(self):
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            f = json.load(fh)
        hops = f["transmission_path"]
        self.assertEqual(len(hops), 3)
        for hop in hops:
            for key in ("hop", "action", "actor", "channel",
                        "expected_market_effect", "timing"):
                self.assertIn(key, hop)
        kinds = {c.get("kind") for c in f["counterforces"]}
        self.assertEqual(kinds, {"counterforce", "blocker"})
        self.assertTrue(any(c.get("chain_hop") for c in f["counterforces"]))
        self.assertTrue(any(b.get("kind") == "physical_sole_source"
                            for b in f["substitution_barriers"]))
        hm = f["hidden_mechanism"]
        self.assertTrue(hm["critical_breakpoints"])
        self.assertIn("linked_proof_or_falsifier",
                      hm["critical_breakpoints"][0])
        self.assertTrue(hm["optional_confirming_evidence"])
        self.assertTrue(hm["regime_caveats"])
        self.assertEqual(hm["source_quality"]["source_type"], "policy_action")
        self.assertTrue(all(isinstance(p, dict) and p.get("observation")
                            for p in f["minimum_proof_set"]))
        self.assertTrue(all(isinstance(a, dict) and a.get("symbol")
                            for a in f["primary_assets"]))
        self.assertEqual(f["horizon_checkpoints"]["timing_profile"],
                         "delayed_pass_through")
        self.assertEqual(len(f["horizon_checkpoints"]["horizons"]), 3)
        self.assertTrue(f["monitor_plan"]["first_decisive_tell"])
        self.assertTrue(f["monitor_plan"]["no_call_signals"])

    def test_every_readout_field_survives_the_saved_snapshot_round_trip(self):
        """Fresh/saved parity at the contract level: the A1-3R snapshot must
        carry every structured field the repaired readout consumes, so a
        numeric or durable reopen feeds the adapter the same input the fresh
        run did."""
        import analysis_result_snapshot as ars
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            fixture = json.load(fh)
        restored = ars.apply_result_snapshot(
            {}, ars.build_result_snapshot(fixture))
        drifted = [f for f in ars.RESULT_SNAPSHOT_FIELDS
                   if f in fixture and restored.get(f) != fixture.get(f)]
        self.assertEqual(drifted, [])
        # The structured shapes specifically must survive intact.
        for f in ("transmission_path", "counterforces", "hidden_mechanism",
                  "minimum_proof_set", "primary_assets",
                  "horizon_checkpoints", "monitor_plan"):
            self.assertEqual(restored[f], fixture[f], f)

    def test_the_fixture_carries_no_secret_or_local_path(self):
        with open(FIXTURE_PATH, encoding="utf-8") as fh:
            blob = fh.read().lower()
        for leak in ("c:\\", "/users/", "api_key", "sk-ant", "password"):
            self.assertNotIn(leak, blob)


if __name__ == "__main__":
    unittest.main()
