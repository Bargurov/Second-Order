#!/usr/bin/env python3
"""Read-only SPY benchmark-cache backfill preflight.

Answers the operator question, "what is the smallest SPY price-cache
backfill that would clear every ``missing_benchmark_proxy`` blocker?"
The preflight is a planning tool — it computes the date range to
fetch, the rough row count, and the number of provider calls the
fetch would take.  It NEVER fetches.

The preflight composes two upstream read-only reports:

  * :mod:`scripts.stat_validation_benchmark_gap_report` — supplies
    per-event 20-business-day target dates and the single global
    SPY cache max date.  Drives the date math.
  * :mod:`scripts.validation_salvage_priority_report` — supplies the
    salvage ranking ``top_salvage_path`` so the recommendation can
    qualify whether SPY backfill is the highest-yield action overall
    or whether other blocker groups dominate.

Both reports are imported through patchable module-level seams so
unit tests can drive the preflight with synthetic payloads.

Date math
---------

  * ``required_end_date`` = max ``benchmark_target_20d_date`` over
    blocked events where it is parseable.  Events with no parseable
    ``event_date`` (and therefore no ``target_20d``) are still
    counted as blockers but contribute nothing to the date math.
  * ``required_start_date``:
      * cache max non-null → ``cache_max + 1 calendar day``
        (any blocker has ``target_20d > cache_max`` by readiness
        logic, so this is always ≤ end)
      * cache max null     → min ``benchmark_target_20d_date`` over
                              blocked events where parseable
      * no parseable target → ``None`` (degraded archive — preflight
                              cannot propose a range)
  * ``estimated_rows_needed`` counts weekdays (Mon-Fri) in
    ``[start, end]`` inclusive.  SPY only has weekday rows, so the
    business-day count is the right approximation.  Returns ``0``
    when the range is empty / inverted / undefined.
  * ``provider_calls_required`` = ``0`` when there is nothing to
    fetch, else ``1``.  yfinance fetches a date range for one
    ticker in a single call.

Output contract::

    {
      "benchmark_symbol":         str,         # "SPY"
      "blocked_event_count":      int,
      "required_start_date":      str | None,  # ISO YYYY-MM-DD
      "required_end_date":        str | None,  # ISO YYYY-MM-DD
      "current_cache_max_date":   str | None,  # ISO YYYY-MM-DD
      "estimated_rows_needed":    int,         # weekdays in range
      "provider_calls_required":  int,         # 0 or 1
      "recommended_next_action":  str,
      # Optional, present iff --check-provider-availability was set:
      "provider_available":       bool,
      # Optional, capped at --limit, asc id:
      "blocked_event_examples":   [
        {"event_id": int, "event_date": str | None,
         "primary_ticker": str | None,
         "benchmark_target_20d_date": str | None},
        ...
      ],
    }

Out of scope (deliberately)
---------------------------
* Read-only.  No DB writes.  Issues no SQL of its own; every DB read
  flows through the upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network — by default.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; never refreshes prices.
* ``--check-provider-availability`` is a soft probe: it imports
  ``yfinance`` at the patchable seam and reports importability.  It
  does NOT download data.

Usage::

    python scripts/benchmark_cache_backfill_preflight.py
    python scripts/benchmark_cache_backfill_preflight.py --json
    python scripts/benchmark_cache_backfill_preflight.py --json --limit 50
    python scripts/benchmark_cache_backfill_preflight.py --json \
        --check-provider-availability
    python scripts/benchmark_cache_backfill_preflight.py --db-path ./events.db
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

# Effectively unlimited — we need every blocked row's target date to
# compute ``max(target_20d)`` correctly, not the upstream report's
# truncated sample.  Upstream reports sort by ``id ASC`` so a small
# limit would silently drop the events with the latest target dates.
_REPORT_FETCH_ALL: int = 10**12


_RECOMMENDED_NO_BLOCKERS = (
    "No missing_benchmark_proxy blockers detected — no SPY cache "
    "backfill is required at this time."
)
_RECOMMENDED_NO_PARSEABLE = (
    "missing_benchmark_proxy blockers exist but no parseable "
    "event_date / target_20d is available — preflight cannot "
    "propose a candidate SPY date range until the upstream events "
    "carry a parseable event_date."
)
_RECOMMENDED_BACKFILL_TOP = (
    "missing_benchmark_proxy is the top salvage path.  Backfill SPY "
    "from {start} through {end} (~{rows} weekday rows estimated, "
    "{calls} provider call) to clear every blocker."
)
_RECOMMENDED_BACKFILL_NOT_TOP = (
    "Backfill SPY from {start} through {end} (~{rows} weekday rows "
    "estimated, {calls} provider call) to clear missing_benchmark_proxy "
    "blockers.  Note: salvage report ranks {top} as the higher-yield "
    "path; SPY backfill is not the top salvage path."
)
_RECOMMENDED_BACKFILL_NO_TOP = (
    "Backfill SPY from {start} through {end} (~{rows} weekday rows "
    "estimated, {calls} provider call) to clear missing_benchmark_proxy "
    "blockers."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly.
# ---------------------------------------------------------------------------


def _run_benchmark_gap_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.stat_validation_benchmark_gap_report import (
        summarize_benchmark_gaps,
    )

    return summarize_benchmark_gaps(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_salvage_priority_report(*, db_path: str | None) -> dict[str, Any]:
    from scripts.validation_salvage_priority_report import (
        summarize_salvage_priority,
    )

    return summarize_salvage_priority(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _probe_provider_importable() -> bool:
    """Soft import probe — returns True iff ``yfinance`` is importable
    in this interpreter, without making any network call.

    Intentionally local to this module so tests can patch it without
    monkey-patching ``sys.modules`` or stubbing the actual provider.
    """
    try:
        import yfinance  # noqa: F401  (importability check only)
    except Exception:
        return False
    return True


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_backfill_preflight(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    check_provider_availability: bool = False,
) -> dict[str, Any]:
    """Combine the gap + salvage payloads into the preflight dict.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    gap_report     = _safe_dict(_run_benchmark_gap_report(db_path=db_path))
    salvage_report = _safe_dict(_run_salvage_priority_report(db_path=db_path))

    benchmark_symbol = (
        gap_report.get("benchmark_symbol") or "SPY"
    )
    blocked_count = _safe_int(gap_report.get("events_missing_benchmark_proxy"))

    raw_rows = gap_report.get("rows") or []
    if not isinstance(raw_rows, list):
        raw_rows = []

    target_dates = sorted(
        d for d in (
            r.get("benchmark_target_20d_date")
            for r in raw_rows if isinstance(r, dict)
        )
        if isinstance(d, str) and d
    )
    cache_max = _first_cache_max(raw_rows)

    required_end_date = target_dates[-1] if target_dates else None
    required_start_date = _compute_start_date(
        cache_max=cache_max, target_dates=target_dates,
    )

    estimated_rows = _count_weekdays_inclusive(
        required_start_date, required_end_date,
    )
    provider_calls = 1 if estimated_rows > 0 else 0

    top_path = salvage_report.get("top_salvage_path") \
        if isinstance(salvage_report.get("top_salvage_path"), str) else None
    recommended = _recommend(
        blocked_count=blocked_count,
        required_start_date=required_start_date,
        required_end_date=required_end_date,
        estimated_rows=estimated_rows,
        provider_calls=provider_calls,
        top_salvage_path=top_path,
    )

    examples = sorted(
        (
            {
                "event_id":                  r.get("event_id"),
                "event_date":                r.get("event_date"),
                "primary_ticker":            r.get("primary_ticker"),
                "benchmark_target_20d_date": r.get("benchmark_target_20d_date"),
            }
            for r in raw_rows
            if isinstance(r, dict) and isinstance(r.get("event_id"), int)
        ),
        key=lambda r: int(r["event_id"]),
    )[:capped_limit]

    payload: dict[str, Any] = {
        "benchmark_symbol":        benchmark_symbol,
        "blocked_event_count":     blocked_count,
        "required_start_date":     required_start_date,
        "required_end_date":       required_end_date,
        "current_cache_max_date":  cache_max,
        "estimated_rows_needed":   estimated_rows,
        "provider_calls_required": provider_calls,
        "recommended_next_action": recommended,
        "blocked_event_examples":  examples,
    }
    if check_provider_availability:
        payload["provider_available"] = bool(_probe_provider_importable())
    return payload


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _first_cache_max(rows: Sequence[Any]) -> str | None:
    """The gap report fills ``benchmark_cache_max_date`` with a single
    global value, repeated on every row.  Take the first non-null
    occurrence — they are all the same.  Returns ``None`` if no row
    carries a value (cache is empty for SPY).
    """
    for r in rows:
        if not isinstance(r, dict):
            continue
        v = r.get("benchmark_cache_max_date")
        if isinstance(v, str) and v:
            return v
    return None


def _compute_start_date(
    *,
    cache_max: str | None,
    target_dates: Sequence[str],
) -> str | None:
    if cache_max:
        d = _parse_iso(cache_max)
        if d is None:
            return None
        return (d + timedelta(days=1)).isoformat()
    if target_dates:
        return target_dates[0]
    return None


def _count_weekdays_inclusive(
    start_iso: str | None, end_iso: str | None,
) -> int:
    """Count Mon-Fri days in ``[start, end]`` inclusive.  Returns ``0``
    when either endpoint is missing or when ``start > end``.
    """
    if start_iso is None or end_iso is None:
        return 0
    start = _parse_iso(start_iso)
    end = _parse_iso(end_iso)
    if start is None or end is None or start > end:
        return 0
    count = 0
    cur = start
    one_day = timedelta(days=1)
    while cur <= end:
        if cur.weekday() < 5:
            count += 1
        cur += one_day
    return count


def _parse_iso(value: str | None) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


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
    blocked_count: int,
    required_start_date: str | None,
    required_end_date: str | None,
    estimated_rows: int,
    provider_calls: int,
    top_salvage_path: str | None,
) -> str:
    if blocked_count <= 0:
        return _RECOMMENDED_NO_BLOCKERS
    if required_start_date is None or required_end_date is None:
        return _RECOMMENDED_NO_PARSEABLE
    if top_salvage_path == "missing_benchmark_proxy":
        template = _RECOMMENDED_BACKFILL_TOP
        return template.format(
            start=required_start_date, end=required_end_date,
            rows=estimated_rows, calls=provider_calls,
        )
    if top_salvage_path:
        return _RECOMMENDED_BACKFILL_NOT_TOP.format(
            start=required_start_date, end=required_end_date,
            rows=estimated_rows, calls=provider_calls,
            top=top_salvage_path,
        )
    return _RECOMMENDED_BACKFILL_NO_TOP.format(
        start=required_start_date, end=required_end_date,
        rows=estimated_rows, calls=provider_calls,
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["SPY benchmark-cache backfill preflight", ""]
    lines.append(f"Benchmark symbol:          {report['benchmark_symbol']}")
    lines.append(f"Blocked event count:       {report['blocked_event_count']}")
    lines.append(
        f"Current cache max date:    "
        f"{report['current_cache_max_date'] or '-'}"
    )
    lines.append(
        f"Required start date:       "
        f"{report['required_start_date'] or '-'}"
    )
    lines.append(
        f"Required end date:         "
        f"{report['required_end_date'] or '-'}"
    )
    lines.append(
        f"Estimated rows needed:     {report['estimated_rows_needed']}"
    )
    lines.append(
        f"Provider calls required:   {report['provider_calls_required']}"
    )
    if "provider_available" in report:
        lines.append(
            f"Provider importable:       {report['provider_available']}"
        )
    examples = report.get("blocked_event_examples") or []
    lines.append("")
    lines.append(f"Blocked event examples ({len(examples)}):")
    if examples:
        for e in examples:
            lines.append(
                f"  id={e.get('event_id')} "
                f"date={e.get('event_date') or '-'} "
                f"ticker={e.get('primary_ticker') or '-'} "
                f"target_20d={e.get('benchmark_target_20d_date') or '-'}"
            )
    else:
        lines.append("  -")
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
            "Read-only SPY benchmark-cache backfill preflight.  "
            "Identifies the SPY date range needed to clear every "
            "missing_benchmark_proxy blocker, the rough weekday-row "
            "count, and the number of provider calls a fetch would "
            "take.  Read-only: no INSERT/UPDATE/DELETE, no provider "
            "fetch, no LLM, no FastAPI surface.  By default does not "
            "import yfinance."
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
            f"Cap blocked_event_examples at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts and the proposed "
            f"date range always reflect every blocked event."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the preflight follows the project's "
            "configured archive."
        ),
    )
    parser.add_argument(
        "--check-provider-availability",
        dest="check_provider_availability",
        action="store_true",
        help=(
            "Soft-probe yfinance importability without downloading "
            "data.  Adds a 'provider_available' bool to the output. "
            "Off by default."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_backfill_preflight(
        db_path=args.db_path,
        limit=args.limit,
        check_provider_availability=args.check_provider_availability,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
