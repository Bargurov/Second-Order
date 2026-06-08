#!/usr/bin/env python
"""Z1A — structural + anti-synthetic validator for a candidate expansion pack.

Read-only: parses a candidate YAML and rejects synthetic/demo/rehearsal framing,
missing/placeholder source URLs, non-canonical mechanism_family, missing or bad
affected-asset roles, bad review_status / source_type / placebo guess, forward-
dated events, and missing required fields. Exits nonzero with reasons if any
candidate fails. Does NOT ingest, fetch, or write anything.

Usage: python scripts/validate_no_synthetic_data.py data/candidates/<pack>.yaml
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date

import yaml

try:
    from mechanism_family import FAMILY_IDS as _CANON
    CANON_FAMILIES = set(_CANON)
except Exception:  # pragma: no cover - fallback to the documented canonical set
    CANON_FAMILIES = {
        "tariff", "sanction", "supply_shock", "ceasefire_deescalation", "policy_surprise",
        "fiscal_issuance", "labor_inflation", "bank_stress", "commodity_squeeze",
        "supply_normalization", "industrial_policy", "regulation", "external_balance", "none",
    }

REQUIRED = ("id", "event_date", "title", "source_url", "source_type", "category",
            "mechanism_family", "mechanism_summary", "affected_assets", "benchmark",
            "placebo_feasibility_guess", "limitation_or_falsifier", "review_status")
SOURCE_TYPES = {"official", "filing", "court", "regulator", "other_primary"}
PLACEBO_GUESSES = {"likely_good", "uncertain", "likely_poor"}
ROLES = {"beneficiary", "exposed"}

_SYNTHETIC = [re.compile(p, re.IGNORECASE) for p in (
    r"\bsynthetic\b", r"\[demo\]", r"\bdemo\b", r"\brehearsal\b", r"showcase", r"showcase_seed",
    r"\bplaceholder\b", r"lorem ipsum", r"\bfixture\b", r"\bfake\b", r"\btbd\b", r"\btodo\b", r"\bxxx\b",
)]
_PLACEHOLDER_URL = re.compile(r"example\.(com|org|net)|placeholder|your-url|url-here|<|\.\.\.|TODO", re.IGNORECASE)
_URL_RE = re.compile(r"^https?://[^\s]+\.[^\s]+$")


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_strings(v)


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if isinstance(data, dict) and "candidates" in data:
        return data["candidates"] or []
    if isinstance(data, list):
        return data
    return []


def validate_candidates(path: str) -> list[str]:
    problems: list[str] = []
    try:
        candidates = _load(path)
    except Exception as exc:
        return [f"could not parse YAML: {exc}"]
    if not candidates:
        return ["no candidates found in file"]

    today = date.today()
    for i, c in enumerate(candidates):
        cid = (c.get("id") if isinstance(c, dict) else None) or f"#{i}"
        if not isinstance(c, dict):
            problems.append(f"{cid}: not a mapping")
            continue
        for f in REQUIRED:
            v = c.get(f)
            if v is None or (isinstance(v, str) and not v.strip()) or (isinstance(v, list) and not v):
                problems.append(f"{cid}: missing/empty required field '{f}'")
        # anti-synthetic scan across all strings
        for s in _iter_strings(c):
            for rx in _SYNTHETIC:
                if rx.search(s):
                    problems.append(f"{cid}: synthetic/demo marker matched /{rx.pattern}/ in text")
                    break
        # source url
        url = c.get("source_url")
        if isinstance(url, str) and url.strip():
            if not _URL_RE.match(url.strip()) or _PLACEHOLDER_URL.search(url):
                problems.append(f"{cid}: source_url is not a real primary-source URL: {url!r}")
        # source type
        if c.get("source_type") not in SOURCE_TYPES:
            problems.append(f"{cid}: source_type must be one of {sorted(SOURCE_TYPES)}")
        # placebo guess
        if c.get("placebo_feasibility_guess") not in PLACEBO_GUESSES:
            problems.append(f"{cid}: placebo_feasibility_guess must be one of {sorted(PLACEBO_GUESSES)}")
        # review status
        if c.get("review_status") != "candidate_only_not_ingested":
            problems.append(f"{cid}: review_status must be 'candidate_only_not_ingested'")
        # canonical family
        if c.get("mechanism_family") not in CANON_FAMILIES:
            problems.append(f"{cid}: mechanism_family {c.get('mechanism_family')!r} is not canonical")
        # event date: ISO + not forward-looking
        ed = c.get("event_date")
        if isinstance(ed, date):
            ed = ed.isoformat()
        try:
            d = date.fromisoformat(str(ed)[:10])
            if d > today:
                problems.append(f"{cid}: event_date {ed} is forward-looking")
        except (ValueError, TypeError):
            problems.append(f"{cid}: event_date {ed!r} is not ISO YYYY-MM-DD")
        # affected assets + roles
        assets = c.get("affected_assets")
        if isinstance(assets, list) and assets:
            for a in assets:
                if not isinstance(a, dict) or not (a.get("ticker") or "").strip():
                    problems.append(f"{cid}: affected_asset missing ticker")
                elif a.get("role") not in ROLES:
                    problems.append(f"{cid}: affected_asset {a.get('ticker')} role must be beneficiary|exposed")
                elif not (a.get("rationale") or "").strip():
                    problems.append(f"{cid}: affected_asset {a.get('ticker')} missing rationale")
        else:
            problems.append(f"{cid}: affected_assets must be a non-empty list")
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print("usage: validate_no_synthetic_data.py <candidates.yaml>", file=sys.stderr)
        return 2
    path = argv[0]
    if not os.path.exists(path):
        print(f"file not found: {path}", file=sys.stderr)
        return 2
    problems = validate_candidates(path)
    if problems:
        print(f"FAIL: {len(problems)} problem(s) in {path}:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"OK: {path} passes structural + anti-synthetic validation (candidate-only, not ingested).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
