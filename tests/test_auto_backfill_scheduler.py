"""Tests for the disabled-by-default APScheduler dry-run skeleton.

The skeleton is dry-run only.  No paid execution, no FastAPI lifespan
wiring, no LLM / yfinance / market_check / network / DB writes.
Every test exercises the public seams of ``auto_backfill_scheduler``
without spawning the APScheduler executor thread — ``add_job`` is
sufficient to inspect the queued job; we never call ``.start()``
unless the test explicitly requires it.
"""

from __future__ import annotations

import os
import sys
import threading
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Capture the thread set as observed when the test module first loads —
# the "no scheduler thread spawned by import" check below compares
# against this baseline, which makes the assertion order-independent
# (later tests may start real schedulers without contaminating this).
_THREADS_AT_IMPORT_TIME: set[str] = {
    (t.name or "").lower() for t in threading.enumerate()
}

import auto_backfill_scheduler as scheduler_module  # noqa: E402
from auto_backfill_config import AutoBackfillConfig  # noqa: E402
from auto_backfill_runner import RunResult  # noqa: E402
from auto_backfill_state import AutoBackfillState  # noqa: E402

# Snapshot AGAIN immediately after importing the module under test;
# any thread that appeared between the two snapshots was created as
# a side-effect of importing ``auto_backfill_scheduler``.
_THREADS_AFTER_MODULE_IMPORT: set[str] = {
    (t.name or "").lower() for t in threading.enumerate()
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _config(
    *,
    enabled: bool = True,
    paid: bool = True,
    interval_hours: int = 6,
    max_per_run: int = 3,
    max_per_day: int = 12,
) -> AutoBackfillConfig:
    """Build an ``AutoBackfillConfig`` directly — bypasses env parsing
    so each test pins the effective_status it needs.
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
        model="claude-haiku-4-5-20251001",
        effective_status=status,
        warnings=[],
    )


def _make_run_result(state: AutoBackfillState) -> RunResult:
    """Build a stand-in ``RunResult`` for a mock runner so the job
    function's logging path doesn't trip on missing attrs.
    """
    return RunResult(
        run_id="test-run",
        dry_run=True,
        decision_reason="configured",
        started=True,
        completed=True,
        skip_reason=None,
        selected_count=0,
        spent_calls=0,
        plan=None,
        state_snapshot_after=state.snapshot(now=datetime(
            2026, 5, 6, 0, 0, 0, tzinfo=timezone.utc,
        )),
        now="2026-05-06T00:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Importing the module must NOT start a scheduler thread
# ---------------------------------------------------------------------------


class TestNotStartedByImport(unittest.TestCase):
    def test_module_has_no_module_level_scheduler_instance(self) -> None:
        # The skeleton has no module-level scheduler — every scheduler
        # is constructed by an explicit call to
        # ``create_auto_backfill_scheduler``.  This guards against a
        # future refactor that accidentally introduces one.
        for name in dir(scheduler_module):
            obj = getattr(scheduler_module, name)
            self.assertFalse(
                obj.__class__.__name__ == "BackgroundScheduler",
                f"module-level BackgroundScheduler instance found: {name}",
            )

    def test_no_thread_spawned_by_module_import(self) -> None:
        # Compare the thread set captured BEFORE importing
        # ``auto_backfill_scheduler`` against the one captured
        # IMMEDIATELY AFTER.  Any new thread between those two
        # snapshots was created as a side-effect of the import.  This
        # is order-independent: a later test that starts a real
        # scheduler cannot pollute this assertion because both
        # snapshots are taken at module load time.
        new_threads = _THREADS_AFTER_MODULE_IMPORT - _THREADS_AT_IMPORT_TIME
        self.assertEqual(
            new_threads, set(),
            f"importing auto_backfill_scheduler spawned threads: {new_threads}",
        )

    def test_module_exposes_required_public_functions(self) -> None:
        for fn in (
            "create_auto_backfill_scheduler",
            "start_auto_backfill_scheduler",
            "stop_auto_backfill_scheduler",
        ):
            self.assertTrue(
                callable(getattr(scheduler_module, fn, None)),
                f"missing public function: {fn}",
            )


# ---------------------------------------------------------------------------
# Job add / skip behaviour by config status
# ---------------------------------------------------------------------------


class TestJobNotAddedWhenDisabled(unittest.TestCase):
    def test_disabled_config_results_in_no_job(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=False),
        )
        self.assertEqual(sched.get_jobs(), [])

    def test_paid_guard_blocked_config_results_in_no_job(self) -> None:
        # blocked_paid_guard is also a non-configured status — even
        # though the skeleton is dry-run, scheduling under a paid-
        # guard-blocked config diverges from the design's "scheduler
        # doesn't start unless both gates green" contract.
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=False),
        )
        self.assertEqual(sched.get_jobs(), [])

    def test_disabled_scheduler_can_be_safely_stopped(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=False),
        )
        # Never started — stop must NOT raise SchedulerNotRunningError.
        scheduler_module.stop_auto_backfill_scheduler(sched)


class TestJobAddedWhenConfigured(unittest.TestCase):
    def test_configured_config_adds_one_job(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
        )
        jobs = sched.get_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].id, scheduler_module.JOB_ID)

    def test_job_uses_interval_trigger_with_configured_seconds(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True, interval_hours=4),
        )
        job = sched.get_jobs()[0]
        # APScheduler's IntervalTrigger stores ``interval`` as a
        # timedelta; total_seconds() should match interval_hours * 3600.
        self.assertEqual(job.trigger.interval.total_seconds(), 4 * 3600)


# ---------------------------------------------------------------------------
# coalesce / max_instances / misfire_grace_time
# ---------------------------------------------------------------------------


class TestJobMisfirePolicy(unittest.TestCase):
    def test_default_coalesce_max_instances_misfire_grace_set(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
        )
        job = sched.get_jobs()[0]
        self.assertTrue(job.coalesce)
        self.assertEqual(job.max_instances, 1)
        self.assertEqual(job.misfire_grace_time, 600)

    def test_overrides_propagate_to_job(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            coalesce=False,
            max_instances=2,
            misfire_grace_seconds=120,
        )
        job = sched.get_jobs()[0]
        self.assertFalse(job.coalesce)
        self.assertEqual(job.max_instances, 2)
        self.assertEqual(job.misfire_grace_time, 120)


# ---------------------------------------------------------------------------
# stop is safe when not running
# ---------------------------------------------------------------------------


class TestStopSafety(unittest.TestCase):
    def test_stop_on_never_started_scheduler_does_not_raise(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
        )
        # Important: APScheduler raises ``SchedulerNotRunningError`` on
        # ``shutdown()`` when in the stopped state — the wrapper must
        # guard against that.
        scheduler_module.stop_auto_backfill_scheduler(sched)
        self.assertFalse(sched.running)

    def test_stop_idempotent_after_start_then_stop(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
        )
        scheduler_module.start_auto_backfill_scheduler(sched)
        try:
            self.assertTrue(sched.running)
            scheduler_module.stop_auto_backfill_scheduler(sched)
            self.assertFalse(sched.running)
            # Calling stop again must not raise.
            scheduler_module.stop_auto_backfill_scheduler(sched)
        finally:
            # Belt-and-braces — if any assertion above fails mid-test,
            # ensure the executor thread is shut down.
            if sched.running:
                sched.shutdown(wait=False)

    def test_start_is_idempotent(self) -> None:
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
        )
        try:
            scheduler_module.start_auto_backfill_scheduler(sched)
            self.assertTrue(sched.running)
            # Second start must not raise.
            scheduler_module.start_auto_backfill_scheduler(sched)
            self.assertTrue(sched.running)
        finally:
            scheduler_module.stop_auto_backfill_scheduler(sched)


# ---------------------------------------------------------------------------
# candidate_loader and runner seams patched
# ---------------------------------------------------------------------------


class TestSeamsPatched(unittest.TestCase):
    """Verify the job function dispatches to the injected
    ``candidate_loader`` and ``runner``.  No APScheduler thread is
    started; the job's underlying callable is invoked directly so the
    test isolates the scheduler's wiring from APScheduler internals.
    """

    def test_candidate_loader_invoked_when_job_runs(self) -> None:
        loader = MagicMock(return_value=[
            {"headline": "Cluster A", "rank_score": 1.0},
        ])
        state = AutoBackfillState(ttl_seconds=600)
        runner = MagicMock(return_value=_make_run_result(state))

        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            candidate_loader=loader,
            runner=runner,
            state=state,
        )
        job = sched.get_jobs()[0]
        # Drive the job synchronously; APScheduler stores the closure
        # on ``job.func``.
        job.func()
        loader.assert_called_once()

    def test_runner_invoked_with_candidates_config_state_ledger(self) -> None:
        cfg = _config(enabled=True, paid=True)
        candidates = [
            {"headline": "Cluster A", "rank_score": 1.0},
            {"headline": "Cluster B", "rank_score": 0.5},
        ]
        loader = MagicMock(return_value=candidates)
        state = AutoBackfillState(ttl_seconds=600)
        runner = MagicMock(return_value=_make_run_result(state))

        sched = scheduler_module.create_auto_backfill_scheduler(
            config=cfg,
            candidate_loader=loader,
            runner=runner,
            state=state,
        )
        sched.get_jobs()[0].func()
        runner.assert_called_once()
        kwargs = runner.call_args.kwargs
        self.assertEqual(list(kwargs["candidates"]), candidates)
        self.assertIs(kwargs["state"], state)
        # Ledger is constructed by the factory; pin its daily_cap
        # against the config so a future change to the seam is loud.
        self.assertEqual(kwargs["ledger"].daily_cap, cfg.max_calls_per_day)
        # Config passed to the runner should reflect the per-tick load
        # (the closure pulls a fresh config snapshot via
        # ``config_loader``); we passed ``config=`` directly so the
        # default ``load_auto_backfill_config`` is used as the loader.
        self.assertEqual(
            kwargs["config"].effective_status, "configured",
        )

    def test_loader_exception_does_not_crash_executor(self) -> None:
        # The job-level wrapper must catch a loader exception so a
        # transient news-cache failure does NOT kill APScheduler's
        # executor thread.
        loader = MagicMock(side_effect=RuntimeError("boom"))
        state = AutoBackfillState(ttl_seconds=600)
        runner = MagicMock(return_value=_make_run_result(state))

        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            candidate_loader=loader,
            runner=runner,
            state=state,
        )
        # Should not raise.
        sched.get_jobs()[0].func()
        runner.assert_not_called()

    def test_runner_exception_does_not_crash_executor(self) -> None:
        loader = MagicMock(return_value=[])
        runner = MagicMock(side_effect=RuntimeError("runner boom"))
        state = AutoBackfillState(ttl_seconds=600)

        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            candidate_loader=loader,
            runner=runner,
            state=state,
        )
        # Should not raise.
        sched.get_jobs()[0].func()
        runner.assert_called_once()

    def test_default_candidate_loader_returns_empty_list(self) -> None:
        # The skeleton's default loader is the no-op ``[]``: the
        # wiring layer is responsible for injecting the real
        # cached-news → candidate-queue loader.  Test by invoking the
        # job without overriding the loader and asserting the runner
        # sees zero candidates.
        state = AutoBackfillState(ttl_seconds=600)
        runner = MagicMock(return_value=_make_run_result(state))
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            runner=runner,
            state=state,
        )
        sched.get_jobs()[0].func()
        kwargs = runner.call_args.kwargs
        self.assertEqual(list(kwargs["candidates"]), [])


# ---------------------------------------------------------------------------
# Engine injection — tests can substitute the BackgroundScheduler entirely
# ---------------------------------------------------------------------------


class TestEngineInjection(unittest.TestCase):
    def test_caller_can_inject_a_scheduler_engine(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler
        custom = BackgroundScheduler(timezone="UTC")
        sched = scheduler_module.create_auto_backfill_scheduler(
            config=_config(enabled=True, paid=True),
            scheduler=custom,
        )
        self.assertIs(sched, custom)
        self.assertEqual(len(sched.get_jobs()), 1)


if __name__ == "__main__":
    unittest.main()
