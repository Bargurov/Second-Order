"""Tests for ``scripts/backup_restore_check.py``.

Covers the public API (``restore_check``, ``find_latest_backup``) and
the CLI (``main``).  Always operates on temp directories — never reads
or writes the repository's real ``events.db`` or ``backups/`` tree.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
import builtins
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import backup_restore_check as brc  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_backup(
    path: Path,
    *,
    events_rows: int = 2,
    cache_rows:  int = 2,
) -> None:
    """Write a SQLite DB at ``path`` with the required tables and
    optional row content."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(
            "CREATE TABLE events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "headline TEXT, "
            "event_date TEXT, "
            "timestamp TEXT)",
        )
        conn.execute(
            "CREATE TABLE price_cache ("
            "ticker TEXT, "
            "date TEXT, "
            "close REAL, "
            "PRIMARY KEY (ticker, date))",
        )
        for i in range(events_rows):
            conn.execute(
                "INSERT INTO events (headline, event_date, timestamp) "
                "VALUES (?, ?, ?)",
                (f"hl-{i}", "2026-04-15", "2026-04-15T12:00:00"),
            )
        for i in range(cache_rows):
            conn.execute(
                "INSERT INTO price_cache (ticker, date, close) "
                "VALUES (?, ?, ?)",
                (f"TICK{i}", f"2026-04-{(i % 28) + 1:02d}", 100.0 + i),
            )
        conn.commit()
    finally:
        conn.close()


def _make_backup_missing(
    path: Path,
    *,
    drop: str,
) -> None:
    """Create a valid backup, then drop the named required table."""
    _make_valid_backup(path)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(f"DROP TABLE {drop}")
        conn.commit()
    finally:
        conn.close()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Test base — isolated tmp dir per test
# ---------------------------------------------------------------------------


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="test_brc_")
        self._tmp_root = Path(self._td)
        self._backup_dir = self._tmp_root / "backups"
        self._backup_dir.mkdir()
        # Track temp copies created via cleanup=False so we can clean
        # them up if a test forgets to.
        self._extra_temp_paths: list[Path] = []

    def tearDown(self) -> None:
        for p in self._extra_temp_paths:
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
        # Best-effort recursive cleanup.
        for root, dirs, files in os.walk(self._tmp_root, topdown=False):
            for name in files:
                try:
                    Path(root, name).unlink()
                except OSError:
                    pass
            for name in dirs:
                try:
                    Path(root, name).rmdir()
                except OSError:
                    pass
        try:
            self._tmp_root.rmdir()
        except OSError:
            pass

    def _new_backup(self, name: str = "events-20260507T120000.db") -> Path:
        path = self._backup_dir / name
        _make_valid_backup(path)
        return path


# ---------------------------------------------------------------------------
# restore_check — happy path
# ---------------------------------------------------------------------------


class TestRestoreCheckValid(_Base):
    def test_valid_backup_returns_ok(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertTrue(
            result["ok"],
            f"expected ok=True, got errors={result['errors']}",
        )
        self.assertEqual(result["errors"], [])

    def test_valid_backup_records_table_counts(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertEqual(result["table_counts"], {
            "events":      2,
            "price_cache": 2,
        })

    def test_valid_backup_exposes_schema_preflight_shape(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertIn("events", result["tables"])
        self.assertIn("price_cache", result["tables"])
        self.assertTrue(result["price_cache_present"])
        self.assertIn("headline", result["events_columns"])

    def test_result_has_required_top_level_keys(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        for key in (
            "ok",
            "backup_path",
            "temp_copy_path",
            "table_counts",
            "warnings",
            "errors",
        ):
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_temp_copy_path_is_recorded(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertIsInstance(result["temp_copy_path"], str)
        self.assertNotEqual(result["temp_copy_path"], result["backup_path"])

    def test_backup_path_recorded_as_string(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertEqual(result["backup_path"], str(backup))


# ---------------------------------------------------------------------------
# restore_check — failure paths
# ---------------------------------------------------------------------------


class TestRestoreCheckErrors(_Base):
    def test_missing_events_table_is_error(self) -> None:
        backup = self._backup_dir / "events-bad-events.db"
        _make_backup_missing(backup, drop="events")
        result = brc.restore_check(backup_path=backup)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("events" in e for e in result["errors"]),
            f"expected events error, got {result['errors']}",
        )

    def test_missing_price_cache_table_is_error(self) -> None:
        backup = self._backup_dir / "events-bad-cache.db"
        _make_backup_missing(backup, drop="price_cache")
        result = brc.restore_check(backup_path=backup)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("price_cache" in e for e in result["errors"]),
            f"expected price_cache error, got {result['errors']}",
        )

    def test_zero_row_count_is_warning_not_error(self) -> None:
        backup = self._backup_dir / "events-empty-rows.db"
        _make_valid_backup(backup, events_rows=0, cache_rows=0)
        result = brc.restore_check(backup_path=backup)
        # Required tables present and readable → ok=True; empty
        # contents surface as warnings.
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_counts"], {
            "events":      0,
            "price_cache": 0,
        })
        warning_text = " | ".join(result["warnings"])
        self.assertIn("events", warning_text)
        self.assertIn("price_cache", warning_text)

    def test_nonexistent_path_is_error(self) -> None:
        ghost = self._backup_dir / "does-not-exist.db"
        result = brc.restore_check(backup_path=ghost)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("does not exist" in e for e in result["errors"]),
            f"expected not-found error, got {result['errors']}",
        )

    def test_directory_path_is_error(self) -> None:
        # Pointing at the backups dir itself should be rejected.
        result = brc.restore_check(backup_path=self._backup_dir)
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("not a file" in e for e in result["errors"]),
            f"expected not-a-file error, got {result['errors']}",
        )

    def test_corrupt_file_is_error(self) -> None:
        bogus = self._backup_dir / "events-corrupt.db"
        bogus.write_bytes(b"not a sqlite database " * 64)
        result = brc.restore_check(backup_path=bogus)
        self.assertFalse(result["ok"])
        self.assertTrue(
            result["errors"],
            "corrupt file must produce at least one error",
        )

    def test_empty_file_is_error(self) -> None:
        empty = self._backup_dir / "events-empty.db"
        empty.write_bytes(b"")
        result = brc.restore_check(backup_path=empty)
        # SQLite tolerates a 0-byte file as "empty database" — no
        # required tables → still an error.
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_neither_path_nor_latest_is_error(self) -> None:
        result = brc.restore_check()
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("must provide" in e for e in result["errors"]),
            f"expected guidance error, got {result['errors']}",
        )

    def test_path_and_latest_mutually_exclusive(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(
            backup_path=backup,
            use_latest=True,
            backup_dir=self._backup_dir,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("mutually exclusive" in e for e in result["errors"]),
            f"expected exclusivity error, got {result['errors']}",
        )


# ---------------------------------------------------------------------------
# --latest selection
# ---------------------------------------------------------------------------


class TestLatestSelection(_Base):
    def test_find_latest_picks_newest_by_mtime(self) -> None:
        old = self._backup_dir / "events-20260101T000000.db"
        new = self._backup_dir / "events-20260507T120000.db"
        _make_valid_backup(old)
        _make_valid_backup(new)
        # Force a deterministic age difference.
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_900_000_000, 1_900_000_000))
        latest = brc.find_latest_backup(self._backup_dir)
        self.assertEqual(latest, new)

    def test_find_latest_returns_none_when_dir_missing(self) -> None:
        ghost = self._tmp_root / "nope"
        self.assertIsNone(brc.find_latest_backup(ghost))

    def test_find_latest_returns_none_when_dir_empty(self) -> None:
        empty = self._tmp_root / "empty_dir"
        empty.mkdir()
        self.assertIsNone(brc.find_latest_backup(empty))

    def test_find_latest_ignores_non_matching_files(self) -> None:
        (self._backup_dir / "README.txt").write_text("not a backup")
        (self._backup_dir / "snapshot.sql").write_text("-- ddl")
        # Only the events-*.db file should win.
        winner = self._backup_dir / "events-20260507T120000.db"
        _make_valid_backup(winner)
        latest = brc.find_latest_backup(self._backup_dir)
        self.assertEqual(latest, winner)

    def test_restore_check_latest_uses_newest(self) -> None:
        old = self._backup_dir / "events-20260101T000000.db"
        new = self._backup_dir / "events-20260507T120000.db"
        _make_valid_backup(old)
        _make_valid_backup(new)
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_900_000_000, 1_900_000_000))
        result = brc.restore_check(
            use_latest=True,
            backup_dir=self._backup_dir,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["backup_path"], str(new))

    def test_restore_check_latest_with_no_backups_is_error(self) -> None:
        result = brc.restore_check(
            use_latest=True,
            backup_dir=self._backup_dir,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("no events-" in e for e in result["errors"]),
            f"expected no-backups error, got {result['errors']}",
        )

    def test_restore_check_latest_with_missing_dir_is_error(self) -> None:
        ghost = self._tmp_root / "nope"
        result = brc.restore_check(
            use_latest=True,
            backup_dir=ghost,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])


# ---------------------------------------------------------------------------
# Side-effect safety
# ---------------------------------------------------------------------------


class TestSideEffectSafety(_Base):
    def test_source_backup_is_not_modified(self) -> None:
        backup = self._new_backup()
        before_hash  = _hash_file(backup)
        before_mtime = backup.stat().st_mtime
        brc.restore_check(backup_path=backup)
        after_hash  = _hash_file(backup)
        after_mtime = backup.stat().st_mtime
        self.assertEqual(before_hash, after_hash,
                         "source backup bytes must not change")
        self.assertEqual(before_mtime, after_mtime,
                         "source backup mtime must not change")

    def test_does_not_touch_events_db_in_cwd(self) -> None:
        sentinel = self._tmp_root / "events.db"
        sentinel.write_bytes(b"sentinel-bytes-must-not-change")
        before_hash  = _hash_file(sentinel)
        before_mtime = sentinel.stat().st_mtime

        backup = self._new_backup()
        cwd = Path.cwd()
        try:
            os.chdir(self._tmp_root)
            brc.restore_check(backup_path=backup)
        finally:
            os.chdir(cwd)

        after_hash  = _hash_file(sentinel)
        after_mtime = sentinel.stat().st_mtime
        self.assertEqual(before_hash, after_hash,
                         "events.db must never be opened or written")
        self.assertEqual(before_mtime, after_mtime,
                         "events.db mtime must not change")

    def test_temp_copy_is_cleaned_by_default(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup)
        self.assertFalse(
            Path(result["temp_copy_path"]).exists(),
            "temp copy must be deleted when cleanup=True",
        )

    def test_temp_copy_is_kept_when_cleanup_false(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup, cleanup=False)
        tmp = Path(result["temp_copy_path"])
        self._extra_temp_paths.append(tmp)
        self.assertTrue(
            tmp.exists(),
            "temp copy must persist when cleanup=False",
        )

    def test_temp_copy_is_a_separate_file_from_source(self) -> None:
        backup = self._new_backup()
        result = brc.restore_check(backup_path=backup, cleanup=False)
        tmp = Path(result["temp_copy_path"])
        self._extra_temp_paths.append(tmp)
        self.assertNotEqual(
            tmp.resolve(), backup.resolve(),
            "temp copy must be a distinct file from the source",
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        backup = self._new_backup()

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
                        f"backup_restore_check must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "backup_restore_check must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            result = brc.restore_check(backup_path=backup)

        # Sanity: real composed result, not a fallback.
        self.assertTrue(result["ok"])
        self.assertEqual(result["table_counts"]["events"], 2)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(brc, "app"))
        self.assertFalse(hasattr(brc, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        backup = self._new_backup()
        real_import = builtins.__import__

        def guard_import(name, globals=None, locals=None, fromlist=(),
                         level=0):
            if name in {"api", "routes.diagnostics"}:
                raise AssertionError(
                    "backup_restore_check must not import FastAPI routes",
                )
            return real_import(name, globals, locals, fromlist, level)

        with patch("builtins.__import__", side_effect=guard_import):
            brc.restore_check(backup_path=backup)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class _CliBase(_Base):
    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = brc.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()


class TestCli(_CliBase):
    def test_cli_valid_backup_exits_zero(self) -> None:
        backup = self._new_backup()
        rc, _ = self._run_cli(["--backup-path", str(backup)])
        self.assertEqual(rc, 0)

    def test_cli_invalid_backup_exits_nonzero(self) -> None:
        bogus = self._backup_dir / "missing.db"
        rc, _ = self._run_cli(["--backup-path", str(bogus)])
        self.assertNotEqual(rc, 0)

    def test_cli_json_output_is_valid_json(self) -> None:
        backup = self._new_backup()
        rc, output = self._run_cli([
            "--backup-path", str(backup),
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in (
            "ok",
            "backup_path",
            "temp_copy_path",
            "table_counts",
            "warnings",
            "errors",
        ):
            self.assertIn(key, body)

    def test_cli_text_output_includes_required_fields(self) -> None:
        backup = self._new_backup()
        rc, output = self._run_cli(["--backup-path", str(backup)])
        self.assertEqual(rc, 0)
        for needle in (
            "backup_path",
            "temp_copy_path",
            "ok",
            "Table counts",
            "Warnings",
            "Errors",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")

    def test_cli_requires_path_or_latest(self) -> None:
        # argparse mutually-exclusive group is required → exit 2 with
        # no other args.
        rc, _ = self._run_cli([])
        self.assertEqual(rc, 2)

    def test_cli_rejects_path_and_latest_together(self) -> None:
        backup = self._new_backup()
        rc, _ = self._run_cli([
            "--backup-path", str(backup),
            "--latest",
        ])
        self.assertEqual(rc, 2)

    def test_cli_latest_picks_newest_in_backup_dir(self) -> None:
        old = self._backup_dir / "events-20260101T000000.db"
        new = self._backup_dir / "events-20260507T120000.db"
        _make_valid_backup(old)
        _make_valid_backup(new)
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_900_000_000, 1_900_000_000))
        rc, output = self._run_cli([
            "--latest",
            "--backup-dir", str(self._backup_dir),
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["backup_path"], str(new))

    def test_cli_keep_temp_preserves_temp_file(self) -> None:
        backup = self._new_backup()
        rc, output = self._run_cli([
            "--backup-path", str(backup),
            "--keep-temp",
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        tmp = Path(body["temp_copy_path"])
        self._extra_temp_paths.append(tmp)
        self.assertTrue(
            tmp.exists(),
            "--keep-temp must leave the temp copy on disk",
        )

    def test_cli_default_cleans_up_temp_file(self) -> None:
        backup = self._new_backup()
        rc, output = self._run_cli([
            "--backup-path", str(backup),
            "--json",
        ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        tmp = Path(body["temp_copy_path"])
        self.assertFalse(
            tmp.exists(),
            "without --keep-temp, temp copy must be deleted",
        )


if __name__ == "__main__":
    unittest.main()
