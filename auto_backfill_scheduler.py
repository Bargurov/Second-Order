"""Disabled-by-default APScheduler dry-run integration skeleton.

This module wraps :func:`auto_backfill_runner.run_auto_backfill_dry_run`
on a ``BackgroundScheduler`` interval.  It is **dry-run only** — no
paid execution, no provider/network/SQLite write, no LLM call.
Importing this module never starts a scheduler thread; the caller
must explicitly invoke :func:`start_auto_backfill_scheduler` for the
job to begin firing.

Out of scope for this skeleton
------------------------------
* **No FastAPI lifespan wiring.**  ``api.py`` is deliberately
  untouched.  A future patch will add a ``_lifespan`` startup hook
  that constructs and starts this scheduler under the same boot
  decision tree the design doc pins.
* **No paid execution path.**  The runner is dry-run by contract; the
  scheduler composes that runner unchanged.  ``execute_paid_candidate``
  is never invoked.
* **No built-in candidate construction.**  The job function pulls
  candidates through an injected ``candidate_loader`` seam.  The
  default loader returns an empty list so the module has zero
  dependency on ``routes.movers`` / the news cache; the wiring layer
  will inject the cached-news → candidate-queue loader when it lands.

See ``docs/auto_backfill_scheduler_design.md`` §1 (scope) and §7
(failure isolation) for the wider contract this skeleton evolves into.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from auto_backfill_config import AutoBackfillConfig, load_auto_backfill_config
from auto_backfill_ledger import AutoBackfillLedger
from auto_backfill_runner import RunResult, run_auto_backfill_dry_run
from auto_backfill_state import AutoBackfillState


_log = logging.getLogger(__name__)


JOB_ID: str = "auto_backfill_dry_run_tick"
JOB_NAME: str = "auto_backfill_dry_run_tick"

# Misfire policy — design doc §7.4.  ``coalesce=True`` collapses any
# queued ticks (e.g. after a laptop sleep) into a single tick;
# ``misfire_grace_time`` drops anything older than 10 minutes rather
# than chasing stale ticks.  ``max_instances=1`` is belt-and-braces
# against overlap; the runner's lock would catch it anyway.
DEFAULT_MISFIRE_GRACE_SECONDS: int = 600
DEFAULT_MAX_INSTANCES: int = 1
DEFAULT_COALESCE: bool = True

# State TTL covers a generous lock hold; the dry-run runner releases
# the lock at the end of each tick anyway.  Mirrors the diagnostics
# route's long-lived state TTL so an operator's ``/auto-backfill-status``
# view shows a comparable stale-lock window.
DEFAULT_STATE_TTL_SECONDS: int = 3600


CandidateLoader = Callable[[], Iterable[Mapping[str, Any]]]
DryRunCallable  = Callable[..., RunResult]
ConfigLoader    = Callable[[], AutoBackfillConfig]
LedgerFactory   = Callable[[int], AutoBackfillLedger]


def _empty_candidate_loader() -> list[dict]:
    """Default candidate loader.  Returns an empty list.

    Concrete loaders (cached-news → candidate-queue items) are
    injected by the wiring layer; this skeleton has no
    ``routes.movers`` / news-cache dependency on purpose.  An empty
    loader makes a dry-run tick observable (the runner completes with
    ``selected_count=0``) without pulling in any production helper.
    """
    return []


def _make_job_function(
    *,
    config_loader: ConfigLoader,
    candidate_loader: CandidateLoader,
    runner: DryRunCallable,
    state: AutoBackfillState,
    ledger_factory: LedgerFactory,
) -> Callable[[], None]:
    """Build the closure APScheduler invokes at each tick.

    The closure pulls a fresh config snapshot per tick (so an env
    edit is observable on the next tick without restarting the
    process), rebuilds the ledger when the daily cap changes, and
    dispatches one dry-run tick.  Per-tick exceptions are caught and
    logged so a structural failure does NOT crash APScheduler's
    executor thread.

    The state and ledger are persistent across ticks so the runner
    sees the real lock + last-completed timestamps it gates on.
    """
    cache: dict[str, Any] = {"ledger": None, "cap": None}

    def _tick() -> None:
        try:
            cfg = config_loader()
            cap = cfg.max_calls_per_day
            if cache["ledger"] is None or cache["cap"] != cap:
                cache["ledger"] = ledger_factory(cap)
                cache["cap"] = cap
            ledger = cache["ledger"]

            candidates = list(candidate_loader())
            result = runner(
                candidates=candidates,
                config=cfg,
                state=state,
                ledger=ledger,
            )
            _log.info(
                "auto_backfill_scheduler: tick run_id=%s decision=%s "
                "selected=%s skip_reason=%s",
                getattr(result, "run_id", None),
                getattr(result, "decision_reason", None),
                getattr(result, "selected_count", None),
                getattr(result, "skip_reason", None),
            )
        except Exception:
            _log.exception("auto_backfill_scheduler: tick failed")

    return _tick


def create_auto_backfill_scheduler(
    *,
    config: Optional[AutoBackfillConfig] = None,
    config_loader: Optional[ConfigLoader] = None,
    candidate_loader: Optional[CandidateLoader] = None,
    runner: Optional[DryRunCallable] = None,
    scheduler: Optional[BackgroundScheduler] = None,
    state: Optional[AutoBackfillState] = None,
    ledger_factory: Optional[LedgerFactory] = None,
    coalesce: bool = DEFAULT_COALESCE,
    max_instances: int = DEFAULT_MAX_INSTANCES,
    misfire_grace_seconds: int = DEFAULT_MISFIRE_GRACE_SECONDS,
    state_ttl_seconds: int = DEFAULT_STATE_TTL_SECONDS,
) -> BackgroundScheduler:
    """Build and configure a ``BackgroundScheduler`` for the dry-run job.

    The job is added ONLY when the resolved config has
    ``effective_status == "configured"`` (both ``ENABLE_AUTO_BACKFILL``
    and ``ENABLE_PAID_ANALYSIS`` are true).  Disabled and
    ``blocked_paid_guard`` configs return a scheduler with no job —
    even though this skeleton is dry-run, scheduling work under a
    paid-guard-blocked config would diverge from the design doc's
    "scheduler doesn't start unless both gates green" contract.

    The returned scheduler is **not started**; the caller must call
    :func:`start_auto_backfill_scheduler` to begin firing.

    Every dependency is injectable so tests can substitute the
    runner, candidate loader, scheduler engine, state, and ledger
    factory.
    """
    # ``config_loader`` and ``config`` form a snapshot/loader pair:
    #   * ``config_loader`` (callable) — re-evaluated every tick so an
    #     env edit is observable without restarting the process.
    #   * ``config`` (snapshot) — pinned for the lifetime of this
    #     scheduler.  Useful for tests and for callers that want a
    #     stable per-process config.
    # Passing ``config_loader`` wins; otherwise a static ``config``
    # becomes the (frozen) loader; otherwise the env-driven default.
    if config_loader is not None:
        cfg_loader: ConfigLoader = config_loader
    elif config is not None:
        cfg_loader = (lambda c=config: c)
    else:
        cfg_loader = load_auto_backfill_config
    cfg = cfg_loader()
    cands = candidate_loader or _empty_candidate_loader
    runner_fn = runner or run_auto_backfill_dry_run
    sched = scheduler if scheduler is not None else BackgroundScheduler()
    st = state if state is not None else AutoBackfillState(
        ttl_seconds=state_ttl_seconds,
    )
    ledger_fac = ledger_factory or (
        lambda cap: AutoBackfillLedger(daily_cap=cap)
    )

    if cfg.effective_status != "configured":
        # Disabled or paid-guard-blocked — return the scheduler with
        # no job attached.  Caller may still ``start_auto_backfill_scheduler``
        # safely; the loop will tick nothing.
        return sched

    interval_seconds = max(int(cfg.interval_hours), 1) * 3600
    job_fn = _make_job_function(
        config_loader=cfg_loader,
        candidate_loader=cands,
        runner=runner_fn,
        state=st,
        ledger_factory=ledger_fac,
    )
    sched.add_job(
        job_fn,
        trigger=IntervalTrigger(seconds=interval_seconds),
        id=JOB_ID,
        name=JOB_NAME,
        coalesce=coalesce,
        max_instances=max_instances,
        misfire_grace_time=misfire_grace_seconds,
        replace_existing=True,
    )
    return sched


def start_auto_backfill_scheduler(scheduler: BackgroundScheduler) -> None:
    """Start the scheduler if it is not already running.  Idempotent.

    Constructing a :class:`BackgroundScheduler` does not spawn the
    executor thread; this function is the single explicit entry
    point that does.  An already-running scheduler is left alone so
    a defensive caller (e.g. lifespan retry) is safe.
    """
    if not scheduler.running:
        scheduler.start()


def stop_auto_backfill_scheduler(scheduler: BackgroundScheduler) -> None:
    """Stop the scheduler if it is running.

    Safe to call on a never-started scheduler — APScheduler's
    ``shutdown()`` raises ``SchedulerNotRunningError`` from the stopped
    state, so the ``running`` guard suppresses that path.  ``wait=False``
    avoids blocking the caller on an in-flight tick; the dry-run job
    is bounded so any in-flight tick completes promptly.
    """
    if scheduler.running:
        scheduler.shutdown(wait=False)


__all__ = [
    "DEFAULT_COALESCE",
    "DEFAULT_MAX_INSTANCES",
    "DEFAULT_MISFIRE_GRACE_SECONDS",
    "DEFAULT_STATE_TTL_SECONDS",
    "JOB_ID",
    "JOB_NAME",
    "create_auto_backfill_scheduler",
    "start_auto_backfill_scheduler",
    "stop_auto_backfill_scheduler",
]
