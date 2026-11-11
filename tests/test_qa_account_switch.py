"""QA-2 on the server, written by the QA chat independently of the owners' tests (docs/account-binding-contract.md).

A browser keeps one session cookie for all its tabs. Here one TestClient is that browser. A tab checks its account
(the preflight a page might make), then another tab signs out and signs in as someone else, and the first tab sends a
request that would have succeeded for its own account. The server must refuse it before the route runs: a stale binding
is 401 account_changed, a missing one 428 account_binding_required. Either way no account, source, usage count,
reservation, send, publisher request, preference, import or review changes, and the refusal names nothing of either
account.

Every request below has a valid body: after the refusals, the same requests are sent again from a page opened for the
account that is signed in, and each is accepted. That proves each refusal came from the binding and not from the body.
The table of writes must cover every route that requires a binding, so a new write route fails this test until it is
added here.

SYNTHETIC accounts, credit and usage policies, feeds (news_fakes) and provider (account_fakes); nothing reaches a
network or a real provider.
"""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from fastapi.testclient import TestClient

from datetime import timedelta

from account_fakes import ACCOUNT, ADMIN_WRITE, BASE, PASSWORDS, POLICY, SESSION_WRITE, START, USAGE_POLICY, \
    USER_WRITE, World, every_file, source_form
from model_fixtures import FAKE_KEY
from news_desk_fakes import (COURIER, REVISION, TARIFF, BriefModel, Feeds, annotate, curate, desk_in, item,
                             trade_feeds)
from news_fakes import Pages, fed_link, fed_page, refreshed
from second_order import accounts as acc, auth, entitlements as ent, news_feeds, news_update_report, news_updates
from second_order import news_views
from second_order import publication_import
from second_order import research_analysis as ra
from second_order.analysis_flow import capture_from_payload

REFUSAL_KEYS = {"contract", "code", "detail"}
SECOND_ADMIN = ("admin-two", "synthetic-admin-two-qa")
MINUTES_PAGE = fed_page(date_line="July 29, 2026", title="Synthetic minutes of the Committee",
                        release_line="For release at 2:00 p.m. EDT")


class StaleTab(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms(credits=40, limit=5)
        refreshed(self.root / "event-inbox")
        self.pages = Pages({fed_link(1): (200, fed_page()), fed_link(2): (200, MINUTES_PAGE)})
        # A curated SYNTHETIC newsroom (news_desk_fakes) and a simulated brief model, so every News desk write and Go
        # deeper has a valid target.
        self.feeds = Feeds(trade_feeds(START))
        self.model = BriefModel(FAKE_KEY)
        self.desk = desk_in(self.root, network=self.feeds, drafting=self.model.sender())
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher,
                           [publisher for publisher in self.desk.publishers.values() if publisher.synthetic],
                           lambda: START)
        self.curated = curate(self.desk, START)
        self.app = self.world.app(publication_fetcher=publication_import.PublicationFetcher(self.pages.transport()),
                                  desk=self.desk)
        self.browser = TestClient(self.app, base_url=BASE)  # One cookie jar: every tab of one browser.
        self.addCleanup(self.browser.close)
        self.world.ids["admin-two"] = acc.create_user(self.world.accounts, SECOND_ADMIN[0], "Admin two (synthetic)",
                                                      "admin", SECOND_ADMIN[1], "qa-setup",
                                                      self.world.clock())["user_id"]

    # ---------------------------------------------------------------- the browser

    def sign_in(self, username: str) -> str:
        password = SECOND_ADMIN[1] if username == SECOND_ADMIN[0] else PASSWORDS[username]
        reply = self.browser.post("/api/session/login", headers=SESSION_WRITE,
                                  json={"username": username, "password": password})
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()["user"]["user_id"]

    def sign_out(self, account: str) -> None:
        reply = self.browser.post("/api/session/logout", headers={**SESSION_WRITE, ACCOUNT: account}, json={})
        self.assertEqual(reply.status_code, 200, reply.text)

    def send(self, request: tuple, account: str | None):
        method, url, body = request
        headers = {**(USER_WRITE if url.startswith("/api/user/") else ADMIN_WRITE),
                   **({ACCOUNT: account} if account else {})}
        return self.browser.request(method, url, headers=headers, json=body)

    def get(self, url: str, account: str) -> dict:
        reply = self.browser.get(url, headers={ACCOUNT: account})
        self.assertEqual(reply.status_code, 200, reply.text)
        return reply.json()

    def state(self) -> tuple:
        """Every row of every accounts-store table (sessions included) and every record file outside the store, except
        empty execution-lock files."""
        connection = sqlite3.connect(self.world.store_path)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                                            "ORDER BY name")]
            rows = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        finally:
            connection.close()
        files = {name: data for name, data in every_file(self.root).items()
                 if not Path(name).name.startswith("accounts.db") and
                 not ("attempt-locks" in Path(name).parts and data == b"")}
        return (rows, files, len(self.world.provider.requests), len(self.pages.requests), len(self.feeds.requests),
                len(self.model.requests))

    def assert_refused(self, reply, status: int, code: str, label: str, *secrets: str) -> None:
        self.assertEqual((reply.status_code, reply.json().get("code")), (status, code), f"{label}: {reply.text[:300]}")
        self.assertEqual(set(reply.json()), REFUSAL_KEYS, label)
        for secret in secrets:
            self.assertNotIn(secret, reply.text, label)

    # ---------------------------------------------------------------- valid writes

    def user_writes(self) -> dict:
        """One valid write per user route, prepared by reader-a's own page, each of which reader-a may send now."""
        a = self.sign_in("reader-a")
        bound = lambda request: self.send(request, a)  # noqa: E731
        made = bound(("POST", "/api/user/sources", source_form(headline="QA account-switch source")))
        source_id = made.json()["source"]["source_id"]
        self.world.clock.advance(seconds=1)
        spare = bound(("POST", "/api/user/sources", source_form(headline="QA source not yet prepared"))).json()[
            "source"]["source_id"]

        def prepared(effort: str) -> str:
            reply = bound(("POST", "/api/user/analyses", {"source_id": source_id, "effort": effort}))
            self.assertEqual(reply.status_code, 201, reply.text)
            return reply.json()["analysis"]["analysis_id"]

        def quoted(analysis_id: str) -> dict:
            reply = bound(("POST", f"/api/user/analyses/{analysis_id}/quotes", {}))
            self.assertEqual(reply.status_code, 201, reply.text)
            return reply.json()["quote"]

        to_run, to_quote = prepared("low"), prepared("medium")
        run_quote = quoted(to_run)
        recorded_id = prepared("high")
        recorded_quote = quoted(recorded_id)
        ran = bound(("POST", f"/api/user/analyses/{recorded_id}/runs", {
            "quote_id": recorded_quote["quote_id"], "effort": "high", "credits": recorded_quote["credits"],
            "approve": True}))
        self.assertEqual(ran.status_code, 201, ran.text)
        recorded = ran.json()["analysis"]
        entries = {row["link"]: row for row in self.get("/api/user/news?scope=all", a)["news"]["entries"]}
        first, minutes = entries[fed_link(1)], entries[fed_link(2)]
        previewed = bound(("POST", "/api/user/news/imports", {"entry_id": first["entry_id"],
                                                               "version_sha256": first["version_sha256"]}))
        self.assertEqual(previewed.status_code, 201, previewed.text)
        preview = previewed.json()["import"]
        interests = self.get("/api/user/news/interests", a)["interests"]
        deeper = self.get(f"/api/user/news/stories/{self.curated[TARIFF]}/deeper", a)["deeper"]
        self.secrets = [source_id, preview["import_id"]]
        return {
            ("POST", "/api/user/sources"): ("POST", "/api/user/sources", source_form(headline="QA stale-tab text")),
            ("POST", "/api/user/analyses"): ("POST", "/api/user/analyses", {"source_id": spare, "effort": "low"}),
            ("POST", "/api/user/analyses/{analysis_id}/quotes"):
                ("POST", f"/api/user/analyses/{to_quote}/quotes", {}),
            ("POST", "/api/user/analyses/{analysis_id}/runs"):
                ("POST", f"/api/user/analyses/{to_run}/runs", {
                    "quote_id": run_quote["quote_id"], "effort": "low", "credits": run_quote["credits"],
                    "approve": True}),
            ("POST", "/api/user/analyses/{analysis_id}/reviews"):
                ("POST", f"/api/user/analyses/{recorded_id}/reviews", {
                    "parent_review_id": None, "result_sha256": recorded["result_sha256"], "status": "human_reviewed",
                    "notes": "SYNTHETIC review from a stale tab."}),
            ("POST", "/api/user/news/interests"):
                ("POST", "/api/user/news/interests", {"interests": ["energy", "trade"],
                                                      "expected_version": interests["version"]}),
            ("POST", "/api/user/news/searches"):
                ("POST", "/api/user/news/searches", {"query": "synthetic", "interests": None, "sources": None,
                                                     "listing": "all", "request_key": "qa-stale-tab-search-01"}),
            ("POST", "/api/user/news/imports"):
                ("POST", "/api/user/news/imports", {"entry_id": minutes["entry_id"],
                                                    "version_sha256": minutes["version_sha256"]}),
            ("POST", "/api/user/news/imports/{import_id}/confirmation"):
                ("POST", f"/api/user/news/imports/{preview['import_id']}/confirmation", {
                    "text_sha256": preview["proposed_source"]["text_sha256"], "confirm": True}),
            ("POST", "/api/user/news/stories/{story_id}/deeper"):
                ("POST", f"/api/user/news/stories/{self.curated[TARIFF]}/deeper", {
                    "material_sha256": deeper["material_sha256"], "effort": "low"}),
        }

    def admin_writes(self) -> dict:
        """One valid write per administrator route, each of which the first administrator may send now."""
        visitor = TestClient(self.app, base_url=BASE)
        self.addCleanup(visitor.close)
        registered = visitor.post("/api/public/registrations", headers=SESSION_WRITE, json={
            "username": "reader-p", "display_name": "Reader P (synthetic)", "password": "synthetic-reader-p-qa",
            "note": "SYNTHETIC registration for the QA account-switch test."})
        self.assertEqual(registered.status_code, 201, registered.text)
        pending = next(user["user_id"] for user in acc.list_users(self.world.accounts)
                       if user["username"] == "reader-p")
        b = self.world.ids["reader-b"]
        run = self.refreshed_run()  # An update run with two arrivals, one assessed, for its step routes.
        attempt = self.held_attempt(b)
        operator_capture = capture_from_payload(source_form(headline="An operator capture (synthetic)"),
                                                self.root / "intake", self.world.clock)["capture_id"]
        zone = acc.quota_timezone(self.world.accounts)  # Counted use has fixed it; the same zone is accepted.
        policy = POLICY  # The synthetic credit policy standard_terms published.
        desk = self.world.client("admin", desk=self.desk)  # Another browser: this one's sign-in is unchanged.
        self.addCleanup(desk.close)
        drafting = desk.post(f"/api/admin/news/stories/{self.curated[REVISION]}/drafting", headers=ADMIN_WRITE, json={})
        self.assertEqual(drafting.status_code, 200, drafting.text)
        draft = drafting.json()["drafting"]
        stories = {row["story_id"]: row for row in desk.get("/api/admin/news").json()["desk"]["stories"]}
        revision_entry = stories[self.curated[REVISION]]["material"]["reports"][0]["entry_id"]
        copy = next(row["entry_id"] for row in stories[self.curated[TARIFF]]["reports_detail"]
                    if row["source"] == "synthetic-courier")
        brief = {"headline": "SYNTHETIC stale-tab brief", "summary": "SYNTHETIC: a summary of what was reported.",
                 "facts": [{"text": "SYNTHETIC fact.", "reports": [revision_entry]}],
                 "implications": [{"text": "SYNTHETIC: it could matter if it lasts."}], "themes": [],
                 "uncertainties": ["SYNTHETIC uncertainty."], "missing": []}
        until = (self.world.clock() + timedelta(days=2)).isoformat()
        made = desk.post("/api/admin/news/batches", headers=ADMIN_WRITE, json={  # A paid batch to approve below.
            "method": "model", "limit": 1, "story_ids": [self.curated["port"]]})
        self.assertIn(made.status_code, (200, 201), made.text)
        batch, total = made.json()["batch"]["batch_id"], made.json()["batch"]["estimated_max_usd_total"]
        material = stories[self.curated[REVISION]]["material"]["material_sha256"]
        assessing = desk.post("/api/admin/news/relevance/batches", headers=ADMIN_WRITE, json={
            "method": "model", "limit": 1, "story_ids": [self.curated[REVISION]], "retry_failed": True})
        self.assertIn(assessing.status_code, (200, 201), assessing.text)
        rbatch, rtotal = assessing.json()["batch"]["batch_id"], assessing.json()["batch"]["estimated_max_usd_total"]
        return {
            ("POST", "/api/admin/users"): ("POST", "/api/admin/users", {
                "username": "reader-q", "display_name": "Reader Q (synthetic)", "role": "user",
                "password": "synthetic-reader-q-qa"}),
            ("POST", "/api/admin/users/{user_id}/status"):
                ("POST", f"/api/admin/users/{b}/status", {"active": False, "reason": "SYNTHETIC stale-tab check"}),
            ("POST", "/api/admin/registrations/{user_id}/decision"):
                ("POST", f"/api/admin/registrations/{pending}/decision", {"decision": "approve",
                                                                          "reason": "SYNTHETIC approval"}),
            ("POST", "/api/admin/users/{user_id}/credits"):
                ("POST", f"/api/admin/users/{b}/credits", {"kind": "grant", "credits": 5,
                                                           "reason": "SYNTHETIC grant", "idempotency_key":
                                                               "qa-stale-tab-grant-0001"}),
            ("POST", "/api/admin/users/{user_id}/daily-limit"):
                ("POST", f"/api/admin/users/{b}/daily-limit", {"limit": 2, "reason": "SYNTHETIC limit"}),
            ("POST", "/api/admin/attempts/{attempt_id}/resolve"):
                ("POST", f"/api/admin/attempts/{attempt['attempt_id']}/resolve", {
                    "resolution": "return", "credits_charged": 0, "reason": "SYNTHETIC return",
                    "observed": ent.observed_state(attempt)}),
            ("POST", "/api/admin/policy/preview"): ("POST", "/api/admin/policy/preview", {"policy": policy}),
            ("POST", "/api/admin/policy"): ("POST", "/api/admin/policy", {
                "policy": policy | {"quote_valid_seconds": 600}, "reason": "SYNTHETIC policy",
                "idempotency_key": "qa-stale-tab-policy-0001"}),
            ("POST", "/api/admin/usage-policy"): ("POST", "/api/admin/usage-policy", {
                "policy": self.usage_policy(), "reason": "SYNTHETIC usage policy",
                "idempotency_key": "qa-stale-tab-usage-0001"}),
            ("POST", "/api/admin/settings"): ("POST", "/api/admin/settings", {"quota_timezone": zone,
                                                                              "reason": "SYNTHETIC setting"}),
            ("POST", "/api/admin/ownership"): ("POST", "/api/admin/ownership", {
                "kind": "capture", "record_id": operator_capture, "user_id": b, "reason": "SYNTHETIC assignment"}),
            ("POST", "/api/admin/news/feeds/refresh"): ("POST", "/api/admin/news/feeds/refresh", {}),
            ("POST", "/api/admin/news/group"): ("POST", "/api/admin/news/group",
                                               {"idempotency_key": "qa-stale-group-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/merge"):
                ("POST", f"/api/admin/news/stories/{self.curated['unrelated']}/merge", {
                    "into": self.curated["port"], "reason": "SYNTHETIC merge", "idempotency_key": "qa-stale-merge-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/detach"):
                ("POST", f"/api/admin/news/stories/{self.curated[TARIFF]}/detach", {
                    "entry_id": copy, "reason": "SYNTHETIC detach", "idempotency_key": "qa-stale-detach-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/title"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/title", {
                    "title": "SYNTHETIC headline", "reason": "SYNTHETIC title",
                    "idempotency_key": "qa-stale-title-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/briefs"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/briefs", {
                    "content": brief, "method": "editorial", "based_on": None,
                    "idempotency_key": "qa-stale-brief-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/publication"):
                ("POST", f"/api/admin/news/stories/{self.curated[TARIFF]}/publication", {
                    "version": 1, "reason": "SYNTHETIC publication", "idempotency_key": "qa-stale-publish-01"}),
            ("POST", "/api/admin/news/topics"): ("POST", "/api/admin/news/topics", {
                "title": "SYNTHETIC topic", "summary": "", "reason": "SYNTHETIC",
                "idempotency_key": "qa-stale-topic-01"}),
            ("POST", "/api/admin/news/topics/{topic_id}/links"):
                ("POST", f"/api/admin/news/topics/{self.curated['topic_id']}/links", {
                    "story_id": self.curated["port"], "action": "link", "label": "", "reason": "SYNTHETIC",
                    "idempotency_key": "qa-stale-link-01"}),
            ("POST", "/api/admin/news/priorities"): ("POST", "/api/admin/news/priorities", {
                "target_kind": "topic", "target_id": self.curated["topic_id"], "level": "major", "until": until,
                "reason": "SYNTHETIC", "idempotency_key": "qa-stale-priority-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/drafting"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/drafting", {}),
            ("POST", "/api/admin/news/drafting/{draft_id}/approval"):
                ("POST", f"/api/admin/news/drafting/{draft['draft_id']}/approval", {
                    "request_sha256": draft["request_sha256"], "approve_paid_request": True,
                    "estimated_max_usd": draft["estimate"]["estimated_real_run_if_output_reaches_max_usd"]}),
            ("POST", "/api/admin/news/stories/{story_id}/texts"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/texts", {}),
            ("POST", "/api/admin/news/stories/{story_id}/reviews"):
                ("POST", f"/api/admin/news/stories/{self.curated[TARIFF]}/reviews", {
                    "version": 1, "note": "", "idempotency_key": "qa-stale-review-01"}),
            ("POST", "/api/admin/news/stories/{story_id}/assessment"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/assessment", {
                    "material_sha256": material, "verdict": "insufficient", "reason": "SYNTHETIC",
                    "idempotency_key": "qa-stale-assess-01"}),
            ("POST", "/api/admin/news/batches"): ("POST", "/api/admin/news/batches", {
                "method": "assisted", "limit": 1, "story_ids": [self.curated["port"]]}),
            ("POST", "/api/admin/news/batches/{batch_id}/approval"):
                ("POST", f"/api/admin/news/batches/{batch}/approval", {
                    "batch_id": batch, "approve_paid_requests": True, "estimated_max_usd_total": total}),
            ("POST", "/api/admin/news/batches/{batch_id}/publication"):
                ("POST", f"/api/admin/news/batches/{batch}/publication", {"reason": "SYNTHETIC", "reviewed": False}),
            ("POST", "/api/admin/news/stories/{story_id}/relevance"):
                ("POST", f"/api/admin/news/stories/{self.curated[REVISION]}/relevance", {
                    "verdict": "relevant", "reason": "SYNTHETIC", "idempotency_key": "qa-stale-relevance-01"}),
            ("POST", "/api/admin/news/relevance/batches"): ("POST", "/api/admin/news/relevance/batches", {
                "method": "assisted", "limit": 1, "story_ids": [self.curated[REVISION]], "retry_failed": True}),
            ("POST", "/api/admin/news/matches"): ("POST", "/api/admin/news/matches", {
                "story_a": self.curated[TARIFF], "story_b": self.curated["port"], "decision": "different",
                "reason": "SYNTHETIC", "topic_id": None, "topic_title": None,
                "idempotency_key": "qa-stale-match-0001"}),
            ("POST", "/api/admin/news/relevance/batches/{batch_id}/approval"):
                ("POST", f"/api/admin/news/relevance/batches/{rbatch}/approval", {
                    "batch_id": rbatch, "approve_paid_requests": True, "estimated_max_usd_total": rtotal}),
            ("POST", "/api/admin/news/updates"): ("POST", "/api/admin/news/updates", {
                "label": "SYNTHETIC stale-tab run", "official": False, "idempotency_key": "qa-stale-update-01"}),
            **{("POST", f"/api/admin/news/updates/{{run_id}}/{step}"):  # The new run's own steps, and the
               ("POST", f"/api/admin/news/updates/{news_updates.run_id_for('qa-stale-update-01')}/{step}", {})
               for step in ("refresh", "texts", "context")},  # previews of the refreshed run's stories.
            **{("POST", f"/api/admin/news/updates/{{run_id}}/{step}"):
               ("POST", f"/api/admin/news/updates/{run}/{step}", {"method": "assisted", "limit": 1})
               for step in ("relevance", "briefs")},
        }

    def refreshed_run(self) -> str:
        """A run refreshed 31 minutes after the desk's feeds (past the update cooldown), with two new SYNTHETIC
        reports: one assessed as relevant (so it needs a brief), one not assessed yet; the shared clock then moves past
        the run, so a run started from the desk is the latest."""
        later = START + timedelta(minutes=31)
        self.feeds.answers.update(trade_feeds(START, courier_extra=[item(
            COURIER.link_host, f"qa-{slug}", title, START + timedelta(minutes=20), f"SYNTHETIC: {title}.")
            for slug, title in (("rates", "Synthetic central bank holds its policy rate after QA review"),
                                ("port", "Synthetic port authority raises berthing fees for QA review"))]))
        run, _ = news_updates.start(self.desk, later, "qa-setup", {"label": "SYNTHETIC QA run", "official": False,
                                                                     "idempotency_key": "qa-setup-update-01"})
        news_updates.refresh(self.desk, run["run_id"], "qa-setup", lambda: later)
        first = news_update_report.report(self.desk, run["run_id"], later)["stories"][0]["story_id"]
        annotate(self.desk, news_views.world(self.desk, later)["stories"][first], later, actor="qa-setup")
        self.world.clock.advance(minutes=45)
        return run["run_id"]

    def held_attempt(self, user_id: str) -> dict:
        """An attempt of `user_id` holding credits with no send, aged so that an administrator may resolve it."""
        client = self.world.client([name for name, uid in self.world.ids.items() if uid == user_id][0])
        self.addCleanup(client.close)
        made = client.post("/api/user/sources", headers=USER_WRITE, json=source_form(headline="QA held attempt"))
        analysis = client.post("/api/user/analyses", headers=USER_WRITE, json={
            "source_id": made.json()["source"]["source_id"], "effort": "low"}).json()["analysis"]["analysis_id"]
        quote = client.post(f"/api/user/analyses/{analysis}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        stored = ent.latest_quote(self.world.accounts, user_id, analysis, self.world.clock(), ra.MODEL)
        attempt, _ = ent.reserve(self.world.accounts, user_id=user_id, quote_id=quote["quote_id"],
                                 request_id=analysis, request_sha256=stored["request_sha256"], model=ra.MODEL,
                                 effort=quote["effort"], credits=quote["credits"], moment=self.world.clock())
        self.world.clock.advance(minutes=16)
        return ent.attempt_record(self.world.accounts, attempt_id=attempt["attempt_id"])

    def usage_policy(self) -> dict:
        return {"account": {**USAGE_POLICY["account"], "searches_per_day": 40}, "server": USAGE_POLICY["server"]}

    # ---------------------------------------------------------------- tests

    def test_the_table_covers_every_route_that_requires_a_binding(self):
        required = {(method, route.path) for route in self.app.routes for method in getattr(route, "methods", ())
                    if auth.binding_required(method, route.path)}
        self.assertEqual(required, set(self.user_writes()) | set(self.admin_writes()))

    def test_a_user_tab_switched_after_its_preflight_changes_nothing_in_either_account(self):
        writes = self.user_writes()
        a = self.world.ids["reader-a"]
        # The page's preflight: its account is still signed in.
        self.assertEqual(self.get("/api/session", a)["user"]["user_id"], a)
        self.assertEqual(self.get("/api/user/account", a)["contract"][:9], "user-api-")
        # Another tab signs out and signs in as reader-b; the first tab never hears of it.
        self.sign_out(a)
        b = self.sign_in("reader-b")
        before = self.state()
        b_name = "reader-b"
        for key, request in writes.items():
            with self.subTest(key):
                self.assert_refused(self.send(request, a), 401, "account_changed", f"stale {key}", b, b_name)
                self.assert_refused(self.send(request, None), 428, "account_binding_required", f"unbound {key}", b)
        for url in ("/api/user/account", "/api/user/sources", "/api/user/news?scope=all", "/api/user/limits",
                    "/api/user/news/interests", "/api/user/analyses"):
            with self.subTest(read=url):
                self.assert_refused(self.browser.get(url, headers={ACCOUNT: a}), 401, "account_changed", url, b,
                                    b_name, *self.secrets)
        stale_out = self.browser.post("/api/session/logout", headers={**SESSION_WRITE, ACCOUNT: a}, json={})
        self.assert_refused(stale_out, 401, "account_changed", "a stale sign-out", b)
        self.assertEqual(self.state(), before)  # Not a row (sessions included), file, send or page request.
        self.assertEqual(self.get("/api/session", b)["user"]["user_id"], b)  # reader-b is still signed in.
        # Opened for the account signed in, the same requests are accepted: the bodies were valid all along.
        self.sign_out(b)
        self.sign_in("reader-a")
        accepted = {key: self.send(request, a).status_code for key, request in writes.items()}
        self.assertEqual(accepted, {key: 201 for key in writes})

    def test_an_administrator_tab_switched_to_another_administrator_or_a_user_changes_nothing(self):
        admin = self.sign_in("admin")
        writes = self.admin_writes()
        self.assertEqual(self.get("/api/session", admin)["user"]["user_id"], admin)  # The preflight.
        self.sign_out(admin)
        for switched_to in ("admin-two", "reader-b"):
            with self.subTest(switched_to=switched_to):
                other = self.sign_in(switched_to)
                before = self.state()
                for key, request in writes.items():
                    with self.subTest(key):
                        self.assert_refused(self.send(request, admin), 401, "account_changed", f"stale {key}", other)
                        if switched_to == "admin-two":
                            self.assert_refused(self.send(request, None), 428, "account_binding_required",
                                                f"unbound {key}", other)
                self.assertEqual(self.state(), before)
                self.sign_out(other)
        self.sign_in("admin")
        accepted, current_draft = {}, None
        for key, request in writes.items():
            if key == ("POST", "/api/admin/news/drafting/{draft_id}/approval"):
                # The preceding accepted title action changed the source packet after this table was prepared.
                # The old approval must be refused; the preceding drafting action gives this admin fresh bytes.
                stale = self.send(request, admin)
                self.assertEqual(stale.status_code, 409, stale.text)
                self.assertEqual(stale.json()["code"], "request_superseded")
                request = ("POST", f"/api/admin/news/drafting/{current_draft['draft_id']}/approval", {
                    "request_sha256": current_draft["request_sha256"], "approve_paid_request": True,
                    "estimated_max_usd": current_draft["estimate"]["estimated_real_run_if_output_reaches_max_usd"]})
            response = self.send(request, admin)
            accepted[key] = response.status_code
            if key == ("POST", "/api/admin/news/stories/{story_id}/drafting"):
                current_draft = response.json()["drafting"]
        self.assertTrue(all(200 <= status < 300 for status in accepted.values()), accepted)


if __name__ == "__main__":
    unittest.main()
