#!/usr/bin/env python3
"""Temp-copy manual ticker repair apply smoke.

Consumes a completed manual ticker repair packet CSV (the 11-column
worksheet emitted by :mod:`scripts.manual_ticker_repair_packet`) and
rehearses the apply flow against a *copied* backup of the events DB,
never touching the live archive.  The smoke is the read-only
operator dress rehearsal: it lets a human see exactly what would
change in the events table before any decision to promote the temp
copy.

Modes
-----

  * ``dry-run`` (default) — parses the CSV, categorizes each row
    (exclusion / retag / no-op / ambiguous), and reports the
    counts.  Does NOT copy any file, write any DB, or invoke the
    downstream readiness / contamination / clean-cohort reports.
    All ``before_*`` / ``after_*`` / ``*_delta`` fields are
    ``None`` in dry-run.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path <PATH> --csv-path <PATH>``.  In write mode the
    smoke (1) hashes the live DB and the input backup, (2) copies
    the backup to a fresh temp file, (3) inspects the temp DB
    schema for the exclusion column, (4) runs the clean-cohort
    and contamination reports against the temp DB to capture
    ``before`` counts, (5) applies the categorized CSV rows to
    the temp DB only, (6) re-runs the same two reports plus the
    readiness report against the post-apply temp DB to capture
    ``after`` counts, and (7) re-hashes the live DB and input
    backup, surfacing any drift as an error.

Apply semantics
---------------

  * **Exclusion row** (``exclude_reason`` set): set
    ``low_signal = 1`` on the matching event in the temp copy.
    ``low_signal`` is the safest existing field with
    "deprioritized / skip" semantics in the events schema; it is
    NOT currently consulted by the readiness, contamination, or
    clean-cohort reports, so an exclusion-only CSV will not move
    those counts.  That truthful behavior is pinned by the test
    suite; the smoke surfaces what the reports say, not what the
    operator wishes they said.
  * **Retag row** (``proposed_primary_ticker`` set): update the
    ``market_tickers`` JSON on the matching event.  Existing row
    content is preserved — the first list entry's other fields
    (e.g. ``weight``, ``role``) survive the update; only the
    ``symbol`` is replaced.  ``proposed_benchmark`` other than
    ``SPY`` (the project's universal benchmark) emits a warning
    but proceeds — the readiness pipeline only consults SPY.
  * **No-op row** (neither set): warning, skipped.
  * **Ambiguous row** (both set): error, NOT applied.
  * **Schema check**: if the CSV has at least one exclusion row
    AND the temp DB schema lacks ``low_signal``, the run fails
    closed with the verbatim error token
    ``schema_missing_exclusion_field``.  NEITHER exclusions NOR
    retags apply on this path — fail-closed is intentionally
    not partial.

Order of operations in write mode (this order matters; the apply
step is gated by the schema check so a temp copy is never
mutated for a fail-closed run)::

     1. validate flags (--write, --confirm, --backup-path,
        --csv-path)
     2. reject if backup_path == db_path
     3. reject if backup_path / csv_path do not exist
     4. hash live DB                      → live_hash_before
     5. hash input backup                 → backup_hash_before
     6. parse CSV                         → categorized rows
     7. copy backup → temp_copy_path
     8. inspect temp DB schema for low_signal column
     9. if exclusions exist & schema lacks column → fail closed,
        no apply
    10. run clean + contam reports        → before counts
    11. apply categorized rows to temp DB
    12. re-run clean + contam reports     → after counts
    13. run readiness report (sanity)
    14. re-hash live DB + input backup
    15. surface drift / errors; ok = (errors empty)

Patchable seams
---------------

Three module-level seams let unit tests drive the smoke without
touching the real readiness pipeline:

  * ``_run_readiness_report``  — wraps ``summarize_readiness``.
  * ``_run_contamination_report`` — wraps ``summarize_contamination``.
  * ``_run_clean_cohort_report`` — wraps ``summarize_clean_cohort``.

Output contract::

    {
      "ok":                              bool,
      "mode":                            "dry-run" | "write",
      "rows_read":                       int,
      "rows_excluded":                   int,
      "rows_retagged":                   int,
      "before_clean_fully_ready":        int | None,
      "after_clean_fully_ready":         int | None,
      "clean_fully_ready_delta":         int | None,
      "before_contaminated_fully_ready": int | None,
      "after_contaminated_fully_ready":  int | None,
      "live_db_unchanged":               bool,
      "input_backup_unchanged":          bool,
      "errors":                          [str, ...],
      "warnings":                        [str, ...],
    }

The output dict carries EXACTLY these 14 keys — no additive
fields.  The temp copy path is surfaced via a ``Temp copy at
<path>`` warning so the operator can locate it without polluting
the structured contract.  In dry-run, every ``before_*`` /
``after_*`` / ``*_delta`` field is ``None``.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.  It is hashed read-only.
* Input backup is NEVER opened for writes.  It is hashed read-
  only, then ``shutil.copy2``'d into a fresh temp file.
* No LLM, no FastAPI surface — never imports ``api`` /
  ``routes.*``.
* No provider, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache``.  The apply smoke does not
  touch the network.
* Default dry-run never imports the readiness / contamination /
  clean-cohort modules — those imports fire only on the un-
  patched write path through the seams.

Usage::

    python scripts/manual_ticker_repair_apply_smoke.py \\
        --dry-run --json --csv-path manual_ticker_repair_high_priority.csv
    python scripts/manual_ticker_repair_apply_smoke.py \\
        --write --confirm --backup-path /path/to/events.backup.db \\
        --csv-path manual_ticker_repair_high_priority.csv --json
"""
from __future__ import annotations

import argparse
import csv
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


_EXCLUSION_COLUMN: str = "low_signal"
_BENCHMARK_TICKER: str = "SPY"
_SCHEMA_MISSING_TOKEN: str = "schema_missing_exclusion_field"

# CSV columns the apply smoke needs to find.  The packet emits all
# 11 columns; we only require the four that drive apply decisions.
_REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "event_id",
    "proposed_primary_ticker",
    "proposed_benchmark",
    "exclude_reason",
)


# ---------------------------------------------------------------------------
# Patchable seams — module-level so tests can patch them.  The lazy
# imports resolve only on the un-patched path so the default dry-run
# never pulls the upstream report modules.
# ---------------------------------------------------------------------------


def _run_readiness_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_readiness_report import summarize_readiness

    return summarize_readiness(db_path=db_path, limit=0)


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(db_path=db_path, limit=0)


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(db_path=db_path, limit=0)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_apply_repair(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
    csv_path: str | None = None,
    write: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run the apply smoke and return the brief-mandated 14-key payload.

    See module docstring for the full order of operations.
    """
    errors: list[str] = []
    warnings: list[str] = []
    mode = "write" if write else "dry-run"

    rows_read = 0
    rows_excluded = 0
    rows_retagged = 0

    before_clean: int | None = None
    after_clean:  int | None = None
    before_contam: int | None = None
    after_contam:  int | None = None

    # Hash before any operation — defense in depth in dry-run, the
    # safety pin in write mode.  None when the path is missing /
    # unreadable; ``_hashes_match`` collapses missing-path comparisons
    # to True so the invariant is never spuriously violated.
    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    parsed_rows, parse_errs, parse_warns = _parse_csv_if_present(csv_path)
    errors.extend(parse_errs)
    warnings.extend(parse_warns)
    rows_read = len(parsed_rows)
    categorized = _categorize_rows(parsed_rows, errors, warnings)

    if write:
        # _do_write_mode mutates errors / warnings in place and returns
        # the post-run counters + before/after report numbers.
        (
            rows_excluded, rows_retagged,
            before_clean, after_clean,
            before_contam, after_contam,
        ) = _do_write_mode(
            db_path=db_path,
            backup_path=backup_path,
            csv_path=csv_path,
            confirm=confirm,
            categorized=categorized,
            errors=errors, warnings=warnings,
        )
    else:
        # Dry-run: count categories, do not touch any file or report.
        rows_excluded = sum(1 for r in categorized if r["kind"] == "exclude")
        rows_retagged = sum(1 for r in categorized if r["kind"] == "retag")

    live_hash_after   = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)

    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after, path=backup_path,
    )
    if not live_db_unchanged:
        errors.append(
            f"LIVE DB BYTES CHANGED during apply smoke — investigate: "
            f"{db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during apply smoke — investigate: "
            f"{backup_path}"
        )

    clean_delta: int | None
    if before_clean is None or after_clean is None:
        clean_delta = None
    else:
        clean_delta = after_clean - before_clean

    return {
        "ok":                              not errors,
        "mode":                            mode,
        "rows_read":                       rows_read,
        "rows_excluded":                   rows_excluded,
        "rows_retagged":                   rows_retagged,
        "before_clean_fully_ready":        before_clean,
        "after_clean_fully_ready":         after_clean,
        "clean_fully_ready_delta":         clean_delta,
        "before_contaminated_fully_ready": before_contam,
        "after_contaminated_fully_ready":  after_contam,
        "live_db_unchanged":               live_db_unchanged,
        "input_backup_unchanged":          input_backup_unchanged,
        "errors":                          errors,
        "warnings":                        warnings,
    }


# ---------------------------------------------------------------------------
# Mode-specific subroutines
# ---------------------------------------------------------------------------


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None, csv_path: str | None,
    confirm: bool, categorized: list[dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> tuple[int, int, int | None, int | None, int | None, int | None]:
    """Execute the write-mode order of operations.

    Returns ``(rows_excluded, rows_retagged, before_clean,
    after_clean, before_contam, after_contam)``.  Any fatal
    short-circuit returns zeros / Nones and appends to ``errors``.
    """
    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return 0, 0, None, None, None, None
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return 0, 0, None, None, None, None
    if not csv_path:
        errors.append("--write requires --csv-path; refusing to write")
        return 0, 0, None, None, None, None

    # Step 2: same-path defense.
    if db_path:
        try:
            same_path = (
                Path(backup_path).resolve() == Path(db_path).resolve()
            )
        except OSError:
            same_path = False
        if same_path:
            errors.append(
                "--backup-path must differ from --db-path; refusing "
                "to write (would mutate the live DB)"
            )
            return 0, 0, None, None, None, None

    # Step 3: backup + csv must exist.
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return 0, 0, None, None, None, None
    if not Path(csv_path).exists():
        errors.append(f"--csv-path does not exist: {csv_path}")
        return 0, 0, None, None, None, None

    # Step 7: copy backup → temp.  Done before the schema check so the
    # operator always has an artifact to inspect, even on a fail-
    # closed schema-missing run.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return 0, 0, None, None, None, None
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 8-9: schema check.  Fail closed if exclusions need a
    # column the temp DB doesn't have.
    has_exclusions = any(r["kind"] == "exclude" for r in categorized)
    schema_has_low_signal = _has_low_signal_column(temp_copy_path)
    if has_exclusions and not schema_has_low_signal:
        errors.append(
            f"{_SCHEMA_MISSING_TOKEN}: temp DB lacks "
            f"{_EXCLUSION_COLUMN!r} column — refusing to apply any rows"
        )
        return 0, 0, None, None, None, None

    # Step 10: before counts.
    try:
        before_clean = _safe_int(
            _safe_dict(_run_clean_cohort_report(db_path=temp_copy_path))
            .get("clean_fully_ready_count")
        )
        before_contam = _safe_int(
            _safe_dict(_run_contamination_report(db_path=temp_copy_path))
            .get("suspicious_count")
        )
    except Exception as e:
        errors.append(f"Pre-apply report failed: {e}")
        return 0, 0, None, None, None, None

    # Step 11: apply categorized rows.
    try:
        applied_excluded, applied_retagged = _apply_categorized_to_temp(
            temp_copy_path, categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB apply failed: {e}")
        return 0, 0, before_clean, None, before_contam, None

    # Step 12-13: after counts + readiness sanity check.
    try:
        after_clean = _safe_int(
            _safe_dict(_run_clean_cohort_report(db_path=temp_copy_path))
            .get("clean_fully_ready_count")
        )
        after_contam = _safe_int(
            _safe_dict(_run_contamination_report(db_path=temp_copy_path))
            .get("suspicious_count")
        )
    except Exception as e:
        errors.append(f"Post-apply report failed: {e}")
        return (
            applied_excluded, applied_retagged,
            before_clean, None, before_contam, None,
        )

    try:
        _run_readiness_report(db_path=temp_copy_path)
    except Exception as e:
        # Readiness doubles as a sanity check; surface failure but
        # don't null the captured counts.
        errors.append(f"Post-apply readiness probe failed: {e}")

    return (
        applied_excluded, applied_retagged,
        before_clean, after_clean, before_contam, after_contam,
    )


# ---------------------------------------------------------------------------
# CSV parsing + categorization
# ---------------------------------------------------------------------------


def _parse_csv_if_present(
    csv_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Parse the CSV at ``csv_path`` into a list of row dicts.

    Returns ``(rows, errors, warnings)``.  Missing path is silent
    (callers will surface a flag-level error elsewhere).  Missing
    required columns surface as an error.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not csv_path:
        return [], errors, warnings
    if not Path(csv_path).exists():
        # Caller's flag validator will surface the missing-csv error;
        # parsing silently returns an empty list so dry-run can still
        # produce a 14-key payload.
        return [], errors, warnings

    try:
        with open(csv_path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            missing = [
                f for f in _REQUIRED_CSV_FIELDS if f not in fieldnames
            ]
            if missing:
                errors.append(
                    f"CSV missing required columns: {', '.join(missing)}"
                )
                return [], errors, warnings
            rows = [dict(r) for r in reader]
    except OSError as e:
        errors.append(f"Failed to read CSV {csv_path}: {e}")
        return [], errors, warnings

    return rows, errors, warnings


def _categorize_rows(
    rows: list[dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> list[dict[str, Any]]:
    """Bucket each parsed CSV row into one of {exclude, retag}.

    Ambiguous rows (both ``proposed_primary_ticker`` and
    ``exclude_reason`` set) and no-op rows (neither set) are
    surfaced via ``errors`` / ``warnings`` and excluded from the
    returned list — they are not applied.
    """
    out: list[dict[str, Any]] = []
    for raw in rows:
        ev_id_raw = (raw.get("event_id") or "").strip()
        try:
            ev_id = int(ev_id_raw)
        except (TypeError, ValueError):
            warnings.append(
                f"Skipping row with unparseable event_id: {ev_id_raw!r}"
            )
            continue
        proposed = (raw.get("proposed_primary_ticker") or "").strip()
        exclude  = (raw.get("exclude_reason") or "").strip()
        benchmark = (raw.get("proposed_benchmark") or "").strip()
        if proposed and exclude:
            errors.append(
                f"event_id {ev_id}: ambiguous row — both "
                f"proposed_primary_ticker and exclude_reason are set"
            )
            continue
        if not proposed and not exclude:
            warnings.append(
                f"event_id {ev_id}: no-op row (no proposal, no exclusion) "
                f"— skipping"
            )
            continue
        if exclude:
            out.append({"kind": "exclude", "event_id": ev_id,
                        "reason": exclude})
        else:
            if benchmark and benchmark.upper() != _BENCHMARK_TICKER:
                warnings.append(
                    f"event_id {ev_id}: proposed_benchmark "
                    f"{benchmark!r} is not {_BENCHMARK_TICKER!r}; the "
                    f"readiness pipeline only consults SPY — recording "
                    f"the symbol but not mutating benchmark fields"
                )
            out.append({
                "kind": "retag", "event_id": ev_id,
                "symbol":    proposed.upper(),
                "benchmark": benchmark.upper(),
            })
    return out


# ---------------------------------------------------------------------------
# Apply step — temp DB only
# ---------------------------------------------------------------------------


def _apply_categorized_to_temp(
    temp_db_path: str, categorized: list[dict[str, Any]],
    warnings: list[str],
) -> tuple[int, int]:
    """Apply categorized rows to the temp DB.  Returns
    ``(rows_excluded, rows_retagged)``.

    Exclusions flip ``low_signal=1``.  Retags update
    ``market_tickers`` JSON, preserving any non-symbol fields on
    the first list entry.  Rows whose event_id is not in the temp
    DB are skipped with a warning.
    """
    rows_excluded = 0
    rows_retagged = 0
    conn = sqlite3.connect(temp_db_path)
    try:
        for row in categorized:
            ev_id = row["event_id"]
            existing = conn.execute(
                "SELECT market_tickers FROM events WHERE id = ?",
                (ev_id,),
            ).fetchone()
            if existing is None:
                warnings.append(
                    f"event_id {ev_id} not in temp events table — "
                    f"skipping"
                )
                continue
            if row["kind"] == "exclude":
                conn.execute(
                    f"UPDATE events SET {_EXCLUSION_COLUMN} = 1 "
                    f"WHERE id = ?",
                    (ev_id,),
                )
                rows_excluded += 1
            elif row["kind"] == "retag":
                current_mt_json = existing[0] or "[]"
                new_mt_json = _retag_market_tickers(
                    current_mt_json, row["symbol"],
                )
                conn.execute(
                    "UPDATE events SET market_tickers = ? WHERE id = ?",
                    (new_mt_json, ev_id),
                )
                rows_retagged += 1
        conn.commit()
    finally:
        conn.close()
    return rows_excluded, rows_retagged


def _retag_market_tickers(current_json: str, new_symbol: str) -> str:
    """Replace the first entry's ``symbol`` while preserving any
    other fields on that entry.  When the JSON is unparseable / not a
    list / empty, returns ``[{"symbol": new_symbol}]``.
    """
    try:
        parsed = json.loads(current_json)
    except (TypeError, ValueError):
        parsed = None
    if not isinstance(parsed, list) or not parsed:
        return json.dumps([{"symbol": new_symbol}])
    first = parsed[0]
    if isinstance(first, dict):
        first["symbol"] = new_symbol
    else:
        parsed[0] = {"symbol": new_symbol}
    return json.dumps(parsed)


# ---------------------------------------------------------------------------
# Schema probe
# ---------------------------------------------------------------------------


def _has_low_signal_column(db_path: str) -> bool:
    """True iff the events table in ``db_path`` has a ``low_signal``
    column.  Returns False on any error reading the schema — callers
    treat that as schema-missing and fail closed.
    """
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return False
    try:
        try:
            rows = conn.execute(
                "PRAGMA table_info(events)"
            ).fetchall()
        except sqlite3.Error:
            return False
        return any(
            isinstance(r, tuple) and len(r) >= 2 and r[1] == _EXCLUSION_COLUMN
            for r in rows
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Hash + temp-copy plumbing
# ---------------------------------------------------------------------------


def _hash_file_safe(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _hashes_match(
    *, before: str | None, after: str | None, path: str | None,
) -> bool:
    if path is None:
        return True
    return before == after


def _copy_to_fresh_temp(src_path: str) -> str:
    src = Path(src_path)
    dst_name = f"apply_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(src_path, str(dst))
    return str(dst)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Manual ticker repair apply smoke", ""]
    lines.append(f"Mode:                              {report['mode']}")
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Rows excluded:                     {report['rows_excluded']}")
    lines.append(f"Rows retagged:                     {report['rows_retagged']}")
    lines.append(
        f"before_clean_fully_ready:          "
        f"{report['before_clean_fully_ready']}"
    )
    lines.append(
        f"after_clean_fully_ready:           "
        f"{report['after_clean_fully_ready']}"
    )
    lines.append(
        f"clean_fully_ready_delta:           "
        f"{report['clean_fully_ready_delta']}"
    )
    lines.append(
        f"before_contaminated_fully_ready:   "
        f"{report['before_contaminated_fully_ready']}"
    )
    lines.append(
        f"after_contaminated_fully_ready:    "
        f"{report['after_contaminated_fully_ready']}"
    )
    lines.append(
        f"Live DB unchanged:                 {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:            {report['input_backup_unchanged']}"
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
            "Temp-copy manual ticker repair apply smoke.  Default is "
            "a read-only dry-run that categorizes the CSV.  Write "
            "mode requires --write --confirm --backup-path --csv-path "
            "together; the smoke copies the backup to a temp file, "
            "applies the categorized CSV rows to the temp copy ONLY, "
            "and runs the readiness / contamination / clean-cohort "
            "reports against the temp DB.  Live events.db is never "
            "opened for writes."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", dest="dry_run", action="store_true",
        help="Run in read-only dry-run mode (default).",
    )
    mode.add_argument(
        "--write", dest="write", action="store_true",
        help=(
            "Enable write mode.  Requires --confirm, --backup-path, "
            "and --csv-path."
        ),
    )
    parser.add_argument(
        "--confirm", dest="confirm", action="store_true",
        help="Required co-flag for --write.",
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help=(
            "Path to a backup of the events DB.  Required for --write. "
            "Must differ from --db-path.  The backup is hashed but "
            "never mutated; the smoke copies it to a temp file and "
            "applies there."
        ),
    )
    parser.add_argument(
        "--csv-path", dest="csv_path", default=None,
        help=(
            "Path to the completed manual_ticker_repair_packet CSV.  "
            "Required in both dry-run and write modes (dry-run "
            "categorizes; write mode applies)."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes.  When "
            "omitted, defaults to ``db.DB_FILE``."
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
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    db_path = args.db_path if args.db_path else _resolve_default_db_path()

    report = smoke_apply_repair(
        db_path=db_path,
        backup_path=args.backup_path,
        csv_path=args.csv_path,
        write=bool(args.write),
        confirm=bool(args.confirm),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
