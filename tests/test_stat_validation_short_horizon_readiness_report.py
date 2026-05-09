"""Tests for ``scripts/stat_validation_short_horizon_readiness_report.py``.

Pin the read-only contract:

* Output carries exactly the 8 spec keys (``total_events``,
  ``events_ready_1d5d``, ``delta_vs_full_ready``, ``missing_tickers_count``,
  ``missing_benchmark_count``, ``insufficient_estimation_window_count``,
  ``examples``, ``recommended_next_action``).
* The short-horizon readiness predicate requires only 1d/5d forward
  cache and a SPY benchmark row at +5bd (not +20bd).
* ``delta_vs_full_ready`` counts the cohort expansion vs. the full
  20d-required readiness predicate from
  :mod:`scripts.stat_validation_readiness_report`.
* Aggregate counts always reflect the full archive — ``--limit``
  truncates only the surfaced ``examples`` list.
* Per-event entries are sorted by ``id`` ascending and carry the
  required keys.
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

from scripts import stat_validation_short_horizon_readiness_report as report  # noqa: E402
from scripts import stat_validation_readiness_report as full_report  # noqa: E402


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
    "events_ready_1d5d",
    "delta_vs_full_ready",
    "missing_tickers_count",
    "missing_benchmark_count",
    "insufficient_estimation_window_count",
    "examples",
    "recommended_next_action",
)

_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "checks",
    "ready_1d5d",
    "delta_eligible",
)

_CHECK_KEYS = (
    "has_event_date",
    "has_market_tickers",
    "forward_cache_1d",
    "forward_cache_5d",
    "benchmark_proxy_available_5d",
    "estimation_window_sufficient",
)


_BENCHMARK_TICKER = "SPY"
_ESTIMATION_WINDOW = 60
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
    seeded = 0
    cursor = event_date - timedelta(days=1)
    while seeded < n_business_days:
        if cursor.weekday() < 5:
            _seed_cache_row(conn,
                            ticker=ticker, date_str=cursor.isoformat())
            seeded += 1
        cursor = cursor - timedelta(days=1)


def _seed_short_horizon_full_cache(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_date: date,
    benchmark: str = _BENCHMARK_TICKER,
) -> None:
    """Seed every row needed to flip every short-horizon readiness check
    True for one ``(ticker, event_date)`` pair: the estimation window
    for the ticker, the 1d/5d forward dates for the ticker, and the
    5d forward date for the benchmark.

    Notably this seeds NO rows past +5bd — an event seeded this way is
    short-horizon-ready but NOT fully_ready under the 20d-required
    predicate.  This is the exact shape that drives ``delta_vs_full_ready``.
    """
    _seed_pre_event_cache(
        conn, ticker=ticker, event_date=event_date,
        n_business_days=_ESTIMATION_WINDOW,
    )
    for h in (1, 5):
        target = _business_day_offset(event_date, h)
        _seed_cache_row(conn, ticker=ticker, date_str=target.isoformat())
    benchmark_target = _business_day_offset(event_date, 5)
    _seed_cache_row(
        conn, ticker=benchmark, date_str=benchmark_target.isoformat(),
    )


def _seed_full_cache_for_event(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_date: date,
    benchmark: str = _BENCHMARK_TICKER,
) -> None:
    """Seed every row needed to flip BOTH the short-horizon and the
    full (20d) readiness predicates True for one event.
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
            f"test_svshrr_{uuid.uuid4().hex}.db",
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
    def test_returns_dict_with_exactly_eight_top_keys(self) -> None:
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        self.assertEqual(
            set(result.keys()), set(_TOP_KEYS),
            f"expected exactly {_TOP_KEYS}, got {sorted(result.keys())}",
        )

    def test_per_event_entry_has_every_required_key(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn,
                event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertEqual(len(result["examples"]), 1)
        entry = result["examples"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, entry, f"per-event missing field: {key}")
        for key in _CHECK_KEYS:
            self.assertIn(key, entry["checks"],
                          f"checks missing field: {key}")
        # The short-horizon report deliberately surfaces no
        # forward_cache_20d check — the whole point is to drop it.
        self.assertNotIn("forward_cache_20d", entry["checks"])

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# Empty / minimal archive
# ---------------------------------------------------------------------------


class TestEmptyArchive(_Base):
    def test_empty_archive_zeros_every_aggregate(self) -> None:
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        for key in _TOP_KEYS:
            if key in ("examples", "recommended_next_action"):
                continue
            self.assertEqual(result[key], 0,
                             f"{key} should be 0 on empty archive")
        self.assertEqual(result["examples"], [])


# ---------------------------------------------------------------------------
# Individual readiness checks
# ---------------------------------------------------------------------------


class TestEventDateAndTickers(_Base):
    def test_missing_event_date_blocks_every_cache_check(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        entry = result["examples"][0]
        self.assertFalse(entry["checks"]["has_event_date"])
        self.assertTrue(entry["checks"]["has_market_tickers"])
        self.assertFalse(entry["checks"]["forward_cache_1d"])
        self.assertFalse(entry["checks"]["forward_cache_5d"])
        self.assertFalse(entry["checks"]["benchmark_proxy_available_5d"])
        self.assertFalse(entry["checks"]["estimation_window_sufficient"])
        self.assertFalse(entry["ready_1d5d"])
        # Without a ticker block, the missing_tickers_count tally
        # should not double-count this event.
        self.assertEqual(result["missing_tickers_count"], 0)

    def test_missing_market_tickers_increments_missing_tickers_count(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, event_date="2026-04-15", market_tickers=None)
            _seed_event(conn, event_date="2026-04-15", market_tickers="")
            _seed_event(conn, event_date="2026-04-15", market_tickers="[]")
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers=json.dumps(
                            [{"symbol": ""}, {"symbol": "  "}],
                        ))
            _seed_event(conn, event_date="2026-04-15",
                        market_tickers="not-json")
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertEqual(result["total_events"],          5)
        self.assertEqual(result["missing_tickers_count"], 5)
        for entry in result["examples"]:
            self.assertFalse(entry["checks"]["has_market_tickers"])
            self.assertIsNone(entry["primary_ticker"])
            self.assertFalse(entry["ready_1d5d"])


class TestForwardCache(_Base):
    def test_short_horizon_satisfied_by_row_at_plus_five_bd(self) -> None:
        # event_date = 2026-04-15 (Wed).  +5bd = 2026-04-22.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-22")
            conn.commit()
        checks = report.summarize_short_horizon_readiness(
            db_path=self._tmp,
        )["examples"][0]["checks"]
        self.assertTrue(checks["forward_cache_1d"])
        self.assertTrue(checks["forward_cache_5d"])

    def test_only_one_bd_row_satisfies_one_d_only(self) -> None:
        # Row at exactly +1bd flips 1d only, not 5d.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-16")
            conn.commit()
        checks = report.summarize_short_horizon_readiness(
            db_path=self._tmp,
        )["examples"][0]["checks"]
        self.assertTrue(checks["forward_cache_1d"])
        self.assertFalse(checks["forward_cache_5d"])


class TestBenchmarkAtFiveBd(_Base):
    def test_spy_at_plus_five_bd_satisfies_short_horizon_benchmark(self) -> None:
        # +5bd from 2026-04-15 (Wed) = 2026-04-22.  Crucially this is
        # BEFORE +20bd (= 2026-05-13) — the short-horizon report
        # accepts what the full report rejects.
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache_row(
                conn, ticker=_BENCHMARK_TICKER, date_str="2026-04-22",
            )
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        checks = result["examples"][0]["checks"]
        self.assertTrue(checks["benchmark_proxy_available_5d"])
        self.assertEqual(result["missing_benchmark_count"], 0)

    def test_spy_only_pre_event_does_not_satisfy_benchmark(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # SPY row well before event_date — never satisfies +5bd target.
            _seed_cache_row(
                conn, ticker=_BENCHMARK_TICKER, date_str="2026-01-01",
            )
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertFalse(
            result["examples"][0]["checks"]["benchmark_proxy_available_5d"],
        )
        self.assertEqual(result["missing_benchmark_count"], 1)

    def test_short_horizon_benchmark_strictly_more_permissive_than_twenty_d(self) -> None:
        # An event with SPY only at +5bd should satisfy the
        # short-horizon predicate but FAIL the full predicate's 20d
        # benchmark check — pinning the cohort-expansion semantics.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()

        short = report.summarize_short_horizon_readiness(db_path=self._tmp)
        full = full_report.summarize_readiness(db_path=self._tmp)

        self.assertTrue(short["examples"][0]["ready_1d5d"])
        self.assertFalse(full["events"][0]["fully_ready"])
        self.assertEqual(short["events_ready_1d5d"], 1)
        self.assertEqual(full["events_fully_ready"], 0)
        self.assertEqual(short["delta_vs_full_ready"], 1)
        self.assertTrue(short["examples"][0]["delta_eligible"])


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
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        checks = result["examples"][0]["checks"]
        self.assertTrue(checks["estimation_window_sufficient"])
        self.assertEqual(result["insufficient_estimation_window_count"], 0)

    def test_just_below_threshold_increments_blocker_count(self) -> None:
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
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertFalse(
            result["examples"][0]["checks"]["estimation_window_sufficient"],
        )
        self.assertEqual(result["insufficient_estimation_window_count"], 1)


# ---------------------------------------------------------------------------
# ready_1d5d / delta_vs_full_ready semantics
# ---------------------------------------------------------------------------


class TestReadyAndDelta(_Base):
    def test_short_horizon_full_cache_marks_event_ready(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        entry = result["examples"][0]
        self.assertTrue(entry["ready_1d5d"])
        for k in _CHECK_KEYS:
            self.assertTrue(entry["checks"][k], f"check {k} is False")
        self.assertEqual(result["events_ready_1d5d"], 1)

    def test_event_fully_ready_under_twenty_d_is_not_delta_eligible(self) -> None:
        # An event that already passes the 20d-required predicate is
        # not a member of the cohort expansion — short-horizon ready,
        # but delta_eligible must be False.
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
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        entry = result["examples"][0]
        self.assertTrue(entry["ready_1d5d"])
        self.assertFalse(entry["delta_eligible"])
        self.assertEqual(result["delta_vs_full_ready"], 0)

    def test_delta_equals_short_minus_full(self) -> None:
        # Sanity: across an arbitrary mix, delta_vs_full_ready must
        # equal events_ready_1d5d - events_fully_ready (since
        # fully_ready ⇒ ready_1d5d once benchmark horizon is relaxed).
        ed_a = date(2026, 4, 15)
        ed_b = date(2026, 6, 15)
        ed_c = date(2026, 8, 17)
        with self._conn() as conn:
            # Fully ready (counts in both predicates).
            _seed_event(
                conn, event_date=ed_a.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_full_cache_for_event(
                conn, ticker="AAPL", event_date=ed_a,
            )
            # Short-horizon only (delta_eligible).
            _seed_event(
                conn, event_date=ed_b.isoformat(),
                market_tickers=json.dumps([{"symbol": "MSFT"}]),
            )
            _seed_short_horizon_full_cache(
                conn, ticker="MSFT", event_date=ed_b,
            )
            # Not ready under either predicate.
            _seed_event(
                conn, event_date=ed_c.isoformat(),
                market_tickers=json.dumps([{"symbol": "GOOG"}]),
            )
            conn.commit()

        short = report.summarize_short_horizon_readiness(db_path=self._tmp)
        full = full_report.summarize_readiness(db_path=self._tmp)
        self.assertEqual(
            short["delta_vs_full_ready"],
            short["events_ready_1d5d"] - full["events_fully_ready"],
        )
        self.assertEqual(short["delta_vs_full_ready"], 1)


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------


class TestAggregateCounts(_Base):
    def test_blocker_counts_are_independent_per_event(self) -> None:
        # Each blocker count is independent — a single event with
        # multiple failures contributes to every applicable blocker
        # tally.  This matches the original report's pattern.
        with self._conn() as conn:
            _seed_event(conn, event_date=None, market_tickers="[]")
            conn.commit()
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        self.assertEqual(result["total_events"],                       1)
        self.assertEqual(result["missing_tickers_count"],              1)
        # Both benchmark and estimation checks degrade to False without
        # event_date or ticker — they still count toward their tallies.
        self.assertEqual(result["missing_benchmark_count"],            1)
        self.assertEqual(result["insufficient_estimation_window_count"], 1)
        self.assertEqual(result["events_ready_1d5d"],                  0)
        self.assertEqual(result["delta_vs_full_ready"],                0)

    def test_recommendation_flips_when_delta_is_meaningful(self) -> None:
        # When the cohort-expansion delta is positive, the
        # recommendation should be different from the no-delta case.
        # No-delta baseline: empty archive.
        baseline = report.summarize_short_horizon_readiness(
            db_path=self._tmp,
        )["recommended_next_action"]

        # Add a delta-eligible event.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        delta_msg = report.summarize_short_horizon_readiness(
            db_path=self._tmp,
        )["recommended_next_action"]
        self.assertNotEqual(baseline, delta_msg)


# ---------------------------------------------------------------------------
# Conservative language
# ---------------------------------------------------------------------------


class TestConservativeLanguage(_Base):
    def test_recommendation_uses_candidate_language_not_proof(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        msg = report.summarize_short_horizon_readiness(
            db_path=self._tmp,
        )["recommended_next_action"]
        lower = msg.lower()
        # Expected vocabulary.
        self.assertIn("candidate", lower)
        # Forbidden vocabulary — the report measures cohort
        # expansion, never statistical evidence.
        for banned in ("proof", "proven", "validated", "alpha", "significant"):
            self.assertNotIn(banned, lower,
                             f"recommendation must not assert {banned!r}")


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

    def test_examples_listed_in_id_ascending_order(self) -> None:
        self._seed_n_events(5)
        result = report.summarize_short_horizon_readiness(db_path=self._tmp)
        ids = [e["event_id"] for e in result["examples"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_examples_only(self) -> None:
        self._seed_n_events(7)
        result = report.summarize_short_horizon_readiness(
            db_path=self._tmp, limit=3,
        )
        self.assertEqual(result["total_events"],         7)
        self.assertEqual(result["missing_tickers_count"], 0)
        self.assertEqual(len(result["examples"]),        3)
        self.assertEqual(
            [e["event_id"] for e in result["examples"]],
            sorted(e["event_id"] for e in result["examples"]),
        )

    def test_negative_limit_clamps_to_zero(self) -> None:
        self._seed_n_events(3)
        result = report.summarize_short_horizon_readiness(
            db_path=self._tmp, limit=-1,
        )
        self.assertEqual(result["examples"],     [])
        self.assertEqual(result["total_events"], 3)


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
            "ready (1d/5d)",
            "delta vs. full",
            "missing tickers",
            "missing benchmark",
            "insufficient estimation window",
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
        self.assertEqual(set(body.keys()), set(_TOP_KEYS))
        self.assertEqual(len(body["examples"]), 1)
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, body["examples"][0],
                          f"per-event missing field: {key}")
        for key in _CHECK_KEYS:
            self.assertIn(key, body["examples"][0]["checks"],
                          f"checks missing field: {key}")

    def test_db_path_resolves_supplied_archive(self) -> None:
        empty = os.path.join(
            tempfile.gettempdir(),
            f"test_svshrr_alt_{uuid.uuid4().hex}.db",
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
            self.assertEqual(body["examples"],     [])
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
        self.assertEqual(len(body["examples"]),  1)


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
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()

        before = _snapshot_tables(self._tmp)
        for _ in range(3):
            report.summarize_short_horizon_readiness(db_path=self._tmp)
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
            _seed_short_horizon_full_cache(
                conn, ticker="AAPL", event_date=ed,
            )
            conn.commit()
        first = report.summarize_short_horizon_readiness(db_path=self._tmp)
        for _ in range(3):
            self.assertEqual(
                report.summarize_short_horizon_readiness(db_path=self._tmp),
                first,
            )


# ---------------------------------------------------------------------------
# Read-only SQL guard
# ---------------------------------------------------------------------------


class TestReadOnlySql(_Base):
    def test_only_select_statements_executed(self) -> None:
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
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-22")
            conn.commit()

        with patch.object(_sqlite3, "connect", side_effect=tracing_connect):
            result = report.summarize_short_horizon_readiness(db_path=self._tmp)

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
            _seed_cache_row(conn, ticker="AAPL", date_str="2026-04-22")
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
                        f"stat_validation_short_horizon_readiness_report "
                        f"must not call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "stat_validation_short_horizon_readiness_report "
                        "must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            result = report.summarize_short_horizon_readiness(db_path=self._tmp)

        self.assertEqual(result["total_events"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(report, "app"))
        self.assertFalse(hasattr(report, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
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
            report.summarize_short_horizon_readiness(db_path=self._tmp)
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


if __name__ == "__main__":
    unittest.main()
