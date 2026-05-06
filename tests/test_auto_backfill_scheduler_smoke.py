"""Tests for ``scripts/auto_backfill_scheduler_smoke.py``.

The smoke script boots the real ``api.app`` lifespan with the auto-
backfill gates flipped on, but it must NOT spawn an APScheduler
executor thread, NOT reach a paid/provider seam, and NOT reserve
against the daily-cap ledger.  These tests pin those guarantees by
running the script's ``main`` entry point and inspecting:

  * the JSON payload structure and ``ok`` flag,
  * that no APScheduler-named thread leaked,
  * that the underlying ``BackgroundScheduler`` constructor was never
    called (defence-in-depth against a future refactor that bypasses
    the patched seams),
  * that ``api.app.state.auto_backfill_scheduler`` is dropped after
    the smoke exits.

Every test runs the smoke in-process; the script handles its own
patching internally via ``_patched_seams`` so tests do not need to
mock the seams themselves.
"""
from __future__ import annotations

import io
import json
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402
from scripts import auto_backfill_scheduler_smoke as smoke  # noqa: E402


_GATE_ENV: tuple[str, ...] = (
    "ENABLE_AUTO_BACKFILL",
    "ENABLE_PAID_ANALYSIS",
)


def _snapshot_apscheduler_threads() -> set[str]:
    return {
        (t.name or "").lower()
        for t in threading.enumerate()
        if "apscheduler" in (t.name or "").lower()
    }


class _SmokeTestBase(unittest.TestCase):
    """Snapshot-and-restore the gate env vars and any leftover
    ``app.state`` scheduler so a flaky prior run does not contaminate
    these tests.
    """

    def setUp(self) -> None:
        self._env_backup = {n: os.environ.pop(n, None) for n in _GATE_ENV}
        smoke._clear_app_state_scheduler(api.app)

    def tearDown(self) -> None:
        leftover = getattr(api.app.state, "auto_backfill_scheduler", None)
        if leftover is not None:
            try:
                if bool(getattr(leftover, "running", False)):
                    leftover.shutdown(wait=False)
            except Exception:
                pass
        smoke._clear_app_state_scheduler(api.app)
        for name, value in self._env_backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ---------------------------------------------------------------------------
# Happy path — main() returns 0 and the JSON payload pins the wired shape
# ---------------------------------------------------------------------------


class TestSmokeMainHappyPath(_SmokeTestBase):
    def test_main_returns_zero_on_success(self) -> None:
        buf = io.StringIO()
        rc = smoke.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())

    def test_json_payload_carries_summary_and_checks(self) -> None:
        buf = io.StringIO()
        smoke.main(argv=["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        self.assertIn("ok",            payload)
        self.assertIn("summary",       payload)
        self.assertIn("checks",        payload)
        self.assertIn("diagnostics",   payload)
        self.assertIn("elapsed_ms",    payload)
        self.assertTrue(payload["ok"])
        self.assertEqual(
            payload["summary"]["failed"], 0,
            msg=json.dumps(payload, indent=2, sort_keys=True, default=str),
        )

    def test_diagnostics_block_reports_dry_run_only_and_started(self) -> None:
        buf = io.StringIO()
        smoke.main(argv=["--json"], out=buf)
        payload = json.loads(buf.getvalue())
        sched = payload["diagnostics"]["scheduler"]
        self.assertEqual(sched["mode"], "dry_run_only")
        self.assertIs(sched["scheduler_started"], True)
        self.assertEqual(sched["job_count"], 1)
        # effective_status must reflect the flipped-on gates.
        self.assertEqual(payload["diagnostics"]["effective_status"], "configured")

    def test_text_output_contains_summary_line(self) -> None:
        buf = io.StringIO()
        rc = smoke.main(argv=[], out=buf)
        self.assertEqual(rc, 0)
        text = buf.getvalue()
        self.assertIn("Summary:", text)
        self.assertIn("PASS", text)


# ---------------------------------------------------------------------------
# No-real-thread / no-paid-cap-reservation guarantees
# ---------------------------------------------------------------------------


class TestSmokeNoRealScheduler(_SmokeTestBase):
    def test_no_apscheduler_thread_leaked(self) -> None:
        before = _snapshot_apscheduler_threads()
        smoke.main(argv=["--json"], out=io.StringIO())
        after = _snapshot_apscheduler_threads()
        new = after - before
        self.assertEqual(
            new, set(),
            msg=f"new apscheduler-named threads observed: {new!r}",
        )

    def test_real_background_scheduler_never_constructed(self) -> None:
        # Defence-in-depth: even if the create-seam patch were ever
        # bypassed, this asserts the underlying APScheduler executor
        # constructor itself was never reached during the smoke run.
        with patch(
            "apscheduler.schedulers.background.BackgroundScheduler.__init__",
            side_effect=AssertionError(
                "BackgroundScheduler.__init__ was reached during smoke",
            ),
        ):
            buf = io.StringIO()
            rc = smoke.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())


class TestSmokeNoLedgerReservation(_SmokeTestBase):
    def test_reserve_calls_was_never_invoked(self) -> None:
        # The smoke script patches ``reserve_calls`` with a raiser
        # while the lifespan is alive.  If anything reserved a paid
        # call, the lifespan would have crashed and the smoke would
        # have failed.  Belt-and-braces: assert the diagnostics
        # surface still reports ``ledger.used == 0`` after the run.
        buf = io.StringIO()
        rc = smoke.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 0, msg=buf.getvalue())
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["diagnostics"]["ledger"]["used"], 0)


# ---------------------------------------------------------------------------
# Cleanup — env vars restored, app.state cleared
# ---------------------------------------------------------------------------


class TestSmokeRestoresEnv(_SmokeTestBase):
    def test_gate_env_vars_absent_after_run(self) -> None:
        # Pre-condition: setUp stripped the gate env vars.
        self.assertNotIn("ENABLE_AUTO_BACKFILL", os.environ)
        self.assertNotIn("ENABLE_PAID_ANALYSIS", os.environ)
        smoke.main(argv=["--json"], out=io.StringIO())
        # Post-condition: the smoke script restored the original
        # absence — neither variable should leak into the test
        # process.
        self.assertNotIn("ENABLE_AUTO_BACKFILL", os.environ)
        self.assertNotIn("ENABLE_PAID_ANALYSIS", os.environ)

    def test_pre_existing_env_value_preserved(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "false"
        os.environ["ENABLE_PAID_ANALYSIS"] = "false"
        try:
            smoke.main(argv=["--json"], out=io.StringIO())
            self.assertEqual(os.environ.get("ENABLE_AUTO_BACKFILL"), "false")
            self.assertEqual(os.environ.get("ENABLE_PAID_ANALYSIS"), "false")
        finally:
            os.environ.pop("ENABLE_AUTO_BACKFILL", None)
            os.environ.pop("ENABLE_PAID_ANALYSIS", None)


class TestSmokeClearsAppState(_SmokeTestBase):
    def test_app_state_attribute_dropped_after_run(self) -> None:
        smoke.main(argv=["--json"], out=io.StringIO())
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
        )


# ---------------------------------------------------------------------------
# Failure surface — when a check fails, exit code is non-zero
# ---------------------------------------------------------------------------


class TestSmokeFailsWhenCheckFails(_SmokeTestBase):
    def test_nonzero_exit_when_status_endpoint_disagrees(self) -> None:
        # Force the status endpoint to report not-wired even though
        # the lifespan attached our fake.  The smoke must catch this
        # regression and exit non-zero.
        original = smoke._check_status_endpoint

        def _fake_status_check(client):
            mode, started, body = original(client)
            bad = smoke.CheckResult(
                "status endpoint mode=dry_run_only",
                False,
                "forced failure for test",
            )
            return bad, started, body

        with patch.object(smoke, "_check_status_endpoint", _fake_status_check):
            buf = io.StringIO()
            rc = smoke.main(argv=["--json"], out=buf)
        self.assertEqual(rc, 1)
        payload = json.loads(buf.getvalue())
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["summary"]["failed"], 1)


if __name__ == "__main__":
    unittest.main()
