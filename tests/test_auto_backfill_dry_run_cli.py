"""Tests for ``scripts/auto_backfill_dry_run.py``.

The CLI is a thin composer over the already-built pure pieces — config
loader, ledger, state, planner, runner — plus a single candidate-source
seam.  These tests pin the seam contract: tests never hit the registry
DB, never import ``routes.diagnostics``, never call the LLM, never
touch ``yfinance`` / ``market_check`` / any provider, and never write
to SQLite.  Both seams (``load_candidates`` and ``run_auto_backfill_dry_run``)
are patched per test.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_backfill_config import AutoBackfillConfig  # noqa: E402
from auto_backfill_planner import (                   # noqa: E402
    AutoBackfillPlan,
    SKIP_COUNT_KEYS,
)
from auto_backfill_runner import RunResult            # noqa: E402
from auto_backfill_state import StateSnapshot         # noqa: E402

from scripts import auto_backfill_dry_run as cli      # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — bypass env parsing and the real runner so each test
# can drive its own world without paid seams.
# ---------------------------------------------------------------------------


def _make_config(
    *,
    enabled: bool = True,
    paid: bool = True,
    max_per_run: int = 3,
    max_per_day: int = 12,
    interval_hours: int = 6,
) -> AutoBackfillConfig:
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


def _candidate(
    headline: str,
    *,
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


def _completed_state_snap() -> StateSnapshot:
    return StateSnapshot(
        lock_held=False,
        lock_owner=None,
        lock_acquired_at=None,
        lock_expires_at=None,
        last_run_id="run-fake-1",
        last_started_at="2026-05-05T12:00:00+00:00",
        last_completed_at="2026-05-05T12:00:01+00:00",
        last_skip_reason=None,
        last_error=None,
        last_selected_count=2,
        last_spent_calls=0,
    )


def _skip_state_snap(reason: str) -> StateSnapshot:
    return StateSnapshot(
        lock_held=False,
        lock_owner=None,
        lock_acquired_at=None,
        lock_expires_at=None,
        last_run_id=None,
        last_started_at=None,
        last_completed_at=None,
        last_skip_reason=reason,
        last_error=None,
        last_selected_count=None,
        last_spent_calls=None,
    )


def _skip_result(reason: str) -> RunResult:
    return RunResult(
        run_id=None,
        dry_run=True,
        decision_reason=reason,
        started=False,
        completed=False,
        skip_reason=reason,
        selected_count=0,
        spent_calls=0,
        plan=None,
        state_snapshot_after=_skip_state_snap(reason),
        now="2026-05-05T12:00:00+00:00",
    )


def _completed_result(
    selected: list[dict],
    *,
    max_calls_per_run: int = 3,
    daily_remaining: int = 12,
    skip_counts: dict[str, int] | None = None,
) -> RunResult:
    counts = {key: 0 for key in SKIP_COUNT_KEYS}
    if skip_counts:
        counts.update(skip_counts)
    plan = AutoBackfillPlan(
        selected=tuple(selected),
        skip_counts=counts,
        skip_reasons={},
        max_calls_per_run=max_calls_per_run,
        daily_remaining=daily_remaining,
        effective_call_cap=min(max_calls_per_run, daily_remaining),
        eligible_count=len(selected),
        considered_count=len(selected),
    )
    return RunResult(
        run_id="run-fake-1",
        dry_run=True,
        decision_reason="configured",
        started=True,
        completed=True,
        skip_reason=None,
        selected_count=len(selected),
        spent_calls=0,
        plan=plan,
        state_snapshot_after=_completed_state_snap(),
        now="2026-05-05T12:00:00+00:00",
    )


# ---------------------------------------------------------------------------
# Disabled config — no candidate fetch, no runner reach into routes
# ---------------------------------------------------------------------------


class TestDisabledConfig(unittest.TestCase):
    def test_disabled_does_not_load_candidates(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config(enabled=False)), \
             patch.object(cli, "load_candidates") as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_skip_result("disabled")) as mock_run:
            buf = StringIO()
            rc = cli.main(argv=[], out=buf)

        self.assertEqual(rc, 0)
        mock_load.assert_not_called()
        mock_run.assert_called_once()
        text = buf.getvalue()
        self.assertIn("disabled", text)
        self.assertIn("Effective status: disabled", text)

    def test_disabled_json_output_carries_reason(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config(enabled=False)), \
             patch.object(cli, "load_candidates") as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_skip_result("disabled")):
            buf = StringIO()
            rc = cli.main(argv=["--json"], out=buf)

        self.assertEqual(rc, 0)
        mock_load.assert_not_called()
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["decision_reason"], "disabled")
        self.assertEqual(payload["skip_reason"],     "disabled")
        self.assertEqual(payload["effective_status"], "disabled")
        self.assertEqual(payload["selected_count"],   0)
        self.assertEqual(payload["selected"],         [])


# ---------------------------------------------------------------------------
# Paid-guard blocked — same behaviour as disabled re: not fetching
# ---------------------------------------------------------------------------


class TestPaidGuardBlocked(unittest.TestCase):
    def test_paid_guard_blocked_does_not_load_candidates(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config(paid=False)), \
             patch.object(cli, "load_candidates") as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_skip_result("paid_guard_blocked")):
            buf = StringIO()
            rc = cli.main(argv=["--json"], out=buf)

        self.assertEqual(rc, 0)
        mock_load.assert_not_called()
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["decision_reason"], "paid_guard_blocked")
        self.assertEqual(payload["skip_reason"],     "paid_guard_blocked")
        self.assertEqual(payload["effective_status"], "blocked_paid_guard")


# ---------------------------------------------------------------------------
# Lock-held — config is "go", runner skips after fetching
# ---------------------------------------------------------------------------


class TestLockHeld(unittest.TestCase):
    def test_lock_held_loads_candidates_then_reports_skip(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=[_candidate("X")]) as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_skip_result("lock_held")):
            buf = StringIO()
            rc = cli.main(argv=["--json"], out=buf)

        self.assertEqual(rc, 0)
        mock_load.assert_called_once()
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["decision_reason"], "lock_held")
        self.assertEqual(payload["skip_reason"],     "lock_held")


# ---------------------------------------------------------------------------
# Configured + candidates — selection cap and rendering surfaces
# ---------------------------------------------------------------------------


class TestConfiguredWithCandidates(unittest.TestCase):
    def test_text_output_lists_selected(self) -> None:
        candidates = [
            _candidate(f"News {i}", rank_score=10.0 - i)
            for i in range(3)
        ]
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config(max_per_run=3)), \
             patch.object(cli, "load_candidates",
                          return_value=candidates), \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_completed_result(candidates)):
            buf = StringIO()
            rc = cli.main(argv=[], out=buf)

        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("News 0", text)
        self.assertIn("News 1", text)
        self.assertIn("News 2", text)
        self.assertIn("Selected:   3", text)
        self.assertIn("Effective per-run cap: 3", text)
        self.assertIn("Skip counts:", text)

    def test_json_output_has_expected_keys(self) -> None:
        candidates = [
            _candidate(f"News {i}", rank_score=10.0 - i)
            for i in range(2)
        ]
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=candidates), \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_completed_result(candidates)):
            buf = StringIO()
            rc = cli.main(argv=["--json"], out=buf)

        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        for key in (
            "decision_reason", "skip_reason", "effective_status",
            "effective_per_run_cap", "daily_remaining",
            "considered_count", "eligible_count", "selected_count",
            "selected", "skip_counts", "skip_reasons", "config", "now",
        ):
            self.assertIn(key, payload, f"missing key {key!r}")
        self.assertEqual(payload["selected_count"], 2)
        self.assertEqual(len(payload["selected"]),  2)
        self.assertIsNone(payload["skip_reason"])
        self.assertEqual(payload["effective_per_run_cap"], 3)

    def test_skip_counts_render_when_run_cap_exhausted(self) -> None:
        candidates = [
            _candidate(f"News {i}", rank_score=10.0 - i)
            for i in range(2)
        ]
        result = _completed_result(
            candidates,
            skip_counts={"run_cap_exhausted": 4},
        )
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=candidates), \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=result):
            buf = StringIO()
            rc = cli.main(argv=["--json"], out=buf)

        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["skip_counts"]["run_cap_exhausted"], 4)


# ---------------------------------------------------------------------------
# CLI plumbing — --limit forwarding, runner seam invocation
# ---------------------------------------------------------------------------


class TestLimitForwarded(unittest.TestCase):
    def test_limit_passed_to_load_candidates(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=[]) as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_completed_result([])):
            cli.main(argv=["--limit", "7"], out=StringIO())

        mock_load.assert_called_once()
        kwargs = mock_load.call_args.kwargs
        self.assertEqual(kwargs.get("limit"), 7)


class TestRunnerSeam(unittest.TestCase):
    def test_runner_invoked_once_with_candidate_list(self) -> None:
        candidates = [_candidate("X")]
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=candidates), \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_completed_result(candidates)) as mock_run:
            cli.main(argv=[], out=StringIO())

        mock_run.assert_called_once()
        kwargs = mock_run.call_args.kwargs
        self.assertEqual(list(kwargs["candidates"]), candidates)
        # Runner is invoked with the live config + freshly-built ledger
        # and state — no DB, no scheduler, no paid path.
        self.assertIn("config",  kwargs)
        self.assertIn("state",   kwargs)
        self.assertIn("ledger",  kwargs)


# ---------------------------------------------------------------------------
# Default loader is exposed but never invoked when patched
# ---------------------------------------------------------------------------


class TestDefaultLoaderRespectsPatch(unittest.TestCase):
    """``load_candidates`` is the only path into routes-land.  When tests
    patch it, the default body must never run — otherwise a stray
    ``routes.diagnostics`` import could pull in paid seams.
    """

    def test_module_exposes_load_candidates(self) -> None:
        self.assertTrue(callable(cli.load_candidates))

    def test_patched_loader_is_only_invocation_point(self) -> None:
        with patch.object(cli, "load_auto_backfill_config",
                          return_value=_make_config()), \
             patch.object(cli, "load_candidates",
                          return_value=[]) as mock_load, \
             patch.object(cli, "run_auto_backfill_dry_run",
                          return_value=_completed_result([])):
            cli.main(argv=[], out=StringIO())
        # One call, with the keyword argument the default expects.
        self.assertEqual(mock_load.call_count, 1)


if __name__ == "__main__":
    unittest.main()
