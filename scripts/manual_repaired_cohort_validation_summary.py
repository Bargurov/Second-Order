#!/usr/bin/env python3
"""Read-only summary artifact for the repaired-cohort validation run.

Wraps :mod:`scripts.manual_repaired_cohort_validation_run` through a
single patchable seam and distills its output into a stable 8-key JSON
shape suitable for demo / review.  This module does NOT compute SAR /
CI / p / FDR — it consumes the runner's output and surfaces a
conservative summary.

Read-only by construction
-------------------------

* Calls into the validation runner, which itself operates on a copied
  backup; this module never touches the live DB or input backup.
* No DB writes anywhere.  No LLM, no FastAPI, no provider call from
  this module — those concerns live in the validation runner.

Output contract::

    {
      "repaired_clean_event_ids":  [int, ...],
      "events_evaluated":          int,
      "records_count":             int,
      "significant_count":         int,
      "top_abs_sar":               [{...}, ...],
      "by_event_verdict":          {str: str},
      "limitations":               [str, ...],
      "recommended_next_action":   str,
    }

The summary carries EXACTLY these 8 keys — no ``ok`` / ``errors`` /
``warnings`` envelope.  Runner errors fold into ``limitations`` as
strings; that is the only escape hatch.

Verdict vocabulary (conservative)
---------------------------------

* ``validated_raw_only`` — at least one record cleared raw
  ``p_value <= alpha``.  Lumps FDR-significant in too because the
  vocabulary lacks a stronger label and the project never claims
  alpha.
* ``contradicted`` — operator supplied a direction expectation per
  mechanism family AND at least one raw-p-significant record has an
  AR sign opposite that expectation.  Default: never assigned (no
  direction map).
* ``inconclusive_fdr`` — no raw-p signal, but at least one record
  with ``|SAR| >= 1.0``.  "Some signal, didn't clear."
* ``insufficient`` — no records, OR every record has ``|SAR| < 1.0``
  AND no raw-p signal.

Order of evaluation: validated_raw_only → contradicted →
inconclusive_fdr → insufficient.  First match wins.

Each entry in ``top_abs_sar`` carries the same 13-field example shape
the runner emits: ``event_id``, ``headline``, ``primary_ticker``,
``benchmark``, ``mechanism_family``, ``horizon``,
``abnormal_return``, ``sar``, ``ci_low``, ``ci_high``, ``p_value``,
``fdr_q``, ``interpretation``.  Sorted by ``abs(sar)`` descending;
ties broken by ``(event_id asc, horizon asc)``; rows with
``sar is None`` sink to the bottom; capped at ``--limit``.

Patchable seam
--------------

* ``_run_validation_run`` — wraps
  ``manual_repaired_cohort_validation_run.run_manual_repaired_cohort_validation``.
  Tests patch this seam directly with synthetic payloads.

Usage::

    python scripts/manual_repaired_cohort_validation_summary.py --json \\
        --backup-path backups/events-20260507T095609.db \\
        --high-priority-csv manual_ticker_repair_high_priority.csv \\
        --medium-csv manual_ticker_repair_medium_production_like.csv \\
        --limit 50
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT:    int   = 50
_DEFAULT_ALPHA:    float = 0.05
_INCONCLUSIVE_SAR_THRESHOLD: float = 1.0


_VERDICT_VALIDATED_RAW_ONLY: str = "validated_raw_only"
_VERDICT_CONTRADICTED:       str = "contradicted"
_VERDICT_INCONCLUSIVE_FDR:   str = "inconclusive_fdr"
_VERDICT_INSUFFICIENT:       str = "insufficient"


# ---------------------------------------------------------------------------
# Patchable seam — local to this module so tests patch a single
# surface.  The lazy import only fires on the un-patched path.
# ---------------------------------------------------------------------------


def _run_validation_run(
    *, backup_path: str | None,
    high_priority_csv: str | None,
    medium_csv: str | None,
    db_path: str | None,
    limit: int,
) -> dict[str, Any]:
    """Invoke the manual-aware repaired-cohort validation runner with
    the operator's inputs and return its full payload.  Tests patch
    this seam to drive the summary without re-running the entire
    pipeline.
    """
    from scripts.manual_repaired_cohort_validation_run import (
        run_manual_repaired_cohort_validation,
    )

    return run_manual_repaired_cohort_validation(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=limit,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_repaired_cohort_validation(
    *,
    backup_path:        str | None     = None,
    high_priority_csv:  str | None     = None,
    medium_csv:         str | None     = None,
    db_path:            str | None     = None,
    limit:              int            = _DEFAULT_LIMIT,
    alpha:              float          = _DEFAULT_ALPHA,
    mechanism_direction: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Run the validation pipeline (via the seam) and distill its
    output into the 8-key summary.  See module docstring for the full
    contract.
    """
    capped_limit = max(int(limit), 0)
    direction_map = dict(mechanism_direction or {})

    payload = _run_validation_run(
        backup_path=backup_path,
        high_priority_csv=high_priority_csv,
        medium_csv=medium_csv,
        db_path=db_path,
        limit=capped_limit,
    )

    repaired_ids = _coerce_int_list(
        payload.get("repaired_clean_event_ids") or [],
    )
    examples: list[dict[str, Any]] = [
        ex for ex in (payload.get("examples") or [])
        if isinstance(ex, dict)
    ]
    events_evaluated = _coerce_int(payload.get("events_evaluated"))
    records_count    = _coerce_int(payload.get("records_count"))
    significant_count = _coerce_int(payload.get("significant_count"))
    runner_errors = [
        e for e in (payload.get("errors") or []) if isinstance(e, str)
    ]

    # by_event_verdict — every event in repaired_clean_event_ids gets a
    # verdict, even those the validation pipeline filtered out (no
    # examples ⇒ insufficient).
    examples_by_event: dict[int, list[dict[str, Any]]] = {}
    for ex in examples:
        ev_id = _coerce_int_or_none(ex.get("event_id"))
        if ev_id is None:
            continue
        examples_by_event.setdefault(ev_id, []).append(ex)
    by_event_verdict: dict[str, str] = {}
    for ev_id in repaired_ids:
        verdict = _verdict_for_event(
            records=examples_by_event.get(ev_id, []),
            alpha=alpha, direction_map=direction_map,
        )
        by_event_verdict[str(ev_id)] = verdict

    # top_abs_sar — sort by abs(sar) desc; ties by (event_id, horizon);
    # sar None rows sink; cap at limit.
    top_abs_sar = _top_abs_sar(examples, limit=capped_limit)

    limitations = _build_limitations(
        records_count=records_count,
        significant_count=significant_count,
        runner_errors=runner_errors,
        repaired_count=len(repaired_ids),
        direction_map=direction_map,
    )
    recommended = _build_recommended_next_action(
        records_count=records_count,
        significant_count=significant_count,
        repaired_count=len(repaired_ids),
        verdicts=by_event_verdict,
    )

    return {
        "repaired_clean_event_ids":  list(repaired_ids),
        "events_evaluated":          events_evaluated,
        "records_count":             records_count,
        "significant_count":         significant_count,
        "top_abs_sar":               top_abs_sar,
        "by_event_verdict":          by_event_verdict,
        "limitations":               limitations,
        "recommended_next_action":   recommended,
    }


# ---------------------------------------------------------------------------
# Verdict logic
# ---------------------------------------------------------------------------


def _verdict_for_event(
    *,
    records: list[dict[str, Any]],
    alpha: float,
    direction_map: dict[str, int],
) -> str:
    """Pick the conservative verdict for one event.  See module
    docstring for the bucket definitions and order of evaluation."""
    if not records:
        return _VERDICT_INSUFFICIENT

    raw_p_hits = [
        r for r in records
        if _is_raw_p_significant(r.get("p_value"), alpha=alpha)
    ]
    has_raw_p = bool(raw_p_hits)

    if has_raw_p:
        # Bucket 2: contradicted — only when operator supplied a
        # direction expectation for this record's mechanism family
        # AND at least one raw-p-significant record's AR sign is
        # opposite that expectation.
        if direction_map and _any_record_contradicts(
            records=raw_p_hits, direction_map=direction_map,
        ):
            return _VERDICT_CONTRADICTED
        return _VERDICT_VALIDATED_RAW_ONLY

    # No raw-p signal — distinguish "some signal" from "nothing."
    max_abs_sar = _max_abs_sar(records)
    if max_abs_sar is not None and max_abs_sar >= _INCONCLUSIVE_SAR_THRESHOLD:
        return _VERDICT_INCONCLUSIVE_FDR
    return _VERDICT_INSUFFICIENT


def _is_raw_p_significant(p_value: Any, *, alpha: float) -> bool:
    p = _coerce_optional_float(p_value)
    if p is None:
        return False
    return p <= alpha


def _any_record_contradicts(
    *, records: list[dict[str, Any]],
    direction_map: dict[str, int],
) -> bool:
    """True iff ANY raw-p-significant record has an AR sign opposite
    the operator's direction expectation for its mechanism family."""
    for r in records:
        family = r.get("mechanism_family")
        if not isinstance(family, str) or not family:
            continue
        expected = direction_map.get(family)
        if not isinstance(expected, int) or expected == 0:
            continue
        ar = _coerce_optional_float(r.get("abnormal_return"))
        if ar is None or ar == 0.0:
            continue
        observed_sign = 1 if ar > 0 else -1
        if observed_sign != (1 if expected > 0 else -1):
            return True
    return False


def _max_abs_sar(records: list[dict[str, Any]]) -> float | None:
    out: float | None = None
    for r in records:
        sar = _coerce_optional_float(r.get("sar"))
        if sar is None:
            continue
        mag = abs(sar)
        if out is None or mag > out:
            out = mag
    return out


# ---------------------------------------------------------------------------
# top_abs_sar
# ---------------------------------------------------------------------------


def _top_abs_sar(
    examples: list[dict[str, Any]], *, limit: int,
) -> list[dict[str, Any]]:
    """Sort by ``abs(sar)`` desc; tie-break by ``(event_id asc,
    horizon asc)``; rows with ``sar is None`` sink to the bottom;
    capped at ``limit``."""
    def sort_key(rec: dict[str, Any]) -> tuple[int, float, int, int]:
        sar = _coerce_optional_float(rec.get("sar"))
        is_null = 1 if sar is None else 0
        # Primary: nulls last.  Secondary: -|sar| (so larger sorts first).
        # Tertiary / quaternary: event_id asc, horizon asc.
        mag = -abs(sar) if sar is not None else 0.0
        ev_id = _coerce_int_or_none(rec.get("event_id")) or 0
        hzn   = _coerce_int_or_none(rec.get("horizon")) or 0
        return (is_null, mag, ev_id, hzn)
    sorted_records = sorted(examples, key=sort_key)
    return [_normalize_example(rec) for rec in sorted_records[:limit]]


def _normalize_example(rec: dict[str, Any]) -> dict[str, Any]:
    """Project an example into the canonical 13-field shape; missing
    fields surface as ``None`` so downstream consumers see a stable
    schema regardless of upstream variations."""
    return {
        "event_id":         rec.get("event_id"),
        "headline":         rec.get("headline"),
        "primary_ticker":   rec.get("primary_ticker"),
        "benchmark":        rec.get("benchmark"),
        "mechanism_family": rec.get("mechanism_family"),
        "horizon":          rec.get("horizon"),
        "abnormal_return":  rec.get("abnormal_return"),
        "sar":              rec.get("sar"),
        "ci_low":           rec.get("ci_low"),
        "ci_high":          rec.get("ci_high"),
        "p_value":          rec.get("p_value"),
        "fdr_q":            rec.get("fdr_q"),
        "interpretation":   rec.get("interpretation"),
    }


# ---------------------------------------------------------------------------
# Limitations + recommended_next_action — conservative language only
# ---------------------------------------------------------------------------


def _build_limitations(
    *,
    records_count: int,
    significant_count: int,
    runner_errors: list[str],
    repaired_count: int,
    direction_map: dict[str, int],
) -> list[str]:
    out: list[str] = [
        "Repaired cohort evidence; not proof and not an alpha claim — "
        "this is a small operator-repaired pilot.",
        f"Repaired cohort N = {repaired_count} events / "
        f"{records_count} (event, horizon) records.",
        "Per-event verdicts use a conservative vocabulary "
        "(validated_raw_only / contradicted / inconclusive_fdr / "
        "insufficient); validated_raw_only does NOT imply FDR clearance.",
    ]
    if not direction_map:
        out.append(
            "No mechanism-family directional expectations were supplied; "
            "'contradicted' is therefore never assigned in this run."
        )
    if records_count == 0:
        out.append(
            "No (event, horizon) records were produced — the validation "
            "pipeline filtered every repaired event out (likely a "
            "forward-cache or estimation-window gap)."
        )
    elif significant_count == 0:
        out.append(
            "No record cleared FDR multiple-testing correction.  Treat "
            "any per-event verdict as suggestive, not confirmatory."
        )
    if runner_errors:
        for e in runner_errors:
            out.append(f"validation runner error: {e}")
    return out


def _build_recommended_next_action(
    *,
    records_count: int,
    significant_count: int,
    repaired_count: int,
    verdicts: dict[str, str],
) -> str:
    if repaired_count == 0:
        return (
            "Repaired cohort is empty — re-run the manual ticker repair "
            "packet on additional contaminated events and re-summarize."
        )
    if records_count == 0:
        return (
            f"Repaired cohort has {repaired_count} events but the "
            f"validation pipeline produced no records.  Inspect the "
            f"forward-cache / estimation-window coverage on the temp "
            f"copy and expand the price backfill window if needed."
        )
    raw_only = sum(
        1 for v in verdicts.values()
        if v == _VERDICT_VALIDATED_RAW_ONLY
    )
    inconclusive = sum(
        1 for v in verdicts.values()
        if v == _VERDICT_INCONCLUSIVE_FDR
    )
    if raw_only > 0:
        return (
            f"Raw-p candidate evidence exists: {raw_only} event(s) carry "
            f"the validated_raw_only verdict, but no FDR-significant "
            f"aggregate claim yet.  Treat as repaired cohort evidence, "
            f"not a causal claim; expand the cohort before making any "
            f"aggregate statistical validation claim."
        )
    if significant_count > 0:
        return (
            f"{significant_count} of {records_count} records cleared the "
            f"raw p-value threshold; {raw_only} event(s) carry the "
            f"validated_raw_only verdict.  Treat as repaired cohort "
            f"evidence, not a causal claim — expand the cohort to "
            f"strengthen the signal."
        )
    if inconclusive > 0:
        return (
            f"No record cleared the raw p-value threshold; "
            f"{inconclusive} event(s) showed |SAR| >= 1 but did not "
            f"clear.  Expand the cohort and consider pre-registering "
            f"directional expectations to enable the contradicted verdict."
        )
    return (
        "Repaired cohort showed no raw-p signal.  Inspect the chosen "
        "candidates' price history and benchmark coverage; consider "
        "re-running the manual ticker repair packet on additional "
        "events before re-summarizing."
    )


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _coerce_int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _coerce_int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    out: list[int] = []
    for v in value:
        i = _coerce_int_or_none(v)
        if i is not None:
            out.append(i)
    return sorted(set(out))


def _coerce_optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if not math.isfinite(f):
            return None
        return f
    return None


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
    lines: list[str] = ["Repaired cohort validation summary", ""]
    lines.append(
        f"Repaired clean event_ids:   "
        f"{report['repaired_clean_event_ids']}"
    )
    lines.append(f"Events evaluated:           {report['events_evaluated']}")
    lines.append(f"Records count:              {report['records_count']}")
    lines.append(f"Significant count:          {report['significant_count']}")

    verdicts = report.get("by_event_verdict") or {}
    if verdicts:
        lines.append("")
        lines.append("Per-event verdict:")
        for ev_id_str in sorted(verdicts.keys(), key=lambda x: int(x)):
            lines.append(f"  id={ev_id_str:>4}  {verdicts[ev_id_str]}")

    top = report.get("top_abs_sar") or []
    if top:
        lines.append("")
        lines.append(f"Top by |SAR| ({len(top)}):")
        for rec in top:
            lines.append(
                f"  id={rec.get('event_id')} h={_fmt(rec.get('horizon'))} "
                f"{rec.get('primary_ticker') or '-'}/{rec.get('benchmark') or '-'} "
                f"family={rec.get('mechanism_family') or '-'} "
                f"AR={_fmt(rec.get('abnormal_return'))} "
                f"SAR={_fmt(rec.get('sar'))} "
                f"p={_fmt(rec.get('p_value'))} "
                f"fdr_q={_fmt(rec.get('fdr_q'))} "
                f"interp={rec.get('interpretation')}"
            )

    lims = report.get("limitations") or []
    if lims:
        lines.append("")
        lines.append("Limitations:")
        for lim in lims:
            lines.append(f"  - {lim}")

    rec_action = report.get("recommended_next_action") or ""
    if rec_action:
        lines.append("")
        lines.append(f"Recommended next action: {rec_action}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only summary artifact for the repaired-cohort "
            "validation run.  Wraps "
            "manual_repaired_cohort_validation_run through a single "
            "patchable seam and distills its output into a stable "
            "8-key JSON shape suitable for demo / review.  Conservative "
            "verdict vocabulary only — never claims proof or alpha."
        ),
    )
    parser.add_argument(
        "--backup-path", dest="backup_path", default=None,
        help="Path to the events DB backup (passed through to the runner).",
    )
    parser.add_argument(
        "--high-priority-csv", dest="high_priority_csv", default=None,
        help="Path to the high-priority manual ticker repair CSV.",
    )
    parser.add_argument(
        "--medium-csv", dest="medium_csv", default=None,
        help="Path to the medium-batch manual ticker repair CSV.",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to the LIVE events DB.  Hashed read-only "
            "by the runner; never opened for writes."
        ),
    )
    parser.add_argument(
        "--limit", type=int, default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced top_abs_sar list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect the full repaired cohort."
        ),
    )
    parser.add_argument(
        "--alpha", type=float, default=_DEFAULT_ALPHA,
        help=(
            f"Significance threshold (default: {_DEFAULT_ALPHA}).  "
            f"Only used to bucket per-event verdicts; aggregate counts "
            f"come straight from the runner."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_repaired_cohort_validation(
        backup_path=args.backup_path,
        high_priority_csv=args.high_priority_csv,
        medium_csv=args.medium_csv,
        db_path=args.db_path,
        limit=int(args.limit),
        alpha=float(args.alpha),
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
