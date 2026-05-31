"""D1A — event_provenance schema (schema only; no writer/intake).

Covers the contract for the minimal provenance table that lets FUTURE
source-anchored events carry provenance without retroactively upgrading
historical rows:

* table + required columns exist after ``init_db`` (with NOT NULL / PK
  constraints actually enforced, not just column names present);
* the ``source_url`` index exists and is on ``source_url``;
* ``init_db`` is idempotent (re-running keeps the table and its rows);
* a legacy event with no provenance row reads as ``unrecorded``;
* ``provenance_status`` is DERIVED ON READ — source_anchored / partial /
  unanchored — never stored;
* ``mechanism_label_provenance`` NOT NULL is enforced, and D1A
  deliberately does NOT lock a value vocabulary (deferred to the D1B
  write layer), so an arbitrary non-empty label is accepted.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import uuid

import db


# Minimal valid provenance payload — all NOT NULL fields present, so a
# rejection in the vocabulary test can ONLY come from the field under test.
def _full_provenance_row(event_id: int, **overrides):
    row = {
        "event_id":                    event_id,
        "source_type":                 "federal_register",
        "source_publisher":            "USTR (Federal Register)",
        "source_url":                  "https://www.federalregister.gov/d/2025-1",
        "source_published_at":         "2025-03-13",
        "mechanism_label_provenance":  "curated",
        "intake_path":                 "manual",
        "created_at":                  "2026-05-31T00:00:00Z",
    }
    row.update(overrides)
    return row


def _insert_provenance(conn, row):
    cols = ", ".join(row.keys())
    qs = ", ".join("?" for _ in row)
    conn.execute(
        f"INSERT INTO event_provenance ({cols}) VALUES ({qs})",
        tuple(row.values()),
    )


def _insert_event(conn, headline="legacy event") -> int:
    cur = conn.execute(
        "INSERT INTO events (timestamp, headline, stage, persistence) "
        "VALUES (?, ?, ?, ?)",
        ("2026-05-31T00:00:00Z", headline, "stage_1", "structural"),
    )
    return int(cur.lastrowid)


class EventProvenanceSchemaTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_event_prov_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    # ----- table + columns ------------------------------------------------
    def test_event_provenance_table_exists(self) -> None:
        with db.connect_db() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='event_provenance'"
            ).fetchone()
        self.assertIsNotNone(row, "event_provenance table missing after init_db")

    def test_required_columns_exist_with_constraints(self) -> None:
        with db.connect_db() as conn:
            info = conn.execute("PRAGMA table_info(event_provenance)").fetchall()
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        by_name = {r[1]: r for r in info}
        expected = {
            "event_id", "source_type", "source_publisher", "source_url",
            "source_published_at", "mechanism_label_provenance",
            "intake_path", "created_at",
        }
        self.assertEqual(set(by_name), expected)

        # event_id is the primary key.
        self.assertEqual(by_name["event_id"][5], 1, "event_id must be PRIMARY KEY")

        # NOT NULL is actually enforced on the required fields.
        for col in ("source_type", "mechanism_label_provenance",
                    "intake_path", "created_at"):
            self.assertEqual(by_name[col][3], 1, f"{col} must be NOT NULL")

        # The optional source fields stay nullable (legacy / partial rows).
        for col in ("source_publisher", "source_url", "source_published_at"):
            self.assertEqual(by_name[col][3], 0, f"{col} must be nullable")

    def test_source_url_index_exists(self) -> None:
        with db.connect_db() as conn:
            idx_rows = conn.execute(
                "PRAGMA index_list(event_provenance)"
            ).fetchall()
            names = {r[1] for r in idx_rows}
            self.assertIn("idx_event_provenance_source_url", names)
            cols = [
                r[2] for r in conn.execute(
                    "PRAGMA index_info(idx_event_provenance_source_url)"
                ).fetchall()
            ]
        self.assertEqual(cols, ["source_url"])

    # ----- idempotency ----------------------------------------------------
    def test_init_db_idempotent(self) -> None:
        # A row written before a second init_db must survive (IF NOT EXISTS
        # must not drop/recreate the table).
        with db.connect_db() as conn:
            ev = _insert_event(conn)
            _insert_provenance(conn, _full_provenance_row(ev))
            conn.commit()

        db.init_db()  # second call — must be a no-op for existing schema/data

        with db.connect_db() as conn:
            tables = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type='table' AND name='event_provenance'"
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT COUNT(*) FROM event_provenance"
            ).fetchone()[0]
        self.assertEqual(tables, 1)
        self.assertEqual(rows, 1, "init_db must not wipe existing provenance rows")

    # ----- legacy behavior ------------------------------------------------
    def test_legacy_event_without_provenance_reads_unrecorded(self) -> None:
        with db.connect_db() as conn:
            ev = _insert_event(conn, "legacy with no provenance")
            conn.commit()
        # No provenance row was written for this legacy event.
        self.assertIsNone(db.get_event_provenance(ev))
        self.assertEqual(db.provenance_status_for_event(ev), "unrecorded")

    # ----- derived-on-read status ----------------------------------------
    def test_provenance_status_source_anchored(self) -> None:
        prov = _full_provenance_row(1)  # has url + published_at
        self.assertEqual(db.derive_provenance_status(prov), "source_anchored")

    def test_provenance_status_partial_url_only(self) -> None:
        prov = _full_provenance_row(1, source_published_at=None)
        self.assertEqual(db.derive_provenance_status(prov), "partial")

    def test_provenance_status_partial_published_only(self) -> None:
        prov = _full_provenance_row(1, source_url=None)
        self.assertEqual(db.derive_provenance_status(prov), "partial")

    def test_provenance_status_unanchored(self) -> None:
        prov = _full_provenance_row(1, source_url=None, source_published_at=None)
        self.assertEqual(db.derive_provenance_status(prov), "unanchored")

    def test_provenance_status_unrecorded_when_no_row(self) -> None:
        self.assertEqual(db.derive_provenance_status(None), "unrecorded")

    def test_derive_accepts_sqlite_row(self) -> None:
        # The helper must accept a sqlite3.Row (no .get()) as well as a dict.
        with db.connect_db() as conn:
            ev = _insert_event(conn)
            _insert_provenance(conn, _full_provenance_row(ev))
            conn.commit()
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM event_provenance WHERE event_id=?", (ev,)
            ).fetchone()
        self.assertEqual(db.derive_provenance_status(row), "source_anchored")

    # ----- vocabulary contract (no CHECK in D1A) --------------------------
    def test_mechanism_label_provenance_not_null_enforced(self) -> None:
        with db.connect_db() as conn:
            ev = _insert_event(conn)
            with self.assertRaises(sqlite3.IntegrityError):
                _insert_provenance(
                    conn, _full_provenance_row(ev, mechanism_label_provenance=None)
                )

    def test_mechanism_label_provenance_vocabulary_unconstrained_in_d1a(self) -> None:
        # D1A is schema-only: it deliberately does NOT lock a value enum via
        # CHECK (no grounded taxonomy exists yet; enforcement belongs to the
        # D1B write layer).  An arbitrary non-empty label must be accepted.
        with db.connect_db() as conn:
            ev = _insert_event(conn)
            _insert_provenance(
                conn, _full_provenance_row(ev, mechanism_label_provenance="some_future_value")
            )
            conn.commit()
            stored = conn.execute(
                "SELECT mechanism_label_provenance FROM event_provenance WHERE event_id=?",
                (ev,),
            ).fetchone()[0]
        self.assertEqual(stored, "some_future_value")


if __name__ == "__main__":
    unittest.main()
