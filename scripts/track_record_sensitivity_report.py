#!/usr/bin/env python3
"""Read-only track-record scoring-rule sensitivity report.

The canonical track-record rule (`db.compute_track_record`) is a generous
ANY-support OR-rule. This report recomputes the SAME accepted track-record
event set under several transparent rules side-by-side so a reader can see how
sensitive the validated / contradicted / unresolved breakdown is to that
generosity. It is **disclosure, not a truth claim**: no rule is asserted
"correct", the canonical headline rule is unchanged, and every rule shares one
denominator (the accepted track-record set, excluding ``db.NON_THESIS_STAGES``
and ``event_hygiene`` synthetic_seed rows — the same denominator
`db.compute_track_record` uses).

Source selection per event is taken VERBATIM from the canonical scorer: the
longest-horizon revisit snapshot when it carries directional tags, otherwise
``market_tickers``. Classification then runs through the tested pure rules in
`stats.track_record_scoring`, so the ``any_support`` column matches the
canonical breakdown exactly.

Read-only: a single ``mode=ro`` connection, plain ``SELECT``s only. No INSERT /
UPDATE / DELETE, no ``init_db``, no provider, no network, no LLM, no FastAPI
surface, no event-study math. The closed Phase 1 / Phase 2 FDR pools are never
read or implied.

Usage::

    python scripts/track_record_sensitivity_report.py
    python scripts/track_record_sensitivity_report.py --json
    python scripts/track_record_sensitivity_report.py --json --limit 20
    python scripts/track_record_sensitivity_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - NON_THESIS_STAGES, synthetic_seed_ids, source-selection helpers
from stats.track_record_scoring import RULES, summarize_rules  # noqa: E402

_DEFAULT_LIMIT = 25
_SYNTHETIC_SEED_OVERRIDE = "synthetic_seed"


def _select_source_tickers(raw_market: Any, raw_revisit: Any) -> list:
    """Pick the directional ticker list canonically: best revisit snapshot when
    it carries directional tags, else market_tickers. Verbatim mirror of
    ``db.compute_track_record`` source preference."""
    try:
        revisit = json.loads(raw_revisit or "[]")
    except (json.JSONDecodeError, TypeError):
        revisit = []
    best = db._best_revisit_snapshot(revisit if isinstance(revisit, list) else [])
    if best:
        _has_sup, _has_con, _sup, dir_cnt = db._score_directions(best)
        if dir_cnt > 0:
            return best
    try:
        tickers = json.loads(raw_market or "[]")
    except (json.JSONDecodeError, TypeError):
        tickers = []
    return tickers if isinstance(tickers, list) else []


def _load_accepted_records(path: str) -> tuple[list[dict], dict]:
    """Return (accepted event records, denominator metadata). Read-only."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], _empty_denominator()
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, headline, mechanism_family, market_tickers, "
                "revisit_snapshots, stage FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            try:
                rows = conn.execute(
                    "SELECT id, headline, mechanism_family, market_tickers, stage "
                    "FROM events ORDER BY id"
                ).fetchall()
                rows = [
                    {"id": r["id"], "headline": r["headline"],
                     "mechanism_family": r["mechanism_family"],
                     "market_tickers": r["market_tickers"],
                     "revisit_snapshots": None, "stage": r["stage"]}
                    for r in rows
                ]
            except sqlite3.Error:
                return [], _empty_denominator()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()

    non_thesis = getattr(db, "NON_THESIS_STAGES", frozenset())
    records: list[dict] = []
    archive_rows = 0
    stage_excluded = 0
    synthetic_excluded = 0
    for r in rows:
        archive_rows += 1
        stage = r["stage"] if isinstance(r["stage"], str) else None
        if stage is not None and stage in non_thesis:
            stage_excluded += 1
            continue
        if r["id"] in synthetic:
            synthetic_excluded += 1
            continue
        records.append({
            "event_id": r["id"],
            "headline": r["headline"],
            "mechanism_family": r["mechanism_family"],
            "tickers": _select_source_tickers(
                r["market_tickers"], r["revisit_snapshots"],
            ),
        })

    denom_meta = {
        "accepted_track_record_events": len(records),
        "archive_rows": archive_rows,
        "excluded_stages": sorted(non_thesis),
        "excluded_override_classes": [_SYNTHETIC_SEED_OVERRIDE],
        "non_thesis_stage_excluded": stage_excluded,
        "synthetic_seed_excluded": synthetic_excluded,
    }
    return records, denom_meta


def _empty_denominator() -> dict:
    return {
        "accepted_track_record_events": 0,
        "archive_rows": 0,
        "excluded_stages": sorted(getattr(db, "NON_THESIS_STAGES", frozenset())),
        "excluded_override_classes": [_SYNTHETIC_SEED_OVERRIDE],
        "non_thesis_stage_excluded": 0,
        "synthetic_seed_excluded": 0,
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    return getattr(db, "DB_FILE", None)


def build_report(*, db_path: str | None = None, limit: int = _DEFAULT_LIMIT) -> dict:
    """Build the sensitivity report dict. Read-only."""
    capped = max(int(limit), 0)
    path = _resolve_db_path(db_path)
    if path is None:
        return {
            "denominator": _empty_denominator(),
            "scoring": summarize_rules([]),
        }
    records, denom_meta = _load_accepted_records(path)
    scoring = summarize_rules(records)
    # The summarize denominator and the accepted-event count are the same set.
    out = {
        "denominator": denom_meta,
        "scoring": {**scoring, "disagreements": scoring["disagreements"][:capped]},
        "disagreements_total": len(scoring["disagreements"]),
    }
    return out


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict) -> str:
    denom = report.get("denominator") or {}
    scoring = report.get("scoring") or {}
    rules = scoring.get("rules") or {}
    n = scoring.get("denominator", 0)
    lines = ["Track-record scoring-rule sensitivity (read-only)", ""]
    lines.append(
        f"Accepted track-record denominator: {n} "
        f"(of {denom.get('archive_rows', 0)} archive rows; "
        f"{denom.get('non_thesis_stage_excluded', 0)} non-thesis-stage + "
        f"{denom.get('synthetic_seed_excluded', 0)} synthetic_seed excluded)"
    )
    lines.append(f"Canonical headline rule: {scoring.get('canonical_rule')} (unchanged)")
    lines.append("")
    lines.append("Rule                | validated | contradicted | unresolved | changed vs any_support")
    for rule in RULES:
        r = rules.get(rule) or {}
        suffix = ""
        if rule == "evidence_weighted" and "changed_vs_majority" in r:
            suffix = f"  [vs majority: {r['changed_vs_majority']} changed]"
        lines.append(
            f"  {rule:<18}| {r.get('validated', 0):>9} | {r.get('contradicted', 0):>12} "
            f"| {r.get('unresolved', 0):>10} | {r.get('changed_vs_any_support', 0):>4}{suffix}"
        )
    comp = scoring.get("composition") or {}
    lines.append("")
    lines.append(
        f"Event composition: single-ticker {comp.get('single_ticker', 0)} | "
        f"multi-ticker {comp.get('multi_ticker', 0)} | "
        f"mixed-evidence {comp.get('mixed_evidence', 0)} | "
        f"no-direction {comp.get('no_direction', 0)}"
    )
    lines.append("")
    dis = scoring.get("disagreements") or []
    lines.append(f"Events where a stricter rule disagrees with any_support "
                 f"(showing {len(dis)} of {report.get('disagreements_total', len(dis))}):")
    if dis:
        for d in dis:
            oc = d.get("outcomes") or {}
            lines.append(
                f"  #{d.get('event_id')} [{d.get('mechanism_family') or '-'}] "
                f"sup={d.get('sup_n')} con={d.get('con_n')} "
                f"(w {d.get('sup_w')}/{d.get('con_w')}): "
                f"any={oc.get('any_support')} maj={oc.get('majority')} "
                f"wtd={oc.get('evidence_weighted')} strict={oc.get('all_support_strict')}"
            )
            lines.append(f"      {(d.get('headline') or '')[:72]}")
    else:
        lines.append("  (no disagreements)")
    lines.append("")
    lines.append(f"Evidence-weight note: {scoring.get('evidence_weight_fallback', '')}")
    lines.append("Non-claims:")
    for nc in scoring.get("non_claims") or []:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only track-record scoring-rule sensitivity report. Recomputes "
            "the accepted track-record outcomes under any_support / majority / "
            "evidence_weighted / all_support_strict over one shared denominator. "
            "Disclosure only; no rule is claimed correct; no DB write, no "
            "provider call."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                   help=f"Cap surfaced disagreement examples (default {_DEFAULT_LIMIT}).")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = build_report(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
