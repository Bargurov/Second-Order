"""Tests for get_trending_clusters() in db.py."""

import json
import math
import shutil
import sqlite3
import tempfile
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


def _make_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE news_clusters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                headline TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                records_json TEXT NOT NULL DEFAULT '[]',
                latest_published_at TEXT,
                updated_at TEXT
            )"""
        )


def _insert_cluster(
    conn: sqlite3.Connection,
    headline: str,
    source_count: int,
    records: list,
    published_at: str,
) -> None:
    payload = {"source_count": source_count, "headline": headline}
    conn.execute(
        "INSERT INTO news_clusters (headline, payload_json, records_json, latest_published_at) "
        "VALUES (?, ?, ?, ?)",
        (headline, json.dumps(payload), json.dumps(records), published_at),
    )


def _ts(hours_ago: float) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


class TestGetTrendingClusters(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        _make_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _call(self, **kwargs):
        import db as db_module
        with patch.object(db_module, "_db_ready", True), \
             patch.object(db_module, "DB_FILE", self.db_path):
            return db_module.get_trending_clusters(**kwargs)

    def test_empty_db_returns_empty(self):
        result = self._call()
        self.assertEqual(result, [])

    def test_not_db_ready_returns_empty(self):
        import db as db_module
        with patch.object(db_module, "_db_ready", False):
            result = db_module.get_trending_clusters()
        self.assertEqual(result, [])

    def test_min_sources_boundary(self):
        with sqlite3.connect(self.db_path) as conn:
            _insert_cluster(conn, "Below threshold", 2, ["r1"], _ts(1))
            _insert_cluster(conn, "Exactly at threshold", 3, ["r1", "r2"], _ts(2))
            _insert_cluster(conn, "Above threshold", 5, ["r1"], _ts(3))

        result = self._call(min_sources=3, window_hours=72)
        headlines = [r["headline"] for r in result]
        self.assertNotIn("Below threshold", headlines)
        self.assertIn("Exactly at threshold", headlines)
        self.assertIn("Above threshold", headlines)

    def test_window_cutoff_inclusive(self):
        # Exactly at the boundary should be included (>= comparison).
        #
        # Freeze "now" so the seeded boundary timestamp and the window
        # cutoff inside get_trending_clusters are computed against the SAME
        # instant.  With two independent datetime.now() calls (one here for
        # boundary_ts, one in db.get_trending_clusters a few statements
        # later) both truncated to whole seconds, a wall-clock second that
        # ticks between them shifts the >=-inclusive cutoff past the
        # exactly-at-boundary row and drops it.  That race is rare in a fast
        # isolated run but surfaces under slow full-suite load (E13).
        import db as db_module
        fixed_now = datetime(2026, 6, 1, 12, 0, 0)
        boundary_ts = (fixed_now - timedelta(hours=72)).isoformat(timespec="seconds")
        outside_ts = (fixed_now - timedelta(hours=73)).isoformat(timespec="seconds")
        with sqlite3.connect(self.db_path) as conn:
            _insert_cluster(conn, "At boundary", 4, ["r1"], boundary_ts)
            _insert_cluster(conn, "Just outside", 4, ["r1"], outside_ts)

        with patch.object(db_module, "datetime") as mock_dt:
            mock_dt.now.return_value = fixed_now
            with patch.object(db_module, "_db_ready", True), \
                 patch.object(db_module, "DB_FILE", self.db_path):
                result = db_module.get_trending_clusters(window_hours=72, min_sources=3)

        headlines = [r["headline"] for r in result]
        self.assertIn("At boundary", headlines)
        self.assertNotIn("Just outside", headlines)

    def test_score_ordering(self):
        # score = source_count * sqrt(1 + record_count)
        # A: 5 sources, 0 records → 5 * sqrt(1) = 5.0
        # B: 3 sources, 8 records → 3 * sqrt(9) = 9.0  (higher)
        # C: 4 sources, 3 records → 4 * sqrt(4) = 8.0
        with sqlite3.connect(self.db_path) as conn:
            _insert_cluster(conn, "Cluster A", 5, [], _ts(1))
            _insert_cluster(conn, "Cluster B", 3, ["r"] * 8, _ts(2))
            _insert_cluster(conn, "Cluster C", 4, ["r"] * 3, _ts(3))

        result = self._call(min_sources=3, window_hours=72)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["headline"], "Cluster B")
        self.assertEqual(result[1]["headline"], "Cluster C")
        self.assertEqual(result[2]["headline"], "Cluster A")

    def test_limit_respected(self):
        with sqlite3.connect(self.db_path) as conn:
            for i in range(10):
                _insert_cluster(conn, f"Story {i}", 5, ["r1"], _ts(i + 1))

        result = self._call(limit=4, min_sources=3, window_hours=72)
        self.assertEqual(len(result), 4)

    def test_result_shape(self):
        with sqlite3.connect(self.db_path) as conn:
            _insert_cluster(conn, "Shape test", 4, ["r1", "r2"], _ts(1))

        result = self._call(min_sources=3, window_hours=72)
        self.assertEqual(len(result), 1)
        r = result[0]
        self.assertIn("headline", r)
        self.assertIn("source_count", r)
        self.assertIn("record_count", r)
        self.assertIn("latest_published_at", r)
        self.assertIn("score", r)
        self.assertEqual(r["source_count"], 4)
        self.assertEqual(r["record_count"], 2)
        expected_score = round(4 * math.sqrt(3), 2)
        self.assertAlmostEqual(r["score"], expected_score, places=2)

    def test_malformed_payload_json_skipped(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO news_clusters (headline, payload_json, records_json, latest_published_at) "
                "VALUES (?, ?, ?, ?)",
                ("Bad payload", "not-json", "[]", _ts(1)),
            )
            _insert_cluster(conn, "Good cluster", 4, [], _ts(2))

        result = self._call(min_sources=3, window_hours=72)
        headlines = [r["headline"] for r in result]
        self.assertNotIn("Bad payload", headlines)
        self.assertIn("Good cluster", headlines)

    def test_malformed_records_json_treated_as_empty(self):
        with sqlite3.connect(self.db_path) as conn:
            payload = json.dumps({"source_count": 5})
            conn.execute(
                "INSERT INTO news_clusters (headline, payload_json, records_json, latest_published_at) "
                "VALUES (?, ?, ?, ?)",
                ("Bad records", payload, "not-json", _ts(1)),
            )

        result = self._call(min_sources=3, window_hours=72)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["record_count"], 0)
        self.assertAlmostEqual(result[0]["score"], round(5 * math.sqrt(1), 2), places=2)


if __name__ == "__main__":
    unittest.main()
