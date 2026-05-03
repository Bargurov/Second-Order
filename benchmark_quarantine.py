"""
benchmark_quarantine.py

Suspicious-print quarantine for benchmark markets.

Why this module
---------------
The engine's macro reads (shock_decomposition, cross_asset_coherence,
real_yield_context, reaction_function_divergence) all lean on a small
set of benchmark prints — 10Y yield, DXY, VIX, TIP, SPY, HYG, oil/gold.
A single corrupt print contaminates every downstream read that touches
that channel.  The shipped pipeline had three distinct "quiet degrade"
paths that would drop a clearly-bad print to None with no downstream
signal:

  * ``market_check._sanitize_returns`` clamps r5 to ±200% and returns
    None for anything past the ceiling — silent.
  * ``market_check._check_one_ticker`` price-floor bounds reject a
    starting close outside plausible ranges (e.g. ^TNX <0 or >30) and
    return ``_no_data`` — the caller sees an empty dict, not a reason.
  * ``market_check._verify_ticker_return`` may report "disputed" when a
    secondary provider disagrees by >3pp — the composers never look at
    that field.

This module lifts those quiet paths into an auditable three-state
quarantine signal that composers can both *display* and *enforce*:

  * ``ok``           — healthy print, no reason flags
  * ``warn``         — suspicious (elevated sigma / unverified) but the
                       observed move is kept so the UI can render it
                       behind a caution flag
  * ``quarantined``  — definitively bad; the observed move MUST be
                       treated as missing by downstream math.  The
                       reasons list names exactly which guards tripped.

Design
------
Pure composer.  No I/O.  Never raises.  Consumes whatever a caller can
cheaply produce — the 5d move, optional 1d move, a volume ratio, the
last close, and an optional verification verdict that market_check may
have attached.  Does NOT trigger new provider calls (see
``_benchmark_thresholds`` below for the "no new calls, strictly evaluate
what's already there" contract).

Inclusion rule for BENCHMARK_REGISTRY
-------------------------------------
A ticker is in the registry iff one or more of the core macro composers
(shock_decomposition / cross_asset_coherence / real_yield_context) reads
its print as an input.  Expanding the registry would pull the quarantine
into general-purpose ticker validation, which has its own layer
(market_check).  Keep this set tight — the whole point of per-benchmark
thresholds is that benchmarks behave differently from generic tickers.
"""

from __future__ import annotations

from typing import Any, Optional


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

DATA_QUALITY_IDS: tuple[str, ...] = ("ok", "warn", "quarantined")

QUARANTINE_REASON_IDS: tuple[str, ...] = (
    # Hard-fail reasons → ``quarantined``
    "hard_bound_violation",      # move magnitude exceeds the hard cap — clearly corrupt
    "price_floor_violation",     # last_price outside physically plausible bounds
    "dual_source_mismatch",      # secondary provider disagreed by >3pp (market_check verdict)
    "no_quote",                  # provider returned None — no print to score
    # Soft-warn reasons → ``warn``
    "stat_outlier",              # move >N×σ where σ is the static prior
    "volume_anomaly",            # volume_ratio <0.1 or >10x its rolling median
    "stale_quote",               # quote_age_minutes exceeds the benchmark's staleness threshold
    "unverified",                # verification was attempted but no secondary opinion returned
)

_HARD_FAIL_REASONS: frozenset[str] = frozenset({
    "hard_bound_violation",
    "price_floor_violation",
    "dual_source_mismatch",
    "no_quote",
})

_SOFT_WARN_REASONS: frozenset[str] = frozenset({
    "stat_outlier",
    "volume_anomaly",
    "stale_quote",
    "unverified",
})


# ---------------------------------------------------------------------------
# Registry — the tight set of benchmarks that feed the macro composers
# ---------------------------------------------------------------------------
# Thresholds are static priors; refresh quarterly if rolling vol diverges
# materially from the hard-coded σ.  Unit-aware: yield benchmarks use
# absolute percentage-point moves, price benchmarks use percent.
#
# Field semantics:
#   unit            — "pp" (percentage-point, yields) or "pct" (prices)
#   sigma_5d        — 1-sigma 5d move in channel-native units
#   outlier_sigma   — sigma multiple above which the print is a warn
#   hard_cap        — move magnitude above which the print is outright
#                     rejected (quarantined); must be a scale where a
#                     real macro move cannot plausibly reach it
#   price_floor     — lower bound on last_price (None = no lower bound)
#   price_ceiling   — upper bound on last_price (None = no upper bound)
#   stale_minutes   — quote age above which we flag "stale_quote"
#
# Sources:
#   yields — historical daily std-dev of 5d pp change; hard cap is a
#            non-crisis ceiling with margin.
#   prices — institutional 1-σ 5d move scales already used by
#            cross_asset_coherence and shock_decomposition.

_YIELD = "pp"
_PCT   = "pct"


BENCHMARK_REGISTRY: dict[str, dict[str, Any]] = {
    # --- Nominal rates ---
    "10Y":  {"unit": _YIELD, "sigma_5d": 0.20, "outlier_sigma": 4.0,
             "hard_cap": 2.50, "price_floor": 0.0, "price_ceiling": 25.0,
             "stale_minutes": 1440},
    "^TNX": {"unit": _YIELD, "sigma_5d": 0.20, "outlier_sigma": 4.0,
             "hard_cap": 2.50, "price_floor": 0.0, "price_ceiling": 25.0,
             "stale_minutes": 1440},
    "2Y":   {"unit": _YIELD, "sigma_5d": 0.25, "outlier_sigma": 4.0,
             "hard_cap": 3.00, "price_floor": 0.0, "price_ceiling": 25.0,
             "stale_minutes": 1440},
    # --- Real yields (TIP ETF; price-unit, inverse to real rates) ---
    "TIP":  {"unit": _PCT,   "sigma_5d": 0.70, "outlier_sigma": 4.0,
             "hard_cap": 10.0, "price_floor": 50.0, "price_ceiling": 150.0,
             "stale_minutes": 1440},
    # --- FX ---
    "DXY":  {"unit": _PCT,   "sigma_5d": 0.70, "outlier_sigma": 4.0,
             "hard_cap": 8.0,  "price_floor": 50.0, "price_ceiling": 200.0,
             "stale_minutes": 1440},
    # --- Vol ---
    "VIX":  {"unit": _PCT,   "sigma_5d": 25.0, "outlier_sigma": 4.0,
             "hard_cap": 200.0, "price_floor": 5.0,  "price_ceiling": 200.0,
             "stale_minutes": 1440},
    "^VIX": {"unit": _PCT,   "sigma_5d": 25.0, "outlier_sigma": 4.0,
             "hard_cap": 200.0, "price_floor": 5.0,  "price_ceiling": 200.0,
             "stale_minutes": 1440},
    # --- Equities ---
    "SPY":  {"unit": _PCT,   "sigma_5d": 1.5,  "outlier_sigma": 4.0,
             "hard_cap": 25.0, "price_floor": 50.0, "price_ceiling": 2000.0,
             "stale_minutes": 1440},
    "ES":   {"unit": _PCT,   "sigma_5d": 1.5,  "outlier_sigma": 4.0,
             "hard_cap": 25.0, "price_floor": 500.0, "price_ceiling": 10000.0,
             "stale_minutes": 1440},
    # --- Credit ETFs ---
    "HYG":  {"unit": _PCT,   "sigma_5d": 1.0,  "outlier_sigma": 4.0,
             "hard_cap": 20.0, "price_floor": 40.0, "price_ceiling": 150.0,
             "stale_minutes": 1440},
    "LQD":  {"unit": _PCT,   "sigma_5d": 1.0,  "outlier_sigma": 4.0,
             "hard_cap": 20.0, "price_floor": 40.0, "price_ceiling": 200.0,
             "stale_minutes": 1440},
    # --- Commodities ---
    "USO":  {"unit": _PCT,   "sigma_5d": 3.0,  "outlier_sigma": 4.0,
             "hard_cap": 40.0, "price_floor": 5.0,   "price_ceiling": 500.0,
             "stale_minutes": 1440},
    "CL":   {"unit": _PCT,   "sigma_5d": 3.0,  "outlier_sigma": 4.0,
             "hard_cap": 40.0, "price_floor": 5.0,   "price_ceiling": 500.0,
             "stale_minutes": 1440},
    "GLD":  {"unit": _PCT,   "sigma_5d": 1.8,  "outlier_sigma": 4.0,
             "hard_cap": 25.0, "price_floor": 50.0,  "price_ceiling": 500.0,
             "stale_minutes": 1440},
    "GC":   {"unit": _PCT,   "sigma_5d": 1.8,  "outlier_sigma": 4.0,
             "hard_cap": 25.0, "price_floor": 500.0, "price_ceiling": 5000.0,
             "stale_minutes": 1440},
    # --- Non-US equity benchmarks (see asset_registry.py for channel mapping) ---
    # DAX / FTSE / Nikkei 225 / Hang Seng / Euro Stoxx 50.  5d sigma is
    # mid-single-digit percent, similar to SPY; hard_cap 30 % — crisis
    # single-week moves (e.g. COVID Feb-20) peaked near 20 %.
    "^GDAXI": {"unit": _PCT, "sigma_5d": 1.8, "outlier_sigma": 4.0,
               "hard_cap": 30.0, "price_floor": 3_000.0, "price_ceiling": 40_000.0,
               "stale_minutes": 1440},
    "^FTSE":  {"unit": _PCT, "sigma_5d": 1.5, "outlier_sigma": 4.0,
               "hard_cap": 25.0, "price_floor": 3_000.0, "price_ceiling": 15_000.0,
               "stale_minutes": 1440},
    "^N225":  {"unit": _PCT, "sigma_5d": 2.0, "outlier_sigma": 4.0,
               "hard_cap": 30.0, "price_floor": 7_000.0, "price_ceiling": 60_000.0,
               "stale_minutes": 1440},
    "^HSI":   {"unit": _PCT, "sigma_5d": 2.5, "outlier_sigma": 4.0,
               "hard_cap": 30.0, "price_floor": 10_000.0, "price_ceiling": 40_000.0,
               "stale_minutes": 1440},
    "^STOXX50E": {"unit": _PCT, "sigma_5d": 1.8, "outlier_sigma": 4.0,
                  "hard_cap": 30.0, "price_floor": 1_500.0, "price_ceiling": 8_000.0,
                  "stale_minutes": 1440},
    # EM equities proxy ETF — wider sigma than developed markets.
    "EEM":   {"unit": _PCT, "sigma_5d": 2.2, "outlier_sigma": 4.0,
              "hard_cap": 30.0, "price_floor": 15.0, "price_ceiling": 200.0,
              "stale_minutes": 1440},
    # --- Non-US FX pairs (yfinance symbol convention: "EURUSD=X") ---
    # Major crosses sit ~1 % weekly sigma; EM crosses sit 2.5–3 %.  Hard
    # caps scaled accordingly.
    "EURUSD=X": {"unit": _PCT, "sigma_5d": 1.0, "outlier_sigma": 4.0,
                 "hard_cap": 8.0, "price_floor": 0.5, "price_ceiling": 2.0,
                 "stale_minutes": 1440},
    "GBPUSD=X": {"unit": _PCT, "sigma_5d": 1.2, "outlier_sigma": 4.0,
                 "hard_cap": 10.0, "price_floor": 0.5, "price_ceiling": 2.5,
                 "stale_minutes": 1440},
    "USDJPY=X": {"unit": _PCT, "sigma_5d": 1.2, "outlier_sigma": 4.0,
                 "hard_cap": 10.0, "price_floor": 50.0, "price_ceiling": 250.0,
                 "stale_minutes": 1440},
    "USDCNY=X": {"unit": _PCT, "sigma_5d": 0.6, "outlier_sigma": 4.0,
                 "hard_cap": 8.0, "price_floor": 5.0, "price_ceiling": 12.0,
                 "stale_minutes": 1440},
    "USDBRL=X": {"unit": _PCT, "sigma_5d": 2.5, "outlier_sigma": 4.0,
                 "hard_cap": 15.0, "price_floor": 1.5, "price_ceiling": 10.0,
                 "stale_minutes": 1440},
    "USDMXN=X": {"unit": _PCT, "sigma_5d": 2.0, "outlier_sigma": 4.0,
                 "hard_cap": 15.0, "price_floor": 10.0, "price_ceiling": 35.0,
                 "stale_minutes": 1440},
    # --- Commodities — Brent (global oil benchmark) + Copper (Dr. Copper) ---
    "BZ=F":  {"unit": _PCT, "sigma_5d": 3.5, "outlier_sigma": 4.0,
              "hard_cap": 40.0, "price_floor": 10.0, "price_ceiling": 250.0,
              "stale_minutes": 1440},
    "HG=F":  {"unit": _PCT, "sigma_5d": 2.8, "outlier_sigma": 4.0,
              "hard_cap": 35.0, "price_floor": 1.0, "price_ceiling": 10.0,
              "stale_minutes": 1440},
    # --- Credit — EM sovereign (USD-denominated) ---
    "EMB":   {"unit": _PCT, "sigma_5d": 1.5, "outlier_sigma": 4.0,
              "hard_cap": 20.0, "price_floor": 60.0, "price_ceiling": 150.0,
              "stale_minutes": 1440},
    # --- Rates — non-US yield / duration proxies.  yfinance does not
    # consistently publish non-US yield indices as "^"-prefixed tickers,
    # so we use ETF-based bond proxies.  IEF / TLT are already US-rate
    # registered via BENCHMARK_REGISTRY["10Y"]; BWX is the G7 ex-US
    # aggregate duration proxy consumed by the non-US rate channel.
    "BWX":   {"unit": _PCT, "sigma_5d": 0.8, "outlier_sigma": 4.0,
              "hard_cap": 12.0, "price_floor": 15.0, "price_ceiling": 60.0,
              "stale_minutes": 1440},
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def is_benchmark(market: Optional[str]) -> bool:
    """True when ``market`` is in the benchmark registry (case-insensitive)."""
    if not isinstance(market, str):
        return False
    return market.strip().upper() in BENCHMARK_REGISTRY


def benchmark_thresholds(market: str) -> Optional[dict[str, Any]]:
    """Return a deep-copied threshold dict for ``market`` (None if unknown)."""
    key = market.strip().upper() if isinstance(market, str) else ""
    pack = BENCHMARK_REGISTRY.get(key)
    if pack is None:
        return None
    return dict(pack)


# ---------------------------------------------------------------------------
# Core quarantine composer
# ---------------------------------------------------------------------------

def _coerce_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # NaN / inf protection — quarantined at the numeric boundary.
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _verification_status(verification: Any) -> Optional[str]:
    """Extract the verification status from a market_check verdict dict."""
    if not isinstance(verification, dict):
        return None
    status = verification.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    return None


def compute_benchmark_quarantine(
    market: str,
    *,
    move_5d: Any = None,
    move_1d: Any = None,
    volume_ratio: Any = None,
    last_price: Any = None,
    verification: Any = None,
    quote_age_minutes: Any = None,
) -> dict[str, Any]:
    """Score a single benchmark print for quarantine.

    Returns a structured verdict::

        {
          "market":         "10Y",
          "is_benchmark":   True,
          "data_quality":   "ok" | "warn" | "quarantined",
          "reasons":        [str, ...],         # empty iff data_quality == "ok"
          "observed_safe":  float | None,       # raw move_5d iff not quarantined
          "thresholds":     {"unit", "sigma_5d", "hard_cap", ...},
        }

    The caller decides whether to display the verdict (``data_quality``
    of ``warn`` is informational) or enforce it (``quarantined`` means
    the downstream math should treat the observed move as missing).

    Never raises.  Unknown markets pass through with
    ``is_benchmark=False`` and no reasons so callers can route
    non-benchmark tickers to generic validation without a special case.
    """
    key = market.strip().upper() if isinstance(market, str) else ""
    thresholds = BENCHMARK_REGISTRY.get(key)

    move5 = _coerce_float(move_5d)

    if thresholds is None:
        return {
            "market":        key or str(market) if market is not None else "",
            "is_benchmark":  False,
            "data_quality":  "ok",
            "reasons":       [],
            "observed_safe": move5,
            "thresholds":    None,
        }

    reasons: list[str] = []

    # --- No-quote: nothing to score.  Quarantine so downstream zeros it. ---
    if move5 is None and _coerce_float(move_1d) is None and last_price is None:
        reasons.append("no_quote")

    # --- Hard bound violation on the 5d move ---
    if move5 is not None and abs(move5) > thresholds["hard_cap"]:
        reasons.append("hard_bound_violation")

    # --- Price floor / ceiling check on the last price ---
    last = _coerce_float(last_price)
    if last is not None:
        floor = thresholds.get("price_floor")
        ceiling = thresholds.get("price_ceiling")
        if (floor is not None and last < floor) or (
            ceiling is not None and last > ceiling
        ):
            reasons.append("price_floor_violation")

    # --- Dual-source verdict from market_check.verify_ticker_return ---
    status = _verification_status(verification)
    if status == "disputed":
        reasons.append("dual_source_mismatch")
    elif status in ("unavailable", "unverified", "timed_out"):
        # Warn-grade: we attempted verification but got no second opinion.
        reasons.append("unverified")

    # --- Statistical outlier on the 5d move (warn-grade) ---
    if (
        move5 is not None
        and "hard_bound_violation" not in reasons
        and thresholds.get("sigma_5d")
    ):
        sigma_cap = thresholds["sigma_5d"] * thresholds["outlier_sigma"]
        if abs(move5) > sigma_cap:
            reasons.append("stat_outlier")

    # --- Volume anomaly (warn-grade) ---
    vol = _coerce_float(volume_ratio)
    if vol is not None and (vol < 0.1 or vol > 10.0):
        reasons.append("volume_anomaly")

    # --- Stale quote (warn-grade) ---
    age = _coerce_float(quote_age_minutes)
    if age is not None and age > thresholds["stale_minutes"]:
        reasons.append("stale_quote")

    # --- Elevate to quarantined iff any hard-fail reason fired ---
    hard = any(r in _HARD_FAIL_REASONS for r in reasons)
    if hard:
        data_quality = "quarantined"
        observed_safe = None
    elif reasons:
        data_quality = "warn"
        observed_safe = move5
    else:
        data_quality = "ok"
        observed_safe = move5

    return {
        "market":        key,
        "is_benchmark":  True,
        "data_quality":  data_quality,
        "reasons":       reasons,
        "observed_safe": observed_safe,
        "thresholds":    {
            "unit":          thresholds["unit"],
            "sigma_5d":      thresholds["sigma_5d"],
            "hard_cap":      thresholds["hard_cap"],
            "outlier_sigma": thresholds["outlier_sigma"],
        },
    }


# ---------------------------------------------------------------------------
# Composer convenience wrapper
# ---------------------------------------------------------------------------

def channel_quality_block(verdicts: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarise a list of per-channel quarantine verdicts into a block.

    Intended for shock_decomposition / cross_asset_coherence output so
    the caller doesn't re-derive the roll-up logic.  Returns::

        {
          "status":        "ok" | "warn" | "quarantined",
          "channels":      { channel_id: {data_quality, reasons, market} },
          "quarantined":   [ channel_id, ... ],
          "warn":          [ channel_id, ... ],
        }

    ``status`` is quarantined iff ANY channel is quarantined; warn iff
    any channel is warn (and none quarantined); ok otherwise.
    """
    channels: dict[str, dict] = {}
    quarantined: list[str] = []
    warn: list[str] = []
    has_quarantined = False
    has_warn = False

    for v in verdicts or []:
        if not isinstance(v, dict):
            continue
        cid = v.get("channel")
        if not isinstance(cid, str) or not cid:
            continue
        channels[cid] = {
            "market":       v.get("market"),
            "data_quality": v.get("data_quality"),
            "reasons":      list(v.get("reasons") or []),
        }
        dq = v.get("data_quality")
        if dq == "quarantined":
            has_quarantined = True
            quarantined.append(cid)
        elif dq == "warn":
            has_warn = True
            warn.append(cid)

    if has_quarantined:
        status = "quarantined"
    elif has_warn:
        status = "warn"
    else:
        status = "ok"

    return {
        "status":      status,
        "channels":    channels,
        "quarantined": quarantined,
        "warn":        warn,
    }
