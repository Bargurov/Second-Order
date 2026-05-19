#!/usr/bin/env python3
"""Read-only recompute checker for freeze_candidate_evidence_v2.json.

Recomputes the five v2 cohort h=1 production-BHAR values from the
local ``price_cache`` and compares them to the values recorded in the
artifact. Read-only end-to-end: no provider, no DB writes, no artifact
mutation, no LLM, no FastAPI surface.

Conventions
-----------

* Production engine: :func:`stats.event_study.compute_event_study`
  (BHAR; see that module's docstring for the exact formula).
* event_index = the trading day BEFORE first_trading_date — matches
  the v2.1 cohort convention. The engine then computes the h-horizon
  buy-and-hold AR as ``(P_asset[t+h]/P_asset[t] - 1) -
  (P_bench[t+h]/P_bench[t] - 1)``.
* BH q-values: :func:`stats.fdr.bh_adjust` across the cohort's five
  h=1 p-values, in cohort order.
* Estimation window: 60 trading days.

Tolerances
----------

Per-row comparison uses ``max(abs_tol, rel_tol * |expected|)``:

* AR_pct, SAR: ``abs_tol = 5e-4`` (storage precision is 4 decimals).
* p, q:        ``abs_tol = 1e-9``, ``rel_tol = 1e-3``.

These are intentionally tight: the engine is deterministic against
the same cache bars, so a real disagreement signals either a method
drift, a date error, or a cache mutation.

Invariants
----------

Independent of numerical recompute:

* Every candidate carries ``method == "production_bhar"``.
* CENX's ``first_trading_date == "2018-04-09"``.
* ``demo_wiring_note`` matches the v2.1 pinned string.
* Every value in ``cohort_statistics.q_values_summary`` is < 0.05.

Exit code
---------

0 = invariants OK AND every row matches within tolerance.
1 = any invariant fails OR any row mismatches OR a cache miss / setup
    error makes recompute impossible.

CLI
---

::

    python scripts/recompute_freeze_candidate_v2.py \\
        --artifact artifacts/freeze_candidate_evidence_v2.json --json

``--check`` is accepted but redundant — check semantics are the default.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date as _date, timedelta as _timedelta
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
_PRE_CAL_DAYS:     int = 200
_POST_CAL_DAYS:    int = 60
_ESTIMATION_BARS:  int = 60

_AR_ABS_TOL:  float = 5e-4
_SAR_ABS_TOL: float = 5e-4
_P_REL_TOL:   float = 1e-3
_Q_REL_TOL:   float = 1e-3
_P_ABS_TOL:   float = 1e-9
_Q_ABS_TOL:   float = 1e-9

_EXPECTED_DEMO_WIRING_NOTE: str = (
    "Section C Demo v1 is unchanged; this artifact is not wired to demo."
)


# ---------------------------------------------------------------------------
# Artifact loading
# ---------------------------------------------------------------------------


def load_artifact(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Cache reader seam — patchable by tests
# ---------------------------------------------------------------------------


def _window_bounds(first_trading_iso: str) -> tuple[str, str]:
    anchor = _date.fromisoformat(first_trading_iso[:10])
    start = (anchor - _timedelta(days=_PRE_CAL_DAYS)).isoformat()
    end = (anchor + _timedelta(days=_POST_CAL_DAYS)).isoformat()
    return start, end


def _default_cache_reader(
    ticker: str, start: str, end: str,
) -> Optional[tuple[list[str], list[float]]]:
    """Production cache reader. Lazy-imports ``price_cache`` so tests
    that patch the seam never pull the live DB into scope.

    Returns ``(dates_iso, closes_list)`` or ``None`` on cache miss.
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


# ---------------------------------------------------------------------------
# Per-row recompute
# ---------------------------------------------------------------------------


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


def recompute_row(
    *,
    primary_ticker:     str,
    benchmark_ticker:   str,
    first_trading_iso:  str,
    horizon:            int = 1,
    cache_reader:       Optional[Callable] = None,
    estimation_window:  int = _ESTIMATION_BARS,
) -> dict[str, Any]:
    """Recompute a single cohort row's h=h value from cache. Raises
    ``RuntimeError`` on any setup failure (cache miss, alignment gap,
    insufficient estimation window). The caller is expected to catch
    and report — this function intentionally does NOT swallow errors,
    so a buggy cohort fails loudly rather than silently masking the
    issue.
    """
    reader = cache_reader if cache_reader is not None else _default_cache_reader
    start, end = _window_bounds(first_trading_iso)
    p_data = reader(primary_ticker, start, end)
    b_data = reader(benchmark_ticker, start, end)
    if p_data is None:
        raise RuntimeError(
            f"cache miss for primary={primary_ticker} window={start}..{end}",
        )
    if b_data is None:
        raise RuntimeError(
            f"cache miss for benchmark={benchmark_ticker} window={start}..{end}",
        )
    p_dates, p_closes = p_data
    b_dates, b_closes = b_data
    common, a_aligned, b_aligned = _align_pair(
        p_dates, p_closes, b_dates, b_closes,
    )
    if first_trading_iso not in common:
        first = common[0] if common else "EMPTY"
        last = common[-1] if common else "EMPTY"
        raise RuntimeError(
            f"first_trading_date {first_trading_iso} not in aligned dates "
            f"for {primary_ticker}/{benchmark_ticker} "
            f"(aligned range {first}..{last})",
        )
    first_trading_idx = common.index(first_trading_iso)
    event_index = first_trading_idx - 1  # production convention
    if event_index < estimation_window:
        raise RuntimeError(
            f"insufficient estimation window for {primary_ticker}: "
            f"event_index={event_index} < {estimation_window}",
        )
    es = compute_event_study(
        asset_prices=a_aligned,
        benchmark_prices=b_aligned,
        event_index=event_index,
        horizons=(horizon,),
        estimation_window=estimation_window,
    )
    h = es["horizons"][horizon]
    ar_pct = (h["abnormal_return"] or 0.0) * 100.0
    sar = h["sar"]
    p = p_value_from_sar(sar, "two-sided")
    return {
        "primary_ticker":    primary_ticker,
        "benchmark_ticker":  benchmark_ticker,
        "first_trading_date": first_trading_iso,
        "event_index":       event_index,
        "h1_AR_pct":         ar_pct,
        "h1_SAR":            sar,
        "h1_p":              p,
        "warnings":          list(es.get("warnings", [])),
    }


# ---------------------------------------------------------------------------
# Cohort orchestration
# ---------------------------------------------------------------------------


def recompute_cohort(
    artifact: dict[str, Any],
    *,
    cache_reader: Optional[Callable] = None,
) -> tuple[list[dict[str, Any]], list[Optional[float]]]:
    """Recompute every candidate row plus the cohort BH q-values.

    Returns ``(rows, q_values_in_cohort_order)``. Q-values are computed
    via :func:`stats.fdr.bh_adjust` across the recomputed h=1 p-values
    in cohort order. The artifact's recorded ordering of candidates is
    preserved (it is the same insertion order used for ``q_values_summary``).
    """
    candidates = artifact.get("candidates", [])
    rows: list[dict[str, Any]] = []
    for c in candidates:
        rows.append(recompute_row(
            primary_ticker=c["primary_ticker"],
            benchmark_ticker=c["benchmark_ticker"],
            first_trading_iso=c["first_trading_date"],
            cache_reader=cache_reader,
        ))
    p_values = [r["h1_p"] for r in rows]
    bh = bh_adjust(p_values, alpha=0.05)
    q_values: list[Optional[float]] = list(bh["adjusted"])
    return rows, q_values


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def _is_close(
    actual: Optional[float], expected: Optional[float],
    *, abs_tol: float, rel_tol: float = 0.0,
) -> bool:
    if actual is None or expected is None:
        return False
    if not (math.isfinite(actual) and math.isfinite(expected)):
        return actual == expected
    return abs(actual - expected) <= max(abs_tol, rel_tol * abs(expected))


def compare_to_artifact(
    *,
    artifact_candidates: list[dict[str, Any]],
    recomputed_rows:     list[dict[str, Any]],
    recomputed_qs:       list[Optional[float]],
    ar_abs_tol:  float = _AR_ABS_TOL,
    sar_abs_tol: float = _SAR_ABS_TOL,
    p_rel_tol:   float = _P_REL_TOL,
    q_rel_tol:   float = _Q_REL_TOL,
    p_abs_tol:   float = _P_ABS_TOL,
    q_abs_tol:   float = _Q_ABS_TOL,
) -> dict[str, Any]:
    """Per-row comparison. Returns ``{all_pass, rows: [...]}``."""
    art_by_ticker = {c["primary_ticker"]: c for c in artifact_candidates}
    rec_by_ticker = {r["primary_ticker"]: r for r in recomputed_rows}
    rec_q_by_ticker = {
        r["primary_ticker"]: q
        for r, q in zip(recomputed_rows, recomputed_qs)
    }

    out_rows: list[dict[str, Any]] = []
    all_pass = True
    for ticker, art_row in art_by_ticker.items():
        rec = rec_by_ticker.get(ticker)
        rec_q = rec_q_by_ticker.get(ticker)
        if rec is None:
            out_rows.append({
                "primary_ticker": ticker, "ok": False,
                "error": "no recomputed row",
            })
            all_pass = False
            continue
        ar_match = _is_close(
            rec["h1_AR_pct"], art_row.get("h1_AR_pct"),
            abs_tol=ar_abs_tol,
        )
        sar_match = _is_close(
            rec["h1_SAR"], art_row.get("h1_SAR"),
            abs_tol=sar_abs_tol,
        )
        p_match = _is_close(
            rec["h1_p"], art_row.get("h1_p"),
            abs_tol=p_abs_tol, rel_tol=p_rel_tol,
        )
        q_match = _is_close(
            rec_q, art_row.get("h1_q_bh"),
            abs_tol=q_abs_tol, rel_tol=q_rel_tol,
        )
        row_ok = ar_match and sar_match and p_match and q_match
        if not row_ok:
            all_pass = False
        out_rows.append({
            "primary_ticker": ticker,
            "ok": row_ok,
            "h1_AR_pct": {
                "artifact": art_row.get("h1_AR_pct"),
                "recomputed": rec["h1_AR_pct"], "match": ar_match,
            },
            "h1_SAR": {
                "artifact": art_row.get("h1_SAR"),
                "recomputed": rec["h1_SAR"], "match": sar_match,
            },
            "h1_p": {
                "artifact": art_row.get("h1_p"),
                "recomputed": rec["h1_p"], "match": p_match,
            },
            "h1_q_bh": {
                "artifact": art_row.get("h1_q_bh"),
                "recomputed": rec_q, "match": q_match,
            },
        })
    return {"all_pass": all_pass, "rows": out_rows}


# ---------------------------------------------------------------------------
# Invariant checks (non-numeric)
# ---------------------------------------------------------------------------


def run_invariant_checks(artifact: dict[str, Any]) -> dict[str, Any]:
    candidates = artifact.get("candidates", [])
    methods = [c.get("method") for c in candidates]
    all_method_production_bhar = (
        len(methods) == 5
        and all(m == "production_bhar" for m in methods)
    )
    cenx = next(
        (c for c in candidates if c.get("primary_ticker") == "CENX"),
        None,
    )
    cenx_first_trading_is_apr9 = (
        cenx is not None
        and cenx.get("first_trading_date") == "2018-04-09"
    )
    demo_note = artifact.get("demo_wiring_note", "")
    demo_wiring_note_preserved = demo_note == _EXPECTED_DEMO_WIRING_NOTE

    qsum = artifact.get("cohort_statistics", {}).get(
        "q_values_summary", {},
    )
    all_artifact_q_below_005 = bool(qsum) and all(
        isinstance(q, (int, float)) and q < 0.05
        for q in qsum.values()
    )

    ok = (
        all_method_production_bhar
        and cenx_first_trading_is_apr9
        and demo_wiring_note_preserved
        and all_artifact_q_below_005
    )
    return {
        "ok": ok,
        "all_method_production_bhar":   all_method_production_bhar,
        "cenx_first_trading_is_apr9":   cenx_first_trading_is_apr9,
        "demo_wiring_note_preserved":   demo_wiring_note_preserved,
        "all_artifact_q_below_005":     all_artifact_q_below_005,
    }


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


def run_all(
    artifact_path: str,
    *,
    cache_reader: Optional[Callable] = None,
) -> dict[str, Any]:
    artifact = load_artifact(artifact_path)
    invariants = run_invariant_checks(artifact)
    rows, qs = recompute_cohort(artifact, cache_reader=cache_reader)
    comparison = compare_to_artifact(
        artifact_candidates=artifact["candidates"],
        recomputed_rows=rows,
        recomputed_qs=qs,
    )
    ok = invariants["ok"] and comparison["all_pass"]
    return {
        "ok":                                 ok,
        "artifact_path":                      artifact_path,
        "invariants":                         invariants,
        "recomputed_rows":                    rows,
        "recomputed_q_values_in_cohort_order": qs,
        "comparison":                         comparison,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only recompute checker for the v2 freeze artifact. "
            "Recomputes h=1 production-BHAR for the 5 cohort rows from "
            "price_cache via stats.event_study and compares to the "
            "values recorded in the artifact. Exits non-zero on mismatch."
        ),
    )
    parser.add_argument(
        "--artifact", default=_DEFAULT_ARTIFACT,
        help=f"Path to the artifact JSON. Default: {_DEFAULT_ARTIFACT}",
    )
    parser.add_argument(
        "--json", action="store_true", dest="as_json",
        help="Emit structured JSON instead of a compact text summary.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help=(
            "Accepted for explicitness. Check semantics are the default: "
            "the script always exits non-zero on any mismatch or "
            "invariant violation. Pass this flag to make the intent "
            "explicit in scripts/CI."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        result = run_all(args.artifact)
    except RuntimeError as exc:
        result = {
            "ok": False,
            "artifact_path": args.artifact,
            "error": f"{type(exc).__name__}: {exc}",
        }
    except FileNotFoundError as exc:
        result = {
            "ok": False,
            "artifact_path": args.artifact,
            "error": f"artifact not found: {exc}",
        }
    if args.as_json:
        print(json.dumps(result, indent=2, default=str))
    else:
        ok = result.get("ok")
        flag = "PASS" if ok else "FAIL"
        print(f"recompute checker: {flag}")
        if "error" in result:
            print(f"  error: {result['error']}")
        else:
            inv = result.get("invariants", {})
            print(
                f"  invariants: "
                f"method={inv.get('all_method_production_bhar')} "
                f"cenx_apr9={inv.get('cenx_first_trading_is_apr9')} "
                f"demo_note={inv.get('demo_wiring_note_preserved')} "
                f"all_q<0.05={inv.get('all_artifact_q_below_005')}"
            )
            for row in result.get("comparison", {}).get("rows", []):
                rflag = "PASS" if row["ok"] else "FAIL"
                print(f"  {row['primary_ticker']:>5}  {rflag}")
    return 0 if result.get("ok") else 1


__all__ = (
    "load_artifact",
    "recompute_row",
    "recompute_cohort",
    "compare_to_artifact",
    "run_invariant_checks",
    "run_all",
    "main",
    # Internal seams exposed for tests
    "_is_close",
    "_align_pair",
    "_window_bounds",
    "_default_cache_reader",
)


if __name__ == "__main__":
    sys.exit(main())
