#!/usr/bin/env python3
"""Temp-copy SPY benchmark-cache backfill smoke.

Demonstrates the SPY backfill flow against a *copied* backup of the
events DB, never touching the live archive.  The purpose is to give
operators a one-command rehearsal of the write path: plan with the
preflight, fetch SPY rows, write into a temp copy, and verify both
the live DB and the input backup are byte-identical at the end.

Modes
-----

  * ``dry-run`` (default) — runs the preflight, reports
    ``rows_planned``, and exits.  Does not call the provider, does
    not copy any file, does not write any DB.  ``rows_written`` is
    always ``0``.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path <PATH>``.  In this mode the smoke (1) hashes the
    live DB and the input backup, (2) checks the provider is
    available — failing closed if not, (3) runs the preflight
    against the backup, (4) copies the backup to a fresh temp
    file, (5) fetches SPY rows for the planned range, (6) writes
    them into the temp copy only, and (7) re-hashes the live DB
    and input backup, surfacing any drift as an error.

Order of operations in write mode (this order matters: the temp
copy is never created for a run that will fail closed)::

     1. validate flags (--write, --confirm, --backup-path)
     2. reject if backup_path == db_path
     3. reject if backup_path does not exist
     4. hash live DB                  → live_hash_before
     5. hash input backup             → backup_hash_before
     6. provider availability check   → fail closed if False
     7. run preflight against backup  → rows_planned, [start, end]
     8. copy backup → temp_copy_path
     9. fetch SPY rows via seam       → list[dict]
    10. INSERT OR IGNORE into temp_copy.price_cache
    11. run readiness report twice
        (backup → before, temp_copy → after) → readiness_delta
    12. re-hash live DB + input backup
    13. surface drift as errors; ok = (errors empty)

Step 11 only runs on the fully successful write path.  Any earlier
short-circuit (flag rejection, missing backup, provider unavailable,
zero planned, fetch failure, write failure) leaves
``readiness_delta = None``.  If the readiness report itself raises,
the run is marked failed (``ok=False``, error surfaced) but the
post-run hash check (step 12) still runs — the safety claim is never
skipped.

Patchable seams
---------------

Four module-level seams let unit tests drive the smoke without
touching yfinance, the network, or the real archive:

  * ``_run_preflight`` — wraps
    :func:`scripts.benchmark_cache_backfill_preflight.summarize_backfill_preflight`.
  * ``_check_provider_available`` — soft import-only probe; True iff
    ``yfinance`` is importable.  No network call.
  * ``_fetch_spy_rows`` — would shell out to yfinance to fetch the
    daily bars for ``[start, end]``.  Tests patch this seam to
    return synthetic rows; production would shell out to yfinance.
  * ``_run_readiness_report`` — wraps
    :func:`scripts.stat_validation_readiness_report.summarize_readiness`.
    Called once against the input backup (``before``) and once
    against the temp copy (``after``) on the successful write path
    only.

Output contract::

    {
      "ok":                     bool,
      "mode":                   "dry-run" | "write",
      "backup_path":            str | None,
      "temp_copy_path":         str | None,
      "rows_planned":           int,
      "rows_written":           int,
      "live_db_unchanged":      bool,
      "input_backup_unchanged": bool,
      "readiness_delta":        {
          "before_fully_ready":             int,
          "after_fully_ready":              int,
          "fully_ready_delta":              int,
          "before_missing_benchmark_proxy": int,
          "after_missing_benchmark_proxy":  int,
          "missing_benchmark_proxy_delta":  int,
      } | None,
      "errors":                 [str, ...],
      "warnings":               [str, ...],
    }

The output dict carries EXACTLY these 11 keys — no additive fields.
Downstream tooling can gate on ``ok`` and the two ``_unchanged``
flags without worrying about schema drift.  ``readiness_delta`` is
``None`` on every path that does not complete a temp-copy write
(dry-run, flag rejection, provider unavailable, zero planned,
fetch/write failure, readiness report failure).

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.  It is hashed read-only.
* Input backup is NEVER opened for writes.  It is hashed read-only,
  then ``shutil.copy2``'d into a fresh temp file; the temp copy is
  the only mutated artifact.
* No LLM, no FastAPI surface — never imports ``api`` / ``routes.*``.
* By default the smoke does not import ``yfinance``,
  ``market_check``, ``market_data``, or ``price_cache``.  Provider
  imports are deferred into the seams and only fire in write mode.
* The temp copy is NOT deleted by the smoke.  It is left in the
  system temp dir so the operator can inspect / promote / discard
  it manually.

Usage::

    python scripts/benchmark_cache_backfill_write_smoke.py --dry-run --json
    python scripts/benchmark_cache_backfill_write_smoke.py \
        --dry-run --json --limit 50
    python scripts/benchmark_cache_backfill_write_smoke.py \
        --write --confirm --backup-path /path/to/events.backup.db --json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
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


_DEFAULT_LIMIT: int = 25
_AUTO_ADJUST_DEFAULT: int = 1


# ---------------------------------------------------------------------------
# Patchable seams — module-level so tests can patch.object them.
# ---------------------------------------------------------------------------


def _run_preflight(*, db_path: str | None) -> dict[str, Any]:
    from scripts.benchmark_cache_backfill_preflight import (
        summarize_backfill_preflight,
    )

    return summarize_backfill_preflight(db_path=db_path)


def _check_provider_available() -> bool:
    """True iff ``yfinance`` is importable in this interpreter.  Does
    NOT make a network call.
    """
    try:
        import yfinance  # noqa: F401  (importability check only)
    except Exception:
        return False
    return True


def _fetch_spy_rows(*, start: str, end: str) -> list[dict[str, Any]]:
    """Fetch SPY daily bars for ``[start, end]`` (inclusive).  Returns
    rows shaped as ``{"date": ISO, "close": float, "volume": float}``.

    This function would call ``yfinance.download("SPY", start=start,
    end=end)`` in production.  Tests MUST patch this seam — the smoke
    has no environment that would tolerate a real network call.
    """
    import yfinance as yf  # local import — only fires in write mode

    # ``yf.download`` end is exclusive; bump by one day so [start, end]
    # is inclusive at both ends.
    end_d = _dt.date.fromisoformat(end) + _dt.timedelta(days=1)
    df = yf.download(
        "SPY", start=start, end=end_d.isoformat(), progress=False,
        auto_adjust=True,
    )
    out: list[dict[str, Any]] = []
    for idx, row in df.iterrows():
        out.append({
            "date":   idx.strftime("%Y-%m-%d"),
            "close":  float(row["Close"]),
            "volume": float(row["Volume"]),
        })
    return out


def _run_readiness_report(*, db_path: str) -> dict[str, Any]:
    """Wrap :func:`scripts.stat_validation_readiness_report.summarize_readiness`
    so tests can patch this seam without importing the readiness
    module themselves.  ``limit=0`` keeps the surfaced ``events`` list
    empty — the smoke only consumes the aggregate counts, never the
    per-event detail.
    """
    from scripts.stat_validation_readiness_report import (
        summarize_readiness,
    )

    return summarize_readiness(db_path=db_path, limit=0)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_backfill_write(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
    write: bool = False,
    confirm: bool = False,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the smoke and return the brief-mandated 10-key payload.

    See module docstring for the order-of-operations and contract.
    """
    del limit  # currently unused; reserved for parity with sibling
    # scripts and for future per-call row caps.

    errors: list[str] = []
    warnings: list[str] = []
    mode = "write" if write else "dry-run"

    rows_planned = 0
    rows_written = 0
    temp_copy_path: str | None = None
    readiness_delta: dict[str, int] | None = None

    # Hash both target files BEFORE any operation.  In dry-run this
    # is purely a defense-in-depth check; in write mode it pins the
    # safety claim.  ``None`` when path is missing or unreadable —
    # those cases collapse to "unchanged = True" by convention since
    # there is nothing to compare against.
    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    if write:
        (
            rows_planned, rows_written, temp_copy_path, readiness_delta,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path,
            confirm=confirm, errors=errors, warnings=warnings,
        )
    else:
        rows_planned = _do_dry_run_plan(
            db_path=db_path, backup_path=backup_path, errors=errors,
        )

    # Re-hash and compare.  If the smoke (or anything else) touched
    # the live DB or the input backup, surface the drift as a fatal
    # error.
    live_hash_after   = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)

    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after,
        path=backup_path,
    )
    if not live_db_unchanged:
        errors.append(
            f"LIVE DB BYTES CHANGED during smoke run — investigate: "
            f"{db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during smoke run — investigate: "
            f"{backup_path}"
        )

    ok = not errors

    return {
        "ok":                     ok,
        "mode":                   mode,
        "backup_path":            backup_path,
        "temp_copy_path":         temp_copy_path,
        "rows_planned":           rows_planned,
        "rows_written":           rows_written,
        "live_db_unchanged":      live_db_unchanged,
        "input_backup_unchanged": input_backup_unchanged,
        "readiness_delta":        readiness_delta,
        "errors":                 errors,
        "warnings":               warnings,
    }


# ---------------------------------------------------------------------------
# Mode-specific subroutines
# ---------------------------------------------------------------------------


def _do_dry_run_plan(
    *, db_path: str | None, backup_path: str | None,
    errors: list[str],
) -> int:
    """Run the preflight to surface ``rows_planned``.  No fetches, no
    copies, no writes.

    Source-of-truth precedence: backup_path → db_path → ``None``.  The
    plan reflects the *backup* when supplied, since that is what a
    write-mode run would target.
    """
    plan_db = backup_path if backup_path else db_path
    try:
        plan = _safe_dict(_run_preflight(db_path=plan_db))
    except Exception as e:
        errors.append(f"Preflight failed during dry-run: {e}")
        return 0
    return _safe_int(plan.get("estimated_rows_needed"))


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None,
    confirm: bool, errors: list[str], warnings: list[str],
) -> tuple[int, int, str | None, dict[str, int] | None]:
    """Execute the write-mode order of operations.

    Returns ``(rows_planned, rows_written, temp_copy_path,
    readiness_delta)``.  ``readiness_delta`` is a 6-key dict on the
    fully successful write path and ``None`` on every short-circuit
    (flag rejection, missing backup, provider unavailable, zero
    planned, fetch failure, write failure, readiness failure).
    """
    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return 0, 0, None, None
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return 0, 0, None, None

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
            return 0, 0, None, None

    # Step 3: backup must exist.
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return 0, 0, None, None

    # Steps 4-5 are done by the caller (hashes are needed for the
    # final comparison too — computing them once is cheaper).

    # Step 6: provider availability.  Fail closed BEFORE copying so
    # we don't leak temp artifacts for runs that can't proceed.
    if not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing"
        )
        return 0, 0, None, None

    # Step 7: preflight against the backup.
    try:
        plan = _safe_dict(_run_preflight(db_path=backup_path))
    except Exception as e:
        errors.append(f"Preflight failed: {e}")
        return 0, 0, None, None

    rows_planned = _safe_int(plan.get("estimated_rows_needed"))
    start = plan.get("required_start_date")
    end   = plan.get("required_end_date")

    if rows_planned == 0 or not isinstance(start, str) \
            or not isinstance(end, str):
        warnings.append(
            "rows_planned is zero or date range undefined — skipping "
            "provider call and temp copy"
        )
        return rows_planned, 0, None, None

    # Step 8: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return rows_planned, 0, None, None

    # Step 9: fetch via the seam.
    try:
        rows = _fetch_spy_rows(start=start, end=end)
    except Exception as e:
        errors.append(f"Provider fetch failed: {e}")
        return rows_planned, 0, temp_copy_path, None

    # Step 10: write to the temp copy ONLY.
    try:
        rows_written = _write_spy_rows_to_temp(temp_copy_path, rows)
    except sqlite3.Error as e:
        errors.append(f"Temp DB write failed: {e}")
        return rows_planned, 0, temp_copy_path, None

    # Step 11: post-write readiness delta.  ``before`` reads the
    # untouched input backup; ``after`` reads the temp copy.  If
    # the readiness call raises, fail closed with an error but
    # leave ``readiness_delta = None`` — the outer hash check
    # still runs.
    try:
        readiness_delta = _compute_readiness_delta(
            backup_path=backup_path, temp_copy_path=temp_copy_path,
        )
    except Exception as e:
        errors.append(f"Readiness report failed: {e}")
        readiness_delta = None

    return rows_planned, rows_written, temp_copy_path, readiness_delta


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _hash_file_safe(path: str | None) -> str | None:
    """Return SHA-256 hex digest of ``path``, or ``None`` if the path
    is missing / unreadable.  Never raises.
    """
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
    """True iff the file's hash is identical before and after the run.

    When ``path`` is ``None`` (operator did not supply a path) the
    invariant is vacuously satisfied.  When the path was supplied
    but unreadable, both hashes are ``None`` and equal — also fine.
    A drift between non-None values returns ``False``.
    """
    if path is None:
        return True
    return before == after


def _copy_to_fresh_temp(src_path: str) -> str:
    """Copy ``src_path`` to a fresh file in the system temp dir, with
    a uuid-suffixed name to avoid collisions.  Returns the destination
    path.  Uses ``shutil.copy2`` so file metadata is preserved (helps
    operator audits).
    """
    src = Path(src_path)
    dst_name = f"smoke_temp_{uuid.uuid4().hex}{src.suffix or '.db'}"
    dst = Path(tempfile.gettempdir()) / dst_name
    shutil.copy2(src_path, str(dst))
    return str(dst)


def _write_spy_rows_to_temp(
    temp_db_path: str, rows: Sequence[dict[str, Any]],
) -> int:
    """INSERT OR IGNORE the SPY rows into ``temp_db_path``'s
    ``price_cache`` table.  Returns the number of rows actually
    inserted (the diff in ``total_changes`` reported by SQLite).

    ``INSERT OR IGNORE`` rather than ``OR REPLACE`` is deliberate —
    if the temp copy already carries SPY rows for any of the dates
    we're writing, we leave them alone so the smoke is idempotent.
    """
    fetched_at = _dt.datetime.now(_dt.timezone.utc).isoformat()
    inserted = 0
    conn = sqlite3.connect(temp_db_path)
    try:
        for r in rows:
            d = r.get("date")
            if not isinstance(d, str) or not d:
                continue
            close  = r.get("close")
            volume = r.get("volume")
            cur = conn.execute(
                "INSERT OR IGNORE INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("SPY", d, close, volume, _AUTO_ADJUST_DEFAULT, fetched_at),
            )
            inserted += int(cur.rowcount or 0)
        conn.commit()
    finally:
        conn.close()
    return inserted


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _compute_readiness_delta(
    *, backup_path: str, temp_copy_path: str,
) -> dict[str, int]:
    """Return a 6-key delta dict comparing readiness of the input
    backup (``before``) vs the temp copy (``after``).

    Calls ``_run_readiness_report`` exactly twice — once per source.
    Either call raising propagates to the caller, which is responsible
    for converting it into a fail-closed error.
    """
    before = _safe_dict(_run_readiness_report(db_path=backup_path))
    after  = _safe_dict(_run_readiness_report(db_path=temp_copy_path))

    before_full = _safe_int(before.get("events_fully_ready"))
    after_full  = _safe_int(after.get("events_fully_ready"))
    before_miss = _safe_int(before.get("events_missing_benchmark_proxy"))
    after_miss  = _safe_int(after.get("events_missing_benchmark_proxy"))

    return {
        "before_fully_ready":             before_full,
        "after_fully_ready":              after_full,
        "fully_ready_delta":              after_full - before_full,
        "before_missing_benchmark_proxy": before_miss,
        "after_missing_benchmark_proxy":  after_miss,
        "missing_benchmark_proxy_delta":  after_miss - before_miss,
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["SPY benchmark-cache backfill smoke", ""]
    lines.append(f"Mode:                       {report['mode']}")
    lines.append(f"OK:                         {report['ok']}")
    lines.append(
        f"Backup path:                {report['backup_path'] or '-'}"
    )
    lines.append(
        f"Temp copy path:             {report['temp_copy_path'] or '-'}"
    )
    lines.append(
        f"Rows planned:               {report['rows_planned']}"
    )
    lines.append(
        f"Rows written (temp copy):   {report['rows_written']}"
    )
    lines.append(
        f"Live DB unchanged:          {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:     {report['input_backup_unchanged']}"
    )
    delta = report.get("readiness_delta")
    if isinstance(delta, dict):
        lines.append("")
        lines.append("Readiness delta (backup → temp copy):")
        lines.append(
            f"  fully_ready:              "
            f"{delta.get('before_fully_ready')} → "
            f"{delta.get('after_fully_ready')} "
            f"(Δ {delta.get('fully_ready_delta')})"
        )
        lines.append(
            f"  missing_benchmark_proxy:  "
            f"{delta.get('before_missing_benchmark_proxy')} → "
            f"{delta.get('after_missing_benchmark_proxy')} "
            f"(Δ {delta.get('missing_benchmark_proxy_delta')})"
        )
    else:
        lines.append("Readiness delta:            -")
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
            "Temp-copy SPY benchmark-cache backfill smoke.  Default "
            "is a read-only dry-run that reports rows_planned via "
            "the preflight.  Write mode requires --write --confirm "
            "--backup-path together; the smoke copies the backup "
            "to a temp file, fetches SPY rows, and writes them into "
            "the temp copy ONLY.  Live events.db is never opened "
            "for writes; both the live DB and the input backup are "
            "verified byte-identical via SHA-256 before/after."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run", action="store_true",
        help="Run in read-only dry-run mode (default).",
    )
    mode.add_argument(
        "--write",
        dest="write", action="store_true",
        help=(
            "Enable write mode.  Requires --confirm and --backup-path."
        ),
    )
    parser.add_argument(
        "--confirm",
        dest="confirm", action="store_true",
        help=(
            "Required co-flag for --write.  Forces an explicit "
            "operator gesture before the smoke will copy / fetch / "
            "write."
        ),
    )
    parser.add_argument(
        "--backup-path",
        dest="backup_path", default=None,
        help=(
            "Path to a backup of the events DB.  Required for --write. "
            "Must differ from --db-path.  The backup is hashed but "
            "never mutated; the smoke copies it to a temp file and "
            "writes there."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes.  When "
            "omitted, defaults to ``db.DB_FILE`` so the preflight "
            "follows the project's configured archive."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Reserved for parity with sibling scripts (default "
            f"{_DEFAULT_LIMIT}).  Currently unused — aggregate counts "
            f"reflect every blocked event."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
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

    report = smoke_backfill_write(
        db_path=db_path,
        backup_path=args.backup_path,
        write=bool(args.write),
        confirm=bool(args.confirm),
        limit=args.limit,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
