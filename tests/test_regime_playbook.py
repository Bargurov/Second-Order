"""Tests for GET /regime-playbook — regime-aware playbook panel backend."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import api as app_module


class TestRegimePlaybook(unittest.TestCase):
    """Integration-style tests against the FastAPI app using TestClient."""

    def setUp(self):
        self.client = TestClient(app_module.app)

    # ------------------------------------------------------------------
    # Empty archive
    # ------------------------------------------------------------------

    def test_empty_archive_returns_list(self):
        with patch("routes.playbook.load_recent_events", return_value=[]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    # ------------------------------------------------------------------
    # Filtering — mocks and low-signal excluded
    # ------------------------------------------------------------------

    def _make_event(self, **kwargs):
        """Minimal valid event dict."""
        base = {
            "id": 1,
            "headline": "Test headline",
            "event_date": "2024-01-01",
            "stage": "escalation",
            "persistence": "structural",
            "mechanism_summary": "Some mechanism",
            "confidence": "high",
            "low_signal": 0,
            "market_tickers": [
                {"symbol": "GLD", "direction_tag": "supports ↑", "return_5d": 2.3}
            ],
            "revisit_snapshots": [],
        }
        base.update(kwargs)
        return base

    def test_mock_events_excluded(self):
        ev = self._make_event(mechanism_summary="[mock: some text]")
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_low_signal_excluded(self):
        ev = self._make_event(low_signal=1)
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_no_direction_tags_excluded(self):
        ev = self._make_event(
            market_tickers=[{"symbol": "SPY", "direction_tag": None, "return_5d": None}]
        )
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_empty_tickers_excluded(self):
        ev = self._make_event(market_tickers=[])
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Geopolitical+Stress")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    # ------------------------------------------------------------------
    # Successful response shape
    # ------------------------------------------------------------------

    def test_valid_event_included(self):
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Geopolitical+Stress")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(len(body), 1)
        entry = body[0]
        self.assertEqual(entry["id"], 1)
        self.assertEqual(entry["validation_outcome"], "validated")
        self.assertAlmostEqual(entry["support_ratio"], 1.0)

    def test_response_shape(self):
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        body = resp.json()
        entry = body[0]
        required_keys = {
            "id", "headline", "event_date", "stage", "persistence",
            "mechanism_summary", "confidence", "validation_outcome",
            "support_ratio", "lead_ticker", "revisit_count",
        }
        self.assertTrue(required_keys.issubset(entry.keys()), f"Missing keys: {required_keys - entry.keys()}")

    def test_lead_ticker_populated(self):
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Calm+with+Undercurrent")
        entry = resp.json()[0]
        self.assertIsNotNone(entry["lead_ticker"])
        self.assertEqual(entry["lead_ticker"]["symbol"], "GLD")
        self.assertAlmostEqual(entry["lead_ticker"]["return_5d"], 2.3)

    def test_score_not_exposed(self):
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook")
        entry = resp.json()[0]
        self.assertNotIn("_score", entry)

    # ------------------------------------------------------------------
    # Limit parameter
    # ------------------------------------------------------------------

    def test_limit_respected(self):
        events = [self._make_event(id=i) for i in range(1, 10)]
        with patch("routes.playbook.load_recent_events", return_value=events):
            resp = self.client.get("/regime-playbook?limit=3")
        self.assertEqual(len(resp.json()), 3)

    def test_limit_default_is_four(self):
        events = [self._make_event(id=i) for i in range(1, 10)]
        with patch("routes.playbook.load_recent_events", return_value=events):
            resp = self.client.get("/regime-playbook")
        self.assertEqual(len(resp.json()), 4)

    # ------------------------------------------------------------------
    # Regime keyword fallback
    # ------------------------------------------------------------------

    def test_calm_regime_returns_quality_events(self):
        """Calm has no keywords; quality events should still be returned."""
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Calm")
        # enabled: false on frontend for Calm, but backend itself returns
        # whatever it finds — it never enforces a Calm exclusion.
        # Just confirm it doesn't error.
        self.assertEqual(resp.status_code, 200)

    def test_unknown_regime_falls_back_gracefully(self):
        ev = self._make_event()
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Unknown+Regime")
        self.assertEqual(resp.status_code, 200)

    # ------------------------------------------------------------------
    # Contradicted events included (not just validated)
    # ------------------------------------------------------------------

    def test_contradicted_event_included(self):
        ev = self._make_event(
            market_tickers=[
                {"symbol": "TLT", "direction_tag": "contradicts ↑", "return_5d": -1.2}
            ]
        )
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Systemic+Stress")
        body = resp.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["validation_outcome"], "contradicted")

    # ------------------------------------------------------------------
    # NaN sanitization
    # ------------------------------------------------------------------

    def test_nan_return_sanitized(self):
        import math
        ev = self._make_event(
            market_tickers=[
                {"symbol": "GLD", "direction_tag": "supports ↑", "return_5d": float("nan")}
            ]
        )
        with patch("routes.playbook.load_recent_events", return_value=[ev]):
            resp = self.client.get("/regime-playbook?regime=Geopolitical+Stress")
        body = resp.json()
        self.assertIsNone(body[0]["lead_ticker"]["return_5d"])


if __name__ == "__main__":
    unittest.main()
