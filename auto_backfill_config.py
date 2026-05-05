"""Pure env-driven configuration for the auto-backfill scheduler.

This module is the single source of truth for "what would the
scheduler do if it were enabled?".  It reads a small set of
environment variables, applies validated fallbacks, and emits a
list of operator-readable warnings — without touching the DB, the
scheduler, the LLM, or any provider.

Design discipline
-----------------
* **No I/O.**  The module is a pure function over ``os.environ`` (or an
  injected dict for tests).  Calling :func:`load_auto_backfill_config`
  does not start a thread, does not connect to SQLite, does not import
  the analyser.
* **Disabled-by-default.**  ``ENABLE_AUTO_BACKFILL`` defaults to false.
  Even when it is true, ``ENABLE_PAID_ANALYSIS`` must also be true for
  the effective status to be ``"configured"``; otherwise the loader
  reports ``"blocked_paid_guard"`` and emits a warning so an operator
  reading the diagnostics panel can tell why no backfill is running.
* **Validated fallbacks.**  Invalid env values (non-int, negative,
  empty model) collapse to the documented default and emit a warning
  naming the env var.  The loader never raises.
* **No secrets.**  This loader never reads ``ANTHROPIC_API_KEY``,
  ``OPENAI_API_KEY``, or any other credential — the diagnostic surface
  is restricted to operational toggles.

The companion design doc is ``docs/auto_backfill_scheduler_design.md``
§3 (env contract) and §9 (diagnostics endpoint).
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Mapping, Optional


# ---------------------------------------------------------------------------
# Defaults — pinned in one place so the diagnostics route, the future
# scheduler, and tests all agree on the same values.
# ---------------------------------------------------------------------------

DEFAULT_INTERVAL_HOURS:    int = 6
DEFAULT_MAX_PER_RUN:       int = 3
DEFAULT_MAX_PER_DAY:       int = 12
DEFAULT_MODEL:             str = "claude-haiku-4-5-20251001"

# Hard caps — values beyond these clamp down with a warning.  The clamp
# protects an operator from typoing ``AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY=10000``
# and silently authorising runaway spend.
_MAX_INTERVAL_HOURS: int = 24 * 7         # one week is the longest plausible cadence
_MAX_PER_RUN:        int = 10
_MAX_PER_DAY:        int = 50

# Effective status enum — diagnostics consumers branch on this, so it is
# part of the public contract.
EFFECTIVE_DISABLED:           str = "disabled"
EFFECTIVE_BLOCKED_PAID_GUARD: str = "blocked_paid_guard"
EFFECTIVE_CONFIGURED:         str = "configured"

EFFECTIVE_STATUSES: tuple[str, ...] = (
    EFFECTIVE_DISABLED,
    EFFECTIVE_BLOCKED_PAID_GUARD,
    EFFECTIVE_CONFIGURED,
)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AutoBackfillConfig:
    """Frozen snapshot of the auto-backfill configuration.

    Every field is a primitive (bool / int / str / list[str]) so the
    snapshot can be serialised to JSON via ``dataclasses.asdict``.
    """

    enabled:              bool
    paid_analysis_enabled: bool
    interval_hours:       int
    max_calls_per_run:    int
    max_calls_per_day:    int
    model:                str
    effective_status:     str
    warnings:             list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Env helpers — local to this module so it has no import dependency on
# routes.movers.  Same vocabulary as ``routes/movers._env_bool`` etc.
# ---------------------------------------------------------------------------

def _env_text(env: Mapping[str, str], name: str) -> Optional[str]:
    raw = env.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _env_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _env_text(env, name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _env_int_clamped(
    env: Mapping[str, str],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
    warnings: list[str],
) -> int:
    """Read an int env var; collapse to ``default`` with a warning when
    the raw value is non-int, negative, or out of [minimum, maximum].

    Clamping (rather than raising) is the right discipline for a
    diagnostics surface: an operator typo should not break the panel,
    but it should be visible.
    """
    raw = _env_text(env, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        warnings.append(
            f"{name}={raw!r} is not an integer; using default {default}"
        )
        return default
    if value < minimum:
        warnings.append(
            f"{name}={value} is below minimum {minimum}; using default {default}"
        )
        return default
    if value > maximum:
        warnings.append(
            f"{name}={value} is above maximum {maximum}; clamping to {maximum}"
        )
        return maximum
    return value


# ---------------------------------------------------------------------------
# Public loader
# ---------------------------------------------------------------------------

def load_auto_backfill_config(
    env: Optional[Mapping[str, str]] = None,
) -> AutoBackfillConfig:
    """Build an :class:`AutoBackfillConfig` from ``env`` (defaults to
    ``os.environ``).

    Pure: never reads anything other than the env mapping passed in,
    never starts a scheduler, never touches SQLite, never imports the
    analyser.
    """
    if env is None:
        env = os.environ

    warnings: list[str] = []

    enabled               = _env_bool(env, "ENABLE_AUTO_BACKFILL", False)
    paid_analysis_enabled = _env_bool(env, "ENABLE_PAID_ANALYSIS",  False)

    interval_hours = _env_int_clamped(
        env, "AUTO_BACKFILL_INTERVAL_HOURS",
        default=DEFAULT_INTERVAL_HOURS,
        minimum=1, maximum=_MAX_INTERVAL_HOURS,
        warnings=warnings,
    )
    max_calls_per_run = _env_int_clamped(
        env, "AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN",
        default=DEFAULT_MAX_PER_RUN,
        minimum=1, maximum=_MAX_PER_RUN,
        warnings=warnings,
    )
    max_calls_per_day = _env_int_clamped(
        env, "AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY",
        default=DEFAULT_MAX_PER_DAY,
        minimum=1, maximum=_MAX_PER_DAY,
        warnings=warnings,
    )
    model = _env_text(env, "AUTO_BACKFILL_MODEL") or DEFAULT_MODEL

    # Cross-field sanity: a per-run cap above the per-day cap is
    # operator-confusing — surface it.  We do not auto-correct because
    # both halves come from the operator and the right answer depends
    # on intent.
    if max_calls_per_run > max_calls_per_day:
        warnings.append(
            f"AUTO_BACKFILL_MAX_LLM_CALLS_PER_RUN={max_calls_per_run} "
            f"exceeds AUTO_BACKFILL_MAX_LLM_CALLS_PER_DAY={max_calls_per_day}; "
            "the per-day cap will dominate and a single run will spend "
            "the whole daily budget."
        )

    # Effective-status decision tree.  Mirrors the design doc §3 boot
    # decision tree.  The "blocked_paid_guard" path also emits an
    # operator-readable warning so the diagnostics panel surfaces the
    # remediation alongside the status.
    if not enabled:
        effective_status = EFFECTIVE_DISABLED
    elif not paid_analysis_enabled:
        effective_status = EFFECTIVE_BLOCKED_PAID_GUARD
        warnings.append(
            "ENABLE_AUTO_BACKFILL=true but ENABLE_PAID_ANALYSIS is false; "
            "scheduler will not start.  Set ENABLE_PAID_ANALYSIS=true to "
            "authorise paid LLM calls, or unset ENABLE_AUTO_BACKFILL."
        )
    else:
        effective_status = EFFECTIVE_CONFIGURED

    return AutoBackfillConfig(
        enabled=enabled,
        paid_analysis_enabled=paid_analysis_enabled,
        interval_hours=interval_hours,
        max_calls_per_run=max_calls_per_run,
        max_calls_per_day=max_calls_per_day,
        model=model,
        effective_status=effective_status,
        warnings=warnings,
    )


__all__ = [
    "AutoBackfillConfig",
    "DEFAULT_INTERVAL_HOURS",
    "DEFAULT_MAX_PER_DAY",
    "DEFAULT_MAX_PER_RUN",
    "DEFAULT_MODEL",
    "EFFECTIVE_BLOCKED_PAID_GUARD",
    "EFFECTIVE_CONFIGURED",
    "EFFECTIVE_DISABLED",
    "EFFECTIVE_STATUSES",
    "load_auto_backfill_config",
]
