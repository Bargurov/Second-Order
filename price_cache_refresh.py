"""Zero-LLM price-cache refresh — planner + executor.

Selects archived events whose ``market_tickers`` blocks need
additional ``price_cache`` rows to become reaction-profile-scorable,
computes the missing date windows + an upper-bound provider-call
estimate, and (only under an explicit ``confirm=True`` flag) writes
the freshly-fetched rows into ``price_cache``.  No LLM, no
``analyze_event``, no ``auto_backfill_runner.execute_paid_candidate``,
no FastAPI wiring.

Companion design: ``docs/price_cache_refresh_design.md`` — §§4–5
specify the window contract / skip taxonomy / dry-run output shape;
§6 specifies the ``--write --confirm`` write contract this module
implements at the function level.

The module exposes three seams so tests can drive each independently:

* :func:`plan_refresh` — fully pure.  Takes pre-decoded events and a
  per-ticker cached-date map, returns a :class:`RefreshPlan`.  Never
  touches SQLite, never touches the network.
* :func:`load_inputs` — reads ``events`` + ``price_cache`` rows from
  a SQLite DB path so the CLI / future executor can hand inputs to
  :func:`plan_refresh`.  Read-only; the function never issues
  ``INSERT`` / ``UPDATE`` / ``DELETE`` statements.
* :func:`execute_refresh` — the only seam in this module that may
  call the active provider or write ``price_cache`` rows, and only
  when the caller passes ``confirm=True``.  The provider seam is
  injectable so tests can drive it with a ``MagicMock`` and assert
  the executor never reaches the real network.

Importing this module pulls in ``sqlite3`` and the stdlib only.
No ``api``, no ``market_check``, no ``analyze_event``, no
``auto_backfill_runner`` import is reached.
"""
from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date as _date, datetime as _dt, timedelta as _timedelta, timezone as _tz
from typing import Any, Callable, Iterable, Mapping, NamedTuple, Optional, Sequence

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


# Gap-mode-20d skip taxonomy.  These keys are appended to
# ``skipped_counts`` only when ``plan_refresh`` is invoked with
# ``gap_mode_20d=True``; the default keyset stays
# ``SKIP_COUNT_KEYS`` for byte-compatibility with existing consumers.
SKIP_TOO_RECENT_20D            = "too_recent_20d"
SKIP_AUTO_ADJUST_MISMATCH_20D  = "auto_adjust_mismatch_20d"
GAP_20D_PLANNED                = "cache_window_gap_20d_planned"
SKIP_LIKELY_DELISTED_OR_SPARSE = "likely_delisted_or_sparse"

GAP_MODE_20D_COUNT_KEYS: tuple[str, ...] = (
    SKIP_TOO_RECENT_20D,
    SKIP_AUTO_ADJUST_MISMATCH_20D,
    GAP_20D_PLANNED,
    SKIP_LIKELY_DELISTED_OR_SPARSE,
)

# Mirrors the diagnostic endpoint's threshold so the planner agrees
# with /diagnostics/no-forward-20d-blockers' classification: a ticker
# whose newest cached row across both ``auto_adjust`` flags is more
# than this many calendar days behind today is treated as
# delisted/sparse rather than a refreshable cache gap.
GAP_MODE_20D_DELISTED_THRESHOLD_CALENDAR_DAYS: int = 60


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
    # Pinned to False so refresh-written rows are visible to
    # ``reaction_profile_hydration`` (which reads with ``auto_adjust=False``).
    # Cross-module contract pinned by
    # ``tests.test_price_cache_refresh.TestAutoAdjustHydratorAlignment``.
    auto_adjust:               bool = False
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
    gap_mode_20d: bool = False,
    cached_dates_other_flag: Optional[
        Mapping[str, frozenset[_date]]
    ] = None,
) -> RefreshPlan:
    """Return a deterministic dry-run refresh plan.

    ``events`` is an iterable of decoded event dicts (the shape
    ``db._decode_event_row`` produces).  ``cached_dates_by_ticker``
    maps a normalised ticker symbol to the set of dates already in
    ``price_cache`` for the configured ``auto_adjust`` flag.

    Optional ``gap_mode_20d`` switches the planner into a focused
    "fix only true cache_max_before_20d_horizon gaps" mode.  When True:

      * The window is narrowed to ``[event_date, event_date + 20bd]``
        (the post-window only) — the pre-window is dropped because the
        20d horizon does not depend on it.
      * Each ticker that survives the standard validity gates lands
        in exactly one of four mutually-exclusive sub-buckets, in
        precedence order:

          1. ``too_recent_20d`` — ``event_date + 20bd > today``; the
             20d target is in the future, no provider can fill it yet.
          2. ``already_covered`` (existing key) — the 20d window is
             already cached at the configured flag; no work to do.
          3. ``auto_adjust_mismatch_20d`` — ``cached_dates_other_flag``
             reaches the 20d target while ``cached_dates_by_ticker``
             does not.  A refresh would re-fetch identical data into
             the wrong cache bucket; surface separately so the operator
             can decide.
          4. ``likely_delisted_or_sparse`` — the newest cached row
             across BOTH flags is more than
             ``GAP_MODE_20D_DELISTED_THRESHOLD_CALENDAR_DAYS`` calendar
             days behind today; refresh cannot help.
          5. ``cache_window_gap_20d_planned`` — none of the above; the
             ticker has a real, refreshable 20d gap.  A
             :class:`TickerRefreshJob` is added with the 20d-only
             window.

      * ``skipped_counts`` carries every legacy key plus the four
        gap-mode keys (``GAP_MODE_20D_COUNT_KEYS``).

    ``cached_dates_other_flag`` is consulted only when
    ``gap_mode_20d=True``; in default mode it is ignored.  Default
    invocations remain byte-compatible with the existing planner —
    ``skipped_counts`` keys, refresh-job semantics, and cap behaviour
    are unchanged.

    No provider call, no SQLite write, no FastAPI / LLM import is
    reachable from this function.  Tests in
    ``tests/test_price_cache_refresh.py`` pin that contract.
    """
    cfg = config or RefreshConfig()
    today = _today_utc(now)
    stale_cutoff = today - _timedelta(days=cfg.stale_after_days)

    skip_counts: dict[str, int] = {key: 0 for key in SKIP_COUNT_KEYS}
    if gap_mode_20d:
        for key in GAP_MODE_20D_COUNT_KEYS:
            skip_counts[key] = 0
    other_flag_cache: Mapping[str, frozenset[_date]] = (
        cached_dates_other_flag if (gap_mode_20d and cached_dates_other_flag)
        else {}
    )

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
        # the Mon-Fri grid.  Gap-mode-20d narrows to the post-window
        # only; default mode includes the pre+anchor+post run so the
        # legacy refresh-job semantics are preserved.
        post_end = _bday_offset(event_date, cfg.post_window_business_days)
        if gap_mode_20d:
            anchor_snapped = _bday_offset(event_date, 0)
            window = _business_days_inclusive(anchor_snapped, post_end)
        else:
            pre_start = _bday_offset(
                event_date, -cfg.pre_window_business_days,
            )
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

            # Stale detection (default mode only): cache has rows for
            # this symbol AND the latest cached date is older than
            # today by more than ``stale_after_days``.  Skipped under
            # gap_mode_20d so the gap-mode 60-day delisted check (a
            # tighter, more useful threshold) is the sole stale signal
            # — otherwise tickers between 60 and 365 days behind would
            # silently fall through both checks.
            if not gap_mode_20d and cached:
                latest = max(cached)
                if latest < stale_cutoff:
                    skip_counts[SKIP_STALE_TICKER] += 1
                    continue

            if gap_mode_20d:
                target_20d = post_end

                # 1. too_recent_20d
                if target_20d > today:
                    skip_counts[SKIP_TOO_RECENT_20D] += 1
                    continue

                # 2. already_covered (legacy key) — the hydrator gets
                # ≥ 21 cache rows from the anchor, so the composer
                # populates return_20d.  Counted under the stable
                # legacy key rather than a new gap-mode key so the
                # operator-facing taxonomy stays compact.
                cached_in_window = sum(
                    1 for d in cached if d >= window[0] and d <= post_end
                )
                if cached_in_window >= len(window):
                    skip_counts[SKIP_ALREADY_COVERED] += 1
                    continue

                # 3. auto_adjust_mismatch_20d — the inverse-flag cache
                # reaches the 20d target while the configured-flag
                # cache does not.
                other_cached = other_flag_cache.get(symbol, frozenset())
                primary_covers_target = (
                    bool(cached) and max(cached) >= target_20d
                )
                other_covers_target = (
                    bool(other_cached) and max(other_cached) >= target_20d
                )
                if other_covers_target and not primary_covers_target:
                    skip_counts[SKIP_AUTO_ADJUST_MISMATCH_20D] += 1
                    continue

                # 4. likely_delisted_or_sparse — newest cached row
                # across both flags is too far behind today.
                newest_anywhere: Optional[_date] = None
                if cached:
                    newest_anywhere = max(cached)
                if other_cached:
                    cand = max(other_cached)
                    if newest_anywhere is None or cand > newest_anywhere:
                        newest_anywhere = cand
                if (
                    newest_anywhere is not None
                    and (today - newest_anywhere).days
                    > GAP_MODE_20D_DELISTED_THRESHOLD_CALENDAR_DAYS
                ):
                    skip_counts[SKIP_LIKELY_DELISTED_OR_SPARSE] += 1
                    continue

                # 5. cache_window_gap_20d_planned — true gap; plan it.
                intervals = _compute_missing_intervals(window, cached)
                if not intervals:
                    # Defensive: window was not fully covered above
                    # but every weekday in it is in cache (shouldn't
                    # happen, but route to the legacy bucket).
                    skip_counts[SKIP_ALREADY_COVERED] += 1
                    continue
                skip_counts[GAP_20D_PLANNED] += 1
                per_event_jobs.append(TickerRefreshJob(
                    event_id=event_id,
                    event_date=event_date.isoformat(),
                    symbol=symbol,
                    intervals=tuple(
                        (s.isoformat(), e.isoformat()) for s, e in intervals
                    ),
                    business_days=sum(
                        len(_business_days_inclusive(s, e))
                        for s, e in intervals
                    ),
                    auto_adjust=cfg.auto_adjust,
                ))
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
    auto_adjust: bool = False,
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


# ---------------------------------------------------------------------------
# Executor — write mode behind explicit confirm=True
# ---------------------------------------------------------------------------


class ProviderRow(NamedTuple):
    """One bar returned by an injected provider seam.

    Kept deliberately stdlib-only (no pandas dependency for tests) so a
    ``MagicMock`` in a unit test can produce these tuples directly.
    """
    date:   str    # ISO ``YYYY-MM-DD``
    close:  float
    volume: float


# Type alias for the injectable provider seam.  Tests pass a
# ``MagicMock`` shaped like this; the production CLI will inject a
# small adapter over ``price_cache.fetch_daily_cached`` that yields
# ``ProviderRow`` tuples without ever pulling pandas into this module.
ProviderFetch = Callable[[str, _date, _date, bool], Sequence[ProviderRow]]


@dataclass(frozen=True)
class RefreshError:
    """One failed (symbol, interval) attempt.  Errors are isolated:
    a raise inside the provider seam is captured here and the
    executor moves on to the next interval / job.
    """
    symbol:        str
    interval:      tuple[str, str]
    error_type:    str
    message:       str


@dataclass(frozen=True)
class ExecutorResult:
    """Outcome of one :func:`execute_refresh` invocation.

    ``dry_run`` and ``confirmed`` are inverses (``dry_run = not confirmed``)
    and both are surfaced so callers can read either name without
    second-guessing — the design doc and the runbook each use one.
    """
    attempted_jobs:  int
    written_rows:    int
    skipped_jobs:    int
    errors:          tuple[RefreshError, ...]
    dry_run:         bool
    confirmed:       bool
    provider_calls:  int

    @property
    def ok(self) -> bool:
        return not self.errors


def execute_refresh(
    plan: RefreshPlan,
    db_path: str,
    *,
    confirm: bool = False,
    provider_fetch: Optional[ProviderFetch] = None,
    fetched_at: Optional[str] = None,
) -> ExecutorResult:
    """Execute a :class:`RefreshPlan` — write mode is opt-in only.

    The default invocation (``confirm=False``, no ``provider_fetch``)
    is a strict no-op: zero provider calls, zero DB writes, every plan
    job recorded as ``skipped_jobs``.  This is the "explicit confirm
    required" gate spelled out in
    ``docs/price_cache_refresh_design.md`` §6.1 — neither flag alone
    can issue a provider call.

    With ``confirm=True``:

    * ``provider_fetch`` is required.  If the caller forgets it, the
      executor refuses to run and returns a structured result with
      no writes (so a misconfigured CLI does not silently succeed).
    * Each (symbol, interval) pair invokes ``provider_fetch`` exactly
      once.  Returned :class:`ProviderRow` tuples are upserted into
      ``price_cache`` via ``INSERT OR REPLACE`` — idempotent, so
      re-running the same plan over the same provider rows leaves the
      table in the same shape.
    * ``plan.max_provider_calls`` is enforced defensively.  If the
      plan was hand-constructed and overshoots the cap, the executor
      stops at the cap; remaining jobs are recorded as
      ``skipped_jobs``.
    * Errors are isolated per interval: a provider raise is caught,
      recorded in :attr:`ExecutorResult.errors`, and the executor
      continues with the next interval / job.  The DB transaction
      commits whatever rows did succeed.
    * No LLM seam, no ``analyze_event``, no
      ``auto_backfill_runner.execute_paid_candidate`` is touched.
      The only side effects are: provider calls (via the injected
      seam) and ``INSERT OR REPLACE`` against ``price_cache``.

    The executor never opens or imports FastAPI.  It is invoked only
    from explicit CLI entry points.
    """
    timestamp = fetched_at or _dt.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ----- Dry-run / confirm-not-set short circuit ---------------------
    if not confirm:
        return ExecutorResult(
            attempted_jobs=0,
            written_rows=0,
            skipped_jobs=len(plan.refresh_jobs),
            errors=(),
            dry_run=True,
            confirmed=False,
            provider_calls=0,
        )

    if provider_fetch is None:
        # ``confirm=True`` without an injected fetch seam is a
        # configuration error.  Refuse to proceed; record every plan
        # job as skipped so the operator-facing report explains the
        # no-op clearly rather than silently succeeding.
        _log.warning(
            "execute_refresh: confirm=True but provider_fetch is None; "
            "no provider calls and no writes will be issued.",
        )
        return ExecutorResult(
            attempted_jobs=0,
            written_rows=0,
            skipped_jobs=len(plan.refresh_jobs),
            errors=(),
            dry_run=False,
            confirmed=True,
            provider_calls=0,
        )

    # ----- Confirmed write path ---------------------------------------
    cap = max(0, int(plan.max_provider_calls))
    calls_used = 0
    attempted = 0
    written   = 0
    skipped   = 0
    errors:   list[RefreshError] = []

    with sqlite3.connect(db_path) as conn:
        for job in plan.refresh_jobs:
            if calls_used >= cap:
                # Plan over-stuffed (or cap=0): record the rest as
                # skipped without issuing further provider calls.
                skipped += 1
                continue

            attempted_this_job = False
            for interval in job.intervals:
                if calls_used >= cap:
                    break

                start_str, end_str = interval
                try:
                    start = _dt.strptime(start_str, "%Y-%m-%d").date()
                    end   = _dt.strptime(end_str,   "%Y-%m-%d").date()
                except (ValueError, TypeError) as exc:
                    errors.append(RefreshError(
                        symbol=job.symbol,
                        interval=interval,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    ))
                    continue

                calls_used += 1
                attempted_this_job = True
                try:
                    rows = provider_fetch(
                        job.symbol, start, end, job.auto_adjust,
                    )
                except Exception as exc:
                    # Per design §6: a provider raise on one interval
                    # must not abort the run.  Capture and continue.
                    errors.append(RefreshError(
                        symbol=job.symbol,
                        interval=interval,
                        error_type=type(exc).__name__,
                        message=str(exc),
                    ))
                    continue

                written += _upsert_rows(
                    conn, job.symbol, rows,
                    auto_adjust=job.auto_adjust,
                    fetched_at=timestamp,
                )

            if attempted_this_job:
                attempted += 1
        conn.commit()

    return ExecutorResult(
        attempted_jobs=attempted,
        written_rows=written,
        skipped_jobs=skipped,
        errors=tuple(errors),
        dry_run=False,
        confirmed=True,
        provider_calls=calls_used,
    )


def _upsert_rows(
    conn:        sqlite3.Connection,
    symbol:      str,
    rows:        Sequence[Any],
    *,
    auto_adjust: bool,
    fetched_at:  str,
) -> int:
    """Upsert provider-returned bars into ``price_cache``.

    Accepts both :class:`ProviderRow` tuples and dict-shaped rows so
    test mocks can return the more readable form.  Returns the count
    of rows that were actually written (rows missing the required
    fields are silently dropped — a malformed row is not an error,
    it's just data the planner cannot use yet).
    """
    flag = 1 if auto_adjust else 0
    written = 0
    for row in rows:
        if isinstance(row, ProviderRow):
            date_str = row.date
            close    = row.close
            volume   = row.volume
        elif isinstance(row, Mapping):
            date_str = row.get("date")
            close    = row.get("close")
            volume   = row.get("volume", 0.0)
        else:
            continue

        if not isinstance(date_str, str) or not date_str:
            continue
        try:
            close_v  = float(close)  if close  is not None else None
            volume_v = float(volume) if volume is not None else None
        except (TypeError, ValueError):
            continue

        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (symbol, date_str[:10], close_v, volume_v, flag, fetched_at),
        )
        written += 1
    return written
