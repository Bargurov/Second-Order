"""Tests for get_event_cascade() in db.py."""

import json
import shutil
import sqlite3
import tempfile
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch


_COLS = (
    "id, headline, stage, persistence, confidence, "
    "timestamp, event_date, mechanism_summary"
)


def _make_db(path: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute(
            """CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                headline TEXT NOT NULL,
                stage TEXT DEFAULT '',
                persistence TEXT DEFAULT '',
                confidence TEXT DEFAULT '',
                timestamp TEXT DEFAULT '',
                event_date TEXT DEFAULT '',
                mechanism_summary TEXT DEFAULT '',
                low_signal INTEGER DEFAULT 0
            )"""
        )


def _insert(conn: sqlite3.Connection, headline: str, **kwargs) -> int:
    defaults = {
        "stage": "Structural", "persistence": "Persistent",
        "confidence": "high", "timestamp": "2025-01-01T00:00:00",
        "event_date": "2025-01-01", "mechanism_summary": "",
    }
    defaults.update(kwargs)
    cur = conn.execute(
        "INSERT INTO events (headline, stage, persistence, confidence, timestamp, event_date, mechanism_summary) "
        "VALUES (:headline, :stage, :persistence, :confidence, :timestamp, :event_date, :mechanism_summary)",
        {"headline": headline, **defaults},
    )
    return cur.lastrowid


class TestGetEventCascade(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp_dir, "test.db")
        _make_db(self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _call(self, event_id: int, **kwargs):
        import db as db_module
        with patch.object(db_module, "_db_ready", True), \
             patch.object(db_module, "DB_FILE", self.db_path):
            return db_module.get_event_cascade(event_id, **kwargs)

    def test_missing_event_returns_none_root(self):
        result = self._call(999)
        self.assertIsNone(result["root"])
        self.assertEqual(result["nodes"], [])

    def test_not_db_ready_returns_empty(self):
        import db as db_module
        with patch.object(db_module, "_db_ready", False):
            result = db_module.get_event_cascade(1)
        self.assertIsNone(result["root"])
        self.assertEqual(result["nodes"], [])

    def test_single_event_no_related(self):
        with sqlite3.connect(self.db_path) as conn:
            eid = _insert(conn, "OPEC cuts oil production by 1 million barrels")
        result = self._call(eid)
        self.assertIsNotNone(result["root"])
        self.assertEqual(result["nodes"], [])

    def test_hop1_related_found(self):
        with sqlite3.connect(self.db_path) as conn:
            root_id = _insert(conn, "OPEC cuts oil production target sharply")
            _insert(conn, "OPEC cuts oil production target barrels",
                    event_date="2025-01-05")
            _insert(conn, "Completely unrelated semiconductor tariff news",
                    event_date="2025-01-06")

        result = self._call(root_id)
        self.assertEqual(len(result["nodes"]), 1)
        self.assertEqual(result["nodes"][0]["hop"], 1)
        self.assertEqual(result["nodes"][0]["parent_id"], root_id)
        self.assertIn("OPEC", result["nodes"][0]["headline"])

    def test_hop2_deduplication(self):
        """A hop-2 event should not appear under two different hop-1 parents."""
        with sqlite3.connect(self.db_path) as conn:
            root_id = _insert(conn, "OPEC cuts oil production output barrels")
            h1a = _insert(conn, "OPEC reduces output barrels production target",
                          event_date="2025-01-03")
            h1b = _insert(conn, "OPEC production cut barrels output meeting",
                          event_date="2025-01-04")
            # This would match both h1a and h1b
            _insert(conn, "OPEC output production target cut barrel supply",
                    event_date="2025-01-06")

        result = self._call(root_id)
        node_ids = [n["id"] for n in result["nodes"]]
        # No duplicates
        self.assertEqual(len(node_ids), len(set(node_ids)))

    def test_chronological_order(self):
        with sqlite3.connect(self.db_path) as conn:
            root_id = _insert(conn, "Federal Reserve interest rate decision hike")
            _insert(conn, "Federal Reserve interest rate decision pause",
                    event_date="2025-03-01")
            _insert(conn, "Federal Reserve interest rate decision benchmark",
                    event_date="2025-01-15")

        result = self._call(root_id)
        if len(result["nodes"]) >= 2:
            dates = [n["event_date"] for n in result["nodes"]]
            self.assertEqual(dates, sorted(dates))

    def test_node_shape(self):
        with sqlite3.connect(self.db_path) as conn:
            root_id = _insert(conn, "OPEC cuts oil production output barrels")
            _insert(conn, "OPEC reduces output barrels production target",
                    mechanism_summary="Supply shock", event_date="2025-01-05")

        result = self._call(root_id)
        self.assertEqual(len(result["nodes"]), 1)
        n = result["nodes"][0]
        for field in ("id", "headline", "stage", "persistence", "confidence",
                      "timestamp", "event_date", "mechanism_summary",
                      "hop", "parent_id", "similarity"):
            self.assertIn(field, n, f"missing field: {field}")
        self.assertIsInstance(n["similarity"], float)
        self.assertGreater(n["similarity"], 0)

    def test_per_level_limit(self):
        with sqlite3.connect(self.db_path) as conn:
            root_id = _insert(conn, "OPEC cuts oil production output barrels")
            for i in range(6):
                _insert(conn, f"OPEC reduces output target barrels production cut {i}",
                        event_date=f"2025-01-0{i+2}")

        result = self._call(root_id, per_level=3)
        hop1 = [n for n in result["nodes"] if n["hop"] == 1]
        self.assertLessEqual(len(hop1), 3)


if __name__ == "__main__":
    unittest.main()
