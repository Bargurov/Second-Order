"""
relative_move.py

Relative-move classifier for market validation.

The current ``_direction_tag`` in ``market_check`` treats any 5d return in the
thesis direction as "supports the thesis".  That over-counts validation when
the whole tape drifted the same way — a beneficiary closing +2% alongside
SPY +2% is zero alpha, not a confirmation.

This module adds a benchmark-aware read on top of the absolute-return
``direction_tag`` without changing it (back-compat for movers / track-record
pipelines).  Consumers that want the richer verdict read ``validation_quality``
and ``thesis_support`` instead.

Output fields attached to each ticker block:
  * relative_return_1d / _5d / _20d : ticker_return − benchmark_return (pp)
  * benchmark_symbol                : which ETF was used ("XLE", "SPY", …)
  * benchmark_return_5d             : the benchmark's own 5d return
  * validation_quality              : one of the labels below
  * validation_quality_label        : human-readable version
  * thesis_support                  : "supported" | "ambiguous_beta"
                                      | "contradicted" | "flat" | "unavailable"
  * rationale                       : one-line explanation

Validation-quality taxonomy (per-ticker, 5d-centric):

  alpha_support       : relative move in thesis direction by ≥ ALPHA_FLOOR pp —
                        real outperformance; this is the only label that
                        counts as a clean validation.
  alpha_contradicts   : relative move AGAINST thesis by ≥ ALPHA_FLOOR pp —
                        ticker underperformed benchmark in the opposite
                        direction.  Strong negative evidence.
  beta_aligned        : absolute move in thesis direction but relative is
                        small (|rel| < ALPHA_FLOOR).  The ticker rode the
                        tape; no idiosyncratic read.  NOT thesis support.
  beta_contradicts    : absolute move AGAINST thesis while rel is small —
                        ticker moved with the market, market moved the
                        wrong way.
  drift               : benchmark moved materially (|bench| ≥ DRIFT_FLOOR)
                        but the ticker-minus-benchmark spread is tiny; the
                        whole read is market-wide noise.
  flat                : neither ticker nor benchmark moved materially.
  unavailable         : missing inputs.

thesis_support rolls the six labels up to four buckets the existing UI and
aggregators can branch on without knowing the full taxonomy.
"""

from __future__ import annotations

from typing import Optional


# ---------------------------------------------------------------------------
# Thresholds (percent, absolute)
# ---------------------------------------------------------------------------

# Relative-return magnitude required to call a move "alpha".  5d spreads of
# 0.5 pp clear typical 1-σ noise for sector-ETF-tracked names without letting
# every wiggle count.
_ALPHA_FLOOR_PCT: float = 0.5

# Absolute-return floor — below this, the ticker is flat by construction.
_ABS_FLAT_FLOOR_PCT: float = 0.5

# Benchmark-move magnitude that flags "market-wide drift" when paired with a
# small ticker-vs-benchmark spread.  When the whole tape moves ≥1% in 5d and
# the name moves with it, the signal is the tape, not the name.
_DRIFT_BENCH_FLOOR_PCT: float = 1.0


# ---------------------------------------------------------------------------
# Labels + rollups
# ---------------------------------------------------------------------------

_VALIDATION_QUALITY_LABELS: dict[str, str] = {
    "alpha_support":     "Alpha support — outperformed benchmark in thesis direction",
    "alpha_contradicts": "Alpha contradicts — underperformed benchmark against thesis",
    "beta_aligned":      "Beta-aligned — moved with benchmark, no idiosyncratic alpha",
    "beta_contradicts":  "Beta-contradicts — moved with market but wrong direction",
    "drift":             "Drift — mostly market-wide move, no signal",
    "flat":              "Flat — neither ticker nor benchmark moved materially",
    "unavailable":       "Validation inputs unavailable",
}

# Support rollup — only alpha_support counts as clean thesis confirmation.
_SUPPORT_ROLLUP: dict[str, str] = {
    "alpha_support":     "supported",
    "alpha_contradicts": "contradicted",
    "beta_aligned":      "ambiguous_beta",
    "beta_contradicts":  "contradicted",
    "drift":             "ambiguous_beta",
    "flat":              "flat",
    "unavailable":       "unavailable",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        out = float(v)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _spread(ticker_r: Optional[float], bench_r: Optional[float]) -> Optional[float]:
    """ticker − benchmark, or None when either side is missing."""
    t = _f(ticker_r)
    b = _f(bench_r)
    if t is None or b is None:
        return None
    return round(t - b, 3)


# ---------------------------------------------------------------------------
# Classifier
# ---------------------------------------------------------------------------

def _classify_quality(
    r5: Optional[float],
    rel5: Optional[float],
    bench5: Optional[float],
    role: str,
) -> str:
    """Core validation-quality decision, driven by the 5d window.

    The 5d horizon is the same one that powers the existing direction_tag
    and match rate — keeping the primary judgment there avoids surfacing
    two conflicting per-ticker reads.
    """
    if r5 is None or rel5 is None or bench5 is None:
        return "unavailable"

    # Role determines which direction "supports" the thesis.
    want_up = role != "loser"

    # Flat: neither ticker nor benchmark moved materially.
    if abs(r5) < _ABS_FLAT_FLOOR_PCT and abs(bench5) < _ABS_FLAT_FLOOR_PCT:
        return "flat"

    # Alpha path — the spread itself clears the alpha floor in either direction.
    if want_up and rel5 >= _ALPHA_FLOOR_PCT:
        return "alpha_support"
    if (not want_up) and rel5 <= -_ALPHA_FLOOR_PCT:
        return "alpha_support"
    if want_up and rel5 <= -_ALPHA_FLOOR_PCT:
        return "alpha_contradicts"
    if (not want_up) and rel5 >= _ALPHA_FLOOR_PCT:
        return "alpha_contradicts"

    # Spread is below the alpha floor — the ticker is tracking the benchmark.
    # Distinguish drift (big benchmark, small spread) from beta-aligned
    # (ticker moved in thesis direction with the tape) from beta-contradicts
    # (ticker moved against thesis, even if only with the tape).
    if abs(r5) < _ABS_FLAT_FLOOR_PCT:
        # Ticker didn't really move; if the benchmark did, this is drift noise
        # the ticker failed to participate in.
        if abs(bench5) >= _DRIFT_BENCH_FLOOR_PCT:
            return "drift"
        return "flat"

    # Ticker moved.  Was the move in thesis direction?
    ticker_up = r5 > 0
    in_direction = ticker_up if want_up else (not ticker_up)

    # If the benchmark also moved materially AND the spread is effectively
    # zero, the ticker's move is almost entirely benchmark-driven → drift.
    # Threshold tightened to ~30% of the alpha floor so a +0.2pp spread on
    # a +1.0% tape still reads as beta_aligned (mild outperformance), not
    # drift — drift is reserved for "rel ≈ 0 with a big benchmark move".
    if abs(bench5) >= _DRIFT_BENCH_FLOOR_PCT and abs(rel5) < _ALPHA_FLOOR_PCT * 0.3:
        return "drift"

    return "beta_aligned" if in_direction else "beta_contradicts"


# ---------------------------------------------------------------------------
# Rationale builder
# ---------------------------------------------------------------------------

def _rationale(
    quality: str,
    r5: Optional[float],
    rel5: Optional[float],
    bench5: Optional[float],
    benchmark_symbol: str,
) -> str:
    if quality == "unavailable":
        return "Relative-move validation inputs unavailable."

    def _fmt(v: Optional[float]) -> str:
        return f"{v:+.2f}%" if isinstance(v, (int, float)) else "n/a"

    bits = (
        f"5d {_fmt(r5)} vs {benchmark_symbol} {_fmt(bench5)} "
        f"(Δ {_fmt(rel5)})"
    )

    if quality == "alpha_support":
        return f"Outperformed {benchmark_symbol} in thesis direction — {bits}."
    if quality == "alpha_contradicts":
        return f"Underperformed {benchmark_symbol} against the thesis — {bits}."
    if quality == "beta_aligned":
        return f"Moved with {benchmark_symbol}; no idiosyncratic alpha — {bits}."
    if quality == "beta_contradicts":
        return f"Moved with market but wrong direction for the thesis — {bits}."
    if quality == "drift":
        return f"Market-wide drift: {benchmark_symbol} led the move — {bits}."
    return f"Neither ticker nor {benchmark_symbol} moved materially — {bits}."


# ---------------------------------------------------------------------------
# Public composer
# ---------------------------------------------------------------------------

def classify_relative_move(
    ticker_returns: Optional[dict],
    benchmark_returns: Optional[dict],
    role: str,
    benchmark_symbol: str = "SPY",
) -> dict:
    """Classify a ticker's 1d/5d/20d move against an appropriate benchmark.

    ``ticker_returns`` / ``benchmark_returns`` are dicts shaped like
    ``{"return_1d": float|None, "return_5d": float|None, "return_20d": float|None}``.
    ``role`` is "beneficiary" or "loser" (anything else is treated as
    beneficiary for direction purposes).  ``benchmark_symbol`` is carried
    through to the response so consumers can label the comparison.

    Returns a dict with a stable shape — see module docstring for fields.
    """
    tr = ticker_returns or {}
    br = benchmark_returns or {}

    rel1 = _spread(tr.get("return_1d"), br.get("return_1d"))
    rel5 = _spread(tr.get("return_5d"), br.get("return_5d"))
    rel20 = _spread(tr.get("return_20d"), br.get("return_20d"))

    r5 = _f(tr.get("return_5d"))
    bench5 = _f(br.get("return_5d"))

    quality = _classify_quality(r5, rel5, bench5, role)
    rationale = _rationale(quality, r5, rel5, bench5, benchmark_symbol)
    support = _SUPPORT_ROLLUP[quality]

    return {
        "relative_return_1d":       rel1,
        "relative_return_5d":       rel5,
        "relative_return_20d":      rel20,
        "benchmark_symbol":         benchmark_symbol,
        "benchmark_return_5d":      round(bench5, 3) if bench5 is not None else None,
        "validation_quality":       quality,
        "validation_quality_label": _VALIDATION_QUALITY_LABELS[quality],
        "thesis_support":           support,
        "rationale":                rationale,
        "available":                quality != "unavailable",
    }
