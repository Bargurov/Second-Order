"""In-memory call ledger for the auto-backfill loop.

This module is a pure accountant.  It tracks how many LLM calls the
auto-backfill subsystem has spent on the current calendar day and
exposes two operations:

* :meth:`AutoBackfillLedger.can_spend` — non-mutating check.
* :meth:`AutoBackfillLedger.reserve_calls` — atomic check-and-reserve.

The ledger:

* Owns no I/O.  No DB writes, no network, no scheduler hooks.  A
  scheduler / FastAPI startup wiring layer can be added later.
* Resets the per-day counter the first time it observes a new
  calendar day.  The clock is injectable so tests can drive rollover
  deterministically.
* Returns structured :class:`LedgerDecision` records with one of three
  reasons: ``"allowed"``, ``"daily_cap_exceeded"``, ``"invalid_request"``.
* Refuses negative caps and negative / non-int request counts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional

# Bool is a subclass of int in Python; we don't want True/False sneaking
# in as request counts.
_BOOL = bool

ALLOWED = "allowed"
DAILY_CAP_EXCEEDED = "daily_cap_exceeded"
INVALID_REQUEST = "invalid_request"


@dataclass(frozen=True)
class LedgerDecision:
    """Outcome of a ``can_spend`` / ``reserve_calls`` call.

    ``allowed`` is the boolean result; ``reason`` is a stable string tag
    suitable for logging and metrics.  The remaining fields describe the
    ledger state at decision time so callers don't have to call back in.
    """

    allowed: bool
    reason: str
    requested: int
    used: int
    remaining: int
    daily_cap: int
    day: str
    detail: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AutoBackfillLedger:
    """Daily-capped, in-memory call counter."""

    def __init__(self, daily_cap: int) -> None:
        if isinstance(daily_cap, _BOOL) or not isinstance(daily_cap, int):
            raise TypeError(
                f"daily_cap must be a non-negative int, got {type(daily_cap).__name__}"
            )
        if daily_cap < 0:
            raise ValueError(f"daily_cap must be >= 0, got {daily_cap}")

        self._daily_cap: int = daily_cap
        self._used: int = 0
        self._day: Optional[date] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def daily_cap(self) -> int:
        return self._daily_cap

    def can_spend(
        self,
        requested_calls: int,
        now: Optional[datetime] = None,
    ) -> LedgerDecision:
        """Return whether ``requested_calls`` would fit under the cap.

        Non-mutating beyond the implicit calendar-day rollover: if the
        current day differs from the last observed day, the counter is
        zeroed before evaluating the request.
        """
        return self._evaluate(requested_calls, now=now, reserve=False)

    def reserve_calls(
        self,
        requested_calls: int,
        now: Optional[datetime] = None,
    ) -> LedgerDecision:
        """Atomically check-and-reserve ``requested_calls``.

        On allow, the internal counter is incremented and the returned
        decision reflects the post-reservation state.  On deny, the
        counter is left untouched.
        """
        return self._evaluate(requested_calls, now=now, reserve=True)

    def snapshot(self, now: Optional[datetime] = None) -> LedgerDecision:
        """Return current state without changing anything.

        Useful for diagnostics and tests; equivalent to ``can_spend(0)``.
        """
        return self.can_spend(0, now=now)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _evaluate(
        self,
        requested_calls: int,
        *,
        now: Optional[datetime],
        reserve: bool,
    ) -> LedgerDecision:
        today = self._resolve_day(now)
        self._maybe_rollover(today)

        if not self._is_valid_request(requested_calls):
            return LedgerDecision(
                allowed=False,
                reason=INVALID_REQUEST,
                requested=self._coerce_int_for_report(requested_calls),
                used=self._used,
                remaining=max(0, self._daily_cap - self._used),
                daily_cap=self._daily_cap,
                day=today.isoformat(),
                detail="requested_calls must be a non-negative int",
            )

        prospective = self._used + requested_calls
        if prospective > self._daily_cap:
            return LedgerDecision(
                allowed=False,
                reason=DAILY_CAP_EXCEEDED,
                requested=requested_calls,
                used=self._used,
                remaining=max(0, self._daily_cap - self._used),
                daily_cap=self._daily_cap,
                day=today.isoformat(),
            )

        if reserve:
            self._used = prospective

        return LedgerDecision(
            allowed=True,
            reason=ALLOWED,
            requested=requested_calls,
            used=self._used,
            remaining=self._daily_cap - self._used,
            daily_cap=self._daily_cap,
            day=today.isoformat(),
        )

    @staticmethod
    def _resolve_day(now: Optional[datetime]) -> date:
        if now is None:
            now = _utcnow()
        return date(now.year, now.month, now.day)

    def _maybe_rollover(self, today: date) -> None:
        if self._day != today:
            self._day = today
            self._used = 0

    @staticmethod
    def _is_valid_request(requested_calls: object) -> bool:
        if isinstance(requested_calls, _BOOL):
            return False
        if not isinstance(requested_calls, int):
            return False
        return requested_calls >= 0

    @staticmethod
    def _coerce_int_for_report(requested_calls: object) -> int:
        # The decision record types ``requested`` as int; for invalid
        # inputs we still return an int so structured consumers don't
        # break — non-int / negative values collapse to 0 in the report.
        if isinstance(requested_calls, _BOOL):
            return 0
        if isinstance(requested_calls, int) and requested_calls >= 0:
            return requested_calls
        return 0
