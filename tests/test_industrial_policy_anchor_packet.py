"""Tests for scripts/industrial_policy_anchor_packet.py (read-only).

The industrial-policy anchor packet consumes the C4 layer for labels (derived,
never hardcoded), explains why signing dates are weak anchors, states the
alternative anchor types and the local-evidence split (price history present,
milestone event rows missing), and keeps 311/312 staged/no-paid.
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

from scripts import industrial_policy_anchor_packet as P  # noqa: E402


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
            tempfile.gettempdir(), f"test_ipa_{uuid.uuid4().hex}.db",
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
              family="industrial_policy", event_date="2022-08-09",
              headline="CHIPS and Science Act signed into law", tickers=("INTC", "MU")):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(tickers)),
            )
            conn.commit()

    def _seed_live_like(self):
        self._seed(311)
        self._seed(312, event_date="2022-08-16",
                   headline="Inflation Reduction Act of 2022 signed into law",
                   tickers=("FSLR", "ENPH"))
        # non-family staged row that must NOT enter
        self._seed(313, family="labor_inflation", event_date="2023-09-15",
                   headline="UAW Stand Up Strike begins", tickers=("GM",))

    def _seed_price_days(self, ticker, days):
        with sqlite3.connect(self._tmp) as conn:
            for d in days:
                conn.execute(
                    "INSERT OR REPLACE INTO price_cache VALUES (?,?,?,?,0,'t')",
                    (ticker, d, 100.0, 1.0e6))
            conn.commit()

    def _case(self, pkt, event_id):
        for c in pkt["cases"]:
            if c["event_id"] == event_id:
                return c
        raise AssertionError(f"case {event_id} missing")


class TestSelectionAndLabels(_Base):
    def test_selects_only_industrial_policy_staged_rows(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        ids = {c["event_id"] for c in pkt["cases"]}
        self.assertEqual(ids, {311, 312})

    def test_scheduled_weak_labels_from_c4(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        for cid in (311, 312):
            c = self._case(pkt, cid)
            self.assertEqual(c["event_date_quality"], "scheduled_or_weak_anchor")
            self.assertEqual(c["anticipation_risk"], "high")
        scope = pkt["cohort_scope"]
        self.assertEqual(sorted(scope["reanchor_needed_ids"]), [311, 312])

    def test_label_derived_not_hardcoded(self):
        # Reword 311 as a discrete rule action: the label and disposition
        # must follow the wording, not the id.
        self._seed(311, headline="Commerce implements CHIPS subsidy "
                                 "allocation rule for fabs")
        pkt = P.build_packet(db_path=self._tmp)
        c = self._case(pkt, 311)
        self.assertEqual(c["event_date_quality"], "clean_discrete_anchor")
        self.assertNotIn("re-anchor", c["disposition"])
        self.assertNotIn(311, pkt["cohort_scope"]["reanchor_needed_ids"])

    def test_stage_passthrough_no_promotion(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        for c in pkt["cases"]:
            self.assertEqual(c["stage"], "z1a_candidate_pack")
            self.assertEqual(c["corpus_status"], "staged")


class TestAnchorReasoningAndEvidence(_Base):
    def test_weak_anchor_explanation_present(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        for cid in (311, 312):
            why = self._case(pkt, cid)["why_current_anchor_is_weak"].lower()
            self.assertIn("signing", why)
            self.assertTrue("priced" in why or "telegraphed" in why)

    def test_alternative_anchor_types_listed(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        req = pkt["policy_timeline_requirements"]["required_anchor_types"]
        blob = " ".join(req).lower()
        self.assertGreaterEqual(len(req), 4)
        for needle in ("bill text", "vote", "conference", "signing"):
            self.assertIn(needle, blob)
        c311 = self._case(pkt, 311)
        self.assertTrue(c311["alternative_anchor_types_needed"])

    def test_local_evidence_split_price_present_rows_missing(self):
        self._seed_live_like()
        # deep pre-signing price history for one exposed ticker
        self._seed_price_days("INTC", [f"2022-0{m}-1{d}" for m in (3, 4, 5, 6)
                                       for d in range(0, 5)])
        pkt = P.build_packet(db_path=self._tmp)
        c311 = self._case(pkt, 311)
        present = " ".join(c311["local_evidence_present"]).lower()
        missing = " ".join(c311["local_evidence_missing"]).lower()
        self.assertIn("intc", present)
        self.assertIn("pre-signing", missing)
        self.assertIn("milestone", missing)

    def test_nearby_milestone_row_is_surfaced_when_it_exists(self):
        self._seed_live_like()
        self._seed(900, stage="realized", family="none",
                   event_date="2022-07-20",
                   headline="Senate advances semiconductor subsidy bill in "
                            "surprise cloture vote", tickers=("INTC",))
        pkt = P.build_packet(db_path=self._tmp)
        c311 = self._case(pkt, 311)
        blob = " ".join(c311["local_evidence_present"])
        self.assertIn("900", blob)

    def test_readout_fields_n1_descriptive(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        for c in pkt["cases"]:
            ro = c["local_readout"]
            self.assertTrue(ro["descriptive_only"])
            self.assertTrue(ro["n_equals_one"])
            self.assertFalse(ro["available"])  # fixture has no usable series


class TestDispositionAndShape(_Base):
    def test_disposition_keep_staged_no_paid_reanchor(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        for cid in (311, 312):
            disp = self._case(pkt, cid)["disposition"]
            self.assertIn("keep_staged_no_paid", disp)
            self.assertIn("re-anchor", disp)

    def test_denominators_separated(self):
        self._seed_live_like()
        self._seed(10, stage="realized", family="none",
                   event_date="2026-04-05", headline="Foo imposes bar",
                   tickers=("FOO",))
        pkt = P.build_packet(db_path=self._tmp)
        d = pkt["denominators"]
        self.assertEqual(d["archive_rows"], 4)
        self.assertEqual(d["accepted_coverage_denominator"], 1)
        self.assertEqual(d["staged_candidate_count"], 3)
        self.assertEqual(d["industrial_policy_staged_count"], 2)
        self.assertEqual(d["industrial_policy_accepted_count"], 0)

    def test_family_interpretation_block(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        fi = pkt["family_interpretation"]
        for key in ("what_can_be_read", "what_cannot_be_read",
                    "why_signing_windows_are_residual_surprise_only"):
            self.assertIn(key, fi)
            self.assertTrue(fi[key])
        self.assertIn("residual", fi["what_can_be_read"].lower())

    def test_next_no_paid_moves_and_non_claims(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        moves = " ".join(pkt["next_no_paid_moves"]).lower()
        self.assertIn("no paid", moves)
        blob = " ".join(pkt["non_claims"]).lower()
        for needle in ("not accepted evidence", "no paid", "promot",
                       "significance", "family-level", "recommendation",
                       "denominator", "fdr", "signing"):
            self.assertIn(needle, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_with_required_sections(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt)
        text.encode("cp1252")
        low = text.lower()
        for section in ("why signing anchors are weak",
                        "alternative anchors", "disposition", "non-claims"):
            self.assertIn(section, low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed_live_like()
        pkt = P.build_packet(db_path=self._tmp)
        text = P._render_text(pkt) + " " + json.dumps(pkt)
        with open(os.path.join(_REPO, "scripts",
                               "industrial_policy_anchor_packet.py"),
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
