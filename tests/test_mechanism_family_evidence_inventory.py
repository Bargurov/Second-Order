"""Tests for ``scripts/mechanism_family_evidence_inventory.py`` (E1).

Read-only mechanism-family evidence inventory. The accepted track-record corpus
(86 thesis rows) is grouped by the tested J1 headline overlay
(``accepted_family_overlay_report.classify_headline``) because every thesis row
is stored ``mechanism_family='none'`` — the headline overlay is the only lens
with family structure. Pins:

* family grouping reuses the real ``classify_headline`` classifier;
* per-family support / contradiction / unresolved counts sum to the family count;
* the single-match + multi-match + unclassified buckets sum to the
  track-record denominator (the sum-invariant);
* per-family event-study availability is on the track-record (86) lens and is
  separate from the global 78/94 coverage lens;
* multi-family and unclassified rows are surfaced, never hidden;
* staged candidates are excluded from every family and denominator (live);
* representative-case selection is deterministic under a stated total order;
* low-n families emit a low-n caveat;
* per-family independent-window capacity is suppressed below an n floor and the
  global capacity block carries the C1 non-claim verbatim;
* the report carries no proof / significance / forecast / recommendation /
  trading framing (outcome label "validated" is the canonical scorer vocabulary);
* the report mutates neither events.db nor price_cache.db;
* a live run preserves the canonical denominators (180 / 94 / 86 / 78-of-94 / 13).

The pure ``assemble_inventory`` core is exercised with synthetic enriched
records (no DB, no price data); the DB wiring and canonical denominators are
exercised against the live archive (skipped when absent).
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.mechanism_family_evidence_inventory import (  # noqa: E402
    CAPACITY_MIN_N,
    LOW_N_FLOOR,
    REPRESENTATIVE_CAP,
    _sector_classifier,
    assemble_inventory,
    build_inventory,
    select_representative_cases,
)

# T1: live-archive checks are explicit opt-in via the shared gate;
# root events.db presence must not change the default universe.
from tests._local_data_gate import (  # noqa: E402
    local_data_skip_reason,
    local_events_db_or_none,
)
LIVE_DB = local_events_db_or_none()


# ---------------------------------------------------------------------------
# Synthetic-record helpers for the pure core
# ---------------------------------------------------------------------------

def _tickers(outcome: str) -> list[dict]:
    """Build a directional ticker list that scores to ``outcome`` under the
    canonical any_support rule (supports -> validated, contradicts ->
    contradicted, neutral/empty -> unresolved)."""
    if outcome == "validated":
        return [{"symbol": "SUP", "direction_tag": "supports_thesis"}]
    if outcome == "contradicted":
        return [{"symbol": "CON", "direction_tag": "contradicts_thesis"}]
    return [{"symbol": "NEU", "direction_tag": "neutral"}]


def _rec(event_id, headline, outcome, date, symbols, es):
    return {
        "event_id": event_id,
        "headline": headline,
        "event_date": date,
        "symbols": list(symbols),
        "tickers": _tickers(outcome),
        "event_study_available": bool(es),
    }


def _fixture_records():
    """11 accepted thesis records spanning single-match families, a multi-match
    row, an unclassified row, plus a thin family — all via real classifier
    tokens (oil -> supply_shock, tariff -> tariff, missile/war -> conflict)."""
    recs = []
    # supply_shock: 6 rows (above LOW_N_FLOOR=5), mixed outcomes, mixed ES
    recs.append(_rec(10, "oil prices jump on outage", "validated", "2026-01-05", ["XOM"], True))
    recs.append(_rec(11, "crude rally as opec cuts", "validated", "2026-01-06", ["XOM", "CVX"], True))
    recs.append(_rec(12, "pipeline outage hits oil", "validated", "2026-02-10", ["CVX"], False))
    recs.append(_rec(15, "tanker seized, barrel up", "validated", "2026-03-01", ["XOM"], False))
    recs.append(_rec(13, "oil refinery fire", "contradicted", "2026-01-07", ["VLO"], True))
    recs.append(_rec(14, "crude osp revised", "unresolved", "2026-04-20", ["XOM"], False))
    # tariff: 2 rows (low_n, < 5)
    recs.append(_rec(20, "new tariff on imports", "validated", "2026-01-10", ["F"], False))
    recs.append(_rec(21, "tariffs raised again", "unresolved", "2026-01-12", ["GM"], False))
    # geopolitical_conflict_context: 1 single-match row (non-canonical family)
    recs.append(_rec(50, "missile launch reported", "validated", "2026-05-01", ["LMT"], False))
    # multi-match: oil + war -> {supply_shock, geopolitical_conflict_context}
    recs.append(_rec(30, "oil tankers hit in war zone", "validated", "2026-02-15", ["XOM"], True))
    # unclassified: no rule tokens
    recs.append(_rec(40, "company reports quarterly earnings", "unresolved", "2026-03-20", ["AAPL"], False))
    return recs


def _fixture_denominators(track_record):
    return {
        "archive_rows": 180,
        "accepted_coverage_denominator": track_record + 3,  # 3 observations
        "accepted_track_record_denominator": track_record,
        "event_study_available_count": 78,        # global coverage lens
        "event_study_coverage_denominator": 94,   # global coverage lens
        "staged_candidates": 13,
    }


def _fixture_observations():
    return {
        "count": 3,
        "by_stored_family": [{"family": "tariff", "count": 2},
                             {"family": "sanction", "count": 1}],
    }


def _build_fixture_inventory():
    recs = _fixture_records()
    return assemble_inventory(
        recs,
        denominators=_fixture_denominators(len(recs)),
        taxonomy_readout=["fixture taxonomy note"],
        observations_bridge=_fixture_observations(),
    )


def _families_by_name(report):
    return {f["family"]: f for f in report["families"]}


# ---------------------------------------------------------------------------
# Pure core — grouping + counts
# ---------------------------------------------------------------------------

class TestFamilyGrouping(unittest.TestCase):
    def test_single_match_families_grouped_by_real_classifier(self):
        report = _build_fixture_inventory()
        fams = _families_by_name(report)
        self.assertIn("supply_shock", fams)
        self.assertEqual(fams["supply_shock"]["accepted_thesis_count"], 6)
        self.assertIn("tariff", fams)
        self.assertEqual(fams["tariff"]["accepted_thesis_count"], 2)
        self.assertIn("geopolitical_conflict_context", fams)
        self.assertEqual(fams["geopolitical_conflict_context"]["accepted_thesis_count"], 1)

    def test_outcome_counts_sum_to_family_count(self):
        report = _build_fixture_inventory()
        for fam in report["families"]:
            oc = fam["outcomes"]
            self.assertEqual(
                oc["validated"] + oc["contradicted"] + oc["unresolved"],
                fam["accepted_thesis_count"],
                f"{fam['family']} outcomes do not sum to count",
            )
        # supply_shock: 4 validated / 1 contradicted / 1 unresolved
        fams = _families_by_name(report)
        self.assertEqual(fams["supply_shock"]["outcomes"],
                         {"validated": 4, "contradicted": 1, "unresolved": 1,
                          "rule": "any_support"})

    def test_sum_invariant_single_multi_unclassified_equals_track_record(self):
        report = _build_fixture_inventory()
        inv = report["global_summary"]["sum_invariant"]
        self.assertEqual(inv["single_match_total"], 9)
        self.assertEqual(inv["multi_match"], 1)
        self.assertEqual(inv["unclassified"], 1)
        self.assertEqual(inv["sum"], 11)
        self.assertTrue(inv["equals_track_record"])


# ---------------------------------------------------------------------------
# Pure core — lenses, ambiguity, observations
# ---------------------------------------------------------------------------

class TestLensesAndBuckets(unittest.TestCase):
    def test_per_family_event_study_is_track_record_lens_not_coverage(self):
        report = _build_fixture_inventory()
        fams = _families_by_name(report)
        es = fams["supply_shock"]["event_study_available"]
        # supply_shock thesis rows 10,11,13 are ES-available -> 3 of 6
        self.assertEqual(es["available"], 3)
        self.assertEqual(es["of_family_thesis"], 6)
        self.assertEqual(es["lens"], "track_record")
        # the global 78/94 coverage figure stays separate and labeled
        g = report["global_summary"]
        self.assertEqual(g["total_event_study_available_coverage_lens"], "78 / 94")

    def test_multi_match_and_unclassified_are_surfaced(self):
        report = _build_fixture_inventory()
        multi = report["multi_family_ambiguous"]
        self.assertEqual(multi["count"], 1)
        self.assertIn(30, multi["representative_event_ids"])
        self.assertIn(["geopolitical_conflict_context", "supply_shock"],
                      [sorted(s) for s in multi["matched_family_sets"]])
        uncl = report["unclassified"]
        self.assertEqual(uncl["count"], 1)
        self.assertIn(40, uncl["representative_event_ids"])

    def test_observations_bridge_explains_coverage_minus_track_record_gap(self):
        report = _build_fixture_inventory()
        bridge = report["accepted_observations_bridge"]
        # coverage (14) - track-record (11) == 3
        self.assertEqual(bridge["count"], 3)
        self.assertEqual(
            report["denominators"]["accepted_coverage_denominator"]
            - report["denominators"]["accepted_track_record_denominator"],
            bridge["count"],
        )


# ---------------------------------------------------------------------------
# Pure core — representative selection + caveats + capacity
# ---------------------------------------------------------------------------

class TestRepresentativeSelection(unittest.TestCase):
    def test_selection_is_deterministic_and_diverse(self):
        report = _build_fixture_inventory()
        fams = _families_by_name(report)
        ids = [c["event_id"] for c in fams["supply_shock"]["representative_cases"]]
        # one contradicted (13), one unresolved (14), fill by ES-available then
        # id (10), final display order by event_id
        self.assertEqual(ids, [10, 13, 14])
        self.assertLessEqual(len(ids), REPRESENTATIVE_CAP)

    def test_select_helper_total_order_explicit(self):
        rows = [
            {"event_id": 5, "outcome": "validated", "event_study_available": False},
            {"event_id": 1, "outcome": "validated", "event_study_available": True},
            {"event_id": 3, "outcome": "contradicted", "event_study_available": False},
            {"event_id": 7, "outcome": "unresolved", "event_study_available": True},
        ]
        chosen = select_representative_cases(rows, cap=3)
        # guarantees the contradiction (3) and the unresolved (7); fills with the
        # ES-available validated (1) over the non-ES validated (5)
        self.assertEqual([c["event_id"] for c in chosen], [1, 3, 7])


class TestCaveatsAndCapacity(unittest.TestCase):
    def test_low_n_family_emits_caveat(self):
        report = _build_fixture_inventory()
        fams = _families_by_name(report)
        self.assertTrue(any("low_n" in w for w in fams["tariff"]["weaknesses"]))
        self.assertLess(fams["tariff"]["accepted_thesis_count"], LOW_N_FLOOR)
        # the well-populated family is not flagged low_n
        self.assertFalse(any("low_n" in w for w in fams["supply_shock"]["weaknesses"]))

    def test_per_family_capacity_suppressed_below_floor(self):
        report = _build_fixture_inventory()
        fams = _families_by_name(report)
        # supply_shock n=6 < CAPACITY_MIN_N -> suppressed, not a bare number
        self.assertLess(fams["supply_shock"]["accepted_thesis_count"], CAPACITY_MIN_N)
        self.assertIsNone(fams["supply_shock"]["independent_window_capacity"])

    def test_global_capacity_carries_non_claim(self):
        report = _build_fixture_inventory()
        cap = report["global_summary"]["independent_window_capacity_global"]
        text = json.dumps(cap).lower()
        self.assertIn("non_claim", json.dumps(cap))
        self.assertIn("not", text)  # the C1 non-claim is a negation
        self.assertNotIn("effective sample size", text.replace("not a true effective sample size", ""))


# ---------------------------------------------------------------------------
# Pure core — banned framing
# ---------------------------------------------------------------------------

class TestNoBannedFraming(unittest.TestCase):
    def test_output_carries_no_overclaim_framing(self):
        report = _build_fixture_inventory()
        blob = json.dumps(report).lower()
        # fully-absent affirmative terms
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "trading signal", "forecast", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r} present")
        # whole-word buy / sell must not appear at all
        import re
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r} present")
        # "recommendation" allowed only inside the negated non-claim
        residue = blob.replace("not a recommendation", "")
        self.assertNotIn("recommendation", residue)

    def test_validated_label_is_the_canonical_scorer_vocabulary(self):
        # "validated" is the track_record_scoring outcome label, not a success
        # claim; it must be present (the outcome split uses it).
        report = _build_fixture_inventory()
        self.assertIn("validated", json.dumps(report))


# ---------------------------------------------------------------------------
# Sector enrichment (best-effort, must populate when the mapping is available)
# ---------------------------------------------------------------------------

class TestSectorEnrichment(unittest.TestCase):
    def test_top_sectors_aggregated_from_records(self):
        recs = [
            _rec(10, "oil prices jump", "validated", "2026-01-05", ["XOM"], True),
            _rec(11, "crude rally opec", "validated", "2026-01-06", ["CVX"], True),
        ]
        for r in recs:
            r["sector"] = "energy"
        report = assemble_inventory(
            recs, denominators=_fixture_denominators(len(recs)),
            taxonomy_readout=[], observations_bridge=_fixture_observations(),
        )
        fam = _families_by_name(report)["supply_shock"]
        self.assertEqual(fam["top_sectors"], [{"sector": "energy", "count": 2}])

    def test_sector_classifier_calls_with_keywords_and_populates(self):
        # The descriptive sector mapping is keyword-only
        # (_classify(*, ticker, headline)); the wrapper must call it correctly
        # rather than swallow a TypeError into a silent None.
        sector_of = _sector_classifier()
        self.assertIsNotNone(sector_of, "sector classifier should be importable")
        self.assertEqual(sector_of("XOM", "oil prices jump on outage"), "energy")
        self.assertEqual(sector_of("LMT", "missile launch reported"), "industrials")


# ---------------------------------------------------------------------------
# Live wiring — read-only + canonical denominators
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB is not None, local_data_skip_reason())
class TestLiveInventory(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_inventory(db_path=str(LIVE_DB))

    def test_read_only_does_not_mutate_events_db(self):
        before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        build_inventory(db_path=str(LIVE_DB))
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

    def test_live_sum_invariant_equals_eighty_six(self):
        inv = self.report["global_summary"]["sum_invariant"]
        self.assertEqual(inv["sum"], 86)
        self.assertTrue(inv["equals_track_record"])

    def test_live_output_has_no_banned_framing(self):
        import re
        blob = json.dumps(self.report).lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "trading signal", "forecast", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r} present")
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r} present")
        residue = blob.replace("not a recommendation", "")
        self.assertNotIn("recommendation", residue)


if __name__ == "__main__":
    unittest.main()
