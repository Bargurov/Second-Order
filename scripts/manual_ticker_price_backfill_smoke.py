#!/usr/bin/env python3
"""Temp-copy price-cache backfill smoke for manually retagged tickers.

Consumes the completed manual ticker repair packet CSV (the 11-column
worksheet emitted by :mod:`scripts.manual_ticker_repair_packet`) and
rehearses the price-cache backfill flow for each operator-proposed
ticker against a *copied* backup of the events DB, never touching the
live archive.  The smoke is the read-only operator dress rehearsal:
it lets a human see exactly which (ticker, date) cells *would* be
fetched and written to the price_cache before any decision to promote
the temp copy.

Scope
-----

This script is paired with — but independent of —
:mod:`scripts.manual_ticker_repair_apply_smoke`.  The apply smoke
mutates ``events.market_tickers`` in a temp copy; this smoke
backfills ``price_cache`` rows for the operator-proposed tickers in
a separate temp copy.  The two are sequenced by the operator: apply
→ promote → backfill → promote.  Neither smoke retags AND backfills
in the same temp copy; the brief calls for two focused dress
rehearsals, not one combined apply.

Modes
-----

  * ``dry-run`` (default) — parses the CSV, computes the per-ticker
    merged window, and reports ``tickers_planned`` and
    ``price_rows_planned``.  Does NOT call the provider, does NOT
    copy any file, does NOT write any DB.  All ``before_*`` /
    ``after_*`` / ``*_delta`` fields are ``None`` in dry-run.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path <PATH> --csv-path <PATH>``.  In write mode the
    smoke (1) hashes the live DB and the input backup, (2) parses
    the CSV and computes the per-ticker plan, (3) fails closed if
    no retag rows are present, (4) probes provider availability and
    fails closed if absent, (5) copies the backup to a fresh temp
    file, (6) runs the clean-cohort and contamination reports
    against the temp DB to capture ``before`` counts, (7) fetches
    rows for each ticker's merged window via the provider seam, (8)
    inserts those rows into the temp copy ONLY, (9) re-runs the same
    two reports plus the readiness report against the post-write
    temp DB to capture ``after`` counts, and (10) re-hashes the live
    DB and input backup, surfacing any drift as an error.

Per-ticker window
-----------------

Each retag CSV row contributes its (proposed_primary_ticker,
event_date) pair.  Rows with the same ticker are merged into a
single window: ``[min(event_dates) - 75bd, max(event_dates) + 20bd]``
where ``bd`` = Mon–Fri business day.

The pre-event side is padded from the readiness check's 60-day
estimation-window requirement to 75 Mon–Fri days so the fetched
range covers ≥60 *actual* trading days even after US market
holidays (~3 per 60-trading-day window) drop out.  See the
``_PRE_EVENT_BDAYS`` comment for the full rationale.  20 forward
business days matches the longest readiness-check horizon
(``stat_validation_readiness_report._HORIZONS = (1, 5, 20)``);
that side is not padded because the readiness check only requires
"any cache row >= event_date + 20bd", not 20 distinct rows.

``price_rows_planned`` is the sum across tickers of the Mon–Fri
day count in each merged window.  The actual provider response may
return fewer rows (holidays, missing bars, market-data gaps);
``price_rows_written`` reflects the post-INSERT count from the temp
DB and may legitimately be lower.

Order of operations in write mode (this order matters; the temp
copy is never created for a run that will fail closed)::

     1. validate flags (--write, --confirm, --backup-path,
        --csv-path)
     2. reject if backup_path == db_path
     3. reject if backup_path / csv_path do not exist
     4. hash live DB                    → live_hash_before
     5. hash input backup               → backup_hash_before
     6. parse CSV + compute plan        → tickers_planned,
                                          price_rows_planned
     7. fail closed if no retag rows
     8. probe provider availability     → fail closed if False
     9. copy backup → temp_copy_path
    10. run clean + contam reports      → before counts
    11. fetch ticker rows via seam      → list[dict] per ticker
    12. INSERT OR IGNORE into temp_copy.price_cache
    13. re-run clean + contam reports   → after counts
    14. run readiness report (sanity)
    15. re-hash live DB + input backup
    16. surface drift / errors; ok = (errors empty)

Patchable seams
---------------

Five module-level seams let unit tests drive the smoke without
touching yfinance or the real readiness pipeline:

  * ``_run_readiness_report``      — wraps ``summarize_readiness``.
  * ``_run_contamination_report``  — wraps ``summarize_contamination``.
  * ``_run_clean_cohort_report``   — wraps ``summarize_clean_cohort``.
  * ``_check_provider_available``  — soft import-only probe; True iff
    ``yfinance`` is importable.  No network call.
  * ``_fetch_ticker_rows``         — would shell out to yfinance to
    fetch daily bars for ``(ticker, [start, end])``.  Tests MUST
    patch this seam.

Output contract::

    {
      "ok":                              bool,
      "mode":                            "dry-run" | "write",
      "rows_read":                       int,
      "tickers_planned":                 int,
      "price_rows_planned":              int,
      "price_rows_written":              int,
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

The output dict carries EXACTLY these 15 keys — no additive fields.
``tickers_planned`` is surfaced even on the provider-unavailable
fail-closed path so the operator can see what *would* have been
fetched.  The temp copy path is surfaced via a ``Temp copy at
<path>`` warning so the structured contract stays exact.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.
* Input backup is NEVER opened for writes.
* No LLM, no FastAPI surface.
* No retag — this script does NOT mutate ``events.market_tickers``;
  the operator still needs the apply smoke for that.  Backfilling
  MS price data against an un-retagged backup leaves event 46
  using DRIV; ``clean_fully_ready_delta`` will be 0 in that
  workflow.  Use the apply smoke first if you want the retag.
* Default dry-run never imports yfinance, ``market_check``,
  ``market_data``, ``price_cache``, or the readiness pipeline.
  Provider + report imports fire only on the un-patched write path.

Usage::

    python scripts/manual_ticker_price_backfill_smoke.py \\
        --dry-run --json --csv-path manual_ticker_repair_high_priority.csv
    python scripts/manual_ticker_price_backfill_smoke.py \\
        --write --confirm --backup-path /path/to/events.backup.db \\
        --csv-path manual_ticker_repair_high_priority.csv --json
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
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Pre-event fetch window in Mon–Fri days.
#
# Why 75 and not 60?  The readiness check
# (``stat_validation_readiness_report._ESTIMATION_WINDOW``) requires
# **60 distinct cache dates strictly before event_date** for
# ``estimation_window_sufficient`` to pass.  Counting straight Mon–Fri
# days back from event_date and asking yfinance for that range is
# *not* enough — US market holidays (MLK Day, Presidents Day, Good
# Friday, Memorial Day, Independence Day, Labor Day, Thanksgiving,
# Christmas, plus a handful of partial closures) drop ~10 trading
# days a year.  In any given 60-trading-day pre-event slice you can
# expect ~3 holidays.  Asking for 60 Mon–Fri days back returns ~57
# actual trading rows from yfinance — below the 60 threshold, so
# the event drops out of fully-ready for an estimation-window gap
# that is not a real readiness problem.
#
# Padding to 75 Mon–Fri days adds a 15-day cushion; even an
# unusually holiday-dense window (Thanksgiving+Christmas+New Year's)
# stays comfortably above 60 actual trading days.  The forward
# horizon (``_FORWARD_BDAYS_MAX = 20``) is left at 20: the readiness
# check there only requires "any cache row >= event_date + 20bd",
# not 20 distinct rows, so holiday slippage doesn't break it.
#
# This pad does NOT weaken the readiness check itself — it only
# shapes the fetch window so yfinance returns enough trading days
# to satisfy the unchanged 60-distinct-date threshold.
_PRE_EVENT_BDAYS:    int = 75
_FORWARD_BDAYS_MAX:  int = 20
_AUTO_ADJUST_DEFAULT: int = 1

_REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_date",
    "proposed_primary_ticker",
)


# ---------------------------------------------------------------------------
# Patchable seams — module-level so tests can patch them.  The lazy
# imports resolve only on the un-patched path so dry-run never pulls
# the upstream report or provider modules.
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


def _check_provider_available() -> bool:
    """True iff ``yfinance`` is importable.  Does NOT make a network
    call.  Tests patch this seam to control the provider-unavailable
    branch deterministically.
    """
    try:
        import yfinance  # noqa: F401
    except Exception:
        return False
    return True


def _fetch_ticker_rows(
    *, ticker: str, start: str, end: str,
) -> list[dict[str, Any]]:
    """Fetch daily bars for ``ticker`` over ``[start, end]`` (inclusive).

    Returns rows shaped as ``{"date": ISO, "close": float, "volume":
    float}``.  In production, this would call
    ``yfinance.download(ticker, start=start, end=end)``.  Tests MUST
    patch this seam — the smoke has no environment that would tolerate
    a real network call.
    """
    import yfinance as yf  # local import — only fires on the un-patched path

    end_d = _dt.date.fromisoformat(end) + _dt.timedelta(days=1)
    df = yf.download(
        ticker, start=start, end=end_d.isoformat(), progress=False,
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


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def smoke_price_backfill(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
    csv_path: str | None = None,
    write: bool = False,
    confirm: bool = False,
) -> dict[str, Any]:
    """Run the price-backfill smoke and return the brief-mandated
    15-key payload.  See module docstring for the full order of
    operations.
    """
    errors: list[str] = []
    warnings: list[str] = []
    mode = "write" if write else "dry-run"

    rows_read = 0
    tickers_planned = 0
    price_rows_planned = 0
    price_rows_written = 0
    before_clean: int | None = None
    after_clean:  int | None = None
    before_contam: int | None = None
    after_contam:  int | None = None

    live_hash_before   = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    parsed_rows, parse_errs, parse_warns = _parse_csv_if_present(csv_path)
    errors.extend(parse_errs)
    warnings.extend(parse_warns)
    rows_read = len(parsed_rows)
    plan = _plan_per_ticker_windows(parsed_rows, warnings)
    tickers_planned    = len(plan)
    price_rows_planned = sum(p["bdays"] for p in plan.values())

    if write:
        (
            price_rows_written,
            before_clean, after_clean,
            before_contam, after_contam,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path, csv_path=csv_path,
            confirm=confirm, plan=plan, errors=errors, warnings=warnings,
        )

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
            f"LIVE DB BYTES CHANGED during backfill smoke — investigate: "
            f"{db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during backfill smoke — investigate: "
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
        "tickers_planned":                 tickers_planned,
        "price_rows_planned":              price_rows_planned,
        "price_rows_written":              price_rows_written,
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
    confirm: bool, plan: dict[str, dict[str, Any]],
    errors: list[str], warnings: list[str],
) -> tuple[int, int | None, int | None, int | None, int | None]:
    """Execute the write-mode order of operations.

    Returns ``(price_rows_written, before_clean, after_clean,
    before_contam, after_contam)``.  Any short-circuit returns 0/None
    and appends to ``errors``.
    """
    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return 0, None, None, None, None
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return 0, None, None, None, None
    if not csv_path:
        errors.append("--write requires --csv-path; refusing to write")
        return 0, None, None, None, None

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
            return 0, None, None, None, None

    # Step 3: backup + csv must exist.
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return 0, None, None, None, None
    if not Path(csv_path).exists():
        errors.append(f"--csv-path does not exist: {csv_path}")
        return 0, None, None, None, None

    # Step 7: fail closed if no retag rows in the plan.
    if not plan:
        errors.append(
            "No retag rows in CSV (no proposed_primary_ticker filled) — "
            "refusing to write; nothing to backfill"
        )
        return 0, None, None, None, None

    # Step 8: provider availability.  Fail closed BEFORE copying so we
    # don't leak temp artifacts for runs that can't proceed.
    if not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — failing "
            "closed without writing"
        )
        return 0, None, None, None, None

    # Step 9: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return 0, None, None, None, None
    warnings.append(f"Temp copy at {temp_copy_path}")

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
        errors.append(f"Pre-write report failed: {e}")
        return 0, None, None, None, None

    # Steps 11-12: fetch + insert per ticker.
    total_written = 0
    for ticker, window in plan.items():
        try:
            rows = _fetch_ticker_rows(
                ticker=ticker, start=window["start"], end=window["end"],
            )
        except Exception as e:
            errors.append(
                f"Provider fetch failed for {ticker}: {e}"
            )
            return (
                total_written, before_clean, None, before_contam, None,
            )
        try:
            written = _insert_ticker_rows_into_temp(
                temp_copy_path, ticker, rows,
            )
        except sqlite3.Error as e:
            errors.append(
                f"Temp DB insert failed for {ticker}: {e}"
            )
            return (
                total_written, before_clean, None, before_contam, None,
            )
        total_written += written

    # Steps 13-14: after counts + readiness sanity check.
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
        errors.append(f"Post-write report failed: {e}")
        return (
            total_written, before_clean, None, before_contam, None,
        )

    try:
        _run_readiness_report(db_path=temp_copy_path)
    except Exception as e:
        errors.append(f"Post-write readiness probe failed: {e}")

    return (
        total_written, before_clean, after_clean,
        before_contam, after_contam,
    )


# ---------------------------------------------------------------------------
# CSV parsing + per-ticker plan
# ---------------------------------------------------------------------------


def _parse_csv_if_present(
    csv_path: str | None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not csv_path:
        return [], errors, warnings
    if not Path(csv_path).exists():
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


def _plan_per_ticker_windows(
    rows: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, dict[str, Any]]:
    """Group retag rows by ticker → merged window dict.

    Returns ``{TICKER: {"start": ISO, "end": ISO, "bdays": int}}``.
    Excludes rows without a proposed ticker, an unparseable event_id,
    or a missing/malformed event_date.
    """
    by_ticker: dict[str, list[_dt.date]] = {}
    for raw in rows:
        proposed = (raw.get("proposed_primary_ticker") or "").strip()
        if not proposed:
            continue
        ev_id_raw = (raw.get("event_id") or "").strip()
        try:
            int(ev_id_raw)
        except (TypeError, ValueError):
            warnings.append(
                f"Skipping row with unparseable event_id: {ev_id_raw!r}"
            )
            continue
        event_date_raw = (raw.get("event_date") or "").strip()
        ev_d = _parse_iso_date(event_date_raw)
        if ev_d is None:
            warnings.append(
                f"Skipping row event_id={ev_id_raw} with unparseable "
                f"event_date: {event_date_raw!r}"
            )
            continue
        ticker = proposed.upper()
        by_ticker.setdefault(ticker, []).append(ev_d)

    plan: dict[str, dict[str, Any]] = {}
    for ticker, dates in by_ticker.items():
        start = _business_day_offset(min(dates), -_PRE_EVENT_BDAYS)
        end   = _business_day_offset(max(dates),  _FORWARD_BDAYS_MAX)
        plan[ticker] = {
            "start": start.isoformat(),
            "end":   end.isoformat(),
            "bdays": _business_days_inclusive(start, end),
        }
    return plan


# ---------------------------------------------------------------------------
# Apply step — temp DB only
# ---------------------------------------------------------------------------


def _insert_ticker_rows_into_temp(
    temp_db_path: str, ticker: str, rows: Iterable[dict[str, Any]],
) -> int:
    """INSERT OR IGNORE the fetched rows into the temp DB's
    price_cache table.  Returns the number of rows actually inserted.

    ``INSERT OR IGNORE`` rather than ``OR REPLACE`` so existing cache
    rows for the (ticker, date, auto_adjust) key are left alone.
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
                (ticker.upper(), d, close, volume,
                 _AUTO_ADJUST_DEFAULT, fetched_at),
            )
            inserted += int(cur.rowcount or 0)
        conn.commit()
    finally:
        conn.close()
    return inserted


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(value: Any) -> _dt.date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _dt.date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _business_day_offset(start: _dt.date, n: int) -> _dt.date:
    """Shift ``start`` by ``n`` business days.  Negative ``n`` shifts
    backward.  Matches
    ``stat_validation_readiness_report._business_day_offset`` for
    forward shifts; mirrors the same Mon–Fri calendar for backward
    shifts so pre-event windows align with the readiness check.
    """
    if n == 0:
        return start
    out = start
    step = _dt.timedelta(days=1 if n > 0 else -1)
    remaining = abs(n)
    while remaining > 0:
        out = out + step
        if out.weekday() < 5:
            remaining -= 1
    return out


def _business_days_inclusive(start: _dt.date, end: _dt.date) -> int:
    """Count Mon–Fri days in ``[start, end]`` inclusive.  Returns 0
    if ``end < start``.
    """
    if end < start:
        return 0
    n = 0
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            n += 1
        cur = cur + _dt.timedelta(days=1)
    return n


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
    dst_name = f"price_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
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
    lines: list[str] = ["Manual ticker price-backfill smoke", ""]
    lines.append(f"Mode:                              {report['mode']}")
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Tickers planned:                   {report['tickers_planned']}")
    lines.append(f"Price rows planned:                {report['price_rows_planned']}")
    lines.append(f"Price rows written:                {report['price_rows_written']}")
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
            "Temp-copy price-cache backfill smoke for manually "
            "retagged tickers.  Default is a read-only dry-run that "
            "computes per-ticker fetch windows from the CSV.  Write "
            "mode requires --write --confirm --backup-path --csv-path "
            "together; the smoke copies the backup to a temp file, "
            "fetches daily bars for each operator-proposed ticker, "
            "and writes them into the temp copy ONLY.  Live "
            "events.db is never opened for writes."
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
            "Path to a backup of the events DB.  Required for "
            "--write.  Must differ from --db-path."
        ),
    )
    parser.add_argument(
        "--csv-path", dest="csv_path", default=None,
        help=(
            "Path to the completed manual_ticker_repair_packet CSV."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Path to the LIVE events DB.  Hashed read-only before "
            "and after the smoke; never opened for writes."
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

    report = smoke_price_backfill(
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
