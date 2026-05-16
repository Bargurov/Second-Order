#!/usr/bin/env python3
"""Daily reviewed-candidate worksheet generator.

Emits a small operator-fillable worksheet — JSON envelope by
default, CSV with ``--csv`` — that the operator hand-fills with
1-3 manually reviewed Daily demo candidates.  Each filled row is
the source for a single
``analyzed_event_artifact_<candidate_id>.json`` the Daily artifact
gate reads under ``artifacts/`` (see
``scripts/daily_analyzed_event_artifact_emitter.py`` for the
downstream emitter).

Read-only by construction
-------------------------

* No DB reads, no DB writes.
* No ``yfinance``, ``market_data``, paid provider, LLM, or FastAPI
  surface (never imports ``api`` or ``routes.*``).
* No mutation of ``news_inbox.json``, the events DB, the news cache,
  or any existing artifact.  The default invocation has no
  filesystem side effect.  ``--output`` is the only way to write a
  file, and the script refuses to overwrite an existing path.
* No fuzzy or LLM-based headline matching.  The script does not
  source candidates from any provider, API, or LLM — every row is
  hand-filled by the operator.
* No ``candidate_id`` is auto-generated.  The ``candidate_id``
  column exists on every row but is blank by construction; the
  operator owns the allocation scheme.

Conservative wording
--------------------

Banned tokens in any prose this script emits: ``proof``, ``proven``,
``validated``, ``automatically``, ``alpha generated``, ``guaranteed``,
``correct ticker``.  The script never claims a row is validated,
proven, defensible, or worth including; the operator owns every
per-row judgment, including which rows the
``include_in_daily_section_c`` flag admits.

Worksheet columns (spec order)
------------------------------

  1. ``candidate_id``
  2. ``headline``
  3. ``event_date``
  4. ``mechanism_family``
  5. ``primary_ticker``
  6. ``benchmark_ticker``
  7. ``market_relevance``
  8. ``inclusion_reason``
  9. ``include_in_daily_section_c``
 10. ``operator_notes``

Output contract (JSON)::

    {
      "ok":                       bool,
      "artifact_type":            "daily_reviewed_candidate_worksheet",
      "generated_at":             str,   # ISO-8601 UTC timestamp
      "worksheet_columns":        [str, ...],     # 10 spec columns
      "worksheet_count":          int,            # = len(worksheet)
      "worksheet":                [
        {                                          # every value is ""
          "candidate_id":               "",
          "headline":                   "",
          "event_date":                 "",
          "mechanism_family":           "",
          "primary_ticker":             "",
          "benchmark_ticker":           "",
          "market_relevance":           "",
          "inclusion_reason":           "",
          "include_in_daily_section_c": "",
          "operator_notes":             "",
        },
        ...
      ],
      "instructions":             [str, ...],     # operator-facing
      "limitations":              [str, ...],
      "warnings":                 [str, ...],
      "errors":                   [str, ...],
      "recommended_next_action":  str,
    }

CSV output is the 10-column header followed by ``--rows`` blank
rows.  Lines terminate with ``\n`` (LF, not CRLF) regardless of
platform.

Usage
-----

    # JSON preview (default), one blank row:
    python scripts/daily_reviewed_candidate_worksheet.py
    python scripts/daily_reviewed_candidate_worksheet.py --json

    # CSV with three blank rows, written to a new file:
    python scripts/daily_reviewed_candidate_worksheet.py --csv --rows 3 \\
        --output artifacts/daily_reviewed_candidate_worksheet.csv
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


_ARTIFACT_TYPE: str = "daily_reviewed_candidate_worksheet"

# Field order matches the spec exactly and is reused as the CSV
# header.  Tests pin this tuple.
_WORKSHEET_COLUMNS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "include_in_daily_section_c",
    "operator_notes",
)

_DEFAULT_ROWS: int = 1

# Worksheet is demo-scoped (1-3 reviewed candidates).  The cap
# keeps the script from emitting a worksheet large enough to be
# mistaken for a backfill batch surface; the operator can re-run
# the script for additional batches.
_MAX_ROWS: int = 10


_INSTRUCTIONS: tuple[str, ...] = (
    "Hand-fill each row with one operator-reviewed Daily demo "
    "candidate.  This script does not source candidates from any "
    "provider, API, or LLM, and does not auto-generate "
    "candidate_id values.",
    "candidate_id is a stable token the operator chooses (e.g. "
    "20260512_opec_supply_cut_001).  The script never assigns or "
    "derives a candidate_id; the column is blank on every row by "
    "construction.",
    "headline should be the operator-quoted headline from a "
    "public source the operator can re-fetch by hand.  The script "
    "does not fetch URLs.",
    "event_date should be ISO YYYY-MM-DD and the US-equity session "
    "in which the event was first publicly priced.",
    "mechanism_family is the operator-reviewed family label (e.g. "
    "supply_shock, demand_destruction, regulatory_constraint).  "
    "The downstream artifact gate refuses any row whose "
    "mechanism_family is blank or the literal 'none' sentinel.",
    "primary_ticker and benchmark_ticker are the operator-reviewed "
    "single-name ticker and benchmark for this candidate.  Both "
    "must be non-empty for the downstream artifact gate to admit "
    "the card.",
    "market_relevance is an operator-supplied number in [0.0, 1.0] "
    "captured at review time; the downstream gate does not enforce "
    "the value, but the operator records it as the audit trail.",
    "inclusion_reason is a free-form one-line note describing why "
    "this candidate is being included in the demo set.  The "
    "operator owns the content; the script does not score, grade, "
    "or screen rows.",
    "include_in_daily_section_c accepts 'yes' / 'true' (case-"
    "insensitive) when the row is ready to emit.  Any other value "
    "(or blank) leaves the row out of the next emitter run.",
    "operator_notes is free-form text — assumptions, follow-up "
    "questions, or watch items the operator wants surfaced on the "
    "audit trail.",
)


_LIMITATIONS: tuple[str, ...] = (
    "this worksheet does not source candidates from any API, "
    "provider, or LLM; every row is hand-entered by the operator "
    "and the script makes no judgment about row quality.",
    "rows are not scored, graded, or screened by this script — "
    "the downstream emitter "
    "(scripts/daily_analyzed_event_artifact_emitter.py) is what "
    "writes the per-row analyzed_event_artifact files the Daily "
    "gate reads.",
    "include_in_daily_section_c = 'yes' is an operator intent "
    "flag only.  This worksheet does not stage any artifact; the "
    "operator hands the filled CSV to the emitter as a separate "
    "step.",
    "candidate_id allocation is an operator decision; this "
    "worksheet refuses to invent or derive candidate_ids and "
    "leaves the column blank on every row.",
)


_RECOMMENDED_NEXT_ACTION: str = (
    "Hand-fill rows in the JSON preview or open the CSV in a "
    "spreadsheet editor and fill rows by hand.  When ready, hand "
    "the filled CSV to "
    "scripts/daily_analyzed_event_artifact_emitter.py to emit one "
    "analyzed_event_artifact_<candidate_id>.json per included row."
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


def build_daily_reviewed_candidate_worksheet(
    *,
    rows:          int = _DEFAULT_ROWS,
    output_path:   str | None = None,
    output_format: str = "json",
    generated_at:  str | None = None,
) -> dict[str, Any]:
    """Build the Daily reviewed-candidate worksheet envelope.

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
            "Daily reviewed-candidate worksheet generator.  Emits a "
            "blank 10-column worksheet (JSON preview by default, CSV "
            "with --csv) the operator hand-fills with 1-3 reviewed "
            "Daily demo candidates.  No DB, no provider, no "
            "yfinance, no LLM, no FastAPI.  No existing artifact is "
            "read or mutated; --output is the only filesystem side "
            "effect, and the script refuses to overwrite an existing "
            "file.  candidate_id is operator-filled — the script "
            "never auto-generates a value."
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
    report = build_daily_reviewed_candidate_worksheet(
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
    "build_daily_reviewed_candidate_worksheet",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
