"""
tests/test_events_export.py

Focused tests for the saved events export capability.

Covers:
  * JSON export shape (count, fields, follow_through derivation)
  * CSV export columns and row rendering
  * Empty-archive behaviour for both formats
  * The /events/export endpoint wiring
"""

import csv
import io
import json
import os
import sys
import unittest
import uuid

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import events_export  # noqa: E402
from tests._db_isolation import TEMP_DB_DIR  # noqa: E402
from events_export import (  # noqa: E402
    CSV_COLUMNS,
    build_csv_export,
    build_json_export,
    load_events_for_export,
)


# ---------------------------------------------------------------------------
# Base: swaps DB_FILE to a temp file so each test has an isolated archive.
# ---------------------------------------------------------------------------


class _ExportBase(unittest.TestCase):

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = str(TEMP_DB_DIR / f"test_export_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except FileNotFoundError:
            pass

    # Tiny factory to reduce repetition.  Returns the saved event id.
    def _save_event(self, **overrides) -> int:
        record = {
            "headline": "Export test headline",
            "stage": "realized",
            "persistence": "structural",
            "what_changed": "Something changed",
            "mechanism_summary": "A → B → C",
            "beneficiaries": ["Alpha Corp"],
            "losers": ["Beta Corp"],
            "assets_to_watch": ["AAPL", "MSFT"],
            "confidence": "medium",
            "market_note": "Test note",
            "market_tickers": [
                {
                    "symbol": "AAPL",
                    "role": "beneficiary",
                    "return_1d": 0.5,
                    "return_5d": 1.2,
                    "return_20d": 3.8,
                    "direction": "supports thesis",
                },
                {
                    "symbol": "MSFT",
                    "role": "loser",
                    "return_1d": -0.1,
                    "return_5d": -2.5,
                    "return_20d": -1.0,
                    "direction": "contradicts thesis",
                },
            ],
            "event_date": "2026-03-15",
            "notes": "Initial research note",
            "model": "claude-test",
            "transmission_chain": ["a", "b", "c", "d"],
            "if_persists": {"horizon": "weeks", "delayed_winners": ["X"]},
            "currency_channel": {"pair": "USDJPY"},
            "policy_sensitivity": {"stance": "neutral"},
            "inventory_context": {"status": "tight"},
            "low_signal": 0,
        }
        record.update(overrides)
        db.save_event(record)
        return db.load_recent_events(1)[0]["id"]


# ---------------------------------------------------------------------------
# JSON export — shape and content
# ---------------------------------------------------------------------------


class TestJsonExportShape(_ExportBase):

    def test_json_export_counts_events(self):
        self._save_event(headline="JSON export A")
        self._save_event(headline="JSON export B")
        payload = build_json_export(load_events_for_export())
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["events"]), 2)

    def test_json_export_has_all_core_fields(self):
        self._save_event(headline="JSON core fields")
        payload = build_json_export(load_events_for_export())
        ev = payload["events"][0]
        for key in (
            "id", "timestamp", "headline", "stage", "persistence",
            "what_changed", "mechanism_summary", "beneficiaries", "losers",
            "assets_to_watch", "confidence", "market_note", "market_tickers",
            "event_date", "notes", "model", "transmission_chain",
            "if_persists", "currency_channel", "policy_sensitivity",
            "inventory_context", "rating", "low_signal", "follow_through",
        ):
            self.assertIn(key, ev, f"Export missing field: {key}")

    def test_json_export_follow_through_picks_largest_magnitude(self):
        """best_5d should be -2.5 (|-2.5| > |1.2|) from our two-ticker record."""
        self._save_event(headline="Follow-through magnitude")
        payload = build_json_export(load_events_for_export())
        ft = payload["events"][0]["follow_through"]
        self.assertAlmostEqual(ft["best_return_5d"], -2.5)
        self.assertAlmostEqual(ft["best_return_20d"], 3.8)
        # Direction is taken from the ticker carrying the best 5d magnitude.
        self.assertEqual(ft["best_direction"], "contradicts thesis")

    def test_json_export_follow_through_handles_missing_tickers(self):
        self._save_event(headline="No tickers", market_tickers=[])
        payload = build_json_export(load_events_for_export())
        ft = payload["events"][0]["follow_through"]
        self.assertIsNone(ft["best_return_5d"])
        self.assertIsNone(ft["best_return_20d"])
        self.assertIsNone(ft["best_direction"])

    def test_json_export_preserves_stored_labels(self):
        """Rating/notes/model/low_signal must round-trip through the export."""
        eid = self._save_event(headline="Labels round-trip")
        db.update_review(eid, rating="good", notes="strong signal")
        payload = build_json_export(load_events_for_export())
        ev = payload["events"][0]
        self.assertEqual(ev["rating"], "good")
        self.assertEqual(ev["notes"], "strong signal")
        self.assertEqual(ev["model"], "claude-test")
        self.assertEqual(ev["low_signal"], 0)

    def test_json_export_is_json_serialisable(self):
        self._save_event(headline="Serialisable check")
        payload = build_json_export(load_events_for_export())
        # Must round-trip through json.dumps without error.
        blob = json.dumps(payload)
        reparsed = json.loads(blob)
        self.assertEqual(reparsed["count"], 1)

    def test_json_export_deterministic_order(self):
        """Newest-first order so consecutive exports diff cleanly."""
        self._save_event(headline="Older", event_date="2026-02-01")
        self._save_event(headline="Newer", event_date="2026-04-01")
        payload = build_json_export(load_events_for_export())
        self.assertEqual(payload["events"][0]["headline"], "Newer")
        self.assertEqual(payload["events"][1]["headline"], "Older")


# ---------------------------------------------------------------------------
# CSV export — columns and rows
# ---------------------------------------------------------------------------


class TestCsvExport(_ExportBase):

    def _parse_csv(self, text: str) -> list[dict]:
        reader = csv.DictReader(io.StringIO(text))
        return list(reader)

    def test_csv_export_header_matches_column_contract(self):
        text = build_csv_export([])
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertEqual(tuple(header), CSV_COLUMNS)

    def test_csv_export_has_expected_columns(self):
        self._save_event(headline="CSV columns")
        text = build_csv_export(load_events_for_export())
        rows = self._parse_csv(text)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        # Scalar/core columns
        self.assertEqual(row["headline"], "CSV columns")
        self.assertEqual(row["stage"], "realized")
        self.assertEqual(row["persistence"], "structural")
        self.assertEqual(row["confidence"], "medium")
        self.assertEqual(row["event_date"], "2026-03-15")
        self.assertEqual(row["model"], "claude-test")

    def test_csv_export_serialises_nested_as_json(self):
        self._save_event(headline="CSV nested")
        text = build_csv_export(load_events_for_export())
        row = self._parse_csv(text)[0]
        # Lists/dicts must come out as valid JSON strings.
        self.assertEqual(json.loads(row["beneficiaries"]), ["Alpha Corp"])
        self.assertEqual(json.loads(row["losers"]), ["Beta Corp"])
        self.assertEqual(
            json.loads(row["transmission_chain"]), ["a", "b", "c", "d"],
        )
        tickers = json.loads(row["market_tickers"])
        self.assertEqual(len(tickers), 2)
        self.assertEqual(tickers[0]["symbol"], "AAPL")
        ip = json.loads(row["if_persists"])
        self.assertEqual(ip["horizon"], "weeks")

    def test_csv_export_includes_follow_through_columns(self):
        self._save_event(headline="CSV follow-through")
        text = build_csv_export(load_events_for_export())
        row = self._parse_csv(text)[0]
        self.assertIn("followthrough_best_5d", row)
        self.assertIn("followthrough_best_20d", row)
        self.assertIn("followthrough_direction", row)
        self.assertAlmostEqual(float(row["followthrough_best_5d"]), -2.5)
        self.assertAlmostEqual(float(row["followthrough_best_20d"]), 3.8)
        self.assertEqual(row["followthrough_direction"], "contradicts thesis")

    def test_csv_export_handles_null_follow_through(self):
        self._save_event(headline="CSV null ft", market_tickers=[])
        text = build_csv_export(load_events_for_export())
        row = self._parse_csv(text)[0]
        self.assertEqual(row["followthrough_best_5d"], "")
        self.assertEqual(row["followthrough_best_20d"], "")
        self.assertEqual(row["followthrough_direction"], "")

    def test_csv_export_escapes_headlines_with_commas_and_quotes(self):
        tricky = 'Title with "quotes", commas, and newline\nand more'
        self._save_event(headline=tricky)
        text = build_csv_export(load_events_for_export())
        rows = self._parse_csv(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["headline"], tricky)

    def test_csv_export_row_count_matches_event_count(self):
        for i in range(3):
            self._save_event(headline=f"CSV multi {i}")
        text = build_csv_export(load_events_for_export())
        rows = self._parse_csv(text)
        self.assertEqual(len(rows), 3)


# ---------------------------------------------------------------------------
# Empty-archive behaviour
# ---------------------------------------------------------------------------


class TestEmptyExport(_ExportBase):

    def test_json_export_empty_archive(self):
        payload = build_json_export(load_events_for_export())
        # Envelope carries events + the track_record_breakdown block.
        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["events"], [])
        self.assertIn("track_record_breakdown", payload)
        breakdown = payload["track_record_breakdown"]
        self.assertEqual(breakdown["schema"], "track_record_breakdown.v1")
        self.assertEqual(breakdown["summary"]["total_events"], 0)

    def test_csv_export_empty_archive_has_header_only(self):
        text = build_csv_export(load_events_for_export())
        lines = [ln for ln in text.split("\n") if ln]
        self.assertEqual(len(lines), 1)  # header row only
        self.assertEqual(lines[0], ",".join(CSV_COLUMNS))

    def test_load_events_for_export_returns_empty_list(self):
        self.assertEqual(load_events_for_export(), [])


# ---------------------------------------------------------------------------
# /events/export endpoint
# ---------------------------------------------------------------------------


class TestExportEndpoint(_ExportBase):

    def setUp(self):
        super().setUp()
        from api import app
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        super().tearDown()

    def test_endpoint_defaults_to_json(self):
        self._save_event(headline="Endpoint JSON default")
        r = self.client.get("/events/export")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(
            r.headers["content-type"].startswith("application/json"),
        )
        body = r.json()
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["events"][0]["headline"], "Endpoint JSON default")

    def test_endpoint_json_includes_follow_through(self):
        self._save_event(headline="Endpoint JSON ft")
        body = self.client.get("/events/export?format=json").json()
        ft = body["events"][0]["follow_through"]
        self.assertIn("best_return_5d", ft)
        self.assertIn("best_return_20d", ft)
        self.assertIn("best_direction", ft)

    def test_endpoint_csv_sets_content_type_and_attachment(self):
        self._save_event(headline="Endpoint CSV")
        r = self.client.get("/events/export?format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["content-type"].startswith("text/csv"))
        self.assertIn("attachment", r.headers.get("content-disposition", ""))
        # Header line + one data row
        rows = list(csv.DictReader(io.StringIO(r.text)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["headline"], "Endpoint CSV")

    def test_endpoint_empty_archive_json(self):
        r = self.client.get("/events/export")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Envelope carries events + the track_record_breakdown block.
        self.assertEqual(body["count"], 0)
        self.assertEqual(body["events"], [])
        self.assertIn("track_record_breakdown", body)
        self.assertEqual(
            body["track_record_breakdown"]["schema"],
            "track_record_breakdown.v1",
        )

    def test_endpoint_empty_archive_csv(self):
        r = self.client.get("/events/export?format=csv")
        self.assertEqual(r.status_code, 200)
        self.assertIn("headline", r.text)  # header row is present
        lines = [ln for ln in r.text.split("\n") if ln]
        self.assertEqual(len(lines), 1)  # only the header

    def test_endpoint_rejects_unknown_format(self):
        r = self.client.get("/events/export?format=xml")
        self.assertEqual(r.status_code, 422)

    def test_endpoint_respects_limit(self):
        for i in range(5):
            self._save_event(headline=f"Limit test {i}")
        r = self.client.get("/events/export?limit=2")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["count"], 2)

    def test_endpoint_emits_strict_json_compliant_body(self):
        """Persisted ticker returns can be NaN (delisted symbols, gaps in
        the stress tape, custom computations that divide by zero).  The
        export endpoint must scrub those before responding so strict
        JSON consumers (browsers, JSON.parse, allow_nan=False) parse
        the body without raising.
        """
        import math
        nan_ticker = {
            "symbol": "DELISTED",
            "role": "beneficiary",
            "return_1d": math.nan,
            "return_5d": math.nan,
            "return_20d": math.nan,
            "direction": "no data",
        }
        self._save_event(
            headline="Ticker with NaN returns",
            market_tickers=[nan_ticker],
        )
        r = self.client.get("/events/export")
        self.assertEqual(r.status_code, 200)
        body_text = r.text
        # Strict re-encode: ``allow_nan=False`` raises if any non-finite
        # float survived sanitisation.  This is the load-bearing check —
        # a cosmetic ``json.dumps(body)`` would silently round-trip NaN.
        try:
            json.dumps(json.loads(body_text), allow_nan=False)
        except ValueError as exc:
            self.fail(
                f"/events/export emitted non-JSON-compliant float: {exc}"
            )
        # The NaN values became null after sanitisation; the rest of the
        # row stays intact.
        body = r.json()
        ev = body["events"][0]
        ticker = ev["market_tickers"][0]
        self.assertEqual(ticker["symbol"], "DELISTED")
        for field in ("return_1d", "return_5d", "return_20d"):
            self.assertIsNone(
                ticker[field],
                f"NaN should sanitize to None on {field}",
            )

    def test_endpoint_handles_inf_ticker_returns(self):
        """``inf`` is the same JSON-compliance issue as NaN.  The route
        must scrub it equivalently.
        """
        import math
        self._save_event(
            headline="Ticker with inf return",
            market_tickers=[{
                "symbol": "EDGE",
                "role": "beneficiary",
                "return_1d": math.inf,
                "return_5d": -math.inf,
                "return_20d": 1.0,
                "direction": "supports thesis",
            }],
        )
        r = self.client.get("/events/export")
        self.assertEqual(r.status_code, 200)
        try:
            json.dumps(json.loads(r.text), allow_nan=False)
        except ValueError as exc:
            self.fail(
                f"/events/export emitted non-JSON-compliant float: {exc}"
            )


if __name__ == "__main__":
    unittest.main()
