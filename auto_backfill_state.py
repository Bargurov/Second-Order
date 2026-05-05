"""In-memory run-state + lock layer for the auto-backfill scheduler.

This module is a pure accountant.  It owns no I/O, never starts a
scheduler, never executes a backfill, and never imports the analyser
or any provider seam.  A future scheduler module will sit on top of
it.

Scope
-----
* **Lock**: a single-holder mutual-exclusion primitive with a TTL so a
  crashed run can be reclaimed without manual intervention.  Acquire
  / release / TTL-expiry semantics mirror the SQL design in
  ``docs/auto_backfill_scheduler_design.md`` §5, but the storage is
  Python-process-local.  Callers that need cross-process coordination
  must provide that on top.
* **Run state**: the last run's identity (``run_id``), start /
  completion timestamps, skip reason, last error message, and the
  per-run selected-count and spent-calls totals.  Mirrors the
  diagnostics-endpoint shape in design §9.

Design discipline
-----------------
* No I/O.  ``snapshot()`` returns a frozen dataclass; mutating methods
  return structured decision records.  No DB writes, no logging
  side-effects, no clock reads when the caller passes ``now``.
* Deterministic clock injection.  Every method accepts ``now`` (UTC
  ``datetime``); when omitted, the module reads the real UTC clock.
  Tests pin the clock at a fixed datetime to keep assertions stable.
* Thread-safe.  A re-entrant ``threading.Lock`` guards the mutable
  state so a future multi-threaded scheduler can call into the module
  without coordinating itself.
* Total functions.  Methods never raise on a state-machine misuse —
  they return a ``MarkDecision`` / ``LockDecision`` / ``ReleaseDecision``
  with ``allowed=False`` and a stable ``reason`` tag.  ``ValueError``
  / ``TypeError`` are reserved for caller-side bugs (empty owner,
  negative counts, non-positive TTL).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


# ---------------------------------------------------------------------------
# Lock decision vocabulary — exhaustive, mutually exclusive.
# ---------------------------------------------------------------------------

LOCK_REASONS: tuple[str, ...] = (
    "acquired",
    "lock_held",
    "already_held_by_owner",
)

RELEASE_REASONS: tuple[str, ...] = (
    "released",
    "not_held",
    "not_owner",
)

MARK_REASONS: tuple[str, ...] = (
    # mark_started
    "started",
    # mark_completed
    "completed",
    # mark_skipped
    "skipped",
    # rejection vocabulary
    "no_lock",
    "no_run_started",
    "run_id_mismatch",
)


# ---------------------------------------------------------------------------
# Decision records — every mutating method returns one of these.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LockDecision:
    """Outcome of an :meth:`AutoBackfillState.acquire` call."""

    allowed: bool
    reason: str
    owner: Optional[str]            # current holder (new on success)
    acquired_at: Optional[str]      # ISO 8601 UTC
    expires_at: Optional[str]       # ISO 8601 UTC
    detail: Optional[str] = None


@dataclass(frozen=True)
class ReleaseDecision:
    """Outcome of an :meth:`AutoBackfillState.release` call."""

    released: bool
    reason: str
    detail: Optional[str] = None


@dataclass(frozen=True)
class MarkDecision:
    """Outcome of ``mark_started`` / ``mark_completed`` / ``mark_skipped``."""

    allowed: bool
    reason: str
    detail: Optional[str] = None


@dataclass(frozen=True)
class StateSnapshot:
    """Full read-only view of the state.  Immutable; safe to pass
    across threads or serialise.
    """

    # Lock surface
    lock_held: bool
    lock_owner: Optional[str]
    lock_acquired_at: Optional[str]
    lock_expires_at: Optional[str]
    # Run surface
    last_run_id: Optional[str]
    last_started_at: Optional[str]
    last_completed_at: Optional[str]
    last_skip_reason: Optional[str]
    last_error: Optional[str]
    last_selected_count: Optional[int]
    last_spent_calls: Optional[int]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _resolve_now(now: Optional[datetime]) -> datetime:
    if now is None:
        return _utcnow()
    if not isinstance(now, datetime):
        raise TypeError(
            f"now must be a datetime, got {type(now).__name__}"
        )
    # Naive datetimes are tolerated for caller convenience but coerced
    # to UTC so all comparisons use the same reference.
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return None if dt is None else dt.isoformat()


# ---------------------------------------------------------------------------
# State + lock object
# ---------------------------------------------------------------------------


class AutoBackfillState:
    """In-memory run-state + lock for the auto-backfill scheduler.

    Single instance per FastAPI process; the lock guarantees no overlap
    *within that process*.  See the module docstring for the
    cross-process contract (out of scope here).
    """

    def __init__(self, *, ttl_seconds: int) -> None:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
            raise TypeError(
                f"ttl_seconds must be an int, got {type(ttl_seconds).__name__}"
            )
        if ttl_seconds <= 0:
            raise ValueError(
                f"ttl_seconds must be > 0, got {ttl_seconds}"
            )
        self._default_ttl: int = ttl_seconds
        self._mu = threading.RLock()

        # Lock state.
        self._owner: Optional[str] = None
        self._acquired_at: Optional[datetime] = None
        self._expires_at:  Optional[datetime] = None

        # Run state.
        self._current_run_id: Optional[str] = None  # while a run is in flight
        self._last_run_id:    Optional[str] = None
        self._last_started_at:    Optional[datetime] = None
        self._last_completed_at:  Optional[datetime] = None
        self._last_skip_reason:   Optional[str] = None
        self._last_error:         Optional[str] = None
        self._last_selected_count: Optional[int] = None
        self._last_spent_calls:    Optional[int] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(
        self,
        owner: str,
        now: Optional[datetime] = None,
        *,
        ttl_seconds: Optional[int] = None,
    ) -> LockDecision:
        """Try to acquire the lock for ``owner``.

        Per-call ``ttl_seconds`` overrides the instance default for
        this acquisition only.  An expired existing lock is reclaimable
        — the new owner wins atomically.
        """
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a non-empty string")
        if ttl_seconds is not None:
            if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
                raise TypeError("ttl_seconds must be an int")
            if ttl_seconds <= 0:
                raise ValueError("ttl_seconds must be > 0")

        ttl = ttl_seconds if ttl_seconds is not None else self._default_ttl
        when = _resolve_now(now)

        with self._mu:
            # Existing holder?
            if self._owner is not None:
                expired = self._expires_at is None or when >= self._expires_at
                if not expired:
                    if self._owner == owner:
                        return LockDecision(
                            allowed=False,
                            reason="already_held_by_owner",
                            owner=self._owner,
                            acquired_at=_iso(self._acquired_at),
                            expires_at=_iso(self._expires_at),
                        )
                    return LockDecision(
                        allowed=False,
                        reason="lock_held",
                        owner=self._owner,
                        acquired_at=_iso(self._acquired_at),
                        expires_at=_iso(self._expires_at),
                    )
                # Else: stale lock — fall through and reclaim.

            self._owner = owner
            self._acquired_at = when
            self._expires_at = when + timedelta(seconds=ttl)
            return LockDecision(
                allowed=True,
                reason="acquired",
                owner=owner,
                acquired_at=_iso(self._acquired_at),
                expires_at=_iso(self._expires_at),
            )

    def release(
        self,
        owner: str,
        now: Optional[datetime] = None,
    ) -> ReleaseDecision:
        """Release the lock if held by ``owner``.  Wrong-owner releases
        are rejected without mutating state.
        """
        if not isinstance(owner, str) or not owner:
            raise ValueError("owner must be a non-empty string")

        when = _resolve_now(now)
        with self._mu:
            self._maybe_expire_lock(when)
            if self._owner is None:
                return ReleaseDecision(
                    released=False,
                    reason="not_held",
                )
            if self._owner != owner:
                return ReleaseDecision(
                    released=False,
                    reason="not_owner",
                    detail=f"current owner={self._owner!r}",
                )
            self._owner = None
            self._acquired_at = None
            self._expires_at = None
            return ReleaseDecision(released=True, reason="released")

    def mark_started(
        self,
        run_id: str,
        now: Optional[datetime] = None,
    ) -> MarkDecision:
        """Record that a run has started under the held lock."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")

        when = _resolve_now(now)
        with self._mu:
            self._maybe_expire_lock(when)
            if self._owner is None:
                return MarkDecision(allowed=False, reason="no_lock")

            self._current_run_id  = run_id
            self._last_run_id     = run_id
            self._last_started_at = when
            # Starting a fresh run clears any stale skip / error from
            # the previous outcome — the new run is in-flight, so the
            # diagnostics surface should not still report yesterday's
            # crash.  Counts are NOT cleared until the run resolves
            # (snapshot during a running job still shows the previous
            # run's totals as "last completed").
            self._last_skip_reason = None
            self._last_error       = None
            return MarkDecision(allowed=True, reason="started")

    def mark_completed(
        self,
        run_id: str,
        selected_count: int,
        spent_calls: int,
        now: Optional[datetime] = None,
    ) -> MarkDecision:
        """Record a normal-completion outcome for the in-flight run."""
        if not isinstance(run_id, str) or not run_id:
            raise ValueError("run_id must be a non-empty string")
        if (not isinstance(selected_count, int)
                or isinstance(selected_count, bool)
                or selected_count < 0):
            raise ValueError("selected_count must be a non-negative int")
        if (not isinstance(spent_calls, int)
                or isinstance(spent_calls, bool)
                or spent_calls < 0):
            raise ValueError("spent_calls must be a non-negative int")

        when = _resolve_now(now)
        with self._mu:
            self._maybe_expire_lock(when)
            if self._owner is None:
                return MarkDecision(allowed=False, reason="no_lock")
            if self._current_run_id is None:
                return MarkDecision(allowed=False, reason="no_run_started")
            if self._current_run_id != run_id:
                return MarkDecision(
                    allowed=False,
                    reason="run_id_mismatch",
                    detail=f"current run_id={self._current_run_id!r}",
                )

            self._last_completed_at   = when
            self._last_selected_count = selected_count
            self._last_spent_calls    = spent_calls
            self._last_skip_reason    = None
            self._last_error          = None
            self._current_run_id      = None
            return MarkDecision(allowed=True, reason="completed")

    def mark_skipped(
        self,
        reason: str,
        now: Optional[datetime] = None,
        *,
        error: Optional[str] = None,
    ) -> MarkDecision:
        """Record a skip outcome.

        ``reason`` is the operator-facing skip-reason string (vocabulary
        defined in ``docs/auto_backfill_scheduler_design.md`` §5.5).
        ``error`` is an optional free-form exception summary; carried
        verbatim into ``last_error`` so a later snapshot can show why
        the skip happened.

        ``mark_skipped`` is callable WITHOUT the lock — a tick that
        couldn't acquire the lock still records its skip reason for
        the diagnostics panel.
        """
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        if error is not None and not isinstance(error, str):
            raise TypeError("error must be a string when provided")

        when = _resolve_now(now)
        with self._mu:
            self._maybe_expire_lock(when)
            self._last_skip_reason = reason
            self._last_error       = error
            # A skip that happens DURING a run closes the run, so the
            # in-flight ``current_run_id`` is cleared.  ``last_run_id``
            # stays so the operator can correlate skip ↔ run.
            self._current_run_id = None
            return MarkDecision(allowed=True, reason="skipped")

    def snapshot(self, now: Optional[datetime] = None) -> StateSnapshot:
        """Read-only view of the current state.

        Reading the snapshot also evaluates lock expiry — a TTL that
        passed without any other call to the module will be reflected
        in ``lock_held=False`` on the returned snapshot.
        """
        when = _resolve_now(now)
        with self._mu:
            self._maybe_expire_lock(when)
            return StateSnapshot(
                lock_held=self._owner is not None,
                lock_owner=self._owner,
                lock_acquired_at=_iso(self._acquired_at),
                lock_expires_at=_iso(self._expires_at),
                last_run_id=self._last_run_id,
                last_started_at=_iso(self._last_started_at),
                last_completed_at=_iso(self._last_completed_at),
                last_skip_reason=self._last_skip_reason,
                last_error=self._last_error,
                last_selected_count=self._last_selected_count,
                last_spent_calls=self._last_spent_calls,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_expire_lock(self, when: datetime) -> None:
        """Drop the lock if its TTL has passed.  Caller must hold
        ``self._mu``.

        Inclusive on the boundary: ``when == expires_at`` is treated as
        expired so an exact-deadline reclaim is reclaim-friendly rather
        than silent-hold (mirrors the test contract).
        """
        if self._owner is None:
            return
        if self._expires_at is None:
            return
        if when >= self._expires_at:
            self._owner = None
            self._acquired_at = None
            self._expires_at = None


__all__ = [
    "AutoBackfillState",
    "LockDecision",
    "ReleaseDecision",
    "MarkDecision",
    "StateSnapshot",
    "LOCK_REASONS",
    "RELEASE_REASONS",
    "MARK_REASONS",
]
