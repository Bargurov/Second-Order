"""Tests for ``scripts/auto_adjust_mismatch_repair_write_smoke.py``.

Operates entirely on temp DB fixtures.  Pins:

* Writer-absent path (synthetic, simulated by patching the
  ``_load_writer`` seam to raise ImportError): the smoke surfaces a
  clean ``writer not implemented yet`` error AND still runs the
  load-bearing ``live events.db`` hash + mtime check.  This pin
  protects the smoke against a future refactor that removes or
  renames the writer module.
* Happy path: with the writer's lazy seam swapped to a fake, dry-run
  → apply → second apply → dry-run produces the expected
  before/write/after/idempotency counts.
* Live ``events.db`` byte-equality (hash + mtime) is enforced; a
  modification between snapshots is captured as an error.
* ``--latest`` resolves the newest ``events-*.db`` in the backup
  directory; missing/corrupt/non-existent paths surface clean errors.
* Aggregator never invokes a provider/yfinance/LLM/FastAPI seam.
* CLI flags ``--backup-path`` and ``--latest`` are mutually exclusive
  and one is required; JSON output carries every required key.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import auto_adjust_mismatch_repair_write_smoke as smoke  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — minimal events + price_cache schema, the two
# tables the smoke pre-flight requires.  Keyed identically to the
# production schema so a future writer can read the seeded state with
# no special-casing.
# ---------------------------------------------------------------------------


_EVENTS_DDL = """
CREATE TABLE events (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    headline       TEXT,
    event_date     TEXT,
    timestamp      TEXT,
    market_tickers TEXT
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


def _seed_backup(
    path: Path,
    *,
    mismatch_rows: int = 3,
    paired_rows: int = 1,
) -> None:
    """Build a SQLite events archive at ``path`` with a known mix:
    ``mismatch_rows`` rows present only at ``auto_adjust=1`` (these
    are what a future writer would repair), and ``paired_rows`` rows
    present at both flags (these must be left alone)."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)
        conn.execute(
            "INSERT INTO events "
            "(headline, event_date, timestamp, market_tickers) "
            "VALUES (?, ?, ?, ?)",
            (
                "mismatch repair candidate",
                "2026-01-05",
                "2026-01-05T13:30:00",
                json.dumps([{"symbol": "AAPL"}]),
            ),
        )
        for i in range(mismatch_rows):
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "AAPL",
                    f"2026-02-{2 + i:02d}",
                    180.0 + i,
                    1000,
                    1,
                    "2026-02-02T20:00:00Z",
                ),
            )
        for i in range(paired_rows):
            ds = f"2026-03-{2 + i:02d}"
            for flag in (0, 1):
                conn.execute(
                    "INSERT INTO price_cache "
                    "(ticker, date, close, volume, auto_adjust, fetched_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    ("AAPL", ds, 200.0 + i, 1000, flag, "2026-03-02T20:00:00Z"),
                )
        conn.commit()
    finally:
        conn.close()


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_mismatches(db_path: Path) -> int:
    """Count price_cache rows present at auto_adjust=1 with no
    auto_adjust=0 counterpart for the same (ticker, date).

    Connections are explicitly closed (rather than relying on
    ``with sqlite3.connect(...)``, which only commits/rollbacks) so
    Windows releases the file handle before the smoke runner tries
    to ``unlink`` the temp copy.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM price_cache p1 "
            "WHERE p1.auto_adjust = 1 AND NOT EXISTS ("
            "  SELECT 1 FROM price_cache p2 "
            "  WHERE p2.ticker = p1.ticker AND p2.date = p1.date "
            "    AND p2.auto_adjust = 0"
            ")"
        ).fetchone()[0]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fake writer — exercised by tests via the lazy seam.
#
# The real writer module ``auto_adjust_mismatch_repair`` does not exist
# yet (see ``tests/test_auto_adjust_mismatch_repair_contract.py``).  The
# fake below is just enough writer behaviour for the smoke
# orchestration to be exercised end-to-end: count mismatches via
# ``_count_mismatches``; apply deletes them in one transaction.  Tests
# that need a different behaviour (e.g. always-zero) build their own
# fakes inline.
# ---------------------------------------------------------------------------


def _fake_plan(*, db_path: str) -> dict:
    n = _count_mismatches(Path(db_path))
    return {"total_mismatches": n, "repairable_count": n}


def _fake_apply(*, db_path: str, confirm: bool, backup_path: str) -> dict:
    if not confirm:
        return {"applied_count": 0, "audit_log_path": None}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT ticker, date FROM price_cache p1 "
            "WHERE p1.auto_adjust = 1 AND NOT EXISTS ("
            "  SELECT 1 FROM price_cache p2 "
            "  WHERE p2.ticker = p1.ticker AND p2.date = p1.date "
            "    AND p2.auto_adjust = 0"
            ")"
        )
        rows = cur.fetchall()
        for ticker, date_str in rows:
            conn.execute(
                "DELETE FROM price_cache "
                "WHERE ticker = ? AND date = ? AND auto_adjust = 1",
                (ticker, date_str),
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "applied_count":  len(rows),
        "audit_log_path": str(backup_path) + ".audit.jsonl",
    }


# ---------------------------------------------------------------------------
# Test base — isolated tmp dir per test
# ---------------------------------------------------------------------------


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="test_aa_repair_smoke_")
        self._tmp_root  = Path(self._td)
        self._backup_dir = self._tmp_root / "backups"
        self._backup_dir.mkdir()
        self._live_db = self._tmp_root / "events.db"

    def tearDown(self) -> None:
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

    def _make_backup(
        self,
        name: str = "events-20260507T120000.db",
        **kwargs,
    ) -> Path:
        path = self._backup_dir / name
        _seed_backup(path, **kwargs)
        return path

    def _make_live_db_sentinel(self, content: bytes = b"live-sentinel") -> Path:
        self._live_db.write_bytes(content)
        return self._live_db

    def _patched_writer(self):
        """Context manager that swaps the lazy writer seam for the
        fake plan/apply pair defined above."""
        return patch.object(
            smoke, "_load_writer",
            return_value=(_fake_plan, _fake_apply),
        )


# ---------------------------------------------------------------------------
# Not-yet-implemented path — the writer module is absent today; the
# smoke must still surface a clean error and verify live DB safety.
# ---------------------------------------------------------------------------


class TestWriterAbsent(_Base):
    """Synthetic writer-absent path: simulate a future refactor that
    removes or renames the writer by patching ``_load_writer`` to raise
    ImportError.  Each test pins one fail-safe behaviour the smoke
    runner must surface in that case."""

    def _writer_absent(self):
        return patch.object(
            smoke, "_load_writer",
            side_effect=ImportError(
                "No module named 'auto_adjust_mismatch_repair'",
            ),
        )

    def test_run_marks_failed_with_clean_error(self) -> None:
        backup = self._make_backup()
        with self._writer_absent():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("writer not implemented yet" in e for e in result["errors"]),
            f"expected not-implemented error, got {result['errors']}",
        )

    def test_live_db_hash_check_still_runs_when_writer_absent(self) -> None:
        # Live DB safety is the load-bearing invariant of this probe.
        # Even when the writer is missing, the hash must be checked so
        # an operator can tell "writer absent" apart from "writer
        # absent + something else mutated the live DB."
        self._make_live_db_sentinel(b"live-bytes-must-not-change")
        before_hash = _hash_file(self._live_db)
        backup = self._make_backup()

        with self._writer_absent():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )

        self.assertTrue(result["live_db_unchanged"])
        self.assertEqual(_hash_file(self._live_db), before_hash)

    def test_no_temp_copy_created_on_writer_absent_path(self) -> None:
        # When the writer is missing the smoke short-circuits before
        # the temp copy is created — so the temp_copy_path slot stays
        # None.  This keeps the not-yet-implemented path a true no-op
        # against the filesystem.
        backup = self._make_backup()
        with self._writer_absent():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertIsNone(result["temp_copy_path"])


# ---------------------------------------------------------------------------
# Happy path — writer seam swapped to the fake plan/apply pair.
# ---------------------------------------------------------------------------


class TestSmokeHappyPath(_Base):

    def test_run_returns_ok_on_seeded_backup(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertTrue(
            result["ok"],
            f"errors: {result['errors']}, warnings: {result['warnings']}",
        )

    def test_before_counts_match_seeded_mismatches(self) -> None:
        # 3 mismatch rows + 1 paired row → planner sees 3 mismatches.
        backup = self._make_backup(mismatch_rows=3, paired_rows=1)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertEqual(result["before"]["total_mismatches"], 3)
        self.assertEqual(result["before"]["repairable_count"], 3)

    def test_write_applied_count_matches_mismatch_rows(self) -> None:
        backup = self._make_backup(mismatch_rows=3, paired_rows=1)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertEqual(result["write"]["applied_count"], 3)

    def test_after_counts_drop_to_zero(self) -> None:
        backup = self._make_backup(mismatch_rows=3, paired_rows=1)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertEqual(result["after"]["total_mismatches"], 0)
        self.assertEqual(result["after"]["repairable_count"], 0)

    def test_idempotency_second_apply_writes_zero(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertEqual(
            result["idempotency"]["idempotent_second_apply_count"], 0,
        )
        self.assertTrue(result["idempotency"]["ok"])

    def test_zero_mismatch_backup_is_ok_with_zero_applied(self) -> None:
        backup = self._make_backup(mismatch_rows=0, paired_rows=2)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["before"]["total_mismatches"], 0)
        self.assertEqual(result["write"]["applied_count"],     0)
        self.assertEqual(result["after"]["total_mismatches"],  0)
        self.assertEqual(
            result["idempotency"]["idempotent_second_apply_count"], 0,
        )


# ---------------------------------------------------------------------------
# Required output shape
# ---------------------------------------------------------------------------


class TestPayloadShape(_Base):

    def test_result_has_required_top_level_keys(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        for key in (
            "ok",
            "backup_path",
            "temp_copy_path",
            "live_db_path",
            "live_db_unchanged",
            "before",
            "write",
            "after",
            "idempotency",
            "warnings",
            "errors",
        ):
            self.assertIn(key, result, f"missing key: {key}")

    def test_temp_copy_path_is_distinct_from_backup(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertNotEqual(
            Path(result["temp_copy_path"]).resolve(),
            Path(result["backup_path"]).resolve(),
        )

    def test_temp_copy_is_cleaned_after_run(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertFalse(
            Path(result["temp_copy_path"]).exists(),
            "temp copy must not survive the smoke run",
        )

    def test_idempotency_section_carries_count_and_ok(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        idem = result["idempotency"]
        self.assertIn("idempotent_second_apply_count", idem)
        self.assertIn("ok", idem)


# ---------------------------------------------------------------------------
# Live events.db byte-equality safety
# ---------------------------------------------------------------------------


class TestLiveDBSafety(_Base):

    def test_existing_live_db_is_byte_equal_after_run(self) -> None:
        self._make_live_db_sentinel(b"live-bytes-must-not-change")
        before_hash  = _hash_file(self._live_db)
        before_mtime = self._live_db.stat().st_mtime

        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["live_db_unchanged"])
        self.assertEqual(_hash_file(self._live_db),    before_hash)
        self.assertEqual(self._live_db.stat().st_mtime, before_mtime)

    def test_absent_live_db_yields_warning_and_skipped_flag(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )
        self.assertTrue(result["ok"])
        self.assertIsNone(result["live_db_unchanged"])
        self.assertTrue(
            any("not found" in w for w in result["warnings"]),
            f"expected not-found warning, got {result['warnings']}",
        )

    def test_live_db_modified_during_run_is_error(self) -> None:
        # Patch the planner to mutate the sentinel mid-run; the probe
        # must catch the change in the post-run hash check.
        self._make_live_db_sentinel(b"original-bytes")
        live_path = self._live_db
        backup    = self._make_backup()

        call_count = {"n": 0}

        def cheating_plan(*, db_path):
            call_count["n"] += 1
            # The smoke calls the planner twice (before + after); we
            # tamper between the two snapshots.
            if call_count["n"] == 2:
                live_path.write_bytes(b"tampered-bytes")
            return _fake_plan(db_path=db_path)

        with patch.object(
            smoke, "_load_writer",
            return_value=(cheating_plan, _fake_apply),
        ):
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(live_path),
            )

        self.assertFalse(result["ok"])
        self.assertFalse(result["live_db_unchanged"])
        self.assertTrue(
            any("changed during run" in e for e in result["errors"]),
            f"expected changed-during-run error, got {result['errors']}",
        )

    def test_live_db_created_during_run_is_error(self) -> None:
        live_path = self._live_db
        backup    = self._make_backup()

        call_count = {"n": 0}

        def creating_plan(*, db_path):
            call_count["n"] += 1
            if call_count["n"] == 2:
                live_path.write_bytes(b"appeared-out-of-nowhere")
            return _fake_plan(db_path=db_path)

        with patch.object(
            smoke, "_load_writer",
            return_value=(creating_plan, _fake_apply),
        ):
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(live_path),
            )

        self.assertFalse(result["ok"])
        self.assertFalse(result["live_db_unchanged"])
        self.assertTrue(
            any("created during run" in e for e in result["errors"]),
            f"expected created-during-run error, got {result['errors']}",
        )

    def test_live_db_unchanged_under_writer_apply(self) -> None:
        # End-to-end pin: even a writer that legitimately mutates the
        # temp copy (the fake apply deletes mismatch rows) must leave
        # the live events.db byte-identical.  This is the load-bearing
        # contract the runbook reads against.
        self._make_live_db_sentinel(b"production-bytes")
        before_hash  = _hash_file(self._live_db)
        before_mtime = self._live_db.stat().st_mtime

        backup = self._make_backup(mismatch_rows=3, paired_rows=1)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["write"]["applied_count"], 3)
        self.assertEqual(_hash_file(self._live_db),    before_hash)
        self.assertEqual(self._live_db.stat().st_mtime, before_mtime)


# ---------------------------------------------------------------------------
# Backup resolution and error paths
# ---------------------------------------------------------------------------


class TestBackupResolution(_Base):

    def test_missing_backup_path_is_error(self) -> None:
        ghost = self._backup_dir / "does-not-exist.db"
        result = smoke.run_write_smoke(
            backup_path=ghost,
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("does not exist" in e for e in result["errors"]))

    def test_directory_path_is_error(self) -> None:
        result = smoke.run_write_smoke(
            backup_path=self._backup_dir,
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any("not a file" in e for e in result["errors"]))

    def test_corrupt_backup_is_error(self) -> None:
        bogus = self._backup_dir / "events-corrupt.db"
        bogus.write_bytes(b"not a sqlite database " * 64)
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=bogus,
                live_db_path=str(self._live_db),
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

    def test_backup_missing_price_cache_table_is_error(self) -> None:
        # The auto-adjust repair smoke also requires ``price_cache``;
        # an events-only backup must be rejected so the smoke does not
        # report a false-clean run against an unusable snapshot.
        path = self._backup_dir / "events-cacheless.db"
        conn = sqlite3.connect(str(path))
        try:
            conn.execute(_EVENTS_DDL)
            conn.commit()
        finally:
            conn.close()
        with self._patched_writer():
            result = smoke.run_write_smoke(
                backup_path=path,
                live_db_path=str(self._live_db),
            )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("price_cache" in e for e in result["errors"]),
            f"expected price_cache-missing error, got {result['errors']}",
        )

    def test_neither_path_nor_latest_is_error(self) -> None:
        result = smoke.run_write_smoke(
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("must provide" in e for e in result["errors"]),
        )

    def test_path_and_latest_mutually_exclusive(self) -> None:
        backup = self._make_backup()
        result = smoke.run_write_smoke(
            backup_path=backup,
            use_latest=True,
            backup_dir=str(self._backup_dir),
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("mutually exclusive" in e for e in result["errors"]),
        )

    def test_latest_picks_newest_in_backup_dir(self) -> None:
        old = self._make_backup("events-20260101T000000.db")
        new = self._make_backup("events-20260507T120000.db")
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_900_000_000, 1_900_000_000))
        with self._patched_writer():
            result = smoke.run_write_smoke(
                use_latest=True,
                backup_dir=str(self._backup_dir),
                live_db_path=str(self._live_db),
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["backup_path"], str(new))

    def test_latest_with_no_backups_is_error(self) -> None:
        result = smoke.run_write_smoke(
            use_latest=True,
            backup_dir=str(self._backup_dir),
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(
            any("no events-" in e for e in result["errors"]),
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Base):

    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        backup = self._make_backup()

        candidate_seams = (
            ("market_check", "_fetch"),
            ("market_check", "_fetch_since"),
            ("market_check", "market_check"),
            ("market_check", "_check_one_ticker"),
            ("market_data",  "get_provider"),
            ("market_data",  "reload_provider_from_env"),
            ("price_cache",  "fetch_daily_cached"),
            ("analyze_event",      "analyze_event"),
            ("auto_backfill_runner", "execute_paid_candidate"),
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
                        f"write smoke must not call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "write smoke must not call yfinance",
                    ),
                ))
            except ImportError:
                pass
            stack.enter_context(self._patched_writer())
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["write"]["applied_count"], 3)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(smoke, "app"))
        self.assertFalse(hasattr(smoke, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard.  Earlier suites in the same process
        # legitimately import ``routes.diagnostics`` and ``api`` and
        # leave them in ``sys.modules``; a snapshot-style ``assertNotIn``
        # would then fire on cached state the smoke flow never touched.
        #
        # Two complementary signals catch a real regression instead:
        #   1. ``builtins.__import__`` is instrumented so any actual
        #      import statement targeting ``api`` / ``routes`` /
        #      ``routes.*`` (including ``from routes import x``) is
        #      recorded — this catches violations even when the target
        #      is already cached, because Python still routes through
        #      __import__.
        #   2. A ``sys.modules`` delta around the call catches the rare
        #      paths that bypass __import__ (e.g. ``importlib.util``).
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

        backup = self._make_backup()
        before_modules = set(sys.modules.keys())
        with self._patched_writer():
            with patch("builtins.__import__", side_effect=tracing_import):
                smoke.run_write_smoke(
                    backup_path=backup,
                    live_db_path=str(self._live_db),
                )
        new_modules = set(sys.modules.keys()) - before_modules
        newly_loaded_forbidden = sorted(
            m for m in new_modules if _is_forbidden(m)
        )

        self.assertEqual(
            forbidden_imports, [],
            "run_write_smoke performed forbidden imports during the "
            f"call: {forbidden_imports}",
        )
        self.assertEqual(
            newly_loaded_forbidden, [],
            "run_write_smoke loaded forbidden modules into "
            f"sys.modules: {newly_loaded_forbidden}",
        )


# ---------------------------------------------------------------------------
# Lazy-seam contract — pin the resolution rules for ``_load_writer``
# even before the writer module ships so tests catch a future shape
# regression on the seam itself.
# ---------------------------------------------------------------------------


class TestLoadWriterSeam(_Base):

    def test_load_writer_raises_when_module_unimportable(self) -> None:
        # Simulate a future refactor that removes or renames the writer
        # module: pop it from ``sys.modules`` and intercept the next
        # ``importlib.import_module`` call so the import truly fails.
        # ``_load_writer`` must surface the absence as an ImportError
        # so the smoke runner's not-yet-implemented branch fires.
        import importlib
        import sys as _sys

        saved = _sys.modules.pop("auto_adjust_mismatch_repair", None)
        real = importlib.import_module

        def _failing(name, *args, **kwargs):
            if name == "auto_adjust_mismatch_repair":
                raise ModuleNotFoundError(
                    "No module named 'auto_adjust_mismatch_repair'",
                )
            return real(name, *args, **kwargs)

        try:
            with patch.object(importlib, "import_module", _failing):
                with self.assertRaises(ImportError):
                    smoke._load_writer()
        finally:
            if saved is not None:
                _sys.modules["auto_adjust_mismatch_repair"] = saved

    def test_load_writer_rejects_module_missing_apply_callable(self) -> None:
        # If a future regression ships a writer module with the planner
        # but no apply function, ``_load_writer`` must still fail loudly
        # rather than silently returning a half-shaped pair.  We
        # override the cached module entry in ``sys.modules`` so the
        # next ``import_module`` call returns our deliberately-incomplete
        # fake; afterward we restore the original entry.
        import sys as _sys
        import types

        fake = types.ModuleType("auto_adjust_mismatch_repair")
        fake.plan_auto_adjust_mismatch_repair = lambda **kw: {}
        # apply intentionally missing

        saved = _sys.modules.get("auto_adjust_mismatch_repair")
        _sys.modules["auto_adjust_mismatch_repair"] = fake
        try:
            with self.assertRaises(ImportError):
                smoke._load_writer()
        finally:
            if saved is not None:
                _sys.modules["auto_adjust_mismatch_repair"] = saved
            else:
                _sys.modules.pop("auto_adjust_mismatch_repair", None)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------


class TestCli(_Base):

    def _run_cli(self, argv: list[str]) -> tuple[int, str]:
        out = StringIO()
        try:
            rc = smoke.main(argv, out=out)
        except SystemExit as exc:
            rc = exc.code
        return rc, out.getvalue()

    def test_cli_valid_backup_with_writer_exits_zero(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            rc, _ = self._run_cli([
                "--backup-path", str(backup),
                "--live-db",     str(self._live_db),
            ])
        self.assertEqual(rc, 0)

    def test_cli_writer_absent_exits_nonzero_with_clean_message(self) -> None:
        # Simulate writer-absent the same way ``TestWriterAbsent`` does,
        # so the CLI surface (exit code, JSON shape) is pinned for the
        # not-yet-implemented branch as well as the in-process API.
        backup = self._make_backup()
        with patch.object(
            smoke, "_load_writer",
            side_effect=ImportError(
                "No module named 'auto_adjust_mismatch_repair'",
            ),
        ):
            rc, output = self._run_cli([
                "--backup-path", str(backup),
                "--live-db",     str(self._live_db),
                "--json",
            ])
        self.assertEqual(rc, 1)
        body = json.loads(output)
        self.assertFalse(body["ok"])
        self.assertTrue(
            any("writer not implemented yet" in e for e in body["errors"]),
        )

    def test_cli_missing_backup_exits_nonzero(self) -> None:
        ghost = self._backup_dir / "missing.db"
        rc, _ = self._run_cli([
            "--backup-path", str(ghost),
            "--live-db",     str(self._live_db),
        ])
        self.assertNotEqual(rc, 0)

    def test_cli_json_output_carries_required_keys(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            rc, output = self._run_cli([
                "--backup-path", str(backup),
                "--live-db",     str(self._live_db),
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in (
            "ok",
            "backup_path",
            "temp_copy_path",
            "live_db_path",
            "live_db_unchanged",
            "before",
            "write",
            "after",
            "idempotency",
            "warnings",
            "errors",
        ):
            self.assertIn(key, body, f"missing JSON key: {key}")

    def test_cli_text_output_summarises_each_stage(self) -> None:
        backup = self._make_backup()
        with self._patched_writer():
            rc, output = self._run_cli([
                "--backup-path", str(backup),
                "--live-db",     str(self._live_db),
            ])
        self.assertEqual(rc, 0)
        for needle in ("before", "write", "after", "idempotency"):
            self.assertIn(needle, output, f"missing stage line: {needle}")

    def test_cli_requires_path_or_latest(self) -> None:
        rc, _ = self._run_cli(["--live-db", str(self._live_db)])
        self.assertEqual(rc, 2)

    def test_cli_rejects_path_and_latest_together(self) -> None:
        backup = self._make_backup()
        rc, _ = self._run_cli([
            "--backup-path", str(backup),
            "--latest",
            "--live-db",     str(self._live_db),
        ])
        self.assertEqual(rc, 2)

    def test_cli_latest_picks_newest(self) -> None:
        old = self._make_backup("events-20260101T000000.db")
        new = self._make_backup("events-20260507T120000.db")
        os.utime(old, (1_700_000_000, 1_700_000_000))
        os.utime(new, (1_900_000_000, 1_900_000_000))
        with self._patched_writer():
            rc, output = self._run_cli([
                "--latest",
                "--backup-dir", str(self._backup_dir),
                "--live-db",   str(self._live_db),
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["backup_path"], str(new))


if __name__ == "__main__":
    unittest.main()
