"""Real-lifespan wiring tests for the auto-backfill scheduler.

Drives the actual ``api.app`` lifespan via ``TestClient`` as a context
manager (``TestClient(app)`` alone does NOT run the lifespan; only the
``with`` form does).  Each test patches the
``auto_backfill_scheduler`` create/start/stop seams with mocks so no
APScheduler executor thread is ever spawned in the test process.

Companion file: ``tests/test_auto_backfill_lifespan_plan.py`` — the
pre-wiring contract spec.  This file is the AUTHORITATIVE wiring test
suite for the implementation in ``api.py``; the plan file remains the
contract spec.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


_GATE_ENV: tuple[str, ...] = (
    "ENABLE_AUTO_BACKFILL",
    "ENABLE_PAID_ANALYSIS",
)


# ---------------------------------------------------------------------------
# Shared base — patches the seams + cleans app.state between tests
# ---------------------------------------------------------------------------


class _LifespanWiringBase(unittest.TestCase):
    """Base class for real-lifespan wiring tests.

    Every subclass test gets:
      * Both gate env vars stripped (snapshot-and-restore in tearDown).
      * Fresh ``MagicMock`` patches for ``auto_backfill_scheduler``'s
        ``create`` / ``start`` / ``stop`` seams so no APScheduler
        thread can spawn even if the gates are flipped on.
      * Aggressive ``app.state.auto_backfill_scheduler`` cleanup —
        any leftover from a previous test (or a test that bypassed
        the patches) is removed before and after.
    """

    def setUp(self) -> None:
        self._env_backup = {n: os.environ.pop(n, None) for n in _GATE_ENV}
        self._clear_app_state_scheduler()

        self._fake_scheduler = MagicMock()
        self._fake_scheduler.running = False

        self._create_patcher = patch(
            "auto_backfill_scheduler.create_auto_backfill_scheduler",
            return_value=self._fake_scheduler,
        )
        self._start_patcher = patch(
            "auto_backfill_scheduler.start_auto_backfill_scheduler",
        )
        self._stop_patcher = patch(
            "auto_backfill_scheduler.stop_auto_backfill_scheduler",
        )
        self.create_mock = self._create_patcher.start()
        self.start_mock  = self._start_patcher.start()
        self.stop_mock   = self._stop_patcher.start()

    def tearDown(self) -> None:
        self._create_patcher.stop()
        self._start_patcher.stop()
        self._stop_patcher.stop()

        # Defensive: if any test bypassed the mocks and a real
        # BackgroundScheduler landed in app.state, shut it down so
        # the executor thread does not leak across tests.
        leftover = getattr(api.app.state, "auto_backfill_scheduler", None)
        if leftover is not None:
            try:
                running = bool(getattr(leftover, "running", False))
                if running:
                    leftover.shutdown(wait=False)
            except Exception:
                pass
        self._clear_app_state_scheduler()

        for name, value in self._env_backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    @staticmethod
    def _clear_app_state_scheduler() -> None:
        # Starlette's ``State.__delattr__`` raises ``KeyError`` on a
        # missing key, not ``AttributeError``; guard both so this stays
        # a true no-op when no scheduler was published.
        try:
            delattr(api.app.state, "auto_backfill_scheduler")
        except (AttributeError, KeyError):
            pass


# ---------------------------------------------------------------------------
# Disabled / paid-guard-blocked → no scheduler, app starts normally
# ---------------------------------------------------------------------------


class TestLifespanWiringDisabled(_LifespanWiringBase):
    """Default env (no gate set) → no scheduler is created; the existing
    lifespan startup behaviour is preserved (the app responds to
    ``/health``).
    """

    def test_default_env_does_not_create_scheduler(self) -> None:
        with TestClient(api.app) as client:
            r = client.get("/health")
            self.assertEqual(r.status_code, 200)
        self.create_mock.assert_not_called()
        self.start_mock.assert_not_called()
        self.stop_mock.assert_not_called()
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
        )

    def test_existing_lifespan_startup_preserved_under_disabled(self) -> None:
        # ``init_db`` + the optional snapshot/revisit gates already ran
        # in the existing lifespan.  Adding the auto-backfill helper
        # must not regress them — ``/health`` 200 inside the
        # ``with`` block proves the lifespan completed startup.
        with TestClient(api.app) as client:
            r = client.get("/health")
        self.assertEqual(r.status_code, 200)


class TestLifespanWiringPaidGuardBlocked(_LifespanWiringBase):
    """``ENABLE_AUTO_BACKFILL=true`` with ``ENABLE_PAID_ANALYSIS`` unset
    or false → no scheduler; warning logged.
    """

    def test_auto_backfill_only_does_not_create_scheduler(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        # ENABLE_PAID_ANALYSIS deliberately not set.
        with TestClient(api.app):
            pass
        self.create_mock.assert_not_called()
        self.start_mock.assert_not_called()
        self.stop_mock.assert_not_called()

    def test_paid_explicitly_false_does_not_create_scheduler(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "false"
        with TestClient(api.app):
            pass
        self.create_mock.assert_not_called()

    def test_paid_guard_emits_warning(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        with self.assertLogs("second_order.api", level="WARNING") as cm:
            with TestClient(api.app):
                pass
        joined = " ".join(cm.output)
        self.assertIn("ENABLE_PAID_ANALYSIS",       joined)
        self.assertIn("not scheduling",             joined)


# ---------------------------------------------------------------------------
# Both gates true → scheduler created and started; stopped on shutdown
# ---------------------------------------------------------------------------


class TestLifespanWiringBothGatesTrue(_LifespanWiringBase):
    def setUp(self) -> None:
        super().setUp()
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def test_both_gates_call_create_and_start_once(self) -> None:
        with TestClient(api.app) as client:
            r = client.get("/health")
            self.assertEqual(r.status_code, 200)
            self.assertIs(
                api.app.state.auto_backfill_scheduler,
                self._fake_scheduler,
            )
        self.create_mock.assert_called_once()
        self.start_mock.assert_called_once_with(self._fake_scheduler)

    def test_factory_receives_resolved_configured_config(self) -> None:
        with TestClient(api.app):
            pass
        self.create_mock.assert_called_once()
        # The lifespan helper passes ``config=`` keyword.  Verify the
        # ``effective_status`` is resolved before the factory sees it.
        kwargs = self.create_mock.call_args.kwargs
        cfg = kwargs.get("config")
        self.assertIsNotNone(cfg, "factory must receive config= kwarg")
        self.assertEqual(cfg.effective_status, "configured")
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.paid_analysis_enabled)

    def test_shutdown_calls_stop_when_scheduler_was_started(self) -> None:
        with TestClient(api.app):
            pass
        self.stop_mock.assert_called_once_with(self._fake_scheduler)

    def test_shutdown_drops_app_state_attribute(self) -> None:
        # The helper drops the attribute after stop so a follow-on
        # lifespan boot starts from a clean slate.
        with TestClient(api.app):
            pass
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
        )


# ---------------------------------------------------------------------------
# Boot-failure isolation — app still starts, no partial scheduler
# ---------------------------------------------------------------------------


class TestLifespanWiringBootFailureSwallowed(_LifespanWiringBase):
    """A factory raise, a start raise, or a config-load raise must not
    crash the app — the lifespan logs a warning and continues.  The
    ``app.state`` attribute must NOT be set on any failure path.
    """

    def setUp(self) -> None:
        super().setUp()
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"

    def test_factory_raise_does_not_propagate(self) -> None:
        self.create_mock.side_effect = RuntimeError("factory blew up")
        # The lifespan must complete; the app must respond to /health.
        with self.assertLogs("second_order.api", level="WARNING"):
            with TestClient(api.app) as client:
                r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
            "factory raise must not publish a partial scheduler",
        )
        # stop is never called — there is nothing to stop.
        self.stop_mock.assert_not_called()

    def test_start_raise_does_not_propagate_or_publish_partial(self) -> None:
        self.start_mock.side_effect = RuntimeError("start blew up")
        with self.assertLogs("second_order.api", level="WARNING"):
            with TestClient(api.app) as client:
                r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        # Pre-start ordering rule: a start failure must NOT publish a
        # half-started scheduler to ``app.state``.  This is the
        # invariant that lets the shutdown path stay simple.
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
            "start raise must not publish a half-started scheduler",
        )
        self.stop_mock.assert_not_called()

    def test_config_load_raise_does_not_propagate(self) -> None:
        with patch(
            "auto_backfill_config.load_auto_backfill_config",
            side_effect=RuntimeError("config exploded"),
        ):
            with self.assertLogs("second_order.api", level="WARNING"):
                with TestClient(api.app) as client:
                    r = client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.create_mock.assert_not_called()
        self.assertIsNone(
            getattr(api.app.state, "auto_backfill_scheduler", None),
        )

    def test_stop_raise_does_not_propagate_through_shutdown(self) -> None:
        # Boot succeeds; shutdown stop raises.  The app must still
        # exit the ``with`` block cleanly.
        self.stop_mock.side_effect = RuntimeError("stop blew up")
        with self.assertLogs("second_order.api", level="WARNING"):
            try:
                with TestClient(api.app) as client:
                    self.assertEqual(client.get("/health").status_code, 200)
            except RuntimeError:
                self.fail(
                    "shutdown must swallow stop() exceptions; a buggy "
                    "stop must not crash the FastAPI shutdown path",
                )
        self.stop_mock.assert_called_once()


# ---------------------------------------------------------------------------
# GET / page-load endpoints must not create a scheduler
# ---------------------------------------------------------------------------


class TestLifespanWiringNoSchedulerFromRequests(_LifespanWiringBase):
    """The scheduler must only be constructed in the lifespan startup
    half — never as a side effect of an HTTP request handler.  With
    the gates off, no number of GET hits should trip the create seam.
    """

    def test_get_endpoints_do_not_create_scheduler_when_disabled(
        self,
    ) -> None:
        # Default env: gates off.  Multiple GET hits across diagnostics
        # surface area must never call the create seam.
        with TestClient(api.app) as client:
            for path in (
                "/health",
                "/diagnostics/auto-backfill-config",
                "/diagnostics/auto-backfill-status",
                "/diagnostics/data-quality",
            ):
                r = client.get(path)
                self.assertEqual(
                    r.status_code, 200,
                    f"endpoint {path} returned {r.status_code}",
                )
        self.create_mock.assert_not_called()
        self.start_mock.assert_not_called()

    def test_get_endpoints_do_not_recreate_scheduler_when_configured(
        self,
    ) -> None:
        # Gates on: the lifespan creates the scheduler exactly once.
        # Subsequent GET hits must NOT increment the create count —
        # that would mean a request handler is constructing schedulers,
        # a concrete regression on the "no GET creates scheduler" rule.
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        with TestClient(api.app) as client:
            self.assertEqual(self.create_mock.call_count, 1)
            for _ in range(5):
                client.get("/health")
                client.get("/diagnostics/auto-backfill-status")
            self.assertEqual(
                self.create_mock.call_count, 1,
                "GET requests must not trigger scheduler creation",
            )
            self.assertEqual(self.start_mock.call_count, 1)


# ---------------------------------------------------------------------------
# Sanity: real-thread safety — without our mocks, boot would have spawned
# a real APScheduler thread.  Verify the patches are taking effect.
# ---------------------------------------------------------------------------


class TestLifespanWiringPatchEffective(_LifespanWiringBase):
    """Defensive: assert the patches actually intercept the seams the
    lifespan calls.  If a future refactor changes the import path, this
    test catches it before a real BackgroundScheduler gets started in
    the test process.
    """

    def test_patches_take_effect_on_create_seam(self) -> None:
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        with TestClient(api.app):
            pass
        # If the lifespan reached the real create function, we'd see a
        # real BackgroundScheduler attached.  Mocks return our fake.
        self.create_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Diagnostics endpoint reflects the attached scheduler
# ---------------------------------------------------------------------------


class TestLifespanWiringStatusEndpointReflectsScheduler(_LifespanWiringBase):
    """Once the lifespan publishes a scheduler to ``app.state``, the
    ``/diagnostics/auto-backfill-status`` endpoint must surface
    ``mode="dry_run_only"`` and the live ``running`` / ``get_jobs()``
    accessors of that scheduler.  Uses the fake scheduler set up by
    ``_LifespanWiringBase`` — no APScheduler thread is spawned.
    """

    def setUp(self) -> None:
        super().setUp()
        os.environ["ENABLE_AUTO_BACKFILL"] = "true"
        os.environ["ENABLE_PAID_ANALYSIS"] = "true"
        # Configure the fake to look like a started scheduler with one
        # registered job.  ``_LifespanWiringBase`` already returns this
        # fake from ``create_auto_backfill_scheduler``; the lifespan
        # then calls our patched ``start_auto_backfill_scheduler``,
        # which is a no-op MagicMock — so we drive ``running`` ourselves
        # to mirror the post-start state.
        self._fake_scheduler.running = True
        self._fake_scheduler.get_jobs.return_value = [object()]

    def test_status_endpoint_reports_dry_run_only_when_scheduler_attached(
        self,
    ) -> None:
        with TestClient(api.app) as client:
            body = client.get("/diagnostics/auto-backfill-status").json()
        block = body["scheduler"]
        self.assertEqual(block["mode"], "dry_run_only")
        self.assertIs(block["scheduler_started"], True)
        self.assertEqual(block["job_count"], 1)
        # Effective status reflects the env gates.
        self.assertEqual(body["effective_status"], "configured")

    def test_status_endpoint_reports_not_wired_after_shutdown(self) -> None:
        # Inside the ``with`` block the scheduler is attached; after
        # shutdown the lifespan helper drops the attribute, so the
        # endpoint returns to the not-wired state.
        with TestClient(api.app) as client:
            inside = client.get("/diagnostics/auto-backfill-status").json()
        # Re-open a fresh client over the same app — this time without
        # the gates so the lifespan does not attach a scheduler.
        os.environ.pop("ENABLE_AUTO_BACKFILL", None)
        os.environ.pop("ENABLE_PAID_ANALYSIS", None)
        with TestClient(api.app) as client:
            outside = client.get("/diagnostics/auto-backfill-status").json()

        self.assertEqual(inside["scheduler"]["mode"], "dry_run_only")
        self.assertEqual(outside["scheduler"]["mode"], "not_wired")
        self.assertIs(outside["scheduler"]["scheduler_started"], False)
        self.assertEqual(outside["scheduler"]["job_count"], 0)


if __name__ == "__main__":
    unittest.main()
