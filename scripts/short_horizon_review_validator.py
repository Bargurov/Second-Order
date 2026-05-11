#!/usr/bin/env python3
"""Read-only validator for a manually reviewed short-horizon worksheet.

Operator workflow: the short-horizon review queue surfaces candidate
events; the operator hand-fills a CSV worksheet committing to either
include / exclude / defer each row.  This script reads that CSV and
checks the operator's decisions for shape — gate values, required
fields per dispatch bucket, ticker formats, direction vocabulary —
so a bad worksheet can't contaminate the temp-apply smoke that
consumes it downstream.

Read-only by construction
-------------------------

* No DB opens, no provider call, no LLM, no FastAPI surface.
* No mutation of the worksheet on disk.
* Row dicts surfaced in the output carry the operator's RAW values
  (no whitespace strip, no case normalisation) so future tooling can
  re-derive whatever it needs without losing fidelity.
* The validator never claims any candidate is fit for production
  signal use — surfaced rows are "accepted for downstream temp-apply
  consumption only," NOT a verdict on the underlying event.

Validation rules
----------------

The worksheet header must include these columns:

  * ``include_in_short_horizon_validation`` — the operator gate.
  * ``proposed_primary_ticker``
  * ``proposed_benchmark_ticker``
  * ``proposed_mechanism_family``
  * ``predicted_direction``
  * ``exclude_reason``

Other columns (``event_id``, ``headline`` etc) ride through untouched.

Per-row dispatch — values are stripped + lowercased only for the
dispatch decision; the raw value stays in the surfaced row dict:

  * ``yes`` → accepted bucket.  Requires non-blank
    ``proposed_primary_ticker``, ``proposed_benchmark_ticker``,
    ``proposed_mechanism_family``, ``predicted_direction``.  Both
    tickers must match the ticker-symbol shape (see below).
    ``predicted_direction`` must be one of {up, down, neutral}.
  * ``no`` → excluded bucket.  Requires non-blank ``exclude_reason``.
  * ``""`` (or whitespace only) → pending bucket.  No required
    fields; the worksheet is legitimately incomplete.
  * Anything else → per-row error.

Ticker format: ``^[A-Z][A-Z0-9.\\-]{0,9}$`` — starts with an
uppercase letter, may contain digits, ``.`` or ``-``, length 1-10.
Lowercase, spaces, prose, or longer strings reject.

Output contract (JSON / dict)::

    {
      "ok":              bool,
      "worksheet_path":  str | None,
      "total_rows":      int,
      "include_count":   int,
      "exclude_count":   int,
      "pending_count":   int,
      "errors":          [str, ...],
      "warnings":        [str, ...],
      "accepted_rows":   [dict, ...],
      "excluded_rows":   [dict, ...],
      "pending_rows":    [dict, ...],
    }

``ok`` is True iff there are no structural errors AND no per-row
errors.  Pending rows do NOT flip ``ok`` to False — they are an
expected mid-review state.

Conservative wording — banned tokens in any surfaced text:
``validated``, ``proves``, ``proof``, ``alpha``, ``automatic``.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_GATE_FIELD: str = "include_in_short_horizon_validation"

_REQUIRED_COLUMNS: tuple[str, ...] = (
    _GATE_FIELD,
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
    "exclude_reason",
)

_YES_REQUIRED_FIELDS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
)

_VALID_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "neutral"})

_TICKER_FIELDS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
)

# Symbol-or-ETF shape.  Starts with an uppercase letter, then up to
# nine more uppercase letters / digits / ``.`` / ``-``.  Covers F, T,
# MS, SPY, BDRY, BRK.B, BRK-A.  Rejects lowercase, prose, spaces,
# overly long strings.
_TICKER_RE: re.Pattern[str] = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def validate_review_worksheet(
    worksheet_path: str | None,
) -> dict[str, Any]:
    """Validate a reviewed short-horizon worksheet CSV.

    See module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    accepted_rows: list[dict[str, Any]] = []
    excluded_rows: list[dict[str, Any]] = []
    pending_rows:  list[dict[str, Any]] = []

    if worksheet_path is None or str(worksheet_path).strip() == "":
        errors.append("--worksheet path is required")
        return _empty_result(worksheet_path, errors, warnings)

    path = Path(worksheet_path)
    if not path.exists():
        errors.append(f"worksheet file does not exist: {worksheet_path}")
        return _empty_result(worksheet_path, errors, warnings)

    try:
        with open(path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [c for c in _REQUIRED_COLUMNS if c not in fieldnames]
            if missing:
                errors.append(
                    f"worksheet missing required columns: "
                    f"{', '.join(missing)}"
                )
                return _empty_result(worksheet_path, errors, warnings)
            rows = [dict(r) for r in reader]
    except OSError as e:
        errors.append(f"failed to read worksheet {worksheet_path}: {e}")
        return _empty_result(worksheet_path, errors, warnings)

    if not rows:
        errors.append(
            "worksheet has no data rows — nothing to review"
        )
        return _empty_result(worksheet_path, errors, warnings)

    for idx, row in enumerate(rows):
        gate_raw = row.get(_GATE_FIELD, "")
        gate = (gate_raw or "").strip().lower()

        if gate == "":
            pending_rows.append(dict(row))
            continue

        if gate == "no":
            reason = (row.get("exclude_reason") or "").strip()
            if not reason:
                errors.append(_row_err(
                    idx, row,
                    "field 'exclude_reason' must be non-blank for "
                    "'no' rows",
                ))
                continue
            excluded_rows.append(dict(row))
            continue

        if gate == "yes":
            row_errs = _validate_yes_row(idx, row)
            if row_errs:
                errors.extend(row_errs)
                continue
            accepted_rows.append(dict(row))
            continue

        errors.append(_row_err(
            idx, row,
            f"field '{_GATE_FIELD}' must be 'yes', 'no', or blank "
            f"— got {gate_raw!r}",
        ))

    include_count = len(accepted_rows)
    exclude_count = len(excluded_rows)
    pending_count = len(pending_rows)
    total_rows    = len(rows)

    return {
        "ok":             not errors,
        "worksheet_path": str(worksheet_path),
        "total_rows":     total_rows,
        "include_count":  include_count,
        "exclude_count":  exclude_count,
        "pending_count":  pending_count,
        "errors":         errors,
        "warnings":       warnings,
        "accepted_rows":  accepted_rows,
        "excluded_rows":  excluded_rows,
        "pending_rows":   pending_rows,
    }


def _validate_yes_row(idx: int, row: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    for field in _YES_REQUIRED_FIELDS:
        value = (row.get(field) or "")
        if not isinstance(value, str) or not value.strip():
            errs.append(_row_err(
                idx, row,
                f"field {field!r} must be non-blank for 'yes' rows",
            ))

    direction = (row.get("predicted_direction") or "").strip().lower()
    if direction and direction not in _VALID_DIRECTIONS:
        errs.append(_row_err(
            idx, row,
            f"field 'predicted_direction' must be one of "
            f"{sorted(_VALID_DIRECTIONS)} — got "
            f"{row.get('predicted_direction')!r}",
        ))

    for field in _TICKER_FIELDS:
        value = (row.get(field) or "").strip()
        if not value:
            continue
        if not _TICKER_RE.match(value):
            errs.append(_row_err(
                idx, row,
                f"field {field!r} must be an uppercase ticker symbol "
                f"(1-10 chars, A-Z / 0-9 / '.' / '-'; no spaces, no "
                f"prose) — got {value!r}",
            ))

    return errs


def _row_err(idx: int, row: dict[str, Any], msg: str) -> str:
    """Prefix a per-row error with the row's identifier."""
    ev_id = row.get("event_id")
    if ev_id is not None and str(ev_id).strip():
        return f"row {idx} (event_id={ev_id}): {msg}"
    return f"row {idx}: {msg}"


def _empty_result(
    worksheet_path: str | None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok":             False,
        "worksheet_path": (
            str(worksheet_path) if worksheet_path is not None else None
        ),
        "total_rows":     0,
        "include_count":  0,
        "exclude_count":  0,
        "pending_count":  0,
        "errors":         errors,
        "warnings":       warnings,
        "accepted_rows":  [],
        "excluded_rows":  [],
        "pending_rows":   [],
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Short-horizon review worksheet validator", ""]
    lines.append(f"OK:               {report['ok']}")
    lines.append(f"Worksheet:        {report['worksheet_path']}")
    lines.append(f"Total rows:       {report['total_rows']}")
    lines.append(f"Include count:    {report['include_count']}")
    lines.append(f"Exclude count:    {report['exclude_count']}")
    lines.append(f"Pending count:    {report['pending_count']}")
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
            "Read-only validator for a manually reviewed short-"
            "horizon worksheet CSV.  Checks gate values, required "
            "fields per bucket, ticker formats, and direction "
            "vocabulary so a malformed worksheet cannot contaminate "
            "the downstream temp-apply smoke.  No DB writes, no "
            "provider, no LLM, no FastAPI.  Conservative wording: "
            "surfaced rows are accepted for downstream consumption "
            "only — never a verdict on the underlying event."
        ),
    )
    parser.add_argument(
        "--worksheet", dest="worksheet", required=True,
        help="Path to the reviewed short-horizon worksheet CSV.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of compact text.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = validate_review_worksheet(args.worksheet)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
