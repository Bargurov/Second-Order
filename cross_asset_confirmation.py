"""
cross_asset_confirmation.py

Cross-asset confirmation matrix.

Given a deterministic event thesis and the live shock-decomposition
channels, produce a per-channel confirm / disconfirm / silent verdict
and aggregate separate confirm and disconfirm scores.

Design
------
- Pure composer; no I/O.  Takes the shock_decomposition `channels` dict
  (as produced by ``_channels_for_payload``) plus an optional rates_pack
  for curve-shape corroboration.
- Confirms and disconfirms are scored **separately** — not as a signed
  sum — so a thesis with two strong confirms and two strong disconfirms
  surfaces as "mixed" rather than "neutral".  This is the critical
  difference from the previous bulk hawk/dove accumulator.
- Each channel's expected direction is looked up from a small thesis →
  channel map.  "silent" means the thesis makes no prediction on that
  channel; those channels never contribute to either score.
- Weights use the channel z-score (normalized magnitude from
  shock_decomposition).  A move that clears the primary-driver floor
  (``_Z_FLOOR``) is eligible; anything below is treated as noise.

Output shape
------------
    {
      thesis:            str,      # pass-through
      channels: {
        <channel_id>: {
          label:       str,
          expected:    "up" | "down" | "silent",
          observed:    float | None,    # move_5d as reported by channels
          unit:        str,
          z:           float,           # normalized magnitude
          observed_dir: "up" | "down" | "flat" | "unavailable",
          verdict:     "confirm" | "disconfirm" | "silent",
          weight:      float,           # contribution to the relevant score
        },
        ...
      },
      confirms:          list[channel_id],
      disconfirms:       list[channel_id],
      silent:            list[channel_id],
      confirm_score:     float,
      disconfirm_score:  float,
      net_score:         float,
      verdict:           str,
      verdict_label:     str,
      rationale:         str,
      curve_shape_read:  str,    # "aligned" | "diverges" | "silent"
      available:         bool,
      stale:             bool,
    }

When the thesis is ``"none"`` OR no channels are available, returns a
compact block with ``verdict="silent"`` so the caller can still render.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Thesis → expected per-channel direction
# ---------------------------------------------------------------------------
#
# Direction refers to the SIGN of the channel's own move_5d reading.
# Units match shock_decomposition._CHANNEL_UNITS:
#   nominal_yield : pp (10Y yield change); +0.3 = +30bps
#   real_yield    : % (TIP ETF price change); + = TIP up = real yields DOWN
#   breakeven     : pp (Fisher proxy); + = breakevens widening
#   fx            : % (DXY); + = dollar strength
#   credit        : pp (SHY_5d − HYG_5d); + = credit widening
#   commodity     : % (CL/GC leader); + = commodities up

_EXPECTED: dict[str, dict[str, str]] = {
    "inflationary": {
        "nominal_yield": "up",      # inflation lifts nominal yields
        "real_yield":    "down",    # TIP falls (real yields rise)
        "breakeven":     "up",      # breakevens widen
        "fx":            "silent",  # ambiguous on DXY
        "credit":        "silent",
        "commodity":     "up",      # commodities lead inflation
    },
    "disinflationary": {
        "nominal_yield": "down",
        "real_yield":    "up",      # TIP rallies (real yields fall)
        "breakeven":     "down",
        "fx":            "silent",
        "credit":        "silent",
        "commodity":     "down",
    },
    "rate_pressure_up": {
        "nominal_yield": "up",
        "real_yield":    "down",    # TIP falls (restrictive real rates)
        "breakeven":     "silent",  # hawkish policy can suppress breakevens
        "fx":            "up",      # hawkish US → DXY up
        "credit":        "up",      # hawkish surprises widen credit
        "commodity":     "silent",
    },
    "rate_pressure_down": {
        "nominal_yield": "down",
        "real_yield":    "up",      # TIP rallies
        "breakeven":     "silent",
        "fx":            "down",    # dovish US → DXY down
        "credit":        "down",    # dovish tightens credit
        "commodity":     "silent",
    },
    # Real-economy supply shock — commodity-led; nominal / breakeven tag along,
    # but fx and credit are not the primary read.
    "supply_shock": {
        "nominal_yield": "silent",  # nominal can go either way (growth vs inflation)
        "real_yield":    "silent",  # real yields depend on policy reaction
        "breakeven":     "up",      # supply-driven inflation expectations rise
        "fx":            "silent",  # direction depends on which region is hit
        "credit":        "up",      # widening as risk premium rises
        "commodity":     "up",      # supply-shock's defining signature
    },
    # Flight to quality — crisis/war/liquidity stress.  Gold, dollar, bonds
    # bid; commodities mixed (gold up, crude often down on demand fear).
    "flight_to_quality": {
        "nominal_yield": "down",    # safety bid pushes yields down
        "real_yield":    "up",      # TIP rallies with bonds
        "breakeven":     "silent",  # breakevens depend on oil path
        "fx":            "up",      # USD safe-haven rally
        "credit":        "up",      # spreads widen in a crisis
        "commodity":     "silent",  # gold up, crude often down
    },
    # Reflation impulse — stimulus, fiscal expansion, pro-growth policy.
    # Growth-positive and mildly inflationary; breakevens widen, curve bear-steepens.
    "reflation": {
        "nominal_yield": "up",      # long end sells off on growth + supply
        "real_yield":    "down",    # TIP falls (real yields up on growth)
        "breakeven":     "up",      # inflation expectations tick up
        "fx":            "silent",  # ambiguous — depends on relative impulses
        "credit":        "down",    # HY outperforms on growth relief
        "commodity":     "up",      # growth-sensitive commodities bid
    },
}

_THESIS_LABELS: dict[str, str] = {
    "inflationary":       "Inflationary",
    "disinflationary":    "Disinflationary",
    "rate_pressure_up":   "Hawkish pressure",
    "rate_pressure_down": "Dovish pressure",
    "supply_shock":       "Supply shock",
    "flight_to_quality":  "Flight to quality",
    "reflation":          "Reflation",
    "none":               "No thesis",
}


# Curve-shape expectations per thesis.
# bull = rates falling; bear = rates rising.
_CURVE_EXPECTED: dict[str, set[str]] = {
    "inflationary":       {"bear_steepener", "parallel_up"},
    "disinflationary":    {"bull_flattener", "parallel_down"},
    "rate_pressure_up":   {"bear_flattener", "parallel_up"},
    "rate_pressure_down": {"bull_steepener", "parallel_down"},
    "supply_shock":       {"bear_steepener", "parallel_up"},    # inflation-like
    "flight_to_quality":  {"bull_flattener", "bull_steepener"}, # rates fall, shape depends
    "reflation":          {"bear_steepener", "parallel_up"},    # growth steepener
}


# ---------------------------------------------------------------------------
# Verdict thresholds
# ---------------------------------------------------------------------------

# A channel must clear this z-score (normalized magnitude) to count as a
# confirm or disconfirm.  Matches shock_decomposition._PRIMARY_FLOOR so
# the two modules stay consistent on "what counts as a real move".
_Z_FLOOR: float = 0.8

# Aggregate verdict thresholds (tuned against the six-channel matrix).
_STRONG_SCORE: float = 4.0   # two ~2σ confirms, or one ~4σ shock
_WEAK_SCORE:   float = 1.5   # one solid confirm clears this
_MIXED_BOTH:   float = 1.5   # both confirm AND disconfirm must clear this

# Asymmetric weighting — disconfirms hurt harder than confirms.  A
# contradictory cross-asset read is more decision-relevant than a
# matching one because it forces the desk to reconsider the thesis,
# whereas a confirm only adds incremental evidence to a held view.
# The multiplier is applied to the raw disconfirm aggregate before the
# verdict thresholds run, so the same _STRONG_SCORE / _WEAK_SCORE
# levels trigger on a smaller raw disconfirm magnitude.  Tuned at 1.4
# so a single ~3σ disconfirm clears _STRONG_SCORE on its own (3 ×
# 1.4 ≈ 4.2), while two ~1σ disconfirms still don't tip strong.
_DISCONFIRM_PENALTY: float = 1.4


_VERDICT_LABELS: dict[str, str] = {
    "strong_confirm":    "Strong confirmation",
    "weak_confirm":      "Weak confirmation",
    "mixed":             "Mixed — confirms and disconfirms both fire",
    "weak_disconfirm":   "Weak disconfirmation",
    "strong_disconfirm": "Strong disconfirmation",
    "silent":            "No cross-asset signal",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _observed_dir(move: Optional[float]) -> str:
    if move is None:
        return "unavailable"
    if move > 0:
        return "up"
    if move < 0:
        return "down"
    return "flat"


def _verdict_for_channel(expected: str, observed_dir: str, z: float) -> str:
    if expected == "silent":
        return "silent"
    if observed_dir in ("unavailable", "flat"):
        return "silent"
    if z < _Z_FLOOR:
        return "silent"
    return "confirm" if observed_dir == expected else "disconfirm"


def _aggregate_verdict(confirm_score: float, disconfirm_score: float) -> str:
    """Classify the overall matrix verdict.

    Confirms and disconfirms are compared **separately** — a thesis with
    strong-on-strong on both sides surfaces as "mixed", not "neutral".
    """
    if confirm_score < _WEAK_SCORE and disconfirm_score < _WEAK_SCORE:
        return "silent"
    if confirm_score >= _MIXED_BOTH and disconfirm_score >= _MIXED_BOTH:
        return "mixed"
    if confirm_score >= _STRONG_SCORE and disconfirm_score < _WEAK_SCORE:
        return "strong_confirm"
    if disconfirm_score >= _STRONG_SCORE and confirm_score < _WEAK_SCORE:
        return "strong_disconfirm"
    if confirm_score > disconfirm_score:
        return "weak_confirm"
    if disconfirm_score > confirm_score:
        return "weak_disconfirm"
    # Scores equal and both below strong → mixed by construction.
    return "mixed"


def _rationale(
    thesis: str,
    verdict: str,
    confirms: list[str],
    disconfirms: list[str],
    confirm_score: float,
    disconfirm_score: float,
    channels: dict[str, dict],
) -> str:
    if verdict == "silent":
        return (
            f"No cross-asset move clears the noise floor on {_THESIS_LABELS.get(thesis, thesis)} thesis."
        )

    def _pair(cid: str) -> str:
        ch = channels.get(cid, {})
        return f"{ch.get('label', cid)} ({ch.get('z', 0):.1f}σ)"

    if verdict in ("strong_confirm", "weak_confirm"):
        parts = ", ".join(_pair(c) for c in confirms[:3]) or "n/a"
        return (
            f"Thesis ({_THESIS_LABELS.get(thesis, thesis)}) confirmed by {parts}; "
            f"confirm score {confirm_score:.1f} vs disconfirm {disconfirm_score:.1f}."
        )
    if verdict in ("strong_disconfirm", "weak_disconfirm"):
        parts = ", ".join(_pair(c) for c in disconfirms[:3]) or "n/a"
        return (
            f"Thesis ({_THESIS_LABELS.get(thesis, thesis)}) disconfirmed by {parts}; "
            f"disconfirm score {disconfirm_score:.1f} vs confirm {confirm_score:.1f}."
        )
    # mixed
    c_part = ", ".join(_pair(c) for c in confirms[:2]) or "n/a"
    d_part = ", ".join(_pair(c) for c in disconfirms[:2]) or "n/a"
    return (
        f"Thesis pulling both ways — confirms: {c_part}; disconfirms: {d_part}."
    )


def _curve_shape_read(thesis: str, rates_pack: Optional[dict]) -> str:
    """Compare observed curve shape against thesis expectation."""
    if not rates_pack or not isinstance(rates_pack, dict):
        return "silent"
    shape = rates_pack.get("curve_shape")
    if shape in (None, "unavailable", "flat"):
        return "silent"
    expected = _CURVE_EXPECTED.get(thesis)
    if not expected:
        return "silent"
    if shape in expected:
        return "aligned"
    return "diverges"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_cross_asset_confirmation(
    thesis: str,
    channels: Optional[dict],
    rates_pack: Optional[dict] = None,
) -> dict:
    """Build the confirmation matrix for the given thesis.

    Pure composer — no I/O.  Input shape:
      thesis: one of real_yield_context THESIS_LABELS
      channels: the ``channels`` field from compute_shock_decomposition
      rates_pack: optional, the ``rates_pack`` field from
        compute_shock_decomposition (used for curve-shape corroboration)

    Always returns a dict.  When the thesis is "none" or no channels are
    usable, ``verdict="silent"`` and scores are 0.
    """
    thesis = thesis or "none"
    channels = channels or {}
    expected_map = _EXPECTED.get(thesis, {})

    channel_reads: dict[str, dict] = {}
    confirms: list[str] = []
    disconfirms: list[str] = []
    silents: list[str] = []
    confirm_score = 0.0
    disconfirm_score = 0.0

    available_any = False
    for cid, ch in channels.items():
        if not isinstance(ch, dict):
            continue
        expected = expected_map.get(cid, "silent")
        z = float(ch.get("z") or 0.0)
        move = ch.get("move_5d")
        obs_dir = _observed_dir(move) if ch.get("available") else "unavailable"
        verdict = _verdict_for_channel(expected, obs_dir, z)

        weight = 0.0
        if verdict == "confirm":
            weight = z
            confirms.append(cid)
            confirm_score += z
        elif verdict == "disconfirm":
            weight = z
            disconfirms.append(cid)
            disconfirm_score += z
        else:
            silents.append(cid)

        channel_reads[cid] = {
            "label":        ch.get("label", cid),
            "expected":     expected,
            "observed":     move,
            "unit":         ch.get("unit", ""),
            "z":            round(z, 2),
            "observed_dir": obs_dir,
            "verdict":      verdict,
            "weight":       round(weight, 2),
        }
        if ch.get("available"):
            available_any = True

    # Sort confirms/disconfirms by descending weight for cleaner UI.
    confirms.sort(key=lambda c: -channel_reads[c]["weight"])
    disconfirms.sort(key=lambda c: -channel_reads[c]["weight"])

    # Apply the asymmetric disconfirm penalty so contradictory reads
    # tip the verdict harder than equally-sized confirms.  The raw
    # disconfirm_score is preserved in the output so consumers can see
    # both numbers; the penalised version is what the verdict reads.
    weighted_disconfirm_score = disconfirm_score * _DISCONFIRM_PENALTY

    verdict = (
        "silent" if thesis == "none" or not available_any
        else _aggregate_verdict(confirm_score, weighted_disconfirm_score)
    )

    rationale = _rationale(
        thesis, verdict, confirms, disconfirms,
        confirm_score, disconfirm_score, channel_reads,
    )

    return {
        "thesis":           thesis,
        "channels":         channel_reads,
        "confirms":         confirms,
        "disconfirms":      disconfirms,
        "silent":           silents,
        "confirm_score":    round(confirm_score, 2),
        "disconfirm_score": round(disconfirm_score, 2),
        "net_score":        round(confirm_score - disconfirm_score, 2),
        "verdict":          verdict,
        "verdict_label":    _VERDICT_LABELS[verdict],
        "rationale":        rationale,
        "curve_shape_read": _curve_shape_read(thesis, rates_pack),
        "available":        available_any,
        "stale":            not available_any,
    }
