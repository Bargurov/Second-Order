"""
tests/test_bulk_zip_export.py

Focused tests for POST /events/export/zip.

  1) Successful ZIP export.
  2) Mixed valid/missing IDs.
  3) Stable filenames/order.
"""

from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest
import uuid
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db
import api


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setup_db() -> str:
    path = os.path.join(tempfile.gettempdir(),
                        f"test_zip_export_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    return path


def _seed(headline: str) -> int:
    db.save_event({
        "timestamp": "2026-04-13T10:00:00",
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "what_changed": "Something changed",
        "mechanism_summary": "A real mechanism",
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


def _open_zip(resp) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BytesIO(resp.content))


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
# 1) Successful ZIP export
# ---------------------------------------------------------------------------

class TestSuccessfulZipExport(_DBTestCase):

    def test_returns_200_with_zip_content_type(self):
        eid = _seed("OPEC cuts output")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("application/zip", resp.headers["content-type"])

    def test_attachment_filename(self):
        eid = _seed("Test")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        disp = resp.headers.get("content-disposition", "")
        self.assertIn("research_packet.zip", disp)

    def test_zip_is_valid(self):
        eid = _seed("Valid zip test")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        self.assertTrue(zf.testzip() is None, "ZIP is corrupt")

    def test_single_event_produces_one_file(self):
        eid = _seed("Solo event")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        self.assertEqual(len(zf.namelist()), 1)

    def test_multi_event_produces_one_file_per_event(self):
        id1 = _seed("Event A")
        id2 = _seed("Event B")
        id3 = _seed("Event C")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [id1, id2, id3]})
        zf = _open_zip(resp)
        self.assertEqual(len(zf.namelist()), 3)

    def test_file_content_is_markdown(self):
        eid = _seed("Markdown content test")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        name = zf.namelist()[0]
        content = zf.read(name).decode("utf-8")
        self.assertIn("# Markdown content test", content)
        self.assertIn("## What Changed", content)

    def test_existing_endpoints_unchanged(self):
        eid = _seed("Unchanged test")
        # Single markdown
        r1 = self.client.get(f"/events/{eid}/export/markdown")
        self.assertEqual(r1.status_code, 200)
        # Bulk markdown
        r2 = self.client.post("/events/export/markdown",
                              json={"event_ids": [eid]})
        self.assertEqual(r2.status_code, 200)


# ---------------------------------------------------------------------------
# 2) Mixed valid/missing IDs
# ---------------------------------------------------------------------------

class TestMixedValidMissing(_DBTestCase):

    def test_valid_and_missing_returns_200(self):
        eid = _seed("Real event")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid, 99999]})
        self.assertEqual(resp.status_code, 200)
        zf = _open_zip(resp)
        self.assertEqual(len(zf.namelist()), 1)

    def test_skipped_header_lists_missing(self):
        eid = _seed("Real event")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid, 99999, 88888]})
        skipped = resp.headers.get("x-skipped-ids", "")
        self.assertIn("99999", skipped)
        self.assertIn("88888", skipped)

    def test_all_missing_returns_404(self):
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [99999]})
        self.assertEqual(resp.status_code, 404)

    def test_empty_list_rejected(self):
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": []})
        self.assertEqual(resp.status_code, 422)

    def test_no_skipped_header_when_all_valid(self):
        id1 = _seed("A")
        id2 = _seed("B")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [id1, id2]})
        skipped = resp.headers.get("x-skipped-ids", "")
        self.assertEqual(skipped, "")


# ---------------------------------------------------------------------------
# 3) Stable filenames/order
# ---------------------------------------------------------------------------

class TestStableFilenamesAndOrder(_DBTestCase):

    def test_filenames_contain_event_id_and_slug(self):
        eid = _seed("OPEC cuts output sharply")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        name = zf.namelist()[0]
        self.assertIn(str(eid), name)
        self.assertIn("OPEC", name)
        self.assertTrue(name.endswith(".md"))

    def test_filenames_are_filesystem_safe(self):
        eid = _seed("Event with spaces & special chars! (2026)")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        name = zf.namelist()[0]
        # No spaces, no special chars except _ and -
        for ch in name:
            self.assertTrue(
                ch.isalnum() or ch in "_-.",
                f"Unexpected char '{ch}' in filename '{name}'",
            )

    def test_files_in_request_order(self):
        id1 = _seed("Alpha")
        id2 = _seed("Beta")
        id3 = _seed("Gamma")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [id3, id1, id2]})
        zf = _open_zip(resp)
        names = zf.namelist()
        self.assertEqual(len(names), 3)
        # Order: Gamma, Alpha, Beta (matching request order)
        self.assertIn("Gamma", names[0])
        self.assertIn("Alpha", names[1])
        self.assertIn("Beta", names[2])

    def test_each_file_has_stable_headings(self):
        eid = _seed("Structured event")
        resp = self.client.post("/events/export/zip",
                                json={"event_ids": [eid]})
        zf = _open_zip(resp)
        content = zf.read(zf.namelist()[0]).decode("utf-8")
        # Same heading order as single-event markdown export
        headings = ["# Structured event", "## What Changed", "## Mechanism"]
        positions = [content.find(h) for h in headings]
        self.assertTrue(all(p >= 0 for p in positions),
                        f"Missing headings in: {content[:200]}")
        for i in range(len(positions) - 1):
            self.assertLess(positions[i], positions[i + 1])


if __name__ == "__main__":
    unittest.main()
