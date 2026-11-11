"""news-registry-0.5: three newsrooms connected through their own terms (Voice of America, Global Voices, Inter Press
Service), each feed skipping the entries it carries for other publishers before anything of them is kept, and
crediting each entry's author where the licence asks for it. Every feed response here is SYNTHETIC; the addresses are
the registered ones, answered by a simulated network."""
from dataclasses import replace
from datetime import timedelta
import hashlib
from html import escape
import json
from pathlib import Path
import tempfile
import unittest

from news_desk_fakes import Feeds, START, desk_in, rfc822, synthetic_annotation
from second_order import (event_inbox, feed_credits, inbox_archive, news_feeds, news_matching, news_registry, news_relevance,
                          news_reports, news_stories, news_views, relevance_requests)

NEWSROOMS = ("voa-news", "globalvoices", "ips-economy")
NOW = START + timedelta(hours=6)
CONTENT = 'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:content="http://purl.org/rss/1.0/modules/content/"'


def entry(host: str, slug: str, title: str, at, excerpt: str | None = None, author: str | None = None,
          creator: str | None = None, body: str | None = None) -> str:
    link = f"https://{host}/2026/10/{slug}/"
    parts = [f"<title>{escape(title)}</title>", f"<link>{link}</link>", f"<guid>{link}</guid>",
             f"<pubDate>{rfc822(at)}</pubDate>"]
    if excerpt is not None:
        parts.append(f"<description>{escape(excerpt)}</description>")
    if author is not None:
        parts.append(f"<author>{escape(author)}</author>")
    if creator is not None:
        parts.append(f"<dc:creator>{escape(creator)}</dc:creator>")
    if body is not None:
        parts.append(f"<content:encoded>{escape(body)}</content:encoded>")
    return "<item>" + "".join(parts) + "</item>"


def feed(items: list[str]) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?><rss version="2.0" {CONTENT}><channel><title>Synthetic</title>'
            + "".join(items) + "</channel></rss>").encode("utf-8")


def voa_feed() -> bytes:
    host = "www.voanews.com"
    return feed([
        entry(host, "staff", "Synthetic VOA staff report on port fees", START,
              "The Synthetic Harbour Authority raised port fees to $4.5 billion a year, VOA's reporter writes.",
              author="webdesk@voanews.com (Jane Synthetic)"),
        entry(host, "wire-ap", "Synthetic AP-WIRE-HEADLINE carried by VOA", START, "Synthetic AP-WIRE-EXCERPT.",
              author="webdesk@voanews.com (Associated Press)"),
        entry(host, "wire-reuters", "Synthetic REUTERS-WIRE-HEADLINE carried by VOA", START, "Synthetic text.",
              author="webdesk@voanews.com (Reuters)")])


def gv_feed(old=START - timedelta(days=10)) -> bytes:
    host = "globalvoices.org"
    return feed([
        entry(host, "own", "Synthetic Global Voices report on a harbour strike", old,
              "Synthetic dockworkers stopped work for two days.", creator="Synthetic Author",
              body="<p>Originally published on Global Voices</p><p>GV-FULL-TEXT-NEVER-KEPT</p>"),
        entry(host, "partner", "Synthetic PARTNER-HEADLINE republished by Global Voices", START,
              "Synthetic partner summary.", creator="Synthetic Partner Org",
              body="<p>An edited version is republished here as part of a content-sharing agreement.</p>"),
        entry(host, "first", "Synthetic FIRST-PUBLISHED-HEADLINE excerpt", START, "Synthetic summary.",
              creator="GV Contributor",
              body="<p>This article is an edited version of a longer piece, first published on June 11, 2026, by "
                   "a synthetic non-profit.</p>")])


def ips_feed() -> bytes:
    host = "www.ipsnews.net"
    return feed([
        entry(host, "harbour", "Synthetic IPS report on harbour strike talks", START,
              "IPS-EXCERPT-NEVER-KEPT synthetic description.", creator="Synthetic Correspondent",
              body="<p>IPS-FULL-TEXT-NEVER-KEPT</p>"),
        entry(host, "external", "Synthetic EXTERNAL-SOURCE-HEADLINE", START, "Synthetic.", creator="External Source")])


def answers() -> dict:
    registry = news_registry.PUBLISHERS
    return {registry["voa-news"].feed.feed_url: (200, voa_feed()), registry["globalvoices"].feed.feed_url:
            (200, gv_feed()), registry["ips-economy"].feed.feed_url: (200, ips_feed())}


def files_text(folder: Path) -> str:
    return "\n".join(path.read_bytes().decode("utf-8", "replace") for path in folder.rglob("*") if path.is_file())


class RegistryTest(unittest.TestCase):
    def test_three_newsrooms_are_connected_each_with_what_its_own_terms_allow(self):
        self.assertEqual(news_registry.REGISTRY_VERSION, "news-registry-0.5")
        rows = {key: news_registry.PUBLISHERS[key] for key in NEWSROOMS}
        self.assertTrue(set(NEWSROOMS) <= {publisher.key for publisher in news_registry.connected()})
        for key, publisher in rows.items():
            self.assertEqual((publisher.role, publisher.status, publisher.interest), ("news", "connected", None), key)
            self.assertIn("2026-10-26", publisher.checked, key)
            self.assertTrue(publisher.attribution and publisher.terms_url.startswith("https://"), key)
            self.assertFalse(publisher.feed.keep_raw, key)  # No complete third-party response is kept.
            self.assertFalse(publisher.feed.contact_required, key)
            self.assertTrue(publisher.feed.feed_url.startswith(f"https://{publisher.feed.link_host}/"), key)
        self.assertEqual((rows["voa-news"].display, rows["voa-news"].material), ("headline_excerpt", "permitted"))
        self.assertEqual((rows["globalvoices"].display, rows["globalvoices"].material),
                         ("headline_excerpt", "permitted"))
        self.assertTrue(rows["voa-news"].material_basis and rows["globalvoices"].material_basis)
        self.assertEqual((rows["ips-economy"].display, rows["ips-economy"].material), ("headline", "none"))
        self.assertFalse(rows["ips-economy"].feed.excerpts)  # Titles and headlines only, by IPS's own terms.
        self.assertTrue(rows["globalvoices"].feed.credit_creator)  # CC BY: the author is credited.

    def test_examined_newsrooms_that_are_not_usable_are_recorded_without_a_feed(self):
        for key in ("the-conversation", "agencia-brasil"):
            publisher = news_registry.PUBLISHERS[key]
            self.assertEqual((publisher.status, publisher.feed, publisher.material), ("not_connected", None, "none"))
            self.assertTrue(publisher.agreement and publisher.note, key)
        with tempfile.TemporaryDirectory() as directory:
            network = Feeds({})
            desk = desk_in(Path(directory), dict(news_registry.PUBLISHERS), network)
            with self.assertRaises(Exception):
                desk.fetcher.fetch("https://theconversation.com/us/business/articles.atom")
            self.assertEqual(network.requests, [])


class RefreshTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.network = Feeds(answers())
        self.desk = desk_in(self.root, dict(news_registry.PUBLISHERS), self.network)
        self.publishers = [news_registry.PUBLISHERS[key] for key in NEWSROOMS]
        self.view = news_feeds.refresh(self.desk.feeds, self.desk.fetcher, self.publishers, lambda: NOW)

    def reports(self) -> dict[str, dict]:
        pool = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        return {row["title"]: row for row in pool.values()}

    def test_each_feed_is_requested_once_and_reading_requests_nothing(self):
        self.assertEqual(sorted(self.network.requests), sorted(p.feed.feed_url for p in self.publishers))
        self.assertEqual([row["outcome"] for row in self.view["refreshed"]], ["ok"] * 3)
        before = files_text(self.root)
        self.reports()
        news_views.world(self.desk, NOW)
        self.assertEqual(len(self.network.requests), 3)
        self.assertEqual(files_text(self.root), before)

    def test_wire_stories_are_skipped_before_anything_of_them_is_kept(self):
        titles = set(self.reports())
        self.assertIn("Synthetic VOA staff report on port fees", titles)
        kept = files_text(self.root)
        for marker in ("AP-WIRE-HEADLINE", "AP-WIRE-EXCERPT", "REUTERS-WIRE-HEADLINE"):
            self.assertNotIn(marker, kept)  # Not in the record, the archive or the retrieval record.
        record = json.loads((self.root / "news-feeds" / "voa-news.json").read_bytes())
        reasons = [row["reason"] for row in record["last_success"]["skipped"]]
        self.assertEqual(reasons, ["Skipped: credited to Associated Press, whose material this publisher's terms "
                                   "exclude", "Skipped: credited to Reuters, whose material this publisher's terms "
                                   "exclude"])

    def test_partner_articles_are_skipped_and_the_full_text_is_never_kept(self):
        titles = set(self.reports())
        self.assertIn("Synthetic Global Voices report on a harbour strike", titles)
        kept = files_text(self.root)
        for marker in ("PARTNER-HEADLINE", "FIRST-PUBLISHED-HEADLINE", "GV-FULL-TEXT-NEVER-KEPT"):
            self.assertNotIn(marker, kept)
        record = json.loads((self.root / "news-feeds" / "globalvoices.json").read_bytes())
        self.assertEqual(record["last_success"]["skipped_count"], 2)
        self.assertTrue(all("marked as another publisher's work" in row["reason"]
                            for row in record["last_success"]["skipped"]))

    def test_a_global_voices_report_credits_its_author_and_keeps_its_own_date(self):
        report = self.reports()["Synthetic Global Voices report on a harbour strike"]
        self.assertEqual(report["attribution"], "By Synthetic Author for Global Voices (CC BY 3.0, "
                                                "https://creativecommons.org/licenses/by/3.0/)")
        self.assertEqual((report["at"], report["at_basis"]), ((START - timedelta(days=10)).isoformat(), "published"))
        self.assertEqual(report["excerpt"], "Synthetic dockworkers stopped work for two days.")
        self.assertEqual(self.reports()["Synthetic VOA staff report on port fees"]["attribution"],
                         "Voice of America (voanews.com)")  # Public domain: the credit VOA asks for, no byline.

    def test_ips_is_headline_only_and_never_material(self):
        reports = self.reports()
        self.assertNotIn("Synthetic EXTERNAL-SOURCE-HEADLINE", reports)  # Credited to "External Source": skipped.
        report = reports["Synthetic IPS report on harbour strike talks"]
        self.assertEqual((report["excerpt"], report["display"], report["material"]), (None, "headline", "none"))
        kept = files_text(self.root)
        self.assertNotIn("IPS-EXCERPT-NEVER-KEPT", kept)
        self.assertNotIn("IPS-FULL-TEXT-NEVER-KEPT", kept)
        self.assertNotIn("Synthetic Correspondent", kept)  # No creator is kept where none must be credited.

    def test_the_new_rules_are_recorded_as_parser_0_2_only_for_the_feeds_that_use_them(self):
        self.assertEqual(event_inbox.parser_version(news_registry.VOA_NEWS), feed_credits.VERSION)
        self.assertEqual(event_inbox.parser_version(news_registry.TECHCRUNCH), "event-inbox-parser-0.1")
        self.assertEqual(event_inbox.parser_version(event_inbox.SOURCES["fed-monetary"]), "event-inbox-parser-0.1")
        records = list((self.root / "news-feeds").rglob("acquisitions/voa-news/*.json"))
        self.assertTrue(records)
        self.assertEqual(json.loads(records[0].read_bytes())["parser"]["version"], "event-inbox-parser-0.2")

    def test_a_credited_author_stays_with_the_entry_after_it_leaves_the_feed(self):
        quiet = Feeds({news_registry.GLOBAL_VOICES.feed_url: (200, feed([]))})
        fetcher = news_feeds.fetcher_for([news_registry.PUBLISHERS["globalvoices"]], quiet.transport())
        news_feeds.refresh(self.desk.feeds, fetcher, [news_registry.PUBLISHERS["globalvoices"]],
                           lambda: NOW + timedelta(hours=1))
        report = self.reports()["Synthetic Global Voices report on a harbour strike"]
        self.assertEqual(report["listing"], "retained")
        self.assertTrue(report["attribution"].startswith("By Synthetic Author for Global Voices"))


class CompatibilityTest(unittest.TestCase):
    def test_entries_without_a_creator_keep_their_fingerprint(self):
        item = {"title": "Synthetic", "title_truncated": False, "link": "https://example.org/a", "excerpt": None,
                "excerpt_truncated": False, "excerpt_repeats_title": False, "feed_timestamp": {"raw": None}}
        expected = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                                  .encode("utf-8")).hexdigest()
        self.assertEqual(inbox_archive.content_sha256(item), expected)
        self.assertNotEqual(inbox_archive.content_sha256({**item, "creator": "Synthetic Author"}), expected)

    def test_a_record_of_a_crediting_source_without_its_creator_is_not_trusted(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = news_registry.GLOBAL_VOICES
            network = Feeds({source.feed_url: (200, gv_feed())})
            news_feeds.refresh(folder, news_feeds.fetcher_for([news_registry.PUBLISHERS["globalvoices"]],
                                                              network.transport()),
                               [news_registry.PUBLISHERS["globalvoices"]], lambda: NOW)
            path = folder / "globalvoices.json"
            record = json.loads(path.read_bytes())
            self.assertEqual(event_inbox.read_record(folder, "globalvoices", source)[0], "ok")
            for item in record["last_success"]["items"]:
                item.pop("creator")
            path.write_text(json.dumps(record), encoding="utf-8")
            self.assertEqual(event_inbox.read_record(folder, "globalvoices", source)[0], "unreadable")
            state, _, _ = event_inbox.read_record(folder, "globalvoices", replace(source, credit_creator=False))
            self.assertEqual(state, "ok")  # The same record without credits is what an ordinary source keeps.


class StoriesTest(unittest.TestCase):
    """The new newsrooms' reports in stories: a newsroom with an excerpt is a confirmed origin beside an official
    release; a headline-only newsroom is a possible one; an AI assistant may judge a pair only when both stories have
    permitted material."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        white = news_registry.PUBLISHERS["whitehouse-news"].feed
        official = feed([entry(white.link_host, "proclamation", "Synthetic proclamation raising port fees by 12 "
                                                                 "percent", START, "A proclamation directs the "
                                                                                   "Synthetic Harbour Authority to "
                                                                                   "collect $4.5 billion in fees.")])
        network = Feeds({**answers(), white.feed_url: (200, official)})
        self.desk = desk_in(root, dict(news_registry.PUBLISHERS), network)
        chosen = [news_registry.PUBLISHERS[key] for key in (*NEWSROOMS, "whitehouse-news")]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, chosen, lambda: NOW)
        pool = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, pool, news_reports.publisher_names(self.desk.publishers),
                           "local-operator", NOW, "group-newsrooms-1")
        self.found = news_views.world(self.desk, NOW)
        self.by_title = {story["title"]: story for story in self.found["stories"].values()}

    def test_different_headlines_are_suggested_not_merged_and_only_permitted_pairs_go_to_an_assistant(self):
        self.assertEqual(len(self.found["stories"]), 4)  # Nothing merged by shared words alone.
        pairs = news_matching.candidates(self.found, NOW, limit=100)
        titles = [set(row["titles"].values()) for row in pairs]
        voa = "Synthetic VOA staff report on port fees"
        proclamation = "Synthetic proclamation raising port fees by 12 percent"
        match = next(row for row, names in zip(pairs, titles) if names == {voa, proclamation})
        self.assertTrue(match["assistant_may_judge"])  # Both are permitted material: VOA and the White House.
        ips = next((row for row, names in zip(pairs, titles) if "Synthetic IPS report on harbour strike talks" in names),
                   None)
        if ips is not None:
            self.assertFalse(ips["assistant_may_judge"])  # IPS gives headlines only: an editor judges it.

    def test_a_joined_newsroom_counts_as_a_confirmed_origin_and_a_headline_only_one_as_possible(self):
        voa = self.by_title["Synthetic VOA staff report on port fees"]
        proclamation = self.by_title["Synthetic proclamation raising port fees by 12 percent"]
        ips = self.by_title["Synthetic IPS report on harbour strike talks"]
        reports = proclamation["reports"] + voa["reports"]
        coverage = news_stories.coverage(reports, news_reports.publisher_names(self.desk.publishers))
        self.assertEqual((coverage["confirmed_official"], coverage["confirmed_news"], coverage["possible_news"]),
                         (1, 1, 0))
        coverage = news_stories.coverage(reports + ips["reports"],
                                         news_reports.publisher_names(self.desk.publishers))
        self.assertEqual((coverage["confirmed_news"], coverage["possible_news"]), (1, 1))
        self.assertEqual(ips["material"]["reports"], [])
        self.assertEqual(ips["relevance"]["state"], "restricted")  # Never sent to a model; an editor judges it.
        self.assertEqual(voa["relevance"]["state"], "pending")  # Permitted material: the assessment may run.



class InterestTest(unittest.TestCase):
    """A word alone does not decide a story's interest when its assessment says otherwise (seen on the real records:
    VOA's "Mobile internet tariffs in Iran rise by 40%" was labelled Trade because of the word "tariffs")."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        host = news_registry.VOA_NEWS.link_host
        answers = {news_registry.VOA_NEWS.feed_url: (200, feed([
            entry(host, "internet", "Synthetic mobile internet tariffs rise by 40%", START,
                  "Synthetic operators raised what subscribers pay for mobile data."),
            entry(host, "border", "Synthetic border tariffs raised on imported grain", START,
                  "Synthetic customs duties on imported grain doubled."),
            entry(host, "pending", "Synthetic tariffs debated in parliament", START, "Synthetic debate.")]))}
        self.desk = desk_in(Path(folder.name), dict(news_registry.PUBLISHERS), Feeds(answers))
        voa = [news_registry.PUBLISHERS["voa-news"]]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, voa, lambda: NOW)
        pool = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, pool, set(), "local-operator", NOW, "group-interests-1")
        for story_id, story in news_views.world(self.desk, NOW)["stories"].items():
            first = story["material"]["reports"][0]
            if "debated" in first["title"]:
                continue  # Never assessed: its words alone still give its interests.
            annotation = synthetic_annotation(first["entry_id"], " ".join(first["title"].split()[:4]))
            if "internet" in first["title"]:
                annotation["dimensions"][0]["dimension"] = "prices"
            checked = news_relevance.check_evidence(annotation, relevance_requests.sources([first], {}))
            news_relevance.record(self.desk.newsroom, story_id, story["material"]["material_sha256"], {
                "method": "synthetic", "outcome": "annotated", "annotation": annotation, "evidence": checked,
                "versions": relevance_requests.versions(), "preparation": {"synthetic": True}}, "synthetic-editor",
                NOW, f"syn-{story_id[6:]}")
        self.stories = {story["title"]: story for story in news_views.world(self.desk, NOW)["stories"].values()}

    def test_a_word_alone_does_not_label_a_price_change_as_trade(self):
        internet = self.stories["Synthetic mobile internet tariffs rise by 40%"]
        self.assertEqual(internet["relevance"]["state"], "relevant")
        self.assertNotIn("trade", internet["interests"])  # Assessed as prices, not trade.
        self.assertIn("trade", self.stories["Synthetic border tariffs raised on imported grain"]["interests"])
        self.assertIn("trade", self.stories["Synthetic tariffs debated in parliament"]["interests"])  # Unassessed.
        card = news_views.card(internet)
        self.assertNotIn("trade", card["interests"])


if __name__ == "__main__":
    unittest.main()
