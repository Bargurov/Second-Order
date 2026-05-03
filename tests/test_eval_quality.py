"""
tests/test_eval_quality.py

Focused tests for the quality-scoring helper used by the eval pass.
No API calls — pure scoring over synthetic analysis dicts.
"""

import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval import (  # noqa: E402
    _compute_engine_quality_deltas,
    _engine_quality_checklist,
    _engine_quality_summary,
    _engine_eval_flags,
    _engine_eval_red_flags,
    _engine_expected_focus_summary,
    _engine_phase_audit_readiness,
    _find_previous_eval_output,
    _format_engine_eval_red_flags_markdown,
    _format_engine_expected_focus_markdown,
    _format_engine_phase_audit_readiness_markdown,
    _format_engine_quality_markdown,
    _format_engine_shape_parity_markdown,
    _format_ready_for_engine_audit_markdown,
    _engine_shape_parity_summary,
    _engine_phase_blocks_for_result,
    _load_engine_summary,
    _load_run_index,
    _quality_score,
    _result_was_asset_rejected,
    _run_index_entry,
    _ready_for_engine_audit,
    _status_blocks_for_result,
    _update_run_index,
    compare_latest_eval_runs,
    run_one,
    ENGINE_QUALITY_FIELDS,
    QUALITY_CHECKS,
    SAMPLE_FILE,
    TARGETED_ENGINE_SAMPLE_IDS,
    select_samples,
    selected_sample_ids,
    skipped_sample_ids,
)


def _rich() -> dict:
    """A baseline analysis that should score a perfect 10/10."""
    return {
        "what_changed": "The US Commerce Department added 28 Chinese semiconductor firms to the Entity List.",
        "mechanism_summary": (
            "Chinese fabs lose access to ASML EUV lithography, Lam Research etch, "
            "and Applied Materials deposition equipment. Non-Chinese fabs gain "
            "pricing power as capacity at leading nodes becomes scarce."
        ),
        "beneficiaries": ["TSMC", "Samsung Foundry"],
        "losers": ["CXMT", "YMTC"],
        "beneficiary_tickers": ["TSM", "SMH"],
        "loser_tickers": ["LRCX", "AMAT"],
        "transmission_chain": [
            "28 Chinese semiconductor firms added to the Entity List",
            "Cuts access to EUV lithography, etch, and deposition equipment",
            "Non-Chinese fabs gain pricing power at leading nodes",
            "TSMC benefits; LRCX and AMAT lose China revenue",
        ],
        "if_persists": {"horizon": "quarters"},
        "currency_channel": {
            "pair": "USD/CNY",
            "mechanism": "Weaker CNY reflects semiconductor import friction.",
        },
        "confidence": "high",
        # Channel pack — the five-prong mechanism gate looks for at
        # least one canonical transmission channel; without it the
        # rich analysis would (mis)trip the channel prong.
        "expected_first_order_channels": ["equities"],
        "expected_second_order_channels": ["fx", "credit"],
    }


class TestQualityScore(unittest.TestCase):

    def test_rich_analysis_scores_full_marks(self):
        r = _quality_score(_rich())
        self.assertEqual(r["score"], len(QUALITY_CHECKS))
        self.assertEqual(r["max_score"], len(QUALITY_CHECKS))
        self.assertTrue(all(r["breakdown"].values()))

    def test_short_mechanism_loses_points(self):
        a = _rich()
        a["mechanism_summary"] = "Too short."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["mechanism_length_ok"])
        self.assertLess(r["score"], len(QUALITY_CHECKS))

    def test_insufficient_evidence_mechanism_fails(self):
        a = _rich()
        a["mechanism_summary"] = "Insufficient evidence to identify mechanism."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["mechanism_length_ok"])

    def test_short_transmission_chain_loses_point(self):
        a = _rich()
        a["transmission_chain"] = ["only", "two"]
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["transmission_chain_depth_ok"])

    def test_missing_beneficiary_tickers_loses_point(self):
        a = _rich()
        a["beneficiary_tickers"] = ["TSM"]  # only one — needs ≥ 2
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["beneficiary_tickers_ok"])

    def test_missing_loser_tickers_loses_point(self):
        a = _rich()
        a["loser_tickers"] = []
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["loser_tickers_ok"])

    def test_degraded_flag_loses_point(self):
        a = _rich()
        a["degraded"] = True
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["not_degraded"])

    def test_validation_warnings_lose_point(self):
        a = _rich()
        a["validation_warnings"] = ["confidence downgraded from high to medium"]
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["no_validation_warnings"])

    def test_vague_what_changed_loses_point(self):
        a = _rich()
        a["what_changed"] = "Various companies saw multiple changes in the market today."
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["specific_what_changed"])

    def test_missing_horizon_loses_point(self):
        a = _rich()
        a["if_persists"] = {}
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["if_persists_horizon_ok"])

    def test_currency_channel_null_both_counts_complete(self):
        # Model correctly declared no FX channel → still counts as complete.
        a = _rich()
        a["currency_channel"] = {"pair": None, "mechanism": None}
        r = _quality_score(a)
        self.assertTrue(r["breakdown"]["currency_channel_complete"])

    def test_currency_channel_half_populated_fails(self):
        a = _rich()
        a["currency_channel"] = {"pair": "USD/CNY", "mechanism": None}
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["currency_channel_complete"])

    def test_empty_entities_fails_populated_check(self):
        a = _rich()
        a["beneficiaries"] = []
        a["losers"] = []
        r = _quality_score(a)
        self.assertFalse(r["breakdown"]["both_entities_populated"])

    def test_weak_analysis_scores_low(self):
        weak = {
            "what_changed": "short",
            "mechanism_summary": "Insufficient evidence.",
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "transmission_chain": [],
            "if_persists": {},
            "currency_channel": {},
            "degraded": True,
            "validation_warnings": ["thin analysis"],
        }
        r = _quality_score(weak)
        # Only currency_channel_complete (both-null path) should pass.
        self.assertLessEqual(r["score"], 2)


class TestTargetedEngineSamples(unittest.TestCase):

    def _samples(self) -> list[dict]:
        path = os.path.join(os.path.dirname(__file__), "..", SAMPLE_FILE)
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)

    def test_engine_next_preset_selects_targeted_samples(self):
        samples = self._samples()
        selected = select_samples(samples, preset="engine-next")

        self.assertEqual(
            [sample["id"] for sample in selected],
            TARGETED_ENGINE_SAMPLE_IDS,
        )

    def test_engine_focused_presets_select_from_expected_eval_focus(self):
        samples = self._samples()

        targeted = select_samples(samples, preset="targeted")
        low_info = select_samples(samples, preset="low-information")
        family = select_samples(samples, preset="mechanism-family")
        all_samples = select_samples(samples, preset="all")

        self.assertEqual(selected_sample_ids(targeted), TARGETED_ENGINE_SAMPLE_IDS)
        self.assertEqual(selected_sample_ids(low_info), ["sample_028"])
        self.assertEqual(
            selected_sample_ids(family),
            [sample_id for sample_id in TARGETED_ENGINE_SAMPLE_IDS if sample_id != "sample_028"],
        )
        self.assertEqual(selected_sample_ids(all_samples), selected_sample_ids(samples))

    def test_skipped_sample_ids_reports_unselected_samples(self):
        samples = self._samples()
        selected = select_samples(samples, preset="low-information")

        self.assertEqual(selected_sample_ids(selected), ["sample_028"])
        self.assertNotIn("sample_028", skipped_sample_ids(samples, selected))
        self.assertIn("sample_001", skipped_sample_ids(samples, selected))

    def test_targeted_samples_carry_expected_eval_focus(self):
        sample_map = {sample["id"]: sample for sample in self._samples()}
        required_categories = {
            "supply_shock",
            "policy_surprise",
            "tariffs_trade",
            "fx_reserve_stress",
            "energy_chokepoint",
            "semiconductor_supply_chain",
            "credit_stress",
            "low_information",
        }
        targeted = [sample_map[sample_id] for sample_id in TARGETED_ENGINE_SAMPLE_IDS]

        self.assertGreaterEqual(len(targeted), 8)
        self.assertLessEqual(len(targeted), 12)
        self.assertTrue(required_categories <= {sample["category"] for sample in targeted})
        for sample in targeted:
            focus = sample.get("expected_eval_focus")
            self.assertIsInstance(focus, dict)
            self.assertIsInstance(focus.get("mechanism_family"), str)
            self.assertIn("likely_channels", focus)
            self.assertIsInstance(focus["likely_channels"], list)
            self.assertIsInstance(focus.get("should_be_low_information"), bool)


class TestEngineEvalFlags(unittest.TestCase):

    def _result(self, **overrides) -> dict:
        base = {
            "id": "sample_x",
            "expected_eval_focus": {
                "mechanism_family": "commodity_squeeze",
                "likely_channels": ["commodities"],
                "should_be_low_information": False,
            },
            "mechanism_family": "commodity_squeeze",
            "low_information": False,
            "degraded": False,
            "confidence": "medium",
            "quality_tier": "usable",
            "primary_thesis_present": True,
            "transmission_chain_valid": True,
            "asset_why_lines_present": True,
            "proof_set_count": 1,
            "falsifier_count": 1,
        }
        base.update(overrides)
        return base

    def test_engine_eval_flags_mark_failures_on_actionable_results(self):
        result = self._result(
            mechanism_family="none",
            primary_thesis_present=False,
            transmission_chain_valid=False,
            asset_why_lines_present=False,
            proof_set_count=0,
            falsifier_count=0,
        )

        flags = _engine_eval_flags(result)

        self.assertTrue(flags["family_none_on_clear_case"])
        self.assertFalse(flags["low_info_expected_but_actionable"])
        self.assertTrue(flags["actionable_but_missing_thesis"])
        self.assertTrue(flags["actionable_but_missing_chain"])
        self.assertTrue(flags["actionable_but_missing_asset_rationale"])
        self.assertTrue(flags["proof_or_falsifier_missing_on_actionable"])

    def test_engine_eval_flags_mark_low_info_expected_but_actionable(self):
        result = self._result(
            expected_eval_focus={
                "mechanism_family": "none",
                "likely_channels": [],
                "should_be_low_information": True,
            },
            mechanism_family="policy_constraint",
        )

        flags = _engine_eval_flags(result)

        self.assertFalse(flags["family_none_on_clear_case"])
        self.assertTrue(flags["low_info_expected_but_actionable"])

    def test_engine_eval_red_flags_summary_and_markdown(self):
        clean = self._result(id="sample_clean")
        bad = self._result(
            id="sample_bad",
            mechanism_family="none",
            primary_thesis_present=False,
            transmission_chain_valid=False,
            asset_why_lines_present=False,
            proof_set_count=0,
        )
        low_info = self._result(
            id="sample_low",
            expected_eval_focus={
                "mechanism_family": "none",
                "likely_channels": [],
                "should_be_low_information": True,
            },
            mechanism_family="none",
        )
        for result in (clean, bad, low_info):
            result["eval_flags"] = _engine_eval_flags(result)

        summary = _engine_eval_red_flags([clean, bad, low_info])
        markdown = _format_engine_eval_red_flags_markdown(summary)

        self.assertEqual(
            summary["family_none_on_clear_case"]["sample_ids"],
            ["sample_bad"],
        )
        self.assertEqual(
            summary["low_info_expected_but_actionable"]["sample_ids"],
            ["sample_low"],
        )
        self.assertIn("## Engine Eval Red Flags", markdown)
        self.assertIn("- Family none on clear case: 1 (sample_bad)", markdown)
        self.assertIn(
            "- Low-info expected but actionable: 1 (sample_low)",
            markdown,
        )
        self.assertIn(
            "- Actionable but missing chain: 1 (sample_bad)",
            markdown,
        )

    def test_engine_phase_audit_readiness_summary_and_markdown(self):
        actionable = self._result(
            id="sample_actionable",
            high_confidence_without_proof=True,
            rationale_too_generic=True,
            thesis_asset_consistent=False,
            falsifier_count=1,
        )
        family_bad = self._result(
            id="sample_family_bad",
            mechanism_family="none",
            actionable_with_family_none=True,
            coherence_rejection_triggered=True,
            falsifier_count=0,
        )
        watch_only = self._result(
            id="sample_watch",
            confidence="low",
            quality_tier="thin",
            falsifier_count=1,
        )
        low_info = self._result(
            id="sample_low",
            expected_eval_focus={
                "mechanism_family": "none",
                "likely_channels": [],
                "should_be_low_information": True,
            },
            low_information=True,
            confidence="low",
            quality_tier="poor",
            falsifier_count=0,
        )
        for result in (actionable, family_bad, watch_only, low_info):
            result["eval_flags"] = _engine_eval_flags(result)

        summary = _engine_phase_audit_readiness([
            actionable, family_bad, watch_only, low_info,
        ])
        markdown = _format_engine_phase_audit_readiness_markdown(summary)

        self.assertEqual(summary["actionable_outputs_count"], 2)
        self.assertEqual(summary["watch_only_outputs_count"], 1)
        self.assertEqual(summary["low_information_outputs_count"], 1)
        self.assertEqual(summary["family_none_clear_case_flags"], 1)
        self.assertEqual(summary["bad_confidence_flags"], 2)
        self.assertEqual(summary["generic_rationale_flags"], 1)
        self.assertEqual(summary["consistency_flags"], 2)
        self.assertEqual(
            summary["falsification_counterfactual_covered_count"], 2,
        )
        self.assertEqual(
            summary["falsification_counterfactual_missing_count"], 2,
        )
        self.assertIn("## Engine Phase Audit Readiness", markdown)
        self.assertIn("- Actionable outputs: 2", markdown)
        self.assertIn("- Watch-only outputs: 1", markdown)
        self.assertIn("- Low-information outputs: 1", markdown)
        self.assertIn("- Family-none clear-case flags: 1", markdown)
        self.assertIn("- Bad-confidence flags: 2", markdown)
        self.assertIn("- Generic-rationale flags: 1", markdown)
        self.assertIn("- Consistency flags: 2", markdown)
        self.assertIn(
            "- Falsification/counterfactual coverage: 2 / 4 covered (2 missing)",
            markdown,
        )

    def test_ready_for_engine_audit_summary_and_markdown(self):
        clean = self._result(
            id="sample_clean",
            actionability_present=True,
            falsifier_count=1,
        )
        tradable_gap = self._result(
            id="sample_gap",
            actionability_present=True,
            tradable_true_without_confirmation=True,
            rationale_too_generic=True,
            falsifier_count=0,
        )
        conflict_gap = self._result(
            id="sample_conflict",
            actionability_present=False,
            market_macro_conflict_detected=True,
            conflict_reason_present=False,
            falsifier_count=1,
        )

        summary = _ready_for_engine_audit([
            clean, tradable_gap, conflict_gap,
        ])
        markdown = _format_ready_for_engine_audit_markdown(summary)

        self.assertEqual(summary["total_samples"], 3)
        self.assertEqual(summary["sample_pass_count"], 1)
        self.assertEqual(summary["sample_fail_count"], 2)
        self.assertEqual(summary["actionability_present_pass_count"], 2)
        self.assertEqual(summary["actionability_present_fail_count"], 1)
        self.assertEqual(summary["tradable_confirmation_fail_count"], 1)
        self.assertEqual(summary["conflict_reason_fail_count"], 1)
        self.assertEqual(summary["generic_rationale_fail_count"], 1)
        self.assertEqual(summary["falsification_fail_count"], 1)
        self.assertIn("## Ready for Engine Audit", markdown)
        self.assertIn("- Overall samples: pass 1 / fail 2 / total 3", markdown)
        self.assertIn("- Actionability field: pass 2 / fail 1", markdown)
        self.assertIn("- Tradable needs confirmation: pass 2 / fail 1", markdown)
        self.assertIn("- Conflict reason coverage: pass 0 / fail 1", markdown)

    def test_expected_focus_summary_groups_metadata_fields(self):
        commodity = self._result(
            id="sample_commodity",
            expected_eval_focus={
                "mechanism_family": "commodity_squeeze",
                "likely_channels": ["commodities", "fx"],
                "should_be_low_information": False,
            },
            mechanism_family="commodity_squeeze",
            causal_strength="strong",
        )
        commodity["eval_flags"] = _engine_eval_flags(commodity)
        low_info = self._result(
            id="sample_low",
            expected_eval_focus={
                "mechanism_family": "none",
                "likely_channels": [],
                "should_be_low_information": True,
            },
            mechanism_family="policy_constraint",
            low_information=False,
            causal_strength="weak",
        )
        low_info["eval_flags"] = _engine_eval_flags(low_info)
        no_metadata = self._result(
            id="sample_no_metadata",
            expected_eval_focus=None,
            causal_strength="strong",
        )
        no_metadata["eval_flags"] = _engine_eval_flags(no_metadata)

        summary = _engine_expected_focus_summary([
            commodity, low_info, no_metadata,
        ])
        markdown = _format_engine_expected_focus_markdown(summary)

        self.assertEqual(
            summary["family_coverage"]["commodity_squeeze"]["sample_count"],
            1,
        )
        self.assertEqual(
            summary["family_coverage"]["commodity_squeeze"]["actual_family_match_count"],
            1,
        )
        self.assertNotIn("sample_no_metadata", markdown)
        self.assertEqual(
            summary["channel_coverage"]["commodities"]["strong_causal_chain_count"],
            1,
        )
        self.assertEqual(
            summary["low_information_expected_vs_actual"]["expected_low_information"]["sample_count"],
            1,
        )
        self.assertEqual(
            summary["low_information_expected_vs_actual"]["expected_low_information"]["actionable_count"],
            1,
        )
        self.assertEqual(
            summary["red_flags_by_expected_family"]["none"]["low_info_expected_but_actionable"],
            1,
        )
        self.assertIn("### Family Coverage", markdown)
        self.assertIn("| commodity_squeeze | 1 | 1 | 0 | 0 | sample_commodity |", markdown)
        self.assertIn("### Channel Coverage", markdown)
        self.assertIn("| commodities | 1 | 1 | 0 | 0 | sample_commodity |", markdown)
        self.assertIn("### Low-Information Expected Vs Actual", markdown)
        self.assertIn("| expected low information | 1 | 0 | 1 | 1 | sample_low |", markdown)
        self.assertIn("### Red Flags By Expected Family", markdown)


class TestEngineShapeParity(unittest.TestCase):

    def test_shape_parity_summary_splits_eval_visible_and_engine_emitted(self):
        result = {
            "mechanism_subtype": "export_controls",
            "actionability_check": {},
            "counterfactual_check": {},
            "quality_warnings": [],
            "proof_status": {},
            "falsifier_status": {},
            "thesis_state": "",
            "thesis_state_reason": "",
            "validation_rationale": "",
            "evidence_sources": [],
            "engine_emitted_fields": [
                "mechanism_subtype",
                "quality_warnings",
                "proof_status",
            ],
        }

        summary = _engine_shape_parity_summary([result])

        self.assertEqual(summary["present_count"], 10)
        self.assertEqual(summary["missing_count"], 0)
        self.assertEqual(summary["missing_fields"], [])
        self.assertEqual(summary["eval_visible"]["present_count"], 10)
        self.assertEqual(summary["eval_visible"]["missing_fields"], [])
        self.assertEqual(summary["engine_emitted"]["present_count"], 3)
        self.assertIn(
            "actionability_check",
            summary["engine_emitted"]["missing_fields"],
        )
        self.assertIn(
            "evidence_sources",
            summary["engine_emitted"]["missing_fields"],
        )

    def test_shape_parity_summary_warns_on_missing_fields(self):
        summary = _engine_shape_parity_summary([
            {
                "mechanism_subtype": "",
                "actionability_check": {},
                "proof_status": {},
                "engine_emitted_fields": ["mechanism_subtype"],
            },
        ])

        self.assertEqual(summary["present_count"], 3)
        self.assertEqual(summary["missing_count"], 7)
        self.assertIn("counterfactual_check", summary["missing_fields"])
        self.assertIn("evidence_sources", summary["missing_fields"])
        self.assertEqual(summary["engine_emitted"]["present_count"], 1)
        self.assertIn(
            "actionability_check",
            summary["engine_emitted"]["missing_fields"],
        )

        markdown = _format_engine_shape_parity_markdown(summary)
        self.assertIn("## Engine/API/Eval Shape Parity", markdown)
        self.assertIn("### Eval-visible fields", markdown)
        self.assertIn("### Engine-emitted fields", markdown)
        self.assertIn("- Present count: 3", markdown)
        self.assertIn("- Missing count: 7", markdown)
        self.assertIn("`counterfactual_check`", markdown)


class TestRunOneNestedEngineBlocks(unittest.TestCase):

    def test_run_one_carries_nested_blocks_into_eval_json(self):
        actionability_check = {
            "tradable": True,
            "why_tradable_or_not": "Proof is concrete and confirmation is named.",
            "required_confirmation": ["SMH outperforms SPY"],
            "sizing_caveat": "Half size until confirmation prints.",
            "risk_level": "standard",
            "max_confidence_before_confirmation": "high",
            "invalidation_trigger": "SMH fails to outperform SPY.",
        }
        counterfactual_check = {
            "what_should_not_happen": "SMH fails to outperform SPY.",
            "why_it_would_break_thesis": "It would break the scarcity read.",
            "evidence_to_watch": ["SMH fails to outperform SPY."],
        }
        proof_status = {
            "available": True,
            "status": "met",
            "matched_count": 1,
            "total_count": 1,
            "matched_items": ["SMH outperforms SPY"],
            "unmet_items": [],
            "items": [],
        }
        falsifier_status = {
            "available": True,
            "status": "watch",
            "triggered": [],
            "watching": ["SMH fails to outperform SPY."],
            "items": [],
        }
        evidence_sources = [
            {
                "source": "Commerce Department Entity List notice",
                "url": "https://example.gov/entity-list-notice",
                "date": "2026-04-20",
            },
        ]
        analysis = _rich()
        analysis.update({
            "assets_to_watch": [],
            "actionability_check": actionability_check,
            "counterfactual_check": counterfactual_check,
            "proof_status": proof_status,
            "falsifier_status": falsifier_status,
            "evidence_sources": evidence_sources,
            "thesis_state": "confirming",
            "thesis_state_reason": "Proof is met and market evidence supports.",
            "validation_rationale": "SMH outperforms SPY on foundry scarcity.",
            "quality_warnings": ["review sizing"],
            "mechanism_subtype": "export_controls",
        })
        sample = {
            "id": "sample_nested",
            "category": "semiconductor_supply_chain",
            "headline": "US expands semiconductor export controls on China",
            "expected_stage": None,
            "expected_persistence": None,
        }

        with patch("analyze_event.analyze_event", return_value=analysis), \
             patch("market_check.build_macro_context_for_prompt", return_value=""), \
             patch("market_check.compute_rates_context", return_value={"regime": "neutral"}), \
             patch("market_check.compute_stress_regime", return_value=None), \
             patch("market_check.classify_policy_sensitivity", return_value={}), \
             patch("market_check.classify_inventory_context", return_value={}), \
             patch("market_check.market_check", return_value={"note": "mock", "tickers": []}), \
             patch("real_yield_context.build_real_yield_context", return_value={}), \
             patch("policy_constraint.compute_policy_constraint", return_value={}), \
             patch("shock_decomposition.compute_shock_decomposition", return_value={}), \
             patch("reaction_function_divergence.compute_reaction_function_divergence", return_value={}), \
             patch("regime_vector.build_regime_vector", return_value={}), \
             patch("surprise_vs_anticipation.compute_surprise_vs_anticipation", return_value={}), \
             patch("terms_of_trade.compute_terms_of_trade", return_value={}), \
             patch("reserve_stress_overlay.compute_reserve_stress", return_value={}), \
             patch("narrative_divergence.compute_narrative_divergence", return_value={}), \
             patch("db.find_historical_analogs", return_value=[]), \
             patch("db.get_confidence_calibration_stats", return_value={}):
            result = run_one(sample)

        self.assertEqual(result["actionability_check"], actionability_check)
        self.assertEqual(result["counterfactual_check"], counterfactual_check)
        self.assertEqual(result["proof_status"], proof_status)
        self.assertEqual(result["falsifier_status"], falsifier_status)
        self.assertEqual(result["evidence_sources"], evidence_sources)
        for field in (
            "actionability_check",
            "counterfactual_check",
            "proof_status",
            "falsifier_status",
            "evidence_sources",
        ):
            self.assertIn(field, result["eval_visible_fields"])
            self.assertIn(field, result["engine_emitted_fields"])

    def test_run_one_defaulted_blocks_are_visible_but_not_engine_emitted(self):
        analysis = _rich()
        analysis["assets_to_watch"] = []
        sample = {
            "id": "sample_defaults",
            "category": "semiconductor_supply_chain",
            "headline": "US expands semiconductor export controls on China",
            "expected_stage": None,
            "expected_persistence": None,
        }

        with patch("analyze_event.analyze_event", return_value=analysis), \
             patch("market_check.build_macro_context_for_prompt", return_value=""), \
             patch("market_check.compute_rates_context", return_value={"regime": "neutral"}), \
             patch("market_check.compute_stress_regime", return_value=None), \
             patch("market_check.classify_policy_sensitivity", return_value={}), \
             patch("market_check.classify_inventory_context", return_value={}), \
             patch("market_check.market_check", return_value={"note": "mock", "tickers": []}), \
             patch("real_yield_context.build_real_yield_context", return_value={}), \
             patch("policy_constraint.compute_policy_constraint", return_value={}), \
             patch("shock_decomposition.compute_shock_decomposition", return_value={}), \
             patch("reaction_function_divergence.compute_reaction_function_divergence", return_value={}), \
             patch("regime_vector.build_regime_vector", return_value={}), \
             patch("surprise_vs_anticipation.compute_surprise_vs_anticipation", return_value={}), \
             patch("terms_of_trade.compute_terms_of_trade", return_value={}), \
             patch("reserve_stress_overlay.compute_reserve_stress", return_value={}), \
             patch("narrative_divergence.compute_narrative_divergence", return_value={}), \
             patch("db.find_historical_analogs", return_value=[]), \
             patch("db.get_confidence_calibration_stats", return_value={}):
            result = run_one(sample)

        self.assertEqual(result["actionability_check"], {})
        self.assertEqual(result["counterfactual_check"], {})
        self.assertEqual(result["proof_status"]["status"], "none")
        self.assertEqual(result["falsifier_status"]["status"], "none")
        self.assertEqual(result["evidence_sources"], [])
        for field in (
            "actionability_check",
            "counterfactual_check",
            "proof_status",
            "falsifier_status",
            "evidence_sources",
        ):
            self.assertIn(field, result["eval_visible_fields"])
            self.assertNotIn(field, result["engine_emitted_fields"])


class TestEngineQualityChecklist(unittest.TestCase):

    def test_engine_quality_checklist_marks_present_fields(self):
        analysis = _rich()
        analysis.update({
            "competing_thesis": {
                "primary_thesis": "Export controls shift leading-edge scarcity to non-Chinese foundries.",
                "alternative_thesis": "The controls are already priced and capacity shifts are limited.",
                "discriminator": {"observation": "SMH outperforms China semis", "timing": "1-5d"},
            },
            "mechanism_family": "supply_chain_chokepoint",
            "regime_conditioned_caveat": (
                "In a hawkish rates regime, the equipment-maker revenue hit "
                "reprices faster because long-duration semi multiples are already compressed."
            ),
            "primary_assets": [
                {
                    "symbol": "TSM",
                    "rank": 1,
                    "rationale": "Direct foundry beneficiary from constrained Chinese capacity.",
                },
            ],
            "secondary_assets": [
                {
                    "symbol": "SMH",
                    "rank": 1,
                    "rationale": "Sector basket reflects foundry scarcity and semi-margin repricing.",
                },
            ],
            "hedge_or_signal_assets": [
                {
                    "symbol": "UUP",
                    "rank": 1,
                    "expected_direction": "higher",
                    "rationale": "Dollar signal for export-control stress confirmation.",
                },
            ],
            "minimum_proof_set": [
                {
                    "observation": "Foundry scarcity supports SMH relative strength",
                    "channel": "equities",
                    "expected_direction": "higher",
                },
                {
                    "observation": "Chinese export-control pressure keeps semis underperforming",
                    "channel": "equities",
                    "expected_direction": "lower",
                },
            ],
            "key_falsifiers": [
                "Chinese export controls loosen and foundry scarcity fades.",
            ],
            "confidence_rationale": (
                "High confidence because export controls directly constrain "
                "EUV equipment access and foundry capacity, supporting TSM "
                "and SMH relative strength."
            ),
            "validation_rationale": (
                "Validation should track SMH outperformance, TSM resilience, "
                "and weaker China semiconductor baskets over the next week."
            ),
            "thesis_state": "confirming",
            "thesis_state_reason": (
                "Supportive equity evidence and proof discipline keep the "
                "semiconductor scarcity thesis confirming."
            ),
            "persistence_signal": {
                "status": "active",
                "label": "repricing still active",
            },
            "proof_status": {
                "available": True,
                "status": "met",
                "matched_count": 2,
                "total_count": 2,
                "matched_items": ["SMH relative strength"],
                "unmet_items": [],
                "items": [],
            },
            "falsifier_status": {
                "available": True,
                "status": "none",
                "triggered": [],
                "watching": [],
                "items": [],
            },
            "actionability": {
                "decision": "tradable",
                "tradable": True,
                "risk_level": "medium",
            },
            "actionability_check": {
                "tradable": True,
                "why_tradable_or_not": "Proof and tape are concrete enough to trade.",
                "required_confirmation": ["SMH outperforms SPY"],
                "sizing_caveat": "Half size until confirmation prints.",
                "risk_level": "standard",
                "max_confidence_before_confirmation": "high",
                "invalidation_trigger": "SMH fails to outperform SPY.",
            },
            "counterfactual_check": {
                "what_should_not_happen": "SMH fails to outperform SPY.",
                "why_it_would_break_thesis": (
                    "It would break the foundry scarcity read."
                ),
                "evidence_to_watch": [
                    "SMH fails to outperform SPY.",
                    "TSM underperforms China semis.",
                ],
            },
            "invalidation_trigger": (
                "If SMH fails to outperform and Chinese semiconductor baskets "
                "hold flat for five sessions, the thesis is invalidated."
            ),
            "evidence_sources": [
                {
                    "source": "Commerce Department Entity List notice",
                    "url": "https://example.gov/entity-list-notice",
                    "date": "2026-04-20",
                },
            ],
            "cross_asset_confirmation": {
                "verdict": "strong_confirm",
                "confirm_score": 3.0,
                "disconfirm_score": 0.0,
            },
            "market_macro_conflict": {
                "detected": True,
                "reason": (
                    "Credit spreads are moving against the equity signal, "
                    "so the macro tape conflicts with the initial market read."
                ),
            },
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertEqual(set(checklist), set(ENGINE_QUALITY_FIELDS))
        self.assertTrue(checklist["primary_thesis_present"])
        self.assertTrue(checklist["alternative_thesis_present"])
        self.assertTrue(checklist["discriminator_present"])
        self.assertEqual(checklist["mechanism_family"], "supply_chain_chokepoint")
        self.assertFalse(checklist["low_information"])
        self.assertTrue(checklist["asset_why_lines_present"])
        self.assertTrue(checklist["transmission_chain_valid"])
        self.assertEqual(checklist["proof_set_count"], 2)
        self.assertEqual(checklist["falsifier_count"], 1)
        self.assertTrue(checklist["thesis_asset_consistent"])
        self.assertTrue(checklist["thesis_proof_consistent"])
        self.assertTrue(checklist["thesis_falsifier_consistent"])
        self.assertTrue(checklist["chain_ends_in_asset_implication"])
        self.assertEqual(checklist["rejected_asset_count"], 0)
        self.assertEqual(checklist["quality_tier"], "excellent")
        self.assertFalse(checklist["high_confidence_without_proof"])
        self.assertFalse(checklist["actionable_without_valid_chain"])
        self.assertFalse(checklist["actionable_without_asset_rationale"])
        self.assertFalse(checklist["actionable_with_family_none"])
        self.assertFalse(checklist["low_information_but_has_assets"])
        self.assertEqual(checklist["causal_strength"], "strong")
        self.assertTrue(checklist["causal_trigger_present"])
        self.assertTrue(checklist["causal_channel_present"])
        self.assertTrue(checklist["pricing_relationship_present"])
        self.assertTrue(checklist["asset_implication_present"])
        self.assertTrue(checklist["regime_caveats_present"])
        self.assertTrue(checklist["regime_caveats_concrete"])
        self.assertEqual(checklist["primary_asset_count"], 1)
        self.assertEqual(checklist["secondary_asset_count"], 1)
        self.assertEqual(checklist["signal_asset_count"], 1)
        self.assertFalse(checklist["beneficiary_signal_conflict"])
        self.assertEqual(checklist["role_channel_mismatch_count"], 0)
        self.assertTrue(checklist["first_order_present"])
        self.assertEqual(checklist["second_order_count"], 3)
        self.assertTrue(checklist["second_order_has_bridge"])
        self.assertFalse(checklist["second_order_skipped_channel"])
        self.assertTrue(checklist["expected_direction_present"])
        self.assertTrue(checklist["signal_asset_direction_valid"])
        self.assertTrue(checklist["family_chain_consistent"])
        self.assertEqual(checklist["generic_chain_hops_count"], 0)
        self.assertTrue(checklist["chain_asset_implication_present"])
        self.assertFalse(checklist["coherence_rejection_triggered"])
        self.assertEqual(checklist["primary_asset_contradiction_count"], 0)
        self.assertFalse(checklist["weak_signal_only_support"])
        self.assertFalse(checklist["mechanism_subtype_present"])
        self.assertFalse(checklist["subtype_family_consistent"])
        self.assertFalse(checklist["proxy_eligibility_present"])
        self.assertEqual(checklist["rejected_proxy_count"], 0)
        self.assertEqual(checklist["low_channel_match_count"], 0)
        self.assertEqual(checklist["high_noise_proxy_count"], 0)
        self.assertTrue(checklist["confidence_rationale_present"])
        self.assertTrue(checklist["confidence_rationale_concrete"])
        self.assertTrue(checklist["thesis_state_present"])
        self.assertTrue(checklist["validation_rationale_present"])
        self.assertTrue(checklist["validation_rationale_concrete"])
        self.assertTrue(checklist["actionability_check_shaped"])
        self.assertTrue(checklist["counterfactual_check_present"])
        self.assertTrue(checklist["counterfactual_check_shaped"])
        self.assertEqual(checklist["counterfactual_evidence_count"], 2)
        self.assertTrue(checklist["proof_status_shaped"])
        self.assertEqual(checklist["proof_status_item_count"], 2)
        self.assertTrue(checklist["falsifier_status_shaped"])
        self.assertEqual(checklist["falsifier_status_item_count"], 0)
        self.assertTrue(checklist["evidence_sources_shaped"])
        self.assertFalse(checklist["rationale_too_generic"])
        self.assertTrue(checklist["actionability_present"])
        self.assertFalse(checklist["tradable_true_without_confirmation"])
        self.assertFalse(checklist["low_info_marked_tradable"])
        self.assertTrue(checklist["market_macro_conflict_detected"])
        self.assertTrue(checklist["conflict_reason_present"])
        self.assertTrue(checklist["actionability_risk_level_present"])
        self.assertTrue(checklist["invalidation_trigger_present"])
        self.assertTrue(checklist["evidence_sources_present"])
        self.assertTrue(checklist["evidence_sources_concrete"])
        self.assertFalse(checklist["weak_traceability_but_high_confidence"])

    def test_engine_quality_checklist_marks_missing_fields(self):
        analysis = {
            "mechanism_summary": "Insufficient evidence.",
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "assets_to_watch": [],
            "transmission_chain": ["only one"],
            "competing_thesis": {},
            "mechanism_family": "",
            "minimum_proof_set": [],
            "key_falsifiers": [],
        }

        checklist = _engine_quality_checklist(analysis)

        self.assertFalse(checklist["primary_thesis_present"])
        self.assertFalse(checklist["alternative_thesis_present"])
        self.assertFalse(checklist["discriminator_present"])
        self.assertEqual(checklist["mechanism_family"], "none")
        self.assertTrue(checklist["low_information"])
        self.assertFalse(checklist["asset_why_lines_present"])
        self.assertFalse(checklist["transmission_chain_valid"])
        self.assertEqual(checklist["proof_set_count"], 0)
        self.assertEqual(checklist["falsifier_count"], 0)
        self.assertFalse(checklist["thesis_asset_consistent"])
        self.assertFalse(checklist["thesis_proof_consistent"])
        self.assertFalse(checklist["thesis_falsifier_consistent"])
        self.assertFalse(checklist["chain_ends_in_asset_implication"])
        self.assertEqual(checklist["rejected_asset_count"], 0)
        self.assertEqual(checklist["quality_tier"], "poor")
        self.assertFalse(checklist["high_confidence_without_proof"])
        self.assertFalse(checklist["actionable_without_valid_chain"])
        self.assertFalse(checklist["actionable_without_asset_rationale"])
        self.assertFalse(checklist["actionable_with_family_none"])
        self.assertFalse(checklist["low_information_but_has_assets"])
        self.assertEqual(checklist["causal_strength"], "weak")
        self.assertFalse(checklist["causal_trigger_present"])
        self.assertFalse(checklist["causal_channel_present"])
        self.assertFalse(checklist["pricing_relationship_present"])
        self.assertFalse(checklist["asset_implication_present"])
        self.assertFalse(checklist["regime_caveats_present"])
        self.assertFalse(checklist["regime_caveats_concrete"])
        self.assertEqual(checklist["primary_asset_count"], 0)
        self.assertEqual(checklist["secondary_asset_count"], 0)
        self.assertEqual(checklist["signal_asset_count"], 0)
        self.assertFalse(checklist["beneficiary_signal_conflict"])
        self.assertEqual(checklist["role_channel_mismatch_count"], 0)
        self.assertFalse(checklist["first_order_present"])
        self.assertEqual(checklist["second_order_count"], 0)
        self.assertFalse(checklist["second_order_has_bridge"])
        self.assertFalse(checklist["second_order_skipped_channel"])
        self.assertFalse(checklist["expected_direction_present"])
        self.assertFalse(checklist["signal_asset_direction_valid"])
        self.assertFalse(checklist["family_chain_consistent"])
        self.assertEqual(checklist["generic_chain_hops_count"], 1)
        self.assertFalse(checklist["chain_asset_implication_present"])
        self.assertFalse(checklist["coherence_rejection_triggered"])
        self.assertEqual(checklist["primary_asset_contradiction_count"], 0)
        self.assertFalse(checklist["weak_signal_only_support"])
        self.assertFalse(checklist["mechanism_subtype_present"])
        self.assertFalse(checklist["subtype_family_consistent"])
        self.assertFalse(checklist["proxy_eligibility_present"])
        self.assertEqual(checklist["rejected_proxy_count"], 0)
        self.assertEqual(checklist["low_channel_match_count"], 0)
        self.assertEqual(checklist["high_noise_proxy_count"], 0)
        self.assertFalse(checklist["confidence_rationale_present"])
        self.assertFalse(checklist["confidence_rationale_concrete"])
        self.assertFalse(checklist["thesis_state_present"])
        self.assertFalse(checklist["validation_rationale_present"])
        self.assertFalse(checklist["validation_rationale_concrete"])
        self.assertFalse(checklist["actionability_check_shaped"])
        self.assertFalse(checklist["counterfactual_check_present"])
        self.assertFalse(checklist["counterfactual_check_shaped"])
        self.assertEqual(checklist["counterfactual_evidence_count"], 0)
        self.assertFalse(checklist["proof_status_shaped"])
        self.assertEqual(checklist["proof_status_item_count"], 0)
        self.assertFalse(checklist["falsifier_status_shaped"])
        self.assertEqual(checklist["falsifier_status_item_count"], 0)
        self.assertFalse(checklist["evidence_sources_shaped"])
        self.assertFalse(checklist["rationale_too_generic"])
        self.assertFalse(checklist["actionability_present"])
        self.assertFalse(checklist["tradable_true_without_confirmation"])
        self.assertFalse(checklist["low_info_marked_tradable"])
        self.assertFalse(checklist["market_macro_conflict_detected"])
        self.assertFalse(checklist["conflict_reason_present"])
        self.assertFalse(checklist["actionability_risk_level_present"])
        self.assertFalse(checklist["invalidation_trigger_present"])
        self.assertFalse(checklist["evidence_sources_present"])
        self.assertFalse(checklist["evidence_sources_concrete"])
        self.assertFalse(checklist["weak_traceability_but_high_confidence"])

    def test_status_blocks_for_result_carries_raw_blocks_and_empty_defaults(self):
        shaped = _status_blocks_for_result({
            "thesis_state": "partial",
            "thesis_state_reason": "Proof is partial but market evidence supports.",
            "validation_rationale": "SMH and TSM are outperforming China semis.",
            "persistence_signal": {"status": "active"},
            "proof_status": {
                "available": True,
                "status": "partial",
                "matched_count": 1,
                "total_count": 2,
                "matched_items": ["SMH relative strength"],
                "unmet_items": ["China semis underperformance"],
                "items": [],
            },
            "falsifier_status": {
                "available": True,
                "status": "watch",
                "triggered": [],
                "watching": ["SMH fails to outperform"],
                "items": [],
            },
        })

        self.assertEqual(shaped["thesis_state"], "partial")
        self.assertEqual(shaped["persistence_signal"], {"status": "active"})
        self.assertEqual(shaped["proof_status"]["status"], "partial")
        self.assertEqual(shaped["falsifier_status"]["status"], "watch")

        empty = _status_blocks_for_result({})
        self.assertEqual(empty["thesis_state"], "")
        self.assertEqual(empty["thesis_state_reason"], "")
        self.assertEqual(empty["validation_rationale"], "")
        self.assertEqual(empty["persistence_signal"], {})
        self.assertEqual(empty["proof_status"]["status"], "none")
        self.assertFalse(empty["proof_status"]["available"])
        self.assertEqual(empty["falsifier_status"]["status"], "none")
        self.assertFalse(empty["falsifier_status"]["available"])

    def test_engine_phase_blocks_for_result_stable_empty_defaults(self):
        empty = _engine_phase_blocks_for_result({})

        self.assertEqual(empty["actionability_check"], {})
        self.assertEqual(empty["counterfactual_check"], {})
        self.assertEqual(empty["evidence_sources"], [])

        malformed = _engine_phase_blocks_for_result({
            "actionability_check": "bad",
            "counterfactual_check": ["bad"],
            "evidence_sources": "bad",
        })
        self.assertEqual(malformed["actionability_check"], {})
        self.assertEqual(malformed["counterfactual_check"], {})
        self.assertEqual(malformed["evidence_sources"], [])

        shaped = _engine_phase_blocks_for_result({
            "actionability_check": {"tradable": False},
            "counterfactual_check": {"evidence_to_watch": []},
            "evidence_sources": [{"source": "filing"}],
        })
        self.assertEqual(shaped["actionability_check"], {"tradable": False})
        self.assertEqual(shaped["counterfactual_check"], {"evidence_to_watch": []})
        self.assertEqual(shaped["evidence_sources"], [{"source": "filing"}])

    def test_engine_quality_checklist_flags_generic_rationales(self):
        analysis = _rich()
        analysis.update({
            "confidence_rationale": "Market reaction.",
            "validation_rationale": "Notable move.",
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["confidence_rationale_present"])
        self.assertFalse(checklist["confidence_rationale_concrete"])
        self.assertTrue(checklist["validation_rationale_present"])
        self.assertFalse(checklist["validation_rationale_concrete"])
        self.assertTrue(checklist["rationale_too_generic"])

    def test_engine_quality_checklist_flags_pre_audit_tradable_gaps(self):
        analysis = _rich()
        analysis.update({
            "actionability": {"tradable": True},
            "market_macro_conflict": {"detected": True},
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["actionability_present"])
        self.assertTrue(checklist["tradable_true_without_confirmation"])
        self.assertFalse(checklist["low_info_marked_tradable"])
        self.assertTrue(checklist["market_macro_conflict_detected"])
        self.assertFalse(checklist["conflict_reason_present"])
        self.assertTrue(checklist["weak_traceability_but_high_confidence"])

    def test_engine_quality_checklist_reads_nested_actionability_check(self):
        analysis = _rich()
        analysis.update({
            "actionability_check": {
                "tradable": True,
                "why_tradable_or_not": "The proof set is specific and confirmable.",
                "risk_level": "high",
                "required_confirmation": (
                    "SMH should outperform SPY by at least 150 bps over "
                    "five sessions before sizing up."
                ),
                "sizing_caveat": "Keep sizing small until confirmation prints.",
                "max_confidence_before_confirmation": "low",
                "invalidation_trigger": (
                    "Invalidated if SMH underperforms SPY while China semis "
                    "hold flat for five sessions."
                ),
            },
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["actionability_present"])
        self.assertFalse(checklist["tradable_true_without_confirmation"])
        self.assertTrue(checklist["actionability_risk_level_present"])
        self.assertTrue(checklist["invalidation_trigger_present"])
        self.assertTrue(checklist["actionability_check_shaped"])

    def test_engine_quality_checklist_flags_nested_tradable_without_confirmation(self):
        analysis = _rich()
        analysis.update({
            "actionability_check": {
                "tradable": True,
                "risk_level": "medium",
            },
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["actionability_present"])
        self.assertTrue(checklist["tradable_true_without_confirmation"])
        self.assertTrue(checklist["actionability_risk_level_present"])
        self.assertFalse(checklist["invalidation_trigger_present"])
        self.assertFalse(checklist["actionability_check_shaped"])

    def test_engine_quality_checklist_reads_nested_counterfactual_check(self):
        analysis = _rich()
        analysis.update({
            "counterfactual_check": {
                "what_should_not_happen": "SMH fails to outperform SPY.",
                "why_it_would_break_thesis": (
                    "That would break the committed scarcity thesis."
                ),
                "evidence_to_watch": [
                    "SMH fails to outperform SPY.",
                    "TSM underperforms China semis.",
                ],
            },
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["counterfactual_check_present"])
        self.assertTrue(checklist["counterfactual_check_shaped"])
        self.assertEqual(checklist["counterfactual_evidence_count"], 2)
        self.assertTrue(checklist["invalidation_trigger_present"])

    def test_engine_quality_checklist_reads_status_block_item_counts(self):
        analysis = _rich()
        analysis.update({
            "proof_status": {
                "available": True,
                "status": "partial",
                "matched_count": 1,
                "total_count": 3,
                "matched_items": ["SMH outperforms"],
                "unmet_items": ["TSM resilience", "China semis weakness"],
                "items": [],
            },
            "falsifier_status": {
                "available": True,
                "status": "watch",
                "triggered": ["SMH underperforms"],
                "watching": ["TSM underperforms"],
                "items": [],
            },
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["proof_status_shaped"])
        self.assertEqual(checklist["proof_status_item_count"], 3)
        self.assertTrue(checklist["falsifier_status_shaped"])
        self.assertEqual(checklist["falsifier_status_item_count"], 2)

    def test_engine_quality_checklist_marks_traceability_diagnostics(self):
        analysis = _rich()
        analysis.update({
            "actionability": {
                "tradable": True,
                "risk_level": "high",
            },
            "key_falsifiers": [
                "SMH fails to outperform while China semis remain stable.",
            ],
            "evidence_sources": ["market data"],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["actionability_risk_level_present"])
        self.assertTrue(checklist["invalidation_trigger_present"])
        self.assertTrue(checklist["evidence_sources_present"])
        self.assertFalse(checklist["evidence_sources_concrete"])
        self.assertTrue(checklist["evidence_sources_shaped"])
        self.assertTrue(checklist["weak_traceability_but_high_confidence"])

    def test_engine_quality_checklist_marks_inconsistency_diagnostics(self):
        analysis = _rich()
        analysis.update({
            "mechanism_summary": (
                "Saudi lifting cuts widen the WCS heavy-sour discount "
                "and lift Gulf Coast refiner margins."
            ),
            "transmission_chain": [
                "Saudi Arabia cuts crude liftings",
                "WCS heavy-sour discount widens",
                "Gulf Coast refiner margins expand",
            ],
            "beneficiaries": ["Gulf Coast refiners"],
            "losers": ["heavy crude producers"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["SU"],
            "assets_to_watch": ["XOM", "SU"],
            "competing_thesis": {
                "primary_thesis": (
                    "Saudi lifting cuts widen the WCS heavy-sour discount "
                    "and lift Gulf Coast refiner margins."
                ),
            },
            "primary_assets": [
                {
                    "symbol": "AAPL",
                    "rank": 1,
                    "rationale": "Smartphone unit shipments improve in Asia.",
                },
            ],
            "minimum_proof_set": [
                {"observation": "TSMC leading-node capacity expands", "channel": "equities"},
            ],
            "key_falsifiers": [
                "Apple trims smartphone revenue guidance.",
            ],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertFalse(checklist["thesis_asset_consistent"])
        self.assertFalse(checklist["thesis_proof_consistent"])
        self.assertFalse(checklist["thesis_falsifier_consistent"])
        self.assertEqual(checklist["rejected_asset_count"], 1)
        self.assertEqual(checklist["role_channel_mismatch_count"], 1)
        self.assertTrue(checklist["coherence_rejection_triggered"])
        self.assertEqual(checklist["primary_asset_contradiction_count"], 1)

    def test_engine_quality_checklist_marks_role_signal_conflicts(self):
        analysis = _rich()
        analysis.update({
            "primary_assets": [
                {
                    "symbol": "TSM",
                    "rank": 1,
                    "rationale": "Direct foundry beneficiary from constrained Chinese capacity.",
                },
            ],
            "hedge_or_signal_assets": [
                {
                    "symbol": "TSM",
                    "rank": 1,
                    "rationale": "Signal bucket incorrectly repeats the beneficiary.",
                },
                {
                    "symbol": "SPY",
                    "rank": 2,
                    "tier": "direct_proxy",
                    "rationale": "Broad equity proxy incorrectly typed as direct.",
                },
            ],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertEqual(checklist["signal_asset_count"], 2)
        self.assertTrue(checklist["beneficiary_signal_conflict"])
        self.assertEqual(checklist["role_channel_mismatch_count"], 2)
        self.assertFalse(checklist["signal_asset_direction_valid"])

    def test_engine_quality_checklist_marks_order_direction_diagnostics(self):
        analysis = _rich()
        analysis.update({
            "expected_second_order_channels": [],
            "secondary_assets": [
                {
                    "symbol": "SMH",
                    "rank": 1,
                    "rationale": "Sector basket reflects foundry scarcity via semi-margin repricing.",
                },
            ],
            "hedge_or_signal_assets": [
                {
                    "symbol": "UUP",
                    "rank": 1,
                    "rationale": "Dollar signal for export-control stress confirmation.",
                },
            ],
            "minimum_proof_set": [
                {
                    "observation": "Foundry scarcity supports SMH relative strength",
                    "channel": "equities",
                },
            ],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["first_order_present"])
        self.assertEqual(checklist["second_order_count"], 1)
        self.assertTrue(checklist["second_order_has_bridge"])
        self.assertTrue(checklist["second_order_skipped_channel"])
        self.assertFalse(checklist["expected_direction_present"])
        self.assertFalse(checklist["signal_asset_direction_valid"])

    def test_engine_quality_checklist_marks_family_chain_coherence_diagnostics(self):
        analysis = {
            "what_changed": "A policy headline was published.",
            "mechanism_summary": "Markets react to broad uncertainty.",
            "mechanism_family": "commodity_squeeze",
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "assets_to_watch": [],
            "transmission_chain": [
                "Event happens",
                "Market reacts",
                "Assets move",
            ],
            "primary_assets": [],
            "secondary_assets": [],
            "hedge_or_signal_assets": [
                {
                    "symbol": "VIX",
                    "rank": 1,
                    "rationale": "Volatility signal only.",
                },
            ],
            "minimum_proof_set": [],
            "key_falsifiers": [],
        }

        checklist = _engine_quality_checklist(analysis)

        self.assertFalse(checklist["family_chain_consistent"])
        self.assertEqual(checklist["generic_chain_hops_count"], 3)
        self.assertFalse(checklist["chain_asset_implication_present"])
        self.assertFalse(checklist["coherence_rejection_triggered"])
        self.assertEqual(checklist["primary_asset_contradiction_count"], 0)
        self.assertTrue(checklist["weak_signal_only_support"])

    def test_engine_quality_checklist_reads_pending_engine_readiness_fields(self):
        analysis = _rich()
        analysis.update({
            "mechanism_family": "supply_chain_chokepoint",
            "mechanism_subtype": "supply_chain_chokepoint_export_controls",
            "proxy_candidates": [
                {
                    "symbol": "SMH",
                    "eligible": True,
                    "channel_match": "high",
                    "noise": "low",
                },
                {
                    "symbol": "KWEB",
                    "eligible": False,
                    "channel_match": "low",
                    "noise": "high",
                },
                {
                    "symbol": "FXI",
                    "rejected": True,
                    "channel_match_score": 0.2,
                    "noise_score": 0.8,
                },
            ],
            "rejected_proxies": ["ASHR"],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["mechanism_subtype_present"])
        self.assertTrue(checklist["subtype_family_consistent"])
        self.assertTrue(checklist["proxy_eligibility_present"])
        self.assertEqual(checklist["rejected_proxy_count"], 3)
        self.assertEqual(checklist["low_channel_match_count"], 2)
        self.assertEqual(checklist["high_noise_proxy_count"], 2)

    def test_engine_quality_checklist_marks_bad_confidence_diagnostics(self):
        analysis = _rich()
        analysis.update({
            "confidence": "high",
            "mechanism_family": "none",
            "primary_assets": [],
            "secondary_assets": [],
            "hedge_or_signal_assets": [],
            "minimum_proof_set": [],
            "transmission_chain": ["Only the first step lands"],
        })

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["high_confidence_without_proof"])
        self.assertTrue(checklist["actionable_without_valid_chain"])
        self.assertTrue(checklist["actionable_without_asset_rationale"])
        self.assertTrue(checklist["actionable_with_family_none"])
        self.assertFalse(checklist["low_information_but_has_assets"])
        self.assertEqual(checklist["causal_strength"], "weak")

    def test_engine_quality_checklist_marks_low_information_with_assets(self):
        analysis = {
            "mechanism_summary": "Insufficient evidence.",
            "confidence": "low",
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": [],
            "assets_to_watch": ["XOM"],
            "transmission_chain": [],
            "minimum_proof_set": [],
            "key_falsifiers": [],
        }

        checklist = _engine_quality_checklist(analysis)

        self.assertTrue(checklist["low_information"])
        self.assertTrue(checklist["low_information_but_has_assets"])
        self.assertFalse(checklist["actionable_without_valid_chain"])
        self.assertEqual(checklist["causal_strength"], "weak")

    def test_engine_quality_summary_and_markdown_counts(self):
        results = [
            {
                "primary_thesis_present": True,
                "mechanism_family": "commodity_squeeze",
                "low_information": False,
                "asset_why_lines_present": True,
                "transmission_chain_valid": True,
                "thesis_asset_consistent": True,
                "thesis_proof_consistent": True,
                "thesis_falsifier_consistent": True,
                "chain_ends_in_asset_implication": True,
                "rejected_asset_count": 0,
                "quality_tier": "excellent",
                "high_confidence_without_proof": False,
                "actionable_without_valid_chain": False,
                "actionable_without_asset_rationale": False,
                "actionable_with_family_none": False,
                "low_information_but_has_assets": False,
                "causal_strength": "strong",
                "causal_trigger_present": True,
                "causal_channel_present": True,
                "pricing_relationship_present": True,
                "asset_implication_present": True,
                "regime_caveats_present": True,
                "regime_caveats_concrete": True,
                "primary_asset_count": 2,
                "secondary_asset_count": 1,
                "signal_asset_count": 1,
                "beneficiary_signal_conflict": False,
                "role_channel_mismatch_count": 0,
                "first_order_present": True,
                "second_order_count": 3,
                "second_order_has_bridge": True,
                "second_order_skipped_channel": False,
                "expected_direction_present": True,
                "signal_asset_direction_valid": True,
                "family_chain_consistent": True,
                "generic_chain_hops_count": 0,
                "chain_asset_implication_present": True,
                "coherence_rejection_triggered": False,
                "primary_asset_contradiction_count": 0,
                "weak_signal_only_support": False,
                "mechanism_subtype_present": True,
                "subtype_family_consistent": True,
                "proxy_eligibility_present": True,
                "rejected_proxy_count": 3,
                "low_channel_match_count": 2,
                "high_noise_proxy_count": 2,
                "proof_set_count": 3,
                "falsifier_count": 2,
                "beneficiary_tickers": ["XOM"],
            },
            {
                "primary_thesis_present": False,
                "mechanism_family": "none",
                "low_information": True,
                "asset_why_lines_present": False,
                "transmission_chain_valid": False,
                "thesis_asset_consistent": False,
                "thesis_proof_consistent": False,
                "thesis_falsifier_consistent": False,
                "chain_ends_in_asset_implication": False,
                "rejected_asset_count": 2,
                "quality_tier": "poor",
                "high_confidence_without_proof": True,
                "actionable_without_valid_chain": True,
                "actionable_without_asset_rationale": True,
                "actionable_with_family_none": True,
                "low_information_but_has_assets": True,
                "causal_strength": "weak",
                "causal_trigger_present": False,
                "causal_channel_present": False,
                "pricing_relationship_present": False,
                "asset_implication_present": False,
                "regime_caveats_present": False,
                "regime_caveats_concrete": False,
                "primary_asset_count": 0,
                "secondary_asset_count": 0,
                "signal_asset_count": 2,
                "beneficiary_signal_conflict": True,
                "role_channel_mismatch_count": 2,
                "first_order_present": False,
                "second_order_count": 1,
                "second_order_has_bridge": False,
                "second_order_skipped_channel": True,
                "expected_direction_present": False,
                "signal_asset_direction_valid": False,
                "family_chain_consistent": False,
                "generic_chain_hops_count": 2,
                "chain_asset_implication_present": False,
                "coherence_rejection_triggered": True,
                "primary_asset_contradiction_count": 1,
                "weak_signal_only_support": True,
                "mechanism_subtype_present": False,
                "subtype_family_consistent": False,
                "proxy_eligibility_present": False,
                "rejected_proxy_count": 0,
                "low_channel_match_count": 0,
                "high_noise_proxy_count": 0,
                "proof_set_count": 0,
                "falsifier_count": 0,
                "beneficiary_tickers": [],
            },
        ]

        summary = _engine_quality_summary(results)
        markdown = _format_engine_quality_markdown(summary)

        self.assertEqual(summary["total_samples"], 2)
        self.assertEqual(summary["low_information_count"], 1)
        self.assertEqual(summary["family_none_count"], 1)
        self.assertEqual(summary["missing_thesis_count"], 1)
        self.assertEqual(summary["missing_asset_rationale_count"], 1)
        self.assertEqual(summary["thesis_asset_consistent_count"], 1)
        self.assertEqual(summary["thesis_proof_consistent_count"], 1)
        self.assertEqual(summary["thesis_falsifier_consistent_count"], 1)
        self.assertEqual(summary["chain_ends_in_asset_implication_count"], 1)
        self.assertEqual(summary["rejected_asset_total"], 2)
        self.assertEqual(summary["quality_tier_counts"]["excellent"], 1)
        self.assertEqual(summary["quality_tier_counts"]["poor"], 1)
        self.assertEqual(summary["high_confidence_without_proof_count"], 1)
        self.assertEqual(summary["actionable_without_valid_chain_count"], 1)
        self.assertEqual(summary["actionable_without_asset_rationale_count"], 1)
        self.assertEqual(summary["actionable_with_family_none_count"], 1)
        self.assertEqual(summary["low_information_but_has_assets_count"], 1)
        self.assertEqual(summary["strong_causal_chain_count"], 1)
        self.assertEqual(summary["weak_causal_chain_count"], 1)
        self.assertEqual(summary["causal_trigger_present_count"], 1)
        self.assertEqual(summary["causal_channel_present_count"], 1)
        self.assertEqual(summary["pricing_relationship_present_count"], 1)
        self.assertEqual(summary["asset_implication_present_count"], 1)
        self.assertEqual(summary["regime_caveats_present_count"], 1)
        self.assertEqual(summary["regime_caveats_concrete_count"], 1)
        self.assertEqual(summary["primary_asset_total"], 2)
        self.assertEqual(summary["secondary_asset_total"], 1)
        self.assertEqual(summary["signal_asset_total"], 3)
        self.assertEqual(summary["beneficiary_signal_conflict_count"], 1)
        self.assertEqual(summary["role_channel_mismatch_total"], 2)
        self.assertEqual(summary["first_order_present_count"], 1)
        self.assertEqual(summary["second_order_total"], 4)
        self.assertEqual(summary["second_order_has_bridge_count"], 1)
        self.assertEqual(summary["second_order_skipped_channel_count"], 1)
        self.assertEqual(summary["expected_direction_present_count"], 1)
        self.assertEqual(summary["signal_asset_direction_valid_count"], 1)
        self.assertEqual(summary["family_chain_consistent_count"], 1)
        self.assertEqual(summary["generic_chain_hops_total"], 2)
        self.assertEqual(summary["chain_asset_implication_present_count"], 1)
        self.assertEqual(summary["coherence_rejection_triggered_count"], 1)
        self.assertEqual(summary["primary_asset_contradiction_total"], 1)
        self.assertEqual(summary["weak_signal_only_support_count"], 1)
        self.assertEqual(summary["mechanism_subtype_present_count"], 1)
        self.assertEqual(summary["subtype_family_consistent_count"], 1)
        self.assertEqual(summary["proxy_eligibility_present_count"], 1)
        self.assertEqual(summary["rejected_proxy_total"], 3)
        self.assertEqual(summary["low_channel_match_total"], 2)
        self.assertEqual(summary["high_noise_proxy_total"], 2)
        self.assertIn("## Engine Quality Summary", markdown)
        self.assertIn("- Total samples: 2", markdown)
        self.assertIn("- Missing-asset-rationale count: 1", markdown)
        self.assertIn("- Thesis-asset consistent count: 1", markdown)
        self.assertIn("- Rejected-asset entries: 2", markdown)
        self.assertIn("- High-confidence without proof count: 1", markdown)
        self.assertIn("- Actionable with family-none count: 1", markdown)
        self.assertIn("- Low-information but has assets count: 1", markdown)
        self.assertIn("- Strong causal chain count: 1", markdown)
        self.assertIn("- Weak causal chain count: 1", markdown)
        self.assertIn("- Pricing relationship present count: 1", markdown)
        self.assertIn("- Regime caveats present count: 1", markdown)
        self.assertIn("- Signal asset entries: 3", markdown)
        self.assertIn("- Role/channel mismatch entries: 2", markdown)
        self.assertIn("- First-order present count: 1", markdown)
        self.assertIn("- Second-order entries: 4", markdown)
        self.assertIn("- Second-order skipped-channel count: 1", markdown)
        self.assertIn("- Expected direction present count: 1", markdown)
        self.assertIn("- Signal asset direction valid count: 1", markdown)
        self.assertIn("- Family-chain consistent count: 1", markdown)
        self.assertIn("- Generic chain-hop entries: 2", markdown)
        self.assertIn("- Chain asset implication present count: 1", markdown)
        self.assertIn("- Coherence rejection triggered count: 1", markdown)
        self.assertIn("- Primary asset contradiction entries: 1", markdown)
        self.assertIn("- Weak signal-only support count: 1", markdown)
        self.assertIn("- Mechanism subtype present count: 1", markdown)
        self.assertIn("- Subtype-family consistent count: 1", markdown)
        self.assertIn("- Proxy eligibility present count: 1", markdown)
        self.assertIn("- Rejected proxy entries: 3", markdown)
        self.assertIn("- Low channel-match entries: 2", markdown)
        self.assertIn("- High-noise proxy entries: 2", markdown)
        self.assertIn("- Quality tiers: excellent 1 / usable 0 / thin 0 / poor 1", markdown)


# ---------------------------------------------------------------------------
# Before/after comparison block
# ---------------------------------------------------------------------------

class TestEngineQualityDeltas(unittest.TestCase):
    """Compare current run against the previous saved eval output and
    surface deltas for the contract-tightening counters."""

    def _result(self, **overrides) -> dict:
        base = {
            "primary_thesis_present": True,
            "mechanism_family": "supply_normalization",
            "low_information": False,
            "asset_why_lines_present": True,
            "transmission_chain_valid": True,
            "proof_set_count": 2,
            "falsifier_count": 1,
            "beneficiary_tickers": ["CVX"],
            "loser_tickers": ["SU"],
        }
        base.update(overrides)
        return base

    def test_summary_carries_eight_delta_keys(self):
        """The summary dict surfaces all eight metrics the task names
        — the diff layer reads off these keys."""
        summary = _engine_quality_summary([self._result()])
        for key in (
            "low_information_count",
            "family_none_count",
            "missing_thesis_count",
            "missing_asset_rationale_count",
            "rejected_asset_count",
            "valid_transmission_chain_count",
            "proof_set_count",
            "falsifier_count",
        ):
            self.assertIn(key, summary, f"summary missing {key!r}")

    def test_proof_and_falsifier_counts_sum_across_results(self):
        results = [
            self._result(proof_set_count=3, falsifier_count=2),
            self._result(proof_set_count=1, falsifier_count=4),
        ]
        summary = _engine_quality_summary(results)
        self.assertEqual(summary["proof_set_count"], 4)
        self.assertEqual(summary["falsifier_count"], 6)

    def test_valid_transmission_chain_count_sums_truthy(self):
        results = [
            self._result(transmission_chain_valid=True),
            self._result(transmission_chain_valid=False),
            self._result(transmission_chain_valid=True),
        ]
        summary = _engine_quality_summary(results)
        self.assertEqual(summary["valid_transmission_chain_count"], 2)

    def test_rejected_asset_count_fires_when_assets_empty_and_not_low_info(self):
        """A non-low-info result with empty ticker buckets is the
        sanitizer-rejected case."""
        rejected = self._result(
            beneficiary_tickers=[], loser_tickers=[], assets_to_watch=[],
        )
        kept = self._result(beneficiary_tickers=["XOM"], loser_tickers=[])
        # low-info results are NOT counted as rejection — that's a
        # different failure mode.
        low_info = self._result(low_information=True,
                                beneficiary_tickers=[], loser_tickers=[])

        self.assertTrue(_result_was_asset_rejected(rejected))
        self.assertFalse(_result_was_asset_rejected(kept))
        self.assertFalse(_result_was_asset_rejected(low_info))

        summary = _engine_quality_summary([rejected, kept, low_info])
        self.assertEqual(summary["rejected_asset_count"], 1)

    def test_compute_deltas_pairs_keys(self):
        previous = {
            "low_information_count": 4,
            "family_none_count": 3,
            "missing_thesis_count": 2,
            "missing_asset_rationale_count": 5,
            "rejected_asset_count": 2,
            "valid_transmission_chain_count": 8,
            "proof_set_count": 12,
            "falsifier_count": 7,
        }
        current = {
            "low_information_count": 1,
            "family_none_count": 1,
            "missing_thesis_count": 0,
            "missing_asset_rationale_count": 2,
            "rejected_asset_count": 0,
            "valid_transmission_chain_count": 12,
            "proof_set_count": 18,
            "falsifier_count": 11,
        }
        deltas = _compute_engine_quality_deltas(current, previous)
        self.assertEqual(deltas["low_information_count"], -3)
        self.assertEqual(deltas["family_none_count"], -2)
        self.assertEqual(deltas["missing_thesis_count"], -2)
        self.assertEqual(deltas["valid_transmission_chain_count"], +4)
        self.assertEqual(deltas["proof_set_count"], +6)
        self.assertEqual(deltas["falsifier_count"], +4)

    def test_compute_deltas_returns_empty_without_previous(self):
        deltas = _compute_engine_quality_deltas(
            {"low_information_count": 2}, None,
        )
        self.assertEqual(deltas, {})

    def test_markdown_renders_signed_deltas_when_provided(self):
        summary = {
            "total_samples": 6,
            "low_information_count": 1,
            "family_none_count": 1,
            "missing_thesis_count": 0,
            "missing_asset_rationale_count": 2,
            "rejected_asset_count": 0,
            "valid_transmission_chain_count": 5,
            "proof_set_count": 14,
            "falsifier_count": 8,
        }
        deltas = {
            "low_information_count": -3,
            "valid_transmission_chain_count": +4,
            "proof_set_count": +6,
            "falsifier_count": 0,
        }
        md = _format_engine_quality_markdown(
            summary, deltas=deltas,
            previous_path="eval_output_2026-04-25_18-00-00.json",
        )
        self.assertIn("- Low-information count: 1  (Δ -3)", md)
        self.assertIn("- Valid transmission_chain count: 5  (Δ +4)", md)
        self.assertIn("- Proof-set entries: 14  (Δ +6)", md)
        self.assertIn("- Falsifier entries: 8  (Δ 0)", md)
        self.assertIn(
            "_Deltas vs eval_output_2026-04-25_18-00-00.json._", md,
        )

    def test_markdown_legacy_layout_when_no_deltas(self):
        """When no previous run exists the markdown falls back to the
        legacy single-run layout — no Δ annotation, no 'Deltas vs'
        footer."""
        summary = _engine_quality_summary([self._result()])
        md = _format_engine_quality_markdown(summary)
        self.assertIn("## Engine Quality Summary", md)
        self.assertNotIn("Δ", md)
        self.assertNotIn("Deltas vs", md)


class TestPreviousEvalDiscovery(unittest.TestCase):
    """``_find_previous_eval_output`` walks the cwd for the most
    recent prior eval JSON, excluding the file the current run is
    about to write."""

    def setUp(self) -> None:
        # Keep temp JSON inside the workspace sandbox.  The unique
        # directory isolates this class from real eval_output_*.json files.
        self._tmp = os.path.join(
            os.path.dirname(__file__),
            f"eval_tmp_{uuid.uuid4().hex}",
        )
        os.makedirs(self._tmp, exist_ok=True)
        self._created: list[str] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for path in self._created:
            try:
                os.remove(path)
            except OSError:
                pass
        try:
            os.rmdir(self._tmp)
        except OSError:
            pass

    def _write(self, name: str, body: dict | str) -> str:
        path = os.path.join(self._tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            if isinstance(body, dict):
                json.dump(body, f)
            else:
                f.write(body)
        self._created.append(path)
        return path

    def test_returns_none_when_no_prior_runs_exist(self):
        self.assertIsNone(_find_previous_eval_output(cwd=self._tmp))

    def test_picks_lexicographically_latest_prior_run(self):
        """File names are timestamp-prefixed so lexicographic order
        matches chronological order."""
        self._write("eval_output_20260420_100000.json",
                    {"engine_quality_summary": {"low_information_count": 5}})
        self._write("eval_output_20260425_180000.json",
                    {"engine_quality_summary": {"low_information_count": 2}})
        path = _find_previous_eval_output(cwd=self._tmp)
        self.assertIsNotNone(path)
        self.assertTrue(path.endswith("20260425_180000.json"))

    def test_excludes_current_run_path(self):
        """Caller passes the path the current run is writing — the
        helper must skip it so the comparison reaches the prior run."""
        prior = self._write(
            "eval_output_20260420_100000.json",
            {"engine_quality_summary": {"low_information_count": 5}},
        )
        current = self._write(
            "eval_output_20260425_180000.json", "",
        )
        path = _find_previous_eval_output(exclude=current, cwd=self._tmp)
        self.assertEqual(os.path.abspath(path), os.path.abspath(prior))

    def test_ignores_non_timestamped_stable_output_names(self):
        self._write(
            "eval_output_latest.json",
            {"engine_quality_summary": {"low_information_count": 99}},
        )
        prior = self._write(
            "eval_output_20260420_100000.json",
            {"engine_quality_summary": {"low_information_count": 5}},
        )

        path = _find_previous_eval_output(cwd=self._tmp)

        self.assertEqual(os.path.abspath(path), os.path.abspath(prior))

    def test_load_engine_summary_returns_block(self):
        path = self._write(
            "eval_output_20260420_100000.json",
            {"engine_quality_summary": {"low_information_count": 5}},
        )
        summary = _load_engine_summary(path)
        self.assertEqual(summary, {"low_information_count": 5})

    def test_load_engine_summary_safe_on_missing_or_corrupt(self):
        self.assertIsNone(_load_engine_summary(None))
        self.assertIsNone(
            _load_engine_summary(os.path.join(self._tmp, "nope.json")),
        )
        bad = self._write("eval_output_bad.json", "{not valid json")
        self.assertIsNone(_load_engine_summary(bad))

    def _output(
        self,
        *,
        timestamp: str,
        preset: str,
        sample_count: int,
        low_information_count: int,
        family_none_count: int,
        red_flag_count: int,
    ) -> dict:
        return {
            "generated_at": timestamp,
            "preset_name": preset,
            "num_samples": sample_count,
            "engine_quality_summary": {
                "low_information_count": low_information_count,
                "family_none_count": family_none_count,
            },
            "engine_eval_red_flags": {
                "flag": {"count": red_flag_count, "sample_ids": []},
            },
        }

    def test_run_index_entry_and_update(self):
        output = self._output(
            timestamp="2026-04-20T10:00:00",
            preset="targeted",
            sample_count=10,
            low_information_count=1,
            family_none_count=2,
            red_flag_count=3,
        )
        index_path = os.path.join(self._tmp, "eval_run_index.json")

        entry = _run_index_entry("eval_output_20260420_100000.json", output)
        runs = _update_run_index(
            "eval_output_20260420_100000.json",
            output,
            path=index_path,
        )

        self.assertEqual(entry["preset"], "targeted")
        self.assertEqual(entry["sample_count"], 10)
        self.assertEqual(entry["low_information_count"], 1)
        self.assertEqual(entry["family_none_count"], 2)
        self.assertEqual(entry["red_flag_count"], 3)
        self.assertEqual(runs, _load_run_index(index_path))

    def test_compare_latest_eval_runs_prints_compact_deltas(self):
        previous = self._output(
            timestamp="2026-04-20T10:00:00",
            preset="targeted",
            sample_count=3,
            low_information_count=1,
            family_none_count=2,
            red_flag_count=1,
        )
        current = self._output(
            timestamp="2026-04-21T10:00:00",
            preset="targeted",
            sample_count=4,
            low_information_count=2,
            family_none_count=1,
            red_flag_count=3,
        )
        self._write("eval_output_20260420_100000.json", previous)
        self._write("eval_output_20260421_100000.json", current)

        markdown = compare_latest_eval_runs(cwd=self._tmp)

        self.assertIn("## Latest Eval Comparison", markdown)
        self.assertIn("- Sample count: 4  (Δ +1)", markdown)
        self.assertIn("- Low-information count: 2  (Δ +1)", markdown)
        self.assertIn("- Family-none count: 1  (Δ -1)", markdown)
        self.assertIn("- Red-flag count: 3  (Δ +2)", markdown)


# ---------------------------------------------------------------------------
# Subtype normalization + proxy-eligibility diagnostics
# ---------------------------------------------------------------------------

class TestSubtypeAndProxyDiagnostics(unittest.TestCase):
    """Six new eval-only fields layered on top of the existing
    diagnostics — never touch engine logic or market fetches.

    Each helper must default cleanly when the underlying engine field
    is absent: bool fields → False, int fields → 0.
    """

    def _baseline_analysis(self, **overrides) -> dict:
        base = {
            "mechanism_family": "tariff",
            "mechanism_subtype": "import_tariff_china",
            "primary_assets": [
                {"symbol": "KWEB", "rank": 1,
                 "rationale": "China-exposed equity basket — direct trade-balance drag."},
                {"symbol": "FXI", "rank": 2,
                 "rationale": "China large-cap basket — secondary tariff hit."},
            ],
            "secondary_assets": [],
            "hedge_or_signal_assets": [
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
                {"symbol": "VIX", "rank": 2,
                 "rationale": "Vol watch instrument — tape-level signal."},
            ],
            "beneficiary_tickers": ["KWEB", "FXI"],
            "loser_tickers": [],
            "validation_warnings": [],
        }
        base.update(overrides)
        return base

    # mechanism_subtype_valid -----------------------------------------------

    def test_subtype_valid_when_registered_for_family(self):
        from eval import _mechanism_subtype_valid
        ev = self._baseline_analysis()
        self.assertTrue(_mechanism_subtype_valid(ev))

    def test_subtype_invalid_when_unknown_for_family(self):
        from eval import _mechanism_subtype_valid
        ev = self._baseline_analysis(mechanism_subtype="oil_supply_shock")
        self.assertFalse(_mechanism_subtype_valid(ev))

    def test_subtype_invalid_when_absent(self):
        from eval import _mechanism_subtype_valid
        ev = self._baseline_analysis()
        del ev["mechanism_subtype"]
        self.assertFalse(_mechanism_subtype_valid(ev))

    def test_subtype_invalid_when_family_is_none(self):
        from eval import _mechanism_subtype_valid
        ev = self._baseline_analysis(mechanism_family="none")
        self.assertFalse(_mechanism_subtype_valid(ev))

    # subtype_dropped_or_warned ---------------------------------------------

    def test_subtype_dropped_warning_marker_detected(self):
        from eval import _subtype_dropped_or_warned
        ev = self._baseline_analysis(
            validation_warnings=[
                "mechanism_subtype dropped — 'oil_supply_shock' not "
                "valid for family 'tariff'",
            ],
        )
        self.assertTrue(_subtype_dropped_or_warned(ev))

    def test_subtype_dropped_false_when_no_warning(self):
        from eval import _subtype_dropped_or_warned
        self.assertFalse(_subtype_dropped_or_warned(self._baseline_analysis()))

    def test_subtype_dropped_false_when_validation_warnings_absent(self):
        from eval import _subtype_dropped_or_warned
        ev = self._baseline_analysis()
        del ev["validation_warnings"]
        self.assertFalse(_subtype_dropped_or_warned(ev))

    def test_subtype_dropped_ignores_unrelated_warnings(self):
        """A warning that doesn't mention mechanism_subtype must NOT
        trip the field."""
        from eval import _subtype_dropped_or_warned
        ev = self._baseline_analysis(
            validation_warnings=[
                "weak causal chain — proof / falsifier structure cleared",
                "transmission_path partially off-family — capped to watch_only",
            ],
        )
        self.assertFalse(_subtype_dropped_or_warned(ev))

    # primary_weighted_assets_count -----------------------------------------

    def test_primary_weighted_count_reads_primary_assets(self):
        from eval import _primary_weighted_assets_count
        self.assertEqual(
            _primary_weighted_assets_count(self._baseline_analysis()), 2,
        )

    def test_primary_weighted_count_falls_back_to_beneficiary_tickers(self):
        """When ``primary_assets`` is empty, the helper falls back to
        legacy ``beneficiary_tickers`` so legacy analyses still
        report a usable number."""
        from eval import _primary_weighted_assets_count
        ev = self._baseline_analysis(
            primary_assets=[],
            beneficiary_tickers=["XOM", "CVX", "VLO"],
        )
        self.assertEqual(_primary_weighted_assets_count(ev), 3)

    def test_primary_weighted_count_zero_on_absent_fields(self):
        from eval import _primary_weighted_assets_count
        self.assertEqual(_primary_weighted_assets_count({}), 0)

    # rejected_assets_excluded_from_validation ------------------------------

    def test_rejected_excluded_zero_on_clean_event(self):
        from eval import _rejected_assets_excluded_from_validation
        ev = self._baseline_analysis()
        self.assertEqual(
            _rejected_assets_excluded_from_validation(ev), 0,
        )

    def test_rejected_excluded_combines_consistency_and_proxy(self):
        """The new helper combines consistency-rejection and proxy-
        rejection counts — both surfaces feed the same number."""
        from eval import _rejected_assets_excluded_from_validation
        ev = self._baseline_analysis(
            primary_assets=[
                {"symbol": "KWEB", "rank": 1,
                 "rationale": "China-exposed equity basket — direct trade-balance drag."},
                {"symbol": "AAPL", "rank": 2,
                 "rationale": "Smartphone shipments improve in Asia next quarter."},
            ],
            competing_thesis={
                "primary_thesis": (
                    "Section 301 tariff on Chinese imports widens "
                    "trade-balance drag; KWEB / FXI baskets reprice."
                ),
            },
            mechanism_summary=(
                "Tariff wedge on Chinese imports tightens trade balances."
            ),
            rejected_proxies=[
                {"symbol": "EWJ", "reason": "off-channel"},
            ],
        )
        # AAPL's rationale is off-thesis vs the tariff thesis tokens →
        # consistency drops it; rejected_proxies adds 1 more.
        self.assertGreaterEqual(
            _rejected_assets_excluded_from_validation(ev), 2,
        )

    # signal_assets_channel_bound -------------------------------------------

    def test_signal_assets_channel_bound_counts_macro_proxies(self):
        from eval import _signal_assets_channel_bound
        # UUP rationale mentions FX, VIX rationale mentions vol —
        # both are channel-bound.
        self.assertEqual(
            _signal_assets_channel_bound(self._baseline_analysis()), 2,
        )

    def test_signal_assets_channel_bound_zero_when_no_binding(self):
        from eval import _signal_assets_channel_bound
        ev = self._baseline_analysis(
            hedge_or_signal_assets=[
                {"symbol": "ABC", "rank": 1,
                 "rationale": "Generic hedge instrument with no specific binding."},
            ],
        )
        self.assertEqual(_signal_assets_channel_bound(ev), 0)

    def test_signal_assets_channel_bound_explicit_channel_field(self):
        """An explicit ``channel`` key on the entry counts even when
        the rationale itself is generic."""
        from eval import _signal_assets_channel_bound
        ev = self._baseline_analysis(
            hedge_or_signal_assets=[
                {"symbol": "DXY", "rank": 1, "channel": "fx",
                 "rationale": "Generic hedge."},
            ],
        )
        self.assertEqual(_signal_assets_channel_bound(ev), 1)

    def test_signal_assets_channel_bound_zero_when_field_absent(self):
        from eval import _signal_assets_channel_bound
        self.assertEqual(_signal_assets_channel_bound({}), 0)

    # high_noise_override_detected ------------------------------------------

    def test_high_noise_override_detected_on_marker(self):
        from eval import _high_noise_override_detected
        ev = self._baseline_analysis(
            validation_warnings=[
                "weak causal chain — proof / falsifier structure cleared",
            ],
        )
        self.assertTrue(_high_noise_override_detected(ev))

    def test_high_noise_override_detected_on_consistency_collapse(self):
        from eval import _high_noise_override_detected
        ev = self._baseline_analysis(
            validation_warnings=[
                "cross-field consistency collapsed — coerced to low-information",
            ],
        )
        self.assertTrue(_high_noise_override_detected(ev))

    def test_high_noise_override_false_on_clean_event(self):
        from eval import _high_noise_override_detected
        self.assertFalse(_high_noise_override_detected(self._baseline_analysis()))

    def test_high_noise_override_false_when_warnings_absent(self):
        from eval import _high_noise_override_detected
        self.assertFalse(_high_noise_override_detected({}))

    # Checklist + summary integration ---------------------------------------

    def test_checklist_carries_six_new_fields(self):
        ev = self._baseline_analysis(
            validation_warnings=[
                "mechanism_subtype dropped — 'foo' not valid for family 'tariff'",
                "weak causal chain — proof / falsifier structure cleared",
            ],
            mechanism_subtype="foo",
        )
        cl = _engine_quality_checklist(ev)
        for key in (
            "mechanism_subtype_valid",
            "subtype_dropped_or_warned",
            "primary_weighted_assets_count",
            "rejected_assets_excluded_from_validation",
            "signal_assets_channel_bound",
            "high_noise_override_detected",
        ):
            self.assertIn(key, cl)
        self.assertFalse(cl["mechanism_subtype_valid"])
        self.assertTrue(cl["subtype_dropped_or_warned"])
        self.assertEqual(cl["primary_weighted_assets_count"], 2)
        self.assertEqual(cl["signal_assets_channel_bound"], 2)
        self.assertTrue(cl["high_noise_override_detected"])

    def test_summary_aggregates_six_new_counts(self):
        results = [
            self._baseline_analysis(),  # all-clean
            self._baseline_analysis(   # subtype dropped + noise override
                mechanism_subtype="oil_supply_shock",
                validation_warnings=[
                    "mechanism_subtype dropped — 'oil_supply_shock' not "
                    "valid for family 'tariff'",
                    "weak causal chain — proof / falsifier structure cleared",
                ],
            ),
        ]
        # Add the same per-result fields the engine_quality_checklist
        # would attach.  We compute via the public helpers so the
        # summary aggregator reads them off the result rows.
        flattened = []
        for ev in results:
            flattened.append({**ev, **_engine_quality_checklist(ev)})

        summary = _engine_quality_summary(flattened)
        self.assertEqual(summary["mechanism_subtype_valid_count"], 1)
        self.assertEqual(summary["subtype_dropped_or_warned_count"], 1)
        self.assertEqual(summary["primary_weighted_assets_total"], 4)
        self.assertEqual(summary["signal_assets_channel_bound_total"], 4)
        self.assertEqual(summary["high_noise_override_detected_count"], 1)
        self.assertGreaterEqual(
            summary["rejected_assets_excluded_total"], 0,
        )

    def test_markdown_renders_six_new_fields(self):
        summary = _engine_quality_summary([])
        # Inject non-zero values so the markdown labels surface.
        summary.update({
            "total_samples": 3,
            "mechanism_subtype_valid_count":     2,
            "subtype_dropped_or_warned_count":   1,
            "primary_weighted_assets_total":     6,
            "rejected_assets_excluded_total":    4,
            "signal_assets_channel_bound_total": 5,
            "high_noise_override_detected_count": 1,
        })
        md = _format_engine_quality_markdown(summary)
        self.assertIn("- Mechanism subtype valid count: 2", md)
        self.assertIn("- Subtype dropped/warned count: 1", md)
        self.assertIn("- Primary weighted-asset entries: 6", md)
        self.assertIn(
            "- Rejected assets excluded from validation: 4", md,
        )
        self.assertIn("- Signal assets channel-bound entries: 5", md)
        self.assertIn("- High-noise override detected count: 1", md)

    def test_summary_clean_zero_defaults_on_empty_result_set(self):
        """All six new summary counts default to 0 when the result
        list is empty — eval markdown stays clean on first runs."""
        summary = _engine_quality_summary([])
        for key in (
            "mechanism_subtype_valid_count",
            "subtype_dropped_or_warned_count",
            "primary_weighted_assets_total",
            "rejected_assets_excluded_total",
            "signal_assets_channel_bound_total",
            "high_noise_override_detected_count",
        ):
            self.assertIn(key, summary)
            self.assertEqual(summary[key], 0)


class TestRationaleQualityDiagnostics(unittest.TestCase):

    def _result(self, **overrides) -> dict:
        base = {
            "low_information": False,
            "mechanism_family": "supply_chain_chokepoint",
            "primary_thesis_present": True,
            "asset_why_lines_present": True,
            "transmission_chain_valid": True,
            "confidence_rationale_present": False,
            "confidence_rationale_concrete": False,
            "thesis_state_present": False,
            "validation_rationale_present": False,
            "validation_rationale_concrete": False,
            "actionability_check_shaped": False,
            "counterfactual_check_present": False,
            "counterfactual_check_shaped": False,
            "counterfactual_evidence_count": 0,
            "proof_status_shaped": False,
            "proof_status_item_count": 0,
            "falsifier_status_shaped": False,
            "falsifier_status_item_count": 0,
            "evidence_sources_shaped": False,
            "rationale_too_generic": False,
        }
        base.update(overrides)
        return base

    def test_summary_aggregates_rationale_quality_counts(self):
        summary = _engine_quality_summary([
            self._result(
                confidence_rationale_present=True,
                confidence_rationale_concrete=True,
                thesis_state_present=True,
                validation_rationale_present=True,
                validation_rationale_concrete=True,
                actionability_check_shaped=True,
                counterfactual_check_present=True,
                counterfactual_check_shaped=True,
                counterfactual_evidence_count=2,
                proof_status_shaped=True,
                proof_status_item_count=3,
                falsifier_status_shaped=True,
                falsifier_status_item_count=1,
                evidence_sources_shaped=True,
            ),
            self._result(
                confidence_rationale_present=True,
                thesis_state_present=True,
                validation_rationale_present=True,
                counterfactual_check_present=True,
                counterfactual_evidence_count=1,
                proof_status_shaped=True,
                proof_status_item_count=2,
                rationale_too_generic=True,
            ),
        ])

        self.assertEqual(summary["confidence_rationale_present_count"], 2)
        self.assertEqual(summary["confidence_rationale_concrete_count"], 1)
        self.assertEqual(summary["thesis_state_present_count"], 2)
        self.assertEqual(summary["validation_rationale_present_count"], 2)
        self.assertEqual(summary["validation_rationale_concrete_count"], 1)
        self.assertEqual(summary["actionability_check_shaped_count"], 1)
        self.assertEqual(summary["counterfactual_check_present_count"], 2)
        self.assertEqual(summary["counterfactual_check_shaped_count"], 1)
        self.assertEqual(summary["counterfactual_evidence_total"], 3)
        self.assertEqual(summary["proof_status_shaped_count"], 2)
        self.assertEqual(summary["proof_status_item_total"], 5)
        self.assertEqual(summary["falsifier_status_shaped_count"], 1)
        self.assertEqual(summary["falsifier_status_item_total"], 1)
        self.assertEqual(summary["evidence_sources_shaped_count"], 1)
        self.assertEqual(summary["rationale_too_generic_count"], 1)

    def test_markdown_renders_rationale_quality_counts(self):
        summary = _engine_quality_summary([])
        summary.update({
            "total_samples": 2,
            "confidence_rationale_present_count": 2,
            "confidence_rationale_concrete_count": 1,
            "thesis_state_present_count": 2,
            "validation_rationale_present_count": 2,
            "validation_rationale_concrete_count": 1,
            "actionability_check_shaped_count": 1,
            "counterfactual_check_present_count": 2,
            "counterfactual_check_shaped_count": 1,
            "counterfactual_evidence_total": 3,
            "proof_status_shaped_count": 2,
            "proof_status_item_total": 5,
            "falsifier_status_shaped_count": 1,
            "falsifier_status_item_total": 1,
            "evidence_sources_shaped_count": 1,
            "rationale_too_generic_count": 1,
        })

        md = _format_engine_quality_markdown(summary)

        self.assertIn("- Confidence rationale present count: 2", md)
        self.assertIn("- Concrete confidence rationale count: 1", md)
        self.assertIn("- Thesis-state present count: 2", md)
        self.assertIn("- Validation rationale present count: 2", md)
        self.assertIn("- Concrete validation rationale count: 1", md)
        self.assertIn("- Actionability-check shaped count: 1", md)
        self.assertIn("- Counterfactual-check present count: 2", md)
        self.assertIn("- Counterfactual-check shaped count: 1", md)
        self.assertIn("- Counterfactual evidence entries: 3", md)
        self.assertIn("- Proof-status shaped count: 2", md)
        self.assertIn("- Proof-status item entries: 5", md)
        self.assertIn("- Falsifier-status shaped count: 1", md)
        self.assertIn("- Falsifier-status item entries: 1", md)
        self.assertIn("- Evidence-sources shaped count: 1", md)
        self.assertIn("- Rationale too generic count: 1", md)

    def test_summary_zero_defaults_for_rationale_quality_counts(self):
        summary = _engine_quality_summary([])
        for key in (
            "confidence_rationale_present_count",
            "confidence_rationale_concrete_count",
            "thesis_state_present_count",
            "validation_rationale_present_count",
            "validation_rationale_concrete_count",
            "actionability_check_shaped_count",
            "counterfactual_check_present_count",
            "counterfactual_check_shaped_count",
            "counterfactual_evidence_total",
            "proof_status_shaped_count",
            "proof_status_item_total",
            "falsifier_status_shaped_count",
            "falsifier_status_item_total",
            "evidence_sources_shaped_count",
            "rationale_too_generic_count",
        ):
            self.assertIn(key, summary)
            self.assertEqual(summary[key], 0)


class TestFinalPreAuditDiagnostics(unittest.TestCase):

    def _result(self, **overrides) -> dict:
        base = {
            "low_information": False,
            "mechanism_family": "policy_surprise",
            "primary_thesis_present": True,
            "asset_why_lines_present": True,
            "transmission_chain_valid": True,
            "actionability_present": False,
            "tradable_true_without_confirmation": False,
            "low_info_marked_tradable": False,
            "market_macro_conflict_detected": False,
            "conflict_reason_present": False,
            "actionability_risk_level_present": False,
            "invalidation_trigger_present": False,
            "evidence_sources_present": False,
            "evidence_sources_concrete": False,
            "weak_traceability_but_high_confidence": False,
        }
        base.update(overrides)
        return base

    def test_summary_aggregates_final_pre_audit_counts(self):
        summary = _engine_quality_summary([
            self._result(
                actionability_present=True,
                market_macro_conflict_detected=True,
                conflict_reason_present=True,
            ),
            self._result(
                actionability_present=True,
                tradable_true_without_confirmation=True,
                low_info_marked_tradable=True,
                market_macro_conflict_detected=True,
            ),
        ])

        self.assertEqual(summary["actionability_present_count"], 2)
        self.assertEqual(summary["tradable_true_without_confirmation_count"], 1)
        self.assertEqual(summary["low_info_marked_tradable_count"], 1)
        self.assertEqual(summary["market_macro_conflict_detected_count"], 2)
        self.assertEqual(summary["conflict_reason_present_count"], 1)

    def test_markdown_renders_final_pre_audit_counts(self):
        summary = _engine_quality_summary([])
        summary.update({
            "total_samples": 2,
            "actionability_present_count": 2,
            "tradable_true_without_confirmation_count": 1,
            "low_info_marked_tradable_count": 1,
            "market_macro_conflict_detected_count": 2,
            "conflict_reason_present_count": 1,
        })

        md = _format_engine_quality_markdown(summary)

        self.assertIn("- Actionability present count: 2", md)
        self.assertIn(
            "- Tradable true without confirmation count: 1", md,
        )
        self.assertIn("- Low-info marked tradable count: 1", md)
        self.assertIn("- Market/macro conflict detected count: 2", md)
        self.assertIn("- Conflict reason present count: 1", md)

    def test_summary_zero_defaults_for_final_pre_audit_counts(self):
        summary = _engine_quality_summary([])
        for key in (
            "actionability_present_count",
            "tradable_true_without_confirmation_count",
            "low_info_marked_tradable_count",
            "market_macro_conflict_detected_count",
            "conflict_reason_present_count",
        ):
            self.assertIn(key, summary)
            self.assertEqual(summary[key], 0)

    def test_summary_aggregates_risk_and_traceability_counts(self):
        summary = _engine_quality_summary([
            self._result(
                actionability_risk_level_present=True,
                invalidation_trigger_present=True,
                evidence_sources_present=True,
                evidence_sources_concrete=True,
            ),
            self._result(
                evidence_sources_present=True,
                weak_traceability_but_high_confidence=True,
            ),
        ])

        self.assertEqual(summary["actionability_risk_level_present_count"], 1)
        self.assertEqual(summary["invalidation_trigger_present_count"], 1)
        self.assertEqual(summary["evidence_sources_present_count"], 2)
        self.assertEqual(summary["evidence_sources_concrete_count"], 1)
        self.assertEqual(summary["weak_traceability_but_high_confidence_count"], 1)

    def test_markdown_renders_risk_and_traceability_counts(self):
        summary = _engine_quality_summary([])
        summary.update({
            "total_samples": 2,
            "actionability_risk_level_present_count": 1,
            "invalidation_trigger_present_count": 1,
            "evidence_sources_present_count": 2,
            "evidence_sources_concrete_count": 1,
            "weak_traceability_but_high_confidence_count": 1,
        })

        md = _format_engine_quality_markdown(summary)

        self.assertIn("- Actionability risk level present count: 1", md)
        self.assertIn("- Invalidation trigger present count: 1", md)
        self.assertIn("- Evidence sources present count: 2", md)
        self.assertIn("- Concrete evidence sources count: 1", md)
        self.assertIn(
            "- Weak traceability but high confidence count: 1", md,
        )

    def test_summary_zero_defaults_for_risk_and_traceability_counts(self):
        summary = _engine_quality_summary([])
        for key in (
            "actionability_risk_level_present_count",
            "invalidation_trigger_present_count",
            "evidence_sources_present_count",
            "evidence_sources_concrete_count",
            "weak_traceability_but_high_confidence_count",
        ):
            self.assertIn(key, summary)
            self.assertEqual(summary[key], 0)


if __name__ == "__main__":
    unittest.main()
