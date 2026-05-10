#!/usr/bin/env python3
"""Curated candidate staging smoke for the repaired cohort.

Exercises the API-backed staging path against a TEST/TEMP DB to
confirm the realistic 5-event repaired cohort
``[30, 40, 46, 60, 73]`` can be staged via
``POST /curated/candidates/stage`` without touching the live archive
``events`` table.

Read-only against the live archive
----------------------------------

* The smoke runs through ``fastapi.testclient.TestClient`` against
  the in-process app, so requests stay local — no provider, no
  yfinance, no LLM.
* The three upstream-report seams in ``routes.curated`` are patched
  with a synthetic 5-event payload mirroring what
  ``manual_repaired_cohort_validation_summary`` would emit for the
  current cohort.  The heavy archive scripts therefore never run.
* The ``events`` table row count is captured before/after the smoke
  and surfaced as ``live_db_unchanged`` so a regression that adds an
  archive write is caught immediately.

Output contract (JSON)::

    {
      "preview_count":    int,        # rows the preview surfaced
      "staged_count":     int,        # rows newly inserted
      "status_counts":    {str: int}, # keys: draft / needs_review
      "staged_event_ids": [int, ...], # source_event_id of every row
                                      # currently in the staging table
      "live_db_unchanged": bool,      # events row count stable
      "errors":           [str, ...],
      "warnings":         [str, ...],
    }

Conservative language
---------------------

The smoke surfaces *staged candidates*, never "validated".  Status
values are limited to ``draft`` and ``needs_review`` because the
underlying API only assigns those two on stage.

Usage::

    python scripts/curated_candidate_stage_smoke.py
    python scripts/curated_candidate_stage_smoke.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Conservative 5-event repaired cohort.  Mirrors the shape
# ``manual_repaired_cohort_validation_summary`` returns for the live
# cohort (top_abs_sar examples carry ticker, benchmark=SPY, mechanism
# family, headline, event_date).  Missing or empty fields would land
# in validation_errors and downgrade status to "draft" — every entry
# below is complete, so each lands in "needs_review".
_REPAIRED_COHORT_FIXTURE: tuple[dict[str, Any], ...] = (
    {"event_id": 30, "ticker": "XOM",  "benchmark": "SPY",
     "mechanism_family": "supply_shock",
     "headline": "h30", "event_date": "2026-04-05",
     "horizon": 5, "sar": 1.0, "p_value": 0.04, "fdr_q": 0.08},
    {"event_id": 40, "ticker": "BDRY", "benchmark": "SPY",
     "mechanism_family": "commodity_squeeze",
     "headline": "h40", "event_date": "2026-04-05",
     "horizon": 5, "sar": 1.0, "p_value": 0.04, "fdr_q": 0.08},
    {"event_id": 46, "ticker": "MS",   "benchmark": "SPY",
     "mechanism_family": "bank_regulatory_capital_relief",
     "headline": "h46", "event_date": "2026-04-06",
     "horizon": 5, "sar": 1.0, "p_value": 0.04, "fdr_q": 0.08},
    {"event_id": 60, "ticker": "XOM",  "benchmark": "SPY",
     "mechanism_family": "supply_shock",
     "headline": "h60", "event_date": "2026-04-08",
     "horizon": 5, "sar": 1.0, "p_value": 0.04, "fdr_q": 0.08},
    {"event_id": 73, "ticker": "XOM",  "benchmark": "SPY",
     "mechanism_family": "supply_shock",
     "headline": "h73", "event_date": "2026-04-06",
     "horizon": 5, "sar": 1.0, "p_value": 0.04, "fdr_q": 0.08},
)


def _summary_payload() -> dict[str, Any]:
    return {
        "repaired_clean_event_ids": [r["event_id"]
                                     for r in _REPAIRED_COHORT_FIXTURE],
        "events_evaluated":         len(_REPAIRED_COHORT_FIXTURE),
        "records_count":            len(_REPAIRED_COHORT_FIXTURE),
        "significant_count":        0,
        "top_abs_sar":              [dict(r)
                                     for r in _REPAIRED_COHORT_FIXTURE],
        "by_event_verdict":         {},
        "limitations":              [],
        "recommended_next_action":  "n/a",
    }


def _empty_expansion_payload() -> dict[str, Any]:
    return {
        "candidate_count":         0,
        "groups":                  {},
        "top_candidates":          [],
        "estimated_repair_yield":  {
            "conservative_estimate": 0,
            "optimistic_estimate":   0,
            "estimate_basis":        "smoke fixture",
        },
        "recommended_next_action": "n/a",
    }


def _empty_short_horizon_payload() -> dict[str, Any]:
    return {
        "ok":                            True,
        "excluded_reviewed_event_ids":   [],
        "reviewed_exclusion_set_count":  0,
        "excluded_reviewed_count":       0,
        "total_short_ready":             0,
        "delta_vs_full_ready":           0,
        "total_candidates_after_filter": 0,
        "candidates":                    [],
        "recommended_next_action":       "n/a",
    }


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_curated_candidate_stage_smoke() -> dict[str, Any]:
    """Drive the curated staging API end-to-end against a TestClient
    and return the smoke envelope.  Reads + writes go through the
    redirected test DB; the live archive ``events`` table is captured
    before and after to surface ``live_db_unchanged``."""
    errors:   list[str] = []
    warnings: list[str] = []

    # Lazy imports — keep heavy dependencies (FastAPI, the route
    # module) off the import path so importing this script for a
    # CLI ``--help`` is cheap.
    import db as _db
    import api as _api
    from routes import curated as _curated_routes
    from fastapi.testclient import TestClient

    # Swap ``db.DB_FILE`` to a fresh temp path for the duration of
    # the smoke so neither preview / stage / status nor any
    # transitively-touched code can mutate the live archive.  The
    # live ``events.db`` is hashed before/after as belt-and-suspenders
    # — ``live_db_unchanged`` reflects the live file, not the temp DB.
    live_db_path  = str(_db.DB_FILE)
    live_count_before = _events_table_count(live_db_path)
    temp_db_path = os.path.join(
        tempfile.gettempdir(),
        f"curated_stage_smoke_{uuid.uuid4().hex}.db",
    )
    saved_db_file = _db.DB_FILE
    _db.DB_FILE = temp_db_path
    warnings.append(f"Smoke ran against temp DB at {temp_db_path}")

    preview_count: int = 0
    staged_count:  int = 0
    status_counts: dict[str, int] = {}
    staged_event_ids: list[int] = []

    try:
        try:
            _db.init_db()
        except Exception as e:  # noqa: BLE001 — operator-visible
            errors.append(f"init_db failed: {e}")
            return _envelope(
                preview_count=0, staged_count=0, status_counts={},
                staged_event_ids=[], live_db_unchanged=True,
                errors=errors, warnings=warnings,
            )

        summary = _summary_payload()
        expansion = _empty_expansion_payload()
        short_h   = _empty_short_horizon_payload()

        client = TestClient(_api.app)
        try:
            with patch.object(
                _curated_routes, "_run_repaired_cohort_summary",
                return_value=summary,
            ), patch.object(
                _curated_routes, "_run_expansion_report",
                return_value=expansion,
            ), patch.object(
                _curated_routes, "_run_short_horizon_packet",
                return_value=short_h,
            ):
                preview_resp = client.get(
                    "/curated/candidates/preview",
                )
                if preview_resp.status_code != 200:
                    errors.append(
                        f"preview returned {preview_resp.status_code}: "
                        f"{preview_resp.text[:200]}"
                    )
                else:
                    preview_count = int(preview_resp.json().get(
                        "preview_count", 0))

                stage_resp = client.post(
                    "/curated/candidates/stage",
                    params={"confirm": "true"},
                )
                if stage_resp.status_code != 200:
                    errors.append(
                        f"stage returned {stage_resp.status_code}: "
                        f"{stage_resp.text[:200]}"
                    )
                else:
                    staged_count = int(stage_resp.json().get(
                        "staged_count", 0))

                status_resp = client.get("/curated/candidates/status")
                if status_resp.status_code != 200:
                    errors.append(
                        f"status returned {status_resp.status_code}: "
                        f"{status_resp.text[:200]}"
                    )
                else:
                    body = status_resp.json()
                    raw = body.get("counts_by_status") or {}
                    status_counts = {
                        str(k): int(v) for k, v in raw.items()
                        if isinstance(v, (int, float))
                        and not isinstance(v, bool)
                    }
        finally:
            client.close()

        staged_event_ids = _staged_event_ids(temp_db_path)
    finally:
        # Restore the live DB_FILE pointer and remove the temp DB so
        # the smoke leaves no on-disk residue.  Restoration must
        # happen even when the body raised — do it in finally.
        _db.DB_FILE = saved_db_file
        try:
            if os.path.exists(temp_db_path):
                os.unlink(temp_db_path)
        except OSError as e:
            warnings.append(f"failed to remove temp DB {temp_db_path}: {e}")

    live_count_after = _events_table_count(live_db_path)
    live_db_unchanged = live_count_after == live_count_before
    if not live_db_unchanged:
        errors.append(
            f"LIVE events table row count changed during smoke: "
            f"before={live_count_before}, after={live_count_after}"
        )

    return _envelope(
        preview_count=preview_count,
        staged_count=staged_count,
        status_counts=status_counts,
        staged_event_ids=staged_event_ids,
        live_db_unchanged=live_db_unchanged,
        errors=errors, warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _events_table_count(db_path: str) -> int:
    """Row count of the live ``events`` table.  Tolerant of a missing
    table — that's indistinguishable from an empty table for the
    smoke's invariant."""
    conn = sqlite3.connect(db_path)
    try:
        try:
            return conn.execute(
                "SELECT COUNT(*) FROM events"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.close()


def _staged_event_ids(db_path: str) -> list[int]:
    conn = sqlite3.connect(db_path)
    try:
        try:
            rows = conn.execute(
                "SELECT source_event_id FROM curated_candidates "
                "ORDER BY source_event_id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.close()
    return [int(r[0]) for r in rows
            if isinstance(r[0], int) or
            (isinstance(r[0], str) and r[0].lstrip("-").isdigit())]


def _envelope(
    *, preview_count: int, staged_count: int,
    status_counts: dict[str, int],
    staged_event_ids: list[int],
    live_db_unchanged: bool,
    errors: list[str], warnings: list[str],
) -> dict[str, Any]:
    return {
        "preview_count":     preview_count,
        "staged_count":      staged_count,
        "status_counts":     status_counts,
        "staged_event_ids":  staged_event_ids,
        "live_db_unchanged": live_db_unchanged,
        "errors":            errors,
        "warnings":          warnings,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated candidate stage smoke", ""]
    lines.append(f"Preview count:       {report['preview_count']}")
    lines.append(f"Staged count:        {report['staged_count']}")
    lines.append(f"Staged event_ids:    {report['staged_event_ids']}")
    lines.append(f"Live DB unchanged:   {report['live_db_unchanged']}")
    counts = report.get("status_counts") or {}
    if counts:
        lines.append("")
        lines.append("Status counts:")
        for k in sorted(counts):
            lines.append(f"  {k:<24} {counts[k]}")
    if report.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in report["warnings"]:
            lines.append(f"  - {w}")
    if report.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in report["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Curated candidate staging smoke for the repaired cohort. "
            "Runs the API-backed preview + stage + status path against "
            "a TEST/TEMP DB only — never mutates live archive events. "
            "Conservative wording: staged candidates, not validated."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_curated_candidate_stage_smoke()
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
