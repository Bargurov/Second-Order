#!/usr/bin/env python3
"""Read-only naive-baseline characterization report (T2A).

Answers "compared to what?" for the scored archive: it compares the observed
support / contradiction / unresolved outcomes against a marginal-preserving
PERMUTATION null (see ``stats.baseline_characterization`` for why a fair coin is
the wrong baseline for a prediction-skewed corpus), and attaches the
event-study-available split.

Read-only: opens ``events.db`` with ``mode=ro`` and loops the existing
event-study gate over cached prices.  No provider, no network, no DB write.  It
NEVER reads, merges, or implies the closed Phase 1 / Phase 2 FDR pools — every
payload carries explicit non-claims, limitations, and a falsifier.

Usage:
    python scripts/baseline_characterization_report.py [--json] [--seed N] [--sims N]
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stats.baseline_characterization import (  # noqa: E402
    ar_sign_observation,
    build_baseline_characterization,
    build_ar_sign_report,
    build_multi_ticker_ar_report,
    event_study_split,
)
from stats.robust_diagnostics import build_diagnostics_block  # noqa: E402

# Horizons mirror stats.baseline_characterization's AR-sign report.  The overlap
# window length reuses the horizon value as a calendar-day proxy for the
# trading-day horizon (disclosed in the robust-diagnostics non-claims).
_ROBUST_HORIZONS: tuple[int, ...] = (1, 5, 20)


def _load_events_readonly(db_path: str) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM events").fetchall()
    finally:
        conn.close()
    events: list[dict] = []
    for r in rows:
        d = dict(r)
        raw = d.get("market_tickers")
        try:
            d["market_tickers"] = json.loads(raw) if raw else []
        except Exception:
            d["market_tickers"] = []
        events.append(d)
    return events


def _event_ordinal(event: dict):
    """Event date as an integer day ordinal, or ``None`` if unparseable."""
    raw = event.get("event_date") if isinstance(event, dict) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip()[:10]).toordinal()
    except ValueError:
        return None


def _robust_per_horizon(events, event_study_fn) -> dict:
    """Extract per-horizon eligible abnormal returns + window starts + SAR rows.

    Eligibility is decided by ``ar_sign_observation`` — the SAME gate the
    AR-sign report uses — so the diagnostics' ``n`` matches the report's
    ``eligible`` count exactly (no third denominator).
    """
    per: dict[int, dict] = {
        h: {"ar_values": [], "window_starts": [], "window_length": h, "es_rows": []}
        for h in _ROBUST_HORIZONS
    }
    for ev in events if isinstance(events, list) else []:
        tickers = ev.get("market_tickers") if isinstance(ev, dict) else None
        if not isinstance(tickers, list) or not tickers:
            continue
        try:
            block = event_study_fn(ev) or {}
        except Exception:
            continue
        if block.get("status") != "event_study_available":
            continue
        sigma = block.get("sigma_ar_daily")
        ordn = _event_ordinal(ev)
        by_h: dict[int, dict] = {}
        for r in block.get("per_horizon") or []:
            if isinstance(r, dict):
                try:
                    by_h[int(r.get("horizon"))] = r
                except (TypeError, ValueError):
                    pass
        for h in _ROBUST_HORIZONS:
            obs = ar_sign_observation(ev, block, h)
            if obs is None:
                continue  # not eligible — keeps n aligned with the AR-sign report
            row = by_h.get(h) or {}
            try:
                ar = float(row.get("abnormal_return"))
            except (TypeError, ValueError):
                continue
            per[h]["ar_values"].append(ar)
            if ordn is not None:
                per[h]["window_starts"].append(ordn)
            per[h]["es_rows"].append({
                "abnormal_return": row.get("abnormal_return"),
                "car": row.get("car"),
                "sigma_ar_daily": sigma,
            })
    return per


def build_report(db_path: str, *, seed: int, n_sims: int) -> dict:
    events = _load_events_readonly(db_path)
    payload = build_baseline_characterization(events, seed=seed, n_sims=n_sims)
    try:
        from event_study_validation import build_event_study_validation, event_study_ar_for_symbol
        payload["event_study_split"] = event_study_split(events, build_event_study_validation)
        payload["ar_sign_disentangler"] = build_ar_sign_report(
            events, build_event_study_validation, seed=seed, n_sims=n_sims)

        # Memoise the per-symbol AR so the three horizons reuse one read per
        # (symbol, event_date) instead of recomputing the event-study three times.
        _ar_cache: dict = {}

        def _ar_fn(symbol, event_date):
            key = (str(symbol).upper(), event_date)
            if key not in _ar_cache:
                _ar_cache[key] = event_study_ar_for_symbol(symbol, event_date)
            return _ar_cache[key]

        payload["multi_ticker_ar"] = build_multi_ticker_ar_report(
            events, _ar_fn, seed=seed, n_sims=n_sims)

        # Small-sample robustness diagnostics — descriptive supplements over the
        # SAME eligible AR set as the AR-sign report (additive, read-only).
        payload["robust_diagnostics"] = build_diagnostics_block(
            _robust_per_horizon(events, build_event_study_validation))
    except Exception as exc:  # pragma: no cover - defensive; report still ships
        payload["event_study_split"] = {"error": f"event-study split unavailable: {exc}"}
        payload["ar_sign_disentangler"] = {"error": f"AR-sign disentangler unavailable: {exc}"}
        payload["multi_ticker_ar"] = {"error": f"multi-ticker AR unavailable: {exc}"}
        payload["robust_diagnostics"] = {"error": f"robust diagnostics unavailable: {exc}"}
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description="Read-only baseline characterization report.")
    ap.add_argument("--json", action="store_true", help="emit JSON only")
    ap.add_argument("--seed", type=int, default=20260608)
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--db", default="events.db")
    args = ap.parse_args()

    report = build_report(args.db, seed=args.seed, n_sims=args.sims)

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    o = report["observed"]
    m = report["marginals"]
    b = report["baseline"]["event_level"]
    print("Baseline characterization — scored archive (read-only)")
    print(f"  scored events: {o['total_scored']}  "
          f"({o['any_supporting']} any-supporting / {o['contradicted']} contradicted / "
          f"{o['unresolved']} unresolved)")
    print(f"  directional: {o['directional_events']} events, {o['directional_ticker_total']} "
          f"ticker-observations; observed supporting fraction {o['observed_supporting_fraction']}")
    print(f"  marginals: predicted-up {m['predicted_up_fraction']}, realized-up "
          f"{m['realized_up_fraction']}  (beneficiary-support {m['beneficiary_support_rate']}, "
          f"loser-support {m['loser_support_rate']})")
    print(f"  permutation null support rate: {report['baseline']['null_support_rate_mean']}")
    print(f"  event-level validated: observed {b['observed_validated']} vs null mean "
          f"{b['null_validated_mean']} (95% {b['null_validated_ci95']}), "
          f"percentile {b['observed_validated_percentile']}")
    print(f"  verdict: {report['interpretation']}")
    print(f"  event-study split: {report.get('event_study_split')}")
    ar = report.get("ar_sign_disentangler") or {}
    if "horizons" in ar:
        print(f"  AR-sign disentangler (vs {ar['benchmark']}): reliable={ar['reliable']} "
              f"({ar['interpretation']})")
        for h in ("1", "5", "20"):
            hd = ar["horizons"][h]
            print(f"    {h}d: eligible {hd['eligible']} | support {hd['observed_support_fraction']} "
                  f"| predicted-up {hd['predicted_up_fraction']} | AR-up {hd['ar_up_fraction']} "
                  f"| reliable {hd['reliable']}")
    mt = report.get("multi_ticker_ar") or {}
    if "horizons" in mt:
        cov = mt["coverage"]
        print(f"  multi-ticker AR (vs {mt['benchmark']}): {mt['interpretation']} "
              f"| reliable={mt['reliable']} thin={mt['reliable_but_thin']}")
        print(f"    coverage: beneficiary {cov['beneficiary_ar']}/{cov['beneficiary_slots']} "
              f"({cov['beneficiary_coverage']}), loser {cov['loser_ar']}/{cov['loser_slots']} "
              f"({cov['loser_coverage']})")
        for h in ("1", "5", "20"):
            hd = mt["horizons"][h]
            tl = hd["ticker_level"]
            print(f"    {h}d: obs {hd['eligible_ticker_obs']} | pred-up {hd['predicted_up_fraction']} "
                  f"| support {tl['observed_support_fraction']} vs null {tl['null_support_rate_mean']} "
                  f"{tl['null_support_rate_ci95']} | dir {tl['direction_vs_null']}")
    rd = report.get("robust_diagnostics") or {}
    if "horizons" in rd:
        print(f"  robust diagnostics (vs {rd.get('benchmark')}) - descriptive "
              f"supplements; overlap is the independence qualifier:")
        for h in ("1", "5", "20"):
            hd = rd["horizons"].get(h) or {}
            st = hd.get("sign_test") or {}
            rk = hd.get("rank_test") or {}
            ov = hd.get("overlap") or {}
            print(f"    {h}d: sign-test n={st.get('n')} "
                  f"(+{st.get('n_pos')}/-{st.get('n_neg')}) "
                  f"p={st.get('p_value')} [{st.get('status')}] "
                  f"| signed-rank p={rk.get('p_value')} "
                  f"[{rk.get('method')}/{rk.get('status')}] "
                  f"| overlap pairs={ov.get('overlapping_pairs')} "
                  f"max_concurrent={ov.get('max_concurrent')} "
                  f"frac_in_overlap={ov.get('fraction_in_overlap')}")
        sar = rd.get("sar_convention") or {}
        print(f"    SAR convention: {sar.get('numerator_convention')} numerator / "
              f"{sar.get('denominator_convention')} denominator "
              f"(match={sar.get('conventions_match')}, status={sar.get('status')})")
        for r in sar.get("per_horizon") or []:
            print(f"      h{r['horizon']}: mean SAR-delta {round(r['mean_sar_delta'], 4)} "
                  f"| max|SAR-delta| {round(r['max_abs_sar_delta'], 4)} (n={r['n']})")
        print("    robust-diagnostics non-claims:")
        for nc in rd.get("non_claims") or []:
            print(f"      - {nc}")
    print("  non-claims:")
    for nc in report["non_claims"]:
        print(f"    - {nc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
