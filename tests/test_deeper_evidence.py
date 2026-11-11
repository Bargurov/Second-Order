"""Go deeper's evidence: a deeper analysis may cite only the publishers' own words (deeper-evidence-0.1).

A Go deeper source opens with Second Order's framing (what it is, the story, what is left out) and labels each report
(Publisher, Published, Address, Headline, Excerpt, Credit), and a shortened text ends with Second Order's note. None of
that is a publisher's words. Go deeper records, with the source, where each publisher passage sits in it (each
headline, excerpt and publication text, by report and publisher); the research request binds that record; and every
quote of a reply must lie wholly inside one of those passages, or the reply is refused as a whole. An ordinary source a
user pastes keeps its whole text as evidence. Records made before the passages were recorded keep their recorded
results, but are not sent again. Everything here is SYNTHETIC and answered by fakes; nothing reaches a network.
"""
import hashlib
import json
import stat
import unittest

from account_fakes import SOURCE, USER_WRITE, source_form
from model_fixtures import THINKING, encoded
from news_desk_fakes import FACT, FACT_TITLE, START, TARIFF, WORDS, wh_page
from test_news_desk_api import DeskWorld
from test_news_texts import TextWorld
from second_order import deeper_evidence, news_views, research_analysis as ra, research_reading, story_deeper

STORIES = "/api/user/news/stories"
NOT_PUBLISHERS = "not the publishers' own words"
WIRE = ("SYNTHETIC CAPITAL (Reuters) - The Synthetic Republic said on Monday it would impose a 15% tariff on imported "
        "steel from next month, citing a review of its steel industry.")


def reply(*quotes: str) -> bytes:
    """A SYNTHETIC tool reply whose one established statement quotes ``quotes``."""
    return encoded({"id": "msg_synthetic_evidence", "type": "message", "role": "assistant", "model": ra.MODEL,
                    "content": [dict(THINKING), {"type": "tool_use", "id": "toolu_synthetic_evidence",
                                                 "name": ra.TOOL_NAME, "input": {
                        "established": [{"statement": "Synthetic statement.", "basis": "action",
                                         "quotes": list(quotes)}],
                        "interpretation": {"kind": "finding", "based_on": [1], "text": "Synthetic interpretation."},
                        "assumptions": [], "competing_explanations": [], "missing_information": [], "tests": []}}],
                    "stop_reason": "tool_use", "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 10}})


class SourceEvidenceTest(unittest.TestCase):
    """The tariff story: two reports (Synthetic Ledger, Synthetic Courier) with the same headline and wire excerpt."""

    def setUp(self):
        world = DeskWorld(self)
        story = news_views.world(world.desk, START)["stories"][world.story(TARIFF)]
        self.text, self.evidence = story_deeper.assemble(story, story["material"], "user-1", world.desk.texts)
        self.spans = self.evidence["spans"]

    def read(self, *quotes: str) -> dict:
        return research_reading.classify(reply(*quotes), ra.MODEL, self.text, self.spans)

    def test_the_framing_the_local_fixture_quoted_is_refused_as_evidence(self):
        # The fixture answers today's request (research-prompt-2) with the analysis as its text.
        unbound = research_reading.mock_response({"model": ra.MODEL}, self.text, "analysis", "0" * 64)
        first = json.loads(json.loads(unbound)["content"][1]["text"])["established"][0]["quotes"][0]
        self.assertTrue(first.startswith("Material for a deeper analysis of a news story"))  # The reported defect.
        refused = research_reading.classify(unbound, ra.MODEL, self.text, self.spans, "format")
        self.assertEqual(refused["outcome"], "refused")
        self.assertIn(NOT_PUBLISHERS, refused["problem"])
        self.assertIsNone(refused["analysis"])
        bound = research_reading.mock_response({"model": ra.MODEL}, self.text, "analysis", "0" * 64, self.spans)
        read = research_reading.classify(bound, ra.MODEL, self.text, self.spans, "format")
        self.assertEqual(read["outcome"], "analysis")
        for item in read["analysis"]["established"]:
            for quote in item["quotes"]:
                self.assertTrue(any(span["start"] <= quote["start"] and quote["end"] <= span["end"]
                                    for span in self.spans))

    def test_a_publishers_words_are_located_in_their_report_with_its_publisher(self):
        words = "The Synthetic Republic said on Monday it would impose a 15% tariff"
        read = self.read(words)
        self.assertEqual(read["outcome"], "analysis", read["problem"])
        quote = read["analysis"]["established"][0]["quotes"][0]
        self.assertEqual(self.text[quote["start"]:quote["end"]], words)
        self.assertLess(self.text.index("Report 1 of 2"), quote["start"])
        self.assertLess(quote["end"], self.text.index("Report 2 of 2"))
        self.assertEqual(quote["evidence"], {"report": 1, "publisher": "Synthetic Ledger", "part": "excerpt"})
        self.assertEqual(quote["occurrences"], 2)  # Once in each report's excerpt.

    def test_a_headline_the_framing_repeats_is_located_in_a_report(self):
        read = self.read(TARIFF)
        quote = read["analysis"]["established"][0]["quotes"][0]
        self.assertLess(self.text.index(TARIFF), quote["start"])  # Its first appearance is the framing's "Story:".
        self.assertEqual(quote["start"], self.text.index(f"Headline: {TARIFF}") + len("Headline: "))
        self.assertEqual(quote["evidence"], {"report": 1, "publisher": "Synthetic Ledger", "part": "headline"})

    def test_framing_labels_and_quotes_crossing_passages_are_refused(self):
        for quote in ("The shared brief of this story is not included", "Synthetic Ledger",
                      "Publisher: Synthetic Ledger", f"Headline: {TARIFF}", f"Excerpt: {WIRE[:40]}",
                      f"imported steel\nExcerpt: {WIRE[:20]}", "its steel industry.\nCredit: Synthetic Ledger",
                      "Synthetic Ledger\n\nReport 2 of 2", "Only the reports' own words can be quoted"):
            with self.subTest(quote=quote):
                self.assertIn(quote, self.text)
                read = self.read(quote)
                self.assertEqual(read["outcome"], "refused")
                self.assertIn(NOT_PUBLISHERS, read["problem"])
        missing = self.read("A synthetic passage that the source does not contain.")
        self.assertEqual(missing["outcome"], "refused")
        self.assertIn("was not found", missing["problem"])

    def test_one_quote_outside_the_publishers_words_refuses_the_whole_reply(self):
        read = self.read(WIRE[:60], "The shared brief of this story is not included")
        self.assertEqual(read["outcome"], "refused")
        self.assertIn("Quote 2", read["problem"])

    def test_a_quote_matched_after_plain_spacing_stays_inside_one_passage(self):
        read = self.read("The Synthetic Republic  said on Monday it would impose")
        quote = read["analysis"]["established"][0]["quotes"][0]
        self.assertEqual(quote["match"], "normalized")
        self.assertEqual(quote["source_passage"], "The Synthetic Republic said on Monday it would impose")
        self.assertEqual(quote["evidence"]["part"], "excerpt")

    def test_the_record_names_each_passage_by_its_place_and_hash(self):
        self.assertEqual(self.evidence["evidence_version"], deeper_evidence.EVIDENCE_VERSION)
        self.assertEqual(self.evidence["source_sha256"], hashlib.sha256(self.text.encode("utf-8")).hexdigest())
        self.assertEqual([(span["report"], span["part"]) for span in self.spans],
                         [(1, "headline"), (1, "excerpt"), (2, "headline"), (2, "excerpt")])
        for span in self.spans:
            self.assertEqual(span["sha256"], hashlib.sha256(self.text[span["start"]:span["end"]].encode()).hexdigest())
        self.assertIsNone(deeper_evidence.problem(self.evidence, self.text))

    def test_a_record_that_does_not_fit_the_text_is_refused(self):
        def changed(**fields) -> dict:
            return {**self.evidence, "spans": [{**self.spans[0], **fields}, *self.spans[1:]]}
        self.assertIn("hash", deeper_evidence.problem(changed(sha256="0" * 64), self.text))
        self.assertIn("outside", deeper_evidence.problem(changed(end=len(self.text) + 1), self.text))
        self.assertIn("order", deeper_evidence.problem(changed(start=self.spans[1]["start"] + 1,
                                                               end=self.spans[1]["start"] + 3), self.text))
        self.assertIn("part", deeper_evidence.problem(changed(part="credit"), self.text))
        self.assertIn("text", deeper_evidence.problem(self.evidence, self.text + "\n"))
        self.assertIsNotNone(deeper_evidence.problem({**self.evidence, "spans": []}, self.text))
        self.assertIsNotNone(deeper_evidence.problem("not a record", self.text))


class ShortenedTextTest(unittest.TestCase):
    def test_a_shortened_publication_is_cited_from_its_text_never_from_the_note(self):
        world = TextWorld(self)
        world.pages.answers[FACT] = (200, wh_page(FACT_TITLE, [f"{WORDS} Paragraph {number}." for number in
                                                              range(260)]), "text/html; charset=UTF-8")
        world.retrieve()
        story = world.story()
        text, evidence = story_deeper.assemble(story, story["material"], "user-1", world.desk.texts)
        note = "[Shortened here to fit the source limit:"
        self.assertIn(note, text)
        self.assertEqual(text, story_deeper.source_text(story, story["material"], "user-1", world.desk.texts))
        texts = [span for span in evidence["spans"] if span["part"] == "text"]
        self.assertTrue(texts)
        self.assertFalse(any(note in text[span["start"]:span["end"]] for span in evidence["spans"]))
        refused = research_reading.classify(reply(note), ra.MODEL, text, evidence["spans"])
        self.assertIn(NOT_PUBLISHERS, refused["problem"])
        words = WORDS[:60]
        read = research_reading.classify(reply(words), ra.MODEL, text, evidence["spans"])
        self.assertEqual(read["outcome"], "analysis", read["problem"])
        self.assertEqual(read["analysis"]["established"][0]["quotes"][0]["evidence"]["part"], "text")


def go_deeper(test: unittest.TestCase, world: DeskWorld, client, effort: str = "low") -> dict:
    """The reader's Go deeper on the tariff story, as the story page sends it."""
    tariff = world.story(TARIFF)
    preview = client.get(f"{STORIES}/{tariff}/deeper").json()["deeper"]
    done = client.post(f"{STORIES}/{tariff}/deeper", headers=USER_WRITE,
                       json={"material_sha256": preview["material_sha256"], "effort": effort})
    test.assertIn(done.status_code, (200, 201), done.text)
    return done.json()["deeper"]


def run_analysis(test: unittest.TestCase, client, analysis_id: str):
    """A credit quote for the analysis, then its approval."""
    quote = client.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={})
    test.assertEqual(quote.status_code, 201, quote.text)
    quote = quote.json()["quote"]
    return client.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
        "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})


class DeeperRunTest(unittest.TestCase):
    def test_go_deeper_records_the_publishers_passages_and_the_request_binds_them(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        done = go_deeper(self, world, reader)
        source_id = done["source"]["source_id"]
        link = json.loads((world.desk.deeper / f"{source_id}.json").read_bytes())
        self.assertEqual(link["link_version"], story_deeper.LINK_VERSION)
        text = reader.get(f"/api/user/sources/{source_id}").json()["source"]["text"]
        self.assertIsNone(deeper_evidence.problem(link["evidence"], text))
        self.assertEqual({span["publisher"] for span in link["evidence"]["spans"]},
                         {"Synthetic Ledger", "Synthetic Courier"})
        manifest = json.loads((world.world.root / "research-analyses" / "requests" / done["analysis"]["analysis_id"] /
                               "manifest.json").read_bytes())
        self.assertEqual(manifest["evidence"]["spans"], link["evidence"]["spans"])
        self.assertEqual(manifest["evidence"]["link_sha256"],
                         hashlib.sha256((world.desk.deeper / f"{source_id}.json").read_bytes()).hexdigest())

    def test_a_reply_quoting_the_framing_is_refused_and_none_of_it_is_shown(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        analysis_id = go_deeper(self, world, reader)["analysis"]["analysis_id"]
        world.world.provider.outcome = "framing"
        self.assertEqual(run_analysis(self, reader, analysis_id).status_code, 201)
        shown = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((shown["state"], shown["result"]["outcome"], shown["result"]["analysis"]),
                         ("recorded", "invalid", None))
        self.assertEqual(len(world.world.provider.requests), 1)

    def test_a_reply_quoting_the_publishers_words_is_recorded_with_their_reports(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        done = go_deeper(self, world, reader)
        analysis_id = done["analysis"]["analysis_id"]
        self.assertEqual(run_analysis(self, reader, analysis_id).status_code, 201)
        result = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]["result"]
        self.assertEqual(result["outcome"], "analysis")
        quotes = [quote for item in result["analysis"]["established"] for quote in item["quotes"]]
        self.assertTrue(quotes)
        for quote in quotes:
            self.assertEqual(quote["evidence"]["part"], "excerpt")
            self.assertIn(quote["evidence"]["publisher"], ("Synthetic Ledger", "Synthetic Courier"))
            self.assertIn(quote["source_passage"], WIRE)

    def test_an_ordinary_source_keeps_its_whole_text_as_evidence(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        saved = reader.post("/api/user/sources", headers=USER_WRITE, json=source_form())
        self.assertEqual(saved.status_code, 201, saved.text)
        source_id = saved.json()["source"]["source_id"]
        prepared = reader.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id,
                                                                              "effort": "low"})
        analysis_id = prepared.json()["analysis"]["analysis_id"]
        manifest = json.loads((world.world.root / "research-analyses" / "requests" / analysis_id /
                               "manifest.json").read_bytes())
        self.assertNotIn("evidence", manifest)
        self.assertEqual(run_analysis(self, reader, analysis_id).status_code, 201)
        result = reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]["result"]
        self.assertEqual(result["outcome"], "analysis")
        quote = result["analysis"]["established"][0]["quotes"][0]
        self.assertNotIn("evidence", quote)  # The shape of an ordinary source's quote is unchanged.
        self.assertEqual(quote["start"], SOURCE.index(quote["source_passage"]))  # Anywhere in the user's own text.


class EarlierRecordsTest(unittest.TestCase):
    LEGACY = ("Material for a deeper analysis of a news story, assembled by Second Order (story-deeper-0.1; reference "
              "deeper-000000000000).\nStory: Synthetic Republic announces 15% tariff on imported steel\nThe shared "
              "brief of this story is not included: an analysis reads the reports themselves.\n\nReport 1 of 1\n"
              f"Publisher: Synthetic Ledger\nHeadline: {TARIFF}\nExcerpt: {WIRE}\nCredit: Synthetic Ledger\n")

    def setUp(self):
        self.world = DeskWorld(self)
        self.reader = self.world.client("reader-a")
        saved = self.reader.post("/api/user/sources", headers=USER_WRITE, json={
            **source_form(TARIFF, self.LEGACY), "source_url": "https://ledger.example.org/news/tariff"})
        self.assertEqual(saved.status_code, 201, saved.text)
        self.source_id = saved.json()["source"]["source_id"]
        self.analyses = {}
        for effort in ("low", "medium"):
            prepared = self.reader.post("/api/user/analyses", headers=USER_WRITE,
                                        json={"source_id": self.source_id, "effort": effort})
            self.analyses[effort] = prepared.json()["analysis"]["analysis_id"]
        self.world.world.provider.outcome = "framing"  # Accepted then: the whole text was the source's evidence.
        run_analysis(self, self.reader, self.analyses["low"])
        self.before = self.reader.get(f"/api/user/analyses/{self.analyses['low']}").json()["analysis"]
        self.assertEqual(self.before["result"]["outcome"], "analysis")
        tariff = news_views.world(self.world.desk, START)["stories"][self.world.story(TARIFF)]
        self.world.desk.deeper.mkdir(parents=True, exist_ok=True)
        (self.world.desk.deeper / f"{self.source_id}.json").write_text(json.dumps({  # As story-deeper-0.1 wrote it.
            "link_version": "story-deeper-link-0.1", "capture_id": self.source_id,
            "user_id": self.world.world.ids["reader-a"], "story_id": tariff["story_id"],
            "material_sha256": tariff["material"]["material_sha256"], "brief": None, "reports": [],
            "recorded_at": START.isoformat(), "statement": story_deeper.STATEMENT}), encoding="utf-8")

    def test_its_recorded_result_is_unchanged(self):
        after = self.reader.get(f"/api/user/analyses/{self.analyses['low']}").json()["analysis"]
        self.assertEqual((after["state"], after["result_sha256"]), ("recorded", self.before["result_sha256"]))
        self.assertEqual(after["result"], self.before["result"])

    def test_it_is_neither_quoted_nor_prepared_again(self):
        sent = len(self.world.world.provider.requests)
        quote = self.reader.post(f"/api/user/analyses/{self.analyses['medium']}/quotes", headers=USER_WRITE, json={})
        self.assertEqual((quote.status_code, quote.json()["code"]), (409, "source_unmarked"))
        again = self.reader.post("/api/user/analyses", headers=USER_WRITE,
                                 json={"source_id": self.source_id, "effort": "high"})
        self.assertEqual((again.status_code, again.json()["code"]), (409, "source_unmarked"))
        self.assertEqual(len(self.world.world.provider.requests), sent)

    def test_its_approval_reserves_and_sends_nothing(self):
        folders = self.world.world.folders
        verified = ra.verified_request(self.analyses["medium"], folders)
        with self.assertRaises(ra.FlowRefused) as refused:
            ra.approved_for_account(self.analyses["medium"], verified["request_sha256"], folders)
        self.assertEqual(str(refused.exception), ra.UNMARKED)
        self.assertEqual(ra.attempt_state(self.analyses["medium"], folders)["state"], "none")

    def test_going_deeper_again_makes_a_source_whose_passages_are_marked(self):
        done = go_deeper(self, self.world, self.reader)
        self.assertTrue(done["created_source"])
        self.assertNotEqual(done["source"]["source_id"], self.source_id)
        link = json.loads((self.world.desk.deeper / f"{done['source']['source_id']}.json").read_bytes())
        self.assertIn("evidence", link)


class BindingTest(unittest.TestCase):
    def test_a_binding_that_no_longer_holds_is_refused(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        done = go_deeper(self, world, reader)
        analysis_id, source_id = done["analysis"]["analysis_id"], done["source"]["source_id"]
        path = world.desk.deeper / f"{source_id}.json"
        original = path.read_bytes()
        record = json.loads(original)
        record["evidence"]["spans"][0]["end"] -= 1
        path.chmod(stat.S_IWRITE | stat.S_IREAD)  # The record is written once and read-only; this test changes it.
        path.write_text(json.dumps(record), encoding="utf-8")
        self.assertEqual(reader.get(f"/api/user/analyses/{analysis_id}").json()["code"], "internal_error")
        path.unlink()
        self.assertEqual(reader.get(f"/api/user/analyses/{analysis_id}").json()["code"], "internal_error")
        path.write_bytes(original)
        self.assertEqual(reader.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]["state"], "prepared")


if __name__ == "__main__":
    unittest.main()
