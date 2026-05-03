"""
evidence_ladder.py

5-rung evidence-ladder read for Still Moving Markets.

Why this module
---------------
The agreement engine and the mover-ranking layer already carry
verdicts and tier weights — but downstream consumers (the Still
Moving surface, telemetry, and shared research notes) still want a
compact, finance-real ladder that answers one question: *what class
of evidence does this card have?*

The ladder deliberately collapses the agreement engine's 7-ish
verdict bands into 5 rungs a macro desk actually quotes:

  1. **primary_confirmation**   — bottleneck / direct alpha support
                                  dominating; no offsetting direct
                                  contradiction.
  2. **secondary_confirmation** — cross-asset tape confirming; direct
                                  proxies haven't moved yet (classic
                                  "good enough to act on, watch for
                                  the direct echo").
  3. **mixed**                  — evidence genuinely split; either
                                  cross-asset tape disagrees or direct
                                  proxies are half-and-half.
  4. **lagging**                — direct proxies confirm but the tape
                                  hasn't cascaded — second-leg not yet
                                  present.
  5. **contradicted**           — direct / bottleneck proxies moving
                                  against with no offsetting alpha; the
                                  thesis is failing, not just slow.

Plus an ``insufficient`` label (off the ladder) when the archive
didn't carry enough directional evidence to place the card at all.

Each rung comes with:

  * A stable **reason_code** — one of a small, canonical enum so
    downstream filters and analytics can group cards by cause.
  * A one-line professional **narrative** — "Thesis is active / partially
    active / breaking / pending", composed from the tier + reason + the
    persistence signal (from ``persistence_signal.classify_persistence_signal``).

Pure composer.  No I/O.  Never raises.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Ladder
# ---------------------------------------------------------------------------

EVIDENCE_TIERS: tuple[str, ...] = (
    "primary_confirmation",
    "secondary_confirmation",
    "mixed",
    "lagging",
    "contradicted",
)


_TIER_RUNG: dict[str, int] = {
    "primary_confirmation":   1,
    "secondary_confirmation": 2,
    "mixed":                  3,
    "lagging":                4,
    "contradicted":           5,
}


_TIER_LABEL: dict[str, str] = {
    "primary_confirmation":   "Primary confirmation",
    "secondary_confirmation": "Secondary confirmation",
    "mixed":                  "Mixed evidence",
    "lagging":                "Lagging — direct only",
    "contradicted":           "Contradicted",
    "insufficient":           "Insufficient evidence",
}


# ---------------------------------------------------------------------------
# Reason codes — compact enum, groupable for analytics
# ---------------------------------------------------------------------------

REASON_CODES: tuple[str, ...] = (
    "primary_proxy_confirming",       # direct/bottleneck carrying the read
    "tape_confirming_primary_lagging",# tape with thesis, direct silent
    "cascade_lag",                     # direct with thesis, tape hasn't echoed
    "split_evidence",                  # tape split across channels
    "bad_primary_basket",              # direct silent + tape confirms
    "direct_miss",                     # direct opposes, tape partially offsets
    "broken",                          # direct opposes decisively, no offset
    "insufficient_evidence",           # not enough directional data
)


_REASON_LABEL: dict[str, str] = {
    "primary_proxy_confirming":       "Direct / bottleneck proxies confirming",
    "tape_confirming_primary_lagging":"Cross-asset tape confirming; direct names still silent",
    "cascade_lag":                     "Direct proxies confirming; tape cascade hasn't arrived",
    "split_evidence":                  "Cross-asset tape split across channels",
    "bad_primary_basket":              "Direct names silent; tape confirms — proxy basket likely off",
    "direct_miss":                     "Direct proxies moving against; tape partially offsetting",
    "broken":                          "Direct / bottleneck proxies contradicting; no alpha offset",
    "insufficient_evidence":           "Not enough directional evidence to judge",
}


# ---------------------------------------------------------------------------
# Tier / reason classifier
# ---------------------------------------------------------------------------

def _counters(agreement: dict) -> dict[str, int]:
    """Pull the per-class counters from an agreement-engine verdict.

    Normalises bottleneck + direct into a combined "primary" pair so
    the ladder logic below doesn't have to mention the bottleneck tier
    directly.  Missing keys default to zero.
    """
    def _n(k: str) -> int:
        try:
            return int(agreement.get(k) or 0)
        except (TypeError, ValueError):
            return 0

    bot_sup = _n("bottleneck_support")
    bot_con = _n("bottleneck_contradict")
    dir_sup = _n("direct_support")
    dir_con = _n("direct_contradict")
    return {
        "primary_support":    bot_sup + dir_sup,
        "primary_contradict": bot_con + dir_con,
        "bottleneck_support":    bot_sup,
        "bottleneck_contradict": bot_con,
        "direct_support":        dir_sup,
        "direct_contradict":     dir_con,
        "second_support":        _n("second_order_support"),
        "second_contradict":     _n("second_order_contradict"),
        "n_eligible":            _n("n_eligible"),
    }


def _classify_tier_and_reason(
    agreement: Optional[dict],
) -> tuple[str, str]:
    """Return ``(tier, reason_code)`` from the agreement verdict."""
    if not isinstance(agreement, dict):
        return "insufficient", "insufficient_evidence"

    verdict = (agreement.get("verdict") or "").strip().lower()
    counts = _counters(agreement)

    p_sup  = counts["primary_support"]
    p_con  = counts["primary_contradict"]
    s_sup  = counts["second_support"]
    s_con  = counts["second_contradict"]

    if verdict == "insufficient":
        return "insufficient", "insufficient_evidence"

    # Defensive: verdict missing / unrecognised AND no directional
    # counters fired — treat as insufficient rather than falling
    # through to the generic "mixed" bucket.  This keeps empty-dict
    # callers honest ("no evidence") instead of implying a mid-band read.
    if (p_sup + p_con + s_sup + s_con) == 0 and not verdict:
        return "insufficient", "insufficient_evidence"

    # --- Contradicted family ---------------------------------------
    # Bottleneck / direct proxies opposing with no alpha offset.
    if verdict == "contradicted":
        # If the contradiction is decisive (bottleneck named), surface
        # "broken" instead of plain "direct_miss" so the UI can render
        # a sharper signal for a thesis whose named actors opposed.
        if counts["bottleneck_contradict"] >= 1 and p_sup == 0:
            return "contradicted", "broken"
        return "contradicted", "direct_miss"

    # --- Primary confirmation --------------------------------------
    # Clean alpha read — direct proxies lead, no offsetting contradiction.
    if verdict == "confirmed" and p_sup >= 1 and p_con == 0:
        return "primary_confirmation", "primary_proxy_confirming"

    # A "confirmed" verdict that carried a direct contradiction somewhere
    # is a judgment call — treat it as primary_confirmation (direct
    # support won) but tag the reason so the UI can show "confirmed
    # despite counter-signal".
    if verdict == "confirmed":
        return "primary_confirmation", "primary_proxy_confirming"

    # --- Secondary confirmation (tape-led) -------------------------
    if verdict == "second_order_only":
        return "secondary_confirmation", "tape_confirming_primary_lagging"

    # A "partial" verdict with direct support + tape lean is secondary
    # confirmation quality — tape is helping, direct alpha is in flux.
    if verdict == "partial" and p_sup >= 1 and s_sup >= 1:
        return "secondary_confirmation", "primary_proxy_confirming"

    # Partial without tape echo — direct proxy confirming solo.
    if verdict == "partial" and p_sup >= 1 and s_sup == 0 and s_con == 0:
        return "lagging", "cascade_lag"

    # --- Lagging — direct confirms, tape silent --------------------
    if p_sup >= 1 and p_con == 0 and s_sup == 0 and s_con == 0:
        return "lagging", "cascade_lag"

    # --- Direct-miss band (weak / direct_miss verdicts) ------------
    if verdict in ("weak", "direct_miss"):
        # If the direct miss includes a bottleneck contradict, surface
        # as broken; otherwise direct_miss.
        if counts["bottleneck_contradict"] >= 1:
            return "contradicted", "broken"
        if counts["direct_contradict"] >= 1:
            return "contradicted", "direct_miss"
        # Neither direct nor bottleneck contradict — it's beta-led
        # pushback with direct silent.  That's mixed, not contradicted.
        return "mixed", "split_evidence"

    # --- Bad primary basket ----------------------------------------
    # Direct silent in both directions, tape clearly confirming.
    if p_sup == 0 and p_con == 0 and s_sup >= 1 and s_sup > s_con:
        return "secondary_confirmation", "bad_primary_basket"

    # --- Mixed family ----------------------------------------------
    # Everything else with both sides firing = split evidence.
    if s_sup >= 1 and s_con >= 1:
        return "mixed", "split_evidence"
    if p_sup >= 1 and p_con >= 1:
        return "mixed", "split_evidence"

    # Fallthrough: we have a verdict band we didn't explicitly map —
    # safer to call it mixed than pretend to classify.
    return "mixed", "split_evidence"


# ---------------------------------------------------------------------------
# Status + narrative — composed from tier + reason + persistence
# ---------------------------------------------------------------------------

_STATUS_FOR_TIER: dict[str, str] = {
    "primary_confirmation":   "active",
    "secondary_confirmation": "partially_active",
    "lagging":                "partially_active",
    "mixed":                  "partially_active",
    "contradicted":           "breaking",
    "insufficient":           "pending",
}


_STATUS_LABEL: dict[str, str] = {
    "active":            "Active",
    "partially_active":  "Partially active",
    "breaking":          "Breaking",
    "pending":           "Pending",
}


def _apply_persistence(status: str, persistence_signal: Optional[dict]) -> str:
    """Fold the persistence signal into the status.  A fading / resolved
    persistence downgrades an active setup; an active persistence
    doesn't upgrade a contradicted one (don't gloss over breakdowns)."""
    if not isinstance(persistence_signal, dict):
        return status
    p = (persistence_signal.get("status") or "").strip().lower()
    if status == "active" and p in ("fading", "resolved"):
        return "partially_active"
    if status == "partially_active" and p == "resolved":
        return "pending"
    return status


def _narrative(
    tier: str,
    reason_code: str,
    status: str,
    persistence_signal: Optional[dict],
    agreement: dict,
) -> str:
    """Compose the one-line "why this is still X" sentence.

    Tight by construction: the tier gives the head ("Thesis is active"),
    the reason code gives the cause, and the persistence signal adds a
    follow-through tag where relevant.  No filler adjectives.
    """
    status_head = {
        "active":            "Thesis is active",
        "partially_active":  "Thesis is partially active",
        "breaking":          "Thesis is breaking",
        "pending":           "Thesis is pending",
    }.get(status, "Thesis status unclear")

    reason_text = _REASON_LABEL.get(reason_code, reason_code.replace("_", " "))

    # Optional persistence tag.
    tail = ""
    if isinstance(persistence_signal, dict):
        p = (persistence_signal.get("status") or "").strip().lower()
        p_label = persistence_signal.get("label")
        if p == "active":
            tail = " (follow-through active)"
        elif p == "fading":
            tail = " (follow-through fading)"
        elif p == "resolved":
            tail = " (setup resolved)"
        elif p_label and p != "watching":
            tail = f" ({p_label.lower()})"

    # Bottleneck call-out when the mechanism's named actors are doing
    # the heavy lifting — adds a finance-real specificity the reason
    # code alone doesn't convey.
    bottleneck_tag = ""
    if isinstance(agreement, dict):
        syms = agreement.get("bottleneck_symbols") or []
        if syms and tier == "primary_confirmation":
            bottleneck_tag = f" — named actors {', '.join(syms[:3])} leading"
        elif syms and tier == "contradicted":
            bottleneck_tag = f" — named actors {', '.join(syms[:3])} moving against"

    return f"{status_head} — {reason_text}{bottleneck_tag}{tail}."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def classify_evidence(
    agreement: Optional[dict],
    *,
    persistence_signal: Optional[dict] = None,
) -> dict[str, Any]:
    """Build the 5-rung evidence-ladder read for a mover card.

    Returned shape::

        {
          "tier":         str,      # one of EVIDENCE_TIERS or "insufficient"
          "tier_label":   str,
          "rung":         int | None,   # 1-5; None for "insufficient"
          "reason_code":  str,      # one of REASON_CODES
          "reason_label": str,
          "status":       "active" | "partially_active" | "breaking" | "pending",
          "status_label": str,
          "narrative":    str,       # one-line professional summary
        }

    All fields are always present — missing / malformed input folds to
    ``insufficient`` with a clean narrative, never raises.
    """
    tier, reason_code = _classify_tier_and_reason(agreement)
    rung = _TIER_RUNG.get(tier)  # None for "insufficient"
    status = _apply_persistence(
        _STATUS_FOR_TIER.get(tier, "pending"),
        persistence_signal,
    )
    narrative = _narrative(
        tier, reason_code, status, persistence_signal, agreement or {},
    )
    sources = _build_ladder_evidence_sources(
        tier=tier,
        reason_code=reason_code,
        agreement=agreement,
    )
    return {
        "tier":         tier,
        "tier_label":   _TIER_LABEL.get(tier, tier.replace("_", " ")),
        "rung":         rung,
        "reason_code":  reason_code,
        "reason_label": _REASON_LABEL.get(reason_code, reason_code),
        "status":       status,
        "status_label": _STATUS_LABEL.get(status, status),
        "narrative":    narrative,
        "evidence_sources": sources,
    }


# ---------------------------------------------------------------------------
# Evidence-source traceability
# ---------------------------------------------------------------------------
# Each ladder verdict maps the agreement-engine counts back to the
# concrete supports / contradicts / silent buckets so a reader can see
# which class of evidence drove the rung.  Reuses existing fields on
# the agreement dict only — no new data fetched.

# Reason codes that ride on a structurally weak evidence read; these
# carry a substantive limitation on the ladder source even when the
# tier itself reads as confirming.
_WEAK_REASON_LIMITATION: dict[str, str] = {
    "tape_confirming_primary_lagging": (
        "tape-led — direct alpha names still silent"
    ),
    "bad_primary_basket": (
        "tape confirms but proxy basket likely off — direct names silent"
    ),
    "cascade_lag": (
        "direct only — second-leg tape cascade has not arrived"
    ),
    "split_evidence": (
        "evidence split across channels — no decisive direction"
    ),
    "direct_miss": (
        "direct proxies moving against; tape only partially offsetting"
    ),
    "broken": (
        "named bottleneck actors moving against the thesis"
    ),
}


def _build_ladder_evidence_sources(
    *,
    tier: str,
    reason_code: str,
    agreement: Optional[dict],
) -> list[dict]:
    """Trace the ladder verdict back to the agreement counters that
    produced it.  Pure read.  Returns ``[]`` for the ``insufficient``
    tier (no directional evidence to attribute) so the schema stays
    stable without inventing sources.
    """
    if tier == "insufficient" or not isinstance(agreement, dict):
        return []
    try:
        from evidence_sources import make_source
    except Exception:
        return []

    counts = _counters(agreement)
    weak_limit = _WEAK_REASON_LIMITATION.get(reason_code, "")
    out: list[dict] = []

    def _emit(field: str, count_key: str, direction: str, channel_limit: str) -> None:
        if counts.get(count_key, 0) <= 0:
            return
        # The verdict-level limitation (if any) takes precedence — it
        # describes the structural weakness driving the reason code.
        # Otherwise fall back to the per-channel observation note.
        limitation = weak_limit or channel_limit
        src = make_source(
            source_type="agreement_verdict",
            field_used=field,
            supports_or_contradicts=direction,
            limitation=limitation,
        )
        if src:
            out.append(src)

    _emit(
        "agreement.bottleneck_support", "bottleneck_support", "supports",
        "",
    )
    _emit(
        "agreement.bottleneck_contradict", "bottleneck_contradict", "contradicts",
        "",
    )
    _emit(
        "agreement.direct_support", "direct_support", "supports",
        "",
    )
    _emit(
        "agreement.direct_contradict", "direct_contradict", "contradicts",
        "",
    )
    _emit(
        "agreement.second_order_support", "second_support", "supports",
        "second-order tape — beta-aligned, not direct",
    )
    _emit(
        "agreement.second_order_contradict", "second_contradict", "contradicts",
        "second-order tape — beta-aligned, not direct",
    )

    # Eligibility floor — when the agreement basket has fewer than three
    # eligible names a reader should know the verdict is being scored on
    # thin coverage, regardless of which direction the counters lean.
    n_elig = counts.get("n_eligible", 0)
    if 0 < n_elig < 3:
        src = make_source(
            source_type="agreement_verdict",
            field_used=f"agreement.n_eligible={n_elig}",
            supports_or_contradicts="neutral",
            limitation=f"thin basket — only {n_elig} eligible name(s) scored",
        )
        if src:
            out.append(src)

    return out
