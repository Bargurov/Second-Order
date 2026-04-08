"""
tests/test_save_event_atomic.py

Focused tests for the save_event atomicity fix and the
update_event_market_refresh movers-cache invalidation.

Covers:

  1. Concurrent duplicate save attempts produce only one row
     (dedup is now atomic under concurrent writes).
  2. Normal non-duplicate saves still work when run back-to-back.
  3. update_event_market_refresh invalidates the persisted movers
     cache immediately (not after TTL expiry).
  4. /movers/* endpoints reflect the refreshed event_age data without
     waiting for the 60-minute weekly TTL to expire.

The implementation remains small and local — no production surface
changes beyond db.save_event / db.update_event_market_refresh.
"""

from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import movers_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_event(headline: str, *, event_date: str = "2026-04-07",
                return_5d: float = 3.5) -> dict:
    return {
        "headline": headline,
        "stage": "realized",
        "persistence": "medium",
        "event_date": event_date,
        "what_changed": "ctx",
        "mechanism_summary": "mech text long enough to pass filters",
        "beneficiaries": ["A"],
        "losers": ["B"],
        "assets_to_watch": ["AAPL"],
        "confidence": "medium",
        "market_note": "note",
        "market_tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "return_5d": return_5d,
             "return_20d": return_5d * 1.1, "direction_tag": "supports \u2191"},
        ],
        "transmission_chain": ["a", "b", "c"],
    }


def _row_count(db_file: str) -> int:
    with sqlite3.connect(db_file) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])


# ---------------------------------------------------------------------------
# Case 1 — concurrent duplicate save attempts → one row
# ---------------------------------------------------------------------------


class TestConcurrentDedup(unittest.TestCase):
    """Multiple threads calling save_event with the same headline at the
    same time must produce exactly one row."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_atomic_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_20_concurrent_duplicates_produce_one_row(self):
        """20 threads racing save_event with identical headline+date → 1 row."""
        event = _base_event("Concurrent duplicate test")
        n_threads = 20
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                barrier.wait()
                db.save_event(dict(event))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertFalse(errors, f"worker exceptions: {errors}")
        self.assertEqual(
            _row_count(self._tmp), 1,
            "check-then-insert race — multiple duplicate rows were inserted",
        )

    def test_concurrent_different_headlines_all_persist(self):
        """Different headlines racing must all land in the table."""
        n_threads = 10
        barrier = threading.Barrier(n_threads)
        errors: list[Exception] = []

        def _worker(i: int) -> None:
            try:
                barrier.wait()
                db.save_event(_base_event(f"Unique headline {i}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertFalse(errors, f"worker exceptions: {errors}")
        self.assertEqual(_row_count(self._tmp), n_threads)

    def test_concurrent_mix_of_duplicates_and_unique(self):
        """Mixed workload: each headline collapses to exactly one row."""
        headlines = ["A", "A", "B", "B", "B", "C"]
        barrier = threading.Barrier(len(headlines))
        errors: list[Exception] = []

        def _worker(h: str) -> None:
            try:
                barrier.wait()
                db.save_event(_base_event(h))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(h,)) for h in headlines]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        self.assertFalse(errors, f"worker exceptions: {errors}")
        # Three unique headlines → three rows after dedup
        self.assertEqual(_row_count(self._tmp), 3)


# ---------------------------------------------------------------------------
# Case 2 — normal non-duplicate saves still work
# ---------------------------------------------------------------------------


class TestNormalSavesStillWork(unittest.TestCase):
    """Serial saves of distinct headlines and of the same headline outside
    the dedup window must behave exactly like before the atomicity fix."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_atomic_normal_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_back_to_back_distinct_saves(self):
        """Two different headlines both land as separate rows."""
        db.save_event(_base_event("First headline"))
        db.save_event(_base_event("Second headline"))
        self.assertEqual(_row_count(self._tmp), 2)

    def test_same_headline_outside_dedup_window_saves_twice(self):
        """A second save after the 10-min window must NOT be blocked."""
        db.save_event(_base_event("Time-window test"))

        # Backdate the first row's timestamp to 15 minutes ago so the
        # dedup window no longer fires.
        old_ts = (datetime.now() - timedelta(minutes=15)).isoformat(timespec="seconds")
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "UPDATE events SET timestamp = ? WHERE headline = ?",
                (old_ts, "Time-window test"),
            )

        db.save_event(_base_event("Time-window test"))
        self.assertEqual(_row_count(self._tmp), 2)

    def test_same_headline_inside_dedup_window_is_still_blocked(self):
        """Contract preservation: a duplicate inside the window is dropped."""
        db.save_event(_base_event("Dedup window test"))
        db.save_event(_base_event("Dedup window test"))
        self.assertEqual(_row_count(self._tmp), 1)

    def test_headline_plus_different_event_date_saves_both(self):
        """Same headline, different event_date → two rows (contract)."""
        db.save_event(_base_event("Date discriminator", event_date="2026-04-07"))
        db.save_event(_base_event("Date discriminator", event_date="2026-04-06"))
        self.assertEqual(_row_count(self._tmp), 2)


# ---------------------------------------------------------------------------
# Case 3 — update_event_market_refresh invalidates movers cache
# ---------------------------------------------------------------------------


class TestMoversCacheInvalidation(unittest.TestCase):
    """The in-place refresh must drop persisted mover slices so readers
    pick up the new numbers on their very next request."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_invalidate_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_update_invalidates_all_persisted_slices(self):
        """Every row in movers_cache is dropped on a successful refresh."""
        # Seed three slices directly so we can prove the invalidation
        # dropped them all — not just one.
        db.save_movers_cache("weekly",
                              [{"headline": "x", "impact": 1.0}],
                              "2026-04-08T10:00:00", 1, 1)
        db.save_movers_cache("yearly",
                              [{"headline": "y", "impact": 2.0}],
                              "2026-04-08T10:00:00", 1, 1)
        db.save_movers_cache("persistent",
                              [{"headline": "z", "impact": 3.0}],
                              "2026-04-08T10:00:00", 1, 1)
        self.assertIsNotNone(db.load_movers_cache("weekly"))
        self.assertIsNotNone(db.load_movers_cache("yearly"))
        self.assertIsNotNone(db.load_movers_cache("persistent"))

        # Seed an event that the refresh will target.
        db.save_event(_base_event("Invalidation target event"))
        eid = db.load_recent_events(1)[0]["id"]

        ok = db.update_event_market_refresh(
            eid,
            [{"symbol": "AAPL", "role": "beneficiary",
              "return_5d": 7.7, "direction_tag": "supports \u2191"}],
            "fresh note",
            "2026-04-08T11:00:00",
        )
        self.assertTrue(ok)

        # Every cached slice is gone.
        self.assertIsNone(db.load_movers_cache("weekly"))
        self.assertIsNone(db.load_movers_cache("yearly"))
        self.assertIsNone(db.load_movers_cache("persistent"))

    def test_update_on_missing_row_does_not_invalidate(self):
        """A no-op UPDATE (row not found) must NOT invalidate the cache.

        Otherwise any callers that probe for a refresh on a deleted
        event would flush the cache repeatedly.
        """
        db.save_movers_cache("weekly",
                              [{"headline": "keep", "impact": 1.0}],
                              "2026-04-08T10:00:00", 1, 1)
        ok = db.update_event_market_refresh(
            99_999,
            [],
            "",
            "2026-04-08T11:00:00",
        )
        self.assertFalse(ok)
        self.assertIsNotNone(db.load_movers_cache("weekly"))

    def test_invalidation_failure_does_not_break_refresh(self):
        """If movers_cache.invalidate() raises, the DB write is still reported OK."""
        db.save_event(_base_event("Refresh despite cache failure"))
        eid = db.load_recent_events(1)[0]["id"]

        with patch("movers_cache.invalidate", side_effect=RuntimeError("boom")):
            ok = db.update_event_market_refresh(
                eid,
                [{"symbol": "AAPL", "role": "beneficiary", "return_5d": 4.4}],
                "note",
                "2026-04-08T11:00:00",
            )
        self.assertTrue(ok)

        # The row itself was updated.
        reloaded = db.load_event_by_id(eid)
        self.assertEqual(reloaded["market_tickers"][0]["return_5d"], 4.4)


# ---------------------------------------------------------------------------
# Case 4 — /movers/* endpoints reflect refreshed data without TTL wait
# ---------------------------------------------------------------------------


class TestMoversEndpointsRefreshedImmediately(unittest.TestCase):
    """End-to-end: refresh an event, then hit /movers/weekly and see the
    new ticker return_5d, not the cached pre-refresh value."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""  # mock path
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_movers_refresh_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Reset all in-memory / persisted mover caches for a clean slate.
        movers_cache.invalidate()
        self.api._news_cache["data"] = None
        self.api._news_cache["ts"] = 0.0
        self.api._TODAYS_MOVERS_CACHE["data"] = None
        self.api._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_movers_weekly_sees_refreshed_return_without_ttl(self):
        """Seed → read movers (populates cache) → update_event_market_refresh
        with a different return_5d → read movers → new number visible."""
        # Seed a weekly-range event.
        headline = f"Weekly refresh target {uuid.uuid4().hex[:6]}"
        recent_ts = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        event = _base_event(headline, return_5d=3.0)
        event["timestamp"] = recent_ts
        db.save_event(event)
        eid = db.load_recent_events(1)[0]["id"]

        # First read populates the persisted movers cache.
        r1 = self.client.get("/movers/weekly")
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertEqual(len(body1), 1)
        self.assertEqual(body1[0]["headline"], headline)
        self.assertEqual(body1[0]["tickers"][0]["return_5d"], 3.0)
        self.assertIsNotNone(db.load_movers_cache("weekly"),
                              "movers cache should be populated after first read")

        # Update in place with a materially different return_5d.
        ok = db.update_event_market_refresh(
            eid,
            [{"symbol": "AAPL", "role": "beneficiary",
              "return_5d": 9.9, "return_20d": 11.0,
              "direction_tag": "supports \u2191"}],
            "refreshed note",
            datetime.now().isoformat(timespec="seconds"),
        )
        self.assertTrue(ok)

        # The persisted cache must be gone (not just stale).
        self.assertIsNone(db.load_movers_cache("weekly"),
                           "update_event_market_refresh must invalidate the movers cache")

        # Second read must reflect the new number immediately.
        r2 = self.client.get("/movers/weekly")
        self.assertEqual(r2.status_code, 200)
        body2 = r2.json()
        self.assertEqual(len(body2), 1)
        self.assertEqual(body2[0]["tickers"][0]["return_5d"], 9.9)

    def test_movers_persistent_reflects_refreshed_data(self):
        """Same contract on the persistent slice — invalidation is global."""
        # Seed a >7d-old event so it qualifies for the strict persistent branch.
        headline = f"Persistent refresh target {uuid.uuid4().hex[:6]}"
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        event = _base_event(
            headline, event_date=(datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            return_5d=4.0,
        )
        event["timestamp"] = old_ts
        # return_20d tuned for an "Accelerating" classification so the
        # strict persistent branch picks it up.
        event["market_tickers"][0]["return_20d"] = 5.0
        db.save_event(event)
        eid = db.load_recent_events(1)[0]["id"]

        r1 = self.client.get("/movers/persistent")
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertTrue(any(m["headline"] == headline for m in body1))
        self.assertIsNotNone(db.load_movers_cache("persistent"))

        # Update with much bigger numbers.
        db.update_event_market_refresh(
            eid,
            [{"symbol": "AAPL", "role": "beneficiary",
              "return_5d": 12.0, "return_20d": 15.0,
              "direction_tag": "supports \u2191"}],
            "refreshed",
            datetime.now().isoformat(timespec="seconds"),
        )
        self.assertIsNone(db.load_movers_cache("persistent"))

        r2 = self.client.get("/movers/persistent")
        body2 = r2.json()
        row = next((m for m in body2 if m["headline"] == headline), None)
        self.assertIsNotNone(row)
        self.assertEqual(row["tickers"][0]["return_5d"], 12.0)


if __name__ == "__main__":
    unittest.main()
