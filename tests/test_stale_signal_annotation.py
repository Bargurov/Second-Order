"""Tests for staleness annotation on /events and /portfolio list endpoints."""

import sys
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
import api as _api_mod


def _make_event(
    id_: int,
    last_check_offset_hours: float | None,
    event_age_days: int = 1,
) -> dict:
    """Build a minimal saved-event dict for staleness testing."""
    now = datetime.now()
    event_date = (now - timedelta(days=event_age_days)).strftime("%Y-%m-%d")
    last_check = (
        (now - timedelta(hours=last_check_offset_hours)).isoformat(timespec="seconds")
        if last_check_offset_hours is not None
        else None
    )
    return {
        "id": id_,
        "timestamp": now.isoformat(timespec="seconds"),
        "headline": f"Test headline {id_}",
        "event_date": event_date,
        "stage": "escalation",
        "persistence": "transient",
        "what_changed": "",
        "mechanism_summary": "Test mechanism",
        "beneficiaries": [],
        "losers": [],
        "assets_to_watch": [],
        "confidence": "medium",
        "market_note": "",
        "market_tickers": [
            {"symbol": "AAPL", "role": "beneficiary",
             "return_1d": 0.5, "return_5d": 1.2, "return_20d": 2.1,
             "direction_tag": "supports ↑", "label": "flat",
             "volume_ratio": 1.0, "vs_xle_5d": None, "spark": []}
        ],
        "last_market_check_at": last_check,
        "notes": "",
        "rating": None,
    }


class TestEventsListAnnotation(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_api_mod.app)

    def _get_events(self, rows):
        with patch("routes.events.load_recent_events", return_value=rows):
            return self.client.get("/events?limit=10").json()

    def test_fresh_event_gets_fresh_signal(self):
        """An event checked 1 hour ago (well within 4h threshold) is fresh."""
        rows = [_make_event(1, last_check_offset_hours=1.0, event_age_days=1)]
        result = self._get_events(rows)
        self.assertEqual(result[0]["stale_signal"], "fresh")
        self.assertIsNotNone(result[0]["hours_since_check"])
        self.assertIsNotNone(result[0]["event_age_days"])

    def test_stale_event_gets_stale_signal(self):
        """An event whose last check was 6h ago (>4h for recent events) is stale."""
        rows = [_make_event(2, last_check_offset_hours=6.0, event_age_days=2)]
        result = self._get_events(rows)
        self.assertEqual(result[0]["stale_signal"], "stale")

    def test_legacy_event_gets_legacy_signal(self):
        """A row with no last_market_check_at is legacy."""
        rows = [_make_event(3, last_check_offset_hours=None, event_age_days=3)]
        result = self._get_events(rows)
        self.assertEqual(result[0]["stale_signal"], "legacy")

    def test_frozen_event_gets_frozen_signal(self):
        """An event older than 30 days is frozen."""
        rows = [_make_event(4, last_check_offset_hours=2.0, event_age_days=35)]
        result = self._get_events(rows)
        self.assertEqual(result[0]["stale_signal"], "frozen")

    def test_annotation_is_additive(self):
        """All original fields are still present after annotation."""
        rows = [_make_event(5, last_check_offset_hours=1.0)]
        result = self._get_events(rows)
        self.assertIn("headline", result[0])
        self.assertIn("market_tickers", result[0])
        self.assertIn("stale_signal", result[0])

    def test_multiple_rows_all_annotated(self):
        rows = [
            _make_event(1, last_check_offset_hours=1.0),
            _make_event(2, last_check_offset_hours=6.0),
        ]
        result = self._get_events(rows)
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertIn("stale_signal", row)


if __name__ == "__main__":
    unittest.main()
