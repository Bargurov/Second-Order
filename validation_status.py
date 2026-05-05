"""validation_status.py

Pure event-level validation-status scorer.  See
``docs/validation_status_design.md`` for the design rationale; this
module implements the four-label vocabulary spelled out in §2:

    validated | contradicted | unresolved | pending

The function is deliberately I/O-free: no DB, no provider calls, no
clock reads other than the explicit ``now`` kwarg (which defaults to
``datetime.now()`` when omitted).  Every decision is derived from the
event dict the caller passes in.

The function refines — does not replace — the legacy
``score_validation_outcome`` in ``validation_outcome.py``.  The legacy
function continues to exist for callers that bind to its
``(label, ratio)`` tuple shape; this module is the new four-label
surface and is the one new code should call.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from event_age_policy import _WARM_MAX_DAYS, classify_event_age

# Pending window — design §4.4 explicitly reuses ``_WARM_MAX_DAYS`` so
# the vocabulary here ("pending" → "warm") stays aligned with the
# freshness-bucket policy.  If calibration later wants a different
# boundary, pin it here with a comment explaining the divergence.
_PENDING_MAX_DAYS: int = _WARM_MAX_DAYS

VALID_STATUSES: tuple = ("validated", "contradicted", "unresolved", "pending")


# ---------------------------------------------------------------------------
# Internal helpers — keep small and pure.
# ---------------------------------------------------------------------------


def _safe_number(v: Any) -> Optional[float]:
    """Return ``v`` as a finite float, or None for booleans / NaN / non-numeric."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    return None


def _has_thesis(event: dict) -> bool:
    """True when the event carries a usable thesis classification.

    Design §3 references ``thesis_*`` fields generically; in this
    schema they map to ``mechanism_summary``, ``what_changed``, and
    ``mechanism_family`` (set to a non-empty / non-"none" value).
    Any one populated counts.
    """
    if not isinstance(event, dict):
        return False
    for key in ("mechanism_summary", "what_changed"):
        v = event.get(key)
        if isinstance(v, str) and v.strip():
            return True
    fam = event.get("mechanism_family")
    if isinstance(fam, str) and fam.strip().lower() not in ("", "none", "unknown"):
        return True
    return False


def _gather_ticker_signals(tickers: Any) -> dict:
    """Walk ``tickers`` once; return raw counters + discriminator flags."""
    signals = {
        "total":         0,
        "tagged":        0,
        "supporting":    0,
        "contradicting": 0,
        "has_role":      False,
        "has_return_1d": False,
    }
    if not isinstance(tickers, list):
        return signals
    signals["total"] = len(tickers)
    for t in tickers:
        if not isinstance(t, dict):
            continue
        tag = t.get("direction_tag")
        if isinstance(tag, str) and tag:
            signals["tagged"] += 1
            tag_l = tag.strip().lower()
            if tag_l.startswith("supports"):
                signals["supporting"] += 1
            elif tag_l.startswith("contradicts"):
                signals["contradicting"] += 1
        role = t.get("role")
        if isinstance(role, str) and role.strip().lower() in ("beneficiary", "loser"):
            signals["has_role"] = True
        if _safe_number(t.get("return_1d")) is not None:
            signals["has_return_1d"] = True
    return signals


def _result(
    *,
    status: str,
    reason: str,
    ratio: Optional[float],
    signals: dict,
    age_days: int,
) -> dict:
    return {
        "status":           status,
        "reason":           reason,
        "ratio":            ratio,
        "counts": {
            "total_tickers":  signals["total"],
            "tagged_tickers": signals["tagged"],
            "directional":    signals["supporting"] + signals["contradicting"],
            "supporting":     signals["supporting"],
            "contradicting":  signals["contradicting"],
        },
        "event_age_days":   age_days,
        "pending_max_days": _PENDING_MAX_DAYS,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def score_validation_status(
    event: dict,
    *,
    now: Optional[datetime] = None,
) -> dict:
    """Classify an event into one of four validation statuses.

    Parameters
    ----------
    event:
        Event row dict.  The function reads ``market_tickers``,
        ``event_date`` / ``timestamp`` (for age), and the thesis fields
        (``mechanism_summary`` / ``what_changed`` / ``mechanism_family``)
        as a discriminator.  Missing or malformed fields never raise;
        the function falls back to safe defaults.
    now:
        Explicit clock for testability.  Defaults to ``datetime.now()``
        via :func:`event_age_policy.classify_event_age`.  Passing the
        same ``event`` with two different ``now`` values is the only
        way to advance time in tests.

    Returns
    -------
    dict
        Stable shape — see ``VALID_STATUSES`` for ``status`` values and
        the return-shape contract in
        ``tests/test_validation_status.py::TestReturnShape``.

    The function is total: it always returns a dict; never raises.
    Backfill semantics fall out automatically — any event with
    ``event_age_days > _PENDING_MAX_DAYS`` and no directional evidence
    is ``unresolved``, never ``pending`` (design §6).
    """
    if not isinstance(event, dict):
        event = {}

    signals = _gather_ticker_signals(event.get("market_tickers"))
    directional = signals["supporting"] + signals["contradicting"]

    # Compute age once — needed for observability on every branch and
    # for the legacy / past-window branches below.
    age_info = classify_event_age(event, now=now)
    age_days = age_info["event_age_days"]
    natural_bucket = age_info["natural_bucket"]

    # ---- 1. Majority rule (design §4.2.1, preserved verbatim) -------------
    if directional > 0:
        ratio = signals["supporting"] / directional
        if signals["supporting"] > signals["contradicting"]:
            label = "validated"
        else:
            # Catches ties (supports == contradicts) and contradicting
            # majorities alike — design §5 row 8 fixes this rule.
            label = "contradicted"
        return _result(
            status=label,
            reason=(
                f"{signals['supporting']} supports vs "
                f"{signals['contradicting']} contradicts "
                f"({signals['total']} tickers); ratio {ratio:.2f}"
            ),
            ratio=round(ratio, 4),
            signals=signals,
            age_days=age_days,
        )

    # ---- 2. No directional evidence — pending vs unresolved ---------------

    # Tagged tickers exist but every tag is neutral / unknown-prefix
    # (e.g. "needs more evidence", "pending").  The classifier ran and
    # abstained — waiting will not change the answer (design §5).
    if signals["tagged"] > 0:
        return _result(
            status="unresolved",
            reason=(
                f"{signals['tagged']} tagged tickers but none directional; "
                f"classifier abstained"
            ),
            ratio=None,
            signals=signals,
            age_days=age_days,
        )

    # Legacy bucket = missing / unparsable anchor.  We can't evaluate
    # the pending window without an anchor; do not optimistically
    # pending (design §5 last row).
    if natural_bucket == "legacy":
        return _result(
            status="unresolved",
            reason="no parsable event_date / timestamp anchor",
            ratio=None,
            signals=signals,
            age_days=age_days,
        )

    # Past the pending window — even with all the discriminator
    # signals in the world, an old row without directional evidence is
    # unresolved.  This is what makes backfill safe: any historical
    # row falls through to here automatically (design §6).
    if age_days > _PENDING_MAX_DAYS:
        return _result(
            status="unresolved",
            reason=(
                f"event {age_days}d old (> {_PENDING_MAX_DAYS}d pending "
                f"window); no directional evidence"
            ),
            ratio=None,
            signals=signals,
            age_days=age_days,
        )

    # Within the pending window — apply the §4.3 discriminator.
    has_thesis = _has_thesis(event)
    discriminator_satisfied = (
        has_thesis or signals["has_role"] or signals["has_return_1d"]
    )

    if discriminator_satisfied:
        bits: list[str] = []
        if has_thesis:
            bits.append("thesis present")
        if signals["has_role"]:
            bits.append("≥1 ticker has role")
        if signals["has_return_1d"]:
            bits.append("≥1 ticker has 1d return")
        return _result(
            status="pending",
            reason=(
                f"event {age_days}d old (≤ {_PENDING_MAX_DAYS}d window); "
                f"no directional tags yet ({', '.join(bits)})"
            ),
            ratio=None,
            signals=signals,
            age_days=age_days,
        )

    return _result(
        status="unresolved",
        reason=(
            f"event {age_days}d old; no thesis, no role, no 1d returns — "
            f"no scorable surface"
        ),
        ratio=None,
        signals=signals,
        age_days=age_days,
    )
