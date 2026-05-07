"""Tests for ``scripts/price_cache_auto_adjust_coverage_report.py``.

Pin the read-only contract:

* Per-ticker fields: ``aa0_row_count``, ``aa1_row_count``,
  ``aa0_max_date``, ``aa1_max_date``, ``aa1_only_dates_count``,
  ``aa0_missing_after_aa1_count``.
* ``aa1_only_dates_count`` is the pure set-difference cardinality
  ``|aa1_dates - aa0_dates|`` over the full history.
* ``aa0_missing_after_aa1_count`` counts distinct dates strictly
  after ``aa0_max_date`` where ``aa=1`` has a row.  When ``aa=0``
  has no rows at all, every ``aa=1`` row counts.
* Aggregate fields (``total_tickers``, ``tickers_with_*``) always
  reflect the full population, not the truncated example list.
* ``--limit`` truncates ``tickers`` only.
* ``--json`` and ``--db-path`` plumbing.
* No mutation: ``price_cache`` table byte-identical across repeated
  runs.
* No provider, yfinance, market_check, market_data,
  ``price_cache.fetch_daily_cached``, LLM, or FastAPI seam invoked.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import price_cache_auto_adjust_coverage_report as report  # noqa: E402


# Hand-rolled minimal price_cache DDL — the report only reads
# ``ticker``, ``date``, ``auto_adjust``.  Avoiding ``price_cache._ensure_table``
# keeps the fixture decoupled from the production module's import-time
# side effects (e.g. ``_purge_corrupt_rows``) and lets the tests pin
# the SQL contract directly.
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
    "total_tickers",
    "tickers_with_aa0_only",
    "tickers_with_aa1_only",
    "tickers_with_both_flags",
    "tickers_with_aa1_only_dates",
    "tickers_with_trailing_aa0_gap",
    "tickers",
    "recommended_next_action",
)


_PER_TICKER_KEYS = (
    "ticker",
    "aa0_row_count",
    "aa1_row_count",
    "aa0_max_date",
    "aa1_max_date",
    "aa1_only_dates_count",
    "aa0_missing_after_aa1_count",
)


_FETCHED_AT = "2026-05-06T12:00:00+00:00"


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _seed(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    date_str: str,
    auto_adjust: int,
    close: float = 100.0,
    volume: float = 5_000_000.0,
    fetched_at: str = _FETCHED_AT,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO price_cache "
        "(ticker, date, close, volume, auto_adjust, fetched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (ticker, date_str, close, volume, auto_adjust, fetched_at),
    )


def _seed_many(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    aa0_dates: list[str] | None = None,
    aa1_dates: list[str] | None = None,
) -> None:
    for d in aa0_dates or []:
        _seed(conn, ticker=ticker, date_str=d, auto_adjust=0)
    for d in aa1_dates or []:
        _seed(conn, ticker=ticker, date_str=d, auto_adjust=1)


def _snapshot_price_cache(db_path: str) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache "
            "ORDER BY ticker, date, auto_adjust"
        ))
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_pc_aa_cov_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
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
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_tickers_is_list(self) -> None:
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertIsInstance(result["tickers"], list)

    def test_recommended_next_action_is_non_empty_string(self) -> None:
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertIsInstance(result["recommended_next_action"], str)
        self.assertTrue(result["recommended_next_action"])


# ---------------------------------------------------------------------------
# Empty / single-flag tickers
# ---------------------------------------------------------------------------


class TestEmptyAndSingleFlag(_Base):
    def test_empty_db_returns_zero_counts(self) -> None:
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertEqual(result["total_tickers"],                 0)
        self.assertEqual(result["tickers_with_aa0_only"],         0)
        self.assertEqual(result["tickers_with_aa1_only"],         0)
        self.assertEqual(result["tickers_with_both_flags"],       0)
        self.assertEqual(result["tickers_with_aa1_only_dates"],   0)
        self.assertEqual(result["tickers_with_trailing_aa0_gap"], 0)
        self.assertEqual(result["tickers"],                       [])
        # The empty-state recommendation must be the no-drift label —
        # phrased as "No ... drift detected".  The drifty label opens
        # with "auto_adjust flag drift detected", so the empty-state
        # string must NOT start with that prefix.
        msg = result["recommended_next_action"]
        self.assertFalse(
            msg.startswith("auto_adjust flag drift detected"),
            f"empty-state recommendation should not signal drift: {msg!r}",
        )
        self.assertIn("No", msg)

    def test_aa0_only_ticker_counts_correctly(self) -> None:
        with self._conn() as conn:
            _seed_many(conn, ticker="AAA",
                       aa0_dates=["2026-04-15", "2026-04-16"])
            conn.commit()
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertEqual(result["total_tickers"],         1)
        self.assertEqual(result["tickers_with_aa0_only"], 1)
        self.assertEqual(result["tickers_with_aa1_only"], 0)
        entry = result["tickers"][0]
        self.assertEqual(entry["ticker"],                      "AAA")
        self.assertEqual(entry["aa0_row_count"],               2)
        self.assertEqual(entry["aa1_row_count"],               0)
        self.assertEqual(entry["aa0_max_date"],                "2026-04-16")
        self.assertEqual(entry["aa1_max_date"],                None)
        self.assertEqual(entry["aa1_only_dates_count"],        0)
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 0)

    def test_aa1_only_ticker_treats_all_dates_as_missing_after(self) -> None:
        # When aa=0 is empty, every aa=1 row counts as
        # "missing after aa=1" because aa0_max_date is None.
        with self._conn() as conn:
            _seed_many(conn, ticker="BBB",
                       aa1_dates=["2026-04-15", "2026-04-16", "2026-04-17"])
            conn.commit()
        result = report.summarize_coverage(db_path=self._tmp)
        entry = result["tickers"][0]
        self.assertEqual(entry["ticker"],                      "BBB")
        self.assertEqual(entry["aa0_row_count"],               0)
        self.assertEqual(entry["aa1_row_count"],               3)
        self.assertEqual(entry["aa0_max_date"],                None)
        self.assertEqual(entry["aa1_max_date"],                "2026-04-17")
        self.assertEqual(entry["aa1_only_dates_count"],        3)
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 3)
        self.assertEqual(result["tickers_with_aa1_only"], 1)


# ---------------------------------------------------------------------------
# Mixed-flag semantics
# ---------------------------------------------------------------------------


class TestSetDifferenceSemantics(_Base):
    def test_aa1_only_dates_is_pure_set_difference(self) -> None:
        # aa=0: {15, 16}; aa=1: {15, 16, 17, 18}.  aa=1-only = {17, 18}.
        with self._conn() as conn:
            _seed_many(
                conn, ticker="MIX",
                aa0_dates=["2026-04-15", "2026-04-16"],
                aa1_dates=["2026-04-15", "2026-04-16", "2026-04-17", "2026-04-18"],
            )
            conn.commit()
        entry = report.summarize_coverage(db_path=self._tmp)["tickers"][0]
        self.assertEqual(entry["aa1_only_dates_count"], 2)

    def test_aa0_missing_after_aa1_is_strict_after_aa0_max(self) -> None:
        # aa=0 max = 2026-04-16.  aa=1 dates strictly after that:
        # {2026-04-17, 2026-04-18}.  Earlier aa=1 dates do NOT count.
        with self._conn() as conn:
            _seed_many(
                conn, ticker="MIX",
                aa0_dates=["2026-04-10", "2026-04-15", "2026-04-16"],
                aa1_dates=[
                    "2026-04-12",  # before aa=0 max — excluded
                    "2026-04-15",  # equal to aa=0 max — excluded
                    "2026-04-16",  # equal to aa=0 max — excluded
                    "2026-04-17",  # strictly after — included
                    "2026-04-18",  # strictly after — included
                ],
            )
            conn.commit()
        entry = report.summarize_coverage(db_path=self._tmp)["tickers"][0]
        self.assertEqual(entry["aa0_max_date"],                "2026-04-16")
        self.assertEqual(entry["aa1_max_date"],                "2026-04-18")
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 2)

    def test_aa1_only_dates_can_exceed_trailing_gap(self) -> None:
        # aa=0: {16}; aa=1: {15, 16, 17}.  aa1_only={15, 17}=2.
        # trailing_after_aa0_max(=16) = {17} = 1.
        with self._conn() as conn:
            _seed_many(
                conn, ticker="X",
                aa0_dates=["2026-04-16"],
                aa1_dates=["2026-04-15", "2026-04-16", "2026-04-17"],
            )
            conn.commit()
        entry = report.summarize_coverage(db_path=self._tmp)["tickers"][0]
        self.assertEqual(entry["aa1_only_dates_count"],        2)
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 1)

    def test_aa0_extends_past_aa1_yields_zero_trailing_gap(self) -> None:
        # aa=0 max past aa=1 max — every aa=1 date is at or before
        # aa=0 max, so the trailing gap is 0.
        with self._conn() as conn:
            _seed_many(
                conn, ticker="X",
                aa0_dates=["2026-04-15", "2026-04-16", "2026-04-17", "2026-04-18"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            conn.commit()
        entry = report.summarize_coverage(db_path=self._tmp)["tickers"][0]
        self.assertEqual(entry["aa0_max_date"],                "2026-04-18")
        self.assertEqual(entry["aa1_max_date"],                "2026-04-16")
        self.assertEqual(entry["aa1_only_dates_count"],        0)
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 0)

    def test_identical_coverage_yields_zero_drift_metrics(self) -> None:
        with self._conn() as conn:
            _seed_many(
                conn, ticker="EQUAL",
                aa0_dates=["2026-04-15", "2026-04-16", "2026-04-17"],
                aa1_dates=["2026-04-15", "2026-04-16", "2026-04-17"],
            )
            conn.commit()
        entry = report.summarize_coverage(db_path=self._tmp)["tickers"][0]
        self.assertEqual(entry["aa1_only_dates_count"],        0)
        self.assertEqual(entry["aa0_missing_after_aa1_count"], 0)


# ---------------------------------------------------------------------------
# Aggregate counts
# ---------------------------------------------------------------------------


class TestAggregateCounts(_Base):
    def test_aggregates_split_by_flag_membership(self) -> None:
        with self._conn() as conn:
            _seed_many(conn, ticker="AA0", aa0_dates=["2026-04-15"])
            _seed_many(conn, ticker="AA1", aa1_dates=["2026-04-15"])
            _seed_many(
                conn, ticker="BOTH",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15"],
            )
            conn.commit()
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertEqual(result["total_tickers"],                 3)
        self.assertEqual(result["tickers_with_aa0_only"],         1)
        self.assertEqual(result["tickers_with_aa1_only"],         1)
        self.assertEqual(result["tickers_with_both_flags"],       1)
        self.assertEqual(result["tickers_with_aa1_only_dates"],   1)  # AA1
        self.assertEqual(result["tickers_with_trailing_aa0_gap"], 1)  # AA1

    def test_recommendation_flips_with_drift(self) -> None:
        # Clean — both flags carry the same dates.
        with self._conn() as conn:
            _seed_many(
                conn, ticker="EQ",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15"],
            )
            conn.commit()
        clean = report.summarize_coverage(db_path=self._tmp)
        self.assertEqual(clean["tickers_with_aa1_only_dates"],   0)
        self.assertEqual(clean["tickers_with_trailing_aa0_gap"], 0)
        clean_msg = clean["recommended_next_action"]

        # Add drift — aa=1 carries a date aa=0 does not.
        with self._conn() as conn:
            _seed(conn, ticker="EQ", date_str="2026-04-16", auto_adjust=1)
            conn.commit()
        drifty = report.summarize_coverage(db_path=self._tmp)
        self.assertGreaterEqual(drifty["tickers_with_aa1_only_dates"], 1)
        self.assertNotEqual(clean_msg, drifty["recommended_next_action"])
        self.assertIn("drift detected", drifty["recommended_next_action"])


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------


class TestSortOrder(_Base):
    def test_worst_drift_floats_to_top(self) -> None:
        with self._conn() as conn:
            # Clean: zero drift.
            _seed_many(
                conn, ticker="CLEAN",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15"],
            )
            # One date of aa=1-only drift.
            _seed_many(
                conn, ticker="ONE",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            # Three dates of aa=1-only drift.
            _seed_many(
                conn, ticker="THREE",
                aa0_dates=["2026-04-15"],
                aa1_dates=[
                    "2026-04-15", "2026-04-16",
                    "2026-04-17", "2026-04-18",
                ],
            )
            conn.commit()
        result = report.summarize_coverage(db_path=self._tmp)
        order = [t["ticker"] for t in result["tickers"]]
        self.assertEqual(order, ["THREE", "ONE", "CLEAN"])

    def test_ties_break_alphabetically(self) -> None:
        with self._conn() as conn:
            for ticker in ("CHARLIE", "ALPHA", "BRAVO"):
                _seed_many(
                    conn, ticker=ticker,
                    aa0_dates=["2026-04-15"],
                    aa1_dates=["2026-04-15", "2026-04-16"],
                )
            conn.commit()
        order = [
            t["ticker"]
            for t in report.summarize_coverage(db_path=self._tmp)["tickers"]
        ]
        self.assertEqual(order, ["ALPHA", "BRAVO", "CHARLIE"])


# ---------------------------------------------------------------------------
# --limit truncation does not affect aggregates
# ---------------------------------------------------------------------------


class TestLimit(_Base):
    def _seed_n_drifty(self, n: int) -> None:
        with self._conn() as conn:
            for i in range(n):
                _seed_many(
                    conn, ticker=f"T{i:02d}",
                    aa0_dates=["2026-04-15"],
                    aa1_dates=["2026-04-15", "2026-04-16"],
                )
            conn.commit()

    def test_default_limit_returns_full_supply(self) -> None:
        self._seed_n_drifty(7)
        result = report.summarize_coverage(db_path=self._tmp)
        self.assertEqual(len(result["tickers"]), 7)

    def test_limit_truncates_tickers_only(self) -> None:
        self._seed_n_drifty(7)
        result = report.summarize_coverage(db_path=self._tmp, limit=3)
        self.assertEqual(len(result["tickers"]),                 3)
        self.assertEqual(result["total_tickers"],                7)
        self.assertEqual(result["tickers_with_both_flags"],      7)
        self.assertEqual(result["tickers_with_aa1_only_dates"],  7)

    def test_negative_limit_clamps_to_zero(self) -> None:
        self._seed_n_drifty(3)
        result = report.summarize_coverage(db_path=self._tmp, limit=-1)
        self.assertEqual(result["tickers"],          [])
        self.assertEqual(result["total_tickers"],    3)


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

    def test_cli_text_output_summarises_each_field(self) -> None:
        with self._conn() as conn:
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            conn.commit()
        rc, output = self._run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        for needle in (
            "Total tickers",
            "aa=0 only",
            "aa=1 only",
            "Both flags",
            "With aa=1-only dates",
            "With trailing aa=0 gap",
            "Recommended next action",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")
        # Ticker line surfaces the metric for the operator at a glance.
        self.assertIn("AAA",                       output)
        self.assertIn("aa1_only_dates=1",          output)
        self.assertIn("aa0_missing_after_aa1=1",   output)

    def test_cli_json_output_carries_required_keys(self) -> None:
        with self._conn() as conn:
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp, "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")
        self.assertEqual(len(body["tickers"]), 1)
        for key in _PER_TICKER_KEYS:
            self.assertIn(key, body["tickers"][0],
                          f"per-ticker missing field: {key}")

    def test_cli_limit_truncates_tickers_only(self) -> None:
        with self._conn() as conn:
            for ticker in ("A", "B", "C"):
                _seed_many(
                    conn, ticker=ticker,
                    aa0_dates=["2026-04-15"],
                    aa1_dates=["2026-04-15", "2026-04-16"],
                )
            conn.commit()
        rc, output = self._run_cli([
            "--db-path", self._tmp,
            "--limit",   "1",
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["total_tickers"],                3)
        self.assertEqual(body["tickers_with_aa1_only_dates"],  3)
        self.assertEqual(len(body["tickers"]),                 1)

    def test_cli_db_path_resolves_supplied_archive(self) -> None:
        # Build a second standalone temp DB and confirm the report
        # walks only that file (not db.DB_FILE).
        empty = os.path.join(
            tempfile.gettempdir(),
            f"test_pc_aa_cov_alt_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(empty)
        try:
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
            self.assertEqual(body["total_tickers"], 0)
            self.assertEqual(body["tickers"],       [])
        finally:
            try:
                os.remove(empty)
            except (OSError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# No mutation — repeated runs leave price_cache byte-identical
# ---------------------------------------------------------------------------


class TestNoMutation(_Base):
    def test_repeated_calls_leave_price_cache_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15", "2026-04-16"],
                aa1_dates=["2026-04-15", "2026-04-16", "2026-04-17"],
            )
            _seed_many(
                conn, ticker="BBB",
                aa1_dates=["2026-04-15"],
            )
            conn.commit()

        before = _snapshot_price_cache(self._tmp)
        for _ in range(3):
            report.summarize_coverage(db_path=self._tmp)
        after = _snapshot_price_cache(self._tmp)
        self.assertEqual(
            before, after,
            "price_cache must be byte-identical across repeated runs",
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        with self._conn() as conn:
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
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
                        f"price_cache_auto_adjust_coverage_report must "
                        f"not call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "price_cache_auto_adjust_coverage_report must "
                        "not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            result = report.summarize_coverage(db_path=self._tmp)

        self.assertEqual(result["total_tickers"],                1)
        self.assertEqual(result["tickers_with_aa1_only_dates"],  1)

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
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            conn.commit()

        before_modules = set(sys.modules.keys())
        with patch("builtins.__import__", side_effect=tracing_import):
            report.summarize_coverage(db_path=self._tmp)
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
# Read-only SQL guard — no write path can quietly regress
# ---------------------------------------------------------------------------


class TestReadOnlySql(_Base):
    def test_only_select_statements_executed(self) -> None:
        # ``sqlite3.Connection.execute`` is a slot on an immutable C
        # type and can't be patched, so install
        # ``Connection.set_trace_callback`` on every connection the
        # script opens.  The callback fires for every SQL statement
        # the connection actually executes, capturing the read-only
        # contract end-to-end.
        import sqlite3 as _sqlite3

        recorded: list[str] = []
        real_connect = _sqlite3.connect

        def tracing_connect(*args, **kwargs):
            conn = real_connect(*args, **kwargs)
            conn.set_trace_callback(recorded.append)
            return conn

        with self._conn() as conn:
            _seed_many(
                conn, ticker="AAA",
                aa0_dates=["2026-04-15"],
                aa1_dates=["2026-04-15", "2026-04-16"],
            )
            conn.commit()

        with patch.object(_sqlite3, "connect", side_effect=tracing_connect):
            result = report.summarize_coverage(db_path=self._tmp)

        self.assertEqual(result["total_tickers"], 1)
        # At least one SELECT must have been issued, and every
        # recorded statement must start with SELECT.
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
# Default db_path resolution
# ---------------------------------------------------------------------------


class TestDefaultDbPathResolution(unittest.TestCase):
    def test_resolves_db_dot_DB_FILE_when_db_path_omitted(self) -> None:
        # Stand up an isolated DB and patch ``db.DB_FILE`` so the
        # default-resolution path goes through the production
        # ``_resolve_db_path`` helper without touching the real
        # project archive.
        path = os.path.join(
            tempfile.gettempdir(),
            f"test_pc_aa_cov_default_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(path)
        try:
            conn.execute(_PRICE_CACHE_DDL)
            _seed(conn, ticker="ZZZ",
                  date_str="2026-04-15", auto_adjust=1)
            conn.commit()
        finally:
            conn.close()
        try:
            import db as _db
            with patch.object(_db, "DB_FILE", path):
                result = report.summarize_coverage()
            self.assertEqual(result["total_tickers"], 1)
            self.assertEqual(result["tickers"][0]["ticker"], "ZZZ")
        finally:
            try:
                os.remove(path)
            except (OSError, PermissionError):
                pass


if __name__ == "__main__":
    unittest.main()
