"""
evidence_attribution.py

Evidence-memo layer on top of the validation chain.

Why this module
---------------
The agreement engine, the evidence ladder, and the channel-timing
scorer each emit a single aggregate read — useful but opaque when a
reader wants to know *which* specific signal drove the conclusion.
A macro desk's validation memo doesn't say "0.35 mixed" — it says
"XOM +3% direct supports on alpha; bank credit hasn't cascaded;
tape is flat elsewhere".

This module produces that attribution layer:

  * **dominant_confirming**    — the single ticker / channel carrying
    the strongest positive contribution (or None when absent).
  * **dominant_contradiction** — the single ticker / channel carrying
    the strongest negative contribution.
  * **missing_proof**          — channels the event's mechanism family
    expects to confirm, but that haven't fired (no observation in
    the window, or flat at peak_end).
  * **channel_breakdown**       — per-channel net factor + support /
    contradict counts, sorted by magnitude so the reader sees the
    heaviest contributors first.
  * **confirmation_shape**       — one of six canonical shapes that
    tell the reader HOW the thesis is earning its score:
      ``single_decisive_channel`` / ``broad_confirmation`` /
      ``mixed_offset`` / ``unilateral_contradiction`` /
      ``scattered_weak`` / ``absent``.

Plus a compact narrative a reader can scan like a research bullet.

Pure composer.  No I/O.  Never raises.  Missing inputs degrade to
the ``absent`` shape without crashing downstream consumers.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Canonical shapes — the six institutional answers to "how is this
# thesis earning its score?".  Ordering matters when classifying:
# unilateral contradiction preempts the positive shapes, absent
# preempts everything when sample is too thin.
# ---------------------------------------------------------------------------

CONFIRMATION_SHAPES: tuple[str, ...] = (
    "single_decisive_channel",
    "broad_confirmation",
    "mixed_offset",
    "unilateral_contradiction",
    "scattered_weak",
    "absent",
)


_SHAPE_LABEL: dict[str, str] = {
    "single_decisive_channel":  "Single decisive channel",
    "broad_confirmation":       "Broad confirmation across channels",
    "mixed_offset":             "Confirming + contradicting channels offset",
    "unilateral_contradiction": "Unilateral contradiction",
    "scattered_weak":           "Scattered weak evidence",
    "absent":                   "No meaningful evidence",
}


# Thresholds — pinned small so constants-test locks any future drift.
_DECISIVE_SHARE: float = 0.60    # top channel carries ≥60% of |total|
_MEANINGFUL_FACTOR: float = 0.30 # per-channel factor above which a channel counts
_OFFSET_FACTOR: float = 0.50     # both sides must clear this to be "mixed_offset"
_BROAD_MIN_CHANNELS: int = 3     # ≥3 channels with meaningful positives


# ---------------------------------------------------------------------------
# Ticker → channel mapping helpers (reuse the same sector map the
# agreement engine uses; duplicated here is worse than coupled import).
# ---------------------------------------------------------------------------

def _ticker_channel(ticker: dict) -> Optional[str]:
    """Derive the canonical channel for a ticker via its
    ``benchmark_sector``.  Returns None when the sector isn't mapped."""
    try:
        from agreement_engine import _channel_for_sector
    except Exception:
        return None
    return _channel_for_sector(ticker.get("benchmark_sector"))


# ---------------------------------------------------------------------------
# Direction helpers
# ---------------------------------------------------------------------------

def _direction_sign(ticker: dict) -> float:
    """Return +1 for a thesis-supporting move, -1 for contradicting,
    0 for flat / unusable.  Prefers the rich ``validation_quality``
    field; falls back to ``direction_tag``."""
    vq = (ticker.get("validation_quality") or "").strip().lower()
    if vq in ("alpha_support", "beta_aligned"):
        return +1.0
    if vq in ("alpha_contradicts", "beta_contradicts"):
        return -1.0
    if vq in ("drift", "flat", "unavailable"):
        return 0.0
    dt = (ticker.get("direction_tag") or "").strip().lower()
    if dt.startswith("supports"):
        return +1.0
    if dt.startswith("contradicts"):
        return -1.0
    return 0.0


def _contribution_weight(ticker: dict) -> float:
    """How heavily does this ticker count in the attribution aggregate?

    Alpha observations get full weight (1.0); beta observations are
    half-weight so a tape-led corroboration doesn't drown out a direct
    alpha hit.  Legacy rows (direction_tag only) are treated as full
    weight to match the existing agreement-engine behaviour.
    """
    vq = (ticker.get("validation_quality") or "").strip().lower()
    if vq in ("alpha_support", "alpha_contradicts"):
        return 1.0
    if vq in ("beta_aligned", "beta_contradicts"):
        return 0.5
    if vq in ("drift", "flat", "unavailable", ""):
        return 1.0 if ticker.get("direction_tag") else 0.0
    return 1.0


# ---------------------------------------------------------------------------
# Core aggregation
# ---------------------------------------------------------------------------

def _build_observations(tickers: list[dict]) -> list[dict]:
    """Turn raw tickers into attribution-friendly observation records."""
    obs: list[dict] = []
    for t in tickers or []:
        if not isinstance(t, dict):
            continue
        channel = _ticker_channel(t)
        if channel is None:
            continue
        sign = _direction_sign(t)
        weight = _contribution_weight(t)
        contribution = sign * weight
        if contribution == 0 and not ticker_is_counted_flat(t):
            # Flat / drifting / unavailable — not evidence in either
            # direction.  Excluded from the aggregate.
            continue
        obs.append({
            "symbol":        t.get("symbol"),
            "channel":       channel,
            "sign":          sign,
            "contribution": contribution,
            "return_5d":    t.get("return_5d"),
            "validation_quality": t.get("validation_quality"),
            "direction_tag":      t.get("direction_tag"),
        })
    return obs


def ticker_is_counted_flat(t: dict) -> bool:
    """Kept as a hook for future policy — currently never counts flat
    tickers into the aggregate so the attribution never surfaces a
    "dominant" signal that's actually zero."""
    return False


def _aggregate_by_channel(obs: list[dict]) -> list[dict]:
    """Sum contributions per channel + count support / contradict hits."""
    by_channel: dict[str, dict] = {}
    for o in obs:
        ch = o["channel"]
        slot = by_channel.setdefault(ch, {
            "channel":        ch,
            "net_factor":     0.0,
            "abs_factor":     0.0,
            "n_support":      0,
            "n_contradict":   0,
            "symbols_support":    [],
            "symbols_contradict": [],
        })
        slot["net_factor"] += o["contribution"]
        slot["abs_factor"] += abs(o["contribution"])
        if o["sign"] > 0:
            slot["n_support"] += 1
            if o.get("symbol"):
                slot["symbols_support"].append(o["symbol"])
        elif o["sign"] < 0:
            slot["n_contradict"] += 1
            if o.get("symbol"):
                slot["symbols_contradict"].append(o["symbol"])

    breakdown = [
        {
            "channel":         slot["channel"],
            "net_factor":      round(slot["net_factor"], 3),
            "abs_factor":      round(slot["abs_factor"], 3),
            "n_support":       slot["n_support"],
            "n_contradict":    slot["n_contradict"],
            "symbols_support":    list(dict.fromkeys(slot["symbols_support"])),
            "symbols_contradict": list(dict.fromkeys(slot["symbols_contradict"])),
        }
        for slot in by_channel.values()
    ]
    breakdown.sort(key=lambda s: (-abs(s["net_factor"]), s["channel"]))
    return breakdown


def _top_by(obs: list[dict], sign_filter: str) -> Optional[dict]:
    """Pick the single strongest observation by |contribution| within
    the sign filter.  ``sign_filter`` is 'support' or 'contradict'."""
    if not obs:
        return None
    if sign_filter == "support":
        candidates = [o for o in obs if o["contribution"] > 0]
    else:
        candidates = [o for o in obs if o["contribution"] < 0]
    if not candidates:
        return None
    top = max(candidates, key=lambda o: abs(o["contribution"]))
    note_bits: list[str] = []
    if top.get("symbol"):
        verb = "supports" if sign_filter == "support" else "contradicts"
        note_bits.append(f"{top['symbol']} {verb}")
    if top.get("return_5d") is not None:
        r = float(top["return_5d"])
        note_bits.append(f"5d {r:+.1f}%")
    if top.get("validation_quality"):
        note_bits.append(str(top["validation_quality"]).replace("_", " "))
    return {
        "ticker":       top.get("symbol"),
        "channel":      top["channel"],
        "contribution": round(abs(top["contribution"]), 3),
        "note":         " · ".join(note_bits) or None,
    }


# ---------------------------------------------------------------------------
# Missing-proof derivation
# ---------------------------------------------------------------------------

def _missing_proof(
    family: Optional[str],
    breakdown: list[dict],
) -> list[dict[str, Any]]:
    """Channels the family's FIRST pack expects that haven't fired —
    either absent from the observation list OR present but net-zero /
    flat (the signal didn't arrive)."""
    if not family or family == "none":
        return []
    try:
        from mechanism_family import FAMILY_CHANNEL_PACKS
    except Exception:
        return []
    pack = FAMILY_CHANNEL_PACKS.get(family) or {}
    first_channels = pack.get("first") or []
    if not first_channels:
        return []
    # Map breakdown for lookup.
    seen = {
        b["channel"]: b for b in breakdown
    }
    # Also fold equities_downstream → equities for the family-pack check
    # since the pack uses "equities" as the canonical channel name.
    if "equities_downstream" in seen and "equities" not in seen:
        seen["equities"] = seen["equities_downstream"]

    missing: list[dict[str, Any]] = []
    for ch in first_channels:
        entry = seen.get(ch)
        if entry is None:
            missing.append({
                "channel":       ch,
                "why_expected":  f"{family}'s primary channel; no observation in the basket",
                "reason_code":   "no_observation",
            })
            continue
        if abs(entry["net_factor"]) < _MEANINGFUL_FACTOR * 0.7:
            # Present but flat — the signal didn't actually move.
            missing.append({
                "channel":      ch,
                "why_expected": f"{family}'s primary channel; observed but net-flat",
                "reason_code":  "observed_flat",
            })
    return missing


# ---------------------------------------------------------------------------
# Shape classifier
# ---------------------------------------------------------------------------

def _classify_shape(breakdown: list[dict]) -> str:
    if not breakdown:
        return "absent"

    total_abs = sum(b["abs_factor"] for b in breakdown)
    if total_abs < 0.3:
        return "absent"

    top = breakdown[0]   # already sorted by |net_factor| desc
    top_share = abs(top["net_factor"]) / total_abs if total_abs > 0 else 0.0

    positives = [b for b in breakdown if b["net_factor"] >= _MEANINGFUL_FACTOR]
    negatives = [b for b in breakdown if b["net_factor"] <= -_MEANINGFUL_FACTOR]

    # Unilateral contradiction: top is strongly negative and no
    # meaningful positive channel exists.
    if top["net_factor"] < 0 and top_share >= _DECISIVE_SHARE and not positives:
        return "unilateral_contradiction"

    # Mixed offset: both sides have meaningful signals AND at least one
    # side clears the offset floor.
    if positives and negatives and (
        max(b["net_factor"] for b in positives) >= _OFFSET_FACTOR
        or abs(min(b["net_factor"] for b in negatives)) >= _OFFSET_FACTOR
    ):
        return "mixed_offset"

    # Single decisive channel: one positive channel carries most of
    # the total weight.
    if top["net_factor"] > 0 and top_share >= _DECISIVE_SHARE:
        return "single_decisive_channel"

    # Broad confirmation: 3+ positive channels, no meaningful negatives.
    if len(positives) >= _BROAD_MIN_CHANNELS and not negatives:
        return "broad_confirmation"

    # Otherwise the evidence is real but scattered.
    return "scattered_weak"


# ---------------------------------------------------------------------------
# Narrative composition
# ---------------------------------------------------------------------------

def _compose_narrative(
    shape: str,
    dominant_confirming: Optional[dict],
    dominant_contradiction: Optional[dict],
    missing: list[dict],
) -> str:
    """Evidence-memo-style one-liner.  Names the dominant signals and
    flags the missing proofs without using hedged language."""
    bits: list[str] = []

    if shape == "single_decisive_channel" and dominant_confirming:
        bits.append(
            f"Thesis is strong primarily on one channel — "
            f"{dominant_confirming['channel']} "
            f"({dominant_confirming.get('ticker') or 'unnamed'} leading)"
        )
    elif shape == "broad_confirmation" and dominant_confirming:
        bits.append(
            "Broad confirmation — multiple channels aligning; top: "
            f"{dominant_confirming['channel']}"
        )
    elif shape == "mixed_offset":
        if dominant_confirming and dominant_contradiction:
            bits.append(
                f"Confirming {dominant_confirming['channel']} offset by "
                f"contradicting {dominant_contradiction['channel']}"
            )
        else:
            bits.append("Confirming and contradicting channels offsetting")
    elif shape == "unilateral_contradiction" and dominant_contradiction:
        bits.append(
            f"Thesis contradicted by {dominant_contradiction['channel']} "
            f"({dominant_contradiction.get('ticker') or 'unnamed'} leading "
            "against); no offsetting confirmation"
        )
    elif shape == "scattered_weak":
        bits.append(
            "Evidence is scattered — multiple small signals, no decisive channel"
        )
    elif shape == "absent":
        bits.append("No material evidence in the observed basket")
    else:
        bits.append(_SHAPE_LABEL.get(shape, shape))

    if missing:
        miss_channels = ", ".join(m["channel"] for m in missing[:3])
        bits.append(f"missing proof on {miss_channels}")

    return "; ".join(bits) + "."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_evidence_attribution(
    tickers: Optional[list[dict]],
    *,
    mechanism_family: Optional[str] = None,
) -> dict[str, Any]:
    """Build the evidence-attribution block.

    Returned shape::

        {
          "available":               bool,
          "confirmation_shape":      str,
          "shape_label":             str,
          "dominant_confirming":     {ticker, channel, contribution, note} | None,
          "dominant_contradiction":  {ticker, channel, contribution, note} | None,
          "missing_proof":            [{channel, why_expected, reason_code}, ...],
          "channel_breakdown":        [{channel, net_factor, abs_factor,
                                        n_support, n_contradict,
                                        symbols_support, symbols_contradict}, ...],
          "narrative":                str,
        }

    ``tickers`` is the mover card's ``big_moves`` list (or any list of
    ticker dicts with ``symbol`` / ``benchmark_sector`` / one of
    ``validation_quality`` / ``direction_tag``).  Missing / malformed
    input yields the ``absent`` shape with empty lists — never raises.
    """
    obs = _build_observations(tickers or [])
    breakdown = _aggregate_by_channel(obs)
    shape = _classify_shape(breakdown)

    dom_sup = _top_by(obs, "support") if obs else None
    dom_con = _top_by(obs, "contradict") if obs else None

    missing = _missing_proof(mechanism_family, breakdown)
    narrative = _compose_narrative(shape, dom_sup, dom_con, missing)
    sources = _build_attribution_evidence_sources(obs, breakdown, missing)

    return {
        "available":              bool(obs),
        "confirmation_shape":     shape,
        "shape_label":            _SHAPE_LABEL.get(shape, shape),
        "dominant_confirming":    dom_sup,
        "dominant_contradiction": dom_con,
        "missing_proof":          missing,
        "channel_breakdown":      breakdown,
        "narrative":              narrative,
        "evidence_sources":       sources,
    }


def _build_attribution_evidence_sources(
    observations: list[dict],
    breakdown: list[dict],
    missing: list[dict],
) -> list[dict]:
    """Compose ``evidence_sources`` traceability for the validation
    basket.  Each per-ticker observation that contributes a non-zero
    sign becomes a source; channels in the family pack that didn't fire
    surface as neutral with a substantive limitation.  No new data is
    fetched.
    """
    try:
        from evidence_sources import make_source
    except Exception:
        return []

    out: list[dict] = []

    # Per-ticker contributions — one source per non-zero observation.
    n_obs = len(observations)
    for o in observations:
        sign = o.get("sign", 0)
        if sign == 0:
            continue
        symbol = o.get("symbol") or "?"
        channel = o.get("channel") or "unclassified"
        direction = "supports" if sign > 0 else "contradicts"
        vq = (o.get("validation_quality") or "").strip().lower()

        limitation = ""
        if vq.startswith("beta"):
            limitation = "beta-aligned tape — no direct alpha confirmation"
        elif n_obs == 1:
            limitation = "single-channel signal — no cross-confirmation"
        elif o.get("return_5d") is None:
            limitation = "no 5d return on the proxy"

        src = make_source(
            source_type="ticker_observation",
            field_used=f"evidence_attribution.channel_breakdown.{channel}.{symbol}",
            supports_or_contradicts=direction,
            limitation=limitation,
        )
        if src:
            out.append(src)

    # Missing-proof entries — channels the family pack expected but that
    # never fired.  Surfaced as neutral with a concrete limitation so a
    # reader can see the gap on the audit trail.
    for m in missing:
        ch = m.get("channel") or "unclassified"
        reason = m.get("reason_code") or "absent"
        if reason == "no_observation":
            limitation = "expected channel had no observation in basket"
        elif reason == "observed_flat":
            limitation = "expected channel observed but net-flat"
        else:
            limitation = "expected channel did not fire"
        src = make_source(
            source_type="market_channel",
            field_used=f"evidence_attribution.missing_proof.{ch}",
            supports_or_contradicts="neutral",
            limitation=limitation,
        )
        if src:
            out.append(src)

    return out
