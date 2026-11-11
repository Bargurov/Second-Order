"""The reader's coverage order uses saved origin evidence, relevance and freshness; no provider is contacted."""
from copy import deepcopy
from datetime import timedelta
import unittest

from news_desk_fakes import START
from test_news_stories import World
from test_news_desk_api import DeskWorld
from second_order import news_rank, news_views


def story(name, units, *, score=1, hot=True, latest=None):
    return {"story_id": name, "latest_at": (latest or START).isoformat(),
            "coverage": {"units": [{"role": role, "independence": independence} for role, independence in units]},
            "rank": {"score": score, "hot": hot}}


class CoverageOrder(unittest.TestCase):
    def test_an_authenticated_reader_opens_the_new_view_without_sending_or_charging(self):
        world = DeskWorld(self)
        reader = world.client("reader-a")
        before = reader.get("/api/user/account").json()
        provider_count = len(world.world.provider.requests)
        reply = reader.get("/api/user/news/stories?view=coverage")
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json()["stories"]["view"], "coverage")
        self.assertEqual(reader.get("/api/user/account").json(), before)
        self.assertEqual(len(world.world.provider.requests), provider_count)

    def test_reporting_breadth_leads_over_article_volume_and_the_hot_score(self):
        broad = story("broad", [("news", "established")] * 3)
        narrow = story("narrow", [("news", "established")], score=100)
        # Copies belong to one unit: extra publishers and entries add no weight.
        narrow["coverage"]["units"][0].update(publishers=["Copy"] * 30, entries=list(range(30)))
        before = deepcopy([narrow, broad])
        self.assertEqual([s["story_id"] for s in news_rank.most_covered([narrow, broad], START)], ["broad", "narrow"])
        self.assertEqual([narrow, broad], before)
        self.assertEqual(news_rank.hot([narrow, broad], START)[0]["story_id"], "narrow")

    def test_possible_and_official_origins_count_half_and_company_origins_nothing(self):
        confirmed = story("confirmed", [("news", "established")])
        possible = story("possible", [("news", "unverified")], score=30)
        official = story("official", [("official", "established")], score=20)
        company = story("company", [("company", "established")] * 20, score=100)
        ranked = news_rank.most_covered([company, possible, official, confirmed], START)
        self.assertEqual([row["story_id"] for row in ranked], ["confirmed", "possible", "official", "company"])

    def test_breadth_is_not_capped_at_hot_nows_points_limit(self):
        units = [("news", "established")] * 10
        small = story("small", units, score=100)
        large = story("large", units + [("news", "established")])
        self.assertEqual(news_rank.breadth_points(small["coverage"]), news_rank.breadth_points(large["coverage"]))
        self.assertEqual(news_rank.most_covered([small, large], START)[0]["story_id"], "large")

    def test_ineligible_stories_stay_out_and_ties_use_hot_score_time_then_id(self):
        unit = [("news", "established")]
        hidden = story("hidden", unit * 50, hot=False)
        old = story("old", unit, latest=START - timedelta(hours=1))
        current = story("b", unit)
        other = story("a", unit)
        important = story("important", unit, score=2)
        ranked = news_rank.most_covered([hidden, old, current, other, important], START)
        self.assertEqual([row["story_id"] for row in ranked], ["important", "a", "b", "old"])

    def test_the_view_uses_the_hot_eligibility_set_and_reads_write_nothing(self):
        world = World(self)
        world.group()
        before = world.network.requests.copy()
        hot = news_views.stories_view(world.desk, "hot", [], START)
        covered = news_views.stories_view(world.desk, "coverage", [], START)
        self.assertEqual({r["story_id"] for r in hot["stories"]}, {r["story_id"] for r in covered["stories"]})
        self.assertEqual(covered, news_views.stories_view(world.desk, "coverage", [], START))
        self.assertEqual(world.network.requests, before)
        self.assertEqual(covered["rank"]["order_version"], news_rank.COVERAGE_ORDER_VERSION)
        self.assertIn("not a measure of worldwide popularity", covered["rank"]["statement"])
        expired = news_views.stories_view(world.desk, "coverage", [], START + timedelta(days=4))
        self.assertEqual(expired["stories"], [])
