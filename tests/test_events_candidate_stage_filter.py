"""AB1 Lane A — ``GET /events`` candidate-only staging suppression.

A ``z1a_candidate_pack`` row is a candidate-only staging stub, not an analyzed
event.  The default listing must hide it so it never renders as an analyzed
case in the Market Overview, while staying reachable for deliberate inspection:

  1) Default ``/events`` excludes ``z1a_candidate_pack`` rows; ``total``
     reflects the post-suppression universe.
  2) ``/events?stage=z1a_candidate_pack`` (an explicit operator request for the
     candidate stage) surfaces them — hiding-by-default must not make the rows
     unreachable through the listing.
  3) ``/events/{id}`` returns a candidate row regardless.
  4) Existing behaviour is unchanged: a ``curated_intake`` stub still appears on
     the default listing (it is NOT a candidate-only stage), and real analyzed
     rows are unaffected.

No LLM or market calls — events are seeded directly into a temp DB.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api
import movers_cache
from fastapi.testclient import TestClient

client = TestClient(api.app)


def _reset_caches() -> None:
    movers_cache.invalidate()
    api._news_cache["data"] = None
    api._news_cache["ts"] = 0.0
    api._TODAYS_MOVERS_CACHE["data"] = None
    api._TODAYS_MOVERS_CACHE["ts"] = 0.0
    api._WEEKLY_MOVERS_CACHE["data"] = None
    api._YEARLY_MOVERS_CACHE["data"] = None
    api._PERSISTENT_MOVERS_CACHE["data"] = None


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.setdefault("ANTHROPIC_API_KEY", "")
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_events_cand_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        _reset_caches()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        _reset_caches()
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _seed(self, *, stage: str, headline: str, with_tickers: bool = True) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        ts = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        tickers = (
            [{"symbol": "XLE", "role": "beneficiary", "return_5d": 4.0,
              "return_20d": 5.0, "direction_tag": "supports up",
              "spark": [0.1, 0.2, 0.3], "anchor_date": today}]
            if with_tickers else []
        )
        db.save_event({
            "headline": headline,
            "stage": stage,
            "persistence": "structural",
            "event_date": today,
            "timestamp": ts,
            "what_changed": "Real change description",
            "mechanism_summary": "Mechanism summary text long enough to pass.",
            "market_tickers": tickers,
        })
        return db.load_recent_events(1)[0]["id"]


class TestCandidateHiddenByDefault(_Base):
    def test_candidate_hidden_by_default(self) -> None:
        cand_id = self._seed(stage="z1a_candidate_pack", headline="Candidate steel tariff")
        real_id = self._seed(stage="realized", headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(cand_id, ids)
        self.assertEqual(body["total"], 1)


class TestCandidateSurfacedByExplicitStage(_Base):
    def test_explicit_stage_surfaces_candidate(self) -> None:
        cand_id = self._seed(stage="z1a_candidate_pack", headline="Candidate steel tariff")
        self._seed(stage="realized", headline="Real Fed decision")

        body = client.get("/events?stage=z1a_candidate_pack").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(cand_id, ids)


class TestCandidateDetailByIdAlwaysServes(_Base):
    def test_candidate_detail_by_id_still_works(self) -> None:
        cand_id = self._seed(stage="z1a_candidate_pack", headline="Candidate steel tariff")
        list_ids = [e["id"] for e in client.get("/events").json()["items"]]
        self.assertNotIn(cand_id, list_ids)
        resp = client.get(f"/events/{cand_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], cand_id)


class TestCuratedIntakeUnchanged(_Base):
    def test_curated_intake_still_listed_by_default(self) -> None:
        intake_id = self._seed(
            stage="curated_intake", headline="Curated intake stub", with_tickers=False,
        )
        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(intake_id, ids)


# ----- AJ1: analysis_pending_review quarantine — same hide pattern as the
# candidate stage (hidden by default, reachable by explicit stage / by id) but
# a distinct stage: a real analyzed row held back from the accepted corpus.
class TestReviewStageHiddenByDefault(_Base):
    def test_review_stage_hidden_by_default(self) -> None:
        review_id = self._seed(
            stage="analysis_pending_review", headline="Pending review FTC case",
        )
        real_id = self._seed(stage="realized", headline="Real Fed decision")

        body = client.get("/events").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(real_id, ids)
        self.assertNotIn(review_id, ids)
        self.assertEqual(body["total"], 1)


class TestReviewStageSurfacedByExplicitStage(_Base):
    def test_explicit_stage_surfaces_only_review(self) -> None:
        review_id = self._seed(
            stage="analysis_pending_review", headline="Pending review FTC case",
        )
        cand_id = self._seed(stage="z1a_candidate_pack", headline="Candidate steel tariff")
        self._seed(stage="realized", headline="Real Fed decision")

        body = client.get("/events?stage=analysis_pending_review").json()
        ids = [e["id"] for e in body["items"]]
        self.assertIn(review_id, ids)
        # No leak: requesting one hidden stage must not surface the other.
        self.assertNotIn(cand_id, ids)
        self.assertTrue(
            all(e["stage"] == "analysis_pending_review" for e in body["items"]),
        )


class TestReviewStageDetailByIdAlwaysServes(_Base):
    def test_review_detail_by_id_still_works(self) -> None:
        review_id = self._seed(
            stage="analysis_pending_review", headline="Pending review FTC case",
        )
        list_ids = [e["id"] for e in client.get("/events").json()["items"]]
        self.assertNotIn(review_id, list_ids)
        resp = client.get(f"/events/{review_id}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["id"], review_id)


if __name__ == "__main__":
    unittest.main()
