"""
cross_asset_coherence.py

Cross-asset coherence / thesis-rejection layer.

Given a deterministic event thesis, score how well the LIVE cross-asset
tape agrees with that thesis across six grouped channels:

    rates        — 10Y nominal yield (pp / 5d)
    fx           — DXY (% / 5d)
    commodities  — CL / GC composite (% / 5d, leader magnitude)
    vol          — VIX change (points / 5d)
    credit       — HY-vs-Treasury spread (pp / 5d, positive = widening)
    equities     — S&P 500 / ES (% / 5d)

Output is richer than a simple support count:

  * a **confirm-vs-disconfirm matrix** with per-channel verdicts,
    z-weighted magnitudes, and an "expected direction" that the thesis
    predicts
  * a **coherence score** (0–100) = confirm_share of total channel
    weight — how internally consistent the tape is with the thesis
  * an explicit **thesis_rejection** flag when disconfirms materially
    outweigh confirms
  * a **tension** flag when BOTH confirm and disconfirm scores clear a
    threshold (the tape is moving, but not in one direction)

This complements — does not replace — the ticker-level
``narrative_divergence`` (which counts direction-tag support at the
equity level).  This layer reads the macro tape.

Design notes
------------
- Pure composer.  No I/O.
- Channel expectations per thesis are small, transparent maps at the
  top of this file.  "silent" means the thesis does NOT predict that
  channel; silent channels never contribute to either score.
- Each channel carries its own 1-σ 5d scale, used for z-weighting.  A
  channel must clear ``_Z_FLOOR`` to count at all.
- Thesis-rejection and tension are SEPARATE flags — a tape can be
  rejection (disconfirms lead cleanly), tension (both fire), or neither.

Output shape (additive nested block; no DB column)
--------------------------------------------------
    {
      "thesis":            str,
      "thesis_label":      str,
      "channels": {
        "rates": {
          label:          str,
          expected:       "up" | "down" | "silent",
          observed:       float | None,    # signed move in channel units
          unit:           str,
          z:              float,            # normalized magnitude
          observed_dir:   "up" | "down" | "flat" | "unavailable",
          verdict:        "confirm" | "disconfirm" | "silent",
          weight:         float,            # contribution to the relevant score
        },
        ... (one entry per channel id)
      },
      "confirms":          list[channel_id],
      "disconfirms":       list[channel_id],
      "silent":            list[channel_id],
      "confirm_score":     float,
      "disconfirm_score":  float,
      "coherence":         int | None,   # 0..100 or None when nothing fired
      "coherence_band":    "high" | "moderate" | "low" | "rejected" | "silent",
      "thesis_rejection":  bool,
      "tension":           bool,
      "verdict":           "strong_confirm" | "weak_confirm" |
                           "mixed" | "rejected" | "silent",
      "verdict_label":     str,
      "rationale":         str,
      "available":         bool,
      "stale":             bool,
    }
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------

CHANNEL_IDS: tuple[str, ...] = (
    "rates",
    "fx",
    "commodities",
    "vol",
    "credit",
    "equities",
)

_CHANNEL_LABELS: dict[str, str] = {
    "rates":       "Rates (10Y)",
    "fx":          "Dollar / FX",
    "commodities": "Commodities",
    "vol":         "Equity vol (VIX)",
    "credit":      "Credit spreads",
    "equities":    "Equities (ES)",
}

# Units per channel — shown in rationale, kept consistent with
# upstream compute_rates_context / compute_stress_regime output.
_CHANNEL_UNITS: dict[str, str] = {
    "rates":       "pp",     # absolute pp change in ^TNX
    "fx":          "%",      # DXY percentage change
    "commodities": "%",      # leader of CL / GC, percentage change
    "vol":         "pts",    # VIX point change
    "credit":      "pp",     # HY-vs-Treasury spread pp
    "equities":    "%",      # ES / SPY percentage change
}

# Institutional 1-σ 5d move scales.  Calibrated to equity-scale FX vol
# and treasury-scale rates so a 1 σ move in any channel produces a
# z-score near 1.0.  Thresholds for contribution live separately —
# here we only normalize magnitudes.
_CHANNEL_SCALE: dict[str, float] = {
    "rates":       0.20,   # 20 bps / 5d in ^TNX
    "fx":          0.90,   # 0.90% / 5d in DXY
    "commodities": 5.00,   # 5% / 5d crude-equivalent
    "vol":         2.50,   # 2.5 VIX points / 5d
    "credit":      1.00,   # 1.0 pp / 5d in HY-SHY spread
    "equities":    2.00,   # 2.0% / 5d in ES
}

# Sanity caps — move values beyond these are dropped as corrupt data.
_CHANNEL_MOVE_CAPS: dict[str, float] = {
    "rates":       5.0,
    "fx":          15.0,
    "commodities": 60.0,
    "vol":         40.0,
    "credit":      10.0,
    "equities":    40.0,
}


# ---------------------------------------------------------------------------
# Thesis → expected direction per channel
# ---------------------------------------------------------------------------
#
# Sign convention (same as channel units):
#   rates:       + = yields rising
#   fx:          + = dollar strengthening
#   commodities: + = composite up (crude/gold leader)
#   vol:         + = VIX rising (stress)
#   credit:      + = spread widening
#   equities:    + = ES rising (risk-on)

_EXPECTED: dict[str, dict[str, str]] = {
    "inflationary": {
        "rates":       "up",      # breakevens push nominal up
        "fx":          "silent",  # ambiguous cross-border
        "commodities": "up",      # supply-driven inflation led by commodities
        "vol":         "up",      # cost shock risk
        "credit":      "up",      # widening as policy-tightening risk rises
        "equities":    "down",    # cost pressure + growth slowdown
    },
    "disinflationary": {
        "rates":       "down",
        "fx":          "silent",
        "commodities": "down",
        "vol":         "down",
        "credit":      "down",
        "equities":    "up",
    },
    "rate_pressure_up": {
        "rates":       "up",
        "fx":          "up",      # hawkish US → DXY up
        "commodities": "silent",
        "vol":         "up",
        "credit":      "up",      # hawkish surprise widens credit
        "equities":    "down",
    },
    "rate_pressure_down": {
        "rates":       "down",
        "fx":          "down",
        "commodities": "silent",
        "vol":         "down",
        "credit":      "down",    # dovish tightens spreads
        "equities":    "up",
    },
    # Flight-to-quality: crisis / geopolitical shock.  Rates down, gold up,
    # VIX up, credit wider, equities down.
    "flight_to_quality": {
        "rates":       "down",
        "fx":          "up",      # USD safe-haven bid
        "commodities": "up",      # gold-led composite
        "vol":         "up",
        "credit":      "up",
        "equities":    "down",
    },
}


_THESIS_LABELS: dict[str, str] = {
    "inflationary":       "Inflationary",
    "disinflationary":    "Disinflationary",
    "rate_pressure_up":   "Hawkish policy pressure",
    "rate_pressure_down": "Dovish policy pressure",
    "flight_to_quality":  "Flight to quality",
    "none":               "No thesis",
}


# ---------------------------------------------------------------------------
# Thresholds (all validated in tests)
# ---------------------------------------------------------------------------

# Z-score floor: a channel must clear this normalized magnitude to be
# treated as a real move.  Below the floor = silent (noise).
_Z_FLOOR: float = 0.80

# Coherence = 100 * confirm_score / (confirm_score + disconfirm_score).
# Bands on the output integer:
_COHERENCE_HIGH:      int = 75    # ≥75 = "high" coherence
_COHERENCE_MODERATE:  int = 50    # 50–74 = "moderate"
_COHERENCE_LOW:       int = 25    # 25–49 = "low"
# <25 = "rejected" (score-only; rejection FLAG uses the stricter rules below)

# Thesis rejection fires when disconfirms are materially heavier than
# confirms AND coherence is below the rejected band.  This is a
# stricter standard than low coherence alone — we want to avoid
# calling a partial tape "rejected" when only one disconfirm happened.
_REJECTION_DISCONFIRM_FLOOR: float = 3.0
_REJECTION_COHERENCE_CEIL:   int   = 35

# Tension flag: both scores clear this floor simultaneously.
_TENSION_FLOOR: float = 2.0

# Aggregate-verdict thresholds (shared with the score bands so the
# labels stay aligned with numbers).
_STRONG_CONFIRM_SCORE: float = 4.0
_WEAK_CONFIRM_SCORE:   float = 1.5


_VERDICT_LABELS: dict[str, str] = {
    "strong_confirm": "Strong cross-asset confirmation",
    "weak_confirm":   "Weak cross-asset confirmation",
    "mixed":          "Mixed — confirms and disconfirms both fire",
    "rejected":       "Cross-asset tape rejects thesis",
    "silent":         "No cross-asset signal",
}

_COHERENCE_BAND_LABELS: dict[str, str] = {
    "high":     "High coherence",
    "moderate": "Moderate coherence",
    "low":      "Low coherence",
    "rejected": "Tape rejects thesis",
    "silent":   "Insufficient data",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(val) -> Optional[float]:
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _safe_move(cid: str, move: Optional[float]) -> Optional[float]:
    """Drop moves beyond the per-channel sanity cap."""
    if move is None:
        return None
    cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
    return move if abs(move) <= cap else None


def _snap_change_5d(snapshots: Optional[list[dict]], market: str) -> Optional[float]:
    if not snapshots:
        return None
    target = market.upper()
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        if (s.get("market") or "").upper() != target:
            continue
        if s.get("value") is None or s.get("error"):
            return None
        return _f(s.get("change_5d"))
    return None


def _stress_haven_assets(stress_regime: Optional[dict]) -> dict:
    if not stress_regime or not isinstance(stress_regime, dict):
        return {}
    detail = stress_regime.get("detail") or {}
    safe = detail.get("safe_haven") or {}
    assets = safe.get("assets") or {}
    return assets if isinstance(assets, dict) else {}


def _observed_dir(move: Optional[float]) -> str:
    if move is None:
        return "unavailable"
    if move > 0:
        return "up"
    if move < 0:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Channel extraction
# ---------------------------------------------------------------------------

def _extract_channel_moves(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> dict[str, Optional[float]]:
    """Return {channel_id: observed_move_5d} in channel-native units.

    All channels read from the same cross-section of the tape.  Missing
    values are returned as None — the scorer treats them as "unavailable".
    """
    rc = rates_context or {}
    sr = stress_regime or {}
    raw = sr.get("raw") or {}
    detail = sr.get("detail") or {}

    # rates — 10Y nominal 5d (pp)
    rates = _safe_move("rates", _f((rc.get("nominal") or {}).get("change_5d")))

    # fx — DXY: prefer snapshot, fall back to stress_regime safe_haven.Dollar
    fx = _safe_move("fx", _snap_change_5d(snapshots, "DXY"))
    if fx is None:
        haven = _stress_haven_assets(stress_regime)
        fx = _safe_move("fx", _f(haven.get("Dollar")))

    # commodities — leader of CL / GC (whichever is larger in z-terms)
    cl = _safe_move("commodities", _snap_change_5d(snapshots, "CL"))
    gc = _safe_move("commodities", _snap_change_5d(snapshots, "GC"))
    if gc is None:
        haven = _stress_haven_assets(stress_regime)
        gc = _safe_move("commodities", _f(haven.get("Gold")))
    commod: Optional[float] = None
    # Use crude-scale for crude, gold-adjusted for gold so sub-scale
    # selection isn't biased.  Scales: crude ≈ 3% / 5d 1σ, gold ≈ 1.5%.
    cl_z = (abs(cl) / 3.0) if cl is not None else 0.0
    gc_z = (abs(gc) / 1.5) if gc is not None else 0.0
    if cl is not None and cl_z >= gc_z:
        commod = cl
    elif gc is not None:
        commod = gc

    # vol — VIX 5d change (points)
    vol = _safe_move("vol", _f(raw.get("vix_change_5d")))

    # credit — HY-vs-Treasury spread (pp, positive = widening)
    credit = _safe_move("credit", _f((detail.get("credit") or {}).get("spread_5d")))
    if credit is None:
        credit = _safe_move("credit", _f(raw.get("credit_spread_5d")))

    # equities — ES snapshot, fall back to breadth gap sign (narrow
    # leadership = negative drift in ES-equivalent terms)
    equities = _safe_move("equities", _snap_change_5d(snapshots, "ES"))
    if equities is None:
        equities = _safe_move("equities", _snap_change_5d(snapshots, "SPY"))

    return {
        "rates":       rates,
        "fx":          fx,
        "commodities": commod,
        "vol":         vol,
        "credit":      credit,
        "equities":    equities,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _channel_z(cid: str, move: Optional[float]) -> float:
    if move is None:
        return 0.0
    scale = _CHANNEL_SCALE.get(cid, 1.0)
    return abs(float(move)) / scale if scale > 0 else 0.0


def _verdict_for(expected: str, observed_dir: str, z: float) -> str:
    if expected == "silent":
        return "silent"
    if observed_dir in ("unavailable", "flat"):
        return "silent"
    if z < _Z_FLOOR:
        return "silent"
    return "confirm" if observed_dir == expected else "disconfirm"


def _coherence_score(confirm: float, disconfirm: float) -> Optional[int]:
    total = confirm + disconfirm
    if total <= 0:
        return None
    return int(round(100.0 * confirm / total))


def _coherence_band(score: Optional[int]) -> str:
    if score is None:
        return "silent"
    if score >= _COHERENCE_HIGH:
        return "high"
    if score >= _COHERENCE_MODERATE:
        return "moderate"
    if score >= _COHERENCE_LOW:
        return "low"
    return "rejected"


def _aggregate_verdict(
    confirm: float, disconfirm: float, rejection: bool, tension: bool,
) -> str:
    if rejection:
        return "rejected"
    if tension:
        return "mixed"
    if confirm < _WEAK_CONFIRM_SCORE and disconfirm < _WEAK_CONFIRM_SCORE:
        return "silent"
    if confirm >= _STRONG_CONFIRM_SCORE and disconfirm < _WEAK_CONFIRM_SCORE:
        return "strong_confirm"
    if confirm > disconfirm:
        return "weak_confirm"
    # Fallback (disconfirm ≥ confirm but not qualifying as rejection):
    return "mixed"


def _rationale(
    thesis: str,
    verdict: str,
    confirms: list[str],
    disconfirms: list[str],
    coherence: Optional[int],
    channels: dict[str, dict],
) -> str:
    def _bit(cid: str) -> str:
        ch = channels.get(cid, {})
        return f"{ch.get('label', cid)} ({ch.get('z', 0):.1f}σ)"

    if verdict == "silent":
        return (
            f"Tape silent on {_THESIS_LABELS.get(thesis, thesis)} thesis — "
            f"no channel cleared the noise floor."
        )

    pieces: list[str] = []
    if confirms:
        pieces.append("confirms: " + ", ".join(_bit(c) for c in confirms[:3]))
    if disconfirms:
        pieces.append("disconfirms: " + ", ".join(_bit(c) for c in disconfirms[:3]))
    body = "; ".join(pieces) if pieces else "mixed cross-asset reads"

    tag = {
        "strong_confirm": "tape confirms thesis",
        "weak_confirm":   "tape mildly confirms thesis",
        "mixed":          "tape pulling both ways",
        "rejected":       "tape rejects thesis",
    }.get(verdict, "")

    coh_txt = f" coherence {coherence}/100." if coherence is not None else ""
    return f"{tag}: {body}.{coh_txt}"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

# Channel → representative benchmark ticker used for quarantine lookups.
# Mirrors the same mapping used in shock_decomposition (different channel
# IDs — this module groups by six grouped channels, not five pipeline ones).
# Credit is a spread composite so it's skipped; quarantine on the
# underlying HYG / LQD prints is meaningful but not symmetric to the
# derived spread, so the channel itself is unquarantined.
_COHERENCE_CHANNEL_BENCHMARK: dict[str, str] = {
    "rates":       "10Y",
    "fx":          "DXY",
    "commodities": "CL",
    "vol":         "VIX",
    "equities":    "SPY",
}


def _apply_coherence_quarantine(
    moves: dict[str, Optional[float]],
    snapshots: Optional[list[dict]],
) -> tuple[dict[str, Optional[float]], list[dict]]:
    """Score each channel move through the benchmark quarantine layer.

    Drops the observed move for any channel whose print is quarantined
    (hard-fail) so the scorer doesn't confirm / disconfirm a corrupt
    read.  Returns (possibly-mutated moves, verdict list) for the
    caller to build a top-level ``channel_quality`` block.
    """
    # Lazy import to keep cross_asset_coherence importable even if the
    # quarantine module is broken on an upgrade path.
    from benchmark_quarantine import compute_benchmark_quarantine

    verdicts: list[dict] = []
    out_moves = dict(moves)
    for cid in CHANNEL_IDS:
        market = _COHERENCE_CHANNEL_BENCHMARK.get(cid)
        if market is None:
            continue

        last_price: Optional[float] = None
        if snapshots:
            target = market.upper()
            for s in snapshots:
                if not isinstance(s, dict):
                    continue
                if (s.get("market") or "").upper() == target:
                    last_price = _f(s.get("value"))
                    break

        verdict = compute_benchmark_quarantine(
            market,
            move_5d=out_moves.get(cid),
            last_price=last_price,
        )
        vc = dict(verdict)
        vc["channel"] = cid
        verdicts.append(vc)

        if verdict["data_quality"] == "quarantined":
            # Hard-fail: strip the observed move so the scorer sees an
            # "unavailable" channel rather than a corrupt read.
            out_moves[cid] = None

    return out_moves, verdicts


def compute_cross_asset_coherence(
    thesis: str,
    rates_context: Optional[dict] = None,
    stress_regime: Optional[dict] = None,
    snapshots: Optional[list[dict]] = None,
) -> dict:
    """Build the cross-asset coherence / thesis-rejection block.

    Pure composer — no I/O.  When thesis is ``"none"`` OR no channel
    data is usable, returns a compact block with ``verdict="silent"``.
    Returns ``{}`` only when every input is fully empty.
    """
    thesis = thesis or "none"
    expected_map = _EXPECTED.get(thesis, {})

    moves = _extract_channel_moves(rates_context, stress_regime, snapshots)
    # Benchmark-quarantine pass — hard-fail corrupt prints before the
    # confirm/disconfirm scorer sees them.  Healthy prints pass through
    # unchanged.
    moves, _quarantine_verdicts = _apply_coherence_quarantine(moves, snapshots)
    from benchmark_quarantine import channel_quality_block as _cq_block
    _channel_quality = _cq_block(_quarantine_verdicts)
    any_available = any(v is not None for v in moves.values())

    if not any_available and thesis == "none":
        return {}

    channels_out: dict[str, dict] = {}
    confirms: list[str] = []
    disconfirms: list[str] = []
    silents: list[str] = []
    confirm_score = 0.0
    disconfirm_score = 0.0

    for cid in CHANNEL_IDS:
        move = moves.get(cid)
        expected = expected_map.get(cid, "silent")
        z = _channel_z(cid, move)
        obs_dir = _observed_dir(move)
        verdict = _verdict_for(expected, obs_dir, z)

        weight = 0.0
        if verdict == "confirm":
            weight = z
            confirm_score += z
            confirms.append(cid)
        elif verdict == "disconfirm":
            weight = z
            disconfirm_score += z
            disconfirms.append(cid)
        else:
            silents.append(cid)

        # Attach per-channel quarantine metadata so the UI can render a
        # caution flag next to warn-grade channels and treat quarantined
        # ones as explicitly missing (the scorer has already zeroed them).
        cq_entry = (_channel_quality.get("channels") or {}).get(cid) or {}
        channels_out[cid] = {
            "label":        _CHANNEL_LABELS[cid],
            "expected":     expected,
            "observed":     round(move, 3) if move is not None else None,
            "unit":         _CHANNEL_UNITS[cid],
            "z":            round(z, 2),
            "observed_dir": obs_dir,
            "verdict":      verdict,
            "weight":       round(weight, 2),
            "data_quality": cq_entry.get("data_quality", "ok"),
            "reasons":      list(cq_entry.get("reasons") or []),
        }

    confirms.sort(key=lambda c: -channels_out[c]["weight"])
    disconfirms.sort(key=lambda c: -channels_out[c]["weight"])

    coherence = _coherence_score(confirm_score, disconfirm_score)
    rejection = (
        disconfirm_score >= _REJECTION_DISCONFIRM_FLOOR
        and coherence is not None
        and coherence <= _REJECTION_COHERENCE_CEIL
    )
    tension = (
        confirm_score >= _TENSION_FLOOR
        and disconfirm_score >= _TENSION_FLOOR
        and not rejection
    )
    verdict = _aggregate_verdict(confirm_score, disconfirm_score, rejection, tension)
    coh_band = _coherence_band(coherence)
    # If rejection fires, override the band label so the UI reads consistently.
    if rejection and coh_band != "rejected":
        coh_band = "rejected"

    rationale = _rationale(thesis, verdict, confirms, disconfirms,
                           coherence, channels_out)

    return {
        "thesis":           thesis,
        "thesis_label":     _THESIS_LABELS.get(thesis, thesis),
        "channels":         channels_out,
        "confirms":         confirms,
        "disconfirms":      disconfirms,
        "silent":           silents,
        "confirm_score":    round(confirm_score, 2),
        "disconfirm_score": round(disconfirm_score, 2),
        "coherence":        coherence,
        "coherence_band":   coh_band,
        "coherence_label":  _COHERENCE_BAND_LABELS[coh_band],
        "thesis_rejection": rejection,
        "tension":          tension,
        "verdict":          verdict,
        "verdict_label":    _VERDICT_LABELS[verdict],
        "rationale":        rationale,
        "channel_quality":  _channel_quality,
        "available":        any_available,
        "stale":            not any_available,
    }
