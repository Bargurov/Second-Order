"""Economic relevance (news-relevance-0.1) over SYNTHETIC feeds and a SYNTHETIC model (news_desk_fakes): the annotation's
schema and evidence check, the deterministic decisions and their paired cases, the feed and Go deeper, editors'
judgements, the paid and assisted batches (approval, single sending, interruption, failures, changed material) and
reads that contact nothing. Nothing reaches a network."""
from argparse import ArgumentParser, Namespace, _SubParsersAction
from contextlib import closing
from datetime import timedelta
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from account_fakes import ADMIN_WRITE, USER_WRITE, World
from news_desk_fakes import (RESPONSE, RESPONSE_OWN, REVISION, START, TARIFF, UNRELATED, BriefModel, Feeds, assess,
                             desk_in, item, publishers, rss, synthetic_annotation, trade_feeds)
from second_order import (news_batches, news_cli, news_desk, news_feeds, news_registry, news_relevance as nr,
                          news_reports, news_stories, news_views, relevance_batches as rb, relevance_requests as rr,
                          story_deeper)
from second_order import newsroom_store as ns
from second_order.accounts import AccountsRefused

KEY = "sk-ant-dummy-simulated-relevance-key-0001"
TECH = news_registry.TECHCRUNCH
ROUNDUP = "SYNTHETIC: These clever apps show off a foldable phone"


class Relevance:
    """The SYNTHETIC trade world plus one TechCrunch headline (its terms forbid use by a model), grouped, with the
    response merged; a SYNTHETIC model to send to."""

    def __init__(self, test: unittest.TestCase, model: bool = True):
        folder = tempfile.TemporaryDirectory()
        test.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        answers = trade_feeds(START)
        answers[TECH.feed_url] = (200, rss([item("techcrunch.com", "apps", ROUNDUP, START - timedelta(hours=6),
                                                 "SYNTHETIC: developers show retro players and flight trackers.")]))
        self.network = Feeds(answers)
        self.model = BriefModel(KEY)
        self.desk = desk_in(self.root, chosen=publishers(), network=self.network,
                            drafting=self.model.sender() if model else None)
        refreshed = [row for row in self.desk.publishers.values() if row.synthetic or row.key == "techcrunch"]
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher, refreshed, lambda: START)
        reports = news_reports.pool(self.desk.inbox, self.desk.feeds, self.desk.publishers)["reports"]
        news_stories.group(self.desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        news_stories.merge(self.desk.newsroom, self.story_id(RESPONSE_OWN), {
            "into": self.story_id(RESPONSE), "reason": "one response", "idempotency_key": "merge-key-0001"}, "setup",
            START)
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

    def view(self, name: str = "hot") -> dict:
        return news_views.stories_view(self.desk, name, [], START)

    def approve(self, batch: dict) -> dict:
        return rb.approve(self.desk, batch["batch_id"], {
            "batch_id": batch["batch_id"], "approve_paid_requests": True,
            "estimated_max_usd_total": batch["estimated_max_usd_total"]}, self.story_now, "admin-1", self.clock)


def sources_of(story: dict) -> dict:
    return rr.sources(story["material"]["reports"], {})


# ---------------------------------------------------------------- the annotation

class SchemaTest(unittest.TestCase):
    def test_an_annotation_follows_the_schema_and_its_limits(self):
        good = synthetic_annotation("r1", "a quoted phrase")
        self.assertEqual(nr.validated(good)["verdict"], "relevant")
        for broken, problem in (({**good, "event_type": None}, "event_type"),
                                ({**good, "report_kind": "ceremonial"}, "event_type"),
                                ({**good, "dimensions": good["dimensions"] * 2}, "at most once"),
                                ({**good, "explanation": "x" * 601}, "explanation"),
                                ({**good, "score": 0.97}, "score"),
                                ({**good, "verdict": "important"}, "verdict")):
            with self.assertRaises(nr.AnnotationRejected) as refused:
                nr.validated(broken)
            self.assertIn(problem, str(refused.exception))

    def test_the_structured_format_carries_no_limit_the_api_refuses_and_no_score(self):
        text = json.dumps(nr.response_schema())
        for keyword in ("maxLength", "minLength", "maxItems", "minItems", "minimum", "maximum"):
            self.assertNotIn(keyword, text)

        def objects(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    yield node
                for value in node.values():
                    yield from objects(value)
            elif isinstance(node, list):
                for value in node:
                    yield from objects(value)
        for node in objects(nr.response_schema()):
            self.assertIs(node["additionalProperties"], False)
            self.assertEqual(set(node["required"]), set(node["properties"]))
        self.assertNotIn("number", text)  # Nothing numeric for a model to rank by.


class EvidenceTest(unittest.TestCase):
    def test_quotes_are_found_in_the_named_reports_headline_excerpt_or_text(self):
        sources = {"r1": {"title": "Synthetic Republic’s 15% tariff on steel", "excerpt": "Duties  begin\nin May.",
                          "text": "SYNTHETIC: the ministry said “importers will pay more” from May."}}
        annotation = synthetic_annotation("r1", "Synthetic Republic's 15% TARIFF")
        annotation["scope"]["magnitudes"] = [{"text": "from May", "evidence": {"report": "r1",
                                                                               "quote": "duties begin in may"}}]
        annotation["dimensions"][0]["evidence"] = [{"report": "r1", "quote": 'said "importers will pay more"'}]
        checked = nr.check_evidence(annotation, sources)
        self.assertEqual(checked["not_found"], 0)
        self.assertEqual({row["field"] for row in checked["quotes"]}, {"title", "excerpt", "text"})
        self.assertEqual((checked["change_supported"], checked["supported_dimensions"], checked["supported_magnitudes"]),
                         (True, ["trade"], ["from May"]))

    def test_a_quote_not_found_or_naming_another_report_supports_nothing(self):
        sources = {"r1": {"title": "Synthetic steel tariff announced", "excerpt": None, "text": None}}
        annotation = synthetic_annotation("r1", "steel tariff announced")
        annotation["dimensions"][0]["evidence"] = [{"report": "r1", "quote": "prices will rise sharply"}]
        annotation["affected"][0]["evidence"] = [{"report": "r9", "quote": "steel tariff announced"}]
        annotation["change_evidence"].append({"report": "r1", "quote": "steel"})
        checked = nr.check_evidence(annotation, sources)
        problems = [row["problem"] for row in checked["quotes"] if not row["found"]]
        self.assertEqual(sorted(problems), ["names a report that is not in the material",
                                            "not found in that report's headline, excerpt or text",
                                            "shorter than 2 words"])
        self.assertEqual((checked["supported_dimensions"], checked["unsupported_dimensions"]), ([], ["trade"]))
        decision = nr.decide(annotation, checked)  # No economic angle the sources do not state.
        self.assertEqual(decision["state"], "needs_review")
        self.assertIn("No economic dimension is supported", decision["reasons"][0])


class DecisionTest(unittest.TestCase):
    """Paired cases: the decision follows what the annotation found the sources to report, not words or publishers."""

    def decide(self, annotation: dict, title: str = "SYNTHETIC headline of the report") -> dict:
        sources = {"r1": {"title": title, "excerpt": None, "text": None}}
        return nr.decide(annotation, nr.check_evidence(annotation, sources))

    def test_a_development_is_relevant_and_the_same_words_in_product_coverage_are_not(self):
        title = "SYNTHETIC phone maker cuts its app store commission to 15%"
        commission = synthetic_annotation("r1", "cuts its app store commission")
        self.assertEqual(self.decide(commission, title)["state"], "relevant")
        roundup = {**synthetic_annotation("r1", "app store", "outside_scope"), "report_kind": "product_coverage"}
        self.assertEqual(self.decide(roundup, "SYNTHETIC: the app store's best new apps")["state"], "outside_scope")
        claimed = {**commission, "report_kind": "product_coverage", "event_type": None}
        decision = self.decide(claimed, title)
        self.assertEqual(decision["state"], "needs_review")  # A relevant verdict for a product review: an editor decides.
        self.assertIn("product coverage, not a reported development", decision["reasons"][0])

    def test_outside_the_scope_is_kept_out_unless_the_sources_support_two_dimensions(self):
        ceremony = synthetic_annotation("r1", "SYNTHETIC headline", "outside_scope")
        self.assertEqual(self.decide(ceremony)["state"], "outside_scope")
        disputed = {**synthetic_annotation("r1", "SYNTHETIC headline"), "verdict": "outside_scope"}
        disputed["dimensions"] = [*disputed["dimensions"], {"dimension": "costs", "how": "SYNTHETIC",
                                                            "evidence": [{"report": "r1", "quote": "headline of"}]}]
        self.assertEqual(self.decide(disputed)["state"], "needs_review")
        thin = synthetic_annotation("r1", "SYNTHETIC headline", "insufficient_information")
        self.assertEqual(self.decide(thin)["state"], "insufficient")

    def test_importance_is_fixed_points_from_categories(self):
        annotation = synthetic_annotation("r1", "SYNTHETIC headline")
        annotation["scope"]["magnitudes"] = [{"text": "15%", "evidence": {"report": "r1", "quote": "headline of"}}]
        checked = nr.check_evidence(annotation, {"r1": {"title": "SYNTHETIC headline of the report"}})
        rated = nr.importance(annotation, checked)
        self.assertEqual((rated["points"], rated["level"]), (1.75, "high"))
        speech = {**annotation, "event_type": "official_statement", "scope": {"reach": "unclear", "magnitudes": []}}
        self.assertEqual(nr.importance(speech, nr.check_evidence(speech, {"r1": {"title": "x"}}))["points"], 0.25)


# ---------------------------------------------------------------- the feed

class FeedTest(unittest.TestCase):
    def test_only_established_relevance_is_listed_and_the_rest_waits_in_view(self):
        world = Relevance(self)
        before = world.view()
        self.assertEqual(before["stories"], [])  # Nothing unassessed is presented as economic news.
        waiting = {row["title"]: row["relevance"] for row in before["awaiting"]}
        self.assertEqual(waiting[ROUNDUP]["state"], "restricted")
        self.assertIn("terms do not allow", waiting[ROUNDUP]["statement"])
        self.assertEqual(waiting[TARIFF]["state"], "pending")
        assess(world.desk, START, {UNRELATED: "outside_scope"})
        hot, latest = world.view(), world.view("latest")
        titles = [row["title"] for row in hot["stories"]]
        self.assertIn(REVISION, titles)
        self.assertNotIn(UNRELATED, titles + [row["title"] for row in latest["stories"] + latest["awaiting"]])
        self.assertNotIn(ROUNDUP, titles)  # A technology publisher's headline is not economic news by its category.
        self.assertIn(ROUNDUP, [row["title"] for row in hot["awaiting"]])
        self.assertEqual(latest["left_out"]["outside_scope"], 1)
        museum = news_views.story_view(world.desk, world.story_id(UNRELATED), START)
        self.assertEqual(museum["relevance"]["state"], "outside_scope")  # Its address still works and says why.
        self.assertEqual(museum["relevance"]["basis_label"], nr.BASIS_LABEL["synthetic"])
        self.assertFalse(museum["deeper"]["available"])
        revision = news_views.story_view(world.desk, world.story_id(REVISION), START)
        self.assertEqual(revision["relevance"]["state"], "relevant")
        self.assertEqual([row["dimension"] for row in revision["relevance"]["dimensions"]], ["trade"])
        signals = [row["signal"] for row in world.story(REVISION)["rank"]["signals"]]
        self.assertIn("importance", signals)

    def test_an_editor_judges_a_restricted_story_with_a_reason_and_can_clear_it(self):
        world = Relevance(self)
        roundup = world.story(ROUNDUP)
        with self.assertRaises(AccountsRefused):  # A judgement needs a reason.
            nr.review(world.desk.newsroom, roundup["story_id"], {"verdict": "outside_scope", "reason": " ",
                                                                 "idempotency_key": "judge-key-01"},
                      roundup["material"]["material_sha256"], "admin-1", START)
        form = {"verdict": "outside_scope", "reason": "Consumer coverage: an app roundup, not a development.",
                "idempotency_key": "judge-key-02"}
        done, created = nr.review(world.desk.newsroom, roundup["story_id"], form,
                                  roundup["material"]["material_sha256"], "admin-1", START)
        again, repeated = nr.review(world.desk.newsroom, roundup["story_id"], form,
                                    roundup["material"]["material_sha256"], "admin-1", START)
        self.assertEqual((created, repeated, again), (True, False, done))
        page = news_views.story_view(world.desk, roundup["story_id"], START)
        self.assertEqual((page["relevance"]["state"], page["relevance"]["basis_label"]),
                         ("outside_scope", "Judged by an editor."))
        self.assertIn("app roundup", page["relevance"]["explanation"])
        self.assertNotIn(ROUNDUP, [row["title"] for row in world.view()["awaiting"]])
        nr.review(world.desk.newsroom, roundup["story_id"], {"verdict": "cleared", "reason": "Reopened.",
                                                             "idempotency_key": "judge-key-03"},
                  roundup["material"]["material_sha256"], "admin-1", START)
        self.assertEqual(world.story(ROUNDUP)["relevance"]["state"], "restricted")
        nr.review(world.desk.newsroom, roundup["story_id"], {"verdict": "relevant", "reason": "SYNTHETIC check.",
                                                             "idempotency_key": "judge-key-04"},
                  roundup["material"]["material_sha256"], "admin-1", START)
        card = next(row for row in world.view()["stories"] if row["title"] == ROUNDUP)
        self.assertEqual(card["brief"]["state"], "not_permitted")  # Listed as a headline only, never summarised.

    def test_reading_the_news_the_desk_and_the_queue_contacts_no_model_and_no_publisher(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "assisted", limit=3)
        before = (len(world.model.requests), len(world.network.requests))
        for name in ("hot", "latest", "interests"):
            world.view(name)
        for story_id in news_views.world(world.desk, START)["stories"]:
            news_views.story_view(world.desk, story_id, START)
        rb.queue(world.desk, START)
        rb.status(world.desk, batch["batch_id"], START)
        rb.packet(world.desk, batch["batch_id"], START)
        news_batches.coverage(world.desk, START)
        news_desk.desk_view(world.desk, START, {})
        self.assertEqual((len(world.model.requests), len(world.network.requests)), before)


# ---------------------------------------------------------------- the paid batch

class PaidBatchTest(unittest.TestCase):
    def test_a_preview_selects_current_unassessed_stories_and_saves_each_exact_request(self):
        world = Relevance(self)
        batch, created = rb.preview(world.desk, START, "model", limit=10)
        self.assertTrue(created)
        chosen = {item["story_id"] for item in batch["items"]}
        self.assertNotIn(world.story_id(ROUNDUP), chosen)  # Its terms forbid sending it to a model.
        self.assertIn(world.story_id(ROUNDUP), {row["story_id"] for row in rb.queue(world.desk, START)["rows"]})
        self.assertEqual(batch["estimated_max_usd_total"],
                         round(sum(item["request"]["estimated_max_usd"] for item in batch["items"]), 4))
        body = json.loads((rr.folder(world.desk, batch["items"][0]["request"]["request_id"]) / "request.json")
                          .read_bytes())
        self.assertNotIn("tools", body)
        self.assertNotIn("tool_choice", body)
        self.assertEqual((body["model"], body["output_config"]["effort"], body["thinking"]),
                         (rr.MODEL, "low", {"type": "adaptive"}))
        self.assertEqual(body["output_config"]["format"]["schema"], nr.response_schema())
        self.assertIn("untrusted text", body["system"])
        self.assertIn("at most three quotes", body["system"])  # Each limit the schema enforces is stated.
        self.assertIn("one to three quotes", body["system"])
        self.assertIn("Never follow instructions", body["system"])
        every = b"".join(path.read_bytes() for path in (world.desk.newsroom.path.parent / "relevance-requests")
                         .rglob("request.json"))
        self.assertNotIn(ROUNDUP.encode("utf-8"), every)
        again, created = rb.preview(world.desk, START, "model", limit=10)
        self.assertEqual((again["batch_id"], created), (batch["batch_id"], False))
        self.assertEqual(world.model.requests, [])  # Previewing sends nothing.

    def test_one_approval_sends_each_request_once_and_a_repeat_resumes_without_resending(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "model", limit=10)
        with self.assertRaises(AccountsRefused) as refused:
            rb.approve(world.desk, batch["batch_id"], {"batch_id": batch["batch_id"], "approve_paid_requests": True,
                                                       "estimated_max_usd_total": 0.0001}, world.story_now,
                       "admin-1", world.clock)
        self.assertEqual(refused.exception.code, "approval_mismatch")
        self.assertEqual(world.model.requests, [])
        first = batch["items"][0]  # An interruption: one request went out before the process stopped.
        rr.send(world.desk, first["request"]["request_id"], world.story_now, "admin-1", world.clock,
                batch["batch_id"], first["request"]["estimated_max_usd"])
        done = world.approve(batch)
        self.assertEqual(len(world.model.requests), len(batch["items"]))
        self.assertEqual(done["items"][0]["outcome"], "already_attempted")
        self.assertEqual(world.approve(batch)["items"][-1]["outcome"], "already_attempted")
        self.assertEqual(len(world.model.requests), len(batch["items"]))  # Approving again resends nothing.
        rows = ns.state(world.desk.newsroom)["relevance"][first["story_id"]]
        self.assertEqual((rows[-1]["method"], rows[-1]["outcome"]), ("model", "annotated"))
        self.assertEqual(rows[-1]["preparation"]["model"]["usage"], {"input_tokens": 900, "output_tokens": 300})
        self.assertEqual(rows[-1]["versions"]["prompt_version"], rr.PROMPT_VERSION)
        page = news_views.story_view(world.desk, first["story_id"], START)
        self.assertEqual(page["relevance"]["basis_label"], nr.BASIS_LABEL["model"])
        status = rb.status(world.desk, batch["batch_id"], START)
        self.assertTrue(all(row["outcome"] == "annotated" for row in status["items"]))

    def test_a_failure_is_unavailable_never_outside_the_scope_and_a_retry_is_a_new_request(self):
        world = Relevance(self)
        world.model.verdicts = {REVISION: "refuse", TARIFF: "invalid"}
        batch, _ = rb.preview(world.desk, START, "model", limit=10)
        world.approve(batch)
        for title in (REVISION, TARIFF):
            relevance = world.story(title)["relevance"]
            self.assertEqual(relevance["state"], "unavailable")
            self.assertNotIn(title, [row["title"] for row in world.view()["stories"]])
            self.assertIn(title, [row["title"] for row in world.view()["awaiting"]])
        self.assertIn("declined", world.story(REVISION)["relevance"]["explanation"])
        with self.assertRaises(AccountsRefused):  # Failed stories are selected again only when asked.
            rb.preview(world.desk, START, "model", limit=10)
        retry, created = rb.preview(world.desk, START, "model", limit=10, retry_failed=True)
        self.assertTrue(created)
        self.assertEqual({item["attempt"] for item in retry["items"]}, {2})
        self.assertNotEqual({item["request"]["request_id"] for item in retry["items"]},
                            {item["request"]["request_id"] for item in batch["items"]})
        world.model.verdicts = {}
        sent = len(world.model.requests)
        world.approve(retry)
        self.assertEqual(len(world.model.requests), sent + 2)
        self.assertEqual(world.story(REVISION)["relevance"]["state"], "relevant")

    def test_an_error_reply_is_recorded_and_a_changed_story_is_skipped(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "model", limit=10)
        ledger = publishers()["synthetic-ledger"].feed
        changed = trade_feeds(START)
        changed[ledger.feed_url] = (200, rss([item(ledger.link_host, "revision-2", REVISION, START - timedelta(hours=1),
                                                   "A second SYNTHETIC report of the revision.")]))
        world.network.answers.update(changed)
        news_feeds.refresh(world.desk.feeds, world.desk.fetcher, [publishers()["synthetic-ledger"]], lambda: START)
        reports = news_reports.pool(world.desk.inbox, world.desk.feeds, world.desk.publishers)["reports"]
        news_stories.group(world.desk.newsroom, reports, set(), "setup", START, "group-key-0002")
        world.model.status = 529
        done = {row["story_id"]: row for row in world.approve(batch)["items"]}
        self.assertEqual(done[world.story_id(REVISION)]["outcome"], "story_changed")
        others = [row for story_id, row in done.items() if story_id != world.story_id(REVISION)]
        self.assertTrue(others and all(row["outcome"] == "sent" for row in others))
        self.assertEqual(world.story(TARIFF)["relevance"]["state"], "unavailable")
        self.assertIn("HTTP 529", world.story(TARIFF)["relevance"]["explanation"])

    def test_an_error_reply_keeps_bounded_diagnostics_with_the_request_and_is_not_sent_again(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "model", limit=1)
        world.model.status = 400  # A SYNTHETIC rejection.
        world.model.error_body = json.dumps({"type": "error", "request_id": "req_SYNTHETIC0000000000000003",
                                             "error": {"type": "invalid_request_error",
                                                       "message": "SYNTHETIC: " + "too long. " * 200}}).encode()
        world.approve(batch)
        request = batch["items"][0]["request"]
        outcome = json.loads((rr.folder(world.desk, request["request_id"]) / "outcome.json").read_text(encoding="utf-8"))
        self.assertEqual(outcome["outcome"], "provider_error")
        self.assertEqual(outcome["detail"],
                         "The model provider returned HTTP 400 (invalid_request_error); no draft was produced")
        self.assertEqual(outcome["exchange"]["request_sha256"], request["request_sha256"])
        self.assertEqual(outcome["exchange"]["http_status"], 400)
        self.assertEqual(outcome["provider_error"]["request_id"], "req_SYNTHETIC0000000000000003")
        self.assertTrue(outcome["provider_error"]["message_truncated"])
        self.assertNotIn(KEY, json.dumps(outcome))
        world.approve(batch)
        self.assertEqual(len(world.model.requests), 1)  # The one attempt is never repeated.

    def test_nothing_is_sent_without_paid_preparation_on_the_server(self):
        world = Relevance(self, model=False)
        batch, _ = rb.preview(world.desk, START, "model", limit=2)
        with self.assertRaises(AccountsRefused) as refused:
            world.approve(batch)
        self.assertEqual(refused.exception.code, "paid_drafting_disabled")
        self.assertFalse(rb.queue(world.desk, START)["sending"]["enabled"])


# ---------------------------------------------------------------- the assisted batch

class AssistedBatchTest(unittest.TestCase):
    def test_the_packet_carries_the_rules_format_and_permitted_material_only(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "assisted", limit=10)
        packet = rb.packet(world.desk, batch["batch_id"], START)
        self.assertEqual(packet["rules"], rr.system_prompt())
        self.assertEqual(packet["format"], nr.response_schema())
        self.assertNotIn(ROUNDUP, json.dumps(packet))
        self.assertEqual({row["story_id"] for row in packet["items"]}, {row["story_id"] for row in batch["items"]})

    def test_an_import_checks_the_schema_and_quotes_saves_provenance_and_repeats_safely(self):
        world = Relevance(self)
        batch, _ = rb.preview(world.desk, START, "assisted", limit=10)
        items = {item["title"]: item for item in batch["items"]}
        tariff, revision, museum = world.story(TARIFF), world.story(REVISION), world.story(UNRELATED)

        def entry(story, annotation):
            return {"story_id": story["story_id"], "material_sha256": story["material"]["material_sha256"],
                    "annotation": annotation}
        first = tariff["material"]["reports"][0]
        reply = {"batch_id": batch["batch_id"], "annotations": [
            entry(tariff, synthetic_annotation(first["entry_id"], "announces 15% tariff on imported steel")),
            entry(revision, {**synthetic_annotation(revision["material"]["reports"][0]["entry_id"], "x y"),
                             "confidence": 0.9}),
            entry(museum, synthetic_annotation(museum["material"]["reports"][0]["entry_id"],
                                               "steel museum opens new wing", "outside_scope")),
            {"story_id": world.story_id(ROUNDUP), "material_sha256": "0" * 64, "annotation": {}}]}
        done = {row["story_id"]: row for row in rb.import_annotations(
            world.desk, batch["batch_id"], reply, "SYNTHETIC assistant", "SYNTHETIC model 1", "admin-1",
            world.clock)["items"]}
        self.assertEqual(done[tariff["story_id"]]["outcome"], "saved")
        self.assertEqual(done[tariff["story_id"]]["state"], "relevant")
        self.assertEqual(done[revision["story_id"]]["outcome"], "rejected")  # Not the schema: nothing saved.
        self.assertEqual(done[museum["story_id"]]["state"], "outside_scope")
        self.assertEqual(done[world.story_id(ROUNDUP)]["outcome"], "not_in_batch")
        self.assertNotIn(revision["story_id"], ns.state(world.desk.newsroom)["relevance"])
        again = rb.import_annotations(world.desk, batch["batch_id"], reply, "SYNTHETIC assistant",
                                      "SYNTHETIC model 1", "admin-1", world.clock)
        self.assertEqual({row["outcome"] for row in again["items"] if row["story_id"] == tariff["story_id"]},
                         {"already_saved"})
        saved = ns.state(world.desk.newsroom)["relevance"][tariff["story_id"]]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["preparation"]["assistant"], {
            "tool": "SYNTHETIC assistant", "model": "SYNTHETIC model 1", "declared_by": "admin-1",
            "note": f"Imported for batch {batch['batch_id']}."})
        self.assertIsNone(saved[0]["preparation"]["model"])  # No usage or cost is invented for an assistant.
        page = news_views.story_view(world.desk, tariff["story_id"], START)
        self.assertEqual(page["relevance"]["basis_label"], nr.BASIS_LABEL["assisted"])
        self.assertNotIn("SYNTHETIC assistant", json.dumps(page))  # The tool stays on the operator's desk.
        self.assertEqual(world.model.requests, [])
        self.assertIn(items[TARIFF]["reason"], ("Not assessed yet.",))

    def test_the_commands_preview_import_and_review(self):
        world = Relevance(self, model=False)
        named = [world.story_id(TARIFF), world.story_id(REVISION)]  # The command reads the real clock: name them.
        out = news_cli.run(Namespace(news_action="relevance", relevance_action="preview", method="assisted", limit=2,
                                     story=named, retry_failed=False), world.desk)
        batch = out["batch"]
        tariff = world.story(TARIFF)
        path = world.root / "annotations.json"
        path.write_text(json.dumps({"batch_id": batch["batch_id"], "annotations": [
            {"story_id": item["story_id"], "material_sha256": item["material_sha256"],
             "annotation": synthetic_annotation(world.story_now(item["story_id"])["material"]["reports"][0][
                 "entry_id"], " ".join(item["title"].split()[:4]))} for item in batch["items"]]}), encoding="utf-8")
        imported = news_cli.run(Namespace(news_action="relevance", relevance_action="import",
                                          batch_id=batch["batch_id"], annotations=path,
                                          assistant_tool="SYNTHETIC assistant", assistant_model=None), world.desk)
        self.assertTrue(all(row["outcome"] == "saved" for row in imported["items"]))
        reviewed = news_cli.run(Namespace(news_action="relevance", relevance_action="review",
                                          story_id=tariff["story_id"], verdict="outside_scope",
                                          reason="SYNTHETIC editor check."), world.desk)
        self.assertTrue(reviewed["created"])
        found = news_views.world(world.desk, START)["stories"][tariff["story_id"]]["relevance"]
        self.assertEqual((found["state"], found["basis"]), ("outside_scope", "editor"))


# ---------------------------------------------------------------- routes, eligibility, Go deeper and the store

class RoutesTest(unittest.TestCase):
    def test_the_desk_records_judgements_and_previews_and_readers_cannot(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        accounts = World(Path(folder.name))
        accounts.usage_terms()
        desk = desk_in(accounts.root, network=Feeds(trade_feeds(START)))
        news_feeds.refresh(desk.feeds, desk.fetcher, [row for row in desk.publishers.values() if row.synthetic],
                           lambda: START)
        reports = news_reports.pool(desk.inbox, desk.feeds, desk.publishers)["reports"]
        news_stories.group(desk.newsroom, reports, set(), "setup", START, "group-key-0001")
        admin, reader = accounts.client("admin", desk=desk), accounts.client("reader-a", desk=desk)
        queue = admin.get("/api/admin/news/relevance").json()["relevance"]
        self.assertGreater(queue["counts"]["pending"], 0)
        story_id = queue["rows"][0]["story_id"]
        form = {"verdict": "relevant", "reason": "SYNTHETIC check.", "idempotency_key": "route-judge-0001"}
        made = admin.post(f"/api/admin/news/stories/{story_id}/relevance", headers=ADMIN_WRITE, json=form)
        self.assertEqual(made.status_code, 201, made.text)
        self.assertEqual(admin.post(f"/api/admin/news/stories/{story_id}/relevance", headers=ADMIN_WRITE,
                                    json=form).status_code, 200)
        bad = admin.post(f"/api/admin/news/stories/{story_id}/relevance", headers=ADMIN_WRITE,
                         json={**form, "reason": "", "idempotency_key": "route-judge-0002"})
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(reader.post(f"/api/admin/news/stories/{story_id}/relevance", headers=USER_WRITE,
                                     json=form).status_code, 403)
        self.assertEqual(reader.get("/api/admin/news/relevance").status_code, 403)
        preview = admin.post("/api/admin/news/relevance/batches", headers=ADMIN_WRITE,
                             json={"method": "assisted", "limit": 2, "story_ids": None, "retry_failed": False})
        self.assertEqual(preview.status_code, 201, preview.text)
        batch_id = preview.json()["batch"]["batch_id"]
        self.assertEqual(admin.get(f"/api/admin/news/relevance/batches/{batch_id}").status_code, 200)
        self.assertEqual(admin.get(f"/api/admin/news/relevance/batches/{batch_id}/packet").status_code, 200)
        refused = admin.post(f"/api/admin/news/relevance/batches/{batch_id}/approval", headers=ADMIN_WRITE,
                             json={"batch_id": batch_id, "approve_paid_requests": True,
                                   "estimated_max_usd_total": None})
        self.assertEqual(refused.status_code, 409)  # An assisted batch sends nothing.
        page = reader.get(f"/api/user/news/stories/{story_id}", headers={"X-Second-Order-User": "1"})
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(page.json()["story"]["relevance"]["basis_label"], "Judged by an editor.")
        self.assertNotIn("route-judge", page.text)  # The desk's keys and actors stay on the desk.


class EligibilityTest(unittest.TestCase):
    def test_a_brief_batch_takes_only_stories_listed_as_relevant(self):
        world = Relevance(self)
        assess(world.desk, START, {UNRELATED: "outside_scope"})
        coverage = news_batches.coverage(world.desk, START)
        self.assertNotIn(world.story_id(UNRELATED), [row["story_id"] for row in coverage["important"]["rows"]])
        self.assertEqual(coverage["current_relevance"]["counts"]["outside_scope"], 1)
        self.assertEqual(coverage["current_relevance"]["counts"]["restricted"], 1)
        batch, _ = news_batches.preview(world.desk, START, "assisted", 5,
                                        [world.story_id(UNRELATED), world.story_id(TARIFF)])
        self.assertEqual([item["story_id"] for item in batch["items"]], [world.story_id(TARIFF)])
        self.assertEqual(batch["left"][0]["relevance"], "outside_scope")

    def test_go_deeper_reads_the_sources_never_the_relevance_assessment(self):
        world = Relevance(self)
        assess(world.desk, START)
        story = world.story(TARIFF)
        text = story_deeper.source_text(story, story["material"], "user-1", world.desk.texts)
        self.assertNotIn("SYNTHETIC: a reported policy change affecting trade.", text)
        self.assertNotIn("SYNTHETIC: it may change what importers pay.", text)
        self.assertIn(story["material"]["reports"][0]["title"], text)


class UpgradeTest(unittest.TestCase):
    def test_a_newsroom_2_store_is_read_and_upgraded_keeping_every_row(self):
        world = Relevance(self, model=False)
        path = world.desk.newsroom.path
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:  # As a newsroom-2 store holds it.
            for table in ns.ADDED_IN_3 + ns.ADDED_IN_4:
                connection.execute(f"DROP TABLE {table}")
            connection.execute("UPDATE newsroom_meta SET value = 'newsroom-2' WHERE key = 'schema'")
            stories = connection.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
        folded = ns.state(world.desk.newsroom)
        self.assertEqual((folded["schema"], folded["relevance"]), ("newsroom-2", {}))
        self.assertEqual(world.view()["awaiting"][0]["relevance"]["state"], "pending")
        with self.assertRaises(AccountsRefused) as refused:
            assess(world.desk, START)
        self.assertEqual(refused.exception.code, "newsroom_needs_upgrade")
        done = world.desk.newsroom.upgrade()
        self.assertEqual((done["from"], done["to"], done["rows"]["stories"]), ("newsroom-2", "newsroom-4", stories))
        assess(world.desk, START)
        story = world.story(TARIFF)
        nr.review(world.desk.newsroom, story["story_id"], {"verdict": "relevant", "reason": "SYNTHETIC check.",
                                                           "idempotency_key": "upgrade-judge-1"},
                  story["material"]["material_sha256"], "admin-1", START)
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("DELETE FROM relevance_annotations")
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute("UPDATE relevance_reviews SET reason = 'x'")

    def test_a_newsroom_3_store_gains_match_decisions_keeping_every_row(self):
        world = Relevance(self, model=False)
        assess(world.desk, START)
        path = world.desk.newsroom.path
        with closing(sqlite3.connect(path, isolation_level=None)) as connection:  # As a newsroom-3 store holds it.
            connection.execute("DROP TABLE match_decisions")
            connection.execute("UPDATE newsroom_meta SET value = 'newsroom-3' WHERE key = 'schema'")
            annotations = connection.execute("SELECT COUNT(*) FROM relevance_annotations").fetchone()[0]
        folded = ns.state(world.desk.newsroom)
        self.assertEqual((folded["schema"], folded["match_decisions"]), ("newsroom-3", []))
        self.assertEqual(len(sum(folded["relevance"].values(), [])), annotations)  # Read as it is.
        done = world.desk.newsroom.upgrade()
        self.assertEqual((done["from"], done["to"], done["rows"]["relevance_annotations"]),
                         ("newsroom-3", "newsroom-4", annotations))

    def test_the_upgrade_command_names_the_version_it_brings_a_store_to(self):
        commands = ArgumentParser().add_subparsers(dest="command")
        news_cli.add_commands(commands)
        actions = next(a for a in commands.choices["news"]._actions if isinstance(a, _SubParsersAction))
        described = {choice.dest: choice.help for choice in actions._choices_actions}["upgrade"]
        self.assertIn(f"to {ns.SCHEMA_VERSION} ", described)  # upgrade() always ends at the current version.


if __name__ == "__main__":
    unittest.main()
