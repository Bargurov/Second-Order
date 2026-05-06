"""Dry-run auto-backfill job runner.

This module is the single composer over the four pure pieces:

* :mod:`auto_backfill_config`   — env-driven config snapshot
* :mod:`auto_backfill_ledger`   — daily LLM-call counter
* :mod:`auto_backfill_state`    — in-memory run-state + lock
* :mod:`auto_backfill_planner`  — deterministic candidate selection

It models a single scheduler "tick" end-to-end without spending
anything: the runner checks policy, acquires the lock, plans
candidates, and stamps the state with the planned outcome — but does
**not** call the LLM, **does not** reserve ledger calls, and **does
not** start a scheduler.

Out of scope (deliberately)
---------------------------
* No APScheduler integration.  The future scheduler imports this
  function but adds nothing to its semantics — it just calls it on a
  timer.
* No paid execution.  ``execute_paid_candidate`` is a stub that raises
  ``NotImplementedError``.  The runner never invokes it; a future
  paid runner will replace the stub with a real
  ``analyze_event``-shaped call inside its own ``try/finally``
  around ledger reservation.
* No FastAPI startup wiring.  The runner is callable from anywhere
  that can construct the four pure objects.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``, no
  network.  Everything inside this module is in-memory state +
  mapping arithmetic.

Determinism
-----------
The function accepts an explicit ``now`` and an explicit
``run_id_factory`` so tests can pin both clock and identity.  Same
inputs ⇒ same outputs.

The companion design lives in
``docs/auto_backfill_scheduler_design.md``.  Skip-reason and
state-transition vocabularies are pinned there.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

from auto_backfill_config import AutoBackfillConfig
from auto_backfill_ledger import AutoBackfillLedger
from auto_backfill_planner import (
    AutoBackfillPlan,
    plan_auto_backfill_candidates,
)
from auto_backfill_policy import (
    REASON_CONFIGURED,
    REASON_LOCK_HELD,
    decide_auto_backfill_run,
)
from auto_backfill_state import AutoBackfillState, StateSnapshot


_DEFAULT_OWNER: str = "auto_backfill_runner"


# ---------------------------------------------------------------------------
# Public result shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """Structured outcome of one dry-run scheduler tick.

    ``run_id`` is None when the runner skipped before starting
    (config disabled, paid guard, lock contention, etc.).  ``plan``
    is None on the same skip paths — only populated once the runner
    has acquired the lock and produced a selection.

    ``spent_calls`` is always ``0`` in dry-run; carrying the field
    keeps the contract identical to a future paid runner.
    """

    run_id: Optional[str]
    dry_run: bool
    decision_reason: str
    started: bool
    completed: bool
    skip_reason: Optional[str]
    selected_count: int
    spent_calls: int
    plan: Optional[AutoBackfillPlan]
    state_snapshot_after: StateSnapshot
    now: str


# ---------------------------------------------------------------------------
# Paid execution stub — explicitly NotImplemented
# ---------------------------------------------------------------------------


def execute_paid_candidate(candidate: Mapping[str, Any]) -> dict:
    """Future paid-execution hook for one candidate.

    The dry-run runner :func:`run_auto_backfill_dry_run` never calls
    this function — it is a placeholder that documents the future
    integration point.  A real implementation will:

    1. ``analyze_event`` the candidate's headline,
    2. update the ``headline_registry`` state,
    3. ``ledger.reserve_calls(1)`` exactly when the call returns
       (success OR failure — the provider may have charged us either
       way),
    4. record errors via ``state.mark_skipped(error=...)`` for the
       run-level summary while continuing the loop.

    Raises ``NotImplementedError`` today so any caller that wires the
    paid path before the implementation lands gets a loud error
    rather than silently spending nothing or crashing in flight.
    """
    raise NotImplementedError(
        "auto_backfill_runner.execute_paid_candidate is not implemented; "
        "auto-backfill currently runs in dry-run mode only.  See "
        "docs/auto_backfill_scheduler_design.md §4 / §11 for the "
        "paid-path contract that will replace this stub."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise TypeError(
            f"now must be a datetime or None, got {type(now).__name__}"
        )
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _default_run_id_factory() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


def _config_for_policy(config: AutoBackfillConfig) -> dict:
    """Project the config dataclass into the mapping shape the policy
    decoder expects.  Pulled out so the runner has a single seam to
    coerce future config-shape evolution.
    """
    return {
        "enabled":            config.enabled,
        "max_calls_per_run":  config.max_calls_per_run,
        "interval_hours":     config.interval_hours,
    }


def _state_for_policy(snap: StateSnapshot, paid_blocked: bool) -> dict:
    return {
        "lock_held":          snap.lock_held,
        "last_completed_at":  snap.last_completed_at,
        "paid_guard_blocked": paid_blocked,
    }


def _skip(
    state: AutoBackfillState,
    *,
    reason: str,
    now: datetime,
    detail: Optional[str] = None,
) -> RunResult:
    """Record a pre-start skip on the state and return the run result.

    The lock is *not* released here — pre-start skips never acquired
    it.  ``detail`` (if any) is folded into ``last_error`` so the
    operator panel can show why the policy rejected the tick.
    """
    state.mark_skipped(reason=reason, error=detail, now=now)
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
        state_snapshot_after=state.snapshot(now=now),
        now=now.isoformat(),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run_auto_backfill_dry_run(
    *,
    candidates: Iterable[Mapping[str, Any]],
    config: AutoBackfillConfig,
    state: AutoBackfillState,
    ledger: AutoBackfillLedger,
    now: Optional[datetime] = None,
    run_id_factory: Optional[Callable[[], str]] = None,
    owner: str = _DEFAULT_OWNER,
) -> RunResult:
    """Execute one dry-run auto-backfill tick.

    The function is total: every code path returns a :class:`RunResult`.
    Inputs are pure / mockable; no I/O beyond the in-memory state and
    ledger objects passed in.

    Skip semantics: a tick that is rejected before any work runs
    records the reason in ``state.last_skip_reason`` and returns with
    ``started=False, completed=False``.  A tick that runs through to
    planning records ``last_run_id``, ``last_started_at``,
    ``last_completed_at``, ``last_selected_count``, and
    ``last_spent_calls=0``.

    The ledger is **never** mutated by this function.  Callers can
    pin the no-mutation invariant directly by snapshotting before/after.
    """
    when = _resolve_now(now)
    factory = run_id_factory or _default_run_id_factory

    # 1. Policy decision based on snapshots taken BEFORE we touch
    #    anything.  ``paid_guard_blocked`` is derived from the config —
    #    a config that says paid is off should block the tick the
    #    same way a runtime kill switch would.
    state_snap_before = state.snapshot(now=when)
    ledger_snap = ledger.snapshot(now=when)
    paid_blocked = not config.paid_analysis_enabled

    decision = decide_auto_backfill_run(
        _config_for_policy(config),
        ledger_snap,
        _state_for_policy(state_snap_before, paid_blocked=paid_blocked),
        now=when,
    )
    if not decision.run_allowed:
        return _skip(
            state, reason=decision.reason, now=when,
            detail=decision.detail,
        )

    # 2. Acquire the lock atomically.  The policy already checked the
    #    snapshot, but a concurrent tick could have grabbed the lock in
    #    the meantime — surface that as ``lock_held`` so the contract
    #    matches a policy-level rejection.
    lock_decision = state.acquire(owner=owner, now=when)
    if not lock_decision.allowed:
        return _skip(state, reason=REASON_LOCK_HELD, now=when)

    # 3. Plan + record outcome.  Wrap the planner in try/finally so a
    #    planner exception still releases the lock.  Build the
    #    RunResult AFTER the finally so the snapshot reflects the
    #    released-lock state — that's the post-tick view operators see.
    run_id = factory()
    state.mark_started(run_id=run_id, now=when)
    plan: Optional[AutoBackfillPlan] = None

    try:
        plan = plan_auto_backfill_candidates(
            list(candidates),
            config.max_calls_per_run,
            daily_remaining=ledger_snap,
        )
        state.mark_completed(
            run_id=run_id,
            selected_count=plan.selected_count,
            spent_calls=0,
            now=when,
        )
    finally:
        # Always release the lock — even if the planner raised, we
        # don't want a stuck lock to block the next tick.  The lock
        # owner check inside ``release`` makes this safe even if the
        # state machine has been mutated unexpectedly.
        state.release(owner=owner, now=when)

    # ``plan`` is None only when the try block raised; the finally
    # already released the lock so we can fall through, but a runner
    # that swallows planner exceptions silently would mask real bugs.
    # Re-raise to surface the failure to the caller.
    if plan is None:                          # pragma: no cover
        raise RuntimeError("plan_auto_backfill_candidates returned no plan")

    return RunResult(
        run_id=run_id,
        dry_run=True,
        decision_reason=REASON_CONFIGURED,
        started=True,
        completed=True,
        skip_reason=None,
        selected_count=plan.selected_count,
        spent_calls=0,
        plan=plan,
        state_snapshot_after=state.snapshot(now=when),
        now=when.isoformat(),
    )


__all__ = [
    "RunResult",
    "execute_paid_candidate",
    "run_auto_backfill_dry_run",
]
