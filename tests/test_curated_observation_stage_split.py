"""K3 — curated_observation stage split.

Pins the contract that a promoted curated row is a *research observation*
(counted by the event-study coverage + data-hygiene denominators) but NOT a
*scoreable thesis* (excluded from the track-record and the diagnostics
outcome blocks).

The single exclusion set ``NON_ANALYSIS_STAGES`` historically served both
notions.  K3 splits them:

  * ``NON_ANALYSIS_STAGES = {curated_intake}``                 — not even an
    observation (no tickers); excluded everywhere.
  * ``NON_THESIS_STAGES   = {curated_intake, curated_observation}`` — no
    scoreable thesis; excluded from track-record / diagnostics outcome.

``curated_observation`` is in the second set but not the first, so it counts
as an observation yet never lands in a thesis denominator.

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
from scripts import data_hygiene_report as hygiene


_SUPPORTS = '[{"symbol": "AAA", "role": "beneficiary", "direction_tag": "supports up", "return_1d": 1.0}]'
_PRIMARY_ONLY = '[{"symbol": "TGT", "role": "primary"}]'


class CuratedObservationStageSplitTest(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db_file = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_obs_split_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()  # creates the schema AND sets db._db_ready = True

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db_file
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    # ----- helper ---------------------------------------------------------
    def _insert_event(
        self, *, stage: str, market_tickers: str = "[]",
        mechanism_family: str = "tariff", headline: str | None = None,
        event_date: str = "2018-03-08", persistence: str = "medium",
    ) -> int:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date, mechanism_family) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "2018-03-08T12:00:00",
                    headline or f"event-{uuid.uuid4().hex[:8]}",
                    stage, persistence, market_tickers, event_date,
                    mechanism_family,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    # ----- constants ------------------------------------------------------
    def test_curated_observation_stage_constant(self) -> None:
        self.assertEqual(db.CURATED_OBSERVATION_STAGE, "curated_observation")

    def test_non_analysis_stages_unchanged(self) -> None:
        self.assertEqual(db.NON_ANALYSIS_STAGES, frozenset({"curated_intake"}))

    def test_non_thesis_stages_is_superset(self) -> None:
        self.assertEqual(
            db.NON_THESIS_STAGES,
            frozenset({"curated_intake", "curated_observation"}),
        )

    def test_curated_observation_not_excluded_from_observation(self) -> None:
        self.assertNotIn(db.CURATED_OBSERVATION_STAGE, db.NON_ANALYSIS_STAGES)

    def test_curated_observation_excluded_from_thesis(self) -> None:
        self.assertIn(db.CURATED_OBSERVATION_STAGE, db.NON_THESIS_STAGES)

    # ----- thesis surfaces EXCLUDE curated_observation --------------------
    def test_track_record_excludes_curated_observation(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_observation", market_tickers=_PRIMARY_ONLY)
        self._insert_event(stage="curated_intake")
        tr = db.compute_track_record()
        self.assertEqual(tr["total"], 1)        # only the realized thesis row
        self.assertEqual(tr["unresolved"], 0)   # curated_observation NOT unresolved

    def test_diag_validation_status_excludes_curated_observation(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_observation", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_intake")
        stats = diag._compute_validation_status_stats()
        self.assertEqual(stats["total_events"], 1)

    def test_diag_track_record_excludes_curated_observation(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_observation", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_intake")
        tr = diag._compute_track_record()
        self.assertEqual(tr["total_events"], 1)

    def test_diag_archive_aggregates_thesis_state_excludes_curated_observation(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_observation", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_intake")
        blocks = diag._compute_archive_aggregates()
        counts = blocks["events_by_thesis_state"]["counts"]
        self.assertEqual(sum(counts.values()), 1)

    def test_track_record_breakdown_excludes_non_thesis_stages(self) -> None:
        # The viewer-facing breakdown must slice the SAME outcome set as
        # db.compute_track_record — so curated_intake AND curated_observation
        # rows must not land in any mechanism-family group.
        from track_record_breakdown import compute_track_record_breakdown
        self._insert_event(stage="realized", market_tickers=_SUPPORTS, mechanism_family="tariff")
        self._insert_event(stage="curated_observation", market_tickers=_PRIMARY_ONLY, mechanism_family="tariff")
        self._insert_event(stage="curated_intake", mechanism_family="tariff")
        events = db.load_recent_events(limit=500)
        bd = compute_track_record_breakdown(events)
        total = sum(g["total"] for g in bd["by_mechanism_family"])
        self.assertEqual(total, 1)  # only the realized thesis row

    # ----- observation surfaces COUNT curated_observation -----------------
    def test_coverage_loader_counts_curated_observation(self) -> None:
        obs_id = self._insert_event(stage="curated_observation", market_tickers=_PRIMARY_ONLY)
        intake_id = self._insert_event(stage="curated_intake")
        events, excluded = cov._load_events(self._tmp)
        ids = [e["id"] for e in events]
        self.assertIn(obs_id, ids)
        self.assertNotIn(intake_id, ids)
        self.assertEqual(excluded, 1)

    def test_hygiene_counts_curated_observation_and_breaks_it_out(self) -> None:
        self._insert_event(stage="realized", market_tickers=_SUPPORTS)
        self._insert_event(stage="curated_observation", market_tickers=_PRIMARY_ONLY)
        self._insert_event(stage="curated_intake")
        report = hygiene.summarize_data_hygiene(db_path=self._tmp)
        # curated_observation is a counted observation (realized + obs = 2),
        # curated_intake stays excluded.
        self.assertEqual(report["analysis_stage_total"], 2)
        self.assertEqual(report["curated_intake_excluded_count"], 1)
        # ...and it is disclosed as a source-anchored promotion.
        self.assertEqual(report["source_anchored_promoted_count"], 1)


if __name__ == "__main__":
    unittest.main()
