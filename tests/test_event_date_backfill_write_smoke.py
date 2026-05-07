"""Tests for ``scripts/event_date_backfill_write_smoke.py``.

Operates entirely on temp DB fixtures.  Pins:

* Happy path: dry-run → apply → second apply → dry-run produces the
  expected before/write/after/idempotency counts.
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

from scripts import event_date_backfill_write_smoke as smoke  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builders — no dependency on ``db.save_event``; the events
# schema we touch is small enough to construct by hand.
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
    ticker      TEXT,
    date        TEXT,
    close       REAL,
    PRIMARY KEY (ticker, date)
)
""".strip()


def _seed_backup(
    path: Path,
    *,
    null_parseable: int = 2,
    null_unparseable: int = 1,
    already_dated: int = 1,
) -> None:
    """Build a SQLite events archive at ``path`` with a known mix of
    rows: NULL event_date with parseable timestamps, NULL with
    malformed timestamps, and rows that already carry an event_date."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_EVENTS_DDL)
        conn.execute(_PRICE_CACHE_DDL)

        for i in range(null_parseable):
            conn.execute(
                "INSERT INTO events "
                "(headline, event_date, timestamp, market_tickers) "
                "VALUES (?, NULL, ?, ?)",
                (
                    f"hl-null-parseable-{i}",
                    f"2026-04-{15 + i:02d}T13:30:00",
                    json.dumps([{"symbol": "AAPL"}, {"symbol": "MSFT"}]),
                ),
            )
        for i in range(null_unparseable):
            conn.execute(
                "INSERT INTO events "
                "(headline, event_date, timestamp, market_tickers) "
                "VALUES (?, NULL, ?, ?)",
                (
                    f"hl-null-bad-{i}",
                    "not-a-date",
                    json.dumps([{"symbol": "GOOG"}]),
                ),
            )
        for i in range(already_dated):
            conn.execute(
                "INSERT INTO events "
                "(headline, event_date, timestamp, market_tickers) "
                "VALUES (?, ?, ?, ?)",
                (
                    f"hl-dated-{i}",
                    "2025-01-01",
                    "2025-01-01T00:00:00",
                    json.dumps([{"symbol": "TSLA"}]),
                ),
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


# ---------------------------------------------------------------------------
# Test base — isolated tmp dir per test
# ---------------------------------------------------------------------------


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.mkdtemp(prefix="test_evb_smoke_")
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


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSmokeHappyPath(_Base):
    def test_run_returns_ok_on_seeded_backup(self) -> None:
        backup = self._make_backup()
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        self.assertTrue(
            result["ok"],
            f"errors: {result['errors']}, warnings: {result['warnings']}",
        )

    def test_before_counts_match_seeded_candidates(self) -> None:
        # 2 parseable + 1 unparseable = 3 NULL-event_date rows total.
        backup = self._make_backup(
            null_parseable=2, null_unparseable=1, already_dated=1,
        )
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        self.assertEqual(result["before"]["total_candidates"], 3)
        # 2 parseable (2 tickers each) + 1 unparseable (1 ticker) = 5
        self.assertEqual(result["before"]["ticker_rows_blocked"], 5)

    def test_write_applied_count_matches_parseable_candidates(self) -> None:
        backup = self._make_backup(
            null_parseable=2, null_unparseable=1, already_dated=1,
        )
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        self.assertEqual(result["write"]["applied_count"], 2)

    def test_after_counts_drop_to_unparseable_remainder(self) -> None:
        backup = self._make_backup(
            null_parseable=2, null_unparseable=1, already_dated=1,
        )
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        # The unparseable rows still count as candidates (NULL
        # event_date + non-empty timestamp), but the planner can't
        # propose them — they remain in total_candidates.
        self.assertEqual(result["after"]["total_candidates"], 1)
        self.assertEqual(result["after"]["ticker_rows_blocked"], 1)

    def test_idempotency_second_apply_writes_zero(self) -> None:
        backup = self._make_backup()
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        self.assertEqual(
            result["idempotency"]["idempotent_second_apply_count"], 0,
        )
        self.assertTrue(result["idempotency"]["ok"])

    def test_zero_candidate_backup_is_ok_with_zero_applied(self) -> None:
        # Only already-dated rows; nothing for the writer to do.
        backup = self._make_backup(
            null_parseable=0, null_unparseable=0, already_dated=2,
        )
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["before"]["total_candidates"], 0)
        self.assertEqual(result["write"]["applied_count"],     0)
        self.assertEqual(result["after"]["total_candidates"],  0)
        self.assertEqual(
            result["idempotency"]["idempotent_second_apply_count"], 0,
        )


# ---------------------------------------------------------------------------
# Required output shape
# ---------------------------------------------------------------------------


class TestPayloadShape(_Base):
    def test_result_has_required_top_level_keys(self) -> None:
        backup = self._make_backup()
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )
        for key in (
            "ok",
            "backup_path",
            "temp_copy_path",
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
        result = smoke.run_write_smoke(
            backup_path=backup,
            live_db_path=str(self._live_db),
        )

        self.assertTrue(result["ok"])
        self.assertTrue(result["live_db_unchanged"])
        self.assertEqual(_hash_file(self._live_db),    before_hash)
        self.assertEqual(self._live_db.stat().st_mtime, before_mtime)

    def test_absent_live_db_yields_warning_and_skipped_flag(self) -> None:
        # Don't create the sentinel — the live_db_path simply doesn't
        # exist.  The probe must surface a warning and run cleanly.
        backup = self._make_backup()
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

        original_planner = smoke.plan_event_date_backfill
        call_count = {"n": 0}

        def cheating_planner(*, db_path=None):
            call_count["n"] += 1
            # The probe calls the planner twice (before + after).  We
            # tamper between the two snapshots.
            if call_count["n"] == 2:
                live_path.write_bytes(b"tampered-bytes")
            return original_planner(db_path=db_path)

        with patch.object(
            smoke, "plan_event_date_backfill", side_effect=cheating_planner,
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
        # live_db absent before; if anything creates it during the run
        # the probe must flag it.
        live_path = self._live_db
        backup    = self._make_backup()

        original_planner = smoke.plan_event_date_backfill
        call_count = {"n": 0}

        def creating_planner(*, db_path=None):
            call_count["n"] += 1
            if call_count["n"] == 2:
                live_path.write_bytes(b"appeared-out-of-nowhere")
            return original_planner(db_path=db_path)

        with patch.object(
            smoke, "plan_event_date_backfill", side_effect=creating_planner,
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
        result = smoke.run_write_smoke(
            backup_path=bogus,
            live_db_path=str(self._live_db),
        )
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])

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
            result = smoke.run_write_smoke(
                backup_path=backup,
                live_db_path=str(self._live_db),
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["write"]["applied_count"], 2)

    def test_module_does_not_carry_fastapi_app_or_router(self) -> None:
        self.assertFalse(hasattr(smoke, "app"))
        self.assertFalse(hasattr(smoke, "router"))

    def test_running_does_not_import_fastapi_routes(self) -> None:
        # Order-independent guard.  Earlier suites in the same process
        # (e.g. ``tests.test_diagnostics``) legitimately import
        # ``routes.diagnostics`` and ``api`` and leave them in
        # ``sys.modules``; a snapshot-style ``assertNotIn`` would then
        # fire on cached state the smoke flow never touched.
        #
        # Two complementary signals catch a real regression instead:
        #   1. ``builtins.__import__`` is instrumented for the duration
        #      of ``run_write_smoke`` so any actual import statement
        #      targeting ``api`` / ``routes`` / ``routes.*`` (including
        #      ``from routes import diagnostics``) is recorded — this
        #      catches violations even when the target is already
        #      cached, because Python still routes through __import__.
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
            # ``from routes import diagnostics`` calls __import__ with
            # name="routes" and fromlist=("diagnostics",); record the
            # resolved submodule so the guard doesn't slip through.
            if name == "routes":
                for sub in fromlist or ():
                    forbidden_imports.append(f"routes.{sub}")
            return real_import(name, globals, locals, fromlist, level)

        backup = self._make_backup()
        before_modules = set(sys.modules.keys())
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

    def test_cli_valid_backup_exits_zero(self) -> None:
        backup = self._make_backup()
        rc, _ = self._run_cli([
            "--backup-path", str(backup),
            "--live-db",     str(self._live_db),
        ])
        self.assertEqual(rc, 0)

    def test_cli_missing_backup_exits_nonzero(self) -> None:
        ghost = self._backup_dir / "missing.db"
        rc, _ = self._run_cli([
            "--backup-path", str(ghost),
            "--live-db",     str(self._live_db),
        ])
        self.assertNotEqual(rc, 0)

    def test_cli_json_output_carries_required_keys(self) -> None:
        backup = self._make_backup()
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
