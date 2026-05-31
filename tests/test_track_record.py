"""
Tests for track record aggregation (compute_track_record).

Covers:
- Empty DB → all zeros
- Single event with "supports" direction → validated
- Single event with "contradicts" only → contradicted
- Single event with null directions → unresolved
- Mixed events with ratings → correct counts
- avg_support_ratio computation
- API endpoint returns the correct shape
"""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import init_db, save_event, update_review, compute_track_record


def _event(headline, tickers, rating=None):
    return {
        "headline": headline,
        "stage": "developing",
        "persistence": "1w",
        "what_changed": "test",
        "mechanism_summary": "test",
        "beneficiaries": ["A"],
        "losers": ["B"],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "",
        "market_tickers": tickers,
        "event_date": "2025-06-01",
        "notes": "",
        "rating": rating,
    }


class _IsolatedDb(unittest.TestCase):
    def setUp(self):
        self._orig = db_module.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_tr_{uuid.uuid4().hex}.db",
        )
        db_module.DB_FILE = self._tmp
        db_module._db_ready = False
        init_db()

    def tearDown(self):
        db_module.DB_FILE = self._orig
        db_module._db_ready = False
        try:
            os.remove(self._tmp)
        except (PermissionError, OSError):
            pass


class TestTrackRecordAggregation(_IsolatedDb):

    def test_empty_db(self):
        r = compute_track_record()
        self.assertEqual(r["total"], 0)
        self.assertEqual(r["validated"], 0)
        self.assertEqual(r["contradicted"], 0)
        self.assertEqual(r["unresolved"], 0)
        self.assertIsNone(r["avg_support_ratio"])
        self.assertEqual(r["rated_good"], 0)

    def test_single_validated_event(self):
        save_event(_event("Validated event", [
            {"symbol": "AAPL", "role": "beneficiary",
             "direction_tag": "supports \u2191", "return_5d": 2.0, "spark": []},
        ]))
        r = compute_track_record()
        self.assertEqual(r["total"], 1)
        self.assertEqual(r["validated"], 1)
        self.assertEqual(r["contradicted"], 0)
        self.assertEqual(r["unresolved"], 0)

    def test_single_contradicted_event(self):
        save_event(_event("Contradicted event", [
            {"symbol": "AAPL", "role": "beneficiary",
             "direction_tag": "contradicts \u2193", "return_5d": -2.0, "spark": []},
        ]))
        r = compute_track_record()
        self.assertEqual(r["validated"], 0)
        self.assertEqual(r["contradicted"], 1)

    def test_single_unresolved_event(self):
        save_event(_event("Unresolved event", [
            {"symbol": "AAPL", "role": "beneficiary",
             "direction_tag": None, "return_5d": None, "spark": []},
        ]))
        r = compute_track_record()
        self.assertEqual(r["unresolved"], 1)
        self.assertEqual(r["validated"], 0)
        self.assertEqual(r["contradicted"], 0)

    def test_mixed_supports_and_contradicts_counts_as_validated(self):
        """If at least one ticker supports, the event is validated."""
        save_event(_event("Mixed event", [
            {"symbol": "AAPL", "role": "beneficiary",
             "direction_tag": "supports \u2191", "return_5d": 2.0, "spark": []},
            {"symbol": "MSFT", "role": "loser",
             "direction_tag": "contradicts \u2191", "return_5d": 1.0, "spark": []},
        ]))
        r = compute_track_record()
        self.assertEqual(r["validated"], 1)
        self.assertEqual(r["contradicted"], 0)

    def test_ratings_counted(self):
        save_event(_event("Good event", []))
        save_event(_event("Mixed event", []))
        save_event(_event("Poor event", []))
        save_event(_event("Unrated event", []))
        # Rating is set via update_review, not save_event
        import sqlite3
        with sqlite3.connect(db_module.DB_FILE) as conn:
            ids = [r[0] for r in conn.execute("SELECT id FROM events ORDER BY id").fetchall()]
        update_review(ids[0], rating="good")
        update_review(ids[1], rating="mixed")
        update_review(ids[2], rating="poor")
        r = compute_track_record()
        self.assertEqual(r["rated_good"], 1)
        self.assertEqual(r["rated_mixed"], 1)
        self.assertEqual(r["rated_poor"], 1)
        self.assertEqual(r["total"], 4)

    def test_avg_support_ratio(self):
        # Event 1: 1 supports out of 2 → 0.5
        save_event(_event("Event A", [
            {"symbol": "AAPL", "direction_tag": "supports \u2191", "return_5d": 1.0, "spark": []},
            {"symbol": "MSFT", "direction_tag": "contradicts \u2193", "return_5d": -1.0, "spark": []},
        ]))
        # Event 2: 2 supports out of 2 → 1.0
        save_event(_event("Event B", [
            {"symbol": "GOOG", "direction_tag": "supports \u2191", "return_5d": 1.0, "spark": []},
            {"symbol": "AMZN", "direction_tag": "supports \u2193", "return_5d": -1.0, "spark": []},
        ]))
        r = compute_track_record()
        # avg = (0.5 + 1.0) / 2 = 0.75
        self.assertAlmostEqual(r["avg_support_ratio"], 0.75, places=3)

    def test_avg_support_ratio_excludes_no_direction_events(self):
        save_event(_event("No direction", [
            {"symbol": "AAPL", "direction_tag": None, "return_5d": None, "spark": []},
        ]))
        r = compute_track_record()
        self.assertIsNone(r["avg_support_ratio"])

    def test_empty_tickers_is_unresolved(self):
        save_event(_event("No tickers", []))
        r = compute_track_record()
        self.assertEqual(r["unresolved"], 1)

    def test_curated_intake_rows_excluded_from_denominator(self):
        """Curated-intake stubs are real archived events but carry no
        thesis outcome — they must never enlarge the track-record
        denominator or land in the unresolved bucket."""
        save_event(_event("Real validated event", [
            {"symbol": "AAPL", "direction_tag": "supports ↑",
             "return_5d": 2.0, "spark": []},
        ]))
        intake = _event("Curated intake stub", [])
        intake["stage"] = db_module.CURATED_INTAKE_STAGE
        intake["persistence"] = "unscored"
        save_event(intake)

        r = compute_track_record()
        self.assertEqual(r["total"], 1)        # curated_intake excluded
        self.assertEqual(r["validated"], 1)
        self.assertEqual(r["unresolved"], 0)   # not counted as unresolved

    def test_multiple_events_correct_totals(self):
        save_event(_event("V1", [{"symbol": "A", "direction_tag": "supports \u2191", "return_5d": 1.0, "spark": []}]))
        save_event(_event("V2", [{"symbol": "B", "direction_tag": "supports \u2193", "return_5d": -1.0, "spark": []}]))
        save_event(_event("C1", [{"symbol": "C", "direction_tag": "contradicts \u2191", "return_5d": 1.0, "spark": []}]))
        save_event(_event("U1", [{"symbol": "D", "direction_tag": None, "return_5d": None, "spark": []}]))
        r = compute_track_record()
        self.assertEqual(r["total"], 4)
        self.assertEqual(r["validated"], 2)
        self.assertEqual(r["contradicted"], 1)
        self.assertEqual(r["unresolved"], 1)


class TestTrackRecordEndpoint(_IsolatedDb):
    """API endpoint returns correct shape."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        super().setUp()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0

    def test_endpoint_returns_all_keys(self):
        r = self.client.get("/stats/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("total", "validated", "contradicted", "unresolved",
                     "avg_support_ratio", "rated_good", "rated_mixed", "rated_poor"):
            self.assertIn(key, body, f"Missing key: {key}")

    def test_endpoint_empty_db(self):
        r = self.client.get("/stats/track-record")
        body = r.json()
        self.assertEqual(body["total"], 0)


if __name__ == "__main__":
    unittest.main()
