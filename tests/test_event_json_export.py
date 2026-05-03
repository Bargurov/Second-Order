"""
tests/test_event_json_export.py

Focused tests for GET /events/{id}/export/json.

  1) Successful JSON export — returns 200 with expected fields.
  2) Missing event — returns 404.
  3) Stable key presence/order.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db
import api
from api import _JSON_EXPORT_KEYS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db() -> str:
    path = os.path.join(tempfile.gettempdir(),
                        f"test_json_export_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    return path


def _seed_full_event() -> int:
    db.save_event({
        "timestamp": "2026-04-13T10:00:00",
        "headline": "Fed raises rates by 50bp",
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "Federal Reserve raised the federal funds rate by 50bp",
        "mechanism_summary": "Higher borrowing costs slow housing demand",
        "beneficiaries": ["XLF", "BAC"],
        "losers": ["VNQ", "O"],
        "assets_to_watch": ["TLT"],
        "confidence": "high",
        "market_note": "Strong move across financials",
        "market_tickers": [
            {"symbol": "XLF", "role": "beneficiary", "return_1d": 1.0,
             "return_5d": 2.5, "return_20d": 4.0, "direction_tag": "supports thesis",
             "volume_ratio": 1.2, "vs_xle_5d": None, "spark": [0.5] * 20},
        ],
        "event_date": "2026-04-13",
        "transmission_chain": ["rates up", "housing slows", "REITs sell"],
        "if_persists": {"direction": "bearish housing"},
    })
    eid = db.load_recent_events(limit=1)[0]["id"]
    db.update_review(eid, rating="good", notes="Clean trade.")
    return eid


def _seed_minimal_event() -> int:
    db.save_event({
        "headline": "Minimal event for export",
        "stage": "developing",
        "persistence": "medium",
        "event_date": "2026-04-13",
    })
    return db.load_recent_events(limit=1)[0]["id"]


class _DBTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = _setup_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass


# ---------------------------------------------------------------------------
# 1) Successful JSON export
# ---------------------------------------------------------------------------

class TestSuccessfulExport(_DBTestCase):

    def test_returns_200(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/json")
        self.assertEqual(resp.status_code, 200)

    def test_content_type_is_json(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/json")
        self.assertIn("application/json", resp.headers["content-type"])

    def test_headline_present(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        self.assertEqual(data["headline"], "Fed raises rates by 50bp")

    def test_id_matches(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        self.assertEqual(data["id"], eid)

    def test_market_tickers_present(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        self.assertIsInstance(data["market_tickers"], list)
        self.assertEqual(data["market_tickers"][0]["symbol"], "XLF")

    def test_rating_and_notes_present(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        self.assertEqual(data["rating"], "good")
        self.assertEqual(data["notes"], "Clean trade.")

    def test_transmission_chain_present(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        self.assertEqual(data["transmission_chain"], ["rates up", "housing slows", "REITs sell"])

    def test_minimal_event_exports(self):
        eid = _seed_minimal_event()
        resp = self.client.get(f"/events/{eid}/export/json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["headline"], "Minimal event for export")
        self.assertEqual(data["stage"], "developing")

    def test_internal_fields_excluded(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        for internal_key in ("low_signal", "model", "last_market_check_at"):
            self.assertNotIn(internal_key, data,
                             f"Internal field '{internal_key}' should not be in export")


# ---------------------------------------------------------------------------
# 2) Missing event
# ---------------------------------------------------------------------------

class TestMissingEvent(_DBTestCase):

    def test_404_for_nonexistent_id(self):
        resp = self.client.get("/events/99999/export/json")
        self.assertEqual(resp.status_code, 404)

    def test_404_body_mentions_id(self):
        resp = self.client.get("/events/99999/export/json")
        self.assertIn("99999", resp.text)


# ---------------------------------------------------------------------------
# 3) Stable key presence/order
# ---------------------------------------------------------------------------

class TestStableKeys(_DBTestCase):

    def test_all_export_keys_present(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        for key in _JSON_EXPORT_KEYS:
            self.assertIn(key, data, f"Missing export key: {key}")

    def test_no_extra_keys(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        extra = set(data.keys()) - set(_JSON_EXPORT_KEYS)
        self.assertEqual(extra, set(), f"Unexpected extra keys: {extra}")

    def test_key_order_matches_spec(self):
        eid = _seed_full_event()
        data = self.client.get(f"/events/{eid}/export/json").json()
        actual_keys = list(data.keys())
        expected_keys = list(_JSON_EXPORT_KEYS)
        self.assertEqual(actual_keys, expected_keys)

    def test_existing_text_endpoint_unchanged(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/text")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers["content-type"])

    def test_existing_markdown_endpoint_unchanged(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/markdown")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp.headers["content-type"])


# ---------------------------------------------------------------------------
# 4) Overlay registry drift — every persisted overlay reaches the export
# ---------------------------------------------------------------------------

class TestOverlayRegistryCoverage(_DBTestCase):
    """Every persisted overlay flows into the JSON export and carries the
    degraded contract even when the row never wrote a value."""

    def test_every_persisted_overlay_is_in_export_keys(self):
        """PERSISTED_OVERLAY_FIELDS minus intentional excludes must all
        appear in _JSON_EXPORT_KEYS.  Guards against the old drift where
        three persisted overlays silently disappeared on export."""
        from events_export import EXPORT_OVERLAY_FIELDS
        for field in EXPORT_OVERLAY_FIELDS:
            self.assertIn(field, _JSON_EXPORT_KEYS,
                          f"Persisted overlay '{field}' missing from JSON export")

    def test_export_overlay_fields_excludes_regime_snapshot(self):
        """regime_snapshot is an internal analog-reranker key — never user-facing."""
        from events_export import EXPORT_OVERLAY_FIELDS
        self.assertNotIn("regime_snapshot", EXPORT_OVERLAY_FIELDS)

    def test_missing_overlays_carry_degraded_contract(self):
        """An event with no persisted overlay values must still emit the
        overlay keys, each populated with the explicit degraded block."""
        eid = _seed_minimal_event()
        data = self.client.get(f"/events/{eid}/export/json").json()

        from events_export import EXPORT_OVERLAY_FIELDS
        for field in EXPORT_OVERLAY_FIELDS:
            overlay = data[field]
            self.assertIsInstance(overlay, dict,
                                  f"{field} must be a dict on export")
            self.assertIn("available", overlay, f"{field} missing available")
            self.assertIn("stale", overlay, f"{field} missing stale")
            self.assertIn("degraded", overlay, f"{field} missing degraded")
            self.assertIn("degraded_reason", overlay,
                          f"{field} missing degraded_reason")
            self.assertFalse(overlay["available"],
                             f"{field} should be unavailable for empty row")
            self.assertTrue(overlay["degraded"],
                            f"{field} should be degraded when empty")


if __name__ == "__main__":
    unittest.main()
