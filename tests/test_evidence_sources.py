"""
tests/test_evidence_sources.py

Contract tests for the evidence-source traceability layer.

Covers:
  1. ``make_source`` schema — accepts the documented enum values,
     rejects unknown values, trims oversized strings.
  2. ``is_weak_traceability`` predicate — fires on thin / mostly-limited
     lists; passes on substantive lists.
  3. ``analyze_event._clean_competing_thesis`` emits an
     ``evidence_sources`` block when the LLM committed evidence lines.
  4. ``_validate_result`` caps confidence high → medium when the
     thesis-side evidence_sources is weak.
  5. ``compute_evidence_attribution`` emits ``evidence_sources``
     pointing at the per-ticker channel breakdown.
  6. ``compute_reaction_function_divergence`` emits
     ``evidence_sources`` covering the implied-side classifier and
     each priced-side channel read.
  7. ``classify_evidence`` emits ``evidence_sources`` mapped to the
     agreement counters that drove the rung.
  8. ``compose_actionability_check`` appends a substantive
     traceability suffix to ``sizing_caveat`` when traceability is
     weak, and steps the actionable risk up to "elevated".
  9. Frozen-archive read shape — events that do not carry the new
     field stay valid (the field is purely additive).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from evidence_sources import (
    DIRECTIONS,
    SOURCE_TYPES,
    is_weak_traceability,
    make_source,
)


# ---------------------------------------------------------------------------
# 1. make_source schema
# ---------------------------------------------------------------------------


class MakeSourceTests(unittest.TestCase):

    def test_accepts_documented_enums(self) -> None:
        src = make_source(
            source_type="ticker_observation",
            field_used="evidence_attribution.channel_breakdown.equities.XOM",
            supports_or_contradicts="supports",
            limitation="",
        )
        self.assertIsNotNone(src)
        self.assertEqual(src["source_type"], "ticker_observation")
        self.assertEqual(src["supports_or_contradicts"], "supports")
        self.assertEqual(src["limitation"], "")

    def test_rejects_unknown_source_type(self) -> None:
        self.assertIsNone(
            make_source(
                source_type="something_else",
                field_used="x",
                supports_or_contradicts="supports",
            )
        )

    def test_rejects_unknown_direction(self) -> None:
        self.assertIsNone(
            make_source(
                source_type="internal_field",
                field_used="x",
                supports_or_contradicts="maybe",
            )
        )

    def test_rejects_empty_field(self) -> None:
        self.assertIsNone(
            make_source(
                source_type="internal_field",
                field_used="   ",
                supports_or_contradicts="supports",
            )
        )

    def test_trims_oversized_limitation(self) -> None:
        long_limit = "x" * 500
        src = make_source(
            source_type="market_channel",
            field_used="x",
            supports_or_contradicts="neutral",
            limitation=long_limit,
        )
        self.assertIsNotNone(src)
        self.assertLessEqual(len(src["limitation"]), 200)

    def test_enums_have_documented_members(self) -> None:
        self.assertIn("internal_field", SOURCE_TYPES)
        self.assertIn("ticker_observation", SOURCE_TYPES)
        self.assertIn("market_channel", SOURCE_TYPES)
        self.assertIn("thesis_classifier", SOURCE_TYPES)
        self.assertIn("regime_signal", SOURCE_TYPES)
        self.assertIn("agreement_verdict", SOURCE_TYPES)
        self.assertEqual(set(DIRECTIONS), {"supports", "contradicts", "neutral"})


# ---------------------------------------------------------------------------
# 2. is_weak_traceability
# ---------------------------------------------------------------------------


class WeakTraceabilityTests(unittest.TestCase):

    def _src(self, *, limitation: str = "") -> dict:
        return {
            "source_type": "internal_field",
            "field_used":  "x.y",
            "supports_or_contradicts": "supports",
            "limitation":  limitation,
        }

    def test_empty_list_is_weak(self) -> None:
        self.assertTrue(is_weak_traceability([]))

    def test_non_list_is_weak(self) -> None:
        self.assertTrue(is_weak_traceability(None))
        self.assertTrue(is_weak_traceability("foo"))

    def test_single_item_is_weak(self) -> None:
        self.assertTrue(is_weak_traceability([self._src()]))

    def test_two_clean_items_pass(self) -> None:
        self.assertFalse(
            is_weak_traceability([self._src(), self._src()])
        )

    def test_majority_limited_is_weak(self) -> None:
        items = [
            self._src(limitation="thin"),
            self._src(limitation="thin"),
            self._src(),
        ]
        self.assertTrue(is_weak_traceability(items))

    def test_invalid_entries_are_excluded_from_count(self) -> None:
        # Only one structurally valid entry remains → weak.
        items = [
            self._src(),
            {"foo": "bar"},
            {"source_type": "bogus", "field_used": "x",
             "supports_or_contradicts": "supports", "limitation": ""},
        ]
        self.assertTrue(is_weak_traceability(items))


# ---------------------------------------------------------------------------
# 3. competing_thesis emits evidence_sources
# ---------------------------------------------------------------------------


class CompetingThesisSourcesTests(unittest.TestCase):

    def test_primary_only_with_channel_emits_supports(self) -> None:
        from analyze_event import _clean_competing_thesis
        block = _clean_competing_thesis({
            "primary_thesis": "OPEC cuts tighten oil supply",
            "evidence_favoring_primary": [
                {"observation": "Brent backwardation", "channel": "commodities"},
                {"observation": "Inventories drawing", "channel": "commodities"},
            ],
        })
        sources = block.get("evidence_sources")
        self.assertIsInstance(sources, list)
        self.assertEqual(len(sources), 2)
        for s in sources:
            self.assertEqual(s["source_type"], "internal_field")
            self.assertEqual(s["supports_or_contradicts"], "supports")
            self.assertIn("evidence_favoring_primary", s["field_used"])

    def test_alternative_evidence_marked_contradicts(self) -> None:
        from analyze_event import _clean_competing_thesis
        block = _clean_competing_thesis({
            "primary_thesis":     "OPEC cuts tighten oil supply",
            "alternative_thesis": "Demand softness offsets the cut",
            "evidence_favoring_primary": [
                {"observation": "Brent backwardation", "channel": "commodities"},
                {"observation": "Spec long building",  "channel": "commodities"},
            ],
            "evidence_favoring_alternative": [
                {"observation": "China PMI weakening", "channel": "commodities"},
            ],
        })
        sources = block["evidence_sources"]
        contradicts = [s for s in sources if s["supports_or_contradicts"] == "contradicts"]
        self.assertEqual(len(contradicts), 1)
        self.assertIn("evidence_favoring_alternative", contradicts[0]["field_used"])

    def test_single_supporting_line_carries_substantive_limitation(self) -> None:
        from analyze_event import _clean_competing_thesis
        block = _clean_competing_thesis({
            "primary_thesis": "OPEC cuts tighten oil supply",
            "evidence_favoring_primary": [
                {"observation": "Brent backwardation", "channel": "commodities"},
            ],
        })
        sources = block.get("evidence_sources") or []
        self.assertEqual(len(sources), 1)
        self.assertIn("single supporting line", sources[0]["limitation"])

    def test_no_evidence_lines_yields_no_sources_field(self) -> None:
        from analyze_event import _clean_competing_thesis
        block = _clean_competing_thesis({
            "primary_thesis": "OPEC cuts tighten oil supply",
            "evidence_favoring_primary": [],
        })
        self.assertNotIn("evidence_sources", block)


# ---------------------------------------------------------------------------
# 4. confidence downgrade on weak thesis traceability
# ---------------------------------------------------------------------------


class ValidateResultTraceabilityTests(unittest.TestCase):

    def _result(self, *, sources: list[dict]) -> dict:
        return {
            "mechanism_summary": "x" * 50,
            "beneficiary_tickers": ["AAA"],
            "loser_tickers":       ["BBB"],
            "beneficiaries":       ["a"],
            "losers":              ["b"],
            "transmission_chain":  ["1", "2", "3"],
            "confidence":          "high",
            "competing_thesis": {
                "primary_thesis": "Test",
                "evidence_sources": sources,
            },
        }

    def test_high_with_weak_traceability_downgrades(self) -> None:
        from analyze_event import _validate_result
        sources = [
            {"source_type": "internal_field",
             "field_used": "x", "supports_or_contradicts": "supports",
             "limitation": "thin"},
        ]
        out = _validate_result(self._result(sources=sources), stage="realized")
        self.assertEqual(out["confidence"], "medium")
        self.assertTrue(any(
            "weak source traceability" in w
            for w in out.get("validation_warnings", [])
        ))

    def test_high_with_strong_traceability_preserved(self) -> None:
        from analyze_event import _validate_result
        sources = [
            {"source_type": "internal_field", "field_used": "a",
             "supports_or_contradicts": "supports", "limitation": ""},
            {"source_type": "internal_field", "field_used": "b",
             "supports_or_contradicts": "supports", "limitation": ""},
            {"source_type": "internal_field", "field_used": "c",
             "supports_or_contradicts": "contradicts", "limitation": ""},
        ]
        out = _validate_result(self._result(sources=sources), stage="realized")
        # Other rules don't fire on this synthetic shape, so high should
        # survive unless our rule kicked in incorrectly.
        self.assertEqual(out["confidence"], "high")

    def test_no_evidence_sources_field_does_not_trigger_rule(self) -> None:
        from analyze_event import _validate_result
        result = self._result(sources=[])
        result["competing_thesis"].pop("evidence_sources", None)
        out = _validate_result(result, stage="realized")
        # Rule shouldn't fire when the field is absent — other rules
        # may still cap, but for our stripped synthetic event high
        # should survive.
        self.assertEqual(out["confidence"], "high")


# ---------------------------------------------------------------------------
# 5. evidence_attribution emits sources
# ---------------------------------------------------------------------------


class AttributionSourcesTests(unittest.TestCase):

    def test_supports_and_missing_proof_surface_as_sources(self) -> None:
        from evidence_attribution import compute_evidence_attribution
        tickers = [
            {"symbol": "XOM", "benchmark_sector": "Energy",
             "validation_quality": "alpha_support", "return_5d": 3.2,
             "direction_tag": "supports thesis"},
            {"symbol": "USO", "benchmark_sector": "Energy",
             "validation_quality": "alpha_support", "return_5d": 2.8,
             "direction_tag": "supports thesis"},
        ]
        block = compute_evidence_attribution(
            tickers, mechanism_family="supply_shock",
        )
        sources = block.get("evidence_sources")
        self.assertIsInstance(sources, list)
        # At least one ticker_observation source.
        self.assertTrue(any(
            s["source_type"] == "ticker_observation"
            and s["supports_or_contradicts"] == "supports"
            for s in sources
        ))

    def test_beta_aligned_carries_substantive_limitation(self) -> None:
        from evidence_attribution import compute_evidence_attribution
        tickers = [
            {"symbol": "VTI", "benchmark_sector": "Financials",
             "validation_quality": "beta_aligned", "return_5d": 0.5,
             "direction_tag": "supports thesis"},
            {"symbol": "SPY", "benchmark_sector": "Financials",
             "validation_quality": "beta_aligned", "return_5d": 0.4,
             "direction_tag": "supports thesis"},
        ]
        block = compute_evidence_attribution(tickers)
        beta_srcs = [
            s for s in block.get("evidence_sources") or []
            if "beta-aligned" in s["limitation"]
        ]
        self.assertTrue(beta_srcs)


# ---------------------------------------------------------------------------
# 6. reaction_function_divergence emits sources
# ---------------------------------------------------------------------------


class ReactionFunctionSourcesTests(unittest.TestCase):

    def test_implied_classifier_and_macro_unavailable_surface(self) -> None:
        from reaction_function_divergence import (
            compute_reaction_function_divergence,
        )
        block = compute_reaction_function_divergence(
            headline="OPEC cuts production",
            mechanism_text="Tighter oil supply lifts inflation",
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        if not block:
            self.skipTest("classifier did not produce a thesis read on this fixture")
        sources = block.get("evidence_sources")
        self.assertIsInstance(sources, list)
        # Macro inputs unavailable should surface a neutral source with
        # a substantive limitation.
        macro_srcs = [
            s for s in sources
            if s["field_used"] == "reaction_function.macro_inputs"
        ]
        self.assertTrue(macro_srcs)
        self.assertEqual(macro_srcs[0]["supports_or_contradicts"], "neutral")
        self.assertIn("macro inputs unavailable", macro_srcs[0]["limitation"])


# ---------------------------------------------------------------------------
# 7. evidence_ladder emits sources
# ---------------------------------------------------------------------------


class EvidenceLadderSourcesTests(unittest.TestCase):

    def test_primary_confirmation_surfaces_supports(self) -> None:
        from evidence_ladder import classify_evidence
        block = classify_evidence({
            "verdict":           "confirmed",
            "direct_support":    2,
            "direct_contradict": 0,
            "second_order_support":    1,
            "second_order_contradict": 0,
            "n_eligible":        4,
        })
        sources = block.get("evidence_sources")
        self.assertIsInstance(sources, list)
        self.assertTrue(any(
            s["supports_or_contradicts"] == "supports"
            and s["source_type"] == "agreement_verdict"
            for s in sources
        ))

    def test_thin_basket_surfaces_neutral_limitation(self) -> None:
        from evidence_ladder import classify_evidence
        block = classify_evidence({
            "verdict":        "confirmed",
            "direct_support": 1,
            "n_eligible":     1,
        })
        sources = block["evidence_sources"]
        thin = [s for s in sources if "thin basket" in s["limitation"]]
        self.assertEqual(len(thin), 1)
        self.assertEqual(thin[0]["supports_or_contradicts"], "neutral")

    def test_insufficient_tier_yields_empty_sources(self) -> None:
        from evidence_ladder import classify_evidence
        block = classify_evidence({})
        self.assertEqual(block["evidence_sources"], [])


# ---------------------------------------------------------------------------
# 8. compose_actionability_check sizing-caveat suffix
# ---------------------------------------------------------------------------


class ActionabilityTraceabilitySuffixTests(unittest.TestCase):
    """Reuses the actionable-event fixture pattern from
    ``test_actionability_check`` so the synthetic event lands on the
    actionable tier and the suffix logic actually fires."""

    _CONCRETE_MECHANISM = (
        "Saudi Aramco cuts liftings by 1mbd, tightening Gulf Coast "
        "refinery feedstock and widening the WCS-WTI heavy-sour discount."
    )

    _PROOF = {
        "observation": "WCS-WTI heavy-sour discount widens 2pp within 5 trading days",
        "channel":     "commodities",
        "threshold":   "2pp",
        "timing":      "1-5d",
    }

    _FALSIFIER = (
        "Saudi Aramco reverses the lifting cut within 5 trading days, "
        "WCS discount tightens back below 1pp."
    )

    def _actionable_event(self, *, sources: list[dict]) -> dict:
        return {
            "headline":           "OPEC surprise cut",
            "what_changed":       (
                "Saudi Aramco cut crude liftings by 1mbd from August "
                "contract volumes, tightening Gulf Coast feedstock supply."
            ),
            "mechanism_summary":  self._CONCRETE_MECHANISM,
            "mechanism_family":   "commodity_squeeze",
            "beneficiaries":      ["XOM", "CVX"],
            "losers":             ["DAL", "AAL"],
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
                "evidence_sources": sources,
            },
            "minimum_proof_set":  [self._PROOF],
            "key_falsifiers":     [self._FALSIFIER],
        }

    def _strong_sources(self) -> list[dict]:
        return [
            {"source_type": "internal_field", "field_used": "a",
             "supports_or_contradicts": "supports", "limitation": ""},
            {"source_type": "internal_field", "field_used": "b",
             "supports_or_contradicts": "supports", "limitation": ""},
            {"source_type": "internal_field", "field_used": "c",
             "supports_or_contradicts": "contradicts", "limitation": ""},
        ]

    def _weak_sources(self) -> list[dict]:
        return [
            {"source_type": "internal_field", "field_used": "a",
             "supports_or_contradicts": "supports", "limitation": "thin"},
        ]

    def test_actionable_fixture_lands_on_actionable_tier(self) -> None:
        from low_information_gate import evidence_quality_tier
        ev = self._actionable_event(sources=self._strong_sources())
        self.assertEqual(evidence_quality_tier(ev), "actionable")

    def test_strong_traceability_no_suffix(self) -> None:
        from low_information_gate import compose_actionability_check
        out = compose_actionability_check(
            self._actionable_event(sources=self._strong_sources()),
        )
        self.assertNotIn("Source-traceability", out["sizing_caveat"])
        self.assertEqual(out["risk_level"], "standard")

    def test_weak_traceability_appends_suffix(self) -> None:
        from low_information_gate import compose_actionability_check
        out = compose_actionability_check(
            self._actionable_event(sources=self._weak_sources()),
        )
        self.assertIn("Source-traceability is weak", out["sizing_caveat"])

    def test_weak_traceability_steps_actionable_risk_up(self) -> None:
        from low_information_gate import compose_actionability_check
        weak = compose_actionability_check(
            self._actionable_event(sources=self._weak_sources()),
        )
        self.assertEqual(weak["risk_level"], "elevated")


# ---------------------------------------------------------------------------
# 9. Frozen-archive shape stability
# ---------------------------------------------------------------------------


class FrozenArchiveStabilityTests(unittest.TestCase):

    def test_event_without_evidence_sources_does_not_break_actionability(self) -> None:
        """Frozen events written before this change carry no
        ``evidence_sources`` field; the actionability composer must
        still produce its full block without the suffix."""
        from low_information_gate import compose_actionability_check
        event = {
            "what_changed":      "Stale analysis from before the new field",
            "mechanism_summary": "x" * 80,
            # No competing_thesis at all — mirrors a frozen event from
            # before the field existed.
        }
        out = compose_actionability_check(event)
        # We don't care which tier this synthetic lands on, only that
        # the composer returns the documented schema and the suffix
        # is absent.
        for key in ("sizing_caveat", "risk_level",
                    "max_confidence_before_confirmation"):
            self.assertIn(key, out)
        self.assertNotIn("Source-traceability", out["sizing_caveat"])


if __name__ == "__main__":
    unittest.main()
