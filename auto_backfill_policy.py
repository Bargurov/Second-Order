"""Pure eligibility policy for the auto-backfill loop.

Given a ``config`` dict, a daily-call ``ledger_snapshot``, and a
runtime ``state_snapshot``, this module decides whether the next
auto-backfill pass should run, why or why not, and what the effective
per-run cap and daily remaining budget are.

The module is deliberately I/O-free: no DB writes, no LLM/provider
calls, no network, no ``market_check`` imports, and no dependencies on
the diagnostics layer.  Inputs are plain ``Mapping`` shapes so the
caller can wire it up to whatever transport layer it likes.

Decision reasons (one of):

* ``invalid_config``      — config is malformed.
* ``disabled``            — operator turned the loop off.
* ``paid_guard_blocked``  — paid execution is currently disallowed.
* ``lock_held``           — another auto-backfill pass is in progress.
* ``recently_run``        — last completion is within ``interval_hours``.
* ``daily_cap_exhausted`` — ledger reports zero remaining budget.
* ``configured``          — green light; caller may invoke the planner.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

_BOOL = bool

REASON_INVALID_CONFIG = "invalid_config"
REASON_DISABLED = "disabled"
REASON_PAID_GUARD_BLOCKED = "paid_guard_blocked"
REASON_LOCK_HELD = "lock_held"
REASON_RECENTLY_RUN = "recently_run"
REASON_DAILY_CAP_EXHAUSTED = "daily_cap_exhausted"
REASON_CONFIGURED = "configured"


@dataclass(frozen=True)
class AutoBackfillRunDecision:
    run_allowed: bool
    reason: str
    effective_per_run_cap: int
    effective_daily_remaining: Optional[int]
    now: str
    detail: Optional[str] = None


def decide_auto_backfill_run(
    config: Any,
    ledger_snapshot: Any = None,
    state_snapshot: Optional[Mapping[str, Any]] = None,
    *,
    now: Optional[datetime] = None,
) -> AutoBackfillRunDecision:
    """Return whether the next auto-backfill pass should run.

    Evaluation order (first match wins):

    1. ``invalid_config``       — config is not a mapping or has bad fields.
    2. ``disabled``              — ``config["enabled"]`` is falsy.
    3. ``paid_guard_blocked``    — ``state_snapshot["paid_guard_blocked"]``.
    4. ``lock_held``             — ``state_snapshot["lock_held"]``.
    5. ``recently_run``          — ``now`` is within ``interval_hours`` of
       ``state_snapshot["last_completed_at"]``.
    6. ``daily_cap_exhausted``   — ledger reports ``remaining <= 0``.
    7. ``configured``            — allow the run.

    The decision always carries ``effective_per_run_cap`` and
    ``effective_daily_remaining`` so the caller can pass them straight
    into ``plan_auto_backfill_candidates`` without re-deriving.
    """
    resolved_now = _resolve_now(now)
    now_iso = resolved_now.isoformat()
    state = state_snapshot if isinstance(state_snapshot, Mapping) else {}
    daily_remaining = _extract_remaining(ledger_snapshot)

    parsed = _parse_config(config)
    if not parsed["valid"]:
        return AutoBackfillRunDecision(
            run_allowed=False,
            reason=REASON_INVALID_CONFIG,
            effective_per_run_cap=0,
            effective_daily_remaining=daily_remaining,
            now=now_iso,
            detail=parsed["error"],
        )

    enabled: bool = parsed["enabled"]
    per_run_cap: int = parsed["max_calls_per_run"]
    interval_hours: float = parsed["interval_hours"]

    if not enabled:
        return _decision(
            False, REASON_DISABLED, per_run_cap, daily_remaining, now_iso,
        )

    if _truthy(state.get("paid_guard_blocked")):
        return _decision(
            False, REASON_PAID_GUARD_BLOCKED, per_run_cap, daily_remaining,
            now_iso,
        )

    if _truthy(state.get("lock_held")):
        return _decision(
            False, REASON_LOCK_HELD, per_run_cap, daily_remaining, now_iso,
        )

    last_completed = _parse_datetime(state.get("last_completed_at"))
    if interval_hours > 0 and last_completed is not None:
        elapsed = resolved_now - last_completed
        if elapsed < timedelta(hours=interval_hours):
            return _decision(
                False, REASON_RECENTLY_RUN, per_run_cap, daily_remaining,
                now_iso,
            )

    if daily_remaining is not None and daily_remaining <= 0:
        return _decision(
            False, REASON_DAILY_CAP_EXHAUSTED, per_run_cap, daily_remaining,
            now_iso,
        )

    return _decision(
        True, REASON_CONFIGURED, per_run_cap, daily_remaining, now_iso,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _decision(
    allowed: bool,
    reason: str,
    per_run_cap: int,
    daily_remaining: Optional[int],
    now_iso: str,
    detail: Optional[str] = None,
) -> AutoBackfillRunDecision:
    return AutoBackfillRunDecision(
        run_allowed=allowed,
        reason=reason,
        effective_per_run_cap=per_run_cap,
        effective_daily_remaining=daily_remaining,
        now=now_iso,
        detail=detail,
    )


def _resolve_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        # Surface this as an obvious programmer error rather than a
        # silent fallback to wallclock time.
        raise TypeError(
            f"now must be a datetime or None, got {type(now).__name__}"
        )
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _truthy(value: Any) -> bool:
    return bool(value)


def _parse_config(config: Any) -> dict[str, Any]:
    if not isinstance(config, Mapping):
        return {"valid": False, "error": "config must be a mapping"}

    enabled = config.get("enabled", False)
    if not isinstance(enabled, _BOOL):
        return {
            "valid": False,
            "error": (
                f"enabled must be a bool, got {type(enabled).__name__}"
            ),
        }

    max_calls = config.get("max_calls_per_run", 0)
    if (
        isinstance(max_calls, _BOOL)
        or not isinstance(max_calls, int)
        or max_calls < 0
    ):
        return {
            "valid": False,
            "error": (
                "max_calls_per_run must be a non-negative int, "
                f"got {max_calls!r}"
            ),
        }

    interval = config.get("interval_hours", 0)
    if isinstance(interval, _BOOL) or not isinstance(interval, (int, float)):
        return {
            "valid": False,
            "error": (
                "interval_hours must be a non-negative number, "
                f"got {interval!r}"
            ),
        }
    if interval < 0:
        return {
            "valid": False,
            "error": "interval_hours must be a non-negative number",
        }

    return {
        "valid": True,
        "enabled": enabled,
        "max_calls_per_run": int(max_calls),
        "interval_hours": float(interval),
    }


def _extract_remaining(ledger_snapshot: Any) -> Optional[int]:
    """Pull a ``remaining`` int out of int / mapping / object inputs.

    Booleans are explicitly rejected (they're a subclass of ``int``) so
    a stray ``True``/``False`` doesn't masquerade as a budget.
    """
    if ledger_snapshot is None:
        return None
    if isinstance(ledger_snapshot, _BOOL):
        return None
    if isinstance(ledger_snapshot, int):
        return ledger_snapshot if ledger_snapshot >= 0 else None
    if isinstance(ledger_snapshot, Mapping):
        value = ledger_snapshot.get("remaining")
    elif hasattr(ledger_snapshot, "remaining"):
        value = getattr(ledger_snapshot, "remaining")
    else:
        return None
    if isinstance(value, _BOOL) or not isinstance(value, int):
        return None
    return value if value >= 0 else None


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
