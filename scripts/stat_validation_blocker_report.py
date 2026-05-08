#!/usr/bin/env python3
"""Read-only statistical-readiness blocker breakdown.

Decomposes the archive's not-fully-ready events into per-blocker
counts plus examples, so an operator can answer the natural follow-up
to :mod:`scripts.stat_validation_readiness_report` — "of the events
that aren't ready, *why* aren't they ready?"

Six blocker categories are surfaced, each negating one readiness
check:

    blocker_key                         negates check
    --------------------------------    -------------------------------
    missing_market_tickers              has_market_tickers
    missing_forward_cache_1d            forward_cache_1d
    missing_forward_cache_5d            forward_cache_5d
    missing_forward_cache_20d           forward_cache_20d
    missing_benchmark_proxy             benchmark_proxy_available
    insufficient_estimation_window      estimation_window_sufficient

The six counts are **not a partition** — an event without an
``event_date`` will show up in every cache-anchored blocker
simultaneously because the underlying readiness check degrades to
``False`` cleanly when the event_date is missing.  This is
intentional: an operator scanning the report sees every actionable
gap at once, and the readiness report itself remains the canonical
place to surface ``events_with_event_date``.

Output contract::

    {
      "total_events":           int,
      "events_fully_ready":     int,
      "events_not_fully_ready": int,
      "blockers": {
        "missing_market_tickers": {
          "count":    int,                # every not-ready event hit
          "examples": list[event_entry],  # capped at --limit
        },
        "missing_forward_cache_1d":       {...},
        "missing_forward_cache_5d":       {...},
        "missing_forward_cache_20d":      {...},
        "missing_benchmark_proxy":        {...},
        "insufficient_estimation_window": {...},
      },
      "recommended_next_action": str,
    }

Each ``event_entry`` carries the readiness report's per-event
shape: ``{event_id, event_date, primary_ticker, checks,
fully_ready}``.

Out of scope (deliberately)
---------------------------
* Read-only.  This script never opens the SQLite file directly —
  every DB read flows through
  :func:`scripts.stat_validation_readiness_report.summarize_readiness`
  via the :func:`_run_readiness_report` seam, which itself only
  issues ``SELECT`` statements.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.

Usage::

    python scripts/stat_validation_blocker_report.py
    python scripts/stat_validation_blocker_report.py --json
    python scripts/stat_validation_blocker_report.py --json --limit 20
    python scripts/stat_validation_blocker_report.py --db-path ./events.db --json
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


_DEFAULT_LIMIT = 25


# Effectively unlimited per-event cap when delegating to the
# readiness report — we need every not-ready event to count blockers
# correctly, not just the readiness report's truncated sample.
_READINESS_FETCH_ALL: int = 10**12


# Stable ordering for the blockers dict + the text renderer.  Each
# tuple is ``(blocker_key, readiness_check_key)``: the blocker is
# counted whenever the readiness check is False.
_BLOCKER_TO_CHECK: tuple[tuple[str, str], ...] = (
    ("missing_market_tickers",         "has_market_tickers"),
    ("missing_forward_cache_1d",       "forward_cache_1d"),
    ("missing_forward_cache_5d",       "forward_cache_5d"),
    ("missing_forward_cache_20d",      "forward_cache_20d"),
    ("missing_benchmark_proxy",        "benchmark_proxy_available"),
    ("insufficient_estimation_window", "estimation_window_sufficient"),
)


_RECOMMENDED_NO_EVENTS = (
    "Archive is empty — no events to validate.  Seed events before "
    "running statistical readiness checks."
)
_RECOMMENDED_OK = (
    "Every event in the archive is fully ready for statistical "
    "validation.  No blockers to clear."
)
_RECOMMENDED_GAPS = (
    "Some events are blocked.  Refresh the price cache for the "
    "tickers and SPY benchmark surfaced under the highest-count "
    "blockers, then re-run this report."
)


# ---------------------------------------------------------------------------
# Lazy seam — kept module-level so tests can patch it directly with a
# synthetic readiness payload.  The lazy import resolves only on the
# un-patched path so unit tests can swap this seam without paying the
# readiness module's import cost.
# ---------------------------------------------------------------------------


def _run_readiness_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the readiness report with an effectively unlimited
    per-event cap and return the parsed payload.

    Tests patch this attribute directly, so the import only resolves
    on the un-patched path.  The large ``limit`` is the cleanest way
    to fetch every event without changing the readiness report's
    public contract.
    """
    from scripts.stat_validation_readiness_report import summarize_readiness

    return summarize_readiness(
        db_path=db_path, limit=_READINESS_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute over the readiness payload
# ---------------------------------------------------------------------------


def summarize_blockers(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Decompose the readiness report into per-blocker counts + examples.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Forwarded to :func:`_run_readiness_report`; ``None`` defers
        to the readiness report's own default (``db.DB_FILE``).
    limit
        Cap each blocker's ``examples`` list at N entries (the
        ``count`` always reflects every not-ready event).  Negative
        values clamp to ``0``.
    """
    capped_limit = max(int(limit), 0)
    readiness = _run_readiness_report(db_path=db_path)
    if not isinstance(readiness, dict):
        readiness = {}

    total_events       = _safe_int(readiness.get("total_events"))
    fully_ready_count  = _safe_int(readiness.get("events_fully_ready"))
    events             = readiness.get("events") or []
    if not isinstance(events, list):
        events = []

    not_ready: list[dict[str, Any]] = [
        e for e in events
        if isinstance(e, dict) and not e.get("fully_ready", False)
    ]
    not_ready_count = len(not_ready)

    blockers: dict[str, dict[str, Any]] = {}
    for blocker_key, check_key in _BLOCKER_TO_CHECK:
        failing = [
            e for e in not_ready
            if not (e.get("checks") or {}).get(check_key, False)
        ]
        blockers[blocker_key] = {
            "count":    len(failing),
            "examples": failing[:capped_limit],
        }

    return {
        "total_events":           total_events,
        "events_fully_ready":     fully_ready_count,
        "events_not_fully_ready": not_ready_count,
        "blockers":               blockers,
        "recommended_next_action":
            _recommend(total_events, not_ready_count),
    }


def _safe_int(value: Any) -> int:
    """Return ``value`` as ``int`` if it converts cleanly, else ``0``.

    Defensive against an upstream readiness payload that has been
    patched with garbage in tests, or against the empty-DB path where
    the readiness report returns counts of ``0``.
    """
    if isinstance(value, bool):
        return 0
    if not isinstance(value, int):
        return 0
    return value


def _recommend(total_events: int, not_ready_count: int) -> str:
    if total_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if not_ready_count == 0:
        return _RECOMMENDED_OK
    return _RECOMMENDED_GAPS


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Statistical-readiness blocker breakdown", ""]
    lines.append(f"Total events:            {report['total_events']}")
    lines.append(f"  fully ready:           {report['events_fully_ready']}")
    lines.append(f"  not fully ready:       {report['events_not_fully_ready']}")
    lines.append("")
    lines.append("Blockers:")

    blockers = report.get("blockers") or {}
    for blocker_key, _ in _BLOCKER_TO_CHECK:
        bucket = blockers.get(blocker_key) or {}
        count = bucket.get("count", 0)
        examples = bucket.get("examples") or []
        lines.append(f"  {blocker_key}: count={count}")
        if examples:
            for entry in examples:
                lines.append(
                    f"      id={entry.get('event_id')} "
                    f"date={entry.get('event_date') or '-'} "
                    f"ticker={entry.get('primary_ticker') or '-'}"
                )
        else:
            lines.append("      (no examples)")
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
            "Read-only blocker breakdown for the archive statistical-"
            "readiness population.  Decomposes not-ready events into "
            "per-blocker counts + examples.  Reuses the readiness "
            "report's SELECT path; no INSERT/UPDATE/DELETE, no "
            "provider, no LLM, no FastAPI surface."
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
            f"Cap each blocker's examples list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Counts always reflect every "
            f"not-ready event."
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

    report = summarize_blockers(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
