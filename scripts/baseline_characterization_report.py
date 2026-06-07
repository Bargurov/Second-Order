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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stats.baseline_characterization import (  # noqa: E402
    build_baseline_characterization,
    build_ar_sign_report,
    event_study_split,
)


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


def build_report(db_path: str, *, seed: int, n_sims: int) -> dict:
    events = _load_events_readonly(db_path)
    payload = build_baseline_characterization(events, seed=seed, n_sims=n_sims)
    try:
        from event_study_validation import build_event_study_validation
        payload["event_study_split"] = event_study_split(events, build_event_study_validation)
        payload["ar_sign_disentangler"] = build_ar_sign_report(
            events, build_event_study_validation, seed=seed, n_sims=n_sims)
    except Exception as exc:  # pragma: no cover - defensive; report still ships
        payload["event_study_split"] = {"error": f"event-study split unavailable: {exc}"}
        payload["ar_sign_disentangler"] = {"error": f"AR-sign disentangler unavailable: {exc}"}
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
    print("  non-claims:")
    for nc in report["non_claims"]:
        print(f"    - {nc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
