"""Tests for ``scripts/event_date_quality_distribution_report.py`` (J1).

A read-only honesty layer that shows how reliable the event-date anchors are
across the archive, the accepted corpus, the event-study-available subset, and
the 15-case representative library. It reuses the existing event-date quality
labels (``scripts/event_date_quality_report``), the event-study coverage report,
the representative case matrix (H1), and the family overlay (E1). It computes:

* NO new score, NO ranking, NO best/worst, NO inference / p-value / FDR.

Pins (RED first):

* canonical denominators 180 / 94 / 86 / 78-of-94 / 13;
* the label definition set is EXACTLY the six edq labels (incl. the archive-only
  ``continuation_or_thread_sibling``), in canonical edq order, each carrying its
  reused anticipation_risk and a guardrail that risk is never summed or ranked;
* five distributions, each listing ALL six labels with explicit zeros, summing
  to their denominator (archive accounts for the 72 unlabeled = 71 realized +
  1 curated_intake; total 180);
* ``event_study_available`` is labeled a coverage-lens subset (78 of 94,
  including 8 curated rows), not a track-record subset;
* 15 representative cases with four distinct lens fields (label / es-available /
  readout-available / outcome), known labels pinned, missing readouts 153/154/160;
* a six-family cross-section (single 52 + multi 16 + unclassified 18 = 86);
* no aggregated quality score / share / percent / rank anywhere;
* lens discipline, reader takeaways, non-claims, deterministic, cp1252-safe,
  read-only, no banned framing.

The pure ``tabulate`` core runs on synthetic inputs; the live wiring runs
against the live archive (skipped when absent).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.event_date_quality_distribution_report import (  # noqa: E402
    FAMILY_ORDER,
    LABELS,
    LABEL_DEFINITIONS,
    build_report,
    format_count_pct,
    main,
    percent,
    render_text,
    tabulate,
)
from scripts.event_date_quality_report import LABELS as EDQ_LABELS  # noqa: E402

LIVE_DB = ROOT / "events.db"

REPRESENTATIVE_IDS = {1, 7, 29, 38, 46, 61, 66, 71, 153, 154, 160, 210, 211, 212, 239}
MISSING_READOUT_IDS = [153, 154, 160]


# --------------------------------------------------------------------------- #
# Pure core: tabulate                                                         #
# --------------------------------------------------------------------------- #
class TestTabulatePure(unittest.TestCase):
    def test_lists_all_labels_with_zeros_in_canonical_order(self):
        out = tabulate(["clean_discrete_anchor", "manual_review_needed",
                        "manual_review_needed"])
        self.assertEqual(list(out["counts"].keys()), list(LABELS))
        self.assertEqual(out["counts"]["manual_review_needed"], 2)
        self.assertEqual(out["counts"]["clean_discrete_anchor"], 1)
        # labels not present are explicit zeros, not missing keys
        self.assertEqual(out["counts"]["continuation_or_thread_sibling"], 0)
        self.assertEqual(out["counts"]["partial_anticipation"], 0)

    def test_total_equals_len_input(self):
        out = tabulate(["partial_anticipation"] * 4 + ["duplicate_or_deferred"])
        self.assertEqual(out["total"], 5)
        self.assertEqual(sum(out["counts"].values()), 5)

    def test_unknown_label_raises(self):
        with self.assertRaises(ValueError):
            tabulate(["not_a_real_label"])


# --------------------------------------------------------------------------- #
# Pure core: percent / format_count_pct (J1A)                                #
# --------------------------------------------------------------------------- #
class TestPercentPure(unittest.TestCase):
    def test_percent_one_decimal(self):
        self.assertEqual(percent(57, 86), 66.3)
        self.assertEqual(percent(57, 108), 52.8)
        self.assertEqual(percent(0, 15), 0.0)
        self.assertEqual(percent(15, 15), 100.0)

    def test_percent_zero_denominator_is_zero(self):
        self.assertEqual(percent(3, 0), 0.0)

    def test_format_count_pct_keeps_count_primary(self):
        self.assertEqual(format_count_pct(57, 86), "57 (66.3%)")
        self.assertEqual(format_count_pct(0, 15), "0 (0.0%)")


# --------------------------------------------------------------------------- #
# Label definitions                                                           #
# --------------------------------------------------------------------------- #
class TestLabelDefinitions(unittest.TestCase):
    def test_labels_match_edq_exactly(self):
        # drift guard: J1 must reuse the authoritative edq label set
        self.assertEqual(tuple(LABELS), tuple(EDQ_LABELS))
        self.assertEqual(set(LABEL_DEFINITIONS), set(EDQ_LABELS))

    def test_includes_archive_only_sixth_label(self):
        self.assertIn("continuation_or_thread_sibling", LABEL_DEFINITIONS)

    def test_each_definition_has_text_and_risk(self):
        for label in LABELS:
            d = LABEL_DEFINITIONS[label]
            self.assertTrue(d["definition"].strip(), label)
            self.assertTrue(d["anticipation_risk"].strip(), label)


# --------------------------------------------------------------------------- #
# Live wiring                                                                 #
# --------------------------------------------------------------------------- #
@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class TestLiveReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(db_path=str(LIVE_DB))
        cls.blob = json.dumps(cls.report).lower()
        cls.text = render_text(cls.report)
        cls.dists = {d["subset"]: d for d in cls.report["distributions"]}

    # -- denominators -------------------------------------------------------- #
    def test_canonical_denominators(self):
        d = self.report["denominators"]
        self.assertEqual(d["archive_rows"], 180)
        self.assertEqual(d["accepted_coverage"], 94)
        self.assertEqual(d["accepted_track_record"], 86)
        self.assertEqual(d["event_study_available"], 78)
        self.assertEqual(d["event_study_total"], 94)
        self.assertEqual(d["staged_candidates"], 13)

    # -- definitions reuse anticipation_risk from edq ------------------------ #
    def test_definitions_in_canonical_order_with_guardrail(self):
        keys = [row["label"] for row in self.report["label_definitions"]]
        self.assertEqual(keys, list(LABELS))
        self.assertTrue(self.report["label_definition_guardrail"].strip())
        # guardrail must say risk is not summed / not used to rank
        g = self.report["label_definition_guardrail"].lower()
        self.assertIn("not", g)
        self.assertTrue("sum" in g or "rank" in g or "score" in g)

    # -- every distribution lists all six labels ----------------------------- #
    def test_every_distribution_has_all_six_labels_in_order(self):
        self.assertEqual(
            {"archive", "accepted_coverage", "accepted_track_record",
             "event_study_available", "representative_library"},
            set(self.dists),
        )
        for name, dist in self.dists.items():
            self.assertEqual(list(dist["counts"].keys()), list(LABELS), name)

    # -- each distribution sums to its denominator --------------------------- #
    def test_archive_distribution_accounts_for_180(self):
        d = self.dists["archive"]
        self.assertEqual(sum(d["counts"].values()), 108)
        self.assertEqual(d["labeled_total"], 108)
        self.assertEqual(d["unlabeled"]["total"], 72)
        self.assertEqual(d["unlabeled"]["by_stage"]["realized"], 71)
        self.assertEqual(d["unlabeled"]["by_stage"]["curated_intake"], 1)
        self.assertEqual(d["labeled_total"] + d["unlabeled"]["total"], 180)
        # archive-only sixth label appears here
        self.assertEqual(d["counts"]["continuation_or_thread_sibling"], 4)
        self.assertEqual(d["counts"]["manual_review_needed"], 57)
        self.assertEqual(d["counts"]["clean_discrete_anchor"], 15)

    def test_coverage_distribution_sums_to_94(self):
        d = self.dists["accepted_coverage"]
        self.assertEqual(sum(d["counts"].values()), 94)
        self.assertEqual(d["labeled_total"], 94)
        self.assertEqual(d["counts"]["clean_discrete_anchor"], 11)
        self.assertEqual(d["counts"]["manual_review_needed"], 57)
        self.assertEqual(d["counts"]["continuation_or_thread_sibling"], 0)

    def test_track_record_distribution_sums_to_86(self):
        d = self.dists["accepted_track_record"]
        self.assertEqual(sum(d["counts"].values()), 86)
        self.assertEqual(d["labeled_total"], 86)
        self.assertEqual(d["counts"]["clean_discrete_anchor"], 5)
        self.assertEqual(d["counts"]["manual_review_needed"], 57)
        self.assertEqual(d["counts"]["continuation_or_thread_sibling"], 0)

    def test_es_distribution_sums_to_78_and_is_coverage_lens(self):
        d = self.dists["event_study_available"]
        self.assertEqual(sum(d["counts"].values()), 78)
        self.assertEqual(d["labeled_total"], 78)
        self.assertEqual(d["counts"]["manual_review_needed"], 45)
        self.assertEqual(d["counts"]["clean_discrete_anchor"], 10)
        self.assertEqual(d["counts"]["continuation_or_thread_sibling"], 0)
        # advisor: must be marked a coverage-lens subset (incl. curated), not
        # a track-record subset
        lens = d["lens"].lower()
        self.assertIn("coverage", lens)
        self.assertIn("78", lens)
        self.assertIn("94", lens)
        self.assertEqual(d["corpus_split"], {"accepted": 70, "curated": 8})

    def test_representative_distribution_sums_to_15(self):
        d = self.dists["representative_library"]
        self.assertEqual(sum(d["counts"].values()), 15)
        self.assertEqual(d["counts"]["clean_discrete_anchor"], 2)
        self.assertEqual(d["counts"]["partial_anticipation"], 3)
        self.assertEqual(d["counts"]["scheduled_or_weak_anchor"], 5)
        self.assertEqual(d["counts"]["duplicate_or_deferred"], 1)
        self.assertEqual(d["counts"]["manual_review_needed"], 4)
        self.assertEqual(d["counts"]["continuation_or_thread_sibling"], 0)

    # -- descriptive percentages (J1A) --------------------------------------- #
    def test_every_distribution_has_counts_and_percentages(self):
        for name, dist in self.dists.items():
            self.assertIn("percentages", dist, name)
            self.assertIn("percent_denominator", dist, name)
            # counts still primary and present
            self.assertEqual(list(dist["counts"].keys()), list(LABELS), name)
            # percentages over all six labels, canonical order (not sorted)
            self.assertEqual(list(dist["percentages"].keys()), list(LABELS), name)

    def test_archive_percent_denominator_is_108_not_180(self):
        d = self.dists["archive"]
        self.assertEqual(d["percent_denominator"], 108)
        self.assertNotEqual(d["percent_denominator"], 180)
        self.assertEqual(d["percentages"]["manual_review_needed"],
                         round(57 / 108 * 100, 1))
        self.assertEqual(d["percentages"]["manual_review_needed"], 52.8)

    def test_archive_unlabeled_72_of_180_stays_explicit(self):
        d = self.dists["archive"]
        self.assertEqual(d["unlabeled"]["total"], 72)
        self.assertEqual(d["denominator"], 180)
        self.assertEqual(d["unlabeled"]["percent_of_archive"],
                         round(72 / 180 * 100, 1))
        self.assertEqual(d["unlabeled"]["percent_of_archive"], 40.0)

    def test_coverage_percent_denominator_is_94(self):
        d = self.dists["accepted_coverage"]
        self.assertEqual(d["percent_denominator"], 94)
        self.assertEqual(d["percentages"]["manual_review_needed"],
                         round(57 / 94 * 100, 1))

    def test_track_record_percent_denominator_is_86(self):
        d = self.dists["accepted_track_record"]
        self.assertEqual(d["percent_denominator"], 86)
        self.assertEqual(d["percentages"]["manual_review_needed"], 66.3)

    def test_es_percent_denominator_is_78(self):
        d = self.dists["event_study_available"]
        self.assertEqual(d["percent_denominator"], 78)
        self.assertEqual(d["percentages"]["manual_review_needed"],
                         round(45 / 78 * 100, 1))

    def test_representative_percent_denominator_is_15(self):
        d = self.dists["representative_library"]
        self.assertEqual(d["percent_denominator"], 15)
        self.assertEqual(d["percentages"]["scheduled_or_weak_anchor"],
                         round(5 / 15 * 100, 1))

    def test_percentages_match_counts_over_denominator(self):
        for name, dist in self.dists.items():
            denom = dist["percent_denominator"]
            for label in LABELS:
                self.assertEqual(
                    dist["percentages"][label],
                    round(dist["counts"][label] / denom * 100, 1),
                    f"{name}/{label}",
                )

    def test_original_counts_unchanged(self):
        self.assertEqual(self.dists["archive"]["counts"]["manual_review_needed"], 57)
        self.assertEqual(self.dists["archive"]["counts"]["clean_discrete_anchor"], 15)
        self.assertEqual(
            self.dists["accepted_track_record"]["counts"]["clean_discrete_anchor"], 5)
        self.assertEqual(sum(self.dists["accepted_coverage"]["counts"].values()), 94)
        self.assertEqual(sum(self.dists["accepted_track_record"]["counts"].values()), 86)
        self.assertEqual(sum(self.dists["event_study_available"]["counts"].values()), 78)
        self.assertEqual(sum(self.dists["representative_library"]["counts"].values()), 15)

    def test_percentage_guardrail_present(self):
        g = self.report["percentage_guardrail"].lower()
        self.assertIn("descriptive composition", g)
        self.assertIn("not", g)
        self.assertIn("score", g)
        self.assertIn("rank", g)
        # avoid-list discipline: never frame anchors as better/worse
        self.assertNotIn("better or worse", g)
        self.assertNotIn("worst", g)

    def test_percent_visible_in_text(self):
        self.assertIn("%", self.text)
        self.assertIn("descriptive composition", self.text.lower())

    # -- representative cases: four distinct lenses --------------------------- #
    def test_representative_cases_15_ids_with_four_lens_fields(self):
        cases = self.report["representative_cases"]
        self.assertEqual({c["event_id"] for c in cases}, REPRESENTATIVE_IDS)
        self.assertEqual(len(cases), 15)
        for c in cases:
            for field in ("event_date_quality", "anticipation_risk",
                          "anchor_caveat", "event_study_available",
                          "readout_available", "outcome", "family", "role"):
                self.assertIn(field, c, f"{c['event_id']} missing {field}")
            self.assertTrue(c["anchor_caveat"].strip())
            self.assertIsInstance(c["event_study_available"], bool)
            self.assertIsInstance(c["readout_available"], bool)

    def test_representative_known_labels(self):
        by_id = {c["event_id"]: c["event_date_quality"]
                 for c in self.report["representative_cases"]}
        for cid in (210, 212):
            self.assertEqual(by_id[cid], "clean_discrete_anchor", cid)
        for cid in (1, 61, 160):
            self.assertEqual(by_id[cid], "partial_anticipation", cid)
        for cid in (46, 66, 211, 71, 153):
            self.assertEqual(by_id[cid], "scheduled_or_weak_anchor", cid)
        self.assertEqual(by_id[29], "duplicate_or_deferred")
        for cid in (7, 38, 154, 239):
            self.assertEqual(by_id[cid], "manual_review_needed", cid)

    def test_representative_labels_match_edq_source(self):
        # drift guard: each case label is the edq label for that id verbatim
        from scripts.event_date_quality_report import build_report as edq
        edq_by_id = {e["event_id"]: e["event_date_quality"]
                     for e in edq(db_path=str(LIVE_DB))["events"]}
        for c in self.report["representative_cases"]:
            self.assertEqual(c["event_date_quality"],
                             edq_by_id[c["event_id"]], c["event_id"])

    def test_missing_readouts_153_154_160(self):
        cases = {c["event_id"]: c for c in self.report["representative_cases"]}
        self.assertEqual(self.report["missing_readout_ids"], MISSING_READOUT_IDS)
        for cid in MISSING_READOUT_IDS:
            self.assertFalse(cases[cid]["readout_available"], cid)
        available = [cid for cid in REPRESENTATIVE_IDS
                     if cid not in MISSING_READOUT_IDS]
        for cid in available:
            self.assertTrue(cases[cid]["readout_available"], cid)

    # -- six-family cross-section ------------------------------------------- #
    def test_family_cross_section(self):
        fx = self.report["family_cross_section"]
        fams = fx["families"]
        self.assertEqual([f["family"] for f in fams], list(FAMILY_ORDER))
        ns = {f["family"]: f["n"] for f in fams}
        self.assertEqual(ns["supply_shock"], 20)
        self.assertEqual(ns["geopolitical_conflict_context"], 11)
        self.assertEqual(ns["tariff"], 11)
        self.assertEqual(ns["sanction"], 4)
        self.assertEqual(ns["ceasefire_deescalation"], 3)
        self.assertEqual(ns["monetary_policy_or_rates"], 3)
        self.assertEqual(sum(ns.values()), 52)
        self.assertEqual(fx["multi_match"], 16)
        self.assertEqual(fx["unclassified"], 18)
        self.assertEqual(fx["single_match_total"] + fx["multi_match"]
                         + fx["unclassified"], 86)
        # every family lists all six labels with zeros, canonical order
        for f in fams:
            self.assertEqual(list(f["counts"].keys()), list(LABELS), f["family"])
            self.assertEqual(sum(f["counts"].values()), f["n"], f["family"])
        supply = next(f for f in fams if f["family"] == "supply_shock")
        self.assertEqual(supply["counts"]["manual_review_needed"], 14)
        self.assertEqual(supply["counts"]["duplicate_or_deferred"], 3)
        self.assertEqual(supply["counts"]["clean_discrete_anchor"], 2)
        self.assertEqual(supply["counts"]["partial_anticipation"], 1)
        tariff = next(f for f in fams if f["family"] == "tariff")
        self.assertEqual(tariff["counts"]["clean_discrete_anchor"], 3)

    # -- no quality aggregation (advisor's core trap) ------------------------ #
    def test_no_quality_aggregation_anywhere(self):
        # No field aggregates labels into a per-subset/per-family quality score,
        # share, percentage, or rank.
        def walk(obj, path=""):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    kl = str(k).lower()
                    for bad in ("quality_score", "reliability_score",
                                "clean_share", "pct_clean", "percent_clean",
                                "quality_rank", "rank", "weighted_score",
                                "risk_score", "score"):
                        self.assertNotIn(bad, kl,
                                         f"aggregating key {k!r} at {path}")
                    walk(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    walk(v, f"{path}[{i}]")
        walk(self.report)

    def test_distributions_not_sorted_by_count(self):
        # canonical label order, never reordered by frequency or risk
        for dist in self.dists.values():
            self.assertEqual(list(dist["counts"].keys()), list(LABELS))

    # -- lens discipline, takeaways, non-claims ------------------------------ #
    def test_lens_discipline_present(self):
        ld = " ".join(self.report["lens_discipline"]).lower()
        self.assertIn("label", ld)
        self.assertTrue("readout" in ld or "event-study" in ld or "outcome" in ld)
        self.assertIn("not", ld)  # "do not collapse" / "is not"

    def test_reader_takeaways_and_no_ranking_statement(self):
        blob = self.blob
        self.assertTrue(self.report["reader_takeaways"])
        # explicit honesty statements: no new score, no ranking
        self.assertIn("no new score", blob)
        self.assertTrue("not a ranking" in blob or "ranks nothing" in blob
                        or "no ranking" in blob)

    def test_non_claims_present(self):
        nc = " ".join(self.report["non_claims"]).lower()
        self.assertIn("not", nc)
        self.assertTrue("fdr" in nc or "phase 1" in nc or "separate" in nc)

    # -- determinism / cp1252 / banned framing ------------------------------- #
    def test_render_text_deterministic_and_cp1252(self):
        again = render_text(build_report(db_path=str(LIVE_DB)))
        self.assertEqual(self.text, again)
        self.text.encode("cp1252")  # raises if a non-cp1252 char slipped in
        self.assertIn("Event-date quality distribution", self.text)
        self.assertIn("180", self.text)

    def test_no_banned_framing(self):
        blob = json.dumps(self.report).lower() + "\n" + self.text.lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "alpha", "best ", "strongest",
                  "predictive", "winner", "loser"]:
            self.assertNotIn(w, blob, f"banned term {w!r}")
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r}")
        residue = blob
        for neg in ("not a recommendation, forecast, or trading signal",
                    "no recommendation or forecast", "not a recommendation"):
            residue = residue.replace(neg, "")
        for w in ("forecast", "recommendation", "trading signal"):
            self.assertNotIn(w, residue, f"affirmative {w!r}")

    # -- CLI ----------------------------------------------------------------- #
    def test_main_json_and_text_exit_zero(self):
        import io
        buf = io.StringIO()
        rc = main(["--db-path", str(LIVE_DB), "--json"], out=buf)
        self.assertEqual(rc, 0)
        parsed = json.loads(buf.getvalue())
        self.assertEqual(parsed["denominators"]["archive_rows"], 180)
        buf2 = io.StringIO()
        rc2 = main(["--db-path", str(LIVE_DB)], out=buf2)
        self.assertEqual(rc2, 0)
        self.assertIn("Event-date quality distribution", buf2.getvalue())

    # -- read-only ----------------------------------------------------------- #
    def test_read_only(self):
        before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        build_report(db_path=str(LIVE_DB))
        after = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main(verbosity=2)
