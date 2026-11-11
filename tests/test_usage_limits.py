"""The usage limits (docs/news-usage-contract.md, sections 2 and 3) on the real application, with SYNTHETIC accounts,
SYNTHETIC limits, a settable clock and a simulated feed network; nothing reaches a network or a provider.

A missing policy refuses counted work; new sources and preparations count once per quota day and reset at the next
midnight; repeats, reopened analyses and refusals count nothing; concurrent requests at a limit never both pass;
storage is measured from the account's own sources, earlier ones included; the protective request rate and
concurrency limits answer 429 with a wait; the shared feed refresh needs a policy, waits its cooldown and stops at its
budget; counted use fixes the quota zone; the administrator publishes the policy once per intent and sees the use.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest import mock

from account_fakes import ADMIN_WRITE, USAGE_POLICY, USER_WRITE, World, every_file, source_form
from news_fakes import standard_feeds
from second_order import accounts as acc, analysis_flow, usage
from test_event_inbox import Network

INBOX_WRITE = {**ADMIN_WRITE, "X-Second-Order-Inbox": "1"}


def policy(**values) -> dict:
    account = {name: values.pop(name) for name in list(values) if name in usage.ACCOUNT_BOUNDS}
    return {"account": {**USAGE_POLICY["account"], **account}, "server": {**USAGE_POLICY["server"], **values}}


class Ticks:
    """A settable monotonic clock for the protective limits."""

    def __init__(self):
        self.value = 1000.0

    def __call__(self) -> float:
        return self.value


class Limits(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms()
        self.user = self.client("reader-a")

    def client(self, username: str | None = "reader-a", **options):
        client = self.world.client(username, **options)
        self.addCleanup(client.close)
        return client

    def limit(self, **values) -> None:
        usage.add_policy(self.world.accounts, policy(**values), self.world.ids["admin"], "SYNTHETIC limits",
                         self.world.clock())

    def add(self, client=None, text: str | None = None, headline: str = "Synthetic office publishes estimates"):
        self.world.clock.advance(seconds=1)  # Identical sources at one instant are one capture.
        form = source_form(headline=headline) | ({"source_text": text} if text is not None else {})
        return (client or self.user).post("/api/user/sources", headers=USER_WRITE, json=form)

    def used(self, operation: str, client=None) -> int:
        limits = (client or self.user).get("/api/user/limits").json()["limits"]
        return next(row["used"] for row in limits["operations"] if row["operation"] == operation)

    def rows(self, table: str) -> list[tuple]:
        connection = sqlite3.connect(self.world.store_path)
        try:
            return connection.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            connection.close()

    def stored_state(self) -> tuple:
        """The usage rows and every record file but the accounts store's own (SQLite may checkpoint it on a read)."""
        files = {name: data for name, data in every_file(self.root).items()
                 if not Path(name).name.startswith("accounts.db")}
        return self.rows("usage_events"), self.rows("usage_releases"), files

    # ---------------------------------------------------------------- counted writes

    def test_new_sources_count_once_per_day_and_reset_at_midnight(self):
        self.limit(sources_per_day=2)
        self.assertEqual([self.add().status_code for _ in range(2)], [201, 201])
        refused = self.add()
        self.assertEqual((refused.status_code, refused.json()["code"]), (409, "usage_limit_reached"))
        self.assertEqual({key: refused.json()["quota"][key] for key in ("operation", "limit", "used", "day")},
                         {"operation": "source", "limit": 2, "used": 2, "day": "2026-10-14"})
        self.assertEqual(refused.json()["quota"]["resets_at"], "2026-10-14T21:00:00+00:00")  # Midnight in Jerusalem.
        self.assertEqual(len(self.user.get("/api/user/sources").json()["sources"]), 2)
        invalid = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | {"headline": ""})
        self.assertEqual(invalid.json()["code"], "invalid_source")  # The form is checked before anything is counted.
        self.world.clock.advance(hours=12)  # Past midnight in Jerusalem: a new quota day.
        self.user = self.client("reader-a")
        self.assertEqual(self.add().status_code, 201)
        self.assertEqual(self.used("source"), 1)

    def test_refused_and_repeated_writes_count_nothing(self):
        self.limit(sources_per_day=5)
        self.assertEqual(self.user.post("/api/user/sources", headers=USER_WRITE,
                                        json=source_form() | {"headline": ""}).status_code, 422)
        self.assertEqual(self.used("source"), 0)
        form = source_form(headline="Synthetic identical source")
        first = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)
        same = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)  # The same instant: one capture.
        self.assertEqual((first.status_code, same.status_code, same.json()["code"], self.used("source")),
                         (201, 422, "invalid_source", 1))
        self.assertIn("nothing new was saved or counted", same.json()["detail"])
        source_id = first.json()["source"]["source_id"]
        prepared = self.user.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id,
                                                                                  "effort": "low"})
        self.assertEqual(prepared.status_code, 201)
        self.limit(preparations_per_day=1)
        reopened = self.user.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id,
                                                                                  "effort": "low"})
        self.assertEqual((reopened.status_code, self.used("preparation")), (200, 1))  # Reopening is free.
        another = self.user.post("/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id,
                                                                                 "effort": "medium"})
        self.assertEqual((another.status_code, another.json()["code"]), (409, "usage_limit_reached"))
        # The first source and the first preparation; the refused source and the repeated capture reserved nothing.
        self.assertEqual((len(self.rows("usage_events")), self.rows("usage_releases")), (2, []))

    def test_an_invalid_source_is_refused_before_anything_is_counted(self):
        # QA-7: every value the capture path refuses is checked before the source's count is reserved, so the refusal
        # leaves no usage event, release or file, under the day's limit and at it (docs/admin-user-contract.md, 9).
        self.limit(sources_per_day=1)
        invalid = {"a headline of 1,501 characters": {"headline": "h" * 1_501},
                   "a headline on two lines": {"headline": "Line one\nline two"},
                   "an address that is not http(s)": {"source_url": "ftp://example.org/synthetic"},
                   "a publication time without an offset": {"published_at": "2026-10-13T10:00:00"},
                   "a publication time in the future": {"published_at": "2026-10-15T10:00:00+03:00"},
                   "a text of 50,001 characters": {"source_text": "x" * 50_001},
                   "a framing tag in the text": {"source_text": "The release quotes <source_text> as printed."},
                   "a field that is not text": {"headline": 7}}
        for when in ("under the limit", "at the limit"):
            for label, changes in invalid.items():
                with self.subTest(when, case=label):
                    self.world.clock.advance(seconds=1)
                    before = self.stored_state()
                    reply = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form() | changes)
                    self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_source"), reply.text)
                    self.assertEqual(self.stored_state(), before)
            if when == "under the limit":
                self.assertEqual(self.add().status_code, 201)  # The day's one new source.
        self.assertEqual((self.used("source"), self.rows("usage_releases")), (1, []))

    def test_a_source_the_operator_writes_after_its_checks_is_refused_and_counts_nothing(self):
        # The operator's form writes the identical capture (same request, same instant) after this request's checks and
        # before its own write, so only the write finds it. That refusal still leaves no usage row, owner row or file
        # of this request (docs/admin-user-contract.md, 9), and the source sent again later counts once.
        self.limit(sources_per_day=2)
        self.world.clock.advance(seconds=1)
        form = source_form(headline="Synthetic source the operator saves first")
        original = analysis_flow.save

        def operator_first(root, capture_id, files):
            with mock.patch.object(analysis_flow, "save", original):
                analysis_flow.capture_from_payload(dict(form), root, self.world.clock)
            return original(root, capture_id, files)
        before, owners = self.stored_state(), self.rows("record_owners")
        with mock.patch.object(analysis_flow, "save", operator_first):
            reply = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)
        self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_source"), reply.text)
        events, releases, files = self.stored_state()
        self.assertEqual((events, releases, self.rows("record_owners")), (before[0], before[1], owners))
        self.assertNotIn("already in your sources", reply.json()["detail"])  # It is the operator's capture.
        added = {Path(name).parts[:2] for name in set(files) - set(before[2])}
        self.assertEqual(len(added), 1, added)  # Only the operator's capture.
        ((folder, capture_id),) = added
        self.assertEqual(folder, "intake")
        self.assertEqual(self.user.get(f"/api/user/sources/{capture_id}").status_code, 404)
        self.world.clock.advance(seconds=1)
        self.assertEqual(self.user.post("/api/user/sources", headers=USER_WRITE, json=form).status_code, 201)
        self.assertEqual((self.used("source"), self.rows("usage_releases")), (1, []))

    def test_a_source_another_account_writes_after_its_checks_is_refused_and_counts_nothing(self):
        # reader-b's request passes its checks; reader-a then saves the identical source (same request, same instant:
        # the same capture), so only reader-b's write finds it. reader-b's refusal leaves it no row or file.
        self.limit(sources_per_day=2)
        other, b = self.client("reader-b"), self.world.ids["reader-b"]
        self.world.clock.advance(seconds=1)
        form = source_form(headline="Synthetic source two accounts send at one instant")
        checked, go = threading.Event(), threading.Event()
        original = usage.stored

        def pause_after_checks(accounts, intake, user_id):  # Called after the plan, before the count.
            if user_id == b and not checked.is_set():
                checked.set()
                go.wait(30)
            return original(accounts, intake, user_id)
        with mock.patch.object(usage, "stored", pause_after_checks), ThreadPoolExecutor(1) as pool:
            theirs = pool.submit(other.post, "/api/user/sources", headers=USER_WRITE, json=form)
            self.assertTrue(checked.wait(30))
            mine = self.user.post("/api/user/sources", headers=USER_WRITE, json=form)
            go.set()
            refused = theirs.result(60)
        self.assertEqual(mine.status_code, 201, mine.text)
        self.assertEqual((refused.status_code, refused.json()["code"]), (422, "invalid_source"), refused.text)
        capture_id = mine.json()["source"]["source_id"]
        self.assertEqual(([row[2] for row in self.rows("usage_events")], self.rows("usage_releases")),
                         ([self.world.ids["reader-a"]], []))
        self.assertNotIn("already in your sources", refused.json()["detail"])  # It is reader-a's.
        self.assertEqual(acc.owner_of(self.world.accounts, "capture", capture_id), self.world.ids["reader-a"])
        self.assertEqual((other.get("/api/user/sources").json()["sources"],
                          other.get(f"/api/user/sources/{capture_id}").status_code), ([], 404))
        self.world.clock.advance(seconds=1)
        self.assertEqual(other.post("/api/user/sources", headers=USER_WRITE, json=form).status_code, 201)
        self.assertEqual((self.used("source", other), self.used("source"), self.rows("usage_releases")), (1, 1, []))

    def test_concurrent_writes_at_the_limit_never_both_pass(self):
        self.limit(sources_per_day=3)
        self.assertEqual(self.add().status_code, 201)
        start = threading.Barrier(6)

        def submit(number: int) -> int:
            start.wait(10)
            return self.add(headline=f"Synthetic concurrent source {number}").status_code
        with ThreadPoolExecutor(6) as pool:
            statuses = sorted(pool.map(submit, range(6)))
        self.assertEqual(statuses, [201, 201, 409, 409, 409, 409])
        self.assertEqual(len(self.user.get("/api/user/sources").json()["sources"]), 3)
        self.assertEqual(self.used("source"), 3)

    def test_storage_counts_every_source_the_account_holds(self):
        self.assertEqual(self.add(text="Synthetic text. " * 30).status_code, 201)  # Before the tighter policy.
        held = usage.stored(self.world.accounts, self.root / "intake", self.world.ids["reader-a"])
        self.assertEqual(held["sources"], 1)
        self.limit(max_sources=1)
        count = self.add()
        self.assertEqual((count.status_code, count.json()["code"], count.json()["storage"]["measure"]),
                         (409, "storage_limit_reached", "sources"))
        self.limit(max_sources=10, max_source_bytes=held["source_bytes"] + 100)
        big = self.add(text="Synthetic longer text. " * 20)
        self.assertEqual((big.status_code, big.json()["storage"]),
                         (409, {"measure": "source_bytes", "limit": held["source_bytes"] + 100,
                                "used": held["source_bytes"], "adding": len(("Synthetic longer text. " * 20).encode())}))
        self.assertEqual(self.add(text="Short synthetic text that is long enough to be accepted here.").status_code,
                         201)
        self.assertEqual(self.client("reader-b").post("/api/user/sources", headers=USER_WRITE,
                                                      json=source_form()).status_code, 201)  # Per account.

    # ---------------------------------------------------------------- protective limits

    def test_the_request_rate_is_limited_per_account_with_a_wait(self):
        self.limit(requests_per_minute=5)
        ticks = Ticks()
        user, other = self.client("reader-a", request_ticks=ticks), self.client("reader-b", request_ticks=ticks)
        self.assertEqual([user.get("/api/user/account").status_code for _ in range(5)], [200] * 5)
        refused = user.get("/api/user/account")
        self.assertEqual((refused.status_code, refused.json()["code"]), (429, "rate_limited"))
        self.assertEqual(refused.json()["retry_after_seconds"], 60)  # The oldest of the five leaves the window.
        self.assertEqual(other.get("/api/user/account").status_code, 200)  # Another account has its own.
        self.assertEqual(user.get("/api/session").status_code, 200)  # The session read is not a user route.
        ticks.value += 61
        self.assertEqual(user.get("/api/user/account").status_code, 200)

    def test_requests_in_progress_are_limited_per_account(self):
        self.limit(concurrent_requests=1)
        source_id = self.add().json()["source"]["source_id"]
        analysis = self.user.post("/api/user/analyses", headers=USER_WRITE,
                                  json={"source_id": source_id, "effort": "low"}).json()["analysis"]["analysis_id"]
        quote = self.user.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        self.world.provider.gate = threading.Event()
        with ThreadPoolExecutor(1) as pool:
            run = pool.submit(self.user.post, f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json={
                "quote_id": quote["quote_id"], "effort": "low", "credits": quote["credits"], "approve": True})
            self.assertTrue(self.world.provider.entered.wait(10))
            busy = self.user.get("/api/user/account")
            self.assertEqual((busy.status_code, busy.json()["code"]), (429, "too_many_requests"))
            self.world.provider.gate.set()
            self.assertEqual(run.result(20).status_code, 201)
        self.assertEqual(self.user.get("/api/user/account").status_code, 200)

    # ---------------------------------------------------------------- the shared refresh

    def test_the_shared_feed_refresh_needs_a_policy_waits_its_cooldown_and_stops_at_its_budget(self):
        network = Network({url: answers * 4 for url, answers in standard_feeds().items()})
        world = World(self.root / "refresh")
        admin = world.client("admin", feeds=network.fetcher(contact=None))
        self.addCleanup(admin.close)
        refresh = lambda: admin.post("/api/inbox/refresh", headers=INBOX_WRITE, json={})  # noqa: E731
        none = refresh()
        self.assertEqual(none.status_code, 409)
        self.assertIn("No usage policy", none.json()["detail"])
        self.assertEqual(network.requests, [])
        usage.add_policy(world.accounts, policy(refreshes_per_day=2, refresh_cooldown_seconds=600),
                         world.ids["admin"], "SYNTHETIC")
        self.assertEqual(refresh().status_code, 200)
        requested = len(network.requests)
        self.assertGreater(requested, 0)
        early = refresh()
        self.assertEqual(early.status_code, 409)
        self.assertIn("allowed in 600 seconds", early.json()["detail"])
        world.clock.advance(seconds=601)
        self.assertEqual(refresh().status_code, 200)
        world.clock.advance(seconds=601)
        spent = refresh()
        self.assertEqual(spent.status_code, 409)
        self.assertIn("Today's 2 feed refreshes are used", spent.json()["detail"])
        self.assertEqual(len(network.requests), 2 * requested)  # Refusals requested nothing.

    # ---------------------------------------------------------------- the quota zone and the administrator

    def test_counted_use_fixes_the_quota_zone(self):
        admin = self.client("admin")
        self.assertEqual(self.add().status_code, 201)
        moved = admin.post("/api/admin/settings", headers=ADMIN_WRITE,
                           json={"quota_timezone": "Europe/London", "reason": "SYNTHETIC"})
        self.assertEqual((moved.status_code, moved.json()["code"]), (409, "quota_timezone_fixed"))

    def test_the_administrator_publishes_the_policy_once_per_intent_and_sees_the_use(self):
        world = World(self.root / "admin")
        admin = world.client("admin")
        self.addCleanup(admin.close)
        empty = admin.get("/api/admin/usage-policy").json()
        self.assertEqual((empty["current"], empty["bounds"]["account"]["concurrent_requests"]),
                         (None, {"min": 1, "max": 64}))
        publish = lambda key, body=USAGE_POLICY: admin.post("/api/admin/usage-policy", headers=ADMIN_WRITE, json={  # noqa: E731
            "policy": body, "reason": "SYNTHETIC limits", "idempotency_key": key})
        first = publish("usage-intent-0001")
        self.assertEqual((first.status_code, first.json()["created"]), (201, True))
        self.assertEqual((publish("usage-intent-0001").status_code, len(usage.policies(world.accounts))), (200, 1))
        self.assertEqual(publish("usage-intent-0001", policy(searches_per_day=1)).json()["code"], "idempotency_conflict")
        for bad in (policy(concurrent_requests=0), {"account": USAGE_POLICY["account"]},
                    policy(searches_per_day=True), policy(max_sources=100_001)):
            self.assertEqual(publish("usage-intent-0002", bad).status_code, 422, bad)
        self.assertEqual(len(usage.policies(world.accounts)), 1)
        with world.client("reader-a") as user:
            user.post("/api/user/sources", headers=USER_WRITE, json=source_form())
        seen = admin.get("/api/admin/usage").json()
        reader = next(row for row in seen["accounts"] if row["user_id"] == world.ids["reader-a"])
        self.assertEqual(next(row["used"] for row in reader["operations"] if row["operation"] == "source"), 1)
        self.assertEqual(reader["storage"]["sources"]["used"], 1)
        with world.client("reader-a") as user:
            self.assertEqual(user.get("/api/admin/usage").status_code, 403)

    def test_usage_rows_are_append_only(self):
        self.assertEqual(self.add().status_code, 201)
        connection = sqlite3.connect(self.world.store_path)
        self.addCleanup(connection.close)
        for statement in ("DELETE FROM usage_events", "UPDATE usage_events SET quota_day = '2000-01-01'",
                          "DELETE FROM usage_policies"):
            with self.assertRaises(sqlite3.DatabaseError):
                connection.execute(statement)


if __name__ == "__main__":
    unittest.main()
