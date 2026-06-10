"""Tests for scripts/regulation_conduct_structural_memo.py (read-only).

The 303-vs-304 memo compares conduct/platform-ecosystem vs structural/
ad-tech-stack regulation as two staged n=1 cases: C4 labels consumed live,
305/306 context-only, 304's paid path carried as closed/deferred, and the
descriptive readout contrast explicitly NOT read as mechanism strength.
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

from scripts import regulation_conduct_structural_memo as M  # noqa: E402


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


def _mt(symbols):
    return json.dumps([{"symbol": s, "role": "exposed"} for s in symbols])


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_rcsm_{uuid.uuid4().hex}.db",
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
              headline="headline", tickers=("AAPL",)):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(tickers)),
            )
            conn.commit()

    def _seed_live_like(self):
        self._seed(302, event_date="2023-09-26", tickers=("AMZN",),
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(315, stage="analysis_pending_review", family="none",
                   event_date="2023-09-26", tickers=("EBAY",),
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(303, event_date="2024-03-21", tickers=("AAPL",),
                   headline="Justice Department sues Apple for monopolizing "
                            "smartphone markets")
        self._seed(304, event_date="2023-01-24", tickers=("GOOGL",),
                   headline="Justice Department sues Google for monopolizing "
                            "digital advertising technologies")
        self._seed(305, event_date="2024-05-23", tickers=("LYV",),
                   headline="Justice Department sues Live Nation-Ticketmaster "
                            "for monopolizing live-concert markets")
        self._seed(306, event_date="2024-09-24", tickers=("V",),
                   headline="Justice Department sues Visa for monopolizing "
                            "debit-network markets")

    def _case(self, memo, event_id):
        for c in memo["cases"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestScopeAndLabels(_Base):
    def test_primary_cases_are_303_and_304_only(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        self.assertEqual(memo["comparison_scope"]["primary_case_ids"], [303, 304])
        self.assertEqual({c["event_id"] for c in memo["cases"]}, {303, 304})

    def test_305_306_are_context_only_and_302_deferred(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        scope = memo["comparison_scope"]
        self.assertEqual(sorted(scope["context_case_ids"]), [305, 306])
        self.assertIn(302, scope["excluded_or_deferred_ids"])

    def test_clean_anchor_labels_from_c4(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        for cid in (303, 304):
            c = self._case(memo, cid)
            self.assertEqual(c["event_date_quality"], "clean_discrete_anchor")
            self.assertIn("keep_staged_no_paid", c["disposition"])

    def test_degraded_anchor_is_flagged_not_assumed_clean(self):
        self._seed_live_like()
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "UPDATE events SET headline = ? WHERE id = 304",
                ("DOJ considers expected action against Google over proposed "
                 "ad-tech remedies",))
            conn.commit()
        memo = M.build_memo(db_path=self._tmp)
        c304 = self._case(memo, 304)
        self.assertEqual(c304["event_date_quality"], "partial_anticipation")
        self.assertIn("caution", c304["disposition"].lower())

    def test_304_paid_path_closed_and_303_not(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        c304 = self._case(memo, 304)
        self.assertIn("deferred", c304["paid_status"].lower())
        self.assertIn("CANDIDATE_304_PAID_GATE_PACKET", c304["paid_status"])
        self.assertNotIn("deferred", self._case(memo, 303)["paid_status"].lower())
        self.assertIn("closed", memo["comparison_scope"]["paid_path_status"].lower())


class TestComparisonContent(_Base):
    def test_mechanism_comparison_block(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        mc = memo["mechanism_comparison"]
        self.assertEqual(mc["conduct_platform_ecosystem_case"], 303)
        self.assertEqual(mc["structural_adtech_stack_case"], 304)
        self.assertTrue(mc["similarities"])
        self.assertTrue(mc["differences"])
        self.assertTrue(mc["why_304_is_not_a_paid_candidate_now"])
        self.assertTrue(mc["what_can_be_read"])
        self.assertTrue(mc["what_cannot_be_read"])

    def test_stronger_readout_not_read_as_mechanism_strength(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        rc = memo["mechanism_comparison"]["readout_contrast"]
        low = rc["not_strength_statement"].lower()
        self.assertIn("does not establish", low)
        self.assertIn("mechanism strength", low)
        # the exposure-mix confound is the core honest point
        self.assertIn("confound", " ".join([
            rc["not_strength_statement"],
            " ".join(memo["mechanism_comparison"]["differences"]),
        ]).lower())

    def test_cases_carry_adds_and_does_not_show(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        for cid in (303, 304):
            c = self._case(memo, cid)
            self.assertTrue(c["what_the_case_adds"])
            self.assertTrue(c["what_the_case_does_not_show"])
            self.assertTrue(c["mechanism_interpretation"])

    def test_readouts_n1_descriptive(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        for c in memo["cases"]:
            ro = c["local_readout"]
            self.assertTrue(ro["descriptive_only"])
            self.assertTrue(ro["n_equals_one"])


class TestDiscipline(_Base):
    def test_denominators_separated(self):
        self._seed_live_like()
        self._seed(10, stage="realized", family="none",
                   event_date="2026-04-05", headline="Foo imposes bar",
                   tickers=("FOO",))
        memo = M.build_memo(db_path=self._tmp)
        d = memo["denominators"]
        self.assertEqual(d["archive_rows"], 7)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 5)
        self.assertEqual(d["regulation_staged_count"], 5)
        self.assertEqual(d["regulation_accepted_count"], 0)

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        for c in memo["cases"]:
            self.assertEqual(c["stage"], "z1a_candidate_pack")
            self.assertEqual(c["corpus_status"], "staged")

    def test_non_claims_cover_required_ground(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        blob = " ".join(memo["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "recommendation",
                       "denominator", "fdr", "closed"):
            self.assertIn(needle, blob)
        moves = " ".join(memo["next_no_paid_moves"]).lower()
        self.assertIn("no paid", moves)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        text = M._render_text(memo)
        text.encode("cp1252")
        low = text.lower()
        for section in ("conduct vs structural", "not proof",
                        "disposition", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like()
        memo = M.build_memo(db_path=self._tmp)
        text = M._render_text(memo) + " " + json.dumps(memo)
        with open(os.path.join(_REPO, "scripts",
                               "regulation_conduct_structural_memo.py"),
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
