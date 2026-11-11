"""Who prepared a shared brief, whether a person read it, whether its material can support one, and whether it still
covers the story's material (story-brief-0.2, newsroom-2), over SYNTHETIC feeds (news_desk_fakes). A newsroom-1 store is
read as it is and written only after its explicit upgrade, which keeps every row."""
from contextlib import closing
from datetime import timedelta
import sqlite3
import tempfile
import unittest
from pathlib import Path

from news_desk_fakes import (LEDGER, REVISION, START, TARIFF, TARIFF_BRIEF, Feeds, assess, desk_in, item, rss,
                             trade_feeds)
from second_order import news_curation, news_feeds, news_reports, news_stories, news_views, story_briefs
from second_order import newsroom_store as ns
from second_order.accounts import AccountsRefused

ASSISTANT = {"tool": "SYNTHETIC assistant", "model": "SYNTHETIC model 1"}


class Desk:
    def __init__(self, test: unittest.TestCase, answers: dict | None = None):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.network = Feeds(answers if answers is not None else trade_feeds(START))
        self.desk = desk_in(self.root, network=self.network)
        self.refresh()
        self.keys = iter(f"prov-key-{number:06d}" for number in range(100_000))

    def refresh(self) -> None:
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: START)

    def group(self) -> None:
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, news_reports.publisher_names(self.desk.publishers), "admin-1",
                           START, next(self.keys))
        assess(self.desk, START)  # SYNTHETIC: every story assessed as relevant, as a relevance batch would.

    def story(self, title: str) -> dict:
        return next(story for story in news_views.world(self.desk, START)["stories"].values()
                    if any(row["title"] == title for row in story["reports"]))

    def content(self, story: dict) -> dict:
        return {**TARIFF_BRIEF, "facts": [{"text": "A 15% tariff on imported steel was announced.",
                                           "reports": [story["material"]["reports"][0]["entry_id"]]}]}

    def assisted(self, title: str = TARIFF) -> dict:
        story = self.story(title)
        done, _ = story_briefs.add_version(
            self.desk.newsroom, story["story_id"], {"content": self.content(story), "based_on": None,
                                                    "idempotency_key": next(self.keys)},
            story["material"], "admin-1", START, method="assisted",
            preparation=story_briefs.assistant_preparation(ASSISTANT["tool"], ASSISTANT["model"], "admin-1"))
        story_briefs.publish(self.desk.newsroom, story["story_id"], {"version": done["version"], "reason": "SYNTHETIC",
                                                                     "idempotency_key": next(self.keys)},
                             "admin-1", START)
        return story


def old_store(path: Path) -> None:
    """A newsroom-1 store, as the first release created it."""
    base = ns.SCHEMA.split(ns.TABLES_2)[0]
    old = base + ns._triggers(tuple(table for table in ns.TABLES
                                    if table not in ns.ADDED_IN_2 + ns.ADDED_IN_3 + ns.ADDED_IN_4))
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, isolation_level=None)) as connection:
        connection.executescript("BEGIN;" + old + "INSERT INTO newsroom_meta VALUES ('schema', 'newsroom-1'); COMMIT;")


class UpgradeTest(unittest.TestCase):
    def test_a_newsroom_1_store_is_read_refuses_writes_and_upgrades_keeping_every_row(self):
        world = Desk(self)
        old_store(world.desk.newsroom.path)
        with closing(sqlite3.connect(world.desk.newsroom.path, isolation_level=None)) as connection:
            connection.execute("INSERT INTO stories VALUES ('story-0000000000000001', 'x:1', '{}', 'admin-1', 'now')")
        folded = ns.state(world.desk.newsroom)
        self.assertEqual((folded["schema"], len(folded["stories"]), folded["reviews"]), ("newsroom-1", 1, {}))
        with self.assertRaises(AccountsRefused) as refused:
            world.group()
        self.assertEqual(refused.exception.code, "newsroom_needs_upgrade")
        done = world.desk.newsroom.upgrade()
        self.assertEqual((done["from"], done["to"], done["upgraded"], done["rows"]["stories"]),
                         ("newsroom-1", "newsroom-4", True, 1))
        self.assertFalse(world.desk.newsroom.upgrade()["upgraded"])  # A second upgrade changes nothing.
        world.group()
        self.assertEqual(ns.state(world.desk.newsroom)["schema"], "newsroom-4")
        with closing(sqlite3.connect(world.desk.newsroom.path, isolation_level=None)) as connection:
            triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
            self.assertTrue({f"{table}_no_{action}" for table in ns.ADDED_IN_2 + ns.ADDED_IN_3 + ns.ADDED_IN_4
                             for action in ("update", "delete")} <= triggers)
            connection.execute("INSERT INTO material_assessments (story_id, material_sha256, verdict, reason, method, "
                               "actor, at) VALUES ('story-0000000000000001', 'x', 'insufficient', 'r', 'editor', "
                               "'admin-1', 'now')")
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("DELETE FROM material_assessments")


class AuthorshipTest(unittest.TestCase):
    def setUp(self):
        self.world = Desk(self)
        self.world.group()

    def test_an_assisted_brief_says_so_and_is_not_said_to_be_reviewed_until_someone_reads_it(self):
        story = self.world.assisted()
        page = news_views.story_view(self.world.desk, story["story_id"], START)
        brief = page["brief"]
        self.assertEqual((brief["method"], brief["authorship"]), ("assisted", "ai_assistant"))
        self.assertEqual(brief["method_label"], "Written with an AI assistant from the material below.")
        self.assertNotIn("editors", brief["method_label"])
        self.assertEqual(brief["review"]["state"], "not_reviewed")
        self.assertNotIn("SYNTHETIC assistant", repr(page))  # The tool and model stay on the operator's desk.
        self.assertNotIn("SYNTHETIC model 1", repr(page))
        story_briefs.review(self.world.desk.newsroom, story["story_id"], {
            "version": brief["version"], "note": "Read against the reports.", "idempotency_key": "review-key-01"},
            "editor-1", START + timedelta(hours=1))
        reviewed = news_views.story_view(self.world.desk, story["story_id"], START)["brief"]["review"]
        self.assertEqual(reviewed["state"], "read_by_editor")
        self.assertNotIn("editor-1", reviewed["statement"])
        row = ns.state(self.world.desk.newsroom)["briefs"][story["story_id"]][-1]
        self.assertEqual(row["preparation"]["assistant"], {"tool": "SYNTHETIC assistant", "model": "SYNTHETIC model 1",
                                                           "declared_by": "admin-1", "note": ""})
        self.assertIsNone(row["preparation"]["model"])  # No usage or model record is invented for an assistant.

    def test_an_editor_written_brief_says_who_wrote_it_and_an_assisted_one_needs_its_assistant(self):
        story = self.world.story(TARIFF)
        with self.assertRaises(AccountsRefused):
            story_briefs.add_version(self.world.desk.newsroom, story["story_id"], {
                "content": self.world.content(story), "based_on": None, "idempotency_key": "assisted-no-tool"},
                story["material"], "admin-1", START, method="assisted", preparation={"model": None, "cost": None})
        with self.assertRaises(AccountsRefused):
            story_briefs.assistant_preparation("", None, "admin-1")
        done, _ = story_briefs.add_version(self.world.desk.newsroom, story["story_id"], {
            "content": self.world.content(story), "method": "editorial", "based_on": None,
            "idempotency_key": "editorial-key-1"}, story["material"], "admin-1", START)
        story_briefs.publish(self.world.desk.newsroom, story["story_id"], {
            "version": done["version"], "reason": "SYNTHETIC", "idempotency_key": "publish-key-1"}, "admin-1", START)
        brief = news_views.story_view(self.world.desk, story["story_id"], START)["brief"]
        self.assertEqual((brief["authorship"], brief["review"]["state"]), ("editor", "written_by_editor"))
        self.assertEqual(brief["method_label"], "Written by an editor from the material below.")

    def test_a_brief_keeps_at_most_three_implications(self):
        story = self.world.story(TARIFF)
        content = {**self.world.content(story), "implications": [{"text": f"It could matter ({n})."} for n in range(4)]}
        with self.assertRaises(AccountsRefused):
            story_briefs.checked_content(content, {row["entry_id"] for row in story["material"]["reports"]})


class MaterialStateTest(unittest.TestCase):
    def test_headline_only_material_and_a_recorded_assessment_say_there_is_not_enough(self):
        hours = lambda value: START - timedelta(hours=value)  # noqa: E731
        world = Desk(self, {LEDGER.feed_url: (200, rss([item(LEDGER.link_host, "bare", "Synthetic bare headline",
                                                             hours(2)),
                                                        item(LEDGER.link_host, "thin", "Synthetic thin report",
                                                             hours(3), "SYNTHETIC: a short excerpt.")]))})
        world.group()
        bare = world.story("Synthetic bare headline")
        page = news_views.story_view(world.desk, bare["story_id"], START)
        self.assertEqual(page["brief_state"], "insufficient")
        self.assertIn("only a headline", page["brief_note"])
        thin = world.story("Synthetic thin report")
        self.assertEqual(news_views.story_view(world.desk, thin["story_id"], START)["brief_state"], "none")
        with self.assertRaises(AccountsRefused):  # A judgement names the material it was made on.
            story_briefs.assess(world.desk.newsroom, thin["story_id"], {
                "material_sha256": "0" * 64, "verdict": "insufficient", "reason": "Too thin.",
                "idempotency_key": "assess-key-0"}, thin["material"], "admin-1", START)
        story_briefs.assess(world.desk.newsroom, thin["story_id"], {
            "material_sha256": thin["material"]["material_sha256"], "verdict": "insufficient",
            "reason": "The excerpt names no measure, date or party.", "idempotency_key": "assess-key-1"},
            thin["material"], "admin-1", START)
        page = news_views.story_view(world.desk, thin["story_id"], START)
        self.assertEqual(page["brief_state"], "insufficient")
        self.assertIn("names no measure", page["brief_note"])
        cards = {row["story_id"]: row for row in news_views.stories_view(world.desk, "latest", [], START)["stories"]}
        self.assertEqual(cards[thin["story_id"]]["brief"]["state"], "insufficient")  # Listed, never hidden.
        self.assertFalse(page["deeper"]["available"])  # Too thin for a reader's paid analysis as well.
        self.assertIn("too thin for an analysis", page["deeper"]["reason"])

    def test_a_published_brief_says_when_the_material_has_changed_since(self):
        world = Desk(self)
        world.group()
        story = world.assisted(REVISION)
        self.assertTrue(news_views.story_view(world.desk, story["story_id"], START)["brief"]["current"])
        later = trade_feeds(START)
        later[LEDGER.feed_url] = (200, rss([item(LEDGER.link_host, "revision-2", REVISION, START - timedelta(hours=1),
                                                 "A second SYNTHETIC report of the revision.")]))
        world.network.answers.update(later)
        world.refresh()
        world.group()
        page = news_views.story_view(world.desk, story["story_id"], START)
        self.assertFalse(page["brief"]["current"])
        self.assertIn("earlier material", page["brief"]["update_note"])
        card = next(row for row in news_views.stories_view(world.desk, "latest", [], START)["stories"]
                    if row["story_id"] == story["story_id"])
        self.assertEqual((card["brief"]["state"], card["brief"]["current"]), ("published", False))


class PlanProvenanceTest(unittest.TestCase):
    def test_a_plan_records_an_assisted_brief_a_review_and_an_assessment(self):
        world = Desk(self)
        world.group()
        story = world.story(TARIFF)
        port = world.story("Synthetic port reports record container volumes")
        plan = {"plan_version": news_curation.PLAN_VERSION, "reason": "SYNTHETIC", "actions": [
            {"key": "brief-tariff", "do": "brief", "story": story["story_id"], "method": "assisted",
             "assistant": ASSISTANT, "content": world.content(story), "publish": True},
            {"key": "read-tariff", "do": "review", "story": story["story_id"], "version": 1},
            {"key": "thin-port", "do": "assess", "story": port["story_id"], "verdict": "insufficient",
             "reason": "SYNTHETIC: the excerpt says only that volumes were a record."}]}
        actions = news_curation.read_plan(plan)
        self.assertTrue(all(row["ok"] for row in news_curation.check(world.desk, actions, START)["checked"]))
        done = news_curation.apply(world.desk, actions, "local-operator", lambda: START)
        self.assertIsNone(done["stopped"])
        brief = news_views.story_view(world.desk, story["story_id"], START)["brief"]
        self.assertEqual((brief["authorship"], brief["review"]["state"]), ("ai_assistant", "read_by_editor"))
        self.assertEqual(news_views.story_view(world.desk, port["story_id"], START)["brief_state"], "insufficient")
        bad = {**plan, "actions": [{**plan["actions"][0], "key": "brief-no-tool", "assistant": {"tool": ""}}]}
        self.assertFalse(news_curation.check(world.desk, news_curation.read_plan(bad), START)["checked"][0]["ok"])


if __name__ == "__main__":
    unittest.main()


class CorrectionTest(unittest.TestCase):
    def test_a_version_recorded_as_an_editors_but_written_with_an_assistant_is_corrected_keeping_its_material(self):
        world = Desk(self)
        world.group()
        story = world.story(TARIFF)
        done, _ = story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": world.content(story), "method": "editorial", "based_on": None,
            "idempotency_key": "wrong-label-1"}, story["material"], "local-operator", START)
        story_briefs.publish(world.desk.newsroom, story["story_id"], {"version": done["version"], "reason": "x",
                                                                      "idempotency_key": "wrong-label-p"},
                             "local-operator", START)
        plan = {"plan_version": news_curation.PLAN_VERSION, "reason": "Version 1 was written with an AI assistant.",
                "actions": [{"key": "fix-tariff", "do": "correct", "story": story["story_id"], "version": 1,
                             "method": "assisted", "assistant": {"tool": "SYNTHETIC assistant"}, "publish": True}]}
        result = news_curation.apply(world.desk, news_curation.read_plan(plan), "local-operator", lambda: START)
        self.assertIsNone(result["stopped"])
        rows = ns.state(world.desk.newsroom)["briefs"][story["story_id"]]
        self.assertEqual([row["method"] for row in rows], ["editorial", "assisted"])  # Version 1 stays as recorded.
        self.assertEqual((rows[1]["content"], rows[1]["material_sha256"]),
                         (rows[0]["content"], rows[0]["material_sha256"]))
        self.assertEqual(rows[1]["preparation"]["corrects"], {"version": 1, "method": "editorial",
                                                               "reason": "Version 1 was written with an AI assistant."})
        brief = news_views.story_view(world.desk, story["story_id"], START)["brief"]
        self.assertEqual((brief["version"], brief["authorship"], brief["review"]["state"]),
                         (2, "ai_assistant", "not_reviewed"))
        again = news_curation.apply(world.desk, news_curation.read_plan(plan), "local-operator", lambda: START)
        self.assertFalse(any(row["created"] for row in again["applied"]))
        with self.assertRaises(AccountsRefused):
            story_briefs.correct_authorship(world.desk.newsroom, story["story_id"], {
                "version": 1, "method": "editorial", "reason": "x", "idempotency_key": "bad-fix-01"},
                {"model": None}, "local-operator", START)
