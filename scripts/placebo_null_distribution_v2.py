#!/usr/bin/env python3
"""Read-only date-shuffled placebo null distribution for the v2 cohort.

For each v2 row, holds (primary_ticker, benchmark_ticker) constant and
samples fake first_trading_dates from the same cached window, then runs
the production BHAR event study on each fake date and computes
Benjamini-Hochberg FDR across the resulting 5 p-values. Repeats for
N draws (default 1000) to estimate how often a random within-cache
5-row cohort would clear ``5/5 q<0.05`` like the v2 cohort did.

What this is NOT
----------------

This is NOT a clean null distribution in the classical sense. The
price_cache contains event-window shards (the operator warmed bars
around known event dates), so even "fake" within-cache dates may
inherit volatility regimes shaped by the original events. Strict
exclusion zones around each row's real event remove the most direct
contamination, but the residual bias toward event-window-adjacent
dates remains.

Read this script's output as: "given the operator's ticker choices
and the cache's event-window shape, how often does a random
within-cache date-shuffle produce 5/5 q<0.05?" — NOT as the
unconditional Type I error rate of the cohort's FDR procedure.

Eligibility constraints
-----------------------

Per row, a candidate fake first_trading_idx must satisfy:

1. Lie inside a contiguous aligned block (no internal calendar gap > 7
   days between adjacent aligned dates). This rules out fake events
   whose 60-bar pre-event window or h=1 post-bar would cross one of
   the cache's multi-year gaps.
2. Have at least ``ESTIMATION_BARS`` (60) aligned bars before it inside
   the same contiguous block, and at least 1 aligned bar after it.
3. Lie OUTSIDE the real-event exclusion zone:
   - ``F < R - ESTIMATION_BARS`` (so the entire 60-bar estimation
     window is strictly before the real event), OR
   - ``F > R + 20`` (so the fake event is at least 20 trading days
     after the real event, keeping the immediate post-event horizon
     clean).

Read-only / no I/O
------------------

* No DB writes, no provider, no LLM, no artifact mutation.
* Cache access is via ``price_cache.read_window_no_fetch`` only.
* Deterministic given a ``--seed``.

CLI
---

::

    python scripts/placebo_null_distribution_v2.py \\
        --artifact artifacts/freeze_candidate_evidence_v2.json \\
        --n-draws 1000 --seed 0 --json

Exit code: 0 on success (numerical output produced); 1 only if the
ledger cannot be loaded or any row has zero eligible fake dates.
The output is informational — a high or low placebo rate is not a
pass/fail verdict.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import date as _date
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from stats.event_study import compute_event_study
from stats.p_values import p_value_from_sar
from stats.fdr import bh_adjust


_DEFAULT_ARTIFACT: str = "artifacts/freeze_candidate_evidence_v2.json"
_DEFAULT_N_DRAWS:  int = 1000
_DEFAULT_SEED:     int = 0
_ESTIMATION_BARS:  int = 60
_GAP_THRESHOLD_DAYS: int = 7      # max calendar gap between adjacent aligned bars
_POST_EVENT_EXCLUSION_TD: int = 20  # exclude fakes within +20 td of real event
_HORIZON: int = 1
_ALPHA: float = 0.05


# ---------------------------------------------------------------------------
# Artifact + cache loading
# ---------------------------------------------------------------------------


def load_v2_cohort_rows(artifact_path: str) -> list[dict[str, Any]]:
    """Extract (primary_ticker, benchmark_ticker, first_trading_date)
    from the artifact's candidates list. The five-row v2.1 cohort.
    """
    with open(artifact_path, "r", encoding="utf-8") as fh:
        artifact = json.load(fh)
    return [
        {
            "primary_ticker":    c["primary_ticker"],
            "benchmark_ticker":  c["benchmark_ticker"],
            "real_event_date":   c["first_trading_date"],
        }
        for c in artifact.get("candidates", [])
    ]


def _default_cache_reader(
    ticker: str, start: str, end: str,
) -> Optional[tuple[list[str], list[float]]]:
    """Lazy-imports price_cache; returns the full cache for ``ticker``
    between ``start`` and ``end`` inclusive (or ``None`` on cache miss).
    """
    from price_cache import read_window_no_fetch  # noqa: PLC0415
    df = read_window_no_fetch(ticker, start=start, end=end, auto_adjust=False)
    if df is None or df.empty:
        return None
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)
    cols = {str(c).lower(): c for c in df.columns}
    close_col = cols.get("close")
    date_col = cols.get("date")
    if close_col is None:
        return None
    dates: list[str] = []
    closes: list[float] = []
    for idx, row in df.iterrows():
        d = row.get(date_col) if date_col is not None else idx
        try:
            c = float(row.get(close_col))
        except (TypeError, ValueError):
            continue
        d_str = str(d)[:10] if d is not None else None
        if not d_str:
            continue
        dates.append(d_str)
        closes.append(c)
    if not dates:
        return None
    return dates, closes


def _align_pair(
    asset_dates: Sequence[str], asset_closes: Sequence[float],
    bench_dates: Sequence[str], bench_closes: Sequence[float],
) -> tuple[list[str], np.ndarray, np.ndarray]:
    a_idx = {d: k for k, d in enumerate(asset_dates)}
    b_idx = {d: k for k, d in enumerate(bench_dates)}
    common = sorted(set(asset_dates) & set(bench_dates))
    a = np.array([asset_closes[a_idx[d]] for d in common], dtype=float)
    b = np.array([bench_closes[b_idx[d]] for d in common], dtype=float)
    return common, a, b


# ---------------------------------------------------------------------------
# Eligibility computation
# ---------------------------------------------------------------------------


def detect_contiguous_block_for_index(
    aligned_dates: list[str],
    target_idx: int,
    *,
    gap_threshold_days: int = _GAP_THRESHOLD_DAYS,
) -> tuple[int, int]:
    """Return ``(block_start_idx, block_end_idx)`` (inclusive) for the
    contiguous block containing ``target_idx`` — i.e., the maximal
    range of indices where consecutive aligned dates differ by at most
    ``gap_threshold_days`` calendar days.
    """
    n = len(aligned_dates)
    if not (0 <= target_idx < n):
        raise ValueError(f"target_idx {target_idx} out of range for length {n}")
    # Walk backward
    start = target_idx
    while start > 0:
        d_prev = _date.fromisoformat(aligned_dates[start - 1])
        d_cur = _date.fromisoformat(aligned_dates[start])
        if (d_cur - d_prev).days > gap_threshold_days:
            break
        start -= 1
    # Walk forward
    end = target_idx
    while end < n - 1:
        d_cur = _date.fromisoformat(aligned_dates[end])
        d_next = _date.fromisoformat(aligned_dates[end + 1])
        if (d_next - d_cur).days > gap_threshold_days:
            break
        end += 1
    return start, end


def compute_eligible_fake_indices(
    aligned_dates: list[str],
    real_event_date: str,
    *,
    estimation_bars: int = _ESTIMATION_BARS,
    post_event_exclusion_td: int = _POST_EVENT_EXCLUSION_TD,
    gap_threshold_days: int = _GAP_THRESHOLD_DAYS,
) -> list[int]:
    """Return the list of fake first_trading aligned-indices that
    satisfy the eligibility rules described in the module docstring.

    If the real event is not in the aligned dates, return an empty
    list (the placebo design requires the real event as the exclusion
    anchor).
    """
    if real_event_date not in aligned_dates:
        return []
    real_idx = aligned_dates.index(real_event_date)
    # Constrain to the contiguous block containing the real event.
    block_start, block_end = detect_contiguous_block_for_index(
        aligned_dates, real_idx, gap_threshold_days=gap_threshold_days,
    )
    # Within-block eligibility: >=60 pre bars, >=1 post bar
    min_f = block_start + estimation_bars
    max_f = block_end - 1
    candidates = range(min_f, max_f + 1)
    # Exclude the real-event neighborhood:
    #   estimation window of the fake must not overlap the real event
    #   AND the fake should be at least post_event_exclusion_td trading
    #   days after the real event if it is post-real.
    eligible = []
    for f in candidates:
        if f < real_idx - estimation_bars:
            eligible.append(f)        # entire estimation window is strictly before real event
        elif f > real_idx + post_event_exclusion_td:
            eligible.append(f)        # fake event is well after real event
        # else: skip — fake's estimation window or immediate horizon overlaps real event
    return eligible


# ---------------------------------------------------------------------------
# Per-row event-study compute (lifted from recompute_freeze_candidate_v2)
# ---------------------------------------------------------------------------


def _event_study_h1_p(
    asset_aligned: np.ndarray,
    bench_aligned: np.ndarray,
    first_trading_idx: int,
) -> Optional[float]:
    """Return the production-BHAR h=1 two-tailed p-value for a fake
    first_trading index in an aligned price pair. Returns ``None`` if
    the estimation window is insufficient or sigma_ar_daily is 0.
    """
    event_index = first_trading_idx - 1  # production convention
    if event_index < _ESTIMATION_BARS:
        return None
    if first_trading_idx >= len(asset_aligned):
        return None
    es = compute_event_study(
        asset_prices=asset_aligned,
        benchmark_prices=bench_aligned,
        event_index=event_index,
        horizons=(_HORIZON,),
        estimation_window=_ESTIMATION_BARS,
    )
    h1 = es["horizons"][_HORIZON]
    return p_value_from_sar(h1["sar"], "two-sided")


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def build_per_row_state(
    cohort_rows: list[dict[str, Any]],
    *,
    cache_reader: Optional[Callable] = None,
) -> list[dict[str, Any]]:
    """For each cohort row, load aligned cache bars and compute the
    eligible fake-index set. Returns one dict per row carrying the
    aligned arrays, eligibility list, and a few diagnostics.
    """
    reader = cache_reader if cache_reader is not None else _default_cache_reader
    out: list[dict[str, Any]] = []
    for row in cohort_rows:
        primary = row["primary_ticker"]
        bench = row["benchmark_ticker"]
        real_event = row["real_event_date"]
        # Pull the whole ticker cache (no calendar window — we want all
        # bars to find contiguous blocks).
        p = reader(primary, "1970-01-01", "2100-12-31")
        b = reader(bench, "1970-01-01", "2100-12-31")
        if p is None or b is None:
            out.append({
                "row": row, "error": (
                    f"cache miss: primary={primary if p is None else 'OK'} "
                    f"bench={bench if b is None else 'OK'}"
                ),
                "eligible_fake_indices": [],
            })
            continue
        p_d, p_c = p
        b_d, b_c = b
        aligned, asset_arr, bench_arr = _align_pair(p_d, p_c, b_d, b_c)
        if real_event not in aligned:
            out.append({
                "row": row, "error": (
                    f"real event {real_event} not in aligned dates"
                ),
                "eligible_fake_indices": [],
            })
            continue
        eligible = compute_eligible_fake_indices(aligned, real_event)
        out.append({
            "row": row,
            "aligned_dates": aligned,
            "asset_aligned": asset_arr,
            "bench_aligned": bench_arr,
            "real_event_idx": aligned.index(real_event),
            "aligned_total":  len(aligned),
            "eligible_fake_indices": eligible,
            "eligible_count": len(eligible),
        })
    return out


def run_placebo_draws(
    per_row_state: list[dict[str, Any]],
    *,
    n_draws: int = _DEFAULT_N_DRAWS,
    seed: int = _DEFAULT_SEED,
    alpha: float = _ALPHA,
) -> dict[str, Any]:
    """Run ``n_draws`` random cohort draws. Each draw picks one fake
    first_trading index per row from that row's eligibility list,
    runs the event study, computes BH FDR, and tallies how many of
    the 5 rows clear ``q < alpha``.
    """
    rng = random.Random(seed)
    # Validate state up-front: every row must have non-empty eligibility
    for st in per_row_state:
        if not st.get("eligible_fake_indices"):
            return {
                "ok": False,
                "error": (
                    f"row {st['row']['primary_ticker']} has zero eligible "
                    f"fake indices; cannot run placebo"
                ),
            }

    discoveries_per_draw: list[int] = []
    all_q_under_alpha: int = 0
    at_least_4: int = 0
    at_least_3: int = 0
    min_qs: list[float] = []

    for _draw_ix in range(n_draws):
        p_values: list[Optional[float]] = []
        for st in per_row_state:
            fake_idx = rng.choice(st["eligible_fake_indices"])
            p = _event_study_h1_p(
                st["asset_aligned"], st["bench_aligned"], fake_idx,
            )
            p_values.append(p)
        # BH FDR across the 5 p-values
        bh = bh_adjust(p_values, alpha=alpha)
        qs = bh["adjusted"]
        # Count discoveries (non-None q < alpha)
        n_disc = sum(
            1 for q in qs
            if q is not None and q < alpha
        )
        discoveries_per_draw.append(n_disc)
        if n_disc == len(per_row_state):
            all_q_under_alpha += 1
        if n_disc >= 4:
            at_least_4 += 1
        if n_disc >= 3:
            at_least_3 += 1
        # Track min q for distribution
        finite_qs = [q for q in qs if q is not None]
        if finite_qs:
            min_qs.append(min(finite_qs))

    median_disc = (
        float(sorted(discoveries_per_draw)[len(discoveries_per_draw) // 2])
        if discoveries_per_draw else 0.0
    )
    median_min_q = (
        float(sorted(min_qs)[len(min_qs) // 2])
        if min_qs else None
    )

    return {
        "ok": True,
        "n_draws":                       n_draws,
        "alpha":                         alpha,
        "row_count":                     len(per_row_state),
        "fraction_all_q_under_alpha":    all_q_under_alpha / n_draws,
        "fraction_at_least_4":           at_least_4 / n_draws,
        "fraction_at_least_3":           at_least_3 / n_draws,
        "median_discoveries_per_draw":   median_disc,
        "median_min_q_per_draw":         median_min_q,
        "count_all_q_under_alpha":       all_q_under_alpha,
        "count_at_least_4":              at_least_4,
        "count_at_least_3":              at_least_3,
    }


def run_all(
    artifact_path: str,
    *,
    n_draws: int = _DEFAULT_N_DRAWS,
    seed: int = _DEFAULT_SEED,
    cache_reader: Optional[Callable] = None,
) -> dict[str, Any]:
    cohort_rows = load_v2_cohort_rows(artifact_path)
    state = build_per_row_state(cohort_rows, cache_reader=cache_reader)
    per_row_diagnostics = [
        {
            "primary_ticker":     st["row"]["primary_ticker"],
            "benchmark_ticker":   st["row"]["benchmark_ticker"],
            "real_event_date":    st["row"]["real_event_date"],
            "aligned_total":      st.get("aligned_total"),
            "eligible_count":     st.get("eligible_count"),
            "error":              st.get("error"),
        }
        for st in state
    ]
    setup_errors = [d for d in per_row_diagnostics if d.get("error")]
    if setup_errors:
        return {
            "ok": False,
            "artifact_path": artifact_path,
            "n_draws": n_draws,
            "seed": seed,
            "per_row_diagnostics": per_row_diagnostics,
            "setup_errors": setup_errors,
        }
    placebo = run_placebo_draws(state, n_draws=n_draws, seed=seed)
    return {
        "ok":                       placebo.get("ok", False),
        "artifact_path":            artifact_path,
        "n_draws":                  n_draws,
        "seed":                     seed,
        "alpha":                    _ALPHA,
        "estimation_bars":          _ESTIMATION_BARS,
        "per_row_diagnostics":      per_row_diagnostics,
        "results":                  placebo,
        "caveats": [
            "Cache is composed of event-window shards warmed for specific "
            "operator-curated events; even date-shuffled fake events inherit "
            "regime characteristics of those windows. This is NOT a true "
            "null distribution.",
            "Eligibility is restricted to the contiguous aligned block "
            "containing each row's real event; fake dates whose estimation "
            "window or h=1 horizon would cross a multi-year cache gap are "
            "excluded by construction.",
            "Real-event exclusion: fakes must be either (a) at least "
            f"{_ESTIMATION_BARS} trading days BEFORE the real event (so the "
            "entire estimation window is clean), or (b) at least "
            f"{_POST_EVENT_EXCLUSION_TD} trading days AFTER the real event.",
            "Result should be read as 'given operator ticker choices and "
            "cache geometry, how often does a within-cache date-shuffle "
            "produce 5/5 q<alpha?' — NOT as the unconditional false-positive "
            "rate of the FDR procedure on the broader market.",
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only date-shuffled placebo null distribution for the "
            "v2 cohort. Estimates the within-cache base rate of 5/5 "
            "q<alpha under randomized fake first_trading_dates."
        ),
    )
    parser.add_argument("--artifact", default=_DEFAULT_ARTIFACT)
    parser.add_argument("--n-draws", type=int, default=_DEFAULT_N_DRAWS)
    parser.add_argument("--seed", type=int, default=_DEFAULT_SEED)
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of a text summary.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    result = run_all(args.artifact, n_draws=args.n_draws, seed=args.seed)
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        ok = result.get("ok")
        flag = "PASS" if ok else "FAIL"
        print(f"placebo null distribution: {flag}")
        if "setup_errors" in result:
            for e in result["setup_errors"]:
                print(f"  setup error: {e}")
            return 1
        r = result["results"]
        print(
            f"  n_draws={r['n_draws']}  seed={args.seed}  "
            f"alpha={result['alpha']}  rows={r['row_count']}"
        )
        print(
            f"  fraction(5/5 q<alpha) = {r['fraction_all_q_under_alpha']:.4f} "
            f"({r['count_all_q_under_alpha']} of {r['n_draws']})"
        )
        print(
            f"  fraction(>=4/5)       = {r['fraction_at_least_4']:.4f} "
            f"({r['count_at_least_4']} of {r['n_draws']})"
        )
        print(
            f"  fraction(>=3/5)       = {r['fraction_at_least_3']:.4f} "
            f"({r['count_at_least_3']} of {r['n_draws']})"
        )
        print(
            f"  median_discoveries    = {r['median_discoveries_per_draw']}"
        )
        print(
            f"  median_min_q          = {r['median_min_q_per_draw']}"
        )
        print("  per-row eligibility:")
        for d in result["per_row_diagnostics"]:
            print(
                f"    {d['primary_ticker']:>5}/{d['benchmark_ticker']:<4}  "
                f"aligned={d['aligned_total']}  "
                f"eligible_fake_dates={d['eligible_count']}"
            )
    return 0 if result.get("ok") else 1


__all__ = (
    "load_v2_cohort_rows",
    "_default_cache_reader",
    "_align_pair",
    "detect_contiguous_block_for_index",
    "compute_eligible_fake_indices",
    "_event_study_h1_p",
    "build_per_row_state",
    "run_placebo_draws",
    "run_all",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
