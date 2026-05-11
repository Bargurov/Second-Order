#!/usr/bin/env python3
"""Deterministic test-fixture worksheet generator for short-horizon
review tooling.

Builds a small in-memory worksheet (a handful of yes / no / pending
rows) in the canonical 16-column schema emitted by
``scripts.short_horizon_review_worksheet`` so the apply and validate
smoke workflows can exercise their CSV-consuming paths without
depending on the operator-filled
``artifacts/short_horizon_review_top10.csv``.

Test / support utility only
---------------------------

* Never reads or rewrites ``artifacts/short_horizon_review_top10.csv``.
* No DB opens.  No FastAPI surface.  No provider, ``market_check``,
  ``market_data``, ``price_cache``, LLM, or ``yfinance`` call.
* No filesystem writes unless ``--output PATH`` is passed.
* Default invocation emits a structured JSON preview to stdout; the
  ``--csv`` flag emits a CSV body whose header is the canonical
  16-column worksheet schema (LF line endings, no Windows CRLF).
* Rows are synthetic test fixtures (``event_id >= 999000``) so they
  cannot collide with archive rows by accident.
* Conservative wording — surfaced text, surfaced row content, and
  this docstring avoid the hype / certainty tokens shared with the
  validator and worksheet (see
  ``scripts.short_horizon_review_validator`` and
  ``scripts.short_horizon_review_worksheet`` for the canonical
  banned-token lists).  The fixture rows are review candidates only
  — never a claim about a real event.

The rendered CSV round-trips cleanly through
``scripts.short_horizon_review_validator.validate_review_worksheet``:
the canonical gate column is ``include_in_short_horizon_validation``,
``yes`` rows carry complete ``proposed_*`` fields with a direction in
``{up, down, neutral}``, ``no`` rows carry a non-blank
``exclude_reason``, and pending rows carry a blank gate.

Output contract (JSON)::

    {
      "ok":            True,
      "fixture_count": int,
      "include_count": int,
      "exclude_count": int,
      "pending_count": int,
      "columns":       [str, ...]    # 16 entries, canonical order
      "rows":          [dict, ...],  # each carries all 16 columns
    }

Usage::

    python scripts/short_horizon_review_fixture.py
    python scripts/short_horizon_review_fixture.py --json
    python scripts/short_horizon_review_fixture.py --csv
    python scripts/short_horizon_review_fixture.py --csv --output fixture.csv
    python scripts/short_horizon_review_fixture.py --json --output fixture.json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence


# Canonical 16-column worksheet schema.  Coupled to
# ``scripts.short_horizon_review_worksheet._WORKSHEET_COLUMNS`` and
# pinned by ``tests.test_short_horizon_review_fixture
# .TestSchemaCoupling``.
_WORKSHEET_COLUMNS: tuple[str, ...] = (
    "event_id",
    "headline",
    "event_date",
    "current_primary_ticker",
    "current_mechanism_family",
    "repair_type",
    "repair_priority",
    "operator_decision_needed",
    "reason_for_review",
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "include_in_short_horizon_validation",
    "exclude_reason",
    "operator_notes",
)


# Module-level fixture rows.  Distinct event_id values >= 999000 so a
# row can't be confused with a real archive row.  Headlines name the
# fixture explicitly; no banned token appears in any cell.
_FIXTURE_ROWS: tuple[dict[str, Any], ...] = (
    {
        "event_id":                            999001,
        "headline":                            "Synthetic test fixture row - bank capital relief candidate",
        "event_date":                          "2026-04-01",
        "current_primary_ticker":              "MS",
        "current_mechanism_family":            "none",
        "repair_type":                         "mechanism_family_only",
        "repair_priority":                     "high",
        "operator_decision_needed":            "bank_regulatory_capital_relief",
        "reason_for_review":                   "test fixture row; expected to land in the accepted bucket",
        "proposed_primary_ticker":             "MS",
        "proposed_benchmark_ticker":           "SPY",
        "proposed_mechanism_family":           "bank_regulatory_capital_relief",
        "predicted_direction":                 "up",
        "include_in_short_horizon_validation": "yes",
        "exclude_reason":                      "",
        "operator_notes":                      "synthetic fixture; test only",
    },
    {
        "event_id":                            999002,
        "headline":                            "Synthetic test fixture row - energy supply disruption candidate",
        "event_date":                          "2026-04-02",
        "current_primary_ticker":              "XOM",
        "current_mechanism_family":            "none",
        "repair_type":                         "mechanism_family_only",
        "repair_priority":                     "high",
        "operator_decision_needed":            "supply_mechanism_family",
        "reason_for_review":                   "test fixture row; expected to land in the accepted bucket",
        "proposed_primary_ticker":             "XOM",
        "proposed_benchmark_ticker":           "XLE",
        "proposed_mechanism_family":           "supply_mechanism_family",
        "predicted_direction":                 "down",
        "include_in_short_horizon_validation": "yes",
        "exclude_reason":                      "",
        "operator_notes":                      "synthetic fixture; test only",
    },
    {
        "event_id":                            999003,
        "headline":                            "Synthetic test fixture row - off-topic feature story",
        "event_date":                          "2026-04-03",
        "current_primary_ticker":              "AA",
        "current_mechanism_family":            "none",
        "repair_type":                         "mechanism_family_only",
        "repair_priority":                     "medium",
        "operator_decision_needed":            "supply_mechanism_family",
        "reason_for_review":                   "test fixture row; expected to land in the excluded bucket",
        "proposed_primary_ticker":             "",
        "proposed_benchmark_ticker":           "",
        "proposed_mechanism_family":           "",
        "predicted_direction":                 "",
        "include_in_short_horizon_validation": "no",
        "exclude_reason":                      "off-topic; no actionable mechanism in headline",
        "operator_notes":                      "synthetic fixture; test only",
    },
    {
        "event_id":                            999004,
        "headline":                            "Synthetic test fixture row - awaiting operator review",
        "event_date":                          "2026-04-04",
        "current_primary_ticker":              "CVX",
        "current_mechanism_family":            "none",
        "repair_type":                         "mechanism_family_only",
        "repair_priority":                     "low",
        "operator_decision_needed":            "supply_mechanism_family",
        "reason_for_review":                   "test fixture row; expected to land in the pending bucket",
        "proposed_primary_ticker":             "",
        "proposed_benchmark_ticker":           "",
        "proposed_mechanism_family":           "",
        "predicted_direction":                 "",
        "include_in_short_horizon_validation": "",
        "exclude_reason":                      "",
        "operator_notes":                      "",
    },
)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_fixture_rows() -> list[dict[str, Any]]:
    """Return a deterministic list of fixture worksheet rows.

    Each row carries every column in ``_WORKSHEET_COLUMNS`` so the
    downstream validator and apply parser can dispatch without
    falling back to defaults.  The returned list is a fresh copy —
    callers may mutate it without corrupting the module-level
    fixture.
    """
    return [dict(r) for r in _FIXTURE_ROWS]


def _bucket(gate: Any) -> str:
    if gate is None:
        return "pending"
    g = str(gate).strip().lower()
    if g == "yes":
        return "yes"
    if g == "no":
        return "no"
    return "pending"


def build_report() -> dict[str, Any]:
    rows = build_fixture_rows()
    include = sum(
        1 for r in rows
        if _bucket(r.get("include_in_short_horizon_validation")) == "yes"
    )
    exclude = sum(
        1 for r in rows
        if _bucket(r.get("include_in_short_horizon_validation")) == "no"
    )
    pending = sum(
        1 for r in rows
        if _bucket(r.get("include_in_short_horizon_validation")) == "pending"
    )
    return {
        "ok":            True,
        "fixture_count": len(rows),
        "include_count": include,
        "exclude_count": exclude,
        "pending_count": pending,
        "columns":       list(_WORKSHEET_COLUMNS),
        "rows":          rows,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def render_csv(rows: list[dict[str, Any]]) -> str:
    buf = io.StringIO()
    # LF line endings (no Windows CRLF) — matches the worksheet's
    # rendered CSV so the fixture is byte-compatible with the real
    # downstream CSV consumers.
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_WORKSHEET_COLUMNS)
    for r in rows:
        writer.writerow([_csv_cell(r.get(k)) for k in _WORKSHEET_COLUMNS])
    return buf.getvalue()


def render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Deterministic test-fixture worksheet generator for "
            "short-horizon review tooling.  Emits a few synthetic "
            "yes / no / pending rows in the canonical 16-column "
            "worksheet schema so apply and validate smoke workflows "
            "can exercise their CSV-consuming paths without the "
            "operator-filled worksheet on disk.  Test / support "
            "utility only — no DB writes, no provider call, no LLM, "
            "no FastAPI surface.  Conservative wording: surfaced "
            "rows are synthetic fixtures, not signals about real "
            "events."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", action="store_true",
        help="Emit a structured JSON preview (this is also the default).",
    )
    fmt.add_argument(
        "--csv", action="store_true",
        help=(
            "Emit a CSV body whose header is the canonical 16-column "
            "worksheet schema.  Line terminator is LF."
        ),
    )
    parser.add_argument(
        "--output", dest="output", default=None,
        help=(
            "Optional path to write the rendered fixture to.  When "
            "omitted, the rendered fixture is printed to stdout and "
            "no file is created."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = build_report()
    if args.csv:
        rendered = render_csv(report["rows"])
    else:
        # JSON is the default; ``--json`` is accepted for ergonomics.
        rendered = render_json(report) + "\n"

    if args.output is not None:
        Path(args.output).write_text(rendered, encoding="utf-8")
        return 0

    output.write(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
