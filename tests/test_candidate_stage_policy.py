"""AB1 Lane A — candidate-only stage policy (``z1a_candidate_pack``).

A ``z1a_candidate_pack`` row is a *candidate-only* staging stub produced by the
Z1B copy-ingest harness for copy-side measurement.  It is NOT an analyzed live
event: it carries no LLM thesis and is not part of the curated archive.  The
policy this file pins:

  * ``z1a_candidate_pack`` ∈ ``NON_ANALYSIS_STAGES`` (⊂ ``NON_THESIS_STAGES``) —
    so it never inflates the event-study coverage denominator, the data-hygiene
    analysis-stage total, or the scored track-record.
  * It is a *candidate-only* stage (``CANDIDATE_ONLY_STAGES``) — a category
    distinct from ``curated_intake`` (a real, if thesis-less, archived stub) so
    the default ``/events`` listing can hide candidates without touching
    curated rows.

Existing ``curated_intake`` / ``curated_observation`` behaviour is unchanged;
those contracts stay pinned in ``test_curated_observation_stage_split.py``.

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
from scripts import event_study_coverage_report as cov


_SUPPORTS = '[{"symbol": "AAA", "role": "beneficiary", "direction_tag": "supports up", "return_1d": 1.0}]'
_PRIMARY_ONLY = '[{"symbol": "TGT", "role": "primary"}]'


class CandidateStagePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_file = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_cand_stage_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db_file
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _insert_event(
        self, *, stage: str, market_tickers: str = "[]",
        mechanism_family: str = "tariff", event_date: str = "2018-03-08",
        persistence: str = "medium",
    ) -> int:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date, mechanism_family) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "2018-03-08T12:00:00",
                    f"event-{uuid.uuid4().hex[:8]}",
                    stage, persistence, market_tickers, event_date,
                    mechanism_family,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    # ----- constants ------------------------------------------------------
    def test_candidate_pack_stage_constant(self) -> None:
        self.assertEqual(db.CANDIDATE_PACK_STAGE, "z1a_candidate_pack")

    def test_candidate_only_stages_constant(self) -> None:
        self.assertEqual(db.CANDIDATE_ONLY_STAGES, frozenset({"z1a_candidate_pack"}))

    def test_candidate_in_non_analysis_stages(self) -> None:
        self.assertIn(db.CANDIDATE_PACK_STAGE, db.NON_ANALYSIS_STAGES)

    def test_candidate_in_non_thesis_stages(self) -> None:
        self.assertIn(db.CANDIDATE_PACK_STAGE, db.NON_THESIS_STAGES)

    def test_candidate_distinct_from_curated_intake(self) -> None:
        # Candidate-only ≠ curated_intake: both are non-analysis, but only the
        # candidate stage lives in CANDIDATE_ONLY_STAGES (the /events hide set).
        self.assertNotIn(db.CURATED_INTAKE_STAGE, db.CANDIDATE_ONLY_STAGES)
        self.assertNotIn(db.CURATED_OBSERVATION_STAGE, db.CANDIDATE_ONLY_STAGES)

    # ----- denominators EXCLUDE the candidate stage -----------------------
    def test_track_record_excludes_candidate(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="z1a_candidate_pack", market_tickers=_PRIMARY_ONLY)
        tr = db.compute_track_record()
        self.assertEqual(tr["total"], 1)        # only the realized thesis row
        self.assertEqual(tr["unresolved"], 0)   # candidate NOT scored unresolved

    def test_coverage_loader_excludes_candidate(self) -> None:
        realized_id = self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        cand_id = self._insert_event(stage="z1a_candidate_pack", market_tickers=_PRIMARY_ONLY)
        events, excluded = cov._load_events(self._tmp)
        ids = [e["id"] for e in events]
        self.assertIn(realized_id, ids)
        self.assertNotIn(cand_id, ids)
        self.assertGreaterEqual(excluded, 1)


if __name__ == "__main__":
    unittest.main()
