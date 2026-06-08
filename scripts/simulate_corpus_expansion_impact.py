#!/usr/bin/env python
"""Z1A — read-only PRE-INGESTION estimator for a candidate expansion pack.

Estimates, WITHOUT ingesting events or fetching prices, what a candidate pack
would do to corpus breadth: category/year/month splits, current-vs-projected
temporal and oil-theme concentration, how many candidate tickers already have
deep cached price history (a coarse placebo-feasibility proxy), which candidate
tickers have NO cached history (would need a future, separately-gated DB-copy
backfill), and concentration warnings.

EVERY number is a pre-ingestion estimate, NOT an event-study result. The
estimator opens the DB read-only (mode=ro), imports no provider, fetches
nothing, and writes nothing.

Usage: python scripts/simulate_corpus_expansion_impact.py <candidates.yaml> [--db events.db]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import Counter

import yaml

OIL_COMPLEX = {"XLE", "USO", "BNO", "XOP", "CVX", "XOM", "COP", "OXY", "VLO", "MPC",
               "PSX", "FRO", "DHT", "STNG", "DUG"}
DEEP_CACHE_ROWS = 250
CONCENTRATION_THRESHOLD = 0.40


def _load_candidates(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and "candidates" in data:
        return data["candidates"] or []
    if isinstance(data, list):
        return data
    return []


def _ticker_set(candidate: dict) -> set:
    return {(a.get("ticker") or "").strip().upper()
            for a in candidate.get("affected_assets") or [] if isinstance(a, dict) and a.get("ticker")}


def _current_corpus(db_path: str) -> dict:
    """Read-only current-corpus concentration from events.db."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        months = Counter()
        oil = 0
        scored = 0
        for r in con.execute("SELECT event_date, market_tickers FROM events"):
            mt = r["market_tickers"]
            try:
                tks = json.loads(mt) if isinstance(mt, str) and mt else mt
            except ValueError:
                tks = None
            if not (isinstance(tks, list) and tks):
                continue
            scored += 1
            ed = (r["event_date"] or "")[:7]
            if ed:
                months[ed] += 1
            syms = {(t.get("symbol") or "").upper() for t in tks if isinstance(t, dict)}
            if syms & OIL_COMPLEX:
                oil += 1
        return {"scored": scored, "months": months, "oil": oil}
    finally:
        con.close()


def _cache_depths(db_path: str, tickers: set) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out = {}
        for tk in tickers:
            try:
                n = con.execute("SELECT COUNT(*) FROM price_cache WHERE ticker=?", (tk,)).fetchone()[0]
            except sqlite3.Error:
                n = 0
            out[tk] = n
        return out
    finally:
        con.close()


def _share(counter, total) -> float:
    return (max(counter.values()) / total) if (counter and total) else 0.0


def build_estimate(candidates_path: str, db_path: str = "events.db") -> dict:
    candidates = _load_candidates(candidates_path)
    n = len(candidates)

    category_split = Counter((c.get("category") or "uncategorized") for c in candidates)
    year_split = Counter(str(c.get("event_date") or "")[:4] for c in candidates)
    month_split = Counter(str(c.get("event_date") or "")[:7] for c in candidates)

    cand_tickers = set()
    cand_oil = 0
    for c in candidates:
        ts = _ticker_set(c)
        cand_tickers |= ts
        if ts & OIL_COMPLEX:
            cand_oil += 1

    depths = _cache_depths(db_path, cand_tickers)
    missing = sorted(tk for tk, d in depths.items() if d == 0)
    need_backfill = sorted(tk for tk, d in depths.items() if d < DEEP_CACHE_ROWS)
    deep_now = sorted(tk for tk, d in depths.items() if d >= DEEP_CACHE_ROWS)
    deep_cache_candidate_count = sum(
        1 for c in candidates if any(depths.get(tk, 0) >= DEEP_CACHE_ROWS for tk in _ticker_set(c))
    )

    cur = _current_corpus(db_path)
    cur_scored = cur["scored"]
    proj_scored = cur_scored + n
    # month concentration
    cur_month_share = _share(cur["months"], cur_scored)
    proj_months = Counter(cur["months"])
    for m, k in month_split.items():
        proj_months[m] += k
    proj_month_share = _share(proj_months, proj_scored)
    # oil concentration
    cur_oil_share = (cur["oil"] / cur_scored) if cur_scored else 0.0
    proj_oil_share = ((cur["oil"] + cand_oil) / proj_scored) if proj_scored else 0.0

    warnings = []
    for cat, k in category_split.items():
        if n and k / n > CONCENTRATION_THRESHOLD:
            warnings.append(f"category concentration: {cat} is {k}/{n} ({100*k/n:.0f}%) of the pack (> {int(CONCENTRATION_THRESHOLD*100)}%)")
    for m, k in month_split.items():
        if n and k / n > CONCENTRATION_THRESHOLD:
            warnings.append(f"month concentration: {m} is {k}/{n} ({100*k/n:.0f}%) of the pack (> {int(CONCENTRATION_THRESHOLD*100)}%)")
    if missing:
        warnings.append(f"{len(missing)} candidate ticker(s) have NO cached price history (future DB-copy backfill needed): {missing}")

    return {
        "estimate_only": True,
        "label": "PRE-INGESTION ESTIMATE ONLY — not an event-study result; no events ingested, no prices fetched.",
        "candidate_count": n,
        "category_split": dict(category_split),
        "year_split": dict(year_split),
        "month_split": dict(month_split),
        "distinct_tickers": sorted(cand_tickers),
        "deep_cache_now": deep_now,
        "deep_cache_candidate_count": deep_cache_candidate_count,
        "candidates_missing_cache": missing,
        "candidates_need_backfill": need_backfill,
        "month_concentration": {"current": round(cur_month_share, 3), "projected": round(proj_month_share, 3)},
        "oil_concentration": {"current": round(cur_oil_share, 3), "projected": round(proj_oil_share, 3)},
        "corpus": {"current_scored": cur_scored, "projected_scored": proj_scored},
        "warnings": warnings,
    }


def summarize(est: dict) -> str:
    L = [
        "Corpus expansion impact — PRE-INGESTION ESTIMATE ONLY (read-only; no ingestion, no fetch)",
        f"  {est['label']}",
        f"  candidates: {est['candidate_count']} | distinct tickers: {len(est['distinct_tickers'])}",
        f"  category split: {est['category_split']}",
        f"  year split: {est['year_split']}",
        f"  month split: {est['month_split']}",
        f"  month concentration (max share): current {est['month_concentration']['current']} -> "
        f"projected {est['month_concentration']['projected']}",
        f"  oil-theme concentration: current {est['oil_concentration']['current']} -> "
        f"projected {est['oil_concentration']['projected']}",
        f"  deep-cache candidates (>= {DEEP_CACHE_ROWS} rows already): {est['deep_cache_candidate_count']} "
        f"(tickers {est['deep_cache_now']})",
        f"  candidate tickers missing cache (need future backfill): {est['candidates_missing_cache']}",
        f"  candidate tickers needing backfill (< {DEEP_CACHE_ROWS} rows): {est['candidates_need_backfill']}",
        "  warnings:",
    ]
    for w in est["warnings"] or ["(none)"]:
        L.append(f"    - {w}")
    L.append("  (placebo-feasibility is ESTIMATED from existing cache depth only; actual feasibility "
             "requires the gated DB-copy backfill + archive_placebo re-run.)")
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Pre-ingestion corpus-expansion impact estimator (read-only).")
    p.add_argument("candidates")
    p.add_argument("--db", default="events.db")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    if not os.path.exists(args.candidates):
        print(f"file not found: {args.candidates}", file=sys.stderr)
        return 2
    est = build_estimate(args.candidates, args.db)
    print(json.dumps(est, indent=2) if args.json else summarize(est))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
