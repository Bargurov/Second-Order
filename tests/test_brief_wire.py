"""The branch-free brief protocol (brief_wire), over SYNTHETIC content; no external request is made.

brief-prompt-8 sent the whole brief in this protocol and the provider rejected its grammar as too large (2026-10-27); its
exact format is frozen in brief_prompt_8_format.json (it was reproduced from the application's contract until that
contract gained what changed's form and respondents, econ-explanation-0.4). The codec is exercised here on the
current contract (CONTRACT_FORMAT); the two stages that replaced the single request (tests/test_brief_stages.py) decode
their replies with the same codec."""
import copy
import hashlib
import json
from pathlib import Path
import unittest

from second_order import brief_drafting, brief_wire, output_schema
from second_order.model_draft import DraftRefused
from news_desk_fakes import insufficient_economics, misfits, tariff_economics, with_report

PROMPT_8 = json.loads(Path(__file__).with_name("brief_prompt_8_format.json").read_text(encoding="utf-8"))
PROMPT_8_FORMAT = PROMPT_8["schema"]  # The format the provider rejected, exactly as it was sent.
PROMPT_8_FORMAT_SHA256 = "2a7c49f25a269eefdbfb3a0aefe3367ca8ae269ce59b47a9ba76946f20d9177e"  # brief-58e058b535778a8e's.
CONTRACT_FORMAT = brief_wire.output_format(brief_drafting.SCHEMA)  # The same protocol over today's contract.
PROMPT_8_RULES = brief_wire.instructions(brief_drafting.SCHEMA)


SMALL = {"type": "object", "additionalProperties": False, "required": ["kind", "detail", "number", "flag"],
         "properties": {"kind": {"type": "string", "enum": ["one", "two"]},
                        "detail": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "number": {"type": "number"}, "flag": {"type": "boolean"}}}


def rich_reply() -> dict:
    return {"headline": "SYNTHETIC tariff", "summary": "SYNTHETIC: an import tariff was announced.",
            "facts": [{"text": "SYNTHETIC: a tariff was announced.", "reports": ["synthetic:report"], "claims": ["k1"]}],
            "claims": [{"id": "k1", "holder": "other_party", "holder_name": "Synthetic Republic",
                        "modality": "prospective", "quote": "SYNTHETIC: it would impose a tariff", "condition": None,
                        "source": "report:synthetic:report"}],  # brief-assisted-3
            "implications": [], "themes": [{"kind": "sector", "name": "Steel", "basis": "SYNTHETIC evidence"}],
            "uncertainties": ["SYNTHETIC: timing"], "missing": [], "insufficient_material": "",
            "economics": with_report(tariff_economics(), "synthetic:report")}


class WireTest(unittest.TestCase):
    def test_the_actual_rejected_schema_is_frozen_and_the_new_grammar_has_no_choices(self):
        recorded = json.loads(Path(__file__).with_name("brief_prompt_7_format.json").read_text(encoding="utf-8"))
        digest = hashlib.sha256(json.dumps(recorded["schema"], sort_keys=True, separators=(",", ":"),
                                           ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(digest, recorded["format_sha256"])
        self.assertEqual(recorded["request_sha256"],
                         "097ddf64f3bc0faaededed225ab5bbcca7b0c15436069e1d3b9a562f4f3dba6e")
        self.assertEqual(output_schema.profile(recorded["schema"])["unions"], 8)
        self.assertEqual(output_schema.profile(PROMPT_8_FORMAT),
                         {"unions": 0, "nested_unions": 0, "optional": 0})
        self.assertEqual(hashlib.sha256(json.dumps(PROMPT_8_FORMAT, sort_keys=True, separators=(",", ":"),
                                                   ensure_ascii=False).encode()).hexdigest(), PROMPT_8_FORMAT_SHA256)

        def check(node):
            if isinstance(node, dict):
                self.assertFalse({"anyOf", "allOf", "oneOf", "enum", "const"} & set(node))
                if node.get("type") == "object":
                    self.assertFalse(node["additionalProperties"])
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        check(PROMPT_8_FORMAT)
        self.assertEqual(output_schema.problems(PROMPT_8_FORMAT), [])
        check(CONTRACT_FORMAT)  # Today's contract in the same protocol: still no choices or unions.
        self.assertEqual(output_schema.problems(CONTRACT_FORMAT), [])

    def test_literal_wire_values_decode_without_coercion_or_losing_false_or_zero(self):
        wire = {"kind": "one", "detail": [], "number": 0, "flag": False}
        self.assertEqual(brief_wire.decode(wire, SMALL),
                         {"kind": "one", "detail": None, "number": 0, "flag": False})
        self.assertEqual(brief_wire.decode({**wire, "detail": [""]}, SMALL)["detail"], "")
        self.assertEqual(brief_wire.decode({**wire, "detail": ["SYNTHETIC"]}, SMALL)["detail"], "SYNTHETIC")
        self.assertEqual(wire["detail"], [])  # No mutation of the provider reply.

    def test_missing_extra_bad_types_and_ambiguous_nullable_values_are_refused(self):
        wire = {"kind": "one", "detail": [], "number": 0, "flag": False}
        cases = [{key: value for key, value in wire.items() if key != "detail"}, {**wire, "extra": "x"},
                 {**wire, "number": "0"}, {**wire, "number": True}, {**wire, "number": float("inf")},
                 {**wire, "number": 10 ** 1000}, {**wire, "flag": 0},
                 *({**wire, "detail": value} for value in (None, "x", {}, ["x", "y"], [None], [3]))]
        for index, wrong in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(DraftRefused):
                brief_wire.decode(wrong, SMALL)

    def test_closed_choices_are_enforced_locally_even_when_the_wire_type_fits(self):
        wire = {"kind": "THREE", "detail": [], "number": 0, "flag": False}
        self.assertEqual(misfits(wire, brief_wire.output_format(SMALL)), [])
        with self.assertRaisesRegex(DraftRefused, "allowed choices"):
            brief_wire.decode(wire, SMALL)

    def test_the_full_economic_content_round_trips_including_explicit_absences(self):
        content = rich_reply()
        before = copy.deepcopy(content)
        wire = brief_wire.encode(content, brief_drafting.SCHEMA)
        self.assertEqual(misfits(wire, CONTRACT_FORMAT), [])
        self.assertEqual(wire["economics"]["insufficient_reason"], [])
        self.assertEqual(wire["economics"]["change"][0]["stage"], "decision")
        self.assertEqual(wire["economics"]["figures"][0]["vintage_label"], [])
        self.assertEqual(wire["economics"]["channels"][0]["note"], ["tariff-pass-through"])
        self.assertEqual((wire["claims"][0]["modality"], wire["claims"][0]["condition"]), ("prospective", []))
        self.assertEqual(brief_wire.decode(wire, brief_drafting.SCHEMA), content)
        self.assertEqual(content, before)

    def test_explicit_insufficiency_keeps_all_required_fields_and_its_empty_representation(self):
        content = {**rich_reply(), "headline": "", "summary": "", "facts": [], "claims": [], "implications": [],
                   "themes": [],
                   "uncertainties": [], "missing": [], "insufficient_material": "SYNTHETIC: not enough evidence",
                   "economics": insufficient_economics()}
        wire = brief_wire.encode(content, brief_drafting.SCHEMA)
        self.assertEqual(wire["economics"]["change"], [])
        self.assertEqual(wire["economics"]["main_uncertainty"], [])
        self.assertEqual(brief_wire.decode(wire, brief_drafting.SCHEMA), content)
        del wire["economics"]
        with self.assertRaisesRegex(DraftRefused, "missing fields"):
            brief_wire.decode(wire, brief_drafting.SCHEMA)

    def test_instructions_retain_choices_and_explicit_transport_rules(self):
        rules = PROMPT_8_RULES
        for word in (brief_wire.VERSION, "zero or one", "case-sensitive", "insufficient_evidence",
                     "from_words", "stock_to_flow", "bounded_inference", "tariff-pass-through"):
            self.assertIn(word, rules)


if __name__ == "__main__":
    unittest.main()
