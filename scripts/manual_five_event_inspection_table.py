#!/usr/bin/env python3
"""Operator inspection table for the manual five-event validation smoke.

Consumes the read-only envelope produced by
:mod:`scripts.manual_five_event_validation_smoke` and re-shapes it
into a per-candidate decision table.  The table answers a single
operator question per row: keep, revise, reject, or block on
coverage — never auto-merge.

Read-only by construction
-------------------------

* The validation seam is patchable
  (:func:`_run_validation_smoke`) so the inspection's tests do not
  depend on price-cache contents.  The seam is the only place that
  reaches into the smoke; the rest of the module is pure compute.
* No DB write.  No provider, ``yfinance``, ``market_data``, LLM, or
  FastAPI / ``api`` / ``routes.*`` import — at module load or
  anywhere else.
* No mutation of freeze artifacts.  No write to
  ``artifacts/freeze_candidate_evidence.json`` or its siblings.

Decision rules
--------------

For each input row in the validation envelope (grouped by
``candidate_id`` / ``row_index``):

* ``revise_ticker_or_benchmark`` — ``primary_ticker`` equals
  ``benchmark_ticker``.  Event-study against the same series is
  structurally degenerate; the operator should revise inputs before
  re-running.  This rule wins over the coverage / signal rules
  below because the input itself is malformed.
* ``coverage_blocked`` — the candidate produced zero records (only
  a ``missing_coverage`` entry).  ``missing_coverage_note`` carries
  the smoke's reason verbatim.
* ``inspect_candidate`` — at least one record is
  ``raw_p_candidate`` or ``fdr_significant``.  The operator
  inspects before any merge; the table never claims a row is fit to
  merge.
* ``inspect_do_not_merge`` — records exist but no raw-p or
  FDR-significant horizons.  The operator looks at the data before
  discarding the candidate; the row is explicitly not a merge
  recommendation.

Conservative wording
--------------------

Banned overclaim tokens (``proof``, ``proven``, ``guaranteed``,
``automatically``, ``validated``, ``alpha generated``,
``correct ticker``, ``definitely``, ``approved``,
``production ready``, ``production-ready``, ``demo_ready``,
``demo-ready``) do not appear in any rendered output.  The table
calls candidates "candidates", coverage gaps "coverage", and
defers every actionable conclusion to the operator.

Output contract (JSON)::

    {
      "ok":       bool,
      "rows":     [{row_dict}, ...],
      "summary":  {summary_dict},
      "warnings": [str, ...],
      "errors":   [str, ...],
    }

Each ``row_dict`` carries::

    candidate_id, event_date, headline, mechanism_family,
    primary_ticker, benchmark_ticker, records_count, raw_p_count,
    fdr_count, horizons_available, missing_coverage_note,
    suggested_operator_decision, decision_reason

The ``summary_dict`` carries::

    total_candidates: int
    by_decision:      {decision_token: int}

Usage::

    python scripts/manual_five_event_inspection_table.py --json
    python scripts/manual_five_event_inspection_table.py --json \\
        --input-csv examples/manual_five_event_expansion_batch.csv
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


_DECISION_COVERAGE_BLOCKED:        str = "coverage_blocked"
_DECISION_INSPECT_DO_NOT_MERGE:    str = "inspect_do_not_merge"
_DECISION_INSPECT_CANDIDATE:       str = "inspect_candidate"
_DECISION_REVISE_TICKER_BENCHMARK: str = "revise_ticker_or_benchmark"


_ALL_DECISIONS: tuple[str, ...] = (
    _DECISION_COVERAGE_BLOCKED,
    _DECISION_INSPECT_DO_NOT_MERGE,
    _DECISION_INSPECT_CANDIDATE,
    _DECISION_REVISE_TICKER_BENCHMARK,
)


# ---------------------------------------------------------------------------
# Patchable seam — call into the validation smoke.  Lazy import so the
# inspection's top-level surface stays narrow and the smoke's
# downstream stats imports do not run when the inspection is built
# from a hand-rolled envelope (e.g. in unit tests).
# ---------------------------------------------------------------------------


def _run_validation_smoke(
    *,
    input_csv: str | None,
    horizons:  Sequence[int] | None,
    alpha:     float | None,
) -> dict[str, Any]:
    """Run the manual five-event validation smoke and return its envelope.

    Tests patch this seam so they never hit the on-disk smoke
    behaviour they do not need.
    """
    from scripts.manual_five_event_validation_smoke import (  # noqa: PLC0415
        run_manual_five_event_validation,
        _DEFAULT_INPUT_CSV,
    )
    return run_manual_five_event_validation(
        input_csv=input_csv if input_csv is not None else _DEFAULT_INPUT_CSV,
        horizons=horizons,
        alpha=alpha,
    )


# ---------------------------------------------------------------------------
# Pure compute — build the inspection table from a validation envelope
# ---------------------------------------------------------------------------


def build_inspection_table(envelope: dict[str, Any]) -> dict[str, Any]:
    """Return the operator decision table for one validation envelope.

    See the module docstring for the full output contract.  The
    function does not mutate ``envelope``.
    """
    warnings: list[str] = list(envelope.get("warnings") or [])
    errors:   list[str] = list(envelope.get("errors")   or [])

    records  = list(envelope.get("event_records")    or [])
    missing  = list(envelope.get("missing_coverage") or [])

    groups: dict[Any, dict[str, Any]] = {}
    order:  list[Any] = []

    def _key(entry: dict[str, Any]) -> Any:
        # row_index is the stable per-input-row anchor; candidate_id
        # is a deterministic mirror but missing or duplicated keys
        # would still collide, so prefer row_index when present.
        if "row_index" in entry and entry["row_index"] is not None:
            return ("row", int(entry["row_index"]))
        return ("cid", str(entry.get("candidate_id") or ""))

    def _bucket(entry: dict[str, Any]) -> dict[str, Any]:
        key = _key(entry)
        if key not in groups:
            groups[key] = {
                "candidate_id":     str(entry.get("candidate_id") or ""),
                "row_index":        entry.get("row_index"),
                "event_date":       str(entry.get("event_date") or ""),
                "headline":         str(entry.get("headline") or ""),
                "mechanism_family": str(entry.get("mechanism_family") or ""),
                "primary_ticker":   str(entry.get("primary_ticker") or ""),
                "benchmark_ticker": str(entry.get("benchmark_ticker") or ""),
                "records":          [],
                "missing":          [],
            }
            order.append(key)
        return groups[key]

    for r in records:
        _bucket(r)["records"].append(r)
    for m in missing:
        _bucket(m)["missing"].append(m)

    # Operator-friendly ordering: ascending row_index when present,
    # falling back to candidate_id, falling back to discovery order.
    # Without this, coverage-blocked rows (which only appear via
    # ``missing_coverage``) sink to the bottom of the table because
    # ``records`` are bucketed first.
    def _sort_key(key: Any) -> tuple[int, int, str]:
        grp = groups[key]
        ri = grp.get("row_index")
        try:
            ri_int = int(ri) if ri is not None else 10**9
        except (TypeError, ValueError):
            ri_int = 10**9
        return (
            0 if ri is not None else 1,
            ri_int,
            str(grp.get("candidate_id") or ""),
        )

    ordered_keys = sorted(order, key=_sort_key)

    rows: list[dict[str, Any]] = []
    for key in ordered_keys:
        rows.append(_build_row(groups[key]))

    summary = _build_summary(rows)

    return {
        "ok":       not errors,
        "rows":     rows,
        "summary":  summary,
        "warnings": warnings,
        "errors":   errors,
    }


def _build_row(group: dict[str, Any]) -> dict[str, Any]:
    records = group["records"]
    missing = group["missing"]

    raw_p_count = sum(
        1 for r in records
        if bool(r.get("raw_p_candidate"))
        and not bool(r.get("fdr_significant"))
    )
    fdr_count = sum(
        1 for r in records if bool(r.get("fdr_significant"))
    )
    horizons_available = sorted({
        int(r["horizon"])
        for r in records
        if _finite(r.get("p_value")) and r.get("horizon") is not None
    })

    missing_note = ""
    if missing:
        missing_note = str(missing[0].get("reason") or "")

    primary   = group["primary_ticker"]
    benchmark = group["benchmark_ticker"]

    decision, reason = _decide(
        records_count=len(records),
        raw_p_count=raw_p_count,
        fdr_count=fdr_count,
        primary_ticker=primary,
        benchmark_ticker=benchmark,
        missing_note=missing_note,
    )

    return {
        "candidate_id":     group["candidate_id"],
        "event_date":       group["event_date"],
        "headline":         group["headline"],
        "mechanism_family": group["mechanism_family"],
        "primary_ticker":   primary,
        "benchmark_ticker": benchmark,
        "records_count":    int(len(records)),
        "raw_p_count":      int(raw_p_count),
        "fdr_count":        int(fdr_count),
        "horizons_available":      list(horizons_available),
        "missing_coverage_note":   missing_note,
        "suggested_operator_decision": decision,
        "decision_reason":             reason,
    }


def _decide(
    *,
    records_count:    int,
    raw_p_count:      int,
    fdr_count:        int,
    primary_ticker:   str,
    benchmark_ticker: str,
    missing_note:     str,
) -> tuple[str, str]:
    pt = (primary_ticker or "").strip().upper()
    bt = (benchmark_ticker or "").strip().upper()

    if pt and bt and pt == bt:
        return (
            _DECISION_REVISE_TICKER_BENCHMARK,
            (
                f"primary_ticker matches benchmark_ticker ({pt}); "
                "the event-study against the same series is "
                "structurally degenerate — revise the ticker or "
                "benchmark before re-running"
            ),
        )

    if records_count == 0:
        note = missing_note.strip()
        if note:
            reason = f"no records produced; missing coverage: {note}"
        else:
            reason = "no records produced; coverage gap reported by the smoke"
        return (_DECISION_COVERAGE_BLOCKED, reason)

    if fdr_count > 0 or raw_p_count > 0:
        return (
            _DECISION_INSPECT_CANDIDATE,
            (
                f"{raw_p_count} raw-p / {fdr_count} FDR-significant "
                "horizon(s) — operator inspection required before any "
                "merge"
            ),
        )

    return (
        _DECISION_INSPECT_DO_NOT_MERGE,
        (
            "records produced but no raw-p or FDR-significant horizons "
            "— operator inspects before discarding; not a merge "
            "recommendation"
        ),
    )


def _build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_decision: dict[str, int] = {d: 0 for d in _ALL_DECISIONS}
    for row in rows:
        d = row.get("suggested_operator_decision")
        if d in by_decision:
            by_decision[d] += 1
        else:
            by_decision[str(d)] = by_decision.get(str(d), 0) + 1
    return {
        "total_candidates": int(len(rows)),
        "by_decision":      by_decision,
    }


def _finite(value: Any) -> bool:
    if value is None:
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


# ---------------------------------------------------------------------------
# Entry point — run smoke + build table
# ---------------------------------------------------------------------------


def run_manual_five_event_inspection_table(
    *,
    input_csv: str | None       = None,
    horizons:  Sequence[int] | None = None,
    alpha:     float | None         = None,
    envelope:  dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the inspection table.

    When ``envelope`` is supplied the function is pure compute over
    it.  Otherwise the validation smoke is invoked through the
    patchable :func:`_run_validation_smoke` seam.
    """
    env = envelope
    if env is None:
        env = _run_validation_smoke(
            input_csv=input_csv,
            horizons=horizons,
            alpha=alpha,
        )
    return build_inspection_table(env)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_json(envelope: dict[str, Any]) -> str:
    return json.dumps(envelope, indent=2, sort_keys=True, default=str)


def _render_text(envelope: dict[str, Any]) -> str:
    lines: list[str] = [
        "Manual five-event operator inspection table",
        "",
    ]
    lines.append(f"OK:                  {envelope['ok']}")
    summary = envelope.get("summary") or {}
    lines.append(
        f"Total candidates:    {summary.get('total_candidates', 0)}"
    )
    by_decision = summary.get("by_decision") or {}
    for d in _ALL_DECISIONS:
        lines.append(f"  {d:<32} {int(by_decision.get(d, 0))}")
    if envelope.get("rows"):
        lines.append("")
        lines.append("Rows:")
        for row in envelope["rows"]:
            lines.append(
                f"  - {row['candidate_id']:<18}  "
                f"{row['event_date']:<10}  "
                f"{row['primary_ticker']:>6}/{row['benchmark_ticker']:<6}  "
                f"records={row['records_count']:>2}  "
                f"raw_p={row['raw_p_count']:>2}  "
                f"fdr={row['fdr_count']:>2}  "
                f"-> {row['suggested_operator_decision']}"
            )
            if row.get("missing_coverage_note"):
                lines.append(
                    f"      coverage_note: {row['missing_coverage_note']}"
                )
            lines.append(f"      reason: {row['decision_reason']}")
    if envelope.get("warnings"):
        lines.append("")
        lines.append("Warnings:")
        for w in envelope["warnings"]:
            lines.append(f"  - {w}")
    if envelope.get("errors"):
        lines.append("")
        lines.append("Errors:")
        for e in envelope["errors"]:
            lines.append(f"  - {e}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only operator inspection table for the manual "
            "five-event validation smoke.  Re-shapes the smoke's "
            "per-(event, horizon) records into per-candidate keep / "
            "revise / reject / coverage rows.  Does not write to the "
            "DB, does not import any paid provider or LLM seam, and "
            "does not merge into the main cohort."
        ),
    )
    parser.add_argument(
        "--input-csv", dest="input_csv", default=None,
        help=(
            "Path to the operator-curated batch CSV.  Defaults to "
            "the smoke's default ('examples/manual_five_event_"
            "expansion_batch.csv').  Read-only."
        ),
    )
    parser.add_argument(
        "--horizons", dest="horizons", default=None,
        help=(
            "Comma-separated forward horizons (days).  Defaults to "
            "the smoke's default (1, 5, 20)."
        ),
    )
    parser.add_argument(
        "--alpha", dest="alpha", type=float, default=None,
        help=(
            "Significance alpha forwarded to the smoke's BH "
            "adjustment.  Defaults to the canonical alpha."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def _parse_horizons(spec: str | None) -> tuple[int, ...] | None:
    if not spec:
        return None
    out: list[int] = []
    for token in spec.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.append(int(token))
        except ValueError as exc:
            raise SystemExit(
                f"invalid --horizons value {token!r}: {exc}"
            ) from exc
    return tuple(out) if out else None


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    envelope = run_manual_five_event_inspection_table(
        input_csv=args.input_csv,
        horizons=_parse_horizons(args.horizons),
        alpha=args.alpha,
    )
    if args.json:
        print(_render_json(envelope), file=output)
    else:
        print(_render_text(envelope), file=output)
    return 0 if envelope.get("ok") else 1


__all__: tuple[str, ...] = (
    "build_inspection_table",
    "run_manual_five_event_inspection_table",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
