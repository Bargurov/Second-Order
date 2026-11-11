"""research-prompt-2: the research reply as the response itself, in the JSON output format (output_config.format).

Why (docs/news-mvp-closure.md (private; not in the public repository), "Second investigation"): both live research-prompt-1
replies of 2026-10-26 broke the strict tool's schema in the tool-call layer. The object parameter `interpretation` came back
as a string holding unfinished JSON text, and the call ended without `missing_information` and `tests`. The provider documents
that tool parameters are written as text, with objects as JSON parsed back by the API (Define tools), and documents JSON
outputs for a reply in a fixed JSON shape when no function is called (Structured outputs; the Claude Sonnet 5.5 migration
guide). The research tool was never called as a function: it only carried the analysis. research-prompt-2 asks for the
identical schema as the response itself and offers no tool.

Whether that holds on the live provider is unverified until a separately approved live request. These tests run against
fakes and show only that the application sends, reads and refuses as the contract says. Every reply here is SYNTHETIC.
"""
import hashlib
import json
import unittest
from unittest import mock

from account_fakes import USER_WRITE, every_file
from model_fixtures import THINKING
from news_desk_fakes import START, TARIFF
from test_deeper_evidence import go_deeper
from test_news_desk_api import DeskWorld
from test_research_reply_contract import (CUT_OFF, INTERPRETATION, LIVE_PROBLEM, complete_input, live_shape, reply,
                                          source_of, strict_subset_problems)
from second_order import event_intake, news_views, research_analysis as ra, research_reading, story_deeper
from second_order.analysis_flow import cost_estimate
from second_order.store import canonical

PROMPT_1 = "research-prompt-1"
EVENT = {"headline": "Synthetic headline", "source_url": "https://example.invalid/a",
         "published_at": "2026-01-02T03:04:05+00:00"}
TEXT = "Synthetic source text."
# research-prompt-1 as built before research-prompt-2 existed (computed on 2026-10-26 from commit 56c2a12). The same
# builder reproduced the two live requests' request.json byte for byte from their capture on that day.
PROMPT_1_SHA256 = {
    "system": "70572d5e7bbeec72bbd2457063bf3bfdf2d52d1e24f7d6ff62e4730d933107eb",
    "tool_description": "9151feabbb58cc35b9cbf6ffe873c60d74fe3e3c961e7e8020eb2c6c8399a808",
    "schema": "76409842762db076e625991b0f8264a7ea2ed34c0e613a75188e9c122832baa2",
    "medium": "99d40b2bc98c517336205dbb91da34e86327d2bee06a2e744e8786fbf9d161db",
    "low": "45ca5955657d72517f4be402a5da7892f1a811517dfc76a723e356fa0a29b5f0",
}


def sha(value) -> str:
    data = value if isinstance(value, str) else canonical(value)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def answer(document, stop_reason: str = "end_turn", content: list | None = None) -> bytes:
    """A SYNTHETIC JSON-output reply: a thinking block, then the document as the one text block."""
    text = document if isinstance(document, str) else json.dumps(document)
    blocks = content if content is not None else [dict(THINKING), {"type": "text", "text": text}]
    return reply({}, stop_reason=stop_reason, content=blocks)


def format_reply(request_body: bytes) -> bytes:
    """The fake provider's SYNTHETIC answer to a research-prompt-2 request: every field, quoting its publishers."""
    return answer(complete_input(source_of(request_body)))


class TodaysRequestTest(unittest.TestCase):
    def test_todays_request_asks_for_the_schema_as_the_json_output_format_and_offers_no_tool(self):
        self.assertEqual(ra.PROMPT_VERSION, "research-prompt-2")
        request = ra.build_request(EVENT, TEXT, "low")
        self.assertNotIn("tools", request)
        self.assertNotIn("tool_choice", request)
        self.assertNotIn("thinking", request)  # Adaptive thinking, the model's default, as under research-prompt-1.
        self.assertEqual(request["output_config"], {"effort": "low", "format": {"type": "json_schema",
                                                                               "schema": ra.output_schema()}})
        self.assertEqual(strict_subset_problems(request["output_config"]["format"]["schema"], "format.schema"), [])
        self.assertEqual((request["model"], request["max_tokens"]), (ra.MODEL, ra.MAX_TOKENS))
        self.assertNotIn(ra.TOOL_NAME, request["system"] + request["messages"][0]["content"])
        self.assertEqual(event_intake.framed_inputs(event_intake.user_message(request)), {**EVENT, "text": TEXT})

    def test_the_schema_is_the_research_prompt_1_tool_schema_unchanged(self):
        self.assertEqual(ra.output_schema(), ra.tool_schema())
        self.assertEqual(sha(ra.output_schema()), PROMPT_1_SHA256["schema"])

    def test_research_prompt_1_is_kept_byte_for_byte(self):
        self.assertEqual(sha(ra.SYSTEM_PROMPT), PROMPT_1_SHA256["system"])
        self.assertEqual(sha(ra.TOOL_DESCRIPTION), PROMPT_1_SHA256["tool_description"])
        for effort in ("medium", "low"):
            self.assertEqual(sha(ra.build_request(EVENT, TEXT, effort, PROMPT_1)), PROMPT_1_SHA256[effort])

    def test_the_new_system_prompt_keeps_every_rule_and_changes_only_how_the_reply_arrives(self):
        old = ra.SYSTEM_PROMPT.split("\n\n")
        new = ra.SYSTEM_PROMPT_FORMAT.split("\n\n")
        changed = [paragraph for paragraph in old if paragraph not in new]
        self.assertEqual(len(changed), 1)
        self.assertIn("call the submit_research_analysis tool", changed[0])
        self.assertEqual(len(old), len(new))
        added = [paragraph for paragraph in new if paragraph not in old]
        self.assertEqual(len(added), 1)
        self.assertIn("no_additional_finding", added[0])  # A source that supports nothing still gets the format.

    def test_an_unknown_prompt_version_is_never_built(self):
        with self.assertRaises(ValueError):
            ra.build_request(EVENT, TEXT, "low", "research-prompt-3")


class FormatReplyTest(unittest.TestCase):
    """research-prompt-2 replies read against a Go deeper source and its publisher passages."""

    @classmethod
    def setUpClass(cls):
        case = unittest.TestCase()
        world = DeskWorld(case)
        story = news_views.world(world.desk, START)["stories"][world.story(TARIFF)]
        cls.source, evidence = story_deeper.assemble(story, story["material"], "user-1", world.desk.texts)
        cls.spans = evidence["spans"]
        case.doCleanups()

    def read(self, body: bytes) -> dict:
        return research_reading.classify(body, ra.MODEL, self.source, self.spans, reply="format")

    def test_a_complete_document_is_accepted_with_its_quotes_in_the_publishers_passages(self):
        read = self.read(answer(complete_input(self.source)))
        self.assertEqual(read["outcome"], "analysis", read["problem"])
        quotes = [quote for item in read["analysis"]["established"] for quote in item["quotes"]]
        self.assertTrue(quotes)
        for quote in quotes:
            self.assertEqual(self.source[quote["start"]:quote["end"]], quote["source_passage"])
            self.assertEqual(quote["evidence"]["part"], "excerpt")
        self.assertEqual(read["analysis"]["tests"], [{"check": "SYNTHETIC check.",
                                                       "counts_against_if": "SYNTHETIC counter-observation."}])
        no_finding = complete_input(self.source)
        no_finding["interpretation"] = {"kind": "no_additional_finding", "text": "SYNTHETIC: nothing more.",
                                        "based_on": []}
        self.assertEqual(self.read(answer(no_finding))["outcome"], "no additional finding")

    def test_an_object_sent_as_a_string_is_never_parsed_even_when_the_string_is_valid_json(self):
        for text in (CUT_OFF, json.dumps(INTERPRETATION)):
            with self.subTest(text=text[:30]):
                read = self.read(answer({**complete_input(self.source), "interpretation": text}))
                self.assertEqual((read["outcome"], read["analysis"]), ("refused", None))
                self.assertEqual(read["problem"], "The analysis failed strict validation: interpretation: Input should "
                                                  "be an object")

    def test_the_live_shape_as_a_document_is_refused_and_nothing_is_filled_in(self):
        document = json.loads(live_shape(self.source))["content"][0]["input"]
        read = self.read(answer(document))
        self.assertEqual((read["outcome"], read["problem"], read["analysis"]), ("refused", LIVE_PROBLEM, None))
        for field in ("established", "interpretation", "assumptions", "competing_explanations",
                      "missing_information", "tests"):
            with self.subTest(field=field):
                document = complete_input(self.source)
                del document[field]
                read = self.read(answer(document))
                self.assertEqual((read["outcome"], read["analysis"]), ("refused", None))
                self.assertIn(f"{field}: Field required", read["problem"])

    def test_text_that_is_not_exactly_one_json_document_is_refused_and_never_extracted(self):
        document = json.dumps(complete_input(self.source))
        for text in (f"```json\n{document}\n```", f"Here is the analysis:\n{document}", f"{document}\nDone.",
                     document + document, "", document[:-1]):
            with self.subTest(text=text[:20]):
                read = self.read(answer(text))
                self.assertEqual((read["outcome"], read["analysis"]), ("refused", None))
                self.assertEqual(read["problem"], "The reply's text is not one valid JSON document")
        self.assertEqual(self.read(answer(f"\n{document}\n"))["outcome"], "analysis")  # Surrounding whitespace only.
        listed = self.read(answer([complete_input(self.source)]))
        self.assertEqual((listed["outcome"], listed["analysis"]), ("refused", None))

    def test_any_block_beside_thinking_and_one_text_block_refuses_the_reply(self):
        document = complete_input(self.source)
        text = {"type": "text", "text": json.dumps(document)}
        call = {"type": "tool_use", "id": "toolu_x", "name": ra.TOOL_NAME, "input": document,
                "caller": {"type": "direct"}}
        for content in ([dict(THINKING), text, text], [text, call], [call], [dict(THINKING)],
                        [{"type": "server_tool_use", "id": "srvtoolu_x", "name": "web_search", "input": {}}, text]):
            with self.subTest(blocks=[block["type"] for block in content]):
                read = self.read(answer(None, content=content))
                self.assertEqual((read["outcome"], read["analysis"]), ("refused", None))
        self.assertEqual(self.read(answer(None, content=[text]))["outcome"], "analysis")  # No thinking block needed.

    def test_stop_reasons_other_than_a_finished_turn_carry_no_analysis(self):
        document = complete_input(self.source)
        refusal = self.read(answer(document, stop_reason="refusal"))
        self.assertEqual((refusal["outcome"], refusal["analysis"]), ("declined", None))
        self.assertEqual(self.read(answer(document, stop_reason="max_tokens"))["outcome"], "incomplete")
        called = self.read(answer(None, stop_reason="tool_use", content=[
            {"type": "tool_use", "id": "toolu_x", "name": ra.TOOL_NAME, "input": document,
             "caller": {"type": "direct"}}]))
        self.assertEqual((called["outcome"], called["analysis"]), ("refused", None))
        self.assertIn("offers no tool", called["problem"])
        prose = self.read(answer("SYNTHETIC: the source supports no analysis."))
        self.assertEqual((prose["outcome"], prose["analysis"]), ("refused", None))  # A decline in prose is not this contract.

    def test_quotes_from_the_framing_or_across_passages_refuse_the_document(self):
        for quote in ("The shared brief of this story is not included", f"Headline: {TARIFF}"):
            with self.subTest(quote=quote):
                document = complete_input(self.source)
                document["established"][0]["quotes"] = [quote]
                read = self.read(answer(document))
                self.assertEqual(read["outcome"], "refused")
                self.assertIn("not the publishers' own words", read["problem"])

    def test_each_contract_refuses_the_other_contracts_reply(self):
        document = complete_input(self.source)
        tool_read = research_reading.classify(answer(document), ra.MODEL, self.source, self.spans, reply="tool")
        # research-prompt-1 reads text that ends the turn as a decline in prose: shown as text, never as analysis.
        self.assertEqual((tool_read["outcome"], tool_read["analysis"]), ("declined", None))
        format_read = self.read(reply(document))
        self.assertEqual((format_read["outcome"], format_read["analysis"]), ("refused", None))
        self.assertEqual(research_reading.classify(reply(document), ra.MODEL, self.source, self.spans)["outcome"],
                         "analysis")  # Without a reply format, a reply is read as research-prompt-1's tool call.
        unknown = research_reading.classify(reply(document), ra.MODEL, self.source, self.spans, reply="other")
        self.assertEqual((unknown["outcome"], unknown["analysis"]), ("refused", None))


class FormatRunTest(unittest.TestCase):
    """The reader's Go deeper path under research-prompt-2, against the fake provider."""

    def run_medium(self, world: DeskWorld, answer_with) -> tuple:
        provider = world.world.provider
        provider.reply = answer_with
        reader = world.client("reader-a")
        analysis_id = go_deeper(self, world, reader, effort="medium")["analysis"]["analysis_id"]
        before = reader.get("/api/user/account").json()["credits"]["available"]
        quote = reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        approval = {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                    "approve": True}
        self.assertEqual(reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE,
                                     json=approval).status_code, 201)
        return reader, analysis_id, before, quote, approval

    def test_a_go_deeper_run_sends_the_saved_format_request_once_and_records_the_analysis(self):
        world = DeskWorld(self)
        reader, analysis_id, before, quote, approval = self.run_medium(world, format_reply)
        self.assertTrue(analysis_id.endswith(".research-prompt-2.medium"), analysis_id)
        shown = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((shown["state"], shown["result"]["outcome"]), ("recorded", "analysis"))
        self.assertTrue(shown["result"]["analysis"]["established"])
        self.assertEqual((shown["charge"]["state"], shown["charge"]["credits_charged"]), ("charged", quote["credits"]))
        self.assertEqual(reader.get("/api/user/account").json()["credits"]["available"], before - quote["credits"])

        provider = world.world.provider
        saved = (world.world.root / "research-analyses" / "requests" / analysis_id / "request.json").read_bytes()
        self.assertEqual(provider.requests, [saved])  # Sent once, byte for byte, never rebuilt.
        sent = json.loads(saved)
        self.assertNotIn("tools", sent)
        self.assertEqual(sent["output_config"]["format"], {"type": "json_schema", "schema": ra.output_schema()})
        self.assertEqual(provider.headers[0]["anthropic-version"], "2023-06-01")
        self.assertNotIn("anthropic-beta", provider.headers[0]["names"])  # JSON outputs need no beta header.

        records = every_file(world.world.root / "research-analyses")
        again = reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json=approval)
        self.assertEqual(again.status_code, 200)  # The same approval: the recorded result, nothing new.
        self.assertEqual(len(provider.requests), 1)
        self.assertEqual(every_file(world.world.root / "research-analyses"), records)

    def test_a_document_that_breaks_the_schema_is_refused_charged_at_its_quote_and_never_sent_again(self):
        world = DeskWorld(self)

        def broken(content: bytes) -> bytes:
            document = complete_input(source_of(content))
            document["interpretation"] = CUT_OFF
            del document["missing_information"], document["tests"]
            return answer(document)
        reader, analysis_id, before, quote, approval = self.run_medium(world, broken)
        shown = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((shown["state"], shown["result"]["outcome"], shown["result"]["analysis"]),
                         ("recorded", "invalid", None))
        self.assertEqual((shown["charge"]["state"], shown["charge"]["credits_charged"]), ("charged", quote["credits"]))
        manifest = json.loads((world.world.root / "research-analyses" / "attempts" / analysis_id /
                               "manifest.json").read_bytes())
        self.assertEqual((manifest["outcome"], manifest["adapter_message"]), ("refused", LIVE_PROBLEM))
        self.assertEqual(reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE,
                                     json={}).json()["code"], "already_attempted")
        self.assertEqual(len(world.world.provider.requests), 1)


class EarlierContractTest(unittest.TestCase):
    """A research-prompt-1 request prepared and run before research-prompt-2 keeps its records and its reading."""

    def test_a_prompt_1_run_reads_the_same_and_a_new_preparation_is_a_new_request(self):
        world = DeskWorld(self)
        provider = world.world.provider
        provider.reply = lambda content: live_shape(source_of(content))
        reader = world.client("reader-a")
        with mock.patch.object(ra, "PROMPT_VERSION", PROMPT_1):  # As prepared and sent before the change.
            analysis_id = go_deeper(self, world, reader, effort="medium")["analysis"]["analysis_id"]
            quote = reader.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE,
                                json={}).json()["quote"]
            reader.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
                "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                "approve": True})
            then = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertTrue(analysis_id.endswith(".research-prompt-1.medium"), analysis_id)
        records = every_file(world.world.root / "research-analyses")

        now = world.client("reader-a").get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((now["result"]["outcome"], now["result_sha256"]), ("invalid", then["result_sha256"]))
        shown = ra.show(analysis_id, world.world.folders)
        self.assertEqual((shown["prompt_version"], shown["tool"], shown["reply_format"]),
                         (PROMPT_1, ra.TOOL_NAME, ra.REPLY_FORMATS["tool"]))
        self.assertEqual(shown["result_view_sha256"], ra.fingerprint(ra.result_view(
            ra.verified_request(analysis_id, world.world.folders), world.world.folders)))
        manifest = json.loads((world.world.root / "research-analyses" / "attempts" / analysis_id /
                               "manifest.json").read_bytes())
        self.assertEqual(manifest["adapter_message"], LIVE_PROBLEM)

        again = world.client("reader-a").post("/api/user/analyses", headers=USER_WRITE, json={
            "source_id": now["source"]["source_id"], "effort": "medium"}).json()["analysis"]
        self.assertTrue(again["analysis_id"].endswith(".research-prompt-2.medium"), again["analysis_id"])
        self.assertEqual((again["state"], len(provider.requests)), ("prepared", 1))  # Prepared only; nothing sent.
        self.assertEqual({path: data for path, data in every_file(world.world.root / "research-analyses").items()
                          if analysis_id in str(path)}, {path: data for path, data in records.items()
                                                         if analysis_id in str(path)})


class PlanningEstimateTest(unittest.TestCase):
    def test_prompt_1_bytes_keep_their_estimate_and_prompt_2_counts_an_allowance_for_the_format_prompt(self):
        tool_bytes = canonical(ra.build_request(EVENT, TEXT, "medium", PROMPT_1)).encode("utf-8")
        before = cost_estimate(tool_bytes, ra.MAX_TOKENS)
        self.assertEqual(ra.research_cost(tool_bytes),
                         {**before, "assumptions": [*before["assumptions"], ra.ESTIMATE_NOTE]})

        format_bytes = canonical(ra.build_request(EVENT, TEXT, "medium")).encode("utf-8")
        estimate = ra.research_cost(format_bytes)
        self.assertEqual(estimate["input_tokens_assumed"], len(format_bytes) // 2 + ra.FORMAT_PROMPT_TOKENS + 1000)
        self.assertGreaterEqual(ra.FORMAT_PROMPT_TOKENS, 1000)
        text = " ".join(estimate["assumptions"])
        self.assertIn("JSON output format", text)
        self.assertNotIn("tool-use", text)
        usd = (estimate["input_tokens_assumed"] * 2 + ra.MAX_TOKENS * 10) / 1_000_000
        self.assertEqual(estimate["estimated_real_run_if_output_reaches_max_usd"], round(usd, 4))


if __name__ == "__main__":
    unittest.main()
