#!/usr/bin/env python3
"""Manual curated event intake worksheet generator.

Emits a blank worksheet — JSON envelope by default, CSV with
``--csv`` — that the operator hand-fills with high-quality
historical events for cohort expansion beyond the current pilot.
This script never sources events from a provider, LLM, or API.  It
never reads or writes any existing artifact.  Every row it surfaces
is empty by construction; the operator is the only source of row
content.

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, ``price_cache.fetch_*``, LLM, or
  paid provider call.  No network access.
* No FastAPI surface — never imports ``api`` or ``routes.*``.
* No existing artifact is read or mutated.  The default invocation
  has no filesystem side effect.  ``--output`` is the only way to
  write a file, and the script refuses to overwrite an existing
  path.

Worksheet columns (spec order)
------------------------------

  1. ``candidate_id``
  2. ``event_date``
  3. ``headline``
  4. ``source_url``
  5. ``event_family``
  6. ``mechanism_family``
  7. ``primary_ticker``
  8. ``benchmark_ticker``
  9. ``predicted_direction``
 10. ``horizon_focus``
 11. ``why_this_event_is_defensible``
 12. ``what_would_falsify``
 13. ``include_in_validation``
 14. ``exclude_reason``
 15. ``operator_notes``

Output contract (JSON)::

    {
      "ok":                       bool,
      "artifact_type":            "manual_event_intake_worksheet",
      "generated_at":             str,   # ISO-8601 UTC timestamp
      "worksheet_columns":        [str, ...],     # 15 spec columns
      "worksheet_count":          int,            # = len(worksheet)
      "worksheet":                [
        {                                          # every value is ""
          "candidate_id":                  "",
          "event_date":                    "",
          "headline":                      "",
          "source_url":                    "",
          "event_family":                  "",
          "mechanism_family":              "",
          "primary_ticker":                "",
          "benchmark_ticker":              "",
          "predicted_direction":           "",
          "horizon_focus":                 "",
          "why_this_event_is_defensible":  "",
          "what_would_falsify":            "",
          "include_in_validation":         "",
          "exclude_reason":                "",
          "operator_notes":                "",
        },
        ...
      ],
      "instructions":             [str, ...],     # operator-facing
      "limitations":              [str, ...],
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

CSV output is the 15-column header followed by ``--rows`` blank
rows.  Lines terminate with ``\n`` (LF, not CRLF) regardless of
platform.

Conservative wording
--------------------

Banned tokens in any prose the script emits: ``proof``, ``proven``,
``validated``, ``automatically``, ``alpha generated``,
``guaranteed``, ``correct ticker``.  The script never claims a row
is validated, significant, defensible, or worth including; the
operator owns every per-row judgment.

Usage::

    # JSON preview (default), one blank row:
    python scripts/manual_event_intake_worksheet.py
    python scripts/manual_event_intake_worksheet.py --json

    # CSV with five blank rows, written to a new file:
    python scripts/manual_event_intake_worksheet.py --csv --rows 5 \\
        --output artifacts/manual_event_intake_worksheet.csv
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import io
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_ARTIFACT_TYPE: str = "manual_event_intake_worksheet"

# Field order matches the spec exactly and is reused as the CSV
# header.  Tests pin this tuple.
_WORKSHEET_COLUMNS: tuple[str, ...] = (
    "candidate_id",
    "event_date",
    "headline",
    "source_url",
    "event_family",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "predicted_direction",
    "horizon_focus",
    "why_this_event_is_defensible",
    "what_would_falsify",
    "include_in_validation",
    "exclude_reason",
    "operator_notes",
)

_DEFAULT_ROWS: int = 1
_MAX_ROWS:     int = 100


_INSTRUCTIONS: tuple[str, ...] = (
    "Hand-fill each row with a single historical event the operator "
    "can defend on the public record.  This script does not source "
    "events from any provider, API, or LLM.",
    "candidate_id should be a stable token the operator chooses "
    "(e.g. mn-001, mn-002) so the row survives reorderings; the "
    "script does not assign candidate_ids.",
    "event_date should be ISO YYYY-MM-DD and the US-equity session "
    "in which the event was first publicly priced.",
    "source_url must be a public reference (news article, official "
    "release, government record) the operator can re-fetch; the "
    "script does not fetch URLs.",
    "predicted_direction is the operator's a priori call before any "
    "validation runs — typical values are 'up', 'down', or 'flat'.  "
    "Leave blank when no directional call is being made.",
    "horizon_focus is a free-form short label for the operator's "
    "expected horizon (for example, '1bd', '5bd', '20bd').  The "
    "downstream pipeline parses this when the row is staged.",
    "include_in_validation accepts 'yes' (queue for sensitivity), "
    "'no' (excluded, with a non-empty exclude_reason), or blank "
    "(deferred until the operator decides).",
    "why_this_event_is_defensible and what_would_falsify are free-"
    "form text the operator owns — the script makes no judgment "
    "about whether a row is defensible or falsifiable.",
)


_LIMITATIONS: tuple[str, ...] = (
    "this worksheet does not source events from any API, provider, "
    "or LLM; every row is hand-entered by the operator and the "
    "script makes no judgment about row quality.",
    "rows are not scored, graded, or screened by this script — "
    "downstream pipelines (preflight, sensitivity, review-queue) "
    "do that work on the rows the operator stages.",
    "this is a separate intake step — operators must not paste "
    "rows into the existing short_horizon or curated worksheets; "
    "those worksheets carry their own row schemas.",
    "include_in_validation = 'yes' is an operator intent flag only; "
    "it does not run any downstream validation or stage the row "
    "into a cohort.",
)


_RECOMMENDED_NEXT_ACTION: str = (
    "Hand-fill rows in the JSON preview or open the CSV in a "
    "spreadsheet editor and fill rows by hand.  When ready, hand "
    "the filled CSV off to the curated-event intake review for "
    "stage validation.  This script does not stage rows."
)


# ---------------------------------------------------------------------------
# Patchable seam — tests patch this to pin the timestamp.
# ---------------------------------------------------------------------------


def _utcnow_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ",
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def build_manual_event_intake_worksheet(
    *,
    rows:         int = _DEFAULT_ROWS,
    output_path:  str | None = None,
    output_format: str = "json",
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build the manual-intake worksheet envelope.

    See module docstring for the full output contract.

    The script never reads any existing artifact.  Returns an
    envelope describing the worksheet shape and N blank rows.  When
    ``output_path`` is supplied, the resulting JSON or CSV is
    persisted to that path — but only if the path does not already
    exist (the script refuses to mutate an existing file).
    """
    errors:   list[str] = []
    warnings: list[str] = []

    rows_clean = _clamp_rows(rows, warnings=warnings)

    worksheet = [_blank_row() for _ in range(rows_clean)]

    envelope: dict[str, Any] = {
        "ok":                       True,
        "artifact_type":            _ARTIFACT_TYPE,
        "generated_at":             generated_at or _utcnow_iso(),
        "worksheet_columns":        list(_WORKSHEET_COLUMNS),
        "worksheet_count":          len(worksheet),
        "worksheet":                worksheet,
        "instructions":             list(_INSTRUCTIONS),
        "limitations":              list(_LIMITATIONS),
        "warnings":                 warnings,
        "errors":                   errors,
        "recommended_next_action":  _RECOMMENDED_NEXT_ACTION,
    }

    if output_path:
        write_err = _write_output(
            envelope=envelope,
            output_path=output_path,
            output_format=output_format,
        )
        if write_err:
            envelope["errors"].append(write_err)
            envelope["ok"] = False

    return envelope


def _blank_row() -> dict[str, str]:
    """Return one blank worksheet row — every value is an empty
    string, in spec column order."""
    return {col: "" for col in _WORKSHEET_COLUMNS}


def _clamp_rows(rows: Any, *, warnings: list[str]) -> int:
    """Coerce ``rows`` to a non-negative int in ``[0, _MAX_ROWS]``.

    Out-of-range values surface a warning and round to the nearest
    valid boundary; non-integer values fall back to ``_DEFAULT_ROWS``
    and surface a warning.  The function never raises — operators
    should be able to inspect the envelope to learn why their value
    was rejected.
    """
    if isinstance(rows, bool):
        warnings.append(
            f"--rows value was a bool; falling back to default "
            f"({_DEFAULT_ROWS})"
        )
        return _DEFAULT_ROWS
    if not isinstance(rows, int):
        warnings.append(
            f"--rows value was not an int; falling back to default "
            f"({_DEFAULT_ROWS})"
        )
        return _DEFAULT_ROWS
    if rows < 0:
        warnings.append(
            f"--rows must be non-negative; received {rows!r}, "
            f"clamping to 0"
        )
        return 0
    if rows > _MAX_ROWS:
        warnings.append(
            f"--rows capped at {_MAX_ROWS}; received {rows!r}"
        )
        return _MAX_ROWS
    return rows


# ---------------------------------------------------------------------------
# Output-file persistence
# ---------------------------------------------------------------------------


def _write_output(
    *,
    envelope:      dict[str, Any],
    output_path:   str,
    output_format: str,
) -> str | None:
    """Persist the envelope to disk in the requested format.

    Returns ``None`` on success, or a single error string when
    something prevents the write.  Refuses to overwrite an existing
    file — the spec forbids mutating existing artifacts, so the
    operator must remove the prior file or pick a new path.
    """
    target = Path(output_path)
    if target.exists():
        return (
            f"refusing to overwrite existing path: {output_path}.  "
            f"Pick a new path or remove the file by hand before "
            f"re-running."
        )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return f"failed to create parent directory for {output_path}: {exc}"

    try:
        with target.open("w", encoding="utf-8", newline="") as fh:
            if output_format == "csv":
                fh.write(_render_csv(envelope))
            else:
                fh.write(_render_json(envelope))
                fh.write("\n")
    except OSError as exc:
        return f"failed to write --output {output_path}: {exc}"
    return None


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_csv(report: dict[str, Any]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_WORKSHEET_COLUMNS)
    for row in report.get("worksheet") or []:
        if not isinstance(row, dict):
            continue
        writer.writerow([_csv_cell(row.get(c)) for c in _WORKSHEET_COLUMNS])
    return buf.getvalue()


def _csv_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Manual curated event intake worksheet generator.  "
            "Emits a blank 15-column worksheet (JSON preview by "
            "default, CSV with --csv) the operator hand-fills.  "
            "No DB, no provider, no yfinance, no LLM, no FastAPI.  "
            "No existing artifact is read or mutated; --output is "
            "the only filesystem side effect, and it refuses to "
            "overwrite an existing file."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json", dest="json_flag", action="store_true",
        help="Emit structured JSON (this is also the default).",
    )
    fmt.add_argument(
        "--csv", dest="csv_flag", action="store_true",
        help=(
            f"Emit a CSV worksheet with the "
            f"{len(_WORKSHEET_COLUMNS)} spec columns.  Rows "
            f"terminate with \\n."
        ),
    )
    parser.add_argument(
        "--rows", dest="rows", type=int, default=_DEFAULT_ROWS,
        help=(
            f"Number of blank rows to emit (default "
            f"{_DEFAULT_ROWS}, capped at {_MAX_ROWS}).  Use 0 to "
            f"emit only the header (CSV) or an empty worksheet "
            f"list (JSON)."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the worksheet to.  Refuses to "
            "overwrite an existing file.  When omitted, the script "
            "prints to stdout and has no filesystem side effect."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    fmt = "csv" if args.csv_flag else "json"
    report = build_manual_event_intake_worksheet(
        rows=int(args.rows),
        output_path=args.output_path,
        output_format=fmt,
    )

    if fmt == "csv":
        output.write(_render_csv(report))
    else:
        print(_render_json(report), file=output)

    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_manual_event_intake_worksheet",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
