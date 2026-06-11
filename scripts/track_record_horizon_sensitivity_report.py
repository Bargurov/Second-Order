#!/usr/bin/env python3
"""Read-only track-record HORIZON-sensitivity report (H1).

The canonical track-record scorer (`db.compute_track_record`) labels each
accepted event from the longest-horizon revisit snapshot that carries at
least one directional ticker (20d > 5d > 1d), falling back to the initial
``market_tickers`` read when no snapshot qualifies. The corpus therefore
mixes observation horizons. This report quantifies how sensitive the
support / contradiction / unresolved split is to that choice by recomputing
the SAME accepted events under fixed single-horizon variants (1d-only,
5d-only, 20d-only, where a snapshot at that horizon exists).

This is the horizon twin of ``track_record_sensitivity_report.py`` (which
varies the scoring RULE). It is disclosure, not a truth claim: the canonical
best-available rule remains the primary headline, no horizon variant is
asserted correct, every count is descriptive, and no FDR or significance
readout is attached. Horizon variants are computed from revisit snapshots
only; the initial ``market_tickers`` read appears solely as the canonical
fallback category in the horizon distribution.

Read-only: a single ``mode=ro`` connection, plain ``SELECT``s only. No
INSERT / UPDATE / DELETE, no ``init_db``, no provider, no network, no LLM,
no event-study math, no FDR pools.

Usage::

    python scripts/track_record_horizon_sensitivity_report.py
    python scripts/track_record_horizon_sensitivity_report.py --json
    python scripts/track_record_horizon_sensitivity_report.py --db-path ./events.db --json
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

import db  # noqa: E402  - NON_THESIS_STAGES, synthetic_seed_ids, scoring helpers

_DEFAULT_LIMIT = 5
_SYNTHETIC_SEED_OVERRIDE = "synthetic_seed"
_HORIZONS = (1, 5, 20)
_OUTCOMES = ("support", "contradiction", "unresolved")

_INTERPRETATION_NOTE = (
    "The canonical best-available rule (20d > 5d > 1d revisit snapshot with "
    "a directional ticker, else the initial market_tickers read) remains the "
    "primary headline; the single-horizon variants are diagnostics only.",
    "No horizon variant is a new claim: every count is a descriptive re-label "
    "of the same accepted events under a fixed observation horizon.",
    "Horizon variants read revisit snapshots only, so events without a "
    "snapshot at a horizon are reported as missing there, never re-scored.",
    "No FDR adjustment and no statistical-significance readout is attached "
    "to any count in this report.",
)

_NON_CLAIMS = (
    "Counts are descriptive event-window evidence labels, not a confirmed "
    "mechanism and not a measure of predictive power.",
    "A flip between horizons shows label sensitivity to the observation "
    "window; it does not say which horizon is correct.",
    "The closed Phase 1 / Phase 2 FDR pools are never read, combined, or "
    "implied by this report.",
    "This report carries no directive or trade framing of any kind.",
)


# ---------------------------------------------------------------------------
# Canonical-mirroring helpers (measured, never changed)
# ---------------------------------------------------------------------------


def _best_snapshot_with_day(snapshots: list) -> tuple[Any, list | None]:
    """(day, tickers) of the snapshot db._best_revisit_snapshot would pick.

    Verbatim mirror of the canonical helper, additionally reporting the
    winning snapshot's ``day`` so the horizon distribution can be measured.
    Returns (None, None) when no snapshot has tickers.
    """
    if not snapshots:
        return None, None
    for snap in sorted(snapshots, key=lambda s: s.get("day", 0), reverse=True):
        tickers = snap.get("tickers")
        if tickers:
            return snap.get("day"), tickers
    return None, None


def _classify(tickers: list) -> tuple[str, int]:
    """ANY-support outcome label + directional-ticker count.

    Identical decision to ``db.compute_track_record``: >=1 supports ->
    support; else >=1 contradicts -> contradiction; else unresolved.
    """
    has_sup, has_con, _sup_cnt, dir_cnt = db._score_directions(tickers)
    if has_sup:
        return "support", dir_cnt
    if has_con:
        return "contradiction", dir_cnt
    return "unresolved", dir_cnt


def _parse_json_list(raw: Any) -> list:
    try:
        value = json.loads(raw or "[]")
    except (json.JSONDecodeError, TypeError):
        value = []
    return value if isinstance(value, list) else []


def _horizon_snapshot(snapshots: list, horizon: int) -> list | None:
    """First snapshot at exactly ``horizon`` days that has tickers, or None.

    First-in-list order mirrors the stable-sort behaviour the canonical
    helper applies to equal-day snapshots.
    """
    for snap in snapshots:
        if isinstance(snap, dict) and snap.get("day") == horizon:
            tickers = snap.get("tickers")
            if tickers:
                return tickers
    return None


# ---------------------------------------------------------------------------
# Load + per-event scoring
# ---------------------------------------------------------------------------


def _empty_denominator() -> dict:
    return {
        "accepted_track_record_events": 0,
        "archive_rows": 0,
        "excluded_stages": sorted(getattr(db, "NON_THESIS_STAGES", frozenset())),
        "excluded_override_classes": [_SYNTHETIC_SEED_OVERRIDE],
        "non_thesis_stage_excluded": 0,
        "synthetic_seed_excluded": 0,
    }


def _load_accepted_rows(path: str) -> tuple[list[sqlite3.Row], dict]:
    """Accepted track-record rows + denominator metadata. Read-only."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return [], _empty_denominator()
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, market_tickers, revisit_snapshots, stage "
                "FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            return [], _empty_denominator()
        try:
            synthetic = db.synthetic_seed_ids(conn)
        except Exception:
            synthetic = frozenset()
    finally:
        conn.close()

    non_thesis = getattr(db, "NON_THESIS_STAGES", frozenset())
    accepted: list[sqlite3.Row] = []
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
        accepted.append(r)

    denom_meta = {
        "accepted_track_record_events": len(accepted),
        "archive_rows": archive_rows,
        "excluded_stages": sorted(non_thesis),
        "excluded_override_classes": [_SYNTHETIC_SEED_OVERRIDE],
        "non_thesis_stage_excluded": stage_excluded,
        "synthetic_seed_excluded": synthetic_excluded,
    }
    return accepted, denom_meta


def _score_event(row: sqlite3.Row) -> dict:
    """Canonical + per-horizon outcome labels for one accepted event."""
    snapshots = _parse_json_list(row["revisit_snapshots"])

    # Canonical: verbatim mirror of db.compute_track_record source selection.
    day, best = _best_snapshot_with_day(snapshots)
    canonical_outcome: str | None = None
    canonical_source = "market_tickers_fallback"
    if best is not None:
        outcome, dir_cnt = _classify(best)
        if dir_cnt > 0:
            canonical_outcome = outcome
            if day in _HORIZONS:
                canonical_source = f"snapshot_{day}d"
            else:
                canonical_source = "snapshot_other_day"
    if canonical_outcome is None:
        market = _parse_json_list(row["market_tickers"])
        canonical_outcome, _ = _classify(market)
        canonical_source = "market_tickers_fallback"

    horizon_outcomes: dict[str, str] = {}
    horizon_dir_cnt: dict[str, int] = {}
    for h in _HORIZONS:
        tickers = _horizon_snapshot(snapshots, h)
        key = f"{h}d"
        if tickers is None:
            horizon_outcomes[key] = "missing"
            horizon_dir_cnt[key] = 0
        else:
            outcome, dir_cnt = _classify(tickers)
            horizon_outcomes[key] = outcome
            horizon_dir_cnt[key] = dir_cnt

    return {
        "event_id": row["id"],
        "canonical_outcome": canonical_outcome,
        "canonical_source": canonical_source,
        "horizon_outcomes": horizon_outcomes,
        "horizon_dir_cnt": horizon_dir_cnt,
    }


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------


def _flip_matrix_keys() -> dict[str, int]:
    return {
        f"{a}_to_{b}": 0
        for a in _OUTCOMES for b in _OUTCOMES if a != b
    }


def build_report(*, db_path: str | None = None,
                 limit: int = _DEFAULT_LIMIT) -> dict:
    """Build the horizon-sensitivity report dict. Read-only."""
    capped = max(int(limit), 0)
    path = db_path if db_path is not None else getattr(db, "DB_FILE", None)
    if path is None:
        rows: list[sqlite3.Row] = []
        denom_meta = _empty_denominator()
    else:
        rows, denom_meta = _load_accepted_rows(path)

    per_event = [_score_event(r) for r in rows]

    # Canonical headline block (mirrors compute_track_record's key names).
    canon_counts = {"support": 0, "contradiction": 0, "unresolved": 0}
    distribution = {
        "snapshot_20d": 0, "snapshot_5d": 0, "snapshot_1d": 0,
        "snapshot_other_day": 0, "market_tickers_fallback": 0,
    }
    for e in per_event:
        canon_counts[e["canonical_outcome"]] += 1
        distribution[e["canonical_source"]] += 1
    canonical = {
        "rule": (
            "any_support over the best-available revisit horizon "
            "(20d > 5d > 1d, dir_cnt > 0), else initial market_tickers"
        ),
        "validated": canon_counts["support"],
        "contradicted": canon_counts["contradiction"],
        "unresolved": canon_counts["unresolved"],
        "total": len(per_event),
        "horizon_distribution": distribution,
    }

    # Per-horizon diagnostic blocks.
    horizons: dict[str, dict] = {}
    for h in _HORIZONS:
        key = f"{h}d"
        block = {
            "available": 0, "missing": 0,
            "support": 0, "contradiction": 0, "unresolved": 0,
            "data_limited_no_direction": 0,
            "differs_from_canonical": 0,
            "flip_matrix_vs_canonical": _flip_matrix_keys(),
            "examples_differs": [],
        }
        for e in per_event:
            outcome = e["horizon_outcomes"][key]
            if outcome == "missing":
                block["missing"] += 1
                continue
            block["available"] += 1
            block[outcome] += 1
            if e["horizon_dir_cnt"][key] == 0:
                block["data_limited_no_direction"] += 1
            canon = e["canonical_outcome"]
            if outcome != canon:
                block["differs_from_canonical"] += 1
                block["flip_matrix_vs_canonical"][f"{canon}_to_{outcome}"] += 1
                if len(block["examples_differs"]) < capped:
                    block["examples_differs"].append({
                        "event_id": e["event_id"],
                        "canonical": canon,
                        "horizon_outcome": outcome,
                    })
        horizons[key] = block

    # Cross-horizon flips (events with snapshots at 2+ horizons).
    multi = 0
    flipping = 0
    cross_examples: list[dict] = []
    for e in per_event:
        present = {k: v for k, v in e["horizon_outcomes"].items()
                   if v != "missing"}
        if len(present) < 2:
            continue
        multi += 1
        if len(set(present.values())) > 1:
            flipping += 1
            if len(cross_examples) < capped:
                cross_examples.append({
                    "event_id": e["event_id"],
                    "outcomes": dict(e["horizon_outcomes"]),
                })

    return {
        "report": "track_record_horizon_sensitivity",
        "read_only": True,
        "denominator": denom_meta,
        "canonical": canonical,
        "horizons": horizons,
        "cross_horizon": {
            "events_with_2plus_horizons": multi,
            "events_flipping_between_horizons": flipping,
            "examples": cross_examples,
        },
        "per_event": [
            {k: v for k, v in e.items() if k != "horizon_dir_cnt"}
            for e in per_event
        ],
        "interpretation_note": list(_INTERPRETATION_NOTE),
        "non_claims": list(_NON_CLAIMS),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict) -> str:
    denom = report.get("denominator") or {}
    canon = report.get("canonical") or {}
    dist = canon.get("horizon_distribution") or {}
    lines = ["Track-record horizon sensitivity (read-only diagnostics)", ""]
    lines.append(
        f"Accepted track-record denominator: {canon.get('total', 0)} "
        f"(of {denom.get('archive_rows', 0)} archive rows; "
        f"{denom.get('non_thesis_stage_excluded', 0)} non-thesis-stage + "
        f"{denom.get('synthetic_seed_excluded', 0)} synthetic_seed excluded)"
    )
    lines.append(
        f"Canonical headline (unchanged): validated {canon.get('validated', 0)} "
        f"/ contradicted {canon.get('contradicted', 0)} "
        f"/ unresolved {canon.get('unresolved', 0)}"
    )
    lines.append(
        "Canonical source distribution: "
        f"20d {dist.get('snapshot_20d', 0)} | 5d {dist.get('snapshot_5d', 0)} "
        f"| 1d {dist.get('snapshot_1d', 0)} "
        f"| other-day {dist.get('snapshot_other_day', 0)} "
        f"| market_tickers fallback {dist.get('market_tickers_fallback', 0)}"
    )
    lines.append("")
    lines.append("Horizon | avail | miss | sup | con | unres | data-ltd | differs-vs-canonical")
    for key in ("1d", "5d", "20d"):
        b = (report.get("horizons") or {}).get(key) or {}
        lines.append(
            f"  {key:<6}| {b.get('available', 0):>5} | {b.get('missing', 0):>4} "
            f"| {b.get('support', 0):>3} | {b.get('contradiction', 0):>3} "
            f"| {b.get('unresolved', 0):>5} "
            f"| {b.get('data_limited_no_direction', 0):>8} "
            f"| {b.get('differs_from_canonical', 0):>3}"
        )
    lines.append("")
    for key in ("1d", "5d", "20d"):
        b = (report.get("horizons") or {}).get(key) or {}
        matrix = b.get("flip_matrix_vs_canonical") or {}
        nonzero = {k: v for k, v in matrix.items() if v}
        if nonzero:
            pairs = ", ".join(f"{k}={v}" for k, v in sorted(nonzero.items()))
            lines.append(f"Flips vs canonical at {key}: {pairs}")
            for ex in b.get("examples_differs") or []:
                lines.append(
                    f"  #{ex.get('event_id')}: canonical "
                    f"{ex.get('canonical')} -> {key} {ex.get('horizon_outcome')}"
                )
    cross = report.get("cross_horizon") or {}
    lines.append("")
    lines.append(
        f"Cross-horizon: {cross.get('events_with_2plus_horizons', 0)} events "
        f"have snapshots at 2+ horizons; "
        f"{cross.get('events_flipping_between_horizons', 0)} change label "
        "between horizons"
    )
    for ex in cross.get("examples") or []:
        oc = ex.get("outcomes") or {}
        lines.append(
            f"  #{ex.get('event_id')}: 1d {oc.get('1d')} | 5d {oc.get('5d')} "
            f"| 20d {oc.get('20d')}"
        )
    lines.append("")
    lines.append("Interpretation:")
    for note in report.get("interpretation_note") or []:
        lines.append(f"  - {note}")
    lines.append("Non-claims:")
    for nc in report.get("non_claims") or []:
        lines.append(f"  - {nc}")
    return "\n".join(lines)


def _render_json(report: dict) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Read-only track-record horizon-sensitivity diagnostics. "
            "Recomputes accepted track-record outcome labels under fixed "
            "1d / 5d / 20d revisit horizons beside the canonical "
            "best-available rule. Disclosure only; the canonical headline "
            "is unchanged; no DB write, no provider call."
        ),
    )
    p.add_argument("--json", action="store_true", help="Emit structured JSON.")
    p.add_argument("--limit", type=int, default=_DEFAULT_LIMIT,
                   help=f"Cap surfaced flip examples (default {_DEFAULT_LIMIT}).")
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
