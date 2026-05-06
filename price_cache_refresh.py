"""Zero-LLM price-cache refresh — pure planner.

Selects archived events whose ``market_tickers`` blocks need
additional ``price_cache`` rows to become reaction-profile-scorable
and computes the missing date windows + an upper-bound provider-call
estimate.  Planner only — no provider calls, no DB writes, no LLM,
no FastAPI wiring.

Companion design: ``docs/price_cache_refresh_design.md`` (§§4–5
specify the window contract, skip taxonomy, and dry-run output
shape this module mirrors).

The module exposes two seams so tests can drive each independently:

* :func:`plan_refresh` — fully pure.  Takes pre-decoded events and a
  per-ticker cached-date map, returns a :class:`RefreshPlan`.  Never
  touches SQLite, never touches the network.
* :func:`load_inputs` — reads ``events`` + ``price_cache`` rows from
  a SQLite DB path so the CLI / future executor can hand inputs to
  :func:`plan_refresh`.  Read-only; the function never issues
  ``INSERT`` / ``UPDATE`` / ``DELETE`` statements.

Both are deliberately stand-alone: importing this module pulls in
``sqlite3`` and the stdlib only.  No ``api``, no ``market_check``,
no ``analyze_event``, no ``auto_backfill_runner`` import is reached.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _dt, timedelta as _timedelta, timezone as _tz
from typing import Any, Iterable, Mapping, Optional

_log = logging.getLogger("second_order.price_cache_refresh")


# ---------------------------------------------------------------------------
# Skip taxonomy — kept stable so consumers can rely on key order.
# ---------------------------------------------------------------------------

SKIP_INVALID_EVENT_DATE = "invalid_event_date"
SKIP_NO_MARKET_TICKERS  = "no_market_tickers"
SKIP_INVALID_TICKER     = "invalid_ticker"
SKIP_STALE_TICKER       = "stale_ticker"
SKIP_ALREADY_COVERED    = "already_covered"
SKIP_CAP_EXHAUSTED      = "cap_exhausted"

SKIP_COUNT_KEYS: tuple[str, ...] = (
    SKIP_INVALID_EVENT_DATE,
    SKIP_NO_MARKET_TICKERS,
    SKIP_INVALID_TICKER,
    SKIP_STALE_TICKER,
    SKIP_ALREADY_COVERED,
    SKIP_CAP_EXHAUSTED,
)

DECISION_NO_WORK       = "no_work"
DECISION_PLANNED       = "planned"
DECISION_CAP_EXHAUSTED = "cap_exhausted"


# ---------------------------------------------------------------------------
# Local helpers — re-implemented here so the module stays import-light.
# ---------------------------------------------------------------------------

# Mirrors ``market_check._PROXY_SUFFIX_RE`` (a ``(proxy)`` annotation
# must never reach the provider).  Re-implemented locally so this
# module does not import ``market_check``; the regex is a one-liner
# and the contract is pinned by tests.
_PROXY_SUFFIX_RE = re.compile(r"\s*\(proxy\)\s*$", re.IGNORECASE)


def _clean_symbol(raw: Any) -> str:
    """Normalise a ticker symbol; return empty string for invalid input."""
    if not isinstance(raw, str):
        return ""
    return _PROXY_SUFFIX_RE.sub("", raw).strip().upper()


def _parse_event_date(raw: Any) -> Optional[_date]:
    """Parse an event_date string; return None on any failure."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _dt.strptime(raw[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _today_utc(now: Optional[_dt]) -> _date:
    if now is None:
        return _dt.now(_tz.utc).date()
    if now.tzinfo is None:
        return now.date()
    return now.astimezone(_tz.utc).date()


def _bday_offset(d: _date, n: int) -> _date:
    """Return d + n business days (Mon–Fri).  Negative n moves backwards.

    No holiday calendar — matches the rest of the reaction-profile
    pipeline, which also does not consult one.
    """
    if n == 0:
        # Snap to the nearest preceding business day if d itself falls
        # on a weekend.  Keeps window endpoints inside the Mon-Fri grid
        # so a cache lookup never asks for a Saturday/Sunday row.
        cur = d
        while cur.weekday() >= 5:
            cur -= _timedelta(days=1)
        return cur
    sign = 1 if n > 0 else -1
    remaining = abs(n)
    cur = d
    while remaining > 0:
        cur += _timedelta(days=sign)
        if cur.weekday() < 5:
            remaining -= 1
    return cur


def _business_days_inclusive(start: _date, end: _date) -> list[_date]:
    """Return every business day in ``[start, end]`` inclusive."""
    if end < start:
        return []
    out: list[_date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            out.append(cur)
        cur += _timedelta(days=1)
    return out


def _compute_missing_intervals(
    window_dates: list[_date],
    cached_dates: frozenset[_date],
) -> list[tuple[_date, _date]]:
    """Group consecutive window dates not in ``cached_dates`` into runs.

    Each run is one provider call under the ``fetch_daily_cached``
    contract.  The result is the upper bound — the cache's
    leading/trailing logic may merge runs internally.
    """
    intervals: list[tuple[_date, _date]] = []
    run_start: Optional[_date] = None
    run_end:   Optional[_date] = None
    for d in window_dates:
        if d in cached_dates:
            if run_start is not None and run_end is not None:
                intervals.append((run_start, run_end))
                run_start = None
                run_end = None
        else:
            if run_start is None:
                run_start = d
            run_end = d
    if run_start is not None and run_end is not None:
        intervals.append((run_start, run_end))
    return intervals


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RefreshConfig:
    """Caps + window parameters for one refresh run.

    Defaults are deliberately conservative; ``docs/price_cache_refresh_design.md``
    §5.3 records the rationale.  Tightening them is a low-risk change;
    loosening them requires a doc + test update.
    """
    pre_window_business_days:  int  = 5
    post_window_business_days: int  = 20
    auto_adjust:               bool = True
    max_events:                int  = 100
    max_tickers_per_event:     int  = 8
    max_provider_calls:        int  = 50
    # A ticker with cached rows but whose latest cached date is older
    # than ``today - stale_after_days`` is treated as delisted /
    # halted: the planner emits ``stale_ticker`` and skips the pair so
    # a refresh run does not waste provider calls on a no-op fetch.
    stale_after_days:          int  = 365


@dataclass(frozen=True)
class TickerRefreshJob:
    """Per-(event, ticker) work item the executor would later issue."""
    event_id:        int
    event_date:      str
    symbol:          str
    intervals:       tuple[tuple[str, str], ...]
    business_days:   int
    auto_adjust:     bool

    @property
    def provider_calls(self) -> int:
        return len(self.intervals)


@dataclass(frozen=True)
class RefreshPlan:
    """Dry-run plan returned by :func:`plan_refresh`."""
    events_considered:        int
    tickers_considered:       int
    refresh_jobs:             tuple[TickerRefreshJob, ...]
    skipped_counts:           dict[str, int]
    provider_calls_estimate:  int
    max_provider_calls:       int
    cap_applied:              bool
    decision_reason:          str

    @property
    def unique_tickers(self) -> int:
        return len({job.symbol for job in self.refresh_jobs})

    @property
    def planned_events(self) -> int:
        return len({job.event_id for job in self.refresh_jobs})

    @property
    def total_business_days(self) -> int:
        return sum(job.business_days for job in self.refresh_jobs)


# ---------------------------------------------------------------------------
# Pure planner
# ---------------------------------------------------------------------------


def plan_refresh(
    events: Iterable[Mapping[str, Any]],
    cached_dates_by_ticker: Mapping[str, frozenset[_date]],
    *,
    config: Optional[RefreshConfig] = None,
    now: Optional[_dt] = None,
) -> RefreshPlan:
    """Return a deterministic dry-run refresh plan.

    ``events`` is an iterable of decoded event dicts (the shape
    ``db._decode_event_row`` produces).  ``cached_dates_by_ticker``
    maps a normalised ticker symbol to the set of dates already in
    ``price_cache`` for the configured ``auto_adjust`` flag.

    No provider call, no SQLite write, no FastAPI / LLM import is
    reachable from this function.  Tests in
    ``tests/test_price_cache_refresh.py`` pin that contract.
    """
    cfg = config or RefreshConfig()
    today = _today_utc(now)
    stale_cutoff = today - _timedelta(days=cfg.stale_after_days)

    skip_counts: dict[str, int] = {key: 0 for key in SKIP_COUNT_KEYS}
    jobs: list[TickerRefreshJob] = []

    events_considered = 0
    tickers_considered = 0
    provider_calls_estimate = 0
    cap_applied = False

    for event in events:
        events_considered += 1

        if not isinstance(event, Mapping):
            skip_counts[SKIP_INVALID_EVENT_DATE] += 1
            continue

        event_id = event.get("id")
        if not isinstance(event_id, int):
            # No usable id → the executor would not be able to attribute
            # the fetch later either.  Treat as invalid.
            skip_counts[SKIP_INVALID_EVENT_DATE] += 1
            continue

        event_date = _parse_event_date(event.get("event_date"))
        if event_date is None or event_date > today:
            skip_counts[SKIP_INVALID_EVENT_DATE] += 1
            continue

        tickers = event.get("market_tickers")
        if not isinstance(tickers, list) or len(tickers) == 0:
            skip_counts[SKIP_NO_MARKET_TICKERS] += 1
            continue

        # Window endpoints — anchored on event_date and snapped onto
        # the Mon-Fri grid.
        pre_start = _bday_offset(event_date, -cfg.pre_window_business_days)
        post_end  = _bday_offset(event_date,  cfg.post_window_business_days)
        window = _business_days_inclusive(pre_start, post_end)

        per_event_jobs: list[TickerRefreshJob] = []

        for raw_ticker in tickers[: cfg.max_tickers_per_event]:
            tickers_considered += 1

            symbol_raw = (
                raw_ticker.get("symbol")
                if isinstance(raw_ticker, Mapping)
                else raw_ticker
            )
            symbol = _clean_symbol(symbol_raw)
            if not symbol:
                skip_counts[SKIP_INVALID_TICKER] += 1
                continue

            cached = cached_dates_by_ticker.get(symbol, frozenset())

            # Stale detection: cache has rows for this symbol AND the
            # latest cached date is older than today by more than
            # ``stale_after_days``.  Symbols never queried before
            # (empty cache) get a chance — that is exactly what the
            # refresh exists for.
            if cached:
                latest = max(cached)
                if latest < stale_cutoff:
                    skip_counts[SKIP_STALE_TICKER] += 1
                    continue

            intervals = _compute_missing_intervals(window, cached)
            if not intervals:
                skip_counts[SKIP_ALREADY_COVERED] += 1
                continue

            per_event_jobs.append(TickerRefreshJob(
                event_id=event_id,
                event_date=event_date.isoformat(),
                symbol=symbol,
                intervals=tuple(
                    (s.isoformat(), e.isoformat()) for s, e in intervals
                ),
                business_days=sum(
                    len(_business_days_inclusive(s, e)) for s, e in intervals
                ),
                auto_adjust=cfg.auto_adjust,
            ))

        if not per_event_jobs:
            continue

        # Whole-event cap check — design §5.3: we truncate by event so
        # a single event's window stays internally consistent.
        event_cost = sum(j.provider_calls for j in per_event_jobs)
        if provider_calls_estimate + event_cost > cfg.max_provider_calls:
            skip_counts[SKIP_CAP_EXHAUSTED] += 1
            cap_applied = True
            continue

        # Also apply the events-cap.  Past it, every additional event
        # is a cap skip — same family of decision, different driver.
        if len({j.event_id for j in jobs}) >= cfg.max_events:
            skip_counts[SKIP_CAP_EXHAUSTED] += 1
            cap_applied = True
            continue

        jobs.extend(per_event_jobs)
        provider_calls_estimate += event_cost

    if not jobs:
        decision_reason = (
            DECISION_CAP_EXHAUSTED
            if cap_applied and skip_counts[SKIP_CAP_EXHAUSTED] > 0
            else DECISION_NO_WORK
        )
    elif cap_applied:
        decision_reason = DECISION_CAP_EXHAUSTED
    else:
        decision_reason = DECISION_PLANNED

    return RefreshPlan(
        events_considered=events_considered,
        tickers_considered=tickers_considered,
        refresh_jobs=tuple(jobs),
        skipped_counts=skip_counts,
        provider_calls_estimate=provider_calls_estimate,
        max_provider_calls=cfg.max_provider_calls,
        cap_applied=cap_applied,
        decision_reason=decision_reason,
    )


# ---------------------------------------------------------------------------
# Read-only DB loader — convenience for the CLI / future executor.
# ---------------------------------------------------------------------------


def load_inputs(
    db_path: str,
    *,
    auto_adjust: bool = True,
    since_days: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, frozenset[_date]]]:
    """Load events + cached price-cache dates from a SQLite DB.

    Read-only: opens the DB in URI ``mode=ro`` mode so a buggy caller
    cannot accidentally issue ``INSERT`` / ``UPDATE`` / ``DELETE``.
    Returns the inputs :func:`plan_refresh` expects.

    ``since_days`` filters events whose ``event_date`` is at most that
    many calendar days in the past.  ``None`` (default) loads every
    event with non-empty ``market_tickers``.
    """
    uri = f"file:{db_path}?mode=ro"
    events: list[dict[str, Any]] = []
    cached_by_ticker: dict[str, set[_date]] = {}

    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row

        events_query = (
            "SELECT id, event_date, market_tickers FROM events "
            "WHERE market_tickers IS NOT NULL "
            "AND market_tickers != '' AND market_tickers != '[]' "
            "AND event_date IS NOT NULL AND event_date != ''"
        )
        params: tuple[Any, ...] = ()
        if since_days is not None:
            cutoff = (_dt.now(_tz.utc).date() - _timedelta(days=since_days)).isoformat()
            events_query += " AND event_date >= ?"
            params = (cutoff,)
        events_query += " ORDER BY event_date DESC, id DESC"

        for row in conn.execute(events_query, params).fetchall():
            try:
                tickers = json.loads(row["market_tickers"]) or []
            except (json.JSONDecodeError, TypeError):
                tickers = []
            if not isinstance(tickers, list) or not tickers:
                continue
            events.append({
                "id":             row["id"],
                "event_date":     row["event_date"],
                "market_tickers": tickers,
            })

        # Restrict the cache scan to symbols we care about — the
        # planner only consults the map for those tickers anyway, and
        # restricting up front keeps memory in check on large caches.
        wanted_symbols: set[str] = set()
        for ev in events:
            for raw in ev.get("market_tickers") or []:
                sym = _clean_symbol(
                    raw.get("symbol") if isinstance(raw, Mapping) else raw
                )
                if sym:
                    wanted_symbols.add(sym)

        if wanted_symbols:
            placeholders = ",".join("?" * len(wanted_symbols))
            cache_query = (
                f"SELECT ticker, date FROM price_cache "
                f"WHERE auto_adjust = ? AND ticker IN ({placeholders})"
            )
            cache_params = (1 if auto_adjust else 0, *sorted(wanted_symbols))
            for row in conn.execute(cache_query, cache_params).fetchall():
                ticker = (row["ticker"] or "").strip().upper()
                date_str = row["date"]
                if not ticker or not isinstance(date_str, str):
                    continue
                try:
                    parsed = _dt.strptime(date_str[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    continue
                cached_by_ticker.setdefault(ticker, set()).add(parsed)

    return events, {k: frozenset(v) for k, v in cached_by_ticker.items()}
