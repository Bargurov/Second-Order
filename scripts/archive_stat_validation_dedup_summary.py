#!/usr/bin/env python3
"""Read-only deduped validation summary for the fully-ready cohort.

Walks the records produced by
:mod:`scripts.archive_stat_validation_run` and collapses duplicate
``(event_date, primary_ticker, horizon)`` records so the operator can
see how much of the surfaced FDR-controlled evidence comes from
independent event-windows versus arithmetic duplicates that share the
same price-window inputs.

The duplicate problem
---------------------
The archive can carry two or more events on the same ``event_date``
that resolve to the same ``primary_ticker``.  When that happens, the
event-study pipeline computes its abnormal-return / SAR over the
identical price window for both events at every horizon, and BH-FDR
sees the duplicates as independent rejections — inflating the
multiplicity ``m`` in ``q = (m / k) * p`` without adding any
statistical power.  The cohort q-values reported by the runner are
therefore *conservative* relative to a deduped cohort: removing the
duplicates can only tighten q (a record's deduped q is <= its raw q).

What this report surfaces
-------------------------
* the raw record count from the runner's payload;
* the *effective* unique record count after the
  ``(event_date, primary_ticker, horizon)`` collapse;
* per-horizon raw / unique counts so the operator can see which
  horizon carries the duplicate weight;
* a ``qvalue_change`` block: how many records cleared the alpha
  threshold under the raw cohort vs the deduped cohort, and how many
  unique groups gain significance once duplicates are removed;
* ``top_abs_sar``: the deduped records sorted by ``|sar|`` descending
  (capped at ``--limit``), each annotated with both ``raw_fdr_q`` and
  ``deduped_fdr_q`` so the operator can see at a glance whether the
  multiplicity inflation is changing the verdict.

Output contract::

    {
      "ok":                              bool,
      "records_count":                   int,
      "effective_unique_records_count":  int,
      "duplicate_records_count":         int,
      "duplicate_groups_count":          int,
      "by_horizon": {                    # keys are str(horizon)
        "1":  {
          "records_count":                int,
          "effective_unique_records_count": int,
        },
        "5":  {...},
        "20": {...},
      },
      "qvalue_change": {
        "raw_significant_records":            int,
        "raw_significant_unique_records":     int,
        "deduped_significant_unique_records": int,
        "groups_gaining_significance":        int,
        "groups_losing_significance":         int,
        "any_change":                         bool,
      },
      "top_abs_sar": [                   # capped at --limit
        {
          "event_id":      int,
          "event_date":    str | None,
          "ticker":        str | None,
          "horizon":       int,
          "headline":      str | None,
          "sar":           float | None,
          "abs_sar":       float | None,
          "p_value":       float | None,
          "raw_fdr_q":     float | None,
          "deduped_fdr_q": float | None,
        },
        ...
      ],
      "config": {
        "alpha": float,
        "limit": int,
      },
      "errors":             list[str],
      "recommended_next_action": str,
    }

Read-only by construction
-------------------------
* Issues only ``SELECT`` statements; never INSERT / UPDATE / DELETE;
  never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM seam, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; this is an analysis tool only.

Usage::

    python scripts/archive_stat_validation_dedup_summary.py
    python scripts/archive_stat_validation_dedup_summary.py --json
    python scripts/archive_stat_validation_dedup_summary.py --json --limit 50
    python scripts/archive_stat_validation_dedup_summary.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int   = 25
_DEFAULT_ALPHA: float = 0.05

# Effectively unlimited per-record cap when delegating to the runner —
# the dedup summary needs every record, not the runner's truncated
# examples list.
_RUNNER_FETCH_ALL: int = 10**12


_RECOMMENDED_NO_RECORDS = (
    "The archive validation runner produced no records to dedupe.  "
    "Refresh the price cache and re-run the validation pipeline before "
    "interpreting FDR-controlled evidence."
)
_RECOMMENDED_NO_DUPLICATES = (
    "Every fully-ready record is unique by (event_date, primary_ticker, "
    "horizon).  The raw FDR cohort already reflects the effective "
    "sample size; no q-value inflation to correct."
)
_RECOMMENDED_DUPLICATES_NO_FLIP = (
    "Duplicate (event_date, primary_ticker, horizon) records are "
    "inflating the BH-FDR multiplicity, but no record's significance "
    "verdict changes after deduplication.  Treat the raw cohort q-values "
    "as conservative; the underlying conclusion is unchanged."
)
_RECOMMENDED_DUPLICATES_WITH_FLIP = (
    "Duplicate (event_date, primary_ticker, horizon) records are "
    "inflating the BH-FDR multiplicity and the significance verdict "
    "would change for at least one unique group under deduplication.  "
    "Treat per-group claims with caution and re-run the validation "
    "pipeline against a deduplicated cohort before relying on the "
    "FDR-controlled evidence."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly with
# synthetic fixtures.  The lazy imports resolve only on the un-patched
# path so unit tests can swap these seams without paying the upstream
# import cost.
# ---------------------------------------------------------------------------


def _run_validation(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the archive validation runner with an effectively
    unlimited per-record cap and return the parsed payload.

    Tests patch this attribute directly, so the import only resolves
    on the un-patched path.
    """
    from scripts.archive_stat_validation_run import run_archive_stat_validation

    return run_archive_stat_validation(
        db_path=db_path, limit=_RUNNER_FETCH_ALL,
    )


def _load_event_dates(
    *, db_path: str | None, event_ids: Sequence[int],
) -> dict[int, str]:
    """Return ``{event_id: event_date_iso}`` for the given ids.

    Read-only — issues a single ``SELECT`` and tolerates a missing or
    unreadable DB by returning an empty dict.  Tests patch this
    attribute directly with a synthetic mapping.
    """
    if not event_ids:
        return {}
    path = _resolve_db_path(db_path)
    if path is None:
        return {}

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return {}

    out: dict[int, str] = {}
    try:
        try:
            placeholders = ",".join("?" * len(event_ids))
            rows = conn.execute(
                f"SELECT id, event_date FROM events "
                f"WHERE id IN ({placeholders})",
                list(event_ids),
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    for raw_id, raw_date in rows:
        try:
            ev_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if isinstance(raw_date, str) and raw_date:
            out[ev_id] = raw_date
    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:  # noqa: BLE001 — best-effort default
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _normalise_ticker(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    out = value.strip().upper()
    return out or None


def _coerce_finite_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    out = float(value)
    if not math.isfinite(out):
        return None
    return out


def _dedup_key(
    record: dict[str, Any], event_dates: dict[int, str],
) -> tuple[str, str, int] | None:
    """Return the ``(event_date, ticker_upper, horizon)`` dedup key for
    a record, or ``None`` when any component is missing.

    Records with missing components are excluded from dedup grouping —
    they cannot be collapsed against anything else, but they are still
    counted as raw records and kept verbatim in the unique cohort.
    """
    ev_id = record.get("event_id")
    horizon = record.get("horizon")
    ticker_upper = _normalise_ticker(record.get("ticker"))
    if not isinstance(ev_id, int):
        return None
    if not isinstance(horizon, int):
        return None
    if ticker_upper is None:
        return None
    event_date = event_dates.get(ev_id)
    if not isinstance(event_date, str) or not event_date:
        return None
    return (event_date, ticker_upper, int(horizon))


def _is_significant(q: Any, alpha: float) -> bool:
    qf = _coerce_finite_float(q)
    if qf is None:
        return False
    return qf <= alpha


# ---------------------------------------------------------------------------
# Pure compute over the runner payload + event-date map
# ---------------------------------------------------------------------------


def summarize_dedup(
    *,
    db_path: str | None = None,
    limit:   int        = _DEFAULT_LIMIT,
    alpha:   float      = _DEFAULT_ALPHA,
) -> dict[str, Any]:
    """Build the deduped validation summary.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)
    alpha_f = float(alpha)

    payload = _run_validation(db_path=db_path)
    if not isinstance(payload, dict):
        payload = {}
    raw_records = payload.get("examples") or []
    if not isinstance(raw_records, list):
        raw_records = []

    upstream_errors = payload.get("errors") or []
    if not isinstance(upstream_errors, list):
        upstream_errors = []
    errors = [str(e) for e in upstream_errors]

    records_count = len(raw_records)

    # ---- map event_id -> event_date -------------------------------------
    event_ids = [
        r["event_id"] for r in raw_records
        if isinstance(r, dict) and isinstance(r.get("event_id"), int)
    ]
    try:
        event_dates = _load_event_dates(
            db_path=db_path, event_ids=event_ids,
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"_load_event_dates failure: {type(exc).__name__}: {exc}"
        )
        event_dates = {}
    if not isinstance(event_dates, dict):
        event_dates = {}

    # ---- group records by dedup key -------------------------------------
    groups: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    keyless: list[dict[str, Any]] = []
    for r in raw_records:
        if not isinstance(r, dict):
            continue
        key = _dedup_key(r, event_dates)
        if key is None:
            keyless.append(r)
        else:
            groups[key].append(r)

    # ---- canonical (smallest event_id) per group ------------------------
    canonical_records: list[dict[str, Any]] = []
    canonical_dedup_keys: list[tuple[str, str, int] | None] = []
    duplicate_groups_count = 0
    for key, members in groups.items():
        if len(members) >= 2:
            duplicate_groups_count += 1
        canonical = min(
            members,
            key=lambda m: (
                m["event_id"] if isinstance(m.get("event_id"), int) else 0,
            ),
        )
        canonical_records.append(canonical)
        canonical_dedup_keys.append(key)
    # Records without a dedup key are kept as-is (they cannot be
    # collapsed; treating them as distinct is the only safe choice).
    for r in keyless:
        canonical_records.append(r)
        canonical_dedup_keys.append(None)

    effective_unique_records_count = len(canonical_records)
    duplicate_records_count = records_count - effective_unique_records_count

    # ---- per-horizon counts ---------------------------------------------
    by_horizon_records: dict[int, int] = defaultdict(int)
    for r in raw_records:
        if isinstance(r, dict) and isinstance(r.get("horizon"), int):
            by_horizon_records[int(r["horizon"])] += 1
    by_horizon_unique: dict[int, int] = defaultdict(int)
    for c in canonical_records:
        if isinstance(c, dict) and isinstance(c.get("horizon"), int):
            by_horizon_unique[int(c["horizon"])] += 1
    by_horizon_keys = sorted(
        set(by_horizon_records.keys()) | set(by_horizon_unique.keys())
    )
    by_horizon: dict[str, dict[str, int]] = {}
    for h in by_horizon_keys:
        by_horizon[str(h)] = {
            "records_count":                  by_horizon_records.get(h, 0),
            "effective_unique_records_count": by_horizon_unique.get(h, 0),
        }

    # ---- q-value flip detection -----------------------------------------
    # bh_adjust the canonical cohort under the same alpha; compare to
    # the raw fdr_q values that the runner already attached to each
    # record.  Records in a duplicate group share the same p-value, so
    # the canonical record carries the group's representative raw_q.
    deduped_p_values: list[Any] = [
        c.get("p_value") for c in canonical_records
    ]
    try:
        from stats.fdr import bh_adjust

        bh_result = bh_adjust(deduped_p_values, alpha=alpha_f)
        deduped_qs: list[float | None] = list(
            bh_result.get("adjusted") or [None] * len(canonical_records)
        )
    except Exception as exc:  # noqa: BLE001 — operator-visible
        errors.append(
            f"bh_adjust failure: {type(exc).__name__}: {exc}"
        )
        deduped_qs = [None] * len(canonical_records)

    raw_significant_records = sum(
        1 for r in raw_records
        if isinstance(r, dict) and _is_significant(r.get("fdr_q"), alpha_f)
    )
    raw_significant_unique_records = sum(
        1 for c in canonical_records
        if _is_significant(c.get("fdr_q"), alpha_f)
    )
    deduped_significant_unique_records = sum(
        1 for q in deduped_qs if _is_significant(q, alpha_f)
    )

    groups_gaining_significance = 0
    groups_losing_significance  = 0
    for c, deduped_q in zip(canonical_records, deduped_qs):
        raw_sig     = _is_significant(c.get("fdr_q"), alpha_f)
        deduped_sig = _is_significant(deduped_q,      alpha_f)
        if deduped_sig and not raw_sig:
            groups_gaining_significance += 1
        elif raw_sig and not deduped_sig:
            groups_losing_significance += 1

    qvalue_change = {
        "raw_significant_records":            raw_significant_records,
        "raw_significant_unique_records":     raw_significant_unique_records,
        "deduped_significant_unique_records": deduped_significant_unique_records,
        "groups_gaining_significance":        groups_gaining_significance,
        "groups_losing_significance":         groups_losing_significance,
        "any_change":                         bool(
            groups_gaining_significance or groups_losing_significance
        ),
    }

    # ---- top |SAR| ranked deduped records --------------------------------
    rankable: list[tuple[float, dict[str, Any], float | None, tuple[str, str, int] | None]] = []
    for c, deduped_q, key in zip(
        canonical_records, deduped_qs, canonical_dedup_keys,
    ):
        sar = _coerce_finite_float(c.get("sar"))
        if sar is None:
            continue
        rankable.append((abs(sar), c, deduped_q, key))
    # Sort by |SAR| desc; tie-break by event_id asc, horizon asc for
    # deterministic ordering across runs.
    rankable.sort(
        key=lambda item: (
            -item[0],
            item[1].get("event_id") if isinstance(item[1].get("event_id"), int) else 0,
            item[1].get("horizon")  if isinstance(item[1].get("horizon"),  int) else 0,
        ),
    )
    top_abs_sar: list[dict[str, Any]] = []
    for abs_sar, c, deduped_q, key in rankable[:capped_limit]:
        ev_id = c.get("event_id") if isinstance(c.get("event_id"), int) else None
        event_date = (
            event_dates.get(ev_id) if isinstance(ev_id, int) else None
        )
        if not isinstance(event_date, str) or not event_date:
            event_date = None
        top_abs_sar.append({
            "event_id":      ev_id,
            "event_date":    event_date,
            "ticker":        _normalise_ticker(c.get("ticker")),
            "horizon":       int(c["horizon"]) if isinstance(c.get("horizon"), int) else None,
            "headline":      c.get("headline") if isinstance(c.get("headline"), str) else None,
            "sar":           _coerce_finite_float(c.get("sar")),
            "abs_sar":       abs_sar,
            "p_value":       _coerce_finite_float(c.get("p_value")),
            "raw_fdr_q":     _coerce_finite_float(c.get("fdr_q")),
            "deduped_fdr_q": _coerce_finite_float(deduped_q),
        })

    return {
        "ok":                             not errors,
        "records_count":                  records_count,
        "effective_unique_records_count": effective_unique_records_count,
        "duplicate_records_count":        duplicate_records_count,
        "duplicate_groups_count":         duplicate_groups_count,
        "by_horizon":                     by_horizon,
        "qvalue_change":                  qvalue_change,
        "top_abs_sar":                    top_abs_sar,
        "config": {
            "alpha": alpha_f,
            "limit": capped_limit,
        },
        "errors":                  list(errors),
        "recommended_next_action": _recommend(
            records_count=records_count,
            duplicate_records_count=duplicate_records_count,
            any_change=qvalue_change["any_change"],
        ),
    }


def _recommend(
    *,
    records_count:           int,
    duplicate_records_count: int,
    any_change:              bool,
) -> str:
    if records_count <= 0:
        return _RECOMMENDED_NO_RECORDS
    if duplicate_records_count <= 0:
        return _RECOMMENDED_NO_DUPLICATES
    if any_change:
        return _RECOMMENDED_DUPLICATES_WITH_FLIP
    return _RECOMMENDED_DUPLICATES_NO_FLIP


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
    lines: list[str] = ["Archive validation dedup summary", ""]
    lines.append(f"ok:                             {report['ok']}")
    lines.append(f"records_count:                  {report['records_count']}")
    lines.append(f"effective_unique_records_count: {report['effective_unique_records_count']}")
    lines.append(f"duplicate_records_count:        {report['duplicate_records_count']}")
    lines.append(f"duplicate_groups_count:         {report['duplicate_groups_count']}")
    lines.append("")

    by_h = report.get("by_horizon") or {}
    if by_h:
        lines.append("Per horizon (raw vs deduped):")
        for h_key in sorted(by_h.keys(), key=lambda x: int(x)):
            block = by_h[h_key]
            lines.append(
                f"  h={h_key:>3}  records={block['records_count']:>4} "
                f"unique={block['effective_unique_records_count']:>4}"
            )
        lines.append("")

    qv = report.get("qvalue_change") or {}
    if qv:
        lines.append("Q-value change under deduplication:")
        lines.append(
            f"  raw_significant_records:           {qv.get('raw_significant_records', 0)}"
        )
        lines.append(
            f"  raw_significant_unique_records:    {qv.get('raw_significant_unique_records', 0)}"
        )
        lines.append(
            f"  deduped_significant_unique:        {qv.get('deduped_significant_unique_records', 0)}"
        )
        lines.append(
            f"  groups_gaining_significance:       {qv.get('groups_gaining_significance', 0)}"
        )
        lines.append(
            f"  groups_losing_significance:        {qv.get('groups_losing_significance', 0)}"
        )
        lines.append(
            f"  any_change:                        {qv.get('any_change', False)}"
        )
        lines.append("")

    top = report.get("top_abs_sar") or []
    lines.append(f"Top |SAR| deduped records ({len(top)}):")
    if top:
        for entry in top:
            headline = (entry.get("headline") or "").strip() or "-"
            if len(headline) > 70:
                headline = headline[:67] + "..."
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('ticker') or '-':<6} "
                f"h={entry.get('horizon')} "
                f"|SAR|={_fmt(entry.get('abs_sar'))} "
                f"SAR={_fmt(entry.get('sar'))} "
                f"p={_fmt(entry.get('p_value'))} "
                f"raw_q={_fmt(entry.get('raw_fdr_q'))} "
                f"dedup_q={_fmt(entry.get('deduped_fdr_q'))}"
            )
            lines.append(f"      headline: {headline}")
    else:
        lines.append("  -")
    lines.append("")

    errors = report.get("errors") or []
    if errors:
        lines.append(f"Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"  - {e}")
    else:
        lines.append("Errors: (none)")
    lines.append("")

    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only deduped validation summary.  Collapses duplicate "
            "(event_date, primary_ticker, horizon) records produced by "
            "scripts.archive_stat_validation_run so the operator can "
            "see the effective FDR sample size and whether any "
            "significance verdicts would change under deduplication.  "
            "Read-only: never edits the archive, no provider, no LLM, "
            "no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced top_abs_sar list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect every "
            f"record."
        ),
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=_DEFAULT_ALPHA,
        help=f"Significance threshold (default: {_DEFAULT_ALPHA}).",
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the report follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_dedup(
        db_path=args.db_path, limit=args.limit, alpha=args.alpha,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0 if report["ok"] else 1


__all__: tuple[str, ...] = (
    "summarize_dedup",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
