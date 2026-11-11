"""Event processing history (event_history): the dated steps an event's own records show, from retrieval to triage,
analysis, review and freeze, joined only by stable IDs and explicit links. SYNTHETIC feeds, model replies and records
through counting fakes in temporary folders; nothing reaches a network or touches data/.
"""
from datetime import datetime, timezone
import json
from unittest.mock import patch

import httpx

from test_event_inbox import fingerprint, rss, rss_item
from test_event_overview import Overview
from test_headline_triage import FED, FED_LINK, NOTE, STATEMENT, Provider, feeds, reply, results, entry_ids
from second_order import event_history


def rows(page: dict, step: str) -> list[dict]:
    return next(group["rows"] for group in page["history"]["steps"] if group["step"] == step)


class NotProcessedTests(Overview):
    def test_a_retrieved_entry_with_nothing_else_is_not_processed_and_says_where_it_came_from(self):
        statement = self.id(STATEMENT, "0916a")
        page = self.overview("inbox", statement)
        history = page["history"]
        self.assertEqual((history["history_version"], history["state"], history["provider_called"]),
                         ("event-history-0.1", "not_processed", False))
        (source,) = rows(page, "source")
        self.assertEqual((source["label"], source["state"], source["version"], source["retrievals"],
                          source["kept_responses"], source["current"]), ("First retrieved", "retrieved", 1, 1, 1, True))
        self.assertIn("Feed timestamp Wed, 16 Sep 2026 18:00:00 GMT (RSS pubDate)", source["detail"])
        self.assertIn("a feed excerpt as supplied (not the article)", source["detail"])
        self.assertNotIn("publish", source["label"].lower())  # Retrieval is never presented as publication.
        for step in ("triage", "analysis", "review", "use"):
            self.assertEqual(rows(page, step), [], step)
        self.assertEqual(history["summary"]["retrievals"], 1)
        limits = " ".join(history["limitations"])
        self.assertIn("not processing steps", limits)
        self.assertIn("No local record verifies billing", limits)
        self.assertIn("started without a research store", limits)
        self.no_calls()

    def test_entries_retrieved_before_records_existed_say_so(self):
        statement = self.id(STATEMENT, "0916a")
        for path in (self.inbox / "acquisitions").rglob("*.json"):
            path.chmod(0o666)
            path.unlink()
        page = self.overview("inbox", statement)
        (source,) = rows(page, "source")
        self.assertEqual(source["retrievals"], 0)
        self.assertIn("before retrieval records were kept", " ".join(page["history"]["limitations"]))


class TriageHistoryTests(Overview):
    def test_a_simulated_result_is_listed_as_simulated_with_no_cost(self):
        statement = self.id(STATEMENT, "0916a")
        self.process(statement, provider=self.provider)
        page = self.overview("inbox", statement)
        (row,) = rows(page, "triage")
        self.assertEqual((row["state"], row["mode"], row["role"], row["version"], row["tone"]),
                         ("accepted", "simulated", "entry", 1, "done"))
        self.assertIn("no model read the entry", row["label"])
        self.assertEqual((row["cost"]["usage_usd"], row["cost"]["billing"]), (0, None))
        self.assertEqual(row["result"]["category"], "Policy decision")
        summary = page["history"]["summary"]
        self.assertEqual((page["history"]["state"], summary["simulated_triage"], summary["model_triage"]),
                         ("processed", 1, 0))

    def test_a_paid_send_without_a_reply_is_uncertain_and_may_have_been_billed(self):
        note = self.id(NOTE)
        lost = Provider(lambda request: httpx.ReadTimeout("simulated: no reply"))
        self.approve(self.prepare(note, mode="paid"), lost, mode="paid")
        page = self.overview("inbox", note)
        (row,) = rows(page, "triage")
        self.assertEqual((row["state"], row["tone"], row["mode"]), ("uncertain", "warn", "paid"))
        self.assertIn("may have been received and billed", row["label"])
        self.assertIsNone(row["cost"]["usage_usd"])
        self.assertEqual(row["cost"]["billing"], "not_verified")
        self.assertGreater(row["cost"]["estimate_usd"], 0)
        self.assertEqual((page["history"]["state"], page["history"]["summary"]["uncertain"]), ("needs_attention", 1))

    def test_a_rejected_reply_and_a_paid_result_keep_their_own_outcomes_and_costs(self):
        note, statement = self.id(NOTE), self.id(STATEMENT, "0916a")
        missing = Provider(lambda request: reply(results(entry_ids(request))[1:]))
        self.approve(self.prepare(note, statement), missing)
        paid = Provider(lambda request: reply(results(entry_ids(request))))  # Reports 9,000 and 1,500 tokens.
        self.approve(self.prepare(statement, mode="paid"), paid, mode="paid")
        by_state = {row["state"]: row for row in rows(self.overview("inbox", statement), "triage")}
        self.assertEqual(set(by_state), {"not_accepted", "accepted"})
        self.assertIn("have no result", by_state["not_accepted"]["detail"])
        accepted = by_state["accepted"]
        self.assertEqual((accepted["mode"], accepted["cost"]["billing"]), ("paid", "not_verified"))
        self.assertGreater(accepted["cost"]["usage_usd"], 0)
        self.assertIn("Usage-derived", accepted["cost"]["basis"])
        self.assertLess(accepted["cost"]["usage_usd"], accepted["cost"]["estimate_usd"])

    def test_comparison_context_is_listed_without_a_result(self):
        statement, note = self.id(STATEMENT, "0916a"), self.id(NOTE)
        self.process(statement, provider=self.provider)
        self.process(statement, note, provider=self.provider)  # The statement comes along only as context.
        roles = sorted((row["role"], bool(row["result"])) for row in rows(self.overview("inbox", statement), "triage"))
        self.assertEqual(roles, [("context", False), ("entry", True)])

    def test_a_changed_entry_keeps_each_result_on_its_own_version(self):
        statement = self.id(STATEMENT, "0916a")
        self.process(statement, provider=self.provider)
        changed = feeds()
        changed[FED] = [(200, rss([rss_item(1, f"{STATEMENT} (title edited)", FED_LINK.format("20260916a"),
                                            pub="Wed, 16 Sep 2026 18:00:00 GMT")]))]
        self.refresh(changed, datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc))
        page = self.overview("inbox", statement)
        self.assertEqual([(row["version"], row["current"], row["retrievals"]) for row in rows(page, "source")],
                         [(1, False, 1), (2, True, 1)])
        (row,) = rows(page, "triage")
        self.assertEqual(row["version"], 1)
        self.assertIn("Version 1 of this entry", row["detail"])


class AnalysisHistoryTests(Overview):
    def test_a_capture_mock_draft_and_review_appear_in_order_with_links(self):
        statement = self.id(STATEMENT, "0916a")
        preview = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        draft_id = self.mock(preview)
        self.review(draft_id, "human_reviewed", "Checked against the source.")
        page = self.overview("inbox", statement)
        captured, drafted = rows(page, "analysis")
        self.assertEqual((captured["state"], captured["href"]),
                         ("captured", f"/events/capture/{preview['capture_id']}"))
        self.assertIn("from version 1 of the Inbox entry", captured["detail"])
        self.assertEqual((drafted["state"], drafted["mode"], drafted["cost"]["usage_usd"], drafted["draft_id"]),
                         ("draft", "mock", 0, draft_id))
        self.assertTrue(drafted["href"].startswith(f"/?draft={draft_id}&from=%2Fevents%2Finbox%2F"))
        (review,) = rows(page, "review")
        self.assertEqual((review["state"], review["current"], review["tone"]), ("human_reviewed", True, "done"))
        summary = page["history"]["summary"]
        self.assertEqual((summary["captures"], summary["drafts"], summary["reviews"]), (1, 1, 1))
        capture_page = self.overview("capture", preview["capture_id"])
        self.assertEqual([row["step"] for group in capture_page["history"]["steps"] for row in group["rows"]],
                         ["source", "analysis", "analysis", "review"])
        self.assertEqual(rows(capture_page, "source")[0]["href"], f"/events/inbox/{statement}")
        self.no_calls()

    def test_captures_without_a_recorded_origin_are_never_attributed_and_are_counted(self):
        statement = self.id(STATEMENT, "0916a")
        typed = self.capture(STATEMENT, FED_LINK.format("20260916a"))  # Same headline and link, no origin.
        page = self.overview("inbox", statement)
        self.assertEqual((rows(page, "analysis"), page["history"]["state"]), ([], "not_processed"))
        self.assertIn("1 saved event has no recorded Inbox origin", " ".join(page["history"]["limitations"]))
        capture_page = self.overview("capture", typed["capture_id"])
        self.assertIn("no recorded Inbox origin", " ".join(capture_page["history"]["limitations"]))
        self.assertEqual(rows(capture_page, "source"), [])

    def test_an_unsent_capture_is_a_valid_step_and_a_lost_paid_send_is_uncertain(self):
        statement = self.id(STATEMENT, "0916a")
        quiet = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        lost = self.capture("Lost paid draft", FED_LINK.format("20260916a"), origin=statement)
        attempt = self.root / "attempts" / lost["capture_id"]
        attempt.mkdir(parents=True)
        (attempt / "reservation.json").write_text(json.dumps({"mode": "paid"}), encoding="utf-8")
        (attempt / "attempt.json").write_text(json.dumps({"state": "sending", "mode": "paid",
                                                          "sent_at": "2026-10-09T15:00:00+00:00"}), encoding="utf-8")
        page = self.overview("inbox", statement)
        analysis = rows(page, "analysis")
        quiet_row = next(row for row in analysis if row.get("capture_id") == quiet["capture_id"])
        self.assertIn("nothing was sent", quiet_row["detail"])
        uncertain = next(row for row in analysis if row["state"] == "uncertain")
        self.assertEqual((uncertain["capture_id"], uncertain["cost"]["billing"], uncertain["cost"]["usage_usd"]),
                         (lost["capture_id"], "not_verified", None))
        self.assertEqual(page["history"]["state"], "needs_attention")

    def test_a_frozen_hypothesis_is_listed_only_through_a_verified_freeze_record(self):
        statement = self.id(STATEMENT, "0916a")
        preview = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        draft_id = self.mock(preview)
        link = {"draft_id": draft_id, "capture_id": preview["capture_id"], "hypothesis_id": "a" * 64,
                "action_id": "b" * 64, "frozen_at": "2026-10-09T16:00:00+00:00", "headline": STATEMENT,
                "draft_view_sha256": "c" * 64, "review_at_freeze": None}
        other = {**link, "capture_id": "20261009T150000000000Z-0123456789ab", "hypothesis_id": "d" * 64}
        found = {"links": [link, other], "problems": [{"action_id": "e" * 64, "problem": "The freeze record eeeee "
                                                       "does not verify"}]}
        with patch("second_order.assessment_records.draft_links", return_value=found):
            history = event_history.inbox_history(statement, self.item(statement), [], self.folders(),
                                                  self.root / "store.db")
        (use,) = next(group["rows"] for group in history["steps"] if group["step"] == "use")
        self.assertEqual((use["hypothesis_id"], use["href"]), ("a" * 64, f"/hypotheses/{'a' * 64}"))
        self.assertIn("Research intake is closed", use["detail"])
        self.assertIn("does not verify", " ".join(history["limitations"]))

    def folders(self):
        from second_order import event_overview
        return event_overview.folders_for(self.inbox, self.root / "intake", self.root / "attempts",
                                          self.root / "prepared-drafts", None, self.root / "reviews", self.triage,
                                          self.root / "links", self.root / "market", None)


class ReadOnlyTests(Overview):
    def test_reading_histories_and_the_index_writes_and_requests_nothing(self):
        statement, note = self.id(STATEMENT, "0916a"), self.id(NOTE)
        self.process(statement, provider=self.provider)
        preview = self.capture(STATEMENT, FED_LINK.format("20260916a"), origin=statement)
        self.mock(preview)
        sent = len(self.provider.requests)
        before = fingerprint(self.root)
        for _ in range(2):
            self.overview("inbox", statement)
            self.overview("inbox", note)
            self.overview("capture", preview["capture_id"])
            index = self.client.get("/api/events/processing").json()
        self.assertEqual(fingerprint(self.root), before)
        self.assertEqual((len(self.provider.requests), len(self.feeds.requests), len(self.board.calls)), (sent, 0, 0))
        self.assertEqual(index["items"][statement], {"model_triage": False, "simulated_triage": True,
                                                     "triage_attention": False, "triage_requests": 1, "captures": 1})
        self.assertNotIn(note, index["items"])
