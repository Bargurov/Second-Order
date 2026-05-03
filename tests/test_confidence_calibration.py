"""
tests/test_confidence_calibration.py

Tests for get_confidence_calibration_stats() — the function that computes
per-bucket (low/medium/high) historical validation rates from saved events.

Covers:
  1. Empty DB → empty dict.
  2. Events with no usable direction are excluded from counts.
  3. All three buckets populated correctly from market_tickers.
  4. Revisit snapshots preferred over market_tickers when available.
  5. min_events threshold hides sparse buckets.
  6. An event with only "contradicts" tickers → not validated.
  7. API endpoint returns the dict (HTTP 200, valid JSON).
"""

import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


def _tmp_db() -> str:
    return os.path.join(
        os.path.dirname(__file__),
        f"test_calibration_{uuid.uuid4().hex}.db",
    )


def _seed(conn, confidence: str, direction_tags: list[str]) -> None:
    """Insert a minimal event row with the given confidence and direction_tags."""
    tickers = json.dumps([
        {"symbol": f"T{i}", "role": "beneficiary", "direction_tag": tag,
         "return_1d": None, "return_5d": None, "return_20d": None,
         "return_60d": None, "volume_ratio": None, "vs_xle_5d": None, "spark": []}
        for i, tag in enumerate(direction_tags)
    ])
    conn.execute(
        "INSERT INTO events (headline, stage, persistence, timestamp, confidence, market_tickers) "
        "VALUES (?, 'realized', 'structural', datetime('now'), ?, ?)",
        (f"headline-{uuid.uuid4().hex[:6]}", confidence, tickers),
    )


class ConfidenceCalibrationStatsTest(unittest.TestCase):

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _conn(self):
        import sqlite3
        return sqlite3.connect(self._tmp)

    # 1. Empty DB → empty dict
    def test_empty_db_returns_empty_dict(self):
        self.assertEqual(db.get_confidence_calibration_stats(), {})

    # 2. Events with no directional outcomes are excluded
    def test_events_with_no_direction_excluded(self):
        with self._conn() as conn:
            _seed(conn, "high", [None, None])
            conn.commit()
        result = db.get_confidence_calibration_stats(min_events=1)
        self.assertNotIn("high", result)

    # 3. Correct hit_rate from market_tickers across three buckets
    def test_three_buckets_from_market_tickers(self):
        with self._conn() as conn:
            # high: 3 validated, 1 contradicted → hit_rate = 0.75
            for _ in range(3):
                _seed(conn, "high", ["supports ↑"])
            _seed(conn, "high", ["contradicts ↓"])
            # medium: 2 validated, 2 not → hit_rate = 0.5
            for _ in range(2):
                _seed(conn, "medium", ["supports ↑"])
            for _ in range(2):
                _seed(conn, "medium", ["contradicts ↓"])
            # low: 1 validated, 3 not → hit_rate = 0.25
            _seed(conn, "low", ["supports ↑"])
            for _ in range(3):
                _seed(conn, "low", ["contradicts ↓"])
            conn.commit()

        result = db.get_confidence_calibration_stats(min_events=1)

        self.assertIn("high", result)
        self.assertAlmostEqual(result["high"]["hit_rate"], 0.75)
        self.assertEqual(result["high"]["n"], 4)

        self.assertIn("medium", result)
        self.assertAlmostEqual(result["medium"]["hit_rate"], 0.5)
        self.assertEqual(result["medium"]["n"], 4)

        self.assertIn("low", result)
        self.assertAlmostEqual(result["low"]["hit_rate"], 0.25)
        self.assertEqual(result["low"]["n"], 4)

    # 4. Revisit snapshots preferred over market_tickers
    def test_revisit_snapshot_preferred(self):
        """When a revisit snapshot exists, it overrides market_tickers direction."""
        tickers_supports = json.dumps([
            {"symbol": "A", "role": "beneficiary", "direction_tag": "supports ↑",
             "return_1d": None, "return_5d": None, "return_20d": None,
             "return_60d": None, "volume_ratio": None, "vs_xle_5d": None, "spark": []}
        ])
        # Revisit snapshot says contradicts (should override market_tickers supports)
        revisit_contradicts = json.dumps([{
            "day": 5,
            "tickers": [{"symbol": "A", "role": "beneficiary",
                          "direction": "contradicts ↓",
                          "return_1d": None, "return_5d": -2.0, "return_20d": None}]
        }])
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (headline, stage, persistence, timestamp, confidence, market_tickers, revisit_snapshots) "
                "VALUES (?, 'realized', 'structural', datetime('now'), 'high', ?, ?)",
                ("revisit-test", tickers_supports, revisit_contradicts),
            )
            conn.commit()

        result = db.get_confidence_calibration_stats(min_events=1)
        # The revisit snapshot says contradicts → event NOT validated
        self.assertIn("high", result)
        self.assertEqual(result["high"]["hit_rate"], 0.0)
        self.assertEqual(result["high"]["n"], 1)

    # 5. min_events threshold hides sparse buckets
    def test_min_events_threshold(self):
        with self._conn() as conn:
            # Only 2 "high" events — below default min_events=3
            _seed(conn, "high", ["supports ↑"])
            _seed(conn, "high", ["contradicts ↓"])
            conn.commit()

        result = db.get_confidence_calibration_stats(min_events=3)
        self.assertNotIn("high", result)

        result2 = db.get_confidence_calibration_stats(min_events=2)
        self.assertIn("high", result2)

    # 6. Pure "contradicts" event → not validated
    def test_contradicts_only_not_validated(self):
        with self._conn() as conn:
            _seed(conn, "medium", ["contradicts ↓", "contradicts ↓"])
            conn.commit()

        result = db.get_confidence_calibration_stats(min_events=1)
        self.assertIn("medium", result)
        self.assertEqual(result["medium"]["hit_rate"], 0.0)
        self.assertEqual(result["medium"]["n"], 1)

    # 7. Mixed supports + contradicts → validated (any supports wins)
    def test_mixed_tickers_validated_when_any_supports(self):
        with self._conn() as conn:
            _seed(conn, "high", ["supports ↑", "contradicts ↓"])
            conn.commit()

        result = db.get_confidence_calibration_stats(min_events=1)
        self.assertEqual(result["high"]["hit_rate"], 1.0)


class ConfidenceCalibrationEndpointTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        for p in [
            patch("analyze_event.analyze_event"),
            patch("market_check.market_check", return_value={"note": "", "details": {}, "tickers": []}),
            patch("market_check.macro_snapshot", return_value=[]),
            patch("market_check.ticker_info", return_value={}),
            patch("market_check.ticker_chart", return_value=[]),
        ]:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        patch.stopall()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def test_endpoint_returns_200(self):
        r = self.client.get("/stats/confidence-calibration")
        self.assertEqual(r.status_code, 200)

    def test_endpoint_returns_dict(self):
        r = self.client.get("/stats/confidence-calibration")
        body = r.json()
        self.assertIsInstance(body, dict)

    def test_endpoint_reflects_seeded_data(self):
        import sqlite3
        with sqlite3.connect(self._tmp) as conn:
            tickers = json.dumps([
                {"symbol": "T0", "role": "beneficiary", "direction_tag": "supports ↑",
                 "return_1d": None, "return_5d": None, "return_20d": None,
                 "return_60d": None, "volume_ratio": None, "vs_xle_5d": None, "spark": []}
            ])
            for _ in range(4):
                conn.execute(
                    "INSERT INTO events (headline, stage, persistence, timestamp, confidence, market_tickers) "
                    "VALUES (?, 'realized', 'structural', datetime('now'), 'high', ?)",
                    (f"h-{uuid.uuid4().hex[:6]}", tickers),
                )
            conn.commit()

        r = self.client.get("/stats/confidence-calibration")
        body = r.json()
        self.assertIn("high", body)
        self.assertAlmostEqual(body["high"]["hit_rate"], 1.0)
        self.assertEqual(body["high"]["n"], 4)


if __name__ == "__main__":
    unittest.main()
