"""Tests for scripts/validation_status_calibration_report.py.

The report is a READ-ONLY calibration of the production
``validation_status.score_validation_status`` decision rule against the
real event archive. These tests protect:

  * the accepted-track-record eligibility gate (NON_THESIS_STAGES +
    synthetic-seed exclusion) — the established "86" denominator, kept
    separate from any raw/archive lens (never summed);
  * missingness accounting (archive == accepted + excluded-by-reason);
  * the directional-evidence-count distribution and the decisive-label
    1/2/3+ breakdown (the crux output);
  * candidate re-labelings that hold the non-directional branch fixed;
  * transition-matrix accounting and percentage reconciliation;
  * family / age-bucket stratification;
  * honest handling of an absent manual rating (no independent target);
  * read-only DB behaviour (bytes unchanged), deterministic Markdown, and
    no provider/network import.

Pure-function fixtures are dict literals; the DB integration test builds a
throwaway SQLite database with the real schema via ``db.init_db()``.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import validation_status_calibration_report as rpt

# A fixed clock so age-dependent (pending/unresolved) branches are
# deterministic. Decisive labels are as-of-invariant regardless.
NOW = datetime(2026, 7, 11, 12, 0, 0)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _ticker(direction_tag=None, role=None, return_1d=None, symbol="AAA"):
    t = {"symbol": symbol}
    if direction_tag is not None:
        t["direction_tag"] = direction_tag
    if role is not None:
        t["role"] = role
    if return_1d is not None:
        t["return_1d"] = return_1d
    return t


def _sup(n):
    return [_ticker(direction_tag="supports_thesis", symbol=f"S{i}") for i in range(n)]


def _con(n):
    return [_ticker(direction_tag="contradicts_thesis", symbol=f"C{i}") for i in range(n)]


def _event(*, eid=1, sup=0, con=0, stage="realized", family=None,
           event_date="2026-01-01", rating=None, extra_tickers=None,
           mechanism_summary="thesis text"):
    ev = {
        "id": eid,
        "stage": stage,
        "event_date": event_date,
        "timestamp": event_date + "T12:00:00",
        "mechanism_summary": mechanism_summary,
        "mechanism_family": family,
        "market_tickers": _sup(sup) + _con(con) + (extra_tickers or []),
        "rating": rating,
    }
    return ev


# ---------------------------------------------------------------------------
# Eligibility gate
# ---------------------------------------------------------------------------


class TestEligibilityGate(unittest.TestCase):
    NON_THESIS = frozenset({"curated_intake", "curated_observation",
                            "z1a_candidate_pack", "analysis_pending_review"})

    def test_accepted_row(self):
        ev = _event(eid=1, stage="realized")
        self.assertEqual(
            rpt.classify_eligibility(ev, synthetic_ids=frozenset(),
                                     non_thesis_stages=self.NON_THESIS),
            "accepted")

    def test_non_thesis_stage_excluded(self):
        ev = _event(eid=2, stage="curated_observation")
        self.assertEqual(
            rpt.classify_eligibility(ev, synthetic_ids=frozenset(),
                                     non_thesis_stages=self.NON_THESIS),
            "excluded_non_thesis_stage")

    def test_synthetic_seed_excluded(self):
        ev = _event(eid=3, stage="realized")
        self.assertEqual(
            rpt.classify_eligibility(ev, synthetic_ids=frozenset({3}),
                                     non_thesis_stages=self.NON_THESIS),
            "excluded_synthetic_seed")

    def test_stage_checked_before_synthetic(self):
        # A row that is BOTH a non-thesis stage and synthetic counts once,
        # under the stage reason (stage is checked first) — no double count.
        ev = _event(eid=4, stage="curated_intake")
        self.assertEqual(
            rpt.classify_eligibility(ev, synthetic_ids=frozenset({4}),
                                     non_thesis_stages=self.NON_THESIS),
            "excluded_non_thesis_stage")


class TestFunnelReconciles(unittest.TestCase):
    NON_THESIS = frozenset({"curated_intake", "curated_observation"})

    def test_archive_equals_accepted_plus_excluded(self):
        events = [
            _event(eid=1, stage="realized"),
            _event(eid=2, stage="anticipation"),
            _event(eid=3, stage="curated_observation"),   # stage excluded
            _event(eid=4, stage="realized"),               # synthetic
            _event(eid=5, stage="curated_intake"),         # stage excluded
        ]
        funnel = rpt.build_funnel(events, synthetic_ids=frozenset({4}),
                                  non_thesis_stages=self.NON_THESIS)
        self.assertEqual(funnel["archive_rows"], 5)
        self.assertEqual(funnel["excluded_non_thesis_stage"], 2)
        self.assertEqual(funnel["excluded_synthetic_seed"], 1)
        self.assertEqual(funnel["accepted"], 2)
        self.assertEqual(
            funnel["accepted"] + funnel["excluded_non_thesis_stage"]
            + funnel["excluded_synthetic_seed"],
            funnel["archive_rows"])


# ---------------------------------------------------------------------------
# Per-event characterization (wraps the production scorer)
# ---------------------------------------------------------------------------


class TestCharacterize(unittest.TestCase):
    def test_single_supporting_is_validated(self):
        ch = rpt.characterize_event(_event(sup=1, con=0), now=NOW)
        self.assertEqual(ch["supporting"], 1)
        self.assertEqual(ch["contradicting"], 0)
        self.assertEqual(ch["directional"], 1)
        self.assertEqual(ch["current_status"], "validated")

    def test_single_contradicting_is_contradicted(self):
        ch = rpt.characterize_event(_event(sup=0, con=1), now=NOW)
        self.assertEqual(ch["directional"], 1)
        self.assertEqual(ch["current_status"], "contradicted")

    def test_tie_is_contradicted(self):
        ch = rpt.characterize_event(_event(sup=2, con=2), now=NOW)
        self.assertEqual(ch["current_status"], "contradicted")
        self.assertEqual(ch["directional"], 4)

    def test_zero_directional_is_not_decisive(self):
        ch = rpt.characterize_event(
            _event(sup=0, con=0, extra_tickers=[_ticker(role="beneficiary")]),
            now=NOW)
        self.assertEqual(ch["directional"], 0)
        self.assertIn(ch["current_status"], ("unresolved", "pending"))

    def test_missing_ticker_array_handled(self):
        ev = _event(sup=0, con=0)
        ev["market_tickers"] = None
        ch = rpt.characterize_event(ev, now=NOW)
        self.assertEqual(ch["total_tickers"], 0)
        self.assertEqual(ch["directional"], 0)

    def test_malformed_ticker_entries_handled(self):
        ev = _event(sup=0, con=0)
        ev["market_tickers"] = ["AAA", 123, None, {"symbol": "X"}]
        ch = rpt.characterize_event(ev, now=NOW)
        # Non-dict entries never crash; none are directional.
        self.assertEqual(ch["directional"], 0)

    def test_rating_carried_when_present(self):
        ch = rpt.characterize_event(_event(sup=2, con=0, rating="good"), now=NOW)
        self.assertEqual(ch["rating"], "good")

    def test_rating_none_when_absent(self):
        ch = rpt.characterize_event(_event(sup=2, con=0, rating=None), now=NOW)
        self.assertIsNone(ch["rating"])


# ---------------------------------------------------------------------------
# Candidate re-labelings — hold the non-directional branch fixed
# ---------------------------------------------------------------------------


class TestCandidateCurrent(unittest.TestCase):
    def test_non_directional_passthrough(self):
        self.assertEqual(rpt.candidate_current("unresolved", 0, 0), "unresolved")
        self.assertEqual(rpt.candidate_current("pending", 0, 0), "pending")

    def test_majority(self):
        self.assertEqual(rpt.candidate_current("x", 2, 0), "validated")
        self.assertEqual(rpt.candidate_current("x", 1, 2), "contradicted")
        self.assertEqual(rpt.candidate_current("x", 1, 1), "contradicted")  # tie


class TestCandidateMin2(unittest.TestCase):
    def test_single_ticker_becomes_unresolved(self):
        self.assertEqual(rpt.candidate_min2("validated", 1, 0), "unresolved")
        self.assertEqual(rpt.candidate_min2("contradicted", 0, 1), "unresolved")

    def test_two_or_more_uses_majority(self):
        self.assertEqual(rpt.candidate_min2("x", 2, 0), "validated")
        self.assertEqual(rpt.candidate_min2("x", 1, 1), "contradicted")  # d=2, tie
        self.assertEqual(rpt.candidate_min2("x", 1, 2), "contradicted")

    def test_non_directional_passthrough(self):
        self.assertEqual(rpt.candidate_min2("unresolved", 0, 0), "unresolved")


class TestCandidateTieUnresolved(unittest.TestCase):
    def test_tie_becomes_unresolved(self):
        self.assertEqual(rpt.candidate_tie_unresolved("contradicted", 2, 2),
                         "unresolved")

    def test_single_ticker_still_decisive(self):
        self.assertEqual(rpt.candidate_tie_unresolved("x", 1, 0), "validated")
        self.assertEqual(rpt.candidate_tie_unresolved("x", 0, 1), "contradicted")

    def test_non_directional_passthrough(self):
        self.assertEqual(rpt.candidate_tie_unresolved("pending", 0, 0), "pending")


class TestCandidateMin2Supermajority(unittest.TestCase):
    def test_single_ticker_unresolved(self):
        self.assertEqual(rpt.candidate_min2_supermajority("x", 1, 0), "unresolved")

    def test_supermajority_validated(self):
        self.assertEqual(rpt.candidate_min2_supermajority("x", 2, 0), "validated")

    def test_supermajority_contradicted(self):
        self.assertEqual(rpt.candidate_min2_supermajority("x", 1, 2), "contradicted")

    def test_mixed_middle_unresolved(self):
        # ratio 0.4 (2 of 5) is neither >= 2/3 nor <= 1/3 → unresolved
        self.assertEqual(rpt.candidate_min2_supermajority("x", 2, 3), "unresolved")
        # exact tie 2/2 → unresolved
        self.assertEqual(rpt.candidate_min2_supermajority("x", 2, 2), "unresolved")

    def test_non_directional_passthrough(self):
        self.assertEqual(rpt.candidate_min2_supermajority("unresolved", 0, 0),
                         "unresolved")


class TestCandidateRegistryDeterministic(unittest.TestCase):
    def test_registry_is_stable_and_includes_current_first(self):
        keys1 = [c["key"] for c in rpt.CANDIDATES]
        keys2 = [c["key"] for c in rpt.CANDIDATES]
        self.assertEqual(keys1, keys2)
        self.assertEqual(keys1[0], "current")
        self.assertIn("min2", keys1)


# ---------------------------------------------------------------------------
# Distributions and the decisive-label crux breakdown
# ---------------------------------------------------------------------------


def _chars(specs, now=NOW):
    return [rpt.characterize_event(_event(eid=i, sup=s, con=c), now=now)
            for i, (s, c) in enumerate(specs, start=1)]


class TestDistributions(unittest.TestCase):
    def test_directional_count_distribution(self):
        ch = _chars([(1, 0), (2, 0), (2, 1), (0, 0)])
        dist = rpt.directional_count_distribution(ch)
        self.assertEqual(dist[1], 1)   # (1,0)
        self.assertEqual(dist[2], 1)   # (2,0)
        self.assertEqual(dist[3], 1)   # (2,1)
        self.assertEqual(dist[0], 1)   # (0,0)

    def test_decisive_evidence_breakdown(self):
        # (1,0)->val dir1 ; (0,1)->con dir1 ; (2,0)->val dir2 ; (1,2)->con dir3
        ch = _chars([(1, 0), (0, 1), (2, 0), (1, 2)])
        b = rpt.decisive_evidence_breakdown(ch)
        self.assertEqual(b["decisive_total"], 4)
        self.assertEqual(b["single_ticker_decisive"], 2)
        self.assertAlmostEqual(b["single_ticker_share"], 0.5)
        self.assertEqual(b["by_bucket"]["1"]["validated"], 1)
        self.assertEqual(b["by_bucket"]["1"]["contradicted"], 1)
        self.assertEqual(b["by_bucket"]["2"]["validated"], 1)
        self.assertEqual(b["by_bucket"]["3plus"]["contradicted"], 1)

    def test_tie_decisive_counted(self):
        ch = _chars([(2, 2), (3, 0)])
        b = rpt.decisive_evidence_breakdown(ch)
        self.assertEqual(b["tie_decisive"], 1)  # the (2,2)

    def test_status_distribution(self):
        ch = _chars([(2, 0), (0, 2), (2, 2)])
        d = rpt.status_distribution(ch)
        self.assertEqual(d["validated"], 1)
        self.assertEqual(d["contradicted"], 2)  # (0,2) and (2,2) tie

    def test_observed_combinations(self):
        ch = _chars([(2, 0), (2, 0), (1, 2)])
        combos = rpt.observed_combinations(ch)
        self.assertEqual(combos[(2, 0)], 2)
        self.assertEqual(combos[(1, 2)], 1)


class TestStratification(unittest.TestCase):
    def test_status_by_family_groups(self):
        ch = [
            rpt.characterize_event(_event(eid=1, sup=2, con=0, family="rates"), now=NOW),
            rpt.characterize_event(_event(eid=2, sup=0, con=2, family="rates"), now=NOW),
            rpt.characterize_event(_event(eid=3, sup=2, con=0, family=None), now=NOW),
        ]
        by_fam = rpt.status_by_family(ch)
        self.assertEqual(by_fam["rates"]["validated"], 1)
        self.assertEqual(by_fam["rates"]["contradicted"], 1)
        # None/empty family collapses to a stable "none" key.
        self.assertEqual(by_fam["none"]["validated"], 1)

    def test_status_by_age_bucket_present(self):
        ch = _chars([(2, 0), (0, 2)])
        by_age = rpt.status_by_age_bucket(ch)
        # every char has an age bucket key; counts reconcile to N
        total = sum(sum(v.values()) for v in by_age.values())
        self.assertEqual(total, 2)


# ---------------------------------------------------------------------------
# Transition matrices and percentage reconciliation
# ---------------------------------------------------------------------------


class TestTransitions(unittest.TestCase):
    def test_min2_moves_only_single_ticker_labels(self):
        ch = _chars([(1, 0), (0, 1), (3, 0)])  # two single-ticker, one 3-ticker
        tm = rpt.transition_matrix(ch, rpt.candidate_min2)
        self.assertEqual(tm["changed"], 2)
        self.assertEqual(tm["transitions"].get(("validated", "unresolved"), 0), 1)
        self.assertEqual(tm["transitions"].get(("contradicted", "unresolved"), 0), 1)
        self.assertEqual(tm["total"], 3)

    def test_current_candidate_moves_nothing(self):
        ch = _chars([(1, 0), (2, 1), (0, 0)])
        tm = rpt.transition_matrix(ch, rpt.candidate_current)
        self.assertEqual(tm["changed"], 0)

    def test_transition_counts_sum_to_total(self):
        ch = _chars([(1, 0), (2, 2), (2, 3), (3, 0)])
        tm = rpt.transition_matrix(ch, rpt.candidate_min2_supermajority)
        self.assertEqual(sum(tm["transitions"].values()), tm["total"])
        self.assertEqual(tm["total"], 4)


class TestPercentages(unittest.TestCase):
    def test_percentages_reconcile(self):
        pct = rpt.percentages({"a": 1, "b": 1, "c": 2}, 4)
        self.assertAlmostEqual(pct["a"], 25.0)
        self.assertAlmostEqual(pct["c"], 50.0)
        self.assertAlmostEqual(sum(pct.values()), 100.0, places=6)

    def test_zero_denominator_safe(self):
        pct = rpt.percentages({}, 0)
        self.assertEqual(pct, {})


# ---------------------------------------------------------------------------
# Ground-truth availability — honest handling of absent rating
# ---------------------------------------------------------------------------


class TestGroundTruth(unittest.TestCase):
    def test_absent_rating_means_no_independent_target(self):
        ch = _chars([(2, 0), (0, 2), (3, 1)])  # no ratings
        gt = rpt.ground_truth_availability(ch)
        self.assertEqual(gt["rating_present_count"], 0)
        self.assertFalse(gt["independent_target_available"])

    def test_present_ratings_still_not_market_ground_truth(self):
        ch = [rpt.characterize_event(_event(eid=1, sup=2, con=0, rating="good"), now=NOW)]
        gt = rpt.ground_truth_availability(ch)
        self.assertEqual(gt["rating_present_count"], 1)
        # Manual rating is human judgement, same-archive — never an
        # independent market target for accuracy.
        self.assertFalse(gt["independent_target_available"])


# ---------------------------------------------------------------------------
# Recommendation — pinned only on clear-cut synthetic fixtures
# ---------------------------------------------------------------------------


class TestRecommendationClearCut(unittest.TestCase):
    def test_empty_archive_not_calibration_ready(self):
        rec = rpt.recommend({"accepted_n": 0, "decisive_total": 0,
                             "single_ticker_share": 0.0})
        self.assertEqual(rec["verdict"], "UNRESOLVED — ARCHIVE NOT CALIBRATION-READY")

    def test_no_decisive_labels_not_calibration_ready(self):
        rec = rpt.recommend({"accepted_n": 10, "decisive_total": 0,
                             "single_ticker_share": 0.0})
        self.assertEqual(rec["verdict"], "UNRESOLVED — ARCHIVE NOT CALIBRATION-READY")

    def test_majority_single_ticker_tightens(self):
        rec = rpt.recommend({"accepted_n": 20, "decisive_total": 10,
                             "single_ticker_share": 0.8})
        self.assertEqual(rec["verdict"], "TIGHTEN_EVIDENCE_FLOOR")

    def test_adequate_floor_keeps(self):
        rec = rpt.recommend({"accepted_n": 86, "decisive_total": 65,
                             "single_ticker_share": 0.046})
        self.assertEqual(rec["verdict"], "KEEP_CURRENT_RULE")

    def test_verdict_is_one_of_four(self):
        for share in (0.0, 0.046, 0.5, 0.8, 1.0):
            rec = rpt.recommend({"accepted_n": 86, "decisive_total": 65,
                                 "single_ticker_share": share})
            self.assertIn(rec["verdict"], (
                "KEEP_CURRENT_RULE", "TIGHTEN_EVIDENCE_FLOOR",
                "WITHHOLD_DECISIVE_LABELS_PENDING_BETTER_DATA",
                "UNRESOLVED — ARCHIVE NOT CALIBRATION-READY"))


# ---------------------------------------------------------------------------
# DB integration — read-only, bytes unchanged, deterministic markdown
# ---------------------------------------------------------------------------


class TestDbIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="valcalib_")
        cls.db_path = os.path.join(cls.tmp, "events.db")
        os.environ["EVENTS_DB_FILE"] = cls.db_path
        import db as _db
        _db.DB_FILE = cls.db_path
        _db.init_db()
        conn = sqlite3.connect(cls.db_path)
        import json as _json
        def ins(eid, stage, tickers, family="none", rating=None,
                event_date="2026-01-01"):
            conn.execute(
                "INSERT INTO events (id, headline, timestamp, event_date, stage, "
                "persistence, mechanism_family, mechanism_summary, what_changed, "
                "market_tickers, rating) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (eid, f"headline {eid}", event_date + "T12:00:00", event_date,
                 stage, "one-off", family, "thesis", "changed",
                 _json.dumps(tickers), rating))
        # accepted, decisive on 2 tickers
        ins(1, "realized",
            [{"symbol": "A", "direction_tag": "supports_thesis"},
             {"symbol": "B", "direction_tag": "supports_thesis"}])
        # accepted, single-ticker decisive
        ins(2, "anticipation",
            [{"symbol": "A", "direction_tag": "contradicts_thesis"}])
        # accepted, no directional evidence
        ins(3, "realized", [{"symbol": "A", "role": "beneficiary"}])
        # non-thesis stage — excluded
        ins(4, "curated_observation",
            [{"symbol": "A", "direction_tag": "supports_thesis"}])
        # synthetic-seed — excluded (flagged in event_hygiene)
        ins(5, "realized",
            [{"symbol": "A", "direction_tag": "supports_thesis"}])
        conn.execute(
            "INSERT INTO event_hygiene (event_id, override_class, override_reason, "
            "created_at) VALUES (?,?,?,?)",
            (5, "synthetic_seed", "test", "2026-01-01T00:00:00"))
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _sha(self):
        return hashlib.sha256(Path(self.db_path).read_bytes()).hexdigest()

    def test_report_reproduces_gate_and_is_read_only(self):
        before = self._sha()
        report = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        after = self._sha()
        self.assertEqual(before, after, "DB bytes must not change")
        f = report["funnel"]
        self.assertEqual(f["archive_rows"], 5)
        self.assertEqual(f["excluded_non_thesis_stage"], 1)  # id 4
        self.assertEqual(f["excluded_synthetic_seed"], 1)    # id 5
        self.assertEqual(f["accepted"], 3)                    # ids 1,2,3

    def test_accepted_and_raw_lenses_are_separate(self):
        report = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        self.assertIn("accepted", report)
        self.assertIn("raw", report)
        # Denominators are distinct sets, never summed into one number.
        self.assertNotEqual(report["accepted"]["n"], report["raw"]["n"])

    def test_percentages_reconcile_on_real_shaped_data(self):
        report = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        pct = report["accepted"]["status_pct"]
        self.assertAlmostEqual(sum(pct.values()), 100.0, places=6)

    def test_markdown_is_deterministic(self):
        r1 = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        r2 = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        self.assertEqual(rpt.render_markdown(r1), rpt.render_markdown(r2))

    def test_markdown_ends_with_recommendation_token(self):
        report = rpt.build_report(db_path=self.db_path, as_of="2026-07-11")
        md = rpt.render_markdown(report)
        self.assertTrue(any(tok in md for tok in (
            "KEEP_CURRENT_RULE", "TIGHTEN_EVIDENCE_FLOOR",
            "WITHHOLD_DECISIVE_LABELS_PENDING_BETTER_DATA",
            "UNRESOLVED — ARCHIVE NOT CALIBRATION-READY")))


# ---------------------------------------------------------------------------
# No provider / network import
# ---------------------------------------------------------------------------


class TestNoProviderImport(unittest.TestCase):
    def test_module_source_has_no_network_or_provider_imports(self):
        src = Path(rpt.__file__).read_text(encoding="utf-8")
        forbidden = ("import requests", "urllib.request", "httpx",
                     "import socket", "news_fetch", "market_data",
                     "provider_fetch", "yfinance", "stooq")
        for tok in forbidden:
            self.assertNotIn(tok, src, f"forbidden import token: {tok}")


if __name__ == "__main__":
    unittest.main()
