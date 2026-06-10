"""Tests for scripts/sanction_thread_collapse_report.py (read-only).

The thread-collapse report must derive sibling links from the C4 layer (never
hardcode them), separate raw staged row count from independent-event count,
surface the curated anchors each staged row continues, and keep everything
staged/no-paid with no breadth overclaim.
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

from scripts import sanction_thread_collapse_report as R  # noqa: E402


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
            tempfile.gettempdir(), f"test_stc_{uuid.uuid4().hex}.db",
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
              family="sanction", event_date="2022-10-07",
              headline="headline", tickers=("NVDA",)):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(tickers)),
            )
            conn.commit()

    def _seed_live_like(self):
        # curated anchors
        self._seed(298, stage="curated_observation", event_date="2019-05-16",
                   headline="BIS adds Huawei + 68 affiliates to the Entity "
                            "List, cutting US RF/chip suppliers' access",
                   tickers=("QRVO",))
        self._seed(300, stage="curated_observation", event_date="2022-08-31",
                   headline="US imposes a license requirement on NVIDIA "
                            "A100/H100 datacenter GPU exports to China",
                   tickers=("NVDA",))
        self._seed(301, stage="curated_observation", event_date="2020-12-18",
                   headline="BIS adds SMIC to the Entity List (presumption "
                            "of denial), cutting US semicap suppliers",
                   tickers=("LRCX",))
        # staged thread rows
        self._seed(307, event_date="2022-10-07",
                   headline="Commerce/BIS implements advanced-computing and "
                            "semiconductor-manufacturing export controls on "
                            "the PRC", tickers=("NVDA", "AMD"))
        self._seed(308, event_date="2023-10-17",
                   headline="Commerce/BIS strengthens advanced-computing and "
                            "semiconductor-equipment export controls",
                   tickers=("NVDA", "AMAT"))
        self._seed(309, event_date="2020-05-15",
                   headline="Commerce amends Foreign Direct Product Rule and "
                            "Entity List targeting Huawei chip sourcing",
                   tickers=("QCOM", "SMH"))
        self._seed(310, event_date="2025-04-15",
                   headline="NVIDIA discloses US license requirement for H20 "
                            "China exports and an estimated charge (8-K)",
                   tickers=("NVDA", "AMD"))
        # a non-sanction staged row that must NOT enter
        self._seed(313, family="labor_inflation", event_date="2023-09-15",
                   headline="UAW Stand Up Strike begins", tickers=("GM",))

    def _case(self, rep, event_id):
        for c in rep["cases"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestSelectionAndLinks(_Base):
    def test_selects_307_310_only(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual({c["event_id"] for c in rep["cases"]},
                         {307, 308, 309, 310})

    def test_related_anchors_mechanical_plus_context(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        scope = rep["thread_scope"]
        self.assertIn(298, scope["related_curated_or_accepted_ids"])
        self.assertIn(300, scope["related_curated_or_accepted_ids"])
        self.assertIn(301, scope["related_curated_or_accepted_ids"])
        anchor_ids = {a["event_id"] for a in rep["related_anchor_rows"]}
        self.assertEqual(anchor_ids, set(scope["related_curated_or_accepted_ids"]))
        # 301's link is registry context, not a mechanical C4 link
        a301 = [a for a in rep["related_anchor_rows"] if a["event_id"] == 301][0]
        self.assertIn("context", a301["link_provenance"])
        a300 = [a for a in rep["related_anchor_rows"] if a["event_id"] == 300][0]
        self.assertIn("mechanical", a300["link_provenance"])

    def test_sibling_labels_consumed_from_c4(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        for cid in (307, 308, 309, 310):
            c = self._case(rep, cid)
            self.assertEqual(c["event_date_quality"],
                             "continuation_or_thread_sibling")
            self.assertTrue(c["related_anchor_ids"])
        self.assertIn(300, self._case(rep, 307)["related_anchor_ids"])
        self.assertIn(298, self._case(rep, 309)["related_anchor_ids"])

    def test_independence_derived_not_hardcoded(self):
        # Reword 307 with no thread-lexicon token and a non-overlapping
        # ticker: the C4 layer stops calling it a sibling, and the report
        # must then count it as a potential independent event.
        self._seed_live_like()
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "UPDATE events SET headline = ?, market_tickers = ? "
                "WHERE id = 307",
                ("Treasury imposes new petroleum shipping restrictions",
                 _mt(("AVGO",))),
            )
            conn.commit()
        rep = R.build_report(db_path=self._tmp)
        scope = rep["thread_scope"]
        self.assertIn(307, scope["independent_event_ids"])
        self.assertNotIn(307, scope["likely_thread_sibling_ids"])
        c307 = self._case(rep, 307)
        self.assertIn("potential_independent", c307["disposition"])


class TestBreadthAccounting(_Base):
    def test_raw_vs_independent_counts(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        b = rep["breadth_accounting"]
        self.assertEqual(b["raw_staged_row_count"], 4)
        self.assertEqual(b["staged_rows_adding_independent_events"], 0)
        self.assertEqual(b["effective_thread_count"], 2)
        self.assertTrue(b["explanation"])

    def test_thread_components_rooted_at_curated_anchors(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        comps = rep["breadth_accounting"]["thread_components"]
        as_sets = [set(c) for c in comps]
        self.assertIn({300, 307, 308, 310}, as_sets)
        self.assertIn({298, 309}, as_sets)


class TestCasesAndDiscipline(_Base):
    def test_readouts_thread_caveated_n1(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        for c in rep["cases"]:
            ro = c["local_readout"]
            self.assertTrue(ro["descriptive_only"])
            self.assertTrue(ro["n_equals_one"])
            self.assertTrue(ro["thread_caveated"])

    def test_dispositions_collapse_or_defer(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        for cid in (307, 308, 309, 310):
            disp = self._case(rep, cid)["disposition"]
            self.assertIn("collapse_into_thread_or_defer", disp)
        self.assertEqual(sorted(rep["thread_scope"]["collapse_or_defer_ids"]),
                         [307, 308, 309, 310])

    def test_what_new_information_present_per_case(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        for c in rep["cases"]:
            self.assertTrue(c["what_new_information_if_any"])
            self.assertTrue(c["why_this_may_be_thread_sibling"])

    def test_denominators_separated(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        d = rep["denominators"]
        self.assertEqual(d["archive_rows"], 8)
        self.assertEqual(d["accepted_coverage_denominator"], 3)  # curated
        self.assertEqual(d["accepted_track_record_denominator"], 0)
        self.assertEqual(d["staged_candidate_count"], 5)
        self.assertEqual(d["sanction_or_export_control_staged_count"], 4)
        self.assertEqual(d["related_accepted_or_curated_count"], 3)

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        for c in rep["cases"]:
            self.assertEqual(c["stage"], "z1a_candidate_pack")
            self.assertEqual(c["corpus_status"], "staged")

    def test_interpretation_and_non_claims(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        ti = rep["thread_interpretation"]
        for key in ("what_can_be_read", "what_cannot_be_read",
                    "why_raw_row_count_overstates_breadth",
                    "how_to_treat_307_310_in_future_packets"):
            self.assertTrue(ti[key])
        self.assertIn("overlap", ti["why_raw_row_count_overstates_breadth"].lower())
        blob = " ".join(rep["non_claims"]).lower()
        for needle in ("not accepted evidence", "not independent breadth",
                       "no paid", "promot", "significance", "family-level",
                       "recommendation", "denominator", "fdr"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep)
        text.encode("cp1252")
        low = text.lower()
        for section in ("overstate", "adds", "disposition", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like()
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "sanction_thread_collapse_report.py"),
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
