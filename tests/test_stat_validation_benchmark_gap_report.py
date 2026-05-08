"""Tests for ``scripts/stat_validation_benchmark_gap_report.py``.

Pin the read-only contract:

* Every gap row is computed from a hand-rolled temp DB containing
  exactly the events + price_cache rows the test needs; no
  production schema migrations are exercised.
* A row is included in ``rows`` iff the event is a
  ``missing_benchmark_proxy`` blocker — defined exactly as in
  :mod:`scripts.stat_validation_readiness_report`: no SPY cache row
  with ``date >= event_date + 20bd``.  Boundary case (max == target)
  is treated as covered and excluded.
* The three degraded paths are surfaced honestly:
    - no ``event_date``  →  ``benchmark_target_20d_date=None``,
                           ``gap_days=None``
    - no SPY rows         →  ``benchmark_cache_max_date=None``,
                           ``gap_days=None``
    - SPY max < target    →  ``gap_days = (target - max).days``
                           (calendar days)
* ``benchmark_cache_max_date`` is a single global value (max SPY
  date) and identical across every emitted row.
* Aggregate ``events_missing_benchmark_proxy`` walks every blocked
  event in the archive; ``--limit`` truncates ``rows`` only.
* Per-event entries are sorted by ``id`` ascending.
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

from scripts import stat_validation_benchmark_gap_report as gap  # noqa: E402
from scripts import stat_validation_readiness_report as readiness  # noqa: E402


# ---------------------------------------------------------------------------
# Temp DB fixture — same minimal DDL as the readiness/blocker tests.
# Hand-rolled (no ``db.init_db``) so the fixture is decoupled from the
# production schema migrations and pins the SQL contract directly.
# ---------------------------------------------------------------------------


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
    "events_missing_benchmark_proxy",
    "benchmark_symbol",
    "rows",
    "recommended_next_action",
)


_ROW_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "benchmark_symbol",
    "benchmark_target_20d_date",
    "benchmark_cache_max_date",
    "gap_days",
)


_BENCHMARK_TICKER = readiness._BENCHMARK_TICKER  # "SPY"
_FETCHED_AT = "2026-05-06T12:00:00+00:00"


def _bd(start: date, n: int) -> date:
    """Local business-day shift — must match the readiness module's
    ``_business_day_offset`` so test fixtures pin the same windows
    the production probe checks against.
    """
    if n <= 0:
        return start
    out = start
    remaining = n
    while remaining > 0:
        out = out + timedelta(days=1)
        if out.weekday() < 5:
            remaining -= 1
    return out


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


def _seed_cache(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    date_str: str,
    auto_adjust: int = 1,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO price_cache "
        "(ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date_str, 100.0, 5_000_000.0, auto_adjust, _FETCHED_AT),
    )


def _snapshot_tables(db_path: str) -> tuple[list, list]:
    conn = sqlite3.connect(db_path)
    try:
        events = list(conn.execute(
            "SELECT id, headline, event_date, market_tickers "
            "FROM events ORDER BY id"
        ))
        cache = list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))
        return events, cache
    finally:
        conn.close()


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        rc = gap.main(argv, out=out)
    except SystemExit as exc:
        rc = exc.code
    return rc, out.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svbg_{uuid.uuid4().hex}.db",
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
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_benchmark_symbol_matches_readiness_module(self) -> None:
        # Single source of truth — the gap report must surface the
        # same benchmark constant the readiness module hardcodes.
        # Otherwise blocker counts and gap rows could disagree about
        # which symbol is the proxy.
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["benchmark_symbol"], _BENCHMARK_TICKER)

    def test_per_row_carries_every_required_field(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        for key in _ROW_KEYS:
            self.assertIn(key, row, f"row missing field: {key}")

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# Empty / fully-covered archives
# ---------------------------------------------------------------------------


class TestEmptyAndCovered(_Base):
    def test_empty_archive_zeros_every_aggregate(self) -> None:
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["total_events"],                   0)
        self.assertEqual(result["events_missing_benchmark_proxy"], 0)
        self.assertEqual(result["rows"],                          [])
        self.assertIn("empty",
                      result["recommended_next_action"].lower())

    def test_fully_covered_event_does_not_appear_in_rows(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # SPY at exactly target_20d — readiness check is ``>=``,
            # so this row satisfies the benchmark proxy.
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str=_bd(ed, 20).isoformat())
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["total_events"],                   1)
        self.assertEqual(result["events_missing_benchmark_proxy"], 0)
        self.assertEqual(result["rows"], [])
        self.assertIn("no benchmark-cache gap",
                      result["recommended_next_action"].lower())


# ---------------------------------------------------------------------------
# Filter — boundary on >= target
# ---------------------------------------------------------------------------


class TestBlockerFilter(_Base):
    def test_spy_at_exactly_target_excluded(self) -> None:
        # ``date == target_20d`` satisfies the readiness check (``>=``)
        # — these events are NOT blockers.
        ed = date(2026, 4, 15)
        target = _bd(ed, 20)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str=target.isoformat())
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 0)
        self.assertEqual(result["rows"], [])

    def test_spy_one_business_day_short_included(self) -> None:
        # Boundary on the other side — SPY's latest is one business day
        # before target.  The event IS a blocker.  The gap_days field
        # is calendar days, not business days, so a 1bd shortfall in a
        # weekday-to-weekday transition is exactly 1 day.
        ed = date(2026, 4, 15)
        target = _bd(ed, 20)
        # ``_bd(ed, 19)`` is one business day before target — the
        # weekday gap may translate to ≥ 1 calendar day depending on
        # whether target falls on a Monday (then 3 calendar days back).
        # The point of the assertion is the blocker-filter side: the
        # event must appear; the precise gap value is pinned in a
        # separate test on a known calendar day.
        max_d = _bd(ed, 19)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str=max_d.isoformat())
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        self.assertEqual(len(result["rows"]),                      1)
        row = result["rows"][0]
        self.assertEqual(row["benchmark_target_20d_date"], target.isoformat())
        self.assertEqual(row["benchmark_cache_max_date"],   max_d.isoformat())
        # gap_days is positive (target - max).days
        self.assertIsNotNone(row["gap_days"])
        self.assertGreaterEqual(row["gap_days"], 1)
        self.assertEqual(row["gap_days"], (target - max_d).days)


# ---------------------------------------------------------------------------
# gap_days math — pin the exact calendar-day arithmetic
# ---------------------------------------------------------------------------


class TestGapDaysMath(_Base):
    def test_known_target_and_max_yield_exact_calendar_diff(self) -> None:
        # event_date 2026-04-15 (Wed) → target_20d = 2026-05-13 (Wed)
        # SPY max 2026-05-08 (Fri) → gap_days = 5 calendar days.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str="2026-05-08")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(len(result["rows"]), 1)
        row = result["rows"][0]
        self.assertEqual(row["benchmark_target_20d_date"], "2026-05-13")
        self.assertEqual(row["benchmark_cache_max_date"],   "2026-05-08")
        self.assertEqual(row["gap_days"], 5)

    def test_max_takes_global_latest_spy_date_not_per_event(self) -> None:
        # Even if a per-event view would suggest "the latest SPY date
        # in the estimation window", the report uses a single global
        # max.  Seed multiple SPY rows; the row's ``benchmark_cache_max_date``
        # must be the lexicographic max.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str="2026-04-30")
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str="2026-05-08")
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str="2026-05-01")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        row = result["rows"][0]
        self.assertEqual(row["benchmark_cache_max_date"], "2026-05-08")
        self.assertEqual(row["gap_days"], 5)

    def test_global_max_is_identical_across_every_emitted_row(self) -> None:
        # Two events with different event_dates — both rows should
        # carry the same ``benchmark_cache_max_date`` (it's a global
        # max, not per-event).
        ed1 = date(2026, 4, 15)
        ed2 = date(2026, 4, 30)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed1.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_event(
                conn, event_date=ed2.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str="2026-05-08")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(len(result["rows"]), 2)
        cache_maxes = {r["benchmark_cache_max_date"] for r in result["rows"]}
        self.assertEqual(cache_maxes, {"2026-05-08"})


# ---------------------------------------------------------------------------
# Degraded inputs — None-fields surface honestly
# ---------------------------------------------------------------------------


class TestDegradedInputs(_Base):
    def test_event_with_no_event_date_emits_row_with_target_none(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER, date_str="2026-05-08")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        row = result["rows"][0]
        self.assertIsNone(row["event_date"])
        self.assertIsNone(row["benchmark_target_20d_date"])
        self.assertEqual(row["benchmark_cache_max_date"], "2026-05-08")
        self.assertIsNone(row["gap_days"])

    def test_event_with_malformed_event_date_emits_row_with_target_none(self) -> None:
        # Non-ISO strings degrade like None — the readiness check
        # tolerates them via ``_parse_iso_date``; the gap report must
        # match.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="not-a-date",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER, date_str="2026-05-08")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        row = result["rows"][0]
        # The event_date passes through verbatim (we don't sanitize),
        # but the target is unset.
        self.assertEqual(row["event_date"], "not-a-date")
        self.assertIsNone(row["benchmark_target_20d_date"])
        self.assertIsNone(row["gap_days"])

    def test_no_spy_rows_at_all_emits_row_with_max_none(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # Seed AAPL but NOT SPY — the benchmark cache is empty.
            _seed_cache(conn, ticker="AAPL", date_str=ed.isoformat())
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        row = result["rows"][0]
        self.assertIsNone(row["benchmark_cache_max_date"])
        self.assertIsNone(row["gap_days"])
        # The target IS knowable — only the max is missing.
        self.assertEqual(
            row["benchmark_target_20d_date"], _bd(ed, 20).isoformat(),
        )

    def test_event_with_no_primary_ticker_still_appears(self) -> None:
        # Missing primary_ticker has no bearing on the benchmark check
        # (the benchmark is SPY, not the primary).  The row should
        # still appear if SPY is short.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers="[]",
            )
            _seed_cache(conn, ticker=_BENCHMARK_TICKER, date_str="2026-05-08")
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        row = result["rows"][0]
        self.assertIsNone(row["primary_ticker"])
        self.assertEqual(row["benchmark_target_20d_date"], _bd(ed, 20).isoformat())
        self.assertEqual(row["benchmark_cache_max_date"],   "2026-05-08")

    def test_event_with_unparseable_market_tickers_does_not_crash(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers="{ malformed json :: ::",
            )
            conn.commit()
        # Should not raise — the row appears as a blocker (no SPY rows)
        # with primary_ticker=None.
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["events_missing_benchmark_proxy"], 1)
        self.assertIsNone(result["rows"][0]["primary_ticker"])


# ---------------------------------------------------------------------------
# Aggregation and ordering
# ---------------------------------------------------------------------------


class TestAggregationAndOrder(_Base):
    def test_aggregate_count_walks_full_archive(self) -> None:
        # Five blocked events, one fully covered.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            for _ in range(5):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            # And one event whose 20d target is already in cache.
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            # Seed SPY only short of the target (so first 5 are blocked,
            # AND the last event also fails — wait, no: every event
            # shares the same event_date, so they share target_20d.
            # Use a different event_date for the covered event.
            conn.commit()

        # Reset for clarity — covered event uses a much earlier
        # event_date so target_20d ≤ what we seed for SPY.
        with self._conn() as conn:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM price_cache")
            for _ in range(5):
                _seed_event(
                    conn, event_date="2026-06-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            covered_ed = date(2026, 1, 15)
            _seed_event(
                conn, event_date=covered_ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            # SPY max satisfies the early event but is short of June.
            _seed_cache(conn, ticker=_BENCHMARK_TICKER,
                        date_str=_bd(covered_ed, 20).isoformat())
            conn.commit()

        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        self.assertEqual(result["total_events"],                   6)
        self.assertEqual(result["events_missing_benchmark_proxy"], 5)
        self.assertEqual(len(result["rows"]),                      5)

    def test_rows_sorted_by_event_id_ascending(self) -> None:
        with self._conn() as conn:
            for _ in range(4):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp)
        ids = [r["event_id"] for r in result["rows"]]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# --limit handling
# ---------------------------------------------------------------------------


class TestLimit(_Base):
    def test_limit_truncates_rows_only(self) -> None:
        with self._conn() as conn:
            for _ in range(10):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp, limit=3)
        self.assertEqual(result["total_events"],                   10)
        self.assertEqual(result["events_missing_benchmark_proxy"], 10)
        self.assertEqual(len(result["rows"]),                      3)

    def test_negative_limit_clamps_to_zero(self) -> None:
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp, limit=-5)
        self.assertEqual(result["events_missing_benchmark_proxy"], 3)
        self.assertEqual(result["rows"], [])

    def test_zero_limit_clamps_to_zero_with_aggregate_intact(self) -> None:
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        result = gap.summarize_benchmark_gaps(db_path=self._tmp, limit=0)
        self.assertEqual(result["events_missing_benchmark_proxy"], 3)
        self.assertEqual(result["rows"], [])


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(_Base):
    def test_repeated_runs_leave_tables_byte_identical(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker="AAPL", date_str="2026-04-16")
            _seed_cache(conn, ticker=_BENCHMARK_TICKER, date_str="2026-05-08")
            conn.commit()

        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            gap.summarize_benchmark_gaps(db_path=self._tmp)
        after = _snapshot_tables(self._tmp)
        self.assertEqual(
            before, after,
            "events + price_cache must be byte-identical across "
            "repeated runs",
        )

    def test_missing_db_path_returns_empty_report_without_raising(self) -> None:
        # Point at a path that doesn't exist — the report should
        # degrade to the empty payload, not raise.
        ghost = os.path.join(
            tempfile.gettempdir(),
            f"test_svbg_ghost_{uuid.uuid4().hex}.db",
        )
        # File doesn't exist; sqlite3.connect would create an empty
        # one if we let it.  The report should still tolerate the
        # missing-tables case via its inner try/except.
        result = gap.summarize_benchmark_gaps(db_path=ghost)
        self.assertEqual(result["total_events"],                   0)
        self.assertEqual(result["events_missing_benchmark_proxy"], 0)
        self.assertEqual(result["rows"],                           [])
        try:
            os.remove(ghost)
        except (OSError, PermissionError):
            pass


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(_Base):
    def test_text_output_carries_section_headers(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        rc, output = _run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        self.assertIn("benchmark-cache gap report", output.lower())
        self.assertIn("Total events",               output)
        self.assertIn("missing benchmark proxy",    output)
        self.assertIn("Recommended next action",    output)

    def test_json_output_carries_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        rc, output = _run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(len(body["rows"]), 1)
        for key in _ROW_KEYS:
            self.assertIn(
                key, body["rows"][0],
                f"row missing field: {key}",
            )

    def test_cli_limit_truncates_rows_only(self) -> None:
        with self._conn() as conn:
            for _ in range(10):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        rc, output = _run_cli([
            "--db-path", self._tmp, "--json", "--limit", "2",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["events_missing_benchmark_proxy"], 10)
        self.assertEqual(len(body["rows"]),                       2)

    def test_cli_db_path_resolves_alt_database(self) -> None:
        # Build a second temp DB with a distinct event count and
        # confirm ``--db-path`` reads from THAT file (not the default
        # archive).
        alt = os.path.join(
            tempfile.gettempdir(),
            f"test_svbg_alt_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(alt)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            for _ in range(2):
                _seed_event(
                    conn, event_date="2026-04-15",
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            conn.commit()
        finally:
            conn.close()
        try:
            rc, output = _run_cli(["--db-path", alt, "--json"])
            self.assertEqual(rc, 0)
            body = json.loads(output)
            self.assertEqual(body["total_events"], 2)
        finally:
            try:
                os.remove(alt)
            except (OSError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

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

        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()

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
                        f"stat_validation_benchmark_gap_report must "
                        f"not call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "stat_validation_benchmark_gap_report must "
                        "not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            result = gap.summarize_benchmark_gaps(db_path=self._tmp)

        self.assertEqual(result["events_missing_benchmark_proxy"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(gap, "app"))
        self.assertFalse(hasattr(gap, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard: instrument ``builtins.__import__``
        # so any actual import statement targeting ``api`` / ``routes``
        # / ``routes.*`` is recorded — even when an earlier suite has
        # already cached the target in ``sys.modules``.
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

        before_modules = set(sys.modules.keys())
        with patch("builtins.__import__", side_effect=tracing_import):
            gap.summarize_benchmark_gaps(db_path=self._tmp)
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

    def test_db_open_only_issues_select_statements(self) -> None:
        # Subclass ``sqlite3.Connection`` and route every connection
        # opened by the script through it so we can capture each SQL
        # statement and assert it is a SELECT.  ``sqlite3.Connection``
        # is an immutable C-extension type, so we can't patch
        # ``execute`` directly — the factory hook on ``sqlite3.connect``
        # is the canonical seam for this.  Pins the read-only contract
        # at the SQL layer rather than via integration alone.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()

        statements: list[str] = []

        class _TracingConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                statements.append(sql)
                return super().execute(sql, *args, **kwargs)

        real_connect = sqlite3.connect

        def tracing_connect(database, *args, **kwargs):
            kwargs.setdefault("factory", _TracingConnection)
            return real_connect(database, *args, **kwargs)

        with patch.object(sqlite3, "connect", side_effect=tracing_connect):
            gap.summarize_benchmark_gaps(db_path=self._tmp)

        self.assertGreater(
            len(statements), 0, "expected at least one SQL statement",
        )
        for sql in statements:
            head = sql.lstrip().split(None, 1)[0].upper()
            self.assertEqual(
                head, "SELECT",
                f"non-SELECT statement issued: {sql!r}",
            )


# ---------------------------------------------------------------------------
# Alignment with readiness module
# ---------------------------------------------------------------------------


class TestReadinessAlignment(unittest.TestCase):
    def test_benchmark_constant_imported_from_readiness(self) -> None:
        # Same object identity: both modules' ``_BENCHMARK_TICKER``
        # must resolve to the same string.  If readiness ever changes
        # (e.g. SPY → VOO), the gap report follows automatically.
        self.assertEqual(
            gap._BENCHMARK_TICKER, readiness._BENCHMARK_TICKER,
        )

    def test_business_day_offset_helper_shared_with_readiness(self) -> None:
        # Same function object — guards against divergent calendars.
        self.assertIs(
            gap._business_day_offset, readiness._business_day_offset,
        )

    def test_blocker_count_matches_readiness_missing_benchmark_count(self) -> None:
        # End-to-end consistency: the gap report's
        # ``events_missing_benchmark_proxy`` MUST match the readiness
        # report's ``events_missing_benchmark_proxy`` on the same
        # archive.  Drift here means the two surfaces would tell
        # different stories about the same blocker.
        tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svbg_align_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            ed = date(2026, 4, 15)
            # Three blocked events + one with SPY at exactly target.
            for _ in range(3):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            covered_ed = date(2026, 1, 15)
            _seed_event(
                conn, event_date=covered_ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            _seed_cache(
                conn, ticker=_BENCHMARK_TICKER,
                date_str=_bd(covered_ed, 20).isoformat(),
            )
            conn.commit()
        finally:
            conn.close()
        try:
            rd = readiness.summarize_readiness(
                db_path=tmp, limit=1_000_000,
            )
            gp = gap.summarize_benchmark_gaps(
                db_path=tmp, limit=1_000_000,
            )
            self.assertEqual(
                rd["events_missing_benchmark_proxy"],
                gp["events_missing_benchmark_proxy"],
                "gap-report blocker count must match readiness's",
            )
            # And the gap report's row count must equal the count.
            self.assertEqual(
                len(gp["rows"]),
                gp["events_missing_benchmark_proxy"],
            )
        finally:
            try:
                os.remove(tmp)
            except (OSError, PermissionError):
                pass


if __name__ == "__main__":
    unittest.main()
