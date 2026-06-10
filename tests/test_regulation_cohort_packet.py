"""Tests for scripts/regulation_cohort_packet.py (read-only).

The regulation cohort packet selects staged regulation cases from local data,
consumes the C4 event-date quality layer for anchor labels (never hardcoding
them), keeps 302 deferred-duplicate out of cohort evidence, carries 304's
operator paid-deferral, and never merges staged candidates into accepted
denominators.
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

from scripts import regulation_cohort_packet as P  # noqa: E402


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
            tempfile.gettempdir(), f"test_rcp_{uuid.uuid4().hex}.db",
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

    def _seed(self, event_id, *, stage="z1a_candidate_pack",
              family="regulation", event_date="2024-03-21",
              headline="headline", ticker="AAA"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, stage, mechanism_family, "
                "headline, market_tickers) VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(ticker)),
            )
            conn.commit()

    def _seed_live_like_cohort(self):
        self._seed(302, event_date="2023-09-26", ticker="AMZN",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(315, stage="analysis_pending_review", family="none",
                   event_date="2023-09-26", ticker="EBAY",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(303, event_date="2024-03-21", ticker="AAPL",
                   headline="Justice Department sues Apple for monopolizing "
                            "smartphone markets")
        self._seed(304, event_date="2023-01-24", ticker="GOOGL",
                   headline="Justice Department sues Google for monopolizing "
                            "digital advertising technologies")
        self._seed(306, event_date="2024-09-24", ticker="V",
                   headline="Justice Department sues Visa for monopolizing "
                            "debit-network markets")
        # a non-regulation staged row that must NOT enter the cohort
        self._seed(313, family="labor_inflation", event_date="2023-09-15",
                   ticker="GM", headline="UAW Stand Up Strike begins")

    def _case(self, pkt, event_id):
        for c in pkt["cases"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestCohortSelection(_Base):
    def test_only_regulation_rows_selected(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        ids = {c["event_id"] for c in pkt["cases"]}
        self.assertIn(303, ids)
        self.assertIn(304, ids)
        self.assertNotIn(313, ids)  # labor row stays out

    def test_302_is_deferred_duplicate_not_cohort_evidence(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        scope = pkt["cohort_scope"]
        self.assertIn(302, scope["deferred_ids"])
        self.assertNotIn(302, scope["included_staged_ids"])
        self.assertIn(315, scope["pending_related_ids"])
        c302 = self._case(pkt, 302)
        self.assertEqual(c302["event_date_quality"], "duplicate_or_deferred")
        self.assertEqual(c302["cohort_use"], "deferred_duplicate")

    def test_303_304_are_clean_anchors_from_c4_layer(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        for cid in (303, 304):
            c = self._case(pkt, cid)
            self.assertEqual(c["event_date_quality"], "clean_discrete_anchor")
            self.assertEqual(c["cohort_use"], "usable_clean_anchor")
        self.assertIn(303, pkt["comparison_readout"]["clean_anchor_cases"])
        self.assertIn(304, pkt["comparison_readout"]["clean_anchor_cases"])

    def test_304_carries_operator_paid_deferral(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        c304 = self._case(pkt, 304)
        self.assertIn("deferred", c304["paid_status"].lower())
        self.assertIn("CANDIDATE_304_PAID_GATE_PACKET", c304["paid_status"])
        c303 = self._case(pkt, 303)
        self.assertNotIn("deferred", c303["paid_status"].lower())

    def test_caution_label_flows_from_event_date_quality_not_hardcoded(self):
        # A regulation case with anticipatory wording must surface the C4
        # partial-anticipation label and a caution cohort_use - proving the
        # label is derived, not assumed clean.
        self._seed(305, event_date="2024-05-23", ticker="LYV",
                   headline="Justice Department considers action against "
                            "Live Nation over proposed remedies")
        pkt = P.build_packet(db_path=self._tmp)
        c305 = self._case(pkt, 305)
        self.assertEqual(c305["event_date_quality"], "partial_anticipation")
        self.assertEqual(c305["cohort_use"], "usable_with_caution")
        self.assertIn(305, pkt["comparison_readout"]["caution_cases"])


class TestTaxonomyAndShape(_Base):
    def test_known_cases_have_curated_subtypes(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertIn("conduct_remedy", self._case(pkt, 303)["regulation_subtype"])
        self.assertIn("structural_remedy", self._case(pkt, 304)["regulation_subtype"])
        self.assertIn("payments_network", self._case(pkt, 306)["regulation_subtype"])
        tax = pkt["family_taxonomy"]
        self.assertIn(303, tax["conduct_remedy"])
        self.assertIn(304, tax["structural_remedy"])
        self.assertIn(306, tax["payments_network"])

    def test_unknown_regulation_row_gets_manual_review_subtype(self):
        self._seed(999, event_date="2024-01-10", ticker="ZZZ",
                   headline="Justice Department sues Zeta Corp for "
                            "monopolizing widget markets")
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 999)
        self.assertIn("other_or_manual_review", c["regulation_subtype"])
        self.assertIn(999, pkt["family_taxonomy"]["other_or_manual_review"])

    def test_denominators_keep_accepted_and_staged_separate(self):
        self._seed_live_like_cohort()
        self._seed(10, stage="realized", family="none", ticker="FOO",
                   event_date="2026-04-05", headline="Foo imposes bar")
        pkt = P.build_packet(db_path=self._tmp)
        d = pkt["denominators"]
        self.assertEqual(d["archive_rows"], 7)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 5)
        self.assertEqual(d["regulation_staged_count"], 4)  # 302,303,304,306
        self.assertEqual(d["regulation_accepted_count"], 0)

    def test_local_readout_is_descriptive_n1(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        ro = self._case(pkt, 303)["local_readout"]
        self.assertTrue(ro["descriptive_only"])
        self.assertTrue(ro["n_equals_one"])
        self.assertFalse(ro["available"])  # empty fixture price cache

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(self._case(pkt, 303)["stage"], "z1a_candidate_pack")
        self.assertEqual(self._case(pkt, 303)["corpus_status"], "staged")

    def test_non_claims_cover_required_ground(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        blob = " ".join(pkt["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "denominator", "fdr",
                       "illustrative"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt)
        text.encode("cp1252")
        low = text.lower()
        self.assertIn("what this family adds", low)
        self.assertIn("staged/no-paid", low)
        self.assertIn("event-date quality", low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like_cohort()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt) + " " + json.dumps(pkt)
        with open(os.path.join(_REPO, "scripts", "regulation_cohort_packet.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


if __name__ == "__main__":
    unittest.main()
