"""
reaction_window.py

Priced-in / reaction-window detection.

Given a saved event, compose a compact ``reaction_window`` block that
captures whether the thesis-aligned move happened BEFORE the event
timestamp (priced in) versus AFTER (real reaction).  The block flags
``priced_in_risk`` so downstream gates can withhold a confirming verdict
when most of the move was already in the tape before the headline.

Output shape (additive — never replaces existing fields):

    {
      "available":       bool,            # False on thin / missing data
      "pre_event_move":  float | None,    # role-aligned 5d drift INTO the event
      "post_event_move": float | None,    # role-aligned aggregate return AFTER
      "priced_in_risk":  "low" | "medium" | "high",
      "rationale":       str,             # one short audit line
    }

Pure composer.  No I/O.  No fetches.  Reads only fields already on the
event:

  * ``surprise_vs_anticipation.debug.pre_event_drift_pct`` (preferred)
    OR a per-ticker ``pre_event_drift`` field if upstream stamped it.
  * ``market_tickers[*].return_5d`` (role-aligned post-event read).
  * ``stage`` — ``anticipation`` / ``surprise`` / ``realized`` —
    drives the priced-in threshold.  Anticipation events tolerate
    larger pre-event drift because that's the intended dynamic; a
    surprise event with the same pre-drift is leakier and the gate
    fires earlier.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Stage-aware priced-in thresholds
# ---------------------------------------------------------------------------
# Anticipation events: tolerate up to ~5% aligned pre-drift before the
# desk treats the move as priced in.  An anticipation thesis is
# explicitly about "what the tape will do BEFORE the event" — pre-drift
# in the thesis direction is signal, not leak.
#
# Surprise / realized events: tighter threshold (~2% aligned pre-drift)
# because pre-event movement on a surprise event is information leak,
# not anticipation.

_PRE_DRIFT_HIGH_ANTICIPATION: float = 5.0   # |%|
_PRE_DRIFT_HIGH_DEFAULT:      float = 2.0   # |%|

# Medium-band breakpoints — tighter than the high band by ~half so the
# medium tier fires for cases where pre-drift is meaningful but not
# dominating.
_PRE_DRIFT_MED_ANTICIPATION:  float = 2.5
_PRE_DRIFT_MED_DEFAULT:       float = 1.0

# Post-event-leads ratio — when |post| ≥ ratio × |pre|, the post-event
# move is large enough that the priced-in concern fades regardless of
# pre-drift size.
_POST_LEADS_RATIO: float = 0.75


def _safe_float(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    return None


def _role_for_ticker(t: dict, *, beneficiary_set: set[str], loser_set: set[str]) -> Optional[str]:
    """Return ``"beneficiary"`` / ``"loser"`` / ``None`` for the
    ticker.  Prefers an explicit ``role`` field on the ticker; falls
    back to membership in the event's beneficiary / loser ticker
    lists."""
    role = t.get("role")
    if isinstance(role, str) and role.lower() in ("beneficiary", "loser"):
        return role.lower()
    sym = t.get("symbol")
    if isinstance(sym, str):
        s = sym.strip().upper()
        if s in beneficiary_set:
            return "beneficiary"
        if s in loser_set:
            return "loser"
    return None


def _aligned_value(value: float, role: str) -> float:
    """Flip sign for losers so the role-aligned move reads positive
    when the thesis is supported."""
    return value if role == "beneficiary" else -value


def _aggregate_post_event_move(event: dict) -> Optional[float]:
    """Average of role-aligned return_5d across direct-name primary
    tickers in market_tickers.  Excludes tickers with missing returns
    or unknown roles.  Returns None when the basket is too thin to
    score."""
    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or not tickers:
        return None

    benef = event.get("beneficiary_tickers") or []
    losers = event.get("loser_tickers") or []
    benef_set = {s.strip().upper() for s in benef if isinstance(s, str)}
    loser_set = {s.strip().upper() for s in losers if isinstance(s, str)}

    aligned: list[float] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        role = _role_for_ticker(t, beneficiary_set=benef_set, loser_set=loser_set)
        if role is None:
            continue
        r5 = _safe_float(t.get("return_5d"))
        if r5 is None:
            continue
        aligned.append(_aligned_value(r5, role))

    if not aligned:
        return None
    return round(sum(aligned) / len(aligned), 3)


def _aggregate_pre_event_move(event: dict) -> Optional[float]:
    """Pull the role-aligned pre-event drift the surprise / anticipation
    composer already saved.  Falls back to per-ticker ``pre_event_drift``
    if upstream stamped it directly on each ticker."""
    sva = event.get("surprise_vs_anticipation")
    if isinstance(sva, dict):
        debug = sva.get("debug")
        if isinstance(debug, dict):
            v = _safe_float(debug.get("pre_event_drift_pct"))
            if v is not None:
                return round(v, 3)
        v = _safe_float(sva.get("pre_event_drift_pct"))
        if v is not None:
            return round(v, 3)

    # Per-ticker fallback — average aligned ``pre_event_drift`` field
    # when upstream stamped it directly on tickers.
    tickers = event.get("market_tickers")
    if not isinstance(tickers, list) or not tickers:
        return None
    benef = event.get("beneficiary_tickers") or []
    losers = event.get("loser_tickers") or []
    benef_set = {s.strip().upper() for s in benef if isinstance(s, str)}
    loser_set = {s.strip().upper() for s in losers if isinstance(s, str)}
    aligned: list[float] = []
    for t in tickers:
        if not isinstance(t, dict):
            continue
        role = _role_for_ticker(t, beneficiary_set=benef_set, loser_set=loser_set)
        if role is None:
            continue
        v = _safe_float(t.get("pre_event_drift"))
        if v is None:
            continue
        aligned.append(_aligned_value(v, role))
    if not aligned:
        return None
    return round(sum(aligned) / len(aligned), 3)


def _stage_thresholds(stage: Any) -> tuple[float, float]:
    """Return ``(high_threshold, medium_threshold)`` keyed on stage.
    Anticipation events tolerate larger pre-drift; surprise / realized
    use the default tighter threshold."""
    s = stage.strip().lower() if isinstance(stage, str) else ""
    if s == "anticipation":
        return _PRE_DRIFT_HIGH_ANTICIPATION, _PRE_DRIFT_MED_ANTICIPATION
    return _PRE_DRIFT_HIGH_DEFAULT, _PRE_DRIFT_MED_DEFAULT


def _classify_priced_in_risk(
    pre_move: Optional[float],
    post_move: Optional[float],
    stage: Any,
) -> str:
    """Classify the priced-in risk for the event.

    Logic:
      * No pre-event data        → ``low`` (we can't claim priced-in
                                   without evidence).
      * Pre-drift is contradicting (negative aligned)
                                  → ``low`` (the tape was on the wrong
                                    side, not pricing the thesis in).
      * Post-event move is small AND pre-drift cleared the high-threshold
                                  → ``high``.
      * Post-event move clears _POST_LEADS_RATIO × |pre|
                                  → ``low`` (tape is leading, not
                                    catching up).
      * Pre-drift between medium and high, post weak
                                  → ``medium``.
      * Otherwise                 → ``low``.
    """
    if pre_move is None:
        return "low"
    if pre_move <= 0:
        # Aligned pre-drift is non-positive — the tape was either flat
        # or against the thesis.  No priced-in risk.
        return "low"

    high_thr, med_thr = _stage_thresholds(stage)
    abs_pre = abs(pre_move)

    if post_move is not None:
        abs_post = abs(post_move)
        # When post-event move is at least 75% of pre-drift in any
        # direction, the post tape is leading — priced-in risk fades.
        if abs_pre > 0 and abs_post >= _POST_LEADS_RATIO * abs_pre:
            return "low"

    if abs_pre >= high_thr:
        return "high"
    if abs_pre >= med_thr:
        return "medium"
    return "low"


def _rationale(
    pre_move: Optional[float],
    post_move: Optional[float],
    priced_in_risk: str,
    stage: Any,
) -> str:
    """One-line audit string explaining the priced_in_risk verdict."""
    s = stage.strip().lower() if isinstance(stage, str) else "unspecified"
    if pre_move is None:
        return f"No pre-event drift available; priced_in_risk={priced_in_risk}"
    pre_str = f"{pre_move:+.2f}%"
    post_str = f"{post_move:+.2f}%" if post_move is not None else "n/a"
    if priced_in_risk == "high":
        return (
            f"Most of the thesis-aligned move ({pre_str}) happened BEFORE "
            f"the event; post-event tape ({post_str}) is weak — stage="
            f"{s} treats this as priced-in."
        )
    if priced_in_risk == "medium":
        return (
            f"Pre-event drift {pre_str} is meaningful relative to "
            f"post-event move {post_str}; partial priced-in concern "
            f"under stage={s}."
        )
    return (
        f"Pre-event drift {pre_str} vs post-event {post_str}; tape "
        f"reaction is the dominant move — priced-in risk low."
    )


def compute_reaction_window(event: Any) -> dict[str, Any]:
    """Return the additive ``reaction_window`` block for ``event``.

    See module docstring for the field contract.  Returns
    ``{"available": False, ...}`` with a stable empty shape when the
    event lacks both the SVA debug field and per-ticker pre-event
    drift — consumers can render the block unconditionally without
    null checks.
    """
    empty: dict[str, Any] = {
        "available":       False,
        "pre_event_move":  None,
        "post_event_move": None,
        "priced_in_risk":  "low",
        "rationale":       "No reaction-window data available.",
    }
    if not isinstance(event, dict):
        return empty

    pre_move = _aggregate_pre_event_move(event)
    post_move = _aggregate_post_event_move(event)
    if pre_move is None and post_move is None:
        return empty

    stage = event.get("stage")
    priced_in_risk = _classify_priced_in_risk(pre_move, post_move, stage)
    rationale = _rationale(pre_move, post_move, priced_in_risk, stage)

    return {
        "available":       True,
        "pre_event_move":  pre_move,
        "post_event_move": post_move,
        "priced_in_risk":  priced_in_risk,
        "rationale":       rationale,
    }


def reaction_window_blocks_confirmation(event: Any) -> bool:
    """True when the reaction_window is in a state that should block a
    confirming verdict — i.e. priced_in_risk is high AND the
    post-event move is weak relative to pre-event drift.

    Pure read; safe to call on events without a reaction_window
    block (returns False).  Used by ``thesis_state`` to gate the
    confirming → mixed downgrade.
    """
    if not isinstance(event, dict):
        return False
    block = event.get("reaction_window")
    if not isinstance(block, dict):
        block = compute_reaction_window(event)
    if not block.get("available"):
        return False
    if block.get("priced_in_risk") != "high":
        return False
    pre = _safe_float(block.get("pre_event_move"))
    post = _safe_float(block.get("post_event_move"))
    if pre is None:
        return False
    # When the post tape leads (≥ ratio × pre), the priced-in
    # concern fades and the gate doesn't fire.
    if post is not None and abs(pre) > 0 and abs(post) >= _POST_LEADS_RATIO * abs(pre):
        return False
    return True
