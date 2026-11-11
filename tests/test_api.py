"""The HTTP layer keeps reads inert, checks every Host, and exposes only explicit local write actions."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from second_order.api import NOT_BUILT, create_app
from second_order.dossier import VIEW_VERSION, prepare

BASE = "http://127.0.0.1:8000"


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        root = Path(cls.folder.name)
        cls.prepared, cls.static = root / "prepared", root / "dist"
        cls.index = prepare(cls.prepared)
        (cls.static / "assets").mkdir(parents=True)
        (cls.static / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
        (cls.static / "assets" / "app.js").write_text("console.log('client')", encoding="utf-8")
        (root / "secret.txt").write_text("outside the client directory", encoding="utf-8")
        cls.app = create_app(cls.prepared, cls.static)
        cls.client = TestClient(cls.app, base_url=BASE)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        cls.folder.cleanup()

    def test_list_and_direct_reads_serve_the_prepared_files(self):
        listing = self.client.get("/api/dossiers")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json(), self.index)
        for row in self.index["dossiers"]:
            response = self.client.get(f"/api/dossiers/{row['id']}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.content, (self.prepared / f"{row['id']}.json").read_bytes())

    def test_unknown_and_malformed_ids_are_not_found(self):
        for dossier_id in ("f" * 64, "not-an-id", "index", "%2E%2E"):
            with self.subTest(dossier_id=dossier_id):
                response = self.client.get(f"/api/dossiers/{dossier_id}")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["detail"], "Unknown dossier ID")
        self.assertEqual(self.client.get("/api/unknown").status_code, 404)

    def test_unprepared_store_explains_the_explicit_action(self):
        with TestClient(create_app(Path(self.folder.name) / "missing", None), base_url=BASE) as client:
            for path in ("/api/dossiers", f"/api/dossiers/{self.index['dossiers'][0]['id']}"):
                response = client.get(path)
                self.assertEqual(response.status_code, 503)
                self.assertIn("python -m second_order prepare", response.json()["detail"])
            self.assertEqual(client.get("/h/anything").text, NOT_BUILT)

    def test_routes_are_get_only_and_writes_are_rejected(self):
        writes = {"/api/drafts/{draft_id}/reviews", "/api/intake", "/api/intake/{capture_id}/mock-drafts",
                  "/api/intake/{capture_id}/publish", "/api/intake/{capture_id}/paid-drafts",
                  "/api/inbox/refresh",  # The explicit, local-only inbox refresh; its GET view only reads.
                  "/api/triage", "/api/triage/{triage_id}/{mode}",  # Headline triage: prepare, then one approval,
                  "/api/triage/{triage_id}/{attempt}/revalidate",  # and an explicit local re-check (no request).
                  "/api/market-context/inbox/{item_id}/confirm",  # Market context: confirm a context date,
                  "/api/market-context/retrievals",  # and send one approved request (only when enabled).
                  # The lifecycle: upgrade the store, import a baseline locally, preview (writes nothing), freeze.
                  "/api/lifecycle/store-upgrade", "/api/lifecycle/baselines", "/api/lifecycle/preview",
                  "/api/lifecycle/freezes",
                  # Assessment: import an outcome locally, preview (writes nothing), evaluate and prepare, prepare a
                  # stored assessment's Dossier, preview an outcome retrieval (writes nothing), send one (if enabled).
                  "/api/lifecycle/outcome-imports", "/api/lifecycle/assessment-preview", "/api/lifecycle/assessments",
                  "/api/lifecycle/dossier-preparations", "/api/lifecycle/retrieval-preview",
                  "/api/lifecycle/retrievals",
                  "/api/insights/checks",  # Findings: the explicit local check of retained evidence.
                  "/api/insights/g17/checks",  # Industry findings: the explicit local check of retained G.17 releases.
                  "/api/insights/electricity/checks",  # Electricity findings: the explicit local computation.
                  "/api/insights/cross-source/checks",  # Cross-source comparisons: the explicit local computation.
                  # The copper tools: a scenario preview (writes nothing) and one saved write-once record.
                  "/api/tools/copper/preview", "/api/tools/copper/scenarios",
                  "/api/tools/copper/capital-charge",  # The capital-recovery panel: writes nothing.
                  "/api/companies/fcx/scenario",  # The FCX Scenarios tab: one exact calculation, writes nothing.
                  # Event chains: the owner's review and reading, each one append-only record.
                  "/api/theses/copper/event-chains/{chain_id}/reviews",
                  "/api/theses/copper/event-chains/{chain_id}/readings",
                  "/api/theses/copper/research/notes",  # Copper research: the owner's note, one append-only record.
                  "/api/related-cases/events/{kind}/{event_id}/matches",  # Related Cases: the explicit local check.
                  # The retained BIS snapshot: open (build its index once), preview (writes nothing), import (local).
                  "/api/inbox/snapshots/bis/open", "/api/inbox/snapshots/bis/preview",
                  "/api/inbox/snapshots/bis/import",
                  # Evidence-first research analysis: prepare a request (nothing is sent), approve one mock response,
                  # send one approved paid request (only when enabled) and append a review version.
                  "/api/research-analyses", "/api/research-analyses/{request_id}/mock",
                  "/api/research-analyses/{request_id}/paid", "/api/research-analyses/{request_id}/reviews",
                  # Accounts (user-api-0.2): sign in and out; a user's source, analysis, quote, approved run, review.
                  "/api/session/login", "/api/session/logout", "/api/user/sources", "/api/user/analyses",
                  "/api/user/analyses/{analysis_id}/quotes", "/api/user/analyses/{analysis_id}/runs",
                  "/api/user/analyses/{analysis_id}/reviews",
                  # The administrator (admin-api-0.1): accounts, credits, limits, resolutions, policy, settings and
                  # ownership, each one explicit, attributed action.
                  "/api/admin/users", "/api/admin/users/{user_id}/status", "/api/admin/users/{user_id}/credits",
                  "/api/admin/users/{user_id}/daily-limit", "/api/admin/attempts/{attempt_id}/resolve",
                  "/api/admin/policy", "/api/admin/settings", "/api/admin/ownership",
                  # Onboarding (onboarding-api-0.1): a public registration, which makes only a pending account; an
                  # administrator's one decision on it; a policy preview, which records nothing.
                  "/api/public/registrations", "/api/admin/registrations/{user_id}/decision",
                  "/api/admin/policy/preview",
                  # Current news (user-api-0.4, docs/news-usage-contract.md): interests, a deliberate counted search,
                  # an explicit import preview and its confirmation; the administrator's usage policy.
                  "/api/user/news/interests", "/api/user/news/searches", "/api/user/news/imports",
                  "/api/user/news/imports/{import_id}/confirmation", "/api/admin/usage-policy",
                  # News stories (user-api-0.5, admin-api-0.4, docs/news-stories-contract.md): a user's Go deeper;
                  # the News desk's refresh, grouping, curation, brief versions and publication, topics, priority
                  # and the paid draft's preview and approval.
                  "/api/user/news/stories/{story_id}/deeper", "/api/admin/news/feeds/refresh", "/api/admin/news/group",
                  "/api/admin/news/stories/{story_id}/merge", "/api/admin/news/stories/{story_id}/detach",
                  "/api/admin/news/stories/{story_id}/title", "/api/admin/news/stories/{story_id}/briefs",
                  "/api/admin/news/stories/{story_id}/publication", "/api/admin/news/topics",
                  "/api/admin/news/topics/{topic_id}/links", "/api/admin/news/priorities",
                  "/api/admin/news/stories/{story_id}/drafting", "/api/admin/news/drafting/{draft_id}/approval",
                  # The second milestone: retrieve a story's official texts, record a review or a material
                  # judgement, preview a batch, approve its paid requests once and publish its versions.
                  "/api/admin/news/stories/{story_id}/texts", "/api/admin/news/stories/{story_id}/reviews",
                  "/api/admin/news/stories/{story_id}/assessment", "/api/admin/news/batches",
                  "/api/admin/news/batches/{batch_id}/approval", "/api/admin/news/batches/{batch_id}/publication",
                  # The third milestone: an editor's relevance judgement, an assessment batch and its one approval.
                  "/api/admin/news/stories/{story_id}/relevance", "/api/admin/news/relevance/batches",
                  "/api/admin/news/relevance/batches/{batch_id}/approval",
                  # A decision about two stories: the same development, related ones, or different ones.
                  "/api/admin/news/matches",
                  # An update run: its start, its one refresh, its text retrieval and its step previews.
                  "/api/admin/news/updates", "/api/admin/news/updates/{run_id}/refresh",
                  "/api/admin/news/updates/{run_id}/texts", "/api/admin/news/updates/{run_id}/relevance",
                  "/api/admin/news/updates/{run_id}/context", "/api/admin/news/updates/{run_id}/briefs"}
        for route in self.app.routes:
            allowed = {"GET", "HEAD", "POST"} if route.path in writes else {"GET", "HEAD"}
            self.assertLessEqual(set(getattr(route, "methods", {"GET"})), allowed, route.path)
        self.assertEqual(self.client.post("/api/dossiers").status_code, 405)
        self.assertEqual(self.client.delete(f"/api/dossiers/{self.index['dossiers'][0]['id']}").status_code, 405)

    def test_reads_never_evaluate_fetch_or_write(self):
        before = {path.name: path.stat().st_mtime_ns for path in self.prepared.iterdir()}
        forbidden = AssertionError("A read path must not evaluate, prepare or fetch")
        # Start the client's event loop first: on Windows it opens a local socket pair at startup.
        with TestClient(self.app, base_url=BASE) as client, \
                patch("second_order.evaluation.evaluate", side_effect=forbidden), \
                patch("second_order.dossier.build_dossier", side_effect=forbidden), \
                patch("second_order.dossier.prepare", side_effect=forbidden), \
                patch("socket.socket.connect", side_effect=forbidden):
            self.assertEqual(client.get("/api/dossiers").status_code, 200)
            for row in self.index["dossiers"]:
                self.assertEqual(client.get(f"/api/dossiers/{row['id']}").status_code, 200)
                self.assertEqual(client.get(f"/h/{row['id']}").status_code, 200)
        self.assertEqual({path.name: path.stat().st_mtime_ns for path in self.prepared.iterdir()}, before)

    def test_direct_urls_and_refresh_load_the_client_shell(self):
        shell = (self.static / "index.html").read_text(encoding="utf-8")
        for path in ["/", "/h/unknown"] + [f"/h/{row['id']}" for row in self.index["dossiers"]]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual((response.status_code, response.text), (200, shell))
        self.assertEqual(self.client.get("/assets/app.js").text, "console.log('client')")
        self.assertNotIn("outside", self.client.get("/%2E%2E/secret.txt").text)
        self.assertEqual(json.loads(self.client.get("/api/dossiers").text)["view_version"], VIEW_VERSION)

    def test_host_validation_covers_api_and_static_reads_before_any_file_is_read(self):
        forbidden = AssertionError("A refused Host reached a file read")
        for host in ("attacker.example:8000", "localhost.attacker.example", "localhost:bad", "localhost:0",
                     "localhost:99999", "localhost:8000/path", "localhost:8000@attacker.example", ""):
            for path in ("/", "/assets/app.js", "/api/dossiers", "/api/unknown"):
                with self.subTest(host=host, path=path), patch.object(Path, "read_bytes", side_effect=forbidden):
                    self.assertEqual(self.client.get(path, headers={"Host": host}).status_code, 403)
        duplicate = self.client.get("/api/dossiers", headers=[("Host", "127.0.0.1:8000"),
                                                               ("Host", "attacker.example:8000")])
        self.assertEqual(duplicate.status_code, 403)

    def test_all_three_local_hosts_allow_plain_reads_with_or_without_a_port(self):
        for host in ("127.0.0.1", "127.0.0.1:8000", "localhost", "localhost:8000", "[::1]", "[::1]:8000"):
            with self.subTest(host=host):
                response = self.client.get("/api/dossiers", headers={"Host": host})
                self.assertEqual((response.status_code, response.json()), (200, self.index))

    def test_malformed_escapes_get_the_shell_or_a_json_404(self):
        # Invalid percent escapes and invalid UTF-8: the client renders Not Found; the API never errors.
        shell = (self.static / "index.html").read_text(encoding="utf-8")
        for segment in ("%", "%Z1", "%C3%28", "%E0%A4", "%FF", "%ED%A0%80"):
            with self.subTest(segment=segment):
                page = self.client.get(f"/h/{segment}")
                self.assertEqual((page.status_code, page.text), (200, shell))
                api = self.client.get(f"/api/dossiers/{segment}")
                self.assertEqual((api.status_code, api.json()["detail"]), (404, "Unknown dossier ID"))


if __name__ == "__main__":
    unittest.main()
