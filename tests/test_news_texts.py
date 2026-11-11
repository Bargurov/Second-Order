"""Official publication texts for the news (news_texts, page_text, news-texts-0.1) and what uses them: the story's
material (story-material-0.2), the paid draft's request, Go deeper's source and the Admin desk's retrieval route. Pages
are SYNTHETIC HTML in each publisher's layout, served at the registered White House addresses by a simulated network;
nothing reaches a network, and reading a story never requests anything."""
from dataclasses import replace
from datetime import timedelta
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from account_fakes import ADMIN_WRITE, USER_WRITE, World, every_file
from news_desk_fakes import (ACTION, BROKEN, FACT, FACT_TITLE, START, TABLED, WH, WORDS, BriefModel, Feeds,
                             Pages, desk_in, pages, stage_replies, wh_feed, wh_page)
from second_order import (brief_drafting, news_cli, news_feeds, news_registry, news_reports, news_stories, news_texts,
                          news_views, page_text, story_briefs, story_deeper)
from second_order import newsroom_store as ns

NOW = START + timedelta(hours=6)


class TextWorld:
    """SYNTHETIC accounts and the White House feed's SYNTHETIC entries, grouped (the fact sheet and the proclamation
    merged as one development), with a simulated network for the pages."""

    def __init__(self, test: unittest.TestCase):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms()
        self.feeds = Feeds({WH.feed_url: (200, wh_feed())})
        self.pages = pages()
        desk = desk_in(self.world.root, chosen=dict(news_registry.PUBLISHERS), network=self.feeds)
        self.desk = replace(desk, text_fetcher=news_texts.fetcher(httpx.MockTransport(self.pages)))
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, [news_registry.PUBLISHERS["whitehouse-news"]],
                           lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        news_stories.merge(self.desk.newsroom, self.story_id("SYNTHETIC: Imposing tariffs on imported widgets"), {
            "into": self.story_id(FACT_TITLE), "reason": "One development", "idempotency_key": "merge-key-0001"},
            "setup", START)

    def story_id(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, NOW)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def story(self, title: str = FACT_TITLE) -> dict:
        return news_views.world(self.desk, NOW)["stories"][self.story_id(title)]

    def retrieve(self, title: str = FACT_TITLE) -> list[dict]:
        story = self.story(title)
        return news_texts.retrieve_all(self.desk.texts, [row for row in story["reports"]], {}, self.desk.text_fetcher,
                                       lambda: NOW, sleep=lambda seconds: None)

    def publish_brief(self) -> dict:
        story = self.story()
        content = {"headline": "SYNTHETIC widget tariff", "summary": "The White House said a tariff applies.",
                   "facts": [{"text": "A tariff on widgets was announced.",
                              "reports": [story["material"]["reports"][0]["entry_id"]]}],
                   "implications": [{"text": "SYNTHETIC: widget buyers could pay more if it applies."}], "themes": [],
                   "uncertainties": ["SYNTHETIC: the rate is not in the excerpt."], "missing": []}
        done, _ = story_briefs.add_version(self.desk.newsroom, story["story_id"], {
            "content": content, "method": "editorial", "based_on": None, "idempotency_key": "brief-key-0001"},
            story["material"], "setup", START)
        story_briefs.publish(self.desk.newsroom, story["story_id"], {"version": done["version"], "reason": "ok",
                                                                     "idempotency_key": "publish-key-0001"},
                             "setup", START)
        return story


class PageTextTest(unittest.TestCase):
    def test_each_layout_reads_its_publication_and_nothing_around_it(self):
        read = page_text.read_page(wh_page(FACT_TITLE, [WORDS]), "text/html; charset=UTF-8", page_text.WHITE_HOUSE)
        self.assertEqual((read["title"], read["date"], read["partial"]), (FACT_TITLE, "2026-10-14T08:30:00-04:00",
                                                                          False))
        self.assertTrue(read["text"].startswith("SYNTHETIC: Today the President signed"))
        self.assertIn("- SYNTHETIC second point, with emphasis.", read["text"])
        self.assertNotIn("Share this", read["text"])
        self.assertNotIn(FACT_TITLE, read["text"])  # The title block is the page's, not the publication's words.
        ustr = (b'<html><head><meta charset="utf-8"></head><body><h1>SYNTHETIC USTR title</h1><article>'
                b'<div class="field field--name-body"><p><strong>WASHINGTON</strong> \xe2\x80\x94 ' +
                WORDS.encode() + b'</p><p>###</p></div></article></body></html>')
        self.assertTrue(page_text.read_page(ustr, "text/html", page_text.USTR)["text"].startswith("WASHINGTON"))
        eia = (b'<html><body><h1>EIA site</h1><div class="tie-article"><div class="article-type">In-brief analysis'
               b'</div><span class="date">October 22, 2026</span><h1>SYNTHETIC refinery title</h1>'
               b'<div class="source">Data source: SYNTHETIC</div><p>' + WORDS.encode() + b'</p></div></body></html>')
        read = page_text.read_page(eia, "text/html; charset=UTF-8", page_text.EIA)
        self.assertEqual((read["title"], read["date"]), ("SYNTHETIC refinery title", "October 22, 2026"))
        self.assertNotIn("Data source", read["text"])
        wto = ('<html><head><meta charset="iso-8859-1"></head><body><h1 id="newsTitle">SYNTHETIC WTO title</h1>'
               f'<div class="centerCol" id="mainContent"><p>{WORDS} Caf\xe9.</p></div></body></html>').encode("latin-1")
        self.assertIn("Café", page_text.read_page(wto, "text/html", page_text.WTO)["text"])

    def test_a_page_that_is_not_the_layout_or_not_its_encoding_is_refused_whole(self):
        with self.assertRaises(page_text.Unreadable):
            page_text.read_page(b"<html><body><p>SYNTHETIC</p></body></html>", "text/html", page_text.WHITE_HOUSE)
        with self.assertRaises(page_text.Unreadable):  # Too little text to be the publication.
            page_text.read_page(wh_page("x", ["Too short."]).replace(b"SYNTHETIC first point of the fact sheet.", b"")
                                .replace(b"SYNTHETIC second point, with <strong>emphasis</strong>.", b""),
                                "text/html", page_text.WHITE_HOUSE)
        with self.assertRaises(page_text.Unreadable):  # The header and the page disagree, or name another encoding.
            page_text.read_page(wh_page(FACT_TITLE, [WORDS]), "text/html; charset=windows-1252", page_text.WHITE_HOUSE)
        wto = (b'<html><head><meta charset="iso-8859-1"></head><body><div id="mainContent"><p>' + WORDS.encode() +
               b' \x92quoted\x92</p></div></body></html>')
        with self.assertRaises(page_text.Unreadable):  # 0x80-0x9F in ISO-8859-1 are not guessed.
            page_text.read_page(wto, "text/html", page_text.WTO)

    def test_a_table_is_left_out_and_named_and_a_long_text_is_kept_partly(self):
        read = page_text.read_page(wh_page(FACT_TITLE, [WORDS], table=True), "text/html", page_text.WHITE_HOUSE)
        self.assertTrue(read["partial"])
        self.assertIn("1 table not flattened", read["partial_reason"])
        self.assertNotIn("SYNTHETIC cell", read["text"])
        long = wh_page(FACT_TITLE, [f"{WORDS} ({number})" for number in range(400)])
        read = page_text.read_page(long, "text/html", page_text.WHITE_HOUSE)
        self.assertTrue(read["partial"] and read["characters"] <= page_text.MAX_CHARACTERS)
        self.assertIn("longer than 60,000 characters", read["partial_reason"])


class RetrievalTest(unittest.TestCase):
    def test_each_page_is_requested_once_kept_and_reused_and_reading_requests_nothing(self):
        world = TextWorld(self)
        self.assertEqual({row["action"] for row in news_texts.plan(world.desk.texts, world.story()["reports"])},
                         {"request"})
        done = world.retrieve()
        self.assertEqual(sorted(row["outcome"] for row in done), ["retrieved", "retrieved"])
        self.assertEqual(sorted(world.pages.requests), sorted([FACT, ACTION]))
        again = world.retrieve()
        self.assertEqual([row["outcome"] for row in again], ["reused", "reused"])
        self.assertEqual(len(world.pages.requests), 2)  # A kept text is never requested again.
        snapshot = news_texts.snapshots(world.desk.texts, world.story()["reports"][0]["entry_id"])[-1]
        for key in ("url", "retrieved_at", "raw_sha256", "extractor", "text_version", "title", "date_printed",
                    "characters", "text_sha256", "coverage", "attribution", "basis", "entry_version_sha256"):
            self.assertIn(key, snapshot)
        self.assertEqual(snapshot["extractor"], "whitehouse-page-text-0.1")
        self.assertIsNotNone(news_texts.text_of(world.desk.texts, snapshot))
        records = sorted((world.desk.texts / "retrievals").glob("*.json"))
        self.assertEqual(len(records), 2)
        before = every_file(world.world.root)
        page = news_views.story_view(world.desk, world.story()["story_id"], NOW)
        news_views.stories_view(world.desk, "hot", [], NOW)
        self.assertEqual(every_file(world.world.root), before)
        self.assertEqual(len(world.pages.requests), 2)
        self.assertEqual({row["text"]["state"] for row in page["sources"]}, {"full_text"})

    def test_failures_say_why_and_leave_the_excerpt_in_use(self):
        world = TextWorld(self)
        broken = world.story("SYNTHETIC: A fact sheet whose page cannot be read")
        done = world.retrieve("SYNTHETIC: A fact sheet whose page cannot be read")
        self.assertEqual(done[0]["outcome"], "unreadable")
        state = news_texts.text_state(world.desk.texts, broken["reports"][0])
        self.assertEqual(state["state"], "failed")
        self.assertIn("layout", state["detail"])
        page = news_views.story_view(world.desk, broken["story_id"], NOW)
        self.assertEqual(page["sources"][0]["text"]["state"], "failed")
        self.assertEqual(world.story("SYNTHETIC: A fact sheet whose page cannot be read")["material"]["coverage"],
                         "headlines_and_excerpts")
        world.pages.answers[FACT] = (500, b"", "text/html")
        self.assertEqual(world.retrieve()[0]["outcome"], "failed")
        self.assertEqual(world.retrieve()[0]["outcome"], "failed")  # Each explicit retrieval tries once, no retry.
        self.assertEqual(world.pages.requests.count(FACT), 2)

    def test_only_listed_publishers_pages_are_requested(self):
        world = TextWorld(self)
        techcrunch = {"source": "techcrunch", "link": "https://techcrunch.com/2026/10/14/synthetic/", "entry_id":
                      "techcrunch:0123456789abcdef0123", "version_sha256": "0" * 64, "publisher": "TechCrunch",
                      "title": "SYNTHETIC"}
        self.assertEqual(news_texts.retrieve(world.desk.texts, techcrunch, "", world.desk.text_fetcher)["outcome"],
                         "not_supported")
        with self.assertRaises(Exception):
            world.desk.text_fetcher.fetch("https://techcrunch.com/2026/10/14/synthetic/")
        with self.assertRaises(Exception):
            world.desk.text_fetcher.fetch("https://www.whitehouse.gov/?s=search")
        self.assertEqual(world.pages.requests, [])
        self.assertIsNone(news_texts.supported("whitehouse-news", "https://www.whitehouse.gov/fact-sheets/x#frag"))
        self.assertIsNotNone(news_texts.supported("eia-todayinenergy",
                                                  "https://www.eia.gov/todayinenergy/detail.php?id=68344"))
        self.assertIsNone(news_texts.supported("eia-todayinenergy",
                                               "https://www.eia.gov/todayinenergy/detail.php?id=1&x=2"))


EC_PAGE = "https://ec.europa.eu/commission/presscorner/detail/en/speech_26_2252"
EC_ADDRESS = ("https://ec.europa.eu/commission/presscorner/api/documents?reference=SPEECH/26/2252&language=en")


def ec_answer(html: str, title: str = "SYNTHETIC remarks on trade", attachments: list | None = None) -> bytes:
    """A SYNTHETIC answer in the shape of the Commission's documents service."""
    return json.dumps({"refCd": "SPEECH/26/2252", "publishDate": "2026-10-23T17:03:04.000+02:00",
                       "docuLanguageResource": {"title": title, "htmlContent": html, "language": "EN",
                                                "attachmentResources": attachments or []}}).encode("utf-8")


class CommissionTextTest(unittest.TestCase):
    """The European Commission's press-corner pages are drawn by a script; their text is read from the documents
    service's answer for the page (SYNTHETIC answers on a simulated network)."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.seen: list[tuple[str, str]] = []
        self.answer = ec_answer(f"<p>{WORDS}</p><ul><li>SYNTHETIC first measure.</li></ul>"
                                "<table><tr><td>SYNTHETIC cell</td></tr></table>")

        def network(request: httpx.Request) -> httpx.Response:
            self.seen.append((str(request.url), request.headers.get("accept", "")))
            if str(request.url) == EC_ADDRESS:
                return httpx.Response(200, content=self.answer, headers={"content-type": "application/json"})
            return httpx.Response(404, content=b"not here", headers={"content-type": "text/html"})
        self.fetch = news_texts.fetcher(httpx.MockTransport(network))
        self.report = {"source": "ec-press", "link": EC_PAGE, "entry_id": "ec-press:0123456789abcdef0123",
                       "version_sha256": "0" * 64, "publisher": "European Commission", "title": "SYNTHETIC"}

    def test_the_documents_service_is_asked_for_the_page_and_its_text_kept_like_any_page(self):
        self.assertIsNotNone(news_texts.supported("ec-press", EC_PAGE))
        self.assertEqual(news_texts.request_address(news_texts.SOURCES["ec-press"], EC_PAGE), EC_ADDRESS)
        self.assertEqual(news_texts.plan(self.root, [self.report])[0]["action"], "request")
        done = news_texts.retrieve(self.root, self.report, "European Commission (© European Union)", self.fetch,
                                   lambda: NOW)
        self.assertEqual((done["outcome"], done["coverage"]), ("retrieved", "partial_text"))  # A table left out.
        self.assertEqual(self.seen, [(EC_ADDRESS, "application/json")])
        snapshot = news_texts.snapshots(self.root, self.report["entry_id"])[-1]
        self.assertEqual((snapshot["extractor"], snapshot["title"], snapshot["url"]),
                         ("ec-presscorner-text-0.1", "SYNTHETIC remarks on trade", EC_PAGE))
        self.assertEqual(snapshot["date_printed"], "2026-10-23T17:03:04.000+02:00")
        text = news_texts.text_of(self.root, snapshot)
        self.assertTrue(text.startswith("SYNTHETIC: Today the President signed"))
        self.assertIn("- SYNTHETIC first measure.", text)
        self.assertNotIn("SYNTHETIC cell", text)
        self.assertTrue((self.root / "raw" / f"{snapshot['raw_sha256']}.json").is_file())
        self.assertEqual(news_texts.retrieve(self.root, self.report, "", self.fetch, lambda: NOW)["outcome"], "reused")
        self.assertEqual(len(self.seen), 1)

    def test_only_the_documents_address_is_requested_and_an_answer_without_a_document_is_refused(self):
        self.assertFalse(news_texts.allowed(EC_PAGE))  # The script-drawn page itself is never requested.
        self.assertTrue(news_texts.allowed(EC_ADDRESS))
        for other in (EC_ADDRESS.replace("language=en", "language=fr"), EC_ADDRESS + "&x=1",
                      "https://ec.europa.eu/commission/presscorner/api/search?text=x"):
            self.assertFalse(news_texts.allowed(other))
        self.assertIsNone(news_texts.supported("ec-press", "https://ec.europa.eu/commission/presscorner/home/en"))
        self.answer = json.dumps({"docuLanguageResource": None}).encode()
        done = news_texts.retrieve(self.root, self.report, "", self.fetch, lambda: NOW)
        self.assertEqual(done["outcome"], "unreadable")
        self.assertEqual(news_texts.text_state(self.root, self.report)["state"], "failed")
        with self.assertRaises(page_text.Unreadable):
            page_text.ec_document(ec_answer(f"<p>{WORDS}</p>"), "text/html")
        read = page_text.ec_document(ec_answer(f"<p>{WORDS}</p>", attachments=[{"title": "SYNTHETIC Q&A"}]),
                                     "application/json")
        self.assertEqual(read["left_out"], [{"kind": "attachment", "text": "Attachment not read: SYNTHETIC Q&A"}])


class MaterialTest(unittest.TestCase):
    def test_retained_text_becomes_the_material_and_a_brief_says_it_covers_earlier_material(self):
        world = TextWorld(self)
        story = world.publish_brief()
        self.assertEqual(story["material"]["material_version"], story_briefs.MATERIAL_VERSION)
        self.assertTrue(news_views.story_view(world.desk, story["story_id"], NOW)["brief"]["current"])
        world.retrieve()
        enriched = world.story()
        self.assertEqual(enriched["material"]["coverage"], "full_text")
        self.assertEqual(enriched["material"]["material_version"], story_briefs.TEXT_MATERIAL_VERSION)
        self.assertIn("full text of 2 official publications", enriched["material"]["statement"])
        self.assertNotEqual(enriched["material"]["material_sha256"], story["material"]["material_sha256"])
        page = news_views.story_view(world.desk, story["story_id"], NOW)
        self.assertFalse(page["brief"]["current"])
        self.assertIn("earlier material", page["brief"]["update_note"])
        self.assertEqual(ns.state(world.desk.newsroom)["briefs"][story["story_id"]][0]["material"]["coverage"],
                         "headlines_and_excerpts")  # The earlier version keeps what it was prepared from.

    def test_the_material_statements_wording_is_pinned_because_it_is_part_of_the_materials_sha256(self):
        world = TextWorld(self)
        world.retrieve("SYNTHETIC: A fact sheet whose page cannot be read")
        single = world.story()
        world.retrieve()
        self.assertEqual(world.story()["material"]["statement"], "Prepared from the full text of 2 official "
                         "publications, as this server retrieved them from the publishers' own pages.")
        rows = [{"publisher": "P", "excerpt": "x", "text": {"state": "full_text", "partial_reason": None}}]
        self.assertEqual(story_briefs._statement(rows), ("full_text", "Prepared from the full text of 1 official "
                         "publication, as this server retrieved them from the publishers' own pages."))
        self.assertEqual(single["material"]["coverage"], "headlines_and_excerpts")

    def test_a_partial_text_is_said_to_be_partial(self):
        world = TextWorld(self)
        world.retrieve("SYNTHETIC: A fact sheet holding a table")
        material = world.story("SYNTHETIC: A fact sheet holding a table")["material"]
        self.assertEqual(material["coverage"], "partial_text")
        self.assertIn("table not flattened", material["statement"])

    def test_the_paid_drafts_request_carries_the_publication_text(self):
        world = TextWorld(self)
        world.retrieve()
        preview = brief_drafting.preview(world.desk, world.story())
        body = json.loads((world.desk.newsroom.path.parent / "drafting" / preview["draft_id"] / "request.json")
                          .read_bytes())
        message = body["messages"][0]["content"]
        self.assertIn("Publication text (full text, retrieved", message)
        self.assertIn("12% tariff on imported widgets, effective November 1, 2026", message)
        # Feed metadata may contain a lead omitted from the extracted publication body; retain both.
        self.assertIn("Excerpt: SYNTHETIC excerpt", message)
        self.assertIn("insufficient_material", body["output_config"]["format"]["schema"]["properties"])
        # brief-prompt-3: a structured output format, never a forced tool (which Claude Sonnet 5.5 refuses).
        self.assertNotIn("tool_choice", body)
        self.assertNotIn("tools", body)
        self.assertEqual((body["thinking"], body["output_config"]["effort"]), ({"type": "adaptive"}, "low"))

    def test_a_model_that_judges_the_material_insufficient_records_that_and_no_version(self):
        world = TextWorld(self)
        model = BriefModel("sk-ant-dummy-simulated-drafting-key-0001")
        original = model.handler

        def insufficient(request: httpx.Request) -> httpx.Response:
            from news_desk_fakes import insufficient_economics
            reply = json.loads(original(request).content)
            reply["content"][-1]["text"] = json.dumps(stage_replies({  # Stage 1's answer.
                "headline": "", "summary": "", "facts": [], "implications": [], "themes": [], "uncertainties": [],
                "missing": [], "insufficient_material": "SYNTHETIC: the excerpt names no measure.",
                "economics": insufficient_economics()})[0])
            return httpx.Response(200, content=json.dumps(reply).encode(), headers={"content-type": "application/json"})
        model.handler = insufficient
        desk = replace(world.desk, drafting=model.sender())
        story = world.story("SYNTHETIC: A fact sheet whose page cannot be read")
        preview = brief_drafting.preview(desk, story)
        done, sent = brief_drafting.approve(desk, preview["draft_id"], {
            "request_sha256": preview["request_sha256"], "approve_paid_request": True,
            "estimated_max_usd": preview["estimate"]["estimated_real_run_if_output_reaches_max_usd"]},
            lambda story_id: news_views.world(desk, NOW)["stories"][story_id], "admin-1", lambda: NOW)
        self.assertTrue(sent)
        self.assertEqual(done["attempt"]["state"], "insufficient")
        page = news_views.story_view(desk, story["story_id"], NOW)
        self.assertEqual(page["brief_state"], "insufficient")
        self.assertIn("names no measure", page["brief_note"])
        self.assertNotIn(story["story_id"], ns.state(desk.newsroom)["briefs"])


class DeeperTextTest(unittest.TestCase):
    def test_go_deeper_reads_the_retained_text_never_the_shared_brief(self):
        world = TextWorld(self)
        world.publish_brief()
        world.retrieve()
        reader = world.world.client("reader-a", desk=world.desk)
        story_id = world.story()["story_id"]
        preview = reader.get(f"/api/user/news/stories/{story_id}/deeper").json()["deeper"]
        text = preview["source"]["text"]
        self.assertIn("What this is: the text of 2 publications", text)
        self.assertIn("12% tariff on imported widgets, effective November 1, 2026", text)
        self.assertIn("The shared brief of this story is not included", text)
        self.assertNotIn("widget buyers could pay more", text)  # The brief's implication is not evidence.
        self.assertEqual(preview["material"]["coverage"], "full_text")
        done = reader.post(f"/api/user/news/stories/{story_id}/deeper", headers=USER_WRITE, json={
            "material_sha256": preview["material_sha256"], "effort": "low"})
        self.assertEqual(done.status_code, 201, done.text)
        source_id = done.json()["deeper"]["source"]["source_id"]
        origin = json.loads((world.desk.deeper / f"{source_id}.json").read_bytes())
        self.assertTrue(all(row["text_sha256"] for row in origin["reports"]))
        self.assertIn("never the shared brief", origin["statement"])
        other = world.world.client("reader-b", desk=world.desk)
        self.assertIsNone(other.get(f"/api/user/news/stories/{story_id}/deeper").json()["deeper"]["existing"])
        self.assertEqual(world.world.provider.requests, [])

    def test_a_text_too_long_for_the_source_limit_is_shortened_and_says_so(self):
        world = TextWorld(self)
        long = wh_page(FACT_TITLE, [f"{WORDS} Paragraph {number}." for number in range(260)])
        world.pages.answers[FACT] = (200, long, "text/html; charset=UTF-8")
        world.retrieve()
        story = world.story()
        text = story_deeper.source_text(story, story["material"], "user-1", world.desk.texts)
        self.assertLessEqual(len(text), story_deeper.MAX_SOURCE_CHARS)
        self.assertIn("[Shortened here to fit the source limit:", text)


class TextRoutesTest(unittest.TestCase):
    def test_the_desk_previews_then_retrieves_counting_only_what_it_requests(self):
        world = TextWorld(self)
        admin = world.world.client("admin", desk=world.desk)
        story_id = world.story()["story_id"]
        plan = admin.get(f"/api/admin/news/stories/{story_id}/texts").json()["texts"]["plan"]
        self.assertEqual([row["action"] for row in plan], ["request", "request"])
        self.assertEqual(world.pages.requests, [])
        done = admin.post(f"/api/admin/news/stories/{story_id}/texts", headers=ADMIN_WRITE, json={})
        self.assertEqual(done.status_code, 200, done.text)
        self.assertEqual(done.json()["texts"]["requests"], 2)
        from second_order import usage
        fetches = lambda: usage.overview(world.world.accounts, world.world.root / "intake",  # noqa: E731
                                         world.world.clock())["server"]["publication_fetches"]["used"]
        self.assertEqual(fetches(), 2)
        again = admin.post(f"/api/admin/news/stories/{story_id}/texts", headers=ADMIN_WRITE, json={}).json()
        self.assertEqual(again["texts"]["requests"], 0)
        self.assertEqual(fetches(), 2)  # A kept text is reused and not counted.
        self.assertEqual(world.world.client("reader-a", desk=world.desk).post(
            f"/api/admin/news/stories/{story_id}/texts", headers=ADMIN_WRITE, json={}).status_code, 403)

    def test_the_command_checks_without_requesting_and_retrieves_on_request(self):
        world = TextWorld(self)
        from argparse import Namespace
        story_id = world.story()["story_id"]
        checked = news_cli.run(Namespace(news_action="texts", story=[story_id], hot=False, limit=30, check=True),
                               world.desk)
        self.assertEqual((checked["requests"], world.pages.requests), (2, []))
        done = news_cli.run(Namespace(news_action="texts", story=[story_id], hot=False, limit=1, check=False),
                            world.desk)
        self.assertEqual(done["requests"], 1)  # The run's limit is kept.
        self.assertEqual([row["outcome"] for row in done["outcomes"]], ["retrieved", "not_requested"])


if __name__ == "__main__":
    unittest.main()
