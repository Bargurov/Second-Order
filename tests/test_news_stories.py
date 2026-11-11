"""Stories, coverage, ranking, topics and briefs over SYNTHETIC publisher feeds (news_desk_fakes): the registry, the
publisher-feed refresh, conservative grouping and the operator's curation, independence of coverage, the deterministic
ranking, and shared briefs with their material, guard and versions. Nothing reaches a network."""
from datetime import datetime, timedelta, timezone
import sqlite3
import tempfile
import unittest
from pathlib import Path

import httpx

from news_desk_fakes import (COURIER, LEDGER, RESPONSE, RESPONSE_OWN, REVISION, START, TARIFF, UNRELATED, Feeds,
                             assess, desk_in, item, publishers, rss, trade_feeds)
from second_order import (news_feeds, news_rank, news_registry, news_reports, news_stories, news_topics, news_views,
                          newsroom_store as ns, story_briefs)
from second_order.accounts import AccountsRefused

TECH = news_registry.TECHCRUNCH
PRN = news_registry.PR_NEWSWIRE


class World:
    """A desk over a temporary folder, its SYNTHETIC feeds refreshed once."""

    def __init__(self, test: unittest.TestCase, answers: dict | None = None, now: datetime = START):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.now = now
        self.network = Feeds(answers if answers is not None else trade_feeds(now))
        self.desk = desk_in(self.root, network=self.network)
        self.refreshable = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, self.refreshable, lambda: now)
        self.keys = iter(f"test-key-{number:06d}" for number in range(100_000))

    def reports(self) -> dict:
        return news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]

    def group(self) -> dict:
        summary, _ = news_stories.group(self.desk.newsroom, self.reports(), news_reports.publisher_names(
            self.desk.publishers), "admin-1", self.now, next(self.keys))
        assess(self.desk, self.now)  # SYNTHETIC: every story assessed as relevant, as a relevance batch would.
        return summary

    def found(self, now: datetime | None = None) -> dict:
        return news_views.world(self.desk, now or self.now)

    def story_of(self, title: str) -> dict:
        return next(story for story in self.found()["stories"].values()
                    if any(row["title"] == title for row in story["reports"]))

    def merge_response(self) -> None:
        """The operator's merge of the two independent reports of the response (different words, one development)."""
        news_stories.merge(self.desk.newsroom, self.story_of(RESPONSE_OWN)["story_id"], {
            "into": self.story_of(RESPONSE)["story_id"], "reason": "Two reports of the same response",
            "idempotency_key": self.key()}, "admin-1", self.now)

    def key(self) -> str:
        return next(self.keys)


class RegistryTest(unittest.TestCase):
    def test_every_candidate_is_recorded_with_its_access_conditions(self):
        names = {publisher.key for publisher in news_registry.PUBLISHERS.values()}
        for key in ("techcrunch", "prnewswire-business", "freightwaves", "cnbc", "bloomberg", "reuters", "ap",
                    "investing-com", "financial-times", "guardian", "yahoo-finance", *news_registry.OFFICIAL_INTEREST):
            self.assertIn(key, names)
        for publisher in news_registry.PUBLISHERS.values():
            self.assertIn(publisher.status, news_registry.STATUSES)
            self.assertIn(publisher.display, news_registry.DISPLAY)
            self.assertIn(publisher.material, news_registry.MATERIAL)
            self.assertTrue(publisher.terms_url.startswith("https://") and publisher.checked)
            self.assertFalse(publisher.synthetic)
            if publisher.status in ("needs_agreement", "needs_credentials", "not_connected"):
                self.assertTrue(publisher.agreement or publisher.credentials)

    def test_material_is_only_what_a_publishers_own_terms_allow(self):
        for publisher in news_registry.PUBLISHERS.values():
            if publisher.material == "permitted":  # Only where the publisher's terms allow it, with the basis stated.
                self.assertTrue(publisher.material_basis, publisher.key)
                self.assertNotEqual(publisher.role, "company", publisher.key)
            elif publisher.role == "official":
                self.assertNotEqual(publisher.status, "connected", publisher.key)
        # Newsrooms are material only when their own text is public domain or openly licensed (news-registry-0.5).
        self.assertEqual({key for key, publisher in news_registry.PUBLISHERS.items() if publisher.role == "news" and
                          publisher.material == "permitted"}, {"voa-news", "globalvoices"})
        self.assertEqual({publisher.key for publisher in news_registry.connected()}, {
            "techcrunch", "prnewswire-business", "whitehouse-news", "ustr-press", "ec-press", "ecb-press", "doj-antitrust", "boc-press", "sec-press", "ons-publications", "rba-releases", "census-indicators", "voa-news", "globalvoices", "ips-economy"})

    def test_company_statements_are_labelled_and_show_headlines_only(self):
        prn = news_registry.PUBLISHERS["prnewswire-business"]
        self.assertEqual((prn.role, prn.display, prn.feed.excerpts, prn.feed.keep_raw), ("company", "headline", False,
                                                                                          False))
        self.assertEqual(news_registry.ROLE_LABEL["company"], "Company statement")


class FeedsTest(unittest.TestCase):
    def feeds(self, answers):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        network = Feeds(answers)
        chosen = [news_registry.PUBLISHERS["techcrunch"], news_registry.PUBLISHERS["prnewswire-business"]]
        return root, network, news_feeds.fetcher_for(chosen, network.transport()), chosen

    def test_refresh_requests_each_connected_feed_once_and_keeps_only_what_it_may(self):
        answers = {TECH.feed_url: (200, rss([item("techcrunch.com", "a", "Synthetic startup raises a round", START,
                                                  "A SYNTHETIC excerpt.")])),
                   PRN.feed_url: (200, rss([item("www.prnewswire.com", "b", "Synthetic Corp. announces results",
                                                 START, "SYNTHETIC lead text of a release.")]))}
        root, network, fetcher, chosen = self.feeds(answers)
        result = news_feeds.refresh(root, fetcher, chosen, lambda: START)
        self.assertEqual(sorted(network.requests), sorted([TECH.feed_url, PRN.feed_url]))
        self.assertEqual([row["outcome"] for row in result["refreshed"]], ["ok", "ok"])
        by_source = {row["source"]: row for row in result["items"]}
        self.assertEqual(by_source["techcrunch"]["excerpt"], "A SYNTHETIC excerpt.")
        self.assertIsNone(by_source["prnewswire-business"]["excerpt"])  # Headlines only: the excerpt is never kept.
        self.assertNotIn(b"SYNTHETIC lead text", b"".join(path.read_bytes() for path in root.rglob("*") if path.is_file()))
        self.assertFalse((root / "raw").exists())  # No third-party response is kept whole.

    def test_a_failed_feed_keeps_its_earlier_entries_and_reading_requests_nothing(self):
        answers = {TECH.feed_url: (200, rss([item("techcrunch.com", "a", "Synthetic startup raises a round", START)])),
                   PRN.feed_url: (503, b"")}
        root, network, fetcher, chosen = self.feeds(answers)
        news_feeds.refresh(root, fetcher, chosen, lambda: START)
        network.answers[TECH.feed_url] = (500, b"")
        news_feeds.refresh(root, fetcher, chosen, lambda: START + timedelta(hours=1))
        before = len(network.requests)
        view = news_feeds.feed_view(root, chosen)
        self.assertEqual(len(network.requests), before)
        states = {row["key"]: row["state"] for row in view["sources"]}
        self.assertEqual(states, {"techcrunch": "failed", "prnewswire-business": "failed"})
        self.assertEqual([row["title"] for row in view["items"]], ["Synthetic startup raises a round"])
        self.assertTrue(view["items"][0]["stale"])

    def test_the_fetcher_refuses_any_address_outside_the_registry(self):
        root, network, fetcher, chosen = self.feeds({})
        with self.assertRaises(Exception):
            fetcher.fetch("https://www.cnbc.com/id/100003114/device/rss/rss.html")
        self.assertEqual(network.requests, [])


class GroupingTest(unittest.TestCase):
    def test_a_repeated_headline_joins_its_story_and_shared_keywords_never_merge(self):
        world = World(self)
        summary = world.group()
        found = world.found()
        tariff = world.story_of(TARIFF)
        self.assertEqual(len(tariff["reports"]), 2)  # The syndicated copy joined by the same-headline rule.
        joined = next(row for row in summary["joined"] if row["story_id"] == tariff["story_id"])
        self.assertEqual(joined["basis"]["rule"], "story-match-0.1/same-headline")
        self.assertIsNot(world.story_of(UNRELATED), tariff)  # "Synthetic Republic ... steel" alone merges nothing.
        self.assertNotEqual(world.story_of(REVISION)["story_id"], tariff["story_id"])
        self.assertEqual(len(world.story_of(RESPONSE)["reports"]), 1)  # Other words: only the operator merges.
        self.assertEqual(found["ungrouped"], [])
        self.assertEqual(world.group()["grouped"], 0)  # Nothing new: nothing is grouped twice.

    def test_grouping_is_idempotent_by_key_and_its_rows_cannot_be_changed(self):
        world = World(self)
        reports, names = world.reports(), news_reports.publisher_names(world.desk.publishers)
        first, created = news_stories.group(world.desk.newsroom, reports, names, "admin-1", START, "same-key-0001")
        again, repeated = news_stories.group(world.desk.newsroom, reports, names, "admin-1", START, "same-key-0001")
        self.assertEqual((created, repeated, first), (True, False, again))
        with self.assertRaises(AccountsRefused):
            news_stories.group(world.desk.newsroom, reports, names, "admin-2", START, "same-key-0001")
        connection = sqlite3.connect(world.desk.newsroom.path)
        for statement in ("UPDATE story_members SET actor = 'x'", "DELETE FROM stories", "UPDATE operations SET kind=1"):
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(statement)
        connection.close()

    def test_suggestions_name_their_evidence_and_need_the_operator(self):
        answers = {LEDGER.feed_url: (200, rss([item(LEDGER.link_host, "a", "Synthetic Republic raises steel tariff to "
                                                                            "25%", START - timedelta(hours=3))])),
                   COURIER.feed_url: (200, rss([item(COURIER.link_host, "b", "Synthetic Republic steel tariff raised to "
                                                                              "25%, officials say",
                                                     START - timedelta(hours=2))]))}
        world = World(self, answers)
        world.group()
        found = world.found()
        self.assertEqual(len(found["stories"]), 2)
        stories = {story_id: story["reports"] for story_id, story in found["stories"].items()}
        suggested = news_stories.suggestions(stories, set())
        self.assertEqual(len(suggested), 1)
        self.assertIn("25", suggested[0]["evidence"]["names_or_figures"])
        self.assertEqual(len(world.found()["stories"]), 2)  # A suggestion changes nothing.

    def test_merge_detach_and_retitle_keep_every_decision_and_the_old_address(self):
        world = World(self)
        world.group()
        tariff, maker = world.story_of(TARIFF), world.story_of("Synthetic Maker Corp. comments on steel tariff")
        news_stories.merge(world.desk.newsroom, maker["story_id"], {"into": tariff["story_id"], "reason": "One "
                           "development: the company's reaction to the tariff", "idempotency_key": world.key()},
                           "admin-1", START)
        found = world.found()
        merged = found["stories"][tariff["story_id"]]
        self.assertEqual(len(merged["reports"]), 3)
        self.assertEqual(ns.resolve_story(found["folded"], maker["story_id"]), tariff["story_id"])
        self.assertEqual(news_views.story_view(world.desk, maker["story_id"], START)["story_id"], tariff["story_id"])
        history = found["folded"]["stories"][tariff["story_id"]]["history"]
        self.assertTrue(any(row["basis"]["rule"] == "operator/merge" and row["reason"].startswith("One") for row in
                            history))
        copy = next(row["entry_id"] for row in merged["reports"] if row["source"] == "synthetic-courier")
        done, _ = news_stories.detach(world.desk.newsroom, tariff["story_id"], {
            "entry_id": copy, "reason": "Checked: a separate report", "idempotency_key": world.key()},
            world.reports(), "admin-1", START)
        self.assertNotEqual(done["new_story_id"], tariff["story_id"])
        self.assertEqual(len(world.found()["stories"][tariff["story_id"]]["reports"]), 2)
        news_stories.retitle(world.desk.newsroom, tariff["story_id"], {
            "title": "Synthetic steel tariff", "reason": "Shorter", "idempotency_key": world.key()}, "admin-1", START)
        self.assertEqual(world.found()["stories"][tariff["story_id"]]["title"], "Synthetic steel tariff")
        with self.assertRaises(AccountsRefused):  # A merged story is not merged again.
            news_stories.merge(world.desk.newsroom, maker["story_id"], {"into": tariff["story_id"], "reason": "again",
                                                                      "idempotency_key": world.key()}, "admin-1", START)


class CoverageTest(unittest.TestCase):
    def test_wire_copies_and_one_publisher_count_once_and_statements_do_not_count(self):
        world = World(self)
        world.group()
        tariff, maker = world.story_of(TARIFF), world.story_of("Synthetic Maker Corp. comments on steel tariff")
        self.assertEqual((tariff["coverage"]["reports"], tariff["coverage"]["reporting_origins"],
                          tariff["coverage"]["repeats"]), (2, 1, 1))
        self.assertTrue(tariff["coverage"]["units"][0]["counted_together_because"])
        world.merge_response()
        response = world.story_of(RESPONSE)
        self.assertEqual((response["coverage"]["reports"], response["coverage"]["reporting_origins"]), (2, 2))
        news_stories.merge(world.desk.newsroom, maker["story_id"], {"into": tariff["story_id"], "reason": "reaction",
                                                                  "idempotency_key": world.key()}, "admin-1", START)
        merged = world.found()["stories"][tariff["story_id"]]
        self.assertEqual((merged["coverage"]["reporting_origins"], merged["coverage"]["company_statements"]), (1, 1))

    def test_a_wire_credit_alone_joins_reports(self):
        rows = [{"entry_id": f"x:{n}", "publisher": name, "title": title, "excerpt": excerpt, "role": "news"}
                for n, (name, title, excerpt) in enumerate((
                    ("A", "Synthetic steel duties set", "CAPITAL (Reuters) - Synthetic duties were set on steel."),
                    ("B", "Steel duties set by Synthetic Republic", "CAPITAL (Reuters) - Synthetic duties, set."),
                    ("C", "Synthetic Republic sets duties", "Officials set synthetic duties, a spokesperson said.")))]
        coverage = news_stories.coverage(rows, set())
        self.assertEqual(coverage["reporting_origins"], 2)
        self.assertIn("the same wire credit (Reuters)", coverage["units"][0]["counted_together_because"])


class RankingTest(unittest.TestCase):
    def test_fresh_independent_developments_lead_and_stale_ones_leave_hot_now(self):
        world = World(self)
        world.group()
        hot = news_views.stories_view(world.desk, "hot", [], START)
        titles = [story["title"] for story in hot["stories"]]
        self.assertEqual(titles[0], REVISION)  # The newest development.
        self.assertIn(RESPONSE, titles)
        later = news_views.stories_view(world.desk, "hot", [], START + timedelta(days=4))
        self.assertEqual(later["stories"], [])
        self.assertTrue(later["notes"][0].startswith("No story has a report from the last 3 days"))
        latest = news_views.stories_view(world.desk, "latest", [], START + timedelta(days=4))
        self.assertTrue(all(story["older"] for story in latest["stories"]))
        self.assertEqual(len(latest["stories"]), len(world.found()["stories"]))

    def test_syndicated_copies_add_no_coverage_points(self):
        world = World(self)
        world.group()
        world.merge_response()
        tariff = world.story_of(TARIFF)
        self.assertFalse(any(row["signal"] == "coverage" for row in tariff["rank"]["signals"]))
        response = world.story_of(RESPONSE)
        self.assertEqual([row["points"] for row in response["rank"]["signals"] if row["signal"] == "coverage"],
                         [news_rank.BREADTH_POINTS])  # Two newsrooms' own reporting: one unit beyond the first.

    def test_a_missing_time_is_ranked_by_when_it_was_first_seen_and_says_so(self):
        world = World(self)
        world.group()
        port = world.story_of("Synthetic port reports record container volumes")
        self.assertEqual((port["first_basis"], port["first_at"]), ("first_seen", START.isoformat()))
        self.assertIn("the feed states no time", port["rank"]["signals"][0]["text"])
        self.assertEqual(port["rank"]["signals"][0]["points"], news_rank.FRESH_POINTS * news_rank.UNSTATED_FACTOR)
        self.assertNotIn("new_development", [row["signal"] for row in port["rank"]["signals"]])

    def test_a_major_mark_lifts_a_story_until_it_ends_and_never_without_recent_reports(self):
        world = World(self)
        world.group()
        tariff = world.story_of(TARIFF)
        news_topics.prioritise(world.desk.newsroom, {"target_kind": "story", "target_id": tariff["story_id"],
                                                     "level": "major", "until": (START + timedelta(days=2)).isoformat(),
                                                     "reason": "Major dispute", "idempotency_key": world.key()},
                               "admin-1", START)
        marked = world.found()["stories"][tariff["story_id"]]
        self.assertIn("priority", [row["signal"] for row in marked["rank"]["signals"]])
        after = world.found(START + timedelta(days=2, minutes=1))["stories"][tariff["story_id"]]
        self.assertNotIn("priority", [row["signal"] for row in after["rank"]["signals"]])
        with self.assertRaises(AccountsRefused):  # At most seven days ahead.
            news_topics.prioritise(world.desk.newsroom, {"target_kind": "story", "target_id": tariff["story_id"],
                                                         "level": "major", "until": (START + timedelta(days=8))
                                                         .isoformat(), "reason": "Too long",
                                                         "idempotency_key": world.key()}, "admin-1", START)

    def test_the_ranking_is_the_same_on_every_read(self):
        world = World(self)
        world.group()
        first = news_views.stories_view(world.desk, "hot", [], START)
        self.assertEqual(first, news_views.stories_view(world.desk, "hot", [], START))

    def test_a_company_statement_alone_is_listed_under_latest_unless_marked_major(self):
        world = World(self)
        world.group()
        statement = world.story_of("Synthetic Maker Corp. comments on steel tariff")
        self.assertFalse(statement["rank"]["hot"])
        self.assertIn("statements_only", [row["signal"] for row in statement["rank"]["signals"]])
        hot = [story["story_id"] for story in news_views.stories_view(world.desk, "hot", [], START)["stories"]]
        latest = [story["story_id"] for story in news_views.stories_view(world.desk, "latest", [], START)["stories"]]
        self.assertNotIn(statement["story_id"], hot)
        self.assertIn(statement["story_id"], latest)
        news_topics.prioritise(world.desk.newsroom, {"target_kind": "story", "target_id": statement["story_id"],
                                                     "level": "major", "until": (START + timedelta(days=1)).isoformat(),
                                                     "reason": "The editors judged it major", "idempotency_key": world.key()},
                               "admin-1", START)
        hot = [story["story_id"] for story in news_views.stories_view(world.desk, "hot", [], START)["stories"]]
        self.assertIn(statement["story_id"], hot)


class TopicsTest(unittest.TestCase):
    def topic(self, world: World) -> str:
        world.group()
        done, _ = news_topics.create(world.desk.newsroom, {"title": "Synthetic steel dispute", "summary": "SYNTHETIC",
                                                           "reason": "Ongoing", "idempotency_key": world.key()},
                                     "admin-1", START)
        for title, label in ((REVISION, "Tariff narrowed"), (TARIFF, "Tariff announced"), (RESPONSE, "A response")):
            news_topics.link(world.desk.newsroom, done["topic_id"], {
                "story_id": world.story_of(title)["story_id"], "action": "link", "label": label,
                "reason": "Part of the dispute", "idempotency_key": world.key()}, "admin-1", START)
        return done["topic_id"]

    def test_developments_form_a_timeline_and_link_related_stories(self):
        world = World(self)
        topic_id = self.topic(world)
        page = news_views.topic_view(world.desk, topic_id, START)
        self.assertEqual([row["label"] for row in page["timeline"]], ["Tariff announced", "A response",
                                                                      "Tariff narrowed"])
        story = news_views.story_view(world.desk, world.story_of(TARIFF)["story_id"], START)
        self.assertEqual([row["label"] for row in story["related"]], ["Tariff narrowed", "A response"])
        newest = world.story_of(REVISION)
        self.assertIn("topic", [row["signal"] for row in newest["rank"]["signals"]])
        self.assertNotIn("topic", [row["signal"] for row in world.story_of(TARIFF)["rank"]["signals"]])

    def test_unlinking_leaves_the_story_and_the_record(self):
        world = World(self)
        topic_id = self.topic(world)
        response = world.story_of(RESPONSE)["story_id"]
        news_topics.link(world.desk.newsroom, topic_id, {"story_id": response, "action": "unlink", "label": "",
                                                         "reason": "Separate", "idempotency_key": world.key()},
                         "admin-1", START)
        self.assertEqual(len(news_views.topic_view(world.desk, topic_id, START)["timeline"]), 2)
        with self.assertRaises(AccountsRefused):
            news_topics.link(world.desk.newsroom, topic_id, {"story_id": response, "action": "unlink", "label": "",
                                                             "reason": "Again", "idempotency_key": world.key()},
                             "admin-1", START)


GOOD = {"headline": "Synthetic Republic narrows its steel tariff",
        "summary": "The Synthetic Republic said it would exempt three grades of steel from its tariff after talks.",
        "facts": [], "implications": [{"text": "Steel buyers in the Synthetic Federation could face lower duties if "
                                                "the exemptions take effect."}],
        "themes": [{"kind": "sector", "name": "Steel", "basis": "The reports concern steel tariffs."}],
        "uncertainties": ["Which grades are exempted is not stated."], "missing": ["The date the change applies."]}


class BriefTest(unittest.TestCase):
    def story(self, world: World, title: str = REVISION) -> dict:
        world.group()
        return world.story_of(title)

    def content(self, story: dict, **changes) -> dict:
        return {**GOOD, "facts": [{"text": "The Synthetic Republic said it would exempt three grades of steel.",
                                   "reports": [story["material"]["reports"][0]["entry_id"]]}], **changes}

    def save(self, world: World, story: dict, content: dict, method: str = "editorial") -> dict:
        done, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": content, "method": method, "based_on": None, "idempotency_key": world.key()},
            story["material"], "admin-1", START)
        return done

    def publish(self, world: World, story: dict, version: int | None):
        return story_briefs.publish(world.desk.newsroom, story["story_id"], {
            "version": version, "reason": "Checked", "idempotency_key": world.key()}, "admin-1", START)

    def test_a_published_brief_is_what_users_read_with_its_material(self):
        world = World(self)
        story = self.story(world)
        done = self.save(world, story, self.content(story))
        self.assertTrue(done["publishable"])
        self.assertEqual(news_views.story_view(world.desk, story["story_id"], START)["brief_state"], "none")
        self.publish(world, story, done["version"])
        page = news_views.story_view(world.desk, story["story_id"], START)
        self.assertEqual(page["brief_state"], "published")
        self.assertEqual(page["brief"]["content"]["headline"], GOOD["headline"])
        self.assertEqual(page["brief"]["material"]["coverage"], "headlines_and_excerpts")
        self.assertIn("The full publications were not read", page["brief"]["material"]["statement"])
        self.assertEqual([row["use"] for row in page["sources"]], ["material"])

    def test_the_guard_refuses_advice_causes_and_certainty(self):
        world = World(self)
        story = self.story(world)
        for implication, rule in (("Investors should buy steel shares.", "advice"),
                                  ("The tariff caused prices to rise, so mills may hire.", "causal_claim"),
                                  ("Steel buyers will pay less.", "unhedged"),
                                  ("Prices could certainly fall.", "certainty"),
                                  ("Traders could sell steel futures.", "trade")):
            done = self.save(world, story, self.content(story, implications=[{"text": implication}]))
            self.assertFalse(done["publishable"])
            self.assertIn(rule, [row["rule"] for row in done["guard"]["findings"]], implication)
            with self.assertRaises(AccountsRefused) as refused:
                self.publish(world, story, done["version"])
            self.assertEqual(refused.exception.code, "brief_not_publishable")
        attributed = self.save(world, story, self.content(story, summary="Officials said talks led to the change."))
        self.assertTrue(attributed["publishable"])  # A cause stated by someone is reported, not claimed.
        claimed = self.save(world, story, self.content(story, summary="Talks led to the change."))
        self.assertEqual([row["rule"] for row in claimed["guard"]["findings"]], ["causal_claim"])

    def test_facts_cite_material_and_the_shape_is_exact(self):
        world = World(self)
        story = self.story(world)
        for bad in (self.content(story, facts=[{"text": "x", "reports": ["synthetic-ledger:unknown"]}]),
                    self.content(story, facts=[]), {**self.content(story), "advice": "x"},
                    self.content(story, themes=[{"kind": "stock", "name": "x", "basis": "y"}])):
            with self.assertRaises(AccountsRefused):
                self.save(world, story, bad)

    def test_versions_append_and_a_withdrawal_leaves_the_story_without_a_brief(self):
        world = World(self)
        story = self.story(world)
        first = self.save(world, story, self.content(story))
        self.publish(world, story, first["version"])
        second = self.save(world, story, self.content(story, headline="Synthetic tariff narrowed"))
        self.assertEqual(second["version"], 2)
        self.assertEqual(news_views.story_view(world.desk, story["story_id"], START)["brief"]["version"], 1)
        self.publish(world, story, 2)
        self.assertEqual(news_views.story_view(world.desk, story["story_id"], START)["brief"]["version"], 2)
        self.publish(world, story, None)
        page = news_views.story_view(world.desk, story["story_id"], START)
        self.assertEqual((page["brief_state"], page["brief"]), ("withdrawn", None))

    def test_reports_whose_terms_allow_no_use_are_listed_but_never_material(self):
        answers = {TECH.feed_url: (200, rss([item("techcrunch.com", "a", "Synthetic startup raises a round",
                                                  START - timedelta(hours=1), "A SYNTHETIC excerpt.")]))}
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        desk = desk_in(Path(folder.name), publishers({}), Feeds(answers))
        news_feeds.refresh(desk.feeds, desk.fetcher, [news_registry.PUBLISHERS["techcrunch"]], lambda: START)
        reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
        news_stories.group(desk.newsroom, reports, set(), "admin-1", START, "group-key-0001")
        story = next(iter(news_views.world(desk, START)["stories"].values()))
        self.assertEqual(story["material"]["reports"], [])
        self.assertEqual(story["material"]["not_used"][0]["publisher"], "TechCrunch")
        page = news_views.story_view(desk, story["story_id"], START)
        self.assertEqual((page["brief_state"], page["deeper"]["available"]), ("not_permitted", False))
        self.assertEqual(page["sources"][0]["excerpt"], "A SYNTHETIC excerpt.")  # Shown as the feed gave it.
        self.assertEqual(page["sources"][0]["use"], "listed")
        with self.assertRaises(AccountsRefused):
            story_briefs.add_version(desk.newsroom, story["story_id"], {"content": GOOD, "method": "editorial",
                                                                        "based_on": None,
                                                                        "idempotency_key": "brief-key-0001"},
                                     story["material"], "admin-1", START)

    def test_the_extract_draft_uses_only_the_reports_own_words(self):
        world = World(self)
        story = self.story(world, RESPONSE)
        draft = story_briefs.extract_draft(story, story["material"])
        self.assertEqual(draft["implications"], [])
        self.assertTrue(all(fact["text"].split(": ", 1)[1] == RESPONSE for fact in draft["facts"]))
        self.assertEqual(story_briefs.checked_content(draft, {row["entry_id"] for row in story["material"]["reports"]}),
                         draft)
        done = self.save(world, story, draft, method="extract")
        self.assertFalse(done["publishable"])  # The editors add why it may matter first.

    def test_a_user_view_carries_no_operator_records(self):
        world = World(self)
        story = self.story(world)
        done = self.save(world, story, self.content(story))
        self.publish(world, story, done["version"])
        text = repr(news_views.story_view(world.desk, story["story_id"], START)) + \
            repr(news_views.stories_view(world.desk, "latest", [], START))
        for secret in ("admin-1", "test-key-", "idempotency", "history", "prepared_by", "actor"):
            self.assertNotIn(secret, text)


class EmptyNewsroomTest(unittest.TestCase):
    def test_reading_without_a_newsroom_creates_nothing_and_says_so(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        desk = desk_in(Path(folder.name))
        view = news_views.stories_view(desk, "hot", [], START)
        self.assertEqual(view["stories"], [])
        self.assertIn("No stories have been put together", view["notes"][0])
        self.assertFalse(desk.newsroom.exists())
        with self.assertRaises(AccountsRefused):
            news_views.story_view(desk, "story-0000000000000000", START)


if __name__ == "__main__":
    unittest.main()
