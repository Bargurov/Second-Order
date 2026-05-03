"""
finance_playbook.py

Single-read synthesis of the macro engine's per-module outputs.

Why this module
---------------
By the time the analyze pipeline finishes, the response carries a dozen
independent diagnostic blocks (regime_snapshot, funding_stress_mode,
thesis_scorecard, historical_analogs, sector_rotation,
confidence_calibration, credit_regime, …).  Each is finance-real on
its own; read together they can still feel like separate diagnostics
rather than one coherent read.

This composer produces a single *playbook* structure that a macro
desk would actually quote:

  * **Headline** — one-line synthesis across regime / funding / thesis /
    rotation.
  * **Per-dimension lines** — one short line per input block, so the
    reader can quickly audit where the headline came from.
  * **Base case** — the thesis-status echo + the concrete sectors the
    playbook says to be long / short.
  * **Key risks** — deterministic selection of the top exposures
    flagged by funding mode, thesis failures, regime flips, or weak
    calibration.
  * **What would change the read** — concrete falsifiers pulled from
    the thesis scorecard's LLM-written criteria + regime-flip watches.
  * **Coherence flags** — explicit callouts when two engine blocks
    contradict each other (e.g. compound regime says "reflation" but
    funding stress says "credit_widening acute").  Readers should see
    the contradiction, not a smoothed-over story.

Pure composer.  No I/O.  Never raises.  Every input block is optional;
missing blocks are surfaced as ``"—"`` line values and omit themselves
from the base-case and risk calculations rather than crashing the
synthesis.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

_DASH = "—"


def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default


def _is_dict(obj: Any) -> bool:
    return isinstance(obj, dict)


# ---------------------------------------------------------------------------
# Per-block line composers
# ---------------------------------------------------------------------------

def _regime_line(regime_snapshot: Optional[dict]) -> tuple[str, dict]:
    """Compose the regime + transition summary line.

    Returns ``(line_text, structured_info)``.  The structured info is
    reused downstream for key-risks and coherence flags.
    """
    info: dict = {"compound_label": "none", "transition_state": "unavailable",
                  "confidence": 0.0, "changed_axes": []}
    if not _is_dict(regime_snapshot):
        return f"Regime: {_DASH} (snapshot unavailable)", info

    compound = regime_snapshot.get("compound") or {}
    transition = regime_snapshot.get("transition") or {}

    label = compound.get("label") or "none"
    conf = float(compound.get("confidence") or 0.0)
    state = transition.get("state") or "unavailable"
    changed = transition.get("changed_axes") or []
    info.update({
        "compound_label":   label,
        "confidence":        conf,
        "transition_state":  state,
        "changed_axes":      changed,
    })

    if label == "none":
        left = "No compound pattern locked"
    else:
        left = f"Compound: {label} ({conf:.2f})"

    if state == "unavailable":
        right = "transition unavailable"
    elif state == "stable":
        right = "transition stable"
    elif state == "shifting":
        right = f"transition shifting ({len(changed)} axes moved)"
    elif state == "flipping":
        flip_axes = [c.get("axis") for c in changed
                     if c.get("direction") == "flip"]
        right = f"transition FLIPPING on {', '.join(flip_axes) or '?'}"
    else:
        right = f"transition {state}"

    return f"Regime: {left}; {right}", info


def _funding_line(funding_mode: Optional[dict]) -> tuple[str, dict]:
    info: dict = {"primary": "none", "severity": "none", "active": []}
    if not _is_dict(funding_mode):
        return f"Funding/liquidity: {_DASH} (unavailable)", info
    if not funding_mode.get("available"):
        return f"Funding/liquidity: {_DASH} (inputs unavailable)", info

    primary = funding_mode.get("primary_mode") or "none"
    severity = funding_mode.get("composite_severity") or "none"
    active = list(funding_mode.get("active_modes") or [])
    info.update({"primary": primary, "severity": severity, "active": active})

    if primary == "none" or severity == "none":
        return "Funding/liquidity: quiet (no mode firing)", info
    other = [m for m in active if m != primary]
    if other:
        return (f"Funding/liquidity: {primary} ({severity}); "
                f"also firing {', '.join(other)}"), info
    return f"Funding/liquidity: {primary} ({severity})", info


def _thesis_line(
    scorecard: Optional[dict],
    calibration: Optional[dict],
) -> tuple[str, dict]:
    info: dict = {"status": "pending", "resolved": 0, "pending": 0,
                  "weak_calibration": False, "hit_rate": None,
                  "depth_tier": "insufficient"}
    if not _is_dict(scorecard):
        return f"Thesis: {_DASH} (scorecard unavailable)", info

    agg = scorecard.get("aggregate") or {}
    status = agg.get("status") or "pending"
    resolved = int(agg.get("resolved_horizons") or 0)
    pending = int(agg.get("pending_horizons") or 0)
    info.update({"status": status, "resolved": resolved, "pending": pending})

    left = f"Thesis {status}"
    if resolved + pending > 0:
        left += f" ({resolved} resolved / {pending} pending)"

    cal_bits = ""
    if _is_dict(calibration):
        hit_rate = calibration.get("hit_rate")
        n = calibration.get("n")
        depth = calibration.get("depth_tier") or "insufficient"
        weak = bool(calibration.get("weak"))
        info.update({
            "hit_rate":          hit_rate,
            "depth_tier":         depth,
            "weak_calibration":   weak,
            "calibration_n":      n,
        })
        if hit_rate is not None and n:
            cal_bits = (
                f"; calibration {hit_rate:.0%} on {n} {depth} events"
                + (" (thin)" if weak else "")
            )
        elif depth == "insufficient":
            cal_bits = "; calibration insufficient"

    return left + cal_bits, info


def _rotation_line(rotation: Optional[dict]) -> tuple[str, dict]:
    info: dict = {"tilt": "neutral", "top_winner": None, "top_loser": None,
                  "winners": [], "losers": []}
    if not _is_dict(rotation):
        return f"Rotation: {_DASH} (unavailable)", info
    if not rotation.get("available"):
        return f"Rotation: {_DASH} (no channels firing)", info

    tilt = rotation.get("broad_market_tilt") or "neutral"
    sectors = rotation.get("sectors") or []

    winners = [s for s in sectors if s.get("direction") == "winner"]
    losers = [s for s in sectors if s.get("direction") == "loser"]
    winners.sort(key=lambda s: -float(s.get("net_score") or 0.0))
    losers.sort(key=lambda s: float(s.get("net_score") or 0.0))

    info.update({
        "tilt":        tilt,
        "winners":     [s.get("symbol") for s in winners[:3]],
        "losers":      [s.get("symbol") for s in losers[:3]],
        "top_winner":  winners[0] if winners else None,
        "top_loser":   losers[0] if losers else None,
    })

    bits: list[str] = [f"tape {tilt}"]
    if winners:
        bits.append(
            "winners " + ", ".join(s.get("symbol", "") for s in winners[:3])
        )
    if losers:
        bits.append(
            "losers " + ", ".join(s.get("symbol", "") for s in losers[:3])
        )
    return "Rotation: " + "; ".join(bits), info


def _analog_line(analogs: Optional[list]) -> tuple[str, dict]:
    info: dict = {"count": 0, "top_score": None,
                  "top_headline": None, "top_reason": None}
    if not isinstance(analogs, list) or not analogs:
        return f"Analogs: {_DASH} (none matched)", info

    # Prefer final_score when present (regime-reranked); fall back to similarity.
    def _score(a: dict) -> float:
        return float(a.get("final_score") or a.get("similarity") or 0.0)

    sorted_analogs = sorted(
        (a for a in analogs if isinstance(a, dict)),
        key=_score, reverse=True,
    )
    if not sorted_analogs:
        return f"Analogs: {_DASH} (malformed)", info

    top = sorted_analogs[0]
    info.update({
        "count":         len(sorted_analogs),
        "top_score":     _score(top),
        "top_headline":  top.get("headline") or top.get("id"),
        "top_reason":    top.get("match_reason"),
    })

    hd = (info["top_headline"] or "")
    if isinstance(hd, str) and len(hd) > 70:
        hd = hd[:67] + "..."
    right = f"{info['count']} analog(s); top: \"{hd}\" ({info['top_score']:.2f})"
    if info["top_reason"]:
        right += f" — {info['top_reason']}"
    return "Analogs: " + right, info


# ---------------------------------------------------------------------------
# Base case assembly
# ---------------------------------------------------------------------------

def _base_case(
    thesis_info: dict,
    rotation_info: dict,
    regime_info: dict,
    funding_info: dict,
) -> dict:
    status = thesis_info.get("status") or "pending"
    long_syms = rotation_info.get("winners") or []
    short_syms = rotation_info.get("losers") or []

    bits: list[str] = []
    if regime_info.get("compound_label") and regime_info["compound_label"] != "none":
        bits.append(f"{regime_info['compound_label']} regime")
    if (funding_info.get("severity") or "none") not in ("none", "unknown"):
        bits.append(
            f"{funding_info.get('primary')} {funding_info['severity']}"
        )
    if status != "pending":
        bits.append(f"thesis {status}")
    if rotation_info.get("tilt") and rotation_info["tilt"] != "neutral":
        bits.append(f"tape {rotation_info['tilt']}")
    rationale = (
        "Base case: " + "; ".join(bits) if bits
        else "Base case: quiet tape, thesis awaiting confirmation"
    )

    return {
        "thesis_status": status,
        "rationale":     rationale,
        "key_sectors":   {"long": long_syms, "short": short_syms},
    }


# ---------------------------------------------------------------------------
# Key-risks assembly
# ---------------------------------------------------------------------------

_SEVERITY_TO_RISK: dict[str, str] = {
    "mild":     "watch",
    "elevated": "elevated",
    "acute":    "acute",
}


def _key_risks(
    scorecard: Optional[dict],
    funding_info: dict,
    regime_info: dict,
    thesis_info: dict,
    analog_info: dict,
) -> list[dict]:
    risks: list[dict] = []

    # 1. Structural thesis failures (5d / 20d).
    if _is_dict(scorecard):
        per_h = scorecard.get("per_horizon") or []
        for h in per_h:
            if (
                h.get("status") == "failed"
                and h.get("horizon") in ("5d", "20d")
            ):
                contradict = (h.get("realized") or {}).get("contradicting") or []
                symbols = [t.get("symbol") for t in contradict if t.get("symbol")]
                risks.append({
                    "risk":     f"Thesis failed at {h.get('horizon')}",
                    "driver":   (
                        ", ".join(symbols[:3])
                        + (" moved against" if symbols else "")
                    ) if symbols else h.get("rationale", ""),
                    "severity": "acute",
                })

    # 2. Funding/liquidity mode firing elevated or acute.
    f_sev = funding_info.get("severity") or "none"
    if f_sev in ("elevated", "acute"):
        risks.append({
            "risk":     f"{funding_info.get('primary')} firing",
            "driver":   f"composite severity {f_sev}",
            "severity": _SEVERITY_TO_RISK.get(f_sev, "watch"),
        })

    # 3. Regime flipping.
    if regime_info.get("transition_state") == "flipping":
        flip_axes = [
            c.get("axis") for c in regime_info.get("changed_axes") or []
            if c.get("direction") == "flip"
        ]
        risks.append({
            "risk":     "Regime flipping",
            "driver":   f"opposite-pair flip on {', '.join(flip_axes) or '?'}",
            "severity": "elevated",
        })

    # 4. Weak calibration on a confident-looking thesis.
    if thesis_info.get("weak_calibration") and thesis_info.get("status") != "pending":
        risks.append({
            "risk":     "Calibration is thin",
            "driver":   (
                f"resolved tier {thesis_info.get('depth_tier')}, "
                f"n={thesis_info.get('calibration_n')}"
            ),
            "severity": "watch",
        })

    # 5. No historical analogs — can't triangulate.
    if (analog_info.get("count") or 0) == 0:
        risks.append({
            "risk":     "No historical analog context",
            "driver":   "archive has no comparable events",
            "severity": "watch",
        })

    return risks


# ---------------------------------------------------------------------------
# "What would change the read"
# ---------------------------------------------------------------------------

def _what_would_change_the_read(
    scorecard: Optional[dict],
    regime_info: dict,
    funding_info: dict,
) -> list[str]:
    watches: list[str] = []

    # 1. LLM-written falsifiers for 5d/20d horizons (skip 1d — too noisy).
    if _is_dict(scorecard):
        per_h = scorecard.get("per_horizon") or []
        for h in per_h:
            if h.get("horizon") in ("5d", "20d") and h.get("status") != "failed":
                crits = h.get("falsification_criteria") or []
                for c in crits[:2]:
                    watches.append(f"[{h['horizon']}] {c}")

    # 2. Regime-flip watch on opposite-pair axes not yet flipped.
    if regime_info.get("transition_state") not in ("flipping",):
        label = regime_info.get("compound_label")
        if label and label != "none":
            watches.append(
                f"Compound regime flipping off `{label}` "
                f"(watch credit / inflation / policy axes)"
            )

    # 3. Funding mode escalation watch.
    f_sev = funding_info.get("severity") or "none"
    if f_sev == "mild":
        watches.append(
            f"Escalation of {funding_info.get('primary')} from mild → elevated"
        )
    elif f_sev == "none" and funding_info.get("active"):
        watches.append(
            f"Any funding mode firing above mild (active today: "
            f"{', '.join(funding_info.get('active', []))})"
        )

    return watches


# ---------------------------------------------------------------------------
# Coherence flags — explicit callouts when blocks contradict each other
# ---------------------------------------------------------------------------

def _coherence_flags(
    regime_info: dict,
    funding_info: dict,
    rotation_info: dict,
    thesis_info: dict,
    analog_info: dict,
) -> list[str]:
    flags: list[str] = []

    # Compound regime says "reflation" or "disinflation_relief" but
    # funding stress is firing acute → structural contradiction.
    label = regime_info.get("compound_label")
    f_sev = funding_info.get("severity") or "none"
    if label in ("reflation", "disinflation_relief") and f_sev == "acute":
        flags.append(
            f"compound={label} conflicts with funding {funding_info.get('primary')} "
            f"{f_sev} — reconcile before trading"
        )

    # Compound regime says "funding_stress" but funding_stress_mode
    # classifier reports no mode firing → inputs disagree.
    if label == "funding_stress" and f_sev == "none":
        flags.append(
            "compound=funding_stress but no funding mode firing in classifier — "
            "one of the two signals is stale"
        )

    # Thesis breaking but rotation tilt still risk_on → sector rotation
    # hasn't caught up (or thesis is wrong).
    if thesis_info.get("status") == "breaking" and rotation_info.get("tilt") == "risk_on":
        flags.append(
            "thesis breaking but rotation tape is risk_on — short-side bias "
            "may not play without a broader turn"
        )

    # Thesis on_track but rotation risk_off + funding acute → thesis is
    # winning INSIDE a risk-off tape; tail risk of broader liquidation.
    if (
        thesis_info.get("status") == "on_track"
        and rotation_info.get("tilt") == "risk_off"
        and f_sev == "acute"
    ):
        flags.append(
            "thesis on_track inside risk_off + acute funding stress — "
            "position sizing should reflect systemic tail risk"
        )

    # Strong confidence claim backed by a weak calibration slice.
    if thesis_info.get("weak_calibration") and (analog_info.get("count") or 0) == 0:
        flags.append(
            "weak calibration + no analogs — the engine's priors are thin"
        )

    return flags


# ---------------------------------------------------------------------------
# Headline composition
# ---------------------------------------------------------------------------

def _headline(
    regime_info: dict,
    funding_info: dict,
    thesis_info: dict,
    rotation_info: dict,
) -> str:
    pieces: list[str] = []

    label = regime_info.get("compound_label")
    if label and label != "none":
        pieces.append(label.replace("_", " "))

    f_sev = funding_info.get("severity") or "none"
    if f_sev not in ("none", "unknown"):
        pieces.append(
            f"{funding_info.get('primary', '').replace('_', ' ')} {f_sev}"
        )

    t_status = thesis_info.get("status")
    if t_status and t_status != "pending":
        pieces.append(f"thesis {t_status}")

    tilt = rotation_info.get("tilt")
    if tilt and tilt != "neutral":
        pieces.append(f"tape {tilt}")

    if not pieces:
        return "Quiet tape; thesis awaiting confirmation."
    return "; ".join(pieces).capitalize() + "."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

_KNOWN_SOURCES: tuple[str, ...] = (
    "regime_snapshot",
    "funding_stress_mode",
    "thesis_scorecard",
    "confidence_calibration",
    "historical_analogs",
    "sector_rotation",
)


def compose_finance_playbook(analysis: Optional[dict]) -> dict[str, Any]:
    """Synthesise a single finance playbook block from the analysis dict.

    Reads only ALREADY-COMPUTED structured fields — no provider calls,
    no new classification logic.  Returns a well-formed dict even when
    every input block is missing, so callers can always dereference it.
    """
    if not _is_dict(analysis):
        analysis = {}

    regime_snapshot     = analysis.get("regime_snapshot")
    funding_mode        = analysis.get("funding_stress_mode")
    scorecard           = analysis.get("thesis_scorecard")
    calibration         = analysis.get("confidence_calibration")
    analogs             = analysis.get("historical_analogs")
    rotation            = analysis.get("sector_rotation")

    # Composed lines + structured info for downstream sections.
    regime_text,   regime_info   = _regime_line(regime_snapshot)
    funding_text,  funding_info  = _funding_line(funding_mode)
    thesis_text,   thesis_info   = _thesis_line(scorecard, calibration)
    rotation_text, rotation_info = _rotation_line(rotation)
    analog_text,   analog_info   = _analog_line(analogs)

    headline = _headline(regime_info, funding_info, thesis_info, rotation_info)
    base_case = _base_case(thesis_info, rotation_info, regime_info, funding_info)
    key_risks = _key_risks(scorecard, funding_info, regime_info, thesis_info, analog_info)
    watches = _what_would_change_the_read(scorecard, regime_info, funding_info)
    flags = _coherence_flags(
        regime_info, funding_info, rotation_info, thesis_info, analog_info,
    )

    # availability: any known source is populated.
    available = any(
        _is_dict(analysis.get(k)) or isinstance(analysis.get(k), list)
        for k in _KNOWN_SOURCES
    )

    sources_used = [
        k for k in _KNOWN_SOURCES
        if (_is_dict(analysis.get(k)) and (
                analysis.get(k) or {}
            )) or (isinstance(analysis.get(k), list) and analysis.get(k))
    ]

    return {
        "available":        available,
        "headline":         headline,
        "lines": {
            "regime":     regime_text,
            "funding":    funding_text,
            "thesis":     thesis_text,
            "rotation":   rotation_text,
            "analogs":    analog_text,
        },
        "base_case":                  base_case,
        "key_risks":                   key_risks,
        "what_would_change_the_read":  watches,
        "coherence_flags":             flags,
        "sources_used":                sources_used,
    }
