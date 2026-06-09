"""AP3a — event_hygiene ``synthetic_seed`` exclusion from accepted-corpus denominators.

A row flagged ``override_class='synthetic_seed'`` in the ``event_hygiene`` sidecar
is a synthetic/test seed (AP2): it must STAY in the archive (retrievable by id)
but be EXCLUDED from every accepted-corpus denominator — track-record, the
event-study coverage / analysis denominator, the diagnostics-route mirrors, and
the viewer breakdown.  ``stage='realized'`` alone is no longer sufficient for
accepted-corpus inclusion once such an override exists.

Empty ``event_hygiene`` MUST preserve current behavior (the whole live system is
unchanged until the AP3b data write).  Only ``synthetic_seed`` excludes; other
override classes do not.

Read-only / temp-DB only: every test builds a throwaway events.db; the live
archive is never touched.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
import uuid

import api  # noqa: F401 — import first to resolve the api<->diagnostics cycle
import db
from routes import diagnostics as diag
from scripts import event_study_coverage_report as cov
from track_record_breakdown import compute_track_record_breakdown

_SUPPORTS = '[{"symbol": "AAA", "role": "beneficiary", "direction_tag": "supports up", "return_1d": 1.0}]'


class SyntheticSeedHygieneExclusionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_synth_hyg_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _insert_event(self, *, stage="realized", market_tickers=_SUPPORTS,
                      mechanism_family="tariff") -> int:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date, mechanism_family) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("2018-03-08T12:00:00", f"event-{uuid.uuid4().hex[:8]}", stage,
                 "medium", market_tickers, "2018-03-08", mechanism_family),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _flag(self, event_id: int, override_class="synthetic_seed") -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, override_reason, created_at) "
                "VALUES (?, ?, ?, ?)",
                (event_id, override_class, "AP2 synthetic seed", "2026-06-09T00:00:00"),
            )
            conn.commit()

    # ----- the single exclusion-source helper -----------------------------
    def test_synthetic_seed_ids_helper(self) -> None:
        a = self._insert_event()
        b = self._insert_event()
        self._flag(b)
        self.assertEqual(db.synthetic_seed_ids(), frozenset({b}))
        self.assertNotIn(a, db.synthetic_seed_ids())

    # ----- denominators EXCLUDE a synthetic_seed row ----------------------
    def test_track_record_excludes_synthetic_seed(self) -> None:
        self._insert_event()                     # real, scores
        synth = self._insert_event(); self._flag(synth)
        self.assertEqual(db.compute_track_record()["total"], 1)

    def test_coverage_loader_excludes_synthetic_seed(self) -> None:
        real = self._insert_event()
        synth = self._insert_event(); self._flag(synth)
        events, excluded = cov._load_events(self._tmp)
        ids = [e["id"] for e in events]
        self.assertIn(real, ids)
        self.assertNotIn(synth, ids)

    def test_diag_track_record_excludes_synthetic_seed(self) -> None:
        self._insert_event()
        synth = self._insert_event(); self._flag(synth)
        self.assertEqual(diag._compute_track_record()["total_events"], 1)

    def test_diag_validation_status_excludes_synthetic_seed(self) -> None:
        self._insert_event()
        synth = self._insert_event(); self._flag(synth)
        self.assertEqual(diag._compute_validation_status_stats()["total_events"], 1)

    def test_diag_archive_aggregates_excludes_synthetic_seed(self) -> None:
        self._insert_event()
        synth = self._insert_event(); self._flag(synth)
        counts = diag._compute_archive_aggregates()["events_by_thesis_state"]["counts"]
        self.assertEqual(sum(counts.values()), 1)

    def test_breakdown_excludes_synthetic_seed(self) -> None:
        self._insert_event(mechanism_family="tariff")
        synth = self._insert_event(mechanism_family="tariff"); self._flag(synth)
        events = db.load_recent_events(limit=500)
        bd = compute_track_record_breakdown(events)
        self.assertEqual(sum(g["total"] for g in bd["by_mechanism_family"]), 1)

    # ----- archive retrieval stays intact ---------------------------------
    def test_synthetic_seed_row_still_retrievable_by_id(self) -> None:
        synth = self._insert_event(); self._flag(synth)
        row = db.load_event_by_id(synth)
        self.assertIsNotNone(row)
        self.assertEqual(row["id"], synth)

    # ----- empty / other-class invariants ---------------------------------
    def test_empty_hygiene_preserves_behavior(self) -> None:
        self._insert_event(); self._insert_event()
        self.assertEqual(db.synthetic_seed_ids(), frozenset())
        self.assertEqual(db.compute_track_record()["total"], 2)  # both counted

    def test_non_synthetic_override_class_not_excluded(self) -> None:
        a = self._insert_event()
        b = self._insert_event(); self._flag(b, override_class="duplicate_copy")
        self.assertEqual(db.synthetic_seed_ids(), frozenset())
        self.assertEqual(db.compute_track_record()["total"], 2)  # neither excluded


class SyntheticSeedDriftValidatorTest(unittest.TestCase):
    """Read-only drift validator over a DB path (AP3a step 4)."""

    def setUp(self) -> None:
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_synth_drift_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _insert(self, stage="realized") -> int:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date, mechanism_family) VALUES (?,?,?,?,?,?,?)",
                ("2018-03-08T12:00:00", f"e-{uuid.uuid4().hex[:8]}", stage,
                 "medium", _SUPPORTS, "2018-03-08", "tariff"),
            )
            conn.commit()
            return int(cur.lastrowid)

    def _flag(self, eid) -> None:
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene (event_id, override_class, override_reason, created_at) "
                "VALUES (?, 'synthetic_seed', 'AP2', '2026-06-09T00:00:00')", (eid,),
            )
            conn.commit()

    def test_validator_reports_clean_exclusion(self) -> None:
        from tools import synthetic_seed_hygiene_validation as v
        self._insert()                       # real
        synth = self._insert(); self._flag(synth)
        rep = v.validate(db_path=self._tmp)
        self.assertEqual(rep["synthetic_seed_count"], 1)
        self.assertIn(synth, rep["synthetic_seed_ids"])
        self.assertEqual(rep["leaked_into_accepted"], [])   # none counted as accepted
        self.assertEqual(rep["not_retrievable"], [])        # still in archive
        self.assertTrue(rep["ok"])

    def test_validator_ok_when_no_flags(self) -> None:
        from tools import synthetic_seed_hygiene_validation as v
        self._insert()
        rep = v.validate(db_path=self._tmp)
        self.assertEqual(rep["synthetic_seed_count"], 0)
        self.assertTrue(rep["ok"])


if __name__ == "__main__":
    unittest.main()
