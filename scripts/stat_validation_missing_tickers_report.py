#!/usr/bin/env python3
"""Read-only triage report for events with missing ``market_tickers``.

Decomposes the archive's not-ready population along a single
actionable axis: events whose ``market_tickers`` JSON resolves to no
usable primary symbol.  These rows can never satisfy the event-study
engine without an operator (or upstream extractor) supplying tickers,
so the report's per-row ``suggested_next_action`` is the constant
``"manual_review_required"``.  The script deliberately performs no
ticker inference, no LLM call, and no provider lookup.

Aligns with :mod:`scripts.stat_validation_readiness_report` by reusing
the same primary-ticker resolver: ``has_market_tickers`` in the
readiness report is False iff this report would surface the event.

Output contract (JSON / dict)::

    {
      "total_events":                  int,   # parseable ids in archive
      "events_missing_market_tickers": int,   # full archive count
      "events": [                              # capped at --limit, id asc
        {
          "event_id":              int,
          "event_date":            str | None,
          "headline":              str | None,
          "stage":                 str | None,
          "persistence":           str | None,
          "confidence":            str | None,
          "suggested_next_action": "manual_review_required",
        },
        ...
      ],
      "recommended_next_action": str,
    }

Output formats
--------------
* default (text)  — totals header + one block per surfaced event.
* ``--json``      — the full dict above.
* ``--csv``       — header row + one row per surfaced event, no
                    totals.  CSV is for pipelining; mixing totals into
                    the body would break downstream parsers.
* ``--json`` and ``--csv`` are mutually exclusive.

``total_events`` counts events whose ``id`` parses cleanly as an
integer — rows with malformed ids are skipped, mirroring
:mod:`scripts.stat_validation_readiness_report`.  In a healthy archive
this matches ``SELECT COUNT(*) FROM events``.

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No ticker inference.  ``suggested_next_action`` is the constant
  ``"manual_review_required"`` for every surfaced row.

Usage::

    python scripts/stat_validation_missing_tickers_report.py
    python scripts/stat_validation_missing_tickers_report.py --json
    python scripts/stat_validation_missing_tickers_report.py --csv --limit 50
    python scripts/stat_validation_missing_tickers_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Single source of truth for the primary-ticker definition.  Sharing
# this helper with the readiness report keeps the "missing tickers"
# determination identical across surfaces — an event surfaced here is
# exactly an event with ``has_market_tickers=False`` over there.
from scripts.stat_validation_readiness_report import _primary_ticker  # noqa: E402


_DEFAULT_LIMIT = 25
_SUGGESTED_NEXT_ACTION = "manual_review_required"


_RECOMMENDED_NO_EVENTS = (
    "Archive is empty — no events to triage.  Seed events before "
    "running missing-ticker checks."
)
_RECOMMENDED_OK = (
    "Every event in the archive carries at least one market ticker.  "
    "No manual review needed for this blocker."
)
_RECOMMENDED_GAPS = (
    "Some events lack market_tickers.  Review the listed headlines "
    "and supply the appropriate symbols (manually — no LLM "
    "inference), then re-run this report."
)


_PER_EVENT_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_date",
    "headline",
    "stage",
    "persistence",
    "confidence",
    "suggested_next_action",
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_missing_tickers(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the missing-market-tickers triage report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Maximum number of per-event entries surfaced under
        ``events``.  ``events_missing_market_tickers`` always reflects
        every missing event in the archive — only the listed examples
        are truncated.  Negative values are clamped to ``0``.
    """
    capped_limit = max(int(limit), 0)
    empty: dict[str, Any] = _empty_report()

    path = _resolve_db_path(db_path)
    if path is None:
        return empty

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return empty

    try:
        try:
            rows = conn.execute(
                "SELECT id, event_date, headline, stage, persistence, "
                "confidence, market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            rows = []
    finally:
        conn.close()

    total_events = 0
    missing: list[dict[str, Any]] = []
    for raw in rows:
        try:
            event_id = int(raw[0])
        except (TypeError, ValueError):
            continue
        total_events += 1
        if _primary_ticker(raw[6]) is not None:
            continue
        missing.append({
            "event_id":              event_id,
            "event_date":            _none_if_blank(raw[1]),
            "headline":              _none_if_blank(raw[2]),
            "stage":                 _none_if_blank(raw[3]),
            "persistence":           _none_if_blank(raw[4]),
            "confidence":            _none_if_blank(raw[5]),
            "suggested_next_action": _SUGGESTED_NEXT_ACTION,
        })

    truncated = missing[:capped_limit]

    return {
        "total_events":                  total_events,
        "events_missing_market_tickers": len(missing),
        "events":                        truncated,
        "recommended_next_action":       _recommend(total_events, len(missing)),
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":                  0,
        "events_missing_market_tickers": 0,
        "events":                        [],
        "recommended_next_action":       _RECOMMENDED_NO_EVENTS,
    }


def _recommend(total_events: int, missing_count: int) -> str:
    if total_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if missing_count == 0:
        return _RECOMMENDED_OK
    return _RECOMMENDED_GAPS


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def _none_if_blank(value: Any) -> str | None:
    """Return ``value`` only if it's a non-empty string; else ``None``.

    Defensive against the historical messiness of the archive: NULL,
    empty strings, and non-string types all collapse to ``None`` so a
    JSON consumer sees a single missing-value sentinel.
    """
    if not isinstance(value, str) or not value:
        return None
    return value


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Missing market_tickers triage report", ""]
    lines.append(f"Total events:                    {report['total_events']}")
    lines.append(
        f"  events missing market_tickers: "
        f"{report['events_missing_market_tickers']}"
    )
    lines.append("")

    events = report.get("events") or []
    lines.append(f"Events listed ({len(events)}):")
    if events:
        for entry in events:
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"stage={entry.get('stage') or '-'} "
                f"persistence={entry.get('persistence') or '-'} "
                f"confidence={entry.get('confidence') or '-'}"
            )
            headline = entry.get("headline") or "-"
            lines.append(f"      headline: {headline}")
            lines.append(
                f"      suggested_next_action: "
                f"{entry.get('suggested_next_action')}"
            )
    else:
        lines.append("  -")
    lines.append("")
    lines.append(f"Recommended next action: {report['recommended_next_action']}")
    return "\n".join(lines)


def _render_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True, default=str)


def _render_csv(report: dict[str, Any]) -> str:
    """Return CSV: header + one row per surfaced event.

    Totals are intentionally omitted — CSV is for pipelining downstream
    tooling, and a totals row would break a naïve ``DictReader``
    consumer.  Operators who need the totals can use ``--json`` (or the
    default text mode).
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(_PER_EVENT_FIELDS)
    for entry in report.get("events") or []:
        writer.writerow([
            entry.get(field) if entry.get(field) is not None else ""
            for field in _PER_EVENT_FIELDS
        ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only triage report for events with missing "
            "market_tickers.  Surfaces event_id, event_date, "
            "headline, stage, persistence, confidence, and a "
            "constant suggested_next_action of "
            "'manual_review_required' (no LLM inference, no ticker "
            "guessing).  Read-only: no INSERT / UPDATE / DELETE, no "
            "provider call, no LLM, no FastAPI surface."
        ),
    )
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    fmt.add_argument(
        "--csv",
        action="store_true",
        help=(
            "Emit CSV (header + one row per surfaced event).  Totals "
            "are omitted from CSV; use --json for the full payload."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=(
            f"Cap the surfaced per-event list at N entries (default "
            f"{_DEFAULT_LIMIT}).  events_missing_market_tickers "
            f"always reflects every missing event in the archive."
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

    report = summarize_missing_tickers(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    elif args.csv:
        # ``csv`` rendering already terminates each row with ``\n``;
        # ``end=""`` avoids an extra trailing blank line that would
        # confuse strict downstream parsers.
        print(_render_csv(report), file=output, end="")
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
