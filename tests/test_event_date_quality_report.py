"""Tests for scripts/event_date_quality_report.py (read-only).

The event-date quality layer assigns categorical anchor labels (never numeric
fake precision), keeps accepted vs staged separated, surfaces weak anchors and
duplicates, and phrases every label as research caution - never as proof,
significance, or validation.
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

from scripts import event_date_quality_report as R  # noqa: E402


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
            tempfile.gettempdir(), f"test_edq_{uuid.uuid4().hex}.db",
        )
        conn = sqlite3.connect(self._tmp)
        try:
            conn.execute(_EVENTS_DDL)
            conn.execute(_EVENT_HYGIENE_DDL)
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def _seed(self, event_id, *, stage="z1a_candidate_pack", family="regulation",
              event_date="2024-03-21", headline="headline", ticker="AAA"):
        with sqlite3.connect(self._tmp) as conn:
            conn.execute(
                "INSERT INTO events (id, event_date, stage, mechanism_family, "
                "headline, market_tickers) VALUES (?,?,?,?,?,?)",
                (event_id, event_date, stage, family, headline, _mt(ticker)),
            )
            conn.commit()

    def _event(self, report, event_id):
        for e in report["events"]:
            if e["event_id"] == event_id:
                return e
        raise AssertionError(f"event {event_id} missing from report")


class TestLabelRules(_Base):
    def test_doj_suit_filing_is_clean_discrete_anchor(self):
        self._seed(1, headline="Justice Department sues Apple for monopolizing "
                               "smartphone markets", ticker="AAPL")
        rep = R.build_report(db_path=self._tmp)
        e = self._event(rep, 1)
        self.assertEqual(e["event_date_quality"], "clean_discrete_anchor")
        self.assertEqual(e["anticipation_risk"], "low")
        self.assertTrue(e["anchor_rationale"])
        self.assertTrue(e["horizon_interpretation_caution"])

    def test_anticipation_wording_maps_to_partial_anticipation(self):
        self._seed(1, headline="Regulator considers new rules and is expected "
                               "to act on the proposed framework", ticker="XYZ")
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 1)["event_date_quality"],
                         "partial_anticipation")

    def test_signed_into_law_is_scheduled_or_weak_anchor(self):
        self._seed(1, family="industrial_policy", event_date="2022-08-09",
                   headline="CHIPS and Science Act signed into law "
                            "(Public Law 117-167)", ticker="INTC")
        rep = R.build_report(db_path=self._tmp)
        e = self._event(rep, 1)
        self.assertEqual(e["event_date_quality"], "scheduled_or_weak_anchor")
        self.assertEqual(e["anticipation_risk"], "high")

    def test_strike_begins_is_partial_anticipation_not_clean(self):
        self._seed(1, family="labor_inflation", event_date="2023-09-15",
                   headline="UAW Stand Up Strike begins against GM, Ford, and "
                            "Stellantis", ticker="GM")
        rep = R.build_report(db_path=self._tmp)
        e = self._event(rep, 1)
        self.assertEqual(e["event_date_quality"], "partial_anticipation")
        self.assertNotEqual(e["event_date_quality"], "clean_discrete_anchor")

    def test_same_date_ticker_headline_pair_is_duplicate_or_deferred(self):
        self._seed(302, event_date="2023-09-26", ticker="AMZN",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(315, stage="analysis_pending_review", family="none",
                   event_date="2023-09-26", ticker="AMZN",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        rep = R.build_report(db_path=self._tmp)
        e302 = self._event(rep, 302)
        self.assertEqual(e302["event_date_quality"], "duplicate_or_deferred")
        self.assertIn("315", e302["thread_independence"])

    def test_identical_headline_same_date_is_duplicate_even_with_different_primary(self):
        # Live 302/315: identical headline + date, but 315's primary leg is a
        # different ticker (EBAY vs AMZN). Still the same announcement.
        self._seed(302, event_date="2023-09-26", ticker="AMZN",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        self._seed(315, stage="analysis_pending_review", family="none",
                   event_date="2023-09-26", ticker="EBAY",
                   headline="FTC sues Amazon.com for illegally maintaining "
                            "monopoly power")
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 302)["event_date_quality"],
                         "duplicate_or_deferred")
        self.assertEqual(self._event(rep, 315)["event_date_quality"],
                         "duplicate_or_deferred")

    def test_keywords_match_whole_words_not_substrings(self):
        # 'sues' must not fire inside 'issues'; the rationale must cite the
        # real keyword.
        self._seed(294, stage="curated_observation", family="tariff",
                   event_date="2015-12-22", ticker="STLD",
                   headline="Commerce issues affirmative PRELIMINARY AD/CVD "
                            "determinations on corrosion-resistant steel")
        # 'possible' must not fire inside 'impossible'.
        self._seed(2, event_date="2026-01-08", ticker="ZZZ", family="none",
                   stage="realized",
                   headline="Impossible demands stall talks as sides dig in")
        rep = R.build_report(db_path=self._tmp)
        e294 = self._event(rep, 294)
        self.assertEqual(e294["event_date_quality"], "clean_discrete_anchor")
        self.assertIn("issues", e294["anchor_rationale"])
        self.assertNotIn("'sues'", e294["anchor_rationale"])
        self.assertEqual(self._event(rep, 2)["event_date_quality"],
                         "manual_review_needed")

    def test_later_same_family_same_ticker_row_is_thread_sibling(self):
        self._seed(300, stage="curated_observation", family="sanction",
                   event_date="2022-08-31", ticker="NVDA",
                   headline="US imposes a license requirement on NVIDIA A100/"
                            "H100 datacenter GPU exports to China")
        self._seed(307, family="sanction", event_date="2022-10-07",
                   ticker="NVDA",
                   headline="Commerce/BIS implements advanced-computing and "
                            "semiconductor-manufacturing export controls on the PRC")
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 307)["event_date_quality"],
                         "continuation_or_thread_sibling")
        # The earlier anchor must NOT be a sibling of its own continuation.
        self.assertNotEqual(self._event(rep, 300)["event_date_quality"],
                            "continuation_or_thread_sibling")

    def test_thread_lexicon_token_links_different_ticker_sibling(self):
        self._seed(298, stage="curated_observation", family="sanction",
                   event_date="2019-05-16", ticker="QRVO",
                   headline="BIS adds Huawei + 68 affiliates to the Entity List")
        self._seed(309, family="sanction", event_date="2020-05-15",
                   ticker="QCOM",
                   headline="Commerce amends Foreign Direct Product Rule and "
                            "Entity List targeting Huawei chip sourcing")
        rep = R.build_report(db_path=self._tmp)
        e309 = self._event(rep, 309)
        self.assertEqual(e309["event_date_quality"],
                         "continuation_or_thread_sibling")
        self.assertIn("298", e309["thread_independence"])

    def test_missing_date_or_no_keyword_is_manual_review_needed(self):
        self._seed(1, event_date="", headline="Justice Department sues X",
                   ticker="X")
        self._seed(2, headline="Quarterly observations on regional dynamics",
                   ticker="Y")
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 1)["event_date_quality"],
                         "manual_review_needed")
        self.assertEqual(self._event(rep, 2)["event_date_quality"],
                         "manual_review_needed")


class TestSeparationAndShape(_Base):
    def _seed_mixed(self):
        self._seed(10, stage="realized", family="none",
                   headline="Justice Department sues Foo", ticker="FOO",
                   event_date="2026-04-05")
        self._seed(11, stage="curated_observation", family="tariff",
                   headline="Commerce imposes duties", ticker="STLD",
                   event_date="2015-12-22")
        self._seed(303, headline="Justice Department sues Apple for "
                                 "monopolizing smartphone markets",
                   ticker="AAPL")
        self._seed(20, stage="curated_intake", family="policy_surprise",
                   headline="intake stub", ticker="CCC")

    def test_corpus_status_separation(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 10)["corpus_status"], "accepted")
        self.assertEqual(self._event(rep, 11)["corpus_status"], "curated")
        self.assertEqual(self._event(rep, 303)["corpus_status"], "staged")
        # intake stub is excluded, not classified
        ids = {e["event_id"] for e in rep["events"]}
        self.assertNotIn(20, ids)
        self.assertIn("staged", rep["label_counts"]["by_corpus_status"])
        self.assertIn("accepted", rep["label_counts"]["by_corpus_status"])

    def test_stage_passthrough_no_promotion(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp)
        self.assertEqual(self._event(rep, 303)["stage"], "z1a_candidate_pack")

    def test_denominator_metadata(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp)
        d = rep["denominators"]
        self.assertEqual(d["archive_rows"], 4)
        self.assertEqual(d["accepted_coverage_denominator"], 2)  # 10 + 11
        self.assertEqual(d["accepted_track_record_denominator"], 1)  # minus curated
        self.assertEqual(d["staged_candidate_count"], 1)
        self.assertEqual(d["excluded_counts"]["curated_intake"], 1)

    def test_lens_staged_filters_events(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp, lens="staged")
        ids = {e["event_id"] for e in rep["events"]}
        self.assertEqual(ids, {303})

    def test_non_claims_cover_required_ground(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp)
        blob = " ".join(rep["non_claims"]).lower()
        for needle in ("not proof", "illustrative", "not accepted evidence",
                       "no paid", "promot", "significance", "denominator",
                       "fdr"):
            self.assertIn(needle, blob)

    def test_no_label_or_caution_reads_as_proof_or_validation(self):
        self._seed_mixed()
        rep = R.build_report(db_path=self._tmp)
        for e in rep["events"]:
            blob = " ".join([
                e["event_date_quality"], e["anticipation_risk"],
                e["thread_independence"], e["anchor_rationale"],
                e["horizon_interpretation_caution"],
            ]).lower()
            for bad in ("proves", "proven", "validated", "confirmed",
                        "significant"):
                self.assertNotIn(bad, blob)


class TestRendering(_Base):
    def test_text_render_cp1252_safe_with_weak_anchor_section(self):
        self._seed(311, family="industrial_policy", event_date="2022-08-09",
                   headline="CHIPS and Science Act signed into law",
                   ticker="INTC")
        self._seed(303, headline="Justice Department sues Apple for "
                                 "monopolizing smartphone markets",
                   ticker="AAPL")
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep)
        text.encode("cp1252")
        low = text.lower()
        self.assertIn("weak", low)
        self.assertIn("staged", low)
        self.assertIn("before cohort", low)

    def test_banned_framing_absent_from_source_and_output(self):
        self._seed(303, headline="Justice Department sues Apple", ticker="AAPL")
        rep = R.build_report(db_path=self._tmp)
        text = R._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts", "event_date_quality_report.py"),
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
