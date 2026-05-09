"""Tests for ``scripts/archive_cleanup_apply_plan.py``.

Pin the backup-gated apply-plan contract:

* Default mode is dry-run; the result carries a stable shape with
  ``mode='dry_run'``, zeroed write-mode keys, and a ``delete_preview``
  block whose ``deduped_event_ids`` is independent of ``--limit``.
* The dedup invariant: ``len(delete_preview.deduped_event_ids) ==
  candidate_count`` even when multi-reason events appear in multiple
  batches.
* CLI gate: ``--write`` requires ``--confirm`` AND ``--backup-path``;
  ``--dry-run`` and ``--write`` are mutually exclusive at argparse.
* ``apply_against_temp_copy`` raises ``ValueError`` without
  ``confirm=True`` or ``backup_path``.
* Write mode operates only on a temp copy of the input backup; the
  input backup file is byte-identical post-run, the live ``events.db``
  is byte-identical post-run.
* The audit log is JSONL with one record per deleted event, carrying
  reasons + headline / timestamp / event_date + backup + temp paths.
* Audit log is materialised on disk only when ``applied_count > 0``;
  zero-candidate runs leave ``audit_log_path`` as ``None``.
* Failure paths (missing / non-SQLite / schema-less backup) surface a
  clean error and leave the live DB hash untouched.
* Source pins: no ``import db`` / ``from db import`` line, no
  destructive SQL outside the documented temp-copy DELETE, no paid
  seams, no filesystem destructors against operator-visible paths.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts import archive_cleanup_apply_plan as apply_plan  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    headline    TEXT,
    timestamp   TEXT,
    event_date  TEXT
)
""".strip()


_DRY_RUN_TOP_KEYS: tuple[str, ...] = (
    "mode",
    "candidate_count",
    "batches",
    "risk_notes",
    "required_confirmation_flags",
    "recommended_next_action",
    "delete_preview",
    "confirm",
    "applied_count",
    "applied_event_ids",
    "backup_path",
    "temp_copy_path",
    "audit_log_path",
    "live_db_path",
    "live_db_unchanged",
    "input_backup_unchanged",
    "warnings",
    "errors",
    "ok",
)


def _seed_event(
    conn: sqlite3.Connection,
    *,
    headline: str | None = "headline",
    timestamp: str | None = "2026-04-01T10:00:00",
    event_date: str | None = "2026-04-01",
) -> int:
    cur = conn.execute(
        "INSERT INTO events (headline, timestamp, event_date) "
        "VALUES (?, ?, ?)",
        (headline, timestamp, event_date),
    )
    return int(cur.lastrowid)


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_events(db_path: str) -> list[tuple]:
    with sqlite3.connect(db_path) as conn:
        return list(conn.execute("SELECT * FROM events ORDER BY id"))


class _Base(unittest.TestCase):
    """Per-test scratch DB that follows the candidate-report shape."""

    def setUp(self) -> None:
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_{uuid.uuid4().hex}.db",
        )
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(_EVENTS_DDL)
            conn.commit()
        # Always point live_db at a non-existent path so the project's
        # real events.db is never touched in tests (defence in depth on
        # top of the script's own no-write-to-live-db contract).
        self._fake_live_db = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_live_{uuid.uuid4().hex}.db",
        )

    def tearDown(self) -> None:
        for p in (self._tmp, self._fake_live_db):
            try:
                os.remove(p)
            except (OSError, PermissionError):
                pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._tmp)


# ---------------------------------------------------------------------------
# Dry-run shape
# ---------------------------------------------------------------------------


class TestDryRunShape(_Base):
    def test_returns_dict_with_top_keyset(self) -> None:
        result = apply_plan.build_apply_plan(db_path=self._tmp)
        self.assertIsInstance(result, dict)
        for key in _DRY_RUN_TOP_KEYS:
            self.assertIn(key, result, f"missing top-level key: {key}")

    def test_dry_run_constant_fields(self) -> None:
        result = apply_plan.build_apply_plan(db_path=self._tmp)
        self.assertEqual(result["mode"], "dry_run")
        self.assertIs(result["confirm"], False)
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["applied_event_ids"], [])
        self.assertIsNone(result["backup_path"])
        self.assertIsNone(result["temp_copy_path"])
        self.assertIsNone(result["audit_log_path"])
        self.assertIsNone(result["live_db_path"])
        self.assertIsNone(result["live_db_unchanged"])
        self.assertIsNone(result["input_backup_unchanged"])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["errors"], [])
        self.assertIs(result["ok"], True)

    def test_delete_preview_keys_and_types(self) -> None:
        result = apply_plan.build_apply_plan(db_path=self._tmp)
        preview = result["delete_preview"]
        self.assertIsInstance(preview, dict)
        self.assertIn("deduped_event_count", preview)
        self.assertIn("deduped_event_ids", preview)
        self.assertIsInstance(preview["deduped_event_count"], int)
        self.assertIsInstance(preview["deduped_event_ids"], list)

    def test_empty_archive_emits_zero_preview(self) -> None:
        result = apply_plan.build_apply_plan(db_path=self._tmp)
        self.assertEqual(result["candidate_count"], 0)
        self.assertEqual(result["delete_preview"]["deduped_event_count"], 0)
        self.assertEqual(result["delete_preview"]["deduped_event_ids"], [])


# ---------------------------------------------------------------------------
# Dedup invariant
# ---------------------------------------------------------------------------


class TestDryRunDedup(_Base):
    def test_dedup_count_equals_candidate_count_single_reason(self) -> None:
        with self._conn() as conn:
            for _ in range(3):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        result = apply_plan.build_apply_plan(db_path=self._tmp)
        self.assertEqual(
            result["delete_preview"]["deduped_event_count"],
            result["candidate_count"],
        )

    def test_multi_reason_event_dedups_to_single_id(self) -> None:
        # ``Fed speakers rotate`` twice on the same event_date matches
        # rotating_macro_template AND duplicate_headline_event_date,
        # so each event_id appears in two batches.  The dedup must
        # collapse them back to ``candidate_count`` unique ids.
        with self._conn() as conn:
            id_a = _seed_event(
                conn,
                headline="Fed speakers rotate",
                timestamp="2026-04-30T08:00:00",
                event_date="2026-04-30",
            )
            id_b = _seed_event(
                conn,
                headline="Fed speakers rotate",
                timestamp="2026-04-30T09:00:00",
                event_date="2026-04-30",
            )
            conn.commit()
        result = apply_plan.build_apply_plan(db_path=self._tmp)

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(
            result["delete_preview"]["deduped_event_count"],
            result["candidate_count"],
        )
        self.assertEqual(
            sorted(result["delete_preview"]["deduped_event_ids"]),
            sorted([id_a, id_b]),
        )

    def test_dedup_independent_of_limit(self) -> None:
        # ``--limit`` only caps per-batch ``examples``; the deduped
        # event_ids must reflect every flagged event regardless.
        with self._conn() as conn:
            for i in range(8):
                _seed_event(
                    conn,
                    headline="Macro shock test event",
                    timestamp=f"2026-04-01T{10 + i:02d}:00:00",
                    event_date=f"2026-04-{1 + i:02d}",
                )
            conn.commit()

        loose = apply_plan.build_apply_plan(db_path=self._tmp, limit=2)
        tight = apply_plan.build_apply_plan(db_path=self._tmp, limit=8)

        self.assertEqual(
            loose["delete_preview"]["deduped_event_ids"],
            tight["delete_preview"]["deduped_event_ids"],
        )
        self.assertEqual(loose["delete_preview"]["deduped_event_count"], 8)


# ---------------------------------------------------------------------------
# Patchable seam (kwarg-based injection)
# ---------------------------------------------------------------------------


class TestPatchableSeam(unittest.TestCase):
    def test_execution_plan_kwarg_short_circuits_db_call(self) -> None:
        # Direct injection: when ``execution_plan=`` is supplied, the
        # underlying candidate-report and execution-plan calls must NOT
        # fire — even if patched to raise.
        injected_plan = {
            "candidate_count": 2,
            "batches": [
                {
                    "reason": "test_fixture_phrase",
                    "size": 2,
                    "event_ids": [10, 20],
                    "examples": [],
                    "manual_review_required_before_delete": True,
                    "description": "x",
                },
            ],
            "risk_notes": ["a"],
            "required_confirmation_flags": ["b"],
            "recommended_next_action": "anything",
        }

        def _explode(*_a, **_kw):  # pragma: no cover — must not run
            raise AssertionError("upstream candidate report was called")

        with patch.object(
            apply_plan._candidate_report,
            "summarize_cleanup_candidates",
            side_effect=_explode,
        ):
            with patch.object(
                apply_plan._execution_plan,
                "build_execution_plan",
                side_effect=_explode,
            ):
                result = apply_plan.build_apply_plan(
                    execution_plan=injected_plan,
                )

        self.assertEqual(result["candidate_count"], 2)
        self.assertEqual(
            result["delete_preview"]["deduped_event_ids"], [10, 20],
        )
        self.assertEqual(
            result["delete_preview"]["deduped_event_count"], 2,
        )

    def test_candidate_report_kwarg_routes_through_execution_plan(self) -> None:
        # Passing ``candidate_report=`` bypasses the candidate-report
        # SELECT but still flows through ``build_execution_plan``.
        injected_report = {
            "candidate_count": 1,
            "reasons": {
                "test_fixture_phrase": 1,
                "rotating_macro_template": 0,
                "fixture_timestamp_cluster": 0,
                "duplicate_headline_event_date": 0,
            },
            "examples": [
                {
                    "event_id": 42,
                    "headline": "Macro shock test event",
                    "timestamp": "2026-04-01T10:00:00",
                    "event_date": "2026-04-01",
                    "reasons": ["test_fixture_phrase"],
                },
            ],
            "fixture_timestamp_threshold": 3,
            "recommended_next_action": "anything",
        }

        def _explode(*_a, **_kw):  # pragma: no cover — must not run
            raise AssertionError("candidate report was called")

        with patch.object(
            apply_plan._candidate_report,
            "summarize_cleanup_candidates",
            side_effect=_explode,
        ):
            result = apply_plan.build_apply_plan(
                candidate_report=injected_report,
            )

        self.assertEqual(result["candidate_count"], 1)
        self.assertEqual(
            result["delete_preview"]["deduped_event_ids"], [42],
        )


# ---------------------------------------------------------------------------
# Read-only contract for the dry-run path
# ---------------------------------------------------------------------------


class TestDryRunReadOnly(_Base):
    def test_dry_run_leaves_events_byte_identical(self) -> None:
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            _seed_event(
                conn,
                headline="Real news headline",
                timestamp="2026-04-15T11:00:00",
                event_date="2026-04-15",
            )
            conn.commit()
        before = _snapshot_events(self._tmp)
        for _ in range(3):
            apply_plan.build_apply_plan(db_path=self._tmp)
        after = _snapshot_events(self._tmp)
        self.assertEqual(before, after)


# ---------------------------------------------------------------------------
# Apply guards (function-level)
# ---------------------------------------------------------------------------


class TestApplyGuards(_Base):
    def test_apply_without_confirm_raises(self) -> None:
        with self.assertRaises(ValueError):
            apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=False,
                live_db_path=self._fake_live_db,
            )

    def test_apply_without_backup_path_raises(self) -> None:
        with self.assertRaises(ValueError):
            apply_plan.apply_against_temp_copy(
                backup_path=None,
                confirm=True,
                live_db_path=self._fake_live_db,
            )


# ---------------------------------------------------------------------------
# Apply happy path against a copied temp DB
# ---------------------------------------------------------------------------


class TestApplyHappyPath(_Base):
    def setUp(self) -> None:
        super().setUp()
        # Seed three test-fixture events into the "backup" file.  We
        # treat ``self._tmp`` as the operator's pre-staged backup; the
        # apply path will copy it to a private temp DB before deletion.
        with self._conn() as conn:
            self._id_a = _seed_event(
                conn, headline="Macro shock test event",
                timestamp="2026-04-01T10:00:00", event_date="2026-04-01",
            )
            self._id_b = _seed_event(
                conn, headline="Macro shock test event",
                timestamp="2026-04-02T10:00:00", event_date="2026-04-02",
            )
            self._id_keep = _seed_event(
                conn, headline="Real news headline",
                timestamp="2026-04-15T11:00:00", event_date="2026-04-15",
            )
            conn.commit()
        # Allocate (but don't pre-create) the audit-log path inside the
        # tempdir.  Tracked here so tearDown can clean it up.
        self._audit_path = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_{uuid.uuid4().hex}.jsonl",
        )

    def tearDown(self) -> None:
        try:
            os.remove(self._audit_path)
        except (OSError, PermissionError):
            pass
        super().tearDown()

    def test_applies_deletes_and_writes_audit_log(self) -> None:
        result = apply_plan.apply_against_temp_copy(
            backup_path=self._tmp,
            confirm=True,
            audit_log_path=self._audit_path,
            live_db_path=self._fake_live_db,
        )

        self.assertTrue(result["ok"], msg=f"errors: {result['errors']}")
        self.assertEqual(result["mode"], "write_temp_copy")
        self.assertIs(result["confirm"], True)
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(
            sorted(result["applied_event_ids"]),
            sorted([self._id_a, self._id_b]),
        )
        self.assertEqual(result["audit_log_path"], self._audit_path)

        # Audit file exists, JSONL, one line per applied event,
        # carrying reasons + metadata.
        self.assertTrue(os.path.exists(self._audit_path))
        with open(self._audit_path, encoding="utf-8") as fh:
            lines = [ln for ln in fh.read().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 2)
        records = [json.loads(ln) for ln in lines]
        for rec in records:
            self.assertIn("event_id", rec)
            self.assertIn("reasons", rec)
            self.assertIn("test_fixture_phrase", rec["reasons"])
            self.assertEqual(rec["action"], "delete_event_from_temp_copy")
            self.assertEqual(rec["backup_path"], str(self._tmp))
            self.assertIn("temp_copy_path", rec)
            self.assertIn("ts", rec)

    def test_input_backup_byte_identical_post_run(self) -> None:
        # Snapshot the operator's input backup before the run; it
        # must be byte-identical afterwards.  A buggy writer that
        # accidentally pointed at the input file would be surfaced.
        hash_before  = _hash_file(Path(self._tmp))
        mtime_before = Path(self._tmp).stat().st_mtime

        result = apply_plan.apply_against_temp_copy(
            backup_path=self._tmp,
            confirm=True,
            audit_log_path=self._audit_path,
            live_db_path=self._fake_live_db,
        )

        self.assertTrue(result["ok"], msg=f"errors: {result['errors']}")
        self.assertIs(result["input_backup_unchanged"], True)
        self.assertEqual(_hash_file(Path(self._tmp)), hash_before)
        self.assertEqual(Path(self._tmp).stat().st_mtime, mtime_before)
        # The kept event is still present in the backup file (because
        # we never wrote to it).
        with sqlite3.connect(self._tmp) as conn:
            ids = sorted(int(r[0]) for r in conn.execute("SELECT id FROM events"))
        self.assertIn(self._id_keep, ids)
        self.assertIn(self._id_a, ids)  # still present in the BACKUP
        self.assertIn(self._id_b, ids)  # still present in the BACKUP

    def test_temp_copy_unlinked_after_run(self) -> None:
        result = apply_plan.apply_against_temp_copy(
            backup_path=self._tmp,
            confirm=True,
            audit_log_path=self._audit_path,
            live_db_path=self._fake_live_db,
        )
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["temp_copy_path"])
        self.assertFalse(
            os.path.exists(result["temp_copy_path"]),
            f"temp copy leaked: {result['temp_copy_path']}",
        )

    def test_backup_path_recorded_in_result(self) -> None:
        result = apply_plan.apply_against_temp_copy(
            backup_path=self._tmp,
            confirm=True,
            audit_log_path=self._audit_path,
            live_db_path=self._fake_live_db,
        )
        self.assertEqual(result["backup_path"], str(self._tmp))


# ---------------------------------------------------------------------------
# Apply zero-candidate path
# ---------------------------------------------------------------------------


class TestApplyZeroCandidates(_Base):
    def test_zero_candidates_writes_no_audit_file(self) -> None:
        # Empty events table → zero candidates → no DELETE, no audit
        # file.  Match the sister write-smoke convention:
        # ``audit_log_path`` stays None.
        audit_path = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_{uuid.uuid4().hex}.jsonl",
        )
        try:
            result = apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=True,
                audit_log_path=audit_path,
                live_db_path=self._fake_live_db,
            )
            self.assertTrue(result["ok"], msg=f"errors: {result['errors']}")
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result["applied_event_ids"], [])
            self.assertIsNone(result["audit_log_path"])
            self.assertFalse(os.path.exists(audit_path))
        finally:
            try:
                os.remove(audit_path)
            except (OSError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# Live DB sentinel — never opened for write
# ---------------------------------------------------------------------------


class TestLiveDbSentinel(_Base):
    def test_live_db_hash_unchanged_on_happy_path(self) -> None:
        # Create a real "live" DB file; hash it before and after a
        # successful apply.  It must be byte-identical.
        with sqlite3.connect(self._fake_live_db) as conn:
            conn.execute(_EVENTS_DDL)
            _seed_event(conn, headline="Live DB row — should never move")
            conn.commit()

        # Pre-stage the backup with cleanup candidates.
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()

        live_hash_before  = _hash_file(Path(self._fake_live_db))
        live_mtime_before = Path(self._fake_live_db).stat().st_mtime

        audit_path = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_{uuid.uuid4().hex}.jsonl",
        )
        try:
            result = apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=True,
                audit_log_path=audit_path,
                live_db_path=self._fake_live_db,
            )
            self.assertTrue(result["ok"], msg=f"errors: {result['errors']}")
            self.assertIs(result["live_db_unchanged"], True)
            self.assertEqual(
                _hash_file(Path(self._fake_live_db)), live_hash_before,
            )
            self.assertEqual(
                Path(self._fake_live_db).stat().st_mtime, live_mtime_before,
            )
        finally:
            try:
                os.remove(audit_path)
            except (OSError, PermissionError):
                pass

    def test_live_db_hash_unchanged_on_bad_backup(self) -> None:
        # Even when the apply fails fast on a missing backup file, the
        # live events.db must remain byte-identical and the live-db
        # sentinel must classify it as unchanged.
        with sqlite3.connect(self._fake_live_db) as conn:
            conn.execute(_EVENTS_DDL)
            _seed_event(conn, headline="Live DB row")
            conn.commit()

        live_hash_before  = _hash_file(Path(self._fake_live_db))

        bogus_backup = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_does_not_exist_{uuid.uuid4().hex}.db",
        )
        result = apply_plan.apply_against_temp_copy(
            backup_path=bogus_backup,
            confirm=True,
            live_db_path=self._fake_live_db,
        )
        self.assertFalse(result["ok"])
        self.assertTrue(any(
            "does not exist" in e for e in result["errors"]
        ))
        # Even on the failure path, the live-DB sentinel must measure
        # the live file and confirm it is unchanged.
        self.assertIs(result["live_db_unchanged"], True)
        # No backup file ever existed; the input-backup sentinel had
        # nothing to measure, so it must remain ``None`` rather than
        # silently classifying the missing file as "unchanged".
        self.assertIsNone(result["input_backup_unchanged"])
        self.assertEqual(
            _hash_file(Path(self._fake_live_db)), live_hash_before,
        )

    def test_live_db_hash_unchanged_on_corrupt_backup(self) -> None:
        # A backup file that exists but is not a valid SQLite database
        # must surface a clean error and leave the live DB untouched.
        with sqlite3.connect(self._fake_live_db) as conn:
            conn.execute(_EVENTS_DDL)
            _seed_event(conn, headline="Live DB row")
            conn.commit()

        live_hash_before = _hash_file(Path(self._fake_live_db))

        corrupt = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_corrupt_{uuid.uuid4().hex}.db",
        )
        with open(corrupt, "wb") as fh:
            fh.write(b"this is not a sqlite database")

        backup_hash_before = _hash_file(Path(corrupt))

        try:
            result = apply_plan.apply_against_temp_copy(
                backup_path=corrupt,
                confirm=True,
                live_db_path=self._fake_live_db,
            )
            self.assertFalse(result["ok"])
            self.assertGreater(len(result["errors"]), 0)
            self.assertIs(result["live_db_unchanged"], True)
            # Pre-flight ran AFTER the input-backup hash was captured,
            # so the sentinel must classify the operator's backup as
            # byte-identical even on the corrupt-backup failure path.
            self.assertIs(result["input_backup_unchanged"], True)
            self.assertEqual(
                _hash_file(Path(self._fake_live_db)), live_hash_before,
            )
            self.assertEqual(_hash_file(Path(corrupt)), backup_hash_before)
        finally:
            try:
                os.remove(corrupt)
            except (OSError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# Failure-path rollback visibility
# ---------------------------------------------------------------------------


class _FailurePathBase(_Base):
    """Common scaffolding for failure-path tests: a seeded "backup"
    with one cleanup candidate AND a seeded live DB.  Both files'
    hashes are captured pre-run so each test can assert they are
    byte-identical post-run regardless of how the run failed."""

    def setUp(self) -> None:
        super().setUp()
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()
        with sqlite3.connect(self._fake_live_db) as conn:
            conn.execute(_EVENTS_DDL)
            _seed_event(conn, headline="Live DB row — must not move")
            conn.commit()
        self._audit_path = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_{uuid.uuid4().hex}.jsonl",
        )
        self._backup_hash_before = _hash_file(Path(self._tmp))
        self._live_hash_before   = _hash_file(Path(self._fake_live_db))

    def tearDown(self) -> None:
        try:
            os.remove(self._audit_path)
        except (OSError, PermissionError):
            pass
        super().tearDown()

    def _assert_full_rollback_contract(
        self,
        result: dict,
        *,
        expected_error_substring: str,
    ) -> None:
        """Pin the rollback contract: ok=False, no claimed applies, no
        audit-log path, byte-identical backup and live DB.  The shared
        contract is asserted in one place so each failure-mode test
        focuses on triggering its specific failure."""
        self.assertFalse(result["ok"], msg=f"errors: {result['errors']}")
        self.assertTrue(
            any(expected_error_substring in e for e in result["errors"]),
            msg=(
                f"expected error containing {expected_error_substring!r} "
                f"in {result['errors']!r}"
            ),
        )
        self.assertEqual(result["applied_count"], 0)
        self.assertEqual(result["applied_event_ids"], [])
        self.assertIsNone(result["audit_log_path"])
        self.assertFalse(
            os.path.exists(self._audit_path),
            msg=(
                f"audit log unexpectedly created at {self._audit_path}"
            ),
        )
        self.assertIs(result["live_db_unchanged"], True)
        self.assertIs(result["input_backup_unchanged"], True)
        self.assertEqual(
            _hash_file(Path(self._tmp)), self._backup_hash_before,
        )
        self.assertEqual(
            _hash_file(Path(self._fake_live_db)), self._live_hash_before,
        )


class TestApplyDeleteFailureRollback(_FailurePathBase):
    def test_delete_failure_full_rollback_contract(self) -> None:
        # Inject a sqlite3.Error from inside ``_delete_in_chunks``.
        # The script must catch it, surface a "DELETE against temp
        # copy failed" error, and report applied_count=0 with no audit
        # log materialised — the temp copy is unlinked in the finally
        # clause, so the failed deletes never escape the private copy.
        with patch.object(
            apply_plan,
            "_delete_in_chunks",
            side_effect=sqlite3.OperationalError("simulated delete failure"),
        ):
            result = apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=True,
                audit_log_path=self._audit_path,
                live_db_path=self._fake_live_db,
            )
        self._assert_full_rollback_contract(
            result,
            expected_error_substring="DELETE against temp copy failed",
        )


class TestApplyAuditLogFailureRollback(_FailurePathBase):
    def test_audit_log_path_is_directory_full_rollback(self) -> None:
        # Pointing audit_log_path at an existing directory makes
        # ``audit_path.open("a")`` raise an OSError subclass
        # (IsADirectoryError on POSIX, PermissionError on Windows).
        # The exact subclass is platform-dependent; we only pin the
        # script's user-facing error string and the rollback contract.
        audit_dir = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_dir_{uuid.uuid4().hex}",
        )
        os.makedirs(audit_dir, exist_ok=True)
        try:
            result = apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=True,
                audit_log_path=audit_dir,
                live_db_path=self._fake_live_db,
            )
            # The shared rollback helper asserts no audit file was
            # created at ``self._audit_path`` (the unrelated .jsonl
            # path from setUp); the trigger directory itself is
            # expected to still exist as a directory afterwards.
            self._assert_full_rollback_contract(
                result,
                expected_error_substring="failed to write audit log",
            )
            self.assertTrue(
                os.path.isdir(audit_dir),
                msg=(
                    f"trigger directory {audit_dir} should still be a "
                    "directory after failure (writer must not have "
                    "converted it to a file)"
                ),
            )
        finally:
            try:
                os.rmdir(audit_dir)
            except (OSError, PermissionError):
                pass

    def test_audit_log_oserror_full_rollback(self) -> None:
        # Inject a generic OSError from ``_write_audit_log`` (full
        # disk, permission denied, etc.).  The DELETEs hit the temp
        # copy before the audit-log step, but the script's contract
        # is "applied_count=0 because we couldn't durably record the
        # action."  Pin that contract so it doesn't drift to
        # "applied_count=N with errors filled".
        def _boom(*_a, **_kw):
            raise OSError("simulated audit-log I/O failure")

        with patch.object(apply_plan, "_write_audit_log", side_effect=_boom):
            result = apply_plan.apply_against_temp_copy(
                backup_path=self._tmp,
                confirm=True,
                audit_log_path=self._audit_path,
                live_db_path=self._fake_live_db,
            )
        self._assert_full_rollback_contract(
            result,
            expected_error_substring="failed to write audit log",
        )


# ---------------------------------------------------------------------------
# CLI gate
# ---------------------------------------------------------------------------


class TestCliGate(_Base):
    def test_write_without_confirm_exits_two(self) -> None:
        out = StringIO()
        code = apply_plan.main(["--write", "--backup-path", self._tmp], out=out)
        self.assertEqual(code, 2)

    def test_write_confirm_without_backup_path_exits_two(self) -> None:
        out = StringIO()
        code = apply_plan.main(["--write", "--confirm"], out=out)
        self.assertEqual(code, 2)

    def test_write_alone_exits_two(self) -> None:
        out = StringIO()
        code = apply_plan.main(["--write"], out=out)
        self.assertEqual(code, 2)

    def test_dry_run_and_write_are_mutually_exclusive(self) -> None:
        # argparse handles the mutex group itself, exiting via
        # SystemExit(2) before our gate code runs.
        with self.assertRaises(SystemExit) as ctx:
            apply_plan.main(["--dry-run", "--write"])
        self.assertEqual(ctx.exception.code, 2)


# ---------------------------------------------------------------------------
# CLI dry-run plumbing
# ---------------------------------------------------------------------------


class TestCliDryRun(_Base):
    def test_default_no_flags_is_dry_run(self) -> None:
        out = StringIO()
        code = apply_plan.main(["--db-path", self._tmp], out=out)
        self.assertEqual(code, 0)
        self.assertIn("dry_run", out.getvalue())

    def test_explicit_dry_run_json_limit(self) -> None:
        # The verification command in the task spec.
        with self._conn() as conn:
            for _ in range(5):
                _seed_event(conn, headline="Macro shock test event")
            conn.commit()

        out = StringIO()
        code = apply_plan.main(
            ["--dry-run", "--json", "--limit", "20", "--db-path", self._tmp],
            out=out,
        )
        self.assertEqual(code, 0)
        payload = json.loads(out.getvalue())
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["candidate_count"], 5)
        self.assertEqual(
            payload["delete_preview"]["deduped_event_count"], 5,
        )
        self.assertEqual(payload["applied_count"], 0)
        self.assertIs(payload["confirm"], False)
        self.assertIsNone(payload["audit_log_path"])
        self.assertIsNone(payload["backup_path"])

    def test_dry_run_text_includes_marker(self) -> None:
        out = StringIO()
        code = apply_plan.main(["--dry-run", "--db-path", self._tmp], out=out)
        self.assertEqual(code, 0)
        text = out.getvalue()
        self.assertIn("apply plan", text.lower())
        self.assertIn("mode:", text)


# ---------------------------------------------------------------------------
# CLI write plumbing
# ---------------------------------------------------------------------------


class TestCliWriteFlow(_Base):
    def test_main_write_mode_routes_to_apply(self) -> None:
        # End-to-end: full write flow via main() against a seeded
        # backup.  Validates that the CLI gate accepts the trio and
        # surfaces a JSON payload with the write-mode shape.
        with self._conn() as conn:
            _seed_event(conn, headline="Macro shock test event")
            conn.commit()

        audit_path = os.path.join(
            tempfile.gettempdir(),
            f"test_acap_audit_{uuid.uuid4().hex}.jsonl",
        )
        try:
            out = StringIO()
            code = apply_plan.main(
                [
                    "--write", "--confirm",
                    "--backup-path", self._tmp,
                    "--audit-log-path", audit_path,
                    "--live-db", self._fake_live_db,
                    "--json",
                ],
                out=out,
            )
            self.assertEqual(code, 0)
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["mode"], "write_temp_copy")
            self.assertIs(payload["confirm"], True)
            self.assertEqual(payload["applied_count"], 1)
            self.assertEqual(payload["audit_log_path"], audit_path)
            self.assertTrue(os.path.exists(audit_path))
        finally:
            try:
                os.remove(audit_path)
            except (OSError, PermissionError):
                pass


# ---------------------------------------------------------------------------
# Source pins
# ---------------------------------------------------------------------------


class TestSourcePins(unittest.TestCase):
    def setUp(self) -> None:
        self._src = Path(apply_plan.__file__).read_text(encoding="utf-8")

    def test_module_source_does_not_import_db_module(self) -> None:
        # The apply path must never reach into the project's writable
        # in-process DB constant.  The candidate-report's lazy
        # ``import db`` for the dry-run default path is contained in
        # the upstream module — we never import it here.
        for pat in (
            r"^\s*import\s+db\b",
            r"^\s*from\s+db\s+import",
        ):
            self.assertIsNone(
                re.search(pat, self._src, flags=re.MULTILINE),
                f"forbidden db import pattern {pat!r} in apply-plan module",
            )

    def test_module_source_does_not_import_paid_seams(self) -> None:
        for pat in (
            r"^\s*import\s+yfinance\b",
            r"^\s*from\s+yfinance\b",
            r"^\s*import\s+market_check\b",
            r"^\s*from\s+market_check\b",
            r"^\s*import\s+market_data\b",
            r"^\s*from\s+market_data\b",
            r"^\s*import\s+price_cache\b",
            r"^\s*from\s+price_cache\b",
            r"^\s*from\s+anthropic\b",
            r"^\s*import\s+anthropic\b",
            r"^\s*import\s+openai\b",
            r"^\s*from\s+openai\b",
            r"^\s*import\s+api\b",
            r"^\s*from\s+api\b",
            r"^\s*from\s+routes\.",
            r"^\s*import\s+routes\.",
            r"^\s*from\s+analyze_event\b",
            r"^\s*import\s+analyze_event\b",
        ):
            self.assertIsNone(
                re.search(pat, self._src, flags=re.MULTILINE),
                f"forbidden import pattern {pat!r} in apply-plan module",
            )

    def test_module_source_has_no_destructive_sql_outside_temp_delete(self) -> None:
        # The only DELETE in this module is the temp-copy DELETE
        # against the events table (issued via parametrised SQL inside
        # ``_delete_in_chunks``).  No UPDATE / INSERT / DROP / ALTER /
        # TRUNCATE statements are permitted.
        forbidden = (
            r"\bUPDATE\s+\w+\s+SET\b",
            r"\bINSERT\s+INTO\b",
            r"\bDROP\s+TABLE\b",
            r"\bTRUNCATE\s+TABLE\b",
            r"\bALTER\s+TABLE\b",
        )
        for pat in forbidden:
            self.assertIsNone(
                re.search(pat, self._src, flags=re.IGNORECASE),
                f"forbidden destructive SQL {pat!r} in apply-plan module",
            )

    def test_module_source_only_filesystem_destructor_is_temp_unlink(self) -> None:
        # ``shutil.rmtree`` and ``os.remove`` are forbidden — the only
        # filesystem destructor permitted is ``Path.unlink`` against
        # the temp copy (resolved at runtime, never against an
        # operator-visible path).
        for pat in (
            r"\bos\.remove\s*\(",
            r"\bshutil\.rmtree\s*\(",
            r"\bos\.unlink\s*\(",
        ):
            self.assertIsNone(
                re.search(pat, self._src),
                f"forbidden filesystem destructor {pat!r} in apply-plan module",
            )


# ---------------------------------------------------------------------------
# Live archive sanity — opt-in
# ---------------------------------------------------------------------------


class TestLiveArchiveSanity(unittest.TestCase):
    """If the project's ``events.db`` is present, the dry-run plan must
    run against it without raising and produce a well-formed payload.
    Skipped when the DB file is absent so CI stays portable.

    Live DB is opened read-only via the candidate-report SELECT chain;
    no events.db hash check is exercised here (write-mode tests cover
    that).
    """

    def setUp(self) -> None:
        self._project_root = Path(__file__).resolve().parents[1]
        self._db = self._project_root / "events.db"
        if not self._db.exists():
            self.skipTest(f"no live archive at {self._db}")

    def test_live_archive_dry_run_well_formed(self) -> None:
        before = self._db.stat().st_mtime
        result = apply_plan.build_apply_plan(db_path=str(self._db))
        for key in _DRY_RUN_TOP_KEYS:
            self.assertIn(key, result)
        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(
            result["delete_preview"]["deduped_event_count"],
            result["candidate_count"],
        )
        # The dry-run is read-only; mtime must not move.
        self.assertEqual(self._db.stat().st_mtime, before)


if __name__ == "__main__":
    unittest.main()
