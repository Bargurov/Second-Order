"""output_schema (output-schema-check-0.1): the offline check of every JSON output format the project sends, against the
structured-outputs rules in the Claude API documentation and the official Python SDK's schema rule (read 2026-10-27),
plus one conservative project rule. Passing it does not show that the provider accepts a request; only a sent request
can show that."""
import hashlib
import json
import unittest
from pathlib import Path

from second_order import brief_stages, headline_triage, news_relevance, output_schema, research_requests

REJECTED = json.loads((Path(__file__).parent / "brief_prompt_6_format.json").read_text(encoding="utf-8"))


def kinds(problems: list[dict]) -> dict[str, int]:
    found: dict[str, int] = {}
    for row in problems:
        found[row["rule"]] = found.get(row["rule"], 0) + 1
    return found


class OutputSchemaTest(unittest.TestCase):
    def test_the_fixture_is_the_rejected_requests_format_unchanged(self):
        schema = REJECTED["schema"]
        self.assertEqual(hashlib.sha256(json.dumps(schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                                        .encode()).hexdigest(), REJECTED["format_sha256"])

    def test_the_rejected_brief_format_breaks_the_sdk_rule_and_nests_unions(self):
        problems = output_schema.problems(REJECTED["schema"])
        self.assertEqual(kinds(problems), {"sdk_node_type": 20, "nested_union": 8})
        self.assertEqual(output_schema.profile(REJECTED["schema"])["unions"], 12)
        where = {row["path"] for row in problems if row["rule"] == "nested_union"}
        self.assertIn("$.properties.economics.anyOf[0].properties.channels.items.properties.note", where)
        self.assertTrue(all(row["source"] for row in problems))

    def test_every_format_the_project_sends_passes(self):
        formats = {"brief stage 1": brief_stages.output_format(1), "brief stage 2": brief_stages.output_format(2),
                   "relevance": news_relevance.response_schema(),
                   "research": research_requests.output_schema(),
                   "headline triage": headline_triage.response_schema(["e1", "e2"], ["e1", "e2", "c1"])}
        for name, schema in formats.items():
            with self.subTest(name):
                self.assertEqual(output_schema.problems(schema), [])

    def test_the_brief_formats_keep_every_field_required_with_fewer_unions_none_nested(self):
        for stage in (1, 2):
            profile = output_schema.profile(brief_stages.output_format(stage))
            self.assertEqual((profile["optional"], profile["unions"], profile["nested_unions"]), (0, 0, 0))
            self.assertLess(profile["unions"], output_schema.profile(REJECTED["schema"])["unions"])

    def test_each_documented_rule_is_checked(self):
        cases = {
            "unsupported_keyword": {"type": "object", "additionalProperties": False, "required": ["a"],
                                    "properties": {"a": {"type": "string", "maxLength": 3}}},
            "additional_properties": {"type": "object", "required": [], "properties": {}},
            "min_items": {"type": "array", "minItems": 2, "items": {"type": "string"}},
            "complex_enum": {"type": "object", "additionalProperties": False, "required": ["a"],
                             "properties": {"a": {"type": "object", "enum": [{"x": 1}]}}},
            "enum_type": {"type": "string", "enum": ["a", 1]},
            "sdk_node_type": {"enum": ["a", "b"]},
            "required_unknown": {"type": "object", "additionalProperties": False, "required": ["b"],
                                 "properties": {"a": {"type": "string"}}},
            "nested_union": {"anyOf": [{"anyOf": [{"type": "string"}, {"type": "integer"}]}, {"type": "null"}]},
        }
        for rule, schema in cases.items():
            with self.subTest(rule):
                self.assertIn(rule, kinds(output_schema.problems(schema)))

    def test_the_published_counts_are_limits(self):
        many = {f"p{n}": {"anyOf": [{"type": "string"}, {"type": "null"}]} for n in range(17)}
        unions = {"type": "object", "additionalProperties": False, "required": list(many), "properties": many}
        self.assertIn("too_many_unions", kinds(output_schema.problems(unions)))
        optional = {"type": "object", "additionalProperties": False, "required": [],
                    "properties": {f"p{n}": {"type": "string"} for n in range(25)}}
        self.assertIn("too_many_optional", kinds(output_schema.problems(optional)))


if __name__ == "__main__":
    unittest.main()
