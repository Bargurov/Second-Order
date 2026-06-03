"""E1 (H9) — event_hygiene OVERRIDE sidecar (schema + derive-on-read; no writer).

Branch 1 of the H8 scoping: the authoritative hygiene classification is
DERIVED ON READ by ``data_hygiene_report.derive_event_hygiene``; the sidecar
persists ONLY non-derivable curatorial overrides. Covers:

* table + the four override-only columns exist after ``init_db``, with PK +
  NOT NULL constraints actually enforced;
* ``override_class`` carries NO SQL CHECK (vocabulary enforced in the future
  write layer, per the event_provenance precedent);
* ``init_db`` is idempotent (override rows survive a second init_db);
* a legacy event with no sidecar row reads as ``None`` via get_event_hygiene
  (no row -> derived heuristic default);
* ``derive_event_hygiene`` classifies synthetic_seed / synthetic_test /
  real_unique / real_duplicate by headline + model + duplicate context, never
  by ticker, and maps the full derived view; an operator override wins, an
  invalid override is ignored.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import db  # noqa: E402
from scripts import data_hygiene_report as report  # noqa: E402

REAL_MODEL = "claude-sonnet-4-20250514"


def _ev(eid, headline, model=REAL_MODEL, event_date="2026-04-10"):
    return {"id": eid, "headline": headline, "model": model, "event_date": event_date}


class EventHygieneSchemaTest(unittest.TestCase):
    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_event_hyg_{uuid.uuid4().hex}.db"
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _insert_event(self, conn, headline="legacy event"):
        cur = conn.execute(
            "INSERT INTO events (timestamp, headline, stage, persistence) "
            "VALUES (?, ?, ?, ?)",
            ("2026-04-10T00:00:00Z", headline, "realized", "structural"),
        )
        return int(cur.lastrowid)

    def test_table_exists(self):
        with db.connect_db() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='event_hygiene'"
            ).fetchone()
        self.assertIsNotNone(row, "event_hygiene table missing after init_db")

    def test_columns_and_constraints(self):
        with db.connect_db() as conn:
            info = conn.execute("PRAGMA table_info(event_hygiene)").fetchall()
        by = {r[1]: r for r in info}  # (cid, name, type, notnull, dflt, pk)
        self.assertEqual(
            set(by), {"event_id", "override_class", "override_reason", "created_at"}
        )
        self.assertEqual(by["event_id"][5], 1, "event_id must be PRIMARY KEY")
        self.assertEqual(by["created_at"][3], 1, "created_at must be NOT NULL")
        self.assertEqual(by["override_class"][3], 0, "override_class must be nullable")
        self.assertEqual(by["override_reason"][3], 0, "override_reason must be nullable")

    def test_override_class_has_no_sql_check(self):
        # Branch 1: vocabulary enforced in the future write layer, not a CHECK.
        with db.connect_db() as conn:
            ev = self._insert_event(conn)
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, created_at) "
                "VALUES (?, ?, ?)",
                (ev, "some_future_value", "2026-06-03T00:00:00Z"),
            )
            conn.commit()
            stored = conn.execute(
                "SELECT override_class FROM event_hygiene WHERE event_id=?", (ev,)
            ).fetchone()[0]
        self.assertEqual(stored, "some_future_value")

    def test_created_at_not_null_enforced(self):
        with db.connect_db() as conn:
            ev = self._insert_event(conn)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO event_hygiene (event_id, override_class, created_at) "
                    "VALUES (?, ?, ?)",
                    (ev, "real_unique", None),
                )

    def test_init_db_idempotent(self):
        with db.connect_db() as conn:
            ev = self._insert_event(conn)
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, created_at) "
                "VALUES (?, ?, ?)",
                (ev, "real_unique", "2026-06-03T00:00:00Z"),
            )
            conn.commit()
        db.init_db()  # second call must not drop the table or its rows
        with db.connect_db() as conn:
            n = conn.execute("SELECT COUNT(*) FROM event_hygiene").fetchone()[0]
        self.assertEqual(n, 1, "init_db must not wipe existing override rows")

    def test_get_event_hygiene_roundtrip_and_none_for_legacy(self):
        with db.connect_db() as conn:
            ev = self._insert_event(conn)
            conn.execute(
                "INSERT INTO event_hygiene "
                "(event_id, override_class, override_reason, created_at) "
                "VALUES (?, ?, ?, ?)",
                (ev, "real_unique", "operator says real", "2026-06-03T00:00:00Z"),
            )
            legacy = self._insert_event(conn, "no sidecar row")
            conn.commit()
        got = db.get_event_hygiene(ev)
        self.assertEqual(got["override_class"], "real_unique")
        self.assertEqual(got["override_reason"], "operator says real")
        self.assertIsNone(db.get_event_hygiene(legacy), "legacy event has no row")


class DeriveEventHygieneTest(unittest.TestCase):
    def test_synthetic_seed(self):
        d = report.derive_event_hygiene(_ev(1, "OPEC slashes output by 2 mbpd"))
        self.assertEqual(d["hygiene_class"], "synthetic_seed")
        self.assertTrue(d["is_synthetic"])
        self.assertEqual(d["source_type"], "seed")
        self.assertTrue(d["excluded_from_research_denominator"])
        self.assertEqual(d["exclusion_reason"], "synthetic_seed")
        self.assertIsNone(d["canonical_event_id"])
        self.assertIn("data_hygiene_report", d["classification_basis"])

    def test_synthetic_test_by_headline_and_by_model(self):
        for ev in (_ev(1, "Macro shock test event"), _ev(2, "Anything", model="test-model")):
            d = report.derive_event_hygiene(ev)
            self.assertEqual(d["hygiene_class"], "synthetic_test")
            self.assertEqual(d["source_type"], "test")
            self.assertTrue(d["is_synthetic"])
            self.assertTrue(d["excluded_from_research_denominator"])
            self.assertEqual(d["exclusion_reason"], "synthetic_test_artifact")

    def test_real_unique_default_without_context(self):
        d = report.derive_event_hygiene(
            _ev(1, "AP News: OPEC members discuss extending output cuts")
        )
        self.assertEqual(d["hygiene_class"], "real_unique")
        self.assertFalse(d["is_synthetic"])
        self.assertFalse(d["excluded_from_research_denominator"])
        self.assertIsNone(d["exclusion_reason"])
        self.assertEqual(d["source_type"], "real_ingested")

    def test_real_duplicate_redundant_copy_with_context(self):
        ctx = {"AP News: OPEC members discuss extending output cuts"}
        d = report.derive_event_hygiene(
            _ev(54, "AP News: OPEC members discuss extending output cuts"),
            duplicate_headlines=ctx, canonical_event_id=39,
        )
        self.assertEqual(d["hygiene_class"], "real_duplicate")
        self.assertTrue(d["excluded_from_research_denominator"])
        self.assertEqual(d["exclusion_reason"], "duplicate_headline")
        self.assertEqual(d["canonical_event_id"], 39)

    def test_real_duplicate_canonical_row_not_excluded(self):
        ctx = {"AP News: OPEC members discuss extending output cuts"}
        d = report.derive_event_hygiene(
            _ev(39, "AP News: OPEC members discuss extending output cuts"),
            duplicate_headlines=ctx, canonical_event_id=39,
        )
        self.assertEqual(d["hygiene_class"], "real_duplicate")
        self.assertFalse(d["excluded_from_research_denominator"])
        self.assertIsNone(d["exclusion_reason"])

    def test_operator_override_wins(self):
        d = report.derive_event_hygiene(
            _ev(1, "OPEC slashes output by 2 mbpd"),
            sidecar={"override_class": "real_unique", "override_reason": "curated"},
        )
        self.assertEqual(d["hygiene_class"], "real_unique")
        self.assertFalse(d["is_synthetic"])
        self.assertEqual(d["classification_basis"], "operator_override")

    def test_invalid_override_is_ignored(self):
        d = report.derive_event_hygiene(
            _ev(1, "OPEC slashes output by 2 mbpd"),
            sidecar={"override_class": "garbage"},
        )
        self.assertEqual(d["hygiene_class"], "synthetic_seed")
        self.assertIn("data_hygiene_report", d["classification_basis"])

    def test_ticker_absence_is_irrelevant(self):
        # A real macro headline with no ticker is real, not synthetic — derive
        # never consults tickers.
        d = report.derive_event_hygiene(_ev(1, "Bank of England faces difficulty"))
        self.assertEqual(d["hygiene_class"], "real_unique")
        self.assertFalse(d["is_synthetic"])


if __name__ == "__main__":
    unittest.main()
