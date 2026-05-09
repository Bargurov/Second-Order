#!/usr/bin/env python3
"""Read-only validation salvage priority report.

Answers the operator question, "what is the fastest path from zero
clean fully-ready events to a credible cohort?"  Combines five
upstream readiness reports into a single salvage payload that ranks
the candidate backfill / review paths by their estimated unlock yield.

Five candidate groups are surfaced, in this stable preference order:

  1. ``price_cache_forward_20d``
        Events whose 20-day forward price-cache window is missing.
        Mechanical fix: backfill the price cache for the listed
        primary tickers — no human judgement required.
  2. ``estimation_window_gap``
        Events whose pre-event estimation window has fewer than the
        required cached days.  Mechanical fix: backfill the price
        cache further into the past for the listed tickers.
  3. ``missing_benchmark_proxy``
        Events whose SPY benchmark is missing from the cache for
        the 20-day forward window.  Mechanical fix: backfill SPY.
  4. ``missing_market_tickers``
        Events whose ``market_tickers`` JSON column is empty / null
        / unparseable.  Manual review required: a human operator
        must look at the headline and choose the relevant symbols
        — this report does not propose tickers.
  5. ``contaminated_fully_ready_manual_review``
        Fully-ready events that the topical-contamination report
        flagged as suspicious.  Manual review required: a human
        operator must confirm or correct the primary-ticker
        assignment before the event can join an FDR-controlled
        aggregate claim — this report does not propose replacement
        tickers.

``top_salvage_path`` is the group_key with the largest
``estimated_events_unlocked`` count; ties resolve via the stable
preference order above (mechanical price-cache backfill is preferred
over human review because it is faster and lower-judgement).

``manual_review_required`` is ``True`` iff the
``contaminated_fully_ready_manual_review`` group carries any events;
the contaminated path is the one that always blocks an aggregate
claim until a human signs off on the primary-ticker assignment.

Output contract::

    {
      "ok":                              bool,
      "current_clean_fully_ready_count": int,
      "target_clean_count":              int,
      "top_salvage_path":                str | None,
      "candidate_groups": {                  # one bucket per group_key
        "price_cache_forward_20d": {
          "blocker_count":             int,
          "estimated_events_unlocked": int,
          "candidates": [                    # capped at --limit, asc id
            {"event_id":       int,
             "event_date":     str | None,
             "primary_ticker": str | None,
             "details":        dict | None},
            ...
          ],
        },
        "estimation_window_gap":                  {...},
        "missing_benchmark_proxy":                {...},
        "missing_market_tickers":                 {...},
        "contaminated_fully_ready_manual_review": {...},
      },
      "estimated_events_unlocked": {
        "price_cache_forward_20d":                int,
        "estimation_window_gap":                  int,
        "missing_benchmark_proxy":                int,
        "missing_market_tickers":                 int,
        "contaminated_fully_ready_manual_review": int,
      },
      "manual_review_required":  bool,
      "recommended_next_action": str,
    }

The ``estimated_events_unlocked`` numbers are upper-bound estimates,
not promises.  An event blocked by multiple readiness checks (e.g.
both ``forward_cache_20d`` and ``estimation_window_sufficient``) will
appear in more than one group's count; clearing one blocker does not
guarantee the event becomes fully-ready.  The vocabulary is
deliberately conservative — "candidate", "estimated", "manual review
required" — and the report never proposes ticker assignments,
mutates the archive, or refreshes prices.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own; every DB read flows through
  the upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; never prescribes a live cache
  refresh.

Usage::

    python scripts/validation_salvage_priority_report.py
    python scripts/validation_salvage_priority_report.py --json
    python scripts/validation_salvage_priority_report.py --json --limit 50
    python scripts/validation_salvage_priority_report.py --json --target 50
    python scripts/validation_salvage_priority_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT  = 25
_DEFAULT_TARGET = 30   # rule-of-thumb minimum for a credible cohort.


# Effectively unlimited per-event cap when delegating to upstream
# reports — we need the full row set to count correctly, not the
# upstream report's truncated sample.
_REPORT_FETCH_ALL: int = 10**12


# Stable preference order: mechanical paths first, human-review paths
# last.  Used both for layout and for tie-breaking in
# ``top_salvage_path`` selection.
_GROUP_ORDER: tuple[str, ...] = (
    "price_cache_forward_20d",
    "estimation_window_gap",
    "missing_benchmark_proxy",
    "missing_market_tickers",
    "contaminated_fully_ready_manual_review",
)


_RECOMMENDED_NO_BLOCKERS_NO_CLEAN = (
    "Archive is empty — no events to assemble a validation cohort "
    "from.  Seed events before running this report."
)
_RECOMMENDED_TARGET_REACHED = (
    "Clean fully-ready cohort already meets the target — no "
    "salvage candidates need attention to clear the credibility "
    "threshold."
)
_RECOMMENDED_MECHANICAL_PATH = (
    "Top salvage candidate group is mechanical (price-cache "
    "backfill).  Estimated events unlocked is an upper bound; "
    "events blocked by multiple checks may need additional "
    "backfill before becoming fully-ready."
)
_RECOMMENDED_MANUAL_PATH = (
    "Top salvage candidate group requires manual review by a "
    "human operator.  This report does not propose ticker "
    "assignments — estimated events unlocked is an upper bound, "
    "not a promise."
)
_RECOMMENDED_NO_PATH = (
    "No salvage candidate groups carry events — no estimated "
    "unlock path is available from this report."
)


# Groups whose blockers are mechanical (price-cache backfill).  The
# remaining groups always require manual review by a human operator.
_MECHANICAL_GROUPS: frozenset[str] = frozenset({
    "price_cache_forward_20d",
    "estimation_window_gap",
    "missing_benchmark_proxy",
})


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly with
# synthetic payloads.  The lazy imports resolve only on the un-patched
# path so unit tests can swap these seams without paying the upstream
# import cost.
# ---------------------------------------------------------------------------


def _run_clean_cohort_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.clean_validation_cohort_report import summarize_clean_cohort

    return summarize_clean_cohort(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_blocker_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_blocker_report import summarize_blockers

    return summarize_blockers(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_forward_cache_gap_export(*, db_path: str | None) -> dict[str, Any]:
    """Wrap the export script's pure helpers into a dict payload.

    The export module exposes ``_load_export_rows`` +
    ``_filter_to_missing_20d`` rather than a public summarize
    function; the wrapper assembles the same envelope shape its
    JSON renderer would produce so tests can patch this seam with a
    ``{ok, count, rows}`` payload uniformly.
    """
    from scripts.stat_validation_forward_cache_gap_export import (
        _load_export_rows, _filter_to_missing_20d,
    )

    raw_rows = _load_export_rows(db_path=db_path)
    rows     = _filter_to_missing_20d(raw_rows)
    return {"ok": True, "count": len(rows), "rows": rows}


def _run_missing_tickers_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_missing_tickers_report import (
        summarize_missing_tickers,
    )

    return summarize_missing_tickers(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_estimation_gap_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_estimation_gap_report import (
        summarize_estimation_gaps,
    )

    return summarize_estimation_gaps(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute over the five upstream payloads
# ---------------------------------------------------------------------------


def summarize_salvage_priority(
    *,
    db_path: str | None = None,
    limit:   int = _DEFAULT_LIMIT,
    target:  int = _DEFAULT_TARGET,
) -> dict[str, Any]:
    """Combine the five upstream reports into the salvage priority
    payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    clean_cohort     = _safe_dict(_run_clean_cohort_report(db_path=db_path))
    blockers_payload = _safe_dict(_run_blocker_report(db_path=db_path))
    forward_export   = _safe_dict(_run_forward_cache_gap_export(db_path=db_path))
    missing_tickers  = _safe_dict(_run_missing_tickers_report(db_path=db_path))
    estimation_gap   = _safe_dict(_run_estimation_gap_report(db_path=db_path))

    current_clean = _safe_int(
        clean_cohort.get("clean_fully_ready_count"))
    contaminated_count = _safe_int(
        clean_cohort.get("contaminated_fully_ready_count"))

    # ---- Group: price_cache_forward_20d --------------------------------
    rows = forward_export.get("rows") or []
    if not isinstance(rows, list):
        rows = []
    h20_rows = [
        r for r in rows
        if isinstance(r, dict) and _safe_int(r.get("horizon")) == 20
    ]
    fc20_candidates = sorted(
        h20_rows,
        key=lambda r: _safe_int(r.get("event_id")),
    )
    fc20_entries = [
        _candidate_entry(
            r,
            details_keys=("horizon", "target_date", "blocker_reason",
                          "benchmark"),
        )
        for r in fc20_candidates
    ]

    # ---- Group: estimation_window_gap ----------------------------------
    est_events = estimation_gap.get("events") or []
    if not isinstance(est_events, list):
        est_events = []
    est_sorted = sorted(
        (e for e in est_events
         if isinstance(e, dict) and isinstance(e.get("event_id"), int)),
        key=lambda e: int(e["event_id"]),
    )
    est_entries = [
        _candidate_entry(
            e,
            details_keys=("missing_days", "pre_event_cached_days",
                          "required_days"),
        )
        for e in est_sorted
    ]
    est_count = _safe_int(estimation_gap.get("events_with_gap")) \
        if estimation_gap.get("events_with_gap") is not None \
        else len(est_sorted)

    # ---- Group: missing_benchmark_proxy --------------------------------
    bench_bucket = (blockers_payload.get("blockers") or {}).get(
        "missing_benchmark_proxy") or {}
    bench_examples = bench_bucket.get("examples") or []
    if not isinstance(bench_examples, list):
        bench_examples = []
    bench_sorted = sorted(
        (b for b in bench_examples
         if isinstance(b, dict) and isinstance(b.get("event_id"), int)),
        key=lambda b: int(b["event_id"]),
    )
    bench_entries = [
        _candidate_entry(b, details_keys=())
        for b in bench_sorted
    ]
    bench_count = _safe_int(bench_bucket.get("count"))

    # ---- Group: missing_market_tickers ---------------------------------
    mt_events = missing_tickers.get("events") or []
    if not isinstance(mt_events, list):
        mt_events = []
    mt_sorted = sorted(
        (e for e in mt_events
         if isinstance(e, dict) and isinstance(e.get("event_id"), int)),
        key=lambda e: int(e["event_id"]),
    )
    mt_entries = [
        _candidate_entry(
            e,
            details_keys=("headline", "stage", "persistence", "confidence"),
        )
        for e in mt_sorted
    ]
    mt_count = _safe_int(missing_tickers.get("events_missing_market_tickers"))

    # ---- Group: contaminated_fully_ready_manual_review -----------------
    excluded = clean_cohort.get("excluded_fully_ready_examples") or []
    if not isinstance(excluded, list):
        excluded = []
    contam_sorted = sorted(
        (e for e in excluded
         if isinstance(e, dict) and isinstance(e.get("event_id"), int)),
        key=lambda e: int(e["event_id"]),
    )
    contam_entries = [
        _candidate_entry(
            e,
            details_keys=("headline", "mechanism_family", "flags"),
        )
        for e in contam_sorted
    ]

    # ---- Assemble candidate_groups -------------------------------------
    raw_groups: dict[str, tuple[int, list[dict[str, Any]]]] = {
        "price_cache_forward_20d":
            (len(fc20_candidates), fc20_entries),
        "estimation_window_gap":
            (est_count, est_entries),
        "missing_benchmark_proxy":
            (bench_count, bench_entries),
        "missing_market_tickers":
            (mt_count, mt_entries),
        "contaminated_fully_ready_manual_review":
            (contaminated_count, contam_entries),
    }

    candidate_groups: dict[str, dict[str, Any]] = {}
    estimated_unlocked: dict[str, int] = {}
    for key in _GROUP_ORDER:
        count, entries = raw_groups[key]
        candidate_groups[key] = {
            "blocker_count":             count,
            "estimated_events_unlocked": count,
            "candidates":                entries[:capped_limit],
        }
        estimated_unlocked[key] = count

    # ---- top_salvage_path ----------------------------------------------
    top_path = _pick_top_path(estimated_unlocked)

    manual_review_required = contaminated_count > 0

    return {
        "ok":                              True,
        "current_clean_fully_ready_count": current_clean,
        "target_clean_count":              max(int(target), 0),
        "top_salvage_path":                top_path,
        "candidate_groups":                candidate_groups,
        "estimated_events_unlocked":       estimated_unlocked,
        "manual_review_required":          manual_review_required,
        "recommended_next_action":
            _recommend(
                current_clean=current_clean, target=int(target),
                top_path=top_path,
                clean_cohort_payload=clean_cohort,
                estimated_unlocked=estimated_unlocked,
            ),
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _candidate_entry(
    entry: dict[str, Any],
    *,
    details_keys: Sequence[str],
) -> dict[str, Any]:
    """Project an upstream entry down to the salvage report's minimal
    candidate shape — ``{event_id, event_date, primary_ticker, details}``.

    ``details_keys`` selects which group-specific fields to forward
    under ``details``; missing keys are skipped silently.  ``details``
    is ``None`` when no group-specific data is available, so callers
    can rely on the field always being present.
    """
    details: dict[str, Any] = {}
    for k in details_keys:
        if k in entry:
            details[k] = entry.get(k)
    return {
        "event_id":       entry.get("event_id"),
        "event_date":     entry.get("event_date"),
        "primary_ticker": entry.get("primary_ticker"),
        "details":        details if details else None,
    }


def _pick_top_path(
    estimated_unlocked: dict[str, int],
) -> str | None:
    """Return the group_key with the largest unlock count; ties
    resolve via the stable ``_GROUP_ORDER`` (mechanical paths first).

    Returns ``None`` when every group's unlock count is zero — there
    is no salvage path available from the report's perspective.
    """
    best_key: str | None = None
    best_count = 0
    for key in _GROUP_ORDER:
        count = int(estimated_unlocked.get(key, 0))
        if count > best_count:
            best_count = count
            best_key = key
    return best_key


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _recommend(
    *,
    current_clean: int, target: int,
    top_path: str | None,
    clean_cohort_payload: dict[str, Any],
    estimated_unlocked: dict[str, int],
) -> str:
    total_events = _safe_int(clean_cohort_payload.get("total_events"))
    fully_ready  = _safe_int(clean_cohort_payload.get("fully_ready_count"))
    if total_events <= 0 and fully_ready <= 0 and not any(
        v > 0 for v in estimated_unlocked.values()
    ):
        return _RECOMMENDED_NO_BLOCKERS_NO_CLEAN

    if current_clean >= target > 0:
        return _RECOMMENDED_TARGET_REACHED

    if top_path is None:
        return _RECOMMENDED_NO_PATH

    if top_path in _MECHANICAL_GROUPS:
        return _RECOMMENDED_MECHANICAL_PATH
    return _RECOMMENDED_MANUAL_PATH


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Validation salvage priority report", ""]
    lines.append(
        f"Current clean fully-ready cohort:        "
        f"{report['current_clean_fully_ready_count']}"
    )
    lines.append(
        f"Target credible-cohort threshold:        "
        f"{report['target_clean_count']}"
    )
    lines.append(
        f"Top salvage path:                        "
        f"{report['top_salvage_path'] or '-'}"
    )
    lines.append(
        f"Manual review required:                  "
        f"{report['manual_review_required']}"
    )
    lines.append("")
    lines.append("Candidate groups:")
    groups = report.get("candidate_groups") or {}
    for key in _GROUP_ORDER:
        bucket = groups.get(key) or {}
        lines.append(
            f"  {key}: blocker_count={bucket.get('blocker_count', 0)}"
            f"  estimated_events_unlocked="
            f"{bucket.get('estimated_events_unlocked', 0)}"
        )
        candidates = bucket.get("candidates") or []
        if candidates:
            for c in candidates:
                lines.append(
                    f"      id={c.get('event_id')} "
                    f"date={c.get('event_date') or '-'} "
                    f"ticker={c.get('primary_ticker') or '-'}"
                )
        else:
            lines.append("      (no candidates)")
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
            "Read-only validation salvage priority report.  Combines "
            "the readiness, blocker, contamination, forward-cache-gap, "
            "missing-tickers, and estimation-gap reports into a "
            "single salvage payload that ranks candidate backfill / "
            "review paths by their estimated unlock yield.  Read-only: "
            "never assigns tickers, never deletes or edits archive "
            "rows, no provider, no LLM, no FastAPI surface."
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
            f"Cap each group's candidates list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every event in the archive."
        ),
    )
    parser.add_argument(
        "--target",
        type=int,
        default=_DEFAULT_TARGET,
        help=(
            f"Target clean fully-ready cohort size for a credible "
            f"FDR-controlled aggregate claim (default "
            f"{_DEFAULT_TARGET})."
        ),
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

    report = summarize_salvage_priority(
        db_path=args.db_path,
        limit=args.limit,
        target=args.target,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
