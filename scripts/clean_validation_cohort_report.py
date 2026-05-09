#!/usr/bin/env python3
"""Read-only clean validation cohort selector.

Combines the three upstream archive-readiness reports into a single
cohort selector that answers, "which fully-ready events look safe to
include in an FDR-controlled aggregate claim, which fully-ready events
need manual review first, and what is the smallest cache backfill
that would expand the cohort?"

Three upstream reports are consumed through patchable seams so unit
tests can drive the selector with synthetic fixtures:

  * :mod:`scripts.stat_validation_readiness_report`
        — source of truth for "which events are fully-ready to drive
          the event-study engine".
  * :mod:`scripts.stat_validation_ticker_contamination_report`
        — applies four heuristic flags to fully-ready events
          (DRIV/LIT-style off-topic, mechanism_family none, duplicate
          (date, ticker), local off-topic headline).  Suspicious
          events are excluded from the clean cohort pending manual
          review.
  * :mod:`scripts.stat_validation_blocker_report`
        — decomposes not-ready events by blocker so an operator can
          see which targeted cache backfill would unlock the next
          batch of candidates.

Output contract::

    {
      "ok":                            bool,
      "total_events":                  int,
      "fully_ready_count":             int,
      "contaminated_fully_ready_count":int,
      "clean_fully_ready_count":       int,
      "clean_fully_ready_event_ids":   list[int],   # asc, ALL ids
      "excluded_fully_ready_examples": [            # capped at --limit
        {
          "event_id":         int,
          "event_date":       str | None,
          "primary_ticker":   str | None,
          "headline":         str | None,
          "mechanism_family": str | None,
          "flags":            list[str],   # = exclusion reasons
        },
        ...
      ],
      "next_salvage_candidates": {                  # one bucket per
        "missing_market_tickers":         {         # blocker key
          "count":      int,
          "candidates": [                           # capped at --limit
            {"event_id": int,
             "event_date": str | None,
             "primary_ticker": str | None},
            ...
          ],
        },
        "missing_forward_cache_1d":       {...},
        "missing_forward_cache_5d":       {...},
        "missing_forward_cache_20d":      {...},
        "missing_benchmark_proxy":        {...},
        "insufficient_estimation_window": {...},
      },
      "recommended_next_action": str,
    }

Conservative language by construction
-------------------------------------
The selector NEVER assigns or proposes replacement tickers, NEVER
deletes archive rows, and the recommended-next-action prose uses
"candidate" / "manual review" / "excluded from aggregate claim"
phrasing only.  Topical contamination is surfaced for human review,
not auto-corrected.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own; every DB read flows through
  the upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or rewrites tickers; this is a selector tool only.

Usage::

    python scripts/clean_validation_cohort_report.py
    python scripts/clean_validation_cohort_report.py --json
    python scripts/clean_validation_cohort_report.py --json --limit 50
    python scripts/clean_validation_cohort_report.py --db-path ./events.db --json
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


# Effectively unlimited per-event cap when delegating to upstream
# reports — we need every fully-ready / contaminated / not-ready event
# to count correctly, not the upstream report's truncated sample.
_REPORT_FETCH_ALL: int = 10**12


# Stable ordering for next_salvage_candidates + the text renderer.
_BLOCKER_KEYS: tuple[str, ...] = (
    "missing_market_tickers",
    "missing_forward_cache_1d",
    "missing_forward_cache_5d",
    "missing_forward_cache_20d",
    "missing_benchmark_proxy",
    "insufficient_estimation_window",
)


_RECOMMENDED_NO_EVENTS = (
    "Archive is empty — no events to assemble a validation cohort "
    "from.  Seed events and refresh the price cache before re-running."
)
_RECOMMENDED_NO_FULLY_READY = (
    "No fully-ready events available.  Refresh the price cache for "
    "the candidates surfaced under the highest-count blocker bucket, "
    "then re-run this report."
)
_RECOMMENDED_ALL_CONTAMINATED = (
    "Every fully-ready event is excluded from the aggregate claim "
    "pending manual review of its primary-ticker assignment.  This "
    "selector does not propose replacement tickers."
)
_RECOMMENDED_ALL_CLEAN = (
    "All fully-ready events pass the topical heuristic checks.  The "
    "clean cohort can be passed to the FDR-controlled validator "
    "as-is; no events are excluded from the aggregate claim."
)
_RECOMMENDED_MIXED = (
    "Clean cohort assembled.  Some fully-ready events are excluded "
    "from the aggregate claim pending manual review of their primary-"
    "ticker assignments — this selector does not propose replacement "
    "tickers.  Refer to the highest-count blocker bucket for the "
    "next salvage candidates."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly with
# synthetic payloads.  The lazy imports resolve only on the un-patched
# path so unit tests can swap these seams without paying the upstream
# import cost.
# ---------------------------------------------------------------------------


def _run_readiness_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the readiness report and return the parsed payload."""
    from scripts.stat_validation_readiness_report import summarize_readiness

    return summarize_readiness(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the contamination report and return the parsed payload.

    The selector needs every contaminated event id to compute
    ``clean_fully_ready_event_ids``, so the contamination report's
    ``examples`` list must not be truncated.
    """
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_blocker_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the blocker report and return the parsed payload.

    The blocker report internally uses an unlimited per-event cap
    when computing counts; we fetch its examples with a generous cap
    so per-bucket candidate lists are populated.
    """
    from scripts.stat_validation_blocker_report import summarize_blockers

    return summarize_blockers(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute over the three upstream payloads
# ---------------------------------------------------------------------------


def summarize_clean_cohort(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Combine the readiness / contamination / blocker reports into
    the clean validation cohort payload.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    readiness     = _safe_dict(_run_readiness_report(db_path=db_path))
    contamination = _safe_dict(_run_contamination_report(db_path=db_path))
    blockers      = _safe_dict(_run_blocker_report(db_path=db_path))

    total_events       = _safe_int(readiness.get("total_events"))
    fully_ready_count  = _safe_int(readiness.get("events_fully_ready"))

    # Contamination ------------------------------------------------------
    contaminated_count = _safe_int(contamination.get("suspicious_count"))
    contam_examples    = contamination.get("examples") or []
    if not isinstance(contam_examples, list):
        contam_examples = []

    contaminated_ids: set[int] = set()
    for e in contam_examples:
        if isinstance(e, dict) and isinstance(e.get("event_id"), int):
            contaminated_ids.add(int(e["event_id"]))

    # Fully-ready event ids from readiness payload -----------------------
    ready_ids: list[int] = []
    for e in (readiness.get("events") or []):
        if not isinstance(e, dict):
            continue
        if not e.get("fully_ready", False):
            continue
        ev_id = e.get("event_id")
        if isinstance(ev_id, int):
            ready_ids.append(ev_id)

    clean_ids = sorted(eid for eid in ready_ids if eid not in contaminated_ids)
    clean_count = len(clean_ids)

    # Excluded examples — sorted by id asc, capped at limit --------------
    excluded_sorted = sorted(
        (e for e in contam_examples
         if isinstance(e, dict) and isinstance(e.get("event_id"), int)),
        key=lambda e: int(e["event_id"]),
    )
    excluded_examples = [
        _excluded_entry(e) for e in excluded_sorted[:capped_limit]
    ]

    # next_salvage_candidates — one bucket per blocker key ---------------
    blockers_payload = blockers.get("blockers") or {}
    if not isinstance(blockers_payload, dict):
        blockers_payload = {}

    next_salvage: dict[str, dict[str, Any]] = {}
    for key in _BLOCKER_KEYS:
        bucket = blockers_payload.get(key) or {}
        bucket_count = _safe_int(bucket.get("count"))
        bucket_examples = bucket.get("examples") or []
        if not isinstance(bucket_examples, list):
            bucket_examples = []
        candidates_sorted = sorted(
            (c for c in bucket_examples
             if isinstance(c, dict) and isinstance(c.get("event_id"), int)),
            key=lambda c: int(c["event_id"]),
        )
        next_salvage[key] = {
            "count":      bucket_count,
            "candidates": [
                _candidate_entry(c) for c in candidates_sorted[:capped_limit]
            ],
        }

    return {
        "ok":                              True,
        "total_events":                    total_events,
        "fully_ready_count":               fully_ready_count,
        "contaminated_fully_ready_count":  contaminated_count,
        "clean_fully_ready_count":         clean_count,
        "clean_fully_ready_event_ids":     clean_ids,
        "excluded_fully_ready_examples":   excluded_examples,
        "next_salvage_candidates":         next_salvage,
        "recommended_next_action":
            _recommend(total_events, fully_ready_count,
                       contaminated_count, clean_count),
    }


# ---------------------------------------------------------------------------
# Pure helpers — small, isolated, easy to test.
# ---------------------------------------------------------------------------


def _excluded_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a contamination example down to the selector's
    ``excluded_fully_ready_examples`` shape."""
    flags = entry.get("flags")
    if not isinstance(flags, list):
        flags = []
    return {
        "event_id":         entry.get("event_id"),
        "event_date":       entry.get("event_date"),
        "primary_ticker":   entry.get("primary_ticker"),
        "headline":         entry.get("headline"),
        "mechanism_family": entry.get("mechanism_family"),
        "flags":            list(flags),
    }


def _candidate_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Project a blocker-report event entry down to the selector's
    minimal ``candidates`` shape — enough for an operator to spot the
    event without forwarding every check field."""
    return {
        "event_id":       entry.get("event_id"),
        "event_date":     entry.get("event_date"),
        "primary_ticker": entry.get("primary_ticker"),
    }


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_int(value: Any) -> int:
    """Return ``value`` as ``int`` if it converts cleanly, else ``0``.

    Defensive against an upstream payload that has been patched with
    garbage in tests, or against the empty-DB path.
    """
    if isinstance(value, bool):
        return 0
    if not isinstance(value, int):
        return 0
    return value


def _recommend(total_events: int, fully_ready: int,
               contaminated: int, clean: int) -> str:
    if total_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if fully_ready <= 0:
        return _RECOMMENDED_NO_FULLY_READY
    if clean == 0:
        return _RECOMMENDED_ALL_CONTAMINATED
    if contaminated == 0:
        return _RECOMMENDED_ALL_CLEAN
    return _RECOMMENDED_MIXED


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Clean validation cohort selector", ""]
    lines.append(f"Total events:                            {report['total_events']}")
    lines.append(f"  fully ready:                           {report['fully_ready_count']}")
    lines.append(f"  contaminated (excluded from claim):    {report['contaminated_fully_ready_count']}")
    lines.append(f"  clean (cohort candidates):             {report['clean_fully_ready_count']}")
    lines.append("")

    clean_ids = report.get("clean_fully_ready_event_ids") or []
    lines.append(f"Clean fully-ready event ids ({len(clean_ids)}):")
    if clean_ids:
        # Show first ~30 ids inline; full list is in JSON output.
        head = clean_ids[:30]
        lines.append("  " + ", ".join(str(i) for i in head)
                     + (" ..." if len(clean_ids) > len(head) else ""))
    else:
        lines.append("  -")
    lines.append("")

    excluded = report.get("excluded_fully_ready_examples") or []
    lines.append(f"Excluded fully-ready examples ({len(excluded)}):")
    if excluded:
        for entry in excluded:
            flags = ",".join(entry.get("flags") or []) or "-"
            headline = entry.get("headline") or "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"family={entry.get('mechanism_family') or '-'}"
            )
            lines.append(f"      reasons: {flags}")
            lines.append(f"      headline: {headline[:120]}")
    else:
        lines.append("  -")
    lines.append("")

    nsc = report.get("next_salvage_candidates") or {}
    lines.append("Next salvage candidates (blocked events grouped by blocker):")
    for key in _BLOCKER_KEYS:
        bucket = nsc.get(key) or {}
        count = bucket.get("count", 0)
        candidates = bucket.get("candidates") or []
        lines.append(f"  {key}: count={count}")
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
            "Read-only clean validation cohort selector.  Combines "
            "the readiness, contamination, and blocker reports into "
            "a single cohort payload.  Read-only: never assigns "
            "tickers, never deletes or edits archive rows, no "
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
            f"Cap each surfaced examples / candidates list at N "
            f"entries (default {_DEFAULT_LIMIT}).  Aggregate counts "
            f"and ``clean_fully_ready_event_ids`` always reflect "
            f"every event in the archive."
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

    report = summarize_clean_cohort(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
