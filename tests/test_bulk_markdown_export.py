"""
tests/test_bulk_markdown_export.py

Focused tests for POST /events/export/markdown (bulk).

  1) Successful multi-event export.
  2) Mixed valid/missing IDs.
  3) Stable section ordering.
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
                        f"test_bulk_md_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    return path


def _seed(headline: str, mechanism: str = "Mechanism") -> int:
    db.save_event({
        "timestamp": "2026-04-13T10:00:00",
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "Something changed",
        "mechanism_summary": mechanism,
        "beneficiaries": ["XOM"],
        "losers": ["DAL"],
        "confidence": "high",
        "market_note": "note",
        "market_tickers": [
            {"symbol": "XOM", "role": "beneficiary", "return_1d": 1.0,
             "return_5d": 3.5, "return_20d": 5.0, "direction_tag": "supports thesis",
             "volume_ratio": 1.2, "vs_xle_5d": None, "spark": [0.5] * 20},
        ],
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
# 1) Successful multi-event export
# ---------------------------------------------------------------------------

class TestSuccessfulBulkExport(_DBTestCase):

    def test_returns_200_with_markdown(self):
        id1 = _seed("OPEC cuts output")
        id2 = _seed("Fed raises rates")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [id1, id2]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp.headers["content-type"])

    def test_both_headlines_in_body(self):
        id1 = _seed("OPEC cuts output")
        id2 = _seed("Fed raises rates")
        body = self.client.post("/events/export/markdown",
                                json={"event_ids": [id1, id2]}).text
        self.assertIn("# OPEC cuts output", body)
        self.assertIn("# Fed raises rates", body)

    def test_events_separated_by_hr(self):
        id1 = _seed("Event A")
        id2 = _seed("Event B")
        body = self.client.post("/events/export/markdown",
                                json={"event_ids": [id1, id2]}).text
        self.assertIn("---", body)

    def test_single_event_works(self):
        eid = _seed("Solo event")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [eid]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Solo event", resp.text)
        # No inter-event separator for a single event (the memo's own
        # footer "---" is internal to the memo, not an inter-event sep).
        self.assertNotIn("\n\n---\n\n", resp.text)

    def test_attachment_filename(self):
        eid = _seed("Test")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [eid]})
        disp = resp.headers.get("content-disposition", "")
        self.assertIn("research_packet.md", disp)

    def test_existing_single_endpoint_unchanged(self):
        eid = _seed("Unchanged test")
        resp = self.client.get(f"/events/{eid}/export/markdown")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/markdown", resp.headers["content-type"])


# ---------------------------------------------------------------------------
# 2) Mixed valid/missing IDs
# ---------------------------------------------------------------------------

class TestMixedValidMissing(_DBTestCase):

    def test_valid_and_missing_returns_200_with_valid_only(self):
        eid = _seed("Real event")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [eid, 99999]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("# Real event", resp.text)

    def test_skipped_header_lists_missing_ids(self):
        eid = _seed("Real event")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [eid, 99999, 88888]})
        skipped = resp.headers.get("x-skipped-ids", "")
        self.assertIn("99999", skipped)
        self.assertIn("88888", skipped)

    def test_all_missing_returns_404(self):
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [99999, 88888]})
        self.assertEqual(resp.status_code, 404)

    def test_empty_list_rejected(self):
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": []})
        self.assertEqual(resp.status_code, 422)

    def test_no_skipped_header_when_all_valid(self):
        id1 = _seed("A")
        id2 = _seed("B")
        resp = self.client.post("/events/export/markdown",
                                json={"event_ids": [id1, id2]})
        skipped = resp.headers.get("x-skipped-ids", "")
        self.assertEqual(skipped, "")


# ---------------------------------------------------------------------------
# 3) Stable section ordering
# ---------------------------------------------------------------------------

class TestSectionOrdering(_DBTestCase):

    def test_events_emitted_in_request_order(self):
        id1 = _seed("Alpha event")
        id2 = _seed("Beta event")
        id3 = _seed("Gamma event")
        body = self.client.post("/events/export/markdown",
                                json={"event_ids": [id3, id1, id2]}).text
        pos_gamma = body.find("# Gamma event")
        pos_alpha = body.find("# Alpha event")
        pos_beta = body.find("# Beta event")
        self.assertLess(pos_gamma, pos_alpha)
        self.assertLess(pos_alpha, pos_beta)

    def test_each_event_has_stable_internal_order(self):
        eid = _seed("Structured event", mechanism="Supply shock mechanism")
        body = self.client.post("/events/export/markdown",
                                json={"event_ids": [eid]}).text
        headings = ["# Structured event", "## What Changed",
                     "## Mechanism", "## Affected Assets", "## Market Check"]
        positions = []
        for h in headings:
            pos = body.find(h)
            self.assertGreater(pos, -1, f"Missing heading: {h}")
            positions.append(pos)
        for i in range(len(positions) - 1):
            self.assertLess(positions[i], positions[i + 1])

    def test_separator_count_matches_event_count(self):
        ids = [_seed(f"Event {i}") for i in range(3)]
        body = self.client.post("/events/export/markdown",
                                json={"event_ids": ids}).text
        # N events → N-1 separators
        self.assertEqual(body.count("\n\n---\n\n"), 2)


if __name__ == "__main__":
    unittest.main()
