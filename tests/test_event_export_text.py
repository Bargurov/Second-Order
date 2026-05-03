"""
tests/test_event_export_text.py

Focused tests for GET /events/{event_id}/export/text.

Proves three invariants:
  1) Export of an existing event returns 200 text/plain with key sections.
  2) 404 is returned cleanly for a missing event.
  3) Text content is accurate — all stored fields appear in the output.

No LLM or market calls — events are seeded directly into the DB.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
from api import _build_event_text_memo
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Helper — seed a rich event and return its id
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    return os.path.join(tempfile.gettempdir(), f"test_export_txt_{uuid.uuid4().hex}.db")


def _seed_event(**kwargs) -> int:
    defaults = {
        "headline": "Fed raises rates by 50bp",
        "stage": "realized",
        "persistence": "structural",
        "event_date": "2026-04-13",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "what_changed": "Federal Reserve increased the federal funds rate target.",
        "mechanism_summary": "Higher rates tighten financial conditions.",
        "beneficiaries": ["Banks", "Money-market funds"],
        "losers": ["Rate-sensitive REITs", "Long-duration bonds"],
        "assets_to_watch": ["TLT", "XLF"],
        "confidence": "high",
        "market_note": "Elevated volume across rate proxies.",
        "market_tickers": [
            {
                "symbol": "TLT",
                "role": "loser",
                "return_1d": -1.25,
                "return_5d": -3.40,
                "return_20d": -6.80,
                "volume_ratio": 2.1,
                "direction_tag": "supports \u2193",
                "label": "notable move",
            },
            {
                "symbol": "XLF",
                "role": "beneficiary",
                "return_1d": 0.85,
                "return_5d": 2.10,
                "return_20d": 4.50,
                "volume_ratio": 1.4,
                "direction_tag": "supports \u2191",
                "label": "in motion",
            },
        ],
        "rating": "good",
        "notes": "Watch follow-through after next FOMC.",
    }
    defaults.update(kwargs)
    db.save_event(defaults)
    return db.load_recent_events(1)[0]["id"]


# ---------------------------------------------------------------------------
# Base — isolated temp DB
# ---------------------------------------------------------------------------

class _ExportBase(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
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


# ---------------------------------------------------------------------------
# 1) Export of existing event — HTTP contract
# ---------------------------------------------------------------------------

class TestExportHttpContract(_ExportBase):

    def test_200_for_existing_event(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/text")
        self.assertEqual(resp.status_code, 200)

    def test_content_type_is_text_plain(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/text")
        self.assertIn("text/plain", resp.headers["content-type"])

    def test_content_disposition_is_attachment(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/text")
        cd = resp.headers.get("content-disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".txt", cd)

    def test_filename_contains_event_id(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/text")
        cd = resp.headers.get("content-disposition", "")
        self.assertIn(str(eid), cd)


# ---------------------------------------------------------------------------
# 2) 404 for missing event
# ---------------------------------------------------------------------------

class TestExportMissing(_ExportBase):

    def test_404_for_nonexistent_id(self):
        resp = client.get("/events/999999/export/text")
        self.assertEqual(resp.status_code, 404)

    def test_404_detail_contains_event_id(self):
        resp = client.get("/events/999999/export/text")
        self.assertIn("999999", resp.json()["detail"])

    def test_404_for_zero_id(self):
        self.assertEqual(client.get("/events/0/export/text").status_code, 404)


# ---------------------------------------------------------------------------
# 3) Text content accuracy — _build_event_text_memo unit tests
# ---------------------------------------------------------------------------

class TestMemoContent(unittest.TestCase):
    """Tests for the pure _build_event_text_memo function — no HTTP needed."""

    def _base_event(self, **kwargs) -> dict:
        base = {
            "id": 1,
            "headline": "Fed raises rates by 50bp",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2026-04-13",
            "timestamp": "2026-04-13T10:00:00",
            "what_changed": "Rate increased.",
            "mechanism_summary": "Higher cost of capital.",
            "beneficiaries": ["Banks"],
            "losers": ["REITs"],
            "assets_to_watch": ["TLT"],
            "confidence": "high",
            "market_note": "High volume.",
            "market_tickers": [],
            "rating": "good",
            "notes": "Watch FOMC.",
        }
        base.update(kwargs)
        return base

    def test_header_present(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("SECOND ORDER", memo)

    def test_headline_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("Fed raises rates by 50bp", memo)

    def test_event_date_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("2026-04-13", memo)

    def test_stage_and_persistence_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("realized", memo)
        self.assertIn("structural", memo)

    def test_confidence_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("high confidence", memo)

    def test_what_changed_section(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("WHAT CHANGED", memo)
        self.assertIn("Rate increased.", memo)

    def test_mechanism_section(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("MECHANISM", memo)
        self.assertIn("Higher cost of capital.", memo)

    def test_beneficiaries_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("Banks", memo)

    def test_losers_in_memo(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("REITs", memo)

    def test_market_check_section_with_tickers(self):
        ev = self._base_event(market_tickers=[{
            "symbol": "TLT",
            "role": "loser",
            "return_1d": -1.25,
            "return_5d": -3.40,
            "return_20d": -6.80,
            "volume_ratio": 2.1,
            "direction_tag": "supports \u2193",
        }])
        memo = _build_event_text_memo(ev)
        self.assertIn("MARKET CHECK", memo)
        self.assertIn("TLT", memo)
        self.assertIn("-1.25%", memo)
        self.assertIn("-3.40%", memo)

    def test_market_note_in_memo(self):
        ev = self._base_event(market_tickers=[{
            "symbol": "TLT", "role": "loser",
            "return_1d": -1.0, "return_5d": -3.0, "return_20d": -6.0,
            "volume_ratio": 2.1, "direction_tag": "supports \u2193",
        }])
        memo = _build_event_text_memo(ev)
        self.assertIn("High volume.", memo)

    def test_rating_in_review_section(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("REVIEW", memo)
        self.assertIn("good", memo)

    def test_notes_in_review_section(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("Watch FOMC.", memo)

    def test_generated_timestamp_in_footer(self):
        memo = _build_event_text_memo(self._base_event())
        self.assertIn("Generated", memo)
        self.assertIn("UTC", memo)

    def test_no_market_section_when_no_tickers(self):
        ev = self._base_event(market_tickers=[])
        memo = _build_event_text_memo(ev)
        self.assertNotIn("MARKET CHECK", memo)

    def test_no_review_section_when_no_rating_or_notes(self):
        ev = self._base_event(rating=None, notes=None)
        memo = _build_event_text_memo(ev)
        self.assertNotIn("REVIEW", memo)

    def test_empty_optional_fields_do_not_crash(self):
        """Minimal event with only required fields must not raise."""
        ev = {
            "id": 2,
            "headline": "Minimal event",
            "stage": "developing",
            "persistence": "transitory",
            "confidence": "low",
            "timestamp": "2026-04-13T10:00:00",
            "event_date": None,
            "what_changed": None,
            "mechanism_summary": None,
            "beneficiaries": [],
            "losers": [],
            "market_tickers": [],
            "market_note": None,
            "rating": None,
            "notes": None,
        }
        memo = _build_event_text_memo(ev)
        self.assertIn("Minimal event", memo)

    def test_memo_is_deterministic(self):
        """Same event → identical memo on every call (modulo the timestamp)."""
        ev = self._base_event()
        # Strip Generated line before comparing since it has a live timestamp
        def strip_generated(m):
            return "\n".join(l for l in m.splitlines() if not l.startswith("Generated"))
        self.assertEqual(
            strip_generated(_build_event_text_memo(ev)),
            strip_generated(_build_event_text_memo(ev)),
        )

    def test_positive_returns_have_plus_sign(self):
        ev = self._base_event(market_tickers=[{
            "symbol": "XLF",
            "role": "beneficiary",
            "return_1d": 0.85,
            "return_5d": 2.10,
            "return_20d": 4.50,
            "volume_ratio": 1.4,
            "direction_tag": "supports \u2191",
        }])
        memo = _build_event_text_memo(ev)
        self.assertIn("+0.85%", memo)
        self.assertIn("+2.10%", memo)


if __name__ == "__main__":
    unittest.main()
