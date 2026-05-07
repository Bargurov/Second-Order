"""Tests for ``scripts/auto_adjust_repair_backup_delta_report.py``.

The report compares the live ``events.db`` against either an
operator-named backup (``--backup-path``) or the most recent
``backups/events-*.db`` snapshot (``--latest``).  Its purpose is to
explain the gap operators see in practice: a live dry-run of the
auto-adjust mismatch repair surfaces N planned writes, but the same
writer run against the latest backup may apply zero — because the
backup is a stale snapshot taken before the cache rows that triggered
the mismatch landed.

These tests pin:

  * The four counts (``mismatch_count``, ``preview_count``,
    ``planned_write_count``, ``repairable_count``) for live + backup
    and their per-field delta.
  * DB metadata (path, exists, size_bytes, mtime) for both sides.
  * Read-only contract — neither file is mutated across repeated runs
    (snapshot the BYTES, not just the mtime).
  * ``--latest`` picks max-mtime ``backups/events-*.db``; missing /
    empty directory yields ``backup.exists=False`` with
    ``delta=None``.
  * ``--backup-path`` wins over ``--latest`` when both are passed.
  * No provider / yfinance / LLM / FastAPI seam invoked.
  * JSON output is valid JSON with all documented top-level keys.
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
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-load to break the api ↔
                                #  routes.diagnostics cycle that the
                                #  report's lazy imports would
                                #  otherwise re-enter.
import db  # noqa: E402

from scripts import auto_adjust_repair_backup_delta_report as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classifier_patches(
    *,
    blocker_reason: str = "no_forward_20d_close",
    sub_reason: str = "auto_adjust_mismatch_for_20d",
) -> tuple:
    return (
        patch(
            "routes.diagnostics._classify_blocker_for_ticker",
            return_value=blocker_reason,
        ),
        patch(
            "routes.diagnostics._classify_no_forward_20d_subreason",
            return_value=sub_reason,
        ),
    )


def _seed_mismatches(db_path: str, count: int, *, prefix: str) -> None:
    """Plant ``count`` auto_adjust_mismatch_for_20d-shaped events into
    the named DB.  Each event lands its own ticker (``{prefix}{i}``)
    plus two aa=1 cache rows inside the [event_d, target_20d] window
    so the planner has two proposed inserts per event.
    """
    orig_path, orig_ready = db.DB_FILE, db._db_ready
    db.DB_FILE = db_path
    db._db_ready = False
    db.init_db()
    try:
        for i in range(count):
            sym = f"{prefix}{i}"
            db.save_event({
                "headline":       f"{prefix} mismatch #{i}",
                "stage":          "realized",
                "persistence":    "medium",
                "event_date":     "2026-01-05",
                "market_tickers": [{"symbol": sym}],
                "timestamp":      "2026-01-05T13:30:00",
            })
            with sqlite3.connect(db_path) as conn:
                for date_str in ("2026-01-20", "2026-02-02"):
                    conn.execute(
                        "INSERT OR REPLACE INTO price_cache "
                        "(ticker, date, close, volume, auto_adjust, "
                        "fetched_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (sym, date_str, 100.0 + i, 5_000_000.0,
                         1, "2026-02-02T20:00:00Z"),
                    )
                conn.commit()
    finally:
        db.DB_FILE = orig_path
        db._db_ready = orig_ready


class _Fixture(unittest.TestCase):
    """Two isolated SQLite DBs per test: ``live`` + ``backup``.  Each
    test seeds them differently to drive the delta arithmetic.
    """

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._orig_ready = db._db_ready
        self._live = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_delta_live_{uuid.uuid4().hex}.db",
        )
        self._backup = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_delta_backup_{uuid.uuid4().hex}.db",
        )
        # Backups dir for --latest tests.
        self._backups_dir = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_delta_backups_{uuid.uuid4().hex}",
        )
        os.makedirs(self._backups_dir, exist_ok=True)

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = self._orig_ready
        for path in (self._live, self._backup):
            try:
                os.remove(path)
            except (OSError, PermissionError):
                pass
        shutil.rmtree(self._backups_dir, ignore_errors=True)

    def _patched(self):
        from contextlib import ExitStack
        stack = ExitStack()
        for cm in _classifier_patches():
            stack.enter_context(cm)
        return stack

    def _run_cli(self, argv: list[str]) -> tuple[int, str, str]:
        out = StringIO()
        err = StringIO()
        old_err = sys.stderr
        try:
            sys.stderr = err
            try:
                rc = cli.main(argv, out=out)
            except SystemExit as exc:
                rc = exc.code
        finally:
            sys.stderr = old_err
        return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


_TOP_LEVEL_KEYS = (
    "live",
    "backup",
    "delta",
    "explanation",
    "available",
)

_PER_DB_KEYS = (
    "db_path",
    "exists",
    "size_bytes",
    "mtime",
    "mismatch_count",
    "preview_count",
    "planned_write_count",
    "repairable_count",
)

_DELTA_KEYS = (
    "mismatch_count",
    "preview_count",
    "planned_write_count",
    "repairable_count",
    "size_bytes",
    "mtime_seconds",
)


class TestPayloadShape(_Fixture):
    def test_json_carries_required_top_level_keys(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        for key in _TOP_LEVEL_KEYS:
            self.assertIn(key, body, f"missing top-level key: {key}")

    def test_live_section_carries_per_db_keys(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        for key in _PER_DB_KEYS:
            self.assertIn(key, body["live"], f"live missing field: {key}")

    def test_backup_section_carries_per_db_keys(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        for key in _PER_DB_KEYS:
            self.assertIn(
                key, body["backup"], f"backup missing field: {key}",
            )

    def test_delta_section_carries_required_keys(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        for key in _DELTA_KEYS:
            self.assertIn(key, body["delta"], f"delta missing field: {key}")


# ---------------------------------------------------------------------------
# Delta arithmetic
# ---------------------------------------------------------------------------


class TestDeltaArithmetic(_Fixture):
    def test_live_more_than_backup_yields_positive_delta(self) -> None:
        _seed_mismatches(self._live,   4, prefix="L")
        _seed_mismatches(self._backup, 2, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        # 4 events × 2 dates = 8 planned writes for live; 2 × 2 = 4
        # for backup.  Mismatch count is one per event.
        self.assertEqual(body["live"]["mismatch_count"],      4)
        self.assertEqual(body["backup"]["mismatch_count"],    2)
        self.assertEqual(body["delta"]["mismatch_count"],     2)
        self.assertEqual(body["live"]["planned_write_count"], 8)
        self.assertEqual(body["backup"]["planned_write_count"], 4)
        self.assertEqual(body["delta"]["planned_write_count"], 4)

    def test_live_equals_backup_yields_zero_delta(self) -> None:
        _seed_mismatches(self._live,   3, prefix="L")
        _seed_mismatches(self._backup, 3, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        self.assertEqual(body["delta"]["mismatch_count"],     0)
        self.assertEqual(body["delta"]["planned_write_count"], 0)

    def test_live_less_than_backup_yields_negative_delta(self) -> None:
        _seed_mismatches(self._live,   1, prefix="L")
        _seed_mismatches(self._backup, 3, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        self.assertEqual(body["delta"]["mismatch_count"], -2)

    def test_preview_count_equals_mismatch_count(self) -> None:
        # Documented invariant: preview_count == mismatch_count by
        # construction.  Pin it so a later refactor that desyncs the
        # two surfaces here loudly.
        _seed_mismatches(self._live,   4, prefix="L")
        _seed_mismatches(self._backup, 2, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        self.assertEqual(
            body["live"]["preview_count"], body["live"]["mismatch_count"],
        )
        self.assertEqual(
            body["backup"]["preview_count"],
            body["backup"]["mismatch_count"],
        )


# ---------------------------------------------------------------------------
# Backup picker — --latest, --backup-path, missing
# ---------------------------------------------------------------------------


def _touch_backup(backups_dir: str, name: str, mtime: float) -> str:
    """Create a backup-shaped file in ``backups_dir`` and stamp its
    mtime so the tests can pin which one --latest picks.
    """
    path = os.path.join(backups_dir, name)
    # Need a real DB so the planner can run against it.  Initialise an
    # empty events archive.
    orig_path, orig_ready = db.DB_FILE, db._db_ready
    db.DB_FILE = path
    db._db_ready = False
    try:
        db.init_db()
    finally:
        db.DB_FILE = orig_path
        db._db_ready = orig_ready
    os.utime(path, (mtime, mtime))
    return path


class TestLatestPicker(_Fixture):
    def test_latest_picks_max_mtime_backup(self) -> None:
        _seed_mismatches(self._live, 1, prefix="L")
        # Three backups with different mtimes — newest one wins.
        _touch_backup(self._backups_dir, "events-20260501T120000.db",
                      1714564800.0)
        _touch_backup(self._backups_dir, "events-20260507T120000.db",
                      1715083200.0)  # newest
        _touch_backup(self._backups_dir, "events-20260505T120000.db",
                      1714910400.0)
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backups-dir", self._backups_dir,
                "--latest",
                "--json",
            ])
        body = json.loads(output)
        self.assertTrue(body["backup"]["exists"])
        self.assertTrue(
            body["backup"]["db_path"].endswith(
                "events-20260507T120000.db"
            ),
            f"expected newest backup picked, got "
            f"{body['backup']['db_path']}",
        )

    def test_latest_with_empty_backups_dir_marks_backup_missing(
        self,
    ) -> None:
        _seed_mismatches(self._live, 2, prefix="L")
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backups-dir", self._backups_dir,
                "--latest",
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        # The most useful operator diagnostic — "we have nothing to
        # compare against."
        self.assertFalse(body["backup"]["exists"])
        self.assertIsNone(body["delta"])
        self.assertIn("backup", body["explanation"].lower())
        # Live side still populated.
        self.assertTrue(body["live"]["exists"])
        self.assertEqual(body["live"]["mismatch_count"], 2)


class TestExplicitBackupPath(_Fixture):
    def test_explicit_backup_path_wins_over_latest(self) -> None:
        # Plant a stale "latest" candidate AND an explicit backup; the
        # explicit one must win.
        _seed_mismatches(self._live,   3, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")  # explicit
        _touch_backup(self._backups_dir, "events-20260507T120000.db",
                      1715083200.0)
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--backups-dir", self._backups_dir,
                "--latest",
                "--json",
            ])
        body = json.loads(output)
        self.assertEqual(body["backup"]["db_path"], self._backup)
        self.assertEqual(body["backup"]["mismatch_count"], 1)


class TestMissingBackupPath(_Fixture):
    def test_missing_explicit_backup_marks_backup_missing(self) -> None:
        _seed_mismatches(self._live, 2, prefix="L")
        bogus = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_delta_does_not_exist_{uuid.uuid4().hex}.db",
        )
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", bogus,
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertFalse(body["backup"]["exists"])
        self.assertIsNone(body["delta"])

    def test_missing_live_db_yields_unavailable_payload(self) -> None:
        bogus_live = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_delta_no_live_{uuid.uuid4().hex}.db",
        )
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     bogus_live,
                "--backup-path", self._backup,
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertFalse(body["live"]["exists"])
        # Either delta or available signals "comparison not possible".
        self.assertFalse(body["available"])


# ---------------------------------------------------------------------------
# Read-only contract — bytes-identical before / after repeated runs
# ---------------------------------------------------------------------------


def _bytes_of(path: str) -> bytes | None:
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


class TestReadOnly(_Fixture):
    def test_neither_db_changes_across_repeated_runs(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        before_live   = _bytes_of(self._live)
        before_backup = _bytes_of(self._backup)
        with self._patched():
            for _ in range(3):
                rc, _, _ = self._run_cli([
                    "--db-path",     self._live,
                    "--backup-path", self._backup,
                    "--json",
                ])
                self.assertEqual(rc, 0)
        self.assertEqual(_bytes_of(self._live),   before_live)
        self.assertEqual(_bytes_of(self._backup), before_backup)


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestNoForbiddenSeams(_Fixture):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")

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
                        f"delta report must not call "
                        f"{module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "delta report must not call yfinance",
                    ),
                ))
            except ImportError:
                pass

            for cm in _classifier_patches():
                stack.enter_context(cm)

            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])

        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["live"]["mismatch_count"], 2)


class TestNoFastApiSurface(unittest.TestCase):
    def test_module_does_not_carry_app_or_router(self) -> None:
        self.assertFalse(hasattr(cli, "app"))
        self.assertFalse(hasattr(cli, "router"))


# ---------------------------------------------------------------------------
# Explanation line + text rendering
# ---------------------------------------------------------------------------


class TestExplanation(_Fixture):
    def test_live_more_than_backup_explanation_mentions_delta(self) -> None:
        _seed_mismatches(self._live,   4, prefix="L")
        _seed_mismatches(self._backup, 2, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        explanation = body["explanation"].lower()
        self.assertIn("live",   explanation)
        self.assertIn("backup", explanation)
        self.assertIn("2",      body["explanation"])

    def test_live_equals_backup_explanation_mentions_agreement(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 2, prefix="L")
        with self._patched():
            _, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
                "--json",
            ])
        body = json.loads(output)
        # Explanation should not falsely claim a delta exists.
        self.assertNotIn("more", body["explanation"].lower())


class TestTextRendering(_Fixture):
    def test_text_output_lists_section_headers(self) -> None:
        _seed_mismatches(self._live,   2, prefix="L")
        _seed_mismatches(self._backup, 1, prefix="L")
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backup-path", self._backup,
            ])
        self.assertEqual(rc, 0)
        for needle in (
            "Auto-adjust repair backup-delta report",
            "Live",
            "Backup",
            "Delta",
            "mismatch_count",
            "planned_write_count",
        ):
            self.assertIn(needle, output, f"missing line: {needle}")


# ---------------------------------------------------------------------------
# CLI — argparse / exit codes
# ---------------------------------------------------------------------------


class TestCliExits(_Fixture):
    def test_neither_backup_flag_passed_treats_as_latest_against_default_dir(
        self,
    ) -> None:
        # When neither --backup-path nor --latest is set, default to
        # --latest against ./backups (which may be empty in tests).
        _seed_mismatches(self._live, 1, prefix="L")
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",     self._live,
                "--backups-dir", self._backups_dir,
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        # backups_dir is empty in setUp → backup not found.
        self.assertFalse(body["backup"]["exists"])

    def test_unknown_flag_exits_nonzero(self) -> None:
        rc, _, _ = self._run_cli(["--obviously-bogus"])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
