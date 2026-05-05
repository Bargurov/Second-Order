"""tests/test_events_validation_status_wiring.py

Smoke tests pinning the wiring of ``validation_status.score_validation_status``
into the ``/events`` and ``/events/{id}`` read surfaces.

What this fixes in the read layer:

  * ``GET /events/{id}`` exposes a new ``validation_status_v2`` block —
    the full dict returned by ``score_validation_status`` (status,
    reason, ratio, counts, event_age_days, pending_max_days).  Today
    detail responses do not surface the validation status at all; this
    test pins that they do.
  * ``GET /events`` items each carry the same ``validation_status_v2``
    block.  The legacy ``validation_status`` STRING from
    ``validation_outcome.score_validation_label`` stays — the new block
    is purely additive (different key, dict shape).
  * The wiring is read-only: no DB writes, no LLM / yfinance /
    market_check calls.

Filtering by the new four-label vocabulary is intentionally out of
scope here — see ``docs/validation_status_design.md`` §7.6 for the
filter-side contract.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Fixture helpers — modelled on tests/test_events_archive_detail_consistency.py
# ---------------------------------------------------------------------------

_REQUIRED_VS_KEYS = {
    "status", "reason", "ratio", "counts", "event_age_days", "pending_max_days",
}
_REQUIRED_COUNT_KEYS = {
    "total_tickers", "tagged_tickers", "directional",
    "supporting", "contradicting",
}
_VALID_STATUSES = {"validated", "contradicted", "unresolved", "pending"}


def _tmp_db() -> str:
    return os.path.join(
        tempfile.gettempdir(),
        f"test_events_vs_wiring_{uuid.uuid4().hex}.db",
    )


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


def _today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _ticker(symbol: str = "XLE", direction_tag: str = "supports ↑") -> dict:
    return {
        "symbol":        symbol,
        "role":          "beneficiary",
        "return_5d":     4.0,
        "direction_tag": direction_tag,
        "anchor_date":   _today_iso(),
    }


def _seed(
    *,
    headline: str = "Seed event",
    days_old: int = 1,
    tickers: list[dict] | None = None,
    mechanism_summary: str = "Mechanism summary text long enough to pass.",
) -> int:
    today = _today_iso()
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline":           headline,
        "stage":              "realized",
        "persistence":        "structural",
        "event_date":         today,
        "timestamp":          ts,
        "what_changed":       "Real change description",
        "mechanism_summary":  mechanism_summary,
        "transmission_chain": ["a", "b"],
        "if_persists":        {"thesis": "stub"},
        "market_tickers":     [_ticker()] if tickers is None else tickers,
        "confidence":         "medium",
    })
    return db.load_recent_events(1)[0]["id"]


def _snapshot_events_table(path: str) -> list[tuple]:
    """Full table content as a sortable list of tuples."""
    with sqlite3.connect(path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


# ---------------------------------------------------------------------------
# Base TestCase — temp DB per test, never touches the production archive
# ---------------------------------------------------------------------------


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


class TestDetailValidationStatusBlock(_Base):
    def test_detail_carries_validation_status_v2_block(self) -> None:
        eid = _seed()
        body = client.get(f"/events/{eid}").json()
        self.assertIn("validation_status_v2", body)
        vs = body["validation_status_v2"]
        self.assertIsInstance(vs, dict)
        self.assertGreaterEqual(set(vs.keys()), _REQUIRED_VS_KEYS)
        self.assertIn(vs["status"], _VALID_STATUSES)
        self.assertIsInstance(vs["reason"], str)
        self.assertGreater(len(vs["reason"]), 0)
        self.assertEqual(set(vs["counts"].keys()), _REQUIRED_COUNT_KEYS)
        self.assertIsInstance(vs["event_age_days"], int)
        self.assertEqual(vs["pending_max_days"], 7)

    def test_detail_validated_when_supports_tags_present(self) -> None:
        eid = _seed(
            headline="Supports majority",
            tickers=[
                _ticker("XLE", "supports_thesis"),
                _ticker("XOM", "supports_thesis"),
                _ticker("F",   "contradicts_thesis"),
            ],
        )
        body = client.get(f"/events/{eid}").json()
        self.assertEqual(body["validation_status_v2"]["status"], "validated")
        self.assertEqual(body["validation_status_v2"]["counts"]["supporting"], 2)
        self.assertEqual(body["validation_status_v2"]["counts"]["contradicting"], 1)

    def test_detail_pending_for_fresh_event_with_thesis_no_tickers(self) -> None:
        # No tickers + thesis present + fresh → pending (design §5).
        eid = _seed(headline="Fresh thesis, no tickers", tickers=[])
        body = client.get(f"/events/{eid}").json()
        self.assertEqual(body["validation_status_v2"]["status"], "pending")
        self.assertIsNone(body["validation_status_v2"]["ratio"])

    def test_detail_unresolved_when_age_past_pending_window(self) -> None:
        # Old event, no tickers → unresolved (past 7d window).
        eid = _seed(
            headline="Stale thesis",
            tickers=[],
            days_old=20,
        )
        # event_date is still today (always set to today by _seed); to push
        # past the pending window we override it directly via the DB row.
        with sqlite3.connect(db.DB_FILE) as conn:
            old_iso = (datetime.now() - timedelta(days=20)).date().isoformat()
            conn.execute(
                "UPDATE events SET event_date = ?, timestamp = ? WHERE id = ?",
                (old_iso, old_iso + "T10:00:00", eid),
            )
            conn.commit()
        body = client.get(f"/events/{eid}").json()
        self.assertEqual(body["validation_status_v2"]["status"], "unresolved")


# ---------------------------------------------------------------------------
# List endpoint
# ---------------------------------------------------------------------------


class TestListValidationStatusBlock(_Base):
    def test_list_items_each_carry_validation_status_v2_block(self) -> None:
        # Distinct, low-Jaccard headlines so read-time dedup doesn't
        # collapse one of them — see db._DEDUP_THRESHOLD.
        _seed(headline="OPEC announces production cuts of 500k bpd")
        _seed(
            headline="ECB holds policy rate steady at 4 percent",
            tickers=[_ticker("XOM", "contradicts_thesis")],
        )
        items = client.get("/events?limit=10").json()["items"]
        self.assertGreaterEqual(len(items), 2)
        for item in items:
            self.assertIn("validation_status_v2", item)
            vs = item["validation_status_v2"]
            self.assertIsInstance(vs, dict)
            self.assertIn(vs["status"], _VALID_STATUSES)
            self.assertEqual(set(vs["counts"].keys()), _REQUIRED_COUNT_KEYS)
            self.assertEqual(vs["pending_max_days"], 7)

    def test_legacy_validation_status_string_still_present(self) -> None:
        _seed(headline="Legacy preserved")
        item = client.get("/events?limit=10").json()["items"][0]
        # Legacy 3-label string from validation_outcome.score_validation_label
        # (still set by routes/events._decorate_row).
        self.assertIn("validation_status", item)
        self.assertIsInstance(item["validation_status"], str)
        self.assertIn(
            item["validation_status"],
            ("validated", "contradicted", "unresolved"),
        )

    def test_list_status_is_consistent_with_legacy_when_directional(self) -> None:
        """When the directional rule fires (supports/contradicts present),
        the new four-label vocabulary collapses to the same word the
        legacy three-label scorer emits."""
        _seed(
            headline="Supports majority list",
            tickers=[
                _ticker("XLE", "supports_thesis"),
                _ticker("XOM", "supports_thesis"),
            ],
        )
        item = client.get("/events?limit=10").json()["items"][0]
        self.assertEqual(item["validation_status"], "validated")
        self.assertEqual(item["validation_status_v2"]["status"], "validated")


# ---------------------------------------------------------------------------
# No DB writes / no provider calls
# ---------------------------------------------------------------------------


class TestReadOnlyContract(_Base):
    def test_detail_endpoint_does_not_write_to_db(self) -> None:
        eid = _seed()
        before = _snapshot_events_table(self._tmp)
        r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200)
        after = _snapshot_events_table(self._tmp)
        self.assertEqual(before, after, "detail endpoint mutated events table")

    def test_list_endpoint_does_not_write_to_db(self) -> None:
        _seed(headline="A")
        _seed(headline="B")
        before = _snapshot_events_table(self._tmp)
        r = client.get("/events?limit=50")
        self.assertEqual(r.status_code, 200)
        after = _snapshot_events_table(self._tmp)
        self.assertEqual(before, after, "list endpoint mutated events table")

    def test_detail_endpoint_makes_no_provider_calls(self) -> None:
        eid = _seed()
        with patch("api.analyze_event",
                   side_effect=AssertionError("detail must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("detail must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("detail must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("detail must not call yfinance.Ticker")):
            r = client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("validation_status_v2", r.json())

    def test_list_endpoint_makes_no_provider_calls(self) -> None:
        _seed()
        with patch("api.analyze_event",
                   side_effect=AssertionError("list must not call analyze_event")), \
             patch("api.market_check",
                   side_effect=AssertionError("list must not call market_check")), \
             patch("yfinance.download",
                   side_effect=AssertionError("list must not call yfinance.download")), \
             patch("yfinance.Ticker",
                   side_effect=AssertionError("list must not call yfinance.Ticker")):
            r = client.get("/events?limit=10")
        self.assertEqual(r.status_code, 200, r.text)
        items = r.json()["items"]
        self.assertGreater(len(items), 0)
        self.assertIn("validation_status_v2", items[0])


if __name__ == "__main__":
    unittest.main()
