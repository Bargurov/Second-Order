#!/usr/bin/env python3
"""Read-only mechanism-family research overview.

Answers, in one place: which mechanism families exist in the canonical
taxonomy, which carry accepted evidence, which exist only as staged no-paid
candidates, which are thin or absent, which representative cases illustrate
each family, and how the Tier-1 candidate shortlist
(``stats/STAGED_CANDIDATE_SHORTLIST.md``) would broaden the archive if later
reviewed.

Separation rules (non-negotiable):

  * Accepted evidence and staged candidates are NEVER merged. The accepted
    lens is the canonical hygiene-aware accepted corpus (excludes
    ``db.NON_ANALYSIS_STAGES`` rows and ``event_hygiene`` synthetic_seed rows
    — the same denominator as ``scripts/event_study_coverage_report.py``).
  * Staged ``z1a_candidate_pack`` rows are review staging, not evidence.
  * The ``none`` / untagged bucket is surfaced as a limitation, never hidden.
  * Family labels are taxonomy, not causal proof; representative cases are
    illustrative, not evidence; no single-event significance is claimed.

Read-only: one ``mode=ro`` connection for the events scan; the optional
per-family accepted compute-ready count reuses the same event-study gate as
the coverage report
(``event_study_validation.build_event_study_validation``, SELECT-only) and
degrades to ``None`` if the gate is unavailable. Staged event-study
availability remains in queue/shortlist reporting and is never merged into
the accepted count. No DB write, no provider, no LLM, no FastAPI surface, no
paid call. The closed Phase 1 / Phase 2 FDR pools are never read or implied.

Usage::

    python scripts/mechanism_family_overview_report.py
    python scripts/mechanism_family_overview_report.py --json
    python scripts/mechanism_family_overview_report.py --db-path events.db --json
    python scripts/mechanism_family_overview_report.py --limit-cases 5
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

import db  # noqa: E402  - stage constants + synthetic_seed_ids + DB_FILE

_DEFAULT_LIMIT_CASES = 3

# Inline mirrors (fallback only — db constants win at runtime).
_CANDIDATE_STAGE = "z1a_candidate_pack"
_CURATED_INTAKE_STAGE = "curated_intake"
_PENDING_REVIEW_STAGE = "analysis_pending_review"
_CURATED_OBSERVATION_STAGE = "curated_observation"
_FALLBACK_NON_ANALYSIS = frozenset({
    _CANDIDATE_STAGE, _CURATED_INTAKE_STAGE, _PENDING_REVIEW_STAGE,
})

# The minimum family set the overview always reports, even at zero.
MIN_FAMILIES: tuple[str, ...] = (
    "tariff", "sanction", "policy_surprise", "regulation",
    "labor_inflation", "industrial_policy", "none",
)

# Tier-1 shortlist bridge — mirrors the committed decision log
# stats/STAGED_CANDIDATE_SHORTLIST.md (AX1-AX5). The report cross-checks each
# id against the live archive and refuses to call an entry staged/no-paid
# unless its row is actually still a staged candidate.
TIER1_SHORTLIST: tuple[dict, ...] = (
    {
        "event_id": 303,
        "label": "DOJ v Apple (2024-03-21, AAPL)",
        "family": "regulation",
        "why_it_broadens": (
            "Conduct-remedy antitrust on a discrete suit-filing date; the "
            "regulation family currently has zero accepted rows."
        ),
    },
    {
        "event_id": 304,
        "label": "DOJ v Google ad-tech (2023-01-24, GOOGL)",
        "family": "regulation",
        "why_it_broadens": (
            "Structural-remedy / divestiture antitrust; pairs with 303 as a "
            "conduct-vs-structural contrast within a new family."
        ),
    },
    {
        "event_id": 313,
        "label": "UAW Stand Up Strike begins (2023-09-15, GM/F)",
        "family": "labor_inflation",
        "why_it_broadens": (
            "Production-disruption / wage-cost shock; the labor_inflation "
            "family currently has zero accepted rows and sits furthest from "
            "the archive's oil/war/semiconductor concentration."
        ),
    },
)

NON_CLAIMS: tuple[str, ...] = (
    "Representative cases are illustrative, not proof of any mechanism.",
    "Staged candidates are review staging, not accepted evidence, and are "
    "excluded from every accepted-corpus denominator.",
    "No single-event significance is claimed at any horizon (n=1: no CI, "
    "p-value, or FDR).",
    "No paid analysis was run to produce this overview; paid /analyze "
    "remains blocked.",
    "The closed Phase 1 / Phase 2 FDR pools are neither read nor implied.",
    "Mechanism-family labels are a research taxonomy, not causal proof.",
)

_DENOMINATOR_NOTE = (
    "Accepted lens = canonical hygiene-aware accepted corpus: excludes "
    "non-analysis stages (curated_intake, z1a_candidate_pack, "
    "analysis_pending_review) and event_hygiene synthetic_seed rows; matches "
    "scripts/event_study_coverage_report.py. The track-record denominator "
    "additionally excludes curated_observation rows (observations carry no "
    "thesis outcome). Staged candidates are counted separately and never "
    "enter accepted denominators."
)

_EVENT_STUDY_AVAILABILITY_NOTE = (
    "accepted_compute_ready_count applies only to accepted-corpus rows. "
    "Staged event-study availability is handled by queue/shortlist reports "
    "and is not merged into accepted compute-ready counts."
)


# ---------------------------------------------------------------------------
# Read-only load + classification
# ---------------------------------------------------------------------------


def _stage_constants() -> tuple[frozenset, str, str, str, str]:
    non_analysis = frozenset(getattr(db, "NON_ANALYSIS_STAGES", _FALLBACK_NON_ANALYSIS))
    candidate = getattr(db, "CANDIDATE_PACK_STAGE", _CANDIDATE_STAGE)
    if not isinstance(candidate, str):
        candidate = _CANDIDATE_STAGE
    intake = getattr(db, "CURATED_INTAKE_STAGE", _CURATED_INTAKE_STAGE)
    pending = getattr(db, "ANALYSIS_PENDING_REVIEW_STAGE", _PENDING_REVIEW_STAGE)
    observation = getattr(db, "CURATED_OBSERVATION_STAGE", _CURATED_OBSERVATION_STAGE)
    return non_analysis, candidate, intake, pending, observation


def _primary_ticker(raw: Any) -> str | None:
    if not raw:
        return None
    parsed = raw
    if isinstance(parsed, str):
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


def _family_of(raw: Any) -> str:
    if isinstance(raw, str) and raw.strip():
        return raw.strip().lower()
    return "none"


def _load_rows(path: str) -> tuple[list[dict], frozenset]:
    """Load (event rows, synthetic ids) read-only; degrade to empty."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], frozenset()
    try:
        conn.row_factory = sqlite3.Row
        try:
            raw = conn.execute(
                "SELECT id, event_date, stage, mechanism_family, headline, "
                "market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], frozenset()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()

    rows = [
        {
            "event_id": r["id"],
            "event_date": r["event_date"],
            "stage": r["stage"] if isinstance(r["stage"], str) else None,
            "family": _family_of(r["mechanism_family"]),
            "headline": (r["headline"] or "")[:90],
            "primary_ticker": _primary_ticker(r["market_tickers"]),
        }
        for r in raw
    ]
    return rows, synthetic


def _case_entry(row: dict, *, status: str) -> dict:
    return {
        "event_id": row["event_id"],
        "event_date": row["event_date"],
        "stage": row["stage"],
        "primary_ticker": row["primary_ticker"],
        "headline": row["headline"],
        "status": status,
    }


def _accepted_compute_ready_counts(
    accepted: list[dict], *, db_path: str,
) -> dict[str, int] | None:
    """Per-family event-study compute-ready counts over ACCEPTED rows only.

    Reuses the same strict gate as the coverage report (SELECT-only).
    Degrades to ``None`` (omitted counts) if the gate can't run — the
    overview must not fail on a fixture without price data.
    """
    try:
        from event_study_validation import (
            STATUS_AVAILABLE,
            build_event_study_validation,
        )
    except Exception:
        return None

    counts: dict[str, int] = {}
    saved = db.DB_FILE
    try:
        db.DB_FILE = db_path
        for row in accepted:
            primary = row["primary_ticker"]
            event = {
                "id": row["event_id"],
                "event_date": row["event_date"],
                "market_tickers": [{"symbol": primary}] if primary else [],
            }
            try:
                out = build_event_study_validation(event)
            except Exception:
                continue
            if out.get("status") == STATUS_AVAILABLE:
                counts[row["family"]] = counts.get(row["family"], 0) + 1
    finally:
        db.DB_FILE = saved
    return counts


# ---------------------------------------------------------------------------
# Overview composer
# ---------------------------------------------------------------------------


def build_overview(
    *, db_path: str | None = None, limit_cases: int = _DEFAULT_LIMIT_CASES,
) -> dict[str, Any]:
    """Build the mechanism-family overview dict. Read-only."""
    cap = max(int(limit_cases), 0)
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    rows, synthetic = _load_rows(path) if path else ([], frozenset())
    non_analysis, candidate_stage, intake, pending, observation = _stage_constants()

    accepted: list[dict] = []
    staged: list[dict] = []
    excluded_by_kind = {
        "synthetic_seed": 0, "curated_intake": 0, "analysis_pending_review": 0,
        "other_non_analysis": 0,
    }
    excluded_rows: list[dict] = []
    for row in rows:
        stage = row["stage"]
        if stage == candidate_stage:
            staged.append(row)
        elif stage is not None and stage in non_analysis:
            if stage == intake:
                excluded_by_kind["curated_intake"] += 1
            elif stage == pending:
                excluded_by_kind["analysis_pending_review"] += 1
            else:
                excluded_by_kind["other_non_analysis"] += 1
            excluded_rows.append(row)
        elif row["event_id"] in synthetic:
            excluded_by_kind["synthetic_seed"] += 1
            excluded_rows.append(row)
        else:
            accepted.append(row)

    observation_count = sum(1 for r in accepted if r["stage"] == observation)

    accepted_ready_counts = (
        _accepted_compute_ready_counts(accepted, db_path=path) if path else None
    )

    # Family rows: minimum set union every observed family, deterministic order.
    observed = (
        {r["family"] for r in accepted}
        | {r["family"] for r in staged}
        | {r["family"] for r in excluded_rows}
    )
    family_names = list(MIN_FAMILIES) + sorted(observed - set(MIN_FAMILIES))

    families: list[dict] = []
    for fam in family_names:
        f_accepted = [r for r in accepted if r["family"] == fam]
        f_staged = [r for r in staged if r["family"] == fam]
        f_excluded = [r for r in excluded_rows if r["family"] == fam]
        f_obs = sum(1 for r in f_accepted if r["stage"] == observation)

        if fam == "none":
            status = "untagged_limitation"
        elif f_accepted:
            status = "accepted_evidence_present"
        elif f_staged:
            status = "staged_only"
        elif f_excluded:
            status = "excluded_only"
        else:
            status = "absent"

        limitations: list[str] = []
        if fam == "none":
            limitations.append(
                "Untagged bucket: these rows carry no mechanism_family label; "
                "family-level analysis is not possible for them. This is a "
                "data limitation, not evidence."
            )
        if f_accepted and f_obs == len(f_accepted) and f_accepted:
            limitations.append(
                "All accepted rows in this family are curated observations "
                "(no LLM thesis, no thesis-outcome contribution)."
            )
        if status == "staged_only":
            limitations.append(
                "Staged candidates only - review staging, not accepted "
                "evidence; excluded from every accepted denominator."
            )
        if status == "excluded_only":
            limitations.append(
                "Present only in excluded buckets (intake / pending-review / "
                "synthetic-seed); not accepted evidence."
            )
        if status == "absent":
            limitations.append("No rows in archive or staging for this family.")

        entry: dict[str, Any] = {
            "family": fam,
            "status": status,
            "accepted_count": len(f_accepted),
            "accepted_observation_count": f_obs,
            "accepted_thesis_count": len(f_accepted) - f_obs,
            "staged_count": len(f_staged),
            "excluded_rows_count": len(f_excluded),
            "accepted_compute_ready_count": (
                accepted_ready_counts.get(fam, 0)
                if accepted_ready_counts is not None else None
            ),
            "representative_accepted_cases": [
                _case_entry(r, status="accepted")
                for r in f_accepted[:cap]
            ],
            "representative_staged_candidates": [
                _case_entry(r, status="staged_no_paid")
                for r in f_staged[:cap]
            ],
            "limitations": limitations,
        }
        families.append(entry)

    # Tier-1 shortlist bridge — DB-verified status per entry.
    by_id = {r["event_id"]: r for r in rows}
    tier1: list[dict] = []
    for spec in TIER1_SHORTLIST:
        row = by_id.get(spec["event_id"])
        if row is None:
            status = "missing_from_archive"
        elif row["stage"] == candidate_stage:
            status = "staged_no_paid"
        else:
            status = f"not_currently_staged(stage={row['stage']})"
        tier1.append({**spec, "status": status})

    return {
        "denominators": {
            "archive_rows": len(rows),
            "accepted_coverage_denominator": len(accepted),
            "accepted_track_record_denominator": len(accepted) - observation_count,
            "staged_candidates": len(staged),
            "excluded": dict(excluded_by_kind),
            "note": _DENOMINATOR_NOTE,
            "event_study_availability_note": _EVENT_STUDY_AVAILABILITY_NOTE,
        },
        "families": families,
        "shortlist_bridge": {
            "source": "stats/STAGED_CANDIDATE_SHORTLIST.md (AX1-AX5 no-paid review log)",
            "tier1": tier1,
            "note": (
                "Review ordering for future no-paid/human review only - not "
                "promotion and not approval for paid analysis."
            ),
        },
        "non_claims": list(NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    d = report["denominators"]
    lines = ["Mechanism-family research overview (read-only)", ""]
    lines.append(
        f"Archive rows: {d['archive_rows']} | accepted coverage: "
        f"{d['accepted_coverage_denominator']} | accepted track-record: "
        f"{d['accepted_track_record_denominator']} | staged candidates: "
        f"{d['staged_candidates']}"
    )
    ex = d["excluded"]
    lines.append(
        f"Excluded (disclosed): synthetic_seed={ex['synthetic_seed']} "
        f"curated_intake={ex['curated_intake']} "
        f"pending_review={ex['analysis_pending_review']}"
    )
    lines.append("Staged candidates are review staging - not accepted evidence.")
    lines.append(
        "Accepted-ready = accepted-corpus event-study compute-ready only. "
        "Staged event-study availability is handled by queue/shortlist "
        "reports and is not merged into accepted compute-ready counts."
    )
    lines.append("")
    lines.append(
        f"{'family':<20}{'status':<28}{'accepted':>9}{'(obs)':>7}"
        f"{'staged':>8}{'accepted-ready':>16}"
    )
    for f in report["families"]:
        accepted_ready = f["accepted_compute_ready_count"]
        lines.append(
            f"{f['family']:<20}{f['status']:<28}{f['accepted_count']:>9}"
            f"{f['accepted_observation_count']:>7}{f['staged_count']:>8}"
            f"{(str(accepted_ready) if accepted_ready is not None else '-'):>16}"
        )
    lines.append("")

    lines.append("If the Tier-1 shortlist is later reviewed (staged / no-paid only):")
    for e in report["shortlist_bridge"]["tier1"]:
        lines.append(f"  #{e['event_id']} [{e['status']}] {e['label']}")
        lines.append(f"      {e['why_it_broadens']}")
    lines.append(f"  {report['shortlist_bridge']['note']}")
    lines.append("")

    lines.append("Limitations:")
    seen: set[str] = set()
    for f in report["families"]:
        for lim in f["limitations"]:
            key = f"{f['family']}: {lim}"
            if key not in seen:
                seen.add(key)
                lines.append(f"  - {f['family']}: {lim}")
    lines.append("")
    lines.append("Non-claims:")
    for nc in report["non_claims"]:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only mechanism-family research overview: accepted vs staged "
            "family coverage, representative cases, and the Tier-1 shortlist "
            "bridge. No DB write, no provider call, no paid analysis; staged "
            "candidates never enter accepted denominators."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--db-path", dest="db_path", default=None,
                   help="Optional events.db path; defaults to db.DB_FILE.")
    p.add_argument("--limit-cases", dest="limit_cases", type=int,
                   default=_DEFAULT_LIMIT_CASES,
                   help=f"Cap representative case lists (default {_DEFAULT_LIMIT_CASES}).")
    return p.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = build_overview(db_path=args.db_path, limit_cases=args.limit_cases)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
