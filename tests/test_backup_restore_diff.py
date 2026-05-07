"""Tests for ``backup_restore_diff`` — pure module.

Tests fabricate temp SQLite files (no real archive, no real backup
directory) so each one is hermetic.  Asserts:

  * Schema computer returns sorted columns per table.
  * Archive-counts collapses missing tables to 0.
  * Event-date summary mirrors the planner's aggregate via pure SQL.
  * Drift orchestrator
      - errors on missing tables and on column-set drift,
      - warns on >5% row-count drift, not on <=5%,
      - returns ``ok=True`` when both sides match.
  * Temp copy is removed by default and kept under ``keep_temp=True``.
  * Live DB is opened ``mode=ro`` — even SELECT-only access on a real
    write connection would create a -journal file; the harness must
    not.
  * Module never imports a provider/yfinance/LLM/FastAPI seam.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backup_restore_diff as brd  # noqa: E402


_EVENTS_COLS_BASE = (
    "id", "timestamp", "headline", "stage", "persistence",
    "what_changed", "mechanism_summary", "beneficiaries", "losers",
    "assets_to_watch", "confidence", "market_note", "market_tickers",
    "event_date", "notes",
)

_PRICE_CACHE_COLS = (
    "ticker", "date", "close", "volume", "auto_adjust", "fetched_at",
)


def _create_events_table(conn, *, extra_cols=()) -> None:
    cols = list(_EVENTS_COLS_BASE) + list(extra_cols)
    col_defs = ", ".join([
        ("id INTEGER PRIMARY KEY AUTOINCREMENT" if c == "id" else f"{c} TEXT")
        for c in cols
    ])
    conn.execute(f"CREATE TABLE events ({col_defs})")


def _create_price_cache_table(conn) -> None:
    conn.execute(
        "CREATE TABLE price_cache ("
        "ticker TEXT, date TEXT, close REAL, volume REAL, "
        "auto_adjust INTEGER, fetched_at TEXT)"
    )


def _make_db(*, events_extra_cols=(), include_price_cache=True) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"brd_{uuid.uuid4().hex}.db",
    )
    conn = sqlite3.connect(path)
    try:
        _create_events_table(conn, extra_cols=events_extra_cols)
        if include_price_cache:
            _create_price_cache_table(conn)
        conn.commit()
    finally:
        conn.close()
    return path


def _insert_event(
    db_path,
    *,
    timestamp,
    event_date,
    market_tickers,
    headline=None,
):
    head = headline or f"H {uuid.uuid4().hex[:8]}"
    payload = json.dumps([{"symbol": s.upper()} for s in market_tickers])
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO events "
            "(timestamp, headline, stage, persistence, "
            " market_tickers, event_date) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (timestamp, head, "realized", "medium",
             payload, event_date),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_price_cache_rows(db_path, n):
    conn = sqlite3.connect(db_path)
    try:
        for i in range(n):
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (f"T{i % 5}", f"2026-04-{(i % 27) + 1:02d}",
                 100.0 + i, 1_000_000.0,
                 0, "2026-05-06T00:00:00+00:00"),
            )
        conn.commit()
    finally:
        conn.close()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_paths: list[str] = []

    def tearDown(self) -> None:
        for p in self._tmp_paths:
            try:
                if os.path.isdir(p):
                    shutil.rmtree(p, ignore_errors=True)
                elif os.path.isfile(p):
                    os.remove(p)
            except (OSError, PermissionError):
                pass

    def _track(self, path: str) -> str:
        self._tmp_paths.append(path)
        return path


# ---------------------------------------------------------------------------
# compute_schema / compute_archive_counts / compute_event_date_backfill_summary
# ---------------------------------------------------------------------------


class TestComputeSchema(_Base):
    def test_returns_sorted_columns_per_table(self) -> None:
        db = self._track(_make_db())
        schema = brd.compute_schema(db)
        self.assertIn("events", schema)
        self.assertIn("price_cache", schema)
        for table, cols in schema.items():
            self.assertEqual(cols, sorted(cols),
                             f"{table} columns should be sorted")

    def test_excludes_sqlite_internal_tables(self) -> None:
        db = self._track(_make_db())
        # Force creation of sqlite_sequence by inserting into events.
        _insert_event(db,
                      timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        schema = brd.compute_schema(db)
        for name in schema:
            self.assertFalse(
                name.startswith("sqlite_"),
                f"internal table leaked: {name}",
            )


class TestComputeArchiveCounts(_Base):
    def test_zero_on_empty_db(self) -> None:
        db = self._track(_make_db())
        counts = brd.compute_archive_counts(db)
        self.assertEqual(counts["events"],      0)
        self.assertEqual(counts["price_cache"], 0)

    def test_reflects_inserted_rows(self) -> None:
        db = self._track(_make_db())
        _insert_event(db, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        _insert_event(db, timestamp="2026-04-15T14:30:00",
                      event_date="2026-04-15", market_tickers=["MSFT"])
        _insert_price_cache_rows(db, n=12)
        counts = brd.compute_archive_counts(db)
        self.assertEqual(counts["events"],      2)
        self.assertEqual(counts["price_cache"], 12)

    def test_missing_table_collapses_to_zero(self) -> None:
        db = self._track(_make_db(include_price_cache=False))
        counts = brd.compute_archive_counts(db)
        self.assertEqual(counts["events"],      0)
        self.assertEqual(counts["price_cache"], 0)


class TestComputeEventDateBackfillSummary(_Base):
    def test_zero_on_empty_db(self) -> None:
        db = self._track(_make_db())
        summary = brd.compute_event_date_backfill_summary(db)
        self.assertEqual(summary["total_candidates"],       0)
        self.assertEqual(summary["ticker_rows_blocked"],    0)
        self.assertEqual(summary["proposed_updates_count"], 0)

    def test_counts_null_and_empty_event_date(self) -> None:
        db = self._track(_make_db())
        _insert_event(db, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL", "MSFT"])
        _insert_event(db, timestamp="2026-04-16T09:00:00",
                      event_date="",   market_tickers=["GOOG"])
        # Dated row excluded.
        _insert_event(db, timestamp="2026-04-17T09:00:00",
                      event_date="2026-04-17", market_tickers=["TSLA"])
        summary = brd.compute_event_date_backfill_summary(db)
        self.assertEqual(summary["total_candidates"],       2)
        self.assertEqual(summary["ticker_rows_blocked"],    3)
        self.assertEqual(summary["proposed_updates_count"], 2)

    def test_unparseable_timestamp_skipped_from_proposed(self) -> None:
        db = self._track(_make_db())
        _insert_event(db, timestamp="not-a-date",
                      event_date=None, market_tickers=["AAPL"])
        summary = brd.compute_event_date_backfill_summary(db)
        self.assertEqual(summary["total_candidates"],       1)
        self.assertEqual(summary["ticker_rows_blocked"],    1)
        self.assertEqual(summary["proposed_updates_count"], 0)


# ---------------------------------------------------------------------------
# diff_backup_against_live — orchestrator
# ---------------------------------------------------------------------------


class TestDiffMatchingDatabases(_Base):
    def test_ok_true_when_schemas_and_counts_align(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        for db in (backup, live):
            _insert_event(db, timestamp="2026-04-15T13:30:00",
                          event_date=None, market_tickers=["AAPL"])
            _insert_price_cache_rows(db, n=10)
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_diagnostics_contain_required_blocks(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        diag = report["diagnostics"]
        for key in (
            "schema", "archive_counts",
            "event_date_backfill", "reaction_profile_blockers",
        ):
            self.assertIn(key, diag, f"missing diagnostic block: {key}")
        self.assertTrue(diag["reaction_profile_blockers"]["skipped"])


class TestDiffSchemaDrift(_Base):
    def test_column_set_drift_is_an_error(self) -> None:
        backup = self._track(_make_db(events_extra_cols=()))
        live   = self._track(_make_db(events_extra_cols=("new_col",)))
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "schema drift" in e and "events" in e
            for e in report["errors"]
        ), report["errors"])

    def test_missing_table_in_live_is_an_error(self) -> None:
        backup = self._track(_make_db(include_price_cache=True))
        live   = self._track(_make_db(include_price_cache=False))
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "missing in live" in e and "price_cache" in e
            for e in report["errors"]
        ), report["errors"])


class TestDiffRowCountDrift(_Base):
    def test_above_five_percent_drift_is_a_warning(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        # 100 vs 110 → 9.09% drift.
        for _ in range(100):
            _insert_event(
                backup, timestamp="2026-04-15T13:30:00",
                event_date="2026-04-15", market_tickers=[],
            )
        for _ in range(110):
            _insert_event(
                live, timestamp="2026-04-15T13:30:00",
                event_date="2026-04-15", market_tickers=[],
            )
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        self.assertEqual(report["errors"], [])
        self.assertTrue(any(
            "row-count drift" in w and "events" in w
            for w in report["warnings"]
        ), report["warnings"])
        self.assertTrue(report["ok"])

    def test_below_five_percent_drift_is_silent(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        for _ in range(100):
            _insert_event(
                backup, timestamp="2026-04-15T13:30:00",
                event_date="2026-04-15", market_tickers=[],
            )
        for _ in range(103):  # 2.91%
            _insert_event(
                live, timestamp="2026-04-15T13:30:00",
                event_date="2026-04-15", market_tickers=[],
            )
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["errors"],   [])
        self.assertTrue(report["ok"])

    def test_zero_zero_collapses_to_zero_drift(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        archive = report["diagnostics"]["archive_counts"]
        self.assertEqual(archive["events"]["drift_pct"],      0.0)
        self.assertEqual(archive["price_cache"]["drift_pct"], 0.0)


class TestDiffEventDateBackfillBlock(_Base):
    def test_per_side_summaries_returned(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        _insert_event(backup, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        # Live has the date filled — fewer candidates.
        _insert_event(live, timestamp="2026-04-15T13:30:00",
                      event_date="2026-04-15", market_tickers=["AAPL"])
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        edb = report["diagnostics"]["event_date_backfill"]
        self.assertEqual(edb["backup"]["total_candidates"], 1)
        self.assertEqual(edb["live"]["total_candidates"],   0)


class TestDiffMissingFiles(_Base):
    def test_missing_backup_produces_error(self) -> None:
        live = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path="/no/such/backup.db",
            live_db_path=live,
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "backup file does not exist" in e
            for e in report["errors"]
        ))

    def test_missing_live_db_produces_error(self) -> None:
        backup = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path=backup,
            live_db_path="/no/such/live.db",
        )
        self.assertFalse(report["ok"])
        self.assertTrue(any(
            "live DB does not exist" in e
            for e in report["errors"]
        ))


class TestNoMutationOfInputs(_Base):
    def _file_signature(self, path: str) -> tuple[int, bytes]:
        with open(path, "rb") as f:
            data = f.read()
        return (len(data), data[:64])

    def test_repeated_diffs_do_not_modify_either_input(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        _insert_event(backup, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        _insert_event(live, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        before_backup = self._file_signature(backup)
        before_live   = self._file_signature(live)
        for _ in range(3):
            brd.diff_backup_against_live(
                backup_path=backup, live_db_path=live,
            )
        after_backup = self._file_signature(backup)
        after_live   = self._file_signature(live)
        self.assertEqual(before_backup, after_backup)
        self.assertEqual(before_live,   after_live)

    def test_no_journal_file_left_alongside_live(self) -> None:
        # ``mode=ro`` + read-only operations must not create a -journal.
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        _insert_event(live, timestamp="2026-04-15T13:30:00",
                      event_date=None, market_tickers=["AAPL"])
        brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        for suffix in ("-journal", "-wal", "-shm"):
            self.assertFalse(
                os.path.exists(live + suffix),
                f"unexpected sidecar at {live + suffix}",
            )


class TestKeepTemp(_Base):
    def test_temp_copy_removed_by_default(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
        )
        # Default: temp_backup_path field is None when not kept.
        self.assertIsNone(report["temp_backup_path"])

    def test_keep_temp_returns_path_that_exists(self) -> None:
        backup = self._track(_make_db())
        live   = self._track(_make_db())
        report = brd.diff_backup_against_live(
            backup_path=backup, live_db_path=live,
            keep_temp=True,
        )
        path = report["temp_backup_path"]
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.isfile(path),
                        f"temp file should exist when keep_temp=True: {path}")
        # Track for cleanup so the temp dir is removed at tearDown.
        self._tmp_paths.append(os.path.dirname(path))


class TestResolveLatestBackup(_Base):
    def test_returns_lex_max_match(self) -> None:
        d = tempfile.mkdtemp(prefix="brd_resolve_")
        self._tmp_paths.append(d)
        for name in (
            "events-20260101T000000.db",
            "events-20260601T000000.db",
            "events-20260301T000000.db",
            "unrelated.txt",
        ):
            with open(os.path.join(d, name), "w") as f:
                f.write("")
        latest = brd.resolve_latest_backup(d)
        self.assertIsNotNone(latest)
        self.assertEqual(os.path.basename(str(latest)),
                         "events-20260601T000000.db")

    def test_returns_none_for_empty_directory(self) -> None:
        d = tempfile.mkdtemp(prefix="brd_resolve_")
        self._tmp_paths.append(d)
        self.assertIsNone(brd.resolve_latest_backup(d))

    def test_returns_none_for_missing_directory(self) -> None:
        self.assertIsNone(brd.resolve_latest_backup("/no/such/dir"))


class TestNoForbiddenSeams(unittest.TestCase):
    def test_module_does_not_carry_provider_seams(self) -> None:
        for forbidden in (
            "fastapi", "router", "app",
            "yfinance", "market_check", "market_data",
            "anthropic", "openai",
        ):
            self.assertFalse(
                hasattr(brd, forbidden),
                f"backup_restore_diff carries '{forbidden}'",
            )


if __name__ == "__main__":
    unittest.main()
