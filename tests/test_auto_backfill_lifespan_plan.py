"""Lifespan-wiring CONTRACT tests for the auto-backfill scheduler.

These tests pin the contract for the FastAPI lifespan wiring that
will eventually live inside ``api.py._lifespan``.  The wiring itself
has NOT been written yet — ``api.py`` is intentionally untouched.

Why these tests exist now
-------------------------
* They fix the lifecycle vocabulary (``disabled`` / ``blocked_paid_guard``
  / ``configured`` / ``boot_failed`` / ``config_load_failed``) so the
  eventual production code reads from the same words the diagnostics
  surface and the runner already use.
* They define the failure-isolation rules (boot exceptions are
  swallowed; shutdown is a no-op when no scheduler was created;
  shutdown swallows stop exceptions too) so the implementer does not
  re-derive them from scratch and accidentally regress.
* They prevent silent drift: when ``api.py`` lifespan wiring lands,
  these tests must be rewritten to drive ``api.app`` directly (via
  ``TestClient`` or by invoking the lifespan context manager).  The
  rewrite is mechanical because every test below names the contract
  bullet it encodes.

Migration notes for the future implementer
------------------------------------------
When the real lifespan wiring lands:

1. Replace ``_AutoBackfillLifespan`` (the harness defined below) with
   the production surface.  Each test should drive the real lifespan,
   not the harness.
2. The decision-reason vocabulary used here ("disabled", "blocked_paid_guard",
   "configured", "started", "boot_failed", "config_load_failed", "no_factory")
   is the contract.  The production code should expose the same words —
   on a structured boot-result, on a log message, or both.
3. Pre-start ordering matters: do NOT publish a partial scheduler to
   ``app.state`` until ``start_auto_backfill_scheduler`` returns
   successfully.  Tests
   ``TestLifespanStartupFailureSwallowed.test_start_raise_does_not_propagate_to_app``
   and ``TestLifespanShutdown.test_shutdown_does_not_call_stop_when_no_scheduler``
   pin this so a partial-init does not leak into the shutdown path.

No I/O — every test below uses mocks/fakes only.  No LLM, no
``yfinance``, no ``market_check``, no provider, no network, no DB
write.  No FastAPI app is constructed; no scheduler is started.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from contextlib import contextmanager
from typing import Any, Callable, Optional
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from auto_backfill_config import (  # noqa: E402
    AutoBackfillConfig, load_auto_backfill_config,
)


# ---------------------------------------------------------------------------
# In-test harness — encodes the contract until ``api.py`` lifespan lands
# ---------------------------------------------------------------------------


# Decision-reason vocabulary.  These strings are the contract: a future
# production lifespan should expose the same words on its boot-result
# (whether via a return value, an attribute on ``app.state``, or a
# structured log line).  Tests below pin every reason at least once.
BOOT_REASON_DISABLED:           str = "disabled"
BOOT_REASON_BLOCKED_PAID_GUARD: str = "blocked_paid_guard"
BOOT_REASON_STARTED:            str = "started"
BOOT_REASON_BOOT_FAILED:        str = "boot_failed"
BOOT_REASON_CONFIG_LOAD_FAILED: str = "config_load_failed"
BOOT_REASON_NO_FACTORY:         str = "no_factory"


class _AutoBackfillLifespan:
    """Self-contained lifespan harness — encodes the FUTURE wiring contract.

    This class is the SPEC.  When ``api.py._lifespan`` is wired up,
    every test in this file should be rewritten to drive the real
    lifespan; the harness is then deleted.

    Behaviour mirrors what the production wiring must do:

    * On boot, load the auto-backfill config.  If the loader raises,
      log + swallow; record ``boot_decision_reason="config_load_failed"``;
      do not create a scheduler.
    * If ``cfg.effective_status != "configured"``, do not create a
      scheduler.  Record the reason verbatim from the config
      (``"disabled"`` or ``"blocked_paid_guard"``).
    * Otherwise, call ``scheduler_factory(cfg)`` to construct a
      scheduler, then ``start(scheduler)``.  Wrap in try/except: any
      exception is swallowed and logged; ``self.scheduler`` stays
      ``None`` and ``boot_decision_reason="boot_failed"``.  This is
      load-bearing — the app must keep serving requests even when the
      scheduler cannot start.
    * On shutdown, call ``stop(self.scheduler)`` ONLY if a scheduler
      was successfully created.  Swallow any exception ``stop`` raises
      so a buggy stop() does not crash the FastAPI shutdown path.

    The harness is intentionally minimal — it carries no APScheduler
    import, no logging side effects beyond the standard library, and
    no global state.  The production lifespan will be at least as
    careful.
    """

    def __init__(
        self,
        *,
        config_loader: Callable[[], AutoBackfillConfig] = load_auto_backfill_config,
        scheduler_factory: Optional[Callable[[AutoBackfillConfig], Any]] = None,
        start: Optional[Callable[[Any], None]] = None,
        stop: Optional[Callable[[Any], None]] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self._config_loader     = config_loader
        self._scheduler_factory = scheduler_factory
        self._start             = start
        self._stop              = stop
        self._log               = logger or logging.getLogger("auto_backfill.lifespan_test_harness")
        self.scheduler:            Optional[Any] = None
        self.boot_decision_reason: Optional[str] = None
        self.warnings:             list[str] = []

    # ----- boot ----------------------------------------------------

    def boot(self) -> None:
        """Run the boot half of the contract.  Always returns; never raises."""
        try:
            cfg = self._config_loader()
        except Exception as exc:
            self._log.warning(
                "auto_backfill: config load failed; app continues",
                exc_info=True,
            )
            self.warnings.append(f"config_load_failed: {exc}")
            self.boot_decision_reason = BOOT_REASON_CONFIG_LOAD_FAILED
            return

        if cfg.effective_status != "configured":
            # ``cfg.effective_status`` is already the contract vocabulary
            # (``"disabled"`` or ``"blocked_paid_guard"``); pass it through
            # verbatim so downstream consumers branch on a single set of
            # strings.
            self.boot_decision_reason = cfg.effective_status
            if cfg.effective_status == BOOT_REASON_BLOCKED_PAID_GUARD:
                self._log.warning(
                    "auto_backfill: ENABLE_AUTO_BACKFILL=true but "
                    "ENABLE_PAID_ANALYSIS=false; not scheduling.",
                )
            return

        if self._scheduler_factory is None:
            # Implementer didn't wire a factory — treat as a soft skip
            # so the app keeps serving requests.  A real lifespan should
            # never hit this branch.
            self.boot_decision_reason = BOOT_REASON_NO_FACTORY
            return

        try:
            scheduler = self._scheduler_factory(cfg)
            if self._start is not None:
                self._start(scheduler)
        except Exception as exc:
            self._log.warning(
                "auto_backfill: scheduler boot failed; app continues",
                exc_info=True,
            )
            self.warnings.append(f"boot_failed: {exc}")
            # Critical: do NOT publish a partial scheduler.  Leaving
            # ``self.scheduler = None`` ensures the shutdown half is a
            # no-op, so a half-started scheduler can never accidentally
            # be ``stop()``-ed.
            self.scheduler = None
            self.boot_decision_reason = BOOT_REASON_BOOT_FAILED
            return

        self.scheduler = scheduler
        self.boot_decision_reason = BOOT_REASON_STARTED

    # ----- shutdown ------------------------------------------------

    def shutdown(self) -> None:
        """Run the shutdown half of the contract.

        Calls ``stop(scheduler)`` only when a scheduler was successfully
        created at boot.  Swallows any exception ``stop`` raises so a
        buggy shutdown does not crash the FastAPI shutdown path.
        """
        if self.scheduler is None:
            return
        if self._stop is None:
            return
        try:
            self._stop(self.scheduler)
        except Exception as exc:
            self._log.warning(
                "auto_backfill: scheduler stop raised; ignoring",
                exc_info=True,
            )
            self.warnings.append(f"stop_raised: {exc}")

    # ----- context manager so tests can use ``with`` syntax --------

    def __enter__(self) -> "_AutoBackfillLifespan":
        self.boot()
        return self

    def __exit__(self, *exc_info) -> None:
        self.shutdown()


# ---------------------------------------------------------------------------
# Test-side env scrubber
# ---------------------------------------------------------------------------


_GATE_ENV: tuple[str, ...] = (
    "ENABLE_AUTO_BACKFILL",
    "ENABLE_PAID_ANALYSIS",
)


@contextmanager
def _scrub_gate_env():
    """Remove the two gate env vars for the duration of the block; restore on exit.

    Other ``AUTO_BACKFILL_*`` env vars (caps / interval / model) are
    intentionally NOT scrubbed — they don't affect ``effective_status``
    and leaving them alone keeps the test's interaction surface
    minimal.
    """
    backup = {name: os.environ.pop(name, None) for name in _GATE_ENV}
    try:
        yield
    finally:
        for name, value in backup.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# ---------------------------------------------------------------------------
# Contract: disabled env → no scheduler created
# ---------------------------------------------------------------------------


class TestLifespanDisabledEnv(unittest.TestCase):
    """Contract bullet: *disabled env → no scheduler created*."""

    def test_default_env_does_not_call_factory(self) -> None:
        factory = MagicMock()
        start   = MagicMock()
        with _scrub_gate_env():
            with _AutoBackfillLifespan(
                scheduler_factory=factory, start=start,
            ) as lifespan:
                pass
        factory.assert_not_called()
        start.assert_not_called()
        self.assertIsNone(lifespan.scheduler)
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_DISABLED)

    def test_explicit_enable_false_does_not_call_factory(self) -> None:
        factory = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "false"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory,
            ) as lifespan:
                pass
        factory.assert_not_called()
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_DISABLED)


# ---------------------------------------------------------------------------
# Contract: paid-guard false → no scheduler created
# ---------------------------------------------------------------------------


class TestLifespanPaidGuardFalse(unittest.TestCase):
    """Contract bullet: *paid guard false → no scheduler created*.

    ``ENABLE_AUTO_BACKFILL=true`` with ``ENABLE_PAID_ANALYSIS`` unset
    (or false) is the design's blocked-paid-guard state.  Boot must
    log a warning explaining the remediation and NOT call the factory.
    """

    def test_paid_unset_does_not_call_factory(self) -> None:
        factory = MagicMock()
        start   = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory, start=start,
            ) as lifespan:
                pass
        factory.assert_not_called()
        start.assert_not_called()
        self.assertEqual(
            lifespan.boot_decision_reason, BOOT_REASON_BLOCKED_PAID_GUARD,
        )

    def test_paid_explicitly_false_does_not_call_factory(self) -> None:
        factory = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "false"
            with _AutoBackfillLifespan(
                scheduler_factory=factory,
            ) as lifespan:
                pass
        factory.assert_not_called()
        self.assertEqual(
            lifespan.boot_decision_reason, BOOT_REASON_BLOCKED_PAID_GUARD,
        )


# ---------------------------------------------------------------------------
# Contract: both gates true → scheduler factory called once
# ---------------------------------------------------------------------------


class TestLifespanBothGatesTrue(unittest.TestCase):
    """Contract bullet: *both gates true → scheduler factory called exactly
    once on boot*.

    A FastAPI lifespan is one boot, one shutdown — the factory must
    therefore be called once across the lifecycle.  Repeated calls
    would imply a per-request scheduler, which is not the contract.
    """

    def test_both_gates_true_calls_factory_exactly_once(self) -> None:
        sched_obj = object()
        factory = MagicMock(return_value=sched_obj)
        start   = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory, start=start,
            ) as lifespan:
                pass
        factory.assert_called_once()
        start.assert_called_once_with(sched_obj)
        self.assertIs(lifespan.scheduler, sched_obj)
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_STARTED)

    def test_factory_receives_resolved_configured_config(self) -> None:
        captured: dict[str, Any] = {}

        def capturing_factory(cfg: AutoBackfillConfig) -> Any:
            captured["cfg"] = cfg
            return MagicMock()

        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=capturing_factory,
            ):
                pass
        cfg = captured.get("cfg")
        self.assertIsNotNone(cfg)
        # Pin the contract: the factory sees a fully-resolved config
        # whose ``effective_status`` is already ``"configured"``.  This
        # lets the production factory short-circuit any "should I run?"
        # check and just construct.
        self.assertEqual(cfg.effective_status, "configured")
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.paid_analysis_enabled)


# ---------------------------------------------------------------------------
# Contract: shutdown calls stop ONLY if a scheduler exists
# ---------------------------------------------------------------------------


class TestLifespanShutdown(unittest.TestCase):
    """Contract bullet: *shutdown calls stop if scheduler exists*.

    Read literally — only if a scheduler was constructed at boot.  A
    boot that skipped the factory (disabled / paid-guard-blocked /
    boot-failed) leaves ``self.scheduler is None``; shutdown must not
    call ``stop`` on ``None`` and must not synthesize a stop call.
    """

    def test_shutdown_calls_stop_when_scheduler_exists(self) -> None:
        sched_obj = object()
        factory = MagicMock(return_value=sched_obj)
        start   = MagicMock()
        stop    = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory, start=start, stop=stop,
            ):
                pass
        stop.assert_called_once_with(sched_obj)

    def test_shutdown_does_not_call_stop_when_disabled_env(self) -> None:
        factory = MagicMock()
        stop    = MagicMock()
        with _scrub_gate_env():
            with _AutoBackfillLifespan(
                scheduler_factory=factory, stop=stop,
            ):
                pass
        stop.assert_not_called()

    def test_shutdown_does_not_call_stop_when_paid_guard_blocks(self) -> None:
        factory = MagicMock()
        stop    = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory, stop=stop,
            ):
                pass
        stop.assert_not_called()

    def test_shutdown_swallows_stop_exceptions(self) -> None:
        sched_obj = object()
        factory = MagicMock(return_value=sched_obj)
        stop    = MagicMock(side_effect=RuntimeError("stop blew up"))
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            try:
                with _AutoBackfillLifespan(
                    scheduler_factory=factory, stop=stop,
                ):
                    pass
            except RuntimeError:
                self.fail(
                    "shutdown must swallow stop() exceptions — a buggy "
                    "stop must not crash the FastAPI shutdown path",
                )
        stop.assert_called_once()


# ---------------------------------------------------------------------------
# Contract: startup failure swallowed/logged; app still starts
# ---------------------------------------------------------------------------


class TestLifespanStartupFailureSwallowed(unittest.TestCase):
    """Contract bullet: *startup failure is swallowed/logged, app still starts*.

    Three failure surfaces share the same swallow-and-continue
    contract:
      1. ``config_loader`` raises (env malformed, import broken).
      2. ``scheduler_factory`` raises (APScheduler import broken).
      3. ``start`` raises (thread spawn fails, OS limits hit).

    All three must result in ``self.scheduler is None`` so the
    shutdown half cannot accidentally stop a half-built scheduler.
    """

    def test_factory_raise_does_not_propagate_to_app(self) -> None:
        factory = MagicMock(side_effect=RuntimeError("factory blew up"))
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            try:
                with _AutoBackfillLifespan(
                    scheduler_factory=factory,
                ) as lifespan:
                    pass
            except RuntimeError:
                self.fail("lifespan must swallow factory exceptions")
        self.assertIsNone(lifespan.scheduler)
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_BOOT_FAILED)

    def test_start_raise_does_not_propagate_to_app(self) -> None:
        # Critical pre-start ordering rule: when ``start`` raises, the
        # scheduler must NOT be published to ``self.scheduler``.  A
        # half-built scheduler in ``app.state`` would invite the
        # shutdown path to call ``stop`` on a never-started object.
        factory = MagicMock(return_value=object())
        start   = MagicMock(side_effect=RuntimeError("start blew up"))
        stop    = MagicMock()
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            try:
                with _AutoBackfillLifespan(
                    scheduler_factory=factory, start=start, stop=stop,
                ) as lifespan:
                    pass
            except RuntimeError:
                self.fail("lifespan must swallow start exceptions")
        self.assertIsNone(lifespan.scheduler)
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_BOOT_FAILED)
        # Pre-start ordering: stop is NEVER called when start failed —
        # a half-started scheduler must not be touched on the way out.
        stop.assert_not_called()

    def test_config_load_failure_swallowed_no_factory_call(self) -> None:
        factory = MagicMock()
        bad_loader = MagicMock(
            side_effect=RuntimeError("config exploded"),
        )
        with _scrub_gate_env():
            try:
                with _AutoBackfillLifespan(
                    config_loader=bad_loader,
                    scheduler_factory=factory,
                ) as lifespan:
                    pass
            except RuntimeError:
                self.fail("lifespan must swallow config-load exceptions")
        factory.assert_not_called()
        self.assertEqual(
            lifespan.boot_decision_reason, BOOT_REASON_CONFIG_LOAD_FAILED,
        )

    def test_warning_recorded_on_boot_failure(self) -> None:
        # Operators rely on the log/warning trail to debug a failed
        # scheduler boot.  Encode the contract: the harness records
        # at least one warning when boot fails, and the warning text
        # references the failure surface.
        factory = MagicMock(side_effect=RuntimeError("factory blew up"))
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan(
                scheduler_factory=factory,
            ) as lifespan:
                pass
        self.assertTrue(
            any("boot_failed" in w for w in lifespan.warnings),
            f"expected a boot_failed warning, got {lifespan.warnings!r}",
        )


# ---------------------------------------------------------------------------
# Contract: factory missing → soft skip (defensive)
# ---------------------------------------------------------------------------


class TestLifespanNoFactoryWired(unittest.TestCase):
    """Defensive contract: when both gates are true but no factory was
    wired, the lifespan must NOT crash the app.  A real lifespan should
    never hit this branch; it exists so an in-progress refactor that
    forgets to wire the factory degrades gracefully.
    """

    def test_no_factory_with_configured_env_does_not_raise(self) -> None:
        with _scrub_gate_env():
            os.environ["ENABLE_AUTO_BACKFILL"] = "true"
            os.environ["ENABLE_PAID_ANALYSIS"] = "true"
            with _AutoBackfillLifespan() as lifespan:
                pass
        self.assertIsNone(lifespan.scheduler)
        self.assertEqual(lifespan.boot_decision_reason, BOOT_REASON_NO_FACTORY)


# ---------------------------------------------------------------------------
# Sanity: the harness IS the spec — confirm it has not drifted from
# the contract vocabulary the rest of the auto-backfill subsystem uses
# ---------------------------------------------------------------------------


class TestContractVocabularyAlignment(unittest.TestCase):
    """The boot-decision vocabulary must align with the runner's and
    the diagnostics endpoint's vocabulary so a future implementer who
    grep-searches for these strings finds one consistent contract.
    """

    def test_disabled_and_blocked_paid_guard_match_config_module(self) -> None:
        from auto_backfill_config import (
            EFFECTIVE_BLOCKED_PAID_GUARD, EFFECTIVE_DISABLED,
        )
        self.assertEqual(BOOT_REASON_DISABLED,           EFFECTIVE_DISABLED)
        self.assertEqual(
            BOOT_REASON_BLOCKED_PAID_GUARD, EFFECTIVE_BLOCKED_PAID_GUARD,
        )


if __name__ == "__main__":
    unittest.main()
