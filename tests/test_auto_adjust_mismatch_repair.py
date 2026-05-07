"""Tests for ``auto_adjust_mismatch_repair`` (writer module) and
``scripts/auto_adjust_mismatch_repair.py`` (CLI gate).

The writer repairs ``auto_adjust_mismatch_for_20d`` cache rows by
copying matching ``aa=1`` rows into ``aa=0`` for the dates inside
``[event_date, event_date + 20bd]``.  No provider call ever — pure
SQL against the existing ``price_cache`` table.

Safety contract pinned by these tests (see also
``tests/test_auto_adjust_mismatch_repair_contract.py`` for the
cross-cutting safety surface):

  * ``plan_auto_adjust_mismatch_repair`` is read-only.
  * ``apply_auto_adjust_mismatch_repair(confirm=False)`` is a strict
    dry-run — no DB writes, no audit log file.
  * ``apply_auto_adjust_mismatch_repair(confirm=True)`` requires a
    ``backup_path`` and copies the DB to it before the first INSERT.
  * Every applied row appends a JSONL record to the audit log; the
    audit log path is surfaced on the result dict.
  * ``events.market_tickers`` never changes.
  * Re-running an apply is a no-op (``INSERT OR REPLACE`` makes the
    write idempotent).
  * The CLI gate ``--write`` requires ``--confirm`` AND
    ``--backup-path``; default is preview/dry-run.
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
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api  # noqa: E402,F401  — pre-load to break the api ↔
                                #  routes.diagnostics cycle the
                                #  loader's lazy import would
                                #  otherwise re-enter mid-load.
import db  # noqa: E402

import auto_adjust_mismatch_repair as repair  # noqa: E402
from scripts import auto_adjust_mismatch_repair as cli  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers — mirror the contract test's seeding shape so fixture
# semantics line up across files.
# ---------------------------------------------------------------------------


def _seed_event(*, headline: str, event_date, symbols=None,
                timestamp=None) -> int:
    ev = {
        "headline":       headline,
        "stage":          "realized",
        "persistence":    "medium",
        "event_date":     event_date,
        "market_tickers": [{"symbol": s.upper()} for s in (symbols or [])],
    }
    if timestamp is not None:
        ev["timestamp"] = timestamp
    db.save_event(ev)
    with sqlite3.connect(db.DB_FILE) as conn:
        row = conn.execute(
            "SELECT id FROM events WHERE headline = ? "
            "ORDER BY id DESC LIMIT 1",
            (headline,),
        ).fetchone()
    return int(row[0])


def _insert_cache_row(
    db_path: str, *, ticker: str, date_str: str, close: float,
    volume: float, auto_adjust: int, fetched_at: str,
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_cache "
            "(ticker, date, close, volume, auto_adjust, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ticker.upper(), date_str, close, volume, auto_adjust,
             fetched_at),
        )
        conn.commit()


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


def _snapshot_market_tickers(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT id, market_tickers FROM events ORDER BY id"
        ))


def _snapshot_cache(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute(
            "SELECT ticker, date, close, volume, auto_adjust, fetched_at "
            "FROM price_cache ORDER BY ticker, date, auto_adjust"
        ))


def _classifier_patches(
    *,
    blocker_reason: str = "no_forward_20d_close",
    sub_reason: str = "auto_adjust_mismatch_for_20d",
) -> tuple:
    """Mirror the patch pattern used by the read-only preview tests.

    The full hydrator stack (cache anchor / T+1 / T+5 / T+20 closes)
    is not the writer's concern — the writer's contract is "given a
    classified mismatch, produce the right INSERT plan and apply it
    safely."  Patching the classifier outputs lets each test focus on
    that contract without seeding a hydrator-grade cache fixture per
    case.
    """
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


class _DBFixture(unittest.TestCase):
    """One isolated SQLite DB per test, plus a unique audit-log path so
    repeated runs never collide."""

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_aa_repair_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db._db_ready = False
        db.init_db()

        self._backup = os.path.join(
            tempfile.gettempdir(),
            f"aa_repair_backup_{uuid.uuid4().hex}.db",
        )
        self._audit = os.path.join(
            tempfile.gettempdir(),
            f"aa_repair_audit_{uuid.uuid4().hex}.jsonl",
        )

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        db._db_ready = False
        for path in (self._tmp, self._backup, self._audit):
            try:
                os.remove(path)
            except (OSError, PermissionError):
                pass

    def _seed_one_mismatch(self) -> tuple[int, str]:
        """Plant one auto_adjust_mismatch_for_20d row.

        event_d = 2026-01-05; target_20d (Mon→Mon, 20bd) = 2026-02-02.
        aa=1 cache covers the window with two rows; aa=0 has nothing.
        Tests wrap calls in ``_classifier_patches`` to make the
        classifier flag this row as the expected mismatch sub-reason
        without standing up a hydrator-grade fixture.
        """
        eid = _seed_event(
            headline="aa-repair single mismatch",
            event_date="2026-01-05",
            symbols=["AAPL"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-01-20",
            close=180.0, volume=5_000_000.0, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )
        _insert_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=181.0, volume=6_000_000.0, auto_adjust=1,
            fetched_at="2026-02-02T20:00:00Z",
        )
        return eid, "AAPL"

    def _patched(self):
        """Return a ContextDecorator-style stack that applies the
        classifier patches.  Tests use ``with self._patched():`` so the
        patch lifetime is exactly the call-under-test.
        """
        from contextlib import ExitStack
        stack = ExitStack()
        for cm in _classifier_patches():
            stack.enter_context(cm)
        return stack


# ---------------------------------------------------------------------------
# Plan shape + read-only contract
# ---------------------------------------------------------------------------


class TestPlanShape(_DBFixture):
    def test_plan_returns_required_top_level_keys(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            plan = repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        for key in (
            "available",
            "total_mismatches",
            "planned_writes",
            "planned_write_count",
        ):
            self.assertIn(key, plan, f"missing plan key: {key}")

    def test_plan_proposes_one_write_per_aa1_only_date(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            plan = repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        writes = plan["planned_writes"]
        # Two aa=1 rows in window, neither at aa=0 → two proposals.
        self.assertEqual(len(writes), 2)
        for w in writes:
            for key in (
                "ticker", "date", "close", "volume",
                "auto_adjust", "fetched_at", "source_event_id",
            ):
                self.assertIn(key, w, f"missing planned-write key: {key}")
            self.assertEqual(w["auto_adjust"], 0)
            self.assertEqual(w["ticker"], "AAPL")
        self.assertEqual(
            sorted(w["date"] for w in writes),
            ["2026-01-20", "2026-02-02"],
        )

    def test_plan_carries_aa1_source_close_and_volume(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            plan = repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        writes = {w["date"]: w for w in plan["planned_writes"]}
        self.assertEqual(writes["2026-01-20"]["close"],  180.0)
        self.assertEqual(writes["2026-01-20"]["volume"], 5_000_000.0)
        self.assertEqual(writes["2026-02-02"]["close"],  181.0)
        self.assertEqual(writes["2026-02-02"]["volume"], 6_000_000.0)


class TestPlanIsReadOnly(_DBFixture):
    def test_plan_does_not_mutate_db(self) -> None:
        self._seed_one_mismatch()
        before_events = _snapshot_events(self._tmp)
        before_cache  = _snapshot_cache(self._tmp)
        with self._patched():
            for _ in range(3):
                repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        after_events = _snapshot_events(self._tmp)
        after_cache  = _snapshot_cache(self._tmp)
        self.assertEqual(before_events, after_events)
        self.assertEqual(before_cache,  after_cache)

    def test_plan_against_empty_db_returns_empty(self) -> None:
        # No classifier patch — empty DB has no rows for the classifier
        # to see anyway.  Pin the empty-shape path explicitly.
        plan = repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        self.assertEqual(plan["planned_write_count"], 0)
        self.assertEqual(plan["planned_writes"],      [])
        self.assertEqual(plan["total_mismatches"], 0)

    def test_plan_against_no_mismatches_returns_empty(self) -> None:
        # Classifier is patched to a non-mismatch sub-reason so the
        # planner skips this event entirely.
        _seed_event(
            headline="no mismatch",
            event_date="2026-01-05",
            symbols=["AAPL"],
            timestamp="2026-01-05T13:30:00",
        )
        _insert_cache_row(
            self._tmp, ticker="AAPL", date_str="2026-02-02",
            close=181.0, volume=6_000_000.0, auto_adjust=0,
            fetched_at="2026-02-02T20:00:00Z",
        )
        with patch(
            "routes.diagnostics._classify_blocker_for_ticker",
            return_value="no_forward_20d_close",
        ), patch(
            "routes.diagnostics._classify_no_forward_20d_subreason",
            return_value="cache_max_before_20d_horizon",
        ):
            plan = repair.plan_auto_adjust_mismatch_repair(db_path=self._tmp)
        self.assertEqual(plan["planned_write_count"], 0)


# ---------------------------------------------------------------------------
# Apply — dry-run default + confirm/backup gating
# ---------------------------------------------------------------------------


class TestApplyDryRunDefault(_DBFixture):
    def test_apply_without_confirm_writes_nothing(self) -> None:
        self._seed_one_mismatch()
        before_events = _snapshot_events(self._tmp)
        before_cache  = _snapshot_cache(self._tmp)
        with self._patched():
            result = repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
            )
        after_events = _snapshot_events(self._tmp)
        after_cache  = _snapshot_cache(self._tmp)
        self.assertEqual(before_events, after_events)
        self.assertEqual(before_cache,  after_cache)
        self.assertEqual(result["applied_count"], 0)
        # Plan still surfaces so the operator sees what *would* run.
        self.assertEqual(len(result["planned_writes"]), 2)

    def test_apply_dry_run_creates_no_audit_log_file(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            result = repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp, audit_log_path=self._audit,
            )
        self.assertFalse(os.path.exists(self._audit))
        # The audit-log key still exists in the result so consumers can
        # rely on its presence; value is ``None`` when nothing was
        # written.
        self.assertIn("audit_log_path", result)
        self.assertIsNone(result["audit_log_path"])


class TestApplyConfirmRequiresBackup(_DBFixture):
    def test_confirm_without_backup_path_raises(self) -> None:
        self._seed_one_mismatch()
        with self.assertRaises(ValueError):
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp, confirm=True, backup_path=None,
            )

    def test_confirm_without_backup_does_not_mutate_db(self) -> None:
        self._seed_one_mismatch()
        before = _snapshot_cache(self._tmp)
        try:
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp, confirm=True, backup_path=None,
            )
        except ValueError:
            pass
        after = _snapshot_cache(self._tmp)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Apply — happy path
# ---------------------------------------------------------------------------


class TestApplyHappyPath(_DBFixture):
    def test_apply_inserts_aa0_rows_for_proposed_dates(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        with sqlite3.connect(self._tmp) as conn:
            aa0_rows = list(conn.execute(
                "SELECT date, close, volume, fetched_at FROM price_cache "
                "WHERE ticker='AAPL' AND auto_adjust=0 ORDER BY date"
            ))
        self.assertEqual(len(aa0_rows), 2)
        # Source close/volume copied byte-for-byte from aa=1.
        self.assertEqual(aa0_rows[0][0], "2026-01-20")
        self.assertEqual(aa0_rows[0][1], 180.0)
        self.assertEqual(aa0_rows[0][2], 5_000_000.0)
        self.assertEqual(aa0_rows[1][0], "2026-02-02")
        self.assertEqual(aa0_rows[1][1], 181.0)
        self.assertEqual(aa0_rows[1][2], 6_000_000.0)

    def test_apply_returns_applied_count_matching_planned_writes(
        self,
    ) -> None:
        self._seed_one_mismatch()
        with self._patched():
            result = repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(len(result["applied_writes"]), 2)

    def test_apply_creates_backup_before_first_insert(self) -> None:
        self._seed_one_mismatch()
        # Capture the live DB bytes BEFORE any apply call.  After the
        # apply, the backup must equal the live bytes from before the
        # apply (so a recovery from the backup restores the pre-write
        # state).
        with open(self._tmp, "rb") as f:
            pre_apply_bytes = f.read()
        with self._patched():
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        self.assertTrue(os.path.exists(self._backup))
        with open(self._backup, "rb") as f:
            backup_bytes = f.read()
        self.assertEqual(
            backup_bytes, pre_apply_bytes,
            "backup must capture the pre-apply DB state byte-for-byte",
        )


# ---------------------------------------------------------------------------
# Apply — audit log
# ---------------------------------------------------------------------------


class TestApplyAuditLog(_DBFixture):
    def test_audit_log_file_exists_when_applied_count_positive(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            result = repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        self.assertTrue(os.path.exists(self._audit))
        self.assertEqual(result["audit_log_path"], self._audit)

    def test_audit_log_has_one_jsonl_record_per_applied_write(self) -> None:
        eid, _ = self._seed_one_mismatch()
        with self._patched():
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        with open(self._audit, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        records = [json.loads(ln) for ln in lines]
        for rec in records:
            self.assertEqual(rec["ticker"],          "AAPL")
            self.assertEqual(rec["auto_adjust"],     0)
            self.assertEqual(rec["source_event_id"], eid)
            self.assertIn("date", rec)
            self.assertIn("ts",   rec)

    def test_apply_with_no_mismatches_does_not_create_audit_log(
        self,
    ) -> None:
        # Empty archive → applied_count=0 → no audit log file.
        result = repair.apply_auto_adjust_mismatch_repair(
            db_path=self._tmp,
            confirm=True,
            backup_path=self._backup,
            audit_log_path=self._audit,
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertFalse(os.path.exists(self._audit))
        self.assertIsNone(result["audit_log_path"])


# ---------------------------------------------------------------------------
# Apply — invariants required by the contract
# ---------------------------------------------------------------------------


class TestApplyDoesNotMutateMarketTickers(_DBFixture):
    def test_market_tickers_unchanged_after_apply(self) -> None:
        self._seed_one_mismatch()
        before = _snapshot_market_tickers(self._tmp)
        with self._patched():
            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        after = _snapshot_market_tickers(self._tmp)
        self.assertEqual(before, after)


class TestApplyIdempotent(_DBFixture):
    def test_running_twice_yields_zero_second_apply(self) -> None:
        # First run: classifier flags as auto_adjust_mismatch_for_20d
        # → two writes proposed and applied.
        self._seed_one_mismatch()
        with self._patched():
            first = repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )
        # Second run: aa=0 now mirrors aa=1, so the planner produces
        # zero proposals (set difference is empty).  The classifier
        # mock still says "mismatch", but proposed_row_dates is empty
        # because aa=0 already covers what aa=1 has.
        second_audit = self._audit + ".second"
        try:
            with self._patched():
                second = repair.apply_auto_adjust_mismatch_repair(
                    db_path=self._tmp,
                    confirm=True,
                    backup_path=self._backup,
                    audit_log_path=second_audit,
                )
        finally:
            try:
                os.remove(second_audit)
            except (OSError, PermissionError):
                pass
        self.assertEqual(first["applied_count"],  2)
        self.assertEqual(second["applied_count"], 0)
        self.assertFalse(
            os.path.exists(second_audit),
            "second-run audit log must not be created when no rows "
            "were written",
        )


# ---------------------------------------------------------------------------
# No paid / FastAPI seams
# ---------------------------------------------------------------------------


class TestApplyNoForbiddenSeams(_DBFixture):
    def test_no_provider_yfinance_or_llm_seam_invoked(self) -> None:
        from contextlib import ExitStack

        self._seed_one_mismatch()

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
                        f"apply_auto_adjust_mismatch_repair must not "
                        f"call {module_name}.{attr}",
                    ),
                ))
            try:
                import yfinance  # noqa: F401
                stack.enter_context(patch(
                    "yfinance.download",
                    side_effect=AssertionError(
                        "apply_auto_adjust_mismatch_repair must not "
                        "call yfinance",
                    ),
                ))
            except ImportError:
                pass

            for cm in _classifier_patches():
                stack.enter_context(cm)

            repair.apply_auto_adjust_mismatch_repair(
                db_path=self._tmp,
                confirm=True,
                backup_path=self._backup,
                audit_log_path=self._audit,
            )


class TestModuleHasNoFastApiSurface(unittest.TestCase):
    def test_module_does_not_carry_app_or_router(self) -> None:
        self.assertFalse(hasattr(repair, "app"))
        self.assertFalse(hasattr(repair, "router"))


# ---------------------------------------------------------------------------
# CLI gate — --write/--confirm/--backup-path
# ---------------------------------------------------------------------------


class _CliFixture(_DBFixture):
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


class TestCliDefaultIsDryRun(_CliFixture):
    def test_default_invocation_does_not_mutate_db(self) -> None:
        self._seed_one_mismatch()
        before = _snapshot_cache(self._tmp)
        with self._patched():
            rc, _, _ = self._run_cli(["--db-path", self._tmp])
        self.assertEqual(rc, 0)
        after = _snapshot_cache(self._tmp)
        self.assertEqual(before, after)

    def test_json_default_emits_planned_writes_count(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path", self._tmp, "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["planned_write_count"], 2)
        self.assertEqual(body["applied_count"],       0)


class TestCliWriteGate(_CliFixture):
    def test_write_without_confirm_exits_nonzero(self) -> None:
        self._seed_one_mismatch()
        before = _snapshot_cache(self._tmp)
        rc, _, err = self._run_cli([
            "--db-path", self._tmp, "--write",
        ])
        self.assertNotEqual(rc, 0)
        self.assertEqual(_snapshot_cache(self._tmp), before)

    def test_write_confirm_without_backup_exits_nonzero(self) -> None:
        self._seed_one_mismatch()
        before = _snapshot_cache(self._tmp)
        rc, _, err = self._run_cli([
            "--db-path", self._tmp, "--write", "--confirm",
        ])
        self.assertNotEqual(rc, 0)
        self.assertEqual(_snapshot_cache(self._tmp), before)

    def test_write_confirm_with_backup_applies(self) -> None:
        self._seed_one_mismatch()
        with self._patched():
            rc, output, _ = self._run_cli([
                "--db-path",        self._tmp,
                "--write",          "--confirm",
                "--backup-path",    self._backup,
                "--audit-log-path", self._audit,
                "--json",
            ])
        self.assertEqual(rc, 0)
        body = json.loads(output)
        self.assertEqual(body["applied_count"], 2)
        # Verify the writes landed in the actual DB.
        with sqlite3.connect(self._tmp) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM price_cache "
                "WHERE auto_adjust=0 AND ticker='AAPL'"
            ).fetchone()[0]
        self.assertEqual(count, 2)
        self.assertTrue(os.path.exists(self._backup))
        self.assertTrue(os.path.exists(self._audit))


class TestCliRejectsUnknownFlag(_CliFixture):
    def test_unknown_flag_exits_nonzero(self) -> None:
        rc, _, _ = self._run_cli([
            "--db-path", self._tmp, "--obviously-bogus-flag",
        ])
        self.assertNotEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
