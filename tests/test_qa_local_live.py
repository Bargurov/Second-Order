"""QA checks of the current-news routes (user-api-0.4, and the stories routes of user-api-0.5) that the owners' tests do
not already make, over HTTP on the real application. Written by the QA chat; SYNTHETIC accounts, limits, feeds
(news_fakes, news_desk_fakes) and pages; nothing reaches a network.

- Every user read, enumerated from the application's own routes (the stories, a story, a topic and what Go deeper
  would use included), contacts neither a publisher nor the provider and changes no row or file; a source whose latest
  refresh failed is shown stale with its earlier entries.
- A search sent twice at once with one request key (a double click, two tabs) counts once.
- A preview sent twice at once requests the publisher's page once and counts once.
- A confirmation over the account's storage limit creates nothing and counts nothing, and the same preview can be
  confirmed once the limit allows it.
- A refused search body writes nothing (docs/admin-user-contract.md section 9).
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from account_fakes import START, USAGE_POLICY, USER_WRITE, World, every_file, source_form
from news_desk_fakes import TARIFF, Feeds, curate, desk_in, trade_feeds
from news_fakes import Pages, fed_link, fed_page, refreshed, standard_feeds
from second_order import news_feeds, publication_import, usage
from test_event_inbox import FED


def policy(**account) -> dict:
    return {"account": {**USAGE_POLICY["account"], **account}, "server": USAGE_POLICY["server"]}


class Gate:
    """A publisher whose answer waits until released, so two previews overlap."""

    def __init__(self, pages: Pages):
        self.pages, self.release, self.entered = pages, threading.Event(), threading.Event()

    def __call__(self, request):
        self.entered.set()
        self.release.wait(10)
        return self.pages(request)


class LocalLive(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.world = World(self.root)
        self.world.standard_terms()
        refreshed(self.root / "event-inbox")
        self.pages = Pages({fed_link(1): (200, fed_page())})
        self.gate = Gate(self.pages)
        import httpx
        self.fetcher = publication_import.PublicationFetcher(httpx.MockTransport(self.gate))
        self.gate.release.set()  # Open unless a test closes it.
        self.network = Feeds(trade_feeds(START))
        self.desk = desk_in(self.root, network=self.network)
        news_feeds.refresh(self.desk.feeds, self.desk.fetcher,
                           [publisher for publisher in self.desk.publishers.values() if publisher.synthetic],
                           lambda: START)
        self.curated = curate(self.desk, START)
        self.user = self.client("reader-a")

    def client(self, username: str):
        client = self.world.client(username, publication_fetcher=self.fetcher, desk=self.desk)
        self.addCleanup(client.close)
        return client

    def state(self) -> tuple:
        connection = sqlite3.connect(self.world.store_path)
        try:
            tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' "
                                                            "ORDER BY name")]
            rows = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        finally:
            connection.close()
        files = {name: data for name, data in every_file(self.root).items()
                 if not Path(name).name.startswith("accounts.db")}
        return rows, files, len(self.pages.requests), len(self.world.provider.requests), len(self.network.requests)

    def entry(self) -> dict:
        news = self.user.get("/api/user/news?scope=all").json()["news"]
        return next(row for row in news["entries"] if row["link"] == fed_link(1))

    def used(self, operation: str) -> int:
        limits = self.user.get("/api/user/limits").json()["limits"]
        return next(row["used"] for row in limits["operations"] if row["operation"] == operation)

    def preview(self, entry: dict, client=None):
        return (client or self.user).post("/api/user/news/imports", headers=USER_WRITE, json={
            "entry_id": entry["entry_id"], "version_sha256": entry["version_sha256"]})

    def test_every_user_read_contacts_nobody_and_writes_nothing_and_a_failed_source_shows_stale(self):
        failing = {**standard_feeds(), FED: [(500, b"down", {"content-type": "text/plain"})]}
        refreshed(self.root / "event-inbox", failing,
                  at=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc))
        made = self.user.post("/api/user/sources", headers=USER_WRITE, json=source_form())
        source_id = made.json()["source"]["source_id"]
        analysis = self.user.post("/api/user/analyses", headers=USER_WRITE,
                                  json={"source_id": source_id, "effort": "low"}).json()["analysis"]["analysis_id"]
        preview = self.preview(self.entry())
        self.assertEqual(preview.status_code, 201, preview.text)
        values = {"source_id": source_id, "analysis_id": analysis, "import_id": preview.json()["import"]["import_id"],
                  "story_id": self.curated[TARIFF], "topic_id": self.curated["topic_id"]}
        reads = sorted({route.path for route in self.user.app.routes if route.path.startswith("/api/user/") and
                        "GET" in getattr(route, "methods", ())})
        before = self.state()
        for path in reads:
            url = path.format(**values)
            queries = {"/api/user/news": ("?scope=interests", "?scope=all"),
                       "/api/user/news/stories": ("?view=hot", "?view=latest", "?view=interests")}
            for query in queries.get(path, ("",)):
                with self.subTest(url + query):
                    reply = self.user.get(url + query)
                    self.assertEqual(reply.status_code, 200, reply.text[:200])
        self.assertEqual(self.state(), before)  # No row, file, publisher request or provider request.
        self.assertGreaterEqual(len(reads), 16, reads)
        fed = next(row for row in self.user.get("/api/user/news?scope=all").json()["news"]["sources"]
                   if row["source"] == "fed-monetary")
        self.assertEqual((fed["state"], fed["stale"], fed["last_attempt"]["outcome"]), ("failed", True, "failed"))
        self.assertGreater(fed["entries"], 0)

    def test_one_search_sent_twice_at_once_counts_once(self):
        form = {"query": "synthetic", "interests": None, "sources": None, "listing": "all",
                "request_key": "qa-double-click-0001"}
        tabs, start = [self.client("reader-a"), self.client("reader-a")], threading.Barrier(2)

        def search(index: int):
            start.wait(5)
            return tabs[index].post("/api/user/news/searches", headers=USER_WRITE, json=form)

        with ThreadPoolExecutor(2) as pool:
            replies = list(pool.map(search, range(2)))
        self.assertEqual(sorted(reply.status_code for reply in replies), [200, 201], [r.text[:200] for r in replies])
        self.assertEqual(replies[0].json()["entries"], replies[1].json()["entries"])
        self.assertEqual(self.used("search"), 1)

    def test_one_preview_sent_twice_at_once_requests_the_page_once_and_counts_once(self):
        entry = self.entry()
        self.gate.release.clear()
        tabs = [self.client("reader-a"), self.client("reader-a")]
        with ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.preview, entry, tabs[0])
            self.assertTrue(self.gate.entered.wait(5))
            second = pool.submit(self.preview, entry, tabs[1])
            replies = [second.result(10)]  # Answered while the first still waits on the publisher.
            self.gate.release.set()
            replies.append(first.result(10))
        outcomes = sorted((reply.status_code, reply.json().get("code")) for reply in replies)
        self.assertEqual(outcomes, [(201, None), (409, "import_in_progress")], [r.text[:200] for r in replies])
        self.assertEqual(len(self.pages.requests), 1)
        self.assertEqual(self.used("import"), 1)
        self.assertEqual(usage.overview(self.world.accounts, self.root / "intake", self.world.clock())["server"][
            "publication_fetches"]["used"], 1)
        again = self.preview(entry)  # The page is kept now: the account's earlier preview, nothing requested.
        self.assertEqual((again.status_code, again.json()["created"], len(self.pages.requests)), (200, False, 1))

    def test_a_confirmation_over_the_storage_limit_creates_nothing_and_can_be_confirmed_later(self):
        preview = self.preview(self.entry()).json()["import"]
        held = usage.stored(self.world.accounts, self.root / "intake", self.world.ids["reader-a"])
        usage.add_policy(self.world.accounts, policy(max_source_bytes=held["source_bytes"] + 10),
                         self.world.ids["admin"], "SYNTHETIC: little room")
        confirm = lambda: self.user.post(  # noqa: E731
            f"/api/user/news/imports/{preview['import_id']}/confirmation", headers=USER_WRITE,
            json={"text_sha256": preview["proposed_source"]["text_sha256"], "confirm": True})
        refused = confirm()
        self.assertEqual((refused.status_code, refused.json().get("code"),
                          refused.json().get("storage", {}).get("measure")),
                         (409, "storage_limit_reached", "source_bytes"), refused.text[:300])
        self.assertEqual((self.used("source"), self.user.get("/api/user/sources").json()["sources"]), (0, []))
        usage.add_policy(self.world.accounts, USAGE_POLICY, self.world.ids["admin"], "SYNTHETIC: room again")
        accepted = confirm()
        self.assertEqual(accepted.status_code, 201, accepted.text[:300])
        self.assertEqual(accepted.json()["source"]["headline"], preview["proposed_source"]["headline"])
        self.assertEqual(self.used("source"), 1)

    def test_a_refused_search_body_writes_nothing(self):
        base = {"query": "synthetic", "interests": None, "sources": None, "listing": "all",
                "request_key": "qa-refused-search-01"}
        cases = {"an empty query": {"query": ""}, "nine words": {"query": " ".join(["word"] * 9)},
                 "a query of punctuation": {"query": "!!!"}, "a short request key": {"request_key": "short"},
                 "an unknown interest": {"interests": ["weather"]}, "an empty source list": {"sources": []},
                 "an unknown listing": {"listing": "everything"}}
        before = self.state()
        for label, change in cases.items():
            with self.subTest(label):
                reply = self.user.post("/api/user/news/searches", headers=USER_WRITE, json=base | change)
                self.assertEqual(reply.status_code, 422, reply.text[:200])
        self.assertEqual(self.state(), before)
        self.assertEqual(self.used("search"), 0)


if __name__ == "__main__":
    unittest.main()
