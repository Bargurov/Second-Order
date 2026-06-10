#!/usr/bin/env python3
"""Read-only research queue report for staged candidates (AT1).

Surfaces, for every ``stage='z1a_candidate_pack'`` staged candidate, the
information a HUMAN reviewer needs to decide what (if anything) to do
next — WITHOUT making any paid call:

  * event-study readiness on the staged primary ticker, via the same
    read-only gate the live route uses
    (``event_study_validation.build_event_study_validation``);
  * per-horizon (1d / 5d / 20d) abnormal-return / SAR / CAR point
    estimates where already computable from the cache (fractions, n=1);
  * source provenance (``event_provenance``: source_type, source_url,
    intake_path);
  * near-duplicate collisions against the non-candidate, non-synthetic
    corpus, reusing the deterministic signals from
    ``scripts/z1b_candidate_collision_report.py`` (a staged row never
    collides with itself, another staged row, or a synthetic seed);
  * one deterministic classification per candidate.

Classification (deterministic precedence, first match wins)
------------------------------------------------------------
1. ``defer_near_duplicate``     — any collision signal fired; review the
   existing event first.
2. ``data_limited``             — the event-study gate cannot compute on
   the staged primary ticker (blocking reasons listed).
3. ``defer_low_identification`` — computable, but the 1d abnormal return
   is unavailable, so there is no immediate-window identification.
4. ``needs_manual_review``      — computable, but provenance is missing,
   a longer horizon is unavailable, or the auto_adjust basis is
   cross-flag.
5. ``ready_for_no_paid_review`` — computable on all three horizons with
   matched basis, sourced, and collision-free: ready for a human
   no-paid review.

The classification orders HUMAN review only.  It is not a trade
recommendation, not a prediction, and not a significance claim (every
payload carries an explicit ``non_claims`` block).  Staged candidates
are excluded from every accepted-corpus denominator; nothing here
changes that.  Paid ``/analyze`` stays blocked unless the operator
explicitly approves a later run.

Out of scope (deliberately)
---------------------------
* Read-only.  The DB is opened ``mode=ro`` (no-create); only ``SELECT``
  statements are issued.  No provider, no ``yfinance`` / ``market_check``
  / ``market_data``, no LLM, no FastAPI surface, no network.
* No promotion, no staging change, no dedup action — it only reports.

Usage::

    python scripts/research_queue_report.py
    python scripts/research_queue_report.py --json
    python scripts/research_queue_report.py --db-path ./events.db --json
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

import db  # noqa: E402  — DB_FILE resolver, stage constants, synthetic_seed_ids
from event_study_validation import (  # noqa: E402
    STATUS_AVAILABLE,
    build_event_study_validation,
)
from scripts.z1b_candidate_collision_report import (  # noqa: E402
    DEFAULT_DATE_WINDOW_DAYS,
    DEFAULT_HEADLINE_THRESHOLD,
    _event_tickers,
    _headline_ratio,
    _parse_date,
)

# Classification labels — deterministic queue triage, never advice.
CLASS_READY = "ready_for_no_paid_review"
CLASS_MANUAL = "needs_manual_review"
CLASS_DUP = "defer_near_duplicate"
CLASS_LOW_ID = "defer_low_identification"
CLASS_DATA_LIMITED = "data_limited"

CLASSIFICATIONS: tuple[str, ...] = (
    CLASS_READY, CLASS_MANUAL, CLASS_DUP, CLASS_LOW_ID, CLASS_DATA_LIMITED,
)

_QUEUE_STAGE = db.CANDIDATE_PACK_STAGE  # "z1a_candidate_pack"

_CORPUS_NOTE = (
    "Staged candidates are excluded from every accepted-corpus denominator "
    "(db.NON_ANALYSIS_STAGES); this queue is review staging, not evidence."
)

_NON_CLAIMS: dict[str, Any] = {
    "not_a_trade_recommendation": True,
    "not_a_prediction": True,
    "no_statistical_significance_claim": True,
    "paid_analysis_remains_blocked": True,
    "notes": (
        "Read-only queue triage to order HUMAN review only. Point "
        "estimates are descriptive single-event values (n=1: no CI, no "
        "p-value, no FDR). Nothing here is advice to transact, a "
        "prediction, or a significance claim. Paid /analyze stays blocked "
        "unless the operator explicitly approves a later, separate run."
    ),
}


# ---------------------------------------------------------------------------
# Pure classifier
# ---------------------------------------------------------------------------


def classify_candidate(
    *,
    status: str,
    per_horizon: Sequence[dict],
    collisions: Sequence[dict],
    has_provenance: bool,
    basis_matched: bool,
) -> str:
    """Return the single deterministic classification for one candidate.

    Precedence is fixed (see module docstring): near-duplicate beats
    everything (a duplicate must be reviewed as a duplicate regardless of
    coverage), then data availability, then identification, then the
    manual-attention flags.
    """
    if collisions:
        return CLASS_DUP
    if status != STATUS_AVAILABLE:
        return CLASS_DATA_LIMITED
    ar_by_horizon: dict[int, Any] = {}
    for entry in per_horizon or []:
        if isinstance(entry, dict):
            try:
                ar_by_horizon[int(entry.get("horizon"))] = entry.get(
                    "abnormal_return"
                )
            except (TypeError, ValueError):
                continue
    if ar_by_horizon.get(1) is None:
        return CLASS_LOW_ID
    if (
        not has_provenance
        or not basis_matched
        or any(ar_by_horizon.get(h) is None for h in (5, 20))
    ):
        return CLASS_MANUAL
    return CLASS_READY


# ---------------------------------------------------------------------------
# Read-only loads
# ---------------------------------------------------------------------------


def _load_queue_inputs(
    path: str,
) -> tuple[list[dict], list[dict], dict[int, dict]]:
    """Return (staged candidates, collision corpus, provenance by id).

    Pure read (``mode=ro``, no-create).  The collision corpus is every
    non-candidate event that is not a synthetic seed — a staged row must
    never collide with itself, another staged row, or a seed.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], [], {}
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, headline, event_date, market_tickers, stage "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], [], {}
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
        provenance: dict[int, dict] = {}
        try:
            for p in conn.execute(
                "SELECT event_id, source_type, source_url, intake_path "
                "FROM event_provenance"
            ):
                provenance[int(p["event_id"])] = {
                    "source_type": p["source_type"],
                    "source_url":  p["source_url"],
                    "intake_path": p["intake_path"],
                }
        except sqlite3.Error:
            provenance = {}
    finally:
        conn.close()

    staged: list[dict] = []
    corpus: list[dict] = []
    for r in rows:
        entry = {
            "id":             int(r["id"]),
            "headline":       r["headline"] or "",
            "event_date":     r["event_date"],
            "date":           _parse_date(r["event_date"]),
            "tickers":        _event_tickers(r["market_tickers"]),
            "market_tickers": r["market_tickers"],
            "stage":          r["stage"],
        }
        if r["stage"] == _QUEUE_STAGE:
            staged.append(entry)
        elif entry["id"] not in synthetic:
            corpus.append(entry)
    return staged, corpus, provenance


def _detect_collisions(
    candidate: dict,
    corpus: Sequence[dict],
    provenance: dict[int, dict],
) -> list[dict]:
    """Collision signals for one staged candidate vs the corpus.

    Mirrors ``z1b_candidate_collision_report.detect_collisions`` (same
    three deterministic signals and thresholds) but compares an archived
    staged ROW — headline / event_date / market_tickers from ``events``
    plus its ``event_provenance`` source_url — instead of a YAML pack
    entry, and only against the non-candidate, non-synthetic corpus.
    """
    own = provenance.get(candidate["id"]) or {}
    c_url = (own.get("source_url") or "").strip()
    c_date = candidate.get("date")
    c_tickers = candidate.get("tickers") or set()
    c_title = (candidate.get("headline") or "").strip()

    collisions: list[dict] = []
    for e in corpus:
        reasons: list[str] = []
        e_url = ((provenance.get(e["id"]) or {}).get("source_url") or "").strip()
        if c_url and e_url and c_url == e_url:
            reasons.append("source_url_exact")
        if (
            c_date is not None
            and e["date"] is not None
            and (c_tickers & e["tickers"])
            and abs((c_date - e["date"]).days) <= DEFAULT_DATE_WINDOW_DAYS
        ):
            reasons.append("date_window_ticker")
        if (
            c_title
            and e["headline"]
            and _headline_ratio(c_title, e["headline"])
            >= DEFAULT_HEADLINE_THRESHOLD
        ):
            reasons.append("headline_similarity")
        if reasons:
            collisions.append({
                "event_id":       e["id"],
                "event_stage":    e["stage"],
                "event_headline": e["headline"],
                "event_date":     e["event_date"],
                "reasons":        reasons,
            })
    return collisions


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_research_queue(*, db_path: str | None = None) -> dict[str, Any]:
    """Return the research-queue report dict (see module docstring)."""
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    empty = {
        "queue_stage":             _QUEUE_STAGE,
        "total_staged_candidates": 0,
        "classification_counts":   {c: 0 for c in CLASSIFICATIONS},
        "candidates":              [],
        "corpus_note":             _CORPUS_NOTE,
        "non_claims":              dict(_NON_CLAIMS),
    }
    if path is None:
        return empty

    staged, corpus, provenance = _load_queue_inputs(str(path))
    if not staged:
        return empty

    counts = {c: 0 for c in CLASSIFICATIONS}
    candidates: list[dict] = []

    # The gate reads price_cache through ``db.DB_FILE``; point it at the
    # same archive for the loop, then restore.  Read-only either way.
    saved_db_file = db.DB_FILE
    try:
        db.DB_FILE = str(path)
        for c in staged:
            payload = build_event_study_validation({
                "id":             c["id"],
                "headline":       c["headline"],
                "event_date":     c["event_date"],
                "market_tickers": c["market_tickers"],
            })
            status = payload.get("status") or ""
            per_horizon = payload.get("per_horizon") or []
            basis = payload.get("auto_adjust_basis") or {}
            basis_matched = (
                basis.get("asset") == basis.get("benchmark")
                if status == STATUS_AVAILABLE else None
            )
            prov = provenance.get(c["id"])
            collisions = _detect_collisions(c, corpus, provenance)
            classification = classify_candidate(
                status=status,
                per_horizon=per_horizon,
                collisions=collisions,
                has_provenance=bool(prov and (prov.get("source_url") or "").strip()),
                basis_matched=bool(basis_matched),
            )
            counts[classification] += 1
            candidates.append({
                "event_id":                  c["id"],
                "headline":                  c["headline"],
                "event_date":                c["event_date"],
                "primary_ticker":            payload.get("primary_ticker"),
                "event_study_status":        status,
                "per_horizon":               per_horizon,
                "blocking_reasons":          payload.get("blocking_reasons") or [],
                "auto_adjust_basis_matched": basis_matched,
                "provenance":                prov,
                "collisions":                collisions,
                "classification":            classification,
            })
    finally:
        db.DB_FILE = saved_db_file

    return {
        "queue_stage":             _QUEUE_STAGE,
        "total_staged_candidates": len(candidates),
        "classification_counts":   counts,
        "candidates":              candidates,
        "corpus_note":             _CORPUS_NOTE,
        "non_claims":              dict(_NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:+.4f}"
    return "-" if value is None else str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = [
        f"Research queue report - staged candidates ({report['queue_stage']})",
        "",
        f"Total staged candidates: {report['total_staged_candidates']}",
    ]
    counts = report.get("classification_counts") or {}
    for cls in CLASSIFICATIONS:
        lines.append(f"  {cls}: {counts.get(cls, 0)}")
    lines.append("")
    for c in report.get("candidates") or []:
        lines.append(
            f"#{c['event_id']} [{c['classification']}] "
            f"{c.get('primary_ticker') or '-'} - "
            f"{(c.get('headline') or '')[:70]}"
        )
        for h in c.get("per_horizon") or []:
            lines.append(
                f"    {h.get('horizon')}d: AR={_fmt(h.get('abnormal_return'))} "
                f"SAR={_fmt(h.get('sar'))} CAR={_fmt(h.get('car'))}"
            )
        for col in c.get("collisions") or []:
            lines.append(
                f"    collision ~ event {col['event_id']} "
                f"({col.get('event_stage')}) [{', '.join(col['reasons'])}]"
            )
        if c.get("blocking_reasons"):
            lines.append(
                f"    blocking: {', '.join(c['blocking_reasons'])}"
            )
    lines.append("")
    lines.append(report["corpus_note"])
    lines.append(
        "Non-claims: not a trade recommendation, not a prediction, no "
        "significance claim (n=1 point estimates); paid /analyze remains "
        "blocked unless explicitly approved later."
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
            "Read-only research queue report over staged "
            "z1a_candidate_pack candidates: event-study readiness, cached "
            "per-horizon point estimates, provenance, near-duplicate "
            "collisions, and a deterministic review classification.  No "
            "paid call, no provider, no DB write; staged candidates stay "
            "outside every accepted-corpus denominator."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
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

    report = summarize_research_queue(db_path=args.db_path)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
