"""Tests for the auto_revisit background scheduler.

Covers:
  * find_due_events respects 1d/5d/20d anchors + grace window
  * already-captured anchors are skipped (day-level dedup)
  * events without event_date or tickers are skipped
  * capture_due_snapshots groups multiple due days per event into one
    followup_check call and appends via the shared db helper
  * start_background_refresh + stop_background_refresh lifecycle is idempotent
  * lifespan wiring is env-gated — no thread starts unless AUTO_REVISIT_ENABLED
"""

import os
import sys
import threading
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from auto_revisit import (
    REVISIT_ANCHORS,
    ANCHOR_GRACE_DAYS,
    _build_day_snapshot,
    _days_since,
    _existing_days,
    capture_due_snapshots,
    find_due_events,
    is_running,
    start_background_refresh,
    stop_background_refresh,
)


_NOW = datetime(2026, 4, 20, 12, 0, 0)


def _event(eid: int, days_ago: int, tickers=None, snaps=None) -> dict:
    """Build a minimal event dict with event_date ``days_ago`` before _NOW."""
    d = (_NOW.date() - timedelta(days=days_ago)).isoformat()
    return {
        "id":             eid,
        "headline":       f"Event {eid}",
        "event_date":     d,
        "market_tickers": tickers if tickers is not None
                          else [{"symbol": "SPY", "role": "beneficiary"}],
        "revisit_snapshots": snaps if snaps is not None else [],
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestDaySince(unittest.TestCase):
    def test_basic_calendar_delta(self):
        self.assertEqual(_days_since("2026-04-15", _NOW), 5)

    def test_zero_when_same_day(self):
        self.assertEqual(_days_since("2026-04-20", _NOW), 0)

    def test_none_when_missing(self):
        self.assertIsNone(_days_since(None, _NOW))
        self.assertIsNone(_days_since("", _NOW))

    def test_none_when_unparseable(self):
        self.assertIsNone(_days_since("not-a-date", _NOW))


class TestExistingDays(unittest.TestCase):
    def test_empty_when_no_snapshots(self):
        self.assertEqual(_existing_days({}), set())

    def test_extracts_days_from_decoded_list(self):
        ev = {"revisit_snapshots": [{"day": 1}, {"day": 5}]}
        self.assertEqual(_existing_days(ev), {1, 5})

    def test_tolerates_raw_json_string(self):
        ev = {"revisit_snapshots": '[{"day": 1}, {"day": 20}]'}
        self.assertEqual(_existing_days(ev), {1, 20})

    def test_malformed_json_returns_empty(self):
        ev = {"revisit_snapshots": "{not json"}
        self.assertEqual(_existing_days(ev), set())


# ---------------------------------------------------------------------------
# find_due_events
# ---------------------------------------------------------------------------

class TestFindDueEvents(unittest.TestCase):
    def test_age_matches_1d_anchor(self):
        events = [_event(1, days_ago=1)]
        self.assertEqual(find_due_events(events, now=_NOW), [(1, 1)])

    def test_age_matches_5d_anchor_includes_1d_too(self):
        """An event 5 days old should fire both 1d and 5d anchors if
        neither has been captured — scheduler catches up on missed ticks."""
        events = [_event(2, days_ago=5)]
        self.assertEqual(set(find_due_events(events, now=_NOW)),
                         {(2, 1), (2, 5)})

    def test_age_matches_20d_anchor(self):
        events = [_event(3, days_ago=20)]
        due = set(find_due_events(events, now=_NOW))
        self.assertEqual(due, {(3, 1), (3, 5), (3, 20)})

    def test_already_captured_day_skipped(self):
        """A 5d anchor already captured on the event must not fire again."""
        ev = _event(4, days_ago=5, snaps=[{"day": 1}, {"day": 5}])
        self.assertEqual(find_due_events([ev], now=_NOW), [])

    def test_partial_capture_only_fires_missing_anchor(self):
        ev = _event(5, days_ago=5, snaps=[{"day": 1}])
        self.assertEqual(find_due_events([ev], now=_NOW), [(5, 5)])

    def test_grace_window_included(self):
        """An event at anchor + grace still fires — scheduler catches up
        on missed anchors within the grace window."""
        ev = _event(6, days_ago=5 + ANCHOR_GRACE_DAYS)
        due_days = [day for (_eid, day) in find_due_events([ev], now=_NOW)]
        self.assertIn(5, due_days)

    def test_past_grace_window_excluded(self):
        """Anchor + grace + 1 day is past the safety window — no fire.
        Archive material belongs to the manual revisit route by that point."""
        # Test at 1d anchor + grace + 1 so the event itself isn't yet far
        # enough past the 5d / 20d anchors to clear their grace windows.
        ev = _event(7, days_ago=1 + ANCHOR_GRACE_DAYS + 1)
        due_days = [day for (_eid, day) in find_due_events([ev], now=_NOW)]
        self.assertNotIn(1, due_days)

    def test_future_event_date_skipped(self):
        """An event_date in the future should not fire any anchor."""
        ev = _event(8, days_ago=-1)
        self.assertEqual(find_due_events([ev], now=_NOW), [])

    def test_missing_event_date_skipped(self):
        ev = _event(9, days_ago=5)
        ev["event_date"] = None
        self.assertEqual(find_due_events([ev], now=_NOW), [])

    def test_missing_tickers_skipped(self):
        ev = _event(10, days_ago=5, tickers=[])
        self.assertEqual(find_due_events([ev], now=_NOW), [])

    def test_anchors_set_from_module_constant(self):
        self.assertEqual(REVISIT_ANCHORS, (1, 5, 20))


# ---------------------------------------------------------------------------
# capture_due_snapshots
# ---------------------------------------------------------------------------

class TestCaptureDueSnapshots(unittest.TestCase):
    def test_empty_when_nothing_due(self):
        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [],
            load_event_fn=lambda _i: None,
            followup_check_fn=lambda *a, **k: [],
            append_fn=lambda *a, **k: True,
        )
        self.assertEqual(log, [])

    def test_captures_missing_anchor_for_single_event(self):
        ev = _event(100, days_ago=5, snaps=[{"day": 1}])
        outcomes = [
            {"symbol": "SPY", "role": "beneficiary",
             "return_1d": 0.5, "return_5d": 2.0, "return_20d": 4.0,
             "direction": "up"},
        ]
        followup_calls: list[tuple] = []
        append_calls: list[tuple] = []

        def _followup(tickers, event_date):
            followup_calls.append((tuple(t["symbol"] for t in tickers), event_date))
            return outcomes

        def _append(eid, snapshot):
            append_calls.append((eid, snapshot))
            return True

        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [ev],
            load_event_fn=lambda _i: ev,
            followup_check_fn=_followup,
            append_fn=_append,
        )

        # Exactly one due day (5d); append called once with the 5d payload.
        self.assertEqual(len(followup_calls), 1)
        self.assertEqual(len(append_calls), 1)
        eid_called, snap = append_calls[0]
        self.assertEqual(eid_called, 100)
        self.assertEqual(snap["day"], 5)
        self.assertTrue(snap["tickers"])
        self.assertEqual(log[0]["status"], "captured")

    def test_one_followup_call_per_event_even_when_multiple_anchors_due(self):
        """A brand-new 5-day-old event with no captures fires 1d + 5d — but the
        scheduler must batch them into ONE followup_check call per event."""
        ev = _event(101, days_ago=5, snaps=[])
        outcomes = [
            {"symbol": "SPY", "role": "beneficiary",
             "return_1d": 0.4, "return_5d": 1.8, "return_20d": None,
             "direction": "up"},
        ]
        followup_calls: list = []

        def _followup(tickers, event_date):
            followup_calls.append(event_date)
            return outcomes

        capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [ev],
            load_event_fn=lambda _i: ev,
            followup_check_fn=_followup,
            append_fn=lambda *a, **k: True,
        )
        self.assertEqual(len(followup_calls), 1)

    def test_provider_error_logged_as_error_status(self):
        ev = _event(102, days_ago=1)

        def _boom(*a, **k):
            raise RuntimeError("provider offline")

        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [ev],
            load_event_fn=lambda _i: ev,
            followup_check_fn=_boom,
            append_fn=lambda *a, **k: True,
        )
        self.assertTrue(log)
        self.assertEqual(log[0]["status"], "error")
        self.assertIn("provider offline", log[0]["error"])

    def test_no_data_when_outcomes_lack_return_for_day(self):
        ev = _event(103, days_ago=1)
        # Outcomes present but return_1d is None — no data ready yet.
        outcomes = [{"symbol": "SPY", "role": "beneficiary", "return_1d": None}]

        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [ev],
            load_event_fn=lambda _i: ev,
            followup_check_fn=lambda *a, **k: outcomes,
            append_fn=lambda *a, **k: True,
        )
        self.assertEqual(log[0]["status"], "no_data")

    def test_event_deleted_between_discovery_and_capture(self):
        ev = _event(104, days_ago=5)

        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [ev],
            # load_event_by_id returns None → event went missing
            load_event_fn=lambda _i: None,
            followup_check_fn=lambda *a, **k: [],
            append_fn=lambda *a, **k: True,
        )
        self.assertTrue(log)
        self.assertTrue(all(e["status"] == "event_missing" for e in log))

    def test_race_with_manual_capture_skips_already_captured_day(self):
        """A manual capture landing between discovery and our write must
        cause the scheduler to skip the already-captured day (no overwrite),
        even if another anchor on the same event is still due."""
        # Event is 5 days old with NO snapshots — so find_due_events picks
        # up BOTH the 1d and 5d anchors.  Between discovery and capture, a
        # manual capture lands the 5d snapshot.
        discovered_ev = _event(105, days_ago=5, snaps=[])
        reloaded_ev = _event(105, days_ago=5, snaps=[{"day": 5}])

        captured_days: list[int] = []

        def _append(eid, snapshot):
            captured_days.append(snapshot["day"])
            return True

        outcomes = [
            {"symbol": "SPY", "role": "beneficiary",
             "return_1d": 0.3, "return_5d": 1.2, "direction": "up"},
        ]

        log = capture_due_snapshots(
            now=_NOW,
            load_events_fn=lambda _n: [discovered_ev],
            load_event_fn=lambda _i: reloaded_ev,
            followup_check_fn=lambda *a, **k: outcomes,
            append_fn=_append,
        )

        # 5d was already captured by the racing writer — scheduler must not
        # re-append it, even though followup_check data is available.
        self.assertNotIn(5, captured_days)
        # 1d is still legitimately due — the scheduler must proceed with it.
        self.assertIn(1, captured_days)
        logged_captured = {e["day"] for e in log if e["status"] == "captured"}
        self.assertNotIn(5, logged_captured)


class TestBuildDaySnapshot(unittest.TestCase):
    def test_filters_outcomes_without_return_key(self):
        outcomes = [
            {"symbol": "A", "role": "beneficiary", "return_5d": 2.0, "direction": "up"},
            {"symbol": "B", "role": "loser", "return_5d": None, "direction": None},
        ]
        snap = _build_day_snapshot(5, outcomes, "2026-04-20T12:00:00")
        self.assertEqual(snap["day"], 5)
        self.assertEqual(len(snap["tickers"]), 1)
        self.assertEqual(snap["tickers"][0]["symbol"], "A")
        self.assertEqual(snap["tickers"][0]["return_5d"], 2.0)


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle(unittest.TestCase):
    """start / stop / is_running with a no-op capture body."""

    def test_start_is_idempotent_and_stop_joins_cleanly(self):
        # Patch capture so we don't hit any real I/O during the lifecycle test.
        with patch("auto_revisit.capture_due_snapshots", return_value=[]):
            started = start_background_refresh(interval=30)
            try:
                self.assertTrue(started)
                self.assertTrue(is_running())
                # Second start must no-op.
                self.assertFalse(start_background_refresh(interval=30))
            finally:
                stop_background_refresh(timeout=2.0)

            self.assertFalse(is_running())

    def test_initial_capture_runs_on_start(self):
        captured = threading.Event()

        def _once_then_block(*_a, **_k):
            captured.set()
            return []

        with patch("auto_revisit.capture_due_snapshots", side_effect=_once_then_block):
            # Use a long interval so the loop body only fires the startup pass.
            start_background_refresh(interval=3600)
            try:
                self.assertTrue(captured.wait(2.0), "initial pass never fired")
            finally:
                stop_background_refresh(timeout=2.0)


# ---------------------------------------------------------------------------
# Lifespan env-gate — no thread starts unless AUTO_REVISIT_ENABLED
# ---------------------------------------------------------------------------

class TestLifespanEnvGate(unittest.TestCase):
    """Importing api / creating TestClient must never start the revisit thread
    on its own.  Only AUTO_REVISIT_ENABLED flips the switch."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_ar_env_{uuid.uuid4().hex}.db",
        )
        db.init_db()

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_thread_not_started_when_env_unset(self):
        """The TestClient lifespan runs; with AUTO_REVISIT_ENABLED unset
        auto_revisit.is_running() must stay False."""
        os.environ.pop("AUTO_REVISIT_ENABLED", None)
        from fastapi.testclient import TestClient
        from api import app
        with TestClient(app):
            self.assertFalse(is_running())

    def test_thread_started_when_env_true(self):
        os.environ["AUTO_REVISIT_ENABLED"] = "true"
        os.environ["AUTO_REVISIT_INTERVAL"] = "3600"
        try:
            with patch("auto_revisit.capture_due_snapshots", return_value=[]):
                from fastapi.testclient import TestClient
                # Import late so the env var is read on lifespan startup.
                import importlib
                import api
                importlib.reload(api)
                with TestClient(api.app):
                    # Thread started by lifespan.
                    self.assertTrue(is_running())
                # After lifespan exit the thread is joined.
                self.assertFalse(is_running())
        finally:
            os.environ.pop("AUTO_REVISIT_ENABLED", None)
            os.environ.pop("AUTO_REVISIT_INTERVAL", None)
            stop_background_refresh(timeout=2.0)


# ---------------------------------------------------------------------------
# Integration: real DB + scheduler + real append_revisit_snapshot
# ---------------------------------------------------------------------------

class TestDbIntegration(unittest.TestCase):
    """End-to-end: seed a real event, run capture_due_snapshots with a stub
    followup, then assert the snapshot landed via the real
    append_revisit_snapshot + load_revisit_snapshots helpers."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_auto_revisit_{uuid.uuid4().hex}.db",
        )
        db.init_db()

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_capture_writes_snapshot_through_real_db_layer(self):
        event_date = (_NOW.date() - timedelta(days=5)).isoformat()
        db.save_event({
            "headline": "Integration test: 5d anchor due",
            "stage": "breaking",
            "persistence": "transient",
            "confidence": "medium",
            "event_date": event_date,
            "market_tickers": [
                {"symbol": "SPY", "role": "beneficiary",
                 "return_1d": 0.5, "return_5d": 2.0,
                 "direction_tag": "supports_thesis", "spark": []},
            ],
        })
        eid = db.load_recent_events(1)[0]["id"]

        outcomes = [
            {"symbol": "SPY", "role": "beneficiary",
             "return_1d": 0.5, "return_5d": 2.0, "return_20d": None,
             "direction": "up"},
        ]

        log = capture_due_snapshots(
            now=_NOW,
            followup_check_fn=lambda *a, **k: outcomes,
        )
        captured_days = {e["day"] for e in log if e["status"] == "captured"}
        # Both 1d and 5d should land via the real append path.
        self.assertIn(1, captured_days)
        self.assertIn(5, captured_days)

        snaps = db.load_revisit_snapshots(eid)
        days_on_row = {s["day"] for s in snaps}
        self.assertIn(1, days_on_row)
        self.assertIn(5, days_on_row)


if __name__ == "__main__":
    unittest.main()
