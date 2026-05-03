"""
tests/test_event_export_csv.py

Focused tests for GET /events/{event_id}/export/csv.

Proves three invariants:
  1) Successful CSV export — 200, text/csv, attachment header.
  2) 404 for a missing event.
  3) Stable header/row shape — columns match CSV_COLUMNS; exactly one data row.

No LLM or market calls — events are seeded directly into the DB.
"""

from __future__ import annotations

import csv
import io
import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
from api import _build_event_csv_export
from events_export import CSV_COLUMNS
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Helper — seed an event and return its id
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    return os.path.join(tempfile.gettempdir(), f"test_export_csv_{uuid.uuid4().hex}.db")


def _seed_event(**kwargs) -> int:
    defaults = {
        "headline": "ECB cuts rates by 25bp",
        "stage": "realized",
        "persistence": "transitory",
        "event_date": "2026-04-13",
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "what_changed": "ECB reduced the deposit rate.",
        "mechanism_summary": "Lower rates ease credit conditions.",
        "beneficiaries": ["Equities", "Property"],
        "losers": ["EUR", "Savers"],
        "assets_to_watch": ["EUO", "EURUSD"],
        "confidence": "medium",
        "market_note": "Broad euro weakness.",
        "market_tickers": [
            {
                "symbol": "EUO",
                "role": "beneficiary",
                "return_1d": 0.60,
                "return_5d": 1.80,
                "return_20d": 3.50,
                "volume_ratio": 1.3,
                "direction_tag": "supports \u2191",
                "label": "in motion",
            },
        ],
        "rating": "mixed",
        "notes": "Watch if cut cycle continues.",
    }
    defaults.update(kwargs)
    db.save_event(defaults)
    return db.load_recent_events(1)[0]["id"]


# ---------------------------------------------------------------------------
# Base — isolated temp DB
# ---------------------------------------------------------------------------

class _CsvBase(unittest.TestCase):
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
# 1) Successful CSV export — HTTP contract
# ---------------------------------------------------------------------------

class TestCsvHttpContract(_CsvBase):

    def test_200_for_existing_event(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/csv")
        self.assertEqual(resp.status_code, 200)

    def test_content_type_is_text_csv(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/csv")
        self.assertIn("text/csv", resp.headers["content-type"])

    def test_content_disposition_is_attachment(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/csv")
        cd = resp.headers.get("content-disposition", "")
        self.assertIn("attachment", cd)
        self.assertIn(".csv", cd)

    def test_filename_contains_event_id(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/csv")
        cd = resp.headers.get("content-disposition", "")
        self.assertIn(str(eid), cd)

    def test_body_is_non_empty(self):
        eid = _seed_event()
        resp = client.get(f"/events/{eid}/export/csv")
        self.assertGreater(len(resp.text), 0)


# ---------------------------------------------------------------------------
# 2) 404 for missing event
# ---------------------------------------------------------------------------

class TestCsvMissing(_CsvBase):

    def test_404_for_nonexistent_id(self):
        resp = client.get("/events/999999/export/csv")
        self.assertEqual(resp.status_code, 404)

    def test_404_detail_contains_event_id(self):
        resp = client.get("/events/999999/export/csv")
        self.assertIn("999999", resp.json()["detail"])

    def test_404_for_zero_id(self):
        self.assertEqual(client.get("/events/0/export/csv").status_code, 404)


# ---------------------------------------------------------------------------
# 3) Stable header / row shape — _build_event_csv_export unit tests
# ---------------------------------------------------------------------------

def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


class TestCsvShape(unittest.TestCase):
    """Tests for _build_event_csv_export — no HTTP needed."""

    def _base_event(self, **kwargs) -> dict:
        base = {
            "id": 1,
            "headline": "ECB cuts rates by 25bp",
            "stage": "realized",
            "persistence": "transitory",
            "event_date": "2026-04-13",
            "timestamp": "2026-04-13T10:00:00",
            "what_changed": "ECB reduced the deposit rate.",
            "mechanism_summary": "Lower rates ease credit conditions.",
            "beneficiaries": ["Equities", "Property"],
            "losers": ["EUR", "Savers"],
            "assets_to_watch": ["EUO"],
            "confidence": "medium",
            "market_note": "Broad euro weakness.",
            "market_tickers": [],
            "rating": "mixed",
            "notes": "Watch if cut cycle continues.",
        }
        base.update(kwargs)
        return base

    def test_header_matches_csv_columns(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        self.assertEqual(rows[0], list(CSV_COLUMNS))

    def test_exactly_one_data_row(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        # header + 1 data row = 2 rows (the trailing newline may add an empty row)
        data_rows = [r for r in rows[1:] if r]
        self.assertEqual(len(data_rows), 1)

    def test_id_column_matches(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event(id=42)))
        header = rows[0]
        data = rows[1]
        idx = header.index("id")
        self.assertEqual(data[idx], "42")

    def test_headline_column_matches(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        header = rows[0]
        data = rows[1]
        idx = header.index("headline")
        self.assertEqual(data[idx], "ECB cuts rates by 25bp")

    def test_stage_column_matches(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        header = rows[0]
        data = rows[1]
        idx = header.index("stage")
        self.assertEqual(data[idx], "realized")

    def test_confidence_column_matches(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        header = rows[0]
        data = rows[1]
        idx = header.index("confidence")
        self.assertEqual(data[idx], "medium")

    def test_beneficiaries_are_json_encoded(self):
        import json
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        header = rows[0]
        data = rows[1]
        idx = header.index("beneficiaries")
        parsed = json.loads(data[idx])
        self.assertIn("Equities", parsed)
        self.assertIn("Property", parsed)

    def test_losers_are_json_encoded(self):
        import json
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        header = rows[0]
        data = rows[1]
        idx = header.index("losers")
        parsed = json.loads(data[idx])
        self.assertIn("EUR", parsed)

    def test_tickers_are_json_encoded_when_present(self):
        import json
        ev = self._base_event(market_tickers=[{
            "symbol": "EUO",
            "role": "beneficiary",
            "return_1d": 0.60,
            "return_5d": 1.80,
            "return_20d": 3.50,
            "volume_ratio": 1.3,
            "direction_tag": "supports \u2191",
        }])
        rows = _parse_csv(_build_event_csv_export(ev))
        header = rows[0]
        data = rows[1]
        idx = header.index("market_tickers")
        parsed = json.loads(data[idx])
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["symbol"], "EUO")

    def test_followthrough_best_5d_derived_from_tickers(self):
        ev = self._base_event(market_tickers=[{
            "symbol": "EUO",
            "role": "beneficiary",
            "return_1d": 0.60,
            "return_5d": 1.80,
            "return_20d": 3.50,
            "volume_ratio": 1.3,
            "direction_tag": "supports \u2191",
        }])
        rows = _parse_csv(_build_event_csv_export(ev))
        header = rows[0]
        data = rows[1]
        idx = header.index("followthrough_best_5d")
        self.assertAlmostEqual(float(data[idx]), 1.80, places=4)

    def test_empty_optional_fields_produce_empty_cells(self):
        ev = self._base_event(what_changed=None, mechanism_summary=None, market_note=None)
        rows = _parse_csv(_build_event_csv_export(ev))
        header = rows[0]
        data = rows[1]
        for col in ("what_changed", "mechanism_summary", "market_note"):
            idx = header.index(col)
            self.assertEqual(data[idx], "")

    def test_csv_is_deterministic(self):
        ev = self._base_event()
        self.assertEqual(_build_event_csv_export(ev), _build_event_csv_export(ev))

    def test_column_count_matches_csv_columns(self):
        rows = _parse_csv(_build_event_csv_export(self._base_event()))
        self.assertEqual(len(rows[0]), len(CSV_COLUMNS))
        self.assertEqual(len(rows[1]), len(CSV_COLUMNS))


# ---------------------------------------------------------------------------
# 4) Overlay registry drift — CSV must not silently drop persisted overlays
# ---------------------------------------------------------------------------

class TestCsvOverlayCoverage(unittest.TestCase):
    """Every persisted overlay in EXPORT_OVERLAY_FIELDS must have a column
    and must carry the sanitized degraded contract when the row is empty."""

    def _bare_event(self) -> dict:
        return {
            "id": 7,
            "headline": "bare",
            "stage": "developing",
            "persistence": "medium",
            "event_date": "2026-04-13",
            "timestamp": "2026-04-13T10:00:00",
            "market_tickers": [],
        }

    def test_every_overlay_field_has_csv_column(self):
        from events_export import EXPORT_OVERLAY_FIELDS
        for field in EXPORT_OVERLAY_FIELDS:
            self.assertIn(field, CSV_COLUMNS,
                          f"Overlay '{field}' dropped on CSV export")

    def test_empty_overlay_cell_is_degraded_json(self):
        import json
        from events_export import EXPORT_OVERLAY_FIELDS
        rows = _parse_csv(_build_event_csv_export(self._bare_event()))
        header, data = rows[0], rows[1]
        for field in EXPORT_OVERLAY_FIELDS:
            idx = header.index(field)
            parsed = json.loads(data[idx])
            self.assertFalse(parsed["available"], f"{field} should be unavailable")
            self.assertTrue(parsed["degraded"], f"{field} should be degraded")


if __name__ == "__main__":
    unittest.main()
