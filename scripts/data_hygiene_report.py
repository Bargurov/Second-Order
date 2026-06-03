#!/usr/bin/env python3
"""Read-only archive data-hygiene report (H6).

The live archive's ``events`` table mixes three populations: genuine ingested
research events, deliberately seeded/demo headlines run through the real
analysis pipeline, and literal test artifacts.  The H5/C audit found that of
157 analysis-stage rows, **71 are synthetic/seed/test** and a further **15 are
redundant copies of real headlines** — so an honest coverage ratio must name
which denominator it uses.

This report makes that classification auditable in one place.  It loops over
every analysis-stage archived event (read-only — plain ``SELECT``s, no
provider, no network, no DB write) and classifies each row into:

  * ``synthetic_seed``   — an exact seeded/demo headline (e.g. "OPEC slashes
    output by 2 mbpd") run through the real model;
  * ``synthetic_test``   — a literal test artifact ("Macro shock test event",
    "Test headline", or the ``test-model`` model fingerprint);
  * ``real_duplicate``   — a genuine headline that appears more than once;
  * ``real_unique``      — a genuine headline appearing exactly once.

Classification keys on the **exact headline** plus the ``model`` fingerprint,
NEVER on lack of a ticker — a real macro headline with no defensible public
ticker is still a real event.  The seed-string assumption: the eight repeated
seed/test strings are treated as synthetic on the combined evidence of the
exact headline, the repeated consecutive-date pattern, and the uniform model
fingerprint visible in each ``synthetic_groups`` entry.  The real recurring
"AP News: OPEC members discuss extending output cuts" is deliberately NOT
collided with the seed "OPEC slashes output by 2 mbpd".

It emits four honest denominators (archive/raw, analysis-stage denominator of
record, real rows, distinct real events) and the three coverage ratios that
follow from them.

What this report explicitly does NOT do (see the ``non_claims`` block)
----------------------------------------------------------------------
* Never reads, modifies, or reopens the closed Phase 1 / Phase 2 FDR pools
  (``demo_artifacts`` / ``cohort_evidence`` are a separate scope).
* Never deletes, edits, or mutates any row — read-only.
* The classification is a documented heuristic, surfaced per-group so a
  reviewer can audit it; it is not a stored label.
* The 157 analysis-stage count stays the disclosed denominator of record; the
  research denominators are reported alongside it, never instead of it.

Usage::

    python scripts/data_hygiene_report.py
    python scripts/data_hygiene_report.py --json
    python scripts/data_hygiene_report.py --json --limit 20
    python scripts/data_hygiene_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402  - DB_FILE resolver + NON_ANALYSIS_STAGES
from event_study_validation import build_event_study_validation  # noqa: E402


_DEFAULT_LIMIT = 50

# ---------------------------------------------------------------------------
# Classification vocabulary (single source of truth)
# ---------------------------------------------------------------------------
# Seeded/demo headlines: real-pipeline fixtures repeated across consecutive
# dates.  Listed as EXACT strings so the genuine recurring news headline
# "AP News: OPEC members discuss extending output cuts" never collides with
# the seed "OPEC slashes output by 2 mbpd".
SEED_HEADLINES: frozenset[str] = frozenset({
    "OPEC slashes output by 2 mbpd",
    "Tech CEO steps down",
    "Turkey lira weakens",
    "Turkey lira weakens as reserves slip further",
    "Fed speakers rotate",
    "Fed speakers rotate on inflation commentary",
})
# Literal test artifacts whose presence in the live archive is a hygiene bug,
# not a research seed.
TEST_HEADLINES: frozenset[str] = frozenset({
    "Macro shock test event",
    "Test headline",
})
# Model fingerprint stamped on a hand-inserted test row.
TEST_MODEL: str = "test-model"

CATEGORY_SYNTHETIC_SEED = "synthetic_seed"
CATEGORY_SYNTHETIC_TEST = "synthetic_test"
CATEGORY_REAL_DUPLICATE = "real_duplicate"
CATEGORY_REAL_UNIQUE = "real_unique"
_SYNTHETIC_CATEGORIES = frozenset({CATEGORY_SYNTHETIC_SEED, CATEGORY_SYNTHETIC_TEST})


_NON_CLAIMS: dict[str, Any] = {
    "does_not_touch_phase1_phase2_fdr_pools": True,
    "does_not_delete_or_mutate_rows": True,
    "classification_is_heuristic_and_auditable": True,
    "denominator_of_record_remains_157": True,
    "notes": (
        "Wider-archive event-study hygiene only. Synthetic/test rows are "
        "classified by exact seed headline + test-model fingerprint (corroborated "
        "by the repeated consecutive-date pattern shown per group), never by lack "
        "of ticker. The report reads the archive read-only, deletes/edits nothing, "
        "and never reads, modifies, or reopens the closed Phase 1 / Phase 2 FDR "
        "pools. The 157 analysis-stage count remains the disclosed denominator of "
        "record; the real-row and distinct-real-event denominators are reported "
        "alongside it, not instead of it."
    ),
}


# ---------------------------------------------------------------------------
# Pure classifier
# ---------------------------------------------------------------------------


def classify_synthetic(headline: Any, model: Any) -> Optional[str]:
    """Classify a single row as synthetic by headline / model — or ``None``.

    Pure and per-row: returns ``"synthetic_test"`` for a literal test artifact
    (a ``TEST_HEADLINES`` headline or the ``test-model`` fingerprint),
    ``"synthetic_seed"`` for a seeded/demo headline, else ``None`` (a real
    row).  Ticker data is intentionally never consulted.
    """
    h = (headline or "").strip()
    m = (model or "").strip()
    if h in TEST_HEADLINES or m == TEST_MODEL:
        return CATEGORY_SYNTHETIC_TEST
    if h in SEED_HEADLINES:
        return CATEGORY_SYNTHETIC_SEED
    return None


def classify_rows(rows: Iterable[dict]) -> list[dict]:
    """Annotate each row dict with a ``category``.

    Pure — operates on in-memory dicts (keys ``headline`` and ``model`` are
    read; everything else is passed through).  Synthetic rows are classified
    per-row; the remaining (real) rows are grouped by exact headline and
    labelled ``real_duplicate`` when the headline appears more than once, else
    ``real_unique``.
    """
    annotated: list[dict] = []
    real_groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        cat = classify_synthetic(r.get("headline"), r.get("model"))
        out = dict(r)
        out["category"] = cat
        annotated.append(out)
        if cat is None:
            real_groups[(r.get("headline") or "").strip()].append(out)
    dup_headlines = {h for h, v in real_groups.items() if len(v) > 1}
    for out in annotated:
        if out["category"] is None:
            h = (out.get("headline") or "").strip()
            out["category"] = (
                CATEGORY_REAL_DUPLICATE if h in dup_headlines else CATEGORY_REAL_UNIQUE
            )
    return annotated


def _primary_ticker(raw_market_tickers: Any) -> Optional[str]:
    """First non-empty ``symbol`` in the market_tickers JSON list, upper-cased.

    Mirrors the canonical ``event_study_validation._primary_ticker`` (a private
    helper); replicated here for the same reason the gate replicates its own
    pure helpers — to avoid a report depending on another module's private API.
    """
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if isinstance(entry, dict):
            sym = entry.get("symbol")
            if isinstance(sym, str) and sym.strip():
                return sym.strip().upper()
    return None


# ---------------------------------------------------------------------------
# Read-only event load
# ---------------------------------------------------------------------------


def _load_rows(path: str) -> tuple[list[dict], int, int]:
    """Return (analysis-stage row dicts, curated_intake_excluded, archive_total).

    Pure read through a read-only connection.  Excludes
    ``db.NON_ANALYSIS_STAGES`` (curated_intake stubs) from the analysis-stage
    set and discloses the excluded count.  Any DB error degrades to empties.
    """
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], 0, 0
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, headline, event_date, stage, market_tickers, model "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], 0, 0
    finally:
        conn.close()

    non_analysis = getattr(db, "NON_ANALYSIS_STAGES", frozenset())
    analysis: list[dict] = []
    excluded = 0
    for r in rows:
        stage = r["stage"]
        if isinstance(stage, str) and stage in non_analysis:
            excluded += 1
            continue
        analysis.append({
            "id": r["id"],
            "headline": r["headline"],
            "event_date": r["event_date"],
            "market_tickers": r["market_tickers"],
            "model": r["model"],
        })
    return analysis, excluded, len(rows)


# ---------------------------------------------------------------------------
# Compute
# ---------------------------------------------------------------------------


def _ratio(numerator: int, denominator: int) -> dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else None
    return {"numerator": numerator, "denominator": denominator, "value": value}


def _date_range(group: list[dict]) -> list[str]:
    ds = sorted((r.get("event_date") or "")[:10] for r in group if r.get("event_date"))
    return [ds[0], ds[-1]] if ds else []


def _status_counts(group: list[dict], status_map: dict[int, str]) -> dict[str, int]:
    return dict(Counter(status_map.get(r["id"], "unknown") for r in group))


def summarize_data_hygiene(
    *, db_path: Optional[str] = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the data-hygiene report dict (read-only).

    Classifies every analysis-stage row, runs the event-study gate for
    compute-ready status, and aggregates the four denominators and three
    coverage ratios.  ``limit`` caps only the surfaced example list (negative
    clamps to 0); aggregate counts always reflect the full archive.  The gate
    reads ``price_cache`` through ``db.DB_FILE``; it is pointed at the resolved
    path for the loop and restored afterwards — nothing is written.
    """
    capped = max(int(limit), 0)
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    if path is None:
        return _empty_report()
    path = str(path)

    analysis, excluded, archive_total = _load_rows(path)
    annotated = classify_rows(analysis)

    # Event-study compute-ready status via the real gate (read-only).  The gate
    # reads price_cache through the module-global ``db.DB_FILE``, so we point it
    # at the resolved path for the loop and restore in ``finally``.  This makes
    # the call NON-REENTRANT (don't run two summaries with different db_paths in
    # one process concurrently) — same single-threaded-CLI contract as the
    # sibling ``event_study_coverage_report``.  Read-only: the gate only SELECTs.
    status_map: dict[int, str] = {}
    original_db_file = db.DB_FILE
    try:
        db.DB_FILE = path
        for r in analysis:
            payload = build_event_study_validation({
                "id": r["id"],
                "market_tickers": r["market_tickers"],
                "event_date": r["event_date"],
            })
            status_map[r["id"]] = payload.get("status", "insufficient_data")
    finally:
        db.DB_FILE = original_db_file

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in annotated:
        by_cat[r["category"]].append(r)

    synthetic = by_cat[CATEGORY_SYNTHETIC_SEED] + by_cat[CATEGORY_SYNTHETIC_TEST]
    real = by_cat[CATEGORY_REAL_DUPLICATE] + by_cat[CATEGORY_REAL_UNIQUE]

    # Real-event grouping (distinct headlines / duplicate collapse).
    real_by_headline: dict[str, list[dict]] = defaultdict(list)
    for r in real:
        real_by_headline[(r.get("headline") or "").strip()].append(r)
    dup_groups = {h: v for h, v in real_by_headline.items() if len(v) > 1}
    real_duplicate_rows = sum(len(v) for v in dup_groups.values())
    redundant = real_duplicate_rows - len(dup_groups)

    def is_ready(r: dict) -> bool:
        return status_map.get(r["id"]) == "event_study_available"

    compute_ready_rows = sum(1 for r in annotated if is_ready(r))
    compute_ready_real = [r for r in real if is_ready(r)]
    compute_ready_distinct = len({(r.get("headline") or "").strip() for r in compute_ready_real})

    # Synthetic groups (by exact headline).
    synth_by_headline: dict[str, list[dict]] = defaultdict(list)
    for r in synthetic:
        synth_by_headline[(r.get("headline") or "").strip()].append(r)

    def group_payload(headline: str, group: list[dict], *, tickers: bool) -> dict[str, Any]:
        out = {
            "headline": headline,
            "count": len(group),
            "ids": sorted(r["id"] for r in group),
            "date_range": _date_range(group),
            "event_study_status_counts": _status_counts(group, status_map),
        }
        if tickers:
            out["primary_tickers"] = sorted(
                {t for t in (_primary_ticker(r.get("market_tickers")) for r in group) if t}
            )
        else:
            out["model_values"] = dict(Counter((r.get("model") or "<null>") for r in group))
        return out

    synthetic_groups = [
        group_payload(h, v, tickers=False)
        for h, v in sorted(synth_by_headline.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    duplicate_groups = [
        group_payload(h, v, tickers=True)
        for h, v in sorted(dup_groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]

    real_unique_no_primary = [
        {"id": r["id"], "headline": r["headline"], "event_date": r["event_date"]}
        for r in by_cat[CATEGORY_REAL_UNIQUE]
        if _primary_ticker(r.get("market_tickers")) is None
    ]

    analysis_stage_total = len(analysis)
    real_row_total = len(real)
    distinct_real_event_total = len(real_by_headline)

    return {
        "archive_raw_total": archive_total,
        "analysis_stage_total": analysis_stage_total,
        "curated_intake_excluded_count": excluded,
        "synthetic_total": len(synthetic),
        "synthetic_seed_count": len(by_cat[CATEGORY_SYNTHETIC_SEED]),
        "synthetic_test_count": len(by_cat[CATEGORY_SYNTHETIC_TEST]),
        "real_row_total": real_row_total,
        "distinct_real_event_total": distinct_real_event_total,
        "real_duplicate_rows": real_duplicate_rows,
        "real_duplicate_groups_count": len(dup_groups),
        "redundant_real_duplicate_rows": redundant,
        "compute_ready_rows": compute_ready_rows,
        "compute_ready_distinct_real_events": compute_ready_distinct,
        "coverage_ratios": {
            "archive_row_level": _ratio(compute_ready_rows, analysis_stage_total),
            "real_row_level": _ratio(compute_ready_rows, real_row_total),
            "distinct_real_event_level": _ratio(compute_ready_distinct, distinct_real_event_total),
        },
        "synthetic_groups": synthetic_groups,
        "duplicate_groups": duplicate_groups,
        "real_unique_no_primary_examples": real_unique_no_primary[:capped],
        "real_unique_no_primary_total": len(real_unique_no_primary),
        "non_claims": dict(_NON_CLAIMS),
    }


def _empty_report() -> dict[str, Any]:
    z = _ratio(0, 0)
    return {
        "archive_raw_total": 0, "analysis_stage_total": 0,
        "curated_intake_excluded_count": 0, "synthetic_total": 0,
        "synthetic_seed_count": 0, "synthetic_test_count": 0, "real_row_total": 0,
        "distinct_real_event_total": 0, "real_duplicate_rows": 0,
        "real_duplicate_groups_count": 0, "redundant_real_duplicate_rows": 0,
        "compute_ready_rows": 0, "compute_ready_distinct_real_events": 0,
        "coverage_ratios": {
            "archive_row_level": z, "real_row_level": z, "distinct_real_event_level": z,
        },
        "synthetic_groups": [], "duplicate_groups": [],
        "real_unique_no_primary_examples": [], "real_unique_no_primary_total": 0,
        "non_claims": dict(_NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_text(report: dict[str, Any]) -> str:
    L: list[str] = ["Archive data-hygiene report", ""]
    L.append(f"archive raw total (incl curated_intake): {report['archive_raw_total']}")
    L.append(f"analysis-stage total (denominator of record): {report['analysis_stage_total']}")
    L.append(f"  curated_intake excluded: {report['curated_intake_excluded_count']}")
    L.append(
        f"  synthetic: {report['synthetic_total']} "
        f"(seed {report['synthetic_seed_count']}, test {report['synthetic_test_count']})"
    )
    L.append(
        f"  real rows: {report['real_row_total']} "
        f"(distinct real events {report['distinct_real_event_total']}; "
        f"{report['redundant_real_duplicate_rows']} redundant duplicate copies)"
    )
    L.append("")
    cr = report["coverage_ratios"]
    L.append("Coverage (compute-ready / denominator):")
    L.append(f"  archive row level:        {cr['archive_row_level']['numerator']}/"
             f"{cr['archive_row_level']['denominator']} = {cr['archive_row_level']['value']}")
    L.append(f"  real row level:           {cr['real_row_level']['numerator']}/"
             f"{cr['real_row_level']['denominator']} = {cr['real_row_level']['value']}")
    L.append(f"  distinct real event level:{cr['distinct_real_event_level']['numerator']}/"
             f"{cr['distinct_real_event_level']['denominator']} = {cr['distinct_real_event_level']['value']}")
    L.append("")
    L.append("Synthetic groups:")
    for g in report["synthetic_groups"]:
        L.append(f"  {g['count']:>3}x {g['date_range']} {g['model_values']} | {g['headline'][:48]}")
    L.append("")
    L.append("Real-duplicate groups:")
    for g in report["duplicate_groups"]:
        L.append(f"  {g['count']:>3}x {g['date_range']} tk={g['primary_tickers']} | {g['headline'][:42]}")
    L.append("")
    L.append("Caveat: synthetic/test rows are classified heuristically (exact seed "
             "headline + test-model fingerprint), kept visible, never deleted; the "
             "157 analysis-stage count stays the denominator of record; the closed "
             "Phase 1/2 FDR pools are untouched.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only archive data-hygiene report. Classifies analysis-stage "
            "rows into synthetic_seed / synthetic_test / real_duplicate / "
            "real_unique and emits the four honest denominators. No mutation, "
            "no provider/network call, never touches the closed FDR pools."
        ),
    )
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON instead of the text summary.")
    parser.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                        help=(f"Cap the surfaced real-unique example list at N "
                              f"(default {_DEFAULT_LIMIT}). Aggregate counts always "
                              f"reflect every event."))
    parser.add_argument("--db-path", dest="db_path", default=None,
                        help="Optional path to a SQLite events.db. Defaults to db.DB_FILE.")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = summarize_data_hygiene(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
