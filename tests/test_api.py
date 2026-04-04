"""Tests for the FastAPI layer (api.py).

Uses FastAPI's TestClient so no real server is needed.
Patches LLM and market calls to avoid external dependencies.
"""

import os
import sys
import unittest
import uuid
from unittest.mock import patch

# Ensure the project root is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402 — imported after path fix


def _mock_analyze(headline, stage, persistence, event_context=""):
    """Deterministic stand-in for analyze_event."""
    return {
        "what_changed": "Test policy change",
        "mechanism_summary": "Test mechanism summary for unit tests.",
        "beneficiaries": ["CompanyA"],
        "losers": ["CompanyB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Mock market check.",
        "details": {},
        "tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "direction_tag": None, "return_1d": 0.1, "return_5d": 0.5,
             "return_20d": 1.2, "volume_ratio": 1.0, "vs_xle_5d": None},
        ],
    }


_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
    patch("api.fetch_all", return_value=[
        {"source": "BBC World", "title": "Test headline A", "published_at": "2025-01-01T00:00:00", "url": ""},
        {"source": "Reuters", "title": "Test headline B", "published_at": "2025-01-01T00:00:00", "url": ""},
    ]),
    patch("api.cluster_headlines", return_value=[
        {"headline": "Test headline A", "sources": [{"name": "BBC World"}], "source_count": 1},
    ]),
]


class APITestCase(unittest.TestCase):
    """Base that swaps DB_FILE to a temp file and patches external calls."""

    @classmethod
    def setUpClass(cls):
        for p in _PATCHES:
            p.start()
        # Import after patches are in place so the module sees them.
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            os.path.dirname(__file__),
            f"test_api_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestHealth(APITestCase):
    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestAnalyze(APITestCase):
    def test_analyze_returns_all_fields(self):
        r = self.client.post("/analyze", json={"headline": "US imposes new tariffs on steel"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("headline", "stage", "persistence", "analysis", "market", "is_mock"):
            self.assertIn(key, body)
        self.assertFalse(body["is_mock"])

    def test_analyze_empty_headline_rejected(self):
        r = self.client.post("/analyze", json={"headline": ""})
        self.assertEqual(r.status_code, 422)

    def test_analyze_with_event_date(self):
        r = self.client.post("/analyze", json={
            "headline": "OPEC cuts production targets",
            "event_date": "2025-03-01",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["event_date"], "2025-03-01")


class TestEvents(APITestCase):
    def test_events_empty(self):
        r = self.client.get("/events")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_events_after_save(self):
        db.save_event({
            "headline": "Saved event",
            "stage": "realized",
            "persistence": "structural",
        })
        r = self.client.get("/events?limit=5")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["headline"], "Saved event")


class TestReview(APITestCase):
    def _seed(self):
        db.save_event({
            "headline": "Review target",
            "stage": "realized",
            "persistence": "structural",
        })
        return db.load_recent_events(1)[0]["id"]

    def test_patch_rating(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={"rating": "good"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_patch_notes(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={"notes": "Looks strong"})
        self.assertEqual(r.status_code, 200)

    def test_patch_empty_body_rejected(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={})
        self.assertEqual(r.status_code, 400)

    def test_patch_nonexistent_event(self):
        r = self.client.patch("/events/99999/review", json={"rating": "poor"})
        self.assertEqual(r.status_code, 404)


class TestNews(APITestCase):
    def test_news_returns_clusters(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("clusters", body)
        self.assertIn("total_headlines", body)
        self.assertEqual(body["total_headlines"], 2)


if __name__ == "__main__":
    unittest.main()
