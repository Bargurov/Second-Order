#!/usr/bin/env python3
"""Read-only archive cleanup-candidate report.

Walks the events archive once and flags rows that look like cleanup
candidates: test-fixture leakage (e.g. ``Macro shock test event`` 12×
in the live archive, ``Insufficient evidence.`` mocks left behind by
test runs), rotating macro headline templates that recur as scraper
noise (``Fed speakers rotate``, ``Turkey lira weakens``,
``OPEC slashes output by 2 mbpd``, ``Tech CEO steps down``), fixture-
shaped timestamp clusters (≥ N rows sharing the same ``timestamp``
string — the smoking-gun signature of a test seed leak), and duplicate
``(headline, event_date)`` clusters.

The report is read-only by construction:

* Issues only ``SELECT`` statements; never INSERT / UPDATE / DELETE;
  never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No deletion path.  Per-row deletion stays in the operator surface;
  this report only surfaces *candidates* and explicitly disclaims
  writes in its ``recommended_next_action`` string.

Detection rules (each is a pure function on a single event row, then
aggregated over the archive):

  * ``test_fixture_phrase``           — headline contains a literal
                                        substring (case-insensitive)
                                        from a tight allow-list.
  * ``rotating_macro_template``       — headline contains a literal
                                        substring (case-insensitive)
                                        from a tight allow-list of
                                        scraper-noise / synthetic-feed
                                        templates we have direct
                                        evidence for in the live
                                        archive.
  * ``fixture_timestamp_cluster``     — the event's ``timestamp`` is
                                        shared by ≥ N other rows for
                                        the same ``timestamp`` string
                                        (default N=3, CLI-overridable).
                                        Blank timestamps are excluded.
  * ``duplicate_headline_event_date`` — the event is part of a
                                        ``(headline, event_date)``
                                        cluster of size ≥ 2.  Blank
                                        headline or event_date rows
                                        are excluded so duplicates do
                                        not double-count with the
                                        missing-* categories already
                                        surfaced by archive
                                        consistency.

Output contract::

    {
      "candidate_count":              int,
      "reasons": {
        "test_fixture_phrase":             int,
        "rotating_macro_template":         int,
        "fixture_timestamp_cluster":       int,
        "duplicate_headline_event_date":   int,
      },
      "examples": [                   # capped at --limit, id ascending
        {
          "event_id":   int,
          "headline":   str | None,
          "timestamp":  str | None,
          "event_date": str | None,
          "reasons":    list[str],   # subset of the four reason keys
                                     # above; sorted, deduplicated,
                                     # always non-empty
        },
        ...
      ],
      "fixture_timestamp_threshold":  int,
      "recommended_next_action":      str,    # one of the two pinned
                                              # vocabulary strings
    }

Aggregate counts always reflect every event in the archive — only the
``examples`` list is truncated by ``--limit``.

Usage::

    python scripts/archive_cleanup_candidate_report.py
    python scripts/archive_cleanup_candidate_report.py --json
    python scripts/archive_cleanup_candidate_report.py --json --limit 20
    python scripts/archive_cleanup_candidate_report.py --db-path ./events.db --json
    python scripts/archive_cleanup_candidate_report.py --json \
                                                       --fixture-timestamp-threshold 2
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT: int = 25
_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD: int = 3


# ---------------------------------------------------------------------------
# Detection allow-lists.  Every entry is evidence-based: each string was
# observed verbatim in the live archive at audit time (counts noted in
# the comments) or is a known canonical seed string from the test
# surface.  Adding to either list is a deliberate operator choice; the
# tests pin the *behaviour* of the matcher, not the contents of the
# lists, so additions do not require test changes.
# ---------------------------------------------------------------------------


# Test-fixture phrases — substring match (case-insensitive).
_TEST_FIXTURE_PHRASES: tuple[str, ...] = (
    "macro shock test event",       # 12× live (audit ULTRA_REVIEW.md)
    "no-paid smoke seed event",     # canonical seed, tests/test_no_paid_smoke.py
    "insufficient evidence.",       # mock string, analyze_event.py:3358 leak
    "smoke seed",
    "fixture event",
    "test event",
    "seed event",
)


# Rotating-macro / scraper-noise templates — substring match
# (case-insensitive).  Each entry was observed verbatim in the live
# archive with high recurrence at audit time.
_ROTATING_MACRO_TEMPLATES: tuple[str, ...] = (
    "fed speakers rotate",          # 33× live
    "turkey lira weakens",          # 33× live
    "opec slashes output",          # 21× live
    "tech ceo steps down",          # 13× live
)


# Reason keys appear in both the per-event ``reasons`` list and the
# top-level ``reasons`` counter.  The counter always carries every key
# (zero-filled) so downstream consumers can branch on a known shape.
_REASON_TEST_FIXTURE_PHRASE         = "test_fixture_phrase"
_REASON_ROTATING_MACRO_TEMPLATE     = "rotating_macro_template"
_REASON_FIXTURE_TIMESTAMP_CLUSTER   = "fixture_timestamp_cluster"
_REASON_DUPLICATE_HEADLINE_EVT_DATE = "duplicate_headline_event_date"


_REASON_KEYS: tuple[str, ...] = (
    _REASON_TEST_FIXTURE_PHRASE,
    _REASON_ROTATING_MACRO_TEMPLATE,
    _REASON_FIXTURE_TIMESTAMP_CLUSTER,
    _REASON_DUPLICATE_HEADLINE_EVT_DATE,
)


# Closed two-string vocabulary for ``recommended_next_action``.  The
# "candidates" string explicitly disclaims writes so an operator cannot
# mistake the report for a deletion tool.
_RECOMMENDED_OK = "No archive cleanup candidates detected."
_RECOMMENDED_CANDIDATES = (
    "Cleanup candidates detected.  Review the listed events and "
    "decide whether to delete them via the operator path; this "
    "report makes no DB writes."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _is_blank(value: Any) -> bool:
    """True iff ``value`` is None / non-string / blank-after-strip."""
    if value is None:
        return True
    if not isinstance(value, str):
        return True
    return value.strip() == ""


def _matches_any_phrase(headline: Any, phrases: Sequence[str]) -> bool:
    """Case-insensitive substring match against ``phrases``."""
    if not isinstance(headline, str) or not headline:
        return False
    lower = headline.lower()
    return any(p in lower for p in phrases)


def _empty_report(threshold: int) -> dict[str, Any]:
    return {
        "candidate_count":              0,
        "reasons": {key: 0 for key in _REASON_KEYS},
        "examples":                     [],
        "fixture_timestamp_threshold":  threshold,
        "recommended_next_action":      _RECOMMENDED_OK,
    }


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_cleanup_candidates(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    fixture_timestamp_threshold: int = _DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
) -> dict[str, Any]:
    """Return the cleanup-candidate report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.  When the path resolves to ``None`` or the connection
        fails, the report degrades cleanly to the empty-archive shape
        — no exception ever bubbles out.
    limit
        Maximum number of per-event entries surfaced under
        ``examples``.  The aggregate counts always reflect every
        flagged event in the archive — only the listed examples are
        truncated.  Negative values are clamped to ``0``.
    fixture_timestamp_threshold
        Minimum cluster size (≥ 2) that flips the
        ``fixture_timestamp_cluster`` reason on for every row sharing
        a non-blank ``timestamp`` string with at least
        ``fixture_timestamp_threshold - 1`` other rows.  Defaults to
        ``3``; pinned in the report so a downstream consumer can read
        the threshold the run used.
    """
    capped_limit = max(int(limit), 0)
    threshold = max(int(fixture_timestamp_threshold), 2)

    path = _resolve_db_path(db_path)
    if path is None:
        return _empty_report(threshold)

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return _empty_report(threshold)

    try:
        try:
            event_rows = conn.execute(
                "SELECT id, headline, timestamp, event_date "
                "FROM events ORDER BY id ASC"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []
    finally:
        conn.close()

    if not event_rows:
        return _empty_report(threshold)

    # Pass 1 — build cluster aggregates over non-blank values.  The
    # in-Python aggregate keeps the SQL surface to a single SELECT and
    # makes the per-row classification a pure dict-lookup.
    timestamp_counts: Counter[str] = Counter()
    headline_event_date_counts: Counter[tuple[str, str]] = Counter()
    for _id, headline, timestamp, event_date in event_rows:
        if not _is_blank(timestamp):
            assert isinstance(timestamp, str)
            timestamp_counts[timestamp] += 1
        if not _is_blank(headline) and not _is_blank(event_date):
            assert isinstance(headline, str)
            assert isinstance(event_date, str)
            headline_event_date_counts[(headline, event_date)] += 1

    # Pass 2 — classify each event.  Reasons are accumulated into a set
    # per event, then sorted for a stable, deduplicated ``reasons``
    # list downstream consumers can compare for equality.
    reasons_counter: Counter[str] = Counter()
    flagged_examples: list[dict[str, Any]] = []

    for raw_id, headline, timestamp, event_date in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue

        flags: set[str] = set()

        if _matches_any_phrase(headline, _TEST_FIXTURE_PHRASES):
            flags.add(_REASON_TEST_FIXTURE_PHRASE)

        if _matches_any_phrase(headline, _ROTATING_MACRO_TEMPLATES):
            flags.add(_REASON_ROTATING_MACRO_TEMPLATE)

        if (not _is_blank(timestamp)
                and timestamp_counts[timestamp] >= threshold):
            flags.add(_REASON_FIXTURE_TIMESTAMP_CLUSTER)

        if (not _is_blank(headline)
                and not _is_blank(event_date)
                and headline_event_date_counts[(headline, event_date)] >= 2):
            flags.add(_REASON_DUPLICATE_HEADLINE_EVT_DATE)

        if not flags:
            continue

        for f in flags:
            reasons_counter[f] += 1

        flagged_examples.append({
            "event_id":   event_id,
            "headline":   headline if isinstance(headline, str) else None,
            "timestamp":  timestamp if isinstance(timestamp, str) else None,
            "event_date": event_date if isinstance(event_date, str) else None,
            "reasons":    sorted(flags),
        })

    # event_rows came from an ``ORDER BY id ASC`` SELECT, and every row
    # we appended preserved that ordering, so id-ascending is already
    # the natural order of ``flagged_examples``.  Truncate after that.
    truncated = flagged_examples[:capped_limit]

    candidate_count = len(flagged_examples)
    return {
        "candidate_count":              candidate_count,
        "reasons": {key: reasons_counter.get(key, 0) for key in _REASON_KEYS},
        "examples":                     truncated,
        "fixture_timestamp_threshold":  threshold,
        "recommended_next_action": (
            _RECOMMENDED_OK if candidate_count == 0 else _RECOMMENDED_CANDIDATES
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Archive cleanup candidate report", ""]
    lines.append(f"Candidate events flagged:                 {report['candidate_count']}")
    reasons = report["reasons"]
    lines.append(f"  test_fixture_phrase:                    {reasons[_REASON_TEST_FIXTURE_PHRASE]}")
    lines.append(f"  rotating_macro_template:                {reasons[_REASON_ROTATING_MACRO_TEMPLATE]}")
    lines.append(
        f"  fixture_timestamp_cluster (threshold={report['fixture_timestamp_threshold']}):"
        f"   {reasons[_REASON_FIXTURE_TIMESTAMP_CLUSTER]}"
    )
    lines.append(f"  duplicate_headline_event_date:          {reasons[_REASON_DUPLICATE_HEADLINE_EVT_DATE]}")
    lines.append("")

    examples = report["examples"]
    lines.append(f"Examples listed ({len(examples)}):")
    if examples:
        for entry in examples:
            headline = (entry.get("headline") or "").strip() or "-"
            if len(headline) > 80:
                headline = headline[:77] + "..."
            lines.append(
                f"  id={entry['event_id']} "
                f"ts={entry.get('timestamp') or '-'} "
                f"date={entry.get('event_date') or '-'}"
            )
            lines.append(f"      headline: {headline}")
            lines.append(f"      reasons:  {', '.join(entry.get('reasons') or [])}")
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
            "Read-only archive cleanup-candidate report.  Surfaces "
            "events that look like test-fixture leakage, rotating "
            "macro headline templates, fixture-shaped timestamp "
            "clusters, or duplicate (headline, event_date) clusters.  "
            "Read-only: no INSERT / UPDATE / DELETE, no provider call, "
            "no LLM, no FastAPI surface; report-only, never deletes."
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
            f"Cap the surfaced per-event examples list at N entries "
            f"(default {_DEFAULT_LIMIT}).  Aggregate counts always "
            f"reflect every flagged event in the archive."
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
        "--fixture-timestamp-threshold",
        dest="fixture_timestamp_threshold",
        type=int,
        default=_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
        help=(
            f"Minimum cluster size that flips fixture_timestamp_cluster "
            f"on (default {_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD}).  "
            f"Values < 2 are clamped to 2."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_cleanup_candidates(
        db_path=args.db_path,
        limit=args.limit,
        fixture_timestamp_threshold=args.fixture_timestamp_threshold,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
