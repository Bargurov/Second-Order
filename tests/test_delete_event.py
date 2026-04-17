"""
tests/test_delete_event.py

Focused tests for DELETE /events/{event_id}.

Proves three invariants:
  1) Deleting an existing event returns {"ok": true, "event_id": N}.
  2) Deleting a nonexistent event returns 404.
  3) After deletion the event no longer appears in /events, /market-movers,
     or /movers/today, and mover caches are invalidated.

No LLM or market calls — all events are seeded directly into the DB.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tmp_db() -> str:
    return os.path.join(tempfile.gettempdir(), f"test_delete_{uuid.uuid4().hex}.db")


def _seed_event(headline: str, days_old: int = 1, xle_return: float = 5.0) -> int:
    """Insert a minimal but mover-eligible event and return its id."""
    today = datetime.now().strftime("%Y-%m-%d")
    ts = (datetime.now() - timedelta(days=days_old)).isoformat(timespec="seconds")
    db.save_event({
        "headline": headline,
        "stage": "realized",
        "persistence": "structural",
        "event_date": today,
        "timestamp": ts,
        "what_changed": "test",
        "mechanism_summary": "Oil shock mover test",
        "market_tickers": [
            {
                "symbol": "XLE",
                "role": "beneficiary",
                "return_5d": xle_return,
                "return_20d": xle_return * 1.4,
                "direction_tag": "supports \u2191",
                "label": "notable move",
                "volume_ratio": 1.5,
                "spark": [0.1, 0.4, 0.7, 0.9, 1.0],
                "anchor_date": today,
            },
        ],
    })
    return db.load_recent_events(1)[0]["id"]


def _reset_caches():
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


# ---------------------------------------------------------------------------
# Base — isolated temp DB per test
# ---------------------------------------------------------------------------

class _DeleteBase(unittest.TestCase):

    def setUp(self):
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = _tmp_db()
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self):
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# 1) Delete existing event
# ---------------------------------------------------------------------------

class TestDeleteExisting(_DeleteBase):

    def test_returns_ok_payload(self):
        eid = _seed_event("Iran oil sanctions announced")
        resp = client.delete(f"/events/{eid}")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["event_id"], eid)

    def test_event_gone_from_db_after_delete(self):
        eid = _seed_event("Iran oil sanctions announced")
        client.delete(f"/events/{eid}")
        self.assertIsNone(db.load_event_by_id(eid))

    def test_delete_is_idempotent_at_protocol_level(self):
        """Second DELETE on same id returns 404 — not 500."""
        eid = _seed_event("Iran oil sanctions announced")
        client.delete(f"/events/{eid}")
        resp2 = client.delete(f"/events/{eid}")
        self.assertEqual(resp2.status_code, 404)

    def test_delete_one_leaves_others_intact(self):
        eid_a = _seed_event("Oil supply shock A")
        eid_b = _seed_event("Fed rate decision B")
        client.delete(f"/events/{eid_a}")
        self.assertIsNone(db.load_event_by_id(eid_a))
        self.assertIsNotNone(db.load_event_by_id(eid_b))


# ---------------------------------------------------------------------------
# 2) 404 on missing / already-deleted events
# ---------------------------------------------------------------------------

class TestDeleteMissing(_DeleteBase):

    def test_nonexistent_id_returns_404(self):
        resp = client.delete("/events/999999")
        self.assertEqual(resp.status_code, 404)

    def test_zero_id_returns_404(self):
        resp = client.delete("/events/0")
        self.assertEqual(resp.status_code, 404)

    def test_404_body_contains_event_id_in_detail(self):
        resp = client.delete("/events/999999")
        self.assertIn("999999", resp.json()["detail"])


# ---------------------------------------------------------------------------
# 3) Caches do not serve deleted event
# ---------------------------------------------------------------------------

class TestCacheInvalidationAfterDelete(_DeleteBase):

    def test_events_list_excludes_deleted(self):
        eid = _seed_event("Iran oil sanctions announced")
        client.delete(f"/events/{eid}")
        body = client.get("/events").json()
        items = body["items"] if isinstance(body, dict) else body
        ids = [e["id"] for e in items]
        self.assertNotIn(eid, ids)

    def test_market_movers_excludes_deleted(self):
        eid = _seed_event("Oil shock market-movers delete test", days_old=1)
        # Confirm it appears before delete
        before = client.get("/market-movers").json()
        headlines_before = [m["headline"] for m in before]
        self.assertIn("Oil shock market-movers delete test", headlines_before)

        client.delete(f"/events/{eid}")
        # Cache must be cleared — re-fetch should rebuild from DB
        after = client.get("/market-movers").json()
        headlines_after = [m["headline"] for m in after]
        self.assertNotIn("Oil shock market-movers delete test", headlines_after)

    def test_movers_today_excludes_deleted(self):
        eid = _seed_event("Oil shock movers-today delete test", days_old=0)
        before = client.get("/movers/today").json()
        headlines_before = [m["headline"] for m in before]
        self.assertIn("Oil shock movers-today delete test", headlines_before)

        client.delete(f"/events/{eid}")
        after = client.get("/movers/today").json()
        headlines_after = [m["headline"] for m in after]
        self.assertNotIn("Oil shock movers-today delete test", headlines_after)

    def test_todays_movers_cache_dict_cleared_after_delete(self):
        """The in-memory _TODAYS_MOVERS_CACHE must be None after delete
        so the next call rebuilds from the DB."""
        _seed_event("Cache-clear verification event", days_old=0)
        # Warm the cache by hitting the endpoint
        client.get("/movers/today")
        self.assertIsNotNone(api._TODAYS_MOVERS_CACHE["data"])

        eid2 = _seed_event("Second event to delete", days_old=0)
        client.delete(f"/events/{eid2}")
        self.assertIsNone(api._TODAYS_MOVERS_CACHE["data"])

    def test_weekly_movers_cache_cleared_after_delete(self):
        """_WEEKLY_MOVERS_CACHE in-memory data must be None after delete."""
        _seed_event("Weekly cache-clear event", days_old=10)
        # Warm weekly cache
        client.get("/movers/weekly")
        eid2 = _seed_event("Weekly event to delete", days_old=10)
        client.delete(f"/events/{eid2}")
        self.assertIsNone(api._WEEKLY_MOVERS_CACHE.get("data"))


if __name__ == "__main__":
    unittest.main()
