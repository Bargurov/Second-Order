"""
event_age_policy.py

Unified event-age-aware TTL / freeze policy.

Central source of truth for how an event's age classifies it into a
recomputation bucket and what TTL + freeze rule applies.  Before this
module the freshness logic lived exclusively inside
``market_check_freshness.compute_staleness`` with thresholds hard-coded
to the market-check refresh path; every other event-derived
recomputation had its own ad-hoc age handling or none at all.

Buckets
-------
Five buckets classify every saved event:

    "hot"     — event_age_days <= 1     (today or yesterday)
                short TTL, recomputes aggressively
    "warm"    — 1 < event_age_days <= 7 (last week)
                medium TTL, recomputes a few times per day
    "stable"  — 7 < event_age_days <= 30 (older but still live)
                long TTL, recomputes once per trading day
    "frozen"  — event_age_days > 30     (archived)
                no refresh by default; force=True required
    "legacy"  — missing / unparsable timestamp anchor
                short TTL so the row gets stamped on first read

Tunable windows
---------------
The thresholds below are empirically calibrated in
``tools/event_age_policy_validation.py`` against the live events
archive.  The validation script replays representative workloads
through ``classify_event_age`` and reports:

    bucket distribution over the archive
    recompute rate at each candidate window
    frozen-row recompute savings

Grounded numbers are in the module docstring for
``market_check_freshness`` — the two modules share the same
thresholds, so a change here needs re-running both validation scripts.

Contract
--------
``classify_event_age(event, *, now=None, force=False)`` returns a dict
with every field the consumers need:

    bucket          — one of {"hot", "warm", "stable", "frozen", "legacy"}
    natural_bucket  — same but always reflects the unforced view
                      (so callers can log that a force was required)
    event_age_days  — integer >= 0
    ttl_seconds     — integer (hot/warm/stable/legacy) or None (frozen)
    is_frozen       — bool; True iff natural_bucket == "frozen"
    force_bypassed  — bool; True iff force=True turned a frozen row
                      into a refreshable one
    reason          — short human-readable explanation
"""

from __future__ import annotations

from datetime import datetime as _dt
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Tunables — see module docstring + tools/event_age_policy_validation.py
# ---------------------------------------------------------------------------

# Bucket boundaries (inclusive upper bound).  A 1-day-old event is hot;
# a 2-day-old event is warm.  A 7-day-old event is warm; an 8-day-old
# event is stable.  > 30 days is frozen.
_HOT_MAX_DAYS: int = 1
_WARM_MAX_DAYS: int = 7
_STABLE_MAX_DAYS: int = 30

# Per-bucket TTL in seconds.  Frozen is None (never refreshed unless
# force=True).  Legacy is 0 (always refreshes on first read).  Hot and
# warm are intentionally different so today/yesterday events pick up
# intraday tape movement while older rows stay cheap.
_HOT_TTL_SECONDS:    int = 2 * 3600    #  2h
_WARM_TTL_SECONDS:   int = 4 * 3600    #  4h — matches legacy recent bucket
_STABLE_TTL_SECONDS: int = 24 * 3600   # 24h — matches legacy older bucket


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: Optional[str]) -> Optional[_dt]:
    """Parse an ISO-8601 timestamp or YYYY-MM-DD date.  Never raises."""
    if not value or not isinstance(value, str):
        return None
    try:
        return _dt.fromisoformat(value)
    except ValueError:
        pass
    try:
        return _dt.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def event_age_days(event: dict, now: _dt) -> int:
    """Return the calendar-day age of a saved event (>= 0).

    Prefers ``event_date`` (the anchor the user supplied); falls back
    to ``timestamp`` (save time) for events that were analysed without
    an explicit anchor.  Future dates clamp to 0.  Unparsable inputs
    return 0 so the caller treats the row as "hot" and refreshes.
    """
    anchor = event.get("event_date") or (event.get("timestamp") or "")[:10]
    parsed = _parse_iso(anchor)
    if parsed is None:
        return 0
    delta = (now.date() - parsed.date()).days
    return max(0, delta)


def _has_timestamp_anchor(event: dict) -> bool:
    """True when the event carries a parsable date or timestamp anchor."""
    for key in ("event_date", "timestamp"):
        val = event.get(key)
        if isinstance(val, str) and val and _parse_iso(val) is not None:
            return True
    return False


def _bucket_for_age(age_days: int) -> str:
    """Pure age → bucket mapping.  No force / legacy handling."""
    if age_days <= _HOT_MAX_DAYS:
        return "hot"
    if age_days <= _WARM_MAX_DAYS:
        return "warm"
    if age_days <= _STABLE_MAX_DAYS:
        return "stable"
    return "frozen"


def _ttl_for_bucket(bucket: str) -> Optional[int]:
    return {
        "hot":    _HOT_TTL_SECONDS,
        "warm":   _WARM_TTL_SECONDS,
        "stable": _STABLE_TTL_SECONDS,
        "frozen": None,
        "legacy": 0,
    }.get(bucket, _WARM_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Public: classify_event_age
# ---------------------------------------------------------------------------


def classify_event_age(
    event: dict,
    *,
    now: Optional[_dt] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Classify a saved event into a freshness bucket + TTL.

    ``event`` must be a dict with at least ``event_date`` or
    ``timestamp``.  Missing anchors → legacy bucket so the caller
    treats the row as needing a stamp-on-first-read refresh.

    ``force=True`` converts a naturally-frozen row into a refreshable
    row (bucket → "stable", force_bypassed=True).  The ``natural_bucket``
    field still reports the unforced classification so observability
    layers see the difference.
    """
    now_dt = now or _dt.now()

    if not _has_timestamp_anchor(event):
        return {
            "bucket":         "legacy",
            "natural_bucket": "legacy",
            "event_age_days": 0,
            "ttl_seconds":    0,
            "is_frozen":      False,
            "force_bypassed": False,
            "reason":         "Row has no parsable event_date or timestamp anchor",
        }

    age = event_age_days(event, now_dt)
    natural = _bucket_for_age(age)

    if natural == "frozen" and not force:
        return {
            "bucket":         "frozen",
            "natural_bucket": "frozen",
            "event_age_days": age,
            "ttl_seconds":    None,
            "is_frozen":      True,
            "force_bypassed": False,
            "reason": (
                f"Event is {age}d old (> {_STABLE_MAX_DAYS}d frozen cutoff); "
                f"archived, no refresh"
            ),
        }

    if natural == "frozen" and force:
        return {
            "bucket":         "stable",
            "natural_bucket": "frozen",
            "event_age_days": age,
            "ttl_seconds":    _STABLE_TTL_SECONDS,
            "is_frozen":      True,
            "force_bypassed": True,
            "reason": (
                f"Event is {age}d old (> {_STABLE_MAX_DAYS}d frozen cutoff); "
                f"force=True bypasses freeze"
            ),
        }

    return {
        "bucket":         natural,
        "natural_bucket": natural,
        "event_age_days": age,
        "ttl_seconds":    _ttl_for_bucket(natural),
        "is_frozen":      False,
        "force_bypassed": False,
        "reason": (
            f"Event is {age}d old → {natural} bucket "
            f"({_ttl_for_bucket(natural) // 3600 if _ttl_for_bucket(natural) else 0}h TTL)"
        ),
    }


# ---------------------------------------------------------------------------
# Convenience wrappers — shared by market_check_freshness and api.py
# ---------------------------------------------------------------------------


def is_frozen(event: dict, *, now: Optional[_dt] = None, force: bool = False) -> bool:
    """Should the caller SKIP recomputation on this event?

    This is the operational freeze check used by hot paths that just
    want a yes/no answer: "is this row archived, or should I refresh?"

    Semantics:
      * ``force=True``  → always False.  The caller explicitly opted
        in to a refresh; nothing is frozen from their perspective.
      * ``force=False`` → True iff the event's natural bucket is
        ``frozen`` (age > 30d).

    Callers that want the *underlying truth* (e.g. observability
    layers logging "this was a forced refresh of a frozen row")
    should check ``classify_event_age(...)["natural_bucket"] == 'frozen'``
    or ``is_naturally_frozen()`` below, which never forces.
    """
    if force:
        return False
    return classify_event_age(event, now=now, force=False)["is_frozen"]


def is_naturally_frozen(event: dict, *, now: Optional[_dt] = None) -> bool:
    """Return True iff the event is in the frozen bucket, ignoring force.

    Use this for observability / telemetry when you need to know the
    underlying freeze state regardless of whether the current caller
    opted out of it.
    """
    return classify_event_age(event, now=now, force=False)["is_frozen"]


def bucket_for_event(event: dict, *, now: Optional[_dt] = None) -> str:
    """Return the raw natural bucket string, no force handling."""
    return classify_event_age(event, now=now, force=False)["bucket"]
