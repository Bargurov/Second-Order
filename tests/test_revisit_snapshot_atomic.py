"""
tests/test_revisit_snapshot_atomic.py

Focused tests for the atomic append_revisit_snapshot fix.

  1. Double-write safety  — two concurrent calls for different days
     both land; neither is lost.
  2. Dedupe still works   — a second write for the same day replaces
     the first, not duplicates it.
  3. Ordering still works — snapshots are always returned sorted by day
     regardless of insertion order.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _setup_db() -> tuple[str, int]:
    """Create a temp DB, seed one event, return (db_path, event_id)."""
    path = os.path.join(tempfile.gettempdir(),
                        f"test_atomic_revisit_{uuid.uuid4().hex}.db")
    db.DB_FILE = path
    db.init_db()
    db.save_event({
        "headline": "Atomic revisit test event",
        "stage": "realized",
        "persistence": "medium",
        "event_date": "2026-04-01",
        "market_tickers": [],
    })
    events = db.load_recent_events(limit=1)
    return path, events[0]["id"]


def _snap(day: int, value: float) -> dict:
    return {
        "day": day,
        "captured_at": f"2026-04-{day + 1:02d}T12:00:00",
        "tickers": [{"symbol": "XOM", "return_5d": value}],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAppendRevisitSnapshotAtomic(unittest.TestCase):

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp, self.event_id = _setup_db()

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (PermissionError, FileNotFoundError):
            pass

    # 1. Double-write safety ------------------------------------------------

    def test_concurrent_different_days_both_land(self):
        """Two threads writing different days must not lose either snapshot."""
        errors: list[Exception] = []
        barrier = threading.Barrier(2)

        def writer(day: int, value: float) -> None:
            try:
                barrier.wait()          # start both threads at the same time
                db.append_revisit_snapshot(self.event_id, _snap(day, value))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=writer, args=(1, 1.0))
        t2 = threading.Thread(target=writer, args=(5, 2.0))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        snaps = db.load_revisit_snapshots(self.event_id)
        days = {s["day"] for s in snaps}
        self.assertIn(1, days, "day-1 snapshot was lost")
        self.assertIn(5, days, "day-5 snapshot was lost")
        self.assertEqual(len(snaps), 2)

    def test_concurrent_same_day_exactly_one_survives(self):
        """Two threads writing the same day must produce exactly one entry."""
        barrier = threading.Barrier(2)
        errors: list[Exception] = []

        def writer(value: float) -> None:
            try:
                barrier.wait()
                db.append_revisit_snapshot(self.event_id, _snap(5, value))
            except Exception as exc:
                errors.append(exc)

        t1 = threading.Thread(target=writer, args=(2.0,))
        t2 = threading.Thread(target=writer, args=(2.5,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(errors, [], f"Thread errors: {errors}")
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(snaps), 1, "same-day dedup produced more than one entry")
        self.assertEqual(snaps[0]["day"], 5)

    # 2. Dedupe still works -------------------------------------------------

    def test_second_write_same_day_replaces_first(self):
        db.append_revisit_snapshot(self.event_id, _snap(5, 2.0))
        db.append_revisit_snapshot(self.event_id, _snap(5, 2.5))
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["tickers"][0]["return_5d"], 2.5)

    def test_different_days_not_deduped(self):
        db.append_revisit_snapshot(self.event_id, _snap(1, 1.0))
        db.append_revisit_snapshot(self.event_id, _snap(5, 2.0))
        db.append_revisit_snapshot(self.event_id, _snap(20, 3.0))
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(len(snaps), 3)

    # 3. Ordering still works -----------------------------------------------

    def test_snapshots_sorted_by_day_regardless_of_insert_order(self):
        for day in (20, 1, 5):
            db.append_revisit_snapshot(self.event_id, _snap(day, float(day)))
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual([s["day"] for s in snaps], [1, 5, 20])

    def test_single_snapshot_order_trivially_correct(self):
        db.append_revisit_snapshot(self.event_id, _snap(5, 2.0))
        snaps = db.load_revisit_snapshots(self.event_id)
        self.assertEqual(snaps[0]["day"], 5)


if __name__ == "__main__":
    unittest.main()
