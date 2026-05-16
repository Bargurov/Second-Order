#!/usr/bin/env python3
"""Daily analyzed-event artifact emitter.

Reads operator-reviewed Daily candidate rows (CSV or JSON) and emits
one ``analyzed_event_artifact_<candidate_id>.json`` per included
candidate.  The emitted artifact is the input the Daily artifact
gate reads under ``artifacts/``; once a row's artifact is on disk
the Section C gate can admit the matching mover card.  See
``routes/daily_artifact_gate.py`` for the gate contract this emitter
feeds, and ``scripts/daily_artifact_gate_implementation_plan.py``
for the surrounding design.

Read-only by construction
-------------------------

* No DB reads or writes.
* No ``yfinance``, ``market_data``, paid provider, LLM, or FastAPI
  surface (never imports ``api`` or ``routes.*``).
* No mutation of ``news_inbox.json``, the events DB, or any other
  shared artifact.
* No fuzzy or LLM-based headline matching; every row is operator-
  supplied through the CSV / JSON input file.
* The default invocation has no filesystem side effect.
  ``--output-dir`` is the only way to write artifacts.  Each per-row
  artifact is refused when its destination path already exists,
  unless the operator passes ``--overwrite``.

Conservative wording
--------------------

Banned tokens in any prose this script emits: ``proof``, ``proven``,
``validated``, ``automatically``, ``alpha generated``, ``guaranteed``,
``correct ticker``.  The emitter never claims a row is validated,
proven, defensible, or worth including; the operator owns every
per-row judgment, including which rows the
``include_in_daily_section_c`` flag admits.

Input row fields
----------------

The CSV header (or JSON object keys) for each candidate row::

    candidate_id
    headline
    event_date
    mechanism_family
    primary_ticker
    benchmark_ticker
    market_relevance
    inclusion_reason
    operator_notes
    include_in_daily_section_c

``include_in_daily_section_c`` is the operator's emit gate — only
rows whose value is ``yes`` or ``true`` (case-insensitive, after
strip) are eligible to emit.  Any other value (``no``, blank,
missing column) leaves the row skipped without an error.

Required fields for emission
----------------------------

A row that is eligible per ``include_in_daily_section_c`` is then
required to carry non-empty ``candidate_id``, ``mechanism_family``,
``primary_ticker``, and ``benchmark_ticker``.  A missing required
field surfaces under envelope ``errors`` and the row is skipped.
``mechanism_family`` of the literal ``"none"`` sentinel (case-
insensitive) is treated as missing, matching the Daily gate's rule.

Output artifact (one JSON file per emitted row)
-----------------------------------------------

``analyzed_event_artifact_<candidate_id>.json`` carries::

    candidate_id
    headline
    event_date
    mechanism_family
    primary_ticker
    benchmark_ticker
    market_relevance
    inclusion_reason
    operator_notes
    artifact_type

``artifact_type`` is the fixed string ``"analyzed_event_artifact"``.
``market_relevance``, ``inclusion_reason``, and ``operator_notes``
pass through verbatim — the operator owns their content; the
emitter does not score, grade, or screen them.

Envelope output (stdout)
------------------------

The script always prints a JSON envelope to stdout.  ``--json`` is
a no-op compatibility flag (JSON is the default).  The envelope
carries::

    {
      "ok":                        bool,
      "artifact_type":             "daily_analyzed_event_artifact_emitter_run",
      "input_path":                str | null,
      "output_dir":                str | null,
      "overwrite":                 bool,
      "dry_run":                   bool,
      "loaded_row_count":          int,
      "emitted_count":             int,
      "skipped_count":             int,
      "candidates": [
        {
          "row_index":                  int,
          "candidate_id":               str,
          "include_in_daily_section_c": raw value,
          "status":                     "would_emit" | "emitted" | "skipped",
          "reason":                     str,
          "missing_fields":             [str, ...],
          "artifact":                   dict | null,
          "written_path":               str (optional),
        },
        ...
      ],
      "required_artifact_fields":  [str, ...],
      "warnings":                  [str, ...],
      "errors":                    [str, ...],
    }

Usage
-----

    # JSON dry-run preview (default — no filesystem side effect):
    python scripts/daily_analyzed_event_artifact_emitter.py
    python scripts/daily_analyzed_event_artifact_emitter.py --json
    python scripts/daily_analyzed_event_artifact_emitter.py \\
        --input reviewed_daily.csv

    # Write artifacts to a directory (refuses to overwrite by default):
    python scripts/daily_analyzed_event_artifact_emitter.py \\
        --input reviewed_daily.csv --output-dir artifacts/

    # Replace existing artifact files at the same path:
    python scripts/daily_analyzed_event_artifact_emitter.py \\
        --input reviewed_daily.csv --output-dir artifacts/ --overwrite
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Fixed string written on every emitted per-row artifact.
_ARTIFACT_TYPE: str = "analyzed_event_artifact"

# Envelope artifact_type tag — distinguishes the run report from the
# per-row artifact bodies the run emits.
_RUN_ARTIFACT_TYPE: str = "daily_analyzed_event_artifact_emitter_run"

# Field order pinned on every emitted artifact body.
_ARTIFACT_BODY_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "headline",
    "event_date",
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
    "market_relevance",
    "inclusion_reason",
    "operator_notes",
    "artifact_type",
)

# Required artifact body fields the Daily gate enforces — mirrored
# from routes/daily_artifact_gate.py so a missing field is caught at
# emission time rather than at promotion time.  ``candidate_id`` is
# enforced separately because it is also the artifact filename key.
_GATE_REQUIRED_FIELDS: tuple[str, ...] = (
    "mechanism_family",
    "primary_ticker",
    "benchmark_ticker",
)

# The Daily gate refuses a card whose artifact carries
# ``mechanism_family == "none"`` (the sentinel emitted upstream when
# the field was missing).  Mirror that here so the same string never
# slips onto an emitted artifact.
_MECHANISM_FAMILY_NONE_SENTINEL: str = "none"

# Operator-emit-gate vocabulary.  Case-insensitive, post-strip.
_INCLUDE_TRUE_TOKENS: frozenset[str] = frozenset({"yes", "true"})

# Column name for the operator-emit gate.  Kept as a module constant
# so tests can pin the string the spec requires.
_INCLUDE_FLAG_COLUMN: str = "include_in_daily_section_c"


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_emitter(
    *,
    input_path: str | None = None,
    output_dir: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Run the emitter and return the run envelope.

    See module docstring for the full output contract.  ``run_emitter``
    is the single pure entry point the CLI wraps; tests call it
    directly with synthetic inputs.
    """
    warnings: list[str] = []
    errors: list[str] = []

    rows, load_errors = _load_input(input_path)
    errors.extend(load_errors)

    if input_path is None:
        warnings.append(
            "no --input supplied; the emitter has nothing to preview "
            "or write.  Pass --input <csv-or-json> to inspect "
            "candidate rows."
        )

    if output_dir is None:
        warnings.append(
            "dry-run only — no --output-dir supplied, so no artifact "
            "files were written.  Pass --output-dir <path> to persist "
            "artifacts."
        )

    candidates: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        outcome = _evaluate_row(row, row_index=i)
        if outcome["missing_fields"] and outcome["status"] == "skipped":
            errors.append(
                f"row {i} (candidate_id={outcome['candidate_id']!r}): "
                f"{outcome['reason']}"
            )
        candidates.append(outcome)

    if output_dir is not None:
        write_errors = _write_artifacts(
            candidates=candidates,
            output_dir=output_dir,
            overwrite=overwrite,
        )
        errors.extend(write_errors)

    emitted_count = sum(
        1 for c in candidates
        if c["status"] in ("would_emit", "emitted")
    )
    skipped_count = len(candidates) - emitted_count

    envelope: dict[str, Any] = {
        "ok":                       not errors,
        "artifact_type":            _RUN_ARTIFACT_TYPE,
        "input_path":               input_path,
        "output_dir":               output_dir,
        "overwrite":                bool(overwrite),
        "dry_run":                  output_dir is None,
        "loaded_row_count":         len(rows),
        "emitted_count":            emitted_count,
        "skipped_count":            skipped_count,
        "candidates":               candidates,
        "required_artifact_fields": list(_ARTIFACT_BODY_FIELDS),
        "warnings":                 warnings,
        "errors":                   errors,
    }
    return envelope


# ---------------------------------------------------------------------------
# Input loading
# ---------------------------------------------------------------------------


def _load_input(
    input_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load operator-reviewed candidate rows from CSV or JSON.

    Returns ``(rows, errors)`` — rows is a list of dicts (one per
    input row).  Errors carry one string per structural problem.
    """
    if input_path is None:
        return [], []
    p = Path(input_path)
    if not p.exists():
        return [], [f"--input file does not exist: {input_path}"]
    suffix = p.suffix.lower()
    if suffix == ".csv":
        return _load_csv(p)
    if suffix == ".json":
        return _load_json(p)
    return [], [
        f"unsupported --input extension {p.suffix!r}; "
        "expected .csv or .json"
    ]


def _load_csv(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            rows: list[dict[str, Any]] = []
            for row in reader:
                rows.append(
                    {k: v for k, v in row.items() if k is not None}
                )
            return rows, []
    except OSError as e:
        return [], [f"failed to read --input CSV {path}: {e}"]


def _load_json(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as e:
        return [], [f"failed to read --input JSON {path}: {e}"]
    except json.JSONDecodeError as e:
        return [], [f"failed to parse --input JSON {path}: {e}"]

    if isinstance(raw, list):
        rows_raw = raw
    elif isinstance(raw, dict):
        rows_raw = raw.get("candidates")
        if not isinstance(rows_raw, list):
            return [], [
                "--input JSON mapping has no 'candidates' list at top "
                "level; expected either a top-level list or "
                "{candidates: [...]}"
            ]
    else:
        return [], [
            f"--input JSON top level is not a list or mapping "
            f"(got {type(raw).__name__})"
        ]

    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for i, entry in enumerate(rows_raw):
        if not isinstance(entry, dict):
            errors.append(
                f"--input JSON row {i} is not a mapping "
                f"(got {type(entry).__name__})"
            )
            continue
        rows.append(dict(entry))
    return rows, errors


# ---------------------------------------------------------------------------
# Per-row evaluation
# ---------------------------------------------------------------------------


def _evaluate_row(
    row: dict[str, Any],
    *,
    row_index: int,
) -> dict[str, Any]:
    """Evaluate a single input row.

    Returns a per-row outcome dict carrying ``status``, ``reason``,
    ``missing_fields``, and an ``artifact`` body when the row would
    emit.  Read-only — never mutates ``row``.
    """
    candidate_id = _as_stripped_str(row.get("candidate_id"))
    include_flag_raw = row.get(_INCLUDE_FLAG_COLUMN)
    include_flag = _as_stripped_str(include_flag_raw).lower()

    outcome: dict[str, Any] = {
        "row_index":                  row_index,
        "candidate_id":               candidate_id,
        "include_in_daily_section_c": include_flag_raw,
        "status":                     "skipped",
        "reason":                     "",
        "missing_fields":             [],
        "artifact":                   None,
    }

    if include_flag not in _INCLUDE_TRUE_TOKENS:
        outcome["reason"] = (
            "include_in_daily_section_c is not 'yes' or 'true'; "
            "row is not eligible for emission"
        )
        return outcome

    missing: list[str] = []
    if not candidate_id:
        missing.append("candidate_id")
    for field in _GATE_REQUIRED_FIELDS:
        v = _as_stripped_str(row.get(field))
        if not v:
            missing.append(field)
            continue
        if (
            field == "mechanism_family"
            and v.lower() == _MECHANISM_FAMILY_NONE_SENTINEL
        ):
            missing.append(field)

    if missing:
        outcome["missing_fields"] = missing
        outcome["reason"] = (
            "row missing or invalid required field(s): "
            + ", ".join(missing)
        )
        return outcome

    outcome["status"] = "would_emit"
    outcome["artifact"] = _build_artifact_body(
        row, candidate_id=candidate_id,
    )
    return outcome


def _build_artifact_body(
    row: dict[str, Any],
    *,
    candidate_id: str,
) -> dict[str, Any]:
    """Build the per-row artifact body in spec field order.

    Required gate fields are stored stripped.  Free-text fields
    pass through verbatim — the operator owns their content.
    ``market_relevance`` is captured as supplied (the gate does not
    enforce its type; the planner notes the value is operator-
    supplied at review time).
    """
    return {
        "candidate_id":     candidate_id,
        "headline":         _passthrough_str(row.get("headline")),
        "event_date":       _passthrough_str(row.get("event_date")),
        "mechanism_family": _as_stripped_str(row.get("mechanism_family")),
        "primary_ticker":   _as_stripped_str(row.get("primary_ticker")),
        "benchmark_ticker": _as_stripped_str(row.get("benchmark_ticker")),
        "market_relevance": row.get("market_relevance"),
        "inclusion_reason": _passthrough_str(row.get("inclusion_reason")),
        "operator_notes":   _passthrough_str(row.get("operator_notes")),
        "artifact_type":    _ARTIFACT_TYPE,
    }


# ---------------------------------------------------------------------------
# Output-file persistence
# ---------------------------------------------------------------------------


def _write_artifacts(
    *,
    candidates: list[dict[str, Any]],
    output_dir: str,
    overwrite: bool,
) -> list[str]:
    """Persist one ``analyzed_event_artifact_<cid>.json`` per
    eligible row.  Returns a list of error strings (empty on full
    success).  Each candidate dict is updated in place to record
    the final ``status`` and (on success) ``written_path``.
    """
    errors: list[str] = []
    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return [f"failed to create --output-dir {output_dir}: {e}"]

    for outcome in candidates:
        if outcome["status"] != "would_emit":
            continue
        cid = outcome["candidate_id"]
        body = outcome["artifact"]
        target = out_dir / f"analyzed_event_artifact_{cid}.json"
        if target.exists() and not overwrite:
            outcome["status"] = "skipped"
            outcome["reason"] = (
                f"refusing to overwrite existing artifact at "
                f"{target}; pass --overwrite to replace it."
            )
            errors.append(outcome["reason"])
            continue
        try:
            target.write_text(
                json.dumps(body, indent=2, sort_keys=True, default=str)
                + "\n",
                encoding="utf-8",
            )
        except OSError as e:
            outcome["status"] = "skipped"
            outcome["reason"] = f"failed to write {target}: {e}"
            errors.append(outcome["reason"])
            continue
        outcome["status"] = "emitted"
        outcome["written_path"] = str(target)
    return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_stripped_str(v: Any) -> str:
    """Coerce ``v`` to a stripped string.

    ``None`` becomes ``""``.  Strings round-trip.  Non-strings are
    rendered via ``str()`` and stripped — so an integer ``42`` from a
    JSON input becomes ``"42"``.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def _passthrough_str(v: Any) -> str:
    """Render ``v`` as a string without trimming whitespace.

    Used for free-text artifact fields (``headline``, ``event_date``,
    ``inclusion_reason``, ``operator_notes``) so the operator's
    formatting survives round-trip.
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read operator-reviewed Daily candidate rows from CSV or "
            "JSON and emit one analyzed_event_artifact_<candidate_id>"
            ".json per included candidate.  No DB, no provider, no "
            "yfinance, no LLM, no FastAPI.  Dry-run JSON preview by "
            "default; --output-dir is the only filesystem side effect, "
            "and the emitter refuses to overwrite an existing artifact "
            "file unless --overwrite is supplied."
        ),
    )
    parser.add_argument(
        "--input", dest="input_path", default=None,
        help=(
            "Path to operator-reviewed candidates (.csv or .json).  "
            "Without this flag the emitter prints an empty preview "
            "envelope and exits."
        ),
    )
    parser.add_argument(
        "--output-dir", dest="output_dir", default=None,
        help=(
            "Directory to write analyzed_event_artifact_<cid>.json "
            "files to.  Without this flag the emitter runs in dry-run "
            "mode and writes nothing."
        ),
    )
    parser.add_argument(
        "--overwrite", action="store_true",
        help=(
            "Replace an existing artifact file at the same path.  "
            "Without this flag the emitter refuses to overwrite and "
            "the row is skipped with an error."
        ),
    )
    parser.add_argument(
        "--json", dest="json_flag", action="store_true",
        help=(
            "Emit structured JSON (this is also the default — kept "
            "for symmetry with sibling read-only scripts)."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    envelope = run_emitter(
        input_path=args.input_path,
        output_dir=args.output_dir,
        overwrite=args.overwrite,
    )
    print(_render_json(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "run_emitter",
    "main",
)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
