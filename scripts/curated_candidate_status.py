#!/usr/bin/env python3
"""Read-only status report over the ``curated_candidates`` table.

Mirrors the ``GET /curated/candidates/status`` endpoint from
``routes/curated.py`` so an operator gets the same picture from the
CLI and the API.  The script is deliberately thin: it queries the
table, aggregates counts, and renders text or JSON.  No DB writes,
no provider calls, no LLM, no FastAPI app surface.

Output contract::

    {
      "ok":                          bool,
      "total":                       int,
      "counts_by_status":            {str: int},
      "counts_by_mechanism_family":  {str: int},
      "counts_by_ticker":            {str: int},
      "missing_field_counts":        {str: int},   # one entry per
                                                    # required field
      "errors":                      [str, ...],
    }

Conservative language only — nothing in this report is called
"validated".  The vocabulary is ``candidate``, ``staging``,
``draft``, ``needs_review``.

Usage::

    python scripts/curated_candidate_status.py
    python scripts/curated_candidate_status.py --json
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


# Required-field vocabulary mirrors routes/curated.py.  Kept duplicated
# (instead of imported) so this script stays free of FastAPI imports —
# the route module pulls in fastapi/pydantic at import time, which is
# heavier than the CLI needs.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_date",
    "headline",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
)


def _connect() -> sqlite3.Connection:
    import db as _db
    return _db.connect_db()


def compute_status() -> dict[str, Any]:
    """Aggregate counts over ``curated_candidates``.  Read-only."""
    errors: list[str] = []
    counts_by_status:           dict[str, int] = {}
    counts_by_mechanism_family: dict[str, int] = {}
    counts_by_ticker:           dict[str, int] = {}
    missing_field_counts:       dict[str, int] = {
        f: 0 for f in _REQUIRED_FIELDS
    }
    total = 0

    conn = _connect()
    try:
        try:
            rows = conn.execute(
                "SELECT status, mechanism_family, primary_ticker, "
                "validation_errors FROM curated_candidates"
            ).fetchall()
        except sqlite3.OperationalError as e:
            # Table not yet created — return an OK envelope with zero
            # counts so the operator sees "no candidates yet" rather
            # than a hard error.
            errors.append(f"curated_candidates table missing: {e}")
            rows = []
    finally:
        conn.close()

    for row in rows:
        total += 1
        status, family, ticker, errors_raw = row
        if isinstance(status, str) and status:
            counts_by_status[status] = counts_by_status.get(status, 0) + 1
        if isinstance(family, str) and family.strip():
            counts_by_mechanism_family[family] = (
                counts_by_mechanism_family.get(family, 0) + 1
            )
        if isinstance(ticker, str) and ticker.strip():
            counts_by_ticker[ticker] = counts_by_ticker.get(ticker, 0) + 1
        if isinstance(errors_raw, str) and errors_raw:
            try:
                err_list = json.loads(errors_raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                err_list = []
            if isinstance(err_list, list):
                for token in err_list:
                    if not isinstance(token, str):
                        continue
                    for f in _REQUIRED_FIELDS:
                        if f in token:
                            missing_field_counts[f] = (
                                missing_field_counts.get(f, 0) + 1
                            )
                            break

    return {
        "ok":                          not errors,
        "total":                       total,
        "counts_by_status":            counts_by_status,
        "counts_by_mechanism_family":  counts_by_mechanism_family,
        "counts_by_ticker":            counts_by_ticker,
        "missing_field_counts":        missing_field_counts,
        "errors":                      errors,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated candidate staging status", ""]
    lines.append(f"OK:                  {report['ok']}")
    lines.append(f"Total candidates:    {report['total']}")
    lines.append("")

    by_status = report.get("counts_by_status") or {}
    if by_status:
        lines.append("By status:")
        for k in sorted(by_status):
            lines.append(f"  {k:<24} {by_status[k]}")
        lines.append("")

    by_family = report.get("counts_by_mechanism_family") or {}
    if by_family:
        lines.append("By mechanism_family:")
        for k in sorted(by_family):
            lines.append(f"  {k:<32} {by_family[k]}")
        lines.append("")

    by_ticker = report.get("counts_by_ticker") or {}
    if by_ticker:
        lines.append("By primary_ticker:")
        for k in sorted(by_ticker):
            lines.append(f"  {k:<10} {by_ticker[k]}")
        lines.append("")

    missing = report.get("missing_field_counts") or {}
    if missing:
        lines.append("Missing field counts:")
        for k in sorted(missing):
            lines.append(f"  {k:<24} {missing[k]}")
        lines.append("")

    if report.get("errors"):
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
            "Read-only status report over curated_candidates.  Counts "
            "by status, mechanism family, primary ticker, and "
            "missing required fields.  Read-only — no DB writes, no "
            "provider calls, no LLM, no FastAPI app surface.  "
            "Conservative wording only: candidate, staging, draft, "
            "needs_review."
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
    report = compute_status()
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
