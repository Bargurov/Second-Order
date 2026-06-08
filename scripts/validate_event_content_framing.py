#!/usr/bin/env python
"""Z1A — banned-framing validator for a candidate expansion pack.

Read-only: scans candidate PROSE fields (title, mechanism_summary, asset
rationales, limitation_or_falsifier, category) for trading-signal / overclaim
framing and recommendation language. URLs, ids, tickers, and benchmarks are NOT
scanned (a 'trade-agreements' URL slug or a ticker is not prose framing). Exits
nonzero with reasons if any candidate's prose carries banned framing.

Usage: python scripts/validate_event_content_framing.py data/candidates/<pack>.yaml
"""
from __future__ import annotations

import os
import re
import sys

import yaml

# Trading-signal / overclaim tokens (word-boundary, case-insensitive).
_BANNED = ["buy", "sell", "long", "short", "alpha", "signal", "trade", "live trading",
           "proof", "proves", "confirmed"]
_BANNED_RE = [re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in _BANNED]
# Recommendation language.
_RECO_RE = [re.compile(p, re.IGNORECASE) for p in (
    r"\brecommend(s|ation)?\b", r"price target", r"\b(buy|sell)\s+rating\b", r"\bovervalued\b",
    r"\bunderpriced\b",
)]

# Only these fields carry reviewer-facing prose.
_PROSE_FIELDS = ("title", "mechanism_summary", "limitation_or_falsifier", "category")


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and "candidates" in data:
        return data["candidates"] or []
    if isinstance(data, list):
        return data
    return []


def _prose_of(c: dict):
    """Yield (field_label, text) for each prose string in a candidate."""
    for f in _PROSE_FIELDS:
        v = c.get(f)
        if isinstance(v, str) and v.strip():
            yield f, v
    for a in c.get("affected_assets") or []:
        if isinstance(a, dict):
            r = a.get("rationale")
            if isinstance(r, str) and r.strip():
                yield f"affected_assets[{a.get('ticker')}].rationale", r


def scan_candidates(path: str) -> list[str]:
    problems: list[str] = []
    try:
        candidates = _load(path)
    except Exception as exc:
        return [f"could not parse YAML: {exc}"]
    for i, c in enumerate(candidates):
        if not isinstance(c, dict):
            continue
        cid = c.get("id") or f"#{i}"
        for field, text in _prose_of(c):
            for rx in _BANNED_RE:
                if rx.search(text):
                    problems.append(f"{cid}: banned framing /{rx.pattern}/ in {field}")
            for rx in _RECO_RE:
                if rx.search(text):
                    problems.append(f"{cid}: recommendation language /{rx.pattern}/ in {field}")
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: validate_event_content_framing.py <candidates.yaml>", file=sys.stderr)
        return 2
    path = argv[0]
    if not os.path.exists(path):
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    problems = scan_candidates(path)
    if problems:
        print(f"FAIL: {len(problems)} framing problem(s) in {path}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {path} prose carries no buy/sell/signal/trade/proof/recommendation framing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
