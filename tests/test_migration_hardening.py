"""
tests/test_migration_hardening.py

Migration discipline for ``db.init_db``.

The schema-upgrade loop runs an ``ALTER TABLE ADD COLUMN`` for every
optional column added since the original v3 schema.  Each statement is
wrapped in ``try / except sqlite3.OperationalError`` so re-running
``init_db`` against an already-migrated database is idempotent —
SQLite raises "duplicate column name" and the loop continues.

Before this hardening, *any* ``OperationalError`` was swallowed: a
syntax error, a locked database, a missing dependent table — all
silently logged as warnings, leaving the runtime convinced the schema
was complete when it was not.  Read paths would later crash on a
column that didn't actually get added.

These tests lock in:
  1. Re-running ``init_db`` against a current schema is a clean
     no-op (every ``ADD COLUMN`` raises duplicate-column, all
     tolerated).
  2. A non-duplicate ``OperationalError`` raised inside the migration
     loop propagates — the runtime never starts on a half-upgraded DB.
  3. After re-init, an old row saved before the second init still
     decodes back with its proof_status / falsifier_status defaults
     intact (no row corruption, no field drift).
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import _decode_event_row, init_db, save_event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_event(headline: str = "headline") -> dict:
    return {
        "headline":          headline,
        "stage":              "test",
        "persistence":        "1d",
        "what_changed":       "x",
        "mechanism_summary":  "y",
        "beneficiaries":      ["A"],
        "losers":             ["B"],
        "assets_to_watch":    [],
        "confidence":         "medium",
        "market_note":        "",
        "market_tickers":     [],
        "event_date":         "2025-01-15",
        "notes":              "",
        "model":              "test-model",
    }


class _IsolatedDbTestCase(unittest.TestCase):
    """Each test runs against a fresh temporary SQLite file."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db = db_module.DB_FILE
        db_module.DB_FILE = self._tmp.name
        db_module._db_ready = False

    def tearDown(self) -> None:
        db_module.DB_FILE = self._orig_db
        db_module._db_ready = False
        try:
            os.unlink(self._tmp.name)
        except (PermissionError, OSError):
            pass


# ---------------------------------------------------------------------------
# Connection wrapper that injects an OperationalError on a chosen SQL
# ---------------------------------------------------------------------------


class _RaisingConn:
    """Proxy around a real sqlite3 connection that raises a chosen
    ``OperationalError`` the first time ``execute`` is called with SQL
    matching ``raise_pattern``.  Every other call delegates to the
    real connection so the rest of ``init_db`` can run normally.
    """

    def __init__(
        self,
        real: sqlite3.Connection,
        *,
        raise_pattern: str,
        raise_message: str,
    ) -> None:
        self._real = real
        self._raise_pattern = raise_pattern
        self._raise_message = raise_message
        self._fired = False

    def execute(self, sql: str, *args, **kwargs):
        if (
            not self._fired
            and self._raise_pattern in sql
        ):
            self._fired = True
            raise sqlite3.OperationalError(self._raise_message)
        return self._real.execute(sql, *args, **kwargs)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._real.__exit__(exc_type, exc, tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


# ---------------------------------------------------------------------------
# 1. Duplicate-column tolerated on re-init
# ---------------------------------------------------------------------------


class DuplicateColumnToleratedTests(_IsolatedDbTestCase):

    def test_re_init_is_a_clean_noop(self) -> None:
        """First init creates the schema; second init re-runs every
        ``ADD COLUMN`` and must tolerate every duplicate-column error
        without raising."""
        init_db()
        self.assertTrue(db_module._db_ready)

        # Reset the ready flag so we can observe the second init's
        # success path (init_db() resets it to False on entry too).
        db_module._db_ready = False
        try:
            init_db()
        except Exception as exc:  # noqa: BLE001
            self.fail(
                f"Re-running init_db on a current schema raised "
                f"unexpectedly: {exc!r}",
            )
        self.assertTrue(db_module._db_ready)

    def test_re_init_preserves_existing_rows(self) -> None:
        """Idempotency must not destroy data."""
        init_db()
        save_event(_minimal_event(headline="row from first init"))

        db_module._db_ready = False
        init_db()  # second init — must not wipe rows

        with sqlite3.connect(db_module.DB_FILE) as conn:
            (count,) = conn.execute(
                "SELECT COUNT(*) FROM events",
            ).fetchone()
        self.assertEqual(count, 1)


# ---------------------------------------------------------------------------
# 2. Non-duplicate OperationalError must propagate
# ---------------------------------------------------------------------------


class NonDuplicateMigrationErrorRaisesTests(_IsolatedDbTestCase):
    """When a real DDL failure occurs inside the migration loop, the
    runtime must NOT silently continue with a half-upgraded schema."""

    def _patched_connect(self, *, raise_on: str, message: str):
        """Return a patched ``sqlite3.connect`` that wraps every
        connection so the chosen ALTER pattern raises on first match."""
        real_connect = sqlite3.connect

        def factory(*args, **kwargs):
            real = real_connect(*args, **kwargs)
            return _RaisingConn(
                real, raise_pattern=raise_on, raise_message=message,
            )
        return factory

    def test_non_duplicate_alter_failure_propagates(self) -> None:
        # Pick a pattern that appears in exactly one migration ALTER —
        # use ``policy_constraint`` because it's a column unique to
        # this table and unlikely to collide with helper SQL.
        patched = self._patched_connect(
            raise_on="policy_constraint",
            message="simulated DDL failure on policy_constraint",
        )
        with patch.object(db_module.sqlite3, "connect", patched):
            with self.assertRaises(sqlite3.OperationalError) as ctx:
                init_db()
        self.assertIn("simulated DDL failure", str(ctx.exception))
        # ``init_db`` resets ``_db_ready`` to False on entry; if the
        # migration raises, the flag must stay False so callers don't
        # treat the half-upgraded DB as usable.
        self.assertFalse(db_module._db_ready)

    def test_locked_database_error_propagates(self) -> None:
        """Real-world failure mode — ``database is locked`` is an
        ``OperationalError`` that does NOT contain "duplicate column".
        The loop must surface it loudly."""
        patched = self._patched_connect(
            raise_on="real_yield_context",
            message="database is locked",
        )
        with patch.object(db_module.sqlite3, "connect", patched):
            with self.assertRaises(sqlite3.OperationalError) as ctx:
                init_db()
        self.assertIn("database is locked", str(ctx.exception))
        self.assertFalse(db_module._db_ready)

    def test_duplicate_column_error_still_tolerated_under_patch(self) -> None:
        """Sanity check on the wrapper: the wrapper itself must not
        accidentally short-circuit when a real duplicate-column error
        is raised by SQLite during a re-init.  We trigger that by
        running ``init_db`` twice with the wrapper passive (raise on
        a pattern that never appears)."""
        patched = self._patched_connect(
            raise_on="__pattern_that_never_appears__",
            message="should never fire",
        )
        with patch.object(db_module.sqlite3, "connect", patched):
            init_db()
            db_module._db_ready = False
            init_db()  # idempotent
        self.assertTrue(db_module._db_ready)


# ---------------------------------------------------------------------------
# 3. Old-row load still stable after re-init
# ---------------------------------------------------------------------------


class OldRowStabilityTests(_IsolatedDbTestCase):
    """After a successful re-init, a row written before the re-init
    must still decode back with the proof_status / falsifier_status
    defaults guaranteed by ``_coerce_status_block``."""

    def test_round_trip_after_re_init(self) -> None:
        init_db()
        save_event(_minimal_event(headline="before re-init"))

        db_module._db_ready = False
        init_db()  # second pass — must not corrupt the row

        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        ev = _decode_event_row(row)

        self.assertEqual(ev["headline"], "before re-init")
        # proof_status / falsifier_status decode to dicts (possibly
        # empty); when populated, ``items`` is always a list — the
        # contract from _coerce_status_block must survive re-init.
        for field in ("proof_status", "falsifier_status"):
            block = ev[field]
            self.assertIsInstance(block, dict)
            if block:
                self.assertIsInstance(block.get("items"), list)


if __name__ == "__main__":
    unittest.main()
