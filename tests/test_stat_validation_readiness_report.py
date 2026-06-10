"""Tests for ``scripts/stat_validation_readiness_report.py``.

Pin the read-only contract:

* Every per-event check is computed from a hand-rolled temp DB
  containing exactly the events + price_cache rows the test needs;
  no production schema migrations are exercised.
* Aggregate counts always reflect the full archive — ``--limit``
  truncates only the surfaced ``events`` list.
* Per-event entries are sorted by ``id`` ascending and carry the
  required keys (``event_id``, ``event_date``, ``primary_ticker``,
  ``checks``, ``fully_ready``).
* ``--json`` and ``--db-path`` plumbing.
* Repeated runs leave events + price_cache byte-identical.
* No provider, yfinance, market_check, market_data,
  ``price_cache.fetch_daily_cached``, LLM, or FastAPI seam invoked.
* Only ``SELECT`` statements are issued against the DB.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import stat_validation_readiness_report as report  # noqa: E402


# Hand-rolled minimal DDL — only the columns the report actually
# reads.  Avoiding ``db.init_db`` keeps the fixture decoupled from
# the production schema migrations and lets the tests pin the SQL
# contract directly.
_EVENTS_DDL = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT
)
""".strip()

_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()


_TOP_KEYS = (
    "total_events",
    "events_with_event_date",
    "events_with_market_tickers",
    "events_with_event_date_and_tickers",
    "events_with_1d_forward_cache",
    "events_with_5d_forward_cache",
    "events_with_20d_forward_cache",
    "events_missing_benchmark_proxy",
    "events_with_insufficient_estimation_window",
    "events_fully_ready",
    "curated_intake_excluded_count",
    "events",
    "recommended_next_action",
)

_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "checks",
    "fully_ready",
)

_CHECK_KEYS = (
    "has_event_date",
    "has_market_tickers",
    "forward_cache_1d",
    "forward_cache_5d",
    "forward_cache_20d",
    "benchmark_proxy_available",
    "estimation_window_sufficient",
)


_BENCHMARK_TICKER = report._BENCHMARK_TICKER  # "SPY"
_ESTIMATION_WINDOW = report._ESTIMATION_WINDOW  # 60
_FETCHED_AT = "2026-05-06T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_event(
    conn: sqlite3.Connection,
    *,
    headline: str = "headline",
    event_date: str | None = None,
    market_tickers: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, event_date, market_tickers) "
        "VALUES (?, ?, ?)",
        (headline, event_date, market_tickers),
    )
    return int(cur.lastrowid)


def _seed_cache_row(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    date_str: str,
    auto_adjust: int = 1,
    close: float = 100.0,
    volume: float = 5_000_000.0,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO price_cache "
        "(ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date_str, close, volume, auto_adjust, _FETCHED_AT),
    )


def _business_day_offset(start: date, n: int) -> date:
    """Match the script's calendar so test fixtures pin the same windows."""
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


def _seed_pre_event_cache(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_date: date,
    n_business_days: int,
) -> None:
    """Seed ``n_business_days`` distinct cached dates strictly before
    ``event_date`` so the estimation-window check can flip on demand.
    """
    seeded = 0
    cursor = event_date - timedelta(days=1)
    while seeded < n_business_days:
        if cursor.weekday() < 5:
            _seed_cache_row(conn,
                            ticker=ticker, date_str=cursor.isoformat())
            seeded += 1
        cursor = cursor - timedelta(days=1)


def _seed_full_cache_for_event(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_date: date,
    benchmark: str = _BENCHMARK_TICKER,
) -> None:
    """Seed every row needed to flip every readiness check to True
    for one ``(ticker, event_date)`` pair: the estimation window for
    the ticker, the 1d/5d/20d forward dates for the ticker, and the
    20d forward date for the benchmark.
    """
    _seed_pre_event_cache(
        conn, ticker=ticker, event_date=event_date,
        n_business_days=_ESTIMATION_WINDOW,
    )
    for h in (1, 5, 20):
        target = _business_day_offset(event_date, h)
        _seed_cache_row(conn, ticker=ticker, date_str=target.isoformat())
    benchmark_target = _business_day_offset(event_date, 20)
    _seed_cache_row(
        conn, ticker=benchmark, date_str=benchmark_target.isoformat(),
    )


def _snapshot_tables(db_path: str) -> tuple[list, list]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute("SELECT * FROM events ORDER BY id"))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svrr_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._tmp)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_per_event_entry_has_every_required_key(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(len(result["events"]), 1)
        entry = result["events"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, entry, f"per-event missing field: {key}")
        for key in _CHECK_KEYS:
            self.assertIn(key, entry["checks"],
                          f"checks missing field: {key}")

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# Empty / minimal archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(_Base):
    def test_empty_archive_zeros_every_aggregate(self) -> None:
        result = report.summarize_readiness(db_path=self._tmp)
        for key in _TOP_KEYS:
            if key in ("events", "recommended_next_action"):
                continue
            self.assertEqual(result[key], 0,
                             f"{key} should be 0 on empty archive")
        self.assertEqual(result["events"], [])


class TestMissingDb(_Base):
    def test_missing_db_returns_empty_shape(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(), f"nocreate_svrr_{uuid.uuid4().hex}.db",
        )
        self.addCleanup(lambda: os.path.exists(missing) and os.remove(missing))
        result = report.summarize_readiness(db_path=missing)
        self.assertEqual(result["total_events"], 0)
        self.assertEqual(result["events"], [])

    def test_missing_db_does_not_create_file(self) -> None:
        # A clean clone has no events.db.  Running the report against a
        # missing path must NOT leave a stray empty events.db behind.
        missing = os.path.join(
            tempfile.gettempdir(), f"nocreate_svrr_{uuid.uuid4().hex}.db",
        )
        self.addCleanup(lambda: os.path.exists(missing) and os.remove(missing))
        self.assertFalse(os.path.exists(missing))
        report.summarize_readiness(db_path=missing)
        self.assertFalse(
            os.path.exists(missing),
            "report must not create a DB file on a missing path",
        )


# ---------------------------------------------------------------------------
# Individual readiness checks
# ---------------------------------------------------------------------------


class TestEventDateAndTickers(_Base):
    def test_missing_event_date_fails_event_date_check(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        entry = result["events"][0]
        self.assertFalse(entry["checks"]["has_event_date"])
        self.assertTrue(entry["checks"]["has_market_tickers"])
        # Forward / estimation checks degrade to False without
        # event_date — every cache check is anchored to the date.
        self.assertFalse(entry["checks"]["forward_cache_1d"])
        self.assertFalse(entry["checks"]["forward_cache_5d"])
        self.assertFalse(entry["checks"]["forward_cache_20d"])
        self.assertFalse(entry["checks"]["benchmark_proxy_available"])
        self.assertFalse(entry["checks"]["estimation_window_sufficient"])
        self.assertFalse(entry["fully_ready"])
        self.assertEqual(result["events_with_event_date"],     0)
        self.assertEqual(result["events_with_market_tickers"], 1)

    def test_empty_event_date_string_fails_check(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertFalse(result["events"][0]["checks"]["has_event_date"])
        self.assertEqual(result["events_with_event_date"], 0)

    def test_unparseable_event_date_fails_check(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="not-a-date",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertFalse(result["events"][0]["checks"]["has_event_date"])

    def test_missing_market_tickers_fails_check(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers=None)
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers="")
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers="[]")
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers=json.dumps(
                            [{"symbol": ""}, {"symbol": "  "}],
                        ))
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers="not-json")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(result["total_events"],               5)
        self.assertEqual(result["events_with_market_tickers"], 0)
        for entry in result["events"]:
            self.assertFalse(entry["checks"]["has_market_tickers"])
            self.assertIsNone(entry["primary_ticker"])

    def test_market_tickers_picks_first_non_empty_symbol(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps(
                    [{"symbol": ""}, {"symbol": "msft"}, {"symbol": "AAPL"}],
                ),
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        # First non-empty symbol wins; symbols are upper-cased.
        self.assertEqual(result["events"][0]["primary_ticker"], "MSFT")


class TestForwardCache(_Base):
    def test_forward_horizon_flips_when_cache_has_post_event_row(self) -> None:
        # event_date = 2026-04-15 (Wed).  Business-day offsets:
        #   +1bd = 2026-04-16
        #   +5bd = 2026-04-22
        #  +20bd = 2026-05-13
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # Seed a row exactly at +1bd — should flip 1d only.
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-16")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        checks = result["events"][0]["checks"]
        self.assertTrue(checks["forward_cache_1d"])
        self.assertFalse(checks["forward_cache_5d"])
        self.assertFalse(checks["forward_cache_20d"])

    def test_forward_horizon_satisfied_by_later_row(self) -> None:
        # A row past +20bd should satisfy every horizon (1d, 5d, 20d).
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-06-01")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        checks = result["events"][0]["checks"]
        self.assertTrue(checks["forward_cache_1d"])
        self.assertTrue(checks["forward_cache_5d"])
        self.assertTrue(checks["forward_cache_20d"])

    def test_forward_horizon_misses_pre_event_rows_only(self) -> None:
        # Cache contains only pre-event rows — every forward horizon
        # check fails, but an estimation window can still pass when
        # there are >=60 of them.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_pre_event_cache(
                conn, ticker="AAPL", event_date=ed,
                n_business_days=80,  # > 60 so estimation passes
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        checks = result["events"][0]["checks"]
        self.assertFalse(checks["forward_cache_1d"])
        self.assertFalse(checks["forward_cache_5d"])
        self.assertFalse(checks["forward_cache_20d"])
        self.assertTrue(checks["estimation_window_sufficient"])

    def test_aa0_and_aa1_dates_are_unioned_for_readiness(self) -> None:
        # Forward-cache check should not care about the auto_adjust
        # flag — a row at aa=0 alone is enough to flip the horizon.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-16",
                            auto_adjust=0)
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertTrue(result["events"][0]["checks"]["forward_cache_1d"])


class TestBenchmarkProxy(_Base):
    def test_missing_spy_at_20bd_marks_benchmark_unavailable(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # AAPL coverage is fine; SPY has no rows.
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-06-01")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertFalse(
            result["events"][0]["checks"]["benchmark_proxy_available"],
        )
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)

    def test_spy_row_at_20bd_marks_benchmark_available(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # +20bd from 2026-04-15 is 2026-05-13.
            _seed_cache_row(conn,
                            ticker=_BENCHMARK_TICKER, date_str="2026-05-13")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertTrue(
            result["events"][0]["checks"]["benchmark_proxy_available"],
        )
        self.assertEqual(result["events_missing_benchmark_proxy"], 0)

    def test_spy_row_before_20bd_does_not_satisfy_benchmark(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # Row at +5bd only — not enough for the 20bd benchmark check.
            _seed_cache_row(conn,
                            ticker=_BENCHMARK_TICKER, date_str="2026-04-22")
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertFalse(
            result["events"][0]["checks"]["benchmark_proxy_available"],
        )


class TestEstimationWindow(_Base):
    def test_sixty_pre_event_dates_satisfies_estimation_window(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_pre_event_cache(
                conn, ticker="AAPL", event_date=ed,
                n_business_days=_ESTIMATION_WINDOW,
            )
            conn.commit()
        checks = report.summarize_readiness(db_path=self._tmp)["events"][0]["checks"]
        self.assertTrue(checks["estimation_window_sufficient"])

    def test_just_below_threshold_fails_estimation_window(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_pre_event_cache(
                conn, ticker="AAPL", event_date=ed,
                n_business_days=_ESTIMATION_WINDOW - 1,
            )
            conn.commit()
        checks = report.summarize_readiness(db_path=self._tmp)["events"][0]["checks"]
        self.assertFalse(checks["estimation_window_sufficient"])

    def test_post_event_rows_do_not_count_toward_estimation_window(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # Many post-event rows, only 5 pre-event ones — estimation
            # window must still fail.
            _seed_pre_event_cache(
                conn, ticker="AAPL", event_date=ed, n_business_days=5,
            )
            for offset in range(1, 80):
                cursor = ed + timedelta(days=offset)
                if cursor.weekday() < 5:
                    _seed_cache_row(conn, ticker="AAPL",
                                    date_str=cursor.isoformat())
            conn.commit()
        checks = report.summarize_readiness(db_path=self._tmp)["events"][0]["checks"]
        self.assertFalse(checks["estimation_window_sufficient"])

    def test_event_date_dates_themselves_do_not_count_as_pre_event(self) -> None:
        # A single row at exactly event_date is "not strictly before",
        # so it does not contribute to the pre-event count.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str=ed.isoformat())
            _seed_pre_event_cache(
                conn, ticker="AAPL", event_date=ed,
                n_business_days=_ESTIMATION_WINDOW - 1,
            )
            conn.commit()
        checks = report.summarize_readiness(db_path=self._tmp)["events"][0]["checks"]
        self.assertFalse(checks["estimation_window_sufficient"])


class TestFullyReady(_Base):
    def test_event_with_full_cache_coverage_is_fully_ready(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        entry = result["events"][0]
        self.assertTrue(entry["fully_ready"])
        self.assertEqual(result["events_fully_ready"], 1)
        for k in _CHECK_KEYS:
            self.assertTrue(entry["checks"][k], f"check {k} is False")


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------


class TestAggregateCounts(_Base):
    def test_mixed_archive_aggregates_decompose_correctly(self) -> None:
        # Each event takes a distinct event_date so the benchmark
        # check is per-event independent — without distinct dates,
        # SPY seeded for event 1 would satisfy the +20bd target for
        # other events sharing that date.
        ed1 = date(2026, 4, 15)
        ed2 = date(2026, 6, 15)
        ed3 = date(2026, 8, 17)
        with self._conn() as conn:
            # Event 1 — fully ready (own SPY at +20bd from ed1).
            _seed_event(
                conn, event_date=ed1.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed1,
            )
            # Event 2 — has date and ticker but no cache for ticker
            # OR for SPY at ed2's +20bd target.
            _seed_event(
                conn, event_date=ed2.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            # Event 3 — date but no tickers; no SPY at ed3's +20bd.
            _seed_event(conn, event_date=ed3.isoformat(),
                        market_tickers="[]")
            # Event 4 — tickers but no date.
            _seed_event(conn, event_date=None,
                        market_tickers=json.dumps([{"symbol": "GOOG"}]))
            # Event 5 — neither.
            _seed_event(conn, event_date=None, market_tickers="[]")
            conn.commit()

        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(result["total_events"],                       5)
        self.assertEqual(result["events_with_event_date"],             3)
        self.assertEqual(result["events_with_market_tickers"],         3)
        self.assertEqual(result["events_with_event_date_and_tickers"], 2)
        self.assertEqual(result["events_with_1d_forward_cache"],       1)
        self.assertEqual(result["events_with_5d_forward_cache"],       1)
        self.assertEqual(result["events_with_20d_forward_cache"],      1)
        # 4 events lack benchmark coverage at +20bd.  Only event 1
        # has SPY seeded at the right target.
        self.assertEqual(result["events_missing_benchmark_proxy"],          4)
        self.assertEqual(result["events_with_insufficient_estimation_window"], 4)
        self.assertEqual(result["events_fully_ready"],                 1)

    def test_recommendation_flips_when_archive_fully_ready(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        ready_msg = report.summarize_readiness(
            db_path=self._tmp,
        )["recommended_next_action"]

        # Add one event that breaks readiness.
        with self._conn() as conn:
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "X"}]),
            )
            conn.commit()
        gappy_msg = report.summarize_readiness(
            db_path=self._tmp,
        )["recommended_next_action"]
        self.assertNotEqual(ready_msg, gappy_msg)


# ---------------------------------------------------------------------------
# Sort order + --limit
# ---------------------------------------------------------------------------


class TestSortAndLimit(_Base):
    def _seed_n_events(self, n: int) -> None:
        with self._conn() as conn:
            for i in range(n):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": f"T{i:02d}"}]),
                )
            conn.commit()

    def test_events_listed_in_id_ascending_order(self) -> None:
        self._seed_n_events(5)
        result = report.summarize_readiness(db_path=self._tmp)
        ids = [e["event_id"] for e in result["events"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_events_only(self) -> None:
        self._seed_n_events(7)
        result = report.summarize_readiness(db_path=self._tmp, limit=3)
        self.assertEqual(result["total_events"],         7)
        self.assertEqual(result["events_with_market_tickers"], 7)
        self.assertEqual(len(result["events"]),          3)
        # Truncation preserves id order.
        self.assertEqual(
            [e["event_id"] for e in result["events"]],
            sorted(e["event_id"] for e in result["events"]),
        )

    def test_negative_limit_clamps_to_zero(self) -> None:
        self._seed_n_events(3)
        result = report.summarize_readiness(db_path=self._tmp, limit=-1)
        self.assertEqual(result["events"],          [])
        self.assertEqual(result["total_events"],    3)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(_Base):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = report.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_text_output_summarises_each_field(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        rc, output = self._run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        for needle in (
            "Total events",
            "with event_date",
            "with market_tickers",
            "forward cache ready (1d)",
            "forward cache ready (5d)",
            "forward cache ready (20d)",
            "missing benchmark proxy",
            "insufficient estimation window",
            "fully ready",
            "Recommended next action",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_json_output_carries_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp, "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(len(body["events"]), 1)
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, body["events"][0],
                          f"per-event missing field: {key}")
        for key in _CHECK_KEYS:
            self.assertIn(key, body["events"][0]["checks"],
                          f"checks missing field: {key}")

    def test_db_path_resolves_supplied_archive(self) -> None:
        empty = os.path.join(
            tempfile.gettempdir(),
            f"test_svrr_alt_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(empty)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.commit()
        finally:
            conn.close()
        try:
            rc, output = self._run_cli([
                "--db-path", empty,
                "--json",
            ])
            self.assertEqual(rc, 0)
            body = json.loads(output)
            self.assertEqual(body["total_events"], 0)
            self.assertEqual(body["events"],       [])
        finally:
            try:
                os.remove(empty)
            except (OSError, PermissionError):
                pass

    def test_limit_truncates_per_event_only(self) -> None:
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp, "--limit", "1", "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_events"], 3)
        self.assertEqual(len(body["events"]),  1)


# ---------------------------------------------------------------------------
# No mutation / repeated-run determinism
# ---------------------------------------------------------------------------


class TestNoMutation(_Base):
    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()

        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            report.summarize_readiness(db_path=self._tmp)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical across "
            "repeated runs",
        )

    def test_repeated_runs_return_identical_payload(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        first = report.summarize_readiness(db_path=self._tmp)
        for _ in range(3):
            self.assertEqual(report.summarize_readiness(db_path=self._tmp), first)


# ---------------------------------------------------------------------------
# Read-only SQL guard
# ---------------------------------------------------------------------------


class TestReadOnlySql(_Base):
    def test_only_select_statements_executed(self) -> None:
        # ``Connection.set_trace_callback`` fires for every statement
        # the connection actually executes.  Wrap ``sqlite3.connect``
        # so every connection the script opens installs the callback;
        # pin the read-only contract end-to-end by asserting every
        # captured statement starts with SELECT.
        import sqlite3 as _sqlite3

        recorded: list[str] = []
        real_connect = _sqlite3.connect

        def tracing_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(recorded.append)
            return conn

        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-16")
            conn.commit()

        with patch.object(_sqlite3, "connect", side_effect=tracing_connect):
            result = report.summarize_readiness(db_path=self._tmp)

        self.assertEqual(result["total_events"], 1)
        non_blank = [sql for sql in recorded if sql and sql.strip()]
        self.assertGreaterEqual(
            len(non_blank), 1,
            "trace callback captured no SQL statements",
        )
        for sql in non_blank:
            head = sql.lstrip().split(None, 1)[0].upper()
            self.assertEqual(
                head, "SELECT",
                f"non-SELECT statement issued by report path: {sql!r}",
            )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-16")
            conn.commit()

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("price_cache",  "_purge_corrupt_rows"),
            ("price_cache",  "_ensure_table"),
            ("price_cache",  "_write_rows"),
        )

        with ExitStack() as stack:
            for module_name, attr in candidate_seams:
                try:
                    mod = __import__(module_name)
                except Exception:
                    continue
                if not hasattr(mod, attr):
                    continue
                stack.enter_context(patch.object(
                    mod, attr,
                    side_effect=AssertionError(
                        f"stat_validation_readiness_report must not "
                        f"call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "stat_validation_readiness_report must not "
                        "call yfinance",
                    ),
                ))
            except ImportError:
                pass
            result = report.summarize_readiness(db_path=self._tmp)

        self.assertEqual(result["total_events"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(report, "app"))
        self.assertFalse(hasattr(report, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # so any actual import statement targeting ``api`` /
        # ``routes`` / ``routes.*`` is recorded — even when an earlier
        # suite already cached the target in ``sys.modules``.
        import builtins

        def _is_forbidden(name: str) -> bool:
            return (
                name == "api" or name.startswith("api.")
                or name == "routes" or name.startswith("routes.")
            )

        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def tracing_import(
            name, globals=None, locals=None, fromlist=(), level=0,
        ):
            if _is_forbidden(name):
                forbidden_imports.append(name)
            if name == "routes":
                for sub in fromlist or ():
                    forbidden_imports.append(f"routes.{sub}")
            return real_import(name, globals, locals, fromlist, level)

        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()

        before_modules = set(sys.modules.keys())
        with patch("builtins.__import__", side_effect=tracing_import):
            report.summarize_readiness(db_path=self._tmp)
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )

        self.assertEqual(
            forbidden_imports, [],
            f"forbidden imports: {forbidden_imports}",
        )
        self.assertEqual(
            newly_loaded_forbidden, [],
            f"forbidden modules loaded: {newly_loaded_forbidden}",
        )


# ---------------------------------------------------------------------------
# Compute-readiness — the strict event-study gate, reused from the proof path
# ---------------------------------------------------------------------------


def _contiguous_window(event_date: date, n_pre: int, n_post: int) -> list[date]:
    """Contiguous business days: ``n_pre`` before, the event, ``n_post`` after."""
    pre: list[date] = []
    cur = event_date
    while len(pre) < n_pre:
        cur -= timedelta(days=1)
        if cur.weekday() < 5:
            pre.append(cur)
    pre.reverse()
    post: list[date] = []
    cur = event_date
    while len(post) < n_post:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            post.append(cur)
    return pre + [event_date] + post


def _seed_series(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    dates: list[date],
    base: float,
    noise: bool,
    auto_adjust: int,
    jump_from: int | None = None,
) -> None:
    """Seed a price series.  ``noise`` adds an alternating idiosyncratic
    term (so the ticker's daily abnormal returns have positive variance →
    positive sigma); the optional post-event jump creates a clear AR."""
    for i, d in enumerate(dates):
        val = base * (1 + 0.0005 * i + (0.003 * ((-1) ** i) if noise else 0.0))
        if jump_from is not None and i >= jump_from:
            val *= 1.04
        _seed_cache_row(conn, ticker=ticker, date_str=d.isoformat(),
                        auto_adjust=auto_adjust, close=round(val, 4))


_EVENTS_DDL_WITH_STAGE = """
CREATE TABLE events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    headline        TEXT,
    event_date      TEXT,
    market_tickers  TEXT,
    stage           TEXT
)
""".strip()


class TestCuratedIntakeExclusion(unittest.TestCase):
    """A stage-carrying fixture: curated_intake rows are excluded from the
    readiness denominator and reported on a separate count, never hidden."""

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_svrr_ci_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL_WITH_STAGE)
            conn.execute(_PRICE_CACHE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(self, *, stage: str, market_tickers: str = "[]",
              event_date: str = "2026-04-15") -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (headline, event_date, market_tickers, "
                "stage) VALUES (?, ?, ?, ?)",
                ("headline", event_date, market_tickers, stage),
            )
            conn.commit()

    def test_curated_intake_excluded_from_denominator_and_counted(self) -> None:
        self._seed(stage="realized",
                   market_tickers=json.dumps([{"symbol": "AAPL"}]))
        self._seed(stage="curated_intake")
        self._seed(stage="curated_intake")
        result = report.summarize_readiness(db_path=self._tmp)
        # only the analysis-eligible row counts toward the denominator
        self.assertEqual(result["total_events"], 1)
        self.assertEqual(result["curated_intake_excluded_count"], 2)
        # the excluded rows never appear in the per-event listing either
        self.assertEqual(len(result["events"]), 1)
        self.assertEqual(result["events"][0]["primary_ticker"], "AAPL")

    def test_excluded_count_zero_when_no_intake_rows(self) -> None:
        self._seed(stage="realized",
                   market_tickers=json.dumps([{"symbol": "AAPL"}]))
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(result["curated_intake_excluded_count"], 0)
        self.assertEqual(result["total_events"], 1)


class TestComputeReadiness(_Base):
    _ED = date(2026, 4, 15)

    def _seed_compute_ready(self, *, ticker_flag: int, spy_flag: int) -> None:
        dates = _contiguous_window(self._ED, 65, 22)
        event_index = 65
        with self._conn() as conn:
            _seed_event(conn, event_date=self._ED.isoformat(),
                        market_tickers=json.dumps([{"symbol": "XLE"}]))
            _seed_series(conn, ticker="XLE", dates=dates, base=50.0, noise=True,
                         auto_adjust=ticker_flag, jump_from=event_index + 1)
            _seed_series(conn, ticker=_BENCHMARK_TICKER, dates=dates, base=100.0,
                         noise=False, auto_adjust=spy_flag)
            conn.commit()

    def test_compute_readiness_section_keys_present(self) -> None:
        cr = report.summarize_readiness(db_path=self._tmp)["compute_readiness"]
        for k in ("archive_ready_count", "event_study_compute_ready_count",
                  "status_counts", "top_blocking_reasons",
                  "auto_adjust_basis_counts", "cross_flag_caveat_count"):
            self.assertIn(k, cr)
        self.assertIn("event_study_available", cr["status_counts"])
        self.assertIn("insufficient_data", cr["status_counts"])

    def test_archive_ready_can_exceed_compute_ready(self) -> None:
        # Full archive coverage (60 pre + isolated +1/+5/+20bd forward
        # points + one SPY point) flips every ARCHIVE check — but the
        # archive gate never checks SPY's pre-event window, so the strict
        # gate refuses: archive-ready 1, compute-ready 0.
        with self._conn() as conn:
            _seed_event(conn, event_date=self._ED.isoformat(),
                        market_tickers=json.dumps([{"symbol": "AAPL"}]))
            _seed_full_cache_for_event(conn, ticker="AAPL", event_date=self._ED)
            conn.commit()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(result["events_fully_ready"], 1)            # archive
        cr = result["compute_readiness"]
        self.assertEqual(cr["archive_ready_count"], 1)
        self.assertEqual(cr["event_study_compute_ready_count"], 0)   # compute
        self.assertTrue(cr["top_blocking_reasons"])
        self.assertIn("insufficient_estimation_window_benchmark",
                      cr["top_blocking_reasons"])

    def test_matched_flag_event_is_compute_ready_without_caveat(self) -> None:
        self._seed_compute_ready(ticker_flag=0, spy_flag=0)
        cr = report.summarize_readiness(db_path=self._tmp)["compute_readiness"]
        self.assertEqual(cr["event_study_compute_ready_count"], 1)
        self.assertEqual(cr["auto_adjust_basis_counts"]["matched"], 1)
        self.assertEqual(cr["auto_adjust_basis_counts"]["cross_flag"], 0)
        self.assertEqual(cr["cross_flag_caveat_count"], 0)

    def test_cross_flag_caveat_counted_separately(self) -> None:
        # Asset adjusted-only, benchmark raw-only → computes on the cross
        # pair, counted as cross_flag and carrying the dividend caveat.
        self._seed_compute_ready(ticker_flag=1, spy_flag=0)
        cr = report.summarize_readiness(db_path=self._tmp)["compute_readiness"]
        self.assertEqual(cr["event_study_compute_ready_count"], 1)
        self.assertEqual(cr["auto_adjust_basis_counts"]["cross_flag"], 1)
        self.assertEqual(cr["auto_adjust_basis_counts"]["matched"], 0)
        self.assertEqual(cr["cross_flag_caveat_count"], 1)

    def test_compute_ready_path_invokes_no_provider_seam(self) -> None:
        from contextlib import ExitStack
        # A compute-READY event so compute_event_study actually runs;
        # assert the strict gate still reaches no provider / writer.
        self._seed_compute_ready(ticker_flag=0, spy_flag=0)
        seams = (
            ("market_data", "get_provider"),
            ("price_cache", "fetch_daily_cached"),
            ("price_cache", "_write_rows"),
        )
        with ExitStack() as stack:
            for mod_name, attr in seams:
                try:
                    mod = __import__(mod_name)
                except Exception:
                    continue
                if hasattr(mod, attr):
                    stack.enter_context(patch.object(
                        mod, attr,
                        side_effect=AssertionError(f"{mod_name}.{attr} called"),
                    ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError("yfinance called"),
                ))
            except ImportError:
                pass
            cr = report.summarize_readiness(db_path=self._tmp)["compute_readiness"]
        self.assertEqual(cr["event_study_compute_ready_count"], 1)


# ---------------------------------------------------------------------------
# Denominator lens (AT1) — accepted (hygiene-aware) vs raw (diagnostic)
# ---------------------------------------------------------------------------
#
# The ``accepted`` lens mirrors the canonical accepted-corpus analysis /
# coverage denominator (``db.NON_ANALYSIS_STAGES`` stage exclusion plus the
# AP3a/AP3b ``event_hygiene`` synthetic_seed exclusion), matching
# ``scripts/event_study_coverage_report.py``.  The ``raw`` lens is an
# all-stage diagnostic scan that includes every archive row and must be
# loudly labeled so it never masquerades as the accepted corpus.

_EVENT_HYGIENE_DDL = """
CREATE TABLE event_hygiene (
    event_id        INTEGER PRIMARY KEY,
    override_class  TEXT,
    override_reason TEXT,
    created_at      TEXT
)
""".strip()

_DENOMINATOR_KEYS = (
    "lens",
    "description",
    "included_stages",
    "excluded_stages",
    "excluded_override_classes",
    "counts",
)

_DENOMINATOR_COUNT_KEYS = (
    "archive_rows",
    "denominator_events",
    "synthetic_seed_flagged",
    "synthetic_seed_excluded",
    "staged_candidates",
    "staged_candidates_excluded",
    "pending_review",
    "pending_review_excluded",
    "curated_intake",
    "curated_intake_excluded",
    "total_excluded",
)

_NON_CLAIM_KEYS = (
    "not_a_trade_recommendation",
    "not_a_prediction",
    "no_statistical_significance_claim",
    "descriptive_coverage_only",
    "raw_lens_is_diagnostic_only",
    "notes",
)

_STAGE_CANDIDATE = "z1a_candidate_pack"
_STAGE_PENDING = "analysis_pending_review"
_STAGE_INTAKE = "curated_intake"


class _LensBase(unittest.TestCase):
    """Fixture with the full lens surface: stage column + event_hygiene."""

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_svrr_lens_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL_WITH_STAGE)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self) -> None:
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(
        self,
        *,
        stage: str = "realized",
        event_id: int | None = None,
        event_date: str = "2026-04-15",
        market_tickers: str | None = None,
    ) -> int:
        tickers = (
            market_tickers
            if market_tickers is not None
            else json.dumps([{"symbol": "AAPL"}])
        )
        with sqlite3.connect(self._tmp) as conn:
            if event_id is None:
                cur = conn.execute(
                    "INSERT INTO events (headline, event_date, market_tickers, "
                    "stage) VALUES (?, ?, ?, ?)",
                    ("headline", event_date, tickers, stage),
                )
                rid = int(cur.lastrowid)
            else:
                conn.execute(
                    "INSERT INTO events (id, headline, event_date, "
                    "market_tickers, stage) VALUES (?, ?, ?, ?, ?)",
                    (event_id, "headline", event_date, tickers, stage),
                )
                rid = event_id
            conn.commit()
            return rid

    def _flag(self, event_id: int, override_class: str = "synthetic_seed") -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, "
                "override_reason, created_at) VALUES (?, ?, ?, ?)",
                (event_id, override_class, "AP2 synthetic seed",
                 "2026-06-09T00:00:00"),
            )
            conn.commit()

    def _listed_ids(self, result: dict) -> list[int]:
        return [e["event_id"] for e in result["events"]]


class TestAcceptedLens(_LensBase):
    def test_default_lens_is_accepted(self) -> None:
        self._seed()
        result = report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(result["denominator"]["lens"], "accepted")

    def test_accepted_excludes_synthetic_seed_rows(self) -> None:
        real = self._seed()
        synth_a = self._seed()
        synth_b = self._seed()
        self._flag(synth_a)
        self._flag(synth_b)
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        self.assertEqual(result["total_events"], 1)
        listed = self._listed_ids(result)
        self.assertIn(real, listed)
        self.assertNotIn(synth_a, listed)
        self.assertNotIn(synth_b, listed)
        counts = result["denominator"]["counts"]
        self.assertEqual(counts["synthetic_seed_flagged"], 2)
        self.assertEqual(counts["synthetic_seed_excluded"], 2)

    def test_accepted_excludes_staged_candidate_and_pending_review(self) -> None:
        # Mirrors the live quarantine boundary: row 302 stays a staged
        # candidate, row 315 stays analysis_pending_review — neither may
        # leak into the accepted/hygiene-aware denominator or listing.
        real = self._seed(event_id=1)
        self._seed(event_id=302, stage=_STAGE_CANDIDATE)
        self._seed(event_id=315, stage=_STAGE_PENDING)
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        self.assertEqual(result["total_events"], 1)
        listed = self._listed_ids(result)
        self.assertIn(real, listed)
        self.assertNotIn(302, listed)
        self.assertNotIn(315, listed)
        counts = result["denominator"]["counts"]
        self.assertEqual(counts["staged_candidates"], 1)
        self.assertEqual(counts["staged_candidates_excluded"], 1)
        self.assertEqual(counts["pending_review"], 1)
        self.assertEqual(counts["pending_review_excluded"], 1)

    def test_accepted_excludes_curated_intake_with_compat_count(self) -> None:
        self._seed()
        self._seed(stage=_STAGE_INTAKE, market_tickers="[]")
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        self.assertEqual(result["total_events"], 1)
        # Back-compat top-level key keeps its literal curated_intake meaning.
        self.assertEqual(result["curated_intake_excluded_count"], 1)
        counts = result["denominator"]["counts"]
        self.assertEqual(counts["curated_intake"], 1)
        self.assertEqual(counts["curated_intake_excluded"], 1)

    def test_other_override_classes_do_not_exclude(self) -> None:
        row = self._seed()
        self._flag(row, override_class="real_duplicate")
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        self.assertEqual(result["total_events"], 1)
        self.assertIn(row, self._listed_ids(result))
        self.assertEqual(
            result["denominator"]["counts"]["synthetic_seed_flagged"], 0,
        )

    def test_accepted_compute_readiness_covers_only_accepted_rows(self) -> None:
        self._seed()
        synth = self._seed()
        self._flag(synth)
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        status = result["compute_readiness"]["status_counts"]
        self.assertEqual(sum(status.values()), 1)

    def test_seventy_one_synthetic_rows_excluded_at_scale(self) -> None:
        # The live AP3b condition: 71 flagged seed rows must drop out of
        # the accepted denominator while staying in the raw scan.
        for _ in range(9):
            self._seed()
        for _ in range(71):
            self._flag(self._seed())
        accepted = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        raw = report.summarize_readiness(db_path=self._tmp, lens="raw")
        self.assertEqual(accepted["total_events"], 9)
        self.assertEqual(
            accepted["denominator"]["counts"]["synthetic_seed_excluded"], 71,
        )
        self.assertEqual(raw["total_events"], 80)

    def test_excluded_stage_names_never_listed_as_included(self) -> None:
        self._seed()
        self._seed(stage=_STAGE_CANDIDATE)
        self._seed(stage=_STAGE_PENDING)
        self._seed(stage=_STAGE_INTAKE, market_tickers="[]")
        result = report.summarize_readiness(db_path=self._tmp, lens="accepted")
        included = result["denominator"]["included_stages"]
        for stage in (_STAGE_CANDIDATE, _STAGE_PENDING, _STAGE_INTAKE):
            self.assertNotIn(stage, included)
        self.assertIn("realized", included)


class TestRawLens(_LensBase):
    def _seed_mixed(self) -> None:
        self._seed(event_id=1)
        self._seed(event_id=302, stage=_STAGE_CANDIDATE)
        self._seed(event_id=315, stage=_STAGE_PENDING)
        self._seed(event_id=400, stage=_STAGE_INTAKE, market_tickers="[]")
        synth = self._seed(event_id=401)
        self._flag(synth)

    def test_raw_includes_every_archive_row(self) -> None:
        self._seed_mixed()
        result = report.summarize_readiness(db_path=self._tmp, lens="raw")
        self.assertEqual(result["total_events"], 5)
        denom = result["denominator"]
        self.assertEqual(denom["lens"], "raw")
        self.assertEqual(denom["excluded_stages"], [])
        self.assertEqual(denom["excluded_override_classes"], [])
        self.assertEqual(denom["counts"]["total_excluded"], 0)
        self.assertEqual(result["curated_intake_excluded_count"], 0)

    def test_raw_still_discloses_hygiene_populations(self) -> None:
        self._seed_mixed()
        counts = report.summarize_readiness(
            db_path=self._tmp, lens="raw",
        )["denominator"]["counts"]
        self.assertEqual(counts["synthetic_seed_flagged"], 1)
        self.assertEqual(counts["staged_candidates"], 1)
        self.assertEqual(counts["pending_review"], 1)
        self.assertEqual(counts["curated_intake"], 1)
        self.assertEqual(counts["synthetic_seed_excluded"], 0)
        self.assertEqual(counts["staged_candidates_excluded"], 0)
        self.assertEqual(counts["pending_review_excluded"], 0)

    def test_raw_lists_quarantined_rows_with_stage_label(self) -> None:
        self._seed_mixed()
        result = report.summarize_readiness(db_path=self._tmp, lens="raw")
        listed = {e["event_id"]: e for e in result["events"]}
        self.assertIn(302, listed)
        self.assertIn(315, listed)
        self.assertEqual(listed[302]["stage"], _STAGE_CANDIDATE)
        self.assertEqual(listed[315]["stage"], _STAGE_PENDING)


class TestLensMetadataAndNonClaims(_LensBase):
    def test_denominator_metadata_contract(self) -> None:
        self._seed()
        for lens in ("accepted", "raw"):
            result = report.summarize_readiness(db_path=self._tmp, lens=lens)
            denom = result["denominator"]
            for key in _DENOMINATOR_KEYS:
                self.assertIn(key, denom, f"[{lens}] missing key: {key}")
            for key in _DENOMINATOR_COUNT_KEYS:
                self.assertIn(
                    key, denom["counts"], f"[{lens}] missing count: {key}",
                )
            self.assertEqual(
                denom["counts"]["denominator_events"], result["total_events"],
            )

    def test_non_claims_block_present(self) -> None:
        self._seed()
        for lens in ("accepted", "raw"):
            result = report.summarize_readiness(db_path=self._tmp, lens=lens)
            self.assertIn("non_claims", result)
            for key in _NON_CLAIM_KEYS:
                self.assertIn(
                    key, result["non_claims"], f"[{lens}] missing: {key}",
                )

    def test_missing_db_keeps_lens_metadata(self) -> None:
        missing = os.path.join(
            tempfile.gettempdir(), f"nocreate_svrr_lens_{uuid.uuid4().hex}.db",
        )
        self.addCleanup(lambda: os.path.exists(missing) and os.remove(missing))
        result = report.summarize_readiness(db_path=missing, lens="raw")
        self.assertEqual(result["denominator"]["lens"], "raw")
        self.assertIn("non_claims", result)

    def test_unknown_lens_raises_value_error(self) -> None:
        self._seed()
        with self.assertRaises(ValueError):
            report.summarize_readiness(db_path=self._tmp, lens="everything")


class TestLensCli(_LensBase):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = report.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def _seed_mixed(self) -> None:
        self._seed(event_id=1)
        self._seed(event_id=302, stage=_STAGE_CANDIDATE)
        synth = self._seed(event_id=401)
        self._flag(synth)

    def test_cli_lens_flag_switches_denominator(self) -> None:
        self._seed_mixed()
        rc_a, out_a = self._run_cli(
            ["--db-path", self._tmp, "--json", "--lens", "accepted"],
        )
        rc_r, out_r = self._run_cli(
            ["--db-path", self._tmp, "--json", "--lens", "raw"],
        )
        self.assertEqual(rc_a, 0)
        self.assertEqual(rc_r, 0)
        body_a = json.loads(out_a)
        body_r = json.loads(out_r)
        self.assertEqual(body_a["total_events"], 1)
        self.assertEqual(body_r["total_events"], 3)
        self.assertEqual(body_a["denominator"]["lens"], "accepted")
        self.assertEqual(body_r["denominator"]["lens"], "raw")

    def test_cli_default_lens_is_accepted(self) -> None:
        self._seed_mixed()
        rc, output = self._run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["denominator"]["lens"], "accepted")
        self.assertEqual(body["total_events"], 1)

    def test_cli_rejects_unknown_lens(self) -> None:
        rc, _ = self._run_cli(
            ["--db-path", self._tmp, "--json", "--lens", "everything"],
        )
        self.assertEqual(rc, 2)

    def test_text_output_names_active_lens(self) -> None:
        self._seed_mixed()
        rc_a, out_a = self._run_cli(["--db-path", self._tmp, "--lens", "accepted"])
        rc_r, out_r = self._run_cli(["--db-path", self._tmp, "--lens", "raw"])
        self.assertEqual(rc_a, 0)
        self.assertEqual(rc_r, 0)
        self.assertIn("accepted", out_a)
        self.assertIn("hygiene-aware", out_a)
        self.assertIn("raw", out_r)
        self.assertIn("diagnostic", out_r)


if __name__ == "__main__":
    unittest.main()
