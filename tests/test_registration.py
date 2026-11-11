"""Self-registration, the administrator's decision and the public credit terms (docs/onboarding-contract.md).

SYNTHETIC accounts in temporary stores (see account_fakes); the provider is the fake transport. A public signup makes
only a pending ordinary account: no session, role, credit, limit, owner or quote, and forged fields refuse the whole
body. Only the right password shows a registration's own status. One administrator decision per registration, durable
and attributed; approval activates the account and grants nothing. The store's triggers refuse what the routes refuse.
The public credit terms are the quotes the real formula gives for synthetic sources, and carry no money or model.
"""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from account_fakes import ADMIN_WRITE, BASE, PASSWORDS, POLICY, SESSION_WRITE, USER_WRITE, World, bind_to
from second_order import accounts as acc, credit_terms, entitlements, registration
from second_order.api import create_app
from test_accounts import leaks
from test_user_research import FIXTURES, ROOT, key_problems

FORM = {"username": "reader-c", "display_name": "Reader C (synthetic)", "password": "synthetic-reader-c",
        "note": "SYNTHETIC registration for the tests."}


class Registration(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))

    def client(self, username: str | None = None) -> TestClient:
        client = self.world.client(username)
        self.addCleanup(client.close)
        return client

    def register(self, client: TestClient, **changes):
        return client.post("/api/public/registrations", headers=SESSION_WRITE, json=FORM | changes)

    def sign_in(self, client: TestClient, username: str = "reader-c", password: str = FORM["password"]):
        reply = client.post("/api/session/login", headers=SESSION_WRITE, json={"username": username,
                                                                                "password": password})
        bind_to(client, reply)
        return reply

    def decide(self, admin: TestClient, user_id: str, decision: str = "approve"):
        return admin.post(f"/api/admin/registrations/{user_id}/decision", headers=ADMIN_WRITE,
                          json={"decision": decision, "reason": "SYNTHETIC decision"})

    def registrant(self) -> str:
        return next(user["user_id"] for user in acc.list_users(self.world.accounts) if user["username"] == "reader-c")

    def rows(self, table: str) -> list[tuple]:
        connection = sqlite3.connect(self.world.store_path)
        try:
            return connection.execute(f"SELECT * FROM {table}").fetchall()
        finally:
            connection.close()

    def test_a_signup_makes_only_a_pending_ordinary_account(self):
        visitor = self.client()
        reply = self.register(visitor)
        self.assertEqual(reply.status_code, 201, reply.text)
        body = reply.json()
        self.assertEqual(body["contract"], "onboarding-api-0.1")
        self.assertEqual(body["duplicate"], False)
        self.assertEqual(set(body["registration"]), {"username", "display_name", "status", "submitted_at",
                                                     "decided_at", "detail"})
        self.assertEqual((body["registration"]["status"], body["registration"]["decided_at"]), ("pending", None))
        self.assertNotIn("set-cookie", reply.headers)
        self.assertNotIn(FORM["password"], reply.text)
        user = acc.user_view(self.world.accounts, self.registrant())
        self.assertEqual((user["role"], user["active"], user["status"], user["created_by"]),
                         ("user", False, "pending", "self-registration"))
        self.assertEqual(self.rows("ledger") + self.rows("daily_limits") + self.rows("record_owners")
                         + self.rows("quotes") + self.rows("sessions"), [])
        self.assertEqual(visitor.get("/api/session").json()["state"], "signed_out")

    def test_forged_or_extra_fields_refuse_the_whole_body(self):
        visitor = self.client()
        before = self.rows("users")
        for extra in ({"role": "admin"}, {"active": True}, {"status": "active"}, {"credits": 100},
                      {"daily_limit": 5}, {"owner": "u-0000000000000000"}, {"user_id": "u-0000000000000000"},
                      {"approved": True}):
            reply = self.register(visitor, **extra)
            self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_request"), extra)
        reply = visitor.post("/api/public/registrations", headers=SESSION_WRITE,
                             json={key: FORM[key] for key in ("username", "display_name", "password")})
        self.assertEqual(reply.json()["code"], "invalid_request")
        for change in ({"username": "Reader-C"}, {"username": "x"}, {"password": "short"},
                       {"display_name": " "}, {"note": "x" * 501}, {"note": "line\nbreak"}, {"password": 1234567890}):
            reply = self.register(visitor, **change)
            self.assertEqual((reply.status_code, reply.json()["code"]), (422, "invalid_registration"), change)
            self.assertEqual(reply.json()["field"], next(iter(change)), change)
            self.assertNotIn("reader-a", reply.text)
        self.assertEqual(self.rows("users"), before)

    def test_writes_need_this_page_and_the_session_header(self):
        visitor = self.client()
        for change in ({"X-Second-Order-Session": "0"}, {"Origin": "http://evil.test"},
                       {"Sec-Fetch-Site": "cross-site"}, {"Content-Type": "text/plain"}):
            headers = {**SESSION_WRITE, **change}
            reply = visitor.post("/api/public/registrations", headers=headers, content=json.dumps(FORM))
            self.assertIn(reply.status_code, (403, 415))
            self.assertEqual(reply.json()["contract"], "onboarding-api-0.1")
        foreign = TestClient(self.world.app(), base_url="http://evil.test")
        self.addCleanup(foreign.close)
        self.assertEqual(foreign.get("/api/public/credit-terms").status_code, 403)
        self.assertEqual(self.rows("registrations"), [])

    def test_conflicts_name_no_account_and_a_resubmission_is_a_duplicate(self):
        visitor = self.client()
        self.assertEqual(self.register(visitor).status_code, 201)
        again = self.register(visitor, display_name="Another name")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["duplicate"], True)
        self.assertEqual(again.json()["registration"]["display_name"], FORM["display_name"])
        refusals = [self.register(visitor, password="another-password-1"),  # a pending registration, wrong password
                    self.register(visitor, username="reader-a", password=PASSWORDS["reader-a"]),  # an active user
                    self.register(visitor, username="admin"),  # an administrator, and a reserved name
                    self.register(visitor, username="operator")]  # reserved
        self.decide(self.client("admin"), self.registrant(), "reject")
        refusals.append(self.register(visitor))  # a rejected registration, right password
        bodies = {json.dumps(reply.json(), sort_keys=True) for reply in refusals}
        self.assertEqual([reply.status_code for reply in refusals], [409] * 5)
        self.assertEqual(len(bodies), 1, bodies)
        self.assertEqual(json.loads(bodies.pop())["code"], "username_unavailable")
        self.assertEqual(len(self.rows("registrations")), 1)

    def test_concurrent_signups_for_one_username_make_one_account(self):
        app = self.world.app()

        def submit(password: str) -> int:
            with TestClient(app, base_url=BASE) as client:
                return client.post("/api/public/registrations", headers=SESSION_WRITE,
                                   json=FORM | {"password": password}).status_code
        passwords = [FORM["password"]] * 4 + [f"synthetic-other-{index}" for index in range(4)]
        with ThreadPoolExecutor(8) as pool:
            statuses = list(pool.map(submit, passwords))
        self.assertEqual(len(self.rows("registrations")), 1)
        self.assertEqual(statuses.count(201), 1)
        self.assertTrue(set(statuses) <= {200, 201, 409})
        winner = statuses.index(201)
        self.assertEqual(statuses.count(200), 3 if winner < 4 else 0)

    def test_only_the_right_password_shows_a_registrations_status_and_no_session_exists(self):
        visitor = self.client()
        self.register(visitor)
        pending = self.sign_in(visitor)
        self.assertEqual((pending.status_code, pending.json()["code"]), (403, "registration_pending"))
        self.assertEqual(pending.json()["contract"], "user-api-0.5")
        self.assertEqual(pending.json()["registration"]["status"], "pending")
        self.assertNotIn("set-cookie", pending.headers)
        wrong = self.sign_in(visitor, password="not-the-password")
        unknown = self.sign_in(visitor, username="nobody-here", password="not-the-password")
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json()["code"], "invalid_credentials")
        for path in ("/api/user/account", "/api/user/sources", "/api/admin/users", "/api/admin/registrations"):
            self.assertEqual(visitor.get(path).status_code, 401, path)
        self.assertEqual(self.rows("sessions"), [])
        self.decide(self.client("admin"), self.registrant(), "reject")
        rejected = self.sign_in(visitor)
        self.assertEqual((rejected.status_code, rejected.json()["code"]), (403, "registration_rejected"))
        self.assertIsNotNone(rejected.json()["registration"]["decided_at"])
        self.assertNotIn("SYNTHETIC decision", rejected.text)  # The administrator's reason stays internal.

    def test_nothing_is_allocated_or_activated_before_approval(self):
        self.register(self.client())
        user_id, admin = self.registrant(), self.client("admin")
        for path, body, code in (
                (f"/api/admin/users/{user_id}/credits", {"kind": "grant", "credits": 10, "reason": "x",
                                                         "idempotency_key": "grant-pending-0001"},
                 "account_not_approved"),
                (f"/api/admin/users/{user_id}/daily-limit", {"limit": 3, "reason": "x"}, "account_not_approved"),
                (f"/api/admin/users/{user_id}/status", {"active": True, "reason": "x"}, "not_approved")):
            reply = admin.post(path, headers=ADMIN_WRITE, json=body)
            self.assertEqual((reply.status_code, reply.json()["code"]), (409, code), path)
        connection = sqlite3.connect(self.world.store_path)
        self.addCleanup(connection.close)
        for statement in ("UPDATE users SET active = 1 WHERE user_id = ?",
                          "INSERT INTO daily_limits (user_id, daily_limit, set_at, set_by, reason) "
                          "VALUES (?, 3, 'now', 'x', 'x')",
                          "INSERT INTO ledger (user_id, kind, amount, actor, reason, at, idempotency_key) "
                          "VALUES (?, 'grant', 5, 'x', 'x', 'now', 'k-direct')",
                          "INSERT INTO record_owners VALUES ('capture', 'c-1', ?, 'now', 'x', 'x')"):
            with self.assertRaises(sqlite3.IntegrityError, msg=statement):
                connection.execute(statement, (user_id,))
        self.assertEqual(acc.user_view(self.world.accounts, user_id)["status"], "pending")

    def test_approval_activates_only_and_the_account_names_each_missing_step(self):
        self.world.standard_terms()
        self.register(self.client())
        user_id, admin = self.registrant(), self.client("admin")
        reply = self.decide(admin, user_id)
        self.assertEqual(reply.status_code, 201, reply.text)
        self.assertEqual((reply.json()["applied"], reply.json()["user"]["status"]), (True, "active"))
        self.assertEqual([row for row in self.rows("ledger") if row[1] == user_id], [])
        user = self.client()
        self.assertEqual(self.sign_in(user).status_code, 200)
        account = user.get("/api/user/account").json()
        self.assertEqual(account["contract"], "user-api-0.5")
        self.assertEqual((account["analysis"]["available"], account["analysis"]["reason"]), (False, "no_daily_limit"))
        self.assertEqual([row["reason"] for row in account["analysis"]["reasons"]],
                         ["no_daily_limit", "no_credits_allocated"])
        self.assertEqual(account["credits"], {"available": 0, "held": 0})
        entitlements.add_credits(self.world.accounts, user_id, "grant", 40, self.world.ids["admin"], "synthetic",
                                 "grant-reader-c-0001", self.world.clock())
        self.assertEqual([row["reason"] for row in user.get("/api/user/account").json()["analysis"]["reasons"]],
                         ["no_daily_limit"])
        entitlements.set_daily_limit(self.world.accounts, user_id, 2, self.world.ids["admin"], "synthetic",
                                     self.world.clock())
        ready = user.get("/api/user/account").json()["analysis"]
        self.assertEqual(ready, {"available": True, "reason": None, "detail": None, "reasons": []})
        entitlements.add_credits(self.world.accounts, user_id, "correction", -40, self.world.ids["admin"], "synthetic",
                                 "correct-reader-c-0001", self.world.clock())
        self.assertEqual(user.get("/api/user/account").json()["analysis"]["reason"], "no_credits_available")

    def test_an_approved_registrant_runs_one_analysis_like_any_user(self):
        self.world.standard_terms()
        self.register(self.client())
        user_id = self.registrant()
        self.decide(self.client("admin"), user_id)
        entitlements.add_credits(self.world.accounts, user_id, "grant", 40, self.world.ids["admin"], "synthetic",
                                 "grant-reader-c-0002", self.world.clock())
        entitlements.set_daily_limit(self.world.accounts, user_id, 1, self.world.ids["admin"], "synthetic",
                                     self.world.clock())
        user = self.client()
        self.sign_in(user)
        from account_fakes import source_form
        source = user.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()["source"]
        analysis = user.post("/api/user/analyses", headers=USER_WRITE,
                             json={"source_id": source["source_id"], "effort": "low"}).json()["analysis"]
        quote = user.post(f"/api/user/analyses/{analysis['analysis_id']}/quotes", headers=USER_WRITE, json={}).json()
        run = user.post(f"/api/user/analyses/{analysis['analysis_id']}/runs", headers=USER_WRITE,
                        json={"quote_id": quote["quote"]["quote_id"], "effort": "low",
                              "credits": quote["quote"]["credits"], "approve": True})
        self.assertEqual(run.status_code, 201, run.text)
        self.assertEqual(run.json()["analysis"]["state"], "recorded")
        self.assertEqual(len(self.world.provider.requests), 1)
        self.assertEqual(run.json()["account"]["credits"]["available"], 40 - quote["quote"]["credits"])

    def test_one_decision_per_registration_even_when_concurrent(self):
        self.register(self.client())
        user_id, app = self.registrant(), self.world.app()
        start = threading.Barrier(2)

        def decide(decision: str):
            with TestClient(app, base_url=BASE) as admin:
                bind_to(admin, admin.post("/api/session/login", headers=SESSION_WRITE,
                                          json={"username": "admin", "password": PASSWORDS["admin"]}))
                start.wait(10)
                return self.decide(admin, user_id, decision)
        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(decide, ("approve", "reject")))
        self.assertEqual(sorted(reply.status_code for reply in replies), [201, 409])
        refused = next(reply for reply in replies if reply.status_code == 409).json()
        self.assertEqual(refused["code"], "already_decided")
        self.assertEqual(len(self.rows("registration_decisions")), 1)
        self.assertEqual(refused["decision"]["decision"], self.rows("registration_decisions")[0][1])
        repeat = self.decide(self.client("admin"), user_id, "approve")
        self.assertEqual((repeat.status_code, repeat.json()["code"]), (409, "already_decided"))
        self.assertEqual(len(self.rows("registration_decisions")), 1)

    def test_only_an_administrator_decides(self):
        self.register(self.client())
        user_id = self.registrant()
        self.assertEqual(self.decide(self.client(), user_id).status_code, 401)
        self.assertEqual(self.decide(self.client("reader-a"), user_id).status_code, 403)
        self.assertEqual(self.client("reader-a").get("/api/admin/registrations").status_code, 403)
        self.assertEqual(self.decide(self.client("admin"), self.world.ids["reader-a"]).status_code, 404)
        self.assertEqual(self.rows("registration_decisions"), [])

    def test_decisions_and_statuses_survive_a_restart(self):
        visitor = self.client()
        self.register(visitor)
        self.register(visitor, username="reader-d")
        admin = self.client("admin")
        self.decide(admin, self.registrant())
        later = next(user["user_id"] for user in acc.list_users(self.world.accounts) if user["username"] == "reader-d")
        self.decide(admin, later, "reject")
        restarted = TestClient(create_app(accounts=self.world.store_path, accounts_clock=self.world.clock),
                               base_url=BASE)
        self.addCleanup(restarted.close)
        restarted.post("/api/session/login", headers=SESSION_WRITE,
                       json={"username": "admin", "password": PASSWORDS["admin"]})
        listed = restarted.get("/api/admin/registrations").json()["registrations"]
        shown = {row["username"]: row["status"] for row in listed}
        self.assertEqual(shown, {"reader-c": "active", "reader-d": "rejected"})
        self.assertEqual(self.sign_in(restarted, "reader-d").json()["code"], "registration_rejected")


class Upgrade(unittest.TestCase):
    def test_an_accounts_1_store_keeps_every_row_and_account(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "accounts.db"
        connection = sqlite3.connect(path, isolation_level=None)
        connection.executescript("BEGIN;" + acc.SCHEMA + acc._append_only(acc.APPEND_ONLY)
                                 + "INSERT INTO accounts_meta VALUES ('schema', 'accounts-1'); COMMIT;")
        # Rows as the accounts-1 code wrote them: three accounts (one deactivated), a session, a grant, events.
        users = {"admin": "u-00000000000000a1", "reader-a": "u-00000000000000a2", "reader-b": "u-00000000000000a3"}
        for username, user_id in users.items():
            connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, '2026-10-01T00:00:00+00:00', 'x')",
                               (user_id, username, username, "admin" if username == "admin" else "user",
                                acc.hash_password(PASSWORDS[username]), 0 if username == "reader-b" else 1))
            connection.execute("INSERT INTO account_events (user_id, kind, detail, actor, reason, at) "
                               "VALUES (?, 'created', '', 'x', 'x', '2026-10-01T00:00:00+00:00')", (user_id,))
        connection.execute("INSERT INTO sessions VALUES ('f' || hex(randomblob(31)), ?, '2026-10-01T00:00:00+00:00', "
                           "'2026-10-01T12:00:00+00:00', NULL, NULL)", (users["reader-a"],))
        connection.execute("INSERT INTO ledger (user_id, kind, amount, actor, reason, at, idempotency_key) "
                           "VALUES (?, 'grant', 25, ?, 'x', '2026-10-01T00:00:00+00:00', 'admin:k-0001')",
                           (users["reader-a"], users["admin"]))
        connection.close()
        with self.assertRaises(acc.AccountsRefused) as refused:
            acc.Accounts.open(path)
        self.assertIn("accounts upgrade", str(refused.exception))
        connection = sqlite3.connect(path)
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall()
                  for table in ("users", "sessions", "ledger", "account_events", "settings", "credit_policies")}
        connection.close()
        self.assertTrue(acc.upgrade_store(path))
        self.assertFalse(acc.upgrade_store(path))
        accounts = acc.Accounts.open(path)
        connection = sqlite3.connect(path)
        self.addCleanup(connection.close)
        for table, rows in before.items():
            self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), rows, table)
        statuses = {user["username"]: user["status"] for user in acc.list_users(accounts)}
        self.assertEqual(statuses, {"admin": "active", "reader-a": "active", "reader-b": "disabled"})
        _, identity = acc.sign_in(accounts, "reader-a", PASSWORDS["reader-a"])
        self.assertEqual(identity.user_id, users["reader-a"])
        with self.assertRaises(acc.AccountsRefused) as disabled:
            acc.sign_in(accounts, "reader-b", PASSWORDS["reader-b"])
        self.assertEqual(disabled.exception.code, "invalid_credentials")
        self.assertEqual(entitlements.balance(accounts, users["reader-a"])["available"], 25)
        self.assertEqual(acc.store_version(path), "accounts-3")

    def test_an_accounts_2_store_gains_the_usage_tables_and_keeps_every_row(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "accounts.db"
        connection = sqlite3.connect(path, isolation_level=None)
        connection.executescript("BEGIN;" + acc.SCHEMA + acc.REGISTRATION_SCHEMA
                                 + acc._append_only(acc.APPEND_ONLY + acc.REGISTRATION_TABLES)
                                 + "INSERT INTO accounts_meta VALUES ('schema', 'accounts-2'); COMMIT;")
        # Rows as the accounts-2 code wrote them: an administrator, an approved registrant, a policy, a grant.
        admin, registrant = "u-00000000000000b1", "u-00000000000000b2"
        for user_id, username, role in ((admin, "admin", "admin"), (registrant, "reader-c", "user")):
            connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, 0, '2026-10-01T00:00:00+00:00', 'x')",
                               (user_id, username, username, role, acc.hash_password("synthetic-password-1")))
        connection.execute("UPDATE users SET active = 1 WHERE user_id = ?", (admin,))
        connection.execute("INSERT INTO registrations VALUES (?, '2026-10-01T00:00:00+00:00', '')", (registrant,))
        connection.execute("INSERT INTO registration_decisions VALUES (?, 'approved', ?, 'x', "
                           "'2026-10-01T01:00:00+00:00')", (registrant, admin))
        connection.execute("UPDATE users SET active = 1 WHERE user_id = ?", (registrant,))
        connection.execute("INSERT INTO credit_policies (policy_seq, policy_version, body, created_at, created_by, "
                           "reason) VALUES (1, 'credit-policy-1', '{}', '2026-10-01T00:00:00+00:00', ?, 'x')", (admin,))
        connection.execute("INSERT INTO ledger (user_id, kind, amount, actor, reason, at, idempotency_key) "
                           "VALUES (?, 'grant', 100, ?, 'x', '2026-10-01T02:00:00+00:00', 'admin:k-0002')",
                           (registrant, admin))
        connection.close()
        with self.assertRaises(acc.AccountsRefused) as refused:
            acc.Accounts.open(path)
        self.assertIn("accounts-2 accounts store", str(refused.exception))
        self.assertIn("accounts upgrade", str(refused.exception))
        tables = ("users", "registrations", "registration_decisions", "credit_policies", "ledger", "sessions")
        connection = sqlite3.connect(path)
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        connection.close()
        self.assertTrue(acc.upgrade_store(path))
        self.assertFalse(acc.upgrade_store(path))
        accounts = acc.Accounts.open(path)
        connection = sqlite3.connect(path, isolation_level=None)
        self.addCleanup(connection.close)
        for table, rows in before.items():
            self.assertEqual(connection.execute(f"SELECT * FROM {table}").fetchall(), rows, table)
        for table in acc.USAGE_TABLES:
            self.assertEqual(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 0, table)
        connection.execute("INSERT INTO news_interests VALUES (?, 1, '[]', '2026-10-02T00:00:00+00:00')", (registrant,))
        with self.assertRaises(sqlite3.DatabaseError):  # The new tables are append-only too.
            connection.execute("DELETE FROM news_interests")
        self.assertEqual(entitlements.balance(accounts, registrant)["available"], 100)
        self.assertEqual(acc.store_version(path), "accounts-3")


class CreditTerms(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.visitor = TestClient(self.world.app(), base_url=BASE)
        self.addCleanup(self.visitor.close)

    def terms(self) -> dict:
        reply = self.visitor.get("/api/public/credit-terms")
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(leaks(reply.json()), [])
        return reply.json()

    def test_without_terms_the_page_says_so(self):
        shown = self.terms()
        self.assertEqual((shown["state"], shown["policy_version"], shown["examples"], shown["quote_valid_seconds"]),
                         ("no_credit_policy", None, [], None))
        self.assertTrue(shown["detail"])
        entitlements.add_policy(self.world.accounts, POLICY | {"efforts": {}}, self.world.ids["admin"], "synthetic")
        self.assertEqual(self.terms()["state"], "no_effort_enabled")

    def test_examples_are_the_quotes_the_server_issues_and_follow_the_policy(self):
        self.world.standard_terms()
        shown = self.terms()
        self.assertEqual(shown["state"], "configured")
        self.assertEqual(shown["quote_valid_seconds"], POLICY["quote_valid_seconds"])
        self.assertEqual([option["effort"] for option in shown["efforts"]], ["low", "medium", "high"])
        reader = self.world.client("reader-a")
        self.addCleanup(reader.close)
        for example in shown["examples"]:
            form = credit_terms.example_form(example["example"], example["characters"])
            source = reader.post("/api/user/sources", headers=USER_WRITE, json=form).json()["source"]
            for quoted in example["quotes"]:
                analysis = reader.post("/api/user/analyses", headers=USER_WRITE, json={
                    "source_id": source["source_id"], "effort": quoted["effort"]}).json()["analysis"]
                quote = reader.post(f"/api/user/analyses/{analysis['analysis_id']}/quotes", headers=USER_WRITE,
                                    json={}).json()["quote"]
                self.assertEqual(quote["credits"], quoted["credits"], (example["example"], quoted["effort"]))
                self.assertEqual(quote["policy_version"], shown["policy_version"])
        sizes = [example["quotes"][0]["credits"] for example in shown["examples"]]
        self.assertEqual(sizes, sorted(sizes))
        self.assertLess(sizes[0], sizes[-1])
        richer = POLICY | {"credits": {"base": 3, "per_1k_input_tokens": 2, "per_1k_output_tokens": 0}}
        entitlements.add_policy(self.world.accounts, richer, self.world.ids["admin"], "synthetic second version")
        changed = self.terms()
        self.assertNotEqual(changed["policy_version"], shown["policy_version"])
        self.assertGreater(changed["examples"][0]["quotes"][0]["credits"], shown["examples"][0]["quotes"][0]["credits"])
        self.assertIn("2 more points", changed["size_note"])
        self.assertEqual(len(self.world.provider.requests), 0)

    def test_size_is_the_saved_requests_bytes_so_other_scripts_count_more(self):
        self.world.standard_terms()
        reader = self.world.client("reader-a")
        self.addCleanup(reader.close)
        credits = {}
        for label, unit in (("English", "SYNTHETIC text. "), ("Hebrew", "טקסט סינתטי. "), ("emoji", "🧪")):
            form = credit_terms.example_form("short", 2_000) | {"source_text": (unit * 6_000)[:6_000]}
            source = reader.post("/api/user/sources", headers=USER_WRITE,
                                 content=json.dumps(form, ensure_ascii=False).encode("utf-8")).json()["source"]
            analysis = reader.post("/api/user/analyses", headers=USER_WRITE,
                                   json={"source_id": source["source_id"], "effort": "low"}).json()["analysis"]
            credits[label] = reader.post(f"/api/user/analyses/{analysis['analysis_id']}/quotes", headers=USER_WRITE,
                                         json={}).json()["quote"]["credits"]
        self.assertLess(credits["English"], credits["Hebrew"])
        self.assertLess(credits["Hebrew"], credits["emoji"])
        self.assertIn("Hebrew letters about twice as much, emoji about four times", self.terms()["size_note"])

    def test_an_administrator_previews_a_policy_without_recording_it(self):
        admin = self.world.client("admin")
        self.addCleanup(admin.close)
        reply = admin.post("/api/admin/policy/preview", headers=ADMIN_WRITE, json={"policy": POLICY})
        self.assertEqual(reply.status_code, 200, reply.text)
        body = reply.json()
        self.assertEqual((body["contract"], body["recorded"]), ("admin-api-0.4", False))
        first = body["examples"][0]["quotes"][0]
        self.assertEqual(set(first), {"effort", "credits", "input_tokens_assumed", "planning_estimate_usd",
                                      "refused_over_budget"})
        self.assertEqual(entitlements.policies(self.world.accounts), [])
        self.assertEqual(self.terms()["state"], "no_credit_policy")
        tight = admin.post("/api/admin/policy/preview", headers=ADMIN_WRITE,
                           json={"policy": POLICY | {"max_request_usd": 0.0001}}).json()
        self.assertTrue(all(quote["refused_over_budget"] for row in tight["examples"] for quote in row["quotes"]))
        bad = admin.post("/api/admin/policy/preview", headers=ADMIN_WRITE, json={"policy": POLICY | {"extra": 1}})
        self.assertEqual(bad.status_code, 422)
        reader = self.world.client("reader-a")
        self.addCleanup(reader.close)
        self.assertEqual(reader.post("/api/admin/policy/preview", headers=ADMIN_WRITE,
                                     json={"policy": POLICY}).status_code, 403)

    def test_without_accounts_the_public_routes_are_unavailable(self):
        local = TestClient(create_app(), base_url=BASE)
        self.addCleanup(local.close)
        for reply in (local.get("/api/public/credit-terms"),
                      local.post("/api/public/registrations", headers=SESSION_WRITE, json=FORM)):
            self.assertEqual((reply.status_code, reply.json()["code"]), (503, "accounts_unavailable"))
            self.assertEqual(reply.json()["contract"], "onboarding-api-0.1")


class PublishedOnboarding(unittest.TestCase):
    """The real server's public payloads, from a SYNTHETIC scenario, against the published onboarding fixtures."""

    def served(self) -> list[dict]:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        world = World(Path(folder.name))
        visitor = TestClient(world.app(), base_url=BASE)
        self.addCleanup(visitor.close)
        rows = [("credit-terms-none", "creditTerms", visitor.get("/api/public/credit-terms").json())]
        world.standard_terms()
        rows.append(("credit-terms", "creditTerms", visitor.get("/api/public/credit-terms").json()))
        post = lambda body: visitor.post("/api/public/registrations", headers=SESSION_WRITE, json=body)  # noqa: E731
        rows.append(("registration-created", "registration", post(FORM).json()))
        rows.append(("registration-duplicate", "registration", post(FORM).json()))
        errors = {"username_unavailable": post(FORM | {"username": "reader-a"}).json(),
                  "invalid_registration": post(FORM | {"password": "short"}).json(),
                  "invalid_request": post(FORM | {"role": "admin"}).json(),
                  "payload_too_large": post(FORM | {"note": "x" * 5000}).json(),
                  "forbidden": visitor.post("/api/public/registrations", json=FORM,
                                            headers={**SESSION_WRITE, "X-Second-Order-Session": "0"}).json()}
        local = TestClient(create_app(), base_url=BASE)
        self.addCleanup(local.close)
        errors["accounts_unavailable"] = local.get("/api/public/credit-terms").json()
        rows += [(f"errors.{code}", "onboardingError", body) for code, body in errors.items()]
        return [{"name": name, "reader": reader, "body": body} for name, reader, body in rows]

    def published(self, name: str) -> object:
        stem, _, code = name.partition(".")
        body = json.loads((FIXTURES / f"onboarding-{stem}.json").read_text(encoding="utf-8"))
        return body[code] if code else body

    def test_served_payloads_have_the_published_shape(self):
        served = self.served()
        for row in served:
            self.assertEqual(key_problems(row["body"], self.published(row["name"])), [], row["name"])
            self.assertEqual(leaks(row["body"]), [], row["name"])

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run the public pages' readers")
    def test_served_payloads_pass_the_public_pages_own_readers(self):
        payloads = self.served()
        path = Path(tempfile.mkdtemp()) / "served.json"
        self.addCleanup(shutil.rmtree, path.parent)
        path.write_text(json.dumps(payloads), encoding="utf-8")
        run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "tests/user-contract-read.ts",
                              str(path)], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        results = json.loads(run.stdout)
        self.assertEqual([(row["name"], row["problem"]) for row in results if row["problem"]], [])
        self.assertEqual(len(results), len(payloads))


if __name__ == "__main__":
    unittest.main()
