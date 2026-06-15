"""Tests for ``scripts/mechanism_family_comparison_report.py`` (I1).

Read-only side-by-side comparison of the accepted mechanism families. It reuses
E1's family inventory (counts) and H1's reaction matrix (selected-case readout
coverage); it computes no new score, no threshold beyond the established
thin-family flag, no inference, no significance. Pins:

* exactly the six accepted families, counts matching E1 verbatim;
* overlay-only flags on geopolitical_conflict_context + monetary_policy_or_rates;
* thin-family flags on sanction + ceasefire_deescalation + monetary_policy_or_rates;
* single 52 + multi 16 + unclassified 18 = 86 carried;
* per-family selected case ids + their readout coverage (H1: 15 selected, 12
  available, missing 153/154/160);
* outcome counts and readouts labeled as different lenses;
* no family ranked best/strongest/predictive; canonical denominators preserved;
* deterministic, cp1252-safe, read-only, no banned framing.

The pure ``build_family_comparison`` core runs on synthetic inputs; the live
wiring runs against the live archive (skipped when absent).
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

from scripts.mechanism_family_comparison_report import (  # noqa: E402
    THIN_FLOOR,
    build_family_comparison,
    build_report,
    render_text,
)

LIVE_DB = ROOT / "events.db"


def _fam(name, n, s, c, u, esa, eso, canonical):
    return {
        "family": name,
        "accepted_thesis_count": n,
        "outcomes": {"validated": s, "contradicted": c, "unresolved": u},
        "event_study_available": {"available": esa, "of_family_thesis": eso},
        "canonical_family": canonical,
    }


def _row(eid, fam, av):
    return {"event_id": eid, "family": fam, "readout": {"available": av}}


def _fixture():
    families = [
        _fam("supply_shock", 20, 11, 3, 6, 20, 20, True),
        _fam("sanction", 4, 0, 0, 4, 1, 4, True),
        _fam("monetary_policy_or_rates", 3, 1, 0, 2, 2, 3, False),
    ]
    matrix = [
        _row(210, "supply_shock", True), _row(29, "supply_shock", True),
        _row(38, "supply_shock", True),
        _row(211, "sanction", True), _row(153, "sanction", False),
        _row(154, "sanction", False),
        _row(46, "monetary_policy_or_rates", True),
        _row(239, "monetary_policy_or_rates", True),
    ]
    return families, matrix


# ---------------------------------------------------------------------------
# Pure: build_family_comparison
# ---------------------------------------------------------------------------

class TestBuildComparison(unittest.TestCase):
    def _rows(self):
        fams, matrix = _fixture()
        return {r["family"]: r for r in
                build_family_comparison(fams, matrix, thin_floor=THIN_FLOOR)}

    def test_one_row_per_family(self):
        fams, matrix = _fixture()
        rows = build_family_comparison(fams, matrix, thin_floor=THIN_FLOOR)
        self.assertEqual([r["family"] for r in rows],
                         ["supply_shock", "sanction", "monetary_policy_or_rates"])

    def test_counts_passthrough(self):
        r = self._rows()["supply_shock"]
        self.assertEqual((r["n"], r["support"], r["contradiction"], r["unresolved"]),
                         (20, 11, 3, 6))
        self.assertEqual((r["event_study_available"], r["event_study_of"]), (20, 20))

    def test_overlay_and_thin_flags(self):
        rows = self._rows()
        self.assertTrue(rows["monetary_policy_or_rates"]["overlay_only"])
        self.assertTrue(rows["monetary_policy_or_rates"]["thin"])
        self.assertTrue(rows["sanction"]["thin"])
        self.assertFalse(rows["sanction"]["overlay_only"])
        self.assertFalse(rows["supply_shock"]["thin"])
        self.assertFalse(rows["supply_shock"]["overlay_only"])

    def test_selected_ids_and_readout_coverage(self):
        rows = self._rows()
        self.assertEqual(sorted(rows["supply_shock"]["selected_case_ids"]), [29, 38, 210])
        self.assertEqual(rows["supply_shock"]["selected_readout_available"], 3)
        self.assertEqual(rows["supply_shock"]["selected_missing_ids"], [])
        self.assertEqual(rows["sanction"]["selected_readout_available"], 1)
        self.assertEqual(rows["sanction"]["selected_missing_ids"], [153, 154])

    def test_es_coverage_complete_vs_partial(self):
        rows = self._rows()
        self.assertEqual(rows["supply_shock"]["event_study_coverage"], "complete")
        self.assertEqual(rows["sanction"]["event_study_coverage"], "partial")

    def test_unresolved_heavy_and_contradiction_flags(self):
        rows = self._rows()
        self.assertTrue(rows["sanction"]["unresolved_heavy"])
        self.assertTrue(rows["supply_shock"]["contradiction_present"])
        self.assertFalse(rows["supply_shock"]["unresolved_heavy"])

    def test_caveats_present(self):
        rows = self._rows()
        sanction = " ".join(rows["sanction"]["caveats"]).lower()
        self.assertIn("thin family", sanction)
        self.assertIn("missing event-study readouts", sanction)
        self.assertIn("illustrative", " ".join(rows["supply_shock"]["caveats"]).lower())


# ---------------------------------------------------------------------------
# Live wiring
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class TestLiveComparison(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(db_path=str(LIVE_DB))
        cls.by = {r["family"]: r for r in cls.report["family_comparison"]}

    def test_six_families_counts_match_e1(self):
        expected = {
            "supply_shock": (20, 11, 3, 6, 20, 20),
            "geopolitical_conflict_context": (11, 7, 2, 2, 10, 11),
            "tariff": (11, 5, 0, 6, 8, 11),
            "sanction": (4, 0, 0, 4, 1, 4),
            "ceasefire_deescalation": (3, 2, 0, 1, 2, 3),
            "monetary_policy_or_rates": (3, 1, 0, 2, 2, 3),
        }
        self.assertEqual(set(self.by), set(expected))
        for fam, (n, s, c, u, esa, eso) in expected.items():
            r = self.by[fam]
            self.assertEqual(
                (r["n"], r["support"], r["contradiction"], r["unresolved"],
                 r["event_study_available"], r["event_study_of"]),
                (n, s, c, u, esa, eso), fam)

    def test_overlay_only_flags(self):
        self.assertTrue(self.by["geopolitical_conflict_context"]["overlay_only"])
        self.assertTrue(self.by["monetary_policy_or_rates"]["overlay_only"])
        self.assertFalse(self.by["supply_shock"]["overlay_only"])

    def test_thin_flags(self):
        for fam in ("sanction", "ceasefire_deescalation", "monetary_policy_or_rates"):
            self.assertTrue(self.by[fam]["thin"], fam)
        for fam in ("supply_shock", "geopolitical_conflict_context", "tariff"):
            self.assertFalse(self.by[fam]["thin"], fam)

    def test_sum_invariant_carried(self):
        si = self.report["global_summary"]["sum_invariant"]
        self.assertEqual((si["single_match_total"], si["multi_match"],
                          si["unclassified"], si["sum"]), (52, 16, 18, 86))

    def test_selected_case_ids_per_family(self):
        expected = {
            "supply_shock": {210, 38, 29},
            "geopolitical_conflict_context": {61, 7},
            "tariff": {1, 212},
            "sanction": {211, 153, 154},
            "ceasefire_deescalation": {66, 71, 160},
            "monetary_policy_or_rates": {46, 239},
        }
        for fam, ids in expected.items():
            self.assertEqual(set(self.by[fam]["selected_case_ids"]), ids, fam)

    def test_h1_readout_coverage_surfaced(self):
        cl = self.report["global_summary"]["case_library"]
        self.assertEqual(cl["total_selected"], 15)
        self.assertEqual(cl["readout_available"], 12)
        self.assertEqual(cl["missing_ids"], [153, 154, 160])

    def test_lens_discipline_stated(self):
        ld = json.dumps(self.report["lens_discipline"]).lower()
        self.assertIn("thesis-direction", ld)
        self.assertIn("primary ticker", ld)
        self.assertIn("spy", ld)

    def test_does_not_rank_families(self):
        import re
        blob = json.dumps(self.report).lower()
        for w in ["best", "strongest", "predictive", "performance"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"ranking word {w!r}")

    def test_canonical_denominators_preserved(self):
        d = self.report["denominators"]
        self.assertEqual(d["archive_rows"], 180)
        self.assertEqual(d["accepted_coverage_denominator"], 94)
        self.assertEqual(d["accepted_track_record_denominator"], 86)
        self.assertEqual(d["event_study_available_count"], 78)
        self.assertEqual(d["event_study_coverage_denominator"], 94)
        self.assertEqual(d["staged_candidates"], 13)

    def test_deterministic(self):
        a = build_report(db_path=str(LIVE_DB))
        self.assertEqual([r["family"] for r in a["family_comparison"]],
                         [r["family"] for r in self.report["family_comparison"]])

    def test_read_only_no_mutation(self):
        before = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        build_report(db_path=str(LIVE_DB))
        after = hashlib.sha256(LIVE_DB.read_bytes()).hexdigest()
        self.assertEqual(before, after)

    def test_text_render_cp1252_safe(self):
        render_text(self.report).encode("cp1252")

    def test_no_banned_framing(self):
        import re
        blob = json.dumps(self.report).lower()
        for w in ["proof", "proven", "statistically significant",
                  "validated-as-success", "alpha"]:
            self.assertNotIn(w, blob, f"banned term {w!r}")
        for w in ["buy", "sell"]:
            self.assertIsNone(re.search(rf"\b{w}\b", blob), f"banned word {w!r}")
        # forecast / recommendation / trading signal allowed only in negated non-claims
        residue = blob
        for neg in ("not a recommendation, forecast, or trading signal",
                    "no recommendation or forecast", "not a recommendation"):
            residue = residue.replace(neg, "")
        for w in ("forecast", "recommendation", "trading signal"):
            self.assertNotIn(w, residue, f"affirmative {w!r}")


if __name__ == "__main__":
    unittest.main()
