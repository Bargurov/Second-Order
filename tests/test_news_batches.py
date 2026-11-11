"""Brief coverage of the important stories and their batch preparation (news-coverage-0.1, news-batch-0.1), over
SYNTHETIC feeds and a SYNTHETIC model (news_desk_fakes): selection by the ranking and the material, a recorded preview,
the paid path's single approval with one attempt per request (resumable, never resent), the assisted path's packet and
import, and publication as its own decision. Nothing reaches a network."""
from argparse import Namespace
from dataclasses import replace
from datetime import timedelta
import json
import tempfile
import unittest
from pathlib import Path

from account_fakes import ADMIN_WRITE, World, every_file
from news_desk_fakes import (RESPONSE, RESPONSE_OWN, REVISION, START, TARIFF, UNRELATED, BriefModel, Feeds,
                             approve_batch, assess, both_stages, desk_in, text_desk, trade_feeds)
from second_order import (brief_drafting, news_batches, news_cli, news_feeds, news_reports, news_stories, news_views,
                          story_briefs)
from second_order import newsroom_store as ns
from second_order.accounts import AccountsRefused

KEY = "sk-ant-dummy-simulated-batch-key-00000001"


def good_brief(story: dict) -> dict:
    first = story["material"]["reports"][0]["entry_id"]
    return {"headline": f"SYNTHETIC brief: {story['title'][:60]}",
            "summary": "SYNTHETIC: the reports state a development.",
            "facts": [{"text": "SYNTHETIC fact as reported.", "reports": [first]}],
            "implications": [{"text": "SYNTHETIC: it could matter to the sector if it lasts."},
                             {"text": "SYNTHETIC: a later revision would be a new development."}],
            "themes": [], "uncertainties": ["SYNTHETIC: the duration is not stated."], "missing": []}


class Batch:
    """The SYNTHETIC trade world, grouped, with the response merged; optionally a SYNTHETIC model to send to."""

    def __init__(self, test: unittest.TestCase, model: bool = False):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.network = Feeds(trade_feeds(START))
        self.model = BriefModel(KEY) if model else None
        self.desk = desk_in(self.root, network=self.network, drafting=self.model.sender() if model else None)
        synthetic = [publisher for publisher in self.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, synthetic, lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        news_stories.merge(self.desk.newsroom, self.story_id(RESPONSE_OWN), {
            "into": self.story_id(RESPONSE), "reason": "one response", "idempotency_key": "merge-key-0001"}, "setup",
            START)
        assess(self.desk, START)  # SYNTHETIC: every story assessed as relevant, as a relevance batch would.
        self.ticks = iter(START + timedelta(seconds=n) for n in range(100_000))

    def clock(self):
        return next(self.ticks)

    def story_id(self, title: str) -> str:
        return next(story_id for story_id, story in news_views.world(self.desk, START)["stories"].items()
                    if any(row["title"] == title for row in story["reports"]))

    def story(self, title: str) -> dict:
        return news_views.world(self.desk, START)["stories"][self.story_id(title)]

    def story_now(self, story_id: str) -> dict:
        return news_views.world(self.desk, START)["stories"][story_id]

    def publish_editorial(self, title: str) -> None:
        story = self.story(title)
        done, _ = story_briefs.add_version(self.desk.newsroom, story["story_id"], {
            "content": good_brief(story), "method": "editorial", "based_on": None,
            "idempotency_key": f"ed-{story['story_id'][6:]}"}, story["material"], "setup", START)
        story_briefs.publish(self.desk.newsroom, story["story_id"], {"version": done["version"], "reason": "ok",
                                                                     "idempotency_key": f"pub-{story['story_id'][6:]}"},
                             "setup", START)

    def coverage(self) -> dict:
        return news_batches.coverage(self.desk, START)


class CoverageTest(unittest.TestCase):
    def test_each_important_story_says_whether_a_reader_gets_a_brief_and_none_is_hidden(self):
        world = Batch(self)
        world.publish_editorial(REVISION)
        report = world.coverage()
        rows = {row["title"]: row for row in report["important"]["rows"]}
        hot = [story["story_id"] for story in news_views.stories_view(world.desk, "hot", [], START)["stories"]]
        self.assertEqual([row["story_id"] for row in report["important"]["rows"]], hot)  # Hot now, in its order.
        self.assertEqual(rows[REVISION]["state"], "ready")
        self.assertEqual(rows[UNRELATED]["state"], "pending")
        self.assertEqual(sum(report["important"]["counts"].values()), len(hot))
        self.assertEqual(report["important"]["ready_share_of_eligible"],
                         round(1 / report["important"]["eligible"], 3))

    def test_a_brief_of_earlier_material_needs_an_update_and_a_saved_version_is_drafted(self):
        world = Batch(self)
        story = world.story(UNRELATED)
        story_briefs.add_version(world.desk.newsroom, story["story_id"], {
            "content": good_brief(story), "method": "editorial", "based_on": None, "idempotency_key": "draft-key-01"},
            story["material"], "setup", START)
        self.assertEqual(news_batches.state_of(ns.state(world.desk.newsroom), world.story(UNRELATED)), "drafted")
        texts, _ = text_desk(world.root / "texts", retrieve=False)
        found = news_views.world(texts, START)
        fact = next(story for story in found["stories"].values() if story["material"]["reports"] and
                    "fact sheet" in story["title"].lower() and "table" not in story["title"])
        content = good_brief(fact)
        done, _ = story_briefs.add_version(texts.newsroom, fact["story_id"], {
            "content": content, "method": "editorial", "based_on": None, "idempotency_key": "text-ed-001"},
            fact["material"], "setup", START)
        story_briefs.publish(texts.newsroom, fact["story_id"], {"version": done["version"], "reason": "ok",
                                                                "idempotency_key": "text-pub-001"}, "setup", START)
        from second_order import news_texts
        news_texts.retrieve_all(texts.texts, fact["reports"], {}, texts.text_fetcher, lambda: START,
                                sleep=lambda seconds: None)
        after = news_views.world(texts, START)
        self.assertEqual(news_batches.state_of(after["folded"], after["stories"][fact["story_id"]]), "update")


class PaidBatchTest(unittest.TestCase):
    def test_a_preview_selects_by_rank_and_records_the_exact_requests_and_their_total(self):
        world = Batch(self, model=True)
        world.publish_editorial(REVISION)
        batch, created = news_batches.preview(world.desk, START, "model", limit=2)
        self.assertTrue(created)
        rows = world.coverage()["important"]["rows"]
        needed = [row["story_id"] for row in rows if row["state"] == "pending" or row["explanation"] == "pending"]
        self.assertEqual([item["story_id"] for item in batch["items"]], needed[:2])  # Hot now's order.
        actions = {item["story_id"]: item["action"] for item in batch["items"]}
        # A published brief without an economic explanation is explained; a story without a brief is prepared.
        self.assertEqual(actions.get(world.story_id(REVISION), "explain"), "explain")
        self.assertTrue(all(action in ("prepare", "explain") for action in actions.values()))
        self.assertEqual(batch["estimated_max_usd_total"],
                         round(sum(item["draft"]["estimated_max_usd"] for item in batch["items"]), 4))
        for item in batch["items"]:
            request = world.desk.newsroom.path.parent / "drafting" / item["draft"]["draft_id"] / "request.json"
            self.assertTrue(request.is_file())
        again, created = news_batches.preview(world.desk, START, "model", limit=2)
        self.assertEqual((again["batch_id"], created), (batch["batch_id"], False))  # The same selection, one record.
        self.assertEqual(world.model.requests, [])  # Previewing sends nothing.
        with self.assertRaises(AccountsRefused):
            news_batches.preview(world.desk, START, "model", limit=0)

    def test_one_approval_sends_each_request_once_and_a_repeat_resumes_without_resending(self):
        world = Batch(self, model=True)
        batch, _ = news_batches.preview(world.desk, START, "model", limit=3)
        wrong = {"batch_id": batch["batch_id"], "approve_paid_requests": True,
                 "estimated_max_usd_total": batch["estimated_max_usd_total"] + 1}
        with self.assertRaises(AccountsRefused) as refused:
            news_batches.approve(world.desk, batch["batch_id"], wrong, world.story_now, "admin-1", world.clock)
        self.assertEqual(refused.exception.code, "approval_mismatch")
        self.assertEqual(world.model.requests, [])
        # An interruption after one send started: that request is never sent again.
        first = batch["items"][0]["draft"]["draft_id"]
        folder = world.desk.newsroom.path.parent / "drafting" / first
        (folder / "attempt.json").write_text("{}", encoding="utf-8")
        (folder / "sent.json").write_text("{}", encoding="utf-8")
        form = {**wrong, "estimated_max_usd_total": batch["estimated_max_usd_total"]}
        done = news_batches.approve(world.desk, batch["batch_id"], form, world.story_now, "admin-1", world.clock)
        outcomes = [row["outcome"] for row in done["items"]]
        self.assertEqual(outcomes, ["already_attempted", "sent", "sent"])
        self.assertEqual(len(world.model.requests), 2)
        again = news_batches.approve(world.desk, batch["batch_id"], form, world.story_now, "admin-1", world.clock)
        self.assertEqual([row["outcome"] for row in again["items"]], ["already_attempted"] * 3)
        self.assertEqual(len(world.model.requests), 2)  # No request was sent twice, nothing charged twice.
        self.assertEqual([row["stage"] for row in done["items"]], [1, 1, 1])
        self.assertEqual([row["next"]["stage"] for row in done["items"][1:]], [2, 2])  # Prepared, not sent.
        status = news_batches.status(world.desk, batch["batch_id"], START)
        self.assertEqual([row["version"] for row in status["items"]], [None] * 3)  # Stage 1 alone saves none.
        second, _ = news_batches.preview(world.desk, START, "model", limit=3,
                                         story_ids=[item["story_id"] for item in batch["items"]])
        self.assertEqual([item["story_id"] for item in second["items"]],
                         [item["story_id"] for item in batch["items"][1:]])  # The interrupted one stopped.
        self.assertEqual({item["draft"]["stage"] for item in second["items"]}, {2})
        self.assertIn("never sent again", second["left"][-1]["drafting"])
        approve_batch(world.desk, second, world.story_now, "admin-1", world.clock)
        self.assertEqual(len(world.model.requests), 4)
        status = news_batches.status(world.desk, batch["batch_id"], START)
        self.assertEqual([row["version"] is not None for row in status["items"]], [False, True, True])
        self.assertEqual(status["approval"]["estimated_max_usd_total"], batch["estimated_max_usd_total"])

    def test_nothing_is_sent_without_paid_drafting_and_a_changed_story_is_skipped(self):
        world = Batch(self, model=True)
        batch, _ = news_batches.preview(world.desk, START, "model", limit=2)
        form = {"batch_id": batch["batch_id"], "approve_paid_requests": True,
                "estimated_max_usd_total": batch["estimated_max_usd_total"]}
        with self.assertRaises(AccountsRefused) as refused:
            news_batches.approve(replace(world.desk, drafting=None), batch["batch_id"], form, world.story_now,
                                 "admin-1", world.clock)
        self.assertEqual(refused.exception.code, "paid_drafting_disabled")
        changed = batch["items"][0]["story_id"]
        story_briefs.assess(world.desk.newsroom, changed, {
            "material_sha256": batch["items"][0]["material_sha256"], "verdict": "sufficient", "reason": "x",
            "idempotency_key": "assess-key-01"}, world.story_now(changed)["material"], "admin-1", START)
        world.network.answers.update({key: value for key, value in trade_feeds(START + timedelta(hours=1)).items()})
        synthetic = [publisher for publisher in world.desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(world.desk.feeds, world.desk.fetcher, synthetic, lambda: START + timedelta(hours=1))
        done = news_batches.approve(world.desk, batch["batch_id"], form, world.story_now, "admin-1", world.clock)
        self.assertTrue(all(row["outcome"] in ("sent", "story_changed") for row in done["items"]))

    def test_publication_is_its_own_decision_and_a_review_is_recorded_only_when_stated(self):
        world = Batch(self, model=True)
        batch, _ = news_batches.preview(world.desk, START, "model", limit=2)
        both_stages(world.desk, batch, START, world.story_now, "admin-1", world.clock)
        before = news_views.stories_view(world.desk, "hot", [], START)
        self.assertFalse(any(row["brief"]["state"] == "published" for row in before["stories"]))  # Not yet published.
        with self.assertRaises(AccountsRefused):
            news_batches.publish(world.desk, batch["batch_id"], {"reason": "", "reviewed": False}, "admin-1",
                                 world.clock)
        done = news_batches.publish(world.desk, batch["batch_id"], {"reason": "SYNTHETIC batch", "reviewed": False},
                                    "admin-1", world.clock)
        self.assertEqual([row["outcome"] for row in done["items"]], ["published", "published"])
        page = news_views.story_view(world.desk, batch["items"][0]["story_id"], START)
        self.assertEqual((page["brief"]["authorship"], page["brief"]["review"]["state"]), ("ai_model", "not_reviewed"))
        again = news_batches.publish(world.desk, batch["batch_id"], {"reason": "SYNTHETIC batch", "reviewed": True},
                                     "admin-1", world.clock)
        self.assertEqual([row["outcome"] for row in again["items"]], ["already_published"] * 2)
        self.assertEqual(ns.state(world.desk.newsroom)["reviews"], {})  # Nothing newly published, nothing reviewed.


class AssistedBatchTest(unittest.TestCase):
    def test_the_packet_import_and_publication_label_ai_assisted_work_and_repeat_safely(self):
        world = Batch(self)
        batch, _ = news_batches.preview(world.desk, START, "assisted", limit=3)
        self.assertIsNone(batch["estimated_max_usd_total"])
        packet = news_batches.packet(world.desk, batch["batch_id"], START)
        self.assertEqual(len(packet["items"]), 3)
        self.assertIn("insufficient_material", packet["rules"])
        first, second, third = (item["story_id"] for item in batch["items"])
        stories = news_views.world(world.desk, START)["stories"]
        drafts = {"batch_id": batch["batch_id"], "drafts": [
            {"story_id": first, "material_sha256": batch["items"][0]["material_sha256"],
             "brief": good_brief(stories[first])},
            {"story_id": second, "material_sha256": batch["items"][1]["material_sha256"],
             "insufficient_material": "SYNTHETIC: the excerpt says too little."},
            {"story_id": third, "material_sha256": "0" * 64, "brief": good_brief(stories[third])}]}
        done = news_batches.import_drafts(world.desk, batch["batch_id"], drafts, "SYNTHETIC assistant", None,
                                          "local-operator", world.clock)
        self.assertEqual([row["outcome"] for row in done["items"]], ["saved", "insufficient", "story_changed"])
        again = news_batches.import_drafts(world.desk, batch["batch_id"], drafts, "SYNTHETIC assistant", None,
                                           "local-operator", world.clock)
        self.assertEqual([row["outcome"] for row in again["items"]], ["already_saved", "already_recorded",
                                                                      "story_changed"])
        row = ns.state(world.desk.newsroom)["briefs"][first][-1]
        self.assertEqual((row["method"], row["preparation"]["assistant"]["tool"], row["preparation"]["batch_id"]),
                         ("assisted", "SYNTHETIC assistant", batch["batch_id"]))
        self.assertIsNone(row["preparation"]["assistant"]["model"])
        published = news_batches.publish(world.desk, batch["batch_id"], {"reason": "SYNTHETIC", "reviewed": True},
                                         "local-operator", world.clock)
        self.assertEqual([row["outcome"] for row in published["items"]], ["published", "no_version", "no_version"])
        brief = news_views.story_view(world.desk, first, START)["brief"]
        self.assertEqual((brief["authorship"], brief["review"]["state"]), ("ai_assistant", "read_by_editor"))
        self.assertEqual(news_views.story_view(world.desk, second, START)["brief_state"], "insufficient")
        with self.assertRaises(AccountsRefused):
            news_batches.approve(world.desk, batch["batch_id"], {}, world.story_now, "admin-1", world.clock)

    def test_reading_coverage_a_batch_and_its_packet_writes_and_requests_nothing(self):
        world = Batch(self)
        batch, _ = news_batches.preview(world.desk, START, "assisted", limit=2)
        before, requests = every_file(world.root), len(world.network.requests)
        world.coverage()
        news_batches.status(world.desk, batch["batch_id"], START)
        news_batches.packet(world.desk, batch["batch_id"], START)
        self.assertEqual((every_file(world.root), len(world.network.requests)), (before, requests))


class BatchRoutesTest(unittest.TestCase):
    def test_the_desk_previews_approves_once_and_publishes_on_the_real_application(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        accounts = World(Path(folder.name))
        accounts.standard_terms()
        model = BriefModel(KEY)
        desk = desk_in(accounts.root, network=Feeds(trade_feeds(START)), drafting=model.sender())
        synthetic = [publisher for publisher in desk.publishers.values() if publisher.synthetic]
        news_feeds.refresh(desk.feeds, desk.fetcher, synthetic, lambda: START)
        reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
        news_stories.group(desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        assess(desk, START)
        admin = accounts.client("admin", desk=desk)
        coverage = admin.get("/api/admin/news/coverage").json()["coverage"]
        self.assertTrue(coverage["readiness"]["paid_drafting"]["enabled"])
        self.assertTrue(coverage["readiness"]["credit_policy"]["published"])
        made = admin.post("/api/admin/news/batches", headers=ADMIN_WRITE, json={"method": "model", "limit": 2,
                                                                                "story_ids": None})
        self.assertEqual(made.status_code, 201, made.text)
        batch = made.json()["batch"]
        self.assertEqual(model.requests, [])
        approval = {"batch_id": batch["batch_id"], "approve_paid_requests": True,
                    "estimated_max_usd_total": batch["estimated_max_usd_total"]}
        sent = admin.post(f"/api/admin/news/batches/{batch['batch_id']}/approval", headers=ADMIN_WRITE, json=approval)
        self.assertEqual(sent.status_code, 200, sent.text)
        self.assertEqual(len(model.requests), 2)
        admin.post(f"/api/admin/news/batches/{batch['batch_id']}/approval", headers=ADMIN_WRITE, json=approval)
        self.assertEqual(len(model.requests), 2)
        made = admin.post("/api/admin/news/batches", headers=ADMIN_WRITE, json={  # The stories' second stage.
            "method": "model", "limit": 2, "story_ids": [item["story_id"] for item in batch["items"]]})
        second = made.json()["batch"]
        self.assertEqual(({item["draft"]["stage"] for item in second["items"]}, len(model.requests)), ({2}, 2))
        admin.post(f"/api/admin/news/batches/{second['batch_id']}/approval", headers=ADMIN_WRITE, json={
            "batch_id": second["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": second["estimated_max_usd_total"]})
        self.assertEqual(model.stages(), [1, 1, 2, 2])
        published = admin.post(f"/api/admin/news/batches/{batch['batch_id']}/publication", headers=ADMIN_WRITE,
                               json={"reason": "SYNTHETIC", "reviewed": False}).json()["publication"]
        self.assertEqual([row["outcome"] for row in published["items"]], ["published", "published"])
        reader = accounts.client("reader-a", desk=desk)
        self.assertEqual(reader.get("/api/admin/news/coverage").status_code, 403)
        hot = reader.get("/api/user/news/stories").json()["stories"]["stories"]
        self.assertEqual(sum(1 for row in hot if row["brief"]["state"] == "published"), 2)
        self.assertEqual(len(model.requests), 4)  # Reading the news sent nothing.

    def test_the_commands_preview_import_and_publish_an_assisted_batch(self):
        world = Batch(self)
        preview = news_cli.run(Namespace(news_action="batch", batch_action="preview", method="assisted", limit=1,
                                         story=[world.story_id(UNRELATED)]), world.desk)  # The real clock: by name.
        batch_id = preview["batch"]["batch_id"]
        packet = news_cli.run(Namespace(news_action="batch", batch_action="packet", batch_id=batch_id), world.desk)
        item = packet["items"][0]
        story = news_views.world(world.desk, START)["stories"][item["story_id"]]
        path = world.root / "drafts.json"
        path.write_text(json.dumps({"batch_id": batch_id, "drafts": [{
            "story_id": item["story_id"], "material_sha256": item["material_sha256"], "brief": good_brief(story)}]}),
            encoding="utf-8")
        done = news_cli.run(Namespace(news_action="batch", batch_action="import", batch_id=batch_id, drafts=path,
                                      assistant_tool="SYNTHETIC assistant", assistant_model=None), world.desk)
        self.assertEqual(done["items"][0]["outcome"], "saved")
        published = news_cli.run(Namespace(news_action="batch", batch_action="publish", batch_id=batch_id,
                                           reason="SYNTHETIC", reviewed=False), world.desk)
        self.assertEqual(published["items"][0]["outcome"], "published")
        status = news_cli.run(Namespace(news_action="batch", batch_action="status", batch_id=batch_id), world.desk)
        self.assertEqual(status["items"][0]["coverage_state"], "ready")
        with self.assertRaises(SystemExit):
            news_cli.run(Namespace(news_action="batch", batch_action="status", batch_id="batch-nope"), world.desk)


if __name__ == "__main__":
    unittest.main()
