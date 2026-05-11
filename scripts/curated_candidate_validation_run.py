#!/usr/bin/env python3
"""Read-only validation runner for staged ``curated_candidates`` rows.

Joins the staged operator-curated candidate table against the
existing read-only statistical validation pipeline so API-staged
candidates can become the next evidence source without manual YAML
loading.  The runner does NOT treat staging as validation — it
filters per-event records to the staged set and surfaces SAR / CI /
p / FDR for review.

Status filter
-------------

Only candidates whose ``status`` is one of
``{"needs_review", "ready_for_validation"}`` feed the pipeline.
Drafts, validated, and archived rows are skipped.  Production reads
this table via the SQL filter; the function-layer drop is a
defensive belt-and-braces guard for non-SQL fixtures.

Required-field check
--------------------

Each staged candidate must carry non-blank ``event_date``,
``headline``, ``primary_ticker``, ``benchmark_ticker``,
``mechanism_family``.  Rows that fail any check land in
``excluded_candidates`` with a per-row reason list AND bump the
aggregate ``missing_fields`` counter.  Excluded candidates are NOT
sent to the validation pipeline.

Patchable seams
---------------

  * ``_load_staged_candidates(*, db_path)`` — returns
    ``(candidates, errors)``.  Production reads from the live
    ``curated_candidates`` table via :data:`db.DB_FILE`; tests patch
    this seam directly.
  * ``_run_validation_pipeline(*, db_path)`` — wraps
    :func:`scripts.archive_stat_validation_run.run_archive_stat_validation`
    and enriches its examples with ``mechanism_family`` +
    ``statistically_significant`` (the same enrichment used by the
    repaired-cohort runner).  Tests patch this seam directly.

Output contract::

    {
      "ok":                       bool,
      "staged_candidate_count":   int,
      "events_evaluated":         int,
      "records_count":            int,
      "significant_count":        int,
      "by_horizon":               {str: {records_count, significant_count}},
      "by_mechanism_family":      {str: {events_evaluated, records_count,
                                         significant_count}},
      "examples":                 [{...}, ...],   # 13 fields each, capped
      "missing_fields":           {field: count, ...},
      "excluded_candidates":      [{source_event_id, reasons}, ...],
      "errors":                   [str, ...],
      "warnings":                 [str, ...],
      "recommended_next_action":  str,
    }

Each example carries 16 fields::

    source_event_id, headline, primary_ticker, benchmark_ticker,
    mechanism_family, horizon, abnormal_return, sar, ci_low,
    ci_high, p_value, fdr_q, interpretation,
    raw_p_candidate, fdr_significant, verdict

The curated row is the source of truth for ``primary_ticker``,
``benchmark_ticker``, ``mechanism_family``, and ``headline``; the
validation pipeline supplies the numerical fields.

The three new verdict fields make a per-record raw-p/FDR split
visible to a demo reader without weakening FDR discipline:

  * ``raw_p_candidate`` — True iff ``p_value`` is a finite real and
    ``p_value <= DEFAULT_ALPHA`` (matches the raw-p check the
    repaired-cohort summary uses).  False when ``p_value`` is None,
    NaN, or not a real number.
  * ``fdr_significant`` — True iff
    :func:`stats.stat_validation.is_statistically_significant`
    clears.  Never True for raw-p-only records — FDR is the strict
    bar.
  * ``verdict`` — closed vocabulary, evaluated top-down:
    - ``fdr_significant``     — ``fdr_significant`` is True.
    - ``validated_raw_only``  — raw-p clears but FDR does not.
      Never reached when ``fdr_significant`` is True.
    - ``inconclusive_fdr``    — at least one of ``p_value`` /
      ``fdr_q`` is a finite real, but neither bar clears.
    - ``not_evaluable``       — both ``p_value`` and ``fdr_q`` are
      missing / non-numeric.

The ``interpretation`` field continues to surface the validation
pipeline's signal label; the three new fields are the clearer
demo-facing fields.

Out of scope (deliberately)
---------------------------

* Live DB is NEVER opened for writes.
* No provider, no LLM, no FastAPI surface — never imports ``api`` /
  ``routes.*``.
* No new SAR / CI / p / FDR computation — every numeric comes
  straight from the existing validation pipeline.

Conservative wording
--------------------

The events surfaced are "staged candidate evidence," not proof,
not a validated archive, not an alpha claim.  Banned tokens
(``proof``, ``validated archive``, ``automatically``, ``alpha``)
never appear in any text the runner emits.

Usage::

    python scripts/curated_candidate_validation_run.py
    python scripts/curated_candidate_validation_run.py --json --limit 50
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 50


# Closed verdict vocabulary surfaced on each example.  Ordered by the
# verdict ladder in the module docstring — fdr_significant is the
# strictest bar; not_evaluable is the absent-data case.
_VERDICT_FDR_SIGNIFICANT:   str = "fdr_significant"
_VERDICT_VALIDATED_RAW_ONLY: str = "validated_raw_only"
_VERDICT_INCONCLUSIVE_FDR:  str = "inconclusive_fdr"
_VERDICT_NOT_EVALUABLE:     str = "not_evaluable"

_STAGED_STATUSES: frozenset[str] = frozenset({
    "needs_review",
    "ready_for_validation",
})

# Required fields for a staged candidate to feed the pipeline.  The
# list mirrors :mod:`scripts.curated_candidate_status` so operators
# get the same picture from the status report and this runner.
_REQUIRED_FIELDS: tuple[str, ...] = (
    "event_date",
    "headline",
    "primary_ticker",
    "benchmark_ticker",
    "mechanism_family",
)


_RECOMMENDED_EMPTY = (
    "No staged candidates feed the validation pipeline — surface "
    "more events to needs_review / ready_for_validation, then "
    "re-run.  Staged candidate evidence only — not proof, not a "
    "validated archive."
)
_RECOMMENDED_HAS_RECORDS = (
    "{n} staged candidate(s) produced {r} (event, horizon) record(s) "
    "with {s} clearing FDR.  Treat as staged candidate evidence — "
    "not proof, not a validated archive.  Operator must inspect each "
    "record before promoting any candidate to a validated status."
)


# ---------------------------------------------------------------------------
# Patchable seams
# ---------------------------------------------------------------------------


def _load_staged_candidates(
    *, db_path: str | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Load staged ``curated_candidates`` rows from the live DB.

    Reads only rows whose ``status`` is one of the staged values.
    Returns ``(candidates, errors)``; errors carries any read-side
    failure (missing table / connect error / etc.) as a string so
    the caller surfaces it under the runner's ``errors`` envelope.

    Tests patch this seam directly; production resolves ``db.DB_FILE``
    when ``db_path`` is None.
    """
    errors: list[str] = []
    path = _resolve_db_path(db_path)
    if path is None:
        errors.append(
            "curated candidate runner: db.DB_FILE not resolvable; "
            "no staged candidates loaded"
        )
        return [], errors

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error as e:
        errors.append(f"failed to open events DB at {path}: {e}")
        return [], errors

    out: list[dict[str, Any]] = []
    try:
        try:
            placeholders = ",".join(["?"] * len(_STAGED_STATUSES))
            rows = conn.execute(
                f"SELECT id, source_event_id, status, event_date, "
                f"headline, source_url, primary_ticker, benchmark_ticker, "
                f"mechanism_family, mechanism_description, "
                f"predicted_direction, prediction_rationale, "
                f"curator_notes, source "
                f"FROM curated_candidates "
                f"WHERE status IN ({placeholders}) "
                f"ORDER BY id ASC",
                list(_STAGED_STATUSES),
            ).fetchall()
        except sqlite3.Error as e:
            errors.append(f"failed to read curated_candidates: {e}")
            return [], errors
        cols = (
            "id", "source_event_id", "status", "event_date", "headline",
            "source_url", "primary_ticker", "benchmark_ticker",
            "mechanism_family", "mechanism_description",
            "predicted_direction", "prediction_rationale",
            "curator_notes", "source",
        )
        for row in rows:
            out.append({c: v for c, v in zip(cols, row)})
    finally:
        conn.close()
    return out, errors


def _run_validation_pipeline(
    *, db_path: str | None,
) -> dict[str, Any]:
    """Invoke the read-only archive validation runner against the
    live events archive.  Reuses the enrichment pattern from the
    repaired-cohort runner so records carry ``mechanism_family`` +
    ``statistically_significant``.
    """
    from scripts.archive_stat_validation_run import (
        run_archive_stat_validation,
    )
    from scripts.manual_repaired_cohort_validation_run import (
        _mechanism_family_by_event_id,
    )
    from stats.stat_validation import (
        DEFAULT_ALPHA, is_statistically_significant,
    )

    payload = run_archive_stat_validation(db_path=db_path, limit=10**9)
    examples = payload.get("examples") or []
    family_by_id = _mechanism_family_by_event_id(db_path)

    records: list[dict[str, Any]] = []
    for ex in examples:
        if not isinstance(ex, dict):
            continue
        ev_id = ex.get("event_id")
        records.append({
            "event_id":                 ev_id,
            "headline":                 ex.get("headline"),
            "ticker":                   ex.get("ticker"),
            "horizon":                  ex.get("horizon"),
            "abnormal_return":          ex.get("abnormal_return"),
            "sar":                      ex.get("sar"),
            "ci_low":                   ex.get("ci_low"),
            "ci_high":                  ex.get("ci_high"),
            "p_value":                  ex.get("p_value"),
            "fdr_q":                    ex.get("fdr_q"),
            "interpretation":           ex.get("interpretation"),
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


def run_curated_candidate_validation(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Run the curated-candidate validation runner.  See module
    docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)
    errors:   list[str] = []
    warnings: list[str] = []

    raw_candidates, load_errors = _load_staged_candidates(db_path=db_path)
    errors.extend(load_errors)

    # Drop candidates whose status is not in the staged set (defensive
    # belt-and-braces filter — the SQL layer already filtered, but a
    # synthetic fixture might leak).
    staged_candidates = [
        c for c in raw_candidates
        if isinstance(c, dict) and c.get("status") in _STAGED_STATUSES
    ]

    # Required-field check + missing_fields aggregate.
    missing_fields: dict[str, int] = {}
    excluded_candidates: list[dict[str, Any]] = []
    eligible_by_id: dict[int, dict[str, Any]] = {}
    for cand in staged_candidates:
        ev_id = cand.get("source_event_id")
        gaps: list[str] = []
        for field in _REQUIRED_FIELDS:
            if _is_missing(cand.get(field)):
                missing_fields[field] = missing_fields.get(field, 0) + 1
                gaps.append(f"missing required field: {field}")
        if gaps:
            excluded_candidates.append({
                "source_event_id": ev_id,
                "reasons":         gaps,
            })
            continue
        if not isinstance(ev_id, int):
            excluded_candidates.append({
                "source_event_id": ev_id,
                "reasons":         ["source_event_id is not an integer"],
            })
            continue
        eligible_by_id[ev_id] = cand

    eligible_ids: set[int] = set(eligible_by_id.keys())

    # Run the validation pipeline (read-only).  Skip when there's
    # nothing eligible — saves a heavy read on the un-patched path.
    if eligible_ids:
        try:
            validation_payload = _safe_dict(
                _run_validation_pipeline(db_path=db_path)
            )
        except Exception as e:  # noqa: BLE001 — operator-visible
            errors.append(f"validation pipeline failed: {e}")
            validation_payload = {}
    else:
        validation_payload = {}

    all_records = validation_payload.get("records") or []
    repaired_records = [
        r for r in all_records
        if isinstance(r, dict)
        and isinstance(r.get("event_id"), int)
        and r["event_id"] in eligible_ids
    ]
    for e_str in validation_payload.get("errors") or []:
        if isinstance(e_str, str) and e_str:
            errors.append(f"validation: {e_str}")

    records_count = len(repaired_records)
    events_evaluated = len({
        r["event_id"] for r in repaired_records
        if isinstance(r.get("event_id"), int)
    })
    significant_count = sum(
        1 for r in repaired_records
        if r.get("statistically_significant")
    )

    by_horizon = _aggregate_by_horizon(repaired_records)
    by_mechanism_family = _aggregate_by_mechanism_family(
        repaired_records, eligible_by_id,
    )

    examples = _build_examples(
        repaired_records, eligible_by_id, limit=capped_limit,
    )

    recommended = _build_recommended(
        staged_count=len(staged_candidates),
        records_count=records_count,
        significant_count=significant_count,
    )

    ok = not errors

    return {
        "ok":                       ok,
        "staged_candidate_count":   len(staged_candidates),
        "events_evaluated":         events_evaluated,
        "records_count":            records_count,
        "significant_count":        significant_count,
        "by_horizon":               by_horizon,
        "by_mechanism_family":      by_mechanism_family,
        "examples":                 examples,
        "missing_fields":           missing_fields,
        "excluded_candidates":      excluded_candidates,
        "errors":                   errors,
        "warnings":                 warnings,
        "recommended_next_action":  recommended,
    }


def _aggregate_by_horizon(
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, dict[str, int]] = {}
    for rec in records:
        h = rec.get("horizon")
        if not isinstance(h, int):
            continue
        block = out.setdefault(str(h), {
            "records_count":     0,
            "significant_count": 0,
        })
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _aggregate_by_mechanism_family(
    records: list[dict[str, Any]],
    eligible_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Group records by the CURATED row's mechanism_family — that's
    the operator-staged classification, which the curated archive
    treats as the source of truth.  Pipeline-derived families are
    ignored.
    """
    out: dict[str, dict[str, int]] = {}
    seen_events: dict[str, set[int]] = {}
    for rec in records:
        ev_id = rec.get("event_id")
        if not isinstance(ev_id, int):
            continue
        cand = eligible_by_id.get(ev_id) or {}
        family = cand.get("mechanism_family")
        if not isinstance(family, str) or not family.strip():
            continue
        block = out.setdefault(family, {
            "events_evaluated":  0,
            "records_count":     0,
            "significant_count": 0,
        })
        seen = seen_events.setdefault(family, set())
        if ev_id not in seen:
            seen.add(ev_id)
            block["events_evaluated"] += 1
        block["records_count"] += 1
        if rec.get("statistically_significant"):
            block["significant_count"] += 1
    return out


def _build_examples(
    records: list[dict[str, Any]],
    eligible_by_id: dict[int, dict[str, Any]],
    *, limit: int,
) -> list[dict[str, Any]]:
    """Compose the per-record example list.  The CURATED row supplies
    primary_ticker / benchmark_ticker / mechanism_family / headline;
    the validation pipeline supplies the numerical fields.  Each row
    also carries the three demo-facing verdict fields documented in
    the module docstring.
    """
    from stats.stat_validation import DEFAULT_ALPHA

    sorted_records = sorted(
        records,
        key=lambda r: (
            r.get("event_id") if isinstance(r.get("event_id"), int) else 0,
            r.get("horizon")  if isinstance(r.get("horizon"),  int) else 0,
        ),
    )
    out: list[dict[str, Any]] = []
    for rec in sorted_records[:limit]:
        ev_id = rec.get("event_id")
        cand = eligible_by_id.get(ev_id) if isinstance(ev_id, int) else {}
        cand = cand or {}
        p_value = rec.get("p_value")
        fdr_q   = rec.get("fdr_q")
        raw_p_candidate = _is_raw_p_candidate(p_value, alpha=DEFAULT_ALPHA)
        # Reuse the validation pipeline's own significance derivation
        # when it surfaced one; fall back to the canonical check
        # otherwise.  Either way, FDR is the strict bar and never
        # fires on a raw-p-only record.
        pipeline_sig = rec.get("statistically_significant")
        if isinstance(pipeline_sig, bool):
            fdr_significant = pipeline_sig
        else:
            fdr_significant = _safe_fdr_significant(
                fdr_q, alpha=DEFAULT_ALPHA,
            )
        out.append({
            "source_event_id":  ev_id,
            "headline":         cand.get("headline"),
            "primary_ticker":   cand.get("primary_ticker"),
            "benchmark_ticker": cand.get("benchmark_ticker"),
            "mechanism_family": cand.get("mechanism_family"),
            "horizon":          rec.get("horizon"),
            "abnormal_return":  rec.get("abnormal_return"),
            "sar":              rec.get("sar"),
            "ci_low":           rec.get("ci_low"),
            "ci_high":          rec.get("ci_high"),
            "p_value":          p_value,
            "fdr_q":            fdr_q,
            "interpretation":   rec.get("interpretation"),
            "raw_p_candidate":  raw_p_candidate,
            "fdr_significant":  fdr_significant,
            "verdict":          _classify_verdict(
                p_value=p_value,
                fdr_q=fdr_q,
                raw_p_candidate=raw_p_candidate,
                fdr_significant=fdr_significant,
            ),
        })
    return out


def _is_finite_number(value: Any) -> bool:
    """True iff ``value`` is a real number (not bool / None / NaN)."""
    if value is None or isinstance(value, bool):
        return False
    if not isinstance(value, (int, float)):
        return False
    return not (math.isnan(float(value)) or math.isinf(float(value)))


def _is_raw_p_candidate(p_value: Any, *, alpha: float) -> bool:
    """True iff ``p_value`` is a finite real <= ``alpha``.

    Mirrors the raw-p check used by
    :mod:`scripts.manual_repaired_cohort_validation_summary` so the
    runner and the cohort summary classify raw-p the same way.  No
    new threshold introduced — ``alpha`` is the existing
    :data:`stats.stat_validation.DEFAULT_ALPHA`.
    """
    if not _is_finite_number(p_value):
        return False
    return float(p_value) <= alpha


def _safe_fdr_significant(fdr_q: Any, *, alpha: float) -> bool:
    """Defensive wrapper around
    :func:`stats.stat_validation.is_statistically_significant`.

    Returns False for any input the strict canonical helper would
    reject (bool, non-numeric, NaN, Inf) so a fixture quirk cannot
    crash the example builder.  Conservative: never returns True
    where the strict helper would refuse to answer.
    """
    from stats.stat_validation import is_statistically_significant

    if not _is_finite_number(fdr_q):
        return False
    try:
        return is_statistically_significant(fdr_q, alpha=alpha)
    except (TypeError, ValueError):
        return False


def _classify_verdict(
    *, p_value: Any, fdr_q: Any,
    raw_p_candidate: bool, fdr_significant: bool,
) -> str:
    """Pick the demo-facing verdict for one record.  Order matters —
    FDR is the strict bar; raw-p-only never becomes ``fdr_significant``.
    """
    if fdr_significant:
        return _VERDICT_FDR_SIGNIFICANT
    if raw_p_candidate:
        return _VERDICT_VALIDATED_RAW_ONLY
    if _is_finite_number(p_value) or _is_finite_number(fdr_q):
        return _VERDICT_INCONCLUSIVE_FDR
    return _VERDICT_NOT_EVALUABLE


def _build_recommended(
    *, staged_count: int, records_count: int, significant_count: int,
) -> str:
    if staged_count == 0:
        return _RECOMMENDED_EMPTY
    if records_count == 0:
        return (
            f"{staged_count} staged candidate(s) cleared the field check "
            f"but produced no validation records — inspect the price-cache "
            f"coverage on the events archive.  Staged candidate evidence "
            f"only — not proof, not a validated archive."
        )
    return _RECOMMENDED_HAS_RECORDS.format(
        n=staged_count, r=records_count, s=significant_count,
    )


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Curated candidate validation runner", ""]
    lines.append(f"OK:                          {report['ok']}")
    lines.append(
        f"Staged candidate count:      {report['staged_candidate_count']}"
    )
    lines.append(f"Events evaluated:            {report['events_evaluated']}")
    lines.append(f"Records count:               {report['records_count']}")
    lines.append(f"Significant count:           {report['significant_count']}")
    if report.get("missing_fields"):
        lines.append("")
        lines.append("Missing-field gaps:")
        for field in sorted(report["missing_fields"].keys()):
            lines.append(
                f"  {field:<25} {report['missing_fields'][field]}"
            )
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
    examples = report.get("examples") or []
    if examples:
        lines.append("")
        lines.append(f"Examples ({len(examples)}):")
        for ex in examples:
            lines.append(
                f"  id={ex.get('source_event_id')} h={_fmt(ex.get('horizon'))} "
                f"{ex.get('primary_ticker') or '-'}/"
                f"{ex.get('benchmark_ticker') or '-'} "
                f"family={ex.get('mechanism_family') or '-'} "
                f"AR={_fmt(ex.get('abnormal_return'))} "
                f"SAR={_fmt(ex.get('sar'))} "
                f"p={_fmt(ex.get('p_value'))} "
                f"fdr_q={_fmt(ex.get('fdr_q'))} "
                f"interp={ex.get('interpretation')}"
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
    lines.append("")
    lines.append(
        f"Recommended next action: {report['recommended_next_action']}"
    )
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only validation runner over the staged "
            "curated_candidates table.  Filters to status in "
            "{needs_review, ready_for_validation}, drops candidates "
            "missing required fields, and surfaces SAR / CI / p / "
            "FDR for the events the existing read-only validation "
            "pipeline produced records for.  Conservative language "
            "only — staged candidate evidence, not proof, not a "
            "validated archive."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of compact text.",
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced examples list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every evaluated staged candidate."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the runner follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout
    report = run_curated_candidate_validation(
        db_path=args.db_path, limit=int(args.limit),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
