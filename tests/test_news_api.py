"""The current-news routes (user-api-0.4, docs/news-usage-contract.md) on the real application, over a SYNTHETIC Event
Inbox refreshed through a simulated network (news_fakes) and a simulated publisher for imports. Nothing reaches a
network or a provider.

Reading news, interests and limits contacts no publisher and counts nothing; interests are versioned per account and a
stale save is refused; a search counts once per request key and reads the cache only; an import preview requests at most
one page, counts once, and is counted only when the publisher was contacted; the server's shared publication budget
bounds the requests; confirmation saves exactly one owned, counted source; another account's import is not found; news
needs a usage policy; the research checks only read; every served payload passes the Client's own readers.
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from fastapi.testclient import TestClient

from account_fakes import USAGE_POLICY, USER_WRITE, World, every_file, source_form
from news_fakes import PARAGRAPHS, Pages, fed_link, fed_page, refreshed
from second_order import publication_import, usage

ROOT = Path(__file__).resolve().parent.parent


def policy(**account) -> dict:
    """USAGE_POLICY with some account or server values changed."""
    server = {name: account.pop(name) for name in list(account) if name in usage.SERVER_BOUNDS}
    return {"account": {**USAGE_POLICY["account"], **account}, "server": {**USAGE_POLICY["server"], **server}}


class News(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms()
        refreshed(self.root / "event-inbox")
        self.pages = Pages({fed_link(1): (200, fed_page())})
        self.options = {"publication_fetcher": publication_import.PublicationFetcher(self.pages.transport())}
        self.user = self.client("reader-a")
        self.served: list[dict] = []

    def client(self, username: str | None, **options) -> TestClient:
        client = self.world.client(username, **(self.options | options))
        self.addCleanup(client.close)
        return client

    def keep(self, name: str, reader: str, reply) -> dict:
        self.served.append({"name": name, "reader": reader, "body": reply.json()})
        return reply.json()

    def news(self, client: TestClient | None = None, scope: str = "all") -> dict:
        reply = (client or self.user).get(f"/api/user/news?scope={scope}")
        self.assertEqual(reply.status_code, 200, reply.text)
        return self.keep(f"news {scope}", "news", reply)["news"]

    def entry(self, source: str = "fed-monetary", client: TestClient | None = None) -> dict:
        return next(row for row in self.news(client)["entries"]
                    if row["source"] == source and row["import"]["state"] != "unsupported")

    def search(self, key: str, query: str = "synthetic", client: TestClient | None = None, **form):
        return (client or self.user).post("/api/user/news/searches", headers=USER_WRITE, json={
            "query": query, "interests": None, "sources": None, "listing": "all", "request_key": key} | form)

    def preview(self, entry: dict, client: TestClient | None = None):
        return (client or self.user).post("/api/user/news/imports", headers=USER_WRITE, json={
            "entry_id": entry["entry_id"], "version_sha256": entry["version_sha256"]})

    def used(self, operation: str, client: TestClient | None = None) -> int:
        limits = (client or self.user).get("/api/user/limits").json()["limits"]
        return next(row["used"] for row in limits["operations"] if row["operation"] == operation)

    def stored_state(self) -> dict:
        """The accounts store's rows, read logically, and every record file but the store's own."""
        with self.world.accounts.reading() as connection:
            rows = list(connection.iterdump())
        return {"rows": rows, "files": {name: data for name, data in every_file(self.root).items()
                                        if not Path(name).name.startswith("accounts.db")}}

    def server_fetches(self) -> int:
        return usage.overview(self.world.accounts, self.root / "intake", self.world.clock())[
            "server"]["publication_fetches"]["used"]

    # ---------------------------------------------------------------- reading and interests

    def test_reading_news_contacts_no_publisher_and_follows_saved_interests(self):
        none = self.news(scope="interests")
        self.assertEqual(none["entries"], [])
        self.assertTrue(any("No interests are chosen" in note for note in none["notes"]))
        interests = self.keep("interests", "interests", self.user.get("/api/user/news/interests"))["interests"]
        self.assertEqual((interests["selected"], interests["version"]), ([], None))
        saved = self.user.post("/api/user/news/interests", headers=USER_WRITE,
                               json={"interests": ["energy"], "expected_version": None})
        self.assertEqual((saved.status_code, saved.json()["changed"], saved.json()["interests"]["version"]),
                         (201, True, 1))
        self.keep("interests saved", "interestsSaved", saved)
        same = self.user.post("/api/user/news/interests", headers=USER_WRITE,
                              json={"interests": ["energy"], "expected_version": 1})
        self.assertEqual((same.status_code, same.json()["changed"]), (200, False))
        stale = self.user.post("/api/user/news/interests", headers=USER_WRITE,
                               json={"interests": ["trade"], "expected_version": None})  # Another tab saved first.
        self.assertEqual((stale.status_code, stale.json()["code"]), (409, "interests_changed"))
        self.assertEqual(stale.json()["interests"]["selected"], ["energy"])
        self.served.append({"name": "interests_changed", "reader": "error", "body": stale.json()})
        chosen = self.news(scope="interests")
        self.assertTrue(chosen["entries"])
        self.assertTrue(all(any(topic["interest"] == "energy" for topic in entry["topics"])
                            for entry in chosen["entries"]))
        other = self.client("reader-b")
        self.assertEqual(other.get("/api/user/news/interests").json()["interests"]["selected"], [])  # Per account.
        self.assertEqual(self.pages.requests, [])
        self.assertEqual(self.world.provider.requests, [])
        self.assertTrue(all(self.used(operation) == 0 for operation in usage.OPERATIONS))
        self.keep("limits", "limits", self.user.get("/api/user/limits"))

    # ---------------------------------------------------------------- searches

    def test_a_search_counts_once_per_key_and_reads_the_cache_only(self):
        usage.add_policy(self.world.accounts, policy(searches_per_day=2), self.world.ids["admin"], "SYNTHETIC")
        first = self.search("search-key-0001")
        self.assertEqual((first.status_code, first.json()["counted"], first.json()["quota"]["used"]), (201, True, 1))
        self.keep("search", "search", first)
        again = self.search("search-key-0001")
        self.assertEqual((again.status_code, again.json()["counted"], again.json()["quota"]["used"]), (200, False, 1))
        reused = self.search("search-key-0001", query="committee")
        self.assertEqual((reused.status_code, reused.json()["code"]), (409, "request_key_reused"))
        refused = self.search("search-key-0002", query="one two three four five six seven eight nine")
        self.assertEqual(refused.status_code, 422)
        self.assertEqual(self.used("search"), 1)  # Neither a reused key nor a refused query counted.
        self.assertEqual(self.search("search-key-0003").status_code, 201)
        limited = self.search("search-key-0004")
        self.assertEqual((limited.status_code, limited.json()["code"]), (409, "usage_limit_reached"))
        self.assertEqual({key: limited.json()["quota"][key] for key in ("operation", "limit", "used")},
                         {"operation": "search", "limit": 2, "used": 2})
        self.served.append({"name": "usage_limit_reached", "reader": "error", "body": limited.json()})
        self.assertEqual(self.search("search-key-0001").status_code, 200)  # A repeat is still answered at the limit.
        self.world.clock.advance(days=1)
        self.user = self.client("reader-a")  # The session of yesterday has ended.
        self.assertEqual(self.search("search-key-0005").status_code, 201)  # A new quota day.
        self.assertEqual(self.pages.requests, [])
        self.assertEqual(self.world.provider.requests, [])

    def test_concurrent_searches_at_the_limit_never_both_pass(self):
        usage.add_policy(self.world.accounts, policy(searches_per_day=3, concurrent_requests=16),
                         self.world.ids["admin"], "SYNTHETIC")
        self.assertEqual(self.search("search-key-0100").status_code, 201)
        start = threading.Barrier(6)

        def submit(number: int) -> int:
            start.wait(10)
            return self.search(f"search-key-01{number:02d}x").status_code
        with ThreadPoolExecutor(6) as pool:
            statuses = sorted(pool.map(submit, range(6)))
        self.assertEqual(statuses, [201, 201, 409, 409, 409, 409])
        self.assertEqual(self.used("search"), 3)

    # ---------------------------------------------------------------- imports

    def test_an_import_requests_the_page_once_counts_once_and_confirms_one_owned_source(self):
        entry = self.entry()
        created = self.preview(entry)
        self.assertEqual((created.status_code, created.json()["created"], created.json()["quota"]["used"]),
                         (201, True, 1), created.text)
        preview = self.keep("import created", "importCreated", created)["import"]
        self.assertEqual((len(self.pages.requests), self.server_fetches()), (1, 1))
        again = self.preview(entry)
        self.assertEqual((again.status_code, again.json()["created"], self.used("import")), (200, False, 1))
        other = self.client("reader-b")
        theirs = self.preview(entry, other)  # Their own preview of the kept copy: no second request.
        self.assertEqual((theirs.status_code, theirs.json()["import"]["publication"]["retrieval"]), (201, "reused"))
        self.assertEqual((len(self.pages.requests), self.server_fetches()), (1, 1))
        self.assertEqual(other.get(f"/api/user/news/imports/{preview['import_id']}").status_code, 404)
        self.keep("import", "import", self.user.get(f"/api/user/news/imports/{preview['import_id']}"))
        confirm = lambda: self.user.post(f"/api/user/news/imports/{preview['import_id']}/confirmation",  # noqa: E731
                                         headers=USER_WRITE, json={"text_sha256": preview["proposed_source"]["text_sha256"],
                                                                   "confirm": True})
        confirmed = confirm()
        self.assertEqual((confirmed.status_code, confirmed.json()["created"]), (201, True), confirmed.text)
        self.keep("import confirmed", "importConfirmed", confirmed)
        source_id = confirmed.json()["source"]["source_id"]
        repeated = confirm()
        self.assertEqual((repeated.status_code, repeated.json()["source"]["source_id"]), (200, source_id))
        self.assertEqual(self.used("source"), 1)
        self.assertEqual([row["source_id"] for row in self.user.get("/api/user/sources").json()["sources"]], [source_id])
        self.assertEqual(self.entry()["import"]["source_ids"], [source_id])
        self.assertEqual(self.world.provider.requests, [])

    def test_a_confirmation_the_capture_path_refuses_counts_and_writes_nothing(self):
        # QA-7 on the shared path: a confirmation saves through the user's source write, so a text that write refuses
        # (here a framing tag, which the preview does not judge) is refused before the source is counted; the claim is
        # released and no row or file is left.
        self.pages.answers[fed_link(1)] = (200, fed_page(paragraphs=PARAGRAPHS + (
            "The statement quotes <source_text> as printed.",)))
        preview = self.preview(self.entry()).json()["import"]
        before = self.stored_state()
        refused = self.user.post(f"/api/user/news/imports/{preview['import_id']}/confirmation", headers=USER_WRITE,
                                 json={"text_sha256": preview["proposed_source"]["text_sha256"], "confirm": True})
        self.assertEqual((refused.status_code, refused.json()["code"]), (422, "invalid_source"), refused.text)
        self.assertEqual(self.stored_state(), before)
        again = self.user.get(f"/api/user/news/imports/{preview['import_id']}").json()["import"]
        self.assertEqual((again["state"], again["source_id"], self.used("source")), ("ready", None, 0))

    def test_a_released_count_is_stamped_by_the_servers_clock(self):
        # A release row is an audit record of the server's time, like its event: here the account's earlier preview of
        # the same version is released at the server's (SYNTHETIC) clock, not at the machine's.
        entry = self.entry()
        self.assertEqual(self.preview(entry).status_code, 201)
        self.world.clock.advance(minutes=5)
        self.assertEqual(self.preview(entry).status_code, 200)
        with self.world.accounts.reading() as connection:
            stamps = connection.execute("SELECT e.at, r.at FROM usage_releases r JOIN usage_events e "
                                        "ON e.event_id = r.event_id").fetchall()
        self.assertEqual([tuple(row) for row in stamps], [(self.world.clock().isoformat(),) * 2])

    def test_refused_previews_count_only_when_the_publisher_was_contacted(self):
        unsupported = next(row for row in self.news()["entries"] if row["import"]["state"] == "unsupported")
        refused = self.preview(unsupported)
        self.assertEqual((refused.status_code, refused.json()["code"], refused.json()["paste_instead"]),
                         (409, "import_unsupported", True))
        self.served.append({"name": "import_unsupported", "reader": "error", "body": refused.json()})
        unknown = self.preview({"entry_id": f"fed-monetary:{'0' * 20}", "version_sha256": "0" * 64})
        changed = self.preview({**self.entry(), "version_sha256": "0" * 64})
        no_fetcher = self.preview(self.entry(), self.client("reader-a", publication_fetcher=None))
        self.assertEqual((no_fetcher.status_code, no_fetcher.json()["code"]), (409, "publication_unavailable"))
        # Every preview refusal says whether the publisher was contacted (docs/news-usage-contract.md, section 4).
        self.assertEqual([(reply.json()["code"], reply.json()["requested"]) for reply in (refused, unknown, changed,
                                                                                           no_fetcher)],
                         [("import_unsupported", False), ("entry_changed", False), ("entry_changed", False),
                          ("publication_unavailable", False)])  # An entry no longer held is `entry_changed`.
        self.assertEqual((self.used("import"), self.server_fetches(), len(self.pages.requests)), (0, 0, 0))
        self.pages.answers[fed_link(1)] = (503, b"")
        failed = self.preview(self.entry())
        self.assertEqual((failed.status_code, failed.json()["code"], failed.json()["requested"]),
                         (409, "publication_unavailable", True))
        self.assertEqual((self.used("import"), self.server_fetches(), len(self.pages.requests)), (1, 1, 1))
        usage.add_policy(self.world.accounts, policy(publication_fetches_per_day=1), self.world.ids["admin"],
                         "SYNTHETIC")
        budget = self.preview(self.entry())
        self.assertEqual((budget.status_code, budget.json()["code"]), (409, "fetch_budget_reached"))
        self.served.append({"name": "fetch_budget_reached", "reader": "error", "body": budget.json()})
        self.assertEqual((self.used("import"), self.server_fetches(), len(self.pages.requests)), (1, 1, 1))

    # ---------------------------------------------------------------- policy, binding, checks

    def test_news_and_searches_need_a_usage_policy(self):
        world = World(self.root / "no-policy")
        refreshed(self.root / "no-policy" / "event-inbox")
        with world.client("reader-a", **self.options) as client:
            for reply in (client.get("/api/user/news?scope=all"), client.get("/api/user/news/interests"),
                          self.search("search-key-0200", client=client),
                          client.post("/api/user/news/interests", headers=USER_WRITE,
                                      json={"interests": ["trade"], "expected_version": None}),
                          client.post("/api/user/sources", headers=USER_WRITE, json=source_form())):
                self.assertEqual((reply.status_code, reply.json()["code"]), (409, "no_usage_policy"), reply.text)
            limits = client.get("/api/user/limits").json()["limits"]
            self.assertEqual((limits["state"], limits["operations"][0]["limit"]), ("no_policy", None))
            self.assertEqual(client.get("/api/user/sources").status_code, 200)  # Reading what exists stays free.

    def test_news_writes_name_their_account(self):
        unbound = self.world.client("reader-a", bind=False, **self.options)
        self.addCleanup(unbound.close)
        self.assertEqual(self.search("search-key-0300", client=unbound).json()["code"], "account_binding_required")
        self.assertEqual(self.used("search"), 0)

    def test_research_checks_only_read(self):
        source_id = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form()).json()["source"]["source_id"]
        prepared = self.user.post("/api/user/analyses", headers=USER_WRITE,
                                  json={"source_id": source_id, "effort": "low"}).json()["analysis"]
        analysis_id = prepared["analysis_id"]
        self.assertEqual(self.user.get(f"/api/user/analyses/{analysis_id}/quality").json()["quality"], None)
        quote = self.user.post(f"/api/user/analyses/{analysis_id}/quotes", headers=USER_WRITE, json={}).json()["quote"]
        recorded = self.user.post(f"/api/user/analyses/{analysis_id}/runs", headers=USER_WRITE, json={
            "quote_id": quote["quote_id"], "effort": quote["effort"], "credits": quote["credits"],
            "approve": True}).json()["analysis"]
        checks = self.keep("quality", "quality", self.user.get(f"/api/user/analyses/{analysis_id}/quality"))["quality"]
        self.assertEqual((checks["rubric_version"], checks["rejected"]), ("research-quality-0.3", []))
        after = self.user.get(f"/api/user/analyses/{analysis_id}").json()["analysis"]
        self.assertEqual((after["result"], after["result_sha256"]), (recorded["result"], recorded["result_sha256"]))
        self.assertEqual(self.client("reader-b").get(f"/api/user/analyses/{analysis_id}/quality").status_code, 404)
        self.assertEqual(len(self.world.provider.requests), 1)  # The run's one send; the checks sent nothing.

    @unittest.skipUnless(shutil.which("node"), "Node is needed to run the Client's readers")
    def test_served_payloads_pass_the_clients_own_readers(self):
        served = []
        for name in ("test_reading_news_contacts_no_publisher_and_follows_saved_interests",
                     "test_a_search_counts_once_per_key_and_reads_the_cache_only",
                     "test_an_import_requests_the_page_once_counts_once_and_confirms_one_owned_source",
                     "test_refused_previews_count_only_when_the_publisher_was_contacted",
                     "test_research_checks_only_read"):
            self.setUp()  # A fresh world for each scenario; every payload it served is kept.
            getattr(self, name)()
            served += self.served
        path = self.root / "served.json"
        path.write_text(json.dumps(served), encoding="utf-8")
        run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", "tests/user-contract-read.ts",
                              str(path)], cwd=ROOT / "frontend", capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stderr)
        results = json.loads(run.stdout)
        self.assertEqual([(row["name"], row["problem"]) for row in results if row["problem"]], [])
        self.assertGreaterEqual(len(results), 14)


if __name__ == "__main__":
    unittest.main()
