#!/usr/bin/env python3
"""Read-only maturity-aware benchmark blocker report.

Answers the operator question, "of the events flagged as
``missing_benchmark_proxy`` blockers, which can be cleared by an
SPY backfill *now* and which are simply too far into the future for
the data to exist yet?"

The plain blocker counts conflate two different conditions:

  * **actionable_now** — the 20-business-day forward target date
    has already passed (``target_date <= latest_available_market_date``).
    Data exists; the cache just doesn't have it.  Backfill clears
    the blocker.
  * **too_early_future_horizon** — the target date is still in the
    future (``target_date > latest_available_market_date``).  The
    data does not exist yet, anywhere; no fetch can clear the
    blocker.  These events must wait for the market to mature.
  * **already_covered_or_inconsistent** — degraded path.  The
    blocker row has no parseable ``benchmark_target_20d_date``
    (i.e., ``event_date`` is missing) so the maturity check cannot
    classify it.  Surface as a separate bucket so it does not
    silently inflate either of the other two counts.

``actionable_required_start_date`` and
``actionable_required_end_date`` describe the SPY date range that
would clear the **actionable_now** bucket only — the future-horizon
blockers do not contribute, since fetching them is impossible:

  * end   = max ``benchmark_target_20d_date`` over actionable rows
  * start = ``current_cache_max_date + 1 calendar day`` if the
            cache exists; else min ``benchmark_target_20d_date`` over
            actionable rows
  * both ``None`` if the actionable bucket is empty

Output contract::

    {
      "total_blocked":                    int,
      "actionable_now_count":             int,
      "too_early_future_horizon_count":   int,
      "latest_available_market_date":     str,    # ISO YYYY-MM-DD
      "actionable_required_start_date":   str | None,
      "actionable_required_end_date":     str | None,
      "examples": [                                 # capped at --limit, asc id
        {"event_id":                  int,
         "event_date":                str | None,
         "primary_ticker":            str | None,
         "benchmark_target_20d_date": str | None,
         "maturity_bucket":
             "actionable_now" |
             "too_early_future_horizon" |
             "already_covered_or_inconsistent"},
        ...
      ],
      "recommended_next_action":          str,
    }

``latest_available_market_date`` defaults to today's local date.
The operator may override via ``--as-of-date YYYY-MM-DD`` — useful
for back-testing the report against a historical archive snapshot.
A malformed ``--as-of-date`` falls back to today's date so the
report still produces a well-formed payload.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own; every DB read flows through
  the upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; never refreshes prices; never
  fetches data.
* Conservative vocabulary only — recommendation never claims
  guarantees, never proposes destructive operations.

Usage::

    python scripts/benchmark_blocker_maturity_report.py
    python scripts/benchmark_blocker_maturity_report.py --json
    python scripts/benchmark_blocker_maturity_report.py --json --limit 50
    python scripts/benchmark_blocker_maturity_report.py --json \\
        --as-of-date 2026-05-08
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 25

# Effectively unlimited per-event cap when delegating to upstream
# reports — we need every blocked row to bucket the maturity counts
# correctly, not the upstream report's truncated sample.
_REPORT_FETCH_ALL: int = 10**12


_BUCKET_ACTIONABLE   = "actionable_now"
_BUCKET_TOO_EARLY    = "too_early_future_horizon"
_BUCKET_INCONSISTENT = "already_covered_or_inconsistent"


_RECOMMENDED_NO_BLOCKERS = (
    "No missing_benchmark_proxy blockers detected — no candidate "
    "SPY backfill action appears necessary."
)
_RECOMMENDED_ALL_FUTURE = (
    "Every blocker appears to be on a future horizon "
    "(target_date > latest_available_market_date).  No SPY backfill "
    "can clear these blockers today; the candidate next step is to "
    "wait for the market to mature past the latest target_date."
)
_RECOMMENDED_ACTIONABLE_ONLY = (
    "All {n} blockers appear actionable_now.  Candidate SPY backfill "
    "range: {start} through {end} (estimated upper bound; some rows "
    "may already be covered by a partial cache)."
)
_RECOMMENDED_MIXED = (
    "{a} of {t} blockers appear actionable_now (candidate SPY "
    "backfill range: {start} through {end}); the remaining {f} are "
    "on a future horizon and may need to wait for the market to "
    "mature."
)
_RECOMMENDED_INCONSISTENT_ONLY = (
    "Every blocker has an unparseable target date — maturity cannot "
    "be classified.  Candidate next step is to confirm the upstream "
    "events carry parseable event_date values."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly.
# ---------------------------------------------------------------------------


def _run_preflight(*, db_path: str | None) -> dict[str, Any]:
    from scripts.benchmark_cache_backfill_preflight import (
        summarize_backfill_preflight,
    )

    return summarize_backfill_preflight(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_benchmark_gap_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_benchmark_gap_report import (
        summarize_benchmark_gaps,
    )

    return summarize_benchmark_gaps(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_blocker_maturity(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    as_of_date: str | None = None,
) -> dict[str, Any]:
    """Return the maturity-aware blocker payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)
    as_of_iso, as_of_d = _resolve_as_of(as_of_date)

    preflight = _safe_dict(_run_preflight(db_path=db_path))
    gap_report = _safe_dict(_run_benchmark_gap_report(db_path=db_path))

    cache_max = preflight.get("current_cache_max_date") \
        if isinstance(preflight.get("current_cache_max_date"), str) \
        else None

    raw_rows = gap_report.get("rows") or []
    if not isinstance(raw_rows, list):
        raw_rows = []

    actionable: list[dict[str, Any]] = []
    too_early:  list[dict[str, Any]] = []
    inconsistent: list[dict[str, Any]] = []

    for r in raw_rows:
        if not isinstance(r, dict):
            continue
        target_iso = r.get("benchmark_target_20d_date")
        target_d = _parse_iso(target_iso)
        if target_d is None:
            inconsistent.append(r)
        elif target_d <= as_of_d:
            actionable.append(r)
        else:
            too_early.append(r)

    total_blocked = len(actionable) + len(too_early) + len(inconsistent)

    actionable_targets = sorted(
        d for d in (
            r.get("benchmark_target_20d_date") for r in actionable
        )
        if isinstance(d, str) and d
    )
    actionable_end = actionable_targets[-1] if actionable_targets else None
    actionable_start = _compute_actionable_start(
        cache_max=cache_max, actionable_targets=actionable_targets,
    )

    examples = _build_examples(
        actionable=actionable, too_early=too_early,
        inconsistent=inconsistent, capped_limit=capped_limit,
    )

    recommended = _recommend(
        actionable_count=len(actionable),
        too_early_count=len(too_early),
        inconsistent_count=len(inconsistent),
        actionable_start=actionable_start,
        actionable_end=actionable_end,
    )

    return {
        "total_blocked":                  total_blocked,
        "actionable_now_count":            len(actionable),
        "too_early_future_horizon_count":  len(too_early),
        "latest_available_market_date":    as_of_iso,
        "actionable_required_start_date":  actionable_start,
        "actionable_required_end_date":    actionable_end,
        "examples":                        examples,
        "recommended_next_action":         recommended,
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_as_of(as_of: str | None) -> tuple[str, date]:
    """Return ``(iso_string, date)`` for the as-of marker.

    A missing or unparseable ``as_of`` falls back to today's local
    date so the report always produces a well-formed payload.  The
    fallback is silent — operators who care can pass an explicit
    ``--as-of-date`` and verify the value surfaces in
    ``latest_available_market_date``.
    """
    if isinstance(as_of, str) and as_of:
        d = _parse_iso(as_of)
        if d is not None:
            return as_of, d
    today = date.today()
    return today.isoformat(), today


def _parse_iso(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _compute_actionable_start(
    *, cache_max: str | None, actionable_targets: Sequence[str],
) -> str | None:
    if not actionable_targets:
        return None
    if cache_max:
        d = _parse_iso(cache_max)
        if d is not None:
            return (d + timedelta(days=1)).isoformat()
    return actionable_targets[0]


def _build_examples(
    *,
    actionable: Sequence[dict[str, Any]],
    too_early:  Sequence[dict[str, Any]],
    inconsistent: Sequence[dict[str, Any]],
    capped_limit: int,
) -> list[dict[str, Any]]:
    """Project blocker rows down to the maturity-tagged example shape
    and return a sorted, capped sample.

    Examples are sorted by ``event_id`` ascending across ALL three
    buckets so the surfaced sample is deterministic and an operator
    can scan for both maturity and id without further sorting.
    """
    tagged: list[dict[str, Any]] = []
    for r in actionable:
        tagged.append(_example(r, _BUCKET_ACTIONABLE))
    for r in too_early:
        tagged.append(_example(r, _BUCKET_TOO_EARLY))
    for r in inconsistent:
        tagged.append(_example(r, _BUCKET_INCONSISTENT))
    tagged_with_id = [
        e for e in tagged if isinstance(e.get("event_id"), int)
    ]
    tagged_with_id.sort(key=lambda e: int(e["event_id"]))
    return tagged_with_id[:capped_limit]


def _example(row: dict[str, Any], bucket: str) -> dict[str, Any]:
    return {
        "event_id":                  row.get("event_id"),
        "event_date":                row.get("event_date"),
        "primary_ticker":            row.get("primary_ticker"),
        "benchmark_target_20d_date": row.get("benchmark_target_20d_date"),
        "maturity_bucket":           bucket,
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recommend(
    *,
    actionable_count: int,
    too_early_count: int,
    inconsistent_count: int,
    actionable_start: str | None,
    actionable_end: str | None,
) -> str:
    total = actionable_count + too_early_count + inconsistent_count
    if total <= 0:
        return _RECOMMENDED_NO_BLOCKERS
    if actionable_count == 0 and too_early_count > 0:
        return _RECOMMENDED_ALL_FUTURE
    if actionable_count == 0 and inconsistent_count > 0:
        return _RECOMMENDED_INCONSISTENT_ONLY
    # actionable_count > 0 from here
    if too_early_count == 0 and inconsistent_count == 0:
        return _RECOMMENDED_ACTIONABLE_ONLY.format(
            n=actionable_count,
            start=actionable_start or "-",
            end=actionable_end or "-",
        )
    return _RECOMMENDED_MIXED.format(
        a=actionable_count,
        t=total,
        f=too_early_count,
        start=actionable_start or "-",
        end=actionable_end or "-",
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Benchmark blocker maturity report", ""]
    lines.append(
        f"Latest available market date:        "
        f"{report['latest_available_market_date']}"
    )
    lines.append(
        f"Total blocked:                       "
        f"{report['total_blocked']}"
    )
    lines.append(
        f"  actionable_now:                    "
        f"{report['actionable_now_count']}"
    )
    lines.append(
        f"  too_early_future_horizon:          "
        f"{report['too_early_future_horizon_count']}"
    )
    lines.append(
        f"Actionable required start date:      "
        f"{report['actionable_required_start_date'] or '-'}"
    )
    lines.append(
        f"Actionable required end date:        "
        f"{report['actionable_required_end_date'] or '-'}"
    )
    examples = report.get("examples") or []
    lines.append("")
    lines.append(f"Examples ({len(examples)}):")
    if examples:
        for e in examples:
            lines.append(
                f"  id={e.get('event_id')} "
                f"date={e.get('event_date') or '-'} "
                f"ticker={e.get('primary_ticker') or '-'} "
                f"target_20d={e.get('benchmark_target_20d_date') or '-'} "
                f"bucket={e.get('maturity_bucket')}"
            )
    else:
        lines.append("  -")
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
            "Read-only maturity-aware benchmark blocker report.  "
            "Splits missing_benchmark_proxy blockers into "
            "actionable_now (target_date <= latest_available_market_date), "
            "too_early_future_horizon (target_date > latest_available_market_date), "
            "and already_covered_or_inconsistent (target_date "
            "unparseable).  Read-only: no INSERT/UPDATE/DELETE, no "
            "provider, no LLM, no FastAPI surface, no fetch."
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
            f"Cap the surfaced ``examples`` list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect every "
            f"blocked event in the archive."
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
    parser.add_argument(
        "--as-of-date",
        dest="as_of_date",
        default=None,
        help=(
            "Optional ISO date (YYYY-MM-DD) used as the boundary "
            "between actionable_now and too_early_future_horizon.  "
            "Defaults to today's local date.  A malformed value "
            "falls back to today's date silently."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_blocker_maturity(
        db_path=args.db_path,
        limit=args.limit,
        as_of_date=args.as_of_date,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
