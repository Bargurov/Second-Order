"""Tests for scripts/staged_family_coverage_report.py (read-only).

The cross-family coverage board consolidates the staged universe: per-family
label counts from the C4 layer, packet detection from committed artifacts,
the C2A computability correction, conservative dispositions, and ranked
no-paid next moves - with accepted vs staged never merged and no paid
approval implied anywhere.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import staged_family_coverage_report as R  # noqa: E402


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

# Live-like staged universe: (id, date, family, headline, tickers)
_UNIVERSE = [
    (302, "2023-09-26", "regulation",
     "FTC sues Amazon.com for illegally maintaining monopoly power", ["AMZN"]),
    (303, "2024-03-21", "regulation",
     "Justice Department sues Apple for monopolizing smartphone markets", ["AAPL"]),
    (304, "2023-01-24", "regulation",
     "Justice Department sues Google for monopolizing digital advertising technologies", ["GOOGL"]),
    (305, "2024-05-23", "regulation",
     "Justice Department sues Live Nation-Ticketmaster for monopolizing live-concert markets", ["LYV"]),
    (306, "2024-09-24", "regulation",
     "Justice Department sues Visa for monopolizing debit-network markets", ["V"]),
    (307, "2022-10-07", "sanction",
     "Commerce/BIS implements advanced-computing and semiconductor-manufacturing export controls on the PRC", ["NVDA", "AMD"]),
    (308, "2023-10-17", "sanction",
     "Commerce/BIS strengthens advanced-computing and semiconductor-equipment export controls", ["NVDA", "AMAT"]),
    (309, "2020-05-15", "sanction",
     "Commerce amends Foreign Direct Product Rule and Entity List targeting Huawei chip sourcing", ["QCOM", "SMH"]),
    (310, "2025-04-15", "sanction",
     "NVIDIA discloses US license requirement for H20 China exports and an estimated multi-billion-dollar charge (8-K)", ["NVDA", "AMD"]),
    (311, "2022-08-09", "industrial_policy",
     "CHIPS and Science Act signed into law (Public Law 117-167)", ["INTC", "MU"]),
    (312, "2022-08-16", "industrial_policy",
     "Inflation Reduction Act of 2022 signed into law (Public Law 117-169)", ["FSLR", "ENPH"]),
    (313, "2023-09-15", "labor_inflation",
     "UAW Stand Up Strike begins against GM, Ford, and Stellantis", ["GM", "F"]),
    (314, "2023-07-14", "labor_inflation",
     "SAG-AFTRA TV/Theatrical/Streaming strike order takes effect", ["NFLX", "WBD"]),
]


def _mt(symbols):
    return json.dumps([{"symbol": s, "role": "exposed"} for s in symbols])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_sfc_{uuid.uuid4().hex}.db",
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

    def _seed_universe(self):
        with sqlite3.connect(self._tmp) as conn:
            for eid, d, fam, hl, tks in _UNIVERSE:
                conn.execute(
                    "INSERT INTO events VALUES (?,?,?,?,?,?)",
                    (eid, d, "z1a_candidate_pack", fam, hl, _mt(tks)),
                )
            # quarantined pending duplicate partner for 302
            conn.execute(
                "INSERT INTO events VALUES (315, '2023-09-26', "
                "'analysis_pending_review', 'none', ?, ?)",
                (_UNIVERSE[0][3], _mt(["EBAY"])),
            )
            # curated sanction anchors (thread partners)
            conn.execute(
                "INSERT INTO events VALUES (298, '2019-05-16', "
                "'curated_observation', 'sanction', "
                "'BIS adds Huawei + 68 affiliates to the Entity List', ?)",
                (_mt(["QRVO"]),))
            conn.execute(
                "INSERT INTO events VALUES (300, '2022-08-31', "
                "'curated_observation', 'sanction', "
                "'US imposes a license requirement on NVIDIA A100/H100 "
                "datacenter GPU exports to China', ?)", (_mt(["NVDA"]),))
            # supplier legs with rows but ZERO pre-event coverage (2026-only)
            for t in ("LEA", "APTV"):
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache VALUES "
                    "(?, '2026-02-02', 100.0, 1e6, 0, 't')", (t,))
            conn.commit()

    def _family(self, rep, name):
        for f in rep["family_coverage"]:
            if f["family"] == name:
                return f
        raise AssertionError(f"family {name!r} missing")

    def _case(self, rep, event_id):
        for c in rep["case_board"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestFamilyCoverage(_Base):
    def test_staged_family_counts(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._family(rep, "regulation")["staged_count"], 5)
        self.assertEqual(self._family(rep, "sanction")["staged_count"], 4)
        self.assertEqual(self._family(rep, "industrial_policy")["staged_count"], 2)
        self.assertEqual(self._family(rep, "labor_inflation")["staged_count"], 2)

    def test_denominators_separated(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        d = rep["denominators"]
        self.assertEqual(d["archive_rows"], 16)
        self.assertEqual(d["staged_candidate_count"], 13)
        self.assertEqual(d["accepted_coverage_denominator"], 2)  # 2 curated
        self.assertEqual(d["accepted_track_record_denominator"], 0)

    def test_packet_detection_from_repo_artifacts(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._family(rep, "regulation")["packet_status"],
                         "packet_available")
        self.assertEqual(self._family(rep, "labor_inflation")["packet_status"],
                         "packet_available")
        self.assertEqual(self._family(rep, "industrial_policy")["packet_status"],
                         "no_packet_yet")
        self.assertEqual(self._family(rep, "sanction")["packet_status"],
                         "no_packet_yet")
        slices = rep["known_deep_slices"]
        for key in ("regulation_cohort_packet", "labor_shock_cohort_packet",
                    "uaw_supplier_transmission_packet"):
            self.assertIn(key, slices)
            self.assertTrue(slices[key]["available"])

    def test_label_counts_per_family(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        reg = self._family(rep, "regulation")
        self.assertEqual(reg["clean_anchor_count"], 4)      # 303/304/305/306
        self.assertEqual(reg["duplicate_deferred_count"], 1)  # 302
        sanc = self._family(rep, "sanction")
        self.assertEqual(sanc["thread_sibling_count"], 4)   # 307-310
        ind = self._family(rep, "industrial_policy")
        self.assertEqual(ind["scheduled_or_weak_count"], 2)  # 311/312
        lab = self._family(rep, "labor_inflation")
        self.assertEqual(lab["partial_anticipation_count"], 1)  # 313
        self.assertEqual(lab["scheduled_or_weak_count"], 1)     # 314

    def test_every_family_has_do_not_pay_status_and_next_move(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        for f in rep["family_coverage"]:
            self.assertIn("no paid", f["no_paid_status"].lower())
            self.assertTrue(f["next_no_paid_move"])


class TestCaseBoard(_Base):
    def test_all_13_staged_cases_on_board(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual({c["event_id"] for c in rep["case_board"]},
                         {u[0] for u in _UNIVERSE})

    def test_302_duplicate_deferred_disposition(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        c = self._case(rep, 302)
        self.assertEqual(c["event_date_quality"], "duplicate_or_deferred")
        self.assertIn("deferred_duplicate", c["disposition"])

    def test_303_304_clean_anchors_and_304_paid_deferral(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        for cid in (303, 304):
            self.assertEqual(self._case(rep, cid)["event_date_quality"],
                             "clean_discrete_anchor")
        c304 = self._case(rep, 304)
        self.assertIn("closed-deferred", c304["disposition"])
        c303 = self._case(rep, 303)
        self.assertNotIn("closed-deferred", c303["disposition"])

    def test_313_partial_and_314_weak_carried(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._case(rep, 313)["event_date_quality"],
                         "partial_anticipation")
        self.assertEqual(self._case(rep, 314)["event_date_quality"],
                         "scheduled_or_weak_anchor")
        self.assertIn("weak", self._case(rep, 314)["disposition"].lower())

    def test_thread_siblings_not_independent_breadth(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        for cid in (307, 308, 309, 310):
            c = self._case(rep, cid)
            self.assertEqual(c["event_date_quality"],
                             "continuation_or_thread_sibling")
            self.assertIn("not", c["disposition"].lower())
        sanc = self._family(rep, "sanction")
        self.assertIn("thread", sanc["next_no_paid_move"].lower())

    def test_311_312_weak_not_clean_evidence(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        for cid in (311, 312):
            c = self._case(rep, cid)
            self.assertEqual(c["event_date_quality"], "scheduled_or_weak_anchor")
            self.assertNotIn("clean", c["disposition"].lower())

    def test_stage_passthrough_no_promotion(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        for c in rep["case_board"]:
            self.assertEqual(c["corpus_status"], "staged")


class TestComputabilityAndOpportunities(_Base):
    def test_lea_aptv_correction_carried(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        lab = self._family(rep, "labor_inflation")
        blob = " ".join(lab["not_currently_computable_cases"])
        self.assertIn("LEA", blob)
        self.assertIn("APTV", blob)
        self.assertIn("0 pre-event", blob)
        self.assertIn("rows cached", blob)

    def test_next_no_paid_opportunities_ranked_and_no_paid(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        opps = rep["next_no_paid_opportunities"]
        self.assertGreaterEqual(len(opps), 3)
        ranks = [o["rank"] for o in opps]
        self.assertEqual(ranks, sorted(ranks))
        for o in opps:
            self.assertTrue(o["no_paid"])
            self.assertIn("requires_gate", o)
            self.assertTrue(o["task"])

    def test_coverage_gaps_named(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        blob = " ".join(rep["coverage_gaps"]).lower()
        for needle in ("industrial_policy", "thread", "supplier", "304"):
            self.assertIn(needle, blob)

    def test_family_filter(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp, family="regulation")
        self.assertEqual({c["mechanism_family"] for c in rep["case_board"]},
                         {"regulation"})
        with self.assertRaises(ValueError):
            R.build_report(db_path=self._tmp, family="bogus")

    def test_non_claims_cover_required_ground(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        blob = " ".join(rep["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "recommendation",
                       "denominator", "fdr", "illustrative"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep)
        text.encode("cp1252")
        low = text.lower()
        for section in ("family coverage", "case board", "computability",
                        "next no-paid", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_universe()
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "staged_family_coverage_report.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


if __name__ == "__main__":
    unittest.main()
