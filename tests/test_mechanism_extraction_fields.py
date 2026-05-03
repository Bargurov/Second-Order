"""
tests/test_mechanism_extraction_fields.py

Validates the new deep-mechanism fields:
  - transmission_path     (list of {hop, channel, actor} dicts)
  - substitution_barriers (list of {barrier, kind, severity} dicts)
  - counterforces         (list of {force, actor, likelihood} dicts)
  - adversarial_challenge (string)

Covers:
  - cleaner behaviour for strict dict, string fallback, filler dropping
  - enum normalization (channel, kind, severity, likelihood)
  - list caps
  - build_analysis_dict flow: defaults, overrides
  - _mock and degraded templates carry the new fields
  - DB save + decode round-trip preserves shape
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze_event import (  # noqa: E402
    _clean_transmission_path,
    _clean_substitution_barriers,
    _clean_counterforces,
    _clean_adversarial_challenge,
    _normalize_schema,
    _mock,
    build_analysis_dict,
    LLM_CORE_FIELDS,
    _LLM_CORE_DEFAULTS,
    _TRANSMISSION_CHANNELS,
    _SUBSTITUTION_BARRIER_KINDS,
)


# ---------------------------------------------------------------------------
# transmission_path cleaner
# ---------------------------------------------------------------------------

class TestTransmissionPathCleaner(unittest.TestCase):

    def test_strict_dict_passes_through(self):
        raw = [
            {"hop": "Fed hikes 25bps", "channel": "rate_transmission", "actor": "FOMC"},
            {"hop": "2Y yield rises 20bps", "channel": "pricing_power", "actor": "Treasury market"},
        ]
        out = _clean_transmission_path(raw)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["hop"], "Fed hikes 25bps")
        self.assertEqual(out[0]["channel"], "rate_transmission")
        self.assertEqual(out[0]["actor"], "FOMC")

    def test_string_lift_for_legacy_output(self):
        # Model returns a plain string step → lift into the dict shape
        raw = ["Step 1: Fed hikes 25bps"]
        out = _clean_transmission_path(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hop"], "Step 1: Fed hikes 25bps")
        self.assertEqual(out[0]["channel"], "unclassified")
        self.assertEqual(out[0]["actor"], "")

    def test_unknown_channel_falls_back_to_unclassified(self):
        raw = [{"hop": "x", "channel": "quantum_spooky_action", "actor": "nature"}]
        out = _clean_transmission_path(raw)
        self.assertEqual(out[0]["channel"], "unclassified")

    def test_all_known_channels_accepted(self):
        for ch in _TRANSMISSION_CHANNELS:
            out = _clean_transmission_path([{"hop": "x", "channel": ch, "actor": "a"}])
            self.assertEqual(out[0]["channel"], ch)

    def test_drops_empty_hop(self):
        raw = [{"hop": "", "channel": "supply", "actor": "x"},
               {"hop": "   ", "channel": "supply", "actor": "x"},
               {"hop": "real hop", "channel": "supply", "actor": "y"}]
        out = _clean_transmission_path(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hop"], "real hop")

    def test_drops_null_like_strings(self):
        raw = ["null", "None", "n/a", "a real hop"]
        out = _clean_transmission_path(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["hop"], "a real hop")

    def test_cap_at_six_entries(self):
        raw = [{"hop": f"h{i}", "channel": "supply", "actor": "a"} for i in range(10)]
        out = _clean_transmission_path(raw)
        self.assertEqual(len(out), 6)

    def test_non_list_returns_empty(self):
        self.assertEqual(_clean_transmission_path(None), [])
        self.assertEqual(_clean_transmission_path("not a list"), [])
        self.assertEqual(_clean_transmission_path({}), [])


# ---------------------------------------------------------------------------
# substitution_barriers cleaner
# ---------------------------------------------------------------------------

class TestSubstitutionBarriersCleaner(unittest.TestCase):

    def test_strict_dict_passes_through(self):
        raw = [{"barrier": "EUV sole-sourced from ASML",
                "kind": "physical_sole_source", "severity": "high"}]
        out = _clean_substitution_barriers(raw)
        self.assertEqual(out, [{
            "barrier": "EUV sole-sourced from ASML",
            "kind": "physical_sole_source",
            "severity": "high",
        }])

    def test_all_known_kinds_accepted(self):
        for kind in _SUBSTITUTION_BARRIER_KINDS:
            out = _clean_substitution_barriers([
                {"barrier": "b", "kind": kind, "severity": "medium"}
            ])
            self.assertEqual(out[0]["kind"], kind)

    def test_unknown_kind_falls_back(self):
        out = _clean_substitution_barriers([
            {"barrier": "b", "kind": "vibes", "severity": "high"}
        ])
        self.assertEqual(out[0]["kind"], "unclassified")

    def test_severity_enum_normalized(self):
        # Extra punctuation / case / compound form all reduce cleanly.
        cases = [
            ("High", "high"),
            ("LOW", "low"),
            ("medium.", "medium"),
            ("low-medium", "low"),
            ("garbage", "medium"),   # default
        ]
        for given, expected in cases:
            out = _clean_substitution_barriers([
                {"barrier": "b", "kind": "regulatory", "severity": given}
            ])
            self.assertEqual(out[0]["severity"], expected, f"given={given!r}")

    def test_string_lift(self):
        out = _clean_substitution_barriers(["ASML is sole-source for EUV"])
        self.assertEqual(out[0]["barrier"], "ASML is sole-source for EUV")
        self.assertEqual(out[0]["severity"], "medium")

    def test_cap_at_five_entries(self):
        raw = [{"barrier": f"b{i}", "kind": "regulatory"} for i in range(10)]
        out = _clean_substitution_barriers(raw)
        self.assertEqual(len(out), 5)


# ---------------------------------------------------------------------------
# counterforces cleaner
# ---------------------------------------------------------------------------

class TestCounterforcesCleaner(unittest.TestCase):

    def test_strict_dict_passes_through(self):
        raw = [{"force": "Congress repeals sanction",
                "actor": "US Congress", "likelihood": "low"}]
        out = _clean_counterforces(raw)
        self.assertEqual(out, [{
            "force": "Congress repeals sanction",
            "actor": "US Congress",
            "likelihood": "low",
        }])

    def test_likelihood_enum_normalized(self):
        out = _clean_counterforces([
            {"force": "f", "actor": "a", "likelihood": "HIGH!"},
        ])
        self.assertEqual(out[0]["likelihood"], "high")

    def test_missing_actor_defaults_empty(self):
        out = _clean_counterforces([
            {"force": "PRC subsidizes domestic fabs", "likelihood": "medium"}
        ])
        self.assertEqual(out[0]["actor"], "")

    def test_drops_empty_force(self):
        raw = [{"force": "", "actor": "x"}, {"force": "valid", "actor": "y"}]
        out = _clean_counterforces(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["force"], "valid")


# ---------------------------------------------------------------------------
# adversarial_challenge cleaner
# ---------------------------------------------------------------------------

class TestAdversarialChallengeCleaner(unittest.TestCase):

    def test_plain_string_preserved(self):
        text = ("The thesis may already be priced — SMH has rallied "
                "on prior rounds of export restrictions.")
        self.assertEqual(_clean_adversarial_challenge(text), text)

    def test_placeholder_passes_through(self):
        placeholder = "No credible challenge identified."
        out = _clean_adversarial_challenge(placeholder)
        self.assertEqual(out, placeholder)

    def test_null_like_collapses_to_empty(self):
        for v in ("null", "None", "n/a", "   ", ""):
            self.assertEqual(_clean_adversarial_challenge(v), "")

    def test_non_string_returns_empty(self):
        self.assertEqual(_clean_adversarial_challenge(None), "")
        self.assertEqual(_clean_adversarial_challenge(42), "")
        self.assertEqual(_clean_adversarial_challenge(["list"]), "")


# ---------------------------------------------------------------------------
# Schema registration + flow through build_analysis_dict
# ---------------------------------------------------------------------------

class TestSchemaRegistration(unittest.TestCase):

    def test_new_fields_in_llm_core_fields(self):
        for name in (
            "transmission_path", "substitution_barriers",
            "counterforces", "adversarial_challenge",
        ):
            self.assertIn(name, LLM_CORE_FIELDS, f"missing: {name}")

    def test_default_shapes(self):
        self.assertEqual(_LLM_CORE_DEFAULTS["transmission_path"], [])
        self.assertEqual(_LLM_CORE_DEFAULTS["substitution_barriers"], [])
        self.assertEqual(_LLM_CORE_DEFAULTS["counterforces"], [])
        self.assertEqual(_LLM_CORE_DEFAULTS["adversarial_challenge"], "")

    def test_build_analysis_dict_populates_defaults(self):
        result = build_analysis_dict({}, {})
        for name in ("transmission_path", "substitution_barriers",
                     "counterforces"):
            self.assertEqual(result[name], [])
        self.assertEqual(result["adversarial_challenge"], "")

    def test_build_analysis_dict_respects_source(self):
        src = {
            "transmission_path": [{"hop": "x", "channel": "supply", "actor": "a"}],
            "adversarial_challenge": "thesis may be priced",
        }
        result = build_analysis_dict(src, {})
        self.assertEqual(len(result["transmission_path"]), 1)
        self.assertEqual(result["adversarial_challenge"], "thesis may be priced")


class TestSchemaNormalization(unittest.TestCase):

    def test_normalize_schema_emits_all_new_fields(self):
        raw = {
            "what_changed": "x",
            "mechanism_summary": "y",
            "transmission_path": [{"hop": "h1", "channel": "supply", "actor": "a"}],
            "substitution_barriers": [{"barrier": "b1", "kind": "regulatory",
                                        "severity": "high"}],
            "counterforces": [{"force": "f1", "actor": "a1", "likelihood": "low"}],
            "adversarial_challenge": "counter-thesis text",
        }
        result = _normalize_schema(raw, headline="test")
        self.assertEqual(result["transmission_path"][0]["hop"], "h1")
        self.assertEqual(result["substitution_barriers"][0]["severity"], "high")
        self.assertEqual(result["counterforces"][0]["likelihood"], "low")
        self.assertEqual(result["adversarial_challenge"], "counter-thesis text")

    def test_normalize_schema_degrades_on_missing_fields(self):
        # Missing fields → cleaners return empty containers / "".
        result = _normalize_schema({"what_changed": "x"}, headline="test")
        self.assertEqual(result["transmission_path"], [])
        self.assertEqual(result["substitution_barriers"], [])
        self.assertEqual(result["counterforces"], [])
        self.assertEqual(result["adversarial_challenge"], "")


class TestMockAndTemplates(unittest.TestCase):

    def test_mock_carries_new_fields(self):
        m = _mock("reason")
        for name in ("transmission_path", "substitution_barriers",
                     "counterforces"):
            self.assertIn(name, m)
            self.assertEqual(m[name], [])
        self.assertEqual(m["adversarial_challenge"], "")


# ---------------------------------------------------------------------------
# DB round-trip
# ---------------------------------------------------------------------------

class TestDBRoundTrip(unittest.TestCase):

    def setUp(self):
        # Isolated temp DB path so we don't touch the shared one.
        import db
        self.tmp = tempfile.NamedTemporaryFile(
            prefix="test_mech_", suffix=".db", delete=False,
        )
        self.tmp.close()
        self._orig_db_file = db.DB_FILE
        db.DB_FILE = self.tmp.name
        self.db = db
        self.db.init_db()

    def tearDown(self):
        self.db.DB_FILE = self._orig_db_file
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _base_event(self) -> dict:
        return {
            "headline": "Test headline",
            "stage": "realized",
            "persistence": "medium",
            "what_changed": "x",
            "mechanism_summary": "y",
            "beneficiaries": ["A"], "losers": ["B"],
            "beneficiary_tickers": ["AAA"], "loser_tickers": ["BBB"],
            "assets_to_watch": [],
            "confidence": "medium",
            "market_note": "",
            "market_tickers": [],
            "event_date": "2026-04-18",
            "model": "test-model",
            "transmission_chain": ["hop1", "hop2"],
            "transmission_path": [
                {"hop": "H1", "channel": "supply", "actor": "Actor1"},
                {"hop": "H2", "channel": "pricing_power", "actor": "Actor2"},
            ],
            "substitution_barriers": [
                {"barrier": "BR1", "kind": "physical_sole_source", "severity": "high"},
            ],
            "counterforces": [
                {"force": "CF1", "actor": "ActorX", "likelihood": "medium"},
            ],
            "adversarial_challenge": "the thesis may already be priced",
            "if_persists": {}, "currency_channel": {},
            "policy_sensitivity": {}, "inventory_context": {},
            "regime_snapshot": {},
            "real_yield_context": {}, "policy_constraint": {},
            "shock_decomposition": {}, "reaction_function_divergence": {},
            "surprise_vs_anticipation": {}, "terms_of_trade": {},
            "reserve_stress": {}, "narrative_divergence": {},
            "credit_regime": {},
        }

    def test_save_and_load_preserves_new_fields(self):
        ev = self._base_event()
        self.db.save_event(ev)
        events = self.db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)
        saved = events[0]
        self.assertEqual(saved["transmission_path"][0]["hop"], "H1")
        self.assertEqual(saved["transmission_path"][0]["channel"], "supply")
        self.assertEqual(saved["substitution_barriers"][0]["severity"], "high")
        self.assertEqual(saved["counterforces"][0]["likelihood"], "medium")
        self.assertEqual(saved["adversarial_challenge"],
                         "the thesis may already be priced")

    def test_save_empty_new_fields_decoded_as_defaults(self):
        ev = self._base_event()
        ev["transmission_path"] = []
        ev["substitution_barriers"] = []
        ev["counterforces"] = []
        ev["adversarial_challenge"] = ""
        self.db.save_event(ev)
        events = self.db.load_recent_events(limit=10)
        saved = events[0]
        self.assertEqual(saved["transmission_path"], [])
        self.assertEqual(saved["substitution_barriers"], [])
        self.assertEqual(saved["counterforces"], [])
        self.assertEqual(saved["adversarial_challenge"], "")


if __name__ == "__main__":
    unittest.main()
