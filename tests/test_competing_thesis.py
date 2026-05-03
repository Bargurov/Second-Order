"""
tests/test_competing_thesis.py

Contract tests for the competing-thesis layer.

primary_thesis is the single load-bearing field; alternative_thesis and
discriminator are optional layers that only attach when they add
information.

Covers:
  1. Registry — competing_thesis is in LLM_CORE_FIELDS and defaults to {}.
  2. Sanitizer — primary_thesis alone passes through; alternative_thesis
     and discriminator attach only when materially distinct / decisive;
     missing primary collapses the block; invalid channels drop evidence
     entries; discriminator timing restricted to fast resolutions.
  3. Registry passthrough — build_analysis_dict carries competing_thesis.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    LLM_CORE_FIELDS,
    _clean_competing_thesis,
    _clean_discriminator,
    _clean_evidence_list,
    build_analysis_dict,
)


def _valid_discriminator() -> dict:
    return {
        "observation": "TSM relative performance vs SMH intraday",
        "channel": "equities",
        "outcome_if_primary": "TSM outperforms SMH by ≥1pp",
        "outcome_if_alternative": "TSM underperforms SMH intraday",
        "timing": "1d",
    }


def _valid_block() -> dict:
    return {
        "primary_thesis":     "Export controls hit Chinese fabs and lift TSMC scarcity premium.",
        "alternative_thesis": "Controls are already priced; the hit lands without the offsetting premium.",
        "evidence_favoring_primary": [
            {"observation": "LRCX / AMAT close down ≥3% on volume",
             "channel": "equities"},
        ],
        "evidence_favoring_alternative": [
            {"observation": "TSM underperforms SMH intraday",
             "channel": "equities"},
        ],
        "discriminator": _valid_discriminator(),
    }


# ---------------------------------------------------------------------------
# 1. Registry
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def test_competing_thesis_in_llm_core_fields(self):
        self.assertIn("competing_thesis", LLM_CORE_FIELDS)

    def test_missing_competing_thesis_defaults_to_empty_dict(self):
        result = build_analysis_dict({"what_changed": "x"})
        self.assertIn("competing_thesis", result)
        self.assertEqual(result["competing_thesis"], {})

    def test_present_competing_thesis_is_preserved(self):
        payload = _valid_block()
        result = build_analysis_dict({
            "what_changed":     "x",
            "competing_thesis": payload,
        })
        self.assertEqual(result["competing_thesis"], payload)

    def test_primary_only_is_preserved(self):
        result = build_analysis_dict({
            "what_changed":     "x",
            "competing_thesis": {
                "primary_thesis": "Single primary read of the event.",
            },
        })
        ct = result["competing_thesis"]
        self.assertEqual(ct["primary_thesis"], "Single primary read of the event.")
        self.assertNotIn("alternative_thesis", ct)
        self.assertNotIn("discriminator", ct)


# ---------------------------------------------------------------------------
# 2a. Sanitizer — the happy path
# ---------------------------------------------------------------------------

class TestSanitizerHappyPath(unittest.TestCase):

    def test_valid_block_passes_through(self):
        out = _clean_competing_thesis(_valid_block())
        self.assertIn("primary_thesis", out)
        self.assertIn("alternative_thesis", out)
        self.assertIn("evidence_favoring_primary", out)
        self.assertIn("evidence_favoring_alternative", out)
        self.assertIn("discriminator", out)
        self.assertEqual(out["discriminator"]["timing"], "1d")

    def test_evidence_list_capped_at_three(self):
        raw = _valid_block()
        raw["evidence_favoring_primary"] = [
            {"observation": f"obs {i}", "channel": "commodities"}
            for i in range(6)
        ]
        out = _clean_competing_thesis(raw)
        self.assertLessEqual(len(out["evidence_favoring_primary"]), 3)


# ---------------------------------------------------------------------------
# 2b. Sanitizer — collapse paths
# ---------------------------------------------------------------------------

class TestSanitizerCollapse(unittest.TestCase):

    def test_non_dict_input_returns_empty(self):
        self.assertEqual(_clean_competing_thesis(None), {})
        self.assertEqual(_clean_competing_thesis("a string"), {})
        self.assertEqual(_clean_competing_thesis(["list"]), {})

    def test_missing_primary_thesis_collapses_block(self):
        raw = _valid_block()
        raw["primary_thesis"] = ""
        self.assertEqual(_clean_competing_thesis(raw), {})

    def test_missing_alternative_thesis_keeps_primary(self):
        """alternative_thesis is optional — block survives with primary
        only when no materially distinct rival is supplied."""
        raw = _valid_block()
        raw["alternative_thesis"] = None
        out = _clean_competing_thesis(raw)
        self.assertTrue(out)
        self.assertIn("primary_thesis", out)
        self.assertNotIn("alternative_thesis", out)
        self.assertNotIn("evidence_favoring_alternative", out)
        self.assertNotIn("discriminator", out)

    def test_missing_discriminator_keeps_alternative(self):
        """A rival thesis without a fast discriminator is acceptable —
        the rival itself is information; only the discriminator drops."""
        raw = _valid_block()
        raw["discriminator"] = {}
        out = _clean_competing_thesis(raw)
        self.assertTrue(out)
        self.assertIn("primary_thesis", out)
        self.assertIn("alternative_thesis", out)
        self.assertNotIn("discriminator", out)

    def test_thin_discriminator_dropped_alternative_kept(self):
        raw = _valid_block()
        raw["discriminator"] = {"observation": "something happens"}
        out = _clean_competing_thesis(raw)
        self.assertTrue(out)
        self.assertIn("alternative_thesis", out)
        self.assertNotIn("discriminator", out)

    def test_alternative_string_equal_to_primary_dropped(self):
        """A near-clone alternative is not materially distinct."""
        raw = _valid_block()
        raw["alternative_thesis"] = raw["primary_thesis"]
        out = _clean_competing_thesis(raw)
        self.assertTrue(out)
        self.assertNotIn("alternative_thesis", out)
        self.assertNotIn("discriminator", out)

    def test_alternative_prefix_of_primary_dropped(self):
        raw = _valid_block()
        raw["alternative_thesis"] = raw["primary_thesis"][:30]
        out = _clean_competing_thesis(raw)
        self.assertTrue(out)
        self.assertNotIn("alternative_thesis", out)

    def test_evidence_for_alternative_dropped_when_alt_missing(self):
        """Evidence for an unstated rival is incoherent — drop it."""
        raw = _valid_block()
        raw["alternative_thesis"] = None
        out = _clean_competing_thesis(raw)
        self.assertNotIn("evidence_favoring_alternative", out)

    def test_null_like_thesis_strings_are_treated_as_missing(self):
        raw = _valid_block()
        raw["primary_thesis"] = "N/A"
        self.assertEqual(_clean_competing_thesis(raw), {})


# ---------------------------------------------------------------------------
# 2c. Discriminator discipline
# ---------------------------------------------------------------------------

class TestDiscriminator(unittest.TestCase):

    def test_valid_discriminator_passes(self):
        out = _clean_discriminator(_valid_discriminator())
        self.assertEqual(out["channel"], "equities")
        self.assertEqual(out["timing"], "1d")

    def test_invalid_channel_rejects(self):
        d = _valid_discriminator()
        d["channel"] = "sentiment"
        self.assertEqual(_clean_discriminator(d), {})

    def test_missing_outcome_rejects(self):
        d = _valid_discriminator()
        d["outcome_if_alternative"] = ""
        self.assertEqual(_clean_discriminator(d), {})

    def test_slow_timing_stripped_not_rejected(self):
        """A 20d+ timing isn't a discriminator — the sanitizer drops
        the timing field but keeps the discriminator itself since the
        observation + outcomes are still decisive."""
        d = _valid_discriminator()
        d["timing"] = "20d+"
        out = _clean_discriminator(d)
        self.assertTrue(out, "discriminator should still be emitted")
        self.assertNotIn("timing", out)

    def test_fast_5_day_timing_preserved(self):
        d = _valid_discriminator()
        d["timing"] = "1-5d"
        out = _clean_discriminator(d)
        self.assertEqual(out["timing"], "1-5d")


# ---------------------------------------------------------------------------
# 2e. Actionable-discipline tests — alternative must be materially
#     different, discriminator must be concrete, generic hedges drop.
# ---------------------------------------------------------------------------

class TestAlternativeMaterialDifference(unittest.TestCase):
    """alternative_thesis must say something different from the
    primary read, not reword it."""

    def test_real_alternative_passes_with_discriminator(self):
        """A genuinely distinct rival mechanism + concrete discriminator
        survives the sanitizer with all five sub-fields."""
        raw = {
            "primary_thesis": (
                "US Treasury licence restores Chevron Venezuelan heavy-sour "
                "liftings; PBF and VLO refining margins lift on cheaper feedstock; "
                "confirmed if WCS-WTI discount widens >=2pp within 5d."
            ),
            "alternative_thesis": (
                "PDVSA infrastructure constraints cap delivered volumes well "
                "below licence headline; refining margin relief never materializes."
            ),
            "evidence_favoring_primary": [
                {"observation": "Chevron-branded cargoes loading at Jose",
                 "channel": "commodities"},
            ],
            "evidence_favoring_alternative": [
                {"observation": "PDVSA issues operational-delay statement",
                 "channel": "commodities"},
            ],
            "discriminator": {
                "observation": "Vessel-tracking data on Chevron Venezuelan loadings",
                "channel": "commodities",
                "outcome_if_primary": ">=50kbd of new Chevron-branded flow within 5d",
                "outcome_if_alternative": "Zero new loadings in shipping trackers within 5d",
                "timing": "1-5d",
            },
        }
        out = _clean_competing_thesis(raw)
        self.assertIn("primary_thesis", out)
        self.assertIn("alternative_thesis", out)
        self.assertIn("evidence_favoring_alternative", out)
        self.assertIn("discriminator", out)

    def test_duplicate_alternative_removed(self):
        """A reworded primary (high content-token overlap) is not a real
        alternative — the alternative_thesis and its retinue drop."""
        primary = (
            "Chevron Venezuelan licence restores heavy-sour feedstock to "
            "Gulf Coast cokers; PBF and VLO refining margins widen."
        )
        raw = {
            "primary_thesis": primary,
            # Same content tokens, just reordered/reworded.
            "alternative_thesis": (
                "Chevron Venezuelan licence restores heavy-sour feedstock to "
                "Gulf Coast cokers; PBF refining margins widen for VLO."
            ),
            "discriminator": _valid_discriminator(),
        }
        out = _clean_competing_thesis(raw)
        self.assertIn("primary_thesis", out)
        self.assertNotIn("alternative_thesis", out)
        self.assertNotIn("evidence_favoring_alternative", out)
        self.assertNotIn("discriminator", out)

    def test_weak_alternative_yields_empty_alt_fields(self):
        """A generic placeholder alternative ('markets may react
        differently') is rejected; primary survives alone."""
        raw = {
            "primary_thesis": "Concrete primary read with named winners and channel.",
            "alternative_thesis": "Markets may react differently than expected.",
            "evidence_favoring_alternative": [
                {"observation": "Some hedge", "channel": "equities"},
            ],
            "discriminator": _valid_discriminator(),
        }
        out = _clean_competing_thesis(raw)
        self.assertIn("primary_thesis", out)
        self.assertNotIn("alternative_thesis", out)
        self.assertNotIn("evidence_favoring_alternative", out)
        self.assertNotIn("discriminator", out)

    def test_no_alternative_yields_empty_alt_fields(self):
        """When the LLM omits the alternative entirely, alt fields are
        absent — no None placeholders, no empty strings, no padding."""
        out = _clean_competing_thesis({
            "primary_thesis": "Concrete primary read.",
        })
        self.assertEqual(set(out.keys()), {"primary_thesis", "evidence_favoring_primary"})


class TestDiscriminatorConcreteness(unittest.TestCase):
    """The discriminator must name an observation specific enough that
    a desk could check it on the tape — not a generic hedge."""

    def test_concrete_discriminator_passes(self):
        out = _clean_discriminator(_valid_discriminator())
        self.assertTrue(out)
        self.assertIn("observation", out)
        self.assertIn("outcome_if_primary", out)
        self.assertIn("outcome_if_alternative", out)

    def test_vague_observation_rejected(self):
        d = _valid_discriminator()
        d["observation"] = "Markets may react differently to the news"
        self.assertEqual(_clean_discriminator(d), {})

    def test_vague_outcome_rejected(self):
        d = _valid_discriminator()
        d["outcome_if_primary"] = "Sentiment shifts toward the bull case"
        self.assertEqual(_clean_discriminator(d), {})

    def test_outcome_depends_phrase_rejected(self):
        d = _valid_discriminator()
        d["outcome_if_alternative"] = "Outcome depends on response from the desk"
        self.assertEqual(_clean_discriminator(d), {})

    def test_reworded_outcomes_rejected(self):
        """outcome_if_primary and outcome_if_alternative must be
        substantively incompatible — two rewordings of the same hedge
        are not a discriminator."""
        d = _valid_discriminator()
        d["outcome_if_primary"]     = "TSM closes up on heavy volume"
        d["outcome_if_alternative"] = "TSM closes up on heavy volume"
        self.assertEqual(_clean_discriminator(d), {})


# ---------------------------------------------------------------------------
# 2d. Evidence list discipline
# ---------------------------------------------------------------------------

class TestEvidenceList(unittest.TestCase):

    def test_valid_entries_pass(self):
        out = _clean_evidence_list([
            {"observation": "oil rallies >3%", "channel": "commodities"},
            {"observation": "KRE lags SPY",    "channel": "equities"},
        ])
        self.assertEqual(len(out), 2)

    def test_invalid_channel_drops_entry(self):
        out = _clean_evidence_list([
            {"observation": "oil rallies", "channel": "sentiment"},
            {"observation": "credit tightens", "channel": "credit"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["channel"], "credit")

    def test_missing_observation_drops_entry(self):
        out = _clean_evidence_list([
            {"observation": "", "channel": "equities"},
            {"channel": "rates"},  # no observation key
        ])
        self.assertEqual(out, [])

    def test_non_list_input_returns_empty(self):
        self.assertEqual(_clean_evidence_list(None), [])
        self.assertEqual(_clean_evidence_list("a string"), [])
        self.assertEqual(_clean_evidence_list({"not": "a list"}), [])


# ---------------------------------------------------------------------------
# 2f. First-order / second-order separation
# ---------------------------------------------------------------------------

def _so(trigger, channel, actor, timing="1-5d"):
    return {
        "trigger": trigger,
        "intermediate_channel": channel,
        "affected_actor": actor,
        "timing": timing,
    }


class TestFirstOrderEffect(unittest.TestCase):
    """``first_order_effect`` is an optional dict on competing_thesis
    describing the direct market / economic impact.  Vague text is
    sanitizer-rejected."""

    def test_concrete_first_order_effect_kept(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock; XOM margins widen on the WCS spread.",
            "first_order_effect": {
                "description": "Brent rallies 2-4% intraday on the headline supply tightening",
                "channel": "commodities",
                "expected_window": "1d",
            },
        })
        fo = out.get("first_order_effect")
        self.assertIsNotNone(fo)
        self.assertEqual(fo["channel"], "commodities")
        self.assertEqual(fo["expected_window"], "1d")

    def test_vague_first_order_effect_dropped(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "first_order_effect": {
                "description": "Markets may react to the announcement",
            },
        })
        self.assertNotIn("first_order_effect", out)

    def test_invalid_channel_dropped_field_kept(self):
        """Bad channel token → field stripped; description survives."""
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "first_order_effect": {
                "description": "Brent rallies 2-4% intraday on the headline.",
                "channel": "sentiment",  # not in enum
                "expected_window": "1d",
            },
        })
        fo = out.get("first_order_effect")
        self.assertIsNotNone(fo)
        self.assertNotIn("channel", fo)
        self.assertEqual(fo["expected_window"], "1d")

    def test_missing_description_collapses_first_order(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "first_order_effect": {
                "channel": "commodities",
                "expected_window": "1d",
            },
        })
        self.assertNotIn("first_order_effect", out)


class TestSecondOrderEffects(unittest.TestCase):
    """``second_order_effects`` is an optional list.  Each entry must
    carry trigger + intermediate_channel + affected_actor + timing —
    entries that skip the intermediate channel are dropped because a
    cascade without a named transmission step isn't a real second-
    order claim."""

    def test_full_second_order_entries_pass(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock; XOM margins widen.",
            "second_order_effects": [
                _so(
                    "Brent-WTI light-heavy diff narrows on supply tightening",
                    "WCS-WTI heavy-sour spread widens",
                    "Canadian oil-sands sellers (SU, CNQ) lose Gulf outlet",
                    timing="5-20d",
                ),
            ],
        })
        so = out.get("second_order_effects")
        self.assertIsNotNone(so)
        self.assertEqual(len(so), 1)
        self.assertEqual(so[0]["timing"], "5-20d")

    def test_entry_missing_intermediate_channel_dropped(self):
        """A second-order claim that skips the intermediate channel is
        just a first-order claim with extra distance — dropped."""
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "second_order_effects": [
                {
                    "trigger": "Brent rallies on supply tightening",
                    "affected_actor": "Canadian oil-sands producers",
                    "timing": "5-20d",
                    # intermediate_channel missing
                },
                _so(
                    "Brent-WTI diff narrows",
                    "WCS-WTI heavy-sour spread widens",
                    "SU and CNQ equities underperform energy peers",
                    timing="5-20d",
                ),
            ],
        })
        so = out.get("second_order_effects") or []
        self.assertEqual(len(so), 1)
        self.assertIn("intermediate_channel", so[0])

    def test_invalid_timing_dropped(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "second_order_effects": [
                _so(
                    "Brent rallies",
                    "WCS-WTI spread widens",
                    "Canadian producers lose share",
                    timing="next quarter",  # not in enum
                ),
            ],
        })
        self.assertNotIn("second_order_effects", out)

    def test_vague_trigger_dropped(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "second_order_effects": [
                _so(
                    "Markets react to the supply news",  # vague
                    "WCS-WTI spread widens",
                    "Canadian producers",
                    timing="5-20d",
                ),
            ],
        })
        self.assertNotIn("second_order_effects", out)

    def test_capped_at_three(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "second_order_effects": [
                _so(
                    f"Trigger {i}",
                    f"Spread {i} widens",
                    f"Actor {i}",
                    timing="5-20d",
                )
                for i in range(6)
            ],
        })
        so = out.get("second_order_effects") or []
        self.assertLessEqual(len(so), 3)

    def test_first_order_only_keeps_second_order_empty(self):
        """When only first-order logic is defensible, the LLM omits
        second_order_effects; the block is absent from the output."""
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock; XOM margins widen.",
            "first_order_effect": {
                "description": "Brent rallies 2-4% intraday on supply tightening",
                "channel": "commodities",
                "expected_window": "1d",
            },
            "second_order_effects": [],
        })
        self.assertIn("first_order_effect", out)
        self.assertNotIn("second_order_effects", out)

    def test_response_shape_unchanged_without_wave_fields(self):
        """An LLM response with no first/second-order fields keeps
        the legacy competing_thesis shape — no new keys appear."""
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
        })
        for key in ("first_order_effect", "second_order_effects"):
            self.assertNotIn(key, out)


# ---------------------------------------------------------------------------
# 2g. Scenario-conditioned proof / falsifier checks
# ---------------------------------------------------------------------------

def _scenario(condition, why, evidence):
    return {
        "condition":         condition,
        "why_it_matters":    why,
        "evidence_to_watch": evidence,
    }


class TestScenarioConditionsSanitizer(unittest.TestCase):
    """``scenario_conditions`` is an optional list inside
    competing_thesis.  Each entry must carry the three required text
    fields and survive vague-text rejection."""

    def test_concrete_scenario_kept(self):
        out = _clean_competing_thesis({
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "XOM and CVX margins widen on the WCS-WTI spread."
            ),
            "scenario_conditions": [
                _scenario(
                    "OPEC extends the voluntary cut beyond June",
                    "Sustained cut keeps the WCS-WTI heavy-sour spread wider",
                    "OPEC monthly press release confirms extension by 2026-06-15",
                ),
            ],
        })
        sc = out.get("scenario_conditions") or []
        self.assertEqual(len(sc), 1)
        for key in ("condition", "why_it_matters", "evidence_to_watch"):
            self.assertIn(key, sc[0])

    def test_vague_condition_dropped(self):
        out = _clean_competing_thesis({
            "primary_thesis": (
                "Saudi Aramco cut tightens Gulf Coast feedstock."
            ),
            "scenario_conditions": [
                _scenario(
                    "Markets may react differently to news",  # vague
                    "Thesis amplifies",
                    "Watch the tape",
                ),
            ],
        })
        self.assertNotIn("scenario_conditions", out)

    def test_missing_required_field_drops_entry(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "scenario_conditions": [
                {
                    "condition": "OPEC extends cut beyond June",
                    # missing why_it_matters
                    "evidence_to_watch": "Press release on 2026-06-15",
                },
                _scenario(
                    "Russia accepts ceasefire terms by Q3",
                    "Ceasefire releases sanctioned oil supply",
                    "UN press conference confirms acceptance",
                ),
            ],
        })
        sc = out.get("scenario_conditions") or []
        self.assertEqual(len(sc), 1)
        self.assertIn("Russia", sc[0]["condition"])

    def test_capped_at_three(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
            "scenario_conditions": [
                _scenario(
                    f"Condition {i} threshold above level",
                    f"Why it matters {i} amplifies cascade",
                    f"Evidence {i} watch press release",
                )
                for i in range(6)
            ],
        })
        sc = out.get("scenario_conditions") or []
        self.assertLessEqual(len(sc), 3)

    def test_response_shape_unchanged_when_field_absent(self):
        out = _clean_competing_thesis({
            "primary_thesis": "Saudi cut tightens Gulf feedstock.",
        })
        self.assertNotIn("scenario_conditions", out)


class TestScenarioObservability(unittest.TestCase):
    """When scenario_conditions exist, proof / falsifier coverage
    must reference the named condition.  Without coverage the tier
    system caps the call at ``watch_only``."""

    def _event_with_conditions(self, scenario_conditions, **overrides):
        ev = {
            "mechanism_family": "supply_normalization",
            "expected_first_order_channels": ["commodities", "equities"],
            "what_changed": (
                "Saudi Aramco cut crude liftings by 1mbd from August "
                "contract volumes, tightening Gulf Coast feedstock supply."
            ),
            "mechanism_summary": (
                "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
                "Coast refinery feedstock and widening WCS-WTI heavy-sour "
                "discount."
            ),
            "beneficiaries": ["XOM"],
            "losers": ["SU"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["SU"],
            "assets_to_watch": ["XOM", "SU"],
            "primary_assets": [
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops as WCS discount widens."},
            ],
            "secondary_assets": [],
            "hedge_or_signal_assets": [],
            "competing_thesis": {
                "primary_thesis": (
                    "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                    "XOM margins widen on the WCS-WTI heavy-sour spread."
                ),
                "scenario_conditions": scenario_conditions,
            },
        }
        ev.update(overrides)
        return ev

    def test_no_conditions_no_audit(self):
        from low_information_gate import evaluate_scenario_observability
        ev = self._event_with_conditions(scenario_conditions=[])
        # Empty list filters out by sanitizer — but we test the audit
        # directly when no list is even present.
        ev["competing_thesis"].pop("scenario_conditions", None)
        result = evaluate_scenario_observability(ev)
        self.assertEqual(result["conditions"], 0)
        self.assertIsNone(result["downgrade"])

    def test_observed_condition_clears_audit(self):
        """A scenario condition whose tokens overlap with a proof
        item is observable — no downgrade fires."""
        from low_information_gate import evaluate_scenario_observability
        ev = self._event_with_conditions(
            scenario_conditions=[
                _scenario(
                    "OPEC extends voluntary cut beyond June meeting",
                    "Sustained cut keeps WCS-WTI heavy-sour spread wider",
                    "OPEC monthly press release confirms extension",
                ),
            ],
            minimum_proof_set=[
                {"observation": "OPEC monthly statement confirms extension within 5d",
                 "channel": "commodities", "threshold": "any extension",
                 "timing": "1-5d"},
            ],
            key_falsifiers=[
                {"observation": "OPEC abandons voluntary cut at next meeting",
                 "channel": "commodities", "threshold": "any reversal",
                 "timing": "1-5d"},
            ],
        )
        result = evaluate_scenario_observability(ev)
        self.assertEqual(result["conditions"], 1)
        self.assertEqual(result["observed"], 1)
        self.assertEqual(result["unobserved"], [])
        self.assertIsNone(result["downgrade"])

    def test_unobserved_condition_signals_watch_only(self):
        """A scenario condition whose tokens don't appear in any
        proof / falsifier item caps the read at watch_only."""
        from low_information_gate import evaluate_scenario_observability
        ev = self._event_with_conditions(
            scenario_conditions=[
                _scenario(
                    "Federal Reserve pivots to easing within 2 meetings",
                    "Easing pivot blunts the cascade by relaxing credit",
                    "FOMC statement signals rate cut at Q3 meeting",
                ),
            ],
            minimum_proof_set=[
                # Proof item is on-thesis but does NOT reference the
                # Fed-pivot condition tokens.
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities", "threshold": "≥2pp",
                 "timing": "5-20d"},
            ],
            key_falsifiers=[],
        )
        result = evaluate_scenario_observability(ev)
        self.assertEqual(result["conditions"], 1)
        self.assertEqual(result["observed"], 0)
        self.assertEqual(len(result["unobserved"]), 1)
        self.assertEqual(result["downgrade"], "watch_only")

    def test_partially_unobserved_caps_tier_at_watch_only(self):
        """End-to-end: when at least one scenario condition is
        unobservable, ``evidence_quality_tier`` must NOT return
        ``actionable``."""
        from low_information_gate import evidence_quality_tier
        ev = self._event_with_conditions(
            scenario_conditions=[
                _scenario(
                    "OPEC extends voluntary cut beyond June meeting",
                    "Sustained cut keeps WCS-WTI heavy-sour spread wider",
                    "OPEC monthly bulletin confirms extension",
                ),
                _scenario(
                    "Federal Reserve pivots to easing within 2 meetings",
                    "Easing pivot blunts the cascade by relaxing credit",
                    "FOMC dot-plot reveals rate cut at Q3 meeting",
                ),
            ],
            minimum_proof_set=[
                {"observation": "OPEC monthly bulletin confirms extension within 5d",
                 "channel": "commodities", "threshold": "any extension",
                 "timing": "1-5d"},
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities", "threshold": "≥2pp",
                 "timing": "5-20d"},
            ],
            key_falsifiers=[
                {"observation": "Saudi cabinet walks back the lifting cut",
                 "channel": "commodities", "threshold": "any reversal",
                 "timing": "1-5d"},
            ],
        )
        # First condition is covered, second isn't — tier must cap
        # at watch_only, NOT actionable.
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_audit_does_not_mutate_event(self):
        from low_information_gate import evaluate_scenario_observability
        ev = self._event_with_conditions(
            scenario_conditions=[
                _scenario(
                    "OPEC extends voluntary cut beyond June",
                    "Sustained cut keeps WCS-WTI heavy-sour spread wider",
                    "OPEC monthly press release confirms extension",
                ),
            ],
        )
        before_keys = set(ev.keys())
        before_ct = set(ev["competing_thesis"].keys())
        evaluate_scenario_observability(ev)
        self.assertEqual(set(ev.keys()), before_keys)
        self.assertEqual(set(ev["competing_thesis"].keys()), before_ct)


# ---------------------------------------------------------------------------
# 2h. Thesis timing discipline
# ---------------------------------------------------------------------------

def _timing_block(reaction="1d", follow="1-5d", stale="5-20d",
                  rationale="realized + medium"):
    return {
        "expected_reaction_window": reaction,
        "follow_through_window":    follow,
        "stale_after":              stale,
        "timing_rationale":         rationale,
    }


class TestThesisTimingSanitizer(unittest.TestCase):
    """``thesis_timing`` lives inside competing_thesis.  Window fields
    are validated against the timing enum; anticipation events can't
    use realized-event timing."""

    def test_concrete_block_passes_through(self):
        from analyze_event import _clean_thesis_timing
        out = _clean_thesis_timing(_timing_block())
        self.assertEqual(out["expected_reaction_window"], "1d")
        self.assertEqual(out["follow_through_window"], "1-5d")
        self.assertEqual(out["stale_after"], "5-20d")
        self.assertIn("timing_rationale", out)

    def test_unknown_window_token_dropped(self):
        from analyze_event import _clean_thesis_timing
        out = _clean_thesis_timing(_timing_block(stale="next quarter"))
        # Reaction + follow_through survive; stale is dropped.
        self.assertIn("expected_reaction_window", out)
        self.assertIn("follow_through_window", out)
        self.assertNotIn("stale_after", out)

    def test_missing_reaction_window_drops_block(self):
        from analyze_event import _clean_thesis_timing
        raw = _timing_block(reaction="invalid")
        # reaction window is required for a valid block.
        self.assertEqual(_clean_thesis_timing(raw), {})

    def test_anticipation_with_realized_timing_rejected(self):
        """Anticipation events can't use 1d reaction — the event
        hasn't happened, so the chain has to wait."""
        from analyze_event import _clean_thesis_timing
        out = _clean_thesis_timing(
            _timing_block(reaction="1d"),
            stage="anticipation",
        )
        self.assertEqual(out, {})

    def test_anticipation_with_5_20d_reaction_kept(self):
        from analyze_event import _clean_thesis_timing
        out = _clean_thesis_timing(
            _timing_block(reaction="5-20d", follow="20d+", stale="20d+"),
            stage="anticipation",
        )
        self.assertEqual(out["expected_reaction_window"], "5-20d")

    def test_non_dict_drops_block(self):
        from analyze_event import _clean_thesis_timing
        self.assertEqual(_clean_thesis_timing(None), {})
        self.assertEqual(_clean_thesis_timing("text"), {})


class TestThesisTimingInference(unittest.TestCase):
    """``_infer_thesis_timing`` derives the four windows from stage +
    persistence (+ family / subtype hints).  Anticipation always
    waits longer than realized."""

    def test_anticipation_uses_delayed_reaction_window(self):
        from analyze_event import _infer_thesis_timing
        out = _infer_thesis_timing(
            "anticipation", "medium", family="sanction",
        )
        self.assertEqual(out["expected_reaction_window"], "5-20d")

    def test_realized_supply_shock_uses_1d_reaction(self):
        from analyze_event import _infer_thesis_timing
        out = _infer_thesis_timing(
            "realized", "structural", family="supply_shock",
        )
        self.assertEqual(out["expected_reaction_window"], "1d")
        # Structural persistence pushes follow-through and stale_after
        # out to the longer windows.
        self.assertEqual(out["follow_through_window"], "5-20d")
        self.assertEqual(out["stale_after"], "20d+")

    def test_realized_industrial_policy_uses_5_20d_reaction(self):
        """Slow-grind families push the realized-event reaction
        window from 1d out to 5-20d."""
        from analyze_event import _infer_thesis_timing
        out = _infer_thesis_timing(
            "realized", "structural", family="industrial_policy",
        )
        self.assertEqual(out["expected_reaction_window"], "5-20d")

    def test_one_off_persistence_compresses_stale(self):
        from analyze_event import _infer_thesis_timing
        out = _infer_thesis_timing("realized", "one_off")
        self.assertEqual(out["stale_after"], "1-5d")

    def test_anticipation_and_realized_disagree(self):
        """Same family + persistence but different stages → different
        reaction windows.  The contract requires this disagreement."""
        from analyze_event import _infer_thesis_timing
        anticipation = _infer_thesis_timing(
            "anticipation", "structural", family="sanction",
        )
        realized = _infer_thesis_timing(
            "realized", "structural", family="sanction",
        )
        self.assertNotEqual(
            anticipation["expected_reaction_window"],
            realized["expected_reaction_window"],
        )

    def test_rationale_includes_stage_and_persistence(self):
        from analyze_event import _infer_thesis_timing
        out = _infer_thesis_timing(
            "realized", "structural", family="supply_shock",
            subtype="oil_supply_shock",
        )
        rationale = out["timing_rationale"]
        self.assertIn("realized", rationale)
        self.assertIn("structural", rationale)
        self.assertIn("supply_shock", rationale)
        self.assertIn("oil_supply_shock", rationale)


class TestThesisTimingFinalizeWiring(unittest.TestCase):
    """``_finalize_analysis`` infers a thesis_timing block when the
    LLM didn't emit one, and re-cleans LLM-emitted blocks against the
    actual stage so anticipation can't smuggle in realized timing."""

    def _build(self, stage="realized", persistence="medium", **overrides):
        from analyze_event import _finalize_analysis
        parsed = {
            "what_changed": (
                "US Treasury issued a 6-month licence for Venezuelan "
                "crude liftings; restoration of heavy-sour feedstock supply."
            ),
            "mechanism_summary": (
                "Treasury restores Chevron's Venezuelan heavy-sour "
                "liftings; cheaper feedstock to Gulf Coast cokers; "
                "WCS-WTI discount widens."
            ),
            "beneficiaries": ["XOM"],
            "losers": ["SU"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["SU"],
            "mechanism_family": "supply_normalization",
            "transmission_chain": [
                "Treasury issues licence",
                "Heavy-sour feedstock supply tightens",
                "WCS-WTI discount widens",
            ],
            "competing_thesis": {
                "primary_thesis": (
                    "Treasury licence restores Gulf Coast feedstock; "
                    "XOM and CVX margins widen on the WCS-WTI spread."
                ),
            },
            "primary_assets": [
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct heavy-sour Gulf Coast refiner."},
            ],
        }
        parsed.update(overrides)
        return _finalize_analysis(
            parsed, headline="Treasury issues licence",
            stage=stage, persistence=persistence,
        )

    def test_inferred_block_attached_when_llm_omits(self):
        out = self._build()
        ct = out.get("competing_thesis") or {}
        timing = ct.get("thesis_timing")
        self.assertIsInstance(timing, dict)
        self.assertIn("expected_reaction_window", timing)
        self.assertIn("timing_rationale", timing)

    def test_anticipation_inference_uses_delayed_window(self):
        out = self._build(stage="anticipation")
        ct = out.get("competing_thesis") or {}
        timing = ct.get("thesis_timing") or {}
        self.assertEqual(
            timing.get("expected_reaction_window"), "5-20d",
        )

    def test_llm_emitted_realized_timing_dropped_for_anticipation(self):
        """LLM emits 1d reaction on an anticipation event — the
        finalize-time re-clean drops it and inference re-derives a
        stage-appropriate block."""
        out = self._build(
            stage="anticipation",
            competing_thesis={
                "primary_thesis": (
                    "Treasury licence restores Gulf Coast feedstock; "
                    "XOM and CVX margins widen on the WCS-WTI spread."
                ),
                "thesis_timing": _timing_block(reaction="1d"),
            },
        )
        ct = out.get("competing_thesis") or {}
        timing = ct.get("thesis_timing") or {}
        # The realized "1d" was rejected, inference put us at 5-20d.
        self.assertEqual(
            timing.get("expected_reaction_window"), "5-20d",
        )

    def test_response_shape_unchanged(self):
        """thesis_timing nests inside competing_thesis — no new
        top-level keys."""
        out = self._build()
        self.assertNotIn("thesis_timing", out)
        self.assertIn(
            "thesis_timing",
            out.get("competing_thesis") or {},
        )


class TestThesisTimingAlignment(unittest.TestCase):
    """``evaluate_thesis_timing_alignment`` audits proof / falsifier
    timing against the declared windows."""

    def _event(self, *, timing_windows, proof_timings):
        return {
            "competing_thesis": {
                "primary_thesis": "Some primary read.",
                "thesis_timing": {
                    **timing_windows,
                    "timing_rationale": "test",
                },
            },
            "minimum_proof_set": [
                {"observation": f"Obs {i}",
                 "channel": "commodities", "timing": t}
                for i, t in enumerate(proof_timings)
            ],
            "key_falsifiers": [],
            "critical_breakpoints": [],
        }

    def test_aligned_proof_no_downgrade(self):
        from low_information_gate import evaluate_thesis_timing_alignment
        ev = self._event(
            timing_windows={
                "expected_reaction_window": "1d",
                "follow_through_window":    "1-5d",
                "stale_after":              "5-20d",
            },
            proof_timings=["1d", "1-5d", "5-20d"],
        )
        result = evaluate_thesis_timing_alignment(ev)
        self.assertEqual(result["checked"], 3)
        self.assertEqual(result["aligned"], 3)
        self.assertIsNone(result["downgrade"])

    def test_majority_misaligned_signals_watch_only(self):
        from low_information_gate import evaluate_thesis_timing_alignment
        ev = self._event(
            timing_windows={
                "expected_reaction_window": "1d",
                "follow_through_window":    "1-5d",
                "stale_after":              "5-20d",
            },
            proof_timings=["20d+", "20d+", "1d"],
        )
        result = evaluate_thesis_timing_alignment(ev)
        self.assertEqual(result["aligned"], 1)
        self.assertEqual(result["downgrade"], "watch_only")

    def test_no_thesis_timing_skips_audit(self):
        from low_information_gate import evaluate_thesis_timing_alignment
        ev = {
            "competing_thesis": {
                "primary_thesis": "x",
                # no thesis_timing
            },
            "minimum_proof_set": [
                {"observation": "x", "channel": "commodities", "timing": "1d"},
            ],
        }
        result = evaluate_thesis_timing_alignment(ev)
        self.assertEqual(result["checked"], 0)
        self.assertIsNone(result["downgrade"])

    def test_misaligned_proof_caps_tier_at_watch_only(self):
        """End-to-end: proof timing dispersion caps the call at
        watch_only, blocking the actionable promotion."""
        from low_information_gate import evidence_quality_tier
        ev = self._event(
            timing_windows={
                "expected_reaction_window": "1d",
                "follow_through_window":    "1-5d",
                "stale_after":              "5-20d",
            },
            proof_timings=["20d+", "20d+", "20d+"],
        )
        # Build out the rest of an actionable-shape event so the
        # tier check would otherwise reach actionable.
        ev["mechanism_family"] = "supply_normalization"
        ev["expected_first_order_channels"] = ["commodities"]
        ev["mechanism_summary"] = (
            "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
            "Coast feedstock and widening WCS-WTI heavy-sour discount."
        )
        ev["what_changed"] = (
            "Saudi Aramco cut crude liftings by 1mbd from August "
            "contract volumes."
        )
        ev["beneficiaries"] = ["XOM"]
        ev["losers"] = ["SU"]
        ev["beneficiary_tickers"] = ["XOM"]
        ev["loser_tickers"] = ["SU"]
        ev["assets_to_watch"] = ["XOM", "SU"]
        ev["competing_thesis"]["primary_thesis"] = (
            "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
            "XOM margins widen on the WCS-WTI heavy-sour spread."
        )
        ev["primary_assets"] = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — "
                          "feedstock cost drops as WCS discount widens."},
        ]
        ev["key_falsifiers"] = ["Saudi cabinet walks back the cut"]
        self.assertEqual(evidence_quality_tier(ev), "watch_only")


if __name__ == "__main__":
    unittest.main()
