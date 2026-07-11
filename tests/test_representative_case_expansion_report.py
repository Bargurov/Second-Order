"""Tests for ``scripts/representative_case_expansion_report.py`` (F1).

Read-only deterministic expansion of the representative case library across
mechanism families. The N1 baseline cases (1, 61, 210, 46, 66, 211) are carried
as already-covered anchors; the report proposes additional cases per family
under a documented deterministic policy. Pins:

* per family the new-pick order is support -> contradiction -> unresolved, then
  fill by (event-study-available, lowest event_id);
* a thin unresolved-only family keeps its unresolved cases, never dropped;
* N1 ids are carried and labeled already-covered; new picks exclude them;
* each family's library (anchor + new) is capped at 3;
* every family with rows is represented (anchor guarantees span);
* the union of anchors + new covers support / contradiction / unresolved;
* the global trim respects the target, never removes an anchor, and protects
  the last entry of an anchorless family;
* selection is deterministic;
* the report carries no proof / significance / forecast / recommendation /
  trading framing;
* the report mutates neither events.db nor price_cache.db;
* a live run preserves the canonical denominators (180 / 94 / 86 / 78-of-94 /
  13) and the per-family coverage table equals the E1 inventory.

The pure selection core is exercised with synthetic family pools (no DB); the
DB wiring + canonical denominators are exercised against the live archive.
"""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.representative_case_expansion_report import (  # noqa: E402
    GLOBAL_MAX,
    GLOBAL_TARGET,
    N1_BASELINE_IDS,
    PER_FAMILY_CAP,
    THIN_FLOOR,
    build_report,
    select_expansion,
    select_family_new,
)
from scripts.mechanism_family_evidence_inventory import build_inventory  # noqa: E402

# T1: live-archive checks are explicit opt-in via the shared gate;
# root events.db presence must not change the default universe.
from tests._local_data_gate import (  # noqa: E402
    local_data_skip_reason,
    local_events_db_or_none,
)
LIVE_DB = local_events_db_or_none()


def _row(event_id, outcome, es, *, headline=None, date="2026-04-01", symbols=None):
    return {
        "event_id": event_id,
        "outcome": outcome,
        "event_study_available": es,
        "headline": headline or f"headline {event_id}",
        "event_date": date,
        "symbols": symbols or [],
    }


# ---------------------------------------------------------------------------
# Pure: per-family new-pick order
# ---------------------------------------------------------------------------

class TestSelectFamilyNew(unittest.TestCase):
    def test_picks_one_of_each_outcome_in_order(self):
        cands = [_row(5, "validated", True), _row(6, "contradicted", True),
                 _row(7, "unresolved", True), _row(8, "validated", True)]
        picks = select_family_new(cands, 3)
        self.assertEqual([p["event_id"] for p in picks], [5, 6, 7])

    def test_prefers_event_study_then_low_id(self):
        # two supports: one ES-available (higher id) beats non-ES (lower id)
        cands = [_row(3, "validated", False), _row(9, "validated", True)]
        picks = select_family_new(cands, 1)
        self.assertEqual([p["event_id"] for p in picks], [9])

    def test_thin_unresolved_only_keeps_unresolved(self):
        cands = [_row(40, "unresolved", False), _row(41, "unresolved", True)]
        picks = select_family_new(cands, 2)
        self.assertEqual(sorted(p["event_id"] for p in picks), [40, 41])
        self.assertTrue(all(p["outcome"] == "unresolved" for p in picks))


# ---------------------------------------------------------------------------
# Pure: expansion selection
# ---------------------------------------------------------------------------

def _fixture_pools():
    return {
        "supply_shock": [
            _row(210, "unresolved", True), _row(38, "validated", True),
            _row(40, "validated", False), _row(29, "contradicted", True),
            _row(39, "contradicted", False), _row(215, "unresolved", False),
        ],
        "sanction": [  # thin (n=3), unresolved only, anchor 211
            _row(211, "unresolved", True), _row(153, "unresolved", False),
            _row(154, "unresolved", True),
        ],
        "tariff": [  # anchor 1, no contradiction
            _row(1, "validated", True), _row(31, "validated", True),
            _row(212, "unresolved", True),
        ],
    }


def _select(pools=None, *, n1=(210, 211, 1), order=("supply_shock", "sanction", "tariff"),
            target=GLOBAL_TARGET):
    return select_expansion(
        pools if pools is not None else _fixture_pools(),
        n1_ids=n1, family_order=order,
        per_family_cap=PER_FAMILY_CAP, thin_floor=THIN_FLOOR, global_target=target,
    )


class TestSelectExpansion(unittest.TestCase):
    def test_anchors_carried_and_labeled_already_covered(self):
        out = _select()
        anchors = [s for s in out["selected"] if s["role"] == "already_covered_anchor"]
        self.assertEqual(sorted(s["event_id"] for s in anchors), [1, 210, 211])
        self.assertEqual(sorted(out["already_covered_ids"]), [1, 210, 211])

    def test_new_picks_exclude_anchors(self):
        out = _select()
        new_ids = {s["event_id"] for s in out["selected"] if s["role"] == "newly_proposed"}
        self.assertEqual(new_ids & {1, 210, 211}, set())

    def test_family_library_capped_at_three_including_anchor(self):
        out = _select()
        for fam, info in out["per_family"].items():
            self.assertLessEqual(info["library_count"], PER_FAMILY_CAP, fam)

    def test_all_families_represented(self):
        out = _select()
        fams = {s["family"] for s in out["selected"]}
        self.assertEqual(fams, {"supply_shock", "sanction", "tariff"})

    def test_outcome_diversity_union_covers_all_three(self):
        out = _select()
        outcomes = {s["outcome"] for s in out["selected"]}
        self.assertEqual(outcomes, {"validated", "contradicted", "unresolved"})
        self.assertTrue(out["summary"]["has_contradiction"])
        self.assertTrue(out["summary"]["has_unresolved"])

    def test_thin_family_unresolved_not_dropped(self):
        out = _select()
        sanction = [s for s in out["selected"] if s["family"] == "sanction"]
        # anchor 211 + at least one new unresolved survive
        new_sanction = [s for s in sanction if s["role"] == "newly_proposed"]
        self.assertGreaterEqual(len(new_sanction), 1)
        self.assertTrue(out["per_family"]["sanction"]["thin"])

    def test_global_trim_respects_target_and_keeps_anchors(self):
        # force a tight target so the natural selection must be trimmed
        out = _select(target=5)
        self.assertLessEqual(out["summary"]["total_proposed"], 5)
        kept = {s["event_id"] for s in out["selected"]}
        # all three anchors survive the trim
        self.assertTrue({1, 210, 211} <= kept)

    def test_trim_protects_last_entry_of_anchorless_family(self):
        pools = {
            "famA": [_row(10, "validated", True), _row(11, "unresolved", True)],
            "orphan": [_row(900, "validated", False)],  # no anchor, single entry
        }
        out = select_expansion(pools, n1_ids=set(), family_order=("famA", "orphan"),
                               per_family_cap=3, thin_floor=4, global_target=1)
        kept = {s["event_id"] for s in out["selected"]}
        # orphan's only entry must survive even under an aggressive target
        self.assertIn(900, kept)

    def test_deterministic(self):
        a = _select()
        b = _select()
        self.assertEqual([s["event_id"] for s in a["selected"]],
                         [s["event_id"] for s in b["selected"]])

    def test_trim_protects_material_support_over_duplicate(self):
        # F1A: under a tight target, a material family's support survives while a
        # duplicate same-outcome extra elsewhere is trimmed first. (The old
        # support-first trim would have removed the material support 150.)
        pools = {
            "big": [  # material (n=5): anchor unresolved + support + contradiction
                _row(100, "unresolved", True), _row(150, "validated", True),
                _row(151, "contradicted", True), _row(152, "validated", True),
                _row(153, "unresolved", True),
            ],
            "dup": [  # anchor unresolved + duplicate unresolved extras (thin)
                _row(200, "unresolved", True), _row(201, "unresolved", True),
                _row(202, "unresolved", True),
            ],
        }
        out = select_expansion(pools, n1_ids={100, 200},
                               family_order=("big", "dup"),
                               per_family_cap=3, thin_floor=4, global_target=5)
        big = {s["outcome"] for s in out["selected"] if s["family"] == "big"}
        self.assertIn("validated", big)  # material support survives the trim
        self.assertIn(150, {s["event_id"] for s in out["selected"]})
        self.assertLessEqual(out["summary"]["total_proposed"], 5)


# ---------------------------------------------------------------------------
# Pure: banned framing
# ---------------------------------------------------------------------------

class TestNoBannedFraming(unittest.TestCase):
    def test_selection_reasons_and_non_claims_clean(self):
        out = _select()
        blob = json.dumps(out).lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "trading signal", "forecast", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r}")
        import re
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r}")


# ---------------------------------------------------------------------------
# Live wiring
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB is not None, local_data_skip_reason())
class TestLiveExpansion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(db_path=str(LIVE_DB))

    def test_read_only_does_not_mutate_db(self):
        before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        build_report(db_path=str(LIVE_DB))
        after = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_canonical_denominators_preserved(self):
        d = self.report["denominators"]
        self.assertEqual(d["archive_rows"], 180)
        self.assertEqual(d["accepted_coverage_denominator"], 94)
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["event_study_available_count"], 78)
        self.assertEqual(d["event_study_coverage_denominator"], 94)
        self.assertEqual(d["staged_candidates"], 13)

    def test_n1_baseline_ids_present_and_labeled(self):
        ac = set(self.report["summary"]["already_covered_ids"])
        self.assertEqual(set(N1_BASELINE_IDS), ac)
        self.assertEqual(self.report["summary"]["count_already_in_n1"], len(N1_BASELINE_IDS))

    def test_total_within_global_cap(self):
        total = self.report["summary"]["total_proposed"]
        self.assertLessEqual(total, GLOBAL_MAX)
        self.assertLessEqual(total, GLOBAL_TARGET)
        self.assertGreaterEqual(total, 12)

    def test_family_coverage_equals_e1_inventory(self):
        e1 = {f["family"]: f for f in build_inventory(db_path=str(LIVE_DB))["families"]}
        for fam in self.report["family_coverage"]:
            ref = e1[fam["family"]]
            self.assertEqual(fam["accepted_n"], ref["accepted_thesis_count"], fam["family"])
            self.assertEqual(fam["support"], ref["outcomes"]["validated"], fam["family"])
            self.assertEqual(fam["contradiction"], ref["outcomes"]["contradicted"], fam["family"])
            self.assertEqual(fam["unresolved"], ref["outcomes"]["unresolved"], fam["family"])
            self.assertEqual(fam["event_study_available"], ref["event_study_available"]["available"], fam["family"])

    def test_six_families_represented(self):
        fams = {f["family"] for f in self.report["family_coverage"]}
        self.assertEqual(fams, {
            "supply_shock", "geopolitical_conflict_context", "tariff",
            "sanction", "ceasefire_deescalation", "monetary_policy_or_rates",
        })

    def test_contradiction_and_unresolved_present_in_library(self):
        outcomes = {s["outcome"] for s in self.report["selected"]}
        self.assertIn("contradicted", outcomes)
        self.assertIn("unresolved", outcomes)

    def test_event_date_quality_is_populated_not_silently_empty(self):
        # the event-date-quality caveat must actually wire to the edq report
        # (field is `event_date_quality`); event 1 is a known partial-anticipation
        dq = {c["event_id"]: c["event_date_quality"] for c in self.report["selected"]}
        self.assertTrue(any(v is not None for v in dq.values()),
                        "event_date_quality is silently None for every case")
        self.assertEqual(dq.get(1), "partial_anticipation")

    def test_largest_family_keeps_a_support_example(self):
        # F1A: supply_shock is the largest family (11 supports); the selected
        # library must show at least one support example, while keeping its
        # contradiction and unresolved representation.
        supply = {c["outcome"] for c in self.report["selected"]
                  if c["family"] == "supply_shock"}
        self.assertIn("validated", supply, "largest family has no support example")
        self.assertIn("contradicted", supply)
        self.assertIn("unresolved", supply)

    def test_staged_candidates_are_excluded(self):
        # every selected case must be in the accepted track-record set; staged /
        # observation / synthetic rows cannot leak into the library
        from scripts.mechanism_family_evidence_inventory import _enrich_records
        accepted = {r["event_id"] for r in _enrich_records(str(LIVE_DB))[0]}
        selected = {c["event_id"] for c in self.report["selected"]}
        self.assertTrue(selected <= accepted)
        self.assertEqual(self.report["denominators"]["staged_candidates"], 13)

    def test_multi_match_and_unclassified_counts_surfaced(self):
        self.assertEqual(self.report["summary"]["multi_match_count"], 16)
        self.assertEqual(self.report["summary"]["unclassified_count"], 18)

    def test_clean_anchor_carries_no_date_quality_caveat(self):
        # event 210 is a clean_discrete_anchor; a clean anchor is not a caveat
        case = next(c for c in self.report["selected"] if c["event_id"] == 210)
        self.assertEqual(case["event_date_quality"], "clean_discrete_anchor")
        self.assertFalse(any("event-date anchor" in cv for cv in case["caveats"]),
                         "clean anchor should not be flagged as a date-quality caveat")

    def test_live_no_banned_framing(self):
        import re
        blob = json.dumps(self.report).lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "trading signal", "forecast", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r}")
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r}")
        residue = blob.replace("not a recommendation", "")
        self.assertNotIn("recommendation", residue)


if __name__ == "__main__":
    unittest.main()
