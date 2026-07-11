"""Tests for scripts/transmission_case_selection_stress_report.py (read-only).

Q1 stress-tests the N1 transmission-case SELECTION under alternative
deterministic policies. It does NOT change the N1 selector and does NOT replace
the six primary cases - it only measures how sensitive the chosen set is.

Discipline:
  * current_n1 reuses N1's real ``select_cases`` (imported read-only).
  * Policies are deterministic and never use returns, sector availability, or
    favorable outcomes.
  * The anchor-score doc/impl mismatch is DETECTED and DISCLOSED, never fixed.
  * No DB writes; no significance / performance-ranking / proof framing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import unittest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from scripts import transmission_case_selection_stress_report as Q  # noqa: E402
from scripts import transmission_case_walkthrough_report as W  # noqa: E402

# T1: live-archive checks are explicit opt-in via the shared gate;
# root events.db presence must not change the default universe.
from tests._local_data_gate import (  # noqa: E402
    local_data_skip_reason,
    local_events_db_or_none,
)
_LIVE_DB = str(local_events_db_or_none() or "")
_N1_IDS = [1, 61, 210, 46, 66, 211]


# ---------------------------------------------------------------------------
# Synthetic enriched-pool helper
# ---------------------------------------------------------------------------


def _pr(eid, *, bucket="support", fam="tariff", overlay=None, info=4,
        has_es=True, anchor="clean_discrete_anchor"):
    if overlay is None:
        overlay = [] if fam == "unclassified" else [fam]
    return {
        "event_id": eid,
        "headline": f"headline {eid}",
        "event_date": "2025-06-01",
        "outcome_bucket": bucket,
        "family_primary": fam,
        "family_overlay": overlay,
        "info_score": info,
        "has_es": has_es,
        "anchor_quality": anchor,
        "is_data_limited": bucket == "data_limited",
        "is_multi_or_unclassified": len(overlay) != 1,
    }


def _diverse_pool():
    """A pool with multiple outcomes, families, anchors, and ties."""
    return [
        _pr(1, bucket="support", fam="tariff", info=5,
            anchor="partial_anticipation"),
        _pr(61, bucket="contradiction", fam="geopolitical_conflict_context",
            info=5, anchor="partial_anticipation"),
        _pr(210, bucket="unresolved", fam="supply_shock", info=5,
            anchor="clean_discrete_anchor"),
        _pr(46, bucket="support", fam="monetary_policy_or_rates", info=4,
            anchor="scheduled_or_weak_anchor"),
        _pr(66, bucket="support", fam="ceasefire_deescalation", info=4,
            anchor="scheduled_or_weak_anchor"),
        _pr(211, bucket="unresolved", fam="sanction", info=4,
            anchor="scheduled_or_weak_anchor"),
        # data-limited / no-event-study row the current set omits
        _pr(153, bucket="data_limited", fam="sanction", info=2, has_es=False,
            anchor="manual_review_needed"),
        # multi-match row (overlay length 2)
        _pr(34, bucket="support", fam="supply_shock",
            overlay=["supply_shock", "geopolitical_conflict_context"],
            info=4, anchor="clean_discrete_anchor"),
        # truly clean unresolved
        _pr(212, bucket="unresolved", fam="tariff", info=4,
            anchor="clean_discrete_anchor"),
    ]


def _denoms():
    return {"archive_rows": 180, "accepted_coverage_denominator": 94,
            "accepted_track_record_denominator": 86, "staged_candidate_count": 13}


def _file_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


# ---------------------------------------------------------------------------
# Policy logic (pure)
# ---------------------------------------------------------------------------


class TestPolicies(unittest.TestCase):
    def test_current_policy_matches_n1_select_cases(self):
        pool = _diverse_pool()
        got = Q.apply_policy(pool, "current_n1", 6)
        want = [c["event_id"] for c in W.select_cases(pool, 6)]
        self.assertEqual(got, want)

    def test_policies_are_deterministic(self):
        pool = _diverse_pool()
        for name in Q.POLICY_NAMES:
            self.assertEqual(Q.apply_policy(pool, name, 6),
                             Q.apply_policy(pool, name, 6), name)

    def test_policies_select_pool_ids_only(self):
        pool = _diverse_pool()
        ids = {r["event_id"] for r in pool}
        for name in Q.POLICY_NAMES:
            for eid in Q.apply_policy(pool, name, 6):
                self.assertIn(eid, ids, name)

    def test_family_first_maximizes_distinct_families(self):
        pool = _diverse_pool()
        sel = Q.apply_policy(pool, "family_first", 6)
        fams = {next(r["family_primary"] for r in pool if r["event_id"] == e)
                for e in sel}
        # family_first should reach more distinct families than a fixed family
        self.assertGreaterEqual(len(fams), 5)

    def test_outcome_first_forces_three_buckets(self):
        pool = _diverse_pool()
        sel = Q.apply_policy(pool, "outcome_first", 6)
        buckets = {next(r["outcome_bucket"] for r in pool if r["event_id"] == e)
                   for e in sel}
        self.assertIn("support", buckets)
        self.assertIn("contradiction", buckets)
        self.assertTrue({"unresolved", "data_limited"} & buckets)

    def test_anchor_quality_first_prefers_clean_anchors(self):
        pool = _diverse_pool()
        sel = Q.apply_policy(pool, "anchor_quality_first", 3)
        anchors = [next(r["anchor_quality"] for r in pool if r["event_id"] == e)
                   for e in sel]
        # the truly-clean rows (210, 34, 212) should be favored early
        self.assertIn("clean_discrete_anchor", anchors)

    def test_missingness_aware_forces_a_data_limited_or_missing_case(self):
        pool = _diverse_pool()
        sel = Q.apply_policy(pool, "missingness_aware", 6)
        has_missing = any(
            (not next(r["has_es"] for r in pool if r["event_id"] == e))
            or next(r["is_data_limited"] for r in pool if r["event_id"] == e)
            for e in sel)
        self.assertTrue(has_missing)

    def test_reverse_id_tiebreak_differs_on_ties(self):
        # two support rows tie at info=5; forward picks lower id, reverse higher
        pool = [_pr(10, bucket="support", info=5),
                _pr(20, bucket="support", info=5),
                _pr(30, bucket="contradiction", info=5),
                _pr(40, bucket="unresolved", info=5)]
        fwd = Q.apply_policy(pool, "current_n1", 1)
        rev = Q.apply_policy(pool, "reverse_id_tiebreak", 1)
        self.assertEqual(fwd, [10])
        self.assertEqual(rev, [20])


# ---------------------------------------------------------------------------
# Report assembly (injected pool / current ids)
# ---------------------------------------------------------------------------


class TestReportAssembly(unittest.TestCase):
    def _rep(self, **kw):
        pool = _diverse_pool()
        current = Q.apply_policy(pool, "current_n1", 6)
        return Q.build_report(pool=pool, current_ids=current,
                              denominators=_denoms(), **kw)

    def test_current_n1_block_present(self):
        rep = self._rep()
        cn = rep["current_n1"]
        self.assertIn("selected_case_ids", cn)
        for key in ("outcome_composition", "family_composition",
                    "anchor_quality_composition",
                    "event_study_availability_composition"):
            self.assertIn(key, cn)

    def test_policy_comparisons_cover_required_policies(self):
        rep = self._rep()
        names = {p["policy_name"] for p in rep["policy_comparisons"]}
        for required in ("family_first", "outcome_first",
                         "anchor_quality_first", "missingness_aware",
                         "reverse_id_tiebreak"):
            self.assertIn(required, names)

    def test_each_policy_reports_required_fields(self):
        rep = self._rep()
        for p in rep["policy_comparisons"]:
            for key in ("policy_name", "selection_rule", "selected_case_ids",
                        "overlap_with_current_count", "retained_current_ids",
                        "dropped_current_ids", "outcome_composition",
                        "family_composition", "anchor_quality_composition",
                        "event_study_availability_composition",
                        "data_limited_count",
                        "multi_match_or_unclassified_count",
                        "reviewer_risk_note"):
                self.assertIn(key, p, key)

    def test_overlap_counts_are_consistent(self):
        rep = self._rep()
        current = set(rep["current_n1"]["selected_case_ids"])
        for p in rep["policy_comparisons"]:
            sel = set(p["selected_case_ids"])
            self.assertEqual(p["overlap_with_current_count"],
                             len(sel & current))
            self.assertEqual(set(p["retained_current_ids"]), sel & current)
            self.assertEqual(set(p["dropped_current_ids"]), current - sel)

    def test_scope_flags(self):
        sc = self._rep()["scope"]
        self.assertIs(sc["read_only"], True)
        self.assertIs(sc["n1_selector_changed"], False)
        self.assertIs(sc["primary_walkthrough_cases_unchanged"], True)
        self.assertIs(sc["no_q2_appendix"], True)
        self.assertIs(sc["no_return_based_selection"], True)
        self.assertIs(sc["no_sector_based_selection"], True)

    def test_pool_has_no_return_or_sector_fields(self):
        # selection inputs must not carry returns or sector data.
        rep = self._rep()
        blob = json.dumps(rep).lower()
        for forbidden in ("abnormal_return", "sector_raw", "_sar", "_car",
                          "sector_backdrop"):
            self.assertNotIn(forbidden, blob)


# ---------------------------------------------------------------------------
# Anchor-score mismatch detection (disclose, never fix)
# ---------------------------------------------------------------------------


class TestAnchorMismatch(unittest.TestCase):
    def _rep(self, pool):
        current = Q.apply_policy(pool, "current_n1", 6)
        return Q.build_report(pool=pool, current_ids=current,
                              denominators=_denoms())

    def test_mismatch_detected_when_non_clean_anchor_rewarded(self):
        # pool contains partial_anticipation / scheduled_or_weak rows, which
        # are non-clean yet not in _CAVEATED_ANCHORS -> they get the +1 bonus.
        rep = self._rep(_diverse_pool())
        chk = rep["anchor_score_policy_check"]
        self.assertIs(chk["mismatch_detected"], True)
        self.assertTrue(chk["documented_policy"])
        self.assertTrue(chk["observed_implementation_behavior"])
        self.assertTrue(chk["recommendation"])

    def test_no_mismatch_when_only_clean_and_caveated_present(self):
        pool = [_pr(1, anchor="clean_discrete_anchor"),
                _pr(2, bucket="contradiction",
                    anchor="manual_review_needed"),
                _pr(3, bucket="unresolved", anchor="duplicate_or_deferred")]
        chk = self._rep(pool)["anchor_score_policy_check"]
        self.assertIs(chk["mismatch_detected"], False)

    def test_mismatch_is_disclosed_not_fixed(self):
        # the report must not alter info_score behaviour - recommendation only.
        rec = self._rep(_diverse_pool())["anchor_score_policy_check"][
            "recommendation"].lower()
        self.assertTrue("disclos" in rec or "scope" in rec or "future" in rec)
        # info_score still rewards a partial_anticipation row (+1), unchanged.
        row = _pr(99, anchor="partial_anticipation")
        edq = {"event_date_quality": "partial_anticipation"}
        self.assertGreaterEqual(W.info_score(row, edq, True), 3)


# ---------------------------------------------------------------------------
# Discipline / non-claims / banned framing
# ---------------------------------------------------------------------------


class TestDiscipline(unittest.TestCase):
    def _rep(self):
        pool = _diverse_pool()
        current = Q.apply_policy(pool, "current_n1", 6)
        return Q.build_report(pool=pool, current_ids=current,
                              denominators=_denoms())

    def test_non_claims_cover_required_ground(self):
        blob = " ".join(self._rep()["non_claims"]).lower()
        for needle in ("does not replace", "illustrative", "significance",
                       "family-level", "performance ranking", "recommendation",
                       "mutation", "denominator"):
            self.assertIn(needle, blob)

    def test_stress_summary_present(self):
        ss = self._rep()["stress_summary"]
        for key in ("stable_elements", "sensitive_elements",
                    "cherry_pick_risk_assessment", "whether_q2_is_needed",
                    "recommendation"):
            self.assertIn(key, ss)

    def test_banned_framing_absent_from_source_and_output(self):
        rep = self._rep()
        text = Q._render_text(rep) + " " + json.dumps(rep)
        with open(os.path.join(_REPO, "scripts",
                               "transmission_case_selection_stress_report.py"),
                  encoding="utf-8") as fh:
            src = fh.read()
        blob = (text + " " + src).lower()
        for pattern in (r"trading signal", r"buy/sell recommendation",
                        r"\bforecast\b", r"\bproves\b", r"\bproven\b",
                        r"confirmed mechanism", r"validated.as.success",
                        r"actionable trade", r"\balpha\b", r"\bsignal\b"):
            self.assertIsNone(re.search(pattern, blob),
                              f"banned framing {pattern!r} present")


# ---------------------------------------------------------------------------
# Rendering / CLI
# ---------------------------------------------------------------------------


class TestRendering(unittest.TestCase):
    def _rep(self):
        pool = _diverse_pool()
        current = Q.apply_policy(pool, "current_n1", 6)
        return Q.build_report(pool=pool, current_ids=current,
                              denominators=_denoms())

    def test_text_render_cp1252_with_required_sections(self):
        text = Q._render_text(self._rep())
        text.encode("cp1252")
        low = text.lower()
        for section in ("denominator", "current n1", "policy", "anchor",
                        "stress", "non-claims"):
            self.assertIn(section, low)

    def test_main_json_smoke(self):
        self.assertEqual(Q.main(["--db-path", _ABSENT, "--json"]), 0)

    def test_main_text_smoke(self):
        self.assertEqual(Q.main(["--db-path", _ABSENT]), 0)


# ---------------------------------------------------------------------------
# Live path (events.db) - exact reproduction + no write
# ---------------------------------------------------------------------------


@unittest.skipUnless(bool(_LIVE_DB), local_data_skip_reason())
class TestLive(unittest.TestCase):
    def test_current_n1_ids_reproduced_exactly(self):
        rep = Q.build_report(db_path=_LIVE_DB)
        self.assertEqual(rep["current_n1"]["selected_case_ids"], _N1_IDS)

    def test_build_never_writes_database(self):
        before = _file_sha256(_LIVE_DB)
        Q.build_report(db_path=_LIVE_DB)
        self.assertEqual(_file_sha256(_LIVE_DB), before)

    def test_denominators_live(self):
        d = Q.build_report(db_path=_LIVE_DB)["denominators"]
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["accepted_coverage_denominator"], 94)
        self.assertEqual(d["staged_candidate_count"], 13)

    def test_anchor_mismatch_detected_live(self):
        rep = Q.build_report(db_path=_LIVE_DB)
        self.assertIs(
            rep["anchor_score_policy_check"]["mismatch_detected"], True)


import tempfile  # noqa: E402
import uuid  # noqa: E402
_ABSENT = os.path.join(tempfile.gettempdir(), f"tcss_absent_{uuid.uuid4().hex}.db")


if __name__ == "__main__":
    unittest.main()
