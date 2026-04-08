"""
policy_constraint.py

Policy Constraint Engine.

Identifies the *binding* macro-policy constraint for an event and the
secondary constraints the reaction function has to juggle.  The goal is
not a generic risk list — it's a compact, institutional diagnosis of
which lever the authority (Fed / ECB / Treasury / EM central bank) can
actually pull, and which it cannot.

Constraint set (fixed, ordered by canonical macro importance):

    inflation            — price stability mandate
    growth               — real activity / employment mandate
    financial_stability  — funding markets, credit, liquidity
    external_balance     — FX, reserves, current account / capital flows
    fiscal               — debt sustainability, bond supply, term premium

For each event we return:

    {
      binding:            <constraint id>,
      binding_label:      <human label>,
      secondary:          [{id, label, score, rationale}, ...],
      policy_room:        "ample" | "limited" | "constrained" | "mixed" | "unknown",
      why:                one institutional-tone sentence,
      reaction_function:  one sentence on what the authority can actually do,
      key_markets:        ["10Y", "GC", "DXY", ...],
      signals:            {<id>: score, ...},     # transparency
      available:          bool,
      stale:              bool,
    }

Design
------
- Pure composer.  Takes pre-fetched `rates_context`, `stress_regime`,
  and optional `snapshots` from the existing warm path.  No new fetches,
  no parallel data plane.
- Scoring is numeric (0..N) per constraint.  Highest score = binding.
- Ties / low top-score → `policy_room="mixed"` and `secondary` is
  populated so the UI shows a constraint conflict, not a false winner.
- When neither `rates_context` nor `stress_regime` are usable, the
  module still tries to read the thesis from keywords and degrades
  with `available=False, stale=True`.
- Returns `{}` only when there is literally no signal *and* no thesis
  (non-macro event) — so api.py can skip rendering the card.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Constraint identifiers + display metadata
# ---------------------------------------------------------------------------

CONSTRAINT_IDS: tuple[str, ...] = (
    "inflation",
    "growth",
    "financial_stability",
    "external_balance",
    "fiscal",
)

_CONSTRAINT_LABELS: dict[str, str] = {
    "inflation":            "Inflation",
    "growth":               "Growth",
    "financial_stability":  "Financial stability",
    "external_balance":     "External balance / FX",
    "fiscal":               "Fiscal",
}

# Canonical liquid markets that should reflect each constraint.  These are
# the same market IDs that already live in market_universe.LIQUID_MARKETS
# (ES/NQ/RTY/CL/GC/DXY/2Y/10Y), plus a few non-universe tickers the product
# already fetches in compute_stress_regime (HYG, TIP, VIX).  Keeping them
# as strings so the UI can render labels without a lookup.
_CONSTRAINT_MARKETS: dict[str, list[str]] = {
    "inflation":           ["10Y", "TIP", "GC", "CL", "DXY"],
    "growth":              ["ES", "NQ", "RTY", "2Y", "HYG"],
    "financial_stability": ["VIX", "HYG", "2Y", "ES"],
    "external_balance":    ["DXY", "10Y", "GC", "ES"],
    "fiscal":              ["10Y", "30Y", "DXY", "GC"],
}


# ---------------------------------------------------------------------------
# Keyword maps — intentionally compact and institutional
# ---------------------------------------------------------------------------

_INFLATION_KW: tuple[str, ...] = (
    "inflation", "cpi", "pce", "price pressure", "tariff", "opec",
    "wage", "rent", "energy price", "oil price", "crude price",
    "food price", "supply shock", "input cost", "passthrough",
    "sticky", "price hike", "commodity rally",
)

_GROWTH_KW: tuple[str, ...] = (
    "recession", "growth scare", "unemployment", "jobless", "layoff",
    "payrolls", "pmi", "ism", "demand destruction", "consumer pullback",
    "retail sales", "slowdown", "soft landing", "gdp", "contraction",
    "softening demand",
)

_FINSTAB_KW: tuple[str, ...] = (
    "bank run", "deposit", "credit", "spread", "contagion", "liquidity",
    "svb", "default", "repo", "funding stress", "basis trade",
    "margin call", "dealer", "leverage", "shadow bank",
)

_EXTBAL_KW: tuple[str, ...] = (
    "yuan", "yen", "euro", "dollar index", "devaluation", "peg",
    "reserves", "current account", "emerging market", "em fx",
    "capital flow", "dxy", "currency crisis", "intervention",
    "cross-border",
)

_FISCAL_KW: tuple[str, ...] = (
    "deficit", "debt ceiling", "bond auction", "fiscal", "treasury supply",
    "term premium", "downgrade", "refunding", "tba", "issuance",
    "budget", "entitlement", "debt sustainability", "primary deficit",
)


_KW_MAP: dict[str, tuple[str, ...]] = {
    "inflation":            _INFLATION_KW,
    "growth":               _GROWTH_KW,
    "financial_stability":  _FINSTAB_KW,
    "external_balance":     _EXTBAL_KW,
    "fiscal":               _FISCAL_KW,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(*parts: str) -> str:
    return " ".join(p or "" for p in parts).lower().strip()


def _keyword_hits(text: str, kws: tuple[str, ...]) -> list[str]:
    if not text:
        return []
    return [kw for kw in kws if kw in text]


def _rates_usable(rates_context: Optional[dict]) -> bool:
    if not rates_context or not isinstance(rates_context, dict):
        return False
    nom = (rates_context.get("nominal") or {}).get("change_5d")
    real = (rates_context.get("real_proxy") or {}).get("change_5d")
    return nom is not None or real is not None


def _stress_usable(stress_regime: Optional[dict]) -> bool:
    if not stress_regime or not isinstance(stress_regime, dict):
        return False
    # compute_stress_regime always returns a regime label; usable iff at
    # least one of the raw numeric signals is actually populated.
    raw = stress_regime.get("raw") or {}
    return bool(raw)


def _snapshot(snapshots: Optional[list[dict]], market: str) -> Optional[dict]:
    if not snapshots:
        return None
    target = market.upper()
    for s in snapshots:
        if not isinstance(s, dict):
            continue
        if (s.get("market") or "").upper() == target:
            if s.get("value") is None or s.get("error"):
                return None
            return s
    return None


def _snap_change_5d(snapshots: Optional[list[dict]], market: str) -> Optional[float]:
    snap = _snapshot(snapshots, market)
    if not snap:
        return None
    val = snap.get("change_5d")
    try:
        return float(val) if val is not None else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _score_constraints(
    text: str,
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    """Return (scores, rationales) keyed by constraint id.

    Each constraint accumulates points from three sources:
      - keyword hits in headline + mechanism (1.0 per hit, capped at 3)
      - rates_context regime / numeric moves (up to 3)
      - stress_regime + snapshot overlays (up to 3)

    Max theoretical per constraint ≈ 9.  In practice 4-6 is a strong
    binding result, 2-3 is a secondary constraint.
    """
    scores: dict[str, float] = {cid: 0.0 for cid in CONSTRAINT_IDS}
    rationales: dict[str, list[str]] = {cid: [] for cid in CONSTRAINT_IDS}

    # ---- Keyword pass --------------------------------------------------
    for cid, kws in _KW_MAP.items():
        hits = _keyword_hits(text, kws)
        if hits:
            scores[cid] += min(len(hits), 3)
            rationales[cid].append(
                f"thesis keywords: {', '.join(hits[:4])}"
            )

    # ---- Rates context -------------------------------------------------
    regime = (rates_context or {}).get("regime") if rates_context else None
    nom_5d = ((rates_context or {}).get("nominal") or {}).get("change_5d")
    real_5d = ((rates_context or {}).get("real_proxy") or {}).get("change_5d")
    be_5d = ((rates_context or {}).get("breakeven_proxy") or {}).get("change_5d")

    if regime == "Inflation pressure":
        scores["inflation"] += 3
        rationales["inflation"].append("rates regime: breakevens widening")
    elif regime == "Real-rate tightening":
        scores["inflation"] += 1
        scores["growth"] += 1
        rationales["inflation"].append("rates regime: real-rate tightening")
        rationales["growth"].append("real-rate tightening squeezes growth")
    elif regime == "Risk-off / growth scare":
        scores["growth"] += 3
        rationales["growth"].append("rates regime: risk-off / growth scare")

    # Nominal yield jumping with no breakeven widening → fiscal term-premium signal.
    if nom_5d is not None and nom_5d > 0.4:
        if be_5d is None or be_5d < 0.2:
            scores["fiscal"] += 2
            rationales["fiscal"].append(
                f"10Y up {nom_5d:+.2f}% / 5d with flat breakevens → term-premium pressure"
            )

    # ---- Stress regime -------------------------------------------------
    signals = (stress_regime or {}).get("signals") or {}
    sregime = (stress_regime or {}).get("regime")
    raw_stress = (stress_regime or {}).get("raw") or {}

    if signals.get("vix_elevated"):
        scores["financial_stability"] += 1
        rationales["financial_stability"].append("VIX elevated vs 20d avg")
    if signals.get("credit_widening"):
        scores["financial_stability"] += 2
        rationales["financial_stability"].append("HY credit spreads widening")
    if signals.get("term_inversion"):
        scores["financial_stability"] += 1
        rationales["financial_stability"].append("vol curve inverted (near-term panic)")
    if signals.get("safe_haven_bid"):
        scores["growth"] += 1
        rationales["growth"].append("safe-haven flows into gold/USD/TLT")
    if sregime == "Systemic Stress":
        scores["financial_stability"] += 2
        rationales["financial_stability"].append("stress regime: systemic")

    # ---- Snapshot overlays --------------------------------------------
    # Equity index falling hard = growth pressure (even absent keyword hit)
    es_5d = _snap_change_5d(snapshots, "ES")
    if es_5d is not None and es_5d < -2.0:
        scores["growth"] += 2
        rationales["growth"].append(f"S&P 500 down {es_5d:+.1f}% / 5d")
    elif es_5d is not None and es_5d < -1.0:
        scores["growth"] += 1
        rationales["growth"].append(f"S&P 500 down {es_5d:+.1f}% / 5d")

    # DXY jump = external balance pressure for rest of world
    dxy_5d = _snap_change_5d(snapshots, "DXY")
    if dxy_5d is not None and abs(dxy_5d) > 1.5:
        scores["external_balance"] += 2
        rationales["external_balance"].append(
            f"DXY move {dxy_5d:+.1f}% / 5d — FX channel active"
        )
    elif dxy_5d is not None and abs(dxy_5d) > 0.8:
        scores["external_balance"] += 1
        rationales["external_balance"].append(
            f"DXY move {dxy_5d:+.1f}% / 5d"
        )

    # Gold rallying hard reinforces inflation / safe-haven channels.
    gc_5d = _snap_change_5d(snapshots, "GC")
    if gc_5d is not None and gc_5d > 2.0:
        scores["inflation"] += 1
        rationales["inflation"].append(f"gold up {gc_5d:+.1f}% / 5d")

    # Crude jump → inflation channel
    cl_5d = _snap_change_5d(snapshots, "CL")
    if cl_5d is not None and cl_5d > 3.0:
        scores["inflation"] += 1
        rationales["inflation"].append(f"crude up {cl_5d:+.1f}% / 5d")

    return scores, rationales


# ---------------------------------------------------------------------------
# Policy room + reaction function prose
# ---------------------------------------------------------------------------

_REACTION: dict[str, str] = {
    "inflation": (
        "Authority leans hawkish: keep real rates restrictive, resist "
        "cuts until inflation prints confirm disinflation."
    ),
    "growth": (
        "Authority leans dovish: prioritise easing channels and forward "
        "guidance over balance-sheet action."
    ),
    "financial_stability": (
        "Authority deploys targeted liquidity (discount window, repo, "
        "swap lines) while keeping headline policy rate untouched."
    ),
    "external_balance": (
        "Authority relies on FX intervention and capital-flow management "
        "before touching the policy rate."
    ),
    "fiscal": (
        "Authority signals coordination with Treasury; policy rate path "
        "becomes secondary to bond supply / term premium dynamics."
    ),
}


def _policy_room(binding: str, scores: dict[str, float],
                 rates_usable: bool, stress_usable: bool) -> str:
    """Classify how much room the authority has to act.

    - ample       — single clear constraint, macro data clean
    - limited     — single constraint but score modest (3-4)
    - constrained — binding constraint conflicts with another strong one
    - mixed       — no single constraint dominates
    - unknown     — no usable macro signals
    """
    if not rates_usable and not stress_usable:
        return "unknown"

    top = scores.get(binding, 0.0)
    if top <= 0:
        return "unknown"

    # How many constraints cleared the "secondary" bar?
    others = sorted(
        [(cid, s) for cid, s in scores.items() if cid != binding and s >= 2.0],
        key=lambda x: -x[1],
    )

    if not others:
        return "ample" if top >= 5 else "limited"

    # Conflict detection: inflation vs growth, or fin-stab vs inflation.
    top_other = others[0]
    conflict_pairs = {
        ("inflation", "growth"),
        ("growth", "inflation"),
        ("inflation", "financial_stability"),
        ("financial_stability", "inflation"),
    }
    if (binding, top_other[0]) in conflict_pairs and top_other[1] >= 3.0:
        return "constrained"

    if top_other[1] >= top - 1.0:
        return "mixed"
    return "limited"


# ---------------------------------------------------------------------------
# Why / explanation builder
# ---------------------------------------------------------------------------

def _why_sentence(binding: str, policy_room: str,
                  scores: dict[str, float],
                  rationales: dict[str, list[str]]) -> str:
    label = _CONSTRAINT_LABELS[binding].lower()
    bits = rationales.get(binding) or []
    lead = bits[0] if bits else "thesis signals dominant"

    if policy_room == "ample":
        tail = "reaction function has clear room to act on this lever alone."
    elif policy_room == "limited":
        tail = "reaction function has narrow room — signal is real but modest."
    elif policy_room == "constrained":
        # Identify the conflicting constraint for the sentence.
        others = sorted(
            [(cid, s) for cid, s in scores.items() if cid != binding and s >= 3.0],
            key=lambda x: -x[1],
        )
        if others:
            conflict_label = _CONSTRAINT_LABELS[others[0][0]].lower()
            tail = (
                f"reaction function is constrained: fighting {conflict_label} "
                f"at the same time."
            )
        else:
            tail = "reaction function is constrained by a competing mandate."
    elif policy_room == "mixed":
        tail = "no single mandate dominates — expect zig-zag reaction function."
    else:
        tail = "macro context partial — reaction function inference is tentative."

    return f"Binding constraint is {label} ({lead}); {tail}"


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def compute_policy_constraint(
    headline: str,
    mechanism_text: str,
    rates_context: Optional[dict],
    stress_regime: Optional[dict],
    snapshots: Optional[list[dict]] = None,
) -> dict:
    """Identify the binding policy constraint and supporting context.

    All inputs are optional — the composer degrades gracefully:
      - No rates + no stress + no keyword hits → ``{}`` (skip rendering).
      - Only keyword hits → returns the block with ``stale=True``.
      - Usable macro data → full scoring + policy_room classification.
    """
    text = _text(headline, mechanism_text)
    rates_ok = _rates_usable(rates_context)
    stress_ok = _stress_usable(stress_regime)

    scores, rationales = _score_constraints(
        text, rates_context, stress_regime, snapshots,
    )

    # No thesis keywords AND no usable macro → nothing to say.
    top_score = max(scores.values()) if scores else 0.0
    if top_score <= 0 and not rates_ok and not stress_ok:
        return {}

    # If all scores are zero but macro is usable, surface a "none" binding
    # so the card can show "no clear binding constraint" rather than hide.
    if top_score <= 0:
        return {
            "binding": "none",
            "binding_label": "No binding constraint",
            "secondary": [],
            "policy_room": "ample" if (rates_ok or stress_ok) else "unknown",
            "why": (
                "No thesis keywords matched and macro overlays are quiet — "
                "no binding policy constraint detected."
            ),
            "reaction_function": "Authority has full optionality; no forced move.",
            "key_markets": [],
            "signals": {cid: round(s, 2) for cid, s in scores.items()},
            "available": rates_ok or stress_ok,
            "stale": not (rates_ok and stress_ok),
        }

    # Pick binding: highest score, inflation wins ties (canonical order).
    ranked = sorted(
        scores.items(),
        key=lambda kv: (-kv[1], CONSTRAINT_IDS.index(kv[0])),
    )
    binding = ranked[0][0]

    # Secondary constraints: ≥ 2 points AND not the binding.  Capped at 2.
    secondary_list: list[dict] = []
    for cid, score in ranked[1:]:
        if score < 2.0:
            continue
        secondary_list.append({
            "id": cid,
            "label": _CONSTRAINT_LABELS[cid],
            "score": round(score, 2),
            "rationale": "; ".join(rationales[cid][:2]) if rationales[cid] else "",
        })
        if len(secondary_list) >= 2:
            break

    policy_room = _policy_room(binding, scores, rates_ok, stress_ok)
    why = _why_sentence(binding, policy_room, scores, rationales)
    reaction = _REACTION.get(binding, "")

    return {
        "binding":            binding,
        "binding_label":      _CONSTRAINT_LABELS[binding],
        "secondary":          secondary_list,
        "policy_room":        policy_room,
        "why":                why,
        "reaction_function":  reaction,
        "key_markets":        list(_CONSTRAINT_MARKETS.get(binding, [])),
        "signals":            {cid: round(s, 2) for cid, s in scores.items()},
        "available":          rates_ok or stress_ok,
        "stale":              not (rates_ok and stress_ok),
    }
