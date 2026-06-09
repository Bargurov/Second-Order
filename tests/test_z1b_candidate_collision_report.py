"""AB1 Lane B — candidate ↔ existing-event collision detection.

Source-URL idempotency alone cannot catch a candidate that duplicates an
existing event under a different URL, a nearby (not exact) date, or a reworded
headline.  ``detect_collisions`` flags probable duplicates by THREE
deterministic signals so a promotion can refuse / warn before re-ingesting:

  * ``source_url_exact``       — candidate source_url == an existing provenance URL
  * ``date_window_ticker``     — |Δdate| ≤ window AND a ticker in common
  * ``headline_similarity``    — title vs headline ratio ≥ threshold

Pinned case: the REAL Z1A steel candidate vs the K14 live observation (event
296).  They share the same federalregister source_url and NUE, but their
event_dates are 7 days apart (2018-03-08 vs 2018-03-01) — so an EXACT date+
ticker check would miss it; source_url and the date-WINDOW check catch it.

Read-only / temp-DB only; never touches the live archive.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402
from scripts.z1b_candidate_collision_report import detect_collisions  # noqa: E402
from scripts.z1b_candidate_pack_copy_ingest import _load_candidates  # noqa: E402

_PACK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "candidates", "z1a_multi_regime_candidates.yaml",
)
_STEEL_URL = (
    "https://www.federalregister.gov/documents/2018/03/15/"
    "2018-05478/adjusting-imports-of-steel-into-the-united-states"
)
_EVENT_296_HEADLINE = (
    "Trump announces intent to impose 25% Section 232 tariffs on steel "
    "(steel-executives meeting); formalized as Proclamation 9705"
)


def _steel_candidate() -> dict:
    cands = _load_candidates(_PACK)
    return next(c for c in cands if str(c.get("id", "")).startswith("section232-steel"))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_collision_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _insert_event(
        self, *, headline: str, event_date: str, tickers_json: str = "[]",
        source_url: str | None = None, stage: str = "curated_observation",
    ) -> int:
        with sqlite3.connect(self._tmp) as conn:
            cur = conn.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date) VALUES (?, ?, ?, ?, ?, ?)",
                ("2018-03-01T12:00:00", headline, stage, "structural",
                 tickers_json, event_date),
            )
            eid = int(cur.lastrowid)
            if source_url:
                conn.execute(
                    "INSERT INTO event_provenance (event_id, source_type, "
                    "source_publisher, source_url, mechanism_label_provenance, "
                    "intake_path, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (eid, "official", "Federal Register", source_url,
                     "curated", "test", "2018-03-01T12:00:00"),
                )
            conn.commit()
            return eid

    def _seed_event_296(self) -> int:
        return self._insert_event(
            headline=_EVENT_296_HEADLINE,
            event_date="2018-03-01",
            tickers_json='[{"symbol": "NUE", "role": "primary"}]',
            source_url=_STEEL_URL,
        )


class SteelEvent296CollisionTest(_Base):
    def test_steel_candidate_collides_with_event_296(self) -> None:
        eid = self._seed_event_296()
        report = detect_collisions([_steel_candidate()], self._tmp)
        self.assertTrue(report["has_collisions"])
        cand = report["candidates"][0]
        self.assertEqual(len(cand["collisions"]), 1)
        col = cand["collisions"][0]
        self.assertEqual(col["event_id"], eid)
        # Same source_url AND (7 days apart, NUE in common) — both fire; an
        # EXACT date+ticker check would have missed it (dates differ).
        self.assertIn("source_url_exact", col["reasons"])
        self.assertIn("date_window_ticker", col["reasons"])

    def test_url_differs_but_date_window_ticker_still_flags(self) -> None:
        # The whole point: source_url idempotency is not enough.  Same steel
        # candidate but a fresh URL still collides via date-window + NUE.
        eid = self._seed_event_296()
        steel = dict(_steel_candidate())
        steel["source_url"] = "https://example.gov/some-other-steel-url"
        report = detect_collisions([steel], self._tmp)
        self.assertTrue(report["has_collisions"])
        reasons = report["candidates"][0]["collisions"][0]["reasons"]
        self.assertNotIn("source_url_exact", reasons)
        self.assertIn("date_window_ticker", reasons)
        self.assertEqual(report["candidates"][0]["collisions"][0]["event_id"], eid)


class SignalIsolationTest(_Base):
    def test_headline_similarity_alone_flags_reword(self) -> None:
        # Different URL, far-apart date, no ticker overlap — only the reworded
        # headline should trip the detector.
        self._insert_event(
            headline="Federal Reserve raises the target rate by 25 basis points",
            event_date="2024-03-20",
            tickers_json='[{"symbol": "TLT", "role": "exposed"}]',
            source_url="https://federalreserve.gov/fomc-2024-03",
        )
        cand = {
            "id": "fomc-reword",
            "title": "Federal Reserve raises the target rate by 25 basis points today",
            "event_date": "2020-01-01",
            "source_url": "https://example.com/unrelated",
            "affected_assets": [{"ticker": "SPY", "role": "exposed"}],
        }
        report = detect_collisions([cand], self._tmp)
        self.assertTrue(report["has_collisions"])
        reasons = report["candidates"][0]["collisions"][0]["reasons"]
        self.assertEqual(reasons, ["headline_similarity"])

    def test_clean_candidate_has_no_collision(self) -> None:
        self._seed_event_296()
        cand = {
            "id": "doj-v-google-adtech-2023-01-24",
            "title": "Justice Department sues Google over digital advertising monopoly",
            "event_date": "2023-01-24",
            "source_url": "https://www.justice.gov/opa/pr/google-adtech",
            "affected_assets": [{"ticker": "GOOGL", "role": "exposed"}],
        }
        report = detect_collisions([cand], self._tmp)
        self.assertFalse(report["has_collisions"])
        self.assertEqual(report["candidates"][0]["collisions"], [])

    def test_summary_counts_and_refusal_flag(self) -> None:
        self._seed_event_296()
        clean = {
            "id": "clean-1", "title": "An entirely unrelated antitrust filing",
            "event_date": "2025-05-05", "source_url": "https://x.gov/y",
            "affected_assets": [{"ticker": "ZZZ", "role": "exposed"}],
        }
        report = detect_collisions([_steel_candidate(), clean], self._tmp)
        self.assertTrue(report["has_collisions"])
        self.assertEqual(report["summary"]["n_candidates"], 2)
        self.assertEqual(report["summary"]["n_with_collisions"], 1)


if __name__ == "__main__":
    unittest.main()
