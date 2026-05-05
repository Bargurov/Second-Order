"""Tests for ``scripts/schema_preflight.py``.

Uses tiny temp SQLite fixtures + scratch backup dirs — never touches
the real ``events.db`` or ``backups/``.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

# Add project root so ``from scripts.schema_preflight import ...`` works
# (Python 3 namespace packages let this resolve without a scripts/__init__.py).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts.schema_preflight import (  # noqa: E402
    _BACKUP_STALE_THRESHOLD_SECONDS,
    collect,
    main,
    render_text,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _build_temp_db(path: str) -> None:
    """Write a tiny SQLite DB with both ``events`` and ``price_cache``."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE events (
                id        INTEGER PRIMARY KEY,
                headline  TEXT NOT NULL,
                stage     TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE price_cache (
                ticker      TEXT,
                date        TEXT,
                close       REAL,
                volume      REAL,
                auto_adjust INTEGER
            )
        """)


def _build_eventless_db(path: str) -> None:
    """A DB without an ``events`` table — exercises the warning branch."""
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE other_table (x INTEGER)")


# ---------------------------------------------------------------------------
# Missing DB
# ---------------------------------------------------------------------------

class TestMissingDB(unittest.TestCase):
    def test_warning_when_db_file_missing(self):
        info = collect("/path/that/should/not/exist.db", "/no/backups/either")
        self.assertFalse(info["database_exists"])
        self.assertIsNone(info["database_size_bytes"])
        self.assertEqual(info["tables"],         [])
        self.assertEqual(info["events_columns"], [])
        self.assertFalse(info["price_cache_present"])
        joined = " ".join(info["warnings"]).lower()
        self.assertIn("database file does not exist", joined)
        self.assertIn("backup directory does not exist", joined)

    def test_no_exception_on_missing_db(self):
        # Pure collector must never raise; assert it returns a dict.
        info = collect("nope.db", "nope-backups")
        self.assertIsInstance(info, dict)


# ---------------------------------------------------------------------------
# Valid DB
# ---------------------------------------------------------------------------

class TestValidDB(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="schema_preflight_")
        self.db  = os.path.join(self.tmp, "events.db")
        self.bd  = os.path.join(self.tmp, "backups")
        _build_temp_db(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_database_exists_and_size_reported(self) -> None:
        info = collect(self.db, self.bd)
        self.assertTrue(info["database_exists"])
        self.assertIsInstance(info["database_size_bytes"], int)
        self.assertGreater(info["database_size_bytes"], 0)

    def test_tables_listed_alphabetically(self) -> None:
        info = collect(self.db, self.bd)
        self.assertEqual(info["tables"], ["events", "price_cache"])

    def test_price_cache_presence_flag(self) -> None:
        info = collect(self.db, self.bd)
        self.assertTrue(info["price_cache_present"])

    def test_events_columns_listed(self) -> None:
        info = collect(self.db, self.bd)
        self.assertEqual(
            set(info["events_columns"]), {"id", "headline", "stage"},
        )

    def test_db_without_events_table_warns(self) -> None:
        path = os.path.join(self.tmp, "no_events.db")
        _build_eventless_db(path)
        info = collect(path, self.bd)
        self.assertNotIn("events", info["tables"])
        self.assertEqual(info["events_columns"], [])
        self.assertTrue(any(
            "events table missing" in w for w in info["warnings"]
        ))


# ---------------------------------------------------------------------------
# Backup warnings
# ---------------------------------------------------------------------------

class TestBackupWarnings(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="schema_preflight_")
        self.db  = os.path.join(self.tmp, "events.db")
        self.bd  = os.path.join(self.tmp, "backups")
        _build_temp_db(self.db)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_missing_backup_dir_warns(self) -> None:
        info = collect(self.db, self.bd)
        self.assertFalse(info["backup_dir_exists"])
        self.assertIsNone(info["latest_backup"])
        self.assertTrue(any(
            "backup directory does not exist" in w
            for w in info["warnings"]
        ))

    def test_empty_backup_dir_warns(self) -> None:
        os.makedirs(self.bd, exist_ok=True)
        info = collect(self.db, self.bd)
        self.assertTrue(info["backup_dir_exists"])
        self.assertIsNone(info["latest_backup"])
        self.assertTrue(any(
            "no backup files" in w for w in info["warnings"]
        ))

    def test_fresh_backup_no_stale_warning(self) -> None:
        os.makedirs(self.bd, exist_ok=True)
        bk = os.path.join(self.bd, "fresh.bak")
        with open(bk, "w") as f:
            f.write("x")
        info = collect(self.db, self.bd, now=os.path.getmtime(bk) + 60)
        self.assertEqual(info["latest_backup"], bk)
        # No stale warning.  The "no backup files" warning is also absent
        # because we wrote one.
        for w in info["warnings"]:
            self.assertNotIn("old (>24h", w)
            self.assertNotIn("no backup files", w)

    def test_stale_backup_warns_with_age(self) -> None:
        os.makedirs(self.bd, exist_ok=True)
        bk = os.path.join(self.bd, "stale.bak")
        with open(bk, "w") as f:
            f.write("x")
        # Inject ``now`` 25h after the file's mtime instead of mutating
        # the file's atime/mtime — keeps the test independent of fs
        # timestamp resolution and tz quirks.
        old_mtime = os.path.getmtime(bk)
        info = collect(
            self.db, self.bd,
            now=old_mtime + (25 * 3600),
        )
        self.assertEqual(info["latest_backup"], bk)
        self.assertGreater(
            info["latest_backup_age_seconds"],
            _BACKUP_STALE_THRESHOLD_SECONDS,
        )
        self.assertTrue(any(
            ">24h threshold" in w for w in info["warnings"]
        ))

    def test_picks_newest_backup_of_many(self) -> None:
        os.makedirs(self.bd, exist_ok=True)
        first  = os.path.join(self.bd, "first.bak")
        second = os.path.join(self.bd, "second.bak")
        for p in (first, second):
            with open(p, "w") as f:
                f.write("x")
        old = time.time() - 3600
        new = time.time()
        os.utime(first,  (old, old))
        os.utime(second, (new, new))
        info = collect(self.db, self.bd)
        self.assertEqual(info["latest_backup"], second)


# ---------------------------------------------------------------------------
# JSON output + CLI
# ---------------------------------------------------------------------------

class TestJSONOutput(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="schema_preflight_")
        self.db  = os.path.join(self.tmp, "events.db")
        self.bd  = os.path.join(self.tmp, "backups")
        _build_temp_db(self.db)
        os.makedirs(self.bd, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_collector_dict_is_json_serialisable(self) -> None:
        info = collect(self.db, self.bd)
        s = json.dumps(info)
        round_trip = json.loads(s)
        self.assertEqual(
            round_trip["database_path"], info["database_path"],
        )
        self.assertEqual(
            set(round_trip["events_columns"]),
            set(info["events_columns"]),
        )

    def test_cli_json_mode_emits_valid_json(self) -> None:
        script = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "schema_preflight.py",
        )
        proc = subprocess.run(
            [sys.executable, script,
             "--db", self.db, "--backup-dir", self.bd, "--json"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = json.loads(proc.stdout)
        for k in (
            "database_path", "database_exists", "database_size_bytes",
            "tables", "events_columns", "price_cache_present",
            "backup_dir", "backup_dir_exists",
            "latest_backup", "latest_backup_age_seconds", "warnings",
        ):
            self.assertIn(k, body, f"missing key in JSON output: {k}")

    def test_cli_text_mode_runs_without_error(self) -> None:
        script = os.path.join(
            os.path.dirname(__file__), "..", "scripts", "schema_preflight.py",
        )
        proc = subprocess.run(
            [sys.executable, script,
             "--db", self.db, "--backup-dir", self.bd],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Text mode hits the rendered headers.
        self.assertIn("=== Schema Preflight ===", proc.stdout)
        self.assertIn("Database path", proc.stdout)
        self.assertIn("Backup dir", proc.stdout)


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

class TestTextRendering(unittest.TestCase):
    def test_text_includes_key_sections_even_when_db_missing(self) -> None:
        info = collect("nope.db", "nope-bd")
        text = render_text(info)
        self.assertIn("Database path", text)
        self.assertIn("Backup dir",    text)
        self.assertIn("Warnings",      text)

    def test_text_lists_columns_when_present(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = os.path.join(tmp, "x.db")
            _build_temp_db(db)
            info = collect(db, os.path.join(tmp, "bk"))
            text = render_text(info)
        self.assertIn("events columns", text)
        self.assertIn("headline",       text)
        self.assertIn("stage",          text)


# ---------------------------------------------------------------------------
# Read-only contract — no writes to the inspected DB or backup dir
# ---------------------------------------------------------------------------

class TestReadOnlyContract(unittest.TestCase):
    def test_collector_does_not_mutate_db_or_backup_dir(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            db = os.path.join(tmp, "events.db")
            bd = os.path.join(tmp, "backups")
            _build_temp_db(db)
            os.makedirs(bd)
            with open(os.path.join(bd, "snap.bak"), "w") as f:
                f.write("x")

            db_size_before  = os.path.getsize(db)
            db_mtime_before = os.path.getmtime(db)
            bd_listing_before = sorted(os.listdir(bd))

            for _ in range(3):
                collect(db, bd)

            self.assertEqual(os.path.getsize(db),  db_size_before)
            self.assertEqual(os.path.getmtime(db), db_mtime_before)
            self.assertEqual(sorted(os.listdir(bd)), bd_listing_before)


if __name__ == "__main__":
    unittest.main()
