"""Tests for scripts/mechanism_family_overview_report.py (read-only).

The overview must keep accepted evidence and staged candidates strictly
separated, surface the `none`/untagged bucket as a limitation, always emit the
minimum family set, present the Tier-1 shortlist bridge as staged/no-paid only,
and carry denominator metadata + non-claims.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import mechanism_family_overview_report as R  # noqa: E402


_EVENTS_DDL = """
CREATE TABLE events (
    id               INTEGER PRIMARY KEY,
    event_date       TEXT,
    stage            TEXT,
    mechanism_family TEXT,
    headline         TEXT,
    market_tickers   TEXT
)
""".strip()

_PRICE_CACHE_DDL = """
CREATE TABLE price_cache (
    ticker      TEXT NOT NULL,
    date        TEXT NOT NULL,
    close       REAL,
    volume      REAL,
    auto_adjust INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (ticker, date, auto_adjust)
)
""".strip()

_EVENT_HYGIENE_DDL = """
CREATE TABLE event_hygiene (
    event_id        INTEGER PRIMARY KEY,
    override_class  TEXT,
    override_reason TEXT,
    created_at      TEXT
)
""".strip()


def _mt(symbol):
    return json.dumps([{"symbol": symbol, "role": "exposed"}])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_mfo_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_PRICE_CACHE_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _seed(self, event_id, *, stage="realized", family=None,
              date="2026-01-05", headline="headline", ticker="AAA"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, stage, mechanism_family, "
                "headline, market_tickers) VALUES (?,?,?,?,?,?)",
                (event_id, date, stage, family, headline, _mt(ticker)),
            )
            conn.commit()

    def _flag_synthetic(self, event_id):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO event_hygiene VALUES (?, 'synthetic_seed', 't', 't')",
                (event_id,),
            )
            conn.commit()

    def _seed_rich_fixture(self):
        # accepted: 1 curated tariff observation + 2 untagged thesis rows
        self._seed(10, stage="curated_observation", family="tariff", ticker="STLD")
        self._seed(11, stage="realized", family="", ticker="AAA")
        self._seed(12, stage="realized", family=None, ticker="BBB")
        # staged Tier-1 trio
        self._seed(303, stage="z1a_candidate_pack", family="regulation",
                   headline="DOJ v Apple", ticker="AAPL")
        self._seed(304, stage="z1a_candidate_pack", family="regulation",
                   headline="DOJ v Google ad-tech", ticker="GOOGL")
        self._seed(313, stage="z1a_candidate_pack", family="labor_inflation",
                   headline="UAW strike", ticker="GM")
        # excluded buckets: synthetic / intake / pending-review
        self._seed(20, stage="realized", family=None, ticker="ZZZ")
        self._flag_synthetic(20)
        self._seed(21, stage="curated_intake", family="policy_surprise", ticker="CCC")
        self._seed(315, stage="analysis_pending_review", family=None, ticker="AMZN")

    def _family(self, report, name):
        for f in report["families"]:
            if f["family"] == name:
                return f
        raise AssertionError(f"family {name!r} missing from report")


class TestFamilyCounting(_Base):
    def test_denominator_metadata_present_and_correct(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        d = rep["denominators"]
        self.assertEqual(d["archive_rows"], 9)
        self.assertEqual(d["accepted_coverage_denominator"], 3)   # 10,11,12
        self.assertEqual(d["accepted_track_record_denominator"], 2)  # minus curated obs
        self.assertEqual(d["staged_candidates"], 3)
        self.assertEqual(d["excluded"]["synthetic_seed"], 1)
        self.assertEqual(d["excluded"]["curated_intake"], 1)
        self.assertEqual(d["excluded"]["analysis_pending_review"], 1)
        self.assertTrue(d["note"])

    def test_family_counting_by_stage_lens(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        tariff = self._family(rep, "tariff")
        self.assertEqual(tariff["accepted_count"], 1)
        self.assertEqual(tariff["accepted_observation_count"], 1)
        self.assertEqual(tariff["accepted_thesis_count"], 0)
        self.assertEqual(tariff["staged_count"], 0)
        self.assertEqual(tariff["status"], "accepted_evidence_present")

    def test_accepted_vs_staged_separation(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        reg = self._family(rep, "regulation")
        self.assertEqual(reg["accepted_count"], 0)
        self.assertEqual(reg["staged_count"], 2)
        self.assertEqual(reg["status"], "staged_only")
        # A staged-only family must never read as accepted evidence.
        self.assertNotIn("accepted_evidence", reg["status"])

    def test_json_names_compute_readiness_as_accepted_only(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        reg = self._family(rep, "regulation")
        self.assertIn("accepted_compute_ready_count", reg)
        self.assertNotIn("event_study_available_accepted", reg)
        self.assertEqual(reg["accepted_compute_ready_count"], 0)
        self.assertEqual(reg["staged_count"], 2)
        self.assertEqual(reg["status"], "staged_only")
        note = rep["denominators"]["event_study_availability_note"].lower()
        self.assertIn("staged", note)
        self.assertIn("queue", note)
        self.assertIn("not merged", note)

    def test_none_family_is_limitation_bucket_not_hidden(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        none_f = self._family(rep, "none")
        self.assertEqual(none_f["accepted_count"], 2)
        self.assertEqual(none_f["status"], "untagged_limitation")
        self.assertTrue(none_f["limitations"])

    def test_excluded_only_family_disclosed(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        ps = self._family(rep, "policy_surprise")
        self.assertEqual(ps["accepted_count"], 0)
        self.assertEqual(ps["staged_count"], 0)
        self.assertEqual(ps["excluded_rows_count"], 1)
        self.assertEqual(ps["status"], "excluded_only")

    def test_minimum_family_set_always_present(self):
        # Empty archive: every minimum family still emitted, status absent.
        rep = R.build_overview(db_path=self._tmp)
        names = {f["family"] for f in rep["families"]}
        for fam in ("tariff", "sanction", "policy_surprise", "regulation",
                    "labor_inflation", "industrial_policy", "none"):
            self.assertIn(fam, names)
        self.assertEqual(self._family(rep, "sanction")["status"], "absent")


class TestRepresentativeCases(_Base):
    def test_staged_candidates_never_in_accepted_cases(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        reg = self._family(rep, "regulation")
        self.assertEqual(reg["representative_accepted_cases"], [])
        staged_ids = {c["event_id"] for c in reg["representative_staged_candidates"]}
        self.assertEqual(staged_ids, {303, 304})
        for c in reg["representative_staged_candidates"]:
            self.assertEqual(c["status"], "staged_no_paid")

    def test_limit_cases_caps_lists(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp, limit_cases=1)
        none_f = self._family(rep, "none")
        self.assertEqual(len(none_f["representative_accepted_cases"]), 1)
        reg = self._family(rep, "regulation")
        self.assertEqual(len(reg["representative_staged_candidates"]), 1)


class TestShortlistBridge(_Base):
    def test_tier1_bridge_staged_no_paid_only(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        bridge = rep["shortlist_bridge"]
        ids = {e["event_id"] for e in bridge["tier1"]}
        self.assertEqual(ids, {303, 304, 313})
        for e in bridge["tier1"]:
            self.assertEqual(e["status"], "staged_no_paid")
            self.assertTrue(e["why_it_broadens"])
        self.assertIn("STAGED_CANDIDATE_SHORTLIST", bridge["source"])

    def test_tier1_entry_not_marked_staged_when_stage_changed(self):
        # If a shortlist id is no longer a staged candidate, the bridge must
        # flag it rather than claim staged/no-paid.
        self._seed(303, stage="realized", family="regulation", ticker="AAPL")
        rep = R.build_overview(db_path=self._tmp)
        e303 = [e for e in rep["shortlist_bridge"]["tier1"] if e["event_id"] == 303][0]
        self.assertNotEqual(e303["status"], "staged_no_paid")
        self.assertIn("not_currently_staged", e303["status"])

    def test_tier1_entry_missing_from_archive_flagged(self):
        rep = R.build_overview(db_path=self._tmp)  # empty archive
        e313 = [e for e in rep["shortlist_bridge"]["tier1"] if e["event_id"] == 313][0]
        self.assertEqual(e313["status"], "missing_from_archive")


class TestNonClaimsAndRendering(_Base):
    def test_non_claims_cover_required_ground(self):
        rep = R.build_overview(db_path=self._tmp)
        blob = " ".join(rep["non_claims"]).lower()
        for needle in ("not proof", "staged", "significance", "fdr",
                       "taxonomy", "paid"):
            self.assertIn(needle, blob)

    def test_text_render_separates_and_is_cp1252_safe(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        text = R._render_text(rep)
        text.encode("cp1252")  # Windows console safety
        low = text.lower()
        self.assertIn("staged", low)
        self.assertIn("not accepted evidence", low)
        self.assertIn("limitation", low)

    def test_text_names_compute_readiness_as_accepted_only(self):
        self._seed_rich_fixture()
        text = R._render_text(R.build_overview(db_path=self._tmp))
        low = text.lower()
        self.assertNotIn("es-avail", low)
        self.assertIn("accepted-ready", low)
        self.assertIn("staged event-study availability", low)
        self.assertIn("not merged", low)

    def test_json_round_trip(self):
        self._seed_rich_fixture()
        rep = R.build_overview(db_path=self._tmp)
        again = json.loads(json.dumps(rep, default=str))
        self.assertEqual(again["denominators"]["staged_candidates"], 3)


if __name__ == "__main__":
    unittest.main()
