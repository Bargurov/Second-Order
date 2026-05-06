"""Unit tests for the zero-LLM price-cache refresh planner.

Pins the safety contract from
``docs/price_cache_refresh_design.md``:

* :func:`price_cache_refresh.plan_refresh` is a pure function — no
  provider call, no SQLite write, no LLM, no ``analyze_event``, no
  ``auto_backfill_runner.execute_paid_candidate``, no FastAPI import.
* :func:`price_cache_refresh.load_inputs` reads ``events`` +
  ``price_cache`` rows from a temp SQLite DB and never issues a
  write statement (the connection is opened in ``mode=ro``).

Test fixture strategy
---------------------
Every test that needs SQLite seeds a fresh temp DB (``setUp`` /
``tearDown``) so the suite is hermetic and parallel-safe.  No
production DB, no shared singleton, no module-level monkey-patching
that could leak across tests.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import price_cache_refresh as pcr  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    *,
    event_id: int,
    event_date: date | str | None,
    tickers: list[Any] | None,
) -> dict[str, Any]:
    """Synthesise a minimal event row for the planner."""
    if isinstance(event_date, date):
        date_str: Any = event_date.isoformat()
    else:
        date_str = event_date
    return {
        "id":             event_id,
        "event_date":     date_str,
        "market_tickers": tickers,
    }


def _make_ticker(symbol: str, **extra: Any) -> dict[str, Any]:
    base = {"symbol": symbol, "role": "beneficiary"}
    base.update(extra)
    return base


def _bdays(start: date, n: int) -> list[date]:
    """Return the next ``n`` business days starting at ``start`` (inclusive)."""
    out: list[date] = []
    cur = start
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Pure-planner unit tests
# ---------------------------------------------------------------------------


class TestPlanRefreshPurity(unittest.TestCase):
    """The planner must touch nothing — no provider, no DB, no LLM."""

    _now = datetime(2026, 5, 6, tzinfo=timezone.utc)

    def test_plan_does_not_call_yfinance_download(self) -> None:
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        with mock.patch(
            "yfinance.download",
            side_effect=AssertionError("yfinance.download must not be called"),
        ), mock.patch(
            "yfinance.Ticker",
            side_effect=AssertionError("yfinance.Ticker must not be called"),
        ):
            pcr.plan_refresh(events, {}, now=self._now)

    def test_plan_does_not_call_price_cache_fetch(self) -> None:
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        with mock.patch(
            "price_cache.fetch_daily_cached",
            side_effect=AssertionError(
                "price_cache.fetch_daily_cached must not be called by the planner"
            ),
        ):
            pcr.plan_refresh(events, {}, now=self._now)

    def test_plan_does_not_call_analyze_event_or_paid_seams(self) -> None:
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        with mock.patch(
            "analyze_event.analyze_event",
            side_effect=AssertionError("analyze_event must not be called"),
        ), mock.patch(
            "auto_backfill_runner.execute_paid_candidate",
            side_effect=AssertionError("execute_paid_candidate must not be called"),
        ):
            pcr.plan_refresh(events, {}, now=self._now)

    def test_module_does_not_import_fastapi_or_paid_modules(self) -> None:
        # Drop any cached import of price_cache_refresh, then re-import
        # in a clean snapshot of sys.modules so we can detect what its
        # import graph actually pulls in.
        before = set(sys.modules)
        sys.modules.pop("price_cache_refresh", None)
        try:
            import price_cache_refresh as _pcr  # noqa: F401
        finally:
            new_modules = set(sys.modules) - before
        forbidden = {
            "fastapi",
            "starlette",
            "api",
            "analyze_event",
            "market_check",
            "yfinance",
            "auto_backfill_runner",
            "auto_backfill_scheduler",
        }
        leaked = forbidden & new_modules
        self.assertEqual(
            leaked, set(),
            f"importing price_cache_refresh pulled in forbidden modules: {leaked}",
        )

    def test_plan_does_not_mutate_inputs(self) -> None:
        cached = {"AAPL": frozenset({date(2026, 4, 1)})}
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        events_snapshot = json.dumps(events, default=str, sort_keys=True)
        cached_snapshot = {k: set(v) for k, v in cached.items()}

        pcr.plan_refresh(events, cached, now=self._now)

        self.assertEqual(json.dumps(events, default=str, sort_keys=True), events_snapshot)
        self.assertEqual({k: set(v) for k, v in cached.items()}, cached_snapshot)


class TestPlanRefreshSelection(unittest.TestCase):
    """Core selection logic — skip taxonomy + window math."""

    _now = datetime(2026, 5, 6, tzinfo=timezone.utc)

    def test_empty_events_yields_no_work_plan(self) -> None:
        plan = pcr.plan_refresh([], {}, now=self._now)
        self.assertEqual(plan.events_considered, 0)
        self.assertEqual(plan.tickers_considered, 0)
        self.assertEqual(plan.refresh_jobs, ())
        self.assertEqual(plan.provider_calls_estimate, 0)
        self.assertFalse(plan.cap_applied)
        self.assertEqual(plan.decision_reason, pcr.DECISION_NO_WORK)

    def test_event_with_empty_market_tickers_is_dropped(self) -> None:
        events = [
            _make_event(event_id=1, event_date=date(2026, 4, 1), tickers=[]),
            _make_event(event_id=2, event_date=date(2026, 4, 2), tickers=None),
        ]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.events_considered, 2)
        self.assertEqual(plan.tickers_considered, 0)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_NO_MARKET_TICKERS], 2)
        self.assertEqual(plan.refresh_jobs, ())

    def test_invalid_event_date_drops_event_with_reason(self) -> None:
        events = [
            _make_event(event_id=1, event_date="not-a-date",
                        tickers=[_make_ticker("AAPL")]),
            _make_event(event_id=2, event_date=None,
                        tickers=[_make_ticker("AAPL")]),
            _make_event(event_id=3, event_date="",
                        tickers=[_make_ticker("AAPL")]),
        ]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_INVALID_EVENT_DATE], 3)
        self.assertEqual(plan.refresh_jobs, ())

    def test_future_event_date_is_invalid(self) -> None:
        events = [_make_event(
            event_id=1,
            event_date=self._now.date() + timedelta(days=10),
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_INVALID_EVENT_DATE], 1)
        self.assertEqual(plan.refresh_jobs, ())

    def test_invalid_ticker_drops_pair_with_reason(self) -> None:
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[
                _make_ticker(""),
                _make_ticker("   "),
                {"role": "beneficiary"},                 # no symbol
                _make_ticker("AAPL (proxy)"),            # proxy stripped → AAPL
                _make_ticker("(proxy)"),                 # proxy stripped → empty
            ],
        )]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        # Four invalid + one valid (AAPL).
        self.assertEqual(plan.tickers_considered, 5)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_INVALID_TICKER], 4)
        self.assertEqual(len(plan.refresh_jobs), 1)
        self.assertEqual(plan.refresh_jobs[0].symbol, "AAPL")

    def test_already_covered_ticker_drops_pair(self) -> None:
        ev_date = date(2026, 4, 1)
        # Cover the entire window: 5 bdays before through 20 bdays after.
        full_window = [
            *_bdays(pcr._bday_offset(ev_date, -5), 5),
            ev_date,
            *_bdays(pcr._bday_offset(ev_date, 1), 20),
        ]
        cached = {"AAPL": frozenset(full_window)}
        events = [_make_event(
            event_id=1, event_date=ev_date,
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, cached, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_ALREADY_COVERED], 1)
        self.assertEqual(plan.refresh_jobs, ())

    def test_partial_coverage_yields_one_interval(self) -> None:
        ev_date = date(2026, 4, 1)
        # Cover the pre-window only; leave the post-window empty.
        pre_only = [
            *_bdays(pcr._bday_offset(ev_date, -5), 5),
            ev_date,
        ]
        cached = {"AAPL": frozenset(pre_only)}
        events = [_make_event(
            event_id=1, event_date=ev_date,
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, cached, now=self._now)
        self.assertEqual(len(plan.refresh_jobs), 1)
        job = plan.refresh_jobs[0]
        self.assertEqual(job.symbol, "AAPL")
        self.assertEqual(len(job.intervals), 1)
        self.assertEqual(job.business_days, 20)
        self.assertEqual(job.provider_calls, 1)
        self.assertEqual(plan.provider_calls_estimate, 1)

    def test_split_coverage_yields_two_intervals(self) -> None:
        ev_date = date(2026, 4, 1)
        # Cover only the event_date itself, leaving the pre-window and
        # post-window each as a missing run.
        cached = {"AAPL": frozenset({ev_date})}
        events = [_make_event(
            event_id=1, event_date=ev_date,
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, cached, now=self._now)
        self.assertEqual(len(plan.refresh_jobs), 1)
        job = plan.refresh_jobs[0]
        self.assertEqual(len(job.intervals), 2)
        self.assertEqual(job.provider_calls, 2)
        self.assertEqual(plan.provider_calls_estimate, 2)

    def test_stale_ticker_skipped_when_latest_cache_too_old(self) -> None:
        ev_date = date(2026, 4, 1)
        # AAPL has cached rows but the latest is over a year before today.
        cached = {"AAPL": frozenset({date(2020, 1, 1), date(2020, 6, 1)})}
        events = [_make_event(
            event_id=1, event_date=ev_date,
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, cached, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_STALE_TICKER], 1)
        self.assertEqual(plan.refresh_jobs, ())

    def test_uncached_ticker_is_not_stale(self) -> None:
        # No rows for this symbol — the planner schedules a refresh.
        ev_date = date(2026, 4, 1)
        events = [_make_event(
            event_id=1, event_date=ev_date,
            tickers=[_make_ticker("BRAND_NEW_SYM")],
        )]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_STALE_TICKER], 0)
        self.assertEqual(len(plan.refresh_jobs), 1)
        self.assertEqual(plan.refresh_jobs[0].symbol, "BRAND_NEW_SYM")

    def test_max_provider_calls_cap_truncates_by_event(self) -> None:
        cfg = pcr.RefreshConfig(max_provider_calls=2)
        # Three independent events, each with two split intervals → 2
        # provider calls each, total 6.  With cap=2, only the first
        # event lands in the plan.
        events: list[dict[str, Any]] = []
        for i in range(1, 4):
            ev_date = date(2026, 4, i)  # Apr 1/2/3 — all weekdays
            events.append(_make_event(
                event_id=i, event_date=ev_date,
                tickers=[_make_ticker(f"SYM{i}")],
            ))
        cached = {f"SYM{i}": frozenset({date(2026, 4, i)}) for i in range(1, 4)}
        plan = pcr.plan_refresh(events, cached, config=cfg, now=self._now)
        self.assertTrue(plan.cap_applied)
        self.assertEqual(plan.decision_reason, pcr.DECISION_CAP_EXHAUSTED)
        self.assertLessEqual(plan.provider_calls_estimate, cfg.max_provider_calls)
        self.assertGreaterEqual(plan.skipped_counts[pcr.SKIP_CAP_EXHAUSTED], 1)
        self.assertEqual(len(plan.refresh_jobs), 1)

    def test_max_events_cap_truncates_by_event_order(self) -> None:
        cfg = pcr.RefreshConfig(max_events=2, max_provider_calls=10_000)
        events = [_make_event(
            event_id=i,
            event_date=date(2026, 4, i),
            tickers=[_make_ticker(f"SYM{i}")],
        ) for i in range(1, 5)]
        plan = pcr.plan_refresh(events, {}, config=cfg, now=self._now)
        self.assertTrue(plan.cap_applied)
        # Two events landed; the other two are recorded as cap skips.
        self.assertEqual(plan.planned_events, 2)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_CAP_EXHAUSTED], 2)

    def test_max_tickers_per_event_cap(self) -> None:
        cfg = pcr.RefreshConfig(max_tickers_per_event=3)
        events = [_make_event(
            event_id=1,
            event_date=date(2026, 4, 1),
            tickers=[_make_ticker(f"SYM{i}") for i in range(8)],
        )]
        plan = pcr.plan_refresh(events, {}, config=cfg, now=self._now)
        # Only the first 3 tickers are considered.
        self.assertEqual(plan.tickers_considered, 3)
        self.assertEqual(len(plan.refresh_jobs), 3)
        self.assertEqual(
            [job.symbol for job in plan.refresh_jobs],
            ["SYM0", "SYM1", "SYM2"],
        )

    def test_decision_reason_planned_when_no_cap(self) -> None:
        events = [_make_event(
            event_id=1, event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.decision_reason, pcr.DECISION_PLANNED)
        self.assertFalse(plan.cap_applied)
        self.assertEqual(len(plan.refresh_jobs), 1)

    def test_plan_is_deterministic(self) -> None:
        events = [_make_event(
            event_id=i, event_date=date(2026, 4, i),
            tickers=[_make_ticker(f"S{i}"), _make_ticker(f"T{i}")],
        ) for i in range(1, 5)]
        plan_a = pcr.plan_refresh(events, {}, now=self._now)
        plan_b = pcr.plan_refresh(events, {}, now=self._now)
        # Tuples are hashable; jobs are frozen dataclasses → equality
        # holds when fields match.
        self.assertEqual(plan_a.refresh_jobs, plan_b.refresh_jobs)
        self.assertEqual(plan_a.skipped_counts, plan_b.skipped_counts)
        self.assertEqual(
            plan_a.provider_calls_estimate, plan_b.provider_calls_estimate,
        )

    def test_invalid_event_object_is_dropped_safely(self) -> None:
        # Strings, ints, lists land in invalid_event_date.
        events = ["not-a-mapping", 42, [{"id": 1}]]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.events_considered, 3)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_INVALID_EVENT_DATE], 3)
        self.assertEqual(plan.refresh_jobs, ())

    def test_event_without_id_is_dropped(self) -> None:
        events = [{"event_date": "2026-04-01", "market_tickers": [_make_ticker("AAPL")]}]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.skipped_counts[pcr.SKIP_INVALID_EVENT_DATE], 1)
        self.assertEqual(plan.refresh_jobs, ())


class TestRefreshPlanShape(unittest.TestCase):
    """Top-level RefreshPlan derived properties."""

    _now = datetime(2026, 5, 6, tzinfo=timezone.utc)

    def test_unique_tickers_dedupes_across_events(self) -> None:
        events = [
            _make_event(event_id=1, event_date=date(2026, 4, 1),
                        tickers=[_make_ticker("AAPL")]),
            _make_event(event_id=2, event_date=date(2026, 4, 2),
                        tickers=[_make_ticker("AAPL"), _make_ticker("MSFT")]),
        ]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        self.assertEqual(plan.unique_tickers, 2)
        self.assertEqual(plan.planned_events, 2)

    def test_total_business_days_sums_across_jobs(self) -> None:
        events = [_make_event(
            event_id=1, event_date=date(2026, 4, 1),
            tickers=[_make_ticker("AAPL")],
        )]
        plan = pcr.plan_refresh(events, {}, now=self._now)
        # Pre 5 + event_date 1 + post 20 = 26 business days uncached.
        self.assertEqual(plan.total_business_days, 26)

    def test_skipped_counts_keys_are_stable(self) -> None:
        plan = pcr.plan_refresh([], {}, now=self._now)
        self.assertEqual(
            tuple(plan.skipped_counts.keys()), pcr.SKIP_COUNT_KEYS,
        )


# ---------------------------------------------------------------------------
# load_inputs — DB read-only contract
# ---------------------------------------------------------------------------


class TestLoadInputsFromTempDB(unittest.TestCase):
    """Seed a fresh temp SQLite DB per test, exercise ``load_inputs``."""

    def setUp(self) -> None:
        self._tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"test_pcr_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute("""
                CREATE TABLE events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_date     TEXT,
                    market_tickers TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    close       REAL,
                    volume      REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp_path)
        except (OSError, PermissionError):
            pass

    def _insert_event(
        self, *,
        event_id: int,
        event_date: str | None,
        tickers: list[dict[str, Any]] | None,
    ) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, market_tickers) VALUES (?, ?, ?)",
                (event_id, event_date, json.dumps(tickers or [])),
            )

    def _insert_cache(
        self, *, ticker: str, dates: list[str], auto_adjust: int = 1,
    ) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            for d in dates:
                conn.execute(
                    "INSERT INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (ticker, d, 100.0, 1_000.0, auto_adjust, "2026-05-01T00:00:00Z"),
                )

    def test_load_inputs_returns_events_with_market_tickers(self) -> None:
        self._insert_event(
            event_id=1, event_date="2026-04-01",
            tickers=[{"symbol": "AAPL"}],
        )
        self._insert_event(
            event_id=2, event_date="2026-04-02",
            tickers=[],   # filtered by load_inputs
        )
        self._insert_event(
            event_id=3, event_date=None,
            tickers=[{"symbol": "MSFT"}],   # missing event_date — filtered
        )

        events, cache_map = pcr.load_inputs(self._tmp_path)

        # Only event 1 survives.
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["id"], 1)
        self.assertEqual(events[0]["event_date"], "2026-04-01")
        self.assertEqual(events[0]["market_tickers"], [{"symbol": "AAPL"}])
        # No cache rows seeded → empty map.
        self.assertEqual(cache_map, {})

    def test_load_inputs_reads_price_cache_for_referenced_tickers(self) -> None:
        self._insert_event(
            event_id=1, event_date="2026-04-01",
            tickers=[{"symbol": "AAPL"}, {"symbol": "MSFT"}],
        )
        self._insert_cache(ticker="AAPL", dates=["2026-03-30", "2026-03-31"])
        self._insert_cache(ticker="MSFT", dates=["2026-03-30"])
        # Cache row for an unreferenced ticker — should NOT appear in
        # the result map.
        self._insert_cache(ticker="UNREF", dates=["2026-03-30"])

        events, cache_map = pcr.load_inputs(self._tmp_path)

        self.assertEqual(len(events), 1)
        self.assertEqual(set(cache_map.keys()), {"AAPL", "MSFT"})
        self.assertEqual(
            cache_map["AAPL"],
            frozenset({date(2026, 3, 30), date(2026, 3, 31)}),
        )
        self.assertEqual(cache_map["MSFT"], frozenset({date(2026, 3, 30)}))

    def test_load_inputs_respects_auto_adjust_flag(self) -> None:
        self._insert_event(
            event_id=1, event_date="2026-04-01",
            tickers=[{"symbol": "AAPL"}],
        )
        self._insert_cache(ticker="AAPL", dates=["2026-03-30"], auto_adjust=0)
        self._insert_cache(ticker="AAPL", dates=["2026-03-31"], auto_adjust=1)

        # Default: auto_adjust=True → only the auto_adjust=1 row.
        _events, cache_map = pcr.load_inputs(self._tmp_path)
        self.assertEqual(cache_map["AAPL"], frozenset({date(2026, 3, 31)}))

        # auto_adjust=False → only the auto_adjust=0 row.
        _events, cache_map = pcr.load_inputs(self._tmp_path, auto_adjust=False)
        self.assertEqual(cache_map["AAPL"], frozenset({date(2026, 3, 30)}))

    def test_load_inputs_since_days_filters_old_events(self) -> None:
        today = datetime.now(timezone.utc).date()
        recent = (today - timedelta(days=10)).isoformat()
        old    = (today - timedelta(days=400)).isoformat()
        self._insert_event(event_id=1, event_date=recent,
                           tickers=[{"symbol": "AAPL"}])
        self._insert_event(event_id=2, event_date=old,
                           tickers=[{"symbol": "MSFT"}])

        events, _ = pcr.load_inputs(self._tmp_path, since_days=30)
        self.assertEqual([ev["id"] for ev in events], [1])

    def test_load_inputs_does_not_write(self) -> None:
        # Read-only mode: the DB is opened with ``mode=ro``.  Any
        # attempted INSERT inside load_inputs would raise; verify the
        # event_count is unchanged across calls.
        self._insert_event(
            event_id=1, event_date="2026-04-01",
            tickers=[{"symbol": "AAPL"}],
        )
        self._insert_cache(ticker="AAPL", dates=["2026-03-30"])

        with sqlite3.connect(self._tmp_path) as conn:
            before_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            before_cache  = conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]

        for _ in range(3):
            pcr.load_inputs(self._tmp_path)

        with sqlite3.connect(self._tmp_path) as conn:
            after_events = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            after_cache  = conn.execute("SELECT COUNT(*) FROM price_cache").fetchone()[0]

        self.assertEqual(before_events, after_events)
        self.assertEqual(before_cache,  after_cache)

    def test_load_inputs_handles_corrupt_market_tickers_json(self) -> None:
        # Bit-rotted JSON in market_tickers must not crash the loader.
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, market_tickers) "
                "VALUES (?, ?, ?)",
                (1, "2026-04-01", "{not valid json"),
            )

        events, cache_map = pcr.load_inputs(self._tmp_path)
        # Bit-rotted row is filtered out (no usable tickers).
        self.assertEqual(events, [])
        self.assertEqual(cache_map, {})


# ---------------------------------------------------------------------------
# End-to-end: load_inputs → plan_refresh, with no provider / no LLM
# ---------------------------------------------------------------------------


class TestEndToEnd(unittest.TestCase):
    """Round-trip from a temp DB through the planner.  Provider, DB
    writers, and LLM seams are all patched to raise so any accidental
    invocation fails the test loudly.
    """

    def setUp(self) -> None:
        self._tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"test_pcr_e2e_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute("""
                CREATE TABLE events (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_date     TEXT,
                    market_tickers TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    close       REAL,
                    volume      REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)
            conn.execute(
                "INSERT INTO events (id, event_date, market_tickers) VALUES (?, ?, ?)",
                (1, "2026-04-01", json.dumps([{"symbol": "AAPL"}])),
            )
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-04-01", 180.0, 1_000_000.0, 1, "2026-05-01T00:00:00Z"),
            )

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp_path)
        except (OSError, PermissionError):
            pass

    def test_round_trip_under_paid_seam_raisers(self) -> None:
        now = datetime(2026, 5, 6, tzinfo=timezone.utc)
        with mock.patch(
            "yfinance.download",
            side_effect=AssertionError("yfinance.download forbidden"),
        ), mock.patch(
            "yfinance.Ticker",
            side_effect=AssertionError("yfinance.Ticker forbidden"),
        ), mock.patch(
            "price_cache.fetch_daily_cached",
            side_effect=AssertionError("price_cache.fetch_daily_cached forbidden"),
        ), mock.patch(
            "analyze_event.analyze_event",
            side_effect=AssertionError("analyze_event forbidden"),
        ), mock.patch(
            "auto_backfill_runner.execute_paid_candidate",
            side_effect=AssertionError("execute_paid_candidate forbidden"),
        ):
            events, cache_map = pcr.load_inputs(self._tmp_path)
            plan = pcr.plan_refresh(events, cache_map, now=now)

        # AAPL has one cached date inside the window → split into a
        # pre-window interval and a post-window interval.
        self.assertEqual(len(plan.refresh_jobs), 1)
        self.assertEqual(plan.refresh_jobs[0].symbol, "AAPL")
        self.assertEqual(plan.refresh_jobs[0].provider_calls, 2)
        self.assertEqual(plan.provider_calls_estimate, 2)
        self.assertEqual(plan.decision_reason, pcr.DECISION_PLANNED)


# ---------------------------------------------------------------------------
# Executor — confirm-gated write contract
# ---------------------------------------------------------------------------


class _ExecutorTestBase(unittest.TestCase):
    """Shared temp-DB + simple-plan fixture used by the executor suites."""

    def setUp(self) -> None:
        self._tmp_path = os.path.join(
            tempfile.gettempdir(),
            f"test_pcr_exec_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    close       REAL,
                    volume      REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp_path)
        except (OSError, PermissionError):
            pass

    def _row_count(self, *, ticker: str | None = None) -> int:
        with sqlite3.connect(self._tmp_path) as conn:
            if ticker is None:
                cur = conn.execute("SELECT COUNT(*) FROM price_cache")
            else:
                cur = conn.execute(
                    "SELECT COUNT(*) FROM price_cache WHERE ticker = ?",
                    (ticker,),
                )
            return int(cur.fetchone()[0])

    def _plan_with_one_job(
        self,
        *,
        symbol: str = "AAPL",
        intervals: tuple[tuple[str, str], ...] = (("2026-04-01", "2026-04-03"),),
        max_provider_calls: int = 50,
    ) -> pcr.RefreshPlan:
        job = pcr.TickerRefreshJob(
            event_id=1,
            event_date="2026-04-01",
            symbol=symbol,
            intervals=intervals,
            business_days=sum(1 for _ in intervals),
            auto_adjust=True,
        )
        return pcr.RefreshPlan(
            events_considered=1,
            tickers_considered=1,
            refresh_jobs=(job,),
            skipped_counts={k: 0 for k in pcr.SKIP_COUNT_KEYS},
            provider_calls_estimate=len(intervals),
            max_provider_calls=max_provider_calls,
            cap_applied=False,
            decision_reason=pcr.DECISION_PLANNED,
        )

    @staticmethod
    def _provider_returning(
        rows_by_symbol: dict[str, list[pcr.ProviderRow]],
    ) -> mock.MagicMock:
        """Return a MagicMock provider that yields per-symbol rows."""
        def _fetch(symbol, start, end, auto_adjust):
            return list(rows_by_symbol.get(symbol, []))
        return mock.MagicMock(side_effect=_fetch, name="provider_fetch")


class TestExecutorConfirmGate(_ExecutorTestBase):
    """``confirm=True`` is mandatory before any write or provider call."""

    def test_default_invocation_is_dry_run(self) -> None:
        plan = self._plan_with_one_job()
        provider = mock.MagicMock(
            side_effect=AssertionError("provider must not be called in dry run"),
        )

        result = pcr.execute_refresh(
            plan, self._tmp_path, provider_fetch=provider,
        )

        self.assertTrue(result.dry_run)
        self.assertFalse(result.confirmed)
        self.assertEqual(result.attempted_jobs, 0)
        self.assertEqual(result.written_rows, 0)
        self.assertEqual(result.skipped_jobs, 1)
        self.assertEqual(result.errors, ())
        self.assertEqual(result.provider_calls, 0)
        provider.assert_not_called()

    def test_confirm_false_writes_nothing_to_db(self) -> None:
        plan = self._plan_with_one_job()
        provider = self._provider_returning({
            "AAPL": [pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6)],
        })

        before = self._row_count()
        pcr.execute_refresh(
            plan, self._tmp_path, confirm=False, provider_fetch=provider,
        )
        after = self._row_count()

        self.assertEqual(before, 0)
        self.assertEqual(after, 0)
        provider.assert_not_called()

    def test_confirm_true_without_provider_is_safe_noop(self) -> None:
        plan = self._plan_with_one_job()
        before = self._row_count()
        result = pcr.execute_refresh(plan, self._tmp_path, confirm=True)
        after = self._row_count()

        self.assertFalse(result.dry_run)
        self.assertTrue(result.confirmed)
        self.assertEqual(result.attempted_jobs, 0)
        self.assertEqual(result.written_rows, 0)
        self.assertEqual(result.skipped_jobs, 1)
        self.assertEqual(after, before)


class TestExecutorWritePath(_ExecutorTestBase):
    """``confirm=True`` + provider seam writes only the expected rows."""

    def test_confirm_true_writes_provider_rows(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-03"),),
        )
        rows = [
            pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1.0e6),
            pcr.ProviderRow(date="2026-04-02", close=181.0, volume=1.1e6),
            pcr.ProviderRow(date="2026-04-03", close=182.0, volume=1.2e6),
        ]
        provider = self._provider_returning({"AAPL": rows})

        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )

        self.assertTrue(result.confirmed)
        self.assertFalse(result.dry_run)
        self.assertEqual(result.attempted_jobs, 1)
        self.assertEqual(result.written_rows, 3)
        self.assertEqual(result.skipped_jobs, 0)
        self.assertEqual(result.errors, ())
        self.assertEqual(result.provider_calls, 1)
        self.assertEqual(self._row_count(ticker="AAPL"), 3)
        provider.assert_called_once()
        # Provider received the correct args.
        args, kwargs = provider.call_args
        self.assertEqual(args[0], "AAPL")
        self.assertEqual(args[1], date(2026, 4, 1))
        self.assertEqual(args[2], date(2026, 4, 3))
        self.assertIs(args[3], True)  # auto_adjust

    def test_writes_only_to_price_cache_table(self) -> None:
        # Other tables in the same DB must not be touched.  Create a
        # sibling table and assert it stays untouched.
        with sqlite3.connect(self._tmp_path) as conn:
            conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO events (id) VALUES (1)")
            conn.execute("INSERT INTO events (id) VALUES (2)")

        plan = self._plan_with_one_job()
        provider = self._provider_returning({
            "AAPL": [pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6)],
        })
        pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )

        with sqlite3.connect(self._tmp_path) as conn:
            ev_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.assertEqual(ev_count, 2)

    def test_uses_injected_fetched_at_timestamp(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-01"),),
        )
        provider = self._provider_returning({
            "AAPL": [pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6)],
        })
        pcr.execute_refresh(
            plan, self._tmp_path, confirm=True,
            provider_fetch=provider, fetched_at="2026-05-06T12:00:00Z",
        )
        with sqlite3.connect(self._tmp_path) as conn:
            row = conn.execute(
                "SELECT fetched_at FROM price_cache WHERE ticker = ?",
                ("AAPL",),
            ).fetchone()
        self.assertEqual(row[0], "2026-05-06T12:00:00Z")

    def test_idempotent_repeated_write(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-02"),),
        )
        rows = [
            pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6),
            pcr.ProviderRow(date="2026-04-02", close=181.0, volume=1.1e6),
        ]
        provider = self._provider_returning({"AAPL": rows})

        pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
            fetched_at="2026-05-06T12:00:00Z",
        )
        first_count = self._row_count(ticker="AAPL")
        # Re-run.  INSERT OR REPLACE leaves the table at the same
        # cardinality.
        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
            fetched_at="2026-05-07T12:00:00Z",
        )
        second_count = self._row_count(ticker="AAPL")

        self.assertEqual(first_count, 2)
        self.assertEqual(second_count, 2)
        self.assertEqual(result.written_rows, 2)
        # The fetched_at column was overwritten on re-run.
        with sqlite3.connect(self._tmp_path) as conn:
            stamps = {
                row[0] for row in conn.execute(
                    "SELECT fetched_at FROM price_cache",
                )
            }
        self.assertEqual(stamps, {"2026-05-07T12:00:00Z"})

    def test_returns_zero_writes_when_provider_returns_empty(self) -> None:
        plan = self._plan_with_one_job()
        provider = self._provider_returning({"AAPL": []})

        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )

        self.assertEqual(result.attempted_jobs, 1)
        self.assertEqual(result.written_rows, 0)
        self.assertEqual(result.errors, ())
        self.assertEqual(self._row_count(), 0)


class TestExecutorErrorIsolation(_ExecutorTestBase):
    """A provider raise on one interval must not poison the run."""

    def test_provider_error_isolated_per_interval(self) -> None:
        # Two jobs.  AAPL's provider call raises; MSFT succeeds.
        good_rows = [
            pcr.ProviderRow(date="2026-04-01", close=300.0, volume=2e6),
        ]

        def _fetch(symbol, start, end, auto_adjust):
            if symbol == "AAPL":
                raise RuntimeError("simulated provider blow-up")
            return list(good_rows)

        provider = mock.MagicMock(side_effect=_fetch, name="provider_fetch")
        plan = pcr.RefreshPlan(
            events_considered=2,
            tickers_considered=2,
            refresh_jobs=(
                pcr.TickerRefreshJob(
                    event_id=1, event_date="2026-04-01", symbol="AAPL",
                    intervals=(("2026-04-01", "2026-04-01"),),
                    business_days=1, auto_adjust=True,
                ),
                pcr.TickerRefreshJob(
                    event_id=2, event_date="2026-04-02", symbol="MSFT",
                    intervals=(("2026-04-01", "2026-04-01"),),
                    business_days=1, auto_adjust=True,
                ),
            ),
            skipped_counts={k: 0 for k in pcr.SKIP_COUNT_KEYS},
            provider_calls_estimate=2,
            max_provider_calls=50,
            cap_applied=False,
            decision_reason=pcr.DECISION_PLANNED,
        )

        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )

        # Both jobs were attempted; one succeeded, one captured an error.
        self.assertEqual(result.attempted_jobs, 2)
        self.assertEqual(result.written_rows, 1)
        self.assertEqual(self._row_count(ticker="AAPL"),  0)
        self.assertEqual(self._row_count(ticker="MSFT"),  1)
        self.assertEqual(len(result.errors), 1)
        err = result.errors[0]
        self.assertEqual(err.symbol, "AAPL")
        self.assertEqual(err.error_type, "RuntimeError")
        self.assertIn("simulated provider blow-up", err.message)
        self.assertFalse(result.ok)


class TestExecutorCapEnforcement(_ExecutorTestBase):
    """Defensive cap: the executor must never overshoot
    ``plan.max_provider_calls`` even if the plan is over-stuffed.
    """

    def test_executor_stops_at_plan_cap(self) -> None:
        # Hand-construct a plan that already overshoots the cap (cap=2,
        # 4 intervals across 2 jobs).  The executor must call the
        # provider at most twice and skip the rest.
        provider = mock.MagicMock(side_effect=lambda *a, **kw: [
            pcr.ProviderRow(date="2026-04-01", close=100.0, volume=1.0),
        ])
        plan = pcr.RefreshPlan(
            events_considered=2,
            tickers_considered=2,
            refresh_jobs=(
                pcr.TickerRefreshJob(
                    event_id=1, event_date="2026-04-01", symbol="AAPL",
                    intervals=(
                        ("2026-04-01", "2026-04-01"),
                        ("2026-04-03", "2026-04-03"),
                        ("2026-04-05", "2026-04-05"),
                    ),
                    business_days=3, auto_adjust=True,
                ),
                pcr.TickerRefreshJob(
                    event_id=2, event_date="2026-04-02", symbol="MSFT",
                    intervals=(("2026-04-01", "2026-04-01"),),
                    business_days=1, auto_adjust=True,
                ),
            ),
            skipped_counts={k: 0 for k in pcr.SKIP_COUNT_KEYS},
            provider_calls_estimate=4,
            max_provider_calls=2,
            cap_applied=True,
            decision_reason=pcr.DECISION_CAP_EXHAUSTED,
        )

        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )

        self.assertEqual(provider.call_count, 2)
        self.assertEqual(result.provider_calls, 2)
        # AAPL was attempted (2 of its 3 intervals fetched); MSFT was
        # skipped because the cap was already exhausted.
        self.assertEqual(result.attempted_jobs, 1)
        self.assertEqual(result.skipped_jobs, 1)
        self.assertEqual(self._row_count(ticker="MSFT"), 0)

    def test_zero_cap_skips_all_jobs(self) -> None:
        provider = mock.MagicMock(
            side_effect=AssertionError("provider must not be called when cap=0"),
        )
        plan = self._plan_with_one_job(max_provider_calls=0)
        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )
        self.assertEqual(result.attempted_jobs, 0)
        self.assertEqual(result.written_rows, 0)
        self.assertEqual(result.skipped_jobs, 1)
        provider.assert_not_called()


class TestExecutorPaidSeamPurity(_ExecutorTestBase):
    """The executor must never reach an LLM / paid auto-backfill seam."""

    def test_executor_never_calls_llm_or_paid_seams(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-01"),),
        )
        provider = self._provider_returning({
            "AAPL": [pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6)],
        })

        with mock.patch(
            "analyze_event.analyze_event",
            side_effect=AssertionError("analyze_event forbidden"),
        ), mock.patch(
            "auto_backfill_runner.execute_paid_candidate",
            side_effect=AssertionError("execute_paid_candidate forbidden"),
        ), mock.patch(
            "yfinance.download",
            side_effect=AssertionError("yfinance.download forbidden"),
        ), mock.patch(
            "yfinance.Ticker",
            side_effect=AssertionError("yfinance.Ticker forbidden"),
        ):
            result = pcr.execute_refresh(
                plan, self._tmp_path, confirm=True, provider_fetch=provider,
            )

        self.assertTrue(result.confirmed)
        self.assertEqual(result.written_rows, 1)
        self.assertEqual(result.errors, ())

    def test_dry_run_invokes_no_provider_seam(self) -> None:
        plan = self._plan_with_one_job()
        # ANY provider seam getting invoked under confirm=False is a
        # contract violation.  Pass a raiser to fail loudly.
        raiser = mock.MagicMock(
            side_effect=AssertionError("provider must not be called under dry-run"),
        )
        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=False, provider_fetch=raiser,
        )
        self.assertTrue(result.dry_run)
        self.assertEqual(self._row_count(), 0)
        raiser.assert_not_called()


class TestExecutorRowFiltering(_ExecutorTestBase):
    """Bad rows from the provider mock are dropped silently."""

    def test_rows_with_missing_date_are_dropped(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-02"),),
        )
        # One good row, two malformed.
        rows = [
            pcr.ProviderRow(date="2026-04-01", close=180.0, volume=1e6),
            {"date": "", "close": 1.0, "volume": 1.0},  # type: ignore[list-item]
            {"close": 1.0, "volume": 1.0},              # type: ignore[list-item]
        ]
        provider = self._provider_returning({"AAPL": rows})  # type: ignore[arg-type]

        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )
        self.assertEqual(result.written_rows, 1)
        self.assertEqual(self._row_count(ticker="AAPL"), 1)

    def test_dict_rows_are_accepted(self) -> None:
        plan = self._plan_with_one_job(
            intervals=(("2026-04-01", "2026-04-01"),),
        )
        provider = self._provider_returning({
            "AAPL": [{"date": "2026-04-01", "close": 180.0, "volume": 1e6}],  # type: ignore[list-item]
        })  # type: ignore[arg-type]
        result = pcr.execute_refresh(
            plan, self._tmp_path, confirm=True, provider_fetch=provider,
        )
        self.assertEqual(result.written_rows, 1)


if __name__ == "__main__":
    unittest.main()
