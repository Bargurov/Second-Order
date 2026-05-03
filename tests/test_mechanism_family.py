"""
tests/test_mechanism_family.py

Validates the mechanism-family taxonomy + keyword-based classifier,
the cleaner + fallback wiring in analyze_event._normalize_schema, and
the DB round-trip for the four new persisted fields.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mechanism_family import (  # noqa: E402
    FAMILY_IDS,
    FAMILY_LABELS,
    FAMILY_CHANNEL_PACKS,
    CHANNEL_IDS as FAMILY_CHANNEL_IDS,
    get_default_channel_pack,
    classify_family,
)
from analyze_event import (  # noqa: E402
    _clean_mechanism_family,
    _clean_channel_list,
    _clean_regime_caveat,
    _resolve_mechanism_family,
    _resolve_channel_packs,
    _normalize_schema,
    _mock,
    _MECH_CHANNEL_ENUM,
    LLM_CORE_FIELDS,
    _LLM_CORE_DEFAULTS,
    build_analysis_dict,
)


# ---------------------------------------------------------------------------
# Taxonomy shape contracts
# ---------------------------------------------------------------------------

class TestTaxonomyShape(unittest.TestCase):

    def test_every_family_has_label(self):
        for fam in FAMILY_IDS:
            self.assertIn(fam, FAMILY_LABELS, f"missing label: {fam}")

    def test_every_family_has_channel_pack(self):
        for fam in FAMILY_IDS:
            self.assertIn(fam, FAMILY_CHANNEL_PACKS)
            pack = FAMILY_CHANNEL_PACKS[fam]
            self.assertIn("first", pack)
            self.assertIn("second", pack)

    def test_channel_pack_values_are_canonical_channels(self):
        for fam, pack in FAMILY_CHANNEL_PACKS.items():
            for key in ("first", "second"):
                for ch in pack[key]:
                    self.assertIn(
                        ch, FAMILY_CHANNEL_IDS,
                        f"{fam}.{key}: unknown channel {ch}",
                    )

    def test_none_family_has_empty_pack(self):
        self.assertEqual(FAMILY_CHANNEL_PACKS["none"]["first"], [])
        self.assertEqual(FAMILY_CHANNEL_PACKS["none"]["second"], [])

    def test_get_default_channel_pack_returns_copy(self):
        pack = get_default_channel_pack("tariff")
        pack["first"].append("NEW")
        # Canonical pack is not mutated.
        self.assertNotIn("NEW", FAMILY_CHANNEL_PACKS["tariff"]["first"])


# ---------------------------------------------------------------------------
# Keyword-based classifier
# ---------------------------------------------------------------------------

class TestKeywordClassifier(unittest.TestCase):

    def test_tariff_detected(self):
        self.assertEqual(
            classify_family("US imposes 25% tariff on Chinese EVs", ""),
            "tariff",
        )

    def test_sanction_detected(self):
        self.assertEqual(
            classify_family("Treasury adds 28 firms to entity list", ""),
            "sanction",
        )

    def test_policy_surprise_detected(self):
        self.assertEqual(
            classify_family("", "Fed delivers jumbo cut at FOMC"),
            "policy_surprise",
        )

    def test_bank_stress_beats_rate_keywords(self):
        # "discount window" should trigger bank_stress before "rate"-adjacent noise
        self.assertEqual(
            classify_family("Fed opens discount window for regional banks", ""),
            "bank_stress",
        )

    def test_ceasefire_beats_commodity(self):
        # Ceasefire is listed first → should win over commodity keywords.
        self.assertEqual(
            classify_family(
                "Ceasefire announced; oil production resumes in Libya", "",
            ),
            "ceasefire_deescalation",
        )

    def test_fiscal_issuance_detected(self):
        self.assertEqual(
            classify_family("Treasury announces quarterly refunding", ""),
            "fiscal_issuance",
        )

    def test_labor_inflation_detected(self):
        self.assertEqual(
            classify_family("Jobs report shows 5.1% wage growth", ""),
            "labor_inflation",
        )

    def test_commodity_squeeze_detected(self):
        self.assertEqual(
            classify_family("OPEC announces 2mbd production cut", ""),
            "commodity_squeeze",
        )

    def test_supply_normalization_detected(self):
        self.assertEqual(
            classify_family("Oil pipeline restart after maintenance", ""),
            "supply_normalization",
        )

    def test_generic_headline_returns_none(self):
        self.assertEqual(classify_family("Company reports earnings", ""), "none")

    def test_empty_input_returns_none(self):
        self.assertEqual(classify_family(None, None), "none")
        self.assertEqual(classify_family("", ""), "none")


# ---------------------------------------------------------------------------
# Family cleaner
# ---------------------------------------------------------------------------

class TestFamilyCleaner(unittest.TestCase):

    def test_valid_family_passes(self):
        self.assertEqual(_clean_mechanism_family("tariff"), "tariff")

    def test_case_insensitive(self):
        self.assertEqual(_clean_mechanism_family("TARIFF"), "tariff")
        self.assertEqual(_clean_mechanism_family("Tariff."), "tariff")

    def test_compound_first_wins(self):
        self.assertEqual(_clean_mechanism_family("tariff/sanction"), "tariff")
        self.assertEqual(_clean_mechanism_family("bank_stress, policy_surprise"),
                         "bank_stress")

    def test_unknown_family_returns_none(self):
        self.assertEqual(_clean_mechanism_family("vibes"), "none")

    def test_null_like_returns_none(self):
        for v in (None, "", "   ", "null", "None", "n/a", 42, [], {}):
            self.assertEqual(_clean_mechanism_family(v), "none")


# ---------------------------------------------------------------------------
# Channel list cleaner
# ---------------------------------------------------------------------------

class TestChannelListCleaner(unittest.TestCase):

    def test_valid_channels_preserved(self):
        self.assertEqual(
            _clean_channel_list(["rates", "fx", "equities"]),
            ["rates", "fx", "equities"],
        )

    def test_unknown_channels_dropped(self):
        self.assertEqual(
            _clean_channel_list(["rates", "vibes", "fx", "moonbase"]),
            ["rates", "fx"],
        )

    def test_dedupes(self):
        self.assertEqual(
            _clean_channel_list(["rates", "RATES", "fx", "rates"]),
            ["rates", "fx"],
        )

    def test_cap_default_four(self):
        out = _clean_channel_list(list(FAMILY_CHANNEL_IDS) + ["rates", "fx"])
        self.assertLessEqual(len(out), 4)

    def test_non_list_returns_empty(self):
        self.assertEqual(_clean_channel_list(None), [])
        self.assertEqual(_clean_channel_list("rates,fx"), [])

    def test_all_six_canonical_channels_valid(self):
        for ch in FAMILY_CHANNEL_IDS:
            self.assertIn(ch, _MECH_CHANNEL_ENUM)


# ---------------------------------------------------------------------------
# Regime caveat cleaner
# ---------------------------------------------------------------------------

class TestRegimeCaveatCleaner(unittest.TestCase):

    def test_real_caveat_preserved(self):
        text = "In a hawkish regime the repricing lands faster."
        self.assertEqual(_clean_regime_caveat(text), text)

    def test_placeholder_preserved(self):
        # The canonical placeholder is NOT null-like; it passes through.
        p = "No regime-conditioned caveat."
        self.assertEqual(_clean_regime_caveat(p), p)

    def test_null_like_collapses_to_empty(self):
        for v in ("null", "None", "n/a", "", "  "):
            self.assertEqual(_clean_regime_caveat(v), "")

    def test_non_string_returns_empty(self):
        self.assertEqual(_clean_regime_caveat(None), "")
        self.assertEqual(_clean_regime_caveat(42), "")


# ---------------------------------------------------------------------------
# _resolve_mechanism_family — LLM preferred, keyword fallback
# ---------------------------------------------------------------------------

class TestResolveFamily(unittest.TestCase):

    def test_llm_valid_family_preserved(self):
        out = _resolve_mechanism_family(
            "tariff", "random headline", "random mechanism",
        )
        self.assertEqual(out, "tariff")

    def test_llm_none_falls_back_to_keyword(self):
        out = _resolve_mechanism_family(
            "none",
            "US imposes tariff on steel imports",
            "supply chain reprice",
        )
        self.assertEqual(out, "tariff")

    def test_llm_null_falls_back_to_keyword(self):
        out = _resolve_mechanism_family(
            None, "OPEC announces production cut", "",
        )
        self.assertEqual(out, "commodity_squeeze")

    def test_llm_invalid_falls_back_to_keyword(self):
        out = _resolve_mechanism_family(
            "vibes", "Treasury sanctions tankers", "",
        )
        self.assertEqual(out, "sanction")

    def test_both_empty_returns_none(self):
        self.assertEqual(
            _resolve_mechanism_family(None, "random", "random"),
            "none",
        )


# ---------------------------------------------------------------------------
# _resolve_channel_packs — fallback to canonical
# ---------------------------------------------------------------------------

class TestResolveChannelPacks(unittest.TestCase):

    def test_llm_commits_both_sides_preserved(self):
        first, second = _resolve_channel_packs(
            "tariff",
            ["commodities", "fx"],
            ["rates"],
        )
        self.assertEqual(first, ["commodities", "fx"])
        self.assertEqual(second, ["rates"])

    def test_both_empty_falls_back_to_canonical(self):
        first, second = _resolve_channel_packs("tariff", [], [])
        canonical = FAMILY_CHANNEL_PACKS["tariff"]
        self.assertEqual(first, canonical["first"])
        self.assertEqual(second, canonical["second"])

    def test_partial_commit_fills_empty_side(self):
        # LLM only commits first-order → second falls back to canonical.
        first, second = _resolve_channel_packs(
            "bank_stress",
            ["credit"], None,
        )
        self.assertEqual(first, ["credit"])
        self.assertEqual(second, FAMILY_CHANNEL_PACKS["bank_stress"]["second"])

    def test_second_dedupes_against_first(self):
        # If LLM puts same channel in both, second should drop it.
        first, second = _resolve_channel_packs(
            "sanction",
            ["commodities", "fx"],
            ["commodities", "credit"],
        )
        self.assertIn("commodities", first)
        self.assertNotIn("commodities", second)
        self.assertIn("credit", second)


# ---------------------------------------------------------------------------
# Schema + registry wiring
# ---------------------------------------------------------------------------

class TestSchemaWiring(unittest.TestCase):

    def test_fields_registered_in_llm_core(self):
        for name in (
            "mechanism_family", "expected_first_order_channels",
            "expected_second_order_channels", "regime_conditioned_caveat",
        ):
            self.assertIn(name, LLM_CORE_FIELDS)

    def test_defaults(self):
        self.assertEqual(_LLM_CORE_DEFAULTS["mechanism_family"], "none")
        self.assertEqual(_LLM_CORE_DEFAULTS["expected_first_order_channels"], [])
        self.assertEqual(_LLM_CORE_DEFAULTS["expected_second_order_channels"], [])
        self.assertEqual(_LLM_CORE_DEFAULTS["regime_conditioned_caveat"], "")

    def test_build_analysis_dict_populates_defaults(self):
        result = build_analysis_dict({}, {})
        self.assertEqual(result["mechanism_family"], "none")
        self.assertEqual(result["expected_first_order_channels"], [])
        self.assertEqual(result["expected_second_order_channels"], [])
        self.assertEqual(result["regime_conditioned_caveat"], "")

    def test_normalize_schema_llm_commits_preserved(self):
        raw = {
            "what_changed": "x",
            "mechanism_summary": "y",
            "mechanism_family": "tariff",
            "expected_first_order_channels": ["commodities", "equities"],
            "expected_second_order_channels": ["rates"],
            "regime_conditioned_caveat": "Hawkish regime amplifies the hit.",
        }
        result = _normalize_schema(raw, headline="US imposes tariff")
        self.assertEqual(result["mechanism_family"], "tariff")
        self.assertEqual(result["expected_first_order_channels"],
                         ["commodities", "equities"])
        self.assertEqual(result["expected_second_order_channels"], ["rates"])
        self.assertEqual(result["regime_conditioned_caveat"],
                         "Hawkish regime amplifies the hit.")

    def test_normalize_schema_keyword_fallback_fills_family(self):
        raw = {
            "what_changed": "x",
            "mechanism_summary": "OPEC production cut raises crude",
            # LLM omitted the family entirely.
        }
        result = _normalize_schema(raw, headline="OPEC cuts 2mbd")
        self.assertEqual(result["mechanism_family"], "commodity_squeeze")
        # First-order falls back to the canonical commodity_squeeze pack.
        canonical = FAMILY_CHANNEL_PACKS["commodity_squeeze"]
        self.assertEqual(result["expected_first_order_channels"],
                         canonical["first"])

    def test_mock_carries_new_fields(self):
        m = _mock("reason")
        self.assertEqual(m["mechanism_family"], "none")
        self.assertEqual(m["expected_first_order_channels"], [])
        self.assertEqual(m["expected_second_order_channels"], [])
        self.assertEqual(m["regime_conditioned_caveat"], "")


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------

class TestDBRoundTrip(unittest.TestCase):

    def setUp(self):
        import db
        self.tmp = tempfile.NamedTemporaryFile(
            prefix="test_family_", suffix=".db", delete=False,
        )
        self.tmp.close()
        self._orig = db.DB_FILE
        db.DB_FILE = self.tmp.name
        self.db = db
        self.db.init_db()

    def tearDown(self):
        self.db.DB_FILE = self._orig
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _event(self) -> dict:
        return {
            "headline": "Mechanism family round-trip",
            "stage": "realized",
            "persistence": "medium",
            "what_changed": "x", "mechanism_summary": "y",
            "beneficiaries": [], "losers": [],
            "beneficiary_tickers": [], "loser_tickers": [],
            "assets_to_watch": [],
            "confidence": "medium",
            "market_note": "", "market_tickers": [],
            "event_date": "2026-04-18",
            "model": "test-model",
            "transmission_chain": [], "transmission_path": [],
            "substitution_barriers": [], "counterforces": [],
            "adversarial_challenge": "",
            "horizon_checkpoints": {},
            "if_persists": {}, "currency_channel": {},
            "policy_sensitivity": {}, "inventory_context": {},
            "regime_snapshot": {},
            "real_yield_context": {}, "policy_constraint": {},
            "shock_decomposition": {}, "reaction_function_divergence": {},
            "surprise_vs_anticipation": {}, "terms_of_trade": {},
            "reserve_stress": {}, "narrative_divergence": {},
            "credit_regime": {}, "credit_transmission": {},
            "mechanism_family": "sanction",
            "expected_first_order_channels": ["equities", "fx"],
            "expected_second_order_channels": ["credit"],
            "regime_conditioned_caveat": "Hawkish regime amplifies.",
        }

    def test_round_trip_preserves_all_four_fields(self):
        ev = self._event()
        self.db.save_event(ev)
        events = self.db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        saved = events[0]
        self.assertEqual(saved["mechanism_family"], "sanction")
        self.assertEqual(saved["expected_first_order_channels"], ["equities", "fx"])
        self.assertEqual(saved["expected_second_order_channels"], ["credit"])
        self.assertEqual(saved["regime_conditioned_caveat"],
                         "Hawkish regime amplifies.")

    def test_default_values_decode_cleanly(self):
        ev = self._event()
        ev["mechanism_family"] = "none"
        ev["expected_first_order_channels"] = []
        ev["expected_second_order_channels"] = []
        ev["regime_conditioned_caveat"] = ""
        self.db.save_event(ev)
        events = self.db.load_recent_events(limit=10)
        saved = events[0]
        self.assertEqual(saved["mechanism_family"], "none")
        self.assertEqual(saved["expected_first_order_channels"], [])
        self.assertEqual(saved["expected_second_order_channels"], [])
        self.assertEqual(saved["regime_conditioned_caveat"], "")


if __name__ == "__main__":
    unittest.main()
