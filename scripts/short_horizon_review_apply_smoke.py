#!/usr/bin/env python3
"""Temp-copy short-horizon reviewed decision apply smoke.

Converts an operator-reviewed short-horizon worksheet into staged
curated candidate rows inside a TEMP copy of the live events DB.
Never touches the live archive; never invokes the validation
pipeline; never imports a provider, ``yfinance``, an LLM, or a
FastAPI surface.

The worksheet is the short-horizon review queue, enriched by hand
with per-row operator decisions.  Accepted rows are staged into the
temp DB's ``curated_candidates`` table for downstream validation by
the existing read-only runners; excluded and pending rows are
counted and surfaced but never written.

Read-only against the live archive
----------------------------------

* The live DB is hashed before and after the smoke and the result is
  surfaced as ``live_db_unchanged``.  The smoke never opens the live
  DB for writes — only ``shutil.copy2`` reads its bytes into a fresh
  temp file.
* Staging happens against the TEMP copy only.
* No call to :mod:`scripts.curated_candidate_validation_run` or any
  other validation runner — staging is NOT validation.
* The temp DB file is kept after the run so an operator can inspect
  the staged rows; the path is surfaced as ``temp_db_path``.

Worksheet schema (CSV)
----------------------

The worksheet is the canonical short-horizon review worksheet
emitted by ``scripts.short_horizon_review_worksheet``.  The operator
gate is the same column the validator reads — ``include_in_short_
horizon_validation`` — so the validator / apply / validate triple
share one column instead of three.

Required base columns::

    event_id
    include_in_short_horizon_validation
        — one of: ``yes`` | ``no`` | ``""`` (blank).  Case- and
          whitespace-insensitive.  Blank means pending_review.

Required columns for ``yes`` rows (per-row check; missing fields
land in ``errors`` and the row is NOT staged)::

    proposed_primary_ticker
    proposed_benchmark_ticker
    proposed_mechanism_family
    predicted_direction        — one of: up | down | neutral

Required column for ``no`` rows::

    exclude_reason

Optional columns (read when present, otherwise blank)::

    headline, event_date (ISO YYYY-MM-DD when present),
    operator_notes, source_url

Worksheet-to-DB column mapping for staging into
``curated_candidates``::

    proposed_primary_ticker   → primary_ticker
    proposed_benchmark_ticker → benchmark_ticker
    proposed_mechanism_family → mechanism_family
    operator_notes            → curator_notes
    event_id                  → source_event_id

Other curated_candidates columns (``mechanism_description``,
``prediction_rationale``, ``source_url``) are left blank — the
worksheet does not carry them and the schema treats them as
optional TEXT.

Output contract::

    {
      "ok":                bool,
      "worksheet_path":    str | None,
      "temp_db_path":      str | None,
      "accepted_count":    int,
      "staged_count":      int,
      "staged_event_ids":  [int, ...],
      "excluded_count":    int,
      "pending_count":     int,
      "live_db_unchanged": bool,
      "errors":            [str, ...],
      "warnings":          [str, ...],
    }

The output dict carries EXACTLY these 11 keys — no additive fields.

``accepted_count`` is the count of operator-accepted worksheet rows.
``staged_count`` is the number of curated_candidate rows actually
inserted.  The two can diverge: an accepted row missing a required
field (or colliding with the ``UNIQUE(source_event_id, source)``
constraint on a re-run) is counted as accepted but never staged.

Patchable seams
---------------

  * ``_copy_live_db_to_temp(*, src_path)`` — ``shutil.copy2`` from
    src into a fresh ``tempfile.gettempdir()`` file.
  * ``_stage_curated_candidates(*, temp_db_path, candidates)`` —
    INSERT each accepted row into the temp DB's
    ``curated_candidates`` table with ``status='needs_review'`` and
    ``source='short_horizon_review_apply_smoke'``.

Conservative wording
--------------------

The events surfaced are "staged candidates," not validated, not
proven, not alpha.  Banned tokens (``proof``, ``proven``,
``automatically``, ``alpha generated``, ``correct ticker``,
``validated``) never appear in any text the smoke emits.

Usage::

    python scripts/short_horizon_review_apply_smoke.py \\
        --worksheet artifacts/short_horizon_review_top10.csv
    python scripts/short_horizon_review_apply_smoke.py \\
        --worksheet artifacts/short_horizon_review_top10.csv --json
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Canonical worksheet gate column — shared with the validator and
# the validate smoke so the validator / apply / validate triple read
# the same column.  Operator values are case- and whitespace-
# insensitive ``yes`` / ``no`` / blank.
_GATE_COLUMN: str = "include_in_short_horizon_validation"
_GATE_YES:    str = "yes"
_GATE_NO:     str = "no"


_WORKSHEET_BASE_REQUIRED: tuple[str, ...] = ("event_id", _GATE_COLUMN)


# Fields required on a ``yes`` row before it can be staged.  Mirrors
# the validator's yes-row contract; column names use the worksheet's
# ``proposed_*`` prefix.
_YES_REQUIRED_FIELDS: tuple[str, ...] = (
    "proposed_primary_ticker",
    "proposed_benchmark_ticker",
    "proposed_mechanism_family",
    "predicted_direction",
)


_VALID_DIRECTIONS: frozenset[str] = frozenset({"up", "down", "neutral"})


_STAGE_STATUS: str = "needs_review"
_STAGE_SOURCE: str = "short_horizon_review_apply_smoke"


_CURATED_CANDIDATES_DDL: str = """
CREATE TABLE IF NOT EXISTS curated_candidates (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_event_id       INTEGER NOT NULL,
    event_date            TEXT,
    headline              TEXT,
    source_url            TEXT,
    primary_ticker        TEXT,
    benchmark_ticker      TEXT,
    mechanism_family      TEXT,
    mechanism_description TEXT,
    predicted_direction   TEXT,
    prediction_rationale  TEXT,
    curator_notes         TEXT,
    status                TEXT NOT NULL DEFAULT 'draft',
    source                TEXT NOT NULL,
    created_at            TEXT NOT NULL,
    validation_errors     TEXT NOT NULL DEFAULT '[]',
    UNIQUE(source_event_id, source)
)
""".strip()


_INSERT_COLUMNS: tuple[str, ...] = (
    "source_event_id",
    "event_date",
    "headline",
    "source_url",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
    "mechanism_description",
    "predicted_direction",
    "prediction_rationale",
    "curator_notes",
    "status",
    "source",
    "created_at",
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _copy_live_db_to_temp(*, src_path: str) -> str:
    """Copy ``src_path`` to a fresh file in ``tempfile.gettempdir()``
    and return the destination path.  Uses ``shutil.copy2`` to
    preserve metadata.
    """
    src = Path(src_path)
    dst_name = (
        f"sh_review_apply_{uuid.uuid4().hex}{src.suffix or '.db'}"
    )
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(str(src), str(dst))
    return str(dst)


def _stage_curated_candidates(
    *, temp_db_path: str, candidates: Sequence[dict[str, Any]],
) -> tuple[int, list[int]]:
    """INSERT each candidate dict into the temp DB's
    ``curated_candidates`` table with ``status='needs_review'`` and
    ``source='short_horizon_review_apply_smoke'``.

    Rows whose ``UNIQUE(source_event_id, source)`` constraint is
    violated are skipped silently — the smoke is idempotent against
    repeated runs against the same temp DB.

    Returns ``(inserted_count, staged_event_ids)``.
    """
    if not candidates:
        return 0, []
    inserted = 0
    staged_ids: list[int] = []
    created_at = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    placeholders = ",".join(["?"] * len(_INSERT_COLUMNS))
    sql = (
        f"INSERT OR IGNORE INTO curated_candidates "
        f"({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders})"
    )
    conn = sqlite3.connect(temp_db_path)
    try:
        conn.execute(_CURATED_CANDIDATES_DDL)
        for cand in candidates:
            ev_id = cand.get("source_event_id")
            row = (
                ev_id,
                cand.get("event_date"),
                cand.get("headline"),
                cand.get("source_url"),
                cand.get("primary_ticker"),
                cand.get("benchmark_ticker"),
                cand.get("mechanism_family"),
                cand.get("mechanism_description"),
                cand.get("predicted_direction"),
                cand.get("prediction_rationale"),
                cand.get("curator_notes"),
                _STAGE_STATUS,
                _STAGE_SOURCE,
                created_at,
            )
            cur = conn.execute(sql, row)
            if cur.rowcount > 0 and isinstance(ev_id, int):
                inserted += 1
                staged_ids.append(ev_id)
        conn.commit()
    finally:
        conn.close()
    staged_ids.sort()
    return inserted, staged_ids


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_short_horizon_review_apply(
    *,
    worksheet_path: str | None = None,
    db_path:        str | None = None,
) -> dict[str, Any]:
    """Run the short-horizon reviewed decision apply smoke.  See
    module docstring for the full output contract.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    accepted_rows: list[dict[str, Any]] = []
    excluded_count: int = 0
    pending_count:  int = 0
    staged_count:   int = 0
    staged_event_ids: list[int] = []
    temp_db_path: str | None = None

    # Step 1: parse worksheet.  Missing path / missing file is a hard
    # fail — the smoke has nothing to apply.
    rows, parse_errors, parse_warnings = _parse_worksheet(worksheet_path)
    errors.extend(parse_errors)
    warnings.extend(parse_warnings)

    accepted_count = 0
    if not parse_errors:
        (
            accepted_rows, excluded_count, pending_count,
            categ_errors, categ_warnings,
        ) = _categorize_rows(rows)
        errors.extend(categ_errors)
        warnings.extend(categ_warnings)
        # Every row whose gate is ``yes`` counts toward
        # accepted_count regardless of whether its required fields
        # validated.  An invalid yes row lands in errors and is NOT
        # staged, so accepted_count may exceed staged_count.
        accepted_count = sum(
            1 for r in rows if _gate_value(r.get(_GATE_COLUMN)) == _GATE_YES
        )

    # Step 2: live DB hash before copy.  Missing live DB is a fail-
    # closed error — operator should explicitly supply --db-path.
    live_hash_before = _hash_file_safe(db_path)
    if db_path is None:
        errors.append(
            "--db-path is None and no default could be resolved — "
            "refusing to run; cannot stage without a copy of the "
            "live DB"
        )
    elif live_hash_before is None:
        errors.append(
            f"live DB does not exist at {db_path} — refusing to "
            f"run; cannot stage without a copy of the live DB"
        )

    # Step 3: copy live → temp, then stage accepted rows.  Skip the
    # copy when earlier steps already failed.
    if not errors and accepted_rows and isinstance(db_path, str):
        try:
            temp_db_path = _copy_live_db_to_temp(src_path=db_path)
            warnings.append(f"Temp DB copy at {temp_db_path}")
        except OSError as e:
            errors.append(f"Failed to copy live DB to temp: {e}")
            temp_db_path = None
        if temp_db_path is not None:
            try:
                staged_count, staged_event_ids = _stage_curated_candidates(
                    temp_db_path=temp_db_path,
                    candidates=accepted_rows,
                )
            except sqlite3.Error as e:
                errors.append(f"Temp DB staging insert failed: {e}")

    # Step 4: re-hash live DB, surface drift.  ``None == None`` is
    # the absent-DB case; the smoke bailed before touching anything,
    # so we report it as unchanged (we left it the way we found it).
    live_hash_after = _hash_file_safe(db_path)
    live_db_unchanged = live_hash_before == live_hash_after
    if (
        live_hash_before is not None
        and live_hash_after is not None
        and live_hash_before != live_hash_after
    ):
        errors.append(
            f"LIVE DB BYTES CHANGED during short-horizon review "
            f"apply smoke — investigate: {db_path}"
        )

    return {
        "ok":                not errors,
        "worksheet_path":    worksheet_path,
        "temp_db_path":      temp_db_path,
        "accepted_count":    accepted_count,
        "staged_count":      staged_count,
        "staged_event_ids":  staged_event_ids,
        "excluded_count":    excluded_count,
        "pending_count":     pending_count,
        "live_db_unchanged": live_db_unchanged,
        "errors":            errors,
        "warnings":          warnings,
    }


# ---------------------------------------------------------------------------
# Worksheet parsing
# ---------------------------------------------------------------------------


def _parse_worksheet(
    worksheet_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors:   list[str] = []
    warnings: list[str] = []
    if worksheet_path is None:
        errors.append(
            "--worksheet is required; refusing to run without a "
            "reviewed worksheet path"
        )
        return [], errors, warnings
    p = Path(worksheet_path)
    if not p.exists():
        errors.append(f"worksheet does not exist: {worksheet_path}")
        return [], errors, warnings
    try:
        with p.open("r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [
                f for f in _WORKSHEET_BASE_REQUIRED
                if f not in fieldnames
            ]
            if missing:
                errors.append(
                    f"worksheet missing required columns: "
                    f"{', '.join(missing)}"
                )
                return [], errors, warnings
            rows = [dict(r) for r in reader]
    except OSError as e:
        errors.append(f"Failed to read worksheet {worksheet_path}: {e}")
        return [], errors, warnings
    return rows, errors, warnings


# ---------------------------------------------------------------------------
# Row categorization
# ---------------------------------------------------------------------------


def _categorize_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, list[str], list[str]]:
    """Sort worksheet rows by gate value (``yes`` / ``no`` / blank).
    Yes rows are field-validated inline; failures land in ``errors``
    and the row is dropped from the accepted bucket.  No rows must
    carry a non-blank ``exclude_reason`` or they fail as well.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    accepted: list[dict[str, Any]] = []
    excluded_count: int = 0
    pending_count:  int = 0

    for i, raw in enumerate(rows):
        gate_raw = raw.get(_GATE_COLUMN)
        gate     = _gate_value(gate_raw)
        ev_id_raw = raw.get("event_id")
        ev_id = _coerce_int(ev_id_raw)
        if ev_id is None:
            errors.append(
                f"row {i}: missing or non-integer event_id "
                f"({ev_id_raw!r}); refusing to stage"
            )
            continue

        if gate == _GATE_YES:
            row_errors = _validate_yes_row(ev_id, raw)
            if row_errors:
                errors.extend(row_errors)
                continue
            accepted.append(_build_candidate(ev_id, raw))
        elif gate == _GATE_NO:
            reason = _coerce_str(raw.get("exclude_reason"))
            if not reason:
                errors.append(
                    f"row {i} event_id={ev_id}: 'no' rows must carry "
                    f"a non-blank 'exclude_reason'; refusing to stage"
                )
                continue
            excluded_count += 1
        elif gate == "":
            # Blank gate is the legitimate pending_review state — no
            # warning, no error.  The operator simply hasn't decided.
            pending_count += 1
        else:
            warnings.append(
                f"row {i} event_id={ev_id}: unknown "
                f"include_in_short_horizon_validation value "
                f"{(_coerce_str(gate_raw) or '')!r}; counted as pending"
            )
            pending_count += 1

    return accepted, excluded_count, pending_count, errors, warnings


def _validate_yes_row(
    event_id: int, raw: dict[str, Any],
) -> list[str]:
    errs: list[str] = []
    for field in _YES_REQUIRED_FIELDS:
        value = raw.get(field)
        if not isinstance(value, str) or not value.strip():
            errs.append(
                f"yes row event_id={event_id}: required field "
                f"{field!r} is missing or blank; refusing to stage"
            )
    direction = _coerce_str(raw.get("predicted_direction"))
    if direction is not None and direction.lower() not in _VALID_DIRECTIONS:
        errs.append(
            f"yes row event_id={event_id}: "
            f"predicted_direction must be one of "
            f"{sorted(_VALID_DIRECTIONS)} — got {direction!r}"
        )
    event_date = _coerce_str(raw.get("event_date"))
    if event_date is not None and not _is_iso_date(event_date):
        errs.append(
            f"yes row event_id={event_id}: event_date must be "
            f"an ISO date (YYYY-MM-DD) — got {event_date!r}"
        )
    return errs


def _build_candidate(
    event_id: int, raw: dict[str, Any],
) -> dict[str, Any]:
    """Map worksheet columns to the curated_candidates DB column set.

    The worksheet's ``proposed_*`` columns become the DB's plain
    columns; ``operator_notes`` becomes ``curator_notes``.  Optional
    DB columns the worksheet does not carry land as ``None``.
    """
    return {
        "source_event_id":       event_id,
        "event_date":            _coerce_str(raw.get("event_date")),
        "headline":              _coerce_str(raw.get("headline")),
        "source_url":            _coerce_str(raw.get("source_url")),
        "primary_ticker":        _coerce_str(
            raw.get("proposed_primary_ticker")
        ),
        "benchmark_ticker":      _coerce_str(
            raw.get("proposed_benchmark_ticker")
        ),
        "mechanism_family":      _coerce_str(
            raw.get("proposed_mechanism_family")
        ),
        "mechanism_description": None,
        "predicted_direction":   _coerce_str(
            raw.get("predicted_direction")
        ),
        "prediction_rationale":  None,
        "curator_notes":         _coerce_str(raw.get("operator_notes")),
    }


def _gate_value(raw: Any) -> str:
    """Normalise a gate cell to ``yes`` / ``no`` / ``""``.

    Operator hand-input is case- and whitespace-insensitive — the
    worksheet carries the raw string, this helper produces the
    dispatch key.  Any non-empty value that isn't ``yes`` or ``no``
    is returned verbatim (lowercased / stripped) so the caller can
    surface a precise warning.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        s = raw.strip().lower()
        return s
    return str(raw).strip().lower()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _coerce_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s or None
    return str(v)


def _coerce_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        _dt.date.fromisoformat(value.strip())
        return True
    except (TypeError, ValueError):
        return False


def _hash_file_safe(path: str | None) -> str | None:
    if path is None:
        return None
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    try:
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Short-horizon review apply smoke", ""]
    lines.append(f"OK:                  {report['ok']}")
    lines.append(f"Worksheet path:      {report['worksheet_path']}")
    lines.append(f"Temp DB path:        {report['temp_db_path']}")
    lines.append(f"Accepted count:      {report['accepted_count']}")
    lines.append(f"Staged count:        {report['staged_count']}")
    lines.append(f"Staged event_ids:    {report['staged_event_ids']}")
    lines.append(f"Excluded count:      {report['excluded_count']}")
    lines.append(f"Pending count:       {report['pending_count']}")
    lines.append(f"Live DB unchanged:   {report['live_db_unchanged']}")
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
            "Temp-copy short-horizon reviewed decision apply smoke.  "
            "Applies operator-accepted rows from a reviewed worksheet "
            "into a TEMP copy of the live events DB as staged "
            "curated candidate rows.  Never opens the live DB for "
            "writes; never runs the validation pipeline.  Conservative "
            "wording: staged candidates, not validated, not proof."
        ),
    )
    parser.add_argument(
        "--worksheet", dest="worksheet_path", default=None,
        help=(
            "Path to the reviewed short-horizon worksheet CSV.  "
            "Required."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Defaults to ``db.DB_FILE``. "
            "Copied to a temp file before any write; never opened for "
            "writes."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _resolve_default_db_path() -> str | None:
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    db_path = args.db_path if args.db_path else _resolve_default_db_path()
    report = smoke_short_horizon_review_apply(
        worksheet_path=args.worksheet_path,
        db_path=db_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
