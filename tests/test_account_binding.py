"""The account binding (user-api-0.3 and admin-api-0.2, docs/account-binding-contract.md): the server side of QA-2.

One browser keeps one session cookie for all its tabs. A tab opened for reader-a and left open while another tab signs
out and signs in as reader-b sends reader-b's cookie with its next request; before the binding, that tab's unsaved source
was saved into reader-b's account. Now a page names the account it was opened for: a request bound to another account
than the session's is refused before any route runs (401 account_changed), so it reads and writes nothing, and a user or
administrator write that names no account is refused (428 account_binding_required).

SYNTHETIC accounts in temporary stores (account_fakes). A test client is one browser (one cookie jar); its tabs differ
only in the account their requests name. The fake provider is never reached by a refused request.
"""
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, PASSWORDS, SESSION_WRITE, USER_WRITE, World, every_file, source_form
from second_order import auth
from second_order.api import create_app

BOUND_REPLY = {"contract", "code", "detail"}


class Binding(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.world = World(Path(folder.name))
        self.world.standard_terms()
        self.browser = self.world.client()  # Unbound: each request below names its own tab's account, or none.
        self.addCleanup(self.browser.close)

    def sign_in(self, username: str) -> str:
        reply = self.browser.post("/api/session/login", headers=SESSION_WRITE,
                                  json={"username": username, "password": PASSWORDS[username]})
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()["user"]["user_id"]

    def sign_out(self) -> None:
        self.assertEqual(self.browser.post("/api/session/logout", headers=SESSION_WRITE, json={}).status_code, 200)

    def state(self) -> tuple:
        """Every row of every accounts-store table and every record file outside the store."""
        connection = sqlite3.connect(self.world.store_path)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                                            "ORDER BY name")]
            rows = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        finally:
            connection.close()
        files = {name: data for name, data in every_file(self.world.root).items()
                 if not name.startswith("accounts")}
        return rows, files

    def sources(self, account: str) -> list[str]:
        reply = self.browser.get("/api/user/sources", headers={ACCOUNT: account})
        self.assertEqual(reply.status_code, 200, reply.text)
        return [row["headline"] for row in reply.json()["sources"]]

    def assert_refused(self, reply, status: int, code: str) -> None:
        self.assertEqual((reply.status_code, reply.json().get("code")), (status, code), reply.text[:300])
        self.assertEqual(set(reply.json()), BOUND_REPLY)  # Nothing of either account rides along.

    # ---------------------------------------------------------------- QA-2 itself

    def test_a_tab_left_open_after_another_sign_in_cannot_write_into_the_new_account(self):
        reader_a = self.sign_in("reader-a")
        tab_a = {**USER_WRITE, ACCOUNT: reader_a}
        first = self.browser.post("/api/user/sources", headers=tab_a, json=source_form("Reader A's first source"))
        self.assertEqual(first.status_code, 201, first.text)
        self.sign_out()  # In a second tab: sign out, then sign in as someone else.
        reader_b = self.sign_in("reader-b")
        before = self.state()
        stale = self.browser.post("/api/user/sources", headers=tab_a, json=source_form("Typed in reader A's tab"))
        self.assert_refused(stale, 401, "account_changed")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.sources(reader_b), [])  # Reader B gained nothing.
        self.assertEqual(self.browser.get("/api/user/account", headers={ACCOUNT: reader_a}).status_code, 401)
        self.assertEqual(self.browser.get("/api/user/sources", headers={ACCOUNT: reader_a}).json()["code"],
                         "account_changed")  # Nor does the old tab read reader B's records under reader A's name.
        self.sign_out()
        self.sign_in("reader-a")
        self.assertEqual(self.sources(reader_a), ["Reader A's first source"])  # Reader A's records are untouched.
        again = self.browser.post("/api/user/sources", headers=tab_a, json=source_form("Saved once reader A is back"))
        self.assertEqual(again.status_code, 201, again.text)  # The tab's own account signed in again: it works.

    def test_a_stale_tab_cannot_prepare_quote_run_or_review_in_the_new_account(self):
        reader_b = self.sign_in("reader-b")
        tab_b = {**USER_WRITE, ACCOUNT: reader_b}
        source = self.browser.post("/api/user/sources", headers=tab_b, json=source_form()).json()["source"]["source_id"]
        analysis = self.browser.post("/api/user/analyses", headers=tab_b, json={"source_id": source, "effort": "high"}
                                     ).json()["analysis"]["analysis_id"]
        quote = self.browser.post(f"/api/user/analyses/{analysis}/quotes", headers=tab_b, json={}).json()["quote"]
        self.sign_out()
        reader_a = self.sign_in("reader-a")
        self.sign_out()
        self.sign_in("reader-b")  # The browser is reader B's again; a tab opened for reader A is still open.
        tab_a = {**USER_WRITE, ACCOUNT: reader_a}
        before = self.state()
        approval = {"quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
                    "approve": True}
        for path, body in ((f"/api/user/analyses/{analysis}/runs", approval),
                           (f"/api/user/analyses/{analysis}/quotes", {}),
                           ("/api/user/analyses", {"source_id": source, "effort": "low"}),
                           (f"/api/user/analyses/{analysis}/reviews", {"parent_review_id": None, "result_sha256": "0" * 64,
                                                                       "status": None, "notes": "x"})):
            self.assert_refused(self.browser.post(path, headers=tab_a, json=body), 401, "account_changed")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.world.provider.requests, [])  # Nothing was sent.

    # ---------------------------------------------------------------- every route

    def concrete(self, path: str) -> str:
        return re.sub(r"\{[^}]+\}", "x", path)

    def routes(self, app):
        for route in app.routes:
            path = getattr(route, "path", "")
            if path.startswith("/api") and path != "/api/{rest:path}":
                for method in sorted(getattr(route, "methods", set()) - {"HEAD"}):
                    yield method, self.concrete(path), auth.route_kind(method, self.concrete(path))

    def test_every_write_names_its_account_and_a_mismatch_is_refused_before_the_route(self):
        app = self.world.app()
        ids = {name: self.world.ids[name] for name in ("admin", "reader-a", "reader-b")}
        before, checked = None, 0
        for method, url, kind in self.routes(app):
            if kind == "public" or method == "GET":
                continue
            role = "reader-a" if kind == "user" else "admin"
            other = "reader-b" if kind == "user" else "reader-a"
            self.sign_in(role)
            before = before or self.state()
            headers = USER_WRITE if kind == "user" else ADMIN_WRITE
            mismatched = self.browser.request(method, url, headers={**headers, ACCOUNT: ids[other]}, content=b"{}")
            self.assert_refused(mismatched, 401, "account_changed")
            if auth.binding_required(method, url):
                unbound = self.browser.request(method, url, headers=headers, content=b"{}")
                self.assert_refused(unbound, 428, "account_binding_required")
            checked += 1
            self.sign_out()
        self.assertGreater(checked, 40)
        rows, files = self.state()
        rows.pop("sessions"), before[0].pop("sessions")  # Only the test's own sign-ins and sign-outs.
        self.assertEqual((rows, files), before)
        self.assertEqual(self.world.provider.requests, [])

    def test_reads_are_refused_when_bound_to_another_account_and_served_when_unbound(self):
        reader_a = self.sign_in("reader-a")
        for path in ("/api/user/account", "/api/user/sources", "/api/user/analyses"):
            self.assertEqual(self.browser.get(path, headers={ACCOUNT: reader_a}).status_code, 200, path)
            self.assertEqual(self.browser.get(path).status_code, 200, path)  # A plain link or an older page.
            self.assert_refused(self.browser.get(path, headers={ACCOUNT: self.world.ids["reader-b"]}), 401,
                                "account_changed")
        self.sign_out()
        admin = self.sign_in("admin")
        for path in ("/api/admin/users", "/api/admin/ledger", "/api/intake"):
            self.assertEqual(self.browser.get(path, headers={ACCOUNT: admin}).status_code, 200, path)
            self.assert_refused(self.browser.get(path, headers={ACCOUNT: reader_a}), 401, "account_changed")

    def test_a_page_of_a_user_meets_an_administrator_session_as_a_changed_account_not_a_forbidden_page(self):
        reader_a = self.sign_in("reader-a")
        self.sign_out()
        admin = self.sign_in("admin")
        self.assert_refused(self.browser.post("/api/user/sources", headers={**USER_WRITE, ACCOUNT: reader_a},
                                              json=source_form()), 401, "account_changed")
        self.assertEqual(self.browser.post("/api/user/sources", headers={**USER_WRITE, ACCOUNT: admin},
                                           json=source_form()).status_code, 403)  # The right account, the wrong role.
        self.assertEqual(self.browser.post("/api/user/sources", headers=USER_WRITE, json=source_form()).status_code,
                         403)  # Without a binding, the role is refused first.

    def test_a_repeated_or_empty_binding_names_no_account(self):
        reader_a = self.sign_in("reader-a")
        for headers in ([*USER_WRITE.items(), (ACCOUNT, reader_a), (ACCOUNT, reader_a)],
                        [*USER_WRITE.items(), (ACCOUNT, "")]):
            reply = self.browser.post("/api/user/sources", headers=headers, json=source_form())
            self.assert_refused(reply, 401, "account_changed")
        self.assertEqual(self.sources(reader_a), [])

    # ---------------------------------------------------------------- sessions and public routes

    def test_signing_out_checks_a_sent_binding_and_needs_none(self):
        reader_a = self.sign_in("reader-a")
        self.sign_out()
        self.sign_in("reader-b")
        stale = self.browser.post("/api/session/logout", headers={**SESSION_WRITE, ACCOUNT: reader_a}, json={})
        self.assert_refused(stale, 401, "account_changed")
        self.assertEqual(self.browser.get("/api/session").json()["user"]["username"], "reader-b")  # Still signed in.
        unbound = self.browser.post("/api/session/logout", headers=SESSION_WRITE, json={})
        self.assertEqual(unbound.status_code, 200)
        self.assertEqual(self.browser.get("/api/session").json()["state"], "signed_out")
        signed_out = self.browser.post("/api/session/logout", headers={**SESSION_WRITE, ACCOUNT: reader_a}, json={})
        self.assertEqual(signed_out.status_code, 200)  # Nobody is signed in: nothing to protect.

    def test_the_session_read_sign_in_and_registration_ignore_a_binding(self):
        reader_a = self.sign_in("reader-a")
        stale = {ACCOUNT: self.world.ids["reader-b"]}
        session = self.browser.get("/api/session", headers=stale)
        self.assertEqual((session.status_code, session.json()["user"]["user_id"]), (200, reader_a))
        signed_in = self.browser.post("/api/session/login", headers={**SESSION_WRITE, **stale},
                                      json={"username": "reader-b", "password": PASSWORDS["reader-b"]})
        self.assertEqual(signed_in.status_code, 200)
        registered = self.browser.post("/api/public/registrations", headers={**SESSION_WRITE, **stale}, json={
            "username": "reader-c", "display_name": "Reader C (synthetic)", "password": "synthetic-reader-c-pass",
            "note": ""})
        self.assertEqual(registered.status_code, 201, registered.text)
        self.assertEqual(self.browser.get("/api/public/credit-terms", headers=stale).status_code, 200)

    def test_a_server_without_accounts_has_no_binding(self):
        local = TestClient(create_app(self.world.root / "p", None, intake=self.world.root / "local-intake"),
                           base_url=BASE)
        self.addCleanup(local.close)
        self.assertEqual(local.get("/api/session", headers={ACCOUNT: "u-0000000000000000"}).json()["mode"],
                         "local-operator")
        self.assertEqual(local.get("/api/intake", headers={ACCOUNT: "u-0000000000000000"}).status_code, 200)


if __name__ == "__main__":
    unittest.main()
