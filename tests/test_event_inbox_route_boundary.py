"""GET /news/inbox — local-state-only boundary tests.

The inbox GET must be network-free, provider-free and write-free: it reads the
persisted ``news_clusters`` store through a read-only SQLite connection and
NEVER touches RSS, a provider, the news refresh path, or any writer.  These
tests prove that with seam recorders (any refresh/fetch/write call raises) and
a bytes-identical database before/after the request.

DB isolation: every test points ``db.DB_FILE`` at its own temporary file; the
live ``events.db`` is never opened here.
"""

import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

import api as _api
import db as _db
import event_inbox

_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "fixtures", "event_inbox_cluster_rows.json")
_FRONTEND_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "frontend", "src", "lib",
    "__tests__", "fixtures", "automatic-event-inbox-v2.json")

# Frozen clock for the shared cross-layer fixture: noon on the day the
# captured rows' latest publications land, so lifecycle ages are stable.
_FIXTURE_NOW = datetime(2026, 7, 7, 12, 0, 0)


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _seed_db(path: str, rows: list[dict]) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS news_clusters ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " headline TEXT NOT NULL,"
        " payload_json TEXT NOT NULL,"
        " records_json TEXT NOT NULL DEFAULT '[]',"
        " latest_published_at TEXT,"
        " updated_at TEXT NOT NULL)")
    for r in rows:
        conn.execute(
            "INSERT INTO news_clusters "
            "(id, headline, payload_json, records_json, latest_published_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (r["id"], r["headline"], json.dumps(r["payload"]),
             json.dumps(r["records"]), r["latest_published_at"], r["updated_at"]))
    conn.commit()
    conn.close()


def _fixture_rows() -> list[dict]:
    with open(_FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)["rows"]


def _raise(name):
    def _inner(*a, **k):
        raise AssertionError(f"GET /news/inbox must never call {name}")
    return _inner


class _InboxRouteBase(unittest.TestCase):
    """Temp DB + seam recorders proving no fetch / no write."""

    seed_rows: list[dict] = []

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(prefix="test_event_inbox_", suffix=".db")
        os.close(fd)
        os.unlink(self.db_path)
        _seed_db(self.db_path, self.seed_rows)
        self._patches = [
            patch.object(_db, "DB_FILE", self.db_path),
            # Provider / network seams: any call is a boundary violation.
            patch.object(_api, "_fetch_fresh_news", _raise("_fetch_fresh_news")),
            patch("news_sources.fetch_all", _raise("news_sources.fetch_all")),
            # Writer seams: any call is a boundary violation.
            patch.object(_db, "insert_news_cluster", _raise("insert_news_cluster")),
            patch.object(_db, "update_news_cluster", _raise("update_news_cluster")),
            patch.object(_db, "upsert_news_headline_assignments",
                         _raise("upsert_news_headline_assignments")),
            patch.object(_api, "save_news_cache", _raise("save_news_cache")),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(_api.app)
        self.pre_hash = _sha256(self.db_path)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass

    def assert_db_untouched(self):
        self.assertEqual(_sha256(self.db_path), self.pre_hash,
                         "GET /news/inbox mutated the local database")


class TestInboxGetBoundary(_InboxRouteBase):
    seed_rows = _fixture_rows()

    def test_get_inbox_is_local_state_only(self):
        resp = self.client.get("/news/inbox")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["contract"], "automatic-event-inbox-v2")
        self.assertEqual(payload["availability"], "AVAILABLE")
        self.assert_db_untouched()

    def test_get_inbox_serves_captured_rows_without_refresh(self):
        with patch.object(event_inbox, "_now", return_value=_FIXTURE_NOW):
            resp = self.client.get("/news/inbox")
        payload = resp.json()
        self.assertGreater(len(payload["events"]), 0)
        surfaced_ids = {ev["cluster_id"] for ev in payload["events"]}
        self.assertIn(13504, surfaced_ids)
        self.assert_db_untouched()

    def test_no_post_route_exists_for_inbox(self):
        resp = self.client.post("/news/inbox")
        self.assertEqual(resp.status_code, 405)
        self.assert_db_untouched()


class TestInboxEmptyStore(_InboxRouteBase):
    seed_rows = []

    def test_empty_store_is_valid_empty_state(self):
        resp = self.client.get("/news/inbox")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["availability"], "AVAILABLE")
        self.assertEqual(payload["events"], [])
        self.assertEqual(payload["counts"]["parent_clusters_total"], 0)
        self.assertEqual(payload["counts"]["candidates_total"], 0)
        self.assert_db_untouched()


class TestInboxMissingStore(unittest.TestCase):
    def test_missing_local_database_is_explicit_unavailable(self):
        missing = os.path.join(tempfile.gettempdir(),
                               "test_event_inbox_missing_does_not_exist.db")
        self.assertFalse(os.path.exists(missing))
        with patch.object(_db, "DB_FILE", missing), \
             patch.object(_api, "_fetch_fresh_news", _raise("_fetch_fresh_news")), \
             patch("news_sources.fetch_all", _raise("news_sources.fetch_all")):
            client = TestClient(_api.app)
            resp = client.get("/news/inbox")
        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["availability"], "UNAVAILABLE")
        self.assertEqual(payload["events"], [])
        self.assertFalse(os.path.exists(missing),
                         "GET /news/inbox created a database file")

    def test_missing_table_is_explicit_unavailable(self):
        fd, path = tempfile.mkstemp(prefix="test_event_inbox_notable_", suffix=".db")
        os.close(fd)
        sqlite3.connect(path).close()  # empty DB, no news_clusters table
        try:
            pre = _sha256(path)
            with patch.object(_db, "DB_FILE", path):
                client = TestClient(_api.app)
                resp = client.get("/news/inbox")
            payload = resp.json()
            self.assertEqual(payload["availability"], "UNAVAILABLE")
            self.assertEqual(payload["events"], [])
            self.assertEqual(_sha256(path), pre)
        finally:
            os.unlink(path)


class TestCrossLayerParityFixture(_InboxRouteBase):
    """The committed frontend fixture IS the captured real producer payload."""

    seed_rows = _fixture_rows()

    def test_committed_frontend_fixture_matches_real_producer_output(self):
        with patch.object(event_inbox, "_now", return_value=_FIXTURE_NOW):
            resp = self.client.get("/news/inbox")
        payload = resp.json()
        with open(_FRONTEND_FIXTURE_PATH, encoding="utf-8") as fh:
            fixture = json.load(fh)
        self.assertEqual(
            payload, fixture,
            "real GET /news/inbox output drifted from the shared cross-layer "
            "fixture the frontend validator imports")
        self.assert_db_untouched()


if __name__ == "__main__":
    unittest.main()
