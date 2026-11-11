"""The official publishers of news-registry-0.2, the subject rule of news-rank-0.2, the time of a report whose feed
states a date but no usable time, and the local operator's curation plan (news_curation, `news curate`), over SYNTHETIC
feeds answered at the registered addresses through a simulated network. Nothing reaches a network, and every action goes
through the same functions as the Admin desk."""
from argparse import Namespace
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from news_desk_fakes import (RESPONSE, RESPONSE_OWN, REVISION, START, TARIFF, Feeds, assess, clock, desk_in, item,
                             rss,
                             trade_feeds)
from second_order import news_cli, news_curation, news_feeds, news_registry, news_reports, news_stories, news_views
from second_order import newsroom_store as ns

OFFICIAL = ("whitehouse-news", "ustr-press", "ec-press", "ecb-press")
NOW = START + timedelta(days=2)
CANADA = "Fact Sheet: Synthetic proclamation further modifies Canadian products subject to tariffs"
CEREMONY = "Synthetic proclamation of a national seafood month"


def official_feeds(now: datetime = NOW) -> dict[str, tuple[int, bytes]]:
    """SYNTHETIC entries at the four official publishers' registered feed addresses (their real addresses are
    answered only by the simulated network)."""
    feeds = {key: news_registry.PUBLISHERS[key].feed for key in OFFICIAL}
    hours = lambda value: now - timedelta(hours=value)  # noqa: E731
    return {
        feeds["whitehouse-news"].feed_url: (200, rss([
            item("www.whitehouse.gov", "canada", CANADA, hours(3),
                 "SYNTHETIC: the President signed a proclamation to further refine the scope of the tariffs on certain "
                 "Canadian products."),
            item("www.whitehouse.gov", "seafood", CEREMONY, hours(4),
                 "SYNTHETIC: a proclamation honouring fishing communities."),
        ])),
        feeds["ustr-press"].feed_url: (200, rss([
            item("ustr.gov", "labor", "Synthetic resolution of a labor mechanism matter", hours(5),
                 "SYNTHETIC: the United States announced the resolution of a matter under an agreement."),
        ])),
        feeds["ec-press"].feed_url: (200, rss([
            item("ec.europa.eu", "trade", "Synthetic Commissioner remarks after the trade council", hours(6),
                 "SYNTHETIC: remarks on EU trade relations and tariffs."),
        ])),
        feeds["ecb-press"].feed_url: (200, rss([item("www.ecb.europa.eu", "survey", "Synthetic ECB survey results",
                                                     hours(7))])),
    }


def real_desk(test: unittest.TestCase, answers: dict) -> tuple[news_views.Desk, Feeds]:
    folder = tempfile.TemporaryDirectory()
    test.addCleanup(folder.cleanup)
    network = Feeds(answers)
    desk = desk_in(Path(folder.name), chosen=dict(news_registry.PUBLISHERS), network=network)
    return desk, network


class OfficialPublishersTest(unittest.TestCase):
    def test_four_official_feeds_are_connected_with_their_terms_and_others_are_recorded_but_not_requested(self):
        self.assertEqual(news_registry.REGISTRY_VERSION, "news-registry-0.5")
        connected = {publisher.key for publisher in news_registry.connected()}
        self.assertEqual(connected, {"techcrunch", "prnewswire-business", *OFFICIAL, "doj-antitrust", "boc-press", "sec-press", "ons-publications", "rba-releases", "census-indicators", "voa-news", "globalvoices", "ips-economy"})
        for key in OFFICIAL:
            publisher = news_registry.PUBLISHERS[key]
            self.assertEqual((publisher.role, publisher.material, publisher.display, publisher.status),
                             ("official", "permitted", "headline_excerpt", "connected"), key)
            self.assertTrue(publisher.material_basis and publisher.attribution and publisher.live_verified, key)
            self.assertFalse(publisher.feed.keep_raw, key)  # No complete response is kept.
            self.assertTrue(publisher.feed.feed_url.startswith(f"https://{publisher.feed.link_host}/"), key)
        for key in ("bea", "bank-of-england"):
            publisher = news_registry.PUBLISHERS[key]
            self.assertNotEqual(publisher.status, "connected", key)
            self.assertIsNone(publisher.feed, key)
            self.assertTrue(publisher.agreement or publisher.credentials, key)
        self.assertEqual(news_registry.PUBLISHERS["bank-of-england"].material, "none")  # Non-commercial reuse only.

    def test_a_refresh_requests_each_once_and_their_releases_are_permitted_material(self):
        desk, network = real_desk(self, official_feeds())
        publishers = [news_registry.PUBLISHERS[key] for key in OFFICIAL]
        result = news_feeds.refresh(desk.feeds, desk.fetcher, publishers, lambda: NOW)
        self.assertEqual([row["outcome"] for row in result["refreshed"]], ["ok"] * 4)
        self.assertEqual(sorted(network.requests), sorted(publisher.feed.feed_url for publisher in publishers))
        reports = {row["title"]: row for row in news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
                   .values()}
        for row in reports.values():
            self.assertEqual((row["role"], row["role_label"], row["material"]), ("official", "Official release",
                                                                                "permitted"))
        interests = {title: [topic["interest"] for topic in row["topics"]] for title, row in reports.items()}
        self.assertEqual(interests[CANADA], ["trade"])  # Found by its words: the White House has no single subject.
        self.assertEqual(interests[CEREMONY], [])
        self.assertEqual(interests["Synthetic resolution of a labor mechanism matter"], ["trade"])  # USTR's own.
        self.assertEqual(interests["Synthetic ECB survey results"], ["monetary-policy"])
        self.assertIsNone(reports["Synthetic ECB survey results"]["excerpt"])  # Its feed gives headlines only.

    def test_the_fetcher_never_requests_a_publisher_that_is_not_connected(self):
        desk, network = real_desk(self, official_feeds())
        with self.assertRaises(Exception):
            desk.fetcher.fetch("https://www.freightwaves.com/feed")
        with self.assertRaises(Exception):
            desk.fetcher.fetch("https://apps.bea.gov/rss/rss.xml")
        self.assertEqual(network.requests, [])


    def test_the_refresh_command_requests_the_official_inbox_feeds_only_when_asked(self):
        from second_order import event_inbox
        desk, network = real_desk(self, official_feeds())
        inbox = Feeds({})  # The Event Inbox's feeds are not answered: each request fails and is recorded as failed.
        fetcher = event_inbox.FeedFetcher(None, inbox.transport())
        plain = news_cli.run(Namespace(news_action="refresh", official=False), desk, inbox_fetcher=fetcher)
        self.assertEqual((plain["official"], inbox.requests), ([], []))
        self.assertEqual({row["source"] for row in plain["refreshed"]},
                         {"techcrunch", "prnewswire-business", *OFFICIAL, "doj-antitrust", "boc-press", "sec-press", "ons-publications", "rba-releases", "census-indicators", "voa-news", "globalvoices", "ips-economy"})
        outcomes = {row["source"]: row["outcome"] for row in plain["refreshed"]}
        self.assertEqual((outcomes["sec-press"], outcomes["ons-publications"]), ("not_requested", "not_requested"))
        asked = news_cli.run(Namespace(news_action="refresh", official=True), desk, inbox_fetcher=fetcher)
        self.assertEqual([row["source"] for row in asked["official"]], list(event_inbox.SOURCES))
        self.assertEqual(sorted(inbox.requests), sorted(source.feed_url for source in event_inbox.SOURCES.values()
                                                        if not source.contact_required))  # BLS needs a contact.


class SubjectRuleTest(unittest.TestCase):
    def setUp(self):
        self.desk, _ = real_desk(self, official_feeds())
        publishers = [news_registry.PUBLISHERS[key] for key in OFFICIAL]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, publishers, lambda: NOW)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, news_reports.publisher_names(self.desk.publishers), "admin-1",
                           NOW, "group-key-0001")

    def story(self, title: str) -> dict:
        return next(story for story in news_views.world(self.desk, NOW)["stories"].values() if story["title"] == title)

    def test_relevance_not_keywords_decides_what_is_listed_and_nothing_unassessed_is_hidden(self):
        # Before any assessment, neither official release is presented as economic news, and both wait in view.
        hot = news_views.stories_view(self.desk, "hot", [], NOW)
        self.assertEqual([row["title"] for row in hot["stories"]], [])
        self.assertLessEqual({CANADA, CEREMONY}, {row["title"] for row in hot["awaiting"]})
        self.assertEqual({row["relevance"]["state"] for row in hot["awaiting"]}, {"pending"})
        assess(self.desk, NOW, {CEREMONY: "outside_scope"})
        hot = news_views.stories_view(self.desk, "hot", [], NOW)
        latest = news_views.stories_view(self.desk, "latest", [], NOW)
        self.assertIn(CANADA, [row["title"] for row in hot["stories"]])
        self.assertNotIn(CEREMONY, [row["title"] for row in hot["stories"] + hot["awaiting"]])
        self.assertNotIn(CEREMONY, [row["title"] for row in latest["stories"] + latest["awaiting"]])
        self.assertEqual(latest["left_out"]["outside_scope"], 1)
        ceremony = self.story(CEREMONY)
        self.assertEqual(ceremony["relevance"]["state"], "outside_scope")
        self.assertIn("relevance", [row["signal"] for row in ceremony["rank"]["signals"]])
        page = news_views.story_view(self.desk, ceremony["story_id"], NOW)  # Its page stays at its address.
        self.assertEqual(page["relevance"]["state"], "outside_scope")
        self.assertFalse(page["deeper"]["available"])
        self.assertIn("outside the economic news's scope", hot["rank"]["statement"])

    def test_a_major_mark_lifts_it_into_hot_now_while_it_lasts(self):
        from second_order import news_topics
        ceremony = self.story(CEREMONY)
        news_topics.prioritise(self.desk.newsroom, {"target_kind": "story", "target_id": ceremony["story_id"],
                                                    "level": "major", "until": (NOW + timedelta(days=1)).isoformat(),
                                                    "reason": "SYNTHETIC check", "idempotency_key": "major-key-0001"},
                               "admin-1", NOW)
        self.assertTrue(self.story(CEREMONY)["rank"]["hot"])


class DatedReportTest(unittest.TestCase):
    def test_a_stated_date_without_a_usable_time_bounds_the_report_time(self):
        from second_order.news_reports import report_time
        seen = "2026-10-25T09:32:20+00:00"
        stated = {"state": "stated", "utc": "2026-10-23T19:51:09+00:00", "as_stated": "x", "date": "2026-10-23"}
        self.assertEqual(report_time(stated, seen), ("2026-10-23T19:51:09+00:00", "published"))
        date_only = {"state": "date_only", "utc": None, "as_stated": "Wed, 21 Oct 2026 00:00:00 GMT",
                     "date": "2026-10-21"}
        self.assertEqual(report_time(date_only, seen), ("2026-10-21T23:59:59+00:00", "dated"))
        self.assertEqual(report_time(date_only, "2026-10-21T08:00:00+00:00"), ("2026-10-21T08:00:00+00:00", "dated"))
        contradicts = {"state": "unstated", "utc": None, "as_stated": "Thu, 22 Oct 2026  09:00:00 EST", "date": None}
        self.assertEqual(report_time(contradicts, seen), ("2026-10-22T23:59:59+00:00", "dated"))
        nothing = {"state": "unstated", "utc": None, "as_stated": None, "date": None}
        self.assertEqual(report_time(nothing, seen), (seen, "first_seen"))
        later = {**date_only, "as_stated": "Sat, 31 Oct 2026 00:00:00 GMT", "date": "2026-10-31"}
        self.assertEqual(report_time(later, seen), (seen, "first_seen"))  # A date after the sighting is not believed.

    def test_a_release_dated_days_before_its_first_retrieval_is_older_news_not_hot(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        wto = "Synthetic members review a safeguard measure"
        body = rss([item("www.wto.org", "review", wto, None, "SYNTHETIC: members reviewed a measure.").replace(
            "</item>", "<pubDate>Thu, 15 Oct 2026 00:00:00 GMT</pubDate></item>")])
        from second_order import event_inbox
        network = Feeds({event_inbox.SOURCES["wto-news"].feed_url: (200, body)})
        root = Path(folder.name)
        retrieved = datetime(2026, 10, 25, 9, 32, tzinfo=timezone.utc)
        event_inbox.refresh_source(event_inbox.SOURCES["wto-news"], event_inbox.FeedFetcher(None, network.transport()),
                                   root / "event-inbox", lambda: retrieved)
        desk = desk_in(root, chosen=dict(news_registry.PUBLISHERS))
        reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
        (report,) = reports.values()
        self.assertEqual((report["at"], report["at_basis"]), ("2026-10-15T23:59:59+00:00", "dated"))
        news_stories.group(desk.newsroom, reports, news_reports.publisher_names(desk.publishers), "admin-1", retrieved,
                           "group-key-0001")
        story = next(iter(news_views.world(desk, retrieved)["stories"].values()))
        self.assertEqual((story["rank"]["hot"], story["rank"]["older"]), (False, True))
        self.assertIn("the date its feed states", story["rank"]["signals"][0]["text"])
        self.assertEqual(news_views.stories_view(desk, "hot", [], retrieved)["stories"], [])


class CurationPlanTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk = desk_in(self.root, network=Feeds(trade_feeds(START)))
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, news_reports.publisher_names(self.desk.publishers), "admin-1",
                           START, "group-key-0001")
        self.ids = {title: self.story_id(title) for title in (TARIFF, RESPONSE, RESPONSE_OWN, REVISION)}

    def story_id(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def brief(self, implication: str = "Steel buyers could face higher costs if the tariff applies.") -> dict:
        material = news_views.world(self.desk, START)["stories"][self.ids[TARIFF]]["material"]
        return {"headline": "A SYNTHETIC 15% steel tariff", "summary": "The Synthetic Republic said it would impose a "
                "15% tariff on imported steel.", "facts": [{"text": "A 15% tariff on imported steel was announced.",
                                                            "reports": [material["reports"][0]["entry_id"]]}],
                "implications": [{"text": implication}], "themes": [{"kind": "sector", "name": "Steel",
                                                                     "basis": "The reports concern steel."}],
                "uncertainties": ["How long it applies is not stated."], "missing": []}

    def plan(self, **changes) -> dict:
        actions = [
            {"key": "merge-response", "do": "merge", "story": self.ids[RESPONSE_OWN], "into": self.ids[RESPONSE]},
            {"key": "title-tariff", "do": "title", "story": self.ids[TARIFF], "title": "SYNTHETIC steel tariff"},
            {"key": "topic-steel", "do": "topic", "title": "SYNTHETIC steel dispute", "summary": "SYNTHETIC."},
            {"key": "link-tariff", "do": "link", "topic": "@topic-steel", "story": self.ids[TARIFF],
             "label": "Tariff announced"},
            {"key": "link-response", "do": "link", "topic": "@topic-steel", "story": self.ids[RESPONSE]},
            {"key": "brief-tariff", "do": "brief", "story": self.ids[TARIFF], "method": "editorial",
             "content": self.brief(), "publish": True},
            {"key": "major-steel", "do": "priority", "target": "@topic-steel", "level": "major",
             "until": (START + timedelta(days=3)).isoformat()},
        ]
        return {"plan_version": news_curation.PLAN_VERSION, "reason": "SYNTHETIC curation check", "actions": actions,
                **changes}

    def operations(self) -> int:
        with closing(sqlite3.connect(self.desk.newsroom.path)) as connection:
            return connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]

    def test_a_malformed_plan_is_refused_before_anything_is_applied(self):
        good = self.plan()
        for bad in ({**good, "plan_version": "other"}, {**good, "actions": []},
                    {**good, "actions": [{"key": "x1x1", "do": "delete", "story": "story-0"}]},
                    {**good, "actions": [{"key": "link-1", "do": "link", "story": "story-0"}]},
                    {**good, "actions": [good["actions"][1], good["actions"][1]]},
                    {"plan_version": news_curation.PLAN_VERSION, "actions": [good["actions"][1]]},
                    {**good, "actions": [{**good["actions"][1], "key": "a b c d"}]}):
            with self.assertRaises(news_curation.PlanRefused):
                news_curation.read_plan(bad)

    def test_check_reads_only_and_says_what_would_stop_a_brief(self):
        before = self.operations()
        plan = self.plan()
        plan["actions"][5]["content"] = self.brief("Investors should buy steel makers, which will cause gains.")
        plan["actions"].append({"key": "title-gone", "do": "title", "story": "story-0000000000000000", "title": "X"})
        result = news_curation.check(self.desk, news_curation.read_plan(plan), START)
        rows = {row["key"]: row for row in result["checked"]}
        self.assertTrue(rows["link-tariff"]["ok"])  # The plan's own topic is known by its key.
        self.assertFalse(rows["brief-tariff"]["ok"])
        self.assertTrue(any("advise" in problem or "advice" in problem or "trade" in problem
                            for problem in rows["brief-tariff"]["problems"]))
        self.assertFalse(rows["title-gone"]["ok"])
        self.assertEqual((result["written"], self.operations()), (0, before))

    def test_check_follows_the_plans_own_merges_for_a_briefs_material(self):
        world = news_views.world(self.desk, START)
        own = world["stories"][self.ids[RESPONSE_OWN]]["material"]["reports"][0]["entry_id"]
        brief = {**self.brief(), "facts": [{"text": "Duties on farm goods were announced.", "reports": [own]}]}
        alone = [{"key": "brief-response", "do": "brief", "story": self.ids[RESPONSE], "method": "editorial",
                  "content": brief, "publish": True}]
        plan = {"plan_version": news_curation.PLAN_VERSION, "reason": "SYNTHETIC", "actions": alone}
        rows = news_curation.check(self.desk, news_curation.read_plan(plan), START)["checked"]
        self.assertFalse(rows[0]["ok"])  # Without the merge, that report is not this story's material.
        plan["actions"] = [self.plan()["actions"][0], *alone]
        rows = news_curation.check(self.desk, news_curation.read_plan(plan), START)["checked"]
        self.assertTrue(all(row["ok"] for row in rows), rows)
        applied = news_curation.apply(self.desk, news_curation.read_plan(plan), "local-operator", clock(START))
        self.assertIsNone(applied["stopped"])

    def test_apply_records_every_action_with_the_local_operator_and_a_repeat_changes_nothing(self):
        actions = news_curation.read_plan(self.plan())
        result = news_curation.apply(self.desk, actions, "local-operator", clock(START))
        self.assertIsNone(result["stopped"])
        self.assertTrue(all(row["created"] for row in result["applied"]))
        self.assertEqual([row["do"] for row in result["applied"]],
                         ["merge", "title", "topic", "link", "link", "brief", "publish", "priority"])
        page = news_views.story_view(self.desk, self.ids[TARIFF], START)
        self.assertEqual(page["brief_state"], "published")
        self.assertEqual(page["brief"]["content"]["headline"], "A SYNTHETIC 15% steel tariff")
        self.assertEqual(page["title"], "SYNTHETIC steel tariff")
        topic_id = result["applied"][2]["result"]["topic_id"]
        topic = news_views.topic_view(self.desk, topic_id, START)
        self.assertEqual([row["story_id"] for row in topic["timeline"]], [self.ids[TARIFF], self.ids[RESPONSE]])
        self.assertTrue(news_views.story_view(self.desk, self.ids[RESPONSE_OWN], START)["merged"])
        folded = ns.state(self.desk.newsroom)
        self.assertEqual(folded["topics"][topic_id]["actor"], "local-operator")
        self.assertEqual(folded["topics"][topic_id]["reason"], "SYNTHETIC curation check")
        count = self.operations()
        again = news_curation.apply(self.desk, actions, "local-operator", clock(START + timedelta(hours=1)))
        self.assertIsNone(again["stopped"])
        self.assertFalse(any(row["created"] for row in again["applied"]))
        self.assertEqual(self.operations(), count)

    def test_a_changed_action_under_a_used_key_stops_the_plan_and_keeps_what_was_done(self):
        news_curation.apply(self.desk, news_curation.read_plan(self.plan()), "local-operator", clock(START))
        changed = self.plan()
        changed["actions"][1]["title"] = "Another SYNTHETIC headline"
        result = news_curation.apply(self.desk, news_curation.read_plan(changed), "local-operator", clock(START))
        self.assertEqual((result["stopped"]["key"], result["stopped"]["code"]),
                         ("title-tariff", "idempotency_conflict"))
        self.assertEqual([row["key"] for row in result["applied"]], ["merge-response"])
        self.assertEqual(news_views.story_view(self.desk, self.ids[TARIFF], START)["title"], "SYNTHETIC steel tariff")

    def test_a_brief_that_the_guard_refuses_is_saved_but_never_published(self):
        plan = self.plan()
        plan["actions"][5]["content"] = self.brief("Investors should buy steel makers.")
        result = news_curation.apply(self.desk, news_curation.read_plan(plan), "local-operator", clock(START))
        self.assertEqual((result["stopped"]["key"], result["stopped"]["code"]), ("brief-tariff",
                                                                                "brief_not_publishable"))
        self.assertTrue(result["stopped"]["problems"])
        self.assertEqual(news_views.story_view(self.desk, self.ids[TARIFF], START)["brief_state"], "none")

    def test_the_commands_read_draft_check_and_apply_a_plan_file(self):
        stories = news_cli.run(Namespace(news_action="stories", view="latest", limit=50), self.desk)
        self.assertIn(self.ids[TARIFF], [row["story_id"] for row in stories["stories"]])
        draft = news_cli.run(Namespace(news_action="draft", story_id=self.ids[TARIFF]), self.desk)
        self.assertFalse(draft["recorded"])
        self.assertEqual(draft["method"], "extract")
        path = self.root / "plan.json"
        plan = self.plan()
        plan["actions"] = plan["actions"][:-1]  # The command's clock is the real one; the SYNTHETIC mark's end is past.
        path.write_text(json.dumps(plan), encoding="utf-8")
        checked = news_cli.run(Namespace(news_action="curate", plan=path, check=True), self.desk)
        self.assertTrue(all(row["ok"] for row in checked["checked"]))
        applied = news_cli.run(Namespace(news_action="curate", plan=path, check=False), self.desk)
        self.assertIsNone(applied["stopped"])
        self.assertEqual(ns.state(self.desk.newsroom)["topics"][applied["applied"][2]["result"]["topic_id"]]["actor"],
                         news_cli.CLI_ACTOR)
        path.write_text(json.dumps({"plan_version": "nope"}), encoding="utf-8")
        with self.assertRaises(SystemExit):
            news_cli.run(Namespace(news_action="curate", plan=path, check=False), self.desk)


if __name__ == "__main__":
    unittest.main()
