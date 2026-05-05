"""Tests for auto_backfill_policy.

Verifies the eligibility decision over every documented reason, the
recent-run boundary, ledger-snapshot acceptance, and that the result
is fully driven by the injected ``now`` so it's deterministic.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from auto_backfill_ledger import AutoBackfillLedger
from auto_backfill_policy import (
    REASON_CONFIGURED,
    REASON_DAILY_CAP_EXHAUSTED,
    REASON_DISABLED,
    REASON_INVALID_CONFIG,
    REASON_LOCK_HELD,
    REASON_PAID_GUARD_BLOCKED,
    REASON_RECENTLY_RUN,
    AutoBackfillRunDecision,
    decide_auto_backfill_run,
)


def _dt(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, 0, tzinfo=timezone.utc)


def _config(**overrides) -> dict:
    cfg = {
        "enabled": True,
        "max_calls_per_run": 10,
        "interval_hours": 0,
    }
    cfg.update(overrides)
    return cfg


def _state(**overrides) -> dict:
    state = {
        "lock_held": False,
        "paid_guard_blocked": False,
        "last_completed_at": None,
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Each documented reason
# ---------------------------------------------------------------------------


class DisabledReasonTests(unittest.TestCase):
    def test_enabled_false_blocks_with_disabled_reason(self):
        decision = decide_auto_backfill_run(
            _config(enabled=False),
            ledger_snapshot=None,
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertIsInstance(decision, AutoBackfillRunDecision)
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_DISABLED)
        # Cap should still be reported even when disabled.
        self.assertEqual(decision.effective_per_run_cap, 10)


class PaidGuardReasonTests(unittest.TestCase):
    def test_paid_guard_blocked_state_blocks_run(self):
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot={"remaining": 5},
            state_snapshot=_state(paid_guard_blocked=True),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_PAID_GUARD_BLOCKED)
        self.assertEqual(decision.effective_daily_remaining, 5)


class LockReasonTests(unittest.TestCase):
    def test_lock_held_blocks_run(self):
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot=None,
            state_snapshot=_state(lock_held=True),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_LOCK_HELD)


class RecentlyRunReasonTests(unittest.TestCase):
    def test_within_interval_is_recently_run(self):
        now = _dt(2026, 5, 5, 12)
        last = (now - timedelta(hours=2)).isoformat()
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at=last),
            now=now,
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_RECENTLY_RUN)

    def test_exact_boundary_is_allowed(self):
        # Elapsed == interval should *not* be classified as recent.
        now = _dt(2026, 5, 5, 12)
        last = (now - timedelta(hours=6)).isoformat()
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at=last),
            now=now,
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)

    def test_one_second_before_boundary_is_blocked(self):
        now = _dt(2026, 5, 5, 12)
        last = (now - timedelta(hours=6) + timedelta(seconds=1)).isoformat()
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at=last),
            now=now,
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_RECENTLY_RUN)

    def test_zero_interval_disables_recent_run_check(self):
        now = _dt(2026, 5, 5, 12)
        last = (now - timedelta(seconds=5)).isoformat()
        decision = decide_auto_backfill_run(
            _config(interval_hours=0),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at=last),
            now=now,
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)


class StaleLastCompletedTests(unittest.TestCase):
    def test_no_last_completed_does_not_block(self):
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at=None),
            now=_dt(2026, 5, 5),
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)

    def test_unparseable_last_completed_is_treated_as_never_run(self):
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at="not a timestamp"),
            now=_dt(2026, 5, 5),
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)

    def test_far_past_last_completed_does_not_block(self):
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(last_completed_at="2020-01-01T00:00:00Z"),
            now=_dt(2026, 5, 5),
        )
        self.assertTrue(decision.run_allowed)


class DailyCapReasonTests(unittest.TestCase):
    def test_zero_remaining_blocks_with_daily_cap_exhausted(self):
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot={"remaining": 0},
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_DAILY_CAP_EXHAUSTED)
        self.assertEqual(decision.effective_daily_remaining, 0)

    def test_ledger_snapshot_int_zero_blocks(self):
        decision = decide_auto_backfill_run(
            _config(), 0, _state(), now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_DAILY_CAP_EXHAUSTED)

    def test_no_ledger_snapshot_does_not_block(self):
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot=None,
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)
        self.assertIsNone(decision.effective_daily_remaining)

    def test_real_ledger_decision_object_accepted(self):
        ledger = AutoBackfillLedger(daily_cap=3)
        ledger.reserve_calls(3, now=_dt(2026, 5, 5))
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot=ledger.snapshot(now=_dt(2026, 5, 5)),
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_DAILY_CAP_EXHAUSTED)
        self.assertEqual(decision.effective_daily_remaining, 0)


class ConfiguredReasonTests(unittest.TestCase):
    def test_happy_path_yields_configured(self):
        decision = decide_auto_backfill_run(
            _config(max_calls_per_run=4, interval_hours=6),
            ledger_snapshot={"remaining": 5},
            state_snapshot=_state(
                last_completed_at="2026-05-04T00:00:00Z",
            ),
            now=_dt(2026, 5, 5, 12),
        )
        self.assertTrue(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_CONFIGURED)
        self.assertEqual(decision.effective_per_run_cap, 4)
        self.assertEqual(decision.effective_daily_remaining, 5)


class InvalidConfigTests(unittest.TestCase):
    def test_non_mapping_config_invalid(self):
        decision = decide_auto_backfill_run(
            "not a dict", None, _state(), now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)
        self.assertEqual(decision.effective_per_run_cap, 0)

    def test_non_bool_enabled_invalid(self):
        decision = decide_auto_backfill_run(
            {"enabled": "yes", "max_calls_per_run": 1, "interval_hours": 0},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)

    def test_negative_max_calls_per_run_invalid(self):
        decision = decide_auto_backfill_run(
            {"enabled": True, "max_calls_per_run": -1, "interval_hours": 0},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)

    def test_non_int_max_calls_per_run_invalid(self):
        decision = decide_auto_backfill_run(
            {"enabled": True, "max_calls_per_run": 1.5, "interval_hours": 0},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)

    def test_negative_interval_invalid(self):
        decision = decide_auto_backfill_run(
            {"enabled": True, "max_calls_per_run": 1, "interval_hours": -2},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertFalse(decision.run_allowed)
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)

    def test_invalid_config_includes_detail(self):
        decision = decide_auto_backfill_run(
            {"enabled": True, "max_calls_per_run": -1, "interval_hours": 0},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertIsNotNone(decision.detail)
        self.assertIn("max_calls_per_run", decision.detail or "")


# ---------------------------------------------------------------------------
# Cap / remaining propagation
# ---------------------------------------------------------------------------


class CapAndRemainingPropagationTests(unittest.TestCase):
    def test_per_run_cap_is_independent_of_daily_remaining(self):
        decision = decide_auto_backfill_run(
            _config(max_calls_per_run=20),
            ledger_snapshot={"remaining": 3},
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertEqual(decision.effective_per_run_cap, 20)
        self.assertEqual(decision.effective_daily_remaining, 3)

    def test_cap_reported_on_blocked_decisions_too(self):
        decision = decide_auto_backfill_run(
            _config(max_calls_per_run=7, enabled=False),
            ledger_snapshot={"remaining": 2},
            state_snapshot=_state(),
            now=_dt(2026, 5, 5),
        )
        self.assertEqual(decision.effective_per_run_cap, 7)
        self.assertEqual(decision.effective_daily_remaining, 2)
        self.assertFalse(decision.run_allowed)


# ---------------------------------------------------------------------------
# Priority ordering
# ---------------------------------------------------------------------------


class PriorityOrderingTests(unittest.TestCase):
    def test_invalid_config_outranks_disabled(self):
        decision = decide_auto_backfill_run(
            {"enabled": "no", "max_calls_per_run": 1, "interval_hours": 0},
            None,
            _state(),
            now=_dt(2026, 5, 5),
        )
        self.assertEqual(decision.reason, REASON_INVALID_CONFIG)

    def test_disabled_outranks_paid_guard(self):
        decision = decide_auto_backfill_run(
            _config(enabled=False),
            ledger_snapshot=None,
            state_snapshot=_state(paid_guard_blocked=True),
            now=_dt(2026, 5, 5),
        )
        self.assertEqual(decision.reason, REASON_DISABLED)

    def test_paid_guard_outranks_lock(self):
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot=None,
            state_snapshot=_state(paid_guard_blocked=True, lock_held=True),
            now=_dt(2026, 5, 5),
        )
        self.assertEqual(decision.reason, REASON_PAID_GUARD_BLOCKED)

    def test_lock_outranks_recent_run(self):
        now = _dt(2026, 5, 5, 12)
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot=None,
            state_snapshot=_state(
                lock_held=True,
                last_completed_at=(now - timedelta(hours=1)).isoformat(),
            ),
            now=now,
        )
        self.assertEqual(decision.reason, REASON_LOCK_HELD)

    def test_recent_run_outranks_daily_cap(self):
        now = _dt(2026, 5, 5, 12)
        decision = decide_auto_backfill_run(
            _config(interval_hours=6),
            ledger_snapshot={"remaining": 0},
            state_snapshot=_state(
                last_completed_at=(now - timedelta(hours=1)).isoformat(),
            ),
            now=now,
        )
        self.assertEqual(decision.reason, REASON_RECENTLY_RUN)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


class DeterminismTests(unittest.TestCase):
    def test_now_is_echoed_in_decision(self):
        now = _dt(2027, 3, 9, 17, 30)
        decision = decide_auto_backfill_run(
            _config(),
            ledger_snapshot=None,
            state_snapshot=_state(),
            now=now,
        )
        self.assertEqual(decision.now, now.isoformat())

    def test_repeat_calls_with_same_inputs_match(self):
        cfg = _config(max_calls_per_run=3, interval_hours=2)
        ledger = {"remaining": 5}
        state = _state(last_completed_at="2026-05-05T00:00:00Z")
        fixed = _dt(2026, 5, 5, 12)
        a = decide_auto_backfill_run(cfg, ledger, state, now=fixed)
        b = decide_auto_backfill_run(cfg, ledger, state, now=fixed)
        self.assertEqual(a, b)

    def test_naive_now_is_treated_as_utc(self):
        # A timezone-naive datetime should produce the same result as an
        # explicit UTC one.
        naive = datetime(2026, 5, 5, 12, 0, 0)
        aware = naive.replace(tzinfo=timezone.utc)
        cfg = _config()
        a = decide_auto_backfill_run(cfg, None, _state(), now=naive)
        b = decide_auto_backfill_run(cfg, None, _state(), now=aware)
        self.assertEqual(a.reason, b.reason)
        self.assertEqual(a.now, b.now)

    def test_non_datetime_now_raises(self):
        with self.assertRaises(TypeError):
            decide_auto_backfill_run(
                _config(), None, _state(), now="2026-05-05",  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
