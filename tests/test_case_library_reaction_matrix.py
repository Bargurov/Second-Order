"""Tests for ``scripts/case_library_reaction_matrix.py`` (H1).

Read-only descriptive market-reaction matrix over exactly the 15 representative
cases (6 N1 anchors + 9 newly proposed). It reuses F1's selection and F2's
event-study readout helpers; it computes no new event-study math and makes no
inference. Pins:

* exactly the 15 case ids, anchors then new, in the documented order;
* per case: role, family, outcome, event-study availability, primary ticker,
  1d/5d/20d SPY-relative readout (or explicit "unavailable");
* missing readouts are exactly 153, 154, 160 and are explicit;
* the readout block is labeled a different lens from the outcome; 29 and 38
  share an identical XLE-vs-SPY readout/date but carry opposite outcomes;
* same primary + same date rows get a shared-cluster caveat;
* canonical denominators (180 / 94 / 86 / 78-of-94 / 13) preserved;
* the report mutates nothing, output is cp1252-safe, no banned framing.

The pure ``build_matrix`` core runs on synthetic inputs; the live wiring runs
against the live archive (skipped when absent).
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

from scripts.case_library_reaction_matrix import (  # noqa: E402
    ALL_IDS,
    ANCHOR_IDS,
    NEW_IDS,
    build_matrix,
    build_report,
    render_text,
)

LIVE_DB = ROOT / "events.db"


def _case(eid, role, fam, outcome, es, *, date="2026-04-05", caveats=None,
          dq="clean_discrete_anchor", assets=None):
    return {
        "event_id": eid,
        "role": role,  # F1 role: already_covered_anchor | newly_proposed
        "family": fam,
        "outcome": outcome,
        "event_study_available": es,
        "headline": f"headline {eid}",
        "event_date": date,
        "caveats": list(caveats or []),
        "event_date_quality": dq,
        "assets": list(assets or []),
    }


def _readout(primary, ar, sar, car):
    return {"benchmark": "SPY", "primary_ticker": primary,
            "per_horizon": {1: (ar, sar, car), 5: (ar, sar, car), 20: (ar, sar, car)}}


# ---------------------------------------------------------------------------
# Pure: build_matrix
# ---------------------------------------------------------------------------

class TestBuildMatrix(unittest.TestCase):
    def test_orders_by_all_ids(self):
        cases = [_case(239, "newly_proposed", "monetary_policy_or_rates", "unresolved", True),
                 _case(1, "already_covered_anchor", "tariff", "support", True)]
        rows = build_matrix(cases, readout_by_id={})
        self.assertEqual([r["event_id"] for r in rows], [1, 239])

    def test_role_mapping_anchor_and_new(self):
        cases = [_case(1, "already_covered_anchor", "tariff", "support", True),
                 _case(7, "newly_proposed", "geopolitical_conflict_context", "support", True)]
        rows = {r["event_id"]: r for r in build_matrix(cases, readout_by_id={})}
        self.assertEqual(rows[1]["role"], "anchor")
        self.assertEqual(rows[7]["role"], "new")

    def test_available_row_has_three_horizons_and_primary(self):
        cases = [_case(7, "newly_proposed", "geopolitical_conflict_context", "support", True)]
        rows = build_matrix(cases, readout_by_id={7: _readout("XLE", -0.075, -1.99, -0.0747)})
        rd = rows[0]["readout"]
        self.assertTrue(rd["available"])
        self.assertEqual(rows[0]["primary_ticker"], "XLE")
        for h in ("1d", "5d", "20d"):
            self.assertIn(h, rd["horizons"])
        self.assertEqual(rd["horizons"]["5d"]["ar_pct"], -7.5)

    def test_missing_readout_is_explicit(self):
        cases = [_case(153, "newly_proposed", "sanction", "unresolved", False)]
        rows = build_matrix(cases, readout_by_id={})
        rd = rows[0]["readout"]
        self.assertFalse(rd["available"])
        self.assertIn("note", rd)
        self.assertIsNone(rows[0]["primary_ticker"])

    def test_shared_primary_date_cluster_caveat(self):
        cases = [
            _case(29, "newly_proposed", "supply_shock", "contradiction", True, date="2026-04-05"),
            _case(38, "newly_proposed", "supply_shock", "support", True, date="2026-04-05"),
            _case(66, "already_covered_anchor", "ceasefire_deescalation", "support", True, date="2026-04-08"),
        ]
        rd = _readout("XLE", 0.0025, 0.15, 0.0025)
        rows = {r["event_id"]: r for r in build_matrix(cases, readout_by_id={29: rd, 38: rd, 66: rd})}
        # 29 and 38 share XLE + 2026-04-05 -> cluster caveat; 66 (different date) does not
        self.assertTrue(any("cluster" in c.lower() for c in rows[29]["caveats"]))
        self.assertTrue(any("cluster" in c.lower() for c in rows[38]["caveats"]))
        self.assertFalse(any("cluster" in c.lower() for c in rows[66]["caveats"]))

    def test_overlay_only_caveat_applied_by_family(self):
        cases = [_case(239, "newly_proposed", "monetary_policy_or_rates", "unresolved", True),
                 _case(1, "already_covered_anchor", "tariff", "support", True)]
        rows = {r["event_id"]: r for r in build_matrix(
            cases, readout_by_id={}, overlay_families={"monetary_policy_or_rates"})}
        self.assertTrue(any("overlay-only" in c.lower() for c in rows[239]["caveats"]))
        self.assertFalse(any("overlay-only" in c.lower() for c in rows[1]["caveats"]))

    def test_each_row_has_non_claim(self):
        rows = build_matrix([_case(1, "already_covered_anchor", "tariff", "support", True)],
                            readout_by_id={})
        nc = rows[0]["non_claim"].lower()
        self.assertIn("descriptive case-library readout", nc)
        self.assertIn("not evidence", nc)


# ---------------------------------------------------------------------------
# Live wiring
# ---------------------------------------------------------------------------

@unittest.skipUnless(LIVE_DB.exists(), "live events.db not present")
class TestLiveMatrix(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = build_report(db_path=str(LIVE_DB))
        cls.by = {r["event_id"]: r for r in cls.report["matrix"]}

    def test_exactly_15_ids_in_order(self):
        self.assertEqual([r["event_id"] for r in self.report["matrix"]], list(ALL_IDS))
        self.assertEqual(len(ALL_IDS), 15)
        self.assertEqual(list(ANCHOR_IDS), [1, 46, 61, 66, 210, 211])
        self.assertEqual(list(NEW_IDS), [7, 29, 38, 71, 153, 154, 160, 212, 239])

    def test_roles_labeled_correctly(self):
        for i in ANCHOR_IDS:
            self.assertEqual(self.by[i]["role"], "anchor")
        for i in NEW_IDS:
            self.assertEqual(self.by[i]["role"], "new")

    def test_all_six_families_present(self):
        fams = {r["family"] for r in self.report["matrix"]}
        self.assertEqual(fams, {
            "supply_shock", "geopolitical_conflict_context", "tariff",
            "sanction", "ceasefire_deescalation", "monetary_policy_or_rates",
        })

    def test_all_outcomes_present(self):
        outs = {r["outcome"] for r in self.report["matrix"]}
        self.assertEqual(outs := outs if False else outs, {"support", "contradiction", "unresolved"})

    def test_readout_available_count_is_12_of_15(self):
        avail = sum(1 for r in self.report["matrix"] if r["readout"]["available"])
        self.assertEqual(avail, 12)
        self.assertEqual(self.report["missingness_summary"]["readout_available_count"], 12)

    def test_missing_ids_exactly_153_154_160(self):
        missing = {r["event_id"] for r in self.report["matrix"] if not r["readout"]["available"]}
        self.assertEqual(missing, {153, 154, 160})
        self.assertEqual(self.report["missingness_summary"]["missing_ids"], [153, 154, 160])

    def test_available_cases_have_three_horizons_and_primary(self):
        for r in self.report["matrix"]:
            if r["readout"]["available"]:
                self.assertIsInstance(r["primary_ticker"], str)
                for h in ("1d", "5d", "20d"):
                    self.assertIn(h, r["readout"]["horizons"])

    def test_missing_cases_say_unavailable(self):
        for i in (153, 154, 160):
            self.assertFalse(self.by[i]["readout"]["available"])
            self.assertIn("note", self.by[i]["readout"])

    def test_29_and_38_share_readout_and_date_opposite_outcome(self):
        self.assertNotEqual(self.by[29]["outcome"], self.by[38]["outcome"])
        self.assertEqual(self.by[29]["primary_ticker"], self.by[38]["primary_ticker"])
        self.assertEqual(self.by[29]["event_date"], self.by[38]["event_date"])
        self.assertEqual(self.by[29]["readout"]["horizons"], self.by[38]["readout"]["horizons"])

    def test_lens_warning_emitted(self):
        lw = json.dumps(self.report["lens_warning"]).lower()
        self.assertIn("primary ticker", lw)
        self.assertIn("spy", lw)
        self.assertIn("thesis", lw)
        self.assertIn("29", lw)
        self.assertIn("38", lw)

    def test_overlay_only_caveat_on_overlay_families(self):
        for i in (7, 46, 61, 239):  # geopolitical + monetary families
            self.assertTrue(any("overlay-only" in c.lower() for c in self.by[i]["caveats"]),
                            f"#{i} missing overlay-only caveat")
        for i in (1, 210):  # tariff + supply_shock (canonical families)
            self.assertFalse(any("overlay-only" in c.lower() for c in self.by[i]["caveats"]),
                             f"#{i} wrongly marked overlay-only")

    def test_event_date_quality_surfaced(self):
        for r in self.report["matrix"]:
            self.assertIsInstance(r["event_date_quality"], str)
            self.assertTrue(r["event_date_quality"])

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
        self.assertEqual([r["event_id"] for r in a["matrix"]],
                         [r["event_id"] for r in self.report["matrix"]])

    def test_read_only_does_not_mutate_db(self):
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
        # forecast / recommendation / trading signal are allowed only inside the
        # negated non-claims; strip those, then nothing may remain
        residue = blob
        for neg in ("not a recommendation, forecast, or trading signal",
                    "not a recommendation of any kind, and no forecast",
                    "no recommendation or forecast", "not a recommendation"):
            residue = residue.replace(neg, "")
        for w in ("forecast", "recommendation", "trading signal"):
            self.assertNotIn(w, residue, f"affirmative {w!r}")


if __name__ == "__main__":
    unittest.main()
