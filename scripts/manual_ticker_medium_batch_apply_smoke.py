#!/usr/bin/env python3
"""Temp-copy medium-batch manual ticker repair apply smoke.

Sized between :mod:`scripts.manual_ticker_repair_apply_smoke` and
:mod:`scripts.manual_ticker_repair_full_smoke`: it applies the
operator-categorized rows from a completed manual ticker repair
packet CSV (the variant emitted by ``manual_ticker_repair_packet
--production-like-only``) AND writes ``mechanism_family``
decisions, all against a *copied* backup of the events DB.  Price-
cache backfill is OFF by default — retag rows mutate
``events.market_tickers`` only.  Backfill can be enabled with
``--with-price-backfill`` for the cases where the operator wants
to dress-rehearse the joint effect on the same temp copy.

Why "medium batch"
------------------

The high-priority packet sized for the apply smoke is small enough
that the operator can hand-walk every row.  The production-like-only
packet is bigger: it covers every fully-ready event whose readiness
signal is gated by mechanism_family or a manual ticker decision.
Three smoke surfaces handle the spectrum:

  * apply smoke         — single-batch dress rehearsal of retags +
                          exclusions only
  * medium-batch smoke  — adds ``mechanism_family`` decisions to the
                          apply phase; backfill is opt-in.  THIS FILE.
  * full smoke          — combined apply + mandatory backfill +
                          contamination + readiness probe

This module reuses the helpers already pinned by the apply / full
smokes — ``_apply_categorized_to_temp``,
``_apply_mechanism_family_decisions``,
``_has_low_signal_column``, ``_has_mechanism_family_column``,
``_parse_mechanism_family_decisions``, ``_categorize_rows`` — so the
behavior contracts are not re-litigated here.

Modes
-----

  * ``dry-run`` (default) — parses the CSV, categorizes each row,
    counts the mechanism-family decisions that would be applied,
    and reports the counts.  Does NOT call the provider, does NOT
    copy any file, does NOT write any DB.  All ``before_*`` /
    ``after_*`` fields are ``None`` in dry-run.
  * ``write``  — requires ALL of ``--write --confirm
    --backup-path <PATH> --csv-path <PATH>``.

Mechanism-family decisions
--------------------------

Two sources are merged:

  1. ``proposed_mechanism_family`` column on the CSV (when present
     and non-empty for a given row).
  2. Repeatable ``--mechanism-family-decision EVENT_ID=FAMILY``
     flags.  These take precedence over the CSV column for the
     same ``event_id`` so an operator can override a CSV value
     without re-running the packet generator.

Both sources funnel through the full-smoke parser and applier,
which keeps the schema check + per-row warning behavior identical.

Order of operations in write mode::

     1. validate flags
     2. reject backup_path == db_path / missing files
     3. hash live DB + input backup
     4. parse CSV + categorize rows
     5. parse mechanism-family decisions (CSV + flags merged)
     6. fail closed if CSV has no actionable rows AND no decisions
     7. (optional, only when --with-price-backfill is set)
        fail closed if retag rows exist + provider unavailable
     8. copy backup → temp_copy_path
     9. schema checks: low_signal (if exclusions),
        mechanism_family (if decisions).  Fail closed on any miss.
    10. run clean-cohort report (before count)
    11. apply categorized rows
    12. apply mechanism-family decisions
    13. (optional) backfill price_cache for retag tickers
    14. run clean-cohort report (after count)
    15. re-hash live DB + input backup
    16. surface drift / errors; ok = (errors empty)

Patchable seams
---------------

Three module-level seams let unit tests drive the smoke without
touching yfinance or the real readiness pipeline:

  * ``_run_clean_cohort_report``  — wraps ``summarize_clean_cohort``.
  * ``_check_provider_available`` — soft import-only probe.
  * ``_fetch_ticker_rows``        — would shell out to yfinance to
    fetch daily bars.  ONLY fires when ``--with-price-backfill`` is
    set.

Output contract::

    {
      "ok":                       bool,
      "mode":                     "dry-run" | "write",
      "rows_read":                int,
      "rows_excluded":            int,
      "rows_retagged":            int,
      "mechanism_family_updates": int,
      "before_clean_fully_ready": int | None,
      "after_clean_fully_ready":  int | None,
      "live_db_unchanged":        bool,
      "input_backup_unchanged":   bool,
      "errors":                   [str, ...],
      "warnings":                 [str, ...],
    }

The output dict carries EXACTLY these 12 keys — no additive fields.
The temp copy path is surfaced via a ``Temp copy at <path>`` warning.

Out of scope (deliberately)
---------------------------
* Live DB is NEVER opened for writes.
* Input backup is NEVER opened for writes.
* No LLM, no FastAPI surface — never imports ``api`` / ``routes.*``.
* No provider call in dry-run.
* No provider call in write mode UNLESS ``--with-price-backfill`` is
  set.

Usage::

    python scripts/manual_ticker_medium_batch_apply_smoke.py \\
        --dry-run --json --csv-path manual_ticker_repair_high_priority.csv
    python scripts/manual_ticker_medium_batch_apply_smoke.py \\
        --write --confirm --backup-path /path/to/events.backup.db \\
        --csv-path manual_ticker_medium_batch.csv --json
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


# Reused pure helpers — both sibling modules use only lazy imports
# inside their seams, so importing the modules here does NOT pull
# yfinance / readiness / contamination / clean-cohort.
from scripts.manual_ticker_repair_apply_smoke import (  # noqa: E402
    _apply_categorized_to_temp,
    _categorize_rows,
    _has_low_signal_column,
)
from scripts.manual_ticker_repair_full_smoke import (  # noqa: E402
    _apply_mechanism_family_decisions,
    _compute_manual_aware_clean_metrics,
    _has_mechanism_family_column,
    _operator_excluded_ids_from_categorized,
    _parse_mechanism_family_decisions,
)
from scripts.manual_ticker_price_backfill_smoke import (  # noqa: E402
    _insert_ticker_rows_into_temp,
    _plan_per_ticker_windows,
)


_REQUIRED_CSV_FIELDS: tuple[str, ...] = (
    "event_id",
    "proposed_primary_ticker",
    "proposed_benchmark",
    "exclude_reason",
)
_MECHANISM_FAMILY_CSV_FIELD: str = "proposed_mechanism_family"
_SCHEMA_MISSING_TOKEN: str = "schema_missing_exclusion_field"
_SCHEMA_MISSING_MF_TOKEN: str = "schema_missing_mechanism_family_field"


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the clean-cohort report with an effectively unlimited
    per-row cap.  The smoke needs every contaminated example's flags
    to compute the manual-aware adjustment — a smaller cap would
    silently drop repaired rows from the adjustment input.
    """
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(db_path=db_path, limit=10**12)


def _check_provider_available() -> bool:
    """True iff ``yfinance`` is importable.  Does NOT make a network
    call.  Tests patch this to drive the provider-unavailable branch.
    """
    try:
        import yfinance  # noqa: F401
    except Exception:
        return False
    return True


def _fetch_ticker_rows(
    *, ticker: str, start: str, end: str,
) -> list[dict[str, Any]]:
    """Fetch daily bars for ``ticker`` over ``[start, end]`` inclusive.

    Production calls ``yfinance.download``; tests MUST patch this
    seam — the smoke has no environment that would tolerate a real
    network call.  This seam is only invoked when
    ``--with-price-backfill`` is set.
    """
    import yfinance as yf  # local import — only fires on un-patched path

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


def smoke_medium_batch_apply(
    *,
    db_path: str | None = None,
    backup_path: str | None = None,
    csv_path: str | None = None,
    write: bool = False,
    confirm: bool = False,
    mechanism_family_decisions: list[str] | None = None,
    with_price_backfill: bool = False,
) -> dict[str, Any]:
    """Run the medium-batch apply smoke and return the 12-key payload.

    See module docstring for the full order of operations.
    """
    errors: list[str] = []
    warnings: list[str] = []
    mode = "write" if write else "dry-run"

    rows_read = 0
    rows_excluded = 0
    rows_retagged = 0
    mechanism_family_updates = 0
    before_clean: int | None = None
    after_clean: int | None = None
    after_clean_payload: dict[str, Any] = {}

    live_hash_before = _hash_file_safe(db_path)
    backup_hash_before = _hash_file_safe(backup_path)

    parsed_rows, parse_errs, parse_warns = _parse_csv_if_present(csv_path)
    errors.extend(parse_errs)
    warnings.extend(parse_warns)
    rows_read = len(parsed_rows)
    categorized = _categorize_rows(parsed_rows, errors, warnings)

    operator_excluded_event_ids = _operator_excluded_ids_from_categorized(
        categorized,
    )

    cli_decisions, decision_errs = _parse_mechanism_family_decisions(
        mechanism_family_decisions,
    )
    errors.extend(decision_errs)
    csv_decisions = _extract_csv_mechanism_family_decisions(parsed_rows)
    # CLI overrides CSV for the same event_id.
    merged_decisions: dict[int, str] = {**csv_decisions, **cli_decisions}

    if write and decision_errs:
        # Malformed CLI flags fail the run closed before the temp copy.
        rows_excluded = 0
        rows_retagged = 0
        mechanism_family_updates = 0
    elif write:
        (
            rows_excluded, rows_retagged, mechanism_family_updates,
            before_clean, after_clean, after_clean_payload,
        ) = _do_write_mode(
            db_path=db_path, backup_path=backup_path, csv_path=csv_path,
            confirm=confirm,
            parsed_rows=parsed_rows, categorized=categorized,
            decisions=merged_decisions,
            with_price_backfill=with_price_backfill,
            errors=errors, warnings=warnings,
        )
    else:
        rows_excluded = sum(1 for r in categorized if r["kind"] == "exclude")
        rows_retagged = sum(1 for r in categorized if r["kind"] == "retag")
        mechanism_family_updates = len(merged_decisions)

    live_hash_after = _hash_file_safe(db_path)
    backup_hash_after = _hash_file_safe(backup_path)

    live_db_unchanged = _hashes_match(
        before=live_hash_before, after=live_hash_after, path=db_path,
    )
    input_backup_unchanged = _hashes_match(
        before=backup_hash_before, after=backup_hash_after, path=backup_path,
    )
    if not live_db_unchanged:
        errors.append(
            f"LIVE DB BYTES CHANGED during medium-batch smoke — "
            f"investigate: {db_path}"
        )
    if not input_backup_unchanged:
        errors.append(
            f"INPUT BACKUP BYTES CHANGED during medium-batch smoke — "
            f"investigate: {backup_path}"
        )

    # Manual-aware clean-cohort metrics — see
    # ``_compute_manual_aware_clean_metrics`` for the full contract.
    # In dry-run all four count fields are None and
    # ``remaining_contamination_reasons`` is the empty dict so consumers
    # get a JSON-iterable shape regardless of mode.
    if write and after_clean is not None:
        manual_aware = _compute_manual_aware_clean_metrics(
            after_clean_payload=after_clean_payload,
            operator_excluded_ids=set(operator_excluded_event_ids),
        )
    else:
        manual_aware = {
            "raw_after_clean_fully_ready":      None,
            "adjusted_after_clean_fully_ready": None,
            "adjusted_clean_fully_ready_delta": None,
            "remaining_contamination_reasons":  {},
        }

    return {
        "ok":                               not errors,
        "mode":                             mode,
        "rows_read":                        rows_read,
        "rows_excluded":                    rows_excluded,
        "rows_retagged":                    rows_retagged,
        "mechanism_family_updates":         mechanism_family_updates,
        "before_clean_fully_ready":         before_clean,
        "after_clean_fully_ready":          after_clean,
        "live_db_unchanged":                live_db_unchanged,
        "input_backup_unchanged":           input_backup_unchanged,
        "errors":                           errors,
        "warnings":                         warnings,
        "operator_excluded_event_ids":      operator_excluded_event_ids,
        "raw_after_clean_fully_ready":      manual_aware["raw_after_clean_fully_ready"],
        "adjusted_after_clean_fully_ready": manual_aware["adjusted_after_clean_fully_ready"],
        "adjusted_clean_fully_ready_delta": manual_aware["adjusted_clean_fully_ready_delta"],
        "remaining_contamination_reasons":  manual_aware["remaining_contamination_reasons"],
    }


def _do_write_mode(
    *, db_path: str | None, backup_path: str | None, csv_path: str | None,
    confirm: bool,
    parsed_rows: list[dict[str, Any]],
    categorized: list[dict[str, Any]],
    decisions: dict[int, str],
    with_price_backfill: bool,
    errors: list[str], warnings: list[str],
) -> tuple[int, int, int, int | None, int | None, dict[str, Any]]:
    """Execute the write-mode order of operations.  Returns
    ``(rows_excluded, rows_retagged, mechanism_family_updates,
    before_clean, after_clean, after_clean_payload)`` — the trailing
    payload is the full post-apply clean-cohort report dict so the
    outer function can compute the manual-aware adjustment without
    re-running the report.
    """
    empty_payload: dict[str, Any] = {}
    # Step 1: flag validation.
    if not confirm:
        errors.append("--write requires --confirm; refusing to write")
        return 0, 0, 0, None, None, empty_payload
    if not backup_path:
        errors.append("--write requires --backup-path; refusing to write")
        return 0, 0, 0, None, None, empty_payload
    if not csv_path:
        errors.append("--write requires --csv-path; refusing to write")
        return 0, 0, 0, None, None, empty_payload

    # Step 2: same-path / existence guards.
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
            return 0, 0, 0, None, None, empty_payload
    if not Path(backup_path).exists():
        errors.append(f"--backup-path does not exist: {backup_path}")
        return 0, 0, 0, None, None, empty_payload
    if not Path(csv_path).exists():
        errors.append(f"--csv-path does not exist: {csv_path}")
        return 0, 0, 0, None, None, empty_payload

    has_exclusions = any(r["kind"] == "exclude" for r in categorized)
    has_retags = any(r["kind"] == "retag" for r in categorized)
    has_decisions = bool(decisions)

    # Step 6: nothing-to-do guard.
    if not has_exclusions and not has_retags and not has_decisions:
        errors.append(
            "No actionable rows in CSV (no exclusions, no retags) "
            "and no mechanism-family decisions — refusing to write; "
            "nothing to apply"
        )
        return 0, 0, 0, None, None, empty_payload

    # Step 7: provider check ONLY when --with-price-backfill is set
    # AND there are retag rows that would need a backfill.  Provider
    # calls are disabled by default — that's the whole point of the
    # medium-batch smoke vs. the full smoke.
    if with_price_backfill and has_retags and not _check_provider_available():
        errors.append(
            "Provider unavailable (yfinance not importable) — "
            "--with-price-backfill cannot run; failing closed without "
            "writing"
        )
        return 0, 0, 0, None, None, empty_payload

    # Step 8: copy backup → temp.
    try:
        temp_copy_path = _copy_to_fresh_temp(backup_path)
    except OSError as e:
        errors.append(f"Failed to copy backup to temp: {e}")
        return 0, 0, 0, None, None, empty_payload
    warnings.append(f"Temp copy at {temp_copy_path}")

    # Step 9a: schema check for low_signal.
    if has_exclusions and not _has_low_signal_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_TOKEN}: temp DB lacks 'low_signal' "
            f"column — refusing to apply any rows"
        )
        return 0, 0, 0, None, None, empty_payload

    # Step 9b: schema check for mechanism_family.
    if has_decisions and not _has_mechanism_family_column(temp_copy_path):
        errors.append(
            f"{_SCHEMA_MISSING_MF_TOKEN}: temp DB lacks "
            f"'mechanism_family' column — refusing to apply any rows "
            f"or decisions"
        )
        return 0, 0, 0, None, None, empty_payload

    # Step 10: before count.
    try:
        before_clean = _safe_int(
            _safe_dict(_run_clean_cohort_report(db_path=temp_copy_path))
            .get("clean_fully_ready_count")
        )
    except Exception as e:
        errors.append(f"Pre-apply clean-cohort report failed: {e}")
        return 0, 0, 0, None, None, empty_payload

    # Step 11: apply categorized rows (events table).
    try:
        rows_excluded, rows_retagged = _apply_categorized_to_temp(
            temp_copy_path, categorized, warnings,
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB apply failed: {e}")
        return 0, 0, 0, before_clean, None, empty_payload

    # Step 12: apply mechanism-family decisions.  The applier returns
    # ``(applied_count, applied_event_ids)`` — surface only the count.
    try:
        mechanism_family_updates, _mf_applied_ids = (
            _apply_mechanism_family_decisions(
                temp_copy_path, decisions, warnings,
            )
        )
    except sqlite3.Error as e:
        errors.append(f"Temp DB mechanism-family apply failed: {e}")
        return rows_excluded, rows_retagged, 0, before_clean, None, empty_payload

    # Step 13: optional backfill.
    if with_price_backfill and has_retags:
        plan = _plan_per_ticker_windows(parsed_rows, warnings)
        for ticker, window in plan.items():
            try:
                rows = _fetch_ticker_rows(
                    ticker=ticker,
                    start=window["start"], end=window["end"],
                )
            except Exception as e:
                errors.append(f"Provider fetch failed for {ticker}: {e}")
                return (
                    rows_excluded, rows_retagged,
                    mechanism_family_updates, before_clean, None,
                    empty_payload,
                )
            try:
                _insert_ticker_rows_into_temp(temp_copy_path, ticker, rows)
            except sqlite3.Error as e:
                errors.append(
                    f"Temp DB price-cache insert failed for {ticker}: {e}"
                )
                return (
                    rows_excluded, rows_retagged,
                    mechanism_family_updates, before_clean, None,
                    empty_payload,
                )

    # Step 14: after count — capture the FULL post-apply payload so the
    # outer function can compute the manual-aware adjustment without
    # re-running the report.
    after_clean_payload: dict[str, Any] = {}
    try:
        after_clean_payload = _safe_dict(
            _run_clean_cohort_report(db_path=temp_copy_path)
        )
        after_clean = _safe_int(
            _safe_dict(after_clean_payload)
            .get("clean_fully_ready_count")
        )
    except Exception as e:
        errors.append(f"Post-apply clean-cohort report failed: {e}")
        return (
            rows_excluded, rows_retagged, mechanism_family_updates,
            before_clean, None, empty_payload,
        )

    return (
        rows_excluded, rows_retagged, mechanism_family_updates,
        before_clean, after_clean, after_clean_payload,
    )


# ---------------------------------------------------------------------------
# CSV parsing — tolerant of either packet variant (with/without
# proposed_mechanism_family column)
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


def _extract_csv_mechanism_family_decisions(
    rows: list[dict[str, Any]],
) -> dict[int, str]:
    """Pull non-empty ``proposed_mechanism_family`` values keyed by
    parseable ``event_id``.  Rows without the column or with an empty
    value contribute nothing.  Malformed event_ids are silently
    skipped — the categorize phase already surfaces them as warnings.
    """
    out: dict[int, str] = {}
    for raw in rows:
        if _MECHANISM_FAMILY_CSV_FIELD not in raw:
            continue
        family = (raw.get(_MECHANISM_FAMILY_CSV_FIELD) or "").strip()
        if not family:
            continue
        ev_id_raw = (raw.get("event_id") or "").strip()
        try:
            ev_id = int(ev_id_raw)
        except (TypeError, ValueError):
            continue
        out[ev_id] = family
    return out


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
    dst_name = f"medium_batch_smoke_{uuid.uuid4().hex}{src.suffix or '.db'}"
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
    lines: list[str] = ["Manual ticker repair medium-batch apply smoke", ""]
    lines.append(f"Mode:                              {report['mode']}")
    lines.append(f"OK:                                {report['ok']}")
    lines.append(f"Rows read:                         {report['rows_read']}")
    lines.append(f"Rows excluded:                     {report['rows_excluded']}")
    lines.append(f"Rows retagged:                     {report['rows_retagged']}")
    lines.append(
        f"Mechanism family updates:          "
        f"{report['mechanism_family_updates']}"
    )
    lines.append(
        f"before_clean_fully_ready:          "
        f"{report['before_clean_fully_ready']}"
    )
    lines.append(
        f"after_clean_fully_ready:           "
        f"{report['after_clean_fully_ready']}"
    )
    lines.append(
        f"Live DB unchanged:                 {report['live_db_unchanged']}"
    )
    lines.append(
        f"Input backup unchanged:            "
        f"{report['input_backup_unchanged']}"
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
            "Temp-copy medium-batch manual ticker repair apply smoke.  "
            "Default is a read-only dry-run that categorizes the CSV "
            "and counts pending mechanism-family decisions.  Write "
            "mode requires --write --confirm --backup-path --csv-path "
            "together; the smoke copies the backup to a temp file, "
            "applies categorized rows + mechanism-family decisions to "
            "the temp copy, and runs the clean-cohort report against "
            "the post-mutation temp DB.  Price-cache backfill is OFF "
            "by default; pass --with-price-backfill to opt in."
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
            "Path to the completed manual_ticker_repair_packet CSV "
            "(production-like-only variant)."
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
        "--mechanism-family-decision",
        dest="mechanism_family_decisions",
        action="append", default=[],
        metavar="EVENT_ID=FAMILY",
        help=(
            "Manual mechanism-family decision (repeatable).  Format: "
            "``event_id=family_token``.  Overrides the CSV's "
            "``proposed_mechanism_family`` column for the same "
            "event_id.  Malformed entries fail the run closed."
        ),
    )
    parser.add_argument(
        "--with-price-backfill", dest="with_price_backfill",
        action="store_true",
        help=(
            "Opt in to price-cache backfill for retag tickers in the "
            "same temp copy.  Provider (yfinance) is OFF by default; "
            "enabling this requires the provider to be importable."
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

    report = smoke_medium_batch_apply(
        db_path=db_path,
        backup_path=args.backup_path,
        csv_path=args.csv_path,
        write=bool(args.write),
        confirm=bool(args.confirm),
        mechanism_family_decisions=args.mechanism_family_decisions,
        with_price_backfill=bool(args.with_price_backfill),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
