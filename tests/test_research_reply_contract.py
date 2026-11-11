"""The research reply's output contract, after the 2026-10-26 live refusal (research-request-0.2, research-prompt-1).

The one live Go deeper request (provider message msg_011CgQ1Zq8mW1rBrdDRiJNWg) was sent with a strict tool whose schema
requires `interpretation` to be an object and all six fields to be present. The reply came back with stop_reason
`tool_use`, its `interpretation` as a string of JSON-like text cut off before its closing quote, and no
`missing_information` or `tests`. The application kept the bytes as received and refused the reply as a whole. These
tests pin that handling and the request it follows: a string is never parsed into an object, nothing missing is filled
in, a complete reply is accepted, the request goes out with its strict tool and schema unchanged, and a refused run is
recorded once, charged once at its quote and never sent again.

Since research-prompt-2 (test_research_format_contract), new requests ask for the analysis in the JSON output format.
The request and run tests here prepare under research-prompt-1, as the live requests were, to keep its handling pinned.

LIVE_SHAPE below is a SANITIZED REPRODUCTION of that reply's structure, not the live reply: its quotes are the
request's own publisher passages and every other text is SYNTHETIC. The live bytes stay in the owner's runtime records
(data/research-analyses/attempts/, ignored by git). Everything here runs against fakes; nothing reaches a network.
"""
import json
import unittest
from unittest import mock

from account_fakes import USER_WRITE, deeper_passages, every_file
from model_fixtures import THINKING
from news_desk_fakes import START, TARIFF
from test_deeper_evidence import go_deeper
from test_news_desk_api import DeskWorld
from second_order import news_views, research_analysis as ra, research_reading, story_deeper

LIVE_PROBLEM = ("The analysis failed strict validation: interpretation: Input should be an object; "
                "missing_information: Field required; tests: Field required")
INTERPRETATION = {"kind": "finding", "text": "SYNTHETIC interpretation of statement 1.", "based_on": [1]}
# The live reply's interpretation was JSON-like text whose last string lacks its closing quote. SYNTHETIC wording.
CUT_OFF = '{"based_on":[1],"kind":"finding","text":"SYNTHETIC interpretation, cut off before its closing quote.}'
UNSUPPORTED = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
               "maxItems", "uniqueItems", "maxProperties", "minProperties"}


def source_of(request_body: bytes) -> str:
    content = json.loads(request_body)["messages"][0]["content"]
    return content.split("<source_text>\n", 1)[1].rsplit("\n</source_text>", 1)[0]


def complete_input(source: str) -> dict:
    """Every field, each of the right type, quoting the source's publisher passages."""
    passages = [passage[:120].rstrip() for passage in deeper_passages(source)][:2]
    return {"assumptions": ["SYNTHETIC assumption."],
            "competing_explanations": [{"explanation": "SYNTHETIC reading.", "would_distinguish": "SYNTHETIC check."}],
            "established": [{"basis": "action", "quotes": [passage], "statement": "SYNTHETIC statement."}
                            for passage in passages],
            "interpretation": dict(INTERPRETATION),
            "missing_information": ["SYNTHETIC missing information."],
            "tests": [{"check": "SYNTHETIC check.", "counts_against_if": "SYNTHETIC counter-observation."}]}


def reply(tool_input: dict, model: str = ra.MODEL, stop_reason: str = "tool_use", content: list | None = None) -> bytes:
    """A reply in the shape the API sent on 2026-10-26: compact JSON, `caller` on the tool call, and the top-level
    container, stop_details and diagnostics fields."""
    blocks = content if content is not None else [{"type": "tool_use", "id": "toolu_sanitized_reply",
                                                   "name": ra.TOOL_NAME, "input": tool_input,
                                                   "caller": {"type": "direct"}}]
    return json.dumps({"model": model, "id": "msg_sanitized_reply", "type": "message", "role": "assistant",
                       "content": blocks, "container": None, "stop_reason": stop_reason, "stop_sequence": None,
                       "stop_details": None,
                       "usage": {"input_tokens": 4252, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                                 "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 0},
                                 "output_tokens": 1588, "output_tokens_details": {"thinking_tokens": 0},
                                 "service_tier": "standard", "inference_geo": "global", "speed": "standard"},
                       "diagnostics": None}, separators=(",", ":")).encode("utf-8")


def live_shape(source: str) -> bytes:
    """LIVE_SHAPE: the SANITIZED REPRODUCTION of the live reply's structure (see the module's docstring)."""
    tool_input = complete_input(source)
    del tool_input["missing_information"], tool_input["tests"]
    tool_input["interpretation"] = CUT_OFF
    return reply(tool_input)


def strict_subset_problems(schema: dict, where: str = "input_schema") -> list[str]:
    """Where a tool schema leaves what strict tool use documents (structured outputs' JSON Schema limitations) or this
    contract's own rule that every field is required."""
    problems = [f"{where}: {keyword} is not supported" for keyword in sorted(UNSUPPORTED & set(schema))]
    if schema.get("type") == "object":
        if schema.get("additionalProperties") is not False:
            problems.append(f"{where}: additionalProperties must be false")
        if set(schema.get("required", [])) != set(schema.get("properties", {})):
            problems.append(f"{where}: every property must be required")
        for name, child in schema.get("properties", {}).items():
            problems += strict_subset_problems(child, f"{where}.{name}")
    if schema.get("type") == "array":
        if schema.get("minItems", 0) not in (0, 1):
            problems.append(f"{where}: minItems must be 0 or 1")
        problems += strict_subset_problems(schema.get("items", {}), f"{where}[]")
    return problems


class ReplyContractTest(unittest.TestCase):
    """Replies read against a Go deeper source and its publisher passages (the tariff story's two reports)."""

    @classmethod
    def setUpClass(cls):
        case = unittest.TestCase()
        world = DeskWorld(case)
        story = news_views.world(world.desk, START)["stories"][world.story(TARIFF)]
        cls.source, evidence = story_deeper.assemble(story, story["material"], "user-1", world.desk.texts)
        cls.spans = evidence["spans"]
        case.doCleanups()

    def read(self, body: bytes) -> dict:
        return research_reading.classify(body, ra.MODEL, self.source, self.spans)

    def test_the_live_shape_is_refused_as_the_live_reply_was(self):
        read = self.read(live_shape(self.source))
        self.assertEqual((read["outcome"], read["problem"], read["analysis"]), ("refused", LIVE_PROBLEM, None))

    def test_an_object_sent_as_a_string_is_never_parsed_even_when_the_string_is_valid_json(self):
        for text in (CUT_OFF, json.dumps(INTERPRETATION)):
            with self.subTest(text=text[:30]):
                tool_input = {**complete_input(self.source), "interpretation": text}
                read = self.read(reply(tool_input))
                self.assertEqual(read["outcome"], "refused")
                self.assertEqual(read["problem"], "The analysis failed strict validation: interpretation: Input should "
                                                  "be an object")
                self.assertIsNone(read["analysis"])

    def test_each_missing_field_refuses_the_reply_and_nothing_is_filled_in(self):
        for field in ("established", "interpretation", "assumptions", "competing_explanations",
                      "missing_information", "tests"):
            with self.subTest(field=field):
                tool_input = complete_input(self.source)
                del tool_input[field]
                read = self.read(reply(tool_input))
                self.assertEqual((read["outcome"], read["analysis"]), ("refused", None))
                self.assertIn(f"{field}: Field required", read["problem"])
        nested = complete_input(self.source)
        del nested["interpretation"]["based_on"]
        self.assertIn("interpretation.based_on: Field required", self.read(reply(nested))["problem"])

    def test_a_complete_reply_is_accepted_with_its_quotes_in_the_publishers_passages(self):
        read = self.read(reply(complete_input(self.source)))
        self.assertEqual(read["outcome"], "analysis", read["problem"])
        quotes = [quote for item in read["analysis"]["established"] for quote in item["quotes"]]
        self.assertTrue(quotes)
        for quote in quotes:
            self.assertEqual(self.source[quote["start"]:quote["end"]], quote["source_passage"])
            self.assertEqual(quote["evidence"]["part"], "excerpt")
        self.assertEqual(read["analysis"]["missing_information"], ["SYNTHETIC missing information."])

    def test_a_complete_reply_quoting_the_framing_or_across_passages_is_refused(self):
        for quote in ("The shared brief of this story is not included", f"Headline: {TARIFF}"):
            with self.subTest(quote=quote):
                tool_input = complete_input(self.source)
                tool_input["established"][0]["quotes"] = [quote]
                read = self.read(reply(tool_input))
                self.assertEqual(read["outcome"], "refused")
                self.assertIn("not the publishers' own words", read["problem"])

    def test_malformed_truncated_and_declined_replies_carry_no_analysis(self):
        self.assertEqual(self.read(b'{"model": "claude-sonnet-5-5", "content": [')["problem"],
                         "The provider response is not valid JSON")
        truncated = self.read(reply({}, stop_reason="max_tokens", content=[
            {"type": "tool_use", "id": "toolu_cut", "name": ra.TOOL_NAME, "input": {"assumptions": []},
             "caller": {"type": "direct"}}]))
        self.assertEqual((truncated["outcome"], truncated["analysis"]), ("incomplete", None))
        declined = self.read(reply({}, stop_reason="end_turn", content=[
            {"type": "text", "text": "SYNTHETIC: the source supports no analysis."}]))
        self.assertEqual((declined["outcome"], declined["analysis"], declined["model_text"]),
                         ("declined", None, "SYNTHETIC: the source supports no analysis."))
        refusal = self.read(reply({}, stop_reason="refusal", content=[]))
        self.assertEqual((refusal["outcome"], refusal["analysis"]), ("declined", None))
        thinking_then_call = self.read(reply({}, content=[dict(THINKING), {
            "type": "tool_use", "id": "toolu_x", "name": ra.TOOL_NAME, "input": complete_input(self.source),
            "caller": {"type": "direct"}}]))
        self.assertEqual(thinking_then_call["outcome"], "analysis")  # A thinking block may precede the call.


def prepared_under_prompt_1(test: unittest.TestCase) -> None:
    """Prepare, quote and run as before research-prompt-2: today's builder still writes research-prompt-1 on request."""
    patcher = mock.patch.object(ra, "PROMPT_VERSION", "research-prompt-1")
    patcher.start()
    test.addCleanup(patcher.stop)


class RequestOnTheWireTest(unittest.TestCase):
    def test_the_sent_bytes_are_the_saved_request_with_its_strict_tool_and_schema(self):
        prepared_under_prompt_1(self)
        world = DeskWorld(self)
        reader = world.client("reader-a")
        analysis_id = go_deeper(self, world, reader, effort="medium")["analysis"]["analysis_id"]
        quote = reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})
        provider = world.world.provider
        saved = (world.world.root / "research-analyses" / "requests" / analysis_id / "request.json").read_bytes()
        self.assertEqual(provider.requests, [saved])  # Sent once, byte for byte, never rebuilt.
        sent = json.loads(provider.requests[0])
        self.assertEqual(sent["tools"], [{"name": ra.TOOL_NAME, "description": ra.TOOL_DESCRIPTION, "strict": True,
                                          "input_schema": ra.tool_schema()}])
        self.assertEqual(strict_subset_problems(sent["tools"][0]["input_schema"]), [])
        self.assertEqual((sent["tool_choice"], sent["model"], sent["output_config"], sent["max_tokens"]),
                         ({"type": "auto"}, ra.MODEL, {"effort": "medium"}, ra.MAX_TOKENS))
        self.assertNotIn("thinking", sent)  # research-prompt-1: thinking left at the model's default (adaptive).
        self.assertEqual(provider.headers[0]["anthropic-version"], "2023-06-01")
        self.assertEqual(provider.headers[0]["content-type"], "application/json")
        self.assertNotIn("anthropic-beta", provider.headers[0]["names"])
        self.assertIn("x-api-key", provider.headers[0]["names"])

    def test_the_tool_schema_stays_within_the_strict_subset_and_requires_every_field(self):
        schema = ra.tool_schema()
        self.assertEqual(strict_subset_problems(schema), [])
        self.assertEqual(set(schema["required"]), {"established", "interpretation", "assumptions",
                                                   "competing_explanations", "missing_information", "tests"})
        self.assertEqual(schema["properties"]["interpretation"]["type"], "object")
        self.assertEqual(strict_subset_problems({**schema, "additionalProperties": True}),
                         ["input_schema: additionalProperties must be false"])


class LiveShapeRunTest(unittest.TestCase):
    """The reader's path when the provider answers in the live shape: recorded as refused, charged once at the quote,
    never sent again, and read back the same way; another Effort is a new request with its own quote."""

    def test_a_refused_run_is_kept_charged_once_and_never_sent_or_charged_again(self):
        prepared_under_prompt_1(self)
        world = DeskWorld(self)
        provider = world.world.provider
        answered: list[bytes] = []

        def answer(content: bytes) -> bytes:
            answered.append(live_shape(source_of(content)))
            return answered[-1]
        provider.reply = answer
        reader = world.client("reader-a")
        analysis_id = go_deeper(self, world, reader, effort="medium")["analysis"]["analysis_id"]
        before = reader.get("/api/user/account").json()["credits"]["available"]
        quote = reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        approval = {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                    "approve": True}
        self.assertEqual(reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE,
                                     json=approval).status_code, 201)
        shown = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((shown["state"], shown["result"]["outcome"], shown["result"]["analysis"]),
                         ("recorded", "invalid", None))
        self.assertEqual((shown["charge"]["state"], shown["charge"]["credits_charged"]), ("charged", quote["credits"]))
        self.assertEqual(reader.get("/api/user/account").json()["credits"]["available"], before - quote["credits"])
        attempt = world.world.root / "research-analyses" / "attempts" / analysis_id
        self.assertEqual((attempt / "response.json").read_bytes(), answered[0])  # Kept exactly as received.
        manifest = json.loads((attempt / "manifest.json").read_bytes())
        self.assertEqual((manifest["outcome"], manifest["adapter_message"]), ("refused", LIVE_PROBLEM))

        records = every_file(world.world.root / "research-analyses")
        again = reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json=approval)
        self.assertEqual(again.status_code, 200)  # The same approval: the recorded result, nothing new.
        self.assertEqual(reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE,
                                     json={}).json()["code"], "already_attempted")
        restarted = world.client("reader-a")  # A new application over the same records.
        self.assertEqual(restarted.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]["result_sha256"],
                         shown["result_sha256"])
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(restarted.get("/api/user/account").json()["credits"]["available"], before - quote["credits"])
        self.assertEqual(every_file(world.world.root / "research-analyses"), records)

        low = restarted.post("/api/user/analyses", headers=USER_WRITE, json={
            "source_id": shown["source"]["source_id"], "effort": "low"}).json()["analysis"]
        self.assertTrue(low["analysis_id"].endswith(".low"))
        self.assertEqual((low["state"], len(provider.requests)), ("prepared", 1))  # Prepared only; nothing sent.
        requests = world.world.root / "research-analyses" / "requests"
        medium_request = json.loads((requests / analysis_id / "request.json").read_bytes())
        low_request = json.loads((requests / low["analysis_id"] / "request.json").read_bytes())
        self.assertEqual({**low_request, "output_config": {"effort": "medium"}}, medium_request)


if __name__ == "__main__":
    unittest.main()
