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
            r2 = self.client.post("/news/refresh")

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Second call should still return the same cluster (known headline)
        self.assertEqual(r1.json()["total_headlines"], 1)
        self.assertEqual(r2.json()["total_headlines"], 1)
        self.assertGreaterEqual(len(r2.json()["clusters"]), 1)


if __name__ == "__main__":
    unittest.main()
