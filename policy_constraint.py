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

# ---------------------------------------------------------------------------
# Macro-surprise linkage — translate classify_macro_surprise output into
# constraint-score contributions.  Fires only when a recent CPI / PPI / PCE /
# NFP / Unemployment print is in its surprise window (in_window = days_until
# between -3 and 0 inclusive, signal is beat / miss).  Keeps the weights
# modest so a surprise reinforces the other signals rather than dominating.
# ---------------------------------------------------------------------------

# Per (indicator, signal) → list of (constraint_id, points, rationale_fmt).
# Designed with the macro desk view: CPI beat = hot = inflation pressure up;
# NFP miss = labor weakening = growth concern up.  Unemployment uses the
# opposite polarity since higher-than-expected is worse for labor.
_SURPRISE_SCORES: dict[tuple[str, str], list[tuple[str, int, str]]] = {
    ("CPI",  "beat"):  [("inflation", 2, "CPI beat — hotter than expected")],
    ("CPI",  "miss"):  [("growth",    1, "CPI miss — cooling, growth softening")],
    ("PPI",  "beat"):  [("inflation", 1, "PPI beat — producer-cost pressure")],
    ("PPI",  "miss"):  [("growth",    1, "PPI miss — weakening pipeline prices")],
    ("PCE",  "beat"):  [("inflation", 2, "PCE beat — Fed's preferred gauge hot")],
    ("PCE",  "miss"):  [("growth",    1, "PCE miss — disinflation, growth softening")],
    ("NFP",  "beat"):  [("inflation", 1, "NFP beat — tight labor, wage pressure")],
    ("NFP",  "miss"):  [("growth",    2, "NFP miss — labor weakening")],
    ("Unemployment", "beat"): [("growth",    2, "Unemployment higher than expected")],
    ("Unemployment", "miss"): [("inflation", 1, "Unemployment lower — tight labor")],
}


# Revision signal scoring — fires independently of the actual-vs-consensus
# surprise.  A CPI print can come in "in line" yet carry a meaningfully
# revised prior that changes the macro picture; ignoring that discards
# genuine information.  Weight is lighter than a fresh surprise (1 point
# vs 2) because a revision is supporting evidence, not the headline.
_REVISION_SCORES: dict[tuple[str, str], list[tuple[str, int, str]]] = {
    ("CPI",          "up"):   [("inflation", 1, "CPI prior revised up — back-window inflation hotter than thought")],
    ("CPI",          "down"): [("growth",    1, "CPI prior revised down — back-window disinflation deeper")],
    ("PCE",          "up"):   [("inflation", 1, "PCE prior revised up — back-window inflation hotter than thought")],
    ("PCE",          "down"): [("growth",    1, "PCE prior revised down — back-window disinflation deeper")],
    ("PPI",          "up"):   [("inflation", 1, "PPI prior revised up — pipeline pressure broader")],
    ("PPI",          "down"): [("growth",    1, "PPI prior revised down — pipeline pressure weaker")],
    ("NFP",          "up"):   [("inflation", 1, "NFP prior revised up — labor tighter than initially reported")],
    ("NFP",          "down"): [("growth",    1, "NFP prior revised down — labor weaker than initially reported")],
    ("Unemployment", "up"):   [("growth",    1, "Unemployment revised up — labor weaker than initially reported")],
    ("Unemployment", "down"): [("inflation", 1, "Unemployment revised down — tighter labor than initially reported")],
}


# Relative band — matches the 5% in-line guard in ``macro_surprise``.
# A revision (or surprise) smaller than this share of |prior| / |consensus|
# is treated as noise; anything larger is a real signal.
_FACTS_RELATIVE_BAND: float = 0.05


def _num(value: object) -> Optional[float]:
    """Coerce to finite float, else None — booleans rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _surprise_from_facts(release: dict) -> Optional[str]:
    """Compute beat / miss / in_line from ``actual`` vs ``consensus``.

    Returns ``None`` when the release isn't marked as carrying facts,
    or when either value is missing / non-numeric.  Caller falls back
    to the upstream heuristic signal in that case.
    """
    if not release.get("has_release_facts"):
        return None
    actual = _num(release.get("actual"))
    consensus = _num(release.get("consensus"))
    if actual is None or consensus is None:
        return None
    diff = actual - consensus
    mag = abs(consensus)
    floor = _FACTS_RELATIVE_BAND * mag if mag > 0 else 0.0
    if abs(diff) <= floor:
        return "in_line"
    return "beat" if diff > 0 else "miss"


def _revision_direction(release: dict) -> Optional[str]:
    """Return ``"up"`` / ``"down"`` when ``revised_prior`` differs
    meaningfully from ``prior``; ``None`` otherwise.

    A statistically-meaningful revision is one larger than the same 5%
    relative band used for the in-line surprise check, so a 0.05pp
    prior revision on a 3.0% CPI print counts as noise while a 0.3pp
    revision does not.
    """
    if not release.get("has_release_facts"):
        return None
    prior = _num(release.get("prior"))
    revised = _num(release.get("revised_prior"))
    if prior is None or revised is None:
        return None
    diff = revised - prior
    mag = abs(prior)
    floor = _FACTS_RELATIVE_BAND * mag if mag > 0 else 0.0
    if abs(diff) <= floor:
        return None
    return "up" if diff > 0 else "down"


def _score_macro_surprises(
    macro_releases: Optional[list[dict]],
) -> tuple[dict[str, float], dict[str, list[str]], list[dict]]:
    """Translate classified macro releases into per-constraint score deltas.

    ``macro_releases`` is the output of ``macro_surprise.classify_macro_surprise``
    — each entry carries ``name``, ``surprise_signal`` ("beat"|"miss"|"in_line"|
    "unknown"|None), ``days_until``, plus (when a feed has populated the cache)
    ``has_release_facts`` + ``actual`` / ``prior`` / ``revised_prior`` /
    ``consensus``.  Only in-window entries (days_until between -3 and 0)
    contribute.

    Priority when a release carries facts:
      1. Compute the surprise directly from ``actual`` vs ``consensus``;
         this overrides any upstream heuristic signal so policy-constraint
         reasoning stays anchored to the official print.
      2. Score a material ``prior`` → ``revised_prior`` revision as an
         independent contribution — a "quiet" print with a meaningful
         prior revision carries real macro information that the headline
         path would otherwise discard.

    When no facts are present, the function falls back to the existing
    heuristic ``surprise_signal`` field as before.

    Returns (score_deltas, rationale_deltas, surprise_log) so the caller can
    merge them into the main score dict without changing existing callers.
    ``surprise_log`` is surfaced on the output for transparency.
    """
    score_deltas: dict[str, float] = {cid: 0.0 for cid in CONSTRAINT_IDS}
    rationale_deltas: dict[str, list[str]] = {cid: [] for cid in CONSTRAINT_IDS}
    surprise_log: list[dict] = []

    if not isinstance(macro_releases, list):
        return score_deltas, rationale_deltas, surprise_log

    for release in macro_releases:
        if not isinstance(release, dict):
            continue
        days_until = release.get("days_until")
        if not isinstance(days_until, int) or not (-3 <= days_until <= 0):
            continue
        indicator = release.get("name", "")

        # Facts-first surprise classification.  When release facts are
        # stored, ``actual`` vs ``consensus`` is the source of truth;
        # any heuristic signal attached upstream is replaced.  Without
        # facts we fall through to the upstream ``surprise_signal``.
        facts_signal = _surprise_from_facts(release)
        if facts_signal is not None:
            effective_signal = facts_signal
        else:
            raw = release.get("surprise_signal")
            effective_signal = raw if raw in ("beat", "miss") else None

        if effective_signal in ("beat", "miss"):
            for constraint, points, rationale in _SURPRISE_SCORES.get(
                (indicator, effective_signal), []
            ):
                score_deltas[constraint] += points
                rationale_deltas[constraint].append(rationale)
                surprise_log.append({
                    "indicator":  indicator,
                    "signal":     effective_signal,
                    "constraint": constraint,
                    "points":     points,
                    "days_until": days_until,
                })

        # Revision signal — independent from surprise.  Fires whenever
        # a material prior revision is stored, even if the headline
        # print landed in-line.
        revision = _revision_direction(release)
        if revision is not None:
            for constraint, points, rationale in _REVISION_SCORES.get(
                (indicator, revision), []
            ):
                score_deltas[constraint] += points
                rationale_deltas[constraint].append(rationale)
                surprise_log.append({
                    "indicator":  indicator,
                    "signal":     f"revision_{revision}",
                    "constraint": constraint,
                    "points":     points,
                    "days_until": days_until,
                })

    return score_deltas, rationale_deltas, surprise_log


# ---------------------------------------------------------------------------
# Front-end policy repricing detector
# ---------------------------------------------------------------------------

# Minimum absolute 2Y move (pp) that counts as front-end repricing.  15bps
# over 5d is the empirical clearing bar for a "market has already shifted"
# read — smaller moves are noise.
_FRONT_END_LEG_FLOOR_PP: float = 0.15

# Minimum 2s10s slope change (pp) that confirms the front-end moved
# independently of the long end — i.e. the curve actually twisted.
_FRONT_END_SLOPE_FLOOR_PP: float = 0.15


def _detect_front_end_repricing(
    rates_pack: Optional[dict],
) -> tuple[bool, str]:
    """Return (active, rationale) for front-end policy repricing.

    "Front-end policy repricing" is distinct from generic inflation pressure
    or growth weakness: it's specifically the 2Y moving materially as markets
    reprice the expected policy path (hikes / cuts priced in or out).  We
    detect it when BOTH:
      * |2Y 5d move| >= _FRONT_END_LEG_FLOOR_PP
      * |2s10s slope 5d| >= _FRONT_END_SLOPE_FLOOR_PP (curve twisted, not
        parallel)

    The rates_pack is the same dict shock_decomposition emits (``twoy_5d_pp``,
    ``slope_5d_pp``).  When absent or unavailable, returns (False, "").
    """
    if not isinstance(rates_pack, dict):
        return False, ""
    twoy = rates_pack.get("twoy_5d_pp")
    slope = rates_pack.get("slope_5d_pp")
    try:
        twoy_f = float(twoy) if twoy is not None else None
        slope_f = float(slope) if slope is not None else None
    except (TypeError, ValueError):
        return False, ""
    if twoy_f is None or slope_f is None:
        return False, ""
    if abs(twoy_f) < _FRONT_END_LEG_FLOOR_PP:
        return False, ""
    if abs(slope_f) < _FRONT_END_SLOPE_FLOOR_PP:
        return False, ""
    direction = "hikes priced" if twoy_f > 0 else "cuts priced"
    return True, (
        f"2Y {twoy_f:+.2f}pp / 5d with 2s10s {slope_f:+.2f}pp — {direction}"
    )


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


# Conflict pairs: pairings of constraints that pull the reaction function
# in opposite directions and cannot both be resolved with the same lever.
# "boxed_in" requires two conflicting constraints at high severity; the less
# severe "constrained" only requires the lower threshold.
_CONFLICT_PAIRS: frozenset[tuple[str, str]] = frozenset({
    ("inflation", "growth"),
    ("growth", "inflation"),
    ("inflation", "financial_stability"),
    ("financial_stability", "inflation"),
    ("inflation", "external_balance"),
    ("external_balance", "inflation"),
})

# Thresholds — empirically chosen so "free_to_respond" is rare (needs clean
# strong signal) and "boxed_in" is rare (needs two mandates fighting).
_FREE_TO_RESPOND_TOP: float = 5.0
_BOXED_IN_FLOOR:      float = 3.5

# When front-end policy repricing is already active, the authority has LESS
# room because markets have moved ahead of any surprise.  This table
# one-step-downgrades the raw policy_room label.
_FRONT_END_DOWNGRADE: dict[str, str] = {
    "free_to_respond": "ample",
    "ample":           "limited",
    "limited":         "constrained",
    # "constrained" / "boxed_in" / "mixed" / "unknown" stay put — already
    # tight enough that front-end repricing adds no new narrowing.
}


def _policy_room(binding: str, scores: dict[str, float],
                 rates_usable: bool, stress_usable: bool,
                 front_end_repricing: bool = False) -> str:
    """Classify how much room the authority has to act.

    - free_to_respond — top score clears ``_FREE_TO_RESPOND_TOP`` AND no
                         other constraint clears the secondary bar.  The
                         reaction function has a clean lever to pull.
    - ample           — clear binding, no meaningful conflict, but signal
                         isn't as strong as free_to_respond.
    - limited         — single constraint but score modest.
    - constrained     — binding constraint conflicts with one other strong
                         constraint.  Authority has to balance.
    - boxed_in        — two (or more) strong conflicting mandates at
                         severity ``_BOXED_IN_FLOOR`` each.  The reaction
                         function is effectively paralysed.
    - mixed           — no single constraint dominates.
    - unknown         — no usable macro signals.
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
        raw = "free_to_respond" if top >= _FREE_TO_RESPOND_TOP else (
              "ample" if top >= 4.0 else "limited")
        return _FRONT_END_DOWNGRADE.get(raw, raw) if front_end_repricing else raw

    top_other = others[0]
    conflict = (binding, top_other[0]) in _CONFLICT_PAIRS

    # Boxed-in: binding AND top conflicting mandate both clear the severity
    # floor — two real mandates at the same time with no clean lever.
    if conflict and top >= _BOXED_IN_FLOOR and top_other[1] >= _BOXED_IN_FLOOR:
        return "boxed_in"

    # Constrained: single conflict at a weaker level.
    if conflict and top_other[1] >= 3.0:
        raw = "constrained"
        return _FRONT_END_DOWNGRADE.get(raw, raw) if front_end_repricing else raw

    if top_other[1] >= top - 1.0:
        return "mixed"

    raw = "limited"
    return _FRONT_END_DOWNGRADE.get(raw, raw) if front_end_repricing else raw


# ---------------------------------------------------------------------------
# Why / explanation builder
# ---------------------------------------------------------------------------

def _why_sentence(binding: str, policy_room: str,
                  scores: dict[str, float],
                  rationales: dict[str, list[str]],
                  front_end_repricing: bool = False) -> str:
    label = _CONSTRAINT_LABELS[binding].lower()
    bits = rationales.get(binding) or []
    lead = bits[0] if bits else "thesis signals dominant"

    if policy_room == "free_to_respond":
        tail = (
            "authority has clean optionality — the data supports the lever "
            "and nothing conflicts with it."
        )
    elif policy_room == "ample":
        tail = "reaction function has clear room to act on this lever alone."
    elif policy_room == "limited":
        tail = "reaction function has narrow room — signal is real but modest."
    elif policy_room == "boxed_in":
        others = sorted(
            [(cid, s) for cid, s in scores.items() if cid != binding and s >= _BOXED_IN_FLOOR],
            key=lambda x: -x[1],
        )
        if others:
            conflict_label = _CONSTRAINT_LABELS[others[0][0]].lower()
            tail = (
                f"authority is boxed in: {label} and {conflict_label} are "
                f"both pressing at once — no clean lever available."
            )
        else:
            tail = "authority is boxed in by two mandates fighting at the same time."
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

    if front_end_repricing:
        tail += " Front-end repricing already in — less room for surprise."

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
    macro_releases: Optional[list[dict]] = None,
    rates_pack: Optional[dict] = None,
) -> dict:
    """Identify the binding policy constraint and supporting context.

    All inputs are optional — the composer degrades gracefully:
      - No rates + no stress + no keyword hits → ``{}`` (skip rendering).
      - Only keyword hits → returns the block with ``stale=True``.
      - Usable macro data → full scoring + policy_room classification.

    ``macro_releases`` is the output of ``macro_surprise.classify_macro_surprise``
    — when provided, recent CPI / PCE / NFP beats/misses add to the
    appropriate constraint score so surprise-driven inflation or growth
    pressure is visible in the binding read.

    ``rates_pack`` is the rates sub-block from ``shock_decomposition``
    (``twoy_5d_pp``, ``slope_5d_pp``).  When provided, a meaningful 2Y
    move in a twisted curve downgrades ``policy_room`` by one notch —
    markets have already repriced, leaving less room for surprise.
    """
    text = _text(headline, mechanism_text)
    rates_ok = _rates_usable(rates_context)
    stress_ok = _stress_usable(stress_regime)

    scores, rationales = _score_constraints(
        text, rates_context, stress_regime, snapshots,
    )

    # Fold in macro-surprise signals from the calendar.  Safe when
    # macro_releases is None / empty: deltas are all zero.
    surprise_deltas, surprise_rationale_deltas, surprise_log = \
        _score_macro_surprises(macro_releases)
    for cid in CONSTRAINT_IDS:
        scores[cid] += surprise_deltas[cid]
        if surprise_rationale_deltas[cid]:
            rationales[cid].extend(surprise_rationale_deltas[cid])

    # Front-end policy repricing check (pure function over rates_pack).
    front_end_active, front_end_rationale = _detect_front_end_repricing(rates_pack)

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
            "front_end_repricing_active":    front_end_active,
            "front_end_repricing_rationale": front_end_rationale,
            "macro_surprise_signals":        surprise_log,
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

    policy_room = _policy_room(
        binding, scores, rates_ok, stress_ok,
        front_end_repricing=front_end_active,
    )
    why = _why_sentence(
        binding, policy_room, scores, rationales,
        front_end_repricing=front_end_active,
    )
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
        "front_end_repricing_active":    front_end_active,
        "front_end_repricing_rationale": front_end_rationale,
        "macro_surprise_signals":        surprise_log,
        "available":          rates_ok or stress_ok,
        "stale":              not (rates_ok and stress_ok),
    }
