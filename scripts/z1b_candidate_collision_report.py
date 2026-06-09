#!/usr/bin/env python3
"""Z1B / Z1D — read-only candidate ↔ existing-event collision report.

Source-URL idempotency (the Z1B copy-ingest dedup) cannot catch a candidate that
duplicates an existing event under a DIFFERENT URL, a nearby (not exact) date, or
a reworded headline.  This module flags probable duplicates by three
deterministic signals so a promotion can refuse / warn before re-ingesting:

  * ``source_url_exact``      — candidate ``source_url`` == an existing
    ``event_provenance.source_url``
  * ``date_window_ticker``    — |Δ event_date| ≤ window AND a ticker in common
    (a candidate ``affected_assets[].ticker`` is a primary/affected symbol on
    the existing event's ``market_tickers``)
  * ``headline_similarity``   — candidate ``title`` vs existing ``headline``
    difflib ratio ≥ threshold

Pinned reference case (see ``tests/test_z1b_candidate_collision_report.py``):
the Z1A steel candidate vs the K14 live observation (event 296) — same
federalregister ``source_url`` and NUE, but event_dates 7 days apart, so an
EXACT date+ticker check would miss it.

Read-only: the DB is opened ``mode=ro``; this module never writes, never calls a
provider, and NEVER auto-deletes or auto-merges — it only reports.  A non-zero
CLI exit on collisions is the "refuse" signal a promotion wrapper can gate on.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from difflib import SequenceMatcher
from typing import Any, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

DEFAULT_DATE_WINDOW_DAYS = 14
DEFAULT_HEADLINE_THRESHOLD = 0.6

NON_CLAIM = (
    "Read-only duplicate-collision report; flags PROBABLE duplicates only and "
    "never auto-deletes or auto-merges. A flag is a prompt for human review, "
    "not a verdict."
)


def _parse_date(value: Any) -> Optional[date]:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except (ValueError, TypeError):
        return None


def _candidate_tickers(candidate: dict) -> set[str]:
    out: set[str] = set()
    for a in candidate.get("affected_assets") or []:
        if isinstance(a, dict):
            sym = (a.get("ticker") or "").strip().upper()
            if sym:
                out.add(sym)
    return out


def _event_tickers(market_tickers_json: Any) -> set[str]:
    if not market_tickers_json:
        return set()
    try:
        rows = json.loads(market_tickers_json) if isinstance(market_tickers_json, str) else market_tickers_json
    except (ValueError, TypeError):
        return set()
    out: set[str] = set()
    for t in rows or []:
        if isinstance(t, dict):
            sym = (t.get("symbol") or "").strip().upper()
            if sym:
                out.add(sym)
    return out


def _headline_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def _candidate_title(candidate: dict) -> str:
    return (candidate.get("title") or candidate.get("headline") or "").strip()


def _load_existing_events(db_path: str) -> list[dict]:
    """Read-only load of (id, headline, event_date, tickers, source_urls)."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        urls_by_event: dict[int, set[str]] = {}
        try:
            for eid, url in con.execute(
                "SELECT event_id, source_url FROM event_provenance "
                "WHERE source_url IS NOT NULL AND TRIM(source_url) != ''"
            ):
                if eid is not None and url:
                    urls_by_event.setdefault(int(eid), set()).add(url.strip())
        except sqlite3.Error:
            urls_by_event = {}

        events: list[dict] = []
        for eid, headline, event_date, market_tickers in con.execute(
            "SELECT id, headline, event_date, market_tickers FROM events"
        ):
            events.append({
                "id": int(eid),
                "headline": headline or "",
                "event_date": event_date,
                "date": _parse_date(event_date),
                "tickers": _event_tickers(market_tickers),
                "source_urls": urls_by_event.get(int(eid), set()),
            })
        return events
    except sqlite3.Error:
        return []
    finally:
        con.close()


def detect_collisions(
    candidates: list[dict],
    db_path: str,
    *,
    date_window_days: int = DEFAULT_DATE_WINDOW_DAYS,
    headline_threshold: float = DEFAULT_HEADLINE_THRESHOLD,
) -> dict:
    """Return a structured collision report for ``candidates`` vs ``db_path``.

    Shape::

        {
          "has_collisions": bool,
          "candidates": [{"id", "source_url", "event_date",
                          "collisions": [{"event_id", "event_headline",
                                          "event_date", "reasons": [...]}]}],
          "summary": {"n_candidates", "n_with_collisions"},
          "non_claim": str,
        }
    """
    existing = _load_existing_events(db_path)
    out_candidates: list[dict] = []
    for c in candidates:
        c_url = (c.get("source_url") or "").strip()
        c_date = _parse_date(c.get("event_date"))
        c_tickers = _candidate_tickers(c)
        c_title = _candidate_title(c)

        collisions: list[dict] = []
        for e in existing:
            reasons: list[str] = []
            if c_url and c_url in e["source_urls"]:
                reasons.append("source_url_exact")
            if (
                c_date is not None
                and e["date"] is not None
                and (c_tickers & e["tickers"])
                and abs((c_date - e["date"]).days) <= date_window_days
            ):
                reasons.append("date_window_ticker")
            if (
                c_title
                and e["headline"]
                and _headline_ratio(c_title, e["headline"]) >= headline_threshold
            ):
                reasons.append("headline_similarity")
            if reasons:
                collisions.append({
                    "event_id": e["id"],
                    "event_headline": e["headline"],
                    "event_date": e["event_date"],
                    "reasons": reasons,
                })
        out_candidates.append({
            "id": c.get("id"),
            "source_url": c_url,
            "event_date": c.get("event_date"),
            "collisions": collisions,
        })

    n_with = sum(1 for c in out_candidates if c["collisions"])
    return {
        "has_collisions": n_with > 0,
        "candidates": out_candidates,
        "summary": {"n_candidates": len(out_candidates), "n_with_collisions": n_with},
        "non_claim": NON_CLAIM,
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Read-only candidate <-> existing-event collision report.",
    )
    ap.add_argument("--candidates", required=True, help="Z1A candidate-pack YAML.")
    ap.add_argument(
        "--db-path", required=True,
        help="DB to check against (a copy, or live opened read-only).",
    )
    ap.add_argument("--date-window-days", type=int, default=DEFAULT_DATE_WINDOW_DAYS)
    ap.add_argument("--headline-threshold", type=float, default=DEFAULT_HEADLINE_THRESHOLD)
    ap.add_argument("--json", action="store_true", help="Emit the full JSON report.")
    args = ap.parse_args(argv)

    from scripts.z1b_candidate_pack_copy_ingest import _load_candidates
    candidates = _load_candidates(args.candidates)
    report = detect_collisions(
        candidates, args.db_path,
        date_window_days=args.date_window_days,
        headline_threshold=args.headline_threshold,
    )

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        s = report["summary"]
        print(
            f"[z1b-collision] {s['n_with_collisions']}/{s['n_candidates']} "
            f"candidate(s) collide with an existing event."
        )
        for c in report["candidates"]:
            for col in c["collisions"]:
                print(
                    f"  COLLISION {c['id']} ~ event {col['event_id']} "
                    f"[{', '.join(col['reasons'])}]: {(col['event_headline'] or '')[:80]}"
                )
        print(NON_CLAIM)

    # Non-zero exit on collisions = the "refuse" signal for a promotion gate.
    return 1 if report["has_collisions"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
