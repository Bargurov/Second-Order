"""
asset_selection.py

Post-LLM asset-selection discipline.

Why this module
---------------
The prompt instructs the LLM to pick direct-name tickers first, sector
ETFs only when diffuse, and never broad-market indices.  In practice
the model still slips in SPY / QQQ / ``^VIX`` or names a sector ETF
when a direct company exists.  That pollutes the downstream agreement
score — a thesis built on CVX + PBF gets a coin-flip reading once the
model buries them under a QQQ proxy that moves with the tape.

This composer sits AFTER the LLM's ticker lists and BEFORE the market
check.  It:

  * Classifies each ticker into tiers
    ``direct_proxy / sector_proxy / second_order / hedge_signal / excluded``.
  * Ranks within each tier (named in beneficiaries/losers text wins;
    list-position is the tiebreaker).
  * Separates primary beneficiary picks from secondary support names
    and hedge/signal assets so the UI and the agreement scorer can
    weight them differently.
  * Excludes low-information picks (broad-market indices, price
    benchmarks, foreign-primary listings) outright — the LLM's mistakes
    never reach market_check.

Pure composer.  No I/O.  Never raises.  Inputs are the LLM's raw
output lists + the text of ``beneficiaries``/``losers`` (for
name-mention boosts) + the event's ``mechanism_family`` (for
channel-pack-aware promotion of sector ETFs).
"""

from __future__ import annotations

from typing import Any, Iterable, Optional


# ---------------------------------------------------------------------------
# Registries — small and opinionated.  Membership beats inference.
# ---------------------------------------------------------------------------

# Broad-market indices / benchmarks — excluded outright.  The prompt
# already forbids them but the LLM slips them in.  Keeping this list
# short + obvious so an engineer can audit: every entry here is
# un-usable as a thesis proxy.
_BROAD_MARKET: frozenset[str] = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "IVV", "RSP",
})

# Index / price-benchmark symbols — not tradable US equities.
_INDEX_OR_BENCHMARK: frozenset[str] = frozenset({
    "^VIX", "VIX", "^SPX", "SPX", "^TNX", "TNX", "^TYX", "TYX",
    "^DJI", "DJI", "^FVX", "FVX", "^RUT", "RUT",
    "DXY", "DX-Y.NYB", "MOVE",
    "TTF", "JKM", "NBP", "HH", "BRENT", "WTI",
})

# Sector equity ETFs mapped to the canonical channel-pack asset class.
# The "channel" key lines up with ``mechanism_family.FAMILY_CHANNEL_PACKS``
# so a sector ETF is promoted to direct tier when the event's family
# has that channel as a PRIMARY-pack channel.
_SECTOR_ETFS: dict[str, str] = {
    # S&P SPDR sector family
    "XLE":  "equities",   "XLF":  "equities", "XLK":  "equities",
    "XLV":  "equities",   "XLY":  "equities", "XLP":  "equities",
    "XLB":  "equities",   "XLI":  "equities", "XLU":  "equities",
    "XLRE": "equities",   "XLC":  "equities",
    # Thematic / narrow industry ETFs
    "SMH":  "equities",   "SOXX": "equities",   # semis
    "XME":  "equities",                          # metals
    "ITA":  "equities",   "XAR":  "equities",    # aerospace & defense
    "KRE":  "equities",   "KBE":  "equities",    # regional banks
    "IYR":  "equities",   "REZ":  "equities",    # real estate
    "BDRY": "equities",   "FRO":  "equities",    # shipping
    "IBB":  "equities",                          # biotech
    "KWEB": "equities",                          # china internet
    "FXI":  "equities",   "EWH":  "equities",    # china large-cap, hong kong
    "EEM":  "equities",   "EWZ":  "equities",    # broad EM, brazil
    "EWY":  "equities",   "EWT":  "equities",    # korea, taiwan
}

# Commodity ETFs — canonical "commodities" channel.  Routed to direct
# tier on commodity-family shocks (supply_shock, commodity_squeeze).
_COMMODITY_ETFS: dict[str, str] = {
    "USO":   "commodities", "UNG":   "commodities",
    "GLD":   "commodities", "IAU":   "commodities", "SLV": "commodities",
    "CPER":  "commodities", "DBA":   "commodities",
    "CORN":  "commodities", "WEAT":  "commodities", "SOYB": "commodities",
    "URA":   "commodities",
}

# Bond / credit ETFs — rates / credit channels.
_BOND_ETFS: dict[str, str] = {
    "TLT":  "rates",  "IEF":  "rates",  "SHY":  "rates",
    "TBF":  "rates",  "TMF":  "rates",
    "LQD":  "credit", "HYG":  "credit", "JNK":  "credit",
    "EMB":  "credit",
}

# FX / currency proxies — always hedge/signal tier, never primary.
_FX_ETFS: frozenset[str] = frozenset({
    "UUP", "UDN", "FXE", "FXY", "FXA", "FXB", "FXC",
    "CEW", "CYB",
})

# Inverse / volatility ETFs — explicit hedge/signal tier so the
# scorer can treat them as a one-way fade signal rather than a direct
# proxy.  Users can still reference them but they never count as a
# beneficiary.
_HEDGE_ETFS: frozenset[str] = frozenset({
    "SH",   "PSQ",  "DOG",                         # inverse equity
    "SQQQ", "SPXU", "TZA", "SDOW",                 # leveraged inverse
    "VXX",  "UVXY", "VIXY", "VIXM",                # vol
    "TBT",                                          # inverse bonds
})

# Hedge/FX/vol ETF → canonical channel.  Kept separate from the
# direct-tier registries above so ``_classify_one`` still tags these as
# ``hedge_signal`` tier, while ``_ticker_channel`` (and every consumer
# that routes a ticker to a macro channel — proof_evaluator,
# cross_event_studies, validation_plan) returns a NAMED channel instead
# of ``None``.  Without this map a VXX direction tag silently drops out
# of vol-channel proof evaluation — a confirming asset with no channel.
_HEDGE_CHANNEL: dict[str, str] = {
    # Vol products carry the vol channel directly.
    "VXX":  "vol",   "UVXY": "vol",   "VIXY": "vol",   "VIXM": "vol",
    # Inverse equity ETFs read on the equities channel (inverted sign
    # is the consumer's problem; the channel is still equities).
    "SH":   "equities", "PSQ":  "equities", "DOG":  "equities",
    "SQQQ": "equities", "SPXU": "equities", "TZA":  "equities",
    "SDOW": "equities",
    # Inverse bonds — rates channel.
    "TBT":  "rates",
}

_FX_CHANNEL: dict[str, str] = {sym: "fx" for sym in _FX_ETFS}


# Foreign-primary listing suffixes that shouldn't ship to a US market
# feed.  The prompt already rules these out; we also enforce here.
_FOREIGN_SUFFIXES: tuple[str, ...] = (
    ".T", ".L", ".TO", ".KS", ".HK", ".PA", ".DE", ".MI", ".MX", ".SA",
)


# ---------------------------------------------------------------------------
# Tier ordering + weights — consumed by callers that want to rank.
# ---------------------------------------------------------------------------

TIER_ORDER: tuple[str, ...] = (
    "direct_proxy",    # the thesis's own named company / commodity
    "sector_proxy",    # sector ETF when the family channel matches
    "second_order",    # sector / thematic whose channel isn't primary
    "hedge_signal",    # inverse / vol / FX — read as signal, not support
    "excluded",        # low-information or forbidden
)


_TIER_RANK: dict[str, int] = {t: i for i, t in enumerate(TIER_ORDER)}


# ---------------------------------------------------------------------------
# Eligibility scoring — per-asset numeric read
# ---------------------------------------------------------------------------
# Every classified asset gets a score in [0, 1] summarising "how useful
# is this proxy for validating the thesis".  Downstream consumers
# (validation_plan, agreement_engine) can filter weak proxies out
# without re-deriving the logic.  Kept tiny and inspectable so an
# engineer can audit any single asset's score from the trace.

# Base score anchored by tier.  The gap between tiers reflects the
# finance-real intuition that a direct name is meaningfully stronger
# than a thematic ETF, which is meaningfully stronger than an
# inverse/hedge read.
_TIER_BASE_SCORE: dict[str, float] = {
    "direct_proxy":  0.90,
    "sector_proxy":  0.75,
    "second_order":  0.50,
    "hedge_signal":  0.30,
    "excluded":      0.00,
}

# Name-mention bump — the LLM explicitly referenced the ticker in the
# beneficiaries / losers text.  Small but meaningful: the writer
# committed to this name specifically, not as a basket default.
_NAME_MENTION_BUMP: float = 0.10

# Position decay — a small penalty per list index, capped so the LLM's
# fourth pick of a direct-name sector still reads as a meaningful
# proxy, not as noise.
_POSITION_DECAY_PER_INDEX: float = 0.05
_POSITION_DECAY_CAP_RATIO: float = 0.40  # ≤ 40% of base score

# Confidence bands keyed on score.  Monotonic so consumers branching
# on the label don't care about threshold movement.
_CONFIDENCE_FLOORS: tuple[tuple[float, str], ...] = (
    (0.75, "high"),
    (0.50, "medium"),
    (0.25, "low"),
)


def compute_eligibility(entry: dict) -> dict:
    """Return ``{score, confidence}`` for a classification entry.

    Pure function of the row's fields (tier, name_mentioned, list_index)
    — no I/O, no external state.  Safe to call on trimmed rows emitted
    by ``classify_and_rank_assets`` OR on the raw internal entries.
    """
    tier = entry.get("tier") or "excluded"
    base = _TIER_BASE_SCORE.get(tier, 0.0)

    score = base
    if entry.get("name_mentioned"):
        score += _NAME_MENTION_BUMP

    idx = int(entry.get("list_index") or 0)
    if idx > 0 and base > 0:
        decay = min(_POSITION_DECAY_PER_INDEX * idx, base * _POSITION_DECAY_CAP_RATIO)
        score -= decay

    score = max(0.0, min(1.0, score))

    confidence = "excluded"
    for floor, label in _CONFIDENCE_FLOORS:
        if score >= floor:
            confidence = label
            break

    return {"score": round(score, 3), "confidence": confidence}


# ---------------------------------------------------------------------------
# Four-component eligibility scoring — explicit per-axis read
# ---------------------------------------------------------------------------
# ``compute_eligibility`` above produces a single composite number for
# back-compat consumers.  This helper exposes the four named axes the
# user contract asks for so the UI / audit can show *why* an asset
# scored where it did:
#
#   direct_exposure  — how directly the ticker expresses the thesis
#                      (single-name = high; basket / hedge = lower)
#   liquidity        — does the ticker route to a tradable US listing
#                      via the registries above (foreign suffixes,
#                      placeholder strings, and unknown shapes score 0)
#   channel_match    — is the ticker's channel inside the family's
#                      mechanism pack (primary vs. secondary vs. off)
#   noise_risk       — high for broad indices / leveraged / off-shape
#                      tickers; low for direct names

# Per-tier base for the direct-exposure axis.
_DIRECT_EXPOSURE_BY_TIER: dict[str, float] = {
    "direct_proxy":  0.85,   # base; named-mention bumps to 1.0 below
    "sector_proxy":  0.50,
    "second_order":  0.35,
    "hedge_signal":  0.20,
    "excluded":      0.00,
}

# Per-tier base for the noise-risk axis.  Higher = more noise / broad-
# read.  Inverse / leveraged / vol products are explicitly higher.
_NOISE_RISK_BY_TIER: dict[str, float] = {
    "direct_proxy":  0.15,
    "sector_proxy":  0.40,
    "second_order":  0.55,
    "hedge_signal":  0.65,
    "excluded":      0.95,
}

# Leveraged / 3x inverse equity ETFs read as much noisier than their
# unlevered cousins because daily compounding drags the read.
_LEVERAGED_INVERSE: frozenset[str] = frozenset({
    "SQQQ", "SPXU", "TZA", "SDOW", "UVXY",
})


def _family_full_channels(family: Optional[str]) -> set[str]:
    """Family's mechanism pack — first ∪ second.  Cached call."""
    try:
        from mechanism_family import FAMILY_CHANNEL_PACKS
        pack = FAMILY_CHANNEL_PACKS.get(family or "none") or {}
        return set(pack.get("first") or []) | set(pack.get("second") or [])
    except Exception:
        return set()


def _channel_for_eligibility(sym: str, tier: Optional[str]) -> Optional[str]:
    """Channel resolution that mirrors validation_plan._asset_channel:
    sector / commodity / bond / hedge / FX ETFs route via _ticker_channel,
    direct single-names default to ``"equities"``."""
    ch = _ticker_channel(sym)
    if ch:
        return ch
    if tier == "direct_proxy" and _looks_like_single_name(sym):
        return "equities"
    return None


def compute_eligibility_components(
    entry: dict,
    *,
    mechanism_family: Optional[str] = None,
) -> dict:
    """Return component scores + composite + short rationale for one
    classified entry.

    Output shape::

        {
          "components": {
              "direct_exposure": float in [0,1],
              "liquidity":       float in [0,1],
              "channel_match":   float in [0,1],
              "noise_risk":      float in [0,1],
          },
          "composite_score":     float in [0,1],
          "eligibility_rationale": short string,
        }

    Pure function — no I/O, no mutation.  Safe to call on trimmed
    rows emitted by ``classify_and_rank_assets`` OR raw internal
    entries.
    """
    tier = entry.get("tier") or "excluded"
    sym_raw = entry.get("symbol")
    sym = sym_raw.strip().upper() if isinstance(sym_raw, str) else ""

    # 1. direct_exposure — name-mention boosts a direct_proxy to 1.0.
    direct_exposure = _DIRECT_EXPOSURE_BY_TIER.get(tier, 0.0)
    if tier == "direct_proxy" and entry.get("name_mentioned"):
        direct_exposure = 1.0

    # 2. liquidity — 0.0 for foreign suffix / index benchmark / unknown
    #    shape; 1.0 otherwise.  Tracks whether we can fetch a US tape
    #    read at all without hitting a foreign feed or a yfinance gap.
    if not sym:
        liquidity = 0.0
    elif sym in _INDEX_OR_BENCHMARK or _has_foreign_suffix(sym):
        liquidity = 0.0
    elif tier == "excluded":
        liquidity = 0.2
    else:
        liquidity = 1.0

    # 3. channel_match — 1.0 on family primary, 0.7 on family secondary,
    #    0.0 off-pack.  When no family is committed the score collapses
    #    to 0.5 (we can't fail a thesis we don't know).
    mechanism_channels = _family_full_channels(mechanism_family)
    primaries = _family_primary_channels().get(mechanism_family or "none") or set()
    if not mechanism_channels:
        channel_match = 0.5
    elif tier == "excluded":
        channel_match = 0.0
    elif tier == "hedge_signal":
        # Hedge tier validates only through its named signal channel,
        # so channel match against the family pack isn't disqualifying;
        # surface 0.5 to mark "channel-mediated, not direct".
        channel_match = 0.5
    else:
        ch = _channel_for_eligibility(sym, tier)
        if ch is None:
            channel_match = 0.0
        elif ch in primaries:
            channel_match = 1.0
        elif ch in mechanism_channels:
            channel_match = 0.7
        else:
            channel_match = 0.0

    # 4. noise_risk — anchored by tier, lifted for broad-market /
    #    leveraged / index / foreign symbols which carry structural
    #    noise even when the LLM picked them.
    noise_risk = _NOISE_RISK_BY_TIER.get(tier, 0.50)
    if sym in _BROAD_MARKET or sym in _INDEX_OR_BENCHMARK:
        noise_risk = max(noise_risk, 0.95)
    elif _has_foreign_suffix(sym):
        noise_risk = max(noise_risk, 0.85)
    elif sym in _LEVERAGED_INVERSE:
        noise_risk = max(noise_risk, 0.80)

    # Composite score: weighted blend.  Higher direct-exposure /
    # liquidity / channel-match push it up; higher noise pushes it
    # down.  Weights tuned so a clean direct name on a primary
    # channel scores ≥ 0.8 while a broad-index stub scores ≤ 0.2.
    composite = (
        0.40 * direct_exposure
        + 0.20 * liquidity
        + 0.30 * channel_match
        + 0.10 * (1.0 - noise_risk)
    )
    composite = max(0.0, min(1.0, composite))

    # Short rationale: lead with the dominant axis — what landed the
    # asset where it did.  Used by the UI / audit so a kept or
    # rejected asset always carries a one-line read.
    if tier == "excluded":
        rationale = f"{sym or 'asset'} excluded by classifier; high noise / non-tradable shape"
    elif tier == "hedge_signal":
        rationale = (
            f"{sym}: signal-only — validates through its named "
            f"channel, never as a thesis beneficiary"
        )
    elif noise_risk >= 0.80:
        rationale = (
            f"{sym}: high noise risk ({noise_risk:.2f}) — "
            f"broad / leveraged / off-shape proxy"
        )
    elif channel_match < 0.5:
        rationale = (
            f"{sym}: channel-match {channel_match:.2f} — outside "
            f"family mechanism pack {sorted(mechanism_channels)}"
        )
    elif tier == "direct_proxy":
        rationale = (
            f"{sym}: direct exposure ({direct_exposure:.2f}) on the "
            f"family's mechanism channel"
        )
    else:
        rationale = (
            f"{sym}: indirect basket (channel-match "
            f"{channel_match:.2f}, noise {noise_risk:.2f})"
        )

    return {
        "components": {
            "direct_exposure": round(direct_exposure, 2),
            "liquidity":       round(liquidity, 2),
            "channel_match":   round(channel_match, 2),
            "noise_risk":      round(noise_risk, 2),
        },
        "composite_score":       round(composite, 3),
        "eligibility_rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Family → primary-channel asset-class set (same seed as agreement_engine).
# ---------------------------------------------------------------------------

_FAMILY_PRIMARY_CACHE: Optional[dict[str, set[str]]] = None


def _family_primary_channels() -> dict[str, set[str]]:
    global _FAMILY_PRIMARY_CACHE
    if _FAMILY_PRIMARY_CACHE is not None:
        return _FAMILY_PRIMARY_CACHE
    try:
        from mechanism_family import FAMILY_CHANNEL_PACKS
        _FAMILY_PRIMARY_CACHE = {
            fam: set(pack.get("first") or [])
            for fam, pack in FAMILY_CHANNEL_PACKS.items()
        }
    except Exception:
        _FAMILY_PRIMARY_CACHE = {}
    return _FAMILY_PRIMARY_CACHE


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _clean_symbol(raw: Any) -> Optional[str]:
    if not isinstance(raw, str):
        return None
    s = raw.strip().upper()
    if not s:
        return None
    return s


def _has_foreign_suffix(sym: str) -> bool:
    return any(sym.endswith(suf) for suf in _FOREIGN_SUFFIXES)


def _looks_like_single_name(sym: str) -> bool:
    """Heuristic: 1-5 alpha chars with no dots or carets — treat as a
    single-company US listing candidate.  Anything ticker-like that
    isn't in an ETF registry falls here."""
    if not sym or "." in sym or "^" in sym:
        return False
    if len(sym) < 1 or len(sym) > 5:
        return False
    return sym.isalpha()


def _ticker_channel(sym: str) -> Optional[str]:
    """Which canonical channel pack does this ETF belong to?

    Returns the named macro channel for direct-tier ETFs (sector /
    commodity / bond) AND for hedge/FX/vol ETFs.  The hedge tier still
    classifies as ``hedge_signal`` for ranking purposes, but every
    asset that carries a real channel pack is required to map back to
    a named channel — otherwise a vol or FX confirming asset silently
    drops out of channel-scoped proof evaluation.
    """
    if sym in _SECTOR_ETFS:
        return _SECTOR_ETFS[sym]
    if sym in _COMMODITY_ETFS:
        return _COMMODITY_ETFS[sym]
    if sym in _BOND_ETFS:
        return _BOND_ETFS[sym]
    if sym in _HEDGE_CHANNEL:
        return _HEDGE_CHANNEL[sym]
    if sym in _FX_CHANNEL:
        return _FX_CHANNEL[sym]
    return None


def _name_mentioned(sym: str, name_text: str) -> bool:
    """True when the ticker symbol appears as a whole word in the
    beneficiaries/losers text.  Case-insensitive, whole-token match —
    ``"XOM"`` inside ``"Exxon (XOM)"`` hits, but ``"GM"`` doesn't hit
    inside ``"GMR shipping"``."""
    if not sym or not isinstance(name_text, str):
        return False
    needle = sym.upper()
    tokens = [t.strip("(),.;:/ ").upper() for t in name_text.replace("·", " ").split()]
    return needle in tokens


# Controlled vocabulary for asset rejection reasons.  Every entry that
# lands in ``excluded_assets`` (here OR in validation_plan downstream)
# carries one of these tags so the UI / audit can branch on a stable
# token instead of free-text rationales that drift over time.
REJECTION_REASONS: tuple[str, ...] = (
    "too_broad",                      # broad-market indices, price benchmarks
    "wrong_channel",                  # asset's channel isn't in the family pack
    "duplicate_proxy",                # second sector ETF on same (side, channel)
    "weak_exposure",                  # foreign listings, unknown ticker shapes
    "signal_only_not_beneficiary",    # hedge tier supplied via beneficiary/loser
)


# Per-tier rationale templates — kept short and inspectable.
def _classify_one(
    sym: str,
    *,
    family: Optional[str],
    name_text: str,
) -> tuple[str, str, Optional[str]]:
    """Return ``(tier, rationale, rejection_reason)`` for a single symbol.

    ``family`` is the event's mechanism_family (may be None / "none").
    ``name_text`` is the joined ``beneficiaries`` + ``losers`` text the
    LLM emitted, used to detect name-mention boosts.
    ``rejection_reason`` is non-None only when the symbol is excluded,
    and uses the controlled ``REJECTION_REASONS`` vocabulary so
    downstream consumers branch on a stable token.
    """
    # Outright exclusions first.
    if sym in _BROAD_MARKET:
        return "excluded", "Broad-market index — no thesis-specific read", "too_broad"
    if sym in _INDEX_OR_BENCHMARK:
        return "excluded", "Price/index benchmark — not a tradable proxy", "too_broad"
    if _has_foreign_suffix(sym):
        return "excluded", "Foreign-primary listing — US market feed unavailable", "weak_exposure"

    # Hedge / signal tier — explicit, never promoted.
    if sym in _HEDGE_ETFS or sym in _FX_ETFS:
        bucket = "FX signal" if sym in _FX_ETFS else "inverse/vol hedge"
        return "hedge_signal", f"{bucket} — direction signal, not a direct proxy", None

    primaries = _family_primary_channels().get(family or "none") or set()
    channel = _ticker_channel(sym)

    if channel is not None:
        # ETF with a known channel — direct tier iff channel is in the
        # family's primary pack.  Commodity ETFs for commodity-family
        # events are the canonical direct case.
        if channel in primaries:
            label = "commodity ETF" if channel == "commodities" else "sector ETF"
            return "sector_proxy", (
                f"{label} on the family's primary channel ({channel})"
            ), None
        return "second_order", (
            f"ETF on a non-primary channel ({channel}) for this family"
        ), None

    # Single-name candidate.
    if _looks_like_single_name(sym):
        if _name_mentioned(sym, name_text):
            return "direct_proxy", (
                "Named in the thesis — direct company exposure"
            ), None
        return "direct_proxy", "Single-name US-listed equity (treated as direct)", None

    # Anything left looks odd — a ticker with dots or unusual shape we
    # couldn't classify.  Safer to exclude than ship to the market check.
    return "excluded", "Unknown ticker shape — excluded defensively", "weak_exposure"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def _normalise_unique(inputs: Iterable[Any]) -> list[str]:
    """Clean + uppercase + dedupe while preserving the LLM's order.
    Non-strings / empties are dropped silently."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in inputs or []:
        sym = _clean_symbol(raw)
        if sym is None or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
    return out


def _rank_within_tier(
    entries: list[dict],
) -> list[dict]:
    """Sort entries within a tier: name-mentioned first, then by LLM
    order (original list index ascending)."""
    entries.sort(key=lambda e: (
        0 if e.get("name_mentioned") else 1,
        e.get("list_index", 0),
    ))
    return entries


def classify_and_rank_assets(
    beneficiary_tickers: Optional[Iterable[Any]] = None,
    loser_tickers:       Optional[Iterable[Any]] = None,
    *,
    mechanism_family:    Optional[str] = None,
    beneficiaries_text:  Optional[Iterable[Any]] = None,
    losers_text:         Optional[Iterable[Any]] = None,
) -> dict[str, Any]:
    """Classify + rank the LLM's ticker lists into tiered proxy roles.

    Returned shape::

        {
          "available":      bool,
          "primary": {
            "beneficiary":  [{"symbol", "tier", "rationale"}, ...],
            "loser":        [...],
          },
          "secondary": {
            "beneficiary":  [...],
            "loser":        [...],
          },
          "hedge_signal":   [...],
          "excluded":       [{"symbol", "reason", "side"}, ...],
          "cleaned_beneficiary_tickers": [str, ...],   # primary + secondary
          "cleaned_loser_tickers":        [str, ...],
          "rationale":      str,
        }

    The cleaned lists are the ones downstream market_check should
    consume — broad indices, price benchmarks, foreign listings, and
    hedge/signal ETFs are removed.  Inputs that were dropped appear in
    ``excluded`` with the reason so the UI and telemetry can audit.
    """
    ben_syms  = _normalise_unique(beneficiary_tickers)
    los_syms  = _normalise_unique(loser_tickers)

    # Ticker collisions across sides — drop from the LOSER side
    # (beneficiary wins by convention; the LLM shouldn't send overlaps
    # but we defend).  Track the drops for telemetry.
    collided = set(ben_syms) & set(los_syms)
    los_syms = [s for s in los_syms if s not in collided]

    name_text = " ".join(str(x) for x in list(beneficiaries_text or []) + list(losers_text or []))

    def _build_side(symbols: list[str], side: str) -> list[dict]:
        out: list[dict] = []
        for idx, sym in enumerate(symbols):
            tier, rationale, rej_reason = _classify_one(
                sym, family=mechanism_family, name_text=name_text,
            )
            out.append({
                "symbol":         sym,
                "tier":           tier,
                "rationale":      rationale,
                "side":            side,
                "list_index":      idx,
                "name_mentioned":  _name_mentioned(sym, name_text),
                "rejection_reason": rej_reason,
            })
        return out

    ben_classified = _build_side(ben_syms, "beneficiary")
    los_classified = _build_side(los_syms, "loser")

    # Partition by tier.
    primary_ben:    list[dict] = []
    secondary_ben:  list[dict] = []
    primary_los:    list[dict] = []
    secondary_los:  list[dict] = []
    hedge:          list[dict] = []
    excluded:       list[dict] = []

    def _excluded_entry(e: dict) -> dict:
        """Build an excluded-row dict with rejection_reason and a
        component-driven eligibility_rationale so the UI / audit
        sees both the controlled tag AND the human-readable read."""
        components = compute_eligibility_components(
            e, mechanism_family=mechanism_family,
        )
        return {
            "symbol":                e["symbol"],
            "reason":                e["rationale"],
            "side":                  e["side"],
            "rejection_reason":      e.get("rejection_reason") or "weak_exposure",
            "eligibility_rationale": components["eligibility_rationale"],
        }

    for e in ben_classified:
        if e["tier"] == "direct_proxy" or e["tier"] == "sector_proxy":
            primary_ben.append(e)
        elif e["tier"] == "second_order":
            secondary_ben.append(e)
        elif e["tier"] == "hedge_signal":
            hedge.append(e)
        else:  # excluded
            excluded.append(_excluded_entry(e))
    for e in los_classified:
        if e["tier"] == "direct_proxy" or e["tier"] == "sector_proxy":
            primary_los.append(e)
        elif e["tier"] == "second_order":
            secondary_los.append(e)
        elif e["tier"] == "hedge_signal":
            hedge.append(e)
        else:
            excluded.append(_excluded_entry(e))
    # Collision rejections — same ticker on both sides is a duplicate
    # of itself across roles; tag as duplicate_proxy so consumers can
    # branch on the controlled vocabulary.
    for sym in collided:
        excluded.append({
            "symbol":                sym,
            "reason":                "Appears on both beneficiary and loser lists",
            "side":                  "both",
            "rejection_reason":      "duplicate_proxy",
            "eligibility_rationale": (
                f"{sym}: appears on both sides of the thesis — "
                "duplicate role assignment"
            ),
        })

    primary_ben   = _rank_within_tier(primary_ben)
    secondary_ben = _rank_within_tier(secondary_ben)
    primary_los   = _rank_within_tier(primary_los)
    secondary_los = _rank_within_tier(secondary_los)

    # "Cleaned" ticker lists — primary + secondary (i.e. survived the
    # filter), keeping side order.  Excludes hedge/signal and excluded.
    cleaned_ben = [e["symbol"] for e in primary_ben] + [e["symbol"] for e in secondary_ben]
    cleaned_los = [e["symbol"] for e in primary_los] + [e["symbol"] for e in secondary_los]

    # Top-level rationale — one institutional line.
    bits: list[str] = []
    bits.append(f"{len(primary_ben)} primary / {len(secondary_ben)} secondary beneficiary")
    if primary_los or secondary_los:
        bits.append(f"{len(primary_los)} primary / {len(secondary_los)} secondary loser")
    if hedge:
        bits.append(f"{len(hedge)} hedge/signal")
    if excluded:
        bits.append(f"{len(excluded)} excluded")
    rationale = "; ".join(bits)

    def _trim_with_family(e: dict) -> dict:
        return _trim(e, mechanism_family=mechanism_family)

    return {
        "available":       bool(primary_ben or secondary_ben or primary_los or secondary_los),
        "primary":         {
            "beneficiary": [_trim_with_family(e) for e in primary_ben],
            "loser":       [_trim_with_family(e) for e in primary_los],
        },
        "secondary":       {
            "beneficiary": [_trim_with_family(e) for e in secondary_ben],
            "loser":       [_trim_with_family(e) for e in secondary_los],
        },
        "hedge_signal":    [_trim_with_family(e) for e in hedge],
        "excluded":        excluded,
        "cleaned_beneficiary_tickers": cleaned_ben,
        "cleaned_loser_tickers":        cleaned_los,
        "rationale":                    rationale,
    }


def _trim(e: dict, *, mechanism_family: Optional[str] = None) -> dict:
    """Strip internal scoring keys from an entry before emission.

    Keeps the fields downstream consumers need to reason about the
    asset: its symbol / tier / rationale / side, the name_mentioned
    flag, the existing composite eligibility read (score + confidence)
    AND the four-axis component breakdown — direct_exposure / liquidity
    / channel_match / noise_risk — plus a short rationale string so
    the UI / audit can render *why* an asset scored where it did.
    """
    eligibility = compute_eligibility(e)
    components = compute_eligibility_components(e, mechanism_family=mechanism_family)
    return {
        "symbol":    e["symbol"],
        "tier":      e["tier"],
        "rationale": e["rationale"],
        "side":      e["side"],
        "name_mentioned":         e.get("name_mentioned", False),
        "eligibility_score":      eligibility["score"],
        "proxy_confidence":       eligibility["confidence"],
        "eligibility_components": components["components"],
        "eligibility_rationale":  components["eligibility_rationale"],
    }
