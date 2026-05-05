"""Pure candidate planner for auto-backfill.

The planner accepts candidate-queue / backfill-preview shaped dictionaries
and returns a deterministic dry-run selection.  It performs no I/O: no DB
writes, no LLM/provider calls, no network, and no market_check imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

_BOOL = bool

ALREADY_ANALYZED_STATES = frozenset({"analyzed", "market_checked", "surfaced"})
EXPIRED_LOW_IMPACT_STATE = "expired_low_impact"

SKIP_INVALID_ITEM = "invalid_item"
SKIP_MISSING_HEADLINE = "missing_headline"
SKIP_ALREADY_ANALYZED = "already_analyzed"
SKIP_EXPIRED_LOW_IMPACT = "expired_low_impact"
SKIP_HAS_SKIP_REASON = "skip_reason"
SKIP_RUN_CAP_EXHAUSTED = "run_cap_exhausted"
SKIP_DAILY_CAP_EXHAUSTED = "daily_cap_exhausted"

SKIP_COUNT_KEYS = (
    SKIP_INVALID_ITEM,
    SKIP_MISSING_HEADLINE,
    SKIP_ALREADY_ANALYZED,
    SKIP_EXPIRED_LOW_IMPACT,
    SKIP_HAS_SKIP_REASON,
    SKIP_RUN_CAP_EXHAUSTED,
    SKIP_DAILY_CAP_EXHAUSTED,
)


@dataclass(frozen=True)
class AutoBackfillPlan:
    """Dry-run selection result for one auto-backfill pass."""

    selected: tuple[dict[str, Any], ...]
    skip_counts: dict[str, int]
    skip_reasons: dict[str, int]
    max_calls_per_run: int
    daily_remaining: int | None
    effective_call_cap: int
    eligible_count: int
    considered_count: int

    @property
    def selected_count(self) -> int:
        return len(self.selected)


@dataclass(frozen=True)
class _Candidate:
    item: Mapping[str, Any]
    original_index: int
    sort_key: tuple[Any, ...] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "sort_key", _candidate_sort_key(self.item, self.original_index))


def plan_auto_backfill_candidates(
    items: Iterable[Mapping[str, Any]],
    max_calls_per_run: int,
    *,
    daily_remaining: Any = None,
    allow_already_analyzed: bool = False,
    allow_expired_low_impact: bool = False,
    allow_skip_reasons: bool = False,
) -> AutoBackfillPlan:
    """Return a deterministic dry-run auto-backfill plan.

    ``items`` should be dictionaries from ``/registry/candidate-queue`` or
    ``/movers/backfill-preview``.  Candidates are ranked by descending
    ``rank_score``, descending ``source_count``, descending ``published_at``,
    then headline / original position for stable ties.

    ``daily_remaining`` can be an integer, a mapping with ``remaining``, or
    a ledger decision object with a ``remaining`` attribute.
    """

    run_cap = _validate_non_negative_int(max_calls_per_run, "max_calls_per_run")
    remaining = _resolve_daily_remaining(daily_remaining)
    effective_cap = run_cap if remaining is None else min(run_cap, remaining)

    skip_counts = {key: 0 for key in SKIP_COUNT_KEYS}
    skip_reasons: dict[str, int] = {}
    eligible: list[_Candidate] = []
    considered_count = 0

    for index, raw_item in enumerate(items):
        considered_count += 1
        if not isinstance(raw_item, Mapping):
            skip_counts[SKIP_INVALID_ITEM] += 1
            continue

        headline = _text(raw_item.get("headline"))
        if not headline:
            skip_counts[SKIP_MISSING_HEADLINE] += 1
            continue

        state = _text(raw_item.get("registry_state")).lower()
        reason = _text(raw_item.get("skip_reason"))

        if _is_already_analyzed(raw_item, state, reason) and not allow_already_analyzed:
            skip_counts[SKIP_ALREADY_ANALYZED] += 1
            _count_skip_reason(skip_reasons, reason)
            continue

        if _is_expired_low_impact(state, reason) and not allow_expired_low_impact:
            skip_counts[SKIP_EXPIRED_LOW_IMPACT] += 1
            _count_skip_reason(skip_reasons, reason)
            continue

        if reason and not allow_skip_reasons:
            skip_counts[SKIP_HAS_SKIP_REASON] += 1
            _count_skip_reason(skip_reasons, reason)
            continue

        eligible.append(_Candidate(raw_item, index))

    ranked = sorted(eligible, key=lambda candidate: candidate.sort_key)

    selected: list[dict[str, Any]] = []
    for candidate in ranked:
        if len(selected) < effective_cap:
            selected.append(dict(candidate.item))
            continue

        if remaining is not None and remaining <= run_cap:
            skip_counts[SKIP_DAILY_CAP_EXHAUSTED] += 1
        else:
            skip_counts[SKIP_RUN_CAP_EXHAUSTED] += 1

    return AutoBackfillPlan(
        selected=tuple(selected),
        skip_counts=skip_counts,
        skip_reasons=skip_reasons,
        max_calls_per_run=run_cap,
        daily_remaining=remaining,
        effective_call_cap=effective_cap,
        eligible_count=len(eligible),
        considered_count=considered_count,
    )


def _validate_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, _BOOL) or not isinstance(value, int):
        raise TypeError(f"{name} must be a non-negative int, got {type(value).__name__}")
    if value < 0:
        raise ValueError(f"{name} must be >= 0, got {value}")
    return value


def _resolve_daily_remaining(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        value = value.get("remaining")
    elif hasattr(value, "remaining"):
        value = getattr(value, "remaining")
    return _validate_non_negative_int(value, "daily_remaining")


def _candidate_sort_key(item: Mapping[str, Any], original_index: int) -> tuple[Any, ...]:
    headline = _text(item.get("headline")).lower()
    return (
        -_number(item.get("rank_score")),
        -_int(item.get("source_count")),
        _published_desc_key(item.get("published_at")),
        headline,
        original_index,
    )


def _published_desc_key(value: Any) -> tuple[int, int, int, int, int, int, int]:
    dt = _parse_datetime(value)
    # Negative components make newer timestamps sort first in ascending sort.
    return (
        -dt.year,
        -dt.month,
        -dt.day,
        -dt.hour,
        -dt.minute,
        -dt.second,
        -dt.microsecond,
    )


def _parse_datetime(value: Any) -> datetime:
    raw = _text(value)
    if not raw:
        return datetime(1, 1, 1, tzinfo=timezone.utc)
    try:
        normalized = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return datetime(1, 1, 1, tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_already_analyzed(
    item: Mapping[str, Any],
    registry_state: str,
    skip_reason: str,
) -> bool:
    if item.get("already_analyzed") is True:
        return True
    if registry_state in ALREADY_ANALYZED_STATES:
        return True
    return skip_reason in {"registry_already_analyzed", "already_market_checked"}


def _is_expired_low_impact(registry_state: str, skip_reason: str) -> bool:
    return (
        registry_state == EXPIRED_LOW_IMPACT_STATE
        or skip_reason == "registry_expired_low_impact"
    )


def _count_skip_reason(skip_reasons: dict[str, int], reason: str) -> None:
    if not reason:
        return
    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _number(value: Any) -> float:
    if isinstance(value, _BOOL):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int(value: Any) -> int:
    if isinstance(value, _BOOL):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
