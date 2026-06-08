#!/usr/bin/env python3
"""Z1B (Gate 1) — read-only before/after measurement on a DB copy.

Measures what the Z1A candidate-pack ingestion + free backfill did to corpus
breadth and event-study readiness ON A COPY ONLY.  It reports, for a before DB
and an after DB:

  * saved events, market-scored events, event-study-available events
  * beneficiary/loser role observations (note: Z1A "exposed" names are
    direction-agnostic and do NOT enter the directional role count by design)
  * event-date-eligible and placebo-feasible observations (via the existing
    archive placebo harness)
  * temporal / theme concentration and family / year / month splits
  * candidate-specific event-study readiness (per affected ticker vs SPY)

Every number is a descriptive coverage read on a COPY that is NOT promoted to
live.  This is a breadth / readiness measurement, not a directional, predictive,
or statistical-importance claim.  Read-only: no writes, no provider, no billed call.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import db  # noqa: E402

NON_CLAIM = (
    "Descriptive breadth / readiness measurement on a non-promoted DB copy; "
    "not a directional, predictive, or statistical-importance claim."
)

# Reuse the Z1A theme set so the oil-concentration read matches the simulator.
try:
    from scripts.simulate_corpus_expansion_impact import OIL_COMPLEX
except Exception:  # pragma: no cover
    OIL_COMPLEX = {"XLE", "USO", "BNO", "XOP", "CVX", "XOM", "COP", "OXY", "VLO", "MPC"}

_SCALAR_METRICS = (
    "saved_events", "market_scored_events", "event_study_available",
    "role_observations", "event_date_eligible", "placebo_feasible",
)


def _ro(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _events(db_path: str) -> list[dict]:
    con = _ro(db_path)
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, event_date, mechanism_family, market_tickers FROM events")]
    finally:
        con.close()


def _parse_tickers(raw: Any) -> list[dict]:
    try:
        tks = json.loads(raw) if isinstance(raw, str) and raw else raw
    except ValueError:
        return []
    return tks if isinstance(tks, list) else []


def _event_study_available_count(db_path: str, rows: list[dict]) -> int:
    """Count events whose primary ticker is event-study computable on this DB.

    Rebinds the resolved DB to ``db_path`` so the read-only price reads land on
    the copy, then restores it.
    """
    from event_study_validation import build_event_study_validation, STATUS_AVAILABLE
    orig = db.DB_FILE
    n = 0
    try:
        db.DB_FILE = db_path
        for r in rows:
            payload = {"event_date": r.get("event_date"), "market_tickers": r.get("market_tickers")}
            res = build_event_study_validation(payload)
            if res.get("status") == STATUS_AVAILABLE:
                n += 1
    finally:
        db.DB_FILE = orig
    return n


def snapshot(db_path: str, *, draws: int = 200) -> dict:
    """Read-only breadth / readiness snapshot of one DB."""
    rows = _events(db_path)
    saved = len(rows)
    scored = 0
    months = Counter()
    years = Counter()
    families = Counter()
    oil = 0
    for r in rows:
        tks = _parse_tickers(r.get("market_tickers"))
        families[(r.get("mechanism_family") or "none")] += 1
        if not tks:
            continue
        scored += 1
        ed = (r.get("event_date") or "")[:7]
        if ed:
            months[ed] += 1
            years[ed[:4]] += 1
        syms = {(t.get("symbol") or "").upper() for t in tks if isinstance(t, dict)}
        if syms & OIL_COMPLEX:
            oil += 1

    available = _event_study_available_count(db_path, rows)

    # Placebo-side denominators from the existing harness (read-only).
    from stats.archive_placebo import build_report
    pb = build_report(db_path, draws=draws)
    role_obs = pb["archive_denominator"]["role_observations"]
    event_eligible = pb["event_anchor_eligible"]
    placebo_feasible = pb["observed_eligible"]

    return {
        "saved_events": saved,
        "market_scored_events": scored,
        "event_study_available": available,
        "role_observations": role_obs,
        "event_date_eligible": event_eligible,
        "placebo_feasible": placebo_feasible,
        "concentration": {
            "max_month_share": round(max(months.values()) / scored, 4) if scored and months else 0.0,
            "oil_theme_share": round(oil / scored, 4) if scored else 0.0,
        },
        "family_split": dict(families),
        "year_split": dict(years),
        "month_split": dict(months),
    }


def _load_candidates(candidates_path: str) -> list[dict]:
    import yaml
    with open(candidates_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and "candidates" in data:
        return list(data["candidates"] or [])
    if isinstance(data, list):
        return list(data)
    return []


def candidate_readiness(after_db: str, candidates_path: str) -> list[dict]:
    """Per-candidate event-study readiness on ``after_db`` (one row per affected
    ticker vs SPY), read-only."""
    from event_study_validation import event_study_ar_for_symbol, STATUS_AVAILABLE
    candidates = _load_candidates(candidates_path)
    out = []
    orig = db.DB_FILE
    try:
        db.DB_FILE = after_db
        for c in candidates:
            ed = str(c.get("event_date") or "")[:10]
            tickers = []
            for a in c.get("affected_assets") or []:
                if not isinstance(a, dict):
                    continue
                sym = (a.get("ticker") or "").strip().upper()
                if not sym:
                    continue
                res = event_study_ar_for_symbol(sym, ed)
                tickers.append({"ticker": sym, "role": a.get("role"),
                                "status": res.get("status")})
            out.append({
                "id": c.get("id"), "event_date": ed,
                "tickers": tickers,
                "any_available": any(t["status"] == STATUS_AVAILABLE for t in tickers),
            })
    finally:
        db.DB_FILE = orig
    return out


def build_before_after(before_db: str, after_db: str, candidates_path: Optional[str],
                       *, draws: int = 200) -> dict:
    before = snapshot(before_db, draws=draws)
    after = snapshot(after_db, draws=draws)
    deltas = {k: after[k] - before[k] for k in _SCALAR_METRICS}
    readiness = candidate_readiness(after_db, candidates_path) if candidates_path else []
    return {
        "copy_only": True,
        "not_promoted": True,
        "before": before,
        "after": after,
        "deltas": deltas,
        "candidate_readiness": readiness,
        "candidate_ready_count": sum(1 for c in readiness if c.get("any_available")),
        "non_claim": NON_CLAIM,
    }


def summarize(report: dict) -> str:
    b, a, d = report["before"], report["after"], report["deltas"]
    L = [
        "Z1B copy-DB before/after measurement (read-only; COPY ONLY, NOT promoted to live)",
        f"  {report['non_claim']}",
        "",
        f"  {'metric':<26}{'before':>8}{'after':>8}{'delta':>8}",
    ]
    labels = {
        "saved_events": "saved events",
        "market_scored_events": "market-scored events",
        "event_study_available": "event-study available",
        "role_observations": "role obs (benef/loser)",
        "event_date_eligible": "event-date eligible",
        "placebo_feasible": "placebo-feasible",
    }
    for k in _SCALAR_METRICS:
        L.append(f"  {labels[k]:<26}{b[k]:>8}{a[k]:>8}{d[k]:>+8}")
    L += [
        "",
        f"  max-month share:  {b['concentration']['max_month_share']} -> {a['concentration']['max_month_share']}",
        f"  oil-theme share:  {b['concentration']['oil_theme_share']} -> {a['concentration']['oil_theme_share']}",
        f"  family split (after): {a['family_split']}",
        f"  candidate-specific readiness: {report['candidate_ready_count']}/"
        f"{len(report['candidate_readiness'])} candidates have >=1 event-study-available ticker",
        "",
        "  Note: Z1A 'exposed' names are direction-agnostic and do not enter the "
        "beneficiary/loser role count; the directional placebo null is unchanged by them.",
        "  Copy-only result. Not promoted to live. Gate 2 (live promotion) is a separate operator decision.",
    ]
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Z1B read-only before/after copy-DB measurement.")
    p.add_argument("--before-db", dest="before_db", required=True)
    p.add_argument("--after-db", dest="after_db", required=True)
    p.add_argument("--candidates", default=None)
    p.add_argument("--draws", type=int, default=1000)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    rep = build_before_after(args.before_db, args.after_db, args.candidates, draws=args.draws)
    print(json.dumps(rep, indent=2, default=str) if args.json else summarize(rep))
    return 0


__all__ = ("snapshot", "candidate_readiness", "build_before_after", "summarize", "main", "NON_CLAIM")


if __name__ == "__main__":
    raise SystemExit(main())
