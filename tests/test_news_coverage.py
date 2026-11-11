"""Reporting origins (story-coverage-0.3), breadth of independent coverage in the ranking (news-rank-0.4) and grouping
different headlines about one development (story-match-0.2), over SYNTHETIC reports and feeds. Nothing reaches a
network."""
from datetime import timedelta
import tempfile
import unittest
from pathlib import Path

from news_desk_fakes import COURIER, REVISION, START, TARIFF, Feeds, assess, desk_in, item, rss, trade_feeds
from second_order import news_feeds, news_matching, news_rank, news_reports, news_stories, news_views
from second_order import newsroom_store as ns
from second_order.accounts import AccountsRefused


def report(entry: str, publisher: str, title: str, excerpt: str | None, role: str = "news") -> dict:
    return {"entry_id": entry, "publisher": publisher, "title": title, "excerpt": excerpt, "role": role}


class OriginsTest(unittest.TestCase):
    def test_publishers_are_counted_apart_from_reporting_origins_and_copies_collapse_into_theirs(self):
        rows = [report("a:1", "Synthetic Daily", "Steel tariff set at 15%",
                       "CAPITAL (Reuters) - The Synthetic Republic said on Monday it would impose a 15% tariff."),
                report("b:1", "Synthetic Times", "Republic to tax steel imports",
                       "CAPITAL (Reuters) - Steel imports will cost buyers more from next month, officials said."),
                report("c:1", "Synthetic Ledger", "Republic sets steel duty after review",
                       "Officials told our reporter the duty follows a review of the steel industry and two hearings."),
                report("d:1", "Synthetic Ministry", "Steel tariff of 15% announced",
                       "The Ministry announced a 15% tariff on imported steel from next month.", role="official"),
                report("e:1", "Synthetic Steel Corp. via Wire", "Synthetic Steel Corp. welcomes tariff",
                       "The company welcomed the tariff.", role="company")]
        coverage = news_stories.coverage(rows, set())
        self.assertEqual((coverage["publishers"], coverage["origins"], coverage["repeats"]), (5, 4, 1))
        self.assertEqual((coverage["news_origins"], coverage["official_origins"], coverage["company_origins"],
                          coverage["reporting_origins"]), (2, 1, 1, 3))
        self.assertEqual((coverage["confirmed_news"], coverage["confirmed_official"], coverage["possible_news"],
                          coverage["possible_official"]), (2, 1, 0, 0))
        self.assertEqual(news_rank.coverage_words(coverage), "From 5 publishers: 3 confirmed reporting origins "
                         "(2 newsrooms, 1 official statement); 1 copy counted with an origin.")
        wire_unit = next(unit for unit in coverage["units"] if "a:1" in unit["entries"])
        self.assertEqual(wire_unit["entries"], ["a:1", "b:1"])
        self.assertIn("the same wire credit (Reuters)", wire_unit["counted_together_because"])

    def test_a_news_site_republishing_an_official_text_is_the_official_statement(self):
        text = "The Ministry announced a 15% tariff on imported steel from next month, after a review of the industry."
        coverage = news_stories.coverage([report("o:1", "Synthetic Ministry", "Ministry sets steel tariff", text,
                                                 role="official"),
                                          report("n:1", "Synthetic Portal", "Steel tariff: the ministry's notice", text)],
                                         set())
        self.assertEqual((coverage["origins"], coverage["official_origins"], coverage["news_origins"]), (1, 1, 0))

    def test_what_cannot_be_established_is_recorded_not_assumed(self):
        rows = [report("a:1", "Synthetic Daily", "Republic sets a 15% steel tariff after long review",
                       "The Republic set a 15% tariff on imported steel after a long review of its steel industry, "
                       "officials said on Monday in the capital."),
                report("b:1", "Synthetic Times", "Republic sets 15% steel tariff after review",
                       "After a review of its steel industry, the Republic said on Monday it set a tariff of 15% on "
                       "imported steel, according to officials in the capital city."),
                report("c:1", "Synthetic Wire Index", "Steel duties rise in the Republic", None)]
        coverage = news_stories.coverage(rows, set())
        self.assertEqual(coverage["origins"], 3)  # Not joined: neither the same headline, text nor credit.
        self.assertEqual(coverage["uncertain"], 2)
        self.assertEqual((coverage["reporting_origins"], coverage["confirmed_news"], coverage["possible_news"]),
                         (3, 1, 2))
        reasons = " ".join(reason for unit in coverage["units"] for reason in unit["uncertain_because"])
        self.assertIn("headlines are similar", reasons)
        self.assertIn("only its headline is held", reasons)
        self.assertEqual(len(coverage["possible_shared_origins"]), 1)


class CoverageWordsTest(unittest.TestCase):
    """The coverage sentence counts confirmed reporting origins apart from possible ones: it never calls an origin
    independent first and qualifies that afterwards."""

    def words(self, **counts) -> str:
        base = {"publishers": 3, "repeats": 0, "confirmed_news": 0, "confirmed_official": 0, "possible_news": 0,
                "possible_official": 0}
        return news_rank.coverage_words({**base, **counts})

    def test_confirmed_and_possible_origins_are_named_apart_by_kind(self):
        text = self.words(confirmed_official=1, possible_news=2)
        self.assertEqual(text, "From 3 publishers: 1 confirmed reporting origin (1 official statement) and 2 possible "
                               "origins (2 newsrooms) whose independence is not established, which count half.")
        self.assertNotIn("independent origin", text)

    def test_only_possible_origins_are_never_called_confirmed(self):
        text = self.words(publishers=2, possible_news=2)
        self.assertEqual(text, "From 2 publishers: 2 possible origins (2 newsrooms) whose independence is not "
                               "established, which count half.")

    def test_one_origin_alone_is_a_reporting_origin(self):
        self.assertEqual(self.words(publishers=2, confirmed_news=1, repeats=1),
                         "From 2 publishers: 1 reporting origin (1 newsroom); 1 copy counted with an origin.")


class BreadthRankingTest(unittest.TestCase):
    def signals(self, units: list[tuple[str, str]], first_hours: float = 30, importance: str | None = None) -> dict:
        now = START
        counted = lambda role, independence: sum(1 for unit in units if unit == (role, independence))  # noqa: E731
        coverage = {"units": [{"role": role, "independence": independence} for role, independence in units],
                    "reporting_origins": sum(1 for role, _ in units if role != "company"),
                    "confirmed_news": counted("news", "established"),
                    "confirmed_official": counted("official", "established"),
                    "possible_news": counted("news", "unverified"),
                    "possible_official": counted("official", "unverified"),
                    "news_origins": sum(1 for role, _ in units if role == "news"),
                    "official_origins": sum(1 for role, _ in units if role == "official"),
                    "publishers": len(units), "repeats": 0,
                    "uncertain": sum(1 for _, independence in units if independence == "unverified")}
        rated = {"points": 1.75, "level": importance, "text": "Assessed as an adopted policy decision."} \
            if importance else None
        story = {"latest_at": (now - timedelta(hours=first_hours)).isoformat(),
                 "first_at": (now - timedelta(hours=first_hours)).isoformat(), "latest_basis": "published",
                 "first_basis": "published", "coverage": coverage, "priority": None, "topic": None,
                 "relevance": {"state": "relevant", "importance": rated, "annotation": {"method": "synthetic"}}}
        return news_rank.signals(story, now)

    def test_independent_newsrooms_weigh_fully_officials_and_unverified_half_companies_not_at_all(self):
        points = lambda rows: next((row["points"] for row in rows["signals"] if row["signal"] == "coverage"), 0.0)  # noqa: E731
        self.assertEqual(points(self.signals([("news", "established")])), 0.0)
        self.assertEqual(points(self.signals([("news", "established")] * 3)), 2.0)
        self.assertEqual(points(self.signals([("news", "established"), ("official", "established")])), 0.5)
        self.assertEqual(points(self.signals([("news", "established"), ("news", "unverified")])), 0.5)
        self.assertEqual(points(self.signals([("news", "established"), ("company", "established")])), 0.0)
        self.assertEqual(points(self.signals([("news", "established")] * 6)), news_rank.BREADTH_CAP)

    def test_wide_coverage_lifts_a_story_and_breaking_news_from_one_source_stays_visible(self):
        older_wide = self.signals([("news", "established")] * 4, first_hours=20)
        older_single = self.signals([("news", "established")], first_hours=20)
        self.assertGreater(older_wide["score"] - older_single["score"], 2.9)  # Breadth is a substantial signal.
        breaking = self.signals([("official", "established")], first_hours=1, importance="high")
        self.assertIn("breaking", [row["signal"] for row in breaking["signals"]])
        self.assertGreater(breaking["score"], older_wide["score"])
        quiet = self.signals([("official", "established")], first_hours=1, importance="low")
        self.assertNotIn("breaking", [row["signal"] for row in quiet["signals"]])


class MatchingTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        hours = lambda value: START - timedelta(hours=value)  # noqa: E731
        answers = trade_feeds(START)
        answers[COURIER.feed_url] = (200, rss([
            item(COURIER.link_host, "duties", "Steel buyers brace as Synthetic Republic duties hit 15%", hours(40),
                 "Importers in Synthetic Capital said the Synthetic Republic's new 15% levy would apply from next month."),
            item(COURIER.link_host, "festival", "Synthetic Capital hosts its autumn music festival", hours(30),
                 "Bands played in Synthetic Capital over the weekend.")]))
        self.desk = desk_in(Path(folder.name), network=Feeds(answers))
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher,
                           [row for row in self.desk.publishers.values() if row.synthetic], lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        assess(self.desk, START)
        self.keys = iter(f"match-key-{n:04d}" for n in range(1000))

    def story_id(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def candidates(self) -> list[dict]:
        return news_matching.candidates(news_views.world(self.desk, START), START)

    def test_different_headlines_about_one_development_are_suggested_with_evidence_and_merged_on_decision(self):
        tariff, duties = self.story_id(TARIFF), self.story_id("Steel buyers brace as Synthetic Republic duties hit 15%")
        pair = sorted([tariff, duties])
        row = next(row for row in self.candidates() if row["stories"] == pair)
        self.assertIn("15%", row["evidence"]["figures"])
        self.assertTrue(row["cross_publisher"] and row["assistant_may_judge"])
        festival = self.story_id("Synthetic Capital hosts its autumn music festival")
        self.assertFalse(any(festival in row["stories"] and tariff in row["stories"] for row in self.candidates()))
        done, created = news_matching.decide(self.desk, pair[0], pair[1], {
            "decision": "same", "reason": "SYNTHETIC: the same tariff, reported in other words.",
            "idempotency_key": next(self.keys)}, "editor", {"editor": True}, "admin-1", START)
        self.assertTrue(created)
        found = news_views.world(self.desk, START)
        merged = found["stories"][tariff] if tariff in found["stories"] else found["stories"][duties]
        self.assertEqual((merged["coverage"]["publishers"], merged["coverage"]["news_origins"]), (2, 2))
        self.assertNotIn(pair, [row["stories"] for row in self.candidates()])
        again, created = news_matching.decide(self.desk, pair[0], pair[1], {
            "decision": "different", "reason": "SYNTHETIC: a second thought.", "idempotency_key": next(self.keys)},
            "editor", {"editor": True}, "admin-1", START)
        self.assertEqual((created, again["decision"]), (False, "same"))  # The first decision stands.

    def test_related_developments_are_linked_under_a_topic_and_different_ones_are_not_suggested_again(self):
        tariff, revision = self.story_id(TARIFF), self.story_id(REVISION)
        done, _ = news_matching.decide(self.desk, tariff, revision, {
            "decision": "related", "reason": "SYNTHETIC: a tariff and its later revision.", "topic_id": None,
            "topic_title": "Synthetic steel tariff", "idempotency_key": next(self.keys)}, "editor", {"editor": True},
            "admin-1", START)
        found = news_views.world(self.desk, START)
        self.assertEqual(found["topics"][done["topic_id"]]["timeline"], [tariff, revision])
        self.assertIn(tariff, found["stories"])  # Separate developments stay separate stories.
        self.assertIn(revision, found["stories"])
        rows = ns.state(self.desk.newsroom)["match_decisions"]
        self.assertEqual([(row["decision"], row["method"]) for row in rows], [("related", "editor")])

    def test_an_assistant_may_judge_only_material_that_may_be_used_by_a_model(self):
        from unittest import mock
        world = news_views.world(self.desk, START)
        first, second = list(world["stories"])[:2]
        world["stories"][first]["material"]["reports"] = []  # As a publisher allowing no use by a model.
        with mock.patch.object(news_views, "world", lambda *args, **kwargs: world), \
                self.assertRaises(AccountsRefused) as refused:
            news_matching.decide(self.desk, first, second, {"decision": "different", "reason": "SYNTHETIC check.",
                                                            "idempotency_key": "match-restricted-01"}, "assisted",
                                 {"assistant": {"tool": "SYNTHETIC"}}, "admin-1", START)
        self.assertEqual(refused.exception.code, "restricted")
        self.assertEqual(ns.state(self.desk.newsroom)["match_decisions"], [])

    def test_the_route_records_an_editors_decision(self):
        from account_fakes import ADMIN_WRITE, World
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        accounts = World(Path(folder.name))
        app = accounts.client("admin", desk=self.desk)
        tariff, duties = self.story_id(TARIFF), self.story_id("Steel buyers brace as Synthetic Republic duties hit 15%")
        form = {"story_a": tariff, "story_b": duties, "decision": "different", "reason": "SYNTHETIC check.",
                "topic_id": None, "topic_title": None, "idempotency_key": "route-match-0001"}
        made = app.post("/api/admin/news/matches", headers=ADMIN_WRITE, json=form)
        self.assertEqual(made.status_code, 201, made.text)
        self.assertEqual(app.post("/api/admin/news/matches", headers=ADMIN_WRITE, json=form).status_code, 200)
        desk = app.get("/api/admin/news").json()["desk"]
        self.assertEqual(desk["match_decisions"][-1]["decision"], "different")


if __name__ == "__main__":
    unittest.main()
