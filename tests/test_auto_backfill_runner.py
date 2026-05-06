"""Tests for ``auto_backfill_runner.run_auto_backfill_dry_run``.

The runner is a pure composer over the four already-built pure pieces:

  * :mod:`auto_backfill_config`   — env-driven config snapshot
  * :mod:`auto_backfill_ledger`   — daily call counter
  * :mod:`auto_backfill_state`    — in-memory run-state + lock
  * :mod:`auto_backfill_planner`  — deterministic candidate selection

It is dry-run only.  No paid execution, no APScheduler integration,
no FastAPI startup wiring, no LLM / yfinance / market_check / network /
DB writes.  Candidates are injected by the caller.

Mirrors the scheduler design contract in
``docs/auto_backfill_scheduler_design.md`` §3 (env), §5 (lock),
§9 (diagnostics surface).
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_backfill_config import AutoBackfillConfig  # noqa: E402
from auto_backfill_ledger import AutoBackfillLedger  # noqa: E402
from auto_backfill_runner import (  # noqa: E402
    RunResult,
    execute_paid_candidate,
    run_auto_backfill_dry_run,
)
from auto_backfill_state import AutoBackfillState  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — synthetic config / candidates / clock
# ---------------------------------------------------------------------------

_T0 = datetime(2026, 5, 5, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds: float) -> datetime:
    return _T0 + timedelta(seconds=seconds)


def _config(
    *, enabled: bool = True, paid: bool = True,
    interval_hours: int = 6,
    max_per_run: int = 3, max_per_day: int = 12,
    model: str = "claude-haiku-4-5-20251001",
) -> AutoBackfillConfig:
    """Build an AutoBackfillConfig directly — bypasses env parsing
    for deterministic tests.  ``effective_status`` is derived the same
    way ``load_auto_backfill_config`` derives it.
    """
    if not enabled:
        status = "disabled"
    elif not paid:
        status = "blocked_paid_guard"
    else:
        status = "configured"
    return AutoBackfillConfig(
        enabled=enabled,
        paid_analysis_enabled=paid,
        interval_hours=interval_hours,
        max_calls_per_run=max_per_run,
        max_calls_per_day=max_per_day,
        model=model,
        effective_status=status,
        warnings=[],
    )


def _candidate(
    headline: str, *,
    rank_score: float = 1.0,
    source_count: int = 3,
    registry_state: str = "eligible",
    skip_reason: str | None = None,
) -> dict:
    return {
        "headline":       headline,
        "rank_score":     rank_score,
        "source_count":   source_count,
        "published_at":   "2026-05-05T11:00:00+00:00",
        "registry_state": registry_state,
        "skip_reason":    skip_reason,
    }


def _make_state_and_ledger(
    *, ttl_seconds: int = 600, daily_cap: int = 12,
) -> tuple[AutoBackfillState, AutoBackfillLedger]:
    return (
        AutoBackfillState(ttl_seconds=ttl_seconds),
        AutoBackfillLedger(daily_cap=daily_cap),
    )


def _fixed_run_id() -> str:
    return "run-fixed-deadbeef"


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------


class TestRunResultShape(unittest.TestCase):
    def test_returns_run_result_with_expected_fields(self) -> None:
        state, ledger = _make_state_and_ledger()
        result = run_auto_backfill_dry_run(
            candidates=[],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertIsInstance(result, RunResult)
        # The dataclass is frozen; just check every documented field exists.
        for field in (
            "run_id", "dry_run", "decision_reason", "started", "completed",
            "skip_reason", "selected_count", "spent_calls", "plan",
            "state_snapshot_after", "now",
        ):
            self.assertTrue(hasattr(result, field), f"missing field {field!r}")
        self.assertTrue(result.dry_run)
        self.assertEqual(result.spent_calls, 0)


# ---------------------------------------------------------------------------
# Disabled / blocked / lock-held — runner skips
# ---------------------------------------------------------------------------


class TestSkipPaths(unittest.TestCase):
    def test_disabled_config_skips_with_disabled_reason(self) -> None:
        state, ledger = _make_state_and_ledger()
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("OPEC cuts crude")],
            config=_config(enabled=False),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertFalse(result.started)
        self.assertFalse(result.completed)
        self.assertEqual(result.decision_reason, "disabled")
        self.assertEqual(result.skip_reason,    "disabled")
        self.assertEqual(result.selected_count, 0)
        # Lock NOT acquired — disabled means do nothing.
        self.assertFalse(result.state_snapshot_after.lock_held)
        # State carries the skip reason so a diagnostic snapshot can show it.
        self.assertEqual(
            result.state_snapshot_after.last_skip_reason, "disabled",
        )

    def test_paid_guard_blocks_when_paid_disabled(self) -> None:
        state, ledger = _make_state_and_ledger()
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("OPEC cuts crude")],
            config=_config(enabled=True, paid=False),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertFalse(result.started)
        self.assertFalse(result.completed)
        self.assertEqual(result.decision_reason, "paid_guard_blocked")
        self.assertEqual(result.skip_reason,     "paid_guard_blocked")
        self.assertFalse(result.state_snapshot_after.lock_held)

    def test_lock_held_by_other_owner_skips_with_lock_held(self) -> None:
        state, ledger = _make_state_and_ledger()
        # Another worker holds the lock.
        state.acquire(owner="another-worker", now=_T0)
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("OPEC cuts crude")],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_at(1),
            run_id_factory=_fixed_run_id,
        )
        self.assertFalse(result.started)
        self.assertFalse(result.completed)
        self.assertEqual(result.decision_reason, "lock_held")
        self.assertEqual(result.skip_reason,    "lock_held")
        # The pre-existing lock is still held by the OTHER worker; the
        # runner did not touch it.
        snap = state.snapshot(now=_at(2))
        self.assertTrue(snap.lock_held)
        self.assertEqual(snap.lock_owner, "another-worker")

    def test_recently_run_skips_within_interval(self) -> None:
        # Seed last_completed_at within the interval window.
        state, ledger = _make_state_and_ledger()
        cfg = _config(interval_hours=6)
        # Manually drive a successful run to set last_completed_at.
        state.acquire(owner="self", now=_T0)
        state.mark_started(run_id="prev", now=_T0)
        state.mark_completed(
            run_id="prev", selected_count=0, spent_calls=0, now=_T0,
        )
        state.release(owner="self", now=_T0)

        # 1 hour later — well inside the 6-hour interval.
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("OPEC cuts crude")],
            config=cfg,
            state=state,
            ledger=ledger,
            now=_T0 + timedelta(hours=1),
            run_id_factory=_fixed_run_id,
        )
        self.assertFalse(result.started)
        self.assertEqual(result.decision_reason, "recently_run")

    def test_daily_cap_exhausted_skips(self) -> None:
        state, ledger = _make_state_and_ledger(daily_cap=2)
        # Burn the day's quota directly via the ledger seam.
        ledger.reserve_calls(2, now=_T0)
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("OPEC cuts crude")],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_at(1),
            run_id_factory=_fixed_run_id,
        )
        self.assertFalse(result.started)
        self.assertEqual(result.decision_reason, "daily_cap_exhausted")
        self.assertEqual(result.skip_reason,    "daily_cap_exhausted")


# ---------------------------------------------------------------------------
# No candidates — runs through but plans empty
# ---------------------------------------------------------------------------


class TestEmptyCandidates(unittest.TestCase):
    def test_empty_candidate_list_completes_with_zero_selected(self) -> None:
        state, ledger = _make_state_and_ledger()
        result = run_auto_backfill_dry_run(
            candidates=[],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertTrue(result.started)
        self.assertTrue(result.completed)
        self.assertEqual(result.decision_reason, "configured")
        self.assertIsNone(result.skip_reason)
        self.assertEqual(result.selected_count, 0)
        # Lock released after completion.
        self.assertFalse(result.state_snapshot_after.lock_held)
        # State reflects the run.
        self.assertEqual(result.state_snapshot_after.last_run_id, _fixed_run_id())
        self.assertEqual(result.state_snapshot_after.last_selected_count, 0)
        self.assertEqual(result.state_snapshot_after.last_spent_calls,    0)


# ---------------------------------------------------------------------------
# Planned candidates — selection cap, ranking, ledger untouched
# ---------------------------------------------------------------------------


class TestPlannedCandidates(unittest.TestCase):
    def test_plan_caps_at_max_per_run(self) -> None:
        state, ledger = _make_state_and_ledger()
        candidates = [
            _candidate(f"OPEC cluster #{i}", rank_score=10.0 - i)
            for i in range(10)
        ]
        result = run_auto_backfill_dry_run(
            candidates=candidates,
            config=_config(max_per_run=3),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertTrue(result.completed)
        self.assertEqual(result.selected_count, 3)
        self.assertEqual(result.plan.selected_count, 3)

    def test_plan_respects_daily_remaining_when_lower_than_run_cap(self) -> None:
        state, ledger = _make_state_and_ledger(daily_cap=5)
        # 3 already spent → only 2 remaining for today.
        ledger.reserve_calls(3, now=_T0)
        candidates = [
            _candidate(f"Cluster #{i}", rank_score=10.0 - i)
            for i in range(10)
        ]
        result = run_auto_backfill_dry_run(
            candidates=candidates,
            config=_config(max_per_run=4),
            state=state,
            ledger=ledger,
            now=_at(1),
            run_id_factory=_fixed_run_id,
        )
        self.assertTrue(result.completed)
        # daily_remaining=2 dominates the 4-per-run cap.
        self.assertEqual(result.selected_count, 2)

    def test_already_analyzed_candidates_filtered_out(self) -> None:
        state, ledger = _make_state_and_ledger()
        candidates = [
            _candidate("Eligible #1",     registry_state="eligible"),
            _candidate("Already #1",      registry_state="analyzed"),
            _candidate("Eligible #2",     registry_state="seen"),
            _candidate("Already #2",      registry_state="market_checked"),
        ]
        result = run_auto_backfill_dry_run(
            candidates=candidates,
            config=_config(max_per_run=10),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertEqual(result.selected_count, 2)
        selected_headlines = [c["headline"] for c in result.plan.selected]
        self.assertEqual(
            sorted(selected_headlines),
            ["Eligible #1", "Eligible #2"],
        )


# ---------------------------------------------------------------------------
# No ledger mutation on dry-run — the load-bearing safety property
# ---------------------------------------------------------------------------


class TestLedgerNotMutated(unittest.TestCase):
    def test_ledger_used_count_unchanged_after_dry_run(self) -> None:
        state, ledger = _make_state_and_ledger(daily_cap=12)
        before = ledger.snapshot(now=_T0).used
        candidates = [
            _candidate(f"Cluster #{i}", rank_score=10.0 - i)
            for i in range(5)
        ]
        result = run_auto_backfill_dry_run(
            candidates=candidates,
            config=_config(max_per_run=3),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertGreater(result.selected_count, 0)
        self.assertEqual(ledger.snapshot(now=_T0).used, before)
        # spent_calls is 0 because no paid call was made.
        self.assertEqual(result.spent_calls, 0)

    def test_ledger_unchanged_even_when_skipped(self) -> None:
        state, ledger = _make_state_and_ledger()
        before = ledger.snapshot(now=_T0).used
        run_auto_backfill_dry_run(
            candidates=[_candidate("X")],
            config=_config(enabled=False),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        self.assertEqual(ledger.snapshot(now=_T0).used, before)


# ---------------------------------------------------------------------------
# State transitions: started → completed; skipped path
# ---------------------------------------------------------------------------


class TestStateTransitions(unittest.TestCase):
    def test_completed_run_stamps_started_and_completed_at(self) -> None:
        state, ledger = _make_state_and_ledger()
        result = run_auto_backfill_dry_run(
            candidates=[_candidate("A")],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        snap = result.state_snapshot_after
        self.assertEqual(snap.last_run_id, _fixed_run_id())
        self.assertIsNotNone(snap.last_started_at)
        self.assertIsNotNone(snap.last_completed_at)
        self.assertIsNone(snap.last_skip_reason)
        self.assertIsNone(snap.last_error)
        self.assertEqual(snap.last_selected_count, 1)
        self.assertEqual(snap.last_spent_calls,    0)

    def test_skipped_path_does_not_stamp_started(self) -> None:
        state, ledger = _make_state_and_ledger()
        run_auto_backfill_dry_run(
            candidates=[_candidate("A")],
            config=_config(enabled=False),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        snap = state.snapshot(now=_at(1))
        self.assertIsNone(snap.last_started_at)
        self.assertIsNone(snap.last_completed_at)
        self.assertEqual(snap.last_skip_reason, "disabled")

    def test_lock_released_after_completion(self) -> None:
        state, ledger = _make_state_and_ledger()
        run_auto_backfill_dry_run(
            candidates=[_candidate("A")],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_fixed_run_id,
        )
        # Same owner can immediately reacquire — the previous run
        # released its lock cleanly.
        decision = state.acquire(owner="probe", now=_at(1))
        self.assertTrue(decision.allowed)


# ---------------------------------------------------------------------------
# Deterministic clock — same now → same observable result
# ---------------------------------------------------------------------------


class TestDeterministicClock(unittest.TestCase):
    def test_two_runs_at_same_now_with_same_factory_match(self) -> None:
        # Each run uses its own fresh state/ledger so the comparison
        # isolates the runner's determinism from the state machine's.
        candidates = [
            _candidate(f"Cluster #{i}", rank_score=10.0 - i)
            for i in range(5)
        ]
        cfg = _config()

        s1, l1 = _make_state_and_ledger()
        s2, l2 = _make_state_and_ledger()
        r1 = run_auto_backfill_dry_run(
            candidates=candidates, config=cfg, state=s1, ledger=l1,
            now=_T0, run_id_factory=_fixed_run_id,
        )
        r2 = run_auto_backfill_dry_run(
            candidates=candidates, config=cfg, state=s2, ledger=l2,
            now=_T0, run_id_factory=_fixed_run_id,
        )
        self.assertEqual(r1.run_id,           r2.run_id)
        self.assertEqual(r1.decision_reason,  r2.decision_reason)
        self.assertEqual(r1.selected_count,   r2.selected_count)
        self.assertEqual(r1.completed,        r2.completed)
        self.assertEqual(
            [c["headline"] for c in r1.plan.selected],
            [c["headline"] for c in r2.plan.selected],
        )

    def test_run_id_factory_is_called_once_per_run(self) -> None:
        calls: list[str] = []

        def _factory() -> str:
            calls.append("invoked")
            return "run-counted"

        state, ledger = _make_state_and_ledger()
        run_auto_backfill_dry_run(
            candidates=[_candidate("A")],
            config=_config(),
            state=state,
            ledger=ledger,
            now=_T0,
            run_id_factory=_factory,
        )
        self.assertEqual(len(calls), 1)


# ---------------------------------------------------------------------------
# Paid execution stub — explicitly not implemented
# ---------------------------------------------------------------------------


class TestPaidExecutionStub(unittest.TestCase):
    def test_execute_paid_candidate_raises_not_implemented(self) -> None:
        with self.assertRaises(NotImplementedError) as cm:
            execute_paid_candidate({"headline": "anything"})
        # The message should make clear this is by design and where to
        # look next, not just a barebones NotImplementedError.
        self.assertIn("not implemented", str(cm.exception).lower())

    def test_runner_does_not_invoke_paid_stub_in_dry_run(self) -> None:
        # Patch the stub to a raiser; runner must never call it.
        from unittest.mock import patch
        state, ledger = _make_state_and_ledger()
        with patch(
            "auto_backfill_runner.execute_paid_candidate",
            side_effect=AssertionError("dry-run runner must not call paid stub"),
        ):
            result = run_auto_backfill_dry_run(
                candidates=[_candidate("A")],
                config=_config(),
                state=state,
                ledger=ledger,
                now=_T0,
                run_id_factory=_fixed_run_id,
            )
        self.assertTrue(result.completed)
        self.assertEqual(result.spent_calls, 0)


if __name__ == "__main__":
    unittest.main()
