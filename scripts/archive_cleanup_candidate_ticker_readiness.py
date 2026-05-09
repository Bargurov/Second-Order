#!/usr/bin/env python3
"""Read-only ticker-readiness summary for archive cleanup candidates.

Builds on :mod:`scripts.archive_cleanup_candidate_report`: takes the
flat candidate list it surfaces, then asks a narrower question per
candidate event — does it carry market tickers, is its primary ticker
covered by ``price_cache``, and is it flagged as low-information?

The report exists so an operator triaging the cleanup queue can tell
at a glance how much follow-up work a delete pass would touch beyond
the headline-level filters: a candidate that *also* anchors a chunk of
``price_cache`` rows or whose primary ticker is the only path to a
benchmark proxy deserves a slower review than a stub event with no
ticker hookup at all.

Read-only by construction:

* Issues only ``SELECT`` statements; never INSERT / UPDATE / DELETE;
  never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM seam (``anthropic`` / ``openai``), no
  ``yfinance``, no ``market_check``, ``market_data``, no
  ``price_cache.fetch_daily_cached``, no provider call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No deletion path.  Per-row deletion stays in the operator surface;
  this report only summarises *readiness columns* on the candidate
  set.

Patchable seam.  ``summarize_candidate_ticker_readiness`` reads
``summarize_cleanup_candidates`` through the imported module attribute
``_candidate_report`` and also accepts an optional
``candidate_report=`` kwarg for direct injection.  Tests and offline
callers can patch either the attribute or pass a pre-fetched dict —
matching the convention established in
``archive_cleanup_execution_plan`` and ``archive_cleanup_apply_plan``.

Column-name mapping.  The events table column is ``low_signal``; the
public output surface exposes the count under ``low_information_count``
to match the operator-facing language used in upstream reports
(``project_health_check.py``) and the task spec.

Output contract::

    {
      "candidate_count":            int,
      "tickers_present_count":      int,
      "price_cache_present_count":  int,
      "low_information_count":      int,
      "examples": [                          # capped at --limit, id asc
        {
          "event_id":           int,
          "headline":           str | None,
          "primary_ticker":     str | None,
          "has_market_tickers": bool,
          "has_price_cache":    bool,
          "low_information":    bool,
          "reasons":            list[str],
        },
        ...
      ],
      "recommended_next_action":    str,    # closed two-string vocabulary
    }

Aggregate counts always reflect every candidate event in the archive
— only the ``examples`` list is truncated by ``--limit``.

Usage::

    python scripts/archive_cleanup_candidate_ticker_readiness.py
    python scripts/archive_cleanup_candidate_ticker_readiness.py --json
    python scripts/archive_cleanup_candidate_ticker_readiness.py --json --limit 20
    python scripts/archive_cleanup_candidate_ticker_readiness.py \\
                                                       --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import archive_cleanup_candidate_report as _candidate_report  # noqa: E402


_DEFAULT_LIMIT: int = 25
_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD: int = 3

# Internal "fetch all" sentinel for the upstream candidate-report call.
# We need every flagged candidate to compute aggregates over the full
# cleanup set; the user-facing ``--limit`` only caps the surfaced
# ``examples`` list.
_INTERNAL_FETCH_ALL: int = 10 ** 9


_RECOMMENDED_OK = (
    "No archive cleanup candidates detected; no ticker-readiness "
    "review required."
)
_RECOMMENDED_REVIEW = (
    "Cleanup candidates detected.  Review per-event ticker / "
    "price_cache / low_information columns to decide whether deletion "
    "via the operator path is safe; this report makes no DB writes."
)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


def _primary_ticker(raw_market_tickers: Any) -> str | None:
    """Return the first non-empty ``symbol`` in the JSON list, or ``None``.

    Tolerant of every malformed shape the archive carries: ``None``,
    ``""``, unparseable JSON, non-list payload, empty / blank / non-string
    symbol fields all collapse to ``None``.  Symbols are upper-cased to
    match the ``price_cache`` convention.

    Inlined (not imported from ``stat_validation_readiness_report``) so
    this module keeps a minimal dependency surface — every helper is
    pure and self-contained.
    """
    if raw_market_tickers is None:
        return None
    parsed: Any = raw_market_tickers
    if isinstance(parsed, str):
        if not parsed:
            return None
        try:
            parsed = json.loads(parsed)
        except (TypeError, ValueError):
            return None
    if not isinstance(parsed, list):
        return None
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        sym = entry.get("symbol")
        if not isinstance(sym, str):
            continue
        sym = sym.strip().upper()
        if sym:
            return sym
    return None


def _truthy_low_signal(value: Any) -> bool:
    """True iff ``value`` represents a 1 / true low-signal flag.

    The events ``low_signal`` column is stored as INTEGER 0/1 today,
    but historical migrations and a future schema change could land
    boolean strings ("1", "true") or actual ``bool`` values.  Any
    non-zero / non-False value flips the flag on.
    """
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        return v in ("1", "true", "yes", "y", "t")
    return False


def _empty_report() -> dict[str, Any]:
    return {
        "candidate_count":           0,
        "tickers_present_count":     0,
        "price_cache_present_count": 0,
        "low_information_count":     0,
        "examples":                  [],
        "recommended_next_action":   _RECOMMENDED_OK,
    }


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_candidate_ticker_readiness(
    *,
    db_path: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    fixture_timestamp_threshold: int = _DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
    candidate_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the candidate-ticker-readiness report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE``.  When neither resolves to a usable path, the
        report degrades cleanly to the empty-archive shape — no
        exception ever bubbles out.
    limit
        Maximum number of per-event entries surfaced under
        ``examples``.  Aggregate counts always reflect every candidate
        in the archive — only the surfaced examples are truncated.
        Negative values are clamped to ``0``.
    fixture_timestamp_threshold
        Forwarded to ``summarize_cleanup_candidates``.
    candidate_report
        Optional pre-fetched candidate-report dict.  When supplied,
        bypasses the underlying candidate-report SELECT entirely.
    """
    capped_limit = max(int(limit), 0)

    if candidate_report is None:
        candidate_report = _candidate_report.summarize_cleanup_candidates(
            db_path=db_path,
            limit=_INTERNAL_FETCH_ALL,
            fixture_timestamp_threshold=fixture_timestamp_threshold,
        )

    candidate_count = int(candidate_report.get("candidate_count", 0) or 0)
    raw_examples = candidate_report.get("examples") or []

    # Deduplicate while preserving id-ascending order — the candidate
    # report already lists each flagged event once with its full
    # ``reasons`` set.
    candidate_ids: list[int] = []
    reasons_by_id: dict[int, list[str]] = {}
    seen: set[int] = set()
    for ex in raw_examples:
        if not isinstance(ex, dict):
            continue
        try:
            eid = int(ex["event_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if eid in seen:
            continue
        seen.add(eid)
        candidate_ids.append(eid)
        reasons_by_id[eid] = sorted(
            r for r in (ex.get("reasons") or []) if isinstance(r, str)
        )

    if candidate_count == 0 or not candidate_ids:
        return _empty_report()

    # Resolve DB path for the per-candidate SELECTs.  We never connect
    # for write — the queries below are SELECTs against ``events`` and
    # ``price_cache`` only.
    path = _resolve_db_path(db_path)
    events_data: dict[int, dict[str, Any]] = {}
    cache_tickers: set[str] = set()

    if path is not None:
        try:
            conn = sqlite3.connect(path)
        except sqlite3.Error:
            conn = None  # type: ignore[assignment]

        if conn is not None:
            try:
                # Fetch the candidate rows in a single chunked IN-list.
                # SQLite caps host parameters at ~999 on older builds;
                # split the candidate id list at a conservative 500.
                CHUNK = 500
                for start in range(0, len(candidate_ids), CHUNK):
                    chunk = candidate_ids[start:start + CHUNK]
                    placeholders = ",".join("?" * len(chunk))
                    try:
                        rows = conn.execute(
                            f"SELECT id, headline, market_tickers, low_signal "
                            f"FROM events WHERE id IN ({placeholders})",
                            chunk,
                        ).fetchall()
                    except sqlite3.Error:
                        rows = []
                    for raw_id, headline, market_tickers, low_signal in rows:
                        try:
                            eid = int(raw_id)
                        except (TypeError, ValueError):
                            continue
                        events_data[eid] = {
                            "headline":       headline,
                            "market_tickers": market_tickers,
                            "low_signal":     low_signal,
                        }

                # Distinct ticker set in price_cache — a single SELECT
                # avoids per-candidate fan-out and matches what
                # ``has_price_cache`` actually checks (existence of any
                # row keyed by ticker).
                try:
                    cache_rows = conn.execute(
                        "SELECT DISTINCT ticker FROM price_cache "
                        "WHERE ticker IS NOT NULL AND ticker != ''"
                    ).fetchall()
                except sqlite3.Error:
                    cache_rows = []
                for (raw_ticker,) in cache_rows:
                    if isinstance(raw_ticker, str) and raw_ticker.strip():
                        cache_tickers.add(raw_ticker.strip().upper())
            finally:
                conn.close()

    # Per-candidate compute.  Every flag degrades to ``False`` cleanly
    # when the upstream row is missing — a candidate id we cannot
    # resolve in the events table is simply "not ready" on every axis
    # rather than crashing the report.
    examples: list[dict[str, Any]] = []
    tickers_present_count     = 0
    price_cache_present_count = 0
    low_information_count     = 0

    for eid in candidate_ids:
        info     = events_data.get(eid, {})
        primary  = _primary_ticker(info.get("market_tickers"))
        has_t    = primary is not None
        has_pc   = has_t and primary in cache_tickers
        is_low   = _truthy_low_signal(info.get("low_signal"))

        if has_t:
            tickers_present_count += 1
        if has_pc:
            price_cache_present_count += 1
        if is_low:
            low_information_count += 1

        headline = info.get("headline")
        examples.append({
            "event_id":           eid,
            "headline":           headline if isinstance(headline, str) else None,
            "primary_ticker":     primary,
            "has_market_tickers": has_t,
            "has_price_cache":    has_pc,
            "low_information":    is_low,
            "reasons":            list(reasons_by_id.get(eid, [])),
        })

    truncated = examples[:capped_limit]

    return {
        "candidate_count":           candidate_count,
        "tickers_present_count":     tickers_present_count,
        "price_cache_present_count": price_cache_present_count,
        "low_information_count":     low_information_count,
        "examples":                  truncated,
        "recommended_next_action": (
            _RECOMMENDED_OK if candidate_count == 0 else _RECOMMENDED_REVIEW
        ),
    }


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Archive cleanup candidate ticker readiness", ""]
    lines.append(
        f"Candidate events flagged:                  {report['candidate_count']}"
    )
    lines.append(
        f"  with market_tickers populated:           {report['tickers_present_count']}"
    )
    lines.append(
        f"  with price_cache coverage (primary):     {report['price_cache_present_count']}"
    )
    lines.append(
        f"  flagged low_information (low_signal=1):  {report['low_information_count']}"
    )
    lines.append("")

    examples = report.get("examples") or []
    lines.append(f"Examples listed ({len(examples)}):")
    if examples:
        for entry in examples:
            headline = (entry.get("headline") or "").strip() or "-"
            if len(headline) > 80:
                headline = headline[:77] + "..."
            lines.append(
                f"  id={entry['event_id']} "
                f"primary_ticker={entry.get('primary_ticker') or '-'} "
                f"tickers={entry['has_market_tickers']} "
                f"price_cache={entry['has_price_cache']} "
                f"low_info={entry['low_information']}"
            )
            lines.append(f"      headline: {headline}")
            reasons = entry.get("reasons") or []
            lines.append(f"      reasons:  {', '.join(reasons) if reasons else '-'}")
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
            "Read-only ticker-readiness summary for archive cleanup "
            "candidates.  Builds on archive_cleanup_candidate_report "
            "and surfaces, per candidate, whether market_tickers is "
            "populated, whether the primary ticker is covered by "
            "price_cache, and whether the row is flagged "
            "low-information.  Read-only: issues only SELECT "
            "statements; this script makes no DB writes."
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
            f"reflect every candidate in the archive."
        ),
    )
    parser.add_argument(
        "--db-path",
        dest="db_path",
        default=None,
        help=(
            "Optional path to a SQLite events.db file.  Forwarded to "
            "summarize_cleanup_candidates and to the per-candidate "
            "SELECTs.  Defaults to db.DB_FILE."
        ),
    )
    parser.add_argument(
        "--fixture-timestamp-threshold",
        dest="fixture_timestamp_threshold",
        type=int,
        default=_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD,
        help=(
            f"Forwarded to summarize_cleanup_candidates "
            f"(default {_DEFAULT_FIXTURE_TIMESTAMP_THRESHOLD}).  "
            f"Values < 2 are clamped to 2 by the upstream."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_candidate_ticker_readiness(
        db_path=args.db_path,
        limit=args.limit,
        fixture_timestamp_threshold=args.fixture_timestamp_threshold,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


__all__: tuple[str, ...] = (
    "summarize_candidate_ticker_readiness",
    "main",
)


if __name__ == "__main__":
    sys.exit(main())
