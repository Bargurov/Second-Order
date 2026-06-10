#!/usr/bin/env python3
"""Read-only event-study point-estimate coverage report.

The event-study engine (``stats.event_study.compute_event_study``, gated by
``event_study_validation.build_event_study_validation``) already computes
per-event abnormal-return / SAR / CAR point estimates and is exposed on a
backend-only single-event route (``GET /events/{id}/event-study``).  But no
surface shows what it produces ACROSS the archive, while the viewer-facing
validation still rests on raw 5-day-return direction tags.

This report closes that visibility gap.  It loops the gate over every
analysis-stage archived event (read-only) and reports:

  * a coverage summary — total events, event_study_available vs
    insufficient_data counts, the blocking-reason breakdown, and the
    auto_adjust basis split (matched vs cross-flag);
  * for each ready event — its per-horizon (1d/5d/20d) point estimates
    (``abnormal_return`` / ``sar`` / ``car``), primary ticker, benchmark,
    and estimation window used;
  * for each insufficient event — its blocking reasons (no point estimates).

It changes NO live validation surface — it makes the live-vs-engine gap
auditable before any viewer-facing rewire.

Curated-intake stubs (``db.NON_ANALYSIS_STAGES``) carry no thesis and are
excluded from the scored set — mirroring the readiness report's
denominator policy — and the excluded count is disclosed.

What this report explicitly does NOT do (see the ``non_claims`` block in
every payload)
--------------------------------------------------------------------------
* Point estimates only.  Confidence intervals, p-values, and BH-FDR are
  cross-sectional cohort statistics undefined at ``n = 1``; this report
  performs NO cross-sectional inference.
* No "confirmed" / "validated" / "significant" language for any event.
* Never reads, modifies, or reopens the closed Phase 1 / Phase 2 FDR
  pools (``evidence_artifacts`` / ``cohort_evidence`` are a separate scope).
* Provider provenance for the current live cache is ``legacy_unknown``
  unless separately reported (see
  ``scripts/price_provider_coverage_report.py``).

Out of scope (deliberately)
---------------------------
* Read-only.  Reaches price data only through the gate's plain ``SELECT``
  path; never INSERT / UPDATE / DELETE, never ``_ensure_table`` /
  ``init_db``.  No provider, no ``yfinance`` / ``market_check`` /
  ``market_data``, no LLM, no FastAPI surface, no network, no cache refresh.

Usage::

    python scripts/event_study_coverage_report.py
    python scripts/event_study_coverage_report.py --json
    python scripts/event_study_coverage_report.py --json --limit 20
    python scripts/event_study_coverage_report.py --db-path ./events.db --json
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

import db  # noqa: E402  - DB_FILE resolver + NON_ANALYSIS_STAGES
from event_study_validation import build_event_study_validation  # noqa: E402


_DEFAULT_LIMIT = 50

_NON_CLAIMS: dict[str, Any] = {
    "point_estimates_only": True,
    "no_confidence_interval_at_n1": True,
    "no_p_value_at_n1": True,
    "no_fdr_at_n1": True,
    "no_confirmed_or_validated_language": True,
    "does_not_touch_phase1_phase2_fdr_pools": True,
    "live_cache_provider_is_legacy_unknown_unless_separately_reported": True,
    "notes": (
        "Per-event point estimates (abnormal_return / sar / car) only. "
        "Confidence intervals, p-values, and BH-FDR are cross-sectional "
        "cohort statistics undefined at n=1; this report performs no "
        "cross-sectional inference and never reads, modifies, or reopens "
        "the closed Phase 1 / Phase 2 FDR pools. Price-provider provenance "
        "for the live cache is legacy_unknown unless separately reported."
    ),
}


# ---------------------------------------------------------------------------
# Empty shape
# ---------------------------------------------------------------------------


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":                  0,
        "event_study_available_count":   0,
        "insufficient_data_count":       0,
        "curated_intake_excluded_count": 0,
        "blocking_reasons":              {},
        "auto_adjust_basis":             {"matched": 0, "cross_flag": 0},
        "available":                     [],
        "insufficient":                  [],
        "non_claims":                    dict(_NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Read-only event load
# ---------------------------------------------------------------------------


def _load_events(path: str) -> tuple[list[dict[str, Any]], int]:
    """Return (analysis-stage event dicts, curated_intake_excluded_count).

    Pure read.  Excludes ``db.NON_ANALYSIS_STAGES`` (curated_intake stubs)
    so the scored denominator matches the readiness report.  Any DB error
    (missing file / table) degrades to an empty list.
    """
    try:
        # Read-only / no-create (matches data_hygiene_report.py): a missing
        # file raises sqlite3.Error here instead of creating a stray events.db.
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], 0
    synthetic: frozenset[int] = frozenset()
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, headline, event_date, market_tickers, stage "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], 0
        # AP3a synthetic-seed exclusion source — read on the SAME open
        # connection before it closes (degrade to empty if the table is absent).
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()

    non_analysis = getattr(db, "NON_ANALYSIS_STAGES", frozenset())
    events: list[dict[str, Any]] = []
    excluded = 0
    for r in rows:
        stage = r["stage"]
        # AP3a: synthetic_seed hygiene rows stay in the archive but are excluded
        # from the analysis/coverage denominator (kept distinct from the
        # NON_ANALYSIS stage stubs but counted in the same ``excluded`` tally).
        if (isinstance(stage, str) and stage in non_analysis) or r["id"] in synthetic:
            excluded += 1
            continue
        events.append({
            "id":             r["id"],
            "headline":       r["headline"],
            "event_date":     r["event_date"],
            "market_tickers": r["market_tickers"],
        })
    return events, excluded


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_event_study_coverage(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the event-study coverage report dict.

    Loops :func:`build_event_study_validation` over every analysis-stage
    event and aggregates the per-event payloads.  Aggregate counts always
    reflect the full archive; ``limit`` caps only the surfaced per-event
    lists (negative clamps to 0).

    The gate reads ``price_cache`` through ``db.connect_db()`` →
    ``db.DB_FILE``, so for the duration of the loop ``db.DB_FILE`` is
    pointed at the resolved path and restored afterwards.  This only
    changes which file read-only ``SELECT``s open — nothing is written.
    """
    capped = max(int(limit), 0)
    path = _resolve_db_path(db_path)
    if path is None:
        return _empty_report()

    events, excluded = _load_events(path)

    available: list[dict[str, Any]] = []
    insufficient: list[dict[str, Any]] = []
    reason_counts: dict[str, int] = {}
    basis_counts = {"matched": 0, "cross_flag": 0}

    original_db_file = db.DB_FILE
    try:
        # Point the gate's read-only price-cache reads at the same DB the
        # events were loaded from.  Restored in finally — no mutation.
        db.DB_FILE = path
        for ev in events:
            payload = build_event_study_validation(ev)
            if payload.get("status") == "event_study_available":
                basis = payload.get("auto_adjust_basis") or {}
                if basis.get("asset") == basis.get("benchmark"):
                    basis_counts["matched"] += 1
                else:
                    basis_counts["cross_flag"] += 1
                available.append({
                    "event_id":               ev.get("id"),
                    "headline":               ev.get("headline"),
                    "event_date":             ev.get("event_date"),
                    "primary_ticker":         payload.get("primary_ticker"),
                    "benchmark":              payload.get("benchmark"),
                    "estimation_window_used": payload.get("estimation_window_used"),
                    "per_horizon":            payload.get("per_horizon") or [],
                })
            else:
                reasons = payload.get("blocking_reasons") or []
                for r in reasons:
                    reason_counts[r] = reason_counts.get(r, 0) + 1
                insufficient.append({
                    "event_id":         ev.get("id"),
                    "headline":         ev.get("headline"),
                    "blocking_reasons": list(reasons),
                })
    finally:
        db.DB_FILE = original_db_file

    return {
        "total_events":                  len(events),
        "event_study_available_count":   len(available),
        "insufficient_data_count":       len(insufficient),
        "curated_intake_excluded_count": excluded,
        "blocking_reasons":              reason_counts,
        "auto_adjust_basis":             basis_counts,
        "available":                     available[:capped],
        "insufficient":                  insufficient[:capped],
        "non_claims":                    dict(_NON_CLAIMS),
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    return getattr(db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:+.4f}"
    return "-" if value is None else str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Event-study point-estimate coverage", ""]
    lines.append(f"Total events (analysis-stage): {report['total_events']}")
    lines.append(f"  event_study_available:       {report['event_study_available_count']}")
    lines.append(f"  insufficient_data:           {report['insufficient_data_count']}")
    lines.append(f"  curated_intake_excluded:     {report['curated_intake_excluded_count']}")
    basis = report.get("auto_adjust_basis") or {}
    lines.append(
        f"  auto_adjust basis:           matched={basis.get('matched', 0)} "
        f"cross_flag={basis.get('cross_flag', 0)}"
    )
    lines.append("")

    reasons = report.get("blocking_reasons") or {}
    lines.append("Top blocking reasons:")
    if reasons:
        for name, count in sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0])):
            lines.append(f"  {count:>4}  {name}")
    else:
        lines.append("  (none)")
    lines.append("")

    available = report.get("available") or []
    lines.append(f"Ready events listed ({len(available)}):")
    if available:
        for e in available:
            lines.append(
                f"  #{e.get('event_id')} {e.get('primary_ticker') or '-'} "
                f"vs {e.get('benchmark') or '-'} "
                f"(est_win={e.get('estimation_window_used')}) "
                f"- {(e.get('headline') or '')[:60]}"
            )
            for h in e.get("per_horizon") or []:
                lines.append(
                    f"       {h.get('horizon')}d: "
                    f"AR={_fmt(h.get('abnormal_return'))} "
                    f"SAR={_fmt(h.get('sar'))} "
                    f"CAR={_fmt(h.get('car'))}"
                )
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append(
        "Caveat: point estimates only - no CI / p-value / FDR at n=1; no "
        "cross-sectional inference; closed Phase 1/2 FDR pools untouched."
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only event-study point-estimate coverage report.  Loops "
            "event_study_validation.build_event_study_validation over the "
            "archive and surfaces per-event abnormal_return / sar / car.  "
            "No cross-sectional inference; never touches the closed FDR "
            "pools; no provider/network call; no DB mutation."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-event lists at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect every "
            f"event."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's configured "
            "archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_event_study_coverage(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
