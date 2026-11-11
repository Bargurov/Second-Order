"""Identity, sessions, roles, ownership and response separation (user-api-0.2, docs/admin-user-contract.md).

SYNTHETIC accounts in temporary stores (see account_fakes). The server derives who is asking from its own session store,
never from the client; every API route is admin-only unless it is a session route or a user route; a user never
reaches the admin build, another account's records or any administrator-only field, by URL, API call, export, error
or forged identity; and the local Host and same-origin protections still apply on top of authentication.
"""
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from account_fakes import ADMIN_WRITE, BASE, PASSWORDS, SESSION_WRITE, USER_WRITE, World, source_form
from second_order import accounts as acc, auth

FORBIDDEN_KEYS = {"model", "provider", "usage", "input_tokens", "output_tokens", "max_tokens", "cost_usd",
                  "usage_cost_usd", "planning_estimate_usd", "estimated_cost", "cost_estimate", "prices",
                  "http_status", "provider_request_id", "request_id_provider", "response_sha256", "request_sha256",
                  "request", "response", "prompt_version", "provenance", "endpoint", "anthropic_version"}
FORBIDDEN_TEXT = re.compile(r"claude|sonnet|anthropic|\busd\b|\$|req_synthetic|toolu_|msg_synthetic|sk-ant|"
                            r"enable-paid|max_tokens|research-prompt-1\b(?!\.)", re.IGNORECASE)


def leaks(payload: object, path: str = "") -> list[str]:
    """Administrator-only keys anywhere in a payload, and model, provider or money words in its values."""
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in FORBIDDEN_KEYS:
                found.append(f"{path}.{key}")
            found += leaks(value, f"{path}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found += leaks(value, f"{path}[{index}]")
    elif isinstance(payload, str) and FORBIDDEN_TEXT.search(payload) and not path.endswith(("analysis_id", ".text")):
        found.append(f"{path}={payload[:60]!r}")
    return found


class Accounts(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms()

    def client(self, username: str | None = None, **options) -> TestClient:
        client = self.world.client(username, **options)
        self.addCleanup(client.close)
        return client

    def flow(self, client: TestClient) -> dict:
        """One source, prepared, quoted, run and reviewed by the signed-in user; every reply collected."""
        replies = {"account": client.get("/api/user/account")}
        replies["source"] = client.post("/api/user/sources", headers=USER_WRITE, json=source_form())
        source_id = replies["source"].json()["source"]["source_id"]
        replies["prepare"] = client.post("/api/user/analyses", headers=USER_WRITE,
                                         json={"source_id": source_id, "effort": "high"})
        analysis_id = replies["prepare"].json()["analysis"]["analysis_id"]
        replies["quote"] = client.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={})
        quote = replies["quote"].json()["quote"]
        replies["run"] = client.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": "high", "credits": quote["credits"], "approve": True})
        replies["review"] = client.post(f"/api/user/analyses/{analysis_id}/reviews", headers=USER_WRITE, json={
            "parent_review_id": None, "result_sha256": replies["run"].json()["analysis"]["result_sha256"],
            "status": "needs_revision", "notes": "Synthetic review notes."})
        replies["analysis"] = client.get(f"/api/user/analyses/{analysis_id}")
        replies["analyses"] = client.get("/api/user/analyses")
        replies["sources"] = client.get("/api/user/sources")
        replies["source_detail"] = client.get(f"/api/user/sources/{source_id}")
        replies["export"] = client.get(f"/api/user/analyses/{analysis_id}/export")
        replies["ids"] = {"source_id": source_id, "analysis_id": analysis_id, "quote": quote}
        return replies

    # ---------------------------------------------------------------- sessions

    def test_sign_in_sets_an_http_only_strict_cookie_and_the_store_keeps_only_its_hash(self):
        client = self.client()
        reply = client.post("/api/session/login", headers=SESSION_WRITE,
                            json={"username": "reader-a", "password": PASSWORDS["reader-a"]})
        self.assertEqual(reply.status_code, 200)
        self.assertEqual(reply.json()["user"]["role"], "user")
        cookie = reply.headers["set-cookie"]
        self.assertIn(f"{auth.SESSION_COOKIE}=", cookie)
        for flag in ("HttpOnly", "SameSite=strict", "Path=/"):
            self.assertIn(flag.lower(), cookie.lower())
        token = client.cookies.get(auth.SESSION_COOKIE)
        with self.world.accounts.reading() as connection:
            stored = [row[0] for row in connection.execute("SELECT token_sha256 FROM sessions")]
        self.assertEqual(stored, [acc.token_hash(token)])
        self.assertNotIn(token, self.world.store_path.read_bytes().decode("latin-1"))

    def test_one_refusal_for_an_unknown_user_a_wrong_password_and_an_inactive_account(self):
        client = self.client()
        acc.set_active(self.world.accounts, self.world.ids["reader-b"], False, self.world.ids["admin"], "test")
        replies = [client.post("/api/session/login", headers=SESSION_WRITE, json=form) for form in (
            {"username": "nobody", "password": "whatever-password"},
            {"username": "reader-a", "password": "wrong-password-1"},
            {"username": "reader-b", "password": PASSWORDS["reader-b"]})]
        for reply in replies:
            self.assertEqual((reply.status_code, reply.json()["code"]), (401, "invalid_credentials"))
        self.assertEqual(len({reply.json()["detail"] for reply in replies}), 1)
        self.assertIsNone(client.cookies.get(auth.SESSION_COOKIE))

    def test_sessions_expire_end_at_sign_out_and_end_when_an_account_is_deactivated(self):
        client = self.client("reader-a")
        self.assertEqual(client.get("/api/user/account").status_code, 200)
        self.world.clock.advance(hours=acc.SESSION_HOURS, seconds=1)
        expired = client.get("/api/user/account")
        self.assertEqual((expired.status_code, expired.json()["code"]), (401, "session_expired"))
        session = client.get("/api/session").json()
        self.assertEqual((session["state"], session["reason"]), ("signed_out", "session_expired"))

        client = self.client("reader-a")
        out = client.post("/api/session/logout", headers=SESSION_WRITE, json={})
        self.assertEqual((out.json()["state"], out.json()["reason"]), ("signed_out", "signed_out"))
        self.assertEqual(client.get("/api/user/account").status_code, 401)

        client = self.client("reader-b")
        acc.set_active(self.world.accounts, self.world.ids["reader-b"], False, self.world.ids["admin"], "test")
        self.assertEqual(client.get("/api/user/account").json()["code"], "session_expired")

    def test_a_forged_cookie_role_or_user_id_grants_nothing(self):
        anonymous = self.client()
        anonymous.cookies.set(auth.SESSION_COOKIE, "forged-token-value")
        self.assertEqual(anonymous.get("/api/user/account").json()["code"], "not_signed_in")
        self.assertEqual(anonymous.get("/api/admin/users").status_code, 401)
        user = self.client("reader-a")
        forged = user.get("/api/admin/users", headers={"X-Role": "admin", "X-User-Id": self.world.ids["admin"]})
        self.assertEqual(forged.status_code, 403)
        body = user.post("/api/user/sources", headers=USER_WRITE,
                         json={**source_form(), "user_id": self.world.ids["reader-b"]})
        self.assertEqual(body.status_code, 422)  # Exactly the documented fields: an owner cannot be named.

    def test_sign_in_needs_this_page_and_its_header(self):
        client = self.client()
        form = {"username": "reader-a", "password": PASSWORDS["reader-a"]}
        for headers in ({**SESSION_WRITE, "Origin": "http://evil.example"},
                        {key: value for key, value in SESSION_WRITE.items() if key != "X-Second-Order-Session"},
                        {**SESSION_WRITE, "Content-Type": "text/plain"}):
            reply = client.post("/api/session/login", headers=headers, content=json.dumps(form))
            self.assertIn(reply.status_code, (403, 415))
            self.assertEqual(reply.json()["contract"], "user-api-0.5")
        self.assertEqual(client.get("/api/session", headers={"host": "evil.example"}).status_code, 403)

    # ---------------------------------------------------------------- roles on every route

    def concrete(self, path: str) -> str:
        return re.sub(r"\{[^}]+\}", "x", path)

    def test_every_api_route_is_admin_only_unless_it_is_a_session_or_user_route(self):
        app = self.world.app()
        user, anonymous = self.client("reader-a"), self.client()
        admin = self.client("admin")
        checked = 0
        for route in app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api") or path == "/api/{rest:path}":
                continue
            for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
                kind = auth.route_kind(method, self.concrete(path))
                url = self.concrete(path)
                send = (lambda client: client.request(method, url, headers=ADMIN_WRITE if kind == "admin"
                                                      else USER_WRITE, content=b"{}"))
                if kind == "public":
                    continue
                checked += 1
                self.assertEqual(send(anonymous).status_code, 401, f"{method} {path}")
                if kind == "admin":
                    self.assertEqual(send(user).status_code, 403, f"{method} {path}")
                else:
                    self.assertEqual(kind, "user", path)
                    self.assertEqual(send(admin).status_code, 403, f"{method} {path}")
        self.assertGreater(checked, 90)

    def test_the_admin_keeps_every_operator_route(self):
        admin = self.client("admin")
        for path in ("/api/intake", "/api/inbox", "/api/triage", "/api/analyses", "/api/events/processing",
                     "/api/admin/users", "/api/admin/actions", "/api/admin/policy"):
            self.assertEqual(admin.get(path).status_code, 200, path)

    # ---------------------------------------------------------------- the two builds

    def builds(self) -> tuple[Path, Path]:
        admin, client = self.world.root / "dist", self.world.root / "dist-client"
        (admin / "assets").mkdir(parents=True)
        (client / "assets").mkdir(parents=True)
        (admin / "index.html").write_text("<!doctype html>ADMIN BUILD", encoding="utf-8")
        (admin / "assets" / "admin.js").write_text("ADMIN CODE claude-sonnet-5-5", encoding="utf-8")
        (client / "client.html").write_text("<!doctype html>CLIENT BUILD", encoding="utf-8")
        (client / "assets" / "client.js").write_text("CLIENT CODE", encoding="utf-8")
        return admin, client

    def test_each_role_receives_only_its_own_build(self):
        static, client_static = self.builds()
        options = {"static": static, "client_static": client_static}
        for username in (None, "reader-a"):
            visitor = self.client(username, **options)
            for path in ("/", "/library", "/admin/users", "/assets/admin.js", "/index.html"):
                self.assertNotIn("ADMIN", visitor.get(path).text, f"{username} {path}")
            self.assertEqual(visitor.get("/assets/client.js").text, "CLIENT CODE")
            self.assertIn("CLIENT BUILD", visitor.get("/").text)
        admin = self.client("admin", **options)
        self.assertIn("ADMIN BUILD", admin.get("/library").text)
        self.assertIn("ADMIN CODE", admin.get("/assets/admin.js").text)

    # ---------------------------------------------------------------- ownership and projections

    def test_another_account_cannot_reach_a_users_records_by_any_route(self):
        replies = self.flow(self.client("reader-a"))
        ids = replies["ids"]
        other = self.client("reader-b")
        analysis = ids["analysis_id"]
        for reply in (other.get(f"/api/user/analyses/{analysis}"), other.get(f"/api/user/analyses/{analysis}/export"),
                      other.get(f"/api/user/sources/{ids['source_id']}"),
                      other.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}),
                      other.post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json={
                          "quote_id": ids["quote"]["quote_id"], "effort": "high", "credits": ids["quote"]["credits"],
                          "approve": True}),
                      other.post(f"/api/user/analyses/{analysis}/reviews", headers=USER_WRITE, json={
                          "parent_review_id": None, "result_sha256": "0" * 64, "status": None, "notes": "x"}),
                      other.post("/api/user/analyses", headers=USER_WRITE,
                                 json={"source_id": ids["source_id"], "effort": "low"})):
            self.assertEqual((reply.status_code, reply.json()["code"]), (404, "not_found"), reply.request.url)
        self.assertEqual(other.get("/api/user/analyses").json()["analyses"], [])
        self.assertEqual(other.get("/api/user/sources").json()["sources"], [])
        missing = other.get("/api/user/analyses/20261014T090000000000Z-0123456789ab.research-prompt-1.high")
        self.assertEqual(missing.json(), other.get(f"/api/user/analyses/{analysis}").json())

    def test_historical_operator_records_stay_admin_owned(self):
        operator = self.client("admin")
        created = operator.post("/api/intake", headers={"Origin": BASE, "Content-Type": "application/json",
                                                        "X-Second-Order-Intake": "1"}, json=source_form())
        capture_id = created.json()["capture_id"]
        user = self.client("reader-a")
        self.assertEqual(user.get(f"/api/user/sources/{capture_id}").status_code, 404)
        self.assertEqual(user.post("/api/user/analyses", headers=USER_WRITE,
                                   json={"source_id": capture_id, "effort": "low"}).status_code, 404)
        assigned = operator.post("/api/admin/ownership", headers=ADMIN_WRITE, json={
            "kind": "capture", "record_id": capture_id, "user_id": self.world.ids["reader-a"],
            "reason": "synthetic explicit assignment"})
        self.assertEqual(assigned.status_code, 201)
        self.assertEqual(user.get(f"/api/user/sources/{capture_id}").status_code, 200)
        again = operator.post("/api/admin/ownership", headers=ADMIN_WRITE, json={
            "kind": "capture", "record_id": capture_id, "user_id": self.world.ids["reader-b"], "reason": "again"})
        self.assertEqual(again.status_code, 409)  # Owners never change.

    def test_no_user_reply_export_or_refusal_carries_an_administrator_only_field(self):
        replies = self.flow(self.client("reader-a"))
        for name, reply in replies.items():
            if name == "ids":
                continue
            self.assertLess(reply.status_code, 300, f"{name}: {reply.text[:200]}")
            self.assertEqual(leaks(reply.json()), [], name)
        self.assertIn("attachment", replies["export"].headers["content-disposition"])
        client = self.client("reader-a")
        analysis = replies["ids"]["analysis_id"]
        refusals = [client.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}),
                    client.post(f"/api/user/analyses/{analysis}/runs", headers=USER_WRITE, json={
                        "quote_id": "q-unknown-quote", "effort": "high", "credits": 1, "approve": True}),
                    client.post("/api/user/analyses", headers=USER_WRITE,
                                json={"source_id": replies["ids"]["source_id"], "effort": "max"}),
                    client.post("/api/user/sources", headers=USER_WRITE, json={**source_form(), "published_at": "x"}),
                    client.get("/api/user/nothing-here"), client.get("/api/admin/actions")]
        for reply in refusals:
            self.assertGreaterEqual(reply.status_code, 400)
            self.assertEqual(reply.json()["contract"], "user-api-0.5")
            self.assertEqual(leaks(reply.json()), [], reply.text)

    def test_a_server_that_cannot_send_says_so_without_naming_its_configuration(self):
        self.world.sending = False
        client = self.client("reader-a")
        account = client.get("/api/user/account").json()
        self.assertEqual((account["analysis"]["available"], account["analysis"]["reason"]),
                         (False, "sending_disabled"))
        source_id = client.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()["source"][
            "source_id"]
        analysis = client.post("/api/user/analyses", headers=USER_WRITE,
                               json={"source_id": source_id, "effort": "low"}).json()["analysis"]["analysis_id"]
        refused = client.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={})
        self.assertEqual((refused.status_code, refused.json()["code"]), (503, "sending_disabled"))
        self.assertEqual(leaks(refused.json()), [])
        self.assertEqual(self.world.provider.requests, [])

    def test_an_internal_failure_reaches_a_user_as_a_generic_contract_error(self):
        client = TestClient(self.world.app(), base_url=BASE, raise_server_exceptions=False)
        self.addCleanup(client.close)
        client.post("/api/session/login", headers=SESSION_WRITE,
                    json={"username": "reader-a", "password": PASSWORDS["reader-a"]})
        with patch("second_order.user_research.account_payload", side_effect=RuntimeError("secret detail sk-ant")):
            reply = client.get("/api/user/account")
        self.assertEqual((reply.status_code, reply.json()["code"]), (500, "internal_error"))
        self.assertNotIn("secret", reply.text)

    def test_an_admin_session_reads_admin_payloads_with_model_timing_usage_and_cost(self):
        self.flow(self.client("reader-a"))
        admin = self.client("admin")
        row = admin.get("/api/admin/actions").json()["actions"][0]
        self.assertEqual((row["action"], row["model"], row["effort"]), ("provider_call", "claude-sonnet-5-5", "high"))
        self.assertEqual(row["usage"], {"input_tokens": 2100, "output_tokens": 700})
        self.assertEqual(row["usage_cost_usd"], round((2100 * 2 + 700 * 10) / 1_000_000, 6))
        self.assertIn("not verified provider billing", row["usage_cost_basis"])
        self.assertIsNotNone(row["timing"]["elapsed_seconds"])
        self.assertIn("provider processing time", row["timing"]["unavailable"])
        self.assertEqual(row["requested_by"]["user_id"], self.world.ids["reader-a"])
        self.assertEqual(row["entitlement"]["state"], "charged")


class LocalOperatorMode(unittest.TestCase):
    """Without an accounts store the server is the local operator's, as before accounts existed."""

    def test_user_routes_answer_that_there_are_no_accounts(self):
        with tempfile.TemporaryDirectory() as folder:
            from second_order.api import create_app
            root = Path(folder)
            with TestClient(create_app(root / "p", None, intake=root / "intake"), base_url=BASE) as client:
                self.assertEqual(client.get("/api/session").json()["mode"], "local-operator")
                reply = client.get("/api/user/account")
                self.assertEqual((reply.status_code, reply.json()["code"]), (503, "accounts_unavailable"))
                self.assertEqual(client.post("/api/session/login", headers=SESSION_WRITE,
                                             json={"username": "x", "password": "y"}).status_code, 503)
                self.assertEqual(client.get("/api/intake").status_code, 200)

    def test_serve_refuses_to_start_without_an_accounts_store(self):
        import subprocess
        import sys
        with tempfile.TemporaryDirectory() as folder:
            run = subprocess.run([sys.executable, "-m", "second_order", "serve", "--accounts",
                                  str(Path(folder) / "missing.db"), "--port", "1"],
                                 cwd=Path(__file__).resolve().parent.parent, capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 2)
            self.assertIn("accounts add-admin", run.stderr)
            self.assertFalse((Path(folder) / "missing.db").exists())


if __name__ == "__main__":
    unittest.main()
