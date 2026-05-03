"""
Tests for track-record scoring using revisit snapshots.

Covers:
- _score_directions helper
- _best_revisit_snapshot helper
- compute_track_record: revisit-preferred scoring, fallback to market_tickers
- Serialization: endpoint returns revisit_scored field
- Frontend wiring: TrackRecord interface and TrackRecordStrip
"""

import os
import sys
import json
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db


class TestScoreDirections(unittest.TestCase):
    """Unit tests for _score_directions helper."""

    def test_supports_detected(self):
        tickers = [
            {"direction_tag": "supports \u2191"},
            {"direction_tag": "contradicts \u2193"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = db._score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 1)
        self.assertEqual(dir_cnt, 2)

    def test_contradicts_only(self):
        tickers = [
            {"direction_tag": "contradicts \u2193"},
            {"direction_tag": "contradicts \u2191"},
        ]
        has_sup, has_con, sup_cnt, dir_cnt = db._score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertTrue(has_con)
        self.assertEqual(sup_cnt, 0)
        self.assertEqual(dir_cnt, 2)

    def test_no_direction(self):
        tickers = [{"direction_tag": None}, {"symbol": "XOM"}]
        has_sup, has_con, sup_cnt, dir_cnt = db._score_directions(tickers)
        self.assertFalse(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(dir_cnt, 0)

    def test_custom_tag_key(self):
        """Revisit tickers use 'direction' not 'direction_tag'."""
        tickers = [{"direction": "supports \u2191"}, {"direction": "supports \u2193"}]
        has_sup, _, sup_cnt, dir_cnt = db._score_directions(tickers)
        self.assertTrue(has_sup)
        self.assertEqual(sup_cnt, 2)
        self.assertEqual(dir_cnt, 2)

    def test_empty_list(self):
        has_sup, has_con, sup_cnt, dir_cnt = db._score_directions([])
        self.assertFalse(has_sup)
        self.assertFalse(has_con)
        self.assertEqual(dir_cnt, 0)


class TestBestRevisitSnapshot(unittest.TestCase):
    """Unit tests for _best_revisit_snapshot helper."""

    def test_prefers_longest_horizon(self):
        snaps = [
            {"day": 1, "tickers": [{"direction": "supports \u2191"}]},
            {"day": 20, "tickers": [{"direction": "contradicts \u2193"}]},
            {"day": 5, "tickers": [{"direction": "supports \u2191"}]},
        ]
        best = db._best_revisit_snapshot(snaps)
        # Should pick day 20
        self.assertIsNotNone(best)
        self.assertEqual(best[0]["direction"], "contradicts \u2193")

    def test_skips_empty_tickers(self):
        snaps = [
            {"day": 20, "tickers": []},
            {"day": 5, "tickers": [{"direction": "supports \u2191"}]},
        ]
        best = db._best_revisit_snapshot(snaps)
        self.assertEqual(best[0]["direction"], "supports \u2191")

    def test_none_when_all_empty(self):
        snaps = [{"day": 5, "tickers": []}]
        self.assertIsNone(db._best_revisit_snapshot(snaps))

    def test_none_when_no_snapshots(self):
        self.assertIsNone(db._best_revisit_snapshot([]))
        self.assertIsNone(db._best_revisit_snapshot(None))


class TestComputeTrackRecord(unittest.TestCase):
    """Integration tests for compute_track_record with revisit scoring."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_tr_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass

    def _seed(self, market_tickers, revisit_snapshots=None, rating=None):
        """Insert a minimal event row."""
        db.save_event({
            "headline": f"Test event {uuid.uuid4().hex[:6]}",
            "stage": "developing",
            "persistence": "medium",
            "event_date": "2026-04-01",
            "market_tickers": market_tickers,
        })
        events = db.load_recent_events(limit=1)
        eid = events[0]["id"]
        if revisit_snapshots:
            for snap in revisit_snapshots:
                db.append_revisit_snapshot(eid, snap)
        if rating:
            db.update_review(eid, rating=rating)
        return eid

    def test_revisit_preferred_over_initial(self):
        """When revisit says contradicts but initial says supports, revisit wins."""
        self._seed(
            market_tickers=[{"symbol": "XOM", "direction_tag": "supports \u2191"}],
            revisit_snapshots=[{
                "day": 20,
                "captured_at": "2026-04-21T12:00:00",
                "tickers": [{"symbol": "XOM", "direction": "contradicts \u2193", "role": "beneficiary"}],
            }],
        )
        tr = db.compute_track_record()
        self.assertEqual(tr["validated"], 0)
        self.assertEqual(tr["contradicted"], 1)
        self.assertEqual(tr["revisit_scored"], 1)

    def test_fallback_to_initial_when_no_revisit(self):
        """Without revisit snapshots, use market_tickers direction_tag."""
        self._seed(
            market_tickers=[{"symbol": "XOM", "direction_tag": "supports \u2191"}],
        )
        tr = db.compute_track_record()
        self.assertEqual(tr["validated"], 1)
        self.assertEqual(tr["revisit_scored"], 0)

    def test_unresolved_when_no_directions(self):
        self._seed(
            market_tickers=[{"symbol": "XOM", "direction_tag": None}],
        )
        tr = db.compute_track_record()
        self.assertEqual(tr["unresolved"], 1)

    def test_revisit_with_no_direction_falls_back(self):
        """Revisit tickers with no direction should fall back to initial."""
        self._seed(
            market_tickers=[{"symbol": "XOM", "direction_tag": "supports \u2191"}],
            revisit_snapshots=[{
                "day": 5,
                "captured_at": "2026-04-06T12:00:00",
                "tickers": [{"symbol": "XOM", "direction": None, "role": "beneficiary"}],
            }],
        )
        tr = db.compute_track_record()
        # Revisit has 0 direction_count → falls back to initial
        self.assertEqual(tr["validated"], 1)
        self.assertEqual(tr["revisit_scored"], 0)

    def test_multiple_events_mixed(self):
        """Mix of revisit-scored and initial-scored events."""
        # Event 1: revisit says validated
        self._seed(
            market_tickers=[{"symbol": "XOM", "direction_tag": None}],
            revisit_snapshots=[{
                "day": 20,
                "captured_at": "2026-04-21T12:00:00",
                "tickers": [{"symbol": "XOM", "direction": "supports \u2191", "role": "beneficiary"}],
            }],
        )
        # Event 2: no revisit, initial says contradicted
        self._seed(
            market_tickers=[{"symbol": "CVX", "direction_tag": "contradicts \u2193"}],
        )
        # Event 3: no revisit, no direction → unresolved
        self._seed(
            market_tickers=[{"symbol": "AAPL"}],
        )
        tr = db.compute_track_record()
        self.assertEqual(tr["total"], 3)
        self.assertEqual(tr["validated"], 1)
        self.assertEqual(tr["contradicted"], 1)
        self.assertEqual(tr["unresolved"], 1)
        self.assertEqual(tr["revisit_scored"], 1)

    def test_avg_support_ratio_includes_revisit(self):
        """Support ratio should use revisit data when available."""
        self._seed(
            market_tickers=[],
            revisit_snapshots=[{
                "day": 5,
                "captured_at": "2026-04-06T12:00:00",
                "tickers": [
                    {"symbol": "XOM", "direction": "supports \u2191", "role": "beneficiary"},
                    {"symbol": "CVX", "direction": "contradicts \u2193", "role": "beneficiary"},
                ],
            }],
        )
        tr = db.compute_track_record()
        # 1 supporting / 2 with direction = 0.5
        self.assertAlmostEqual(tr["avg_support_ratio"], 0.5, places=2)

    def test_longest_horizon_preferred(self):
        """20d snapshot takes precedence over 5d."""
        self._seed(
            market_tickers=[],
            revisit_snapshots=[
                {"day": 5, "captured_at": "2026-04-06",
                 "tickers": [{"symbol": "XOM", "direction": "supports \u2191"}]},
                {"day": 20, "captured_at": "2026-04-21",
                 "tickers": [{"symbol": "XOM", "direction": "contradicts \u2193"}]},
            ],
        )
        tr = db.compute_track_record()
        self.assertEqual(tr["contradicted"], 1)
        self.assertEqual(tr["validated"], 0)

    def test_ratings_still_counted(self):
        self._seed(market_tickers=[], rating="good")
        self._seed(market_tickers=[], rating="poor")
        tr = db.compute_track_record()
        self.assertEqual(tr["rated_good"], 1)
        self.assertEqual(tr["rated_poor"], 1)

    def test_returns_revisit_scored_field(self):
        tr = db.compute_track_record()
        self.assertIn("revisit_scored", tr)


class TestTrackRecordEndpoint(unittest.TestCase):
    """Verify /stats/track-record serializes revisit_scored."""

    _PATCHES = [
        patch("market_snapshots.get_all_snapshots", return_value={
            "snapshots": [], "ts": 0, "age_seconds": 0, "stale": True,
        }),
    ]

    @classmethod
    def setUpClass(cls):
        for p in cls._PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        import api as api_module
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        for p in cls._PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_tr_ep_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass

    def test_endpoint_includes_revisit_scored(self):
        r = self.client.get("/stats/track-record")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("revisit_scored", body)
        self.assertIsInstance(body["revisit_scored"], int)

    def test_endpoint_shape_stable(self):
        """All existing fields must still be present."""
        r = self.client.get("/stats/track-record")
        body = r.json()
        for key in ("total", "validated", "contradicted", "unresolved",
                     "avg_support_ratio", "rated_good", "rated_mixed", "rated_poor",
                     "revisit_scored"):
            self.assertIn(key, body, f"Missing field: {key}")


class TestFrontendWiring(unittest.TestCase):
    """Verify frontend files have revisit_scored wiring."""

    def _read(self, *parts):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            *parts,
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_track_record_interface_has_revisit_scored(self):
        content = self._read("frontend", "src", "lib", "api.ts")
        self.assertIn("revisit_scored", content)

    def test_market_overview_shows_revisit_scored(self):
        content = self._read("frontend", "src", "components", "pages", "market-overview.tsx")
        self.assertIn("revisit_scored", content)
        self.assertIn("revisit-scored", content)


if __name__ == "__main__":
    unittest.main()
