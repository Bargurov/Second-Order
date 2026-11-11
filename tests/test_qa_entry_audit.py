"""QA audit of the entry release (37caa69): refusals, reads, races and the QA findings, over HTTP.

SYNTHETIC accounts, credit and usage policies and provider only (see account_fakes): temporary stores, the fake
transport, no network and no real key. Written by the QA chat for the next integration; the product tests keep their
owners. Since the account binding (docs/account-binding-contract.md), every signed-in client names its account, as a
page opened for it does, and so does each further tab of the same browser.

- Every refused write (user, public, sign-in and administrator routes), and every repeat the server answers as a
  duplicate, leaves the accounts store's rows and every record file exactly as they were and sends nothing
  (docs/admin-user-contract.md section 9: a refusal below 500 reserved, sent and wrote nothing).
- Every read route writes nothing, with an attempt held, running or unresolved.
- Two quotes of one analysis approved at once reserve and send once; two tabs saving on one review version keep one.
- The QA findings, with their original assertions. QA-1 and QA-3 were expected failures on 37caa69; on Admin's
  fee19a8 they pass as written, so their markers were removed. QA-4 and QA-5 were reported from manual reproductions
  and are tested here since their repair.

An attempt's execution lock file (accounts/attempt-locks/*.lock) is empty and records nothing (attempt_locks); an
administrator's refused resolution creates one by taking the lock, so record files are compared without empty lock
files, and the read check asserts that reads create none.
"""
from concurrent.futures import ThreadPoolExecutor
import difflib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, POLICY, SESSION_WRITE, USAGE_POLICY, USER_WRITE, World, \
    bind_to, every_file, source_form
from second_order import accounts as acc, entitlements as ent, research_analysis as ra, user_research

PASSWORDS = {"reader-c": "synthetic-reader-c-qa", "reader-d": "synthetic-reader-d-qa"}
REGISTRANT = {"username": "reader-p", "display_name": "Reader P (synthetic)", "password": "synthetic-reader-p-qa",
              "note": "SYNTHETIC registration for the QA audit."}
LOCKS = "attempt-locks"


def records(world: World) -> dict:
    """The accounts store's rows, read logically (SQLite may checkpoint its files on any connection), and every other
    file under the world's folder except empty execution-lock files."""
    with world.accounts.reading() as connection:
        rows = list(connection.iterdump())
    files = {name: data for name, data in every_file(world.root).items()
             if not Path(name).name.startswith("accounts.db") and not (LOCKS in Path(name).parts and data == b"")}
    return {"rows": rows, "files": files}


def lock_files(world: World) -> list[str]:
    folder = world.accounts.lock_dir
    return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class QABase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms(credits=40, limit=3)
        self.admin_id = self.world.ids["admin"]
        self.user = self.client("reader-a")
        self.other = self.client("reader-b")
        self.admin = self.client("admin")
        self.visitor = self.client()

    def client(self, username: str | None = None) -> TestClient:
        if username in PASSWORDS:
            client = TestClient(self.world.app(), base_url=BASE)
            reply = client.post("/api/session/login", headers=SESSION_WRITE,
                                json={"username": username, "password": PASSWORDS[username]})
            self.assertEqual(reply.status_code, 200, reply.text)
            bind_to(client, reply)
        else:
            client = self.world.client(username)
        self.addCleanup(client.close)
        return client

    def tab(self, client: TestClient) -> TestClient:
        """Another tab of the same browser, opened for the same account: its own connection, the same session cookie
        and the same account binding."""
        other = TestClient(self.world.app(), base_url=BASE)
        self.addCleanup(other.close)
        other.cookies.set("second_order_session", client.cookies.get("second_order_session"))
        if ACCOUNT in client.headers:
            other.headers[ACCOUNT] = client.headers[ACCOUNT]
        return other

    def account(self, username: str, credits: int | None, limit: int | None) -> None:
        """A further synthetic user with the given grant and daily limit (None: none recorded)."""
        user_id = acc.create_user(self.world.accounts, username, f"{username} (synthetic)", "user",
                                  PASSWORDS[username], "qa-setup", self.world.clock())["user_id"]
        self.world.ids[username] = user_id
        if credits is not None:
            ent.add_credits(self.world.accounts, user_id, "grant", credits, self.admin_id, "SYNTHETIC grant",
                            f"qa-grant-{username}", self.world.clock())
        if limit is not None:
            ent.set_daily_limit(self.world.accounts, user_id, limit, self.admin_id, "SYNTHETIC limit",
                                self.world.clock())

    def source(self, client: TestClient, **form) -> str:
        self.world.clock.advance(seconds=1)  # Two identical sources at one instant would be one capture.
        reply = client.post("/api/user/sources", headers=USER_WRITE, json=source_form(**form))
        self.assertEqual(reply.status_code, 201, reply.text)
        return reply.json()["source"]["source_id"]

    def prepared(self, client: TestClient, effort: str = "high") -> str:
        reply = client.post("/api/user/analyses", headers=USER_WRITE,
                            json={"source_id": self.source(client), "effort": effort})
        self.assertIn(reply.status_code, (200, 201), reply.text)
        return reply.json()["analysis"]["analysis_id"]

    def quote(self, client: TestClient, analysis_id: str) -> dict:
        reply = client.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={})
        self.assertEqual(reply.status_code, 201, reply.text)
        return reply.json()["quote"]

    def approval(self, quote: dict, **changes) -> dict:
        return {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                "approve": True} | changes

    def run_analysis(self, client: TestClient, analysis_id: str, quote: dict, **changes):
        return client.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE,
                           json=self.approval(quote, **changes))

    def recorded(self, client: TestClient | None = None) -> dict:
        client = client or self.user
        analysis_id = self.prepared(client)
        reply = self.run_analysis(client, analysis_id, self.quote(client, analysis_id))
        self.assertEqual(reply.status_code, 201, reply.text)
        self.assertEqual(reply.json()["analysis"]["state"], "recorded")
        return reply.json()["analysis"]

    def review(self, client: TestClient, analysis_id: str, **form):
        return client.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json=form)

    def held_attempt(self) -> tuple[str, dict]:
        """An analysis of reader-a with a reservation and no send: an attempt in flight, as just after a run reserved."""
        analysis_id = self.prepared(self.user, "low")
        quote = self.quote(self.user, analysis_id)
        stored = ent.latest_quote(self.world.accounts, self.world.ids["reader-a"], analysis_id, self.world.clock(),
                                  ra.MODEL)
        attempt, _ = ent.reserve(self.world.accounts, user_id=self.world.ids["reader-a"], quote_id=quote["quote_id"],
                                 request_id=analysis_id, request_sha256=stored["request_sha256"], model=ra.MODEL,
                                 effort=quote["effort"], credits=quote["credits"], moment=self.world.clock())
        return analysis_id, attempt

    def registrant(self) -> str:
        reply = self.visitor.post("/api/public/registrations", headers=SESSION_WRITE, json=REGISTRANT)
        self.assertEqual(reply.status_code, 201, reply.text)
        return next(user["user_id"] for user in acc.list_users(self.world.accounts)
                    if user["username"] == REGISTRANT["username"])

    def assert_unchanged(self, label: str, send, status: int, code: str | None) -> dict:
        """Send one request; it must answer status (and code), in its contract's shape, and change no record."""
        before, sent = records(self.world), len(self.world.provider.requests)
        reply = send()
        body = reply.json()
        self.assertEqual((reply.status_code, body.get("code") if code else None), (status, code),
                         f"{label}: {reply.text[:300]}")
        self.assertIn("contract", body, label)
        after = records(self.world)
        if after != before:
            changed = sorted(set(after["files"]) ^ set(before["files"]) |
                             {name for name in before["files"] if after["files"].get(name) != before["files"][name]})
            rows = list(difflib.unified_diff(before["rows"], after["rows"], lineterm="", n=0))[2:]
            self.fail(f"{label} changed records: files {changed}, rows {rows[:6]}")
        self.assertEqual(len(self.world.provider.requests), sent, f"{label} reached the provider")
        return body


class RefusalsWriteNothing(QABase):
    def test_refused_source_forms_write_nothing(self):
        post = lambda body=None, headers=USER_WRITE, **form: lambda: self.user.post(  # noqa: E731
            "/api/user/sources", headers=headers, **({"content": body} if body is not None else
                                                     {"json": source_form() | form}))
        base = source_form()
        cases = {
            "an extra field": (post(owner_id=self.world.ids["reader-b"]), 422, "invalid_source"),
            "a missing field": (lambda: self.user.post("/api/user/sources", headers=USER_WRITE, json={
                key: base[key] for key in ("headline", "source_url", "published_at")}), 422, "invalid_source"),
            "a headline of 1,501 characters": (post(headline="h" * 1_501), 422, "invalid_source"),
            "a headline on two lines": (post(headline="Line one\nline two"), 422, "invalid_source"),
            "an empty headline": (post(headline=""), 422, "invalid_source"),
            "an address that is not http(s)": (post(source_url="ftp://example.org/synthetic"), 422,
                                               "invalid_source"),
            "an address of 2,084 characters": (post(source_url="https://example.org/" + "a" * 2_064), 422,
                                               "invalid_source"),
            "a publication time without an offset": (post(published_at="2026-10-13T10:00:00"), 422,
                                                     "invalid_source"),
            "a text of 50,001 characters": (post(source_text="x" * 50_001), 422, "invalid_source"),
            "an empty text": (post(source_text=""), 422, "invalid_source"),
            "an unpaired surrogate escape": (post(body=json.dumps(base).replace(
                "SYNTHETIC TEST SOURCE", "SYNTHETIC \\ud800 TEST SOURCE").encode()), 422, "invalid_source"),
            "a body that is not JSON": (post(body=b"headline=x"), 422, "invalid_source"),
            "a body over 270,000 bytes": (post(body=b" " * 270_001), 413, "payload_too_large"),
            "no action header": (post(headers={k: v for k, v in USER_WRITE.items() if k != "X-Second-Order-User"}),
                                 403, "forbidden"),
            "another site's Origin": (post(headers=USER_WRITE | {"Origin": "http://evil.example"}), 403,
                                      "forbidden"),
            "a form body": (post(headers=USER_WRITE | {"Content-Type": "text/plain"}), 415, "invalid_request"),
            "an administrator's session": (lambda: self.admin.post("/api/user/sources", headers=USER_WRITE,
                                                                   json=base), 403, "forbidden"),
            "no session": (lambda: self.visitor.post("/api/user/sources", headers=USER_WRITE, json=base), 401,
                           "not_signed_in"),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                self.assert_unchanged(label, send, status, code)

    def test_refused_preparations_and_quotes_write_nothing(self):
        mine, theirs = self.source(self.user), self.source(self.other)
        theirs_analysis = self.prepared(self.other)
        held, _ = self.held_attempt()
        prepare = lambda client=self.user, **body: lambda: client.post(  # noqa: E731
            "/api/user/analyses", headers=USER_WRITE, json=body)
        quote = lambda analysis_id, body=None: lambda: self.user.post(  # noqa: E731
            f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={} if body is None else body)
        cases = {
            "another account's source": (prepare(source_id=theirs, effort="high"), 404, "not_found"),
            "an unknown source": (prepare(source_id="20261014T090000000000Z-000000000000", effort="high"), 404,
                                  "not_found"),
            "an Effort the policy does not offer": (prepare(source_id=mine, effort="xhigh"), 409,
                                                    "unsupported_effort"),
            "an unknown Effort": (prepare(source_id=mine, effort="extreme"), 409, "unsupported_effort"),
            "an extra field": (prepare(source_id=mine, effort="high", user_id=self.world.ids["reader-b"]), 422,
                               "invalid_request"),
            "a quote body that is not empty": (quote(held, {"credits": 1}), 422, "invalid_request"),
            "a quote of another account's analysis": (quote(theirs_analysis), 404, "not_found"),
            "a quote of an attempted analysis": (quote(held), 409, "already_attempted"),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                self.assert_unchanged(label, send, status, code)

    def test_refused_approvals_reserve_send_and_write_nothing(self):
        self.account("reader-c", credits=1, limit=3)
        self.account("reader-d", credits=40, limit=None)
        ent.set_daily_limit(self.world.accounts, self.world.ids["reader-b"], 0, self.admin_id, "SYNTHETIC limit 0",
                            self.world.clock())
        poor, unlimited = self.client("reader-c"), self.client("reader-d")
        analysis_id = self.prepared(self.user)
        quote = self.quote(self.user, analysis_id)
        other_analysis = self.prepared(self.user, "low")
        other_quote = self.quote(self.user, other_analysis)
        quoted = {}
        for name, client in (("reader-b", self.other), ("reader-c", poor), ("reader-d", unlimited)):
            prepared = self.prepared(client)
            quoted[name] = (prepared, self.quote(client, prepared))
        run = lambda client, analysis, body: lambda: client.post(  # noqa: E731
            f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json=body)
        theirs_analysis, theirs_quote = quoted["reader-b"]
        poor_analysis, poor_quote = quoted["reader-c"]
        unlimited_analysis, unlimited_quote = quoted["reader-d"]
        cases = {
            "approve false": (run(self.user, analysis_id, self.approval(quote, approve=False)), 422,
                              "invalid_request"),
            "credits that are not the quote's": (run(self.user, analysis_id, self.approval(
                quote, credits=quote["credits"] - 1)), 409, "quote_mismatch"),
            "an Effort that is not the quote's": (run(self.user, analysis_id, self.approval(quote, effort="low")),
                                                  409, "quote_mismatch"),
            "another analysis's quote": (run(self.user, analysis_id, self.approval(other_quote)), 409,
                                         "quote_mismatch"),
            "another account's quote on one's own analysis": (run(self.user, analysis_id, self.approval(
                theirs_quote)), 409, "quote_mismatch"),
            "another account's analysis": (run(self.user, theirs_analysis, self.approval(theirs_quote)), 404,
                                           "not_found"),
            "credits as text": (run(self.user, analysis_id, self.approval(quote, credits=str(quote["credits"]))),
                                422, "invalid_request"),
            "an extra field": (run(self.user, analysis_id, self.approval(quote, user_id="u-0")), 422,
                               "invalid_request"),
            "a daily limit of 0": (run(self.other, theirs_analysis, self.approval(theirs_quote)), 409,
                                   "daily_limit_reached"),
            "fewer credits than the quote": (run(poor, poor_analysis, self.approval(poor_quote)), 409,
                                             "insufficient_credits"),
            "no daily limit": (run(unlimited, unlimited_analysis, self.approval(unlimited_quote)), 409,
                               "no_daily_limit"),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                self.assert_unchanged(label, send, status, code)
        ent.add_policy(self.world.accounts, POLICY, self.admin_id, "SYNTHETIC republished", self.world.clock())
        self.assert_unchanged("a quote under the previous policy version", run(
            self.user, analysis_id, self.approval(quote)), 409, "quote_superseded")
        fresh = self.quote(self.user, analysis_id)
        self.world.clock.advance(seconds=POLICY["quote_valid_seconds"] + 1)
        self.assert_unchanged("an expired quote", run(self.user, analysis_id, self.approval(fresh)), 409,
                              "quote_expired")

    def test_refused_reviews_write_nothing(self):
        prepared = self.prepared(self.user)
        analysis = self.recorded()
        analysis_id, sha = analysis["analysis_id"], analysis["result_sha256"]
        first = self.review(self.user, analysis_id, parent_review_id=None, result_sha256=sha, status="needs_revision",
                            notes="Synthetic first version.")
        self.assertEqual(first.status_code, 201, first.text)
        parent = first.json()["review"]["review_id"]
        review = lambda client=self.user, target=analysis_id, **form: lambda: self.review(  # noqa: E731
            client, target, **({"parent_review_id": parent, "result_sha256": sha, "status": "human_reviewed",
                                "notes": "Synthetic second version."} | form))
        cases = {
            "an analysis without a result": (review(target=prepared, parent_review_id=None), 409, "no_result"),
            "another result": (review(result_sha256="f" * 64), 409, "result_changed"),
            "a version that is not the latest": (review(parent_review_id=None), 409, "review_conflict"),
            "nothing changed": (review(status="needs_revision", notes="Synthetic first version."), 422,
                                "invalid_review"),
            "a form feed in the notes": (review(notes="Copied from a PDF\x0cpage two"), 422, "invalid_review"),
            "notes of 20,001 characters": (review(notes="n" * 20_001), 422, "invalid_review"),
            "a malformed parent": (review(parent_review_id="v1"), 422, "invalid_review"),
            "an unknown status": (review(status="approved"), 422, "invalid_review"),
            "neither status nor notes": (review(status=None, notes="  "), 422, "invalid_review"),
            "an extra field": (lambda: self.review(self.user, analysis_id, parent_review_id=parent,
                                                   result_sha256=sha, status=None, notes="x",
                                                   reviewer="u-0"), 422, "invalid_review"),
            "another account's analysis": (review(client=self.other), 404, "not_found"),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                self.assert_unchanged(label, send, status, code)

    def test_refused_registrations_and_sign_ins_write_nothing(self):
        self.registrant()
        rejected = dict(REGISTRANT, username="reader-r")
        self.assertEqual(self.visitor.post("/api/public/registrations", headers=SESSION_WRITE,
                                           json=rejected).status_code, 201)
        rejected_id = next(user["user_id"] for user in acc.list_users(self.world.accounts)
                           if user["username"] == "reader-r")
        self.assertEqual(self.admin.post(f"/api/admin/registrations/{rejected_id}/decision", headers=ADMIN_WRITE,
                                         json={"decision": "reject", "reason": "SYNTHETIC"}).status_code, 201)
        register = lambda headers=SESSION_WRITE, **changes: lambda: self.visitor.post(  # noqa: E731
            "/api/public/registrations", headers=headers, json=dict(REGISTRANT, username="reader-n") | changes)
        sign_in = lambda **body: lambda: self.visitor.post(  # noqa: E731
            "/api/session/login", headers=SESSION_WRITE, json=body)
        cases = {
            "a role field": (register(role="admin"), 422, "invalid_request"),
            "a credits field": (register(credits=100), 422, "invalid_request"),
            "a malformed username": (register(username="Reader N"), 422, "invalid_registration"),
            "a reserved username": (register(username="operator"), 409, "username_unavailable"),
            "a taken username": (register(username="reader-a"), 409, "username_unavailable"),
            "a rejected username, same password": (register(username="reader-r"), 409, "username_unavailable"),
            "a pending username, another password": (register(username="reader-p", password="synthetic-other-pw"),
                                                     409, "username_unavailable"),
            "a short password": (register(password="short"), 422, "invalid_registration"),
            "a control character in the note": (register(note="bell\x07"), 422, "invalid_registration"),
            "a display name of 81 characters": (register(display_name="d" * 81), 422, "invalid_registration"),
            "no session header": (register(headers={k: v for k, v in SESSION_WRITE.items()
                                                    if k != "X-Second-Order-Session"}), 403, "forbidden"),
            "the same registration again": (register(username="reader-p"), 200, None),
            "a wrong password": (sign_in(username="reader-a", password="synthetic-wrong-pw"), 401,
                                 "invalid_credentials"),
            "an unknown user": (sign_in(username="nobody-here", password="synthetic-wrong-pw"), 401,
                                "invalid_credentials"),
            "a sign-in with an extra field": (sign_in(username="reader-a", password="synthetic-reader-a",
                                                      role="admin"), 422, "invalid_request"),
            "a pending registration's password": (sign_in(username="reader-p", password=REGISTRANT["password"]),
                                                  403, "registration_pending"),
            "a rejected registration's password": (sign_in(username="reader-r", password=REGISTRANT["password"]),
                                                   403, "registration_rejected"),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                body = self.assert_unchanged(label, send, status, code)
                if code is None:
                    self.assertTrue(body["duplicate"])

    def test_refused_administrator_actions_write_nothing(self):
        pending = self.registrant()
        decided = self.visitor.post("/api/public/registrations", headers=SESSION_WRITE,
                                    json=dict(REGISTRANT, username="reader-q")).json()
        self.assertEqual(decided["registration"]["status"], "pending")
        decided_id = next(user["user_id"] for user in acc.list_users(self.world.accounts)
                          if user["username"] == "reader-q")
        self.assertEqual(self.admin.post(f"/api/admin/registrations/{decided_id}/decision", headers=ADMIN_WRITE,
                                         json={"decision": "approve", "reason": "SYNTHETIC"}).status_code, 201)
        capture = self.source(self.user)
        _, attempt = self.held_attempt()  # A counted run: the quota time zone is fixed from now on.
        reader_a, reader_b = self.world.ids["reader-a"], self.world.ids["reader-b"]
        post = lambda path, body, client=None: lambda: (client or self.admin).post(  # noqa: E731
            path, headers=ADMIN_WRITE, json=body)
        grant = lambda user_id, **body: post(f"/api/admin/users/{user_id}/credits", {  # noqa: E731
            "kind": "grant", "credits": 10, "reason": "SYNTHETIC", "idempotency_key": "qa-grant-0001"} | body)
        resolve = lambda **body: post(f"/api/admin/attempts/{attempt['attempt_id']}/resolve", {  # noqa: E731
            "resolution": "return", "credits_charged": 0, "reason": "SYNTHETIC",
            "observed": {"sent_at": None, "outcome": None}} | body)
        ent.add_credits(self.world.accounts, reader_b, "grant", 5, self.admin_id, "SYNTHETIC", "qa-grant-0001",
                        self.world.clock())
        invalid_policy = dict(POLICY, model="another-model")
        cases = {
            "credits for a pending registration": (grant(pending), 409, "account_not_approved"),
            "a daily limit for a pending registration": (post(f"/api/admin/users/{pending}/daily-limit", {
                "limit": 3, "reason": "SYNTHETIC"}), 409, "account_not_approved"),
            "the status action on a pending registration": (post(f"/api/admin/users/{pending}/status", {
                "active": True, "reason": "SYNTHETIC"}), 409, "not_approved"),
            "a record for a pending registration": (post("/api/admin/ownership", {
                "kind": "capture", "record_id": capture, "user_id": pending, "reason": "SYNTHETIC"}), 409,
                "account_not_approved"),
            "a record that already has an owner": (post("/api/admin/ownership", {
                "kind": "capture", "record_id": capture, "user_id": reader_b, "reason": "SYNTHETIC"}), 409,
                "invalid_request"),
            "a decision on an account that is not a registration": (post(
                f"/api/admin/registrations/{reader_a}/decision", {"decision": "approve", "reason": "SYNTHETIC"}),
                404, "not_found"),
            "a second decision": (post(f"/api/admin/registrations/{decided_id}/decision", {
                "decision": "reject", "reason": "SYNTHETIC"}), 409, "already_decided"),
            "an unknown decision": (post(f"/api/admin/registrations/{pending}/decision", {
                "decision": "maybe", "reason": "SYNTHETIC"}), 422, "invalid_request"),
            "a negative grant": (grant(reader_a, credits=-5, idempotency_key="qa-grant-0002"), 422,
                                 "invalid_request"),
            "a correction below zero": (grant(reader_a, kind="correction", credits=-10_000,
                                              idempotency_key="qa-grant-0003"), 409, "invalid_request"),
            "an idempotency key reused for another amount": (grant(reader_b, credits=6), 409, "invalid_request"),
            "a policy for an unverified model": (post("/api/admin/policy", {"policy": invalid_policy,
                                                                           "reason": "SYNTHETIC"}), 422,
                                                 "invalid_request"),
            "a policy without a reason": (post("/api/admin/policy", {"policy": POLICY}), 422, "invalid_request"),
            "another quota time zone after a run": (post("/api/admin/settings", {
                "quota_timezone": "Europe/London", "reason": "SYNTHETIC"}), 409, "quota_timezone_fixed"),
            "a resolution of an attempt in flight": (resolve(), 409, "in_flight"),
            "a resolution on a state that was not observed": (resolve(observed={
                "sent_at": "2026-10-14T09:00:00+00:00", "outcome": None}), 409, "state_changed"),
            "an unknown resolution": (resolve(resolution="refund"), 422, "invalid_request"),
            "a return that charges": (resolve(credits_charged=2), 422, "invalid_request"),
            "an account with a taken username": (post("/api/admin/users", {
                "username": "reader-a", "display_name": "x", "role": "user", "password": "synthetic-pass-x"}), 409,
                "invalid_request"),
            "an account with an unknown role": (post("/api/admin/users", {
                "username": "reader-z", "display_name": "x", "role": "owner", "password": "synthetic-pass-x"}),
                422, "invalid_request"),
            "deactivating oneself": (post(f"/api/admin/users/{self.admin_id}/status", {
                "active": False, "reason": "SYNTHETIC"}), 409, "invalid_request"),
            "an administrator action by a user": (post("/api/admin/policy", {"policy": POLICY, "reason": "x"},
                                                       client=self.user), 403, "forbidden"),
            "an administrator action signed out": (post("/api/admin/policy", {"policy": POLICY, "reason": "x"},
                                                        client=self.visitor), 401, "not_signed_in"),
            "a preview of a valid policy": (post("/api/admin/policy/preview", {"policy": POLICY}), 200, None),
            "the time zone already in force": (post("/api/admin/settings", {
                "quota_timezone": "Asia/Jerusalem", "reason": "SYNTHETIC"}), 200, None),
            "the same grant again": (grant(reader_b, credits=5), 200, None),
        }
        for label, (send, status, code) in cases.items():
            with self.subTest(label):
                self.assert_unchanged(label, send, status, code)

    def test_repeats_answered_as_duplicates_write_and_send_nothing(self):
        analysis = self.recorded()
        quote_id = ent.attempt_record(self.world.accounts, request_id=analysis["analysis_id"])["quote_id"]
        quote = {"quote_id": quote_id, "effort": analysis["effort"], "credits": analysis["charge"]["credits_reserved"]}
        source_id = analysis["source"]["source_id"]
        body = self.assert_unchanged("the same approval again", lambda: self.run_analysis(
            self.tab(self.user), analysis["analysis_id"], quote), 200, None)
        self.assertTrue(body["duplicate"])
        body = self.assert_unchanged("preparing the same source and Effort again", lambda: self.user.post(
            "/api/user/analyses", headers=USER_WRITE, json={"source_id": source_id, "effort": analysis["effort"]}),
            200, None)
        self.assertFalse(body["created"])


class ReadsWriteNothing(QABase):
    def test_every_read_route_writes_nothing_while_an_attempt_is_held_and_after_it_ages(self):
        analysis = self.recorded()
        analysis_id = analysis["analysis_id"]
        self.assertEqual(self.review(self.user, analysis_id, parent_review_id=None,
                                     result_sha256=analysis["result_sha256"], status="human_reviewed",
                                     notes="Synthetic.").status_code, 201)
        held, attempt = self.held_attempt()
        self.registrant()
        user_reads = ["/api/session", "/api/user/account", "/api/user/sources",
                      f"/api/user/sources/{analysis['source']['source_id']}", "/api/user/analyses",
                      f"/api/user/analyses/{analysis_id}", f"/api/user/analyses/{analysis_id}/export",
                      f"/api/user/analyses/{held}"]
        admin_reads = ["/api/admin/users", "/api/admin/registrations", "/api/admin/registrations?status=pending",
                       f"/api/admin/ledger?user_id={self.world.ids['reader-a']}", "/api/admin/ledger",
                       "/api/admin/holds", "/api/admin/policy", "/api/admin/settings", "/api/admin/actions"]
        public_reads = ["/api/public/credit-terms", "/api/session"]
        locks_before = lock_files(self.world)
        for moment in ("held and running", "aged past fifteen minutes"):
            before = records(self.world)
            for client, paths in ((self.user, user_reads), (self.admin, admin_reads), (self.visitor, public_reads)):
                for path in paths:
                    reply = client.get(path)
                    self.assertEqual(reply.status_code, 200, f"{path}: {reply.text[:200]}")
            self.assertEqual(records(self.world), before, moment)
            self.assertEqual(lock_files(self.world), locks_before, f"{moment}: a read created a lock file")
            state = self.user.get(f"/api/user/analyses/{held}").json()["analysis"]["state"]
            self.assertEqual(state, "running" if moment.startswith("held") else "unresolved")
            self.world.clock.advance(minutes=16)
        holds = self.admin.get("/api/admin/holds").json()["holds"]
        self.assertEqual([(row["attempt_id"], row["resolvable"]) for row in holds], [(attempt["attempt_id"], True)])


class Races(QABase):
    def test_two_quotes_of_one_analysis_approved_at_once_reserve_and_send_once(self):
        analysis_id = self.prepared(self.user)
        first, second = self.quote(self.user, analysis_id), self.quote(self.user, analysis_id)
        tabs = [self.tab(self.user), self.tab(self.user)]
        start = threading.Barrier(2)

        def approve(index: int):
            start.wait(5)
            return self.run_analysis(tabs[index], analysis_id, (first, second)[index])

        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(approve, range(2)))
        statuses = sorted((reply.status_code, reply.json().get("code")) for reply in replies)
        self.assertEqual(statuses, [(201, None), (409, "already_attempted")], [reply.text[:200] for reply in replies])
        self.assertEqual(len(self.world.provider.requests), 1)
        attempts = ent.attempts(self.world.accounts, self.world.ids["reader-a"])
        self.assertEqual(len(attempts), 1)
        holds = [entry for entry in ent.ledger(self.world.accounts, self.world.ids["reader-a"])
                 if entry["kind"] == "hold"]
        self.assertEqual(len(holds), 1)
        self.assertTrue(ent.balance(self.world.accounts, self.world.ids["reader-a"])["reconciles"])

    def test_two_tabs_saving_on_one_review_version_keep_exactly_one(self):
        analysis = self.recorded()
        analysis_id = analysis["analysis_id"]
        tabs = [self.tab(self.user), self.tab(self.user)]
        start = threading.Barrier(2)

        def save(index: int):
            start.wait(5)
            return self.review(tabs[index], analysis_id, parent_review_id=None,
                               result_sha256=analysis["result_sha256"], status="needs_revision",
                               notes=f"Synthetic notes from tab {index + 1}.")

        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(save, range(2)))
        statuses = sorted((reply.status_code, reply.json().get("code")) for reply in replies)
        self.assertEqual(statuses, [(201, None), (409, "review_conflict")], [reply.text[:200] for reply in replies])
        files = sorted(path.name for path in (self.world.folders.reviews / analysis_id).iterdir())
        self.assertEqual(files, ["000001.json"])
        self.assertEqual(len(self.user.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]["reviews"]), 1)


class SharedLimits(unittest.TestCase):
    def test_the_clients_review_notes_limit_is_the_servers(self):
        """The source limits have their own parity test (test_user_research); the notes limit had none."""
        published = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "contracts" / "user.ts") \
            .read_text(encoding="utf-8")
        self.assertIn(f"export const MAX_NOTES = {ra.MAX_NOTES:_};", published)


class Findings(QABase):
    """The QA report's findings, each with the assertion first written for it. QA-1 and QA-3 were expected failures on
    37caa69 and pass unchanged on Admin's fee19a8 (c2f0896, e238845); QA-4 and QA-5 follow its ff05022 and c2f0896."""

    def save_notes(self, notes: str):
        analysis = self.recorded()
        return self.user.post(f"/api/user/analyses/{analysis['analysis_id']}/reviews", headers=USER_WRITE,
                              content=json.dumps({"parent_review_id": None, "result_sha256": analysis["result_sha256"],
                                                  "status": None, "notes": notes}, ensure_ascii=False).encode())

    def test_qa1_control_a_review_of_20000_three_byte_characters_is_accepted(self):
        notes = "字" * 20_000  # SYNTHETIC: 60,000 bytes in UTF-8.
        reply = self.save_notes(notes)
        self.assertEqual(reply.status_code, 201, reply.text[:300])

    def test_qa1_a_review_of_20000_characters_in_any_script_is_accepted(self):
        """QA-1: notes are limited to 20,000 characters (contract section 6, Review; MAX_NOTES on both sides), but the
        review route reads at most 65,536 bytes (research_analysis.MAX_REVIEW_BODY), so notes in four-byte
        characters are refused 413 from about 16,370 characters, while the Client counts them as within the limit."""
        notes = "\U0001F4C8" * 20_000  # SYNTHETIC: 80,000 bytes in UTF-8.
        reply = self.save_notes(notes)
        self.assertEqual(reply.status_code, 201, reply.text[:300])

    def test_qa3_rewording_an_outcome_note_keeps_saved_reviews_bound_to_the_unchanged_result(self):
        """QA-3: result_sha256 hashes the user result including the server's fixed outcome sentence
        (user_research.NOTES), so a wording change alone makes every recorded result's hash new: each saved review
        then reads as "saved against an earlier result", and a review loaded before the change is refused as
        result_changed, though the recorded result did not change."""
        analysis = self.recorded()
        analysis_id = analysis["analysis_id"]
        saved = self.review(self.user, analysis_id, parent_review_id=None, result_sha256=analysis["result_sha256"],
                            status="human_reviewed", notes="Synthetic review of the recorded result.")
        self.assertEqual(saved.status_code, 201, saved.text)
        reworded = dict(user_research.NOTES, analysis="Each quoted passage appears in your source text. Judging "
                                                      "whether the reading is sound is up to you.")
        with patch.dict(user_research.NOTES, reworded):
            shown = self.user.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
            again = self.review(self.user, analysis_id, parent_review_id=saved.json()["review"]["review_id"],
                                result_sha256=analysis["result_sha256"], status="human_reviewed",
                                notes="Saved from the page loaded before the wording changed.")
        self.assertEqual(shown["result"]["note"], reworded["analysis"])  # The rewording is what the page shows.
        self.assertEqual(shown["result"]["analysis"], analysis["result"]["analysis"])  # The research content is equal.
        self.assertEqual(shown["result_sha256"], saved.json()["review"]["result_sha256"])
        self.assertEqual(again.status_code, 201, again.text)  # Not refused as result_changed.

    def test_qa4_a_form_feed_in_review_notes_is_refused_as_a_control_character_and_nothing_is_saved(self):
        """QA-4: a form feed was refused as "notes must be text of at most 20000 characters"."""
        analysis = self.recorded()
        analysis_id = analysis["analysis_id"]
        for notes in ("Synthetic page one\fpage two.", "Synthetic\x1b[31m escape."):
            with self.subTest(notes=notes):
                body = self.assert_unchanged(f"notes {notes!r}", lambda: self.review(
                    self.user, analysis_id, parent_review_id=None, result_sha256=analysis["result_sha256"],
                    status=None, notes=notes), 422, "invalid_review")
                self.assertIn("control characters", body["detail"])
                self.assertNotIn("20,000", body["detail"])
                self.assertNotIn("20000", body["detail"])
        long = self.review(self.user, analysis_id, parent_review_id=None, result_sha256=analysis["result_sha256"],
                           status=None, notes="n" * 20_001)
        self.assertEqual((long.status_code, long.json()["code"]), (422, "invalid_review"))
        self.assertIn("20,000 characters", long.json()["detail"])  # The length rule still names itself.

    def test_qa5_a_repeated_policy_publication_publishes_once_and_a_quote_issued_between_stays_valid(self):
        """QA-5: a double click or a lost reply submitted again published a second version, which superseded a quote
        issued in between (409 quote_superseded)."""
        intent = {"policy": POLICY | {"quote_valid_seconds": 600}, "reason": "SYNTHETIC: a shorter quote validity",
                  "idempotency_key": "qa5-intent-0001"}
        first = self.admin.post("/api/admin/policy", headers=ADMIN_WRITE, json=intent)
        self.assertEqual(first.status_code, 201, first.text)
        analysis_id = self.prepared(self.user)
        quote = self.quote(self.user, analysis_id)  # Issued under the version just published.
        before = len(ent.policies(self.world.accounts))
        repeat = self.assert_unchanged("the same publication again", lambda: self.admin.post(
            "/api/admin/policy", headers=ADMIN_WRITE, json=intent), 200, None)
        self.assertFalse(repeat["created"])
        self.assertEqual(repeat["published"]["policy_version"], first.json()["published"]["policy_version"])
        self.assertEqual(len(ent.policies(self.world.accounts)), before)
        ran = self.run_analysis(self.user, analysis_id, quote)
        self.assertEqual(ran.status_code, 201, ran.text)  # Not 409 quote_superseded.
        usage_intent = {"policy": USAGE_POLICY, "reason": "SYNTHETIC usage policy, once",
                        "idempotency_key": "qa5-usage-intent-0001"}
        self.assertEqual(self.admin.post("/api/admin/usage-policy", headers=ADMIN_WRITE, json=usage_intent).status_code,
                         201)
        again = self.assert_unchanged("the same usage policy again", lambda: self.admin.post(
            "/api/admin/usage-policy", headers=ADMIN_WRITE, json=usage_intent), 200, None)
        self.assertFalse(again["created"])
        self.assert_unchanged("the key with other values", lambda: self.admin.post(
            "/api/admin/usage-policy", headers=ADMIN_WRITE, json=usage_intent | {"reason": "SYNTHETIC: another"}),
            409, "idempotency_conflict")


if __name__ == "__main__":
    unittest.main()
