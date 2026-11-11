"""Update runs (news_updates, news-update-0.1) over SYNTHETIC publishers and feeds: the plan, a run's cutoff and
reference time, one refresh per run, arrivals classified by what their feeds state, the stories they reached, the
preparation steps through the existing batches with a simulated model, partial failures, changed inputs, duplicate
processing, publication timing, the brief's history for readers, and reads that change nothing. Nothing reaches a
network or a provider."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from account_fakes import ADMIN_WRITE, every_file
from model_fixtures import FAKE_KEY
from news_desk_fakes import (EXTENSION, GAZETTE, MINE, RATES, SHIPYARD, START, SYNTHETIC, TARIFF, UNRELATED,
                             BriefModel, Feeds, approve_batch, both_stages, curate, desk_in, insufficient_economics,
                             item, later_items, trade_feeds)
from second_order import (news_baseline, news_batches, news_feeds, news_matching, news_rank, news_registry,
                          news_update_report, news_updates, news_views, relevance_batches, story_briefs, usage)
from second_order.accounts import AccountsRefused
from test_news_desk_api import DeskWorld

T1 = START + timedelta(hours=1)  # The earlier baseline's cutoff: the first run's reference time.
T2 = START + timedelta(hours=3)  # The run.
ACTOR = "synthetic-editor"


def later() -> dict:
    """The SYNTHETIC feeds at T2 (news_desk_fakes.later_items): a new development of the tariff topic and a central
    bank decision, published after T1; a copy of the tariff report on another feed; an older shipyard report not listed
    before; an entry with no publication time; and the museum report's excerpt, revised."""
    return trade_feeds(START, **later_items(lambda hours: START + timedelta(hours=hours)))


class UpdateWorld:
    """SYNTHETIC publishers only, refreshed and curated at START (a published tariff brief, a topic of three
    developments, every story assessed), a baseline at T1, and the later feeds waiting on the simulated network."""

    def __init__(self, test: unittest.TestCase):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.network = Feeds(trade_feeds(START))
        self.model = BriefModel(FAKE_KEY)
        self.model.economics = insufficient_economics
        self.desk = desk_in(self.root, chosen=dict(SYNTHETIC), network=self.network, drafting=self.model.sender())
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, list(SYNTHETIC.values()), lambda: START)
        self.ids = curate(self.desk, START)
        self.baseline, _ = news_baseline.record(self.desk, T1, ACTOR, "SYNTHETIC: before the update")
        self.network.answers.update(later())
        self.ticks = iter(T2 + timedelta(seconds=n) for n in range(100_000))

    def clock(self):
        return next(self.ticks)

    def start(self, key: str = "update-key-0001", at=T2) -> dict:
        run, _ = news_updates.start(self.desk, at, ACTOR, {"label": "SYNTHETIC update", "idempotency_key": key,
                                                           "official": False})
        return run

    def refreshed(self) -> dict:
        run = self.start()
        news_updates.refresh(self.desk, run["run_id"], ACTOR, self.clock)
        return run

    def report(self, run: dict) -> dict:
        return news_update_report.report(self.desk, run["run_id"], self.clock())

    def story_now(self, story_id: str) -> dict:
        return news_views.world(self.desk, self.clock())["stories"][story_id]


def row_of(report: dict, title: str) -> dict:
    return next(row for row in report["stories"] if row["title"] == title)


class PlanTest(unittest.TestCase):
    def test_the_plan_names_each_source_its_limits_and_the_reference_and_changes_nothing(self):
        world = UpdateWorld(self)
        before, requests = every_file(world.root), len(world.network.requests)
        plan = news_updates.plan(world.desk, T2, official=False)
        self.assertEqual(every_file(world.root), before)
        self.assertEqual(len(world.network.requests), requests)
        self.assertEqual({row["source"] for row in plan["sources"]}, set(SYNTHETIC))
        self.assertEqual(plan["requests"], {"feeds": 4, "skipped": 0})
        self.assertEqual(plan["reference"]["basis"], "baseline")
        self.assertEqual(plan["reference"]["id"], world.baseline["baseline_id"])
        self.assertTrue(plan["paid"]["enabled"])  # A simulated sender: enabled, and still nothing is sent.
        self.assertGreater(plan["paid"]["briefs"]["output_at_max_usd"], plan["paid"]["relevance"]["output_at_max_usd"])
        self.assertIn("not a billing ceiling", plan["paid"]["statement"])
        soon = news_updates.plan(world.desk, START + timedelta(minutes=10), official=False)  # Requested at START.
        self.assertEqual({row["action"] for row in soon["sources"]}, {"cooldown"})


class RunTest(unittest.TestCase):
    def test_a_run_records_its_cutoff_reference_and_what_was_held_once(self):
        world = UpdateWorld(self)
        run = world.start()
        self.assertEqual(run["started_at"], T2.isoformat())
        self.assertEqual(run["reference"]["at"], world.baseline["cutoff"])
        self.assertIn(world.ids[TARIFF], run["stories_before"])
        self.assertNotEqual(run["baseline_id"], world.baseline["baseline_id"])  # Its own baseline, apart.
        again, created = news_updates.start(world.desk, T2 + timedelta(minutes=5), ACTOR, {
            "label": "SYNTHETIC update", "idempotency_key": "update-key-0001", "official": False})
        self.assertFalse(created)
        self.assertEqual(again["run_id"], run["run_id"])
        with self.assertRaises(AccountsRefused) as refused:  # Another run while this one has not refreshed.
            world.start("update-key-0002")
        self.assertEqual(refused.exception.code, "update_open")

    def test_a_run_refreshes_once_requesting_each_source_once_and_groups_what_arrived(self):
        world = UpdateWorld(self)
        run = world.start()
        requests = len(world.network.requests)
        done = news_updates.refresh(world.desk, run["run_id"], ACTOR, world.clock)
        self.assertEqual(sorted(world.network.requests[requests:]),
                         sorted(publisher.feed.feed_url for publisher in SYNTHETIC.values()))
        self.assertEqual(done["requests"], 4)
        self.assertEqual(done["grouping"]["new_stories"], 4)  # Extension, rates, shipyard, mine.
        self.assertEqual(done["grouping"]["joined"], 1)  # The tariff copy joins the tariff story.
        with self.assertRaises(AccountsRefused) as refused:
            news_updates.refresh(world.desk, run["run_id"], ACTOR, world.clock)
        self.assertEqual(refused.exception.code, "already_refreshed")
        self.assertEqual(len(world.network.requests), requests + 4)  # The refused second refresh requested nothing.
        second = world.start("update-key-0002", at=T2 + timedelta(minutes=10))
        self.assertEqual(second["reference"], {"at": run["started_at"], "basis": "run", "id": run["run_id"],
                                               "statement": f"The previous update run's cutoff ({run['run_id']})."})
        with self.assertRaises(AccountsRefused) as refused:  # Only the latest run refreshes.
            news_updates.refresh(world.desk, run["run_id"], ACTOR, world.clock)
        self.assertEqual(refused.exception.code, "not_latest_run")
        cooled = news_updates.refresh(world.desk, second["run_id"], ACTOR, world.clock)
        self.assertEqual(cooled["requests"], 0)  # Each source was requested minutes ago.
        self.assertEqual({row["outcome"] for row in cooled["sources"]}, {"cooldown"})

    def test_arrivals_keep_new_late_and_unknown_publication_times_apart(self):
        world = UpdateWorld(self)
        report = world.report(world.refreshed())
        classes = {row["title"]: row["class"] for row in report["arrivals"]}
        self.assertEqual(classes, {TARIFF: "published_since", RATES: "published_since", EXTENSION: "published_since",
                                   SHIPYARD: "published_before", MINE: "time_unknown"})
        self.assertEqual(report["counts"]["run"]["by_class"],
                         {"published_since": 3, "published_before": 1, "time_unknown": 1})
        kinds = {row["title"]: row["kind"] for row in report["stories"]}
        self.assertEqual(kinds, {TARIFF: "additional_reporting", RATES: "new_development",
                                 EXTENSION: "new_development", SHIPYARD: "discovered_late", MINE: "time_unknown",
                                 UNRELATED: "revised"})
        mine = row_of(report, MINE)
        self.assertEqual(mine["first_basis"], "first_seen")  # Its retrieval time is never called a publication time.
        self.assertFalse(mine["newly_published"])
        shipyard = news_views.world(world.desk, T2)["stories"][row_of(report, SHIPYARD)["story_id"]]
        self.assertEqual(shipyard["first_at"], (START - timedelta(hours=30)).isoformat())  # Not its retrieval time.
        self.assertNotIn("new_development", {row["signal"] for row in shipyard["rank"]["signals"]})
        rates = news_views.world(world.desk, T2)["stories"][row_of(report, RATES)["story_id"]]
        self.assertEqual(rates["first_basis"], "published")
        self.assertTrue(row_of(report, TARIFF)["newly_published"])
        self.assertEqual(report["counts"]["before"]["listed"], len(news_baseline.load(
            world.desk, report["baseline_id"])["stories"]))

    def test_a_follow_up_to_an_ongoing_topic_is_suggested_and_related_without_relabelling_the_topic(self):
        world = UpdateWorld(self)
        run = world.refreshed()
        report = world.report(run)
        extension = row_of(report, EXTENSION)["story_id"]
        suggestion = next(row for row in report["follow_ups"]["topics"] if row["story_id"] == extension)
        self.assertEqual(suggestion["topic_id"], world.ids["topic_id"])
        self.assertTrue(suggestion["later_than_topic"])
        self.assertIn("15%", suggestion["evidence"]["figures"])
        self.assertTrue(suggestion["evidence"]["names"])
        news_matching.decide(world.desk, extension, suggestion["with_story"], {
            "decision": "related", "reason": "SYNTHETIC: the tariff extended", "topic_id": world.ids["topic_id"],
            "topic_title": None, "idempotency_key": "match-key-0001"}, "editor", {"editor": True}, ACTOR, T2)
        found = news_views.world(world.desk, T2)
        topic = found["topics"][world.ids["topic_id"]]
        self.assertEqual(topic["timeline"][-1], extension)  # The newest development, in order.
        self.assertEqual(topic["labels"][world.ids[TARIFF]], "Tariff announced")  # Its label kept.
        self.assertEqual(row_of(world.report(run), EXTENSION)["kind"], "topic_development")


class PreparationTest(unittest.TestCase):
    def test_the_model_path_runs_end_to_end_only_through_explicit_approvals_and_publication(self):
        world = UpdateWorld(self)
        world.model.verdicts = {MINE: "outside_scope", UNRELATED: "outside_scope"}
        run = world.refreshed()
        assessed = news_updates.relevance(world.desk, run["run_id"], "model", 40, ACTOR, world.clock())
        self.assertEqual(sorted(assessed["step"]["stories"]), sorted(
            row["story_id"] for row in world.report(run)["stories"]))  # Every run story: new, changed or revised.
        self.assertEqual(world.model.requests, [])  # A preview sends nothing.
        report = world.report(run)
        self.assertEqual(report["paid"]["not_attempted"], 6)
        self.assertGreater(report["paid"]["not_attempted_estimate_usd"], 0)
        self.assertTrue(any("awaits a paid approval" in row for row in report["attention"]))
        self.assertEqual(report["next"][0]["step"], "approval")
        batch = assessed["batch"]
        relevance_batches.approve(world.desk, batch["batch_id"], {
            "batch_id": batch["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": batch["estimated_max_usd_total"]}, world.story_now, ACTOR, world.clock)
        self.assertEqual(len(world.model.requests), 6)
        relevance_batches.approve(world.desk, batch["batch_id"], {  # Approving again sends nothing again.
            "batch_id": batch["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": batch["estimated_max_usd_total"]}, world.story_now, ACTOR, world.clock)
        self.assertEqual(len(world.model.requests), 6)
        report = world.report(run)
        self.assertEqual(row_of(report, MINE)["relevance"]["state"], "outside_scope")
        self.assertEqual(row_of(report, MINE)["tone"], "done")
        self.assertEqual({row["title"] for row in report["stories"] if row["step"] == "briefs"},
                         {TARIFF, RATES, EXTENSION, SHIPYARD})
        extension = row_of(report, EXTENSION)["story_id"]
        news_matching.decide(world.desk, extension, world.ids[TARIFF], {
            "decision": "related", "reason": "SYNTHETIC: the tariff extended", "topic_id": world.ids["topic_id"],
            "topic_title": None, "idempotency_key": "match-key-0001"}, "editor", {"editor": True}, ACTOR, T2)
        built = news_updates.context(world.desk, run["run_id"], ACTOR, world.clock())
        self.assertEqual({row["story_id"] for row in built["built"]}, {extension})  # The topic's earlier developments.
        self.assertEqual(built["built"][0]["options"], ["--topic-history"])
        self.assertEqual(set(built["without_options"]), {world.ids[TARIFF], row_of(report, RATES)["story_id"],
                                                         row_of(report, SHIPYARD)["story_id"]})
        prepared = news_updates.briefs(world.desk, run["run_id"], "model", 25, ACTOR, world.clock())
        self.assertEqual(len(prepared["batch"]["items"]), 4)
        self.assertEqual({item["draft"]["stage"] for item in prepared["batch"]["items"]}, {1})
        self.assertGreater(prepared["batch"]["followup_estimated_max_usd_total"], 0)  # Planned, not approved.
        self.assertEqual(len(world.model.requests), 6)
        approve_batch(world.desk, prepared["batch"], world.story_now, ACTOR, world.clock)
        self.assertEqual(len(world.model.requests), 10)  # Stage 1 of each story, once; stage 2 is only prepared.
        report = world.report(run)
        self.assertEqual({row["title"] for row in report["stories"] if row["step"] == "briefs"},
                         {TARIFF, RATES, EXTENSION, SHIPYARD})  # No version yet: the next stage awaits.
        self.assertEqual(report["counts"]["run"]["published_in_run"], 0)
        explained = news_updates.briefs(world.desk, run["run_id"], "model", 25, ACTOR, world.clock())
        self.assertNotEqual(explained["batch"]["batch_id"], prepared["batch"]["batch_id"])
        self.assertEqual({item["draft"]["stage"] for item in explained["batch"]["items"]}, {2})
        self.assertEqual(world.report(run)["next"][-1]["step"], "approval")
        self.assertEqual(len(world.model.requests), 10)  # Previewing the second stage sends nothing.
        approve_batch(world.desk, explained["batch"], world.story_now, ACTOR, world.clock)
        self.assertEqual(len(world.model.requests), 14)
        self.assertEqual(world.model.stages(), [1] * 4 + [2] * 4)
        report = world.report(run)
        self.assertEqual({row["title"] for row in report["stories"] if row["step"] == "publication"},
                         {TARIFF, RATES, EXTENSION, SHIPYARD})
        self.assertEqual(report["counts"]["run"]["published_in_run"], 0)  # Nothing is published by itself.
        self.assertEqual(report["next"][-1]["step"], "publication")
        done = news_batches.publish(world.desk, prepared["batch"]["batch_id"], {
            "reason": "SYNTHETIC: checked the run", "reviewed": False}, ACTOR, world.clock)
        self.assertEqual({row["outcome"] for row in done["items"]}, {"published"})
        again = news_batches.publish(world.desk, prepared["batch"]["batch_id"], {
            "reason": "SYNTHETIC: again", "reviewed": False}, ACTOR, world.clock)
        self.assertEqual({row["outcome"] for row in again["items"]}, {"already_published"})
        report = world.report(run)
        self.assertEqual(report["counts"]["run"]["published_in_run"], 4)
        self.assertEqual(report["paid"]["attempted"], {"recorded": 10, "validated": 4})
        self.assertEqual(report["failed"], [])
        self.assertEqual([row for row in report["stories"] if row["tone"] in ("todo", "attention")], [])

    def test_a_failed_paid_attempt_is_reported_as_a_failure_and_never_selected_again(self):
        world = UpdateWorld(self)
        run = world.refreshed()
        assessed = news_updates.relevance(world.desk, run["run_id"], "model", 40, ACTOR, world.clock())
        world.model.status = 529  # The provider answers with an error.
        batch = assessed["batch"]
        relevance_batches.approve(world.desk, batch["batch_id"], {
            "batch_id": batch["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": batch["estimated_max_usd_total"]}, world.story_now, ACTOR, world.clock)
        report = world.report(run)
        failed = [row for row in report["stories"] if row["tone"] == "failed"]
        self.assertEqual(len(failed), 6)
        states = {row["title"]: row["relevance"]["state"] for row in failed}
        self.assertEqual(states, {RATES: "unavailable", EXTENSION: "unavailable", SHIPYARD: "unavailable",
                                  MINE: "unavailable", TARIFF: "relevant", UNRELATED: "outside_scope"})
        # A failure never becomes a judgement: new stories are unavailable, and a story assessed before keeps its
        # earlier material's judgement, with the failure of its current material reported beside it.
        self.assertTrue(all("failed" in row["next"] for row in failed))
        self.assertEqual(len([row for row in report["failed"] if row.startswith("Paid request")]), 6)
        sent = len(world.model.requests)
        with self.assertRaises(AccountsRefused) as refused:
            news_updates.relevance(world.desk, run["run_id"], "model", 40, ACTOR, world.clock())
        self.assertEqual(refused.exception.code, "nothing_to_prepare")
        self.assertEqual(len(world.model.requests), sent)

    def test_a_source_that_fails_is_reported_and_the_others_still_arrive(self):
        world = UpdateWorld(self)
        world.network.answers[GAZETTE.feed_url] = (500, b"")
        report = world.report(world.refreshed())
        self.assertEqual(report["refresh"]["requests"], 4)
        self.assertEqual({row["source"]: row["outcome"] for row in report["refresh"]["sources"]}["synthetic-gazette"],
                         "failed")
        self.assertTrue(any(row.startswith("Synthetic Gazette (synthetic-gazette)") for row in report["failed"]))
        self.assertEqual({row["title"] for row in report["arrivals"]}, {TARIFF, RATES, EXTENSION})

    def test_a_brief_batch_saved_under_an_earlier_prompt_is_reported_as_unsendable_and_sends_nothing(self):
        from unittest import mock
        from second_order import brief_stages
        world = UpdateWorld(self)
        run = world.refreshed()
        news_updates.relevance(world.desk, run["run_id"], "assisted", 40, ACTOR, world.clock())
        from news_desk_fakes import assess
        assess(world.desk, world.clock(), {MINE: "outside_scope", UNRELATED: "outside_scope"}, ACTOR,
               synthetic_only=True)
        prepared = news_updates.briefs(world.desk, run["run_id"], "model", 25, ACTOR, world.clock())
        batch_id = prepared["batch"]["batch_id"]
        self.assertEqual(world.report(run)["paid"]["sendable"], 4)
        later_contract = {1: "brief-evidence-99", 2: "brief-explanation-99"}
        with mock.patch.object(brief_stages, "STAGE_VERSIONS", later_contract):  # A later request contract.
            report = world.report(run)
            rows = [row for row in report["paid"]["requests"] if row["batch_id"] == batch_id]
            self.assertEqual(len(rows), 4)
            self.assertTrue(all("an earlier request contract" in row["skipped"] for row in rows))
            self.assertEqual(report["paid"]["sendable"], 0)
            self.assertFalse(any(row["step"] == "approval" for row in report["next"]))
            self.assertEqual({row["title"] for row in report["stories"] if row["step"] == "briefs"},
                             {TARIFF, RATES, EXTENSION, SHIPYARD})  # Prepared again, not awaiting the old batch.
            note = next(line for line in report["attention"] if batch_id in line)
            self.assertIn("would send none", note)
            done = news_batches.approve(world.desk, batch_id, {
                "batch_id": batch_id, "approve_paid_requests": True,
                "estimated_max_usd_total": prepared["batch"]["estimated_max_usd_total"]}, world.story_now, ACTOR,
                world.clock)
        self.assertEqual({row["outcome"] for row in done["items"]}, {"request_superseded"})
        self.assertEqual(world.model.requests, [])

    def test_changed_material_skips_a_saved_request_and_the_next_run_prepares_the_story_again(self):
        world = UpdateWorld(self)
        run = world.refreshed()
        news_updates.relevance(world.desk, run["run_id"], "assisted", 40, ACTOR, world.clock())
        from news_desk_fakes import assess
        assess(world.desk, world.clock(), {MINE: "outside_scope", UNRELATED: "outside_scope"}, ACTOR,
               synthetic_only=True)
        prepared = news_updates.briefs(world.desk, run["run_id"], "model", 25, ACTOR, world.clock())
        tariff = world.ids[TARIFF]
        world.network.answers.update(later() | {GAZETTE.feed_url: trade_feeds(START, gazette_extra=[
            item(GAZETTE.link_host, "tariff-gazette", TARIFF, START + timedelta(hours=3.5), "SYNTHETIC: the tariff "
                 "was confirmed again.")])[GAZETTE.feed_url]})
        second = world.start("update-key-0002", at=T2 + timedelta(hours=1))
        news_updates.refresh(world.desk, second["run_id"], ACTOR, lambda: T2 + timedelta(hours=1, minutes=1))
        sent = len(world.model.requests)
        done = news_batches.approve(world.desk, prepared["batch"]["batch_id"], {
            "batch_id": prepared["batch"]["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": prepared["batch"]["estimated_max_usd_total"]}, world.story_now, ACTOR,
            world.clock)
        outcome = {row["story_id"]: row["outcome"] for row in done["items"]}
        self.assertEqual(outcome[tariff], "story_changed")  # Its material changed since the preview: not sent.
        self.assertEqual(len(world.model.requests), sent + len(prepared["batch"]["items"]) - 1)
        later_report = world.report(second)
        self.assertEqual(row_of(later_report, TARIFF)["kind"], "additional_reporting")
        self.assertEqual(row_of(later_report, TARIFF)["step"], "relevance")  # Its material changed: assess again.


class ReadsAndTimesTest(unittest.TestCase):
    def test_reading_a_run_and_the_news_requests_sends_and_writes_nothing(self):
        world = UpdateWorld(self)
        run = world.refreshed()
        news_updates.relevance(world.desk, run["run_id"], "model", 40, ACTOR, world.clock())
        before, requests = every_file(world.root), len(world.network.requests)
        news_update_report.report(world.desk, run["run_id"], T2 + timedelta(hours=2))
        news_updates.plan(world.desk, T2 + timedelta(hours=2), official=False)
        news_updates.listing(world.desk)
        news_updates.texts(world.desk, run["run_id"], ACTOR, world.clock, check=True)
        for view in news_views.VIEWS:
            news_views.stories_view(world.desk, view, [], T2 + timedelta(hours=2))
        news_views.story_view(world.desk, world.ids[TARIFF], T2 + timedelta(hours=2))
        news_views.topic_view(world.desk, world.ids["topic_id"], T2 + timedelta(hours=2))
        self.assertEqual(every_file(world.root), before)
        self.assertEqual(len(world.network.requests), requests)
        self.assertEqual(world.model.requests, [])

    def test_publication_does_not_make_a_story_newer_and_readers_see_what_changed(self):
        world = UpdateWorld(self)
        run = world.refreshed()
        from news_desk_fakes import assess
        assess(world.desk, world.clock(), {MINE: "outside_scope", UNRELATED: "outside_scope"}, ACTOR,
               synthetic_only=True)
        prepared = news_updates.briefs(world.desk, run["run_id"], "model", 25, ACTOR, world.clock())
        both_stages(world.desk, prepared["batch"], world.clock(), world.story_now, ACTOR, world.clock)
        before = news_views.world(world.desk, T2 + timedelta(hours=2))["stories"][world.ids[TARIFF]]
        publish_at = T2 + timedelta(hours=5)
        news_batches.publish(world.desk, prepared["batch"]["batch_id"], {"reason": "SYNTHETIC", "reviewed": False},
                             ACTOR, lambda: publish_at)
        found = news_views.world(world.desk, T2 + timedelta(hours=6))
        tariff = found["stories"][world.ids[TARIFF]]
        self.assertEqual(tariff["latest_at"], before["latest_at"])  # The newest report's time, not the publication's.
        self.assertEqual(tariff["latest_at"], (START + timedelta(hours=2)).isoformat())
        latest = [story["story_id"] for story in news_rank.latest(list(found["stories"].values()))]
        self.assertLess(latest.index(row_of(world.report(run), RATES)["story_id"]), latest.index(tariff["story_id"]))
        page = news_views.story_view(world.desk, world.ids[TARIFF], T2 + timedelta(hours=6))
        brief = page["brief"]
        self.assertEqual(brief["version"], 2)
        self.assertEqual(brief["published_at"], publish_at.isoformat())
        self.assertGreater(brief["published_at"], brief["prepared_at"])
        history = brief["revisions"]
        self.assertEqual([row["version"] for row in history["earlier"]], [1])
        self.assertEqual(history["earlier"][0]["authorship"], "editor")
        self.assertTrue(history["earlier"][0]["explained"])
        self.assertEqual(history["updated_at"], publish_at.isoformat())
        self.assertIn(f"Adds the report “{TARIFF}” (Synthetic Courier).", history["changes"])
        self.assertIn("Says its evidence is insufficient for an economic explanation.", history["changes"])
        self.assertIn("This version was drafted by an AI model in this application; the earlier one was written by "
                      "an editor.", history["changes"])
        self.assertEqual(history["earlier"][0]["recorded_as"], None)
        first = news_views.story_view(world.desk, row_of(world.report(run), RATES)["story_id"], T2 + timedelta(hours=6))
        self.assertEqual(first["brief"]["revisions"], {"earlier": [], "changes": [], "updated_at": None})


class RoutesTest(unittest.TestCase):
    def test_the_desk_plans_starts_refreshes_and_reports_a_run_only_by_explicit_actions(self):
        world = DeskWorld(self)
        world.world.clock.advance(hours=3)
        world.network.answers.update(later())
        admin = world.client("admin")
        before, requests = every_file(world.world.root), len(world.network.requests)
        read = admin.get("/api/admin/news/updates")
        self.assertEqual(read.status_code, 200, read.text)
        self.assertEqual(read.json()["runs"], [])
        self.assertEqual(read.json()["plan"]["update_version"], news_updates.UPDATE_VERSION)
        self.assertEqual(every_file(world.world.root), before)  # Reading the plan writes and requests nothing.
        self.assertEqual(len(world.network.requests), requests)
        self.assertEqual(world.client("reader-a").get("/api/admin/news/updates").status_code, 403)
        started = admin.post("/api/admin/news/updates", headers=ADMIN_WRITE, json={
            "label": "SYNTHETIC run", "official": False, "idempotency_key": "run-key-0001"})
        self.assertEqual(started.status_code, 201, started.text)
        run = started.json()["run"]
        self.assertNotIn("reports_before", run)
        path = f"/api/admin/news/updates/{run['run_id']}"
        refreshed = admin.post(f"{path}/refresh", headers=ADMIN_WRITE, json={})
        self.assertEqual(refreshed.status_code, 200, refreshed.text)
        expected = len([row for row in news_registry.connected() if not row.feed.contact_required]) + 4
        self.assertEqual(refreshed.json()["refresh"]["requests"], expected)  # Each feed once; no official feed.
        self.assertEqual(len(world.network.requests), requests + expected)
        refreshes = lambda: usage.overview(world.world.accounts, world.world.root / "intake",  # noqa: E731
                                           world.world.clock())["server"]["refreshes"]["used"]
        self.assertEqual(refreshes(), 1)
        again = admin.post(f"{path}/refresh", headers=ADMIN_WRITE, json={})
        self.assertEqual((again.status_code, again.json()["code"]), (409, "already_refreshed"))
        self.assertEqual(refreshes(), 1)  # The refused refresh is not counted.
        self.assertEqual(len(world.network.requests), requests + expected)
        report = admin.get(path).json()["report"]
        self.assertEqual(report["refresh_state"], "done")
        self.assertTrue(any(row.startswith("TechCrunch") for row in report["failed"]))  # Only SYNTHETIC answers.
        self.assertEqual(report["counts"]["run"]["by_class"], {"published_since": 3, "published_before": 1,
                                                               "time_unknown": 1})
        assessed = admin.post(f"{path}/relevance", headers=ADMIN_WRITE, json={"method": "assisted", "limit": 40})
        self.assertEqual(assessed.status_code, 201, assessed.text)
        report = admin.get(path).json()["report"]
        self.assertTrue(any(row["step"] == "import" for row in report["next"]))
        refused = admin.post(f"{path}/briefs", headers=ADMIN_WRITE, json={"method": "model", "limit": 25})
        self.assertEqual((refused.status_code, refused.json()["code"]), (409, "nothing_to_prepare"))


class CorrectedAuthorshipTest(unittest.TestCase):
    def test_an_earlier_version_shows_who_really_prepared_it_once_corrected(self):
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        done, _ = story_briefs.correct_authorship(world.desk.newsroom, tariff, {
            "version": 1, "method": "assisted", "reason": "SYNTHETIC: written with an assistant, recorded as an editor's",
            "idempotency_key": "correct-key-0001"}, story_briefs.assistant_preparation("SYNTHETIC assistant", None,
                                                                                      ACTOR), ACTOR, T1)
        story_briefs.publish(world.desk.newsroom, tariff, {"version": done["version"], "reason": "SYNTHETIC",
                                                           "idempotency_key": "publish-key-0001"}, ACTOR, T1)
        brief = news_views.story_view(world.desk, tariff, T1)["brief"]
        self.assertEqual(brief["version"], 2)
        earlier = brief["revisions"]["earlier"][0]
        self.assertEqual((earlier["version"], earlier["method"], earlier["authorship"], earlier["recorded_as"]),
                         (1, "assisted", "ai_assistant", "editorial"))  # Never shown as an editor's any more.
        self.assertEqual(brief["revisions"]["changes"], [
            "Corrects who prepared version 1: it was written with an AI assistant, not written by an editor as first "
            "recorded. The content is unchanged."])


class DraftingCommandTest(unittest.TestCase):
    """``news drafting preview|approve``: one story's model draft, outside any batch, under the per-request approval."""

    def run_cli(self, desk, **fields):
        from argparse import Namespace
        from second_order import news_cli
        return news_cli.run(Namespace(news_action="drafting", **fields), desk)

    def test_each_stage_is_previewed_without_sending_and_sent_once_only_on_its_exact_approval(self):
        from dataclasses import replace
        from unittest import mock
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        preview = self.run_cli(world.desk, drafting_action="preview", story_id=tariff)
        again = self.run_cli(world.desk, drafting_action="preview", story_id=tariff)
        self.assertEqual(again["draft_id"], preview["draft_id"])  # The same material is the same request.
        self.assertEqual(world.model.requests, [])
        estimate = preview["estimate"]["estimated_real_run_if_output_reaches_max_usd"]
        folder = world.desk.newsroom.path.parent / "drafting" / preview["draft_id"]
        with self.assertRaises(SystemExit) as refused:  # A wrong fingerprint: refused before anything is reserved.
            self.run_cli(world.desk, drafting_action="approve", draft_id=preview["draft_id"], request_sha256="0" * 64,
                         estimated_max_usd=estimate, approve_paid_request=True)
        self.assertIn("approval_mismatch", str(refused.exception))
        with mock.patch.dict("os.environ", {}, clear=True), self.assertRaises(SystemExit) as unkeyed:
            self.run_cli(replace(world.desk, drafting=None), drafting_action="approve", draft_id=preview["draft_id"],
                         request_sha256=preview["request_sha256"], estimated_max_usd=estimate,
                         approve_paid_request=True)
        self.assertIn("is not set; nothing was sent", str(unkeyed.exception))
        self.assertEqual(world.model.requests, [])
        self.assertFalse((folder / "attempt.json").exists())
        sent = self.run_cli(world.desk, drafting_action="approve", draft_id=preview["draft_id"],
                            request_sha256=preview["request_sha256"], estimated_max_usd=estimate,
                            approve_paid_request=True)
        self.assertTrue(sent["sent"])
        self.assertEqual(world.model.requests, [(folder / "request.json").read_bytes()])  # The saved bytes, once.
        repeat = self.run_cli(world.desk, drafting_action="approve", draft_id=preview["draft_id"],
                              request_sha256=preview["request_sha256"], estimated_max_usd=estimate,
                              approve_paid_request=True)
        self.assertFalse(repeat["sent"])
        self.assertEqual(len(world.model.requests), 1)
        self.assertEqual(sent["next"]["stage"], 2)  # Stage 2 was prepared from stage 1's checked reply, not sent.
        second = self.run_cli(world.desk, drafting_action="preview", story_id=tariff)
        self.assertEqual((second["state"], second["draft_id"]), ("awaiting_stage_2", sent["next"]["draft_id"]))
        self.assertEqual(len(world.model.requests), 1)
        self.assertTrue(self.approve_cli(world, second)["sent"])
        self.assertFalse(self.approve_cli(world, second)["sent"])
        self.assertEqual(world.model.stages(), [1, 2])
        story = news_views.world(world.desk, T2)["stories"][tariff]
        self.assertEqual(story["brief"]["version"], 1)  # A model draft is saved unpublished; readers see version 1.
        saved = news_views.world(world.desk, T2)["folded"]["briefs"][tariff][-1]
        self.assertEqual((saved["version"], saved["method"]), (2, "model"))

    def test_a_rejected_draft_keeps_bounded_diagnostics_and_is_never_sent_again(self):
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        preview = self.run_cli(world.desk, drafting_action="preview", story_id=tariff)
        folder = world.desk.newsroom.path.parent / "drafting" / preview["draft_id"]
        world.model.status = 400  # A SYNTHETIC rejection; not the trial's error, which was not kept.
        world.model.error_body = json.dumps({"type": "error", "error": {
            "type": "invalid_request_error", "message": "SYNTHETIC: output_config.format is not accepted."}}).encode()
        world.model.headers = {"request-id": "req_SYNTHETIC0000000000000002", "x-synthetic-header": "not-kept"}
        approval = dict(drafting_action="approve", draft_id=preview["draft_id"], request_sha256=preview["request_sha256"],
                        estimated_max_usd=preview["estimate"]["estimated_real_run_if_output_reaches_max_usd"],
                        approve_paid_request=True)
        sent = self.run_cli(world.desk, **approval)
        attempt = sent["attempt"]
        self.assertEqual((attempt["state"], attempt["detail"]), (
            "provider_error", "The model provider returned HTTP 400 (invalid_request_error); no draft was produced"))
        self.assertEqual(attempt["request_id"], "req_SYNTHETIC0000000000000002")
        self.assertEqual(attempt["provider_error"]["message"], "SYNTHETIC: output_config.format is not accepted.")
        outcome = json.loads((folder / "outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(outcome["exchange"]["request_sha256"], preview["request_sha256"])
        self.assertEqual(outcome["exchange"]["sent_at"],
                         json.loads((folder / "sent.json").read_text(encoding="utf-8"))["started_at"])
        self.assertLessEqual(outcome["exchange"]["sent_at"], outcome["exchange"]["answered_at"])
        self.assertEqual(outcome["exchange"]["http_status"], 400)
        for content in every_file(folder).values():
            self.assertNotIn(FAKE_KEY.encode(), content)
            self.assertNotIn(b"not-kept", content)  # No other response header is kept.
        self.assertFalse(self.run_cli(world.desk, **approval)["sent"])
        self.assertEqual(len(world.model.requests), 1)  # One attempt; never retried.
        self.assertEqual(news_views.world(world.desk, T2)["stories"][tariff]["brief"]["version"], 1)

    def approve_cli(self, world, preview):
        return self.run_cli(world.desk, drafting_action="approve", draft_id=preview["draft_id"],
                            request_sha256=preview["request_sha256"], approve_paid_request=True,
                            estimated_max_usd=preview["estimate"]["estimated_real_run_if_output_reaches_max_usd"])

    def test_current_brief_prompt_counts_the_format_prompt_and_supersedes_an_earlier_request_unsent(self):
        from second_order import brief_drafting, brief_stages
        world = UpdateWorld(self)
        preview = self.run_cli(world.desk, drafting_action="preview", story_id=world.ids[TARIFF])
        folder = world.desk.newsroom.path.parent / "drafting" / preview["draft_id"]
        body = (folder / "request.json").read_bytes()
        self.assertEqual(json.loads(body)["output_config"]["format"]["schema"], brief_stages.output_format(1))
        self.assertEqual(preview["estimate"]["input_tokens_assumed"], len(body) // 2 + 1_000 + 1_000)
        self.assertIn("JSON output format", " ".join(preview["estimate"]["assumptions"]))
        record = json.loads((folder / "preview.json").read_text(encoding="utf-8"))
        self.assertEqual((record["prompt_version"], record["stage"], record["stage_version"]),
                         (brief_drafting.PROMPT_VERSION, 1, brief_stages.STAGE_VERSIONS[1]))
        (folder / "preview.json").chmod(0o644)  # Saved records are read-only; this test rewrites one.
        (folder / "preview.json").write_text(json.dumps({**record, "prompt_version": "brief-prompt-8", "stage": None,
                                                         "stage_version": None}),
                                             encoding="utf-8")  # As a single request saved before the stages.
        with self.assertRaises(SystemExit) as refused:
            self.approve_cli(world, preview)
        self.assertIn("request_superseded", str(refused.exception))
        self.assertIn(f"brief-prompt-8, an earlier request contract than {brief_drafting.PROMPT_VERSION}",
                      str(refused.exception))
        self.assertEqual(world.model.requests, [])
        self.assertFalse((folder / "attempt.json").exists())

    def test_an_insufficient_reply_in_the_new_shape_records_the_judgement_and_no_version(self):
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        world.model.brief_reply = lambda reply: {
            **{key: "" for key in ("headline", "summary")}, **{key: [] for key in (
                "facts", "implications", "themes", "uncertainties", "missing")},
            "insufficient_material": "SYNTHETIC: the headline alone says too little.",
            "economics": reply["economics"]}  # The fake checks that this reply fits the request's format.
        attempt = self.approve_cli(world, self.run_cli(world.desk, drafting_action="preview",
                                                       story_id=tariff))["attempt"]
        self.assertEqual(attempt["state"], "insufficient")
        self.assertEqual(attempt["version"], None)
        self.assertEqual(news_views.world(world.desk, T2)["folded"]["briefs"][tariff][-1]["version"], 1)

    def test_an_empty_headline_without_a_judgement_is_refused_not_filled(self):
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        world.model.brief_reply = lambda reply: {**reply, "headline": ""}
        first = self.approve_cli(world, self.run_cli(world.desk, drafting_action="preview", story_id=tariff))
        self.assertEqual(first["attempt"]["state"], "validated")  # The evidence stage holds no headline.
        attempt = self.approve_cli(world, self.run_cli(world.desk, drafting_action="preview",
                                                       story_id=tariff))["attempt"]
        self.assertEqual(attempt["state"], "invalid")
        self.assertIn("The headline is text of 1 to 160 characters", attempt["detail"])
        self.assertEqual(news_views.world(world.desk, T2)["folded"]["briefs"][tariff][-1]["version"], 1)

    def test_a_reply_carrying_the_key_keeps_no_diagnostics_and_an_old_outcome_still_reads(self):
        from second_order import brief_drafting
        world = UpdateWorld(self)
        tariff = world.ids[TARIFF]
        preview = self.run_cli(world.desk, drafting_action="preview", story_id=tariff)
        folder = world.desk.newsroom.path.parent / "drafting" / preview["draft_id"]
        world.model.status = 400
        world.model.error_body = json.dumps({"type": "error", "error": {
            "type": "invalid_request_error", "message": f"SYNTHETIC: header {FAKE_KEY}"}}).encode()
        attempt = self.run_cli(world.desk, drafting_action="approve", draft_id=preview["draft_id"],
                               request_sha256=preview["request_sha256"], approve_paid_request=True,
                               estimated_max_usd=preview["estimate"]["estimated_real_run_if_output_reaches_max_usd"]
                               )["attempt"]
        self.assertEqual(attempt["state"], "invalid")
        self.assertIsNone(attempt["provider_error"])
        for content in every_file(folder).values():
            self.assertNotIn(FAKE_KEY.encode(), content)
        # An outcome recorded before diagnostics existed (the shape of the T-MED trial's) reads without them.
        old = folder.parent / "brief-synthetic-old-outcome"
        old.mkdir()
        (old / "outcome.json").write_text(json.dumps({
            "outcome": "provider_error", "finished_at": "2026-10-27T00:53:46+00:00", "usage": None, "version": None,
            "detail": "The model provider returned HTTP 400 (invalid_request_error); no draft was produced"}),
            encoding="utf-8")
        state = brief_drafting.attempt_state(old)
        self.assertEqual((state["state"], state["request_id"], state["provider_error"]), ("provider_error", None, None))


if __name__ == "__main__":
    unittest.main()
