"""
tests/test_event_markdown_export.py

Focused tests for the GET /events/{id}/export/markdown endpoint.

  1) Successful markdown export — returns well-formed Markdown with expected sections.
  2) Missing event — returns 404.
  3) Stable section order/headers — headings appear in a fixed sequence.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db() -> str:
    path = os.path.join(tempfile.gettempdir(),
                        f"test_md_export_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    return path


def _seed_full_event() -> int:
    """Seed one event with all fields populated. Returns event_id."""
    db.save_event({
        "timestamp": "2026-04-13T10:00:00",
        "headline": "OPEC cuts output sharply",
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "OPEC announced 1.5M bpd production cut",
        "mechanism_summary": "Reduced supply lifts crude benchmarks, energy equities rally",
        "beneficiaries": ["XOM", "CVX"],
        "losers": ["DAL", "UAL"],
        "assets_to_watch": ["CL=F", "XLE"],
        "confidence": "high",
        "market_note": "Strong move across energy complex",
        "market_tickers": [
            {"symbol": "XOM", "role": "beneficiary", "return_1d": 1.2,
             "return_5d": 3.5, "return_20d": 5.0, "direction_tag": "supports thesis",
             "volume_ratio": 1.3, "vs_xle_5d": 0.5, "spark": [0.5] * 20},
            {"symbol": "DAL", "role": "loser", "return_1d": -0.8,
             "return_5d": -2.1, "return_20d": -3.0, "direction_tag": "supports thesis",
             "volume_ratio": 0.9, "vs_xle_5d": None, "spark": [0.5] * 20},
        ],
        "event_date": "2026-04-13",
    })
    events = db.load_recent_events(limit=1)
    eid = events[0]["id"]
    # Add a rating + notes via update_review
    db.update_review(eid, rating="good", notes="Clean energy thesis confirmed.")
    return eid


def _seed_minimal_event() -> int:
    """Seed an event with only required fields."""
    db.save_event({
        "headline": "Minimal event",
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
# 1) Successful markdown export
# ---------------------------------------------------------------------------

class TestSuccessfulExport(_DBTestCase):

    def test_returns_200_with_markdown_content_type(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/markdown")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp.headers["content-type"])

    def test_attachment_filename(self):
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/markdown")
        disp = resp.headers.get("content-disposition", "")
        self.assertIn(".md", disp)
        self.assertIn(str(eid), disp)

    def test_headline_in_h1(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("# OPEC cuts output sharply", body)

    def test_what_changed_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("1.5M bpd production cut", body)

    def test_mechanism_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("Reduced supply lifts crude", body)

    def test_beneficiaries_and_losers_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("XOM", body)
        self.assertIn("DAL", body)

    def test_market_table_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("| Ticker |", body)
        self.assertIn("+3.50%", body)

    def test_review_section_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("## Review", body)
        self.assertIn("good", body)
        self.assertIn("Clean energy thesis confirmed", body)

    def test_minimal_event_still_exports(self):
        eid = _seed_minimal_event()
        resp = self.client.get(f"/events/{eid}/export/markdown")
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("# Minimal event", body)

    def test_footer_present(self):
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertIn("Second Order", body)
        self.assertIn("Generated", body)


# ---------------------------------------------------------------------------
# 2) Missing event
# ---------------------------------------------------------------------------

class TestMissingEvent(_DBTestCase):

    def test_404_for_nonexistent_id(self):
        resp = self.client.get("/events/99999/export/markdown")
        self.assertEqual(resp.status_code, 404)

    def test_404_body_contains_id(self):
        resp = self.client.get("/events/99999/export/markdown")
        self.assertIn("99999", resp.text)


# ---------------------------------------------------------------------------
# 3) Stable section order/headers
# ---------------------------------------------------------------------------

class TestSectionOrder(_DBTestCase):

    def test_section_order_is_fixed(self):
        """Headers must appear in this exact order when all sections are present."""
        eid = _seed_full_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text

        expected_order = [
            "# OPEC cuts output sharply",
            "## What Changed",
            "## Mechanism",
            "## Affected Assets",
            "## Market Check",
            "## Review",
        ]
        positions = []
        for heading in expected_order:
            pos = body.find(heading)
            self.assertGreater(pos, -1, f"Missing heading: {heading}")
            positions.append(pos)

        for i in range(len(positions) - 1):
            self.assertLess(
                positions[i], positions[i + 1],
                f"'{expected_order[i]}' should appear before '{expected_order[i + 1]}'",
            )

    def test_optional_sections_omitted_when_empty(self):
        """Minimal event should not have Market Check or Review headings."""
        eid = _seed_minimal_event()
        body = self.client.get(f"/events/{eid}/export/markdown").text
        self.assertNotIn("## Market Check", body)
        self.assertNotIn("## Review", body)

    def test_text_endpoint_still_works(self):
        """The existing plain-text export is unaffected."""
        eid = _seed_full_event()
        resp = self.client.get(f"/events/{eid}/export/text")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/plain", resp.headers["content-type"])


if __name__ == "__main__":
    unittest.main()
