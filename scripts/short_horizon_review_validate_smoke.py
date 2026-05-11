#!/usr/bin/env python3
"""Reviewed short-horizon validation smoke.

Reads a manually reviewed short-horizon worksheet, extracts the rows
the operator accepted, and runs the read-only 1d/5d archive
validation pipeline against a TEMP copy of the events DB so the
operator can see the short-horizon evidence carried by the existing
price_cache for the accepted candidates.  The script never mutates
the live DB and never fetches new price data — by construction.

Read-only by construction
-------------------------
* The validation pipeline runs against a temp copy via the single
  patchable seam ``_run_short_horizon_validation_on_temp_db``.  Tests
  patch the seam with synthetic payloads; on the un-patched path the
  seam copies the live DB → temp file before calling the read-only
  archive runner.
* No DB writes against the live DB.
* No ``yfinance`` / market_data provider; the smoke uses only the
  price_cache rows that already exist in the temp copy.
* No LLM, no FastAPI surface — never imports ``api`` / ``routes.*``.

Worksheet schema
----------------
The worksheet is a CSV.  ``event_id`` is the only required column.
The canonical operator gate column is
``include_in_short_horizon_validation`` — read when present and the
sole signal for classification (the previous heuristic that inferred
acceptance from ``proposed_*`` columns is gone).  ``exclude_reason``
and ``headline`` are read when present; missing columns are treated
as blank.  A row is classified as:

  * ``accepted``  — ``include_in_short_horizon_validation`` is
    ``yes`` (case- and whitespace-insensitive).  These event_ids
    drive the validation cohort.
  * ``excluded``  — ``include_in_short_horizon_validation`` is
    ``no``.  Surfaced in ``excluded_candidates`` with the operator's
    ``exclude_reason`` verbatim.
  * ``pending``   — gate is blank (legitimately mid-review) or
    carries an unrecognised value.  Surfaced via a single aggregated
    warning; never counted in ``accepted_count`` /
    ``excluded_candidates``.

Filter-only design
------------------
This is a "filter-only" smoke: the worksheet does NOT drive any
mutation of the temp DB.  Accepted ``proposed_primary_ticker`` /
``proposed_mechanism_family`` values are not applied — they only
identify which event_ids the operator approved.  The validation
pipeline runs against the unmodified temp copy of the live DB and
the smoke filters records to the accepted event_id set + the 1d/5d
horizons.  This keeps the smoke aligned with the
"existing price_cache only" constraint: retags whose target ticker
is not already cached would fail the readiness gate anyway.

Output contract::

    {
      "ok":                   bool,
      "worksheet_path":       str | None,
      "accepted_count":       int,
      "events_evaluated":     int,
      "records_count":        int,
      "significant_count":    int,
      "by_horizon": {
        "1": {"records_count": int, "significant_count": int},
        "5": {"records_count": int, "significant_count": int},
      },
      "by_mechanism_family": {
        family: {
          "events_evaluated":  int,
          "records_count":     int,
          "significant_count": int,
        },
        ...
      },
      "examples":             [{...}, ...],   # capped at --limit
      "excluded_candidates": [
        {"event_id": int, "reason": str, "headline": str | None},
        ...
      ],
      "errors":               [str, ...],
      "warnings":              [str, ...],
    }

Each example carries::

    event_id, headline, primary_ticker, benchmark, mechanism_family,
    horizon, abnormal_return, sar, ci_low, ci_high, p_value, fdr_q,
    interpretation

CLI exit code is always 0 — failure is surfaced via the envelope's
``ok`` field.  A missing worksheet emits a valid JSON envelope with
``ok=False`` and an explanatory error, so a verification pipeline
that calls the script with ``--json`` never breaks on the exit code.

Output file is only written when ``--output`` is passed; default
invocation has no filesystem side effect.  When ``--output`` IS
passed, the file is written on every code path — including the
error envelope returned when the worksheet is missing or malformed
— so a verification pipeline can rely on the artifact existing.

``accepted_count`` is the number of UNIQUE accepted event_ids, not
the number of accepted rows; a worksheet with duplicate event_ids
collapses to one entry per id.

Conservative wording
--------------------
Records here are "reviewed short-horizon evidence" — candidates,
never proof, never validated archive, never alpha generated.  The
banned-token guard runs over the ``errors`` and ``warnings`` text
streams only; record payloads carry upstream pipeline language.

Usage::

    python scripts/short_horizon_review_validate_smoke.py \\
        --worksheet artifacts/short_horizon_review_top10.csv --json

    python scripts/short_horizon_review_validate_smoke.py \\
        --worksheet artifacts/short_horizon_review_top10.csv \\
        --output artifacts/short_horizon_review_evidence.json --json
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_SHORT_HORIZONS: tuple[int, ...] = (1, 5)
_BENCHMARK_TICKER: str = "SPY"
_DEFAULT_LIMIT: int = 25


# Canonical operator gate column — shared with the validator and
# apply smoke so the validator / apply / validate triple read the
# same column.
_GATE_COLUMN: str = "include_in_short_horizon_validation"
_GATE_YES:    str = "yes"
_GATE_NO:     str = "no"


# ---------------------------------------------------------------------------
# Patchable seam — tests patch this directly.  Lazy imports keep the
# un-patched path's import cost off the smoke's surface.
# ---------------------------------------------------------------------------


def _run_short_horizon_validation_on_temp_db(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Run the read-only short-horizon (1d/5d) archive validation
    pipeline against a TEMP copy of the live DB.

    Production: copies ``db_path`` → a fresh temp file and invokes
    :func:`scripts.archive_stat_validation_short_horizon_run.run_archive_short_horizon_stat_validation`
    against the copy with an effectively unlimited per-record cap, then
    enriches each example with ``mechanism_family`` from the temp DB
    and re-derives ``statistically_significant`` from ``fdr_q``.

    Tests MUST patch this seam directly with a synthetic payload.  The
    seam exists so the smoke surface stays free of yfinance / FastAPI
    imports on the patched path.
    """
    from scripts.archive_stat_validation_short_horizon_run import (
        run_archive_short_horizon_stat_validation,
    )
    from scripts.manual_repaired_cohort_validation_run import (
        _mechanism_family_by_event_id,
    )
    from scripts.manual_ticker_repair_full_smoke import _copy_to_fresh_temp
    from stats.stat_validation import (
        DEFAULT_ALPHA, is_statistically_significant,
    )

    if not db_path or not Path(db_path).exists():
        return {
            "ok":      False,
            "records": [],
            "errors":  [
                f"db_path not found for short-horizon validation: {db_path}",
            ],
        }

    try:
        temp_path = _copy_to_fresh_temp(db_path)
    except OSError as exc:
        return {
            "ok":      False,
            "records": [],
            "errors":  [f"failed to copy live DB to temp: {exc}"],
        }

    try:
        payload = run_archive_short_horizon_stat_validation(
            db_path=temp_path, limit=10**9,
        )
    except sqlite3.Error as exc:
        return {
            "ok":      False,
            "records": [],
            "errors":  [
                f"archive short-horizon validation failed: {exc}",
            ],
        }

    examples = payload.get("examples") or []
    family_by_id = _mechanism_family_by_event_id(temp_path)

    records: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        ev_id = ex.get("event_id")
        records.append({
            "event_id":         ev_id,
            "headline":         ex.get("headline"),
            "ticker":           ex.get("primary_ticker") or ex.get("ticker"),
            "horizon":          ex.get("horizon"),
            "abnormal_return":  ex.get("abnormal_return"),
            "sar":              ex.get("sar"),
            "ci_low":           ex.get("ci_low"),
            "ci_high":          ex.get("ci_high"),
            "p_value":          ex.get("p_value"),
            "fdr_q":            ex.get("fdr_q"),
            "interpretation":   ex.get("interpretation"),
            "mechanism_family": (
                family_by_id.get(ev_id) if isinstance(ev_id, int) else None
            ),
            "statistically_significant": is_statistically_significant(
                ex.get("fdr_q"), alpha=DEFAULT_ALPHA,
            ),
        })

    enriched = dict(payload)
    enriched["records"] = records
    return enriched


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def run_short_horizon_review_validate(
    *,
    worksheet_path: str | None = None,
    db_path:        str | None = None,
    output_path:    str | None = None,
    limit:          int        = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the reviewed short-horizon validation smoke.  See module
    docstring for the full output contract.
    """
    envelope = _compute_envelope(
        worksheet_path=worksheet_path, db_path=db_path, limit=limit,
    )

    # Step 5: optional output-file persistence.  Runs on EVERY code
    # path when output_path is set so a verification pipeline can
    # depend on the artifact existing even on failure envelopes.
    if output_path:
        try:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(
                    envelope, fh, indent=2, sort_keys=True, default=str,
                )
        except OSError as exc:
            envelope["errors"].append(
                f"failed to write --output {output_path}: {exc}"
            )
            envelope["ok"] = False

    return envelope


def _compute_envelope(
    *,
    worksheet_path: str | None,
    db_path:        str | None,
    limit:          int,
) -> dict[str, Any]:
    errors:   list[str] = []
    warnings: list[str] = []

    # Step 1: worksheet input gate.
    if not worksheet_path:
        errors.append(
            "--worksheet is required: pass a path to a manually "
            "reviewed short-horizon worksheet CSV",
        )
        return _envelope(
            worksheet_path=worksheet_path,
            errors=errors, warnings=warnings,
        )
    if not Path(worksheet_path).exists():
        errors.append(f"--worksheet does not exist: {worksheet_path}")
        return _envelope(
            worksheet_path=worksheet_path,
            errors=errors, warnings=warnings,
        )

    # Step 2: parse the worksheet.
    rows, parse_errors, parse_warnings = _parse_worksheet(worksheet_path)
    errors.extend(parse_errors)
    warnings.extend(parse_warnings)
    if parse_errors:
        return _envelope(
            worksheet_path=worksheet_path,
            errors=errors, warnings=warnings,
        )

    # Step 3: classify rows.
    classified = _classify_rows(rows)
    accepted_event_ids:    set[int] = classified["accepted_event_ids"]
    accepted_meta:         dict[int, dict[str, Any]] = classified["accepted_meta"]
    excluded_candidates: list[dict[str, Any]] = classified["excluded_candidates"]
    pending_event_ids:     list[int] = classified["pending_event_ids"]

    if pending_event_ids:
        warnings.append(
            f"{len(pending_event_ids)} worksheet row(s) had a blank or "
            f"unrecognised include_in_short_horizon_validation gate "
            f"value; skipped as pending"
        )

    accepted_count = len(accepted_event_ids)

    # Step 4: run validation seam — only when there is anything to
    # evaluate.  An empty accepted set short-circuits to zeros.
    records_count: int = 0
    events_evaluated: int = 0
    significant_count: int = 0
    by_horizon: dict[str, Any] = _empty_by_horizon()
    by_mechanism_family: dict[str, Any] = {}
    examples: list[dict[str, Any]] = []

    if accepted_event_ids:
        try:
            validation_payload = _safe_dict(
                _run_short_horizon_validation_on_temp_db(db_path=db_path),
            )
        except Exception as exc:  # noqa: BLE001 — operator-visible
            errors.append(
                f"validation seam raised: "
                f"{type(exc).__name__}: {exc}",
            )
            validation_payload = {}

        all_records = validation_payload.get("records") or []
        # Copy each accepted record so the worksheet-metadata overrides
        # don't mutate the patched payload in tests.
        accepted_records = [
            dict(r)
            for r in all_records
            if isinstance(r, dict)
            and isinstance(r.get("event_id"), int)
            and r["event_id"] in accepted_event_ids
            and r.get("horizon") in _SHORT_HORIZONS
        ]
        _apply_worksheet_metadata(accepted_records, accepted_meta)

        # Surface a clear warning for any accepted row whose
        # ``proposed_mechanism_family`` is blank.  Those records still
        # count toward ``records_count`` / ``by_horizon`` / examples
        # (existing horizon-filtered semantics are unchanged), but are
        # excluded from ``by_mechanism_family`` so the aggregation never
        # silently buckets them under ``None``.
        events_with_records = {
            r["event_id"] for r in accepted_records
            if isinstance(r.get("event_id"), int)
        }
        missing_family_ids = sorted(
            ev_id for ev_id in events_with_records
            if not (accepted_meta.get(ev_id) or {}).get(
                "proposed_mechanism_family"
            )
        )
        if missing_family_ids:
            warnings.append(
                f"{len(missing_family_ids)} accepted row(s) have a blank "
                f"proposed_mechanism_family and are not included in the "
                f"by_mechanism_family aggregation: event_ids="
                f"{missing_family_ids}"
            )

        records_count = len(accepted_records)
        events_evaluated = len({
            r["event_id"] for r in accepted_records
            if isinstance(r.get("event_id"), int)
        })
        significant_count = sum(
            1 for r in accepted_records
            if r.get("statistically_significant")
        )
        by_horizon = _aggregate_by_horizon(accepted_records)
        by_mechanism_family = _aggregate_by_mechanism_family(accepted_records)
        examples = _build_examples(accepted_records, limit=limit)

        for e_str in validation_payload.get("errors") or []:
            if isinstance(e_str, str) and e_str:
                errors.append(f"validation: {e_str}")

    return _envelope(
        worksheet_path=worksheet_path,
        accepted_count=accepted_count,
        events_evaluated=events_evaluated,
        records_count=records_count,
        significant_count=significant_count,
        by_horizon=by_horizon,
        by_mechanism_family=by_mechanism_family,
        examples=examples,
        excluded_candidates=excluded_candidates,
        errors=errors,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Worksheet parsing
# ---------------------------------------------------------------------------


def _parse_worksheet(
    worksheet_path: str,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Read the worksheet CSV.  Only ``event_id`` is required; other
    columns are optional and treated as blank when absent.
    """
    errors:   list[str] = []
    warnings: list[str] = []
    try:
        with open(worksheet_path, "r", newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []
            if "event_id" not in fieldnames:
                errors.append(
                    "worksheet is missing required column: event_id"
                )
                return [], errors, warnings
            rows = [dict(r) for r in reader]
    except OSError as exc:
        errors.append(
            f"failed to read worksheet {worksheet_path}: {exc}",
        )
        return [], errors, warnings
    return rows, errors, warnings


def _classify_rows(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify worksheet rows into accepted / excluded / pending.

    Returns a dict with keys:
        accepted_event_ids:    set[int]
        accepted_meta:         dict[int, dict]   # per-event worksheet metadata
        excluded_candidates:   list[{event_id, reason, headline}]
        pending_event_ids:     list[int]

    The canonical gate column is
    ``include_in_short_horizon_validation`` — ``yes`` accepts,
    ``no`` excludes, blank / unknown is pending.

    For accepted rows we additionally capture the operator's
    ``proposed_primary_ticker`` / ``proposed_benchmark_ticker`` /
    ``proposed_mechanism_family`` plus the row ``headline``.  Those
    values are the post-review source of truth for the validation
    examples and the ``by_mechanism_family`` aggregation.
    """
    accepted_event_ids: set[int] = set()
    accepted_meta: dict[int, dict[str, Any]] = {}
    excluded_candidates: list[dict[str, Any]] = []
    pending: list[int] = []
    excluded_seen: set[int] = set()

    for row in rows:
        ev_id = _parse_event_id(row.get("event_id"))
        if ev_id is None:
            continue
        gate           = _gate_value(row.get(_GATE_COLUMN))
        exclude_reason = _coerce_str(row.get("exclude_reason"))
        headline       = _coerce_str(row.get("headline"))

        if gate == _GATE_NO:
            if ev_id in excluded_seen:
                continue
            excluded_seen.add(ev_id)
            excluded_candidates.append({
                "event_id": ev_id,
                # Conservative wording — fall back to a neutral note
                # if the operator forgot to record a reason on a no
                # row.  The apply smoke is responsible for enforcing
                # the non-blank rule; here we just route.
                "reason":   exclude_reason or "no reason recorded",
                "headline": headline,
            })
            continue
        if gate == _GATE_YES:
            accepted_event_ids.add(ev_id)
            # Last write wins on a duplicate event_id — matches the
            # existing accepted-set semantics where duplicates collapse.
            accepted_meta[ev_id] = {
                "proposed_primary_ticker":   _coerce_str(
                    row.get("proposed_primary_ticker")
                ),
                "proposed_benchmark_ticker": _coerce_str(
                    row.get("proposed_benchmark_ticker")
                ),
                "proposed_mechanism_family": _coerce_str(
                    row.get("proposed_mechanism_family")
                ),
                "headline":                  headline,
            }
            continue
        pending.append(ev_id)

    return {
        "accepted_event_ids":  accepted_event_ids,
        "accepted_meta":       accepted_meta,
        "excluded_candidates": excluded_candidates,
        "pending_event_ids":   pending,
    }


def _gate_value(raw: Any) -> str:
    """Normalise an ``include_in_short_horizon_validation`` cell.

    Case- and whitespace-insensitive.  Empty / non-string returns
    ``""`` so the caller treats it as pending.
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip().lower()
    return str(raw).strip().lower()


def _parse_event_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except (TypeError, ValueError):
            return None
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------------------
# Aggregates + examples
# ---------------------------------------------------------------------------


def _empty_by_horizon() -> dict[str, Any]:
    return {
        str(h): {
            "records_count":     0,
            "significant_count": 0,
        }
        for h in _SHORT_HORIZONS
    }


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out = _empty_by_horizon()
    for rec in records:
        h = rec.get("horizon")
        if h not in _SHORT_HORIZONS:
            continue
        key = str(h)
        out[key]["records_count"] += 1
        if rec.get("statistically_significant"):
            out[key]["significant_count"] += 1
    return out


def _apply_worksheet_metadata(
    records: list[dict[str, Any]],
    accepted_meta: dict[int, dict[str, Any]],
) -> None:
    """Override each record's ``mechanism_family`` / ``ticker`` /
    ``benchmark`` / ``headline`` with the operator's worksheet values
    where the operator filled them in.

    ``mechanism_family`` is overridden unconditionally: post-review,
    the worksheet's ``proposed_mechanism_family`` is the source of
    truth.  A blank operator value lands ``None`` on the record so the
    ``by_mechanism_family`` aggregator drops it cleanly rather than
    silently bucketing the upstream value.

    ``ticker`` and ``benchmark`` are overridden only when the operator
    actually supplied a value — a blank cell falls back to the
    upstream record's value.  ``headline`` falls back to the worksheet
    only when the record carries none.
    """
    for rec in records:
        ev_id = rec.get("event_id")
        meta = accepted_meta.get(ev_id) if isinstance(ev_id, int) else None
        if not meta:
            # Defensive — record's event_id is in accepted_event_ids
            # but somehow not in accepted_meta.  Strip mechanism_family
            # so the aggregator doesn't silently bucket it.
            rec["mechanism_family"] = None
            continue
        rec["mechanism_family"] = meta.get("proposed_mechanism_family")
        primary = meta.get("proposed_primary_ticker")
        if primary:
            rec["ticker"] = primary
        benchmark = meta.get("proposed_benchmark_ticker")
        if benchmark:
            rec["benchmark"] = benchmark
        if not _coerce_str(rec.get("headline")) and meta.get("headline"):
            rec["headline"] = meta["headline"]


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, Any]] = {}
    seen_events: dict[str, set[int]] = {}
    for rec in records:
        family = rec.get("mechanism_family")
        if not isinstance(family, str) or not family:
            continue
        block = out.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        ev_id = rec.get("event_id")
        if isinstance(ev_id, int):
            seen = seen_events.setdefault(family, set())
            if ev_id not in seen:
                seen.add(ev_id)
                block["events_evaluated"] += 1
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _build_examples(
    records: list[dict[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    capped = max(int(limit), 0)
    sorted_records = sorted(
        records,
        key=lambda r: (r.get("event_id", 0), r.get("horizon", 0)),
    )
    out: list[dict[str, Any]] = []
    for rec in sorted_records[:capped]:
        out.append({
            "event_id":         rec.get("event_id"),
            "headline":         rec.get("headline"),
            "primary_ticker":   rec.get("ticker"),
            "benchmark":        rec.get("benchmark") or _BENCHMARK_TICKER,
            "mechanism_family": rec.get("mechanism_family"),
            "horizon":          rec.get("horizon"),
            "abnormal_return":  rec.get("abnormal_return"),
            "sar":              rec.get("sar"),
            "ci_low":           rec.get("ci_low"),
            "ci_high":          rec.get("ci_high"),
            "p_value":          rec.get("p_value"),
            "fdr_q":            rec.get("fdr_q"),
            "interpretation":   rec.get("interpretation"),
        })
    return out


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------


def _envelope(
    *,
    worksheet_path: str | None,
    accepted_count: int = 0,
    events_evaluated: int = 0,
    records_count: int = 0,
    significant_count: int = 0,
    by_horizon: dict[str, Any] | None = None,
    by_mechanism_family: dict[str, Any] | None = None,
    examples: list[dict[str, Any]] | None = None,
    excluded_candidates: list[dict[str, Any]] | None = None,
    errors: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "ok":                  not errors,
        "worksheet_path":      worksheet_path,
        "accepted_count":      accepted_count,
        "events_evaluated":    events_evaluated,
        "records_count":       records_count,
        "significant_count":   significant_count,
        "by_horizon":          (
            by_horizon if by_horizon is not None else _empty_by_horizon()
        ),
        "by_mechanism_family": (
            by_mechanism_family if by_mechanism_family is not None else {}
        ),
        "examples":            examples or [],
        "excluded_candidates": excluded_candidates or [],
        "errors":              errors,
        "warnings":            warnings,
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Reviewed short-horizon validation smoke", ""]
    lines.append(f"ok:                  {report['ok']}")
    lines.append(f"worksheet_path:      {report['worksheet_path']}")
    lines.append(f"accepted_count:      {report['accepted_count']}")
    lines.append(f"events_evaluated:    {report['events_evaluated']}")
    lines.append(f"records_count:       {report['records_count']}")
    lines.append(f"significant_count:   {report['significant_count']}")
    lines.append("")
    lines.append("Per horizon:")
    for h_key in sorted(report["by_horizon"].keys(), key=lambda x: int(x)):
        block = report["by_horizon"][h_key]
        lines.append(
            f"  h={h_key:>3}  records={block['records_count']:>4} "
            f"significant={block['significant_count']:>4}"
        )

    fam_block = report.get("by_mechanism_family") or {}
    if fam_block:
        lines.append("")
        lines.append("Per mechanism_family:")
        for family in sorted(fam_block.keys()):
            stats = fam_block[family]
            lines.append(
                f"  {family:<32} events={stats['events_evaluated']:>3} "
                f"records={stats['records_count']:>4} "
                f"significant={stats['significant_count']:>4}"
            )

    examples = report.get("examples") or []
    if examples:
        lines.append("")
        lines.append(f"Examples ({len(examples)}):")
        for ex in examples:
            headline = (ex.get("headline") or "").strip() or "-"
            if len(headline) > 70:
                headline = headline[:67] + "..."
            lines.append(
                f"  id={ex.get('event_id')} h={ex.get('horizon'):>3} "
                f"ticker={ex.get('primary_ticker') or '-':<6} "
                f"bench={ex.get('benchmark') or '-'} "
                f"AR={_fmt(ex.get('abnormal_return'))} "
                f"SAR={_fmt(ex.get('sar'))} "
                f"p={_fmt(ex.get('p_value'))} "
                f"fdr_q={_fmt(ex.get('fdr_q'))} "
                f"interp={ex.get('interpretation')}"
            )
            lines.append(f"      headline: {headline}")

    excluded = report.get("excluded_candidates") or []
    if excluded:
        lines.append("")
        lines.append(f"Excluded candidates ({len(excluded)}):")
        for entry in excluded:
            head = (entry.get("headline") or "").strip() or "-"
            if len(head) > 70:
                head = head[:67] + "..."
            lines.append(
                f"  id={entry.get('event_id')} reason={entry.get('reason')}"
            )
            lines.append(f"      headline: {head}")

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
            "Reviewed short-horizon validation smoke.  Reads a "
            "manually reviewed short-horizon worksheet, extracts the "
            "operator-accepted event_ids, and runs the read-only "
            "1d/5d archive validation pipeline against a TEMP copy of "
            "the events DB so the operator can see the short-horizon "
            "evidence carried by the existing price_cache.  No live "
            "DB writes, no provider, no LLM, no FastAPI.  Conservative "
            "wording — reviewed short-horizon evidence, candidate, "
            "never proof."
        ),
    )
    parser.add_argument(
        "--worksheet", dest="worksheet_path", default=None,
        help=(
            "Path to the manually reviewed short-horizon worksheet "
            "CSV.  ``event_id`` is the only required column.  The "
            "canonical operator gate is "
            "``include_in_short_horizon_validation`` "
            "(``yes`` / ``no`` / blank); ``exclude_reason`` and "
            "``headline`` are read when present."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Defaults to "
            "db.DB_FILE.  The smoke only reads from this path; "
            "validation runs against a temp copy."
        ),
    )
    parser.add_argument(
        "--output", dest="output_path", default=None,
        help=(
            "Optional path to write the JSON envelope to.  When "
            "omitted, the smoke has no filesystem side effect."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced ``examples`` list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every accepted record."
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

    report = run_short_horizon_review_validate(
        worksheet_path=args.worksheet_path,
        db_path=db_path,
        output_path=args.output_path,
        limit=int(args.limit),
    )

    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


__all__: tuple[str, ...] = (
    "run_short_horizon_review_validate",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
