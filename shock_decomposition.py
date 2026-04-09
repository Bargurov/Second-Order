"""
shock_decomposition.py

Real vs Nominal shock decomposition.

Given the live macro state (rates_context + stress_regime + optional
snapshots), classify which transmission channel is doing the work:

    nominal_yield  — nominal rates (10Y, ^TNX move)
    real_yield     — real rates (TIP move, sign-inverted)
    breakeven      — breakeven inflation (nominal − real proxy)
    fx             — dollar / DXY
    commodity      — gold + crude composite

Returns a compact block with primary driver, secondary drivers, the
short empirical rationale, what it implies for the macro read, and the
key liquid markets that should confirm or challenge it.

Design
------
- Pure composer.  Takes pre-fetched dicts; performs no I/O.
- Channels are normalized via institutional 1-sigma 5d move scales so
  magnitudes can be compared apples-to-apples (yields in %, prices in %).
- Highest normalized magnitude = primary; others above the secondary
  threshold are listed in score order.
- This is a *macro state* read — not driven by event keywords.  The same
  macro state is the same decomposition no matter what headline shipped.
- When no macro inputs are usable, returns the block with
  ``available=False, stale=True`` and an empty channel set so the UI
  can render a degraded "macro unavailable" pill.
- When macro is usable but every channel is below the noise floor,
  returns ``primary="none"`` so the UI can show "no clear shock today".
- Returns ``{}`` only when there is literally no data of any kind.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Channel metadata
# ---------------------------------------------------------------------------

CHANNEL_IDS: tuple[str, ...] = (
    "nominal_yield",
    "real_yield",
    "breakeven",
    "fx",
    "commodity",
)

_CHANNEL_LABELS: dict[str, str] = {
    "nominal_yield": "Nominal yields",
    "real_yield":    "Real yields",
    "breakeven":     "Breakeven inflation",
    "fx":            "Dollar / FX",
    "commodity":     "Commodities",
}

# Institutional 1-sigma 5d move scales.
#
# Unit conventions (must match compute_rates_context output):
#   nominal_yield — absolute pp change in ^TNX Close
#                   (e.g. 0.20 = 20 bps.  NOT percentage change in yield level.)
#   real_yield    — percentage change in TIP ETF price
#                   (e.g. 0.50 = TIP fell/rose 0.50%)
#   breakeven     — nominal_pp_change + TIP_pct_change proxy
#                   (same order of magnitude as nominal pp)
#   fx            — percentage change in DXY (DX-Y.NYB or equivalent)
#   commodity     — percentage change in CL (crude) or GC (gold)
#
# A move of ~1.5× the scale starts to feel real; >2.5× is a regime event.
_CHANNEL_SCALE: dict[str, float] = {
    "nominal_yield": 0.20,   # 20 bps absolute change in ^TNX
    "real_yield":    0.50,   # 0.50% TIP ETF price move
    "breakeven":     0.20,   # breakeven proxy (nominal pp + TIP pct)
    "fx":            0.70,   # 0.70% DXY move
    "commodity":     3.00,   # 3% crude-equivalent move
}

# Sanity caps per channel: move_5d values beyond these thresholds are
# artifacts of corrupted price-cache data (stub rows near zero, or
# _safe_pct applied to a near-zero historical yield start point producing
# values like +2680%).  Discard rather than propagate.
#
# Units match _CHANNEL_SCALE above.
_CHANNEL_MOVE_CAPS: dict[str, float] = {
    "nominal_yield": 5.0,    # ±500 bps in 5 days has never been recorded
    "real_yield":    20.0,   # TIP ETF ±20% in 5 days is physically impossible
    "breakeven":     7.0,    # derived proxy; ceiling a bit above nominal
    "fx":            15.0,   # DXY ±15% in 5 days has never happened
    "commodity":     60.0,   # crude can spike hard but not 60%+ in 5 days
}

# Canonical liquid markets to watch per channel.  These are the same
# market IDs the rest of the product already understands.
_CHANNEL_MARKETS: dict[str, list[str]] = {
    "nominal_yield": ["10Y", "2Y", "30Y", "TLT"],
    "real_yield":    ["TIP", "10Y", "TLT", "GC"],
    "breakeven":     ["TIP", "10Y", "GC", "CL"],
    "fx":            ["DXY", "10Y", "GC", "ES"],
    "commodity":     ["CL", "GC", "DXY", "10Y"],
}

# Macro-read sentence templates per primary driver.
_MACRO_READ: dict[str, str] = {
    "nominal_yield": (
        "Move is in nominal rates with neither real yields nor breakevens "
        "dominating — duration trades will lead the reaction function."
    ),
    "real_yield": (
        "Real yields are doing the work — risk assets and long-duration "
        "growth equities should feel this most directly."
    ),
    "breakeven": (
        "Inflation expectations are leading — gold, TIPS, and commodity-"
        "linked equities should confirm; nominals matter less than the "
        "breakeven path."
    ),
    "fx": (
        "Dollar channel is dominant — EM equities, FX-sensitive multinationals "
        "and commodity prices will reflect the shock first."
    ),
    "commodity": (
        "Commodity-led shock — passthrough to inflation expectations and "
        "energy/materials equities is the main monitoring axis."
    ),
    "none": (
        "All channels are below their normal noise band — no single shock "
        "is doing the work; macro is in a quiet state."
    ),
}


# Ranking floor: a channel must clear this normalized magnitude (z-units)
# to qualify as the primary driver.  Below this, primary is "none".
_PRIMARY_FLOOR: float = 0.8

# Secondary threshold: channels above this normalized magnitude are
# listed alongside the primary.
_SECONDARY_FLOOR: float = 0.6


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
    """Return move if within the sanity cap for this channel, else None.

    Prevents corrupted price-cache values (e.g. +2680% from near-zero
    historical ^TNX rows) from reaching the z-score ranking.
    """
    if move is None:
        return None
    cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
    return move if abs(move) <= cap else None


def _rates_usable(rates_context: Optional[dict]) -> bool:
    if not rates_context or not isinstance(rates_context, dict):
        return False
    nom = (rates_context.get("nominal") or {}).get("change_5d")
    real = (rates_context.get("real_proxy") or {}).get("change_5d")
    return nom is not None or real is not None


def _stress_haven_assets(stress_regime: Optional[dict]) -> dict:
    """Return the safe-haven asset 5d returns dict from stress_regime.

    Stress regime exposes Gold/Dollar/Long Bonds 5d under
    ``detail.safe_haven.assets``.  Empty dict when unavailable.
    """
    if not stress_regime or not isinstance(stress_regime, dict):
        return {}
    detail = stress_regime.get("detail") or {}
    safe = detail.get("safe_haven") or {}
    assets = safe.get("assets") or {}
    return assets if isinstance(assets, dict) else {}


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


# ---------------------------------------------------------------------------
# Channel extraction
# ---------------------------------------------------------------------------

def _extract_channels(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> dict[str, dict]:
    """Pull each channel's 5d move from the supplied macro inputs.

    Returns {channel_id: {label, move_5d, available, scale}} for every
    channel id (channels with no data are still present with
    ``available=False`` so the UI never KeyErrors).
    """
    out: dict[str, dict] = {
        cid: {
            "label":     _CHANNEL_LABELS[cid],
            "move_5d":   None,
            "available": False,
            "scale":     _CHANNEL_SCALE[cid],
        }
        for cid in CHANNEL_IDS
    }

    rc = rates_context or {}
    nom_5d = _safe_move("nominal_yield", _f((rc.get("nominal") or {}).get("change_5d")))
    real_5d = _safe_move("real_yield", _f((rc.get("real_proxy") or {}).get("change_5d")))
    be_5d = _safe_move("breakeven", _f((rc.get("breakeven_proxy") or {}).get("change_5d")))

    if nom_5d is not None:
        out["nominal_yield"]["move_5d"] = nom_5d
        out["nominal_yield"]["available"] = True
    if real_5d is not None:
        out["real_yield"]["move_5d"] = real_5d
        out["real_yield"]["available"] = True
    if be_5d is not None:
        out["breakeven"]["move_5d"] = be_5d
        out["breakeven"]["available"] = True

    # FX: prefer snapshot DXY, fall back to safe-haven Dollar.
    dxy_5d = _safe_move("fx", _snap_change_5d(snapshots, "DXY"))
    if dxy_5d is None:
        haven = _stress_haven_assets(stress_regime)
        dxy_5d = _safe_move("fx", _f(haven.get("Dollar")))
    if dxy_5d is not None:
        out["fx"]["move_5d"] = dxy_5d
        out["fx"]["available"] = True

    # Commodities: composite of crude + gold (whichever is moving more,
    # measured against its own scale).  This avoids the equal-weight bias
    # that would let small gold moves outweigh big crude moves.
    cl_5d = _safe_move("commodity", _snap_change_5d(snapshots, "CL"))
    gc_5d = _safe_move("commodity", _snap_change_5d(snapshots, "GC"))
    if gc_5d is None:
        haven = _stress_haven_assets(stress_regime)
        gc_5d = _safe_move("commodity", _f(haven.get("Gold")))

    cmdty_components: list[tuple[str, float, float]] = []
    if cl_5d is not None:
        cmdty_components.append(("crude", cl_5d, 3.0))
    if gc_5d is not None:
        cmdty_components.append(("gold", gc_5d, 1.5))

    if cmdty_components:
        # Pick the component with the largest normalized magnitude as the
        # representative move.  Stash both raw values for the UI.
        leader = max(cmdty_components, key=lambda c: abs(c[1]) / c[2])
        out["commodity"]["move_5d"] = leader[1]
        out["commodity"]["available"] = True
        out["commodity"]["leader"] = leader[0]
        if cl_5d is not None:
            out["commodity"]["crude_5d"] = cl_5d
        if gc_5d is not None:
            out["commodity"]["gold_5d"] = gc_5d
        # Effective scale matches whichever leg is leading.
        out["commodity"]["scale"] = leader[2]

    return out


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------

def _normalized_magnitude(channel: dict) -> float:
    move = channel.get("move_5d")
    scale = channel.get("scale") or 1.0
    if move is None or scale <= 0:
        return 0.0
    return abs(float(move)) / scale


def _rank_channels(channels: dict[str, dict]) -> list[tuple[str, float]]:
    """Return [(channel_id, normalized_magnitude), ...] sorted desc.

    Only available channels are returned.
    """
    rows: list[tuple[str, float]] = []
    for cid, ch in channels.items():
        if not ch.get("available"):
            continue
        rows.append((cid, _normalized_magnitude(ch)))
    rows.sort(key=lambda r: -r[1])
    return rows


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

def _fmt_move(move: Optional[float]) -> str:
    if move is None:
        return "—"
    return f"{move:+.2f}%"


def _rationale(primary: str, channels: dict[str, dict],
               ranked: list[tuple[str, float]]) -> str:
    """Return a one-line empirical rationale.

    Always tied to actual numbers — never generic prose.
    """
    if primary == "none":
        if not ranked:
            return "All transmission channels unavailable; cannot decompose."
        top = ranked[0]
        ch = channels[top[0]]
        return (
            f"All channels below noise band — leader is "
            f"{_CHANNEL_LABELS[top[0]].lower()} at {_fmt_move(ch.get('move_5d'))} / 5d "
            f"({top[1]:.1f}σ)."
        )

    primary_ch = channels[primary]
    primary_move = primary_ch.get("move_5d")
    primary_z = _normalized_magnitude(primary_ch)

    bits = [
        f"{_CHANNEL_LABELS[primary].lower()} {_fmt_move(primary_move)} / 5d "
        f"({primary_z:.1f}σ)"
    ]

    # Add the next ranked channel for contrast (if any).
    for cid, z in ranked[1:3]:
        ch = channels[cid]
        bits.append(
            f"{_CHANNEL_LABELS[cid].lower()} {_fmt_move(ch.get('move_5d'))} ({z:.1f}σ)"
        )

    return f"Primary mover: {bits[0]}" + (
        " — vs " + ", ".join(bits[1:]) if len(bits) > 1 else ""
    )


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_shock_decomposition(
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]] = None,
) -> dict:
    """Decompose the live macro shock into transmission channels.

    Pure composer — no I/O.  All inputs optional; degrades gracefully:
      - No usable inputs at all → ``{}`` (UI skips the card).
      - Only some channels available → block with ``stale=True`` and the
        unavailable channels marked ``available=False``.
      - All channels quiet → ``primary="none"`` and macro_read explains.
    """
    rates_ok = _rates_usable(rates_context)
    stress_ok = bool(stress_regime and isinstance(stress_regime, dict)
                     and (stress_regime.get("raw") or stress_regime.get("detail")))

    channels = _extract_channels(rates_context, stress_regime, snapshots)
    available_count = sum(1 for c in channels.values() if c["available"])

    # Hard short-circuit: nothing to say at all.
    if available_count == 0 and not rates_ok and not stress_ok:
        return {}

    ranked = _rank_channels(channels)

    if not ranked:
        # Macro inputs were nominally present but every channel ended up
        # unavailable (e.g. snapshots all errored).  Surface a stale block.
        return {
            "primary":       "none",
            "primary_label": "Macro unavailable",
            "secondary":     [],
            "rationale":     "No channel had a usable 5d move.",
            "macro_read":    _MACRO_READ["none"],
            "key_markets":   [],
            "channels":      _channels_for_payload(channels),
            "available":     False,
            "stale":         True,
        }

    top_id, top_z = ranked[0]
    if top_z < _PRIMARY_FLOOR:
        primary = "none"
    else:
        primary = top_id

    secondary: list[dict] = []
    for cid, z in ranked[1:]:
        if z < _SECONDARY_FLOOR:
            continue
        secondary.append({
            "id":       cid,
            "label":    _CHANNEL_LABELS[cid],
            "move_5d":  channels[cid].get("move_5d"),
            "z":        round(z, 2),
        })
        if len(secondary) >= 3:
            break

    primary_label = (
        _CHANNEL_LABELS[primary] if primary != "none" else "No clear shock"
    )
    key_markets = list(_CHANNEL_MARKETS.get(primary, [])) if primary != "none" else []
    rationale = _rationale(primary, channels, ranked)
    macro_read = _MACRO_READ.get(primary, _MACRO_READ["none"])

    # Stale flag: any of the five channels is missing.
    stale = available_count < len(CHANNEL_IDS)

    return {
        "primary":       primary,
        "primary_label": primary_label,
        "secondary":     secondary,
        "rationale":     rationale,
        "macro_read":    macro_read,
        "key_markets":   key_markets,
        "channels":      _channels_for_payload(channels),
        "available":     True,
        "stale":         stale,
    }


def sanitize_shock_decomposition_block(block: dict) -> dict:
    """Clamp absurd move_5d values in a persisted shock-decomposition block.

    Frozen-archive events were saved before the unit fix landed; their channel
    dicts may carry move_5d values like +2680 (from _safe_pct on near-zero
    historical ^TNX rows).  This function applies _CHANNEL_MOVE_CAPS and
    recalculates z-scores so the frontend never sees those artifacts.

    Returns a deep copy with clamped values — does not mutate the input.
    Idempotent: safe to call on already-sanitized blocks.
    """
    import copy
    if not block or not isinstance(block, dict):
        return block or {}

    block = copy.deepcopy(block)

    channels = block.get("channels") or {}
    for cid, ch in channels.items():
        if not isinstance(ch, dict):
            continue
        move = ch.get("move_5d")
        if move is None:
            continue
        cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
        if abs(float(move)) > cap:
            ch["move_5d"] = None
            ch["available"] = False
            ch["z"] = 0.0

    # Sanitize secondary list — drop any entry whose move is absurd.
    secondary = block.get("secondary") or []
    clean_secondary = []
    for s in secondary:
        if not isinstance(s, dict):
            continue
        cid = s.get("id", "")
        move = s.get("move_5d")
        cap = _CHANNEL_MOVE_CAPS.get(cid, 100.0)
        if move is not None and abs(float(move)) > cap:
            continue
        clean_secondary.append(s)
    block["secondary"] = clean_secondary

    return block


def _channels_for_payload(channels: dict[str, dict]) -> dict[str, dict]:
    """Strip internal fields ("scale") and round numbers for JSON payload."""
    out: dict[str, dict] = {}
    for cid, ch in channels.items():
        entry = {
            "label":     ch["label"],
            "move_5d":   round(ch["move_5d"], 3) if ch.get("move_5d") is not None else None,
            "available": ch["available"],
            "z":         round(_normalized_magnitude(ch), 2),
        }
        # Carry through commodity sub-components when present.
        if "crude_5d" in ch:
            entry["crude_5d"] = round(ch["crude_5d"], 3)
        if "gold_5d" in ch:
            entry["gold_5d"] = round(ch["gold_5d"], 3)
        if "leader" in ch:
            entry["leader"] = ch["leader"]
        out[cid] = entry
    return out
