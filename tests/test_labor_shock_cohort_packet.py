"""Tests for scripts/labor_shock_cohort_packet.py (read-only).

The labor-shock cohort packet selects staged labor_inflation cases, consumes
the C4 event-date quality layer for anchor labels (derived, never hardcoded),
distinguishes goods-production from media/content-pipeline transmission,
flags local asset availability honestly, and never merges staged candidates
into accepted denominators.
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

from scripts import labor_shock_cohort_packet as P  # noqa: E402


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


def _mt(*symbols):
    return json.dumps([{"symbol": s, "role": "exposed"} for s in symbols])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_lscp_{uuid.uuid4().hex}.db",
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
              family="labor_inflation", event_date="2023-09-15",
              headline="headline", tickers=("GM",)):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, stage, mechanism_family, "
                "headline, market_tickers) VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(*tickers)),
            )
            conn.commit()

    def _seed_price_row(self, ticker):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,0,'t')",
                (ticker, "2023-09-15", 100.0, 1.0e6),
            )
            conn.commit()

    def _seed_live_like(self):
        self._seed(313, event_date="2023-09-15", tickers=("GM", "F"),
                   headline="UAW Stand Up Strike begins against GM, Ford, "
                            "and Stellantis")
        self._seed(314, event_date="2023-07-14", tickers=("NFLX", "WBD"),
                   headline="SAG-AFTRA TV/Theatrical/Streaming strike order "
                            "takes effect")
        # a regulation staged row that must NOT enter this cohort
        self._seed(303, family="regulation", event_date="2024-03-21",
                   tickers=("AAPL",),
                   headline="Justice Department sues Apple for monopolizing "
                            "smartphone markets")

    def _case(self, pkt, event_id):
        for c in pkt["cases"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestCohortSelection(_Base):
    def test_only_labor_rows_selected(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        ids = {c["event_id"] for c in pkt["cases"]}
        self.assertEqual(ids, {313, 314})

    def test_313_partial_anticipation_from_c4(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 313)
        self.assertEqual(c["event_date_quality"], "partial_anticipation")
        self.assertEqual(c["cohort_use"], "usable_with_caution")

    def test_314_scheduled_weak_anchor_from_c4(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 314)
        self.assertEqual(c["event_date_quality"], "scheduled_or_weak_anchor")
        self.assertEqual(c["cohort_use"], "weak_anchor_only")

    def test_labels_flow_from_c4_not_hardcoded(self):
        # Seed 313 with clean filing wording instead: the label must follow
        # the wording, proving the packet derives rather than assumes.
        self._seed(313, event_date="2023-09-15", tickers=("GM", "F"),
                   headline="UAW files unfair labor practice charges against "
                            "GM and Ford")
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 313)
        self.assertEqual(c["event_date_quality"], "clean_discrete_anchor")
        self.assertEqual(c["cohort_use"], "usable_with_caution")

    def test_exposed_tickers_carried(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(self._case(pkt, 313)["exposed_tickers"], ["GM", "F"])
        self.assertEqual(self._case(pkt, 313)["primary_ticker"], "GM")


class TestTaxonomyAndAssets(_Base):
    def test_goods_vs_media_subtypes(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertIn("production_disruption",
                      self._case(pkt, 313)["labor_subtype"])
        self.assertIn("content_pipeline_disruption",
                      self._case(pkt, 314)["labor_subtype"])
        tax = pkt["family_taxonomy"]
        self.assertIn(313, tax["production_disruption"])
        self.assertIn(314, tax["content_pipeline_disruption"])
        self.assertIn(313, tax["wage_cost_pressure"])
        self.assertIn(314, tax["wage_cost_pressure"])

    def test_comparison_readout_assigns_cases(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        cr = pkt["comparison_readout"]
        self.assertEqual(cr["goods_production_case"], 313)
        self.assertEqual(cr["media_content_case"], 314)
        self.assertTrue(cr["what_comparison_can_show"])
        self.assertTrue(cr["what_comparison_cannot_show"])

    def test_asset_map_flags_local_price_data(self):
        self._seed_live_like()
        self._seed_price_row("GM")  # only GM has local data in this fixture
        pkt = P.build_packet(db_path=self._tmp)
        amap = self._case(pkt, 313)["asset_proxy_map"]
        for cat in ("direct_exposures", "second_order_exposures",
                    "noisy_or_context_assets", "excluded_assets"):
            self.assertIn(cat, amap)
            for entry in amap[cat]:
                self.assertIn("local_price_data", entry)
                self.assertIsInstance(entry["local_price_data"], bool)
        direct = {e["ticker"]: e["local_price_data"]
                  for e in amap["direct_exposures"]}
        self.assertTrue(direct["GM"])
        self.assertFalse(direct["F"])

    def test_unknown_labor_row_gets_manual_review_subtype(self):
        self._seed(999, event_date="2024-02-02", tickers=("ZZZ",),
                   headline="Dockworkers begin strike at major ports")
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 999)
        self.assertIn("other_or_manual_review", c["labor_subtype"])


class TestShapeAndDiscipline(_Base):
    def test_denominators_keep_accepted_and_staged_separate(self):
        self._seed_live_like()
        self._seed(10, stage="realized", family="none", tickers=("FOO",),
                   event_date="2026-04-05", headline="Foo imposes bar")
        pkt = P.build_packet(db_path=self._tmp)
        d = pkt["denominators"]
        self.assertEqual(d["archive_rows"], 4)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 3)
        self.assertEqual(d["labor_staged_count"], 2)
        self.assertEqual(d["labor_accepted_count"], 0)

    def test_local_readout_descriptive_n1(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        ro = self._case(pkt, 313)["local_readout"]
        self.assertTrue(ro["descriptive_only"])
        self.assertTrue(ro["n_equals_one"])
        self.assertFalse(ro["available"])  # fixture has no usable series

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        self.assertEqual(self._case(pkt, 313)["stage"], "z1a_candidate_pack")
        self.assertEqual(self._case(pkt, 313)["corpus_status"], "staged")

    def test_non_claims_cover_required_ground(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        blob = " ".join(pkt["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "denominator", "fdr",
                       "illustrative"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt)
        text.encode("cp1252")
        low = text.lower()
        self.assertIn("what this family adds", low)
        self.assertIn("staged/no-paid", low)
        self.assertIn("goods", low)
        self.assertIn("media", low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt) + " " + json.dumps(pkt)
        with open(os.path.join(_REPO, "scripts", "labor_shock_cohort_packet.py"),
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
