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
import re
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
# Per-row analyzed-event artifact emission
# ---------------------------------------------------------------------------
#
# A filled worksheet row carrying a candidate_id can be persisted as
# ``analyzed_event_artifact_<candidate_id>.json`` so the Daily Section C
# artifact gate (routes/daily_artifact_gate.py) can match the row to
# the on-disk artifact at promotion time.  The emitter only writes when
# both --emit-artifacts and --output-dir are passed; default behavior
# remains read-only with zero filesystem side effects.


_PER_ROW_ARTIFACT_TYPE: str = "analyzed_event_artifact"

# Field order pinned on every emitted per-row artifact body.  Mirrors
# the schema scripts/daily_analyzed_event_artifact_emitter.py emits so
# the Daily gate sees the same shape regardless of which emitter wrote
# the artifact.
_ARTIFACT_BODY_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "artifact_type",
)

# candidate_id must be a safe filename component.  Allow alphanumerics,
# underscore, hyphen, and dot.  Anything else is rejected so that an
# operator-supplied id cannot escape ``output_dir`` via path traversal.
_VALID_CANDIDATE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


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
    rows:           int = _DEFAULT_ROWS,
    output_path:    str | None = None,
    output_format:  str = "json",
    generated_at:   str | None = None,
    emit_artifacts: bool = False,
    output_dir:     str | None = None,
    worksheet_rows: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the manual-intake worksheet envelope.

    See module docstring for the full output contract.

    The script never reads any existing artifact.  Returns an
    envelope describing the worksheet shape and N blank rows.  When
    ``output_path`` is supplied, the resulting JSON or CSV is
    persisted to that path — but only if the path does not already
    exist (the script refuses to mutate an existing file).

    When both ``emit_artifacts`` and ``output_dir`` are passed, the
    envelope's filled worksheet rows (those carrying a non-empty,
    filename-safe ``candidate_id``) are persisted as
    ``analyzed_event_artifact_<candidate_id>.json`` under
    ``output_dir``.  Default behavior is unchanged: with the flags
    omitted, no per-row artifact is written.  ``worksheet_rows`` is
    an optional caller-supplied rows list — when present it replaces
    the blank-row factory output so callers can build a worksheet
    over already-filled rows in a single call.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    if worksheet_rows is None:
        rows_clean = _clamp_rows(rows, warnings=warnings)
        worksheet: list[dict[str, Any]] = [
            _blank_row() for _ in range(rows_clean)
        ]
    else:
        worksheet = []
        for r in worksheet_rows:
            if not isinstance(r, dict):
                continue
            # Start from a blank-spec row so every spec column is
            # present (default ""); overlay caller-supplied keys so
            # both spec and extra fields (e.g. market_relevance) pass
            # through the projection.
            projected: dict[str, Any] = {
                col: _coerce_cell(r.get(col))
                for col in _WORKSHEET_COLUMNS
            }
            for k, v in r.items():
                if k not in projected:
                    projected[k] = _coerce_cell(v)
            worksheet.append(projected)

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
        "emit_artifacts":           bool(emit_artifacts),
        "output_dir":               output_dir,
        "emitted_artifacts":        [],
        "skipped_artifacts":        [],
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

    if emit_artifacts and output_dir:
        emit_result = emit_analyzed_event_artifacts(
            envelope=envelope,
            output_dir=output_dir,
        )
        envelope["emitted_artifacts"] = emit_result["emitted"]
        envelope["skipped_artifacts"] = emit_result["skipped"]
        envelope["output_dir"] = emit_result["output_dir"]
        for e in emit_result["errors"]:
            envelope["errors"].append(e)
        if emit_result["errors"]:
            envelope["ok"] = False
    elif emit_artifacts and not output_dir:
        envelope["warnings"].append(
            "--emit-artifacts was passed without --output-dir; no "
            "per-row artifact was written.  Pass both flags together "
            "to emit analyzed_event_artifact files."
        )

    return envelope


def _coerce_cell(value: Any) -> str:
    """Coerce a caller-supplied row cell to a stripped string.

    Mirrors the worksheet's empty-string-by-default invariant: ``None``
    and missing keys land as ``""``; any other value is stringified
    and stripped.  Callers can therefore pass in dicts with only a few
    keys populated and the worksheet row will round-trip cleanly.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


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
# Analyzed-event artifact emission
# ---------------------------------------------------------------------------


def emit_analyzed_event_artifacts(
    *,
    envelope:    dict[str, Any] | None = None,
    rows:        Sequence[dict[str, Any]] | None = None,
    output_dir:  str,
    overwrite:   bool = False,
) -> dict[str, Any]:
    """Write one ``analyzed_event_artifact_<candidate_id>.json`` per
    filled worksheet row.

    Accepts either a worksheet ``envelope`` (whose ``worksheet`` list
    is read) or a raw ``rows`` list.  A row is "filled" when its
    ``candidate_id`` is a non-empty, filename-safe string; rows with
    no candidate_id or with characters unsafe for a filename are
    skipped with a reason.  Refuses to overwrite an existing artifact
    file unless ``overwrite`` is true — the default keeps the on-disk
    artifact pool stable.  Never imports a DB, a provider, or a
    FastAPI surface.

    Returns
    -------
    dict
        ``{output_dir, emitted_count, skipped_count, emitted, skipped,
        errors}``.  Each ``emitted`` entry carries ``row_index``,
        ``candidate_id``, and ``path``; each ``skipped`` entry carries
        ``row_index``, ``candidate_id`` (possibly empty), and
        ``reason``.
    """
    if envelope is not None and rows is None:
        rows_iter = envelope.get("worksheet") or []
    else:
        rows_iter = rows or []

    emitted:    list[dict[str, Any]] = []
    skipped:    list[dict[str, Any]] = []
    err_list:   list[str] = []

    target_dir = Path(output_dir)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        err_list.append(
            f"failed to create output_dir {output_dir!r}: {exc}",
        )
        return {
            "output_dir":     str(target_dir),
            "emitted_count":  0,
            "skipped_count":  0,
            "emitted":        emitted,
            "skipped":        skipped,
            "errors":         err_list,
        }

    for idx, row in enumerate(rows_iter):
        if not isinstance(row, dict):
            continue
        cid_raw = row.get("candidate_id", "")
        cid = cid_raw.strip() if isinstance(cid_raw, str) else ""
        if not cid:
            # Blank rows are skipped silently — the script's default
            # invocation emits blank rows and "--emit-artifacts on a
            # blank worksheet" is intentionally a no-op.
            continue
        if not _VALID_CANDIDATE_ID_RE.match(cid):
            skipped.append({
                "row_index":    idx,
                "candidate_id": cid,
                "reason": (
                    "candidate_id contains characters that are not "
                    "safe for a filename"
                ),
            })
            continue

        body = _build_artifact_body(row)
        artifact_path = target_dir / f"analyzed_event_artifact_{cid}.json"
        if artifact_path.exists() and not overwrite:
            skipped.append({
                "row_index":    idx,
                "candidate_id": cid,
                "reason":       "artifact already exists at the target path",
                "path":         str(artifact_path),
            })
            continue
        try:
            artifact_path.write_text(
                json.dumps(body, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            err_list.append(
                f"failed to write {artifact_path}: {exc}",
            )
            continue
        emitted.append({
            "row_index":    idx,
            "candidate_id": cid,
            "path":         str(artifact_path),
        })

    return {
        "output_dir":     str(target_dir),
        "emitted_count":  len(emitted),
        "skipped_count":  len(skipped),
        "emitted":        emitted,
        "skipped":        skipped,
        "errors":         err_list,
    }


def _build_artifact_body(row: dict[str, Any]) -> dict[str, Any]:
    """Build the per-row analyzed_event_artifact body.

    Always emits the four gate-relevant fields (candidate_id,
    headline, event_date, mechanism_family, primary_ticker,
    benchmark_ticker) plus the fixed ``artifact_type`` tag.
    ``market_relevance`` is included only when the worksheet row
    carries a non-empty value — the field is optional on the gate
    side and the operator may legitimately leave it blank.
    """
    body: dict[str, Any] = {
        "artifact_type":     _PER_ROW_ARTIFACT_TYPE,
        "candidate_id":      _coerce_cell(row.get("candidate_id")),
        "headline":          _coerce_cell(row.get("headline")),
        "event_date":        _coerce_cell(row.get("event_date")),
        "mechanism_family":  _coerce_cell(row.get("mechanism_family")),
        "primary_ticker":    _coerce_cell(row.get("primary_ticker")),
        "benchmark_ticker":  _coerce_cell(row.get("benchmark_ticker")),
    }
    mr = _coerce_cell(row.get("market_relevance"))
    if mr:
        body["market_relevance"] = mr
    return body


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
    parser.add_argument(
        "--emit-artifacts", dest="emit_artifacts", action="store_true",
        help=(
            "Write one analyzed_event_artifact_<candidate_id>.json "
            "per filled worksheet row under --output-dir.  Default "
            "off — emission only runs when both --emit-artifacts and "
            "--output-dir are passed.  Blank rows are skipped "
            "silently; existing artifact files are not overwritten."
        ),
    )
    parser.add_argument(
        "--output-dir", dest="output_dir", default=None,
        help=(
            "Directory under which to write per-row "
            "analyzed_event_artifact_<candidate_id>.json files.  "
            "Required when --emit-artifacts is passed; ignored "
            "otherwise.  Created if it does not already exist."
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
        emit_artifacts=args.emit_artifacts,
        output_dir=args.output_dir,
    )

    if fmt == "csv":
        output.write(_render_csv(report))
    else:
        print(_render_json(report), file=output)

    return 0 if report.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_manual_event_intake_worksheet",
    "emit_analyzed_event_artifacts",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
