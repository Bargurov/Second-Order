"""
tests/test_hidden_mechanism.py

Contract tests for the hidden-mechanism forensic-taxonomy layer.

Covers:
  1. Enum registries — bottleneck / transmission_type / channel_domain
     each expose a stable id list + label dict + is_valid_* guard.
  2. Sanitizer — valid enums pass through; invalid / compound / missing
     values normalize to "none"; null-like forensic_note strings are
     stripped; asset_rationales keys filtered to the declared ticker
     universe; all-empty payloads collapse to {}.
  3. Registry passthrough — hidden_mechanism flows through
     ``build_analysis_dict`` (so save/load parity works once the LLM
     pipeline is emitting it).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mechanism_family import (
    BOTTLENECK_IDS, BOTTLENECK_LABELS,
    TRANSMISSION_TYPE_IDS, TRANSMISSION_TYPE_LABELS,
    CHANNEL_DOMAIN_IDS, CHANNEL_DOMAIN_LABELS,
    is_valid_bottleneck, is_valid_transmission_type, is_valid_channel_domain,
)
from analyze_event import (
    LLM_CORE_FIELDS,
    _clean_hidden_mechanism,
    build_analysis_dict,
)


# ---------------------------------------------------------------------------
# 1. Enum registries
# ---------------------------------------------------------------------------

class TestTaxonomyRegistries(unittest.TestCase):

    def test_bottleneck_registry_is_non_empty_and_labels_match(self):
        self.assertGreater(len(BOTTLENECK_IDS), 5)
        for bid in BOTTLENECK_IDS:
            self.assertIn(bid, BOTTLENECK_LABELS)
            self.assertTrue(is_valid_bottleneck(bid))
        self.assertFalse(is_valid_bottleneck("not_a_bottleneck"))
        self.assertFalse(is_valid_bottleneck(None))

    def test_transmission_type_registry_covers_core_modes(self):
        # Core forensic transmission modes must be present.
        for expected in (
            "physical_flow", "pricing_power", "regulatory_gate",
            "financing", "balance_sheet", "substitution", "passthrough",
        ):
            self.assertIn(expected, TRANSMISSION_TYPE_IDS)
            self.assertIn(expected, TRANSMISSION_TYPE_LABELS)
            self.assertTrue(is_valid_transmission_type(expected))
        self.assertFalse(is_valid_transmission_type("sentiment"))

    def test_channel_domain_registry_covers_core_domains(self):
        for expected in (
            "regulatory", "financing", "supply_chain", "demand",
            "macro_rates", "currency", "labor", "infrastructure",
        ):
            self.assertIn(expected, CHANNEL_DOMAIN_IDS)
            self.assertIn(expected, CHANNEL_DOMAIN_LABELS)
            self.assertTrue(is_valid_channel_domain(expected))
        self.assertFalse(is_valid_channel_domain(""))


# ---------------------------------------------------------------------------
# 2. Sanitizer
# ---------------------------------------------------------------------------

_VALID_TICKERS: set[str] = {"CVX", "PBF", "VLO", "SU", "CNQ"}


class TestHiddenMechanismSanitizer(unittest.TestCase):

    def test_valid_block_passes_through(self):
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "commodity_quality_mismatch",
            "transmission_type": "physical_flow",
            "channel_domain":    "supply_chain",
            "forensic_note":     "Gulf Coast coking refineries configured for heavy-sour API 8-16 barrels.",
            "asset_rationales":  {
                "CVX": "Direct licence holder on Venezuelan lift volumes.",
                "PBF": "Gulf Coast pure-play coker refiner.",
            },
        }, _VALID_TICKERS)
        self.assertEqual(out["bottleneck_type"], "commodity_quality_mismatch")
        self.assertEqual(out["transmission_type"], "physical_flow")
        self.assertEqual(out["channel_domain"], "supply_chain")
        self.assertIn("CVX", out["asset_rationales"])
        self.assertIn("Gulf Coast", out["forensic_note"])

    def test_invalid_enum_values_fall_back_to_none(self):
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "commodity_quality_mismatch_with_extras",
            "transmission_type": "regulatory_gate/physical_flow",
            "channel_domain":    "made_up_domain",
            "forensic_note":     "something concrete",
        }, _VALID_TICKERS)
        self.assertEqual(out["bottleneck_type"],   "none")
        self.assertEqual(out["transmission_type"], "none")
        self.assertEqual(out["channel_domain"],    "none")

    def test_asset_rationales_filtered_to_declared_tickers(self):
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "commodity_quality_mismatch",
            "transmission_type": "physical_flow",
            "channel_domain":    "supply_chain",
            "asset_rationales":  {
                "CVX":     "Concrete rationale for CVX.",
                "AAPL":    "Not in the event's ticker universe — must be dropped.",
                "  pbf  ": "Lower-cased + padded keys normalise to PBF.",
            },
        }, _VALID_TICKERS)
        self.assertIn("CVX", out["asset_rationales"])
        self.assertIn("PBF", out["asset_rationales"])
        self.assertNotIn("AAPL", out["asset_rationales"])

    def test_null_like_forensic_note_dropped(self):
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "shipping_chokepoint",
            "transmission_type": "physical_flow",
            "channel_domain":    "infrastructure",
            "forensic_note":     "N/A",
        }, _VALID_TICKERS)
        self.assertNotIn("forensic_note", out)

    def test_all_empty_collapses_to_empty_dict(self):
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "invalid",
            "transmission_type": None,
            "channel_domain":    "",
            "forensic_note":     "n/a",
            "asset_rationales":  {},
        }, _VALID_TICKERS)
        self.assertEqual(out, {})

    def test_non_dict_input_returns_empty_dict(self):
        self.assertEqual(_clean_hidden_mechanism(None, _VALID_TICKERS), {})
        self.assertEqual(_clean_hidden_mechanism("a string", _VALID_TICKERS), {})
        self.assertEqual(_clean_hidden_mechanism(["a", "list"], _VALID_TICKERS), {})

    def test_rationale_values_are_length_capped(self):
        long_line = "x" * 500
        out = _clean_hidden_mechanism({
            "bottleneck_type":   "capacity_bottleneck",
            "transmission_type": "substitution",
            "channel_domain":    "supply_chain",
            "asset_rationales":  {"CVX": long_line},
        }, _VALID_TICKERS)
        # Hard cap lives in the sanitizer — enforce non-unbounded.
        self.assertLessEqual(len(out["asset_rationales"]["CVX"]), 240)


# ---------------------------------------------------------------------------
# 4. Minimum proof set + breakpoints + regime dependency + escape path
# ---------------------------------------------------------------------------

class TestProofAndBreakpoints(unittest.TestCase):

    def _valid_base(self) -> dict:
        return {
            "bottleneck_type":   "commodity_quality_mismatch",
            "transmission_type": "physical_flow",
            "channel_domain":    "supply_chain",
        }

    def test_valid_minimum_proof_set_passes_through(self):
        base = self._valid_base()
        base["minimum_proof_set"] = [
            {"observation": "WCS-WTI discount widens ≥2pp",
             "channel": "commodities", "threshold": "≥2pp",
             "timing": "5-20d"},
            {"observation": "new Chevron cargo loadings at Jose",
             "channel": "commodities", "timing": "1-5d"},
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertEqual(len(out["minimum_proof_set"]), 2)
        self.assertEqual(out["minimum_proof_set"][0]["channel"], "commodities")

    def test_proof_entries_with_invalid_channel_dropped(self):
        base = self._valid_base()
        base["minimum_proof_set"] = [
            {"observation": "foo", "channel": "sentiment"},  # invalid channel
            {"observation": "bar", "channel": "equities"},
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertEqual(len(out["minimum_proof_set"]), 1)
        self.assertEqual(out["minimum_proof_set"][0]["channel"], "equities")

    def test_minimum_proof_set_capped_at_four(self):
        base = self._valid_base()
        base["minimum_proof_set"] = [
            {"observation": f"obs {i}", "channel": "commodities"}
            for i in range(10)
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertLessEqual(len(out["minimum_proof_set"]), 4)

    def test_optional_evidence_is_capped_at_three(self):
        base = self._valid_base()
        base["optional_confirming_evidence"] = [
            {"observation": f"obs {i}", "channel": "credit"}
            for i in range(6)
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertLessEqual(len(out["optional_confirming_evidence"]), 3)

    def test_breakpoint_timing_restricted_to_fast_falsifiers(self):
        """Slow-horizon 'breakpoints' belong in falsifies_if, not here.
        Sanitizer must strip 5-20d / 20d+ timings from critical_breakpoints."""
        base = self._valid_base()
        base["critical_breakpoints"] = [
            {"signal": "fast fade", "channel": "commodities",
             "timing": "1d", "threshold": "oil reverses >50% intraday"},
            {"signal": "slow fade", "channel": "commodities",
             "timing": "20d+", "threshold": "structural"},
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        timings = {b.get("timing") for b in out["critical_breakpoints"]}
        self.assertIn("1d", timings)
        self.assertNotIn("20d+", timings)
        self.assertNotIn("5-20d", timings)

    def test_regime_dependency_flows_through_and_is_capped(self):
        base = self._valid_base()
        base["regime_dependency"] = "Requires tight credit regime with HY >450bp"
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertIn("regime_dependency", out)
        self.assertIn("credit", out["regime_dependency"].lower())

    def test_null_like_regime_dependency_dropped(self):
        base = self._valid_base()
        base["regime_dependency"] = "N/A"
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertNotIn("regime_dependency", out)

    def test_substitution_escape_path_preserved(self):
        base = self._valid_base()
        base["substitution_escape_path"] = "Russia reroutes crude to Indian refiners at discount"
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        self.assertIn("substitution_escape_path", out)
        self.assertIn("India", out["substitution_escape_path"])

    def test_breakpoint_signal_key_preserved(self):
        """Breakpoint entries use 'signal', not 'observation' — check
        the sanitizer keeps the right key label."""
        base = self._valid_base()
        base["critical_breakpoints"] = [
            {"signal": "oil reverses", "channel": "commodities", "timing": "1d"},
        ]
        out = _clean_hidden_mechanism(base, _VALID_TICKERS)
        entry = out["critical_breakpoints"][0]
        self.assertIn("signal", entry)
        self.assertNotIn("observation", entry)

    def test_only_proof_fields_present_still_returns_block(self):
        """If the LLM emits only proof_breakpoints sub-fields and no
        taxonomy values, the block must still be preserved (not collapsed
        to {}).  Taxonomy fields default to 'none'."""
        out = _clean_hidden_mechanism({
            "minimum_proof_set": [
                {"observation": "spot test", "channel": "equities"},
            ],
        }, _VALID_TICKERS)
        self.assertNotEqual(out, {})
        self.assertEqual(out["bottleneck_type"], "none")
        self.assertEqual(len(out["minimum_proof_set"]), 1)


# ---------------------------------------------------------------------------
# 3. Registry passthrough
# ---------------------------------------------------------------------------

class TestBuildAnalysisDictCarriesHiddenMechanism(unittest.TestCase):

    def test_hidden_mechanism_is_in_llm_core_fields(self):
        self.assertIn("hidden_mechanism", LLM_CORE_FIELDS)

    def test_missing_hidden_mechanism_defaults_to_empty_dict(self):
        result = build_analysis_dict({"what_changed": "x"})
        self.assertIn("hidden_mechanism", result)
        self.assertEqual(result["hidden_mechanism"], {})

    def test_present_hidden_mechanism_is_preserved_verbatim(self):
        payload = {
            "bottleneck_type":   "refinancing_channel",
            "transmission_type": "financing",
            "channel_domain":    "financing",
            "forensic_note":     "Five-year maturity wall with no committed rollover.",
            "asset_rationales":  {"XYZ": "direct issuer exposure"},
        }
        result = build_analysis_dict({
            "what_changed":     "x",
            "hidden_mechanism": payload,
        })
        self.assertEqual(result["hidden_mechanism"], payload)


if __name__ == "__main__":
    unittest.main()
