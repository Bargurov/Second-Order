"""Tests for ``auto_backfill_state.AutoBackfillState``.

The module is the in-memory run-state + lock layer that a future
APScheduler-style auto-backfill scheduler will sit on top of.  It is
deliberately pure: no SQLite, no scheduler, no LLM, no network, no
FastAPI startup wiring.  These tests cover only the contract:

  * ``acquire`` / ``release`` happy path with structured decisions.
  * Wrong-owner ``release`` is rejected, not a no-op silently mutating
    state.
  * Stale-lock expiry: a lock past its TTL can be re-acquired.
  * Lifecycle: ``mark_started`` → ``mark_completed`` → ``snapshot``
    reflects the run; same for ``mark_skipped``.
  * Deterministic clock injection — every method accepts ``now`` so a
    fixed datetime makes the entire suite reproducible.

Mirrors the scheduler design contract in
``docs/auto_backfill_scheduler_design.md`` §5 (lock) and §9 (state).
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_backfill_state import (  # noqa: E402
    AutoBackfillState,
    LockDecision,
    MarkDecision,
    ReleaseDecision,
    StateSnapshot,
)


# Fixed UTC clock — tests advance time by passing explicit datetimes,
# never by sleeping.
_T0 = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


# ---------------------------------------------------------------------------
# Acquire / release happy path
# ---------------------------------------------------------------------------


class TestAcquireRelease(unittest.TestCase):
    def test_first_acquire_succeeds(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        decision = state.acquire(owner="worker-A", now=_T0)
        self.assertIsInstance(decision, LockDecision)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "acquired")
        self.assertEqual(decision.owner, "worker-A")
        self.assertEqual(decision.acquired_at, _T0.isoformat())
        self.assertEqual(decision.expires_at, _at(60).isoformat())

    def test_release_by_owner_succeeds(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="worker-A", now=_T0)
        decision = state.release(owner="worker-A", now=_at(10))
        self.assertIsInstance(decision, ReleaseDecision)
        self.assertTrue(decision.released)
        self.assertEqual(decision.reason, "released")

    def test_acquire_after_release_succeeds(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.release(owner="A", now=_at(5))
        decision = state.acquire(owner="B", now=_at(10))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.owner, "B")

    def test_acquire_returns_existing_holder_on_conflict(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.acquire(owner="B", now=_at(10))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "lock_held")
        # The existing holder is surfaced so an operator log can show
        # who is blocking.
        self.assertEqual(decision.owner, "A")


# ---------------------------------------------------------------------------
# No-overlap semantics
# ---------------------------------------------------------------------------


class TestNoOverlap(unittest.TestCase):
    def test_concurrent_second_acquire_rejected(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        first = state.acquire(owner="A", now=_T0)
        second = state.acquire(owner="B", now=_T0)
        self.assertTrue(first.allowed)
        self.assertFalse(second.allowed)
        self.assertEqual(second.reason, "lock_held")

    def test_same_owner_re_acquire_rejected(self) -> None:
        # Re-entering acquire from the same owner is treated as a caller
        # bug, not silent success — the owner already holds the lock and
        # should call ``release`` first or accept the existing decision.
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.acquire(owner="A", now=_at(1))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "already_held_by_owner")
        self.assertEqual(decision.owner, "A")


# ---------------------------------------------------------------------------
# Wrong-owner release
# ---------------------------------------------------------------------------


class TestWrongOwnerRelease(unittest.TestCase):
    def test_release_by_non_owner_rejected_state_unchanged(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.release(owner="B", now=_at(10))
        self.assertIsInstance(decision, ReleaseDecision)
        self.assertFalse(decision.released)
        self.assertEqual(decision.reason, "not_owner")
        # The lock still belongs to A.
        snap = state.snapshot(now=_at(11))
        self.assertTrue(snap.lock_held)
        self.assertEqual(snap.lock_owner, "A")

    def test_release_when_no_lock_held_returns_not_held(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        decision = state.release(owner="A", now=_T0)
        self.assertFalse(decision.released)
        self.assertEqual(decision.reason, "not_held")


# ---------------------------------------------------------------------------
# Stale lock expiry
# ---------------------------------------------------------------------------


class TestStaleLockExpiry(unittest.TestCase):
    def test_expired_lock_can_be_reclaimed(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        # 61 seconds later — past the 60s TTL.
        decision = state.acquire(owner="B", now=_at(61))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "acquired")
        self.assertEqual(decision.owner, "B")
        # The new expiry anchors on the new acquisition.
        self.assertEqual(decision.acquired_at, _at(61).isoformat())
        self.assertEqual(decision.expires_at, _at(61 + 60).isoformat())

    def test_lock_at_exact_expiry_is_reclaimable(self) -> None:
        # ``now == expires_at`` is the boundary; the doc says "past its
        # TTL" — pin inclusive on the equality so the boundary is
        # reclaim-friendly rather than silent-hold.
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.acquire(owner="B", now=_at(60))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.owner, "B")

    def test_one_second_before_expiry_blocks_acquire(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.acquire(owner="B", now=_at(59))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "lock_held")
        self.assertEqual(decision.owner, "A")

    def test_per_acquire_ttl_overrides_instance_default(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0, ttl_seconds=10)
        # Past the per-call override (10s) but well inside the
        # instance default (60s) — must reclaim.
        decision = state.acquire(owner="B", now=_at(11))
        self.assertTrue(decision.allowed)


# ---------------------------------------------------------------------------
# Run lifecycle: started → completed
# ---------------------------------------------------------------------------


class TestRunLifecycleCompleted(unittest.TestCase):
    def test_mark_started_sets_run_id_and_timestamp(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.mark_started(run_id="run-abc", now=_at(1))
        self.assertIsInstance(decision, MarkDecision)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "started")
        snap = state.snapshot(now=_at(2))
        self.assertEqual(snap.last_run_id,     "run-abc")
        self.assertEqual(snap.last_started_at, _at(1).isoformat())
        # No completion or skip yet.
        self.assertIsNone(snap.last_completed_at)
        self.assertIsNone(snap.last_skip_reason)

    def test_mark_completed_records_counts_and_clears_skip(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        # First, a skip lands a reason; a subsequent completed run
        # must clear it so consumers see the FRESH outcome.
        state.acquire(owner="A", now=_T0)
        state.mark_skipped(reason="lock_held", now=_at(1))
        state.release(owner="A", now=_at(2))

        state.acquire(owner="A", now=_at(10))
        state.mark_started(run_id="run-1", now=_at(11))
        decision = state.mark_completed(
            run_id="run-1", selected_count=4, spent_calls=2, now=_at(20),
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "completed")

        snap = state.snapshot(now=_at(21))
        self.assertEqual(snap.last_completed_at,  _at(20).isoformat())
        self.assertEqual(snap.last_selected_count, 4)
        self.assertEqual(snap.last_spent_calls,    2)
        self.assertIsNone(snap.last_skip_reason)
        self.assertIsNone(snap.last_error)

    def test_mark_completed_without_lock_rejected(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        decision = state.mark_completed(
            run_id="run-1", selected_count=0, spent_calls=0, now=_T0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no_lock")

    def test_mark_completed_without_started_rejected(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        decision = state.mark_completed(
            run_id="run-1", selected_count=0, spent_calls=0, now=_at(1),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no_run_started")

    def test_mark_completed_run_id_mismatch_rejected(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="run-1", now=_at(1))
        decision = state.mark_completed(
            run_id="DIFFERENT", selected_count=0, spent_calls=0, now=_at(2),
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "run_id_mismatch")


# ---------------------------------------------------------------------------
# Run lifecycle: started → skipped (or skipped without start)
# ---------------------------------------------------------------------------


class TestRunLifecycleSkipped(unittest.TestCase):
    def test_skip_before_start_records_reason_only(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        decision = state.mark_skipped(reason="lock_held", now=_T0)
        self.assertIsInstance(decision, MarkDecision)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "skipped")
        snap = state.snapshot(now=_at(1))
        self.assertEqual(snap.last_skip_reason, "lock_held")
        # No started/completed/error fields touched.
        self.assertIsNone(snap.last_started_at)
        self.assertIsNone(snap.last_completed_at)
        self.assertIsNone(snap.last_error)

    def test_skip_with_error_carries_error_field(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="r-1", now=_at(1))
        decision = state.mark_skipped(
            reason="job_crashed",
            error="ZeroDivisionError: integer division by zero",
            now=_at(5),
        )
        self.assertTrue(decision.allowed)
        snap = state.snapshot(now=_at(6))
        self.assertEqual(snap.last_skip_reason, "job_crashed")
        self.assertEqual(
            snap.last_error,
            "ZeroDivisionError: integer division by zero",
        )

    def test_completed_clears_previous_error(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="r-1", now=_at(1))
        state.mark_skipped(reason="job_crashed", error="boom", now=_at(2))
        state.release(owner="A", now=_at(3))
        # Second run completes cleanly.
        state.acquire(owner="A", now=_at(10))
        state.mark_started(run_id="r-2", now=_at(11))
        state.mark_completed(
            run_id="r-2", selected_count=3, spent_calls=1, now=_at(20),
        )
        snap = state.snapshot(now=_at(21))
        self.assertIsNone(snap.last_error)
        self.assertIsNone(snap.last_skip_reason)


# ---------------------------------------------------------------------------
# Snapshot shape — every field documented in the brief
# ---------------------------------------------------------------------------


class TestSnapshotShape(unittest.TestCase):
    def test_empty_state_snapshot_has_all_fields(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        snap = state.snapshot(now=_T0)
        self.assertIsInstance(snap, StateSnapshot)
        self.assertFalse(snap.lock_held)
        self.assertIsNone(snap.lock_owner)
        self.assertIsNone(snap.lock_acquired_at)
        self.assertIsNone(snap.lock_expires_at)
        self.assertIsNone(snap.last_run_id)
        self.assertIsNone(snap.last_started_at)
        self.assertIsNone(snap.last_completed_at)
        self.assertIsNone(snap.last_skip_reason)
        self.assertIsNone(snap.last_error)
        self.assertIsNone(snap.last_selected_count)
        self.assertIsNone(snap.last_spent_calls)

    def test_snapshot_after_full_lifecycle(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="r-1", now=_at(1))
        state.mark_completed(
            run_id="r-1", selected_count=5, spent_calls=3, now=_at(10),
        )
        state.release(owner="A", now=_at(11))
        snap = state.snapshot(now=_at(12))
        self.assertFalse(snap.lock_held)
        self.assertIsNone(snap.lock_owner)
        self.assertEqual(snap.last_run_id,        "r-1")
        self.assertEqual(snap.last_started_at,    _at(1).isoformat())
        self.assertEqual(snap.last_completed_at,  _at(10).isoformat())
        self.assertEqual(snap.last_selected_count, 5)
        self.assertEqual(snap.last_spent_calls,    3)
        self.assertIsNone(snap.last_skip_reason)
        self.assertIsNone(snap.last_error)

    def test_snapshot_reports_lock_expiry_after_stale(self) -> None:
        # When a snapshot is taken AFTER the TTL has passed but before
        # anyone re-acquired, the snapshot should report the lock as
        # NOT held — TTL expiry is observable without an explicit
        # release-by-expiry call.
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        snap = state.snapshot(now=_at(120))
        self.assertFalse(snap.lock_held)
        self.assertIsNone(snap.lock_owner)


# ---------------------------------------------------------------------------
# Deterministic clock injection
# ---------------------------------------------------------------------------


class TestDeterministicClock(unittest.TestCase):
    def test_two_snapshots_with_same_now_are_equal(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="r", now=_at(1))
        state.mark_completed(
            run_id="r", selected_count=2, spent_calls=1, now=_at(2),
        )
        s1 = state.snapshot(now=_at(5))
        s2 = state.snapshot(now=_at(5))
        self.assertEqual(s1, s2)

    def test_now_defaults_to_real_clock_but_acquire_still_records_iso(
        self,
    ) -> None:
        # If the caller omits ``now``, the module reads the real UTC
        # clock.  We only assert that ``acquired_at`` is non-empty and
        # parseable as ISO 8601 — value depends on wall time, of course.
        state = AutoBackfillState(ttl_seconds=60)
        decision = state.acquire(owner="A")
        self.assertTrue(decision.allowed)
        self.assertIsInstance(decision.acquired_at, str)
        # Round-trip parse — guards against accidental non-ISO output.
        datetime.fromisoformat(decision.acquired_at)


# ---------------------------------------------------------------------------
# Defensive input handling
# ---------------------------------------------------------------------------


class TestInputValidation(unittest.TestCase):
    def test_acquire_rejects_empty_owner(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        with self.assertRaises(ValueError):
            state.acquire(owner="", now=_T0)

    def test_mark_started_rejects_empty_run_id(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        with self.assertRaises(ValueError):
            state.mark_started(run_id="", now=_at(1))

    def test_mark_completed_rejects_negative_counts(self) -> None:
        state = AutoBackfillState(ttl_seconds=60)
        state.acquire(owner="A", now=_T0)
        state.mark_started(run_id="r", now=_at(1))
        with self.assertRaises(ValueError):
            state.mark_completed(
                run_id="r", selected_count=-1, spent_calls=0, now=_at(2),
            )
        with self.assertRaises(ValueError):
            state.mark_completed(
                run_id="r", selected_count=0, spent_calls=-1, now=_at(2),
            )

    def test_constructor_rejects_non_positive_ttl(self) -> None:
        with self.assertRaises(ValueError):
            AutoBackfillState(ttl_seconds=0)
        with self.assertRaises(ValueError):
            AutoBackfillState(ttl_seconds=-1)


if __name__ == "__main__":
    unittest.main()
