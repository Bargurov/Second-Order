"""Other publishers' coverage from the GDELT news index (news-index-0.2), over SYNTHETIC feeds and a SIMULATED index
(httpx MockTransport): one explicit request per story, rate limiting recorded as such with the cooldown it starts, the
matching rule, an explicit attach, coverage by publisher and origin, and reads that request nothing. Nothing reaches a
network."""
from datetime import timedelta
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from argparse import Namespace

from news_desk_fakes import COURIER, START, TARIFF, Feeds, assess, desk_in, item, rss, trade_feeds
from second_order import news_cli, news_feeds, news_index, news_reports, news_stories, news_views
from second_order.accounts import AccountsRefused

DUTIES = "Steel buyers brace as Synthetic Republic duties hit 15% after Marrowvale review"


def seen(hours: float) -> str:
    return (START - timedelta(hours=hours)).strftime("%Y%m%dT%H%M%SZ")


class Index:
    """A SIMULATED GDELT index: answers each request with ``status`` and these articles, and records every request."""

    def __init__(self, articles: list[dict], status: int = 200):
        self.articles, self.status, self.requests, self.headers = articles, status, [], {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(str(request.url))
        if self.status != 200:
            return httpx.Response(self.status, content=b"Please limit requests to one every 5 seconds",
                                  headers=self.headers)
        return httpx.Response(200, content=json.dumps({"articles": self.articles}).encode("utf-8"),
                              headers={"content-type": "application/json"})


def article(domain: str, title: str, hours: float, scheme: str = "https") -> dict:
    return {"url": f"{scheme}://www.{domain}/news/{abs(hash(title)) % 10_000}", "title": title, "domain": domain,
            "seendate": seen(hours), "language": "English", "sourcecountry": "Synthetic"}


class IndexTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        answers = trade_feeds(START)
        answers[COURIER.feed_url] = (200, rss([item(COURIER.link_host, "duties", DUTIES, START - timedelta(hours=40),
                                                    "Importers in Marrowvale said the new 15% levy would apply.")]))
        self.desk = desk_in(Path(folder.name), network=Feeds(answers))
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher,
                           [row for row in self.desk.publishers.values() if row.synthetic], lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        assess(self.desk, START)
        self.story_id = next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                             if story["title"] == DUTIES)
        self.index = Index([
            article("synthetic-wire.example", "Marrowvale importers brace for 15% steel duties", 30),
            article("synthetic-post.example", "Marrowvale importers brace for 15% steel duties", 29),  # A copy.
            article("synthetic-review.example", "Republic's Marrowvale review ends with 15% duties", 28),
            article("synthetic-sport.example", "Marrowvale wins the cup", 30),  # One name only, no figure.
            article("synthetic-old.example", "Marrowvale steel duties of 15% proposed", 24 * 9),  # Too early.
            article("synthetic-plain.example", "Marrowvale 15% steel duties confirmed", 27, scheme="http"),
        ])

    def lookup(self, at=START) -> dict:
        return news_index.lookup(self.desk, self.story_id, at, httpx.MockTransport(self.index))

    def test_one_explicit_request_is_recorded_with_what_the_matching_rule_accepts(self):
        before = news_views.world(self.desk, START)["stories"][self.story_id]
        record = self.lookup()
        self.assertEqual(len(self.index.requests), 1)
        self.assertIn("api.gdeltproject.org", self.index.requests[0])
        self.assertIn("marrowvale", record["query"]["names"])
        self.assertEqual(record["outcome"], "ok")
        accepted = {row["domain"] for row in record["articles"] if row["match"]["accepted"]}
        self.assertEqual(accepted, {"synthetic-wire.example", "synthetic-post.example", "synthetic-review.example"})
        reasons = {row["domain"]: row["match"]["why"] for row in record["articles"]}
        self.assertIn("outside the lookup's window", reasons["synthetic-old.example"])
        self.assertIn("not an https address", reasons["synthetic-plain.example"])
        self.assertEqual(news_index.lookups(self.desk.index, self.story_id)[0]["lookup_id"], record["lookup_id"])
        after = news_views.world(self.desk, START)["stories"][self.story_id]
        self.assertEqual(after["coverage"], before["coverage"])  # A lookup attaches nothing by itself.

    def test_a_rate_limited_answer_says_nothing_is_known_and_stops_a_run(self):
        self.index.status = 429
        record = self.lookup()
        self.assertEqual((record["outcome"], record["status"], record["articles"]), ("rate_limited", 429, []))
        self.assertIn("Nothing is known about coverage", record["detail"])
        pauses = []
        rows = news_index.lookup_many(self.desk, [self.story_id, self.story_id], lambda: START + timedelta(hours=1),
                                      httpx.MockTransport(self.index), sleep=pauses.append)
        self.assertEqual([row["outcome"] for row in rows], ["rate_limited"])  # The run stops at the first 429.
        cooling = news_index.lookup_many(self.desk, [self.story_id, self.story_id], lambda: START + timedelta(hours=1),
                                         httpx.MockTransport(self.index), sleep=pauses.append)
        self.assertEqual([row["outcome"] for row in cooling], ["index_cooling_down"])  # Refused before any request.
        self.assertEqual(len(self.index.requests), 2)

    def test_a_rate_limited_answer_records_its_limit_and_no_request_is_sent_until_the_cooldown_ends(self):
        self.index.status, self.index.headers = 429, {"Retry-After": "120"}
        record = self.lookup()
        self.assertEqual(record["rate_limit"], {
            "retry_after": "120", "message": "Please limit requests to one every 5 seconds", "consecutive": 1,
            "cooldown_seconds": news_index.COOLDOWN_SECONDS,
            "cooldown_until": (START + timedelta(seconds=news_index.COOLDOWN_SECONDS)).isoformat()})
        with self.assertRaises(AccountsRefused) as refused:
            self.lookup(START + timedelta(minutes=5))
        self.assertEqual(refused.exception.code, "index_cooling_down")
        self.assertIn("no request is sent before", str(refused.exception))
        self.assertEqual(len(self.index.requests), 1)  # Nothing was sent, and nothing was recorded.
        self.assertEqual(len(news_index.lookups(self.desk.index, self.story_id)), 1)

    def test_each_further_rate_limit_doubles_the_cooldown_and_an_answer_ends_it(self):
        self.index.status = 429
        first = self.lookup()
        later = START + timedelta(seconds=news_index.COOLDOWN_SECONDS + 60)
        second = self.lookup(later)
        self.assertEqual((second["rate_limit"]["consecutive"], second["rate_limit"]["cooldown_seconds"]),
                         (2, 2 * news_index.COOLDOWN_SECONDS))
        self.assertIsNone(first["rate_limit"]["retry_after"])
        self.index.status = 200
        after = later + timedelta(seconds=2 * news_index.COOLDOWN_SECONDS + 1)
        self.assertEqual(self.lookup(after)["outcome"], "ok")
        self.assertIsNone(news_index.cooldown(self.desk.index, after + timedelta(seconds=1)))
        self.assertEqual(self.lookup(after + timedelta(seconds=2))["outcome"], "ok")

    def test_a_longer_retry_after_is_respected_and_the_cooldown_is_capped(self):
        self.index.status, self.index.headers = 429, {"Retry-After": "7200"}
        self.assertEqual(self.lookup()["rate_limit"]["cooldown_seconds"], 7200)
        self.index.headers = {"Retry-After": "10000000"}
        self.assertEqual(self.lookup(START + timedelta(hours=3))["rate_limit"]["cooldown_seconds"],
                         news_index.MAX_COOLDOWN_SECONDS)

    def test_the_status_shows_the_cooldown_and_the_coverage_kept_from_earlier_answers(self):
        record = self.lookup()
        news_index.attach(self.desk, self.story_id, record["lookup_id"], {"reason": "SYNTHETIC: indexed coverage.",
                                                                         "idempotency_key": "attach-key-0001"},
                          "setup", START)
        kept = news_views.world(self.desk, START)["stories"][self.story_id]["coverage"]
        self.index.status = 429
        self.lookup(START + timedelta(minutes=1))
        now = START + timedelta(minutes=2)
        status = news_index.status(self.desk.index, now)
        self.assertTrue(status["cooldown"]["active"])
        self.assertEqual(status["cooldown"]["consecutive"], 1)
        self.assertIn("no request is sent before", status["cooldown"]["detail"])
        row = next(row for row in status["stories"] if row["story_id"] == self.story_id)
        self.assertEqual((row["lookups"], row["attached"], row["last_answer_at"], row["last_outcome"]),
                         (2, 3, record["requested_at"], "rate_limited"))
        self.assertIn("kept from the answer of", row["detail"])
        self.assertEqual(news_views.world(self.desk, now)["stories"][self.story_id]["coverage"], kept)
        shown = news_cli._index(Namespace(index_action="status"), self.desk, now)
        self.assertEqual(shown["cooldown"], status["cooldown"])
        self.assertEqual(len(self.index.requests), 2)  # The status reads files only.
        source = next(row for row in news_views.story_view(self.desk, self.story_id, now)["sources"]
                      if row["entry_id"].startswith(news_index.SOURCE_KEY))
        self.assertIn("Kept from a GDELT index lookup", source["published"]["note"])

    def test_attaching_adds_publishers_and_origins_never_material_or_freshness(self):
        before = news_views.world(self.desk, START)["stories"][self.story_id]
        record = self.lookup()
        done, created = news_index.attach(self.desk, self.story_id, record["lookup_id"], {
            "reason": "SYNTHETIC: the index's coverage of the duties.", "idempotency_key": "attach-key-0001"},
            "admin-1", START)
        self.assertEqual((created, len(done["attached"])), (True, 3))
        again, created = news_index.attach(self.desk, self.story_id, record["lookup_id"], {
            "reason": "SYNTHETIC: again.", "idempotency_key": "attach-key-0002"}, "admin-1", START)
        self.assertEqual((created, again["attached"]), (True, []))  # Nothing new is added twice.
        story = news_views.world(self.desk, START)["stories"][self.story_id]
        coverage = story["coverage"]
        self.assertEqual(coverage["publishers"], 4)  # Courier and three indexed domains.
        self.assertEqual(coverage["origins"], 3)  # The two same-title copies are one origin.
        self.assertEqual(coverage["news_origins"], 3)
        self.assertGreaterEqual(coverage["uncertain"], 2)  # Known by headline only: independence not established.
        self.assertEqual((story["first_at"], story["latest_at"]), (before["first_at"], before["latest_at"]))
        self.assertEqual(story["material"]["reports"], before["material"]["reports"])  # Never material.
        reasons = {row["reason"] for row in story["material"]["not_used"]}
        self.assertEqual(reasons, {"Listed from the GDELT index of news coverage: its headline and link only; its "
                                   "text is not held, and nothing of it is used for summaries or analysis."})
        page = news_views.story_view(self.desk, self.story_id, START)
        indexed = [row for row in page["sources"] if row["entry_id"].startswith("gdelt-index:")]
        self.assertEqual(len(indexed), 3)
        self.assertTrue(all(row["attribution"].startswith("Indexed by the GDELT Project") and row["use"] == "listed"
                            for row in indexed))
        rows = news_views.stories_view(self.desk, "latest", [], START)["sources"]
        self.assertIn("gdelt-index", [row["source"] for row in rows])

    def test_the_operator_may_choose_the_query_from_the_storys_own_words_and_plurals_match(self):
        self.index.articles = [article("synthetic-desk.example", "Steel buyer braces for Marrowvale duty", 30),
                               article("synthetic-cup.example", "Marrowvale cup final", 30)]
        record = news_index.lookup(self.desk, self.story_id, START, httpx.MockTransport(self.index),
                                   chosen=["Steel", "duties", "buyers"])
        self.assertEqual((record["query"]["names"], record["query"]["chosen_by"]), (["steel", "duties", "buyers"],
                                                                                  "operator"))
        self.assertIn("steel+duties+buyers", self.index.requests[-1])
        accepted = {row["domain"]: row["match"] for row in record["articles"]}
        self.assertTrue(accepted["synthetic-desk.example"]["accepted"])  # "buyer" and "duty" match their plurals.
        self.assertEqual(accepted["synthetic-desk.example"]["shared_names"], ["buyers", "duties", "marrowvale", "steel"])
        self.assertFalse(accepted["synthetic-cup.example"]["accepted"])
        self.assertEqual(self.lookup()["query"]["chosen_by"], "rule")
        for words in (["steel"], ["steel", "duties", "buyers", "review"], ["steel", "football"]):
            with self.assertRaises(news_index.AccountsRefused):  # Too few, too many, or not the story's own words.
                news_index.lookup(self.desk, self.story_id, START, httpx.MockTransport(self.index), chosen=words)

    def test_reading_requests_nothing_and_a_vague_story_is_not_looked_up(self):
        self.lookup()
        before = len(self.index.requests)
        news_views.stories_view(self.desk, "hot", [], START)
        news_views.story_view(self.desk, self.story_id, START)
        news_index.lookups(self.desk.index, self.story_id)
        self.assertEqual(len(self.index.requests), before)
        record = news_index.lookups(self.desk.index, self.story_id)[0]
        self.assertTrue(set(record["query"]["names"]) <= set(news_index._headline_terms(DUTIES)))  # Its own headline's.
        self.assertNotEqual(self.story_id, next(story_id for story_id, story in news_views.world(
            self.desk, START)["stories"].items() if story["title"] == TARIFF))


if __name__ == "__main__":
    unittest.main()
