"""
Tests for the revisit timeline feature.

Covers:
- DB: append_revisit_snapshot, load_revisit_snapshots, dedup by day
- API: GET /events/{id}/revisit, POST /events/{id}/revisit
- Frontend wiring: api.ts methods and AnalysisView component
"""

import os
import sys
import json
import tempfile
import unittest
import uuid
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MOCK_TICKERS = [
    {"symbol": "XOM", "label": "Exxon Mobil", "role": "beneficiary",
     "return_1d": 1.2, "return_5d": 3.5, "return_20d": 5.0,
     "direction_tag": "supports thesis", "volume_ratio": 1.1,
     "vs_xle_5d": 0.5, "spark": [100, 101, 102, 103, 104]},
    {"symbol": "CVX", "label": "Chevron", "role": "beneficiary",
     "return_1d": 0.8, "return_5d": 2.1, "return_20d": 3.0,
     "direction_tag": "supports thesis", "volume_ratio": 0.9,
     "vs_xle_5d": 0.3, "spark": [100, 101, 101, 102, 102]},
]

_FOLLOWUP_OUTCOMES = [
    {"symbol": "XOM", "role": "beneficiary",
     "return_1d": 0.45, "return_5d": 2.31, "return_20d": 4.10,
     "direction": "supports_thesis", "anchor_date": "2026-04-01"},
    {"symbol": "CVX", "role": "beneficiary",
     "return_1d": 0.20, "return_5d": 1.50, "return_20d": None,
     "direction": "supports_thesis", "anchor_date": "2026-04-01"},
]


# ---------------------------------------------------------------------------
# DB layer tests
# ---------------------------------------------------------------------------

class TestRevisitSnapshotDb(unittest.TestCase):
    """Test append_revisit_snapshot and load_revisit_snapshots."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_revisit_db_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Seed one event directly.
        db.save_event({
            "headline": "Test event",
            "stage": "developing",
            "persistence": "medium",
            "event_date": "2026-04-01",
            "market_tickers": _MOCK_TICKERS,
        })
        events = db.load_recent_events(limit=1)
        self.event_id = events[0]["id"]

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass

    def test_empty_by_default(self):
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(snaps, [])

    def test_append_and_load(self):
        snap = {"day": 1, "captured_at": "2026-04-02T12:00:00",
                "tickers": [{"symbol": "XOM", "return_1d": 0.45}]}
        ok = db.append_revisit_snapshot(self.event_id, snap)
        self.assertTrue(ok)
        loaded = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["day"], 1)
        self.assertEqual(loaded[0]["tickers"][0]["symbol"], "XOM")

    def test_multiple_days_sorted(self):
        db.append_revisit_snapshot(self.event_id,
            {"day": 5, "captured_at": "2026-04-06T12:00:00", "tickers": []})
        db.append_revisit_snapshot(self.event_id,
            {"day": 1, "captured_at": "2026-04-02T12:00:00", "tickers": []})
        db.append_revisit_snapshot(self.event_id,
            {"day": 20, "captured_at": "2026-04-21T12:00:00", "tickers": []})
        loaded = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(loaded), 3)
        self.assertEqual([s["day"] for s in loaded], [1, 5, 20])

    def test_dedup_replaces_same_day(self):
        db.append_revisit_snapshot(self.event_id,
            {"day": 5, "captured_at": "2026-04-06T12:00:00",
             "tickers": [{"symbol": "XOM", "return_5d": 2.0}]})
        db.append_revisit_snapshot(self.event_id,
            {"day": 5, "captured_at": "2026-04-06T18:00:00",
             "tickers": [{"symbol": "XOM", "return_5d": 2.5}]})
        loaded = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["tickers"][0]["return_5d"], 2.5)

    def test_missing_event_returns_false(self):
        ok = db.append_revisit_snapshot(99999, {"day": 1, "tickers": []})
        self.assertFalse(ok)

    def test_load_missing_event_returns_empty(self):
        self.assertEqual(db.load_revisit_snapshots(99999), [])

    def test_event_row_carries_snapshots(self):
        """load_event_by_id should include decoded revisit_snapshots."""
        db.append_revisit_snapshot(self.event_id,
            {"day": 1, "captured_at": "2026-04-02T12:00:00",
             "tickers": [{"symbol": "XOM", "return_1d": 0.45}]})
        event = db.load_event_by_id(self.event_id)
        self.assertIsInstance(event["revisit_snapshots"], list)
        self.assertEqual(len(event["revisit_snapshots"]), 1)


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------

class TestRevisitEndpoints(unittest.TestCase):
    """End-to-end tests for GET/POST /events/{id}/revisit.

    These tests exercise the real revisit route (route handler →
    ``load_event_by_id`` → ``append_revisit_snapshot`` →
    ``load_revisit_snapshots``).  The only boundary that is mocked is
    ``api.followup_check`` — the call into ``market_check.followup_check``
    which in turn reaches yfinance.  Everything between the HTTP layer
    and the DB runs for real.
    """

    @classmethod
    def setUpClass(cls):
        # Mock only the true external boundary: the market data provider.
        # followup_check() is what ultimately hits yfinance.  Every
        # internal composer (stage / persistence / rates / stress / overlays)
        # is unreachable from the revisit route — no need to mock them.
        cls._followup_patch = patch(
            "api.followup_check", return_value=_FOLLOWUP_OUTCOMES,
        )
        cls._followup_patch.start()
        from fastapi.testclient import TestClient
        import api as api_module
        cls.api_mod = api_module
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        cls._followup_patch.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_revisit_api_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass

    def _seed_event(self):
        """Seed the DB directly so we never run the /analyze pipeline.

        Going through /analyze used to require mocking ~15 internal
        composers (classify_stage, compute_stress_regime, build_regime_vector,
        compute_shock_decomposition, …) just to land a row — which meant the
        revisit tests were effectively asserting against a fiction that did
        not touch the code under test.  Seeding via ``db.save_event`` keeps
        the test focused on what the revisit endpoint actually does.
        """
        db.save_event({
            "headline": "OPEC cuts output",
            "stage": "developing",
            "persistence": "medium",
            "event_date": "2026-04-01",
            "market_tickers": _MOCK_TICKERS,
        })
        events = db.load_recent_events(limit=1)
        return events[0]["id"]

    def test_get_empty_timeline(self):
        eid = self._seed_event()
        r = self.client.get(f"/events/{eid}/revisit")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["event_id"], eid)
        self.assertEqual(body["snapshots"], [])

    def test_get_404(self):
        r = self.client.get("/events/999999/revisit")
        self.assertEqual(r.status_code, 404)

    def test_post_captures_snapshots(self):
        eid = self._seed_event()
        r = self.client.post(f"/events/{eid}/revisit")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["event_id"], eid)
        snaps = body["snapshots"]
        # followup_check returns return_1d for both tickers, return_5d for both,
        # return_20d for XOM only — so we should have day 1, 5, and 20 snapshots.
        days = [s["day"] for s in snaps]
        self.assertIn(1, days)
        self.assertIn(5, days)
        # Day 20: only XOM has return_20d
        self.assertIn(20, days)

    def test_post_snapshot_structure(self):
        eid = self._seed_event()
        r = self.client.post(f"/events/{eid}/revisit")
        body = r.json()
        for snap in body["snapshots"]:
            self.assertIn("day", snap)
            self.assertIn("captured_at", snap)
            self.assertIn("tickers", snap)
            self.assertIsInstance(snap["tickers"], list)
            for t in snap["tickers"]:
                self.assertIn("symbol", t)
                self.assertIn("role", t)

    def test_post_idempotent(self):
        """Calling POST twice replaces snapshots for the same day."""
        eid = self._seed_event()
        self.client.post(f"/events/{eid}/revisit")
        self.client.post(f"/events/{eid}/revisit")
        r = self.client.get(f"/events/{eid}/revisit")
        snaps = r.json()["snapshots"]
        day_counts = {}
        for s in snaps:
            day_counts[s["day"]] = day_counts.get(s["day"], 0) + 1
        for d, cnt in day_counts.items():
            self.assertEqual(cnt, 1, f"Day {d} should appear exactly once, got {cnt}")

    def test_post_404(self):
        r = self.client.post("/events/999999/revisit")
        self.assertEqual(r.status_code, 404)

    def test_snapshot_persisted_in_db(self):
        eid = self._seed_event()
        self.client.post(f"/events/{eid}/revisit")
        snaps = db.load_revisit_snapshots(eid)
        self.assertGreater(len(snaps), 0)


# ---------------------------------------------------------------------------
# Frontend wiring tests
# ---------------------------------------------------------------------------

class TestRevisitFrontendWiring(unittest.TestCase):
    """Verify api.ts and AnalysisView have the revisit timeline wiring."""

    def _read(self, *parts):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            *parts,
        )
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def test_api_ts_has_revisit_types(self):
        content = self._read("frontend", "src", "lib", "api.ts")
        self.assertIn("RevisitSnapshot", content)
        self.assertIn("RevisitTimeline", content)
        self.assertIn("RevisitTicker", content)

    def test_api_ts_has_get_method(self):
        content = self._read("frontend", "src", "lib", "api.ts")
        self.assertIn("getRevisitTimeline", content)
        self.assertIn("/revisit", content)

    def test_api_ts_has_capture_method(self):
        content = self._read("frontend", "src", "lib", "api.ts")
        self.assertIn("captureRevisit", content)
        self.assertIn("method: \"POST\"", content)

    def test_analysis_view_has_revisit_timeline(self):
        content = self._read("frontend", "src", "components", "pages", "analysis-view.tsx")
        self.assertIn("RevisitTimeline", content)
        self.assertIn("Follow-through", content)
        self.assertIn("captureRevisit", content)


if __name__ == "__main__":
    unittest.main()
