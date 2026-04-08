"""
tests/test_analysis_upgrade.py

Regression tests for the upgraded analysis engine in analyze_event.py.

Covers:
  * messy / self-correcting JSON extraction
  * strict schema normalization (types, enums, null-like filler)
  * malformed structured sections (if_persists, currency_channel,
    transmission_chain)
  * contradiction-aware downgrades
  * degraded-fallback path for weak model outputs
  * ticker overlap dedupe + loser-side inverse proxy fallback
  * the end-to-end _finalize_analysis pipeline
"""

import sys
import unittest

sys.path.insert(0, ".")

from analyze_event import (
    _clean_entity_list,
    _clean_transmission_chain,
    _degraded_fallback,
    _dedupe_ticker_overlap,
    _detect_weak_output,
    _extract_json,
    _finalize_analysis,
    _is_null_like,
    _is_vague_entity,
    _normalize_confidence,
    _normalize_currency_channel,
    _normalize_if_persists,
    _normalize_schema,
    _validate_result,
)


# ---------------------------------------------------------------------------
# Messy / self-correcting JSON extraction
# ---------------------------------------------------------------------------

class TestExtractJsonMessy(unittest.TestCase):

    def test_prose_before_json_extracted(self):
        text = 'Here is the analysis you asked for: {"what_changed": "x"}'
        out = _extract_json(text)
        self.assertEqual(out, {"what_changed": "x"})

    def test_prose_before_and_after_json_extracted(self):
        text = 'Thinking... {"a": 1} and that is the final answer.'
        self.assertEqual(_extract_json(text), {"a": 1})

    def test_fenced_json_block(self):
        text = 'Result:\n```json\n{"a": 1, "b": 2}\n```\nDone.'
        self.assertEqual(_extract_json(text), {"a": 1, "b": 2})

    def test_unfenced_code_block(self):
        text = 'Output:\n```\n{"a": 1}\n```'
        self.assertEqual(_extract_json(text), {"a": 1})

    def test_self_correcting_model_returns_last_block(self):
        """When the model emits a draft followed by a correction, the last
        valid JSON block is the intended final answer."""
        text = (
            'First attempt: {"what_changed": "draft"}\n'
            'Actually, let me revise:\n'
            '{"what_changed": "final"}'
        )
        out = _extract_json(text)
        self.assertEqual(out["what_changed"], "final")

    def test_nested_braces_inside_json(self):
        text = '{"a": 1, "b": {"c": 2, "d": [3, 4]}}'
        out = _extract_json(text)
        self.assertEqual(out["b"]["c"], 2)

    def test_returns_none_for_unparseable(self):
        self.assertIsNone(_extract_json("no json here"))
        self.assertIsNone(_extract_json("{not valid}"))
        self.assertIsNone(_extract_json(""))

    def test_ignores_array_only_input(self):
        """A bare JSON array should not be mistaken for the result dict."""
        self.assertIsNone(_extract_json("[1, 2, 3]"))


# ---------------------------------------------------------------------------
# Null-like / vague placeholder detection
# ---------------------------------------------------------------------------

class TestNullLikeDetection(unittest.TestCase):

    def test_none_is_null_like(self):
        self.assertTrue(_is_null_like(None))

    def test_empty_string_null_like(self):
        self.assertTrue(_is_null_like(""))
        self.assertTrue(_is_null_like("   "))

    def test_literal_null_strings(self):
        for s in ("null", "None", "N/A", "n/a", "nan", "nil", "TBD",
                  "unknown", "unclear", "not applicable", "to be determined"):
            with self.subTest(s=s):
                self.assertTrue(_is_null_like(s))

    def test_real_text_not_null_like(self):
        for s in ("TSMC", "US LNG exporters", "ASML"):
            with self.subTest(s=s):
                self.assertFalse(_is_null_like(s))

    def test_numbers_not_null_like(self):
        self.assertFalse(_is_null_like(42))
        self.assertFalse(_is_null_like(3.14))


class TestVagueEntity(unittest.TestCase):

    def test_various_companies_is_vague(self):
        self.assertTrue(_is_vague_entity("various companies"))
        self.assertTrue(_is_vague_entity("Various Firms"))
        self.assertTrue(_is_vague_entity("several players"))

    def test_the_market_is_vague(self):
        self.assertTrue(_is_vague_entity("the market"))
        self.assertTrue(_is_vague_entity("global markets"))
        self.assertTrue(_is_vague_entity("all investors"))
        self.assertTrue(_is_vague_entity("investors"))

    def test_depends_is_vague(self):
        self.assertTrue(_is_vague_entity("depends on outcome"))
        self.assertTrue(_is_vague_entity("depends on response"))

    def test_tbd_and_unknown(self):
        self.assertTrue(_is_vague_entity("TBD"))
        self.assertTrue(_is_vague_entity("unknown"))
        self.assertTrue(_is_vague_entity("unclear"))
        self.assertTrue(_is_vague_entity("unclear impact"))

    def test_too_short(self):
        self.assertTrue(_is_vague_entity("A"))
        self.assertTrue(_is_vague_entity(""))

    def test_specific_entity_not_vague(self):
        self.assertFalse(_is_vague_entity("US Gulf Coast heavy-crude refiners"))
        self.assertFalse(_is_vague_entity("TSMC"))
        self.assertFalse(_is_vague_entity("Chevron (direct equity upside)"))


# ---------------------------------------------------------------------------
# Clean entity list
# ---------------------------------------------------------------------------

class TestCleanEntityList(unittest.TestCase):

    def test_passes_through_specific_entries(self):
        raw = ["Chevron", "US Gulf Coast refiners", "PBF"]
        self.assertEqual(_clean_entity_list(raw), raw)

    def test_strips_vague_placeholders(self):
        raw = ["various companies", "TSMC", "unknown", "the market", "ASML"]
        out = _clean_entity_list(raw)
        self.assertEqual(out, ["TSMC", "ASML"])

    def test_dedupes_case_insensitive(self):
        raw = ["TSMC", "tsmc", "Tsmc"]
        self.assertEqual(_clean_entity_list(raw), ["TSMC"])

    def test_rejects_non_list(self):
        self.assertEqual(_clean_entity_list("just a string"), [])
        self.assertEqual(_clean_entity_list(None), [])
        self.assertEqual(_clean_entity_list({"a": 1}), [])

    def test_drops_non_string_items(self):
        raw = ["TSMC", None, 42, {"x": 1}, "ASML"]
        self.assertEqual(_clean_entity_list(raw), ["TSMC", "ASML"])

    def test_strips_whitespace(self):
        raw = ["  TSMC  ", "\tASML\n"]
        self.assertEqual(_clean_entity_list(raw), ["TSMC", "ASML"])


# ---------------------------------------------------------------------------
# Clean transmission chain
# ---------------------------------------------------------------------------

class TestCleanTransmissionChain(unittest.TestCase):

    def test_passes_through_list_of_strings(self):
        chain = ["step 1", "step 2", "step 3", "step 4"]
        self.assertEqual(_clean_transmission_chain(chain), chain)

    def test_rejects_non_list(self):
        self.assertEqual(_clean_transmission_chain("just a string"), [])
        self.assertEqual(_clean_transmission_chain(None), [])
        self.assertEqual(_clean_transmission_chain({"step": "x"}), [])

    def test_flattens_dict_items(self):
        """Some models emit [{'step': '...'}, ...] — flatten into strings."""
        chain = [
            {"step": "one"},
            {"step": "two"},
        ]
        out = _clean_transmission_chain(chain)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], "one")

    def test_drops_null_like_entries(self):
        chain = ["real step", "", "null", "N/A", "another real step"]
        self.assertEqual(
            _clean_transmission_chain(chain),
            ["real step", "another real step"],
        )

    def test_caps_at_six_entries(self):
        chain = [f"step {i}" for i in range(10)]
        out = _clean_transmission_chain(chain)
        self.assertEqual(len(out), 6)


# ---------------------------------------------------------------------------
# Confidence normalization
# ---------------------------------------------------------------------------

class TestNormalizeConfidence(unittest.TestCase):

    def test_passes_through_valid_values(self):
        for v in ("low", "medium", "high"):
            self.assertEqual(_normalize_confidence(v), v)

    def test_case_insensitive(self):
        self.assertEqual(_normalize_confidence("HIGH"), "high")
        self.assertEqual(_normalize_confidence("Medium"), "medium")

    def test_strips_trailing_junk(self):
        self.assertEqual(_normalize_confidence("medium confidence"), "medium")
        self.assertEqual(_normalize_confidence("high."), "high")
        self.assertEqual(_normalize_confidence("low,"), "low")

    def test_unknown_defaults_to_low(self):
        self.assertEqual(_normalize_confidence("certain"), "low")
        self.assertEqual(_normalize_confidence(None), "low")
        self.assertEqual(_normalize_confidence(42), "low")


# ---------------------------------------------------------------------------
# if_persists horizon enum
# ---------------------------------------------------------------------------

class TestIfPersistsHorizon(unittest.TestCase):

    def test_quarters_accepted(self):
        out = _normalize_if_persists({
            "substitution": "x is substituted by y over time.",
            "horizon": "quarters",
        })
        self.assertEqual(out["horizon"], "quarters")

    def test_weeks_months_quarters_all_accepted(self):
        for h in ("weeks", "months", "quarters"):
            out = _normalize_if_persists({
                "substitution": "something real",
                "horizon": h,
            })
            self.assertEqual(out["horizon"], h)

    def test_singular_aliases_mapped(self):
        self.assertEqual(
            _normalize_if_persists({"substitution": "x", "horizon": "week"})["horizon"],
            "weeks",
        )
        self.assertEqual(
            _normalize_if_persists({"substitution": "x", "horizon": "month"})["horizon"],
            "months",
        )
        self.assertEqual(
            _normalize_if_persists({"substitution": "x", "horizon": "quarter"})["horizon"],
            "quarters",
        )

    def test_invalid_horizon_dropped(self):
        out = _normalize_if_persists({
            "substitution": "x",
            "horizon": "forever",
        })
        self.assertNotIn("horizon", out)

    def test_days_not_accepted_as_horizon(self):
        out = _normalize_if_persists({
            "substitution": "x",
            "horizon": "days",
        })
        self.assertNotIn("horizon", out)


# ---------------------------------------------------------------------------
# currency_channel normalization edge cases
# ---------------------------------------------------------------------------

class TestNormalizeCurrencyChannelStrict(unittest.TestCase):

    def test_mechanism_too_short_rejected(self):
        raw = {"pair": "DXY", "mechanism": "dollar up"}
        self.assertEqual(_normalize_currency_channel(raw), {})

    def test_pair_and_mechanism_required(self):
        self.assertEqual(
            _normalize_currency_channel({"pair": "DXY"}), {},
        )
        self.assertEqual(
            _normalize_currency_channel({"mechanism": "Dollar strengthens broadly"}),
            {},
        )

    def test_good_channel_preserved(self):
        raw = {
            "pair": "USD/JPY",
            "mechanism": "Widening US-JP rate differential pushes yen weaker against dollar.",
            "beneficiaries": "US importers of Japanese goods",
            "squeezed": "BOJ policy credibility",
        }
        out = _normalize_currency_channel(raw)
        self.assertEqual(out["pair"], "USD/JPY")
        self.assertIn("rate differential", out["mechanism"])

    def test_list_rejected(self):
        self.assertEqual(_normalize_currency_channel([1, 2]), {})


# ---------------------------------------------------------------------------
# Ticker overlap dedupe
# ---------------------------------------------------------------------------

class TestDedupeTickerOverlap(unittest.TestCase):

    def test_no_overlap_untouched(self):
        b, l = _dedupe_ticker_overlap(["TSM"], ["LRCX"])
        self.assertEqual(b, ["TSM"])
        self.assertEqual(l, ["LRCX"])

    def test_overlap_removed_from_loser(self):
        b, l = _dedupe_ticker_overlap(["TSM", "ASML"], ["ASML", "LRCX"])
        self.assertEqual(b, ["TSM", "ASML"])
        self.assertEqual(l, ["LRCX"])

    def test_proxy_suffix_preserved_across_overlap_check(self):
        """Proxy-suffixed losers should not be dropped by the dedupe."""
        b, l = _dedupe_ticker_overlap(["SH"], ["SH (proxy)"])
        self.assertEqual(l, ["SH (proxy)"])

    def test_case_insensitive_overlap(self):
        b, l = _dedupe_ticker_overlap(["tsm"], ["TSM"])
        self.assertEqual(l, [])


# ---------------------------------------------------------------------------
# Weak-output detection + degraded fallback
# ---------------------------------------------------------------------------

class TestWeakOutputDetection(unittest.TestCase):

    def test_thin_mechanism_and_no_chain_detected(self):
        result = {
            "mechanism_summary": "short",
            "what_changed": "x",
            "transmission_chain": [],
            "beneficiaries": [],
            "losers": [],
        }
        self.assertIsNotNone(_detect_weak_output(result))

    def test_insufficient_evidence_and_empty_sections_detected(self):
        result = {
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "what_changed": "x",
            "transmission_chain": [],
            "beneficiaries": [],
            "losers": [],
        }
        reason = _detect_weak_output(result)
        self.assertIsNotNone(reason)
        self.assertIn("insufficient", reason)

    def test_thin_mechanism_but_real_chain_not_weak(self):
        result = {
            "mechanism_summary": "short",
            "what_changed": "also short",
            "transmission_chain": ["step1", "step2", "step3"],
            "beneficiaries": [],
            "losers": [],
        }
        self.assertIsNone(_detect_weak_output(result))

    def test_rich_mechanism_not_weak(self):
        result = {
            "mechanism_summary": (
                "A very long mechanism summary that clearly describes the "
                "first-order disruption, the secondary effect, and who wins "
                "and loses in each leg of the transmission chain."
            ),
            "what_changed": "A concrete policy change is described here.",
            "transmission_chain": [],
            "beneficiaries": [],
            "losers": [],
        }
        self.assertIsNone(_detect_weak_output(result))


class TestDegradedFallback(unittest.TestCase):

    def test_degraded_marker_present(self):
        out = _degraded_fallback(
            "Test headline", "realized", "medium", "thin mechanism",
        )
        self.assertTrue(out["degraded"])
        self.assertEqual(out["confidence"], "low")

    def test_degraded_clears_rich_sections(self):
        out = _degraded_fallback("headline", "realized", "medium", "x")
        self.assertEqual(out["if_persists"], {})
        self.assertEqual(out["currency_channel"], {})
        self.assertEqual(out["transmission_chain"], [])
        self.assertEqual(out["beneficiaries"], [])
        self.assertEqual(out["losers"], [])

    def test_degraded_preserves_tickers_when_supplied(self):
        out = _degraded_fallback(
            "headline", "realized", "medium", "x",
            preserved_tickers=["SMH", "TSM"],
        )
        self.assertEqual(out["beneficiary_tickers"], ["SMH", "TSM"])
        self.assertEqual(out["assets_to_watch"], ["SMH", "TSM"])

    def test_degraded_is_not_flagged_as_mock(self):
        """Degraded output is still a real LLM result, not a mock."""
        from analyze_event import is_mock
        out = _degraded_fallback("headline", "realized", "medium", "x")
        self.assertFalse(is_mock(out))

    def test_degraded_surfaces_validation_warning(self):
        out = _degraded_fallback("headline", "realized", "medium", "reason X")
        self.assertIn("validation_warnings", out)
        self.assertTrue(any("degraded" in w for w in out["validation_warnings"]))


# ---------------------------------------------------------------------------
# Contradiction-aware validation
# ---------------------------------------------------------------------------

def _rich_result(**overrides) -> dict:
    base = {
        "what_changed": "The US Treasury granted Chevron a 6-month licence.",
        "mechanism_summary": (
            "Venezuelan extra-heavy crude is a refinery-specific feedstock; "
            "restoring Chevron lowers Gulf Coast refiner input costs while "
            "displacing Canadian WCS barrels."
        ),
        "beneficiaries": ["Chevron", "US Gulf Coast refiners"],
        "losers": ["Canadian oil-sands producers"],
        "beneficiary_tickers": ["CVX", "VLO"],
        "loser_tickers": ["SU"],
        "transmission_chain": [
            "US Treasury grants licence",
            "Heavy sour crude resumes to Gulf Coast",
            "Refiner feedstock cost drops",
            "Chevron benefits; Canadian WCS loses outlet",
        ],
        "if_persists": {"horizon": "months"},
        "currency_channel": {},
        "confidence": "high",
    }
    base.update(overrides)
    return base


class TestContradictionValidation(unittest.TestCase):

    def test_high_confidence_with_empty_loser_tickers_downgraded(self):
        result = _rich_result(loser_tickers=[])
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "medium")
        self.assertTrue(any(
            "loser tickers" in w for w in out.get("validation_warnings", [])
        ))

    def test_high_confidence_with_empty_beneficiary_tickers_downgraded(self):
        result = _rich_result(beneficiary_tickers=[])
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "medium")

    def test_insufficient_evidence_forces_low(self):
        result = _rich_result(
            mechanism_summary="Insufficient evidence to identify mechanism.",
            confidence="high",
        )
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "low")
        self.assertTrue(any(
            "insufficient evidence" in w.lower()
            for w in out.get("validation_warnings", [])
        ))

    def test_short_chain_with_high_confidence_downgraded(self):
        result = _rich_result(
            transmission_chain=["only one step"],
        )
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "medium")
        self.assertTrue(any(
            "transmission chain" in w
            for w in out.get("validation_warnings", [])
        ))

    def test_thin_mechanism_clears_rich_if_persists(self):
        result = _rich_result(
            mechanism_summary="too short",
            if_persists={"horizon": "months", "substitution": "alt supply"},
            currency_channel={"pair": "DXY", "mechanism": "x" * 30},
            confidence="medium",
        )
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["if_persists"], {})
        self.assertEqual(out["currency_channel"], {})

    def test_empty_entities_with_high_confidence_downgraded(self):
        result = _rich_result(beneficiaries=[], losers=[])
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "medium")

    def test_anticipation_high_still_downgraded(self):
        result = _rich_result(confidence="high")
        out = _validate_result(result, stage="anticipation")
        self.assertEqual(out["confidence"], "medium")

    def test_clean_high_confidence_survives(self):
        result = _rich_result()
        out = _validate_result(result, stage="realized")
        self.assertEqual(out["confidence"], "high")
        self.assertNotIn("validation_warnings", out)


# ---------------------------------------------------------------------------
# Schema normalization (end-to-end on a raw LLM dict)
# ---------------------------------------------------------------------------

class TestNormalizeSchema(unittest.TestCase):

    def test_null_like_strings_cleaned(self):
        raw = {
            "what_changed": "null",
            "mechanism_summary": "N/A",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
            "confidence": "unknown",
            "if_persists": {},
            "currency_channel": {},
        }
        out = _normalize_schema(raw, headline="headline")
        self.assertEqual(out["what_changed"], "")
        self.assertEqual(out["mechanism_summary"], "")
        self.assertEqual(out["confidence"], "low")

    def test_malformed_sections_fail_soft(self):
        raw = {
            "what_changed": "Something real happened.",
            "mechanism_summary": "A real mechanism long enough to pass the floor.",
            "beneficiaries": "not a list",
            "losers": 42,
            "transmission_chain": "step1, step2",
            "if_persists": "should be dict",
            "currency_channel": [1, 2, 3],
            "confidence": "medium",
        }
        out = _normalize_schema(raw, headline="headline")
        self.assertEqual(out["beneficiaries"], [])
        self.assertEqual(out["losers"], [])
        self.assertEqual(out["transmission_chain"], [])
        self.assertEqual(out["if_persists"], {})
        self.assertEqual(out["currency_channel"], {})

    def test_vague_entities_dropped(self):
        raw = {
            "what_changed": "Something real.",
            "mechanism_summary": "A real mechanism that is long enough here.",
            "beneficiaries": ["TSMC", "various companies", "ASML"],
            "losers": ["the market", "LRCX", "unknown"],
            "transmission_chain": [],
            "confidence": "medium",
        }
        out = _normalize_schema(raw, headline="h")
        self.assertEqual(out["beneficiaries"], ["TSMC", "ASML"])
        self.assertEqual(out["losers"], ["LRCX"])

    def test_raw_ticker_fields_coerced(self):
        raw = {
            "what_changed": "x",
            "mechanism_summary": "y",
            "beneficiary_tickers": "TSM",      # bare string
            "loser_tickers": ["LRCX", 42, {"sym": "AMAT"}, "AMAT"],
        }
        out = _normalize_schema(raw, headline="h")
        self.assertEqual(out["_raw_beneficiary_tickers"], ["TSM"])
        self.assertEqual(out["_raw_loser_tickers"], ["LRCX", "AMAT"])


# ---------------------------------------------------------------------------
# End-to-end _finalize_analysis pipeline
# ---------------------------------------------------------------------------

class TestFinalizeAnalysis(unittest.TestCase):

    def _headline(self) -> str:
        return (
            "US Commerce adds Chinese semiconductor firms to export control list"
        )

    def _good_parsed(self) -> dict:
        return {
            "what_changed": (
                "The US Commerce Department added 28 Chinese semiconductor firms "
                "to the Entity List."
            ),
            "mechanism_summary": (
                "Chinese fabs lose access to ASML EUV lithography, Lam Research "
                "etch systems, and Applied Materials deposition equipment. US "
                "and allied equipment makers lose China revenue near term but "
                "benefit from accelerated TSMC/Samsung/Intel re-investment."
            ),
            "beneficiaries": ["TSMC", "ASML", "Samsung Foundry"],
            "losers": ["Chinese DRAM foundries", "Lam Research", "Applied Materials"],
            "beneficiary_tickers": ["TSM", "ASML", "SMH"],
            "loser_tickers": ["LRCX", "AMAT"],
            "transmission_chain": [
                "Entity List expanded",
                "Equipment access cut",
                "Chinese fab expansion stalls",
                "TSMC/ASML gain; LRCX/AMAT lose China revenue",
            ],
            "if_persists": {
                "substitution": "Chinese fabs accelerate indigenous DUV lines.",
                "horizon": "quarters",
            },
            "currency_channel": {
                "pair": "USD/KRW",
                "mechanism": (
                    "Korean chip exports gain pricing power, modestly supporting "
                    "the won on a trade-balance basis."
                ),
            },
            "confidence": "high",
        }

    def test_good_parsed_passes_through_unchanged(self):
        out = _finalize_analysis(
            self._good_parsed(), self._headline(), "realized", "structural",
        )
        self.assertEqual(out["confidence"], "high")
        self.assertIn("TSM", out["beneficiary_tickers"])
        self.assertIn("LRCX", out["loser_tickers"])
        self.assertEqual(out["if_persists"]["horizon"], "quarters")
        self.assertNotIn("degraded", out)

    def test_weak_parsed_triggers_degraded_fallback(self):
        parsed = {
            "what_changed": "x",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "transmission_chain": [],
            "confidence": "high",
        }
        out = _finalize_analysis(
            parsed, "China launches space module", "realized", "structural",
        )
        self.assertTrue(out.get("degraded"))
        self.assertEqual(out["confidence"], "low")
        self.assertEqual(out["if_persists"], {})

    def test_overlap_removed_from_loser_side(self):
        parsed = self._good_parsed()
        parsed["loser_tickers"] = ["TSM", "LRCX"]  # TSM overlaps beneficiary
        out = _finalize_analysis(
            parsed, self._headline(), "realized", "structural",
        )
        self.assertIn("TSM", out["beneficiary_tickers"])
        self.assertNotIn("TSM", out["loser_tickers"])
        self.assertIn("LRCX", out["loser_tickers"])

    def test_anticipation_downgrades_high_confidence(self):
        parsed = self._good_parsed()
        out = _finalize_analysis(
            parsed, self._headline(), "anticipation", "structural",
        )
        self.assertEqual(out["confidence"], "medium")

    def test_empty_loser_tickers_trigger_inverse_proxy(self):
        parsed = self._good_parsed()
        parsed["loser_tickers"] = []  # force empty → proxy map runs
        # Use a headline with a semiconductor theme so the loser proxy matches
        out = _finalize_analysis(
            parsed,
            "Semiconductor chip foundry TSMC fab export restriction",
            "realized", "structural",
        )
        self.assertTrue(any("(proxy)" in t for t in out["loser_tickers"]))

    def test_messy_json_then_finalize_stays_stable(self):
        """A parsed dict from a messy model response should normalize cleanly."""
        text = (
            "Analysis draft (ignore): {\"what_changed\": \"draft\"}\n"
            "Final answer: " + (
                '{"what_changed": "The US Commerce Department added 28 firms.", '
                '"mechanism_summary": "Chinese fabs lose access to EUV lithography '
                'and etch tools, forcing inferior domestic alternatives and shifting '
                'pricing power to non-Chinese foundries.", '
                '"beneficiaries": ["TSMC", "Samsung"], '
                '"losers": ["CXMT", "Lam Research"], '
                '"beneficiary_tickers": ["TSM", "SMH"], '
                '"loser_tickers": ["LRCX", "AMAT"], '
                '"transmission_chain": ["Entity list", "access cut", "repricing", "winners/losers"], '
                '"if_persists": {"horizon": "quarters"}, '
                '"currency_channel": {}, '
                '"confidence": "medium"}'
            )
        )
        parsed = _extract_json(text)
        self.assertIsNotNone(parsed)
        out = _finalize_analysis(
            parsed, "chip export controls", "realized", "structural",
        )
        # Must have normalized away the draft
        self.assertNotEqual(out["what_changed"], "draft")
        self.assertIn("TSM", out["beneficiary_tickers"])
        # CXMT is a known-bad ticker; LRCX/AMAT are clean
        self.assertIn("LRCX", out["loser_tickers"])


# ---------------------------------------------------------------------------
# Degraded vs mock detection
# ---------------------------------------------------------------------------

class TestDegradedVsMock(unittest.TestCase):

    def test_mock_flagged_as_mock(self):
        from analyze_event import is_mock, _mock
        self.assertTrue(is_mock(_mock("no API key")))

    def test_degraded_not_flagged_as_mock(self):
        from analyze_event import is_mock
        out = _degraded_fallback("h", "realized", "medium", "x")
        self.assertFalse(is_mock(out))

    def test_degraded_field_only_present_when_true(self):
        """Normal analyses should not carry a 'degraded' key at all."""
        parsed = {
            "what_changed": "The US Commerce Department added firms to Entity List.",
            "mechanism_summary": (
                "Chinese fabs lose access to EUV lithography equipment and "
                "depend on inferior domestic alternatives."
            ),
            "beneficiaries": ["TSMC"],
            "losers": ["Chinese DRAM foundries"],
            "beneficiary_tickers": ["TSM"],
            "loser_tickers": ["LRCX"],
            "transmission_chain": [
                "Entity list expanded",
                "Access cut",
                "Pricing power shifts",
                "Winners and losers",
            ],
            "confidence": "medium",
        }
        out = _finalize_analysis(parsed, "chip export", "realized", "structural")
        self.assertNotIn("degraded", out)


if __name__ == "__main__":
    unittest.main()
