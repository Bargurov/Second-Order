#!/usr/bin/env python3
"""Read-only benchmark sensitivity cache preflight.

Answers the operator question, "for a given list of events and a given
benchmark, can the existing local price_cache support running the
benchmark-sensitivity comparison, or is something missing?"

Default targets are events ``60`` and ``73`` against the ``XLE``
benchmark — the two events flagged in the manual-review backlog as
candidates for an XLE-vs-SPY sensitivity check.  Both inputs are
parameterizable so the same preflight covers other event lists or
other benchmarks (e.g., ``--benchmark XLF``, ``--event-ids 60,73,112``).

For every (event, benchmark) pair the preflight checks two cache
properties against the local ``price_cache``:

  * **Forward horizons** — the cache must hold a row for the ticker on
    or after the event date plus each required business-day horizon
    (default ``1, 5, 20``).
  * **Estimation window** — the cache must hold at least
    ``--estimation-window`` (default ``60``) distinct dates strictly
    before the event date.

Both checks run independently for the **primary ticker** (read from
``events.market_tickers[0]``) and for the **benchmark ticker**.  A
sensitivity comparison can run iff *both* checks pass for both
tickers.

When a check fails the preflight emits an actionable missing-coverage
range so the operator can plan a backfill without re-deriving the date
math.  Ranges are reported with ISO-formatted ``start`` / ``end`` dates
and a short ``reason`` token (``forward_horizon_gap`` /
``estimation_window_short`` / ``no_cache_for_ticker``).

Output contract (JSON)::

    {
      "ok":                       bool,    # ran without internal errors
      "checked_events":           int,
      "ready_count":              int,
      "blocked_count":            int,
      "rows": [
        {
          "event_id":                  int,
          "primary_ticker":            str | None,
          "benchmark_ticker":          str,
          "event_date":                str | None,
          "required_horizons":         list[int],
          "primary_cache_available":   bool,
          "benchmark_cache_available": bool,
          "missing_primary_ranges": [
            {"start": str, "end": str, "reason": str},
            ...
          ],
          "missing_benchmark_ranges": [
            {"start": str, "end": str, "reason": str},
            ...
          ],
          "can_run_sensitivity": bool,
          "blocker_reason":      str,
        },
        ...
      ],
      "recommended_next_action": str,
    }

Out of scope (deliberately)
---------------------------
* Read-only.  Issues only ``SELECT`` statements; never INSERT /
  UPDATE / DELETE.  Never backfills the cache or proposes a benchmark.
* No DB writes, no LLM, no ``yfinance``, no ``market_check``,
  ``market_data``, ``price_cache.fetch_daily_cached``, no provider
  call, no network.
* No FastAPI app surface — never imports ``api`` or ``routes.*``.
* Does not modify the benchmark-sensitivity logic itself; only
  reports cache readiness for it.
* Does not infer SPY-vs-XLE conclusions — surfaces cache state only.

Usage::

    python scripts/benchmark_sensitivity_preflight.py
    python scripts/benchmark_sensitivity_preflight.py --json
    python scripts/benchmark_sensitivity_preflight.py --json --event-ids 60,73
    python scripts/benchmark_sensitivity_preflight.py --json --benchmark SPY
    python scripts/benchmark_sensitivity_preflight.py --db-path ./events.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date as _date, timedelta as _timedelta
from pathlib import Path
from typing import Any, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


_DEFAULT_EVENT_IDS:        tuple[int, ...] = (60, 73)
_DEFAULT_BENCHMARK:        str             = "XLE"
_DEFAULT_HORIZONS:         tuple[int, ...] = (1, 5, 20)
_DEFAULT_ESTIMATION_WINDOW: int            = 60


_REASON_FORWARD:      str = "forward_horizon_gap"
_REASON_ESTIMATION:   str = "estimation_window_short"
_REASON_NO_CACHE:     str = "no_cache_for_ticker"


_BLOCKER_NO_EVENT_DATE: str = "missing_event_date"
_BLOCKER_NO_PRIMARY:    str = "missing_primary_ticker"
_BLOCKER_READY:         str = "ready"


# NYSE observed-closure calendar.  Inlined here (not imported from
# ``market_check``) so the default code path keeps the no-provider /
# no-fastapi import invariants pinned by ``TestImportIsolation``.
#
# Why this matters: the forward-horizon and estimation-window checks
# both compare ``price_cache`` rows against a date math that historically
# used weekday-only offsets (Mon-Fri).  That treats every NYSE-closed
# weekday — for example, 2026-01-01 — as a required trading day, so a
# row that can never exist would keep an event blocked.  This set lets
# the missing-range logic distinguish "the market was closed" from
# "the cache is short a real trading day".
#
# Coverage: 2024-2030, mirroring ``market_check._US_MARKET_HOLIDAYS``.
# A year missing from this set degrades to weekday-only behavior for
# that year (the conservative direction — never a false-clear).
_MARKET_HOLIDAYS: frozenset[_date] = frozenset({
    # 2024
    _date(2024, 1, 1),    # New Year's Day
    _date(2024, 1, 15),   # MLK Day
    _date(2024, 2, 19),   # Presidents' Day
    _date(2024, 3, 29),   # Good Friday
    _date(2024, 5, 27),   # Memorial Day
    _date(2024, 6, 19),   # Juneteenth
    _date(2024, 7, 4),    # Independence Day
    _date(2024, 9, 2),    # Labor Day
    _date(2024, 11, 28),  # Thanksgiving
    _date(2024, 12, 25),  # Christmas
    # 2025
    _date(2025, 1, 1),    # New Year's Day
    _date(2025, 1, 20),   # MLK Day
    _date(2025, 2, 17),   # Presidents' Day
    _date(2025, 4, 18),   # Good Friday
    _date(2025, 5, 26),   # Memorial Day
    _date(2025, 6, 19),   # Juneteenth
    _date(2025, 7, 4),    # Independence Day
    _date(2025, 9, 1),    # Labor Day
    _date(2025, 11, 27),  # Thanksgiving
    _date(2025, 12, 25),  # Christmas
    # 2026
    _date(2026, 1, 1),    # New Year's Day
    _date(2026, 1, 19),   # MLK Day
    _date(2026, 2, 16),   # Presidents' Day
    _date(2026, 4, 3),    # Good Friday
    _date(2026, 5, 25),   # Memorial Day
    _date(2026, 6, 19),   # Juneteenth
    _date(2026, 7, 3),    # Independence Day (obs. Fri)
    _date(2026, 9, 7),    # Labor Day
    _date(2026, 11, 26),  # Thanksgiving
    _date(2026, 12, 25),  # Christmas
    # 2027
    _date(2027, 1, 1),    # New Year's Day
    _date(2027, 1, 18),   # MLK Day
    _date(2027, 2, 15),   # Presidents' Day
    _date(2027, 3, 26),   # Good Friday
    _date(2027, 5, 31),   # Memorial Day
    _date(2027, 6, 18),   # Juneteenth (obs. Fri)
    _date(2027, 7, 5),    # Independence Day (obs. Mon)
    _date(2027, 9, 6),    # Labor Day
    _date(2027, 11, 25),  # Thanksgiving
    _date(2027, 12, 24),  # Christmas (obs. Fri)
    # 2028
    _date(2028, 1, 17),   # MLK Day
    _date(2028, 2, 21),   # Presidents' Day
    _date(2028, 4, 14),   # Good Friday
    _date(2028, 5, 29),   # Memorial Day
    _date(2028, 6, 19),   # Juneteenth
    _date(2028, 7, 4),    # Independence Day
    _date(2028, 9, 4),    # Labor Day
    _date(2028, 11, 23),  # Thanksgiving
    _date(2028, 12, 25),  # Christmas
    # 2029
    _date(2029, 1, 1),    # New Year's Day
    _date(2029, 1, 15),   # MLK Day
    _date(2029, 2, 19),   # Presidents' Day
    _date(2029, 3, 30),   # Good Friday
    _date(2029, 5, 28),   # Memorial Day
    _date(2029, 6, 19),   # Juneteenth
    _date(2029, 7, 4),    # Independence Day
    _date(2029, 9, 3),    # Labor Day
    _date(2029, 11, 22),  # Thanksgiving
    _date(2029, 12, 25),  # Christmas
    # 2030
    _date(2030, 1, 1),    # New Year's Day
    _date(2030, 1, 21),   # MLK Day
    _date(2030, 2, 18),   # Presidents' Day
    _date(2030, 4, 19),   # Good Friday
    _date(2030, 5, 27),   # Memorial Day
    _date(2030, 6, 19),   # Juneteenth
    _date(2030, 7, 4),    # Independence Day
    _date(2030, 9, 2),    # Labor Day
    _date(2030, 11, 28),  # Thanksgiving
    _date(2030, 12, 25),  # Christmas
})


_RECOMMENDED_NO_EVENTS = (
    "No events were checked — supply --event-ids and re-run."
)
_RECOMMENDED_ALL_READY = (
    "All {n} checked event(s) have primary and benchmark cache "
    "coverage sufficient to run benchmark sensitivity against {bench}."
)
_RECOMMENDED_BLOCKED = (
    "{blocked} of {n} checked event(s) are blocked from {bench} "
    "benchmark sensitivity by missing price_cache coverage.  Inspect "
    "'missing_primary_ranges' and 'missing_benchmark_ranges' per row "
    "and backfill the listed date ranges in price_cache before "
    "re-running benchmark sensitivity."
)


# ---------------------------------------------------------------------------
# Patchable seam
# ---------------------------------------------------------------------------


def _load_archive_state(
    *,
    db_path: str | None,
    event_ids: Sequence[int],
    tickers: Sequence[str],
) -> dict[str, Any]:
    """Read the events table for ``event_ids`` and the price_cache for
    every ticker in ``tickers``.

    Returns::

        {
          "events": {
            event_id: {
              "event_date":     str | None,
              "primary_ticker": str | None,
            },
            ...
          },
          "cache": {
            ticker_upper: sorted list of distinct ISO date strings,
            ...
          },
        }

    Read-only by construction — only ``SELECT`` statements are issued.
    Tests patch this attribute directly so the import only resolves on
    the un-patched path.  Returns empty maps on any DB error so callers
    degrade gracefully.
    """
    out: dict[str, Any] = {"events": {}, "cache": {}}
    path = _resolve_db_path(db_path)
    if path is None:
        return out

    try:
        conn = sqlite3.connect(path)
    except sqlite3.Error:
        return out

    try:
        ids_list = [int(i) for i in event_ids if isinstance(i, int)]
        if ids_list:
            placeholders = ",".join(["?"] * len(ids_list))
            try:
                rows = conn.execute(
                    f"SELECT id, event_date, market_tickers FROM events "
                    f"WHERE id IN ({placeholders})",
                    ids_list,
                ).fetchall()
            except sqlite3.Error:
                rows = []
            for raw_id, raw_event_date, raw_market_tickers in rows:
                if not isinstance(raw_id, int):
                    continue
                out["events"][raw_id] = {
                    "event_date":     raw_event_date if isinstance(raw_event_date, str) else None,
                    "primary_ticker": _primary_ticker(raw_market_tickers),
                }

        unique_tickers = sorted({
            t.strip().upper() for t in tickers
            if isinstance(t, str) and t.strip()
        })
        for ticker in unique_tickers:
            try:
                rows = conn.execute(
                    "SELECT DISTINCT date FROM price_cache "
                    "WHERE ticker = ? AND date IS NOT NULL AND date != '' "
                    "ORDER BY date",
                    (ticker,),
                ).fetchall()
            except sqlite3.Error:
                rows = []
            out["cache"][ticker] = [
                r[0] for r in rows
                if isinstance(r[0], str) and r[0]
            ]
    finally:
        conn.close()

    return out


def _resolve_db_path(db_path: str | None) -> str | None:
    if db_path is not None:
        return db_path
    try:
        import db as _db
    except Exception:
        return None
    return getattr(_db, "DB_FILE", None)


# ---------------------------------------------------------------------------
# Pure compute
# ---------------------------------------------------------------------------


def summarize_benchmark_sensitivity_preflight(
    *,
    db_path: str | None = None,
    event_ids: Sequence[int] = _DEFAULT_EVENT_IDS,
    benchmark: str = _DEFAULT_BENCHMARK,
    horizons: Sequence[int] = _DEFAULT_HORIZONS,
    estimation_window: int = _DEFAULT_ESTIMATION_WINDOW,
) -> dict[str, Any]:
    """Run the read-only benchmark-sensitivity preflight.

    See module docstring for the full output contract.
    """
    benchmark_upper = (benchmark or "").strip().upper()
    horizons_clean: tuple[int, ...] = tuple(
        h for h in horizons if isinstance(h, int) and h > 0
    )
    if not horizons_clean:
        horizons_clean = _DEFAULT_HORIZONS
    est_window = max(int(estimation_window), 0)

    event_ids_clean: list[int] = []
    seen: set[int] = set()
    for ev in event_ids:
        if isinstance(ev, int) and ev not in seen:
            event_ids_clean.append(ev)
            seen.add(ev)

    # Step 1: load events to discover primary tickers, then load cache
    # for the union of (primary tickers ∪ {benchmark}).  We do the load
    # in one seam call so tests can drive the entire DB surface from a
    # single synthetic payload.
    initial_state = _safe_dict(_load_archive_state(
        db_path=db_path,
        event_ids=event_ids_clean,
        tickers=[benchmark_upper] if benchmark_upper else [],
    ))
    events_map = _safe_dict(initial_state.get("events"))
    primary_tickers: list[str] = []
    for ev_id in event_ids_clean:
        ev_meta = _safe_dict(events_map.get(ev_id))
        pt = ev_meta.get("primary_ticker")
        if isinstance(pt, str) and pt:
            primary_tickers.append(pt)

    # Second pass to also pull primary-ticker caches.  We could make
    # this one round-trip in production, but the seam contract is
    # deliberately simple — tests provide both event metadata and cache
    # in a single payload, so two seam calls in production cost one
    # extra SELECT and keep the test surface tight.
    full_state = _safe_dict(_load_archive_state(
        db_path=db_path,
        event_ids=event_ids_clean,
        tickers=([benchmark_upper] if benchmark_upper else []) + primary_tickers,
    ))
    events_map = _safe_dict(full_state.get("events")) or events_map
    cache_map = _safe_dict(full_state.get("cache"))

    rows: list[dict[str, Any]] = []
    for ev_id in event_ids_clean:
        ev_meta = _safe_dict(events_map.get(ev_id))
        event_date_str = ev_meta.get("event_date")
        primary_ticker = ev_meta.get("primary_ticker")
        rows.append(_check_event(
            event_id=ev_id,
            event_date_str=event_date_str if isinstance(event_date_str, str) else None,
            primary_ticker=primary_ticker if isinstance(primary_ticker, str) and primary_ticker else None,
            benchmark_ticker=benchmark_upper,
            horizons=horizons_clean,
            estimation_window=est_window,
            cache_map=cache_map,
        ))

    ready_count   = sum(1 for r in rows if r["can_run_sensitivity"])
    blocked_count = len(rows) - ready_count

    return {
        "ok":                      True,
        "checked_events":          len(rows),
        "ready_count":             ready_count,
        "blocked_count":           blocked_count,
        "rows":                    rows,
        "recommended_next_action": _recommend(
            checked_events=len(rows),
            blocked_count=blocked_count,
            benchmark=benchmark_upper,
        ),
    }


def _check_event(
    *,
    event_id: int,
    event_date_str: str | None,
    primary_ticker: str | None,
    benchmark_ticker: str,
    horizons: tuple[int, ...],
    estimation_window: int,
    cache_map: dict[str, Any],
) -> dict[str, Any]:
    """Build the per-row dict for a single event."""
    event_d = _parse_iso_date(event_date_str)

    row_base: dict[str, Any] = {
        "event_id":                  event_id,
        "primary_ticker":            primary_ticker,
        "benchmark_ticker":          benchmark_ticker,
        "event_date":                event_date_str,
        "required_horizons":         list(horizons),
        "primary_cache_available":   False,
        "benchmark_cache_available": False,
        "missing_primary_ranges":    [],
        "missing_benchmark_ranges":  [],
        "can_run_sensitivity":       False,
        "blocker_reason":            "",
    }

    if event_d is None:
        row_base["blocker_reason"] = _BLOCKER_NO_EVENT_DATE
        return row_base

    if not primary_ticker:
        # We can still check the benchmark cache for completeness, but
        # the row cannot run sensitivity without a primary ticker.
        bench_dates = _safe_str_list(cache_map.get(benchmark_ticker.upper()))
        bench_ok, bench_missing = _check_ticker_cache(
            ticker=benchmark_ticker, event_d=event_d,
            horizons=horizons, estimation_window=estimation_window,
            cache_dates=bench_dates,
        )
        row_base["benchmark_cache_available"] = bench_ok
        row_base["missing_benchmark_ranges"]  = bench_missing
        row_base["blocker_reason"]            = _BLOCKER_NO_PRIMARY
        return row_base

    primary_dates = _safe_str_list(cache_map.get(primary_ticker.upper()))
    primary_ok, primary_missing = _check_ticker_cache(
        ticker=primary_ticker, event_d=event_d,
        horizons=horizons, estimation_window=estimation_window,
        cache_dates=primary_dates,
    )

    bench_dates = _safe_str_list(cache_map.get(benchmark_ticker.upper()))
    bench_ok, bench_missing = _check_ticker_cache(
        ticker=benchmark_ticker, event_d=event_d,
        horizons=horizons, estimation_window=estimation_window,
        cache_dates=bench_dates,
    )

    can_run = primary_ok and bench_ok
    blocker = _build_blocker_reason(
        primary_ok=primary_ok,
        benchmark_ok=bench_ok,
        primary_missing=primary_missing,
        benchmark_missing=bench_missing,
        primary_ticker=primary_ticker,
        benchmark_ticker=benchmark_ticker,
    )

    row_base["primary_cache_available"]   = primary_ok
    row_base["benchmark_cache_available"] = bench_ok
    row_base["missing_primary_ranges"]    = primary_missing
    row_base["missing_benchmark_ranges"]  = bench_missing
    row_base["can_run_sensitivity"]       = can_run
    row_base["blocker_reason"]            = blocker
    return row_base


def _check_ticker_cache(
    *,
    ticker: str,
    event_d: _date,
    horizons: tuple[int, ...],
    estimation_window: int,
    cache_dates: list[str],
) -> tuple[bool, list[dict[str, str]]]:
    """Return (is_available, missing_ranges) for a single ticker.

    Forward-horizon gap and estimation-window short are reported as
    separate range entries so an operator can address them independently.
    Empty cache surfaces both gaps with reason ``no_cache_for_ticker``
    instead.

    Both checks use ``_trading_day_offset`` / ``_trading_days_before`` so
    a known NYSE-closed weekday (for example ``2026-01-01``) is never
    flagged as a missing row.  Forward-horizon targets shift to the
    N-th *trading day* after the event, which is strictly stronger than
    the prior weekday-only target — it never silently clears a real
    missing trading day.
    """
    missing: list[dict[str, str]] = []

    if not cache_dates:
        # No cache rows at all — emit a single bracketing range that
        # spans the entire window the operator would need to backfill
        # for THIS event (estimation window through max forward horizon).
        max_h = max(horizons) if horizons else 0
        range_start = _trading_day_offset(
            event_d, -max(estimation_window, 1),
        ).isoformat()
        range_end = _trading_day_offset(event_d, max_h).isoformat() \
            if max_h > 0 else event_d.isoformat()
        missing.append({
            "start":  range_start,
            "end":    range_end,
            "reason": _REASON_NO_CACHE,
        })
        return False, missing

    cache_max_iso = cache_dates[-1]
    cache_set = set(cache_dates)
    event_iso = event_d.isoformat()

    # Forward-horizon gap ----------------------------------------------------
    # The target is the N-th *trading day* after the event, where
    # N = max(horizons).  A holiday between event and horizon shifts
    # the target one calendar day further out; the cache must still
    # carry a real row at or past that trading date.
    forward_ok = True
    if horizons:
        target_max_h = max(horizons)
        target_max_d = _trading_day_offset(event_d, target_max_h)
        target_max_iso = target_max_d.isoformat()
        if cache_max_iso < target_max_iso:
            forward_ok = False
            if cache_max_iso < event_iso:
                # Cache doesn't even reach the event date; start the
                # missing range at the next trading day, which is the
                # earliest forward observation we'd actually use.
                range_start_d = _trading_day_offset(event_d, 1)
            else:
                cmax_d = _date.fromisoformat(cache_max_iso)
                range_start_d = _next_trading_day(cmax_d)
            missing.append({
                "start":  range_start_d.isoformat(),
                "end":    target_max_iso,
                "reason": _REASON_FORWARD,
            })

    # Estimation-window short -----------------------------------------------
    # Resolve the estimation window to the concrete set of the
    # ``estimation_window`` most-recent trading days strictly before
    # ``event_d``.  The cache must contain a row for each of them.  Any
    # NYSE-closed weekday in the lookback range is dropped from the
    # required set, so a missing holiday row never blocks; any real
    # trading day missing from the cache still does.
    est_ok = True
    if estimation_window > 0:
        required_pre_dates = _trading_days_before(event_d, estimation_window)
        missing_pre_dates = [
            d for d in required_pre_dates
            if d.isoformat() not in cache_set
        ]
        if missing_pre_dates:
            est_ok = False
            missing.append({
                "start":  missing_pre_dates[0].isoformat(),
                "end":    missing_pre_dates[-1].isoformat(),
                "reason": _REASON_ESTIMATION,
            })

    return forward_ok and est_ok, missing


def _build_blocker_reason(
    *,
    primary_ok: bool,
    benchmark_ok: bool,
    primary_missing: list[dict[str, str]],
    benchmark_missing: list[dict[str, str]],
    primary_ticker: str,
    benchmark_ticker: str,
) -> str:
    if primary_ok and benchmark_ok:
        return _BLOCKER_READY
    parts: list[str] = []
    if not primary_ok:
        reasons = sorted({r.get("reason", "") for r in primary_missing if r.get("reason")})
        parts.append(
            f"primary {primary_ticker}: {', '.join(reasons) or 'cache_gap'}"
        )
    if not benchmark_ok:
        reasons = sorted({r.get("reason", "") for r in benchmark_missing if r.get("reason")})
        parts.append(
            f"benchmark {benchmark_ticker}: {', '.join(reasons) or 'cache_gap'}"
        )
    return "; ".join(parts)


def _recommend(
    *, checked_events: int, blocked_count: int, benchmark: str,
) -> str:
    if checked_events <= 0:
        return _RECOMMENDED_NO_EVENTS
    if blocked_count <= 0:
        return _RECOMMENDED_ALL_READY.format(
            n=checked_events, bench=benchmark or "(unspecified)",
        )
    return _RECOMMENDED_BLOCKED.format(
        n=checked_events, blocked=blocked_count,
        bench=benchmark or "(unspecified)",
    )


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _business_day_offset(start: _date, n: int) -> _date:
    """Shift ``start`` by ``n`` business days.  Positive = forward,
    negative = backward, zero = unchanged.

    Mirrors ``stat_validation_readiness_report._business_day_offset`` for
    positive ``n`` and extends to negative ``n`` so the preflight can
    back-project an estimation-window backfill range.

    Note: weekday-only.  See ``_trading_day_offset`` for the NYSE
    holiday-aware variant used by the missing-range logic.
    """
    if n == 0:
        return start
    out = start
    direction = 1 if n > 0 else -1
    remaining = abs(n)
    one_day = _timedelta(days=1)
    while remaining > 0:
        out = out + (one_day if direction > 0 else -one_day)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _is_trading_day(d: _date) -> bool:
    """Return True if ``d`` is a NYSE trading day (weekday and not a
    known US market holiday)."""
    return d.weekday() < 5 and d not in _MARKET_HOLIDAYS


def _trading_day_offset(start: _date, n: int) -> _date:
    """Shift ``start`` by ``n`` trading days, skipping weekends AND
    known US market holidays.  Positive = forward, negative = backward,
    zero = unchanged.

    Used by ``_check_ticker_cache`` so that the forward-horizon target
    and the estimation-window anchor line up with dates that could
    actually have a row in ``price_cache``.
    """
    if n == 0:
        return start
    out = start
    direction = 1 if n > 0 else -1
    remaining = abs(n)
    one_day = _timedelta(days=1)
    while remaining > 0:
        out = out + (one_day if direction > 0 else -one_day)
        if _is_trading_day(out):
            remaining -= 1
    return out


def _trading_days_before(event_d: _date, n: int) -> list[_date]:
    """Return the ``n`` most-recent trading days strictly before
    ``event_d``, in ascending date order.

    Anchors the estimation-window check to concrete dates so the
    missing-range output names real trading days an operator can
    backfill, rather than a count that drifts as the cache shifts.
    """
    if n <= 0:
        return []
    out: list[_date] = []
    cur = event_d - _timedelta(days=1)
    while len(out) < n:
        if _is_trading_day(cur):
            out.append(cur)
        cur = cur - _timedelta(days=1)
    out.reverse()
    return out


def _next_trading_day(after: _date) -> _date:
    """Return the next trading day strictly after ``after``."""
    cur = after + _timedelta(days=1)
    while not _is_trading_day(cur):
        cur = cur + _timedelta(days=1)
    return cur


def _parse_iso_date(value: Any) -> _date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def _primary_ticker(raw_market_tickers: Any) -> str | None:
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


def _safe_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str) and v]


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _render_text(report: dict[str, Any]) -> str:
    lines: list[str] = ["Benchmark sensitivity cache preflight", ""]
    lines.append(f"Checked events:  {report['checked_events']}")
    lines.append(f"Ready:           {report['ready_count']}")
    lines.append(f"Blocked:         {report['blocked_count']}")
    lines.append("")
    rows = report.get("rows") or []
    lines.append(f"Rows ({len(rows)}):")
    if rows:
        for r in rows:
            lines.append(
                f"  id={r.get('event_id')} "
                f"date={r.get('event_date') or '-'} "
                f"primary={r.get('primary_ticker') or '-'} "
                f"benchmark={r.get('benchmark_ticker')} "
                f"can_run={r.get('can_run_sensitivity')}"
            )
            lines.append(f"      blocker_reason: {r.get('blocker_reason') or '-'}")
            for kind, key in (
                ("primary",   "missing_primary_ranges"),
                ("benchmark", "missing_benchmark_ranges"),
            ):
                ranges = r.get(key) or []
                if ranges:
                    for rg in ranges:
                        lines.append(
                            f"      {kind} missing: "
                            f"{rg.get('start')} → {rg.get('end')} "
                            f"({rg.get('reason')})"
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


def _parse_int_csv(value: str) -> tuple[int, ...]:
    out: list[int] = []
    for tok in (value or "").split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok))
        except ValueError:
            continue
    return tuple(out)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only benchmark-sensitivity cache preflight.  Inspects "
            "the local price_cache to explain why benchmark sensitivity "
            "can or cannot run for a given list of events against a "
            "given benchmark.  Default targets are events 60 and 73 "
            "against XLE.  Read-only: never backfills the cache, never "
            "edits the archive, no provider, no LLM, no FastAPI surface."
        ),
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Emit structured JSON instead of the compact text report.",
    )
    parser.add_argument(
        "--event-ids", dest="event_ids",
        default=",".join(str(i) for i in _DEFAULT_EVENT_IDS),
        help=(
            f"Comma-separated event_ids to check (default "
            f"{','.join(str(i) for i in _DEFAULT_EVENT_IDS)})."
        ),
    )
    parser.add_argument(
        "--benchmark", dest="benchmark", default=_DEFAULT_BENCHMARK,
        help=f"Benchmark ticker symbol (default {_DEFAULT_BENCHMARK!r}).",
    )
    parser.add_argument(
        "--horizons", dest="horizons",
        default=",".join(str(h) for h in _DEFAULT_HORIZONS),
        help=(
            f"Comma-separated forward horizons in business days "
            f"(default {','.join(str(h) for h in _DEFAULT_HORIZONS)})."
        ),
    )
    parser.add_argument(
        "--estimation-window", dest="estimation_window",
        type=int, default=_DEFAULT_ESTIMATION_WINDOW,
        help=(
            f"Number of distinct pre-event cache dates required "
            f"(default {_DEFAULT_ESTIMATION_WINDOW})."
        ),
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None,
        help=(
            "Optional path to a SQLite events.db file.  Defaults to "
            "db.DB_FILE so the preflight follows the project's "
            "configured archive."
        ),
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None, *, out: Any = None) -> int:
    args = _parse_args(argv)
    output = out if out is not None else sys.stdout

    report = summarize_benchmark_sensitivity_preflight(
        db_path=args.db_path,
        event_ids=_parse_int_csv(args.event_ids),
        benchmark=args.benchmark,
        horizons=_parse_int_csv(args.horizons),
        estimation_window=args.estimation_window,
    )
    if args.json:
        print(_render_json(report), file=output)
    else:
        print(_render_text(report), file=output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
