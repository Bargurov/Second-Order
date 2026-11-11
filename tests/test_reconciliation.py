"""Corrective regressions for entitlements and reconciliation (SYNTHETIC stores, settable clocks, fake transports).

Each test reproduces a defect found on 5c8d315 by a targeted review, with controlled clocks, events and real locks
rather than timing: a quota-zone change creating allowance; an Admin resolution reported as saved when another one had
applied; a refund message derived from the absence of a send timestamp; a 15-minute age treated as proof that no worker
could still send; integrity failures reported as "sending disabled"; and long runs holding the request thread pool.
"""
from datetime import datetime
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

import anyio
import httpx
from fastapi.testclient import TestClient

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, PASSWORDS, USER_WRITE, World, source_form
from second_order import accounts as acc, attempt_locks, entitlements as ent, research_analysis as ra
from second_order.accounts import AccountsRefused
from second_order.analysis_flow import FlowRefused

ROOT = Path(__file__).resolve().parent.parent
SHA = "a" * 64
WAIT = 20  # Seconds an event wait may take before the test fails; never a sleep that decides an outcome.


class Base(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms(credits=40, limit=3)
        self.accounts, self.ids = self.world.accounts, self.world.ids
        self.user, self.admin_id = self.ids["reader-a"], self.ids["admin"]

    def client(self, username: str | None = None) -> TestClient:
        client = self.world.client(username)
        self.addCleanup(client.close)
        return client

    def refused(self, code: str, action) -> AccountsRefused:
        with self.assertRaises(AccountsRefused) as caught:
            action()
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        return caught.exception

    def quote(self, request_id: str, moment: datetime | None = None) -> dict:
        return ent.issue_quote(self.accounts, user_id=self.user, request_id=request_id, request_sha256=SHA,
                               effort="high", model=ra.MODEL, input_tokens_assumed=1_000, max_tokens=16_000,
                               planning_estimate_usd=0.1, moment=moment or self.world.clock())

    def reserve(self, quote: dict, moment: datetime | None = None) -> dict:
        return ent.reserve(self.accounts, user_id=self.user, quote_id=quote["quote_id"],
                           request_id=quote["request_id"], request_sha256=SHA, model=ra.MODEL, effort="high",
                           credits=quote["credits"], moment=moment or self.world.clock())[0]


# ---------------------------------------------------------------- defect 1: the quota time zone

class QuotaZone(Base):
    def test_a_zone_change_after_a_counted_run_is_refused_and_creates_no_allowance(self):
        """The reviewed reproduction: limit 1, one run under Asia/Jerusalem, then Pacific/Honolulu at the same
        instant used to read used 0 and allow a second run."""
        ent.set_daily_limit(self.accounts, self.user, 1, self.admin_id, "synthetic", self.world.clock())
        first, second = self.quote("r-1"), self.quote("r-2")
        self.reserve(first)
        error = self.refused("quota_timezone_fixed", lambda: acc.set_quota_timezone(
            self.accounts, "Pacific/Honolulu", self.admin_id, "synthetic"))
        self.assertIn("Asia/Jerusalem", str(error))
        snapshot = ent.user_snapshot(self.accounts, self.user, self.world.clock())["daily"]
        self.assertEqual((snapshot["timezone"], snapshot["used"], snapshot["remaining"]), ("Asia/Jerusalem", 1, 0))
        self.refused("daily_limit_reached", lambda: self.reserve(second))
        self.assertEqual(acc.settings_history(self.accounts), [])

    def test_the_zone_is_configured_freely_before_any_run_and_kept_afterwards(self):
        self.assertEqual(acc.set_quota_timezone(self.accounts, "Pacific/Honolulu", self.admin_id, "x"),
                         ("Pacific/Honolulu", True))
        self.assertEqual(acc.set_quota_timezone(self.accounts, "Asia/Jerusalem", self.admin_id, "back"),
                         ("Asia/Jerusalem", True))
        self.assertFalse(acc.timezone_fixed(self.accounts))
        self.reserve(self.quote("r-1"))
        self.assertTrue(acc.timezone_fixed(self.accounts))
        self.assertEqual(acc.set_quota_timezone(self.accounts, "Asia/Jerusalem", self.admin_id, "same"),
                         ("Asia/Jerusalem", False))  # The zone in force is accepted unchanged; nothing is recorded.
        for zone in ("Pacific/Honolulu", "UTC", "Pacific/Kiritimati"):  # Behind, equal-ish and ahead of Jerusalem.
            self.refused("quota_timezone_fixed", lambda zone=zone: acc.set_quota_timezone(
                self.accounts, zone, self.admin_id, "x"))
        self.assertEqual([row["value"] for row in acc.settings_history(self.accounts)],
                         ["Pacific/Honolulu", "Asia/Jerusalem"])

    def test_a_change_waiting_on_an_open_reservation_sees_it(self):
        """A reservation holds SQLite's write lock while it counts and inserts; a zone change in another thread
        waits for it and then refuses. The lock is held explicitly here, so the order is certain."""
        quote = self.quote("r-1")
        held = acc._connect(self.world.store_path)
        held.execute("BEGIN IMMEDIATE")
        held.execute("INSERT INTO attempts VALUES ('a-held', ?, 'r-1', ?, 'high', ?, '2026-10-14', "
                     "'Asia/Jerusalem', ?, 1)", (self.user, quote["quote_id"], quote["credits"],
                                                 self.world.clock().isoformat()))
        outcome: dict = {}
        started = threading.Event()

        def change():
            started.set()
            try:
                outcome["result"] = acc.set_quota_timezone(self.accounts, "Pacific/Honolulu", self.admin_id, "x")
            except AccountsRefused as exc:
                outcome["refused"] = exc.code
        worker = threading.Thread(target=change)
        worker.start()
        self.assertTrue(started.wait(WAIT))
        held.execute("COMMIT")
        held.close()
        worker.join(WAIT)
        self.assertEqual(outcome, {"refused": "quota_timezone_fixed"})

    def test_a_reservation_waiting_on_a_zone_change_counts_in_the_new_zone(self):
        quote = self.quote("r-1")
        held = acc._connect(self.world.store_path)
        held.execute("BEGIN IMMEDIATE")
        held.execute("INSERT INTO settings (name, value, set_at, set_by, reason) VALUES "
                     "('quota_timezone', 'Pacific/Honolulu', ?, ?, 'x')", (self.world.clock().isoformat(),
                                                                          self.admin_id))
        made: dict = {}
        worker = threading.Thread(target=lambda: made.setdefault("attempt", self.reserve(quote)))
        worker.start()
        held.execute("COMMIT")
        held.close()
        worker.join(WAIT)
        self.assertEqual((made["attempt"]["quota_timezone"], made["attempt"]["quota_day"]),
                         ("Pacific/Honolulu", "2026-10-13"))  # 09:00 UTC is 23:00 on the 13th in Honolulu.

    def test_the_fixed_zone_survives_a_restart(self):
        self.reserve(self.quote("r-1"))
        reopened = acc.Accounts.open(self.world.store_path)
        self.assertTrue(acc.timezone_fixed(reopened))
        self.refused("quota_timezone_fixed", lambda: acc.set_quota_timezone(reopened, "UTC", self.admin_id, "x"))

    def test_midnight_and_the_25_hour_dst_day_count_once_each_with_a_fixed_zone(self):
        ent.set_daily_limit(self.accounts, self.user, 1, self.admin_id, "synthetic", self.world.clock())
        moments = {"before midnight 24 Oct": "2026-10-24T20:59:59+00:00",
                   "after midnight 25 Oct": "2026-10-24T21:00:00+00:00",  # 00:00 IDT on the 25-hour day.
                   "late on 25 Oct": "2026-10-25T21:30:00+00:00",  # 23:30 IST: still the same local day.
                   "midnight 26 Oct": "2026-10-25T22:00:00+00:00"}
        outcomes = {}
        for number, (label, moment) in enumerate(moments.items()):
            at = datetime.fromisoformat(moment)
            try:
                made = self.reserve(self.quote(f"r-{number}", at), at)
                outcomes[label] = made["quota_day"]
            except AccountsRefused as exc:
                outcomes[label] = exc.code
        self.assertEqual(outcomes, {"before midnight 24 Oct": "2026-10-24", "after midnight 25 Oct": "2026-10-25",
                                    "late on 25 Oct": "daily_limit_reached", "midnight 26 Oct": "2026-10-26"})

    def test_the_admin_route_says_why_a_change_is_refused(self):
        self.reserve(self.quote("r-1"))
        admin = self.client("admin")
        reply = admin.post("/api/admin/settings", headers=ADMIN_WRITE,
                           json={"quota_timezone": "Pacific/Honolulu", "reason": "x"})
        self.assertEqual((reply.status_code, reply.json()["code"]), (409, "quota_timezone_fixed"))
        self.assertIn("Asia/Jerusalem", reply.json()["detail"])
        self.assertTrue(admin.get("/api/admin/settings").json()["fixed"])
        same = admin.post("/api/admin/settings", headers=ADMIN_WRITE,
                          json={"quota_timezone": "Asia/Jerusalem", "reason": "x"})
        self.assertEqual((same.status_code, same.json()["changed"]), (200, False))


# ---------------------------------------------------------------- the user flow over HTTP, with a fake transport

class Flow(Base):
    def setUp(self):
        super().setUp()
        self.user_client, self.admin_client = self.client("reader-a"), self.client("admin")

    def prepared(self, effort: str = "high") -> tuple[str, dict]:
        self.world.clock.advance(seconds=1)
        source = self.user_client.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()
        analysis = self.user_client.post("/api/user/analyses", headers=USER_WRITE, json={
            "source_id": source["source"]["source_id"], "effort": effort}).json()["analysis"]["analysis_id"]
        quote = self.user_client.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={})
        self.assertEqual(quote.status_code, 201, quote.text)
        return analysis, quote.json()["quote"]

    def approve(self, analysis: str, quote: dict, client: TestClient | None = None) -> httpx.Response:
        return (client or self.user_client).post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"], "approve": True})

    def analysis(self, analysis: str) -> dict:
        return self.user_client.get(f"/api/user/analyses/{analysis}").json()["analysis"]

    def account(self) -> dict:
        return self.user_client.get("/api/user/account").json()

    def hold(self, client: TestClient | None = None) -> dict:
        holds = (client or self.admin_client).get("/api/admin/holds").json()["holds"]
        self.assertEqual(len(holds), 1, holds)
        return holds[0]

    def resolve(self, hold: dict, resolution: str, credits: int = 0, client: TestClient | None = None,
                observed: dict | None = None) -> httpx.Response:
        return (client or self.admin_client).post(f"/api/admin/attempts/{hold['attempt_id']}/resolve",
                                                  headers=ADMIN_WRITE, json={
            "resolution": resolution, "credits_charged": credits, "reason": "synthetic decision",
            "observed": hold["observed"] if observed is None else observed})

    def running(self, analysis: str, quote: dict) -> tuple[threading.Thread, dict]:
        reply: dict = {}
        worker = threading.Thread(target=lambda: reply.setdefault("run", self.approve(analysis, quote)))
        worker.start()
        return worker, reply

    def resolutions(self) -> list:
        return [row for row in ent.ledger(self.accounts) if row["kind"] in ("release", "settle")]


class Resolution(Flow):
    """Defect 2: eligibility and application in one coordinated operation; nothing unapplied reported as saved."""

    def test_a_competing_resolution_is_refused_with_the_resolution_that_applied(self):
        analysis, quote = self.prepared()
        self.world.provider.error = httpx.ReadTimeout("synthetic timeout after the request left")
        self.assertEqual(self.approve(analysis, quote).json()["analysis"]["state"], "failed")
        tab_a, tab_b = self.client("admin"), self.client("admin")
        seen_a, seen_b = self.hold(tab_a), self.hold(tab_b)
        self.assertTrue(seen_a["resolvable"])
        self.assertEqual(self.resolve(seen_b, "charge", 2, tab_b).status_code, 201)
        late = self.resolve(seen_a, "return", 0, tab_a)
        self.assertEqual((late.status_code, late.json()["code"]), (409, "already_resolved"))
        self.assertEqual((late.json()["resolution"]["kind"], late.json()["resolution"]["credits_charged"]),
                         ("charged", 2))
        self.assertEqual(len(self.resolutions()), 1)
        self.assertEqual(self.analysis(analysis)["charge"]["credits_charged"], 2)

    def test_a_send_that_started_after_the_page_loaded_refuses_the_decision(self):
        quote = self.quote("r-1")
        made = self.reserve(quote)
        self.world.clock.advance(minutes=16)
        seen = self.hold()
        self.assertEqual((seen["observed"], seen["resolvable"]), ({"sent_at": None, "outcome": None}, True))
        self.assertTrue(ent.mark_sent(self.accounts, made["attempt_id"], self.world.clock()))  # Its send started.
        stale_decision = self.resolve(seen, "return")
        self.assertEqual((stale_decision.status_code, stale_decision.json()["code"]), (409, "state_changed"))
        self.assertIsNotNone(stale_decision.json()["current"]["sent_at"])
        self.assertEqual(self.resolutions(), [])
        self.world.clock.advance(minutes=16)
        self.assertEqual(self.resolve(self.hold(), "return").status_code, 201)  # Reloaded, decided knowingly.

    def test_settlement_after_the_page_loaded_wins_and_is_reported(self):
        analysis, quote = self.prepared()
        served = TestClient(self.world.app(), base_url=BASE, raise_server_exceptions=False)  # As a real server.
        self.addCleanup(served.close)
        served.cookies.set("second_order_session", self.user_client.cookies.get("second_order_session"))
        served.headers[ACCOUNT] = self.user_client.headers[ACCOUNT]
        with patch("second_order.user_research._settle", side_effect=RuntimeError("synthetic stop after recording")):
            self.assertEqual(self.approve(analysis, quote, served).status_code, 500)
        seen = self.hold()
        self.assertTrue(seen["resolvable"])  # Recorded on disk, never settled; no worker holds it.
        made = ent.attempt_record(self.accounts, request_id=analysis)
        ent.resolve(self.accounts, made["attempt_id"], "charged", quote["credits"], ent.SYSTEM, "late settlement",
                    self.world.clock())
        late = self.resolve(seen, "return")
        self.assertEqual((late.status_code, late.json()["code"], late.json()["resolution"]["kind"]),
                         (409, "already_resolved", "charged"))
        self.assertEqual(len(self.resolutions()), 1)

    def test_a_resolution_must_repeat_the_observed_state_and_never_exceed_the_quote(self):
        analysis, quote = self.prepared()
        self.world.provider.error = httpx.ReadTimeout("synthetic")
        self.approve(analysis, quote)
        seen = self.hold()
        missing = self.admin_client.post(f"/api/admin/attempts/{seen['attempt_id']}/resolve", headers=ADMIN_WRITE,
                                         json={"resolution": "return", "credits_charged": 0, "reason": "x"})
        self.assertEqual(missing.status_code, 422)
        self.assertEqual(self.resolve(seen, "charge", quote["credits"] + 1).status_code, 422)
        self.assertEqual(self.resolutions(), [])


class ExecutionGate(Flow):
    """Defect 3: only a free execution lock, never age alone, lets an administrator resolve an unfinished attempt."""

    def test_a_worker_paused_before_its_send_holds_the_attempt_beyond_fifteen_minutes(self):
        analysis, quote = self.prepared()
        paused, release = threading.Event(), threading.Event()
        real = ent.mark_sent

        def paused_mark(*args, **kwargs):
            paused.set()
            release.wait(WAIT)
            return real(*args, **kwargs)
        with patch("second_order.entitlements.mark_sent", side_effect=paused_mark):
            worker, reply = self.running(analysis, quote)
            self.assertTrue(paused.wait(WAIT))
            self.world.clock.advance(minutes=20)
            self.assertEqual(self.analysis(analysis)["state"], "running")
            seen = self.hold()
            self.assertEqual((seen["resolvable"], seen["worker_active"]), (False, True))
            refused = self.resolve(seen, "return")
            self.assertEqual((refused.status_code, refused.json()["code"]), (409, "in_flight"))
            release.set()
            worker.join(WAIT)
        self.assertEqual((reply["run"].status_code, reply["run"].json()["analysis"]["state"]), (201, "recorded"))
        self.assertEqual(len(self.world.provider.requests), 1)
        self.assertEqual(self.analysis(analysis)["charge"]["state"], "charged")

    def test_an_active_transport_beyond_fifteen_minutes_is_running_and_not_resolvable(self):
        analysis, quote = self.prepared()
        self.world.provider.gate = threading.Event()
        worker, reply = self.running(analysis, quote)
        self.assertTrue(self.world.provider.arrivals.acquire(timeout=WAIT))
        self.world.clock.advance(minutes=20)
        shown = self.analysis(analysis)
        self.assertEqual((shown["state"], shown["charge"]["state"]), ("running", "held"))
        seen = self.hold()
        self.assertFalse(seen["resolvable"])
        self.assertEqual(self.resolve(seen, "return").json()["code"], "in_flight")
        self.world.provider.gate.set()
        worker.join(WAIT)
        self.assertEqual(reply["run"].json()["analysis"]["charge"]["credits_charged"], quote["credits"])
        self.assertEqual(len(self.resolutions()), 1)

    def paused_before_the_lock(self):
        """Pause the worker after its reservation and before it takes the execution lock."""
        paused, release = threading.Event(), threading.Event()
        real = attempt_locks.hold

        def hold(folder, name, wait=0.0):
            if wait == attempt_locks.WORKER_WAIT:
                paused.set()
                release.wait(WAIT)
            return real(folder, name, wait)
        return paused, release, patch("second_order.attempt_locks.hold", side_effect=hold)

    def test_a_returned_attempt_never_dispatches(self):
        analysis, quote = self.prepared()
        paused, release, patcher = self.paused_before_the_lock()
        with patcher:
            worker, reply = self.running(analysis, quote)
            self.assertTrue(paused.wait(WAIT))
            self.world.clock.advance(minutes=16)
            seen = self.hold()
            self.assertEqual((seen["observed"]["sent_at"], seen["resolvable"]), (None, True))
            self.assertEqual(self.resolve(seen, "return").status_code, 201)
            release.set()
            worker.join(WAIT)
        self.assertEqual(self.world.provider.requests, [])
        run = reply["run"].json()
        self.assertEqual((reply["run"].status_code, run["code"]), (409, "already_attempted"))
        self.assertIn("An administrator returned all", run["detail"])
        shown = self.analysis(analysis)
        self.assertEqual((shown["state"], shown["charge"]["state"]), ("not_sent", "returned"))
        self.assertEqual(self.account()["credits"], {"available": 40, "held": 0})

    def charge_before_send(self, credits: int) -> tuple[dict, dict, dict]:
        analysis, quote = self.prepared()
        paused, release, patcher = self.paused_before_the_lock()
        with patcher:
            worker, reply = self.running(analysis, quote)
            self.assertTrue(paused.wait(WAIT))
            self.world.clock.advance(minutes=16)
            self.assertEqual(self.resolve(self.hold(), "charge", credits).status_code, 201)
            release.set()
            worker.join(WAIT)
        self.assertEqual(self.world.provider.requests, [])
        return reply["run"].json(), self.analysis(analysis), quote

    def test_a_charge_before_the_send_is_reported_as_charged_never_as_returned(self):
        run, shown, quote = self.charge_before_send(3)
        returned = quote["credits"] - 3
        for text in (run["detail"], shown["state_detail"]):
            self.assertIn(f"3 of the {quote['credits']} reserved credits were charged, and {returned} were returned",
                          text)
            self.assertNotIn("returned all", text)
            self.assertNotIn("stay reserved", text)
        self.assertEqual((shown["state"], shown["charge"]), ("unresolved", {
            "credits_reserved": quote["credits"], "credits_charged": 3, "credits_returned": returned,
            "state": "charged", "quota_day": "2026-10-14"}))
        account = self.account()
        self.assertEqual((account["credits"], account["daily"]["used"]), ({"available": 37, "held": 0}, 1))

    def test_a_zero_charge_keeps_the_day_and_returns_every_credit(self):
        run, shown, quote = self.charge_before_send(0)
        self.assertIn(f"0 of the {quote['credits']} reserved credits were charged", run["detail"])
        self.assertEqual((shown["charge"]["state"], shown["charge"]["credits_returned"]), ("charged", quote["credits"]))
        self.assertEqual(self.account()["daily"]["used"], 1)

    def test_a_stopped_worker_process_releases_the_attempt_for_reconciliation(self):
        made = self.reserve(self.quote("r-1"))
        ent.mark_sent(self.accounts, made["attempt_id"], self.world.clock())
        self.world.clock.advance(minutes=30)
        holder = subprocess.Popen(
            [sys.executable, "-c", "import sys\nfrom pathlib import Path\nfrom second_order import attempt_locks\n"
             "with attempt_locks.hold(Path(sys.argv[1]), sys.argv[2]):\n    print('held', flush=True)\n"
             "    sys.stdin.read()\n", str(self.accounts.lock_dir), made["attempt_id"]],
            cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            seen = self.hold()
            self.assertEqual((seen["resolvable"], seen["worker_active"]), (False, True))
            self.assertEqual(self.resolve(seen, "return").json()["code"], "in_flight")
        finally:
            holder.kill()
            holder.wait(WAIT)
            holder.stdin.close()  # The synthetic worker's pipes; closing them only releases this test's handles.
            holder.stdout.close()
        restarted = self.client("admin")  # A new server over the same store: nothing is held now.
        seen = self.hold(restarted)
        self.assertEqual((seen["resolvable"], seen["worker_active"]), (True, False))
        self.assertEqual(self.resolve(seen, "charge", made["credits"], restarted).status_code, 201)


class Refusals(Flow):
    """Defect 5: "sending disabled" only for the server's sending configuration; other failures say what they are."""

    def test_sending_disabled_is_only_the_sending_configuration(self):
        analysis, quote = self.prepared()
        self.world.sending = False
        no_sender = self.approve(analysis, quote, self.client("reader-a"))
        self.assertEqual((no_sender.status_code, no_sender.json()["code"]), (503, "sending_disabled"))
        self.world.sending = True
        from second_order.paid_drafts import PaidSender
        with patch.object(self.world, "sender", lambda: PaidSender(api_key=lambda: "",
                                                                   client_factory=self.world.provider.factory)):
            no_key = self.approve(analysis, quote, self.client("reader-a"))
        self.assertEqual((no_key.status_code, no_key.json()["code"]), (503, "sending_disabled"))
        self.assertEqual(ent.attempts(self.accounts), [])

    def test_request_integrity_failures_are_not_reported_as_sending_disabled(self):
        analysis, quote = self.prepared()
        cases = {"approved_for_account": (FlowRefused(409, "the saved request names another model"), 500,
                                          "internal_error"),
                 "credential_free": (FlowRefused(409, "the saved request would carry the credential"), 500,
                                     "internal_error")}
        for name, (error, status, code) in cases.items():
            with patch(f"second_order.research_analysis.{name}", side_effect=error):
                reply = self.approve(analysis, quote)
            self.assertEqual((reply.status_code, reply.json()["code"]), (status, code), name)
            self.assertNotIn("model", reply.json()["detail"])
            self.assertNotIn("credential", reply.json()["detail"])
        with patch("second_order.research_analysis.approved_for_account",
                   side_effect=FlowRefused(404, "Unknown research request ID")):
            missing = self.approve(analysis, quote)
        self.assertEqual((missing.status_code, missing.json()["code"]), (404, "not_found"))
        self.assertEqual((ent.attempts(self.accounts), self.world.provider.requests), ([], []))

    def test_an_existing_attempt_is_already_attempted_before_anything_is_reserved(self):
        analysis, quote = self.prepared()
        (self.world.folders.attempts / analysis).mkdir(parents=True)
        reply = self.approve(analysis, quote)
        self.assertEqual((reply.status_code, reply.json()["code"]), (409, "already_attempted"))
        self.assertEqual((ent.attempts(self.accounts), self.account()["credits"]), ([], {"available": 40, "held": 0}))


class Responsiveness(Base):
    """Defect 6: runs waiting on the provider must not hold the threads every other request needs."""

    def test_long_runs_do_not_block_session_account_or_admin_reads(self):
        user_token, user = acc.sign_in(self.accounts, "reader-a", PASSWORDS["reader-a"], self.world.clock())
        admin_token, admin = acc.sign_in(self.accounts, "admin", PASSWORDS["admin"], self.world.clock())
        as_user = {"Cookie": f"second_order_session={user_token}", ACCOUNT: user.user_id}
        as_admin = {"Cookie": f"second_order_session={admin_token}", ACCOUNT: admin.user_id}
        with TestClient(self.world.app(), base_url=BASE) as client:  # One event loop, as one served process.
            runs = []
            for _ in range(2):
                self.world.clock.advance(seconds=1)
                source = client.post("/api/user/sources", headers={**USER_WRITE, **as_user},
                                     json=source_form()).json()["source"]["source_id"]
                analysis = client.post("/api/user/analyses", headers={**USER_WRITE, **as_user}, json={
                    "source_id": source, "effort": "high"}).json()["analysis"]["analysis_id"]
                quote = client.post(f"/api/user/analyses/{analysis}/quotes", headers={**USER_WRITE, **as_user},
                                    json={}).json()["quote"]
                runs.append((analysis, quote))

            async def two_request_threads():
                anyio.to_thread.current_default_thread_limiter().total_tokens = 2
            client.portal.call(two_request_threads)
            self.world.provider.gate = threading.Event()
            workers = [threading.Thread(target=lambda analysis=analysis, quote=quote: client.post(
                f"/api/user/analyses/{analysis}/runs", headers={**USER_WRITE, **as_user}, json={
                    "quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"], "approve": True}))
                for analysis, quote in runs]
            for worker in workers:
                worker.start()
            try:
                for _ in workers:
                    self.assertTrue(self.world.provider.arrivals.acquire(timeout=WAIT))
                reads: dict = {}
                reader = threading.Thread(target=lambda: reads.update({
                    "session": client.get("/api/session", headers=as_user).status_code,
                    "account": client.get("/api/user/account", headers=as_user).status_code,
                    "admin": client.get("/api/admin/users", headers=as_admin).status_code}))
                reader.start()
                reader.join(WAIT)
                self.assertFalse(reader.is_alive(), "reads waited behind the running analyses")
                self.assertEqual(reads, {"session": 200, "account": 200, "admin": 200})
            finally:
                self.world.provider.gate.set()
                for worker in workers:
                    worker.join(WAIT)
        self.assertEqual(len(self.world.provider.requests), 2)


if __name__ == "__main__":
    unittest.main()
