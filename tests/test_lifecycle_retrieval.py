"""Outcome-data retrieval for frozen hypotheses (A3): a lifecycle plan, one approved download through a FAKE
transport, reuse of kept packages and snapshots, and every safeguard of the market retrieval.

The Board's server is simulated in process (market_fakes.FakeRelease, labelled SYNTHETIC); its call count shows what
was requested. No network is reached, no real store is opened and nothing real is frozen, downloaded or assessed.
"""
from datetime import date, datetime, timedelta
import json
import socket
import unittest
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from fred_fixtures import FakeFred, datasets
from market_fakes import FakeRelease
from second_order import market_store
from second_order.api import create_app
from second_order.market_calendar import expected_sessions
from second_order.store import open_store
from store_records import stored_before_policy_b
from test_daily import cmt_hypothesis, ny
from test_fred import run_import
from test_lifecycle_assessment import AFTER, UTC, AssessmentHarness, second_form
from test_lifecycle_freeze import BASE, LIFECYCLE, manual, tree
from test_pilot_rehearsal import FREEZE_AT, FRESH, pilot_form


class RetrievalHarness(AssessmentHarness):
    def setUp(self):
        super().setUp()
        self.release = FakeRelease(self.clock)
        self.client = self.app_with(self.release.fetcher())

    def app_with(self, fetcher) -> TestClient:
        client = TestClient(create_app(self.root / "no-dossiers", None, self.drafts, self.reviews, self.intake,
                                       self.attempts, market=self.market, market_fetcher=fetcher, store=self.store,
                                       lifecycle_clock=self.clock), base_url=BASE)
        self.addCleanup(client.close)
        return client

    def plan(self, hypotheses: list[str], client: TestClient | None = None, expect: int = 200) -> dict:
        response = (client or self.client).post("/api/lifecycle/retrieval-preview", headers=LIFECYCLE,
                                                content=json.dumps({"hypotheses": hypotheses}))
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def send(self, shown: dict, attempt: int | None = None, client: TestClient | None = None):
        return (client or self.client).post("/api/lifecycle/retrievals", headers=LIFECYCLE, content=json.dumps(
            {"plan_sha256": shown["plan_sha256"], "hypotheses": [row["hypothesis_id"] for row in shown["hypotheses"]],
             "attempt": attempt or shown["next_attempt"]}))


class PlanTests(RetrievalHarness):
    def test_one_download_serves_every_selected_hypothesis_and_a_covered_selection_needs_none(self):
        first, second = self.frozen(), self.frozen(second_form())
        self.at(AFTER)
        before = tree(self.root)
        shown = self.plan([first, second])
        self.assertEqual(tree(self.root), before)  # A preview writes nothing and sends nothing.
        self.assertEqual(self.release.calls, [])
        self.assertEqual((shown["plan_version"], shown["requests"], shown["request"]["download"]),
                         ("lifecycle-outcome-plan-0.2", 1, "full_release_package"))
        self.assertEqual({(row["required_from"], row["required_through"]) for row in shown["hypotheses"]},
                         {("2026-09-15", "2026-09-23")})
        self.assertEqual(shown["missing_sessions"], ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
                                                     "2026-09-21", "2026-09-22", "2026-09-23"])
        self.assertEqual(shown["future_sessions"], [])
        sent = self.send(shown)
        self.assertEqual(sent.status_code, 201, sent.text)
        result = sent.json()
        self.assertEqual((result["outcome"], result["validation"], result["imported"], result["evaluated"]),
                         ("saved", "accepted", False, False))
        self.assertEqual(len(self.release.calls), 1)
        again = self.plan([first, second])
        self.assertEqual(again["requests"], 0)
        self.assertEqual(again["reuse"]["packages"], [{"package_id": result["package_id"],
                                                       "hypotheses": sorted([first, second]), "needs_import": True}])
        refused = self.send(again, attempt=1)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("Nothing is missing", refused.json()["detail"])
        imported = self.import_outcome(first, result["package_id"])
        reused = self.import_outcome(second, result["package_id"], expect=200)  # The same snapshot serves both.
        self.assertEqual((reused["reused"], reused["snapshot"]["snapshot_id"]),
                         (True, imported["snapshot"]["snapshot_id"]))
        self.assertEqual(self.plan([first, second])["reuse"]["snapshots"],
                         [{"snapshot_id": imported["snapshot"]["snapshot_id"], "hypotheses": sorted([first, second])}])
        self.assertEqual(len(self.release.calls), 1)
        record = json.loads((self.market / "packages" / result["package_id"] / "acquisition.json").read_text("utf-8"))
        self.assertEqual(record["approval"], {"plan_version": "lifecycle-outcome-plan-0.2",
                                              "plan_sha256": shown["plan_sha256"], "attempt": 1,
                                              "hypotheses": sorted([first, second])})

    def test_future_sessions_are_never_requested_and_a_late_long_horizon_uses_its_own_dates(self):
        hypothesis_id = self.frozen()
        self.at(datetime(2026, 9, 22, 15, tzinfo=UTC))  # 11 a.m. in New York: Monday the 21st is not posted yet.
        shown = self.plan([hypothesis_id])
        self.assertEqual(shown["missing_sessions"], ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"])
        self.assertEqual(shown["awaiting_release"],
                         [{"session": "2026-09-21", "obtainable_from": "2026-09-22 16:15 New York time"}])
        self.assertEqual(shown["future_sessions"], ["2026-09-22", "2026-09-23"])
        legs = [{**leg, "horizon": 20} for leg in manual()["legs"]]
        late = self.frozen(manual(legs=legs, story_id="synthetic-late-long", headline="Synthetic late, long freeze"),
                           at=datetime(2026, 9, 24, 15, tzinfo=UTC))
        self.at(AFTER)
        sessions = sorted(expected_sessions(date(2026, 9, 25), date(2026, 12, 31)))
        target = sessions[20].isoformat()  # Twenty sessions after the first date after the New York freeze date.
        self.assertEqual(self.readiness(late)["expected"]["latest_expected_target"], target)
        shown = self.plan([late])
        [row] = shown["hypotheses"]
        self.assertEqual((row["required_from"], row["required_through"]), ("2026-09-15", target))
        self.assertGreater(target, "2026-09-29")  # Beyond the fourteen days after publication an event window covers.
        self.assertTrue(all(day < "2026-10-01" for day in shown["missing_sessions"]))
        self.assertEqual(shown["future_sessions"][0], "2026-10-01")
        self.assertEqual(shown["future_sessions"][-1], target)

    def test_a_fred_hypothesis_is_never_planned(self):
        self.store.parent.mkdir(parents=True)
        writer = open_store(str(self.store))
        baseline = run_import(writer, FakeFred(datasets(date(2025, 5, 30)), date(2025, 6, 2)), date(2025, 6, 2),
                              datetime(2025, 6, 2, 22, tzinfo=UTC))["snapshot_id"]
        frozen = ny(2025, 6, 3, 9, 30)
        legacy = stored_before_policy_b(writer, cmt_hypothesis(ny(2025, 6, 3, 9), frozen), frozen, baseline)
        writer.close()
        self.at(datetime(2025, 6, 22, 12, tzinfo=UTC))
        refused = self.plan([legacy], expect=409)
        self.assertIn("never substituted", refused["detail"])
        self.assertEqual(self.release.calls, [])


class SafeguardTests(RetrievalHarness):
    def test_a_server_without_retrieval_and_a_changed_plan_send_nothing(self):
        hypothesis_id = self.frozen()
        self.at(AFTER)
        disabled = self.app_with(None)
        shown = self.plan([hypothesis_id], client=disabled)
        self.assertFalse(shown["retrieval"]["enabled"])
        refused = self.send(shown, client=disabled)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("--enable-market-retrieval", refused.json()["detail"])
        shown = self.plan([hypothesis_id])
        self.outcome_package()  # Local data changed after the preview: the approval no longer matches it.
        changed = self.send(shown)
        self.assertEqual(changed.status_code, 409)
        self.assertIn("changed since the preview", changed.json()["detail"])
        self.assertEqual(self.release.calls, [])

    def test_attempts_are_reserved_before_sending_and_failures_stay_visible(self):
        hypothesis_id = self.frozen()
        self.at(AFTER)
        shown = self.plan([hypothesis_id])
        started = market_store.started_path(self.market, shown["plan_sha256"], 1, market_store.LIFECYCLE_ATTEMPTS)
        seen = []
        self.release.before = lambda request: seen.append(started.is_file())
        self.release.script = [503]
        failed = self.send(shown)
        self.assertEqual(failed.status_code, 201, failed.text)
        self.assertEqual((failed.json()["outcome"], seen, len(self.release.calls)), ("refused_reply", [True], 1))
        state = self.client.get(f"/api/lifecycle/retrievals/{shown['plan_sha256']}/1").json()
        self.assertEqual((state["state"], state["outcome"]["http_status"]), ("finished", 503))
        repeated = self.send(shown, attempt=1)  # The same attempt is never sent twice.
        self.assertEqual(repeated.status_code, 409)
        self.assertEqual(len(self.release.calls), 1)
        self.release.script = [lambda request: httpx.Response(302, headers={
            "location": "https://example.com/elsewhere", "date": "Thu, 01 Oct 2026 13:00:00 GMT"})]
        redirected = self.send(self.plan([hypothesis_id]))
        self.assertEqual(redirected.json()["outcome"], "refused_reply")
        self.assertIn("redirects are not followed", redirected.json()["detail"])
        self.assertEqual(len(self.release.calls), 2)  # Not followed: no second request.
        self.clock.moment = AFTER + timedelta(minutes=5)
        saved = self.send(self.plan([hypothesis_id]))
        self.assertEqual((saved.json()["attempt"], saved.json()["outcome"]), (3, "saved"))
        self.assertEqual(len(self.release.calls), 3)
        # A start with no recorded outcome (a process that stopped mid-request) stays visible as uncertain.
        market_store.write_exclusive(market_store.started_path(self.market, "a" * 64, 1,
                                                               market_store.LIFECYCLE_ATTEMPTS), {
            "attempt_version": "lifecycle-retrieval-attempt-0.1", "plan_sha256": "a" * 64, "number": 1})
        uncertain = self.client.get(f"/api/lifecycle/retrievals/{'a' * 64}/1").json()
        self.assertEqual(uncertain["state"], "uncertain")
        self.assertEqual(self.client.get(f"/api/lifecycle/retrievals/{'a' * 64}/2").json()["state"], "not_started")
        # The market-context page keeps reading only its own attempts.
        self.assertEqual(market_store.read_attempts(self.market), [])

    def test_lifecycle_reads_and_actions_make_no_outside_connection(self):
        attempts = []
        original = socket.socket.connect

        def local_only(sock, address):
            if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
                attempts.append(address)
                raise AssertionError("an outside connection was attempted")
            return original(sock, address)
        with patch("socket.socket.connect", local_only), patch("socket.getaddrinfo",
                                                               side_effect=AssertionError("name lookup")):
            hypothesis_id, snapshot = self.ready()
            shown = self.assessment_preview(hypothesis_id, snapshot)
            recorded = self.assess(shown).json()
            for path in ("/api/lifecycle", f"/api/lifecycle/hypotheses/{hypothesis_id}/readiness",
                         f"/api/lifecycle/hypotheses/{hypothesis_id}/assessments/{recorded['evaluation_id']}",
                         f"/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{recorded['evaluation_id']}",
                         f"/api/lifecycle/assessment-actions/{shown['preview_sha256']}", "/api/lifecycle/draft-links"):
                self.assertEqual(self.client.get(path).status_code, 200, path)
            self.assertEqual(self.plan([hypothesis_id])["requests"], 0)
        self.assertEqual((attempts, self.release.calls), ([], []))


class ReleaseTimingTests(RetrievalHarness):
    """Outcome plans follow the Board's posting time (h15_release), the rule baselines use: a session that has ended
    is requested only once the Board's 4:15 p.m. New York release can state it. SYNTHETIC packages, pilot calendar."""

    def pilot_case(self, form: dict | None = None, baseline=FRESH, at=FREEZE_AT) -> str:
        self.at(baseline[1] + timedelta(minutes=5))
        snapshot = self.import_baseline(self.keep(*baseline))["snapshot"]["snapshot_id"]
        self.at(at)
        inputs = self.inputs(snapshot, form or pilot_form())
        shown = self.preview(inputs)
        self.assertTrue(shown["freezable"], shown["blockers"])
        response = self.approve(inputs, shown)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["hypothesis_id"]

    def test_the_last_target_waits_for_its_release_before_and_is_requested_after(self):
        case = self.pilot_case()  # Statement 9 December; the 5-observation target is Thursday 17 December.
        self.keep(date(2026, 12, 16), datetime(2026, 12, 17, 21, 30, tzinfo=UTC))  # Everything through the 16th.
        self.at(datetime(2026, 12, 18, 14, tzinfo=UTC))  # Friday 9 a.m. in New York: the 17th has ended, unposted.
        morning = self.plan([case])
        self.assertEqual((morning["requests"], morning["missing_sessions"]), (0, []))
        self.assertEqual(morning["awaiting_release"],
                         [{"session": "2026-12-17", "obtainable_from": "2026-12-18 16:15 New York time"}])
        self.assertEqual(morning["hypotheses"][0]["awaiting_release"], ["2026-12-17"])
        refused = self.send(morning)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("no earlier than 2026-12-18 16:15 New York time", refused.json()["detail"])
        self.at(datetime(2026, 12, 18, 21, 14, tzinfo=UTC))  # 4:14 p.m.: still before the release.
        self.assertEqual(self.plan([case])["requests"], 0)
        self.at(datetime(2026, 12, 18, 21, 15, tzinfo=UTC))  # 4:15 p.m.: the release can state the 17th.
        after = self.plan([case])
        self.assertEqual((after["requests"], after["missing_sessions"], after["awaiting_release"]),
                         (1, ["2026-12-17"], []))
        self.assertNotEqual(after["plan_sha256"], morning["plan_sha256"])
        sent = self.send(after)
        self.assertEqual((sent.status_code, sent.json()["outcome"]), (201, "saved"))
        self.assertEqual(len(self.release.calls), 1)  # The refused morning approval sent nothing.

    def test_a_friday_target_waits_over_the_weekend_until_monday_afternoon(self):
        legs = [{**leg, "horizon": 1} for leg in pilot_form()["legs"]]
        case = self.pilot_case(pilot_form(legs=legs))  # Scored from Thursday the 10th; target Friday 11 December.
        self.keep(date(2026, 12, 10), datetime(2026, 12, 11, 21, 30, tzinfo=UTC))
        for moment in (datetime(2026, 12, 12, 15, tzinfo=UTC), datetime(2026, 12, 13, 15, tzinfo=UTC),
                       datetime(2026, 12, 14, 14, tzinfo=UTC)):  # Saturday, Sunday, Monday 9 a.m.
            self.at(moment)
            shown = self.plan([case])
            self.assertEqual((shown["requests"], shown["awaiting_release"]),
                             (0, [{"session": "2026-12-11", "obtainable_from": "2026-12-14 16:15 New York time"}]))
        self.at(datetime(2026, 12, 14, 21, 20, tzinfo=UTC))  # Monday 4:20 p.m.
        self.assertEqual(self.plan([case])["missing_sessions"], ["2026-12-11"])

    def test_one_request_still_serves_a_case_with_posted_gaps_while_another_awaits_its_release(self):
        waiting = self.pilot_case()
        self.keep(date(2026, 12, 16), datetime(2026, 12, 17, 21, 30, tzinfo=UTC))  # Serves the first case only.
        # A second case bound to a baseline received later (stating only through the 8th): the package above was
        # received before it, so it serves none of this case's sessions, and the 9th to the 16th, all posted, are
        # missing.
        late = self.pilot_case(pilot_form(story_id="synthetic-rehearsal-late-case",
                                          headline="SYNTHETIC rehearsal: a late second case (not a real case)"),
                               baseline=(date(2026, 12, 8), datetime(2026, 12, 17, 21, 40, tzinfo=UTC)),
                               at=datetime(2026, 12, 17, 22, tzinfo=UTC))
        self.at(datetime(2026, 12, 18, 14, tzinfo=UTC))  # Friday 9 a.m.
        shown = self.plan([waiting, late])
        rows = {row["hypothesis_id"]: row for row in shown["hypotheses"]}
        self.assertEqual((rows[waiting]["missing_sessions"], rows[waiting]["awaiting_release"]), ([], ["2026-12-17"]))
        self.assertEqual(rows[late]["missing_sessions"][0], "2026-12-09")
        self.assertEqual(rows[late]["missing_sessions"][-1], "2026-12-16")
        self.assertEqual((shown["requests"], shown["request"]["missing_to"]), (1, "2026-12-16"))
        self.assertEqual([item["session"] for item in shown["awaiting_release"]], ["2026-12-17"])
        sent = self.send(shown)
        self.assertEqual((sent.status_code, sent.json()["outcome"]), (201, "saved"))

    def test_held_data_decide_even_before_the_release_time(self):
        case = self.pilot_case()
        # A package received at 8 a.m. on Friday that already states Thursday's value: what it states is used.
        package_id = self.keep(date(2026, 12, 17), datetime(2026, 12, 18, 13, tzinfo=UTC))
        self.at(datetime(2026, 12, 18, 13, 30, tzinfo=UTC))
        shown = self.plan([case])
        self.assertEqual((shown["requests"], shown["missing_sessions"], shown["awaiting_release"]), (0, [], []))
        self.assertEqual(shown["reuse"]["packages"][0]["package_id"], package_id)
        snapshot = self.import_outcome(case, package_id)["snapshot"]["snapshot_id"]
        self.assertEqual(self.readiness(case)["state"], "ready")
        self.assertTrue(self.assessment_preview(case, snapshot)["assessable"])


if __name__ == "__main__":
    unittest.main()
