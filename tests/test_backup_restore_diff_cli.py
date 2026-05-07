"""Tests for ``scripts/backup_restore_diff.py`` — drift CLI.

Each test fabricates temp DB files plus a temp backups directory so
the CLI never depends on the real archive.  Asserts:

  * ``--latest`` picks the lexicographically newest ``events-*.db``
    in ``--backups-dir``.
  * ``--backup-path`` and ``--latest`` are mutually exclusive
    (argparse rejects neither/both).
  * ``--json`` carries every required top-level key.
  * Exit code 0 on ok=True, non-zero on schema drift.
  * ``--keep-temp`` preserves the temp copy.
  * No FastAPI / no provider / no LLM seam reachable from the CLI
    module.
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
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import backup_restore_diff as cli  # noqa: E402


_TOP_KEYS = (
    "ok",
    "backup_path",
    "live_db_path",
    "temp_backup_path",
    "diagnostics",
    "warnings",
    "errors",
)


def _make_events_db(*, extra_cols=()) -> str:
    path = os.path.join(
        tempfile.gettempdir(),
        f"brd_cli_{uuid.uuid4().hex}.db",
    )
    cols = [
        "id INTEGER PRIMARY KEY AUTOINCREMENT",
        "timestamp TEXT NOT NULL",
        "headline TEXT NOT NULL",
        "stage TEXT NOT NULL",
        "persistence TEXT NOT NULL",
        "market_tickers TEXT DEFAULT '[]'",
        "event_date TEXT DEFAULT NULL",
    ] + [f"{c} TEXT" for c in extra_cols]
    conn = sqlite3.connect(path)
    try:
        conn.execute(f"CREATE TABLE events ({', '.join(cols)})")
        conn.execute(
            "CREATE TABLE price_cache "
            "(ticker TEXT, date TEXT, close REAL, volume REAL, "
            " auto_adjust INTEGER, fetched_at TEXT)"
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _run_cli(argv):
    out = StringIO()
    rc = cli.main(argv, out=out)
    return rc, out.getvalue()


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

    def _make_backups_dir(self, names) -> str:
        d = tempfile.mkdtemp(prefix="brd_cli_dir_")
        self._tmp_paths.append(d)
        for name in names:
            shutil.copy2(_make_events_db(), os.path.join(d, name))
        return d


class TestCliMutualExclusion(unittest.TestCase):
    def test_neither_latest_nor_backup_path_rejected(self) -> None:
        with patch("sys.stderr", new_callable=StringIO):
            with self.assertRaises(SystemExit) as cm:
                _run_cli(["--live-db", "events.db"])
        self.assertEqual(cm.exception.code, 2)

    def test_both_latest_and_backup_path_rejected(self) -> None:
        with patch("sys.stderr", new_callable=StringIO):
            with self.assertRaises(SystemExit) as cm:
                _run_cli([
                    "--latest", "--backup-path", "x.db",
                    "--live-db", "events.db",
                ])
        self.assertEqual(cm.exception.code, 2)


class TestCliExplicitBackupPath(_Base):
    def test_emits_top_level_keys_in_json(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        rc, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_KEYS:
            self.assertIn(key, body, f"missing JSON key: {key}")
        self.assertTrue(body["ok"])
        self.assertEqual(body["backup_path"],  backup)
        self.assertEqual(body["live_db_path"], live)

    def test_text_output_lists_status(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        rc, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
        ])
        self.assertEqual(rc, 0)
        self.assertIn("OK", output)
        self.assertIn("Backup:",  output)
        self.assertIn("Live DB:", output)


class TestCliLatestResolution(_Base):
    def test_latest_picks_newest_file(self) -> None:
        backups = self._make_backups_dir([
            "events-20260101T000000.db",
            "events-20260601T000000.db",
            "events-20260301T000000.db",
        ])
        live = self._track(_make_events_db())
        rc, output = _run_cli([
            "--latest",
            "--backups-dir", backups,
            "--live-db",     live,
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertTrue(body["backup_path"].endswith(
            "events-20260601T000000.db",
        ))

    def test_latest_with_empty_dir_exits_non_zero(self) -> None:
        backups = self._make_backups_dir([])
        live = self._track(_make_events_db())
        with patch("sys.stderr", new_callable=StringIO):
            rc, _ = _run_cli([
                "--latest",
                "--backups-dir", backups,
                "--live-db",     live,
                "--json",
            ])
        self.assertNotEqual(rc, 0)


class TestCliExitCodes(_Base):
    def test_exit_zero_on_matching_dbs(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        rc, _ = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
            "--json",
        ])
        self.assertEqual(rc, 0)

    def test_exit_nonzero_on_schema_drift(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db(extra_cols=("new_col",)))
        rc, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
            "--json",
        ])
        self.assertNotEqual(rc, 0)
        body = json.loads(output)
        self.assertFalse(body["ok"])
        self.assertTrue(body["errors"])


class TestCliKeepTemp(_Base):
    def test_keep_temp_returns_existing_path(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        rc, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
            "--keep-temp",
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        path = body["temp_backup_path"]
        self.assertIsInstance(path, str)
        self.assertTrue(os.path.isfile(path),
                        f"temp file missing: {path}")
        # Track the temp dir for cleanup.
        self._tmp_paths.append(os.path.dirname(path))

    def test_default_temp_field_is_none(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        _, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
            "--json",
        ])
        body = json.loads(output)
        self.assertIsNone(body["temp_backup_path"])


class TestCliText(_Base):
    def test_text_lists_warnings_when_drift_exceeds_threshold(self) -> None:
        backup = self._track(_make_events_db())
        live   = self._track(_make_events_db())
        # Seed disparate row counts to exceed the 5% warn threshold.
        for path, count in ((backup, 100), (live, 110)):
            conn = sqlite3.connect(path)
            try:
                for _ in range(count):
                    conn.execute(
                        "INSERT INTO events "
                        "(timestamp, headline, stage, persistence, "
                        " market_tickers, event_date) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        ("2026-04-15T13:30:00",
                         f"H {uuid.uuid4().hex[:8]}",
                         "realized", "medium", "[]", "2026-04-15"),
                    )
                conn.commit()
            finally:
                conn.close()
        rc, output = _run_cli([
            "--backup-path", backup,
            "--live-db",     live,
        ])
        self.assertEqual(rc, 0)
        self.assertIn("Warnings:", output)
        self.assertIn("row-count drift", output)


class TestCliNoForbiddenSeams(unittest.TestCase):
    def test_cli_module_carries_no_router_or_app(self) -> None:
        for forbidden in (
            "fastapi", "router", "app",
            "yfinance", "market_check", "market_data",
            "anthropic", "openai",
        ):
            self.assertFalse(
                hasattr(cli, forbidden),
                f"cli module carries '{forbidden}'",
            )


if __name__ == "__main__":
    unittest.main()
