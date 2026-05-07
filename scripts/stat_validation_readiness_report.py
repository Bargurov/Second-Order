#!/usr/bin/env python3
"""Read-only archive statistical-readiness coverage report.

Walks the events archive once and answers, per event, "could the
event-study engine in :mod:`stats.event_study` actually produce a
record for this row given what the price cache currently has?"

Five binary readiness checks are computed per event:

  * ``has_event_date``                — non-empty ISO event_date.
  * ``has_market_tickers``            — at least one non-empty symbol
                                        in the stored ``market_tickers``
                                        JSON list.
  * ``forward_cache_1d``              — price_cache has at least one
                                        row for the **primary ticker**
                                        (the first non-empty symbol)
                                        with ``date >= event_date +
                                        1 business day``.
  * ``forward_cache_5d`` / ``_20d``   — same, with horizons 5 and 20.
  * ``benchmark_proxy_available``     — price_cache has at least one
                                        row for ``SPY`` with
                                        ``date >= event_date + 20bd``.
                                        ``SPY`` is the project's
                                        universal benchmark fallback
                                        (see ``market_check._DEFAULT_BENCHMARK``).
  * ``estimation_window_sufficient``  — at least 60 distinct cached
                                        dates strictly before the
                                        event_date for the primary
                                        ticker, matching
                                        ``stats.event_study._DEFAULT_ESTIMATION_WINDOW``.

``fully_ready`` is the AND of every above check.  Per-event checks
that depend on a parsed event_date or a primary ticker degrade to
``False`` cleanly when those inputs are missing — there is no
exception path.

Top-level aggregates count every event in the archive (no ``--limit``
truncation); the ``events`` list is capped at ``--limit`` and sorted
by ``id`` ascending so the surfaced sample is deterministic.

Output contract::

    {
      "total_events":                            int,
      "events_with_event_date":                  int,
      "events_with_market_tickers":              int,
      "events_with_event_date_and_tickers":      int,
      "events_with_1d_forward_cache":            int,
      "events_with_5d_forward_cache":            int,
      "events_with_20d_forward_cache":           int,
      "events_missing_benchmark_proxy":          int,
      "events_with_insufficient_estimation_window": int,
      "events_fully_ready":                      int,
      "events": [                          # capped at --limit, id asc
        {
          "event_id":         int,
          "event_date":       str | None,
          "primary_ticker":   str | None,
          "checks": {
            "has_event_date":               bool,
            "has_market_tickers":           bool,
            "forward_cache_1d":             bool,
            "forward_cache_5d":             bool,
            "forward_cache_20d":            bool,
            "benchmark_proxy_available":    bool,
            "estimation_window_sufficient": bool,
          },
          "fully_ready": bool,
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE; never calls ``_ensure_table`` / ``init_db``.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* No event-study compute — this report only measures *readiness*,
  not the abnormal returns themselves.

Usage::

    python scripts/stat_validation_readiness_report.py
    python scripts/stat_validation_readiness_report.py --json
    python scripts/stat_validation_readiness_report.py --json --limit 20
    python scripts/stat_validation_readiness_report.py --db-path ./events.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_LIMIT = 25

# Mirrors ``stats.event_study._DEFAULT_ESTIMATION_WINDOW`` and
# ``market_check._DEFAULT_BENCHMARK`` so the readiness check stays
# aligned with what the compute path actually requires.  Inlined here
# (not imported) so the report keeps its no-project-imports posture
# for the SELECT path.
_ESTIMATION_WINDOW: int = 60
_BENCHMARK_TICKER:  str = "SPY"
_HORIZONS:          tuple[int, ...] = (1, 5, 20)


_RECOMMENDED_OK = (
    "Every event in the archive has the cache coverage needed to run "
    "the event-study engine over 1d/5d/20d horizons."
)
_RECOMMENDED_GAPS = (
    "Some events lack the cache coverage needed for the event-study "
    "engine.  Refresh the price cache for the listed primary tickers "
    "and SPY benchmark, then re-run this report."
)


# ---------------------------------------------------------------------------
# Pure SQL probe + compute
# ---------------------------------------------------------------------------


def summarize_readiness(
    *, db_path: str | None = None, limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    """Return the statistical-readiness coverage report dict.

    See module docstring for the full output contract.

    Parameters
    ----------
    db_path
        Optional path to a SQLite events.db file.  When omitted, reads
        ``db.DB_FILE`` so the report follows the project's configured
        archive.
    limit
        Maximum number of per-event entries surfaced under
        ``events``.  The aggregate counts always reflect every event
        in the archive — only the listed examples are truncated.
        Negative values are clamped to ``0``.
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
            event_rows = conn.execute(
                "SELECT id, event_date, market_tickers FROM events ORDER BY id"
            ).fetchall()
        except sqlite3.Error:
            event_rows = []

        try:
            cache_rows = conn.execute(
                "SELECT ticker, date FROM price_cache "
                "WHERE ticker IS NOT NULL AND ticker != '' "
                "  AND date IS NOT NULL AND date != ''"
            ).fetchall()
        except sqlite3.Error:
            cache_rows = []
    finally:
        conn.close()

    cache_dates_by_ticker = _group_cache_dates(cache_rows)

    # Per-event compute -------------------------------------------------------
    per_event: list[dict[str, Any]] = []
    for raw_id, raw_event_date, raw_market_tickers in event_rows:
        try:
            event_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        event_date_str = raw_event_date if isinstance(raw_event_date, str) else None
        primary_ticker = _primary_ticker(raw_market_tickers)
        has_event_date = _parse_iso_date(event_date_str) is not None
        has_market_tickers = primary_ticker is not None
        event_d = _parse_iso_date(event_date_str)

        forward = {
            h: _has_forward_cache_row(
                cache_dates_by_ticker, primary_ticker, event_d, h,
            )
            for h in _HORIZONS
        }
        benchmark_ok = _has_forward_cache_row(
            cache_dates_by_ticker, _BENCHMARK_TICKER, event_d, max(_HORIZONS),
        )
        est_ok = _has_estimation_window(
            cache_dates_by_ticker, primary_ticker, event_d,
            window=_ESTIMATION_WINDOW,
        )

        checks = {
            "has_event_date":               has_event_date,
            "has_market_tickers":           has_market_tickers,
            "forward_cache_1d":             forward[1],
            "forward_cache_5d":             forward[5],
            "forward_cache_20d":            forward[20],
            "benchmark_proxy_available":    benchmark_ok,
            "estimation_window_sufficient": est_ok,
        }
        fully_ready = all(checks.values())
        per_event.append({
            "event_id":       event_id,
            "event_date":     event_date_str if isinstance(event_date_str, str) and event_date_str else None,
            "primary_ticker": primary_ticker,
            "checks":         checks,
            "fully_ready":    fully_ready,
        })

    # Aggregates --------------------------------------------------------------
    total_events = len(per_event)
    n_event_date          = sum(1 for e in per_event if e["checks"]["has_event_date"])
    n_market_tickers      = sum(1 for e in per_event if e["checks"]["has_market_tickers"])
    n_both                = sum(
        1 for e in per_event
        if e["checks"]["has_event_date"] and e["checks"]["has_market_tickers"]
    )
    n_forward_1d          = sum(1 for e in per_event if e["checks"]["forward_cache_1d"])
    n_forward_5d          = sum(1 for e in per_event if e["checks"]["forward_cache_5d"])
    n_forward_20d         = sum(1 for e in per_event if e["checks"]["forward_cache_20d"])
    n_missing_benchmark   = sum(
        1 for e in per_event if not e["checks"]["benchmark_proxy_available"]
    )
    n_insufficient_est    = sum(
        1 for e in per_event if not e["checks"]["estimation_window_sufficient"]
    )
    n_fully_ready         = sum(1 for e in per_event if e["fully_ready"])

    # Per-event entries are already in id-ascending order from the
    # SQL ``ORDER BY id`` above; cap at the requested limit.
    truncated = per_event[:capped_limit]

    return {
        "total_events":                                total_events,
        "events_with_event_date":                      n_event_date,
        "events_with_market_tickers":                  n_market_tickers,
        "events_with_event_date_and_tickers":          n_both,
        "events_with_1d_forward_cache":                n_forward_1d,
        "events_with_5d_forward_cache":                n_forward_5d,
        "events_with_20d_forward_cache":               n_forward_20d,
        "events_missing_benchmark_proxy":              n_missing_benchmark,
        "events_with_insufficient_estimation_window":  n_insufficient_est,
        "events_fully_ready":                          n_fully_ready,
        "events":                                      truncated,
        "recommended_next_action": (
            _RECOMMENDED_OK
            if total_events > 0 and n_fully_ready == total_events
            else _RECOMMENDED_GAPS
        ),
    }


def _empty_report() -> dict[str, Any]:
    return {
        "total_events":                                0,
        "events_with_event_date":                      0,
        "events_with_market_tickers":                  0,
        "events_with_event_date_and_tickers":          0,
        "events_with_1d_forward_cache":                0,
        "events_with_5d_forward_cache":                0,
        "events_with_20d_forward_cache":               0,
        "events_missing_benchmark_proxy":              0,
        "events_with_insufficient_estimation_window":  0,
        "events_fully_ready":                          0,
        "events":                                      [],
        # An empty archive isn't "fully ready" for downstream
        # event-study work — there's nothing to validate.  The gaps
        # message is the truthful default; an explicit no-events
        # phrasing would be a separate label without operator value.
        "recommended_next_action":                     _RECOMMENDED_GAPS,
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
# Pure helpers — small, isolated, easy to unit-test individually.
# ---------------------------------------------------------------------------


def _group_cache_dates(
    rows: Sequence[tuple],
) -> dict[str, set[str]]:
    """Collect ``{ticker_upper: {iso_date, ...}}`` from raw price_cache rows.

    The auto_adjust flag is intentionally ignored — the readiness
    check cares only that *some* row for the (ticker, date) key
    exists in the cache, regardless of which adjustment flag carries
    it.  Both flags' dates are unioned via ``set``.
    """
    out: dict[str, set[str]] = {}
    for raw_ticker, raw_date in rows:
        if not isinstance(raw_ticker, str) or not raw_ticker:
            continue
        if not isinstance(raw_date, str) or not raw_date:
            continue
        out.setdefault(raw_ticker.upper(), set()).add(raw_date)
    return out


def _parse_iso_date(value: Any) -> _date | None:
    """Return ``date`` for ISO ``YYYY-MM-DD`` strings; else ``None``.

    Defensive against the historical messiness of the archive: empty
    strings, non-string types, malformed dates, and date-time strings
    longer than 10 chars (we accept those by trimming to the first 10
    chars, matching ``price_cache.read_window_no_fetch``).
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _primary_ticker(raw_market_tickers: Any) -> str | None:
    """Return the first non-empty ``symbol`` in the JSON list, or ``None``.

    Tolerant of every malformed shape the archive carries:

      * ``None`` / ``""``                 → ``None``
      * unparseable JSON                   → ``None``
      * non-list payload                   → ``None``
      * list with no dict entries          → ``None``
      * list with empty/blank symbols      → ``None``
      * list with non-string symbol fields → ``None``

    Symbols are upper-cased to match the price_cache convention.
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


def _business_day_offset(start: _date, n: int) -> _date:
    """Shift ``start`` forward by ``n`` business days.

    Matches ``scripts.auto_adjust_mismatch_repair_preview._business_day_offset``
    so the readiness check uses the same business-day calendar as the
    no_forward_20d hydrator and the diagnostics surface.  ``n <= 0``
    returns ``start`` unchanged.
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + _timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _has_forward_cache_row(
    cache_dates_by_ticker: dict[str, set[str]],
    ticker: str | None,
    event_d: _date | None,
    horizon_business_days: int,
) -> bool:
    """True iff the cache has any row for ``ticker`` on or after the
    horizon-shifted event date.

    Returns ``False`` for missing ticker, missing event_date, or empty
    cache — every degraded path collapses to "not ready" cleanly.
    """
    if ticker is None or event_d is None:
        return False
    target = _business_day_offset(event_d, horizon_business_days)
    target_iso = target.isoformat()
    dates = cache_dates_by_ticker.get(ticker.upper())
    if not dates:
        return False
    # ISO-formatted YYYY-MM-DD strings sort lexicographically the same
    # as chronological order, so a string ``>= target_iso`` test is
    # exactly the chronological "on or after" check.
    return any(d >= target_iso for d in dates)


def _has_estimation_window(
    cache_dates_by_ticker: dict[str, set[str]],
    ticker: str | None,
    event_d: _date | None,
    *,
    window: int,
) -> bool:
    """True iff the cache has at least ``window`` distinct dates
    strictly before ``event_d`` for ``ticker``.

    The check is "distinct dates", not "rows" — auto_adjust=0 and
    auto_adjust=1 holding the same date count once.  This matches
    the event-study convention that the estimation window is a
    sequence of pre-event business-day closes, not a row count.
    """
    if ticker is None or event_d is None:
        return False
    dates = cache_dates_by_ticker.get(ticker.upper())
    if not dates:
        return False
    event_iso = event_d.isoformat()
    pre_count = sum(1 for d in dates if d < event_iso)
    return pre_count >= window


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Archive statistical-readiness coverage report", ""]
    lines.append(f"Total events:                                  {report['total_events']}")
    lines.append(f"  with event_date:                             {report['events_with_event_date']}")
    lines.append(f"  with market_tickers:                         {report['events_with_market_tickers']}")
    lines.append(f"  with both:                                   {report['events_with_event_date_and_tickers']}")
    lines.append(f"  forward cache ready (1d):                    {report['events_with_1d_forward_cache']}")
    lines.append(f"  forward cache ready (5d):                    {report['events_with_5d_forward_cache']}")
    lines.append(f"  forward cache ready (20d):                   {report['events_with_20d_forward_cache']}")
    lines.append(f"  missing benchmark proxy ({_BENCHMARK_TICKER}):              {report['events_missing_benchmark_proxy']}")
    lines.append(f"  insufficient estimation window (<{_ESTIMATION_WINDOW}d):       {report['events_with_insufficient_estimation_window']}")
    lines.append(f"  fully ready:                                 {report['events_fully_ready']}")
    lines.append("")

    events = report["events"]
    lines.append(f"Events listed ({len(events)}):")
    if events:
        for entry in events:
            checks = entry.get("checks") or {}
            failed = sorted(k for k, v in checks.items() if v is False)
            failed_str = ", ".join(failed) if failed else "-"
            lines.append(
                f"  id={entry.get('event_id')} "
                f"date={entry.get('event_date') or '-'} "
                f"ticker={entry.get('primary_ticker') or '-'} "
                f"fully_ready={entry.get('fully_ready')}"
            )
            lines.append(f"      failed_checks: {failed_str}")
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
            "Read-only archive statistical-readiness coverage report.  "
            "Walks the events archive once and counts how many rows "
            "have the cache coverage needed to drive the event-study "
            "engine.  Read-only: no INSERT / UPDATE / DELETE, no "
            "provider call, no LLM, no FastAPI surface."
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
            f"Cap the surfaced per-event list at N entries (default "
            f"{_DEFAULT_LIMIT}).  Aggregate counts always reflect "
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

    report = summarize_readiness(db_path=args.db_path, limit=args.limit)
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
