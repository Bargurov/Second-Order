"""
movers_ranking.py

Agreement-tier-aware ranking + "why this is still moving" explanation
for the Still Moving Markets surface.

Why this module
---------------
The shipped ranking formula — ``impact = max_move × (1 + support_ratio)``
— is a naive vote-counter multiplied by magnitude.  Two 3% moves rank
identically at 50% support ratio whether the 50% is:

  * a clean direct-proxy hit offset by tape noise (genuinely moving
    with thesis-specific alpha),
  * or a coin-flip split across satellites (no institutional signal).

Since the agreement engine now emits verdict tiers (confirmed /
partial / second_order_only / mixed / weak / direct_miss /
contradicted / insufficient) and per-class counters, the ranker can
separate strong primary-confirmation setups from noisy mixed ones
AND produce a readable "why still moving" explanation — instead of
a lone percentage pill that collapses the nuance.

Pure composer.  No I/O.  Never raises.

Contract
--------
    compute_rank_score(agreement, max_move, persistence_signal=None) -> dict
    build_why_still_moving(event, agreement, big_moves, persistence_signal, decay_info) -> dict
    classify_tier(agreement) -> str
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Tier ladder — maps agreement-engine verdicts to a user-facing tier name
# and a rank weight in [0, 1].  Tiers are ordered: the top deserves the
# "Still moving with alpha" treatment, the bottom is "should not be on
# this surface".
# ---------------------------------------------------------------------------

TIER_ORDER: tuple[str, ...] = (
    "strong_confirmation",     # confirmed with direct support — clean alpha
    "partial_confirmation",    # direct support present but diluted by beta pushback
    "tape_confirmation",       # second_order_only — tape confirms, direct lags
    "mixed",                   # split read, no dominant signal
    "weak_lean",               # beta-led pushback OR direct miss
    "contradicted",            # direct proxies opposed
    "insufficient",            # too few eligible tickers to judge
)


_TIER_WEIGHT: dict[str, float] = {
    "strong_confirmation":   1.00,
    "partial_confirmation":  0.70,
    "tape_confirmation":     0.55,
    "mixed":                 0.40,
    "weak_lean":             0.25,
    "contradicted":          0.10,
    "insufficient":          0.35,   # honest uncertainty, not a penalty
}


_TIER_LABEL: dict[str, str] = {
    "strong_confirmation":   "Strong confirmation",
    "partial_confirmation":  "Partial confirmation",
    "tape_confirmation":     "Tape-led confirmation",
    "mixed":                 "Mixed read",
    "weak_lean":             "Weak — leaning against",
    "contradicted":          "Contradicted",
    "insufficient":          "Insufficient evidence",
}


# Map agreement_engine.verdict → our user-facing tier.  Any verdict we
# don't recognise (future additions) falls through to "mixed" so the
# ranker never crashes on new states.
_VERDICT_TO_TIER: dict[str, str] = {
    "confirmed":          "strong_confirmation",
    "partial":            "partial_confirmation",
    "second_order_only":  "tape_confirmation",
    "mixed":              "mixed",
    "weak":               "weak_lean",
    "direct_miss":        "weak_lean",
    "contradicted":       "contradicted",
    "insufficient":       "insufficient",
}


# Persistence-signal bonuses — already-computed by the
# persistence_signal module.  "Active" setups get a small lift,
# "fading" setups take a penalty so the surface surfaces the rows
# that are STILL in motion.
_PERSISTENCE_BONUS: dict[str, float] = {
    "active":    +0.10,
    "watching":   0.0,
    "fading":    -0.20,
    "resolved":  -0.40,
}


# ---------------------------------------------------------------------------
# Conviction ranking — the richer layer that combines evidence-ladder
# quality with repricing-state quality.  Used to upgrade the Still
# Moving Markets surface so primary-confirmation + durable follow-
# through ranks decisively above a noisy mixed case that merely
# happens to be "moving".
# ---------------------------------------------------------------------------

# Evidence-tier → quality factor (0 - 1).  Preserves the nuance the
# evidence_ladder tier already encodes: primary = clean alpha,
# secondary = tape-led, lagging = direct alone (still credible),
# mixed = weakly tied, contradicted = thesis broken.
_EVIDENCE_QUALITY: dict[str, float] = {
    "primary_confirmation":    1.00,
    "secondary_confirmation":  0.70,
    "lagging":                 0.55,   # direct confirms; cascade pending
    "mixed":                   0.35,
    "contradicted":            0.10,
    "insufficient":            0.40,   # honest uncertainty, not a penalty
}


# Repricing-state → quality factor in [-0.5, +0.5].  Combines with the
# legacy persistence status when the richer repricing state isn't
# available; when BOTH are present the repricing state wins because
# it's the more specific signal.
_REPRICING_QUALITY: dict[str, float] = {
    "second_leg":    +0.50,   # second-wave repricing confirming
    "gap_and_hold":  +0.35,
    "grind":         +0.20,
    "watching":       0.00,
    "retrace":       -0.15,
    "fade":          -0.35,
    "invalidation":  -0.50,
    "resolved":      -0.40,
}


# User-facing conviction classes — five buckets that make the surface
# readable at a glance.
CONVICTION_CLASSES: tuple[str, ...] = (
    "conviction",      # primary + durable follow-through
    "secondary",       # tape confirmation OR primary without follow-through
    "lagging",         # direct alpha with cascade pending
    "noisy_mix",       # mixed evidence, weak persistence
    "breaking",        # contradicted OR invalidation
    "pending",         # insufficient evidence
)


_CONVICTION_LABEL: dict[str, str] = {
    "conviction": "High conviction",
    "secondary":  "Secondary conviction",
    "lagging":    "Lagging — second leg pending",
    "noisy_mix":  "Noisy mixed case",
    "breaking":   "Breaking thesis",
    "pending":    "Pending — insufficient evidence",
}


# ---------------------------------------------------------------------------
# Impact-level quality gates
#
# Beyond evidence_ladder + persistence (already in conviction_score), three
# stored signals further qualify how much a mover's magnitude can be
# trusted: weighted_evidence (the validation aggregate label), proof_status
# (proof-coverage discipline), and thesis_state (composite state word).
#
# ``thesis_state`` is the richer composite — it folds in weighted_evidence
# and proof flags already — so it drives the numeric multiplier.  The other
# two act as hard categorical gates on ``impact_level`` so a falsified /
# low-info / contradicted card cannot be promoted by magnitude alone.
# ---------------------------------------------------------------------------

# Thesis-state multipliers on conviction_score.  None / unrecognised states
# pass through (1.0) so legacy callers without thesis_state are unaffected.
_THESIS_STATE_FACTOR: dict[str, float] = {
    "confirming":      1.10,
    "partial":         1.00,
    "watching":        1.00,
    "weakening":       0.50,
    "stale":           0.40,
    "low_information": 0.20,
    "falsified":       0.10,
}


# Impact-level enum.  Categorical answer the surface uses to decide whether
# a card can lead the list ("high") or just sit in the middle / tail.
IMPACT_LEVELS: tuple[str, ...] = ("low", "medium", "high")


# Minimum magnitude (|return_5d|) before a mover can claim ``high``.  A
# tiny clean confirmation is real but not surface-leading material.
_HIGH_IMPACT_MAGNITUDE_FLOOR: float = 1.5


# Minimum conviction_score before a mover can claim ``high``.  Anchored
# below the canonical fixture (primary + supportive + proof met +
# confirming + second_leg + 3% move ≈ 4.95) so a representative high
# case classifies correctly with comfortable margin.
_HIGH_IMPACT_SCORE_FLOOR: float = 2.5


# Score below which a mover lands in ``low``.  Mirrors the rationale on
# the floor: a near-zero score has no business leading the surface.
_LOW_IMPACT_SCORE_CEILING: float = 0.5


# Thesis states that disqualify ``high`` regardless of magnitude.
_NEVER_HIGH_THESIS_STATES: frozenset[str] = frozenset({
    "low_information", "falsified", "stale", "weakening",
})


# Weighted-evidence labels that disqualify ``high``.
_NEVER_HIGH_EVIDENCE_LABELS: frozenset[str] = frozenset({
    "mixed", "contradictory", "insufficient",
})


# Evidence-ladder tiers that disqualify ``high``.
_NEVER_HIGH_EVIDENCE_TIERS: frozenset[str] = frozenset({
    "contradicted", "insufficient",
})


# Thesis states / evidence labels that force ``low``.
_FORCE_LOW_THESIS_STATES: frozenset[str] = frozenset({
    "low_information", "falsified", "stale",
})

_FORCE_LOW_EVIDENCE_LABELS: frozenset[str] = frozenset({
    "contradictory",
})


def _thesis_state_factor(thesis_state: Optional[str]) -> float:
    if not isinstance(thesis_state, str):
        return 1.0
    return _THESIS_STATE_FACTOR.get(thesis_state.strip().lower(), 1.0)


def compute_impact_level(
    *,
    conviction_score: float,
    max_move: float,
    evidence_tier: Optional[str],
    weighted_evidence: Optional[dict],
    persistence_quality: float,
    thesis_state: Optional[str],
) -> tuple[str, list[str]]:
    """Categorical impact label + ordered list of dominant reasons.

    Hard gates (cannot be high):
      * thesis_state in low_information / falsified / stale / weakening
      * weighted_evidence label in mixed / contradictory / insufficient
      * evidence-ladder tier in contradicted / insufficient
      * persistence_quality fully invalidating (<= -0.45)
      * |max_move| below the magnitude floor
      * conviction_score below the score floor

    Hard gates (forced low):
      * thesis_state in low_information / falsified / stale
      * weighted_evidence label contradictory
      * conviction_score below the low ceiling
    """
    reasons: list[str] = []
    state = (thesis_state or "").strip().lower()
    label = (weighted_evidence or {}).get("evidence_label") if isinstance(weighted_evidence, dict) else None
    label = (label or "").strip().lower() or None
    tier = (evidence_tier or "").strip().lower() or None
    mag = abs(float(max_move or 0.0))

    # --- Force-low gates ---------------------------------------------------
    if state in _FORCE_LOW_THESIS_STATES:
        reasons.append(f"thesis_state={state} blocks promotion")
        return "low", reasons
    if label in _FORCE_LOW_EVIDENCE_LABELS:
        reasons.append("weighted_evidence is contradictory")
        return "low", reasons
    if tier == "contradicted":
        reasons.append("evidence ladder reads contradicted")
        return "low", reasons
    if conviction_score < _LOW_IMPACT_SCORE_CEILING:
        reasons.append(
            f"conviction_score {conviction_score:.2f} below low ceiling"
        )
        return "low", reasons

    # --- Disqualifiers for ``high`` ---------------------------------------
    blocked: list[str] = []
    if state in _NEVER_HIGH_THESIS_STATES:
        blocked.append(f"thesis_state={state}")
    if label in _NEVER_HIGH_EVIDENCE_LABELS:
        blocked.append(f"weighted_evidence={label}")
    if tier in _NEVER_HIGH_EVIDENCE_TIERS:
        blocked.append(f"evidence_tier={tier}")
    if persistence_quality <= -0.45:
        blocked.append("persistence invalidating")
    if mag < _HIGH_IMPACT_MAGNITUDE_FLOOR:
        blocked.append(
            f"magnitude {mag:.1f}% below {_HIGH_IMPACT_MAGNITUDE_FLOOR:.1f}% floor"
        )
    if conviction_score < _HIGH_IMPACT_SCORE_FLOOR:
        blocked.append(
            f"conviction_score {conviction_score:.2f} below high floor"
        )

    if not blocked:
        reasons.append("primary evidence + supportive aggregate clears all gates")
        return "high", reasons

    reasons.append("blocked from high: " + "; ".join(blocked))
    return "medium", reasons


def _repricing_quality(persistence_signal: Optional[dict]) -> tuple[float, Optional[str]]:
    """Return ``(quality_factor, repricing_state_used)`` from the
    persistence signal.  Prefers the richer repricing_state; falls
    back to the coarse persistence status when unavailable."""
    if not isinstance(persistence_signal, dict):
        return 0.0, None
    rp = persistence_signal.get("repricing") or {}
    state = rp.get("state") if isinstance(rp, dict) else None
    if isinstance(state, str) and state in _REPRICING_QUALITY:
        return _REPRICING_QUALITY[state], state
    # Legacy fallback — the coarse active/watching/fading/resolved.
    status = persistence_signal.get("status")
    if isinstance(status, str) and status in _PERSISTENCE_BONUS:
        return _PERSISTENCE_BONUS[status], status
    return 0.0, None


def _conviction_class(
    evidence_tier: str,
    evidence_quality: float,
    persistence_quality: float,
) -> str:
    """Bucket the (evidence × persistence) pair into the five user-
    facing conviction classes.  The thresholds are picked so the
    edge cases read correctly:

      * primary + positive repricing → conviction
      * primary alone → secondary (ranked high but not conviction-tier)
      * lagging tier → lagging (preserved as its own bucket)
      * mixed × weak persistence → noisy_mix
      * contradicted / invalidation → breaking
    """
    if evidence_tier == "insufficient":
        return "pending"
    if evidence_tier == "contradicted":
        return "breaking"
    if persistence_quality <= -0.45:
        # Invalidation / resolved override the evidence tier — even a
        # "primary" card with a fully resolved setup isn't conviction.
        return "breaking" if evidence_tier == "contradicted" else "pending"
    if evidence_tier == "lagging":
        return "lagging"
    if evidence_tier == "primary_confirmation" and persistence_quality >= 0.15:
        return "conviction"
    if evidence_tier == "primary_confirmation":
        return "secondary"
    if evidence_tier == "secondary_confirmation":
        return "secondary"
    # mixed — noisy by construction
    return "noisy_mix"


def compute_conviction_rank(
    evidence: Optional[dict],
    max_move: float,
    *,
    persistence_signal: Optional[dict] = None,
    weighted_evidence: Optional[dict] = None,
    proof_status: Optional[dict] = None,
    thesis_state: Optional[str] = None,
) -> dict[str, Any]:
    """Conviction-ranking layer — the combined evidence × persistence
    score that Still Moving Markets sorts on.

    Inputs
    ------
    evidence:
        The dict emitted by ``evidence_ladder.classify_evidence`` —
        carries the 5-rung tier + reason_code.  Missing or malformed
        input folds to the ``pending`` class.
    max_move:
        The |return_5d| magnitude of the card's top ticker.
    persistence_signal:
        The event's ``persistence_signal`` dict — the ``repricing``
        block inside drives the richer quality factor; falls back to
        the coarse ``status`` when the repricing block is absent.

    Returns a dict with:

      * ``conviction_class`` — one of CONVICTION_CLASSES
      * ``conviction_label`` — UI-quotable short string
      * ``conviction_score`` — the scalar Still Moving Markets sorts on
      * ``evidence_quality`` — 0..1 factor from the evidence tier
      * ``persistence_quality`` — -0.5..+0.5 factor from repricing state
      * ``repricing_state`` — the repricing_state used (when any)
      * ``why_ranks_here`` — 1-3 ordered bullet strings explaining the
        ranking position (e.g. ["Primary confirmation", "Second-leg
        repricing", "Durable follow-through"])
      * ``rationale`` — single-line audit string for telemetry / logs
    """
    tier = (evidence.get("tier") if isinstance(evidence, dict) else None) or "insufficient"
    evidence_quality = _EVIDENCE_QUALITY.get(tier, 0.4)

    persistence_quality, repricing_used = _repricing_quality(persistence_signal)

    # Core score.  Magnitude × evidence quality × (1 + persistence).
    # Clamped ≥ 0 — a mover card is never "negatively interesting".
    mag = max(0.0, float(max_move or 0.0))
    score = mag * evidence_quality * (1.0 + persistence_quality)

    # Thesis-state multiplier — single composite gate that folds in
    # weighted_evidence + proof flags + persistence (the state is derived
    # from those upstream).  Using the composite avoids double-counting
    # the same signals via separate weighted_evidence / proof_status
    # multipliers.  None / unrecognised states pass through unchanged so
    # legacy callers without thesis_state are unaffected.
    score *= _thesis_state_factor(thesis_state)
    score = max(0.0, round(score, 3))

    conviction_class = _conviction_class(
        tier, evidence_quality, persistence_quality,
    )

    # Explanation — ordered by what actually drove the ranking.  Keep
    # it tight: primary driver first, persistence tag next, reason
    # code third.  A reader should scan this in one glance.
    why: list[str] = []
    if tier == "primary_confirmation":
        why.append("Primary confirmation: direct / bottleneck alpha leading")
    elif tier == "secondary_confirmation":
        why.append("Secondary confirmation: cross-asset tape carrying the read")
    elif tier == "lagging":
        why.append("Lagging: direct proxies confirm; cascade pending")
    elif tier == "mixed":
        why.append("Mixed evidence — weak thesis tie")
    elif tier == "contradicted":
        why.append("Contradicted: direct proxies moved against")
    elif tier == "insufficient":
        why.append("Insufficient evidence to judge")

    # Persistence / repricing tag — only when it meaningfully shifts
    # the ranking one way or the other.
    if repricing_used == "second_leg":
        why.append("Second-leg repricing: tape has caught up after the gap")
    elif repricing_used == "gap_and_hold":
        why.append("Durable follow-through: gap holding past the initial move")
    elif repricing_used == "grind":
        why.append("Steady grind — slow but still thesis-positive")
    elif repricing_used in ("fade", "retrace"):
        why.append("Follow-through fading — signal decaying")
    elif repricing_used == "invalidation":
        why.append("Invalidation — setup has broken down")
    elif repricing_used == "resolved":
        why.append("Setup resolved — archive value only")
    elif repricing_used == "active":
        why.append("Persistence active — thesis still playing out")
    elif repricing_used == "fading":
        why.append("Persistence fading — monitor before leaning further")

    # Reason-code tag — surfaces the specific failure mode for the
    # non-primary tiers so the reader sees WHY ranking got docked.
    reason_code = (evidence.get("reason_code") if isinstance(evidence, dict) else None)
    reason_label = (evidence.get("reason_label") if isinstance(evidence, dict) else None)
    if conviction_class in ("noisy_mix", "lagging", "secondary") and reason_label:
        # Don't double-report if the reason is the same as the tier.
        if reason_code and reason_code != "primary_proxy_confirming":
            why.append(f"Reason: {reason_label}")

    rationale = (
        f"{mag:.1f}% × evidence {evidence_quality:.2f} ({tier}) "
        f"× (1 + persistence {persistence_quality:+.2f}"
        + (f" from {repricing_used}" if repricing_used else "")
        + f") → {score:.2f}"
    )

    # Categorical impact gate — hard rules from thesis_state +
    # weighted_evidence + evidence ladder + persistence + magnitude.
    # The numeric ``conviction_score`` handles graceful degradation;
    # this categorical answer enforces the must-not-promote rules so a
    # huge move on mixed / low-info evidence cannot lead the surface.
    impact_level, impact_reasons = compute_impact_level(
        conviction_score=score,
        max_move=mag,
        evidence_tier=tier,
        weighted_evidence=weighted_evidence,
        persistence_quality=persistence_quality,
        thesis_state=thesis_state,
    )

    # Proof discipline tag — read-only context.  Surfaced on the dict
    # so consumers can render "proof met / unmet / partial / none"
    # without re-fetching the event.  Does not feed the numeric score
    # (thesis_state already captures proof-coverage).
    proof_status_str: Optional[str] = None
    if isinstance(proof_status, dict):
        ps = proof_status.get("status")
        if isinstance(ps, str) and ps:
            proof_status_str = ps

    return {
        "conviction_class":     conviction_class,
        "conviction_label":     _CONVICTION_LABEL.get(
            conviction_class, conviction_class.replace("_", " "),
        ),
        "conviction_score":     score,
        "evidence_quality":     round(evidence_quality, 3),
        "persistence_quality":  round(persistence_quality, 3),
        "repricing_state":      repricing_used,
        "thesis_state":         thesis_state,
        "proof_status":         proof_status_str,
        "impact_level":         impact_level,
        "impact_reasons":       impact_reasons,
        "why_ranks_here":       why[:3],
        "rationale":            rationale,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def classify_tier(agreement: Optional[dict]) -> str:
    """Map an agreement-engine verdict dict to a mover-surface tier."""
    if not isinstance(agreement, dict):
        return "insufficient"
    verdict = agreement.get("verdict") or "insufficient"
    return _VERDICT_TO_TIER.get(verdict, "mixed")


# ---------------------------------------------------------------------------
# Rank score — the scalar the movers surface sorts on
# ---------------------------------------------------------------------------

def compute_rank_score(
    agreement: Optional[dict],
    max_move: float,
    *,
    persistence_signal: Optional[dict] = None,
) -> dict[str, Any]:
    """Compute the tier-aware rank score for a mover card.

    Design intent:

      * Magnitude still matters — a 0.5% move can't out-rank a 3% move
        on conviction alone.  ``max_move`` is the primary amplifier.
      * Agreement tier scales the magnitude (0.1× contradicted →
        1.0× strong_confirmation).  A 3% move with contradicting
        direct proxies reads as "0.3 unit of impact" while the same
        magnitude with strong alpha support reads as 3.0 units.
      * Persistence is an additive bonus / penalty on a 0-1 scale
        multiplied by the already-tier-weighted magnitude.  A fading
        5% move shouldn't dominate a mild but still-active 3% move.
      * Mixed / partial tiers are preserved as middle-of-the-road
        weights (0.4 / 0.7) — they DON'T collapse to a flat low score.

    Returns::

        {
          "tier":         str,          # user-facing tier name
          "tier_label":   str,          # short UI label
          "tier_weight":  float,        # in [0, 1]
          "rank_score":   float,        # the scalar the surface sorts on
          "rationale":    str,          # one-line "why this score"
        }
    """
    mag = max(0.0, _f(max_move) or 0.0)
    tier = classify_tier(agreement)
    tier_weight = _TIER_WEIGHT.get(tier, 0.4)

    # Core: magnitude × tier weight.  A confirmation tier preserves
    # the full magnitude; a contradicted tier floors at 10% of it.
    base = mag * tier_weight

    # Persistence overlay — additive factor on the base score so an
    # actively-persisting setup can overtake a fresher but fading one.
    persistence_state = None
    persistence_factor = 0.0
    if isinstance(persistence_signal, dict):
        persistence_state = persistence_signal.get("status")
        if isinstance(persistence_state, str):
            persistence_factor = _PERSISTENCE_BONUS.get(persistence_state, 0.0)
    score = base * (1.0 + persistence_factor)

    # Final clamp — a persistence penalty can't drive the score below
    # zero; a mover card is never "negatively interesting".
    score = max(0.0, round(score, 3))

    # Rationale line — compact enough for telemetry / log inspection.
    bits: list[str] = [
        f"{mag:.1f}% × {tier_weight:.2f} ({tier})",
    ]
    if persistence_state and persistence_factor != 0.0:
        sign = "+" if persistence_factor > 0 else ""
        bits.append(f"persistence {persistence_state} {sign}{int(persistence_factor*100)}%")
    rationale = " · ".join(bits)

    return {
        "tier":         tier,
        "tier_label":   _TIER_LABEL.get(tier, tier.replace("_", " ")),
        "tier_weight":  tier_weight,
        "rank_score":   score,
        "rationale":    rationale,
    }


# ---------------------------------------------------------------------------
# "Why this is still moving" — structured explanation
# ---------------------------------------------------------------------------

def _top_ticker(big_moves: Optional[list[dict]]) -> Optional[dict]:
    """Highest-|return_5d| ticker; None when the list is empty."""
    if not big_moves:
        return None
    usable = [t for t in big_moves if isinstance(t, dict) and t.get("return_5d") is not None]
    if not usable:
        return None
    return max(usable, key=lambda t: abs(_f(t.get("return_5d")) or 0.0))


def _decay_warning(decay_info: Optional[dict]) -> Optional[str]:
    """Extract a readable decay warning when the follow-through is
    fading — returns None when there's nothing to flag."""
    if not isinstance(decay_info, dict):
        return None
    label = decay_info.get("label")
    if label in (None, "sustaining", "accelerating"):
        return None
    evidence = decay_info.get("evidence") or ""
    return f"Follow-through {label}" + (f" — {evidence}" if evidence else "")


def build_why_still_moving(
    event: Optional[dict],
    agreement: Optional[dict],
    big_moves: Optional[list[dict]] = None,
    *,
    persistence_signal: Optional[dict] = None,
    decay_info: Optional[dict] = None,
) -> dict[str, Any]:
    """Return a structured "why still moving" block for a mover card.

    The block is deliberately small — a one-line ``headline`` the
    frontend can quote, 2-4 ``reason_lines`` a reader scans, and a
    ``watch_signals`` list a desk can monitor.  Missing inputs degrade
    to empty lists; the block never raises.
    """
    agreement = agreement or {}
    event = event or {}

    tier = classify_tier(agreement)
    tier_label = _TIER_LABEL.get(tier, tier)

    top = _top_ticker(big_moves)
    top_symbol = top.get("symbol") if top else None
    top_r5 = _f(top.get("return_5d")) if top else None

    # Headline — one line a desk would actually quote.
    if top_symbol and top_r5 is not None:
        sign = "+" if top_r5 >= 0 else ""
        headline = f"{top_symbol} {sign}{top_r5:.1f}% / 5d · {tier_label}"
    elif top_symbol:
        headline = f"{top_symbol} leading · {tier_label}"
    else:
        headline = tier_label

    reason_lines: list[str] = []

    # 1. Agreement line — verbatim from the agreement engine's reason.
    agreement_reason = agreement.get("reason")
    if isinstance(agreement_reason, str) and agreement_reason:
        reason_lines.append(f"Validation: {agreement_reason}")

    # 2. Persistence line — active / fading / resolved state + evidence.
    if isinstance(persistence_signal, dict):
        p_status = persistence_signal.get("status")
        p_label = persistence_signal.get("label")
        p_evidence = persistence_signal.get("evidence")
        if p_status and p_status != "watching":
            line = f"Persistence: {p_label or p_status}"
            if p_evidence:
                line += f" — {p_evidence}"
            reason_lines.append(line)

    # 3. Decay warning — when follow-through is fading it deserves a
    # visible flag on the surface.
    decay_line = _decay_warning(decay_info)
    if decay_line:
        reason_lines.append(decay_line)

    # 4. Direct-vs-second-order split — compact counter so the reader
    # sees how the tier was earned without a full click-through.
    d_sup = int(agreement.get("direct_support", 0) or 0)
    d_con = int(agreement.get("direct_contradict", 0) or 0)
    s_sup = int(agreement.get("second_order_support", 0) or 0)
    s_con = int(agreement.get("second_order_contradict", 0) or 0)
    if (d_sup + d_con + s_sup + s_con) > 0:
        reason_lines.append(
            f"Proxy split: {d_sup}/{d_con} direct, {s_sup}/{s_con} tape"
        )

    # Watch signals — what would flip the read.  Keep it tight; the
    # sector surface shouldn't duplicate the analyze page's "what
    # would change the read" bullets.
    watch_signals: list[str] = []
    if tier == "partial_confirmation":
        watch_signals.append(
            "Direct proxies need to hold as beta noise fades for partial → strong"
        )
    elif tier == "tape_confirmation":
        watch_signals.append(
            "Direct proxies still silent — watch for an alpha-move to lock in"
        )
    elif tier in ("mixed", "weak_lean"):
        watch_signals.append(
            "Needs a direct-proxy break one way or the other to resolve"
        )
    elif tier == "contradicted":
        watch_signals.append(
            "Thesis needs to find new proxies OR concede — current basket has broken"
        )

    # If persistence is fading/resolved, surface the revisit angle.
    if isinstance(persistence_signal, dict):
        if persistence_signal.get("status") == "fading":
            watch_signals.append(
                "Follow-through is fading; re-score before leaning further"
            )
        elif persistence_signal.get("status") == "resolved":
            watch_signals.append(
                "Setup has resolved — card is primarily archive value"
            )

    return {
        "headline":       headline,
        "tier":           tier,
        "tier_label":     tier_label,
        "reason_lines":   reason_lines,
        "watch_signals":  watch_signals,
    }
