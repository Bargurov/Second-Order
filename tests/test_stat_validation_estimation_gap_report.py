"""Tests for ``scripts/stat_validation_estimation_gap_report.py``.

The report is a focused, read-only drill-in on the
``insufficient_estimation_window`` blocker: for every evaluable event
(parseable ``event_date`` AND a primary ticker) it surfaces how far
short of the 60-day estimation window the price cache currently is,
plus the boundary dates an operator can use to plan a backfill.

What we pin
-----------
* Per-event field shape — every required field per spec.
* Math: ``pre_event_cached_days`` counts distinct cached dates strictly
  before ``event_date`` for the primary ticker; ``missing_days`` is
  ``max(0, 60 - pre)``; the boundary dates are the earliest cache row
  for the ticker (any direction) and the latest pre-event cache row.
* Filter: only evaluable events with a real gap appear in the events
  list.  Healthy events (>= 60) and not-evaluable events (no
  event_date, no primary ticker) are NOT listed but ARE counted
  in the appropriate aggregates.
* Edge cases — zero cache, post-only cache, boundary cache row on
  event_date, same date under auto_adjust=0 and 1, datetime-suffixed
  event_date.
* Read-only: repeated runs leave the DB byte-identical.
* CLI plumbing: ``--json``, ``--limit``, ``--db-path``.
* No DB writes, no provider, no yfinance, no LLM, no FastAPI app or
  router surface.
"""
from __future__ import annotations

import builtins
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

from scripts import stat_validation_estimation_gap_report as cli  # noqa: E402


_REQUIRED_DAYS = 60


# ---------------------------------------------------------------------------
# Per-event field contract
# ---------------------------------------------------------------------------


_PER_EVENT_KEYS = (
    "event_id",
    "event_date",
    "primary_ticker",
    "pre_event_cached_days",
    "required_days",
    "missing_days",
    "earliest_cache_date",
    "latest_pre_event_cache_date",
)


_TOP_KEYS = (
    "total_events",
    "events_evaluable",
    "events_with_gap",
    "required_days",
    "events",
    "recommended_next_action",
)


# ---------------------------------------------------------------------------
# Temp-DB fixture
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


def _seed_event(
    conn: sqlite3.Connection,
    *,
    event_date: str | None,
    market_tickers: str | None,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, event_date, market_tickers) "
        "VALUES (?, ?, ?)",
        ("hl", event_date, market_tickers),
    )
    return int(cur.lastrowid)


def _seed_cache(
    conn: sqlite3.Connection,
    *,
    ticker: str, date_str: str, auto_adjust: int = 1,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO price_cache "
        "(ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date_str, 100.0, 5_000_000.0, auto_adjust,
         "2026-05-08T12:00:00+00:00"),
    )


def _seed_n_pre_event_dates(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    event_d: date,
    n: int,
    auto_adjust: int = 1,
) -> list[str]:
    """Seed ``n`` distinct cache dates strictly before ``event_d``.

    Walks backwards day-by-day from event_d - 1, skipping weekends so
    the seeded dates resemble a real price-cache trail.  Returns the
    list of seeded ISO dates in chronological order (earliest first).
    """
    seeded: list[str] = []
    cursor = event_d - timedelta(days=1)
    while len(seeded) < n:
        if cursor.weekday() < 5:
            iso = cursor.isoformat()
            _seed_cache(conn, ticker=ticker, date_str=iso,
                        auto_adjust=auto_adjust)
            seeded.append(iso)
        cursor = cursor - timedelta(days=1)
    seeded.sort()
    return seeded


class _TempDbCase(unittest.TestCase):
    """Per-test temp SQLite DB with the events + price_cache schema."""

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_svegr_{uuid.uuid4().hex}.db",
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

    def _summarize(self, **kwargs):
        return cli.summarize_estimation_gaps(db_path=self._tmp, **kwargs)


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------


class TestReportShape(_TempDbCase):
    def test_top_level_keys_present_for_empty_archive(self) -> None:
        result = self._summarize()
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top key: {key}")
        self.assertEqual(result["total_events"],     0)
        self.assertEqual(result["events_evaluable"], 0)
        self.assertEqual(result["events_with_gap"],  0)
        self.assertEqual(result["required_days"],    _REQUIRED_DAYS)
        self.assertEqual(result["events"],           [])

    def test_per_event_field_shape(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            # 10 pre-event dates → gap of 50.
            _seed_n_pre_event_dates(conn, ticker="AAPL", event_d=ed, n=10)
            conn.commit()

        result = self._summarize()
        self.assertEqual(len(result["events"]), 1)
        entry = result["events"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, entry, f"per-event field missing: {key}")

    def test_required_days_is_60(self) -> None:
        self.assertEqual(self._summarize()["required_days"], 60)


# ---------------------------------------------------------------------------
# Filter — events list contains only evaluable + gapped events
# ---------------------------------------------------------------------------


class TestEventsListFilter(_TempDbCase):
    def test_healthy_event_does_not_appear_in_events_list(self) -> None:
        # Event with exactly 60 distinct pre-event cached dates is at the
        # boundary — by the readiness rule (>= 60) it's ready, so the
        # gap report MUST exclude it from the events list.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=60,
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["events_evaluable"], 1)
        self.assertEqual(result["events_with_gap"],  0)
        self.assertEqual(result["events"],           [])

    def test_event_without_event_date_does_not_appear(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["total_events"],     1)
        self.assertEqual(result["events_evaluable"], 0)
        self.assertEqual(result["events_with_gap"],  0)
        self.assertEqual(result["events"],           [])

    def test_event_without_primary_ticker_does_not_appear(self) -> None:
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15",
                market_tickers="[]",
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["total_events"],     1)
        self.assertEqual(result["events_evaluable"], 0)
        self.assertEqual(result["events_with_gap"],  0)
        self.assertEqual(result["events"],           [])

    def test_event_with_gap_appears_in_events_list(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=10,
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["total_events"],     1)
        self.assertEqual(result["events_evaluable"], 1)
        self.assertEqual(result["events_with_gap"],  1)
        self.assertEqual(len(result["events"]),      1)


# ---------------------------------------------------------------------------
# Math — pre_event_cached_days, missing_days, boundary dates
# ---------------------------------------------------------------------------


class TestMath(_TempDbCase):
    def test_pre_event_cached_days_counts_distinct_pre_event_dates(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            seeded = _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=10,
            )
            conn.commit()

        result = self._summarize()
        entry = result["events"][0]
        self.assertEqual(entry["pre_event_cached_days"], 10)
        self.assertEqual(entry["missing_days"], _REQUIRED_DAYS - 10)
        self.assertEqual(entry["earliest_cache_date"], seeded[0])
        self.assertEqual(entry["latest_pre_event_cache_date"], seeded[-1])

    def test_event_date_boundary_is_strict_less_than(self) -> None:
        # A cache row landing exactly on event_date does NOT count
        # toward pre_event_cached_days — matches the readiness check's
        # strict-less-than rule.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker="AAPL", date_str=ed.isoformat())
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=3,
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["events"][0]["pre_event_cached_days"], 3)

    def test_auto_adjust_variants_count_each_date_once(self) -> None:
        # Same date stored under both auto_adjust=0 and auto_adjust=1
        # must count once — matches readiness/_group_cache_dates which
        # unions adjustment flags via set.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            iso = (ed - timedelta(days=2)).isoformat()
            _seed_cache(conn, ticker="AAPL", date_str=iso, auto_adjust=0)
            _seed_cache(conn, ticker="AAPL", date_str=iso, auto_adjust=1)
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["events"][0]["pre_event_cached_days"], 1)

    def test_post_only_cache_yields_zero_pre_and_none_latest(self) -> None:
        # Cache rows only on/after event_date — pre = 0, missing = 60,
        # latest_pre_event = None, but earliest IS set (post-event date).
        ed = date(2026, 4, 15)
        post_iso = (ed + timedelta(days=1)).isoformat()
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_cache(conn, ticker="AAPL", date_str=post_iso)
            conn.commit()

        result = self._summarize()
        entry = result["events"][0]
        self.assertEqual(entry["pre_event_cached_days"], 0)
        self.assertEqual(entry["missing_days"], _REQUIRED_DAYS)
        self.assertIsNone(entry["latest_pre_event_cache_date"])
        self.assertEqual(entry["earliest_cache_date"], post_iso)

    def test_no_cache_yields_zero_pre_and_none_dates(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            conn.commit()

        result = self._summarize()
        entry = result["events"][0]
        self.assertEqual(entry["pre_event_cached_days"], 0)
        self.assertEqual(entry["missing_days"], _REQUIRED_DAYS)
        self.assertIsNone(entry["earliest_cache_date"])
        self.assertIsNone(entry["latest_pre_event_cache_date"])

    def test_other_tickers_cache_does_not_count(self) -> None:
        # Cache rows for MSFT must not influence the AAPL gap.
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="MSFT", event_d=ed, n=200,
            )
            conn.commit()

        result = self._summarize()
        entry = result["events"][0]
        self.assertEqual(entry["pre_event_cached_days"], 0)
        self.assertIsNone(entry["earliest_cache_date"])

    def test_datetime_suffixed_event_date_is_trimmed(self) -> None:
        # ``2026-04-15T09:30:00`` should parse as 2026-04-15 (matches the
        # readiness report's ``[:10]`` trim).
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date="2026-04-15T09:30:00",
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["events_evaluable"], 1)
        self.assertEqual(result["events_with_gap"],  1)
        self.assertEqual(result["events"][0]["pre_event_cached_days"], 5)

    def test_missing_days_clamps_to_zero_for_excess_cache(self) -> None:
        # An event that's >> 60 (here 200) should NOT appear in the
        # events list at all — but if a future variant decides to list
        # healthy rows, missing_days must still clamp at 0.  Pin the
        # invariant at the function level by exercising the helper
        # directly.
        self.assertEqual(cli._missing_days(0),   60)
        self.assertEqual(cli._missing_days(59),  1)
        self.assertEqual(cli._missing_days(60),  0)
        self.assertEqual(cli._missing_days(200), 0)


# ---------------------------------------------------------------------------
# Aggregates + ordering + limit
# ---------------------------------------------------------------------------


class TestAggregatesAndLimit(_TempDbCase):
    def test_events_sorted_by_event_id_ascending(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
            conn.commit()

        result = self._summarize()
        ids = [e["event_id"] for e in result["events"]]
        self.assertEqual(ids, sorted(ids))

    def test_limit_truncates_events_list_only(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            for _ in range(10):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
            conn.commit()

        result = self._summarize(limit=3)
        self.assertEqual(result["total_events"],     10)
        self.assertEqual(result["events_evaluable"], 10)
        self.assertEqual(result["events_with_gap"],  10)
        self.assertEqual(len(result["events"]),      3)

    def test_negative_limit_clamps_to_zero(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
            conn.commit()

        result = self._summarize(limit=-1)
        self.assertEqual(result["events_with_gap"], 1)
        self.assertEqual(result["events"],          [])

    def test_mixed_population_aggregates(self) -> None:
        # 2 ready, 3 with gap, 1 not-evaluable (no event_date).
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            # 2 ready events for AAPL — but the price_cache is shared
            # across events for the same ticker, so we seed one large
            # window that satisfies both.
            for _ in range(2):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=70,
            )
            # 3 events with a different ticker that has only 5 pre-event
            # cache rows seeded.
            for _ in range(3):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "TSLA"}]),
                )
            _seed_n_pre_event_dates(
                conn, ticker="TSLA", event_d=ed, n=5,
            )
            # 1 not-evaluable event (no event_date).
            _seed_event(
                conn, event_date=None,
                market_tickers=json.dumps([{"symbol": "TSLA"}]),
            )
            conn.commit()

        result = self._summarize()
        self.assertEqual(result["total_events"],     6)
        self.assertEqual(result["events_evaluable"], 5)
        self.assertEqual(result["events_with_gap"],  3)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> tuple[int, str]:
    out = StringIO()
    try:
        rc = cli.main(argv, out=out)
    except SystemExit as exc:
        rc = exc.code
    return rc, out.getvalue()


class TestCli(_TempDbCase):
    def _seed_one_gap_event(self, *, n: int = 5) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=n,
            )
            conn.commit()

    def test_json_mode_emits_valid_json_with_required_keys(self) -> None:
        self._seed_one_gap_event(n=5)
        rc, output = _run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(body["events_with_gap"], 1)
        entry = body["events"][0]
        for key in _PER_EVENT_KEYS:
            self.assertIn(key, entry, f"per-event field missing: {key}")

    def test_text_mode_renders_summary_and_examples(self) -> None:
        self._seed_one_gap_event(n=5)
        rc, output = _run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        text = output.lower()
        for token in (
            "estimation",
            "total events",
            "required",
            "missing",
            "recommended",
        ):
            self.assertIn(token, text,
                          f"text rendering missing token: {token!r}")

    def test_json_limit_truncates_events_only(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            for _ in range(8):
                _seed_event(
                    conn, event_date=ed.isoformat(),
                    market_tickers=json.dumps([{"symbol": "AAPL"}]),
                )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
            conn.commit()

        rc, output = _run_cli([
            "--db-path", self._tmp, "--json", "--limit", "2",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["events_with_gap"], 8)
        self.assertEqual(len(body["events"]),     2)

    def test_db_path_flag_is_consumed(self) -> None:
        # Smoke: the script accepts an explicit --db-path and produces a
        # non-error report against an empty temp DB.
        rc, output = _run_cli(["--db-path", self._tmp, "--json"])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_events"], 0)


# ---------------------------------------------------------------------------
# Read-only invariant
# ---------------------------------------------------------------------------


class TestReadOnly(_TempDbCase):
    def test_repeated_runs_leave_db_byte_identical(self) -> None:
        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=10,
            )
            conn.commit()

        def _snapshot() -> tuple[list, list]:
            conn = sqlite3.connect(self._tmp)
            try:
                events = list(conn.execute(
                    "SELECT * FROM events ORDER BY id",
                ))
                cache = list(conn.execute(
                    "SELECT ticker, date, close, volume, "
                    "auto_adjust, fetched_at FROM price_cache "
                    "ORDER BY ticker, date, auto_adjust",
                ))
                return events, cache
            finally:
                conn.close()

        before = _snapshot()
        for _ in range(3):
            cli.summarize_estimation_gaps(db_path=self._tmp)
        after = _snapshot()
        self.assertEqual(before, after,
                         "events + price_cache must be byte-identical "
                         "across repeated read-only runs")


# ---------------------------------------------------------------------------
# No banned seams
# ---------------------------------------------------------------------------


class TestNoBannedSeams(_TempDbCase):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        ed = date(2026, 4, 15)
        with self._conn() as conn:
            _seed_event(
                conn, event_date=ed.isoformat(),
                market_tickers=json.dumps([{"symbol": "AAPL"}]),
            )
            _seed_n_pre_event_dates(
                conn, ticker="AAPL", event_d=ed, n=5,
            )
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
                        f"estimation gap report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "estimation gap report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            result = cli.summarize_estimation_gaps(db_path=self._tmp)

        self.assertEqual(result["events_with_gap"], 1)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(cli, "app"))
        self.assertFalse(hasattr(cli, "router"))

    def test_running_does_not_import_fastapi_routes_or_llm(self) -> None:
        # Order-independent guard: trace every import the script
        # triggers and reject api/routes/llm/yfinance namespaces.
        forbidden_imports: list[str] = []
        real_import = builtins.__import__

        def _is_forbidden(name: str) -> bool:
            return (
                name == "api" or name.startswith("api.")
                or name == "routes" or name.startswith("routes.")
                or name == "yfinance" or name.startswith("yfinance.")
                or name == "openai" or name.startswith("openai.")
                or name == "anthropic" or name.startswith("anthropic.")
            )

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
            cli.summarize_estimation_gaps(db_path=self._tmp)
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )
        self.assertEqual(forbidden_imports, [],
                         f"forbidden imports: {forbidden_imports}")
        self.assertEqual(newly_loaded_forbidden, [],
                         f"forbidden modules loaded: {newly_loaded_forbidden}")


if __name__ == "__main__":
    unittest.main()
