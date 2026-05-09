#!/usr/bin/env python3
"""Read-only manual ticker repair shortlist.

Combines two upstream read-only reports into a single triage list of
events worth a human ticker review:

  * :mod:`scripts.stat_validation_missing_tickers_report` — events
    whose ``market_tickers`` JSON resolves to no usable primary
    symbol; an operator must supply a ticker before the event can
    enter event-study validation.
  * :mod:`scripts.stat_validation_ticker_contamination_report` —
    *fully-ready* events whose primary ticker assignment looks
    topically suspicious (DRIV/LIT thematic fallback on an unrelated
    headline, duplicate ``(event_date, primary_ticker)`` rows,
    local-news / off-topic headlines, or unclassified mechanism
    family).

The two source populations are disjoint by construction (missing
tickers ⇒ ``has_market_tickers=False`` ⇒ not fully-ready, while
contaminated ⇒ fully-ready including ``has_market_tickers=True``), so
no deduplication is required.

The script is a triage tool only.  It does not propose replacement
tickers, never edits the archive, and never calls a provider, an LLM,
``yfinance``, or any FastAPI surface.  ``manual_review_priority`` is
the report's only judgement axis and is derived purely from the
upstream flag set:

  * ``high``   — at least one flag clearly indicates a ticker
                 mismatch (``driv_lit_off_topic`` or
                 ``local_off_topic_headline``).  The current primary
                 symbol is almost certainly wrong; a human must pick
                 the right one (or drop the event).
  * ``medium`` — either the event has no ``market_tickers`` at all
                 (``missing_market_tickers`` source), or its only
                 contamination flag is ``duplicate_date_ticker``
                 (collision with another event; one of the two has a
                 wrong ticker but it isn't obvious which).
  * ``low``    — only ``mechanism_family_none`` fired.  Not strictly a
                 ticker problem; surfaced for transparency so an
                 operator scanning the shortlist can see and skip it.

Output contract::

    {
      "ok":               bool,
      "total_candidates": int,
      "by_priority": {
        "high":   int,
        "medium": int,
        "low":    int,
      },
      "by_reason": {
        "missing_market_tickers":   int,
        "contaminated_fully_ready": int,
      },
      "candidates": [                  # capped at --limit; sorted by
                                       # priority (high>medium>low)
                                       # then event_id asc
        {
          "event_id":               int,
          "headline":               str | None,
          "primary_ticker":         str | None,   # None for the
                                                  # missing-tickers
                                                  # source bucket
          "flags":                  list[str],
          "reason":                 str,          # one of the
                                                  # ``by_reason`` keys
          "manual_review_priority": "high" | "medium" | "low",
        },
        ...
      ],
      "recommended_next_action": str,
    }

Aggregate counts (``total_candidates``, ``by_priority``,
``by_reason``) reflect every shortlisted event in the archive.  Only
the ``candidates`` list is truncated by ``--limit``.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues no SQL of its own; every DB read flows through
  the upstream reports' SELECT-only paths.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Never assigns or proposes replacement tickers; the script only
  flags events for a human to look at.

Usage::

    python scripts/manual_ticker_repair_shortlist.py
    python scripts/manual_ticker_repair_shortlist.py --json
    python scripts/manual_ticker_repair_shortlist.py --json --limit 50
    python scripts/manual_ticker_repair_shortlist.py --db-path ./events.db --json
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
# reports — the shortlist needs every flagged row in the archive to
# tally aggregates correctly, not the upstream report's truncated
# sample.
_REPORT_FETCH_ALL: int = 10**12


_REASON_MISSING:      str = "missing_market_tickers"
_REASON_CONTAMINATED: str = "contaminated_fully_ready"


_PRIORITY_HIGH:   str = "high"
_PRIORITY_MEDIUM: str = "medium"
_PRIORITY_LOW:    str = "low"


# Stable ordering for sort + by_priority bookkeeping.  Lower rank
# means surfaced earlier in the candidates list.
_PRIORITY_RANK: dict[str, int] = {
    _PRIORITY_HIGH:   0,
    _PRIORITY_MEDIUM: 1,
    _PRIORITY_LOW:    2,
}


# Contamination flags that, when present, are strong evidence the
# primary ticker is wrong (not just orthogonal metadata noise).
_HIGH_PRIORITY_CONTAM_FLAGS: frozenset[str] = frozenset({
    "driv_lit_off_topic",
    "local_off_topic_headline",
})

# A duplicate ``(event_date, primary_ticker)`` collision implies one
# of the two assignments is wrong, but does not by itself say which
# event needs a new ticker — medium priority on its own.
_MEDIUM_PRIORITY_CONTAM_FLAGS: frozenset[str] = frozenset({
    "duplicate_date_ticker",
})


_RECOMMENDED_NO_CANDIDATES = (
    "No events on the manual ticker repair shortlist — every event "
    "either carries a usable ticker or is not flagged as suspicious."
)
_RECOMMENDED_HAS_CANDIDATES = (
    "{n} event(s) flagged for manual review — operator must inspect "
    "each headline and supply or replace the primary ticker by hand. "
    "No LLM inference, no archive mutation."
)


# ---------------------------------------------------------------------------
# Lazy seams — kept module-level so tests can patch them directly with
# synthetic payloads.  The lazy imports resolve only on the un-patched
# path so unit tests can swap these seams without paying the upstream
# import cost.
# ---------------------------------------------------------------------------


def _run_missing_tickers_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the missing-market-tickers report with an effectively
    unlimited per-event cap and return the parsed payload.

    Tests patch this attribute directly, so the import only resolves
    on the un-patched path.
    """
    from scripts.stat_validation_missing_tickers_report import (
        summarize_missing_tickers,
    )

    return summarize_missing_tickers(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


def _run_contamination_report(*, db_path: str | None) -> dict[str, Any]:
    """Invoke the topical ticker-contamination report with an
    effectively unlimited per-event cap and return the parsed payload.

    Tests patch this attribute directly.
    """
    from scripts.stat_validation_ticker_contamination_report import (
        summarize_contamination,
    )

    return summarize_contamination(
        db_path=db_path, limit=_REPORT_FETCH_ALL,
    )


# ---------------------------------------------------------------------------
# Pure compute over the two upstream payloads
# ---------------------------------------------------------------------------


def summarize_repair_shortlist(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Combine the missing-tickers + contamination payloads into the
    manual ticker repair shortlist.

    See module docstring for the full output contract.
    """
    capped_limit = max(int(limit), 0)

    missing_payload = _safe_dict(_run_missing_tickers_report(db_path=db_path))
    contam_payload  = _safe_dict(_run_contamination_report(db_path=db_path))

    candidates: list[dict[str, Any]] = []
    candidates.extend(_candidates_from_missing(missing_payload))
    candidates.extend(_candidates_from_contamination(contam_payload))

    candidates.sort(key=lambda c: (
        _PRIORITY_RANK.get(c["manual_review_priority"], 99),
        c["event_id"],
    ))

    by_priority = {
        _PRIORITY_HIGH:   sum(
            1 for c in candidates
            if c["manual_review_priority"] == _PRIORITY_HIGH
        ),
        _PRIORITY_MEDIUM: sum(
            1 for c in candidates
            if c["manual_review_priority"] == _PRIORITY_MEDIUM
        ),
        _PRIORITY_LOW:    sum(
            1 for c in candidates
            if c["manual_review_priority"] == _PRIORITY_LOW
        ),
    }
    by_reason = {
        _REASON_MISSING:      sum(
            1 for c in candidates if c["reason"] == _REASON_MISSING
        ),
        _REASON_CONTAMINATED: sum(
            1 for c in candidates if c["reason"] == _REASON_CONTAMINATED
        ),
    }

    return {
        "ok":                       True,
        "total_candidates":         len(candidates),
        "by_priority":              by_priority,
        "by_reason":                by_reason,
        "candidates":               candidates[:capped_limit],
        "recommended_next_action":  _recommend(len(candidates)),
    }


def _candidates_from_missing(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project missing-market-tickers events into shortlist entries.

    Every missing-tickers row is medium priority — there is no
    primary ticker to inspect, so the operator must supply one
    manually but the event is no more or less obviously broken than
    any other ticker-less row.
    """
    raw_events = payload.get("events") or []
    if not isinstance(raw_events, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw_events:
        if not isinstance(entry, dict):
            continue
        ev_id = entry.get("event_id")
        if not isinstance(ev_id, int):
            continue
        out.append({
            "event_id":               ev_id,
            "headline":               entry.get("headline"),
            "primary_ticker":         None,
            "flags":                  [_REASON_MISSING],
            "reason":                 _REASON_MISSING,
            "manual_review_priority": _PRIORITY_MEDIUM,
        })
    return out


def _candidates_from_contamination(
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Project contamination examples into shortlist entries.

    All flagged contamination rows are surfaced — including the
    ``mechanism_family_none``-only ones — but priority reflects how
    likely the ticker itself is wrong.  ``mechanism_family_none``
    alone is "low" because it is not strictly a ticker problem.
    """
    raw_examples = payload.get("examples") or []
    if not isinstance(raw_examples, list):
        return []
    out: list[dict[str, Any]] = []
    for entry in raw_examples:
        if not isinstance(entry, dict):
            continue
        ev_id = entry.get("event_id")
        if not isinstance(ev_id, int):
            continue
        flags_raw = entry.get("flags") or []
        if not isinstance(flags_raw, list):
            flags_raw = []
        flags = [f for f in flags_raw if isinstance(f, str)]
        out.append({
            "event_id":               ev_id,
            "headline":               entry.get("headline"),
            "primary_ticker":         entry.get("primary_ticker"),
            "flags":                  flags,
            "reason":                 _REASON_CONTAMINATED,
            "manual_review_priority": _priority_for_contamination(flags),
        })
    return out


def _priority_for_contamination(flags: Sequence[str]) -> str:
    """Map the contamination flag set to a priority bucket.

    ``high`` if any flag in :data:`_HIGH_PRIORITY_CONTAM_FLAGS`
    fired; ``medium`` if a duplicate-collision is the only ticker
    signal; ``low`` otherwise (e.g. mechanism_family_none only, or
    the defensive empty-flag-list edge case).
    """
    flag_set = set(flags)
    if flag_set & _HIGH_PRIORITY_CONTAM_FLAGS:
        return _PRIORITY_HIGH
    if flag_set & _MEDIUM_PRIORITY_CONTAM_FLAGS:
        return _PRIORITY_MEDIUM
    return _PRIORITY_LOW


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _recommend(total_candidates: int) -> str:
    if total_candidates <= 0:
        return _RECOMMENDED_NO_CANDIDATES
    return _RECOMMENDED_HAS_CANDIDATES.format(n=total_candidates)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Manual ticker repair shortlist", ""]
    lines.append(f"Total candidates:                {report['total_candidates']}")
    by_priority = report.get("by_priority") or {}
    lines.append(
        f"  high:   {by_priority.get(_PRIORITY_HIGH, 0)}"
    )
    lines.append(
        f"  medium: {by_priority.get(_PRIORITY_MEDIUM, 0)}"
    )
    lines.append(
        f"  low:    {by_priority.get(_PRIORITY_LOW, 0)}"
    )
    lines.append("")
    by_reason = report.get("by_reason") or {}
    lines.append("By reason:")
    lines.append(
        f"  missing_market_tickers:   {by_reason.get(_REASON_MISSING, 0)}"
    )
    lines.append(
        f"  contaminated_fully_ready: {by_reason.get(_REASON_CONTAMINATED, 0)}"
    )
    lines.append("")

    candidates = report.get("candidates") or []
    lines.append(f"Candidates listed ({len(candidates)}):")
    if candidates:
        for entry in candidates:
            flags = ",".join(entry.get("flags") or []) or "-"
            headline = entry.get("headline") or "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"priority={entry.get('manual_review_priority')} "
                f"reason={entry.get('reason')} "
                f"ticker={entry.get('primary_ticker') or '-'}"
            )
            lines.append(f"      flags: {flags}")
            lines.append(f"      headline: {headline[:120]}")
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
            "Read-only manual ticker repair shortlist.  Combines the "
            "missing-market-tickers report and the topical ticker-"
            "contamination report into a single triage list of events "
            "worth human ticker review.  Each row carries an "
            "event_id, headline, current primary_ticker (if any), "
            "flags, reason, and manual_review_priority.  Read-only: "
            "never assigns tickers, never edits the archive, no "
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
            f"Cap the surfaced candidates list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
            f"every shortlisted event."
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

    report = summarize_repair_shortlist(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
