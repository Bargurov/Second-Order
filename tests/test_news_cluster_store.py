"""
tests/test_news_cluster_store.py

Focused tests for the persisted incremental news clustering store.

Covers the four cases the task brief calls out:

  1. Empty DB bootstrap                     (TestRefreshClusters.test_bootstrap_*)
  2. Incremental refresh clusters only new  (TestRefreshClusters.test_incremental_only_clusters_new)
  3. Existing clusters reused, not rerun    (TestRefreshClusters.test_known_headlines_reuse_payload)
  4. Unchanged output contract              (TestEndpointContract.*)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import news_cluster_store


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime(2026, 4, 8, 12, 0, 0)


def _rec(source: str, title: str, hours_ago: int = 1) -> dict:
    published = (_now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")
    return {
        "source": source,
        "title": title,
        "published_at": published,
        "url": f"https://example.com/{uuid.uuid4().hex[:8]}",
    }


# ---------------------------------------------------------------------------
# 1. refresh_clusters — bootstrap + incremental + reuse
# ---------------------------------------------------------------------------


class TestRefreshClusters(unittest.TestCase):
    """End-to-end behaviour of the incremental clustering store.

    Each test uses a fresh temp SQLite file so bootstrap behaviour is
    real (the store writes assignments and cluster rows to actual
    tables).  Clustering logic is injected via ``cluster_fn`` so we can
    observe call counts without hitting the real TF-IDF pipeline.
    """

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_news_cluster_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.cluster_calls: list[list[dict]] = []

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _fake_cluster_fn(self, records: list[dict]) -> list[dict]:
        """A stub clusterer that groups by the first word of the title.

        This keeps test expectations completely deterministic — no
        TF-IDF fuzziness — while still exercising every code path in
        refresh_clusters (new cluster insertion, merge into existing,
        sources aggregation).  The call list lets tests assert how
        many times we reclustered.
        """
        self.cluster_calls.append(list(records))
        groups: dict[str, list[dict]] = {}
        for rec in records:
            key = (rec["title"].split()[0] if rec["title"] else "?")
            groups.setdefault(key, []).append(rec)

        out: list[dict] = []
        for key, group in groups.items():
            # Pick the first record's title as representative.
            rep = max(group, key=lambda r: len(r["title"]))
            sources = [
                {"name": r["source"], "tier": "major", "url": r.get("url", "")}
                for r in group
            ]
            pub_dates = [r["published_at"] for r in group if r["published_at"]]
            published_at = max(pub_dates) if pub_dates else ""
            out.append({
                "headline":     rep["title"],
                "summary":      f"stub summary for {key}",
                "consensus":    {"subject": key},
                "sources":      sources,
                "published_at": published_at,
                "source_count": len(sources),
                "agreement":    "consistent",
                "evidence":     [],
            })
        return out

    def _refresh(self, records, *, recency_hours: int = 48):
        return news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._fake_cluster_fn,
            now=_now(),
            recency_hours=recency_hours,
        )

    # ------------------------------------------------------------------
    # Case 1: Empty DB bootstrap
    # ------------------------------------------------------------------

    def test_bootstrap_empty_db_clusters_everything(self):
        """First refresh against an empty DB clusters the whole batch once."""
        records = [
            _rec("BBC", "Tariffs imposed on steel"),
            _rec("Reuters", "Tariffs imposed on steel imports"),
            _rec("WSJ", "OPEC cuts oil production"),
        ]
        out = self._refresh(records)

        # cluster_fn called exactly once with the full batch
        self.assertEqual(len(self.cluster_calls), 1)
        self.assertEqual(len(self.cluster_calls[0]), 3)

        # Two clusters (Tariffs + OPEC), ordered multi-source first
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["source_count"], 2)  # Tariffs has 2 sources
        self.assertEqual(out[1]["source_count"], 1)  # OPEC solo

        # Assignments + cluster rows persisted
        assigns = db.load_news_headline_assignments()
        self.assertEqual(len(assigns), 3)
        clusters = db.load_news_clusters()
        self.assertEqual(len(clusters), 2)

    def test_bootstrap_empty_records_returns_empty(self):
        """Empty records list is a clean no-op."""
        out = self._refresh([])
        self.assertEqual(out, [])
        self.assertEqual(self.cluster_calls, [])
        self.assertEqual(db.load_news_clusters(), [])

    # ------------------------------------------------------------------
    # Case 2: Incremental refresh only clusters new headlines
    # ------------------------------------------------------------------

    def test_incremental_only_clusters_new(self):
        """Second refresh with only new headlines recluters just those."""
        self._refresh([
            _rec("BBC", "Tariffs imposed on steel"),
            _rec("Reuters", "Tariffs imposed on steel imports"),
        ])
        self.cluster_calls.clear()

        # Second call: the two known headlines plus one completely new one
        self._refresh([
            _rec("BBC", "Tariffs imposed on steel"),         # known
            _rec("Reuters", "Tariffs imposed on steel imports"),  # known
            _rec("FT", "Bananas banned from EU markets"),    # new
        ])

        # cluster_fn was called with JUST the new record
        self.assertEqual(len(self.cluster_calls), 1)
        self.assertEqual(len(self.cluster_calls[0]), 1)
        self.assertEqual(
            self.cluster_calls[0][0]["title"], "Bananas banned from EU markets",
        )

    def test_incremental_nothing_new_skips_clustering(self):
        """A refresh where every record is already assigned calls cluster_fn zero times."""
        records = [
            _rec("BBC", "Tariffs imposed on steel"),
            _rec("Reuters", "Tariffs imposed on steel imports"),
        ]
        self._refresh(records)
        self.cluster_calls.clear()

        out = self._refresh(records)  # identical batch
        self.assertEqual(self.cluster_calls, [])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_count"], 2)

    def test_new_source_merges_into_existing_cluster(self):
        """A new source joining an existing headline updates the cluster in place."""
        self._refresh([
            _rec("BBC", "Tariffs imposed on steel"),
        ])
        # Before: 1 cluster, 1 source
        before = db.load_news_clusters()
        self.assertEqual(len(before), 1)
        self.assertEqual(before[0]["payload"]["source_count"], 1)

        self.cluster_calls.clear()
        self._refresh([
            _rec("BBC", "Tariffs imposed on steel"),         # known
            _rec("Reuters", "Tariffs imposed on steel imports"),  # new, should merge
        ])

        after = db.load_news_clusters()
        self.assertEqual(len(after), 1, "Merge must not create a new cluster row")
        self.assertEqual(after[0]["payload"]["source_count"], 2)
        source_names = {s["name"] for s in after[0]["payload"]["sources"]}
        self.assertIn("BBC", source_names)
        self.assertIn("Reuters", source_names)

    # ------------------------------------------------------------------
    # Case 3: Existing clusters reused instead of full recluster
    # ------------------------------------------------------------------

    def test_known_headlines_reuse_payload(self):
        """Known records return their stored cluster payload without rebuilding it."""
        records = [
            _rec("BBC", "Tariffs imposed on steel"),
            _rec("Reuters", "Tariffs imposed on steel imports"),
            _rec("WSJ", "OPEC cuts oil production"),
        ]
        first = self._refresh(records)
        self.cluster_calls.clear()
        second = self._refresh(records)

        # No cluster_fn calls on the second pass (nothing new)
        self.assertEqual(self.cluster_calls, [])
        # Output content is the same set of cluster headlines
        self.assertEqual(
            {c["headline"] for c in first},
            {c["headline"] for c in second},
        )

    def test_aged_out_cluster_dropped_from_output(self):
        """Clusters whose latest published_at is past the recency cutoff don't surface."""
        old_records = [
            _rec("BBC", "Ancient headline about tariffs", hours_ago=100),
        ]
        self._refresh(old_records, recency_hours=48)
        # The cluster is in the DB but outside the 48h window
        live = self._refresh([], recency_hours=48)
        self.assertEqual(live, [])
        # ... and a 200h window still returns it
        wider = self._refresh([], recency_hours=200)
        self.assertEqual(len(wider), 1)

    def test_output_sorted_multi_source_first_then_newest(self):
        """Output order: multi-source clusters ahead of single, newest first within."""
        # Solo new cluster (1 source), published more recently
        # Multi-source cluster (2 sources), published earlier
        self._refresh([
            _rec("BBC", "Old story about OPEC", hours_ago=10),
            _rec("Reuters", "Old story about OPEC details", hours_ago=9),
            _rec("FT", "Brand new single-source headline", hours_ago=1),
        ])
        out = self._refresh([], recency_hours=48)
        self.assertEqual(len(out), 2)
        # Multi-source OPEC cluster ranks first
        self.assertEqual(out[0]["source_count"], 2)
        self.assertEqual(out[1]["source_count"], 1)

    def test_provider_failure_in_new_batch_returns_existing(self):
        """A crashing cluster_fn on the new batch falls back to the existing active set."""
        # Two completely non-overlapping topics so the real TF-IDF
        # merge step inside refresh_clusters keeps them in separate
        # clusters on the seed pass.
        self._refresh([
            _rec("BBC", "Tariffs imposed on steel imports"),
            _rec("Reuters", "OPEC cuts oil production targets"),
        ])
        seed_cluster_count = len(db.load_news_clusters())
        self.assertEqual(seed_cluster_count, 2)
        self.cluster_calls.clear()

        def _boom(records):
            raise RuntimeError("simulated clusterer failure")

        out = news_cluster_store.refresh_clusters(
            [_rec("WSJ", "Moon mission launches next week")],
            cluster_fn=_boom,
            now=_now(),
        )
        # Existing active clusters still returned
        self.assertEqual(len(out), seed_cluster_count)
        # No cluster row was added for the failed new batch
        self.assertEqual(len(db.load_news_clusters()), seed_cluster_count)


# ---------------------------------------------------------------------------
# 2. DB integration
# ---------------------------------------------------------------------------


class TestDbNewsClusterStore(unittest.TestCase):
    """Schema migration + CRUD helpers round-trip through SQLite."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_news_db_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_tables_exist(self):
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('news_clusters', 'news_headline_assignments')"
            ).fetchall()
        self.assertEqual(
            {r[0] for r in rows},
            {"news_clusters", "news_headline_assignments"},
        )

    def test_insert_load_round_trip(self):
        payload = {
            "headline": "Test cluster", "summary": "s",
            "sources": [{"name": "BBC", "tier": "major", "url": ""}],
            "published_at": "2026-04-08T10:00:00",
            "source_count": 1, "agreement": "consistent", "evidence": [],
        }
        records = [{"source": "BBC", "title": "Test cluster",
                    "published_at": "2026-04-08T10:00:00", "url": ""}]
        cid = db.insert_news_cluster(
            "Test cluster", payload, records, "2026-04-08T10:00:00",
            "2026-04-08T10:00:00",
        )
        self.assertIsInstance(cid, int)

        loaded = db.load_news_clusters()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["headline"], "Test cluster")
        self.assertEqual(loaded[0]["payload"]["source_count"], 1)
        self.assertEqual(loaded[0]["records"], records)

    def test_update_cluster(self):
        cid = db.insert_news_cluster(
            "Original", {"headline": "Original", "source_count": 1}, [],
            "2026-04-08T10:00:00", "2026-04-08T10:00:00",
        )
        ok = db.update_news_cluster(
            cid, "Updated", {"headline": "Updated", "source_count": 2},
            [{"source": "BBC", "title": "Updated"}],
            "2026-04-08T11:00:00", "2026-04-08T11:00:00",
        )
        self.assertTrue(ok)
        loaded = db.load_news_clusters()
        self.assertEqual(loaded[0]["headline"], "Updated")
        self.assertEqual(loaded[0]["payload"]["source_count"], 2)

    def test_recency_cutoff_filters_old_clusters(self):
        db.insert_news_cluster(
            "Old", {"headline": "Old"}, [],
            "2026-04-01T00:00:00", "2026-04-01T00:00:00",
        )
        db.insert_news_cluster(
            "Recent", {"headline": "Recent"}, [],
            "2026-04-08T11:00:00", "2026-04-08T11:00:00",
        )
        all_rows = db.load_news_clusters()
        self.assertEqual(len(all_rows), 2)
        recent_only = db.load_news_clusters(recency_cutoff="2026-04-07T00:00:00")
        self.assertEqual(len(recent_only), 1)
        self.assertEqual(recent_only[0]["headline"], "Recent")

    def test_assignment_round_trip(self):
        db.upsert_news_headline_assignments(
            [("BBC", "tariffs imposed", 1), ("Reuters", "opec cuts", 2)],
            "2026-04-08T10:00:00",
        )
        out = db.load_news_headline_assignments()
        self.assertEqual(out[("BBC", "tariffs imposed")], 1)
        self.assertEqual(out[("Reuters", "opec cuts")], 2)

    def test_assignment_reassignment(self):
        """Upsert replaces an existing (source, title_key) row."""
        db.upsert_news_headline_assignments(
            [("BBC", "tariffs", 1)], "2026-04-08T10:00:00",
        )
        db.upsert_news_headline_assignments(
            [("BBC", "tariffs", 5)], "2026-04-08T11:00:00",
        )
        out = db.load_news_headline_assignments()
        self.assertEqual(out[("BBC", "tariffs")], 5)

    def test_delete_cluster_also_clears_assignments(self):
        cid = db.insert_news_cluster(
            "X", {"headline": "X"}, [], "2026-04-08T10:00:00", "2026-04-08T10:00:00",
        )
        db.upsert_news_headline_assignments(
            [("BBC", "x", cid)], "2026-04-08T10:00:00",
        )
        self.assertTrue(db.delete_news_cluster(cid))
        self.assertEqual(db.load_news_clusters(), [])
        self.assertEqual(db.load_news_headline_assignments(), {})

    def test_clear_news_cluster_store(self):
        db.insert_news_cluster("A", {}, [], "2026-04-08T10:00:00", "2026-04-08T10:00:00")
        db.upsert_news_headline_assignments(
            [("BBC", "a", 1)], "2026-04-08T10:00:00",
        )
        db.clear_news_cluster_store()
        self.assertEqual(db.load_news_clusters(), [])
        self.assertEqual(db.load_news_headline_assignments(), {})

    def test_corrupt_payload_is_skipped_on_load(self):
        """A row with malformed JSON is skipped rather than crashing."""
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "INSERT INTO news_clusters "
                "(headline, payload_json, records_json, latest_published_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("broken", "{not json", "[]", "2026-04-08T10:00:00", "2026-04-08T10:00:00"),
            )
        self.assertEqual(db.load_news_clusters(), [])


# ---------------------------------------------------------------------------
# 3. Output contract — /news endpoint stability
# ---------------------------------------------------------------------------


class TestNewsEndpointContract(unittest.TestCase):
    """Stability of /news response shape across the cluster store refactor."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_news_contract_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        # Reset refresh guard so tests don't interfere with each other
        import api as _api
        _api._last_refresh_at = 0.0
        _api._last_refresh_payload = None
        self._api_mod = _api

    def _expire_cooldown(self):
        """Reset the refresh cooldown so the next POST /news/refresh runs fresh."""
        self._api_mod._last_refresh_at = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_shape_preserved(self):
        """Response body still contains clusters, total_headlines, feed_status, total_count."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "Test contract A",
             "published_at": "2026-04-08T11:00:00", "url": ""},
            {"source": "Reuters", "title": "Test contract A details",
             "published_at": "2026-04-08T11:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
            {"name": "Reuters", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.get("/news")

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("clusters", body)
        self.assertIn("total_headlines", body)
        self.assertIn("feed_status", body)
        self.assertIn("total_count", body)
        self.assertEqual(len(body["clusters"]), body["total_count"])

    def test_cluster_entries_have_frontend_visible_keys(self):
        """Every cluster carries the keys the frontend consumes."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "Keys test A",
             "published_at": "2026-04-08T11:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        fake_clusters = [{
            "headline": "Keys test A",
            "summary": "summary",
            "consensus": {},
            "sources": [{"name": "BBC", "tier": "major", "url": ""}],
            "published_at": "2026-04-08T11:00:00",
            "source_count": 1,
            "agreement": "consistent",
            "evidence": [],
        }]
        with patch("api.fetch_all", return_value=(records, feed_status)), \
                patch("api.cluster_headlines", return_value=fake_clusters):
            r = self.client.get("/news")

        body = r.json()
        self.assertEqual(len(body["clusters"]), 1)
        c = body["clusters"][0]
        for key in ("headline", "sources", "source_count"):
            self.assertIn(key, c)

    def test_news_refresh_still_invokes_fetch(self):
        """POST /news/refresh goes through the full incremental path."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "Refresh path test",
             "published_at": "2026-04-08T11:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r1 = self.client.post("/news/refresh")
            self._expire_cooldown()
            r2 = self.client.post("/news/refresh")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Second call should still return the same cluster (known headline)
        self.assertEqual(r1.json()["total_headlines"], 1)
        self.assertEqual(r2.json()["total_headlines"], 1)
        self.assertGreaterEqual(len(r2.json()["clusters"]), 1)

    # ------------------------------------------------------------------
    # Refresh metadata
    # ------------------------------------------------------------------

    def test_refresh_meta_present(self):
        """POST /news/refresh returns refresh_meta in the response."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "Meta test headline",
             "published_at": "2026-04-10T10:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        self.assertEqual(r.status_code, 200)
        meta = r.json().get("refresh_meta")
        self.assertIsNotNone(meta, "refresh_meta missing from response")
        for key in ("known", "new", "merged", "created", "reused", "source"):
            self.assertIn(key, meta, f"refresh_meta missing key: {key}")

    def test_refresh_meta_first_call_creates(self):
        """First refresh with new headlines reports source=incremental."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "First call test",
             "published_at": "2026-04-10T10:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["new"], 1)
        self.assertEqual(meta["known"], 0)
        self.assertEqual(meta["created"], 1)
        self.assertEqual(meta["source"], "incremental")

    def test_refresh_meta_second_call_reuses(self):
        """Second refresh with same headlines reports known > 0, new = 0."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "Reuse test headline",
             "published_at": "2026-04-10T10:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            self.client.post("/news/refresh")
            self._expire_cooldown()
            r2 = self.client.post("/news/refresh")

        meta = r2.json()["refresh_meta"]
        self.assertEqual(meta["known"], 1)
        self.assertEqual(meta["new"], 0)
        self.assertGreaterEqual(meta["reused"], 1)
        self.assertIn(meta["source"], ("stored", "stored_fallback"))

    def test_refresh_meta_stored_fallback(self):
        """When clusters age out of recency, fallback path is labeled."""
        from unittest.mock import patch

        # Use an old published_at so clusters fall outside the 48h window
        records = [
            {"source": "BBC", "title": "Fallback test headline",
             "published_at": "2026-04-07T10:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            self.client.post("/news/refresh")
            self._expire_cooldown()
            r2 = self.client.post("/news/refresh")

        meta = r2.json()["refresh_meta"]
        self.assertEqual(meta["source"], "stored_fallback")
        self.assertGreaterEqual(len(r2.json()["clusters"]), 1)

    def test_get_news_includes_refresh_meta(self):
        """GET /news passes through refresh_meta from the cached payload."""
        from unittest.mock import patch

        records = [
            {"source": "BBC", "title": "GET meta passthrough",
             "published_at": "2026-04-10T10:00:00", "url": ""},
        ]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
        ]
        # Force a fresh fetch by clearing the cache
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.get("/news")

        self.assertEqual(r.status_code, 200)
        meta = r.json().get("refresh_meta")
        self.assertIsNotNone(meta, "GET /news should include refresh_meta")
        self.assertIn("source", meta)

    def test_get_news_synthesizes_meta_on_legacy_cache(self):
        """GET /news from a legacy cache (no refresh_meta) synthesizes one."""
        # Populate in-memory cache with a payload that has no refresh_meta
        self.api._news_cache["data"] = {
            "clusters": [{"headline": "cached", "sources": [], "source_count": 0}],
            "total_headlines": 1,
            "feed_status": [],
        }
        import time
        self.api._news_cache["ts"] = time.monotonic()

        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        meta = r.json().get("refresh_meta")
        self.assertIsNotNone(meta, "refresh_meta should always be present")
        self.assertEqual(meta["freshness"], "stale")
        self.assertEqual(meta["source"], "cached_fallback")

    # ------------------------------------------------------------------
    # Refresh status: ok / degraded / error
    # ------------------------------------------------------------------

    def test_refresh_status_ok_on_success(self):
        """All feeds succeed → status=ok."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Status ok test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["ok_feeds"], 1)
        self.assertEqual(meta["fail_feeds"], 0)
        self.assertNotIn("error", meta)

    def test_refresh_status_degraded_on_partial_failure(self):
        """Some feeds fail → status=degraded."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Degraded test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
            {"name": "Reuters", "url": "", "ok": False, "count": 0, "error": "timeout"},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["status"], "degraded")
        self.assertEqual(meta["ok_feeds"], 1)
        self.assertEqual(meta["fail_feeds"], 1)
        self.assertIn("error", meta)
        # Clusters should still be returned
        self.assertGreaterEqual(len(r.json()["clusters"]), 1)

    def test_refresh_status_error_all_feeds_fail(self):
        """All feeds fail → status=error, clusters still returned if any."""
        from unittest.mock import patch

        records = []
        feed_status = [
            {"name": "BBC", "url": "", "ok": False, "count": 0, "error": "timeout"},
            {"name": "Reuters", "url": "", "ok": False, "count": 0, "error": "timeout"},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        self.assertEqual(r.status_code, 200)
        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["status"], "error")
        self.assertIn("error", meta)

    def test_refresh_status_error_fetch_raises(self):
        """fetch_all() raises → status=error, returns last cached data."""
        from unittest.mock import patch

        # Seed the cache with known data first
        records = [{"source": "BBC", "title": "Seed for fallback",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r1 = self.client.post("/news/refresh")
        self.assertEqual(r1.status_code, 200)
        self.assertGreaterEqual(len(r1.json()["clusters"]), 1)

        # Now make fetch_all raise
        self._expire_cooldown()
        with patch("api.fetch_all", side_effect=ConnectionError("network down")):
            r2 = self.client.post("/news/refresh")

        self.assertEqual(r2.status_code, 200)
        meta = r2.json()["refresh_meta"]
        self.assertEqual(meta["status"], "error")
        self.assertEqual(meta["source"], "cached_fallback")
        # Clusters from the previous seed should be returned
        self.assertGreaterEqual(len(r2.json()["clusters"]), 1)

    def test_refresh_status_error_fetch_raises_no_cache(self):
        """fetch_all() raises with no prior cache → empty response."""
        from unittest.mock import patch

        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        with patch("api.fetch_all", side_effect=ConnectionError("network down")):
            r = self.client.post("/news/refresh")

        self.assertEqual(r.status_code, 200)
        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["status"], "error")
        self.assertEqual(meta["source"], "empty")
        self.assertEqual(r.json()["clusters"], [])

    # ------------------------------------------------------------------
    # Freshness metadata
    # ------------------------------------------------------------------

    def test_freshness_fresh_on_success(self):
        """Successful refresh stamps freshness=fresh + last_successful_refresh."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Freshness test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["freshness"], "fresh")
        self.assertIsNotNone(meta["last_successful_refresh"])
        # Timestamp should be a valid ISO string
        from datetime import datetime
        datetime.fromisoformat(meta["last_successful_refresh"])

    def test_freshness_stale_on_error(self):
        """Failed refresh marks freshness=stale."""
        from unittest.mock import patch

        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        with patch("api.fetch_all", side_effect=ConnectionError("down")):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["freshness"], "stale")

    def test_freshness_preserves_last_success_on_error(self):
        """When refresh fails, last_successful_refresh from prior success is kept."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Prior success",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r1 = self.client.post("/news/refresh")
        prev_ts = r1.json()["refresh_meta"]["last_successful_refresh"]
        self.assertIsNotNone(prev_ts)

        # Now fail
        self._expire_cooldown()
        with patch("api.fetch_all", side_effect=ConnectionError("down")):
            r2 = self.client.post("/news/refresh")

        meta = r2.json()["refresh_meta"]
        self.assertEqual(meta["freshness"], "stale")
        self.assertEqual(meta["last_successful_refresh"], prev_ts)

    def test_freshness_degraded_on_partial_failure(self):
        """Partial feed failure marks freshness=degraded."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Partial test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [
            {"name": "BBC", "url": "", "ok": True, "count": 1, "error": None},
            {"name": "Reuters", "url": "", "ok": False, "count": 0, "error": "timeout"},
        ]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["freshness"], "degraded")
        self.assertIsNotNone(meta["last_successful_refresh"])

    # ------------------------------------------------------------------
    # Refresh throttle / dedup
    # ------------------------------------------------------------------

    def test_immediate_repeat_refresh_returns_recent(self):
        """Calling refresh twice in quick succession returns status=recent."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Throttle test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r1 = self.client.post("/news/refresh")
            r2 = self.client.post("/news/refresh")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.json()["refresh_meta"]["status"], "ok")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["refresh_meta"]["status"], "recent")
        # Clusters still present on the throttled response
        self.assertGreaterEqual(len(r2.json()["clusters"]), 1)

    def test_refresh_after_cooldown_runs_normally(self):
        """After the cooldown window, refresh runs a fresh fetch."""
        from unittest.mock import patch
        import api as _api

        records = [{"source": "BBC", "title": "Cooldown test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r1 = self.client.post("/news/refresh")

        self.assertEqual(r1.json()["refresh_meta"]["status"], "ok")

        # Simulate cooldown expiry
        _api._last_refresh_at = 0.0

        records2 = [{"source": "BBC", "title": "Cooldown test 2",
                      "published_at": "2026-04-10T11:00:00", "url": ""}]
        with patch("api.fetch_all", return_value=(records2, feed_status)):
            r2 = self.client.post("/news/refresh")

        # Should run a real refresh, not return "recent"
        self.assertEqual(r2.json()["refresh_meta"]["status"], "ok")

    def test_normal_refresh_still_works(self):
        """Single refresh call returns ok with clusters (regression check)."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Normal regression test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.post("/news/refresh")

        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["refresh_meta"]["status"], "ok")
        self.assertGreaterEqual(len(body["clusters"]), 1)
        self.assertEqual(body["total_headlines"], 1)
        self.assertIn("feed_status", body)

    # ------------------------------------------------------------------
    # Initial-load metadata (GET /news always carries refresh_meta)
    # ------------------------------------------------------------------

    def test_get_news_always_has_refresh_meta(self):
        """GET /news always returns refresh_meta, even on cold start."""
        from unittest.mock import patch

        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        records = [{"source": "BBC", "title": "Initial load test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            r = self.client.get("/news")

        self.assertEqual(r.status_code, 200)
        meta = r.json().get("refresh_meta")
        self.assertIsNotNone(meta)
        self.assertIn("status", meta)
        self.assertIn("freshness", meta)
        self.assertIn("last_successful_refresh", meta)

    def test_get_news_meta_persists_across_cache_reads(self):
        """After refresh, subsequent GET /news returns the same meta."""
        from unittest.mock import patch

        records = [{"source": "BBC", "title": "Persist meta test",
                     "published_at": "2026-04-10T10:00:00", "url": ""}]
        feed_status = [{"name": "BBC", "url": "", "ok": True, "count": 1, "error": None}]
        with patch("api.fetch_all", return_value=(records, feed_status)):
            self.client.post("/news/refresh")
            r = self.client.get("/news")

        meta = r.json()["refresh_meta"]
        self.assertEqual(meta["status"], "ok")
        self.assertEqual(meta["freshness"], "fresh")


# ---------------------------------------------------------------------------
# 4. Payload/records consistency — inflated payload guard
# ---------------------------------------------------------------------------


class TestPayloadRecordsConsistency(unittest.TestCase):
    """Payload source_count/sources/evidence must match records_json."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_news_consistency_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        self.cluster_calls: list[list[dict]] = []

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _mega_cluster_fn(self, records: list[dict]) -> list[dict]:
        """A clusterer that inflates sources — simulates a mega-cluster.

        Returns a single cluster claiming 30 sources even when only 2
        records are passed.  This reproduces the observed production bug.
        """
        self.cluster_calls.append(list(records))
        fake_sources = [
            {"name": f"Feed_{i}", "tier": "high", "url": ""}
            for i in range(30)
        ]
        for r in records:
            fake_sources.append(
                {"name": r["source"], "tier": "high", "url": r.get("url", "")}
            )
        pub_dates = [r["published_at"] for r in records if r.get("published_at")]
        published_at = max(pub_dates) if pub_dates else ""
        rep = records[0] if records else {"title": "?", "source": "?"}
        return [{
            "headline": rep["title"],
            "summary": "stub",
            "consensus": {},
            "sources": fake_sources,
            "published_at": published_at,
            "source_count": len(fake_sources),
            "agreement": "consistent",
            "evidence": [
                {"source": "Feed_0", "tier": "high", "title": "Unrelated A",
                 "published_at": published_at, "note": ""},
                {"source": "Feed_1", "tier": "high", "title": "Unrelated B",
                 "published_at": published_at, "note": ""},
                {"source": rep["source"], "tier": "high", "title": rep["title"],
                 "published_at": published_at, "note": ""},
            ],
        }]

    def test_insert_sanitizes_inflated_payload(self):
        """INSERT: cluster_fn returns 30+ sources but only 2 records exist.

        Stored and returned payload must reflect the 2 actual records.
        """
        records = [
            _rec("BBC", "Tariffs imposed on EU steel"),
            _rec("Reuters", "Tariffs imposed on EU steel imports"),
        ]
        out = news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._mega_cluster_fn,
            now=_now(),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_count"], 2)
        source_names = {s["name"] for s in out[0]["sources"]}
        self.assertEqual(source_names, {"BBC", "Reuters"})

        stored = db.load_news_clusters()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["payload"]["source_count"], 2)
        stored_names = {s["name"] for s in stored[0]["payload"]["sources"]}
        self.assertEqual(stored_names, {"BBC", "Reuters"})

    def test_load_sanitizes_corrupted_stored_cluster(self):
        """LOAD: existing DB row has inflated payload_json. Return path
        must sanitize it so source_count matches records."""
        import sqlite3

        inflated_payload = {
            "headline": "Test corruption",
            "summary": "s",
            "sources": [{"name": f"Feed_{i}", "tier": "high", "url": ""} for i in range(30)],
            "published_at": "2026-04-08T11:00:00",
            "source_count": 30,
            "agreement": "consistent",
            "evidence": [
                {"source": "Feed_0", "title": "Ghost evidence",
                 "published_at": "2026-04-08T11:00:00", "note": "", "tier": "high"},
            ],
        }
        real_records = [
            {"source": "BBC", "title": "Test corruption",
             "published_at": "2026-04-08T11:00:00", "url": ""},
            {"source": "Reuters", "title": "Test corruption details",
             "published_at": "2026-04-08T11:00:00", "url": ""},
        ]
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "INSERT INTO news_clusters "
                "(headline, payload_json, records_json, latest_published_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "Test corruption",
                    json.dumps(inflated_payload),
                    json.dumps(real_records),
                    "2026-04-08T11:00:00",
                    "2026-04-08T11:00:00",
                ),
            )
        db.upsert_news_headline_assignments(
            [("BBC", "test corruption", 1), ("Reuters", "test corruption details", 1)],
            "2026-04-08T11:00:00",
        )

        out = news_cluster_store.refresh_clusters(
            [_rec("BBC", "Test corruption"), _rec("Reuters", "Test corruption details")],
            cluster_fn=lambda recs: [],
            now=_now(),
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["source_count"], 2)
        source_names = {s["name"] for s in out[0]["sources"]}
        self.assertEqual(source_names, {"BBC", "Reuters"})

    def test_evidence_filtered_to_record_sources(self):
        """Evidence entries from non-record sources must be removed."""
        records = [
            _rec("BBC", "Oil prices surge on Iran conflict"),
        ]
        out = news_cluster_store.refresh_clusters(
            records,
            cluster_fn=self._mega_cluster_fn,
            now=_now(),
        )
        self.assertEqual(len(out), 1)
        evidence = out[0].get("evidence", [])
        for ev in evidence:
            self.assertEqual(ev["source"], "BBC",
                             f"Evidence from non-record source: {ev['source']}")
        ev_titles = [e["title"] for e in evidence]
        self.assertNotIn("Unrelated A", ev_titles)
        self.assertNotIn("Unrelated B", ev_titles)

    def test_evidence_same_source_wrong_title_filtered(self):
        """Evidence from the correct source but a different title must be filtered.

        Reproduces the production case where CNBC evidence cited
        'self-defense strikes in Iran' while the actual CNBC record was
        'I never heard of the Strait of Hormuz'.
        """
        payload = {
            "headline": "Hormuz supply chain shock",
            "sources": [{"name": "CNBC", "tier": "high", "url": ""}],
            "source_count": 1,
            "evidence": [
                {"source": "CNBC", "tier": "high",
                 "title": "Self-defense strikes in Iran",
                 "published_at": "2026-05-26", "note": ""},
            ],
        }
        records = [{"source": "CNBC", "title": "Hormuz supply chain shock",
                    "published_at": "2026-05-26", "url": ""}]
        result = news_cluster_store._sanitize_payload(payload, records)
        self.assertEqual(result["evidence"], [],
                         "Same-source evidence with a different title must be removed")

    def test_inflated_payload_does_not_outrank_genuine(self):
        """After sanitization, a 1-source cluster must not outrank a genuine 2-source."""

        def _honest_cluster_fn(records: list[dict]) -> list[dict]:
            groups: dict[str, list[dict]] = {}
            for rec in records:
                key = rec["title"].split()[0] if rec["title"] else "?"
                groups.setdefault(key, []).append(rec)

            out: list[dict] = []
            for key, group in groups.items():
                rep = max(group, key=lambda r: len(r["title"]))
                sources = [
                    {"name": r["source"], "tier": "high", "url": r.get("url", "")}
                    for r in group
                ]
                pub_dates = [r["published_at"] for r in group if r["published_at"]]
                published_at = max(pub_dates) if pub_dates else ""
                out.append({
                    "headline": rep["title"],
                    "summary": f"stub for {key}",
                    "consensus": {},
                    "sources": sources,
                    "published_at": published_at,
                    "source_count": len(sources),
                    "agreement": "consistent",
                    "evidence": [],
                })
            return out

        genuine_multi = [
            _rec("BBC", "Genuine multi-source tariff story"),
            _rec("Reuters", "Genuine multi-source tariff details"),
        ]
        out1 = news_cluster_store.refresh_clusters(
            genuine_multi,
            cluster_fn=_honest_cluster_fn,
            now=_now(),
        )
        self.assertEqual(out1[0]["source_count"], 2)

        single_inflated = _rec("FT", "Single inflated story about oil")
        out2 = news_cluster_store.refresh_clusters(
            genuine_multi + [single_inflated],
            cluster_fn=self._mega_cluster_fn,
            now=_now(),
        )
        top = out2[0]
        self.assertEqual(top["source_count"], 2,
                         "Genuine 2-source cluster must rank above sanitized 1-source")

    def test_sanitize_payload_empty_records(self):
        """Empty records -> source_count=0, no sources, no evidence."""
        inflated = {
            "headline": "Ghost",
            "sources": [{"name": "Feed_0", "tier": "high", "url": ""}],
            "source_count": 1,
            "evidence": [{"source": "Feed_0", "title": "Ghost", "published_at": "", "note": ""}],
        }
        result = news_cluster_store._sanitize_payload(inflated, [])
        self.assertEqual(result["source_count"], 0)
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
