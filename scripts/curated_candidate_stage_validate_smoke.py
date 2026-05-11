#!/usr/bin/env python3
"""Read-only curated stage + validation evidence smoke.

Stages the repaired cohort (event_ids 30, 40, 46, 60, 73) as
``curated_candidates`` rows in a TEMP copy of the live events DB,
then runs :mod:`scripts.curated_candidate_validation_run` against
that temp DB and surfaces SAR / CI / p / FDR for the staged set.

The smoke is a transparent demo of the stage → validate flow: an
operator can run it without any API call and inspect the JSON
artifact to see what evidence the existing read-only validation
pipeline produces from the staged cohort.

Order of operations
-------------------

  1. Hash the live DB (read-only invariant).
  2. Copy live DB → fresh temp file via ``_copy_live_db_to_temp``.
  3. Stage 5 hardcoded curated_candidate rows (one per repaired
     event_id) into the TEMP DB's ``curated_candidates`` table.
     Status is set to ``ready_for_validation`` so the validation
     runner picks them up.
  4. Run :func:`scripts.curated_candidate_validation_run.run_curated_candidate_validation`
     against the temp DB via ``_run_curated_validation``.
  5. Reshape the runner's 13-key payload into the spec's 10-key
     output (drops ``ok``, ``missing_fields``,
     ``recommended_next_action``; renames ``staged_candidate_count``
     → ``staged_count``).
  6. Optionally persist to ``--output`` path.
  7. Re-hash the live DB and surface drift as an error.

Repaired cohort
---------------

The 5 events in :data:`_REPAIRED_COHORT` are the post-repair clean
events from prior repair-cohort smokes — events that the operator
has already triaged through the high-priority + medium ticker
repair + mechanism-family repair workflows.  Their metadata
(primary_ticker, benchmark_ticker, mechanism_family) is the
operator-supplied set, NOT whatever the live events table currently
shows; the curated_candidate row is the source of truth.

Patchable seams
---------------

  * ``_copy_live_db_to_temp(*, src_path)`` — ``shutil.copy2`` from
    src into a fresh ``tempfile.gettempdir()`` file.
  * ``_stage_candidates_into_temp(*, temp_db_path, candidates)`` —
    INSERT each candidate dict into the temp DB's curated_candidates
    table.  Uses ``status = 'ready_for_validation'``.
  * ``_run_curated_validation(*, db_path)`` — wraps
    :func:`scripts.curated_candidate_validation_run.run_curated_candidate_validation`.
    Tests patch this seam to drive the smoke without invoking the
    full archive validation pipeline.

Output contract::

    {
      "staged_count":         int,
      "events_evaluated":     int,
      "records_count":        int,
      "significant_count":    int,
      "by_horizon":           {str: {...}},
      "by_mechanism_family":  {str: {...}},
      "examples":             [{...}, ...],
      "excluded_candidates":  [{source_event_id, reasons}, ...],
      "warnings":             [str, ...],
      "errors":               [str, ...],
    }

The output dict carries EXACTLY these 10 keys — no ``ok`` envelope
(by spec).  The ``errors`` list is non-empty when something failed.

Each example in the ``examples`` list inherits the runner's 16-field
shape, which now includes the three demo-facing verdict fields
``raw_p_candidate`` / ``fdr_significant`` / ``verdict``.  The smoke
propagates these fields verbatim — it never recomputes statistics.
A raw-p-only record (event 46- or 73-style) lands with
``verdict="validated_raw_only"`` while still carrying the upstream
``interpretation="not_significant"`` label, so a demo reader sees
the raw-p / FDR split without weakening FDR discipline.

Out of scope (deliberately)
---------------------------

* Live DB is NEVER opened for writes.
* No provider, no LLM, no FastAPI, no yfinance — every numeric
  comes from the existing ``price_cache`` via the validation
  pipeline.
* Synthetic results are NEVER fabricated; if the validation
  pipeline produces zero records for an event, that event is
  documented in ``excluded_candidates`` with a reason.

Conservative wording
--------------------

The events surfaced are "staged candidate evidence," not proof,
not a validated archive.  Banned over-claims (``automatically``,
``alpha generated``, ``definitely validated``, ``is proven``)
never appear in any text the smoke emits.

Usage::

    python scripts/curated_candidate_stage_validate_smoke.py
    python scripts/curated_candidate_stage_validate_smoke.py --json
    python scripts/curated_candidate_stage_validate_smoke.py --json \\
        --output evidence.json
"""
from __future__ import annotations

import argparse
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


# ---------------------------------------------------------------------------
# The repaired cohort — 5 events the operator has already triaged
# through the prior repair workflows.  Metadata mirrors the prior
# repair-packet decisions so the curated row is the operator's
# source-of-truth view of each event.
# ---------------------------------------------------------------------------


_REPAIRED_COHORT: tuple[dict[str, Any], ...] = (
    {
        "source_event_id":       30,
        "event_date":            "2026-04-05",
        "headline":              (
            "US fighter jet shot down over Iran, search underway for "
            "crew member, US officials say - Reuters"
        ),
        "source_url":            None,
        "primary_ticker":        "XOM",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "supply_shock",
        "mechanism_description": (
            "US-Iran military escalation creates Gulf oil supply "
            "disruption risk; XOM is a liquid US oil-major proxy."
        ),
        "predicted_direction":   "up",
        "prediction_rationale":  "Supply chokepoint risk lifts crude proxy.",
        "curator_notes":         "From mechanism_family_repair_packet.csv.",
    },
    {
        "source_event_id":       40,
        "event_date":            "2026-04-05",
        "headline":              (
            "Petronas-chartered tanker loaded with Iraqi crude passes "
            "through Hormuz"
        ),
        "source_url":            None,
        "primary_ticker":        "BDRY",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "commodity_squeeze",
        "mechanism_description": (
            "Hormuz crude transit is a shipping chokepoint; "
            "commodity_squeeze is the canonical family."
        ),
        "predicted_direction":   "up",
        "prediction_rationale":  "Shipping chokepoint risk premium.",
        "curator_notes":         "From mechanism_family_repair_packet.csv.",
    },
    {
        "source_event_id":       46,
        "event_date":            "2026-04-06",
        "headline":              (
            "Federal Reserve Board announces section 23A exemption "
            "for Morgan Stanley Bank, N.A."
        ),
        "source_url":            None,
        "primary_ticker":        "MS",
        "benchmark_ticker":      "SPY",
        "mechanism_family":      "bank_regulatory_capital_relief",
        "mechanism_description": (
            "Section 23A exemption lifts capital flexibility at the "
            "bank subsidiary; parent equity absorbs the surprise."
        ),
        "predicted_direction":   "up",
        "prediction_rationale":  "Capital relief lifts dividend capacity.",
        "curator_notes":         "From manual_ticker_repair_high_priority.csv.",
    },
    {
        "source_event_id":       60,
        "event_date":            "2026-04-08",
        "headline":              (
            "FirstFT: Trump threatens to attack Iran's power plants "
            "and bridges unless it reopens Strait of Hormuz"
        ),
        "source_url":            None,
        "primary_ticker":        "XOM",
        "benchmark_ticker":      "XLE",
        "mechanism_family":      "supply_shock",
        "mechanism_description": (
            "Hormuz reopening threat is an oil-supply chokepoint "
            "risk; XOM is the liquid US oil major proxy."
        ),
        "predicted_direction":   "up",
        "prediction_rationale":  "Chokepoint risk lifts crude basis.",
        "curator_notes":         "From manual_ticker_repair_medium_production_like.csv.",
    },
    {
        "source_event_id":       73,
        "event_date":            "2026-04-06",
        "headline":              (
            "OPEC members agree to extend voluntary oil output cuts "
            "through next quarter"
        ),
        "source_url":            None,
        "primary_ticker":        "XOM",
        "benchmark_ticker":      "XLE",
        "mechanism_family":      "supply_shock",
        "mechanism_description": (
            "OPEC voluntary output-cut extension is a textbook "
            "supply-side shock for crude."
        ),
        "predicted_direction":   "up",
        "prediction_rationale":  "Tighter supply lifts oil-major earnings.",
        "curator_notes":         "From manual_ticker_repair_medium_production_like.csv.",
    },
)


# Per-row column order for the INSERT statement.  Mirrors the
# ``curated_candidates`` schema in ``db.py``.
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


_OUTPUT_KEYS: tuple[str, ...] = (
    "staged_count",
    "events_evaluated",
    "records_count",
    "significant_count",
    "by_horizon",
    "by_mechanism_family",
    "examples",
    "excluded_candidates",
    "warnings",
    "errors",
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
        f"curated_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
    )
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(str(src), str(dst))
    return str(dst)


def _stage_candidates_into_temp(
    *, temp_db_path: str, candidates: Sequence[dict[str, Any]],
) -> int:
    """INSERT each curated candidate dict into the temp DB's
    ``curated_candidates`` table.  Sets status to
    ``ready_for_validation`` so the validation runner picks the
    rows up.

    Returns the number of rows inserted.  Rows whose ``UNIQUE``
    (``source_event_id``, ``source``) constraint is violated are
    skipped silently — the smoke is idempotent against repeated
    runs against the same temp DB.
    """
    if not candidates:
        return 0
    inserted = 0
    created_at = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()
    placeholders = ",".join(["?"] * len(_INSERT_COLUMNS))
    sql = (
        f"INSERT OR IGNORE INTO curated_candidates "
        f"({', '.join(_INSERT_COLUMNS)}) VALUES ({placeholders})"
    )
    conn = sqlite3.connect(temp_db_path)
    try:
        for cand in candidates:
            row = (
                cand.get("source_event_id"),
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
                "ready_for_validation",
                cand.get("source", "stage_validate_smoke"),
                created_at,
            )
            cur = conn.execute(sql, row)
            if cur.rowcount > 0:
                inserted += 1
        conn.commit()
    finally:
        conn.close()
    return inserted


def _run_curated_validation(*, db_path: str) -> dict[str, Any]:
    """Wrap
    :func:`scripts.curated_candidate_validation_run.run_curated_candidate_validation`
    so tests patch a single surface.  Lazy import keeps the
    runner off the un-patched path's import cost when callers
    drive the smoke with synthetic payloads.
    """
    from scripts.curated_candidate_validation_run import (
        run_curated_candidate_validation,
    )

    return run_curated_candidate_validation(db_path=db_path)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_curated_stage_validate(
    *, db_path: str | None = None, output_path: str | None = None,
) -> dict[str, Any]:
    """Run the curated stage + validation evidence smoke.  Returns
    the 10-key payload described in the module docstring.
    """
    errors:   list[str] = []
    warnings: list[str] = []

    live_path = _resolve_db_path(db_path)
    if live_path is None:
        errors.append(
            "could not resolve a live events DB path — set db.DB_FILE "
            "or pass --db-path explicitly"
        )
        return _empty_payload(errors=errors)

    if not Path(live_path).exists():
        errors.append(f"events DB does not exist: {live_path}")
        return _empty_payload(errors=errors)

    live_hash_before = _hash_file(live_path)

    try:
        temp_path = _copy_live_db_to_temp(src_path=live_path)
    except OSError as e:
        errors.append(f"failed to copy live DB to temp: {e}")
        return _empty_payload(errors=errors)
    warnings.append(f"Temp copy at {temp_path}")

    try:
        inserted = _stage_candidates_into_temp(
            temp_db_path=temp_path, candidates=_REPAIRED_COHORT,
        )
    except sqlite3.Error as e:
        errors.append(f"failed to stage candidates into temp DB: {e}")
        return _finalize(
            inserted=0, runner_payload={}, warnings=warnings, errors=errors,
            live_path=live_path, live_hash_before=live_hash_before,
            output_path=output_path,
        )
    if inserted < len(_REPAIRED_COHORT):
        warnings.append(
            f"staged {inserted}/{len(_REPAIRED_COHORT)} candidates; "
            f"others were already present in temp DB (UNIQUE constraint)."
        )

    try:
        runner_payload = _run_curated_validation(db_path=temp_path)
    except Exception as e:  # noqa: BLE001 — operator-visible
        errors.append(f"curated validation runner failed: {e}")
        runner_payload = {}

    return _finalize(
        inserted=inserted, runner_payload=runner_payload,
        warnings=warnings, errors=errors,
        live_path=live_path, live_hash_before=live_hash_before,
        output_path=output_path,
    )


def _finalize(
    *, inserted: int, runner_payload: dict[str, Any],
    warnings: list[str], errors: list[str],
    live_path: str, live_hash_before: str | None,
    output_path: str | None,
) -> dict[str, Any]:
    """Reshape the runner payload into the 10-key spec output, surface
    the live DB byte-identity invariant, and (optionally) persist to
    ``output_path``."""
    runner = runner_payload if isinstance(runner_payload, dict) else {}

    # Surface runner-side errors / warnings into our envelope.
    for e in runner.get("errors") or []:
        if isinstance(e, str) and e:
            errors.append(e)
    for w in runner.get("warnings") or []:
        if isinstance(w, str) and w:
            warnings.append(w)

    payload: dict[str, Any] = {
        "staged_count":         _coerce_int(
            runner.get("staged_candidate_count", inserted),
        ),
        "events_evaluated":     _coerce_int(runner.get("events_evaluated")),
        "records_count":        _coerce_int(runner.get("records_count")),
        "significant_count":    _coerce_int(runner.get("significant_count")),
        "by_horizon":           runner.get("by_horizon") or {},
        "by_mechanism_family":  runner.get("by_mechanism_family") or {},
        "examples":             list(runner.get("examples") or []),
        "excluded_candidates":  list(runner.get("excluded_candidates") or []),
        "warnings":             list(warnings),
        "errors":               list(errors),
    }

    # Re-hash the live DB and verify byte-identity.
    live_hash_after = _hash_file(live_path)
    if live_hash_before is not None and live_hash_before != live_hash_after:
        payload["errors"].append(
            f"LIVE DB BYTES CHANGED during stage+validate smoke — "
            f"investigate: {live_path}"
        )

    # Optional persistence.
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True, default=str)
        except OSError as e:
            payload["errors"].append(
                f"failed to write --output JSON to {output_path}: {e}"
            )

    return payload


def _empty_payload(*, errors: list[str]) -> dict[str, Any]:
    return {
        "staged_count":         0,
        "events_evaluated":     0,
        "records_count":        0,
        "significant_count":    0,
        "by_horizon":           {},
        "by_mechanism_family":  {},
        "examples":             [],
        "excluded_candidates":  [],
        "warnings":             [],
        "errors":               list(errors),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_file(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    h = hashlib.sha256()
    try:
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated stage + validation evidence smoke", ""]
    lines.append(f"Staged count:           {report['staged_count']}")
    lines.append(f"Events evaluated:       {report['events_evaluated']}")
    lines.append(f"Records count:          {report['records_count']}")
    lines.append(f"Significant count:      {report['significant_count']}")
    if report.get("excluded_candidates"):
        lines.append("")
        lines.append(
            f"Excluded candidates ({len(report['excluded_candidates'])}):"
        )
        for entry in report["excluded_candidates"]:
            lines.append(
                f"  source_event_id={entry.get('source_event_id')}: "
                f"{entry.get('reasons')}"
            )
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
            "Read-only curated stage + validation evidence smoke.  "
            "Stages the repaired cohort (event_ids 30, 40, 46, 60, 73) "
            "as curated_candidates rows in a TEMP copy of the live "
            "events DB and runs the existing curated-candidate "
            "validation runner against that temp DB.  Conservative "
            "language only — staged candidate evidence, not a "
            "validated archive."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of compact text.",
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to persist the JSON output to disk.  When "
            "omitted, no file is written."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = smoke_curated_stage_validate(
        db_path=args.db_path, output_path=args.output_path,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
