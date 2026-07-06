"""Tests for Mission I2C-B - the frozen falsifier battery (F1-F6).

Contract under test (I0 protocol i0-v1 section 15; task I2C-B):

* direction is sign(MEMP - 0.5) with the G6B convention: sign(0)=0, and a flip
  is counted only when sign(perturbed) * sign(full) == -1 (an exact-0.5 is
  never a flip);
* F1 LOYO removes each calendar year's EVENTS AND ordinary dates (reference R
  shrinks) and recomputes MEMP against the reduced R; F2 LOEO removes one
  EVENT at a time with R FIXED (so LOEO MEMP == median of the surviving I2B
  event percentiles);
* F3 decimates against the canonical greedy earliest-first disjoint subset
  (I1A geometry, starts >= h+1), the SAME reference sessions across the four
  metrics, with counts 927/233 (FOMC) and 960/287/51 (OPEC);
* F4 is per family x horizon (sign counts over 4 metrics); F5 is per family x
  metric (agreement over feasible horizons); F6 is the inside/outside
  central-50% [0.25, 0.75] position of the I2C-A calibration percentile;
* the 20-cell family, observed MEMPs, and calibration percentiles are
  unchanged; no ranking, no combined score, no significance framing.

Conventions are unit-tested on hand distributions; the full 20-cell battery is
tested live (builds the I2A substrate once) and skipped without the cache.
"""
from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import i2a_response_substrate as i2a  # noqa: E402
from scripts import i2b_memp_primary as i2b  # noqa: E402
from scripts import i2c_calibration as i2c  # noqa: E402
from scripts import i2c_falsifiers as i2f  # noqa: E402

LIVE_DB = i1.default_db_path()
LIVE_READY = LIVE_DB.exists()


# ---------------------------------------------------------------------------
# Direction and flip convention (G6B)
# ---------------------------------------------------------------------------


class SignConventionTests(unittest.TestCase):
    def test_sign_dir_above_below_and_exact_half(self):
        self.assertEqual(i2f.sign_dir(0.6), 1)
        self.assertEqual(i2f.sign_dir(0.4), -1)
        self.assertEqual(i2f.sign_dir(0.5), 0)

    def test_flip_only_on_strict_opposite(self):
        self.assertTrue(i2f.flipped(0.4, 0.6))   # - vs + -> flip
        self.assertTrue(i2f.flipped(0.6, 0.4))
        self.assertFalse(i2f.flipped(0.6, 0.7))  # + vs + -> no flip
        self.assertFalse(i2f.flipped(0.4, 0.3))

    def test_exact_half_is_never_a_flip(self):
        self.assertFalse(i2f.flipped(0.5, 0.6))  # perturbed exactly 0.5
        self.assertFalse(i2f.flipped(0.6, 0.5))  # full exactly 0.5
        self.assertFalse(i2f.flipped(0.5, 0.5))


class AbsMidRankHelperTests(unittest.TestCase):
    def test_matches_i2b_absolute_mid_rank(self):
        R = [-3.0, 1.0, 1.0, -2.0, 5.0]
        sorted_abs = sorted(abs(r) for r in R)
        for v in (-4.0, 1.0, 0.0, 2.5, 5.0):
            self.assertEqual(
                i2f._abs_mid_rank(v, sorted_abs),
                i2b.mid_rank_percentile(v, R, absolute=True))


# ---------------------------------------------------------------------------
# F2 (R fixed) and F1 (R reduced) pure recomputation
# ---------------------------------------------------------------------------


class LeaveOneOutTests(unittest.TestCase):
    def test_loeo_is_median_of_surviving_percentiles_R_fixed(self):
        abs_pcts = {"a": 0.9, "b": 0.9, "c": 0.1, "d": 0.1, "e": 0.9}
        full = statistics.median(abs_pcts.values())
        surface = i2f.loeo_surface(abs_pcts, full)
        self.assertEqual(len(surface), 5)
        for row in surface:
            others = [p for k, p in abs_pcts.items() if k != row["identity"]]
            self.assertEqual(row["memp"], statistics.median(others))

    def test_loeo_flip_uses_full_sign(self):
        # full median = 0.9 (>0.5). Removing one high value can drop median.
        abs_pcts = {"a": 0.9, "b": 0.9, "c": 0.1}   # median 0.9
        surface = i2f.loeo_surface(abs_pcts, 0.9)
        # remove 'a' -> [0.9,0.1] median 0.5 -> sign 0 -> not a flip
        row_a = next(r for r in surface if r["identity"] == "a")
        self.assertEqual(row_a["memp"], 0.5)
        self.assertFalse(row_a["flip"])

    def test_loyo_reduces_reference_and_recomputes(self):
        # events across two years; year removal drops both events and refs
        events = [("e18", "2018-06-01", 5.0, "2018"),
                  ("e19", "2019-06-01", 1.0, "2019")]
        references = [("2018-03-01", 0.0, "2018"), ("2018-03-02", 4.0, "2018"),
                      ("2019-03-01", 2.0, "2019"), ("2019-03-02", 3.0, "2019")]
        full = 0.75  # arbitrary carried full-sample MEMP
        surface = i2f.loyo_surface(events, references, full)
        self.assertEqual({r["year"] for r in surface}, {"2018", "2019"})
        # remove 2018: survivor e19 (|1.0|) vs R' = |{2.0,3.0}| -> below both -> 0
        row18 = next(r for r in surface if r["year"] == "2018")
        self.assertEqual(row18["memp"], 0.0)
        # remove 2019: survivor e18 (|5.0|) vs R' = |{0.0,4.0}| -> above both -> 1
        row19 = next(r for r in surface if r["year"] == "2019")
        self.assertEqual(row19["memp"], 1.0)


# ---------------------------------------------------------------------------
# F3 decimation, F4/F5 grouping, F6 position (pure)
# ---------------------------------------------------------------------------


class DecimationAndGroupingTests(unittest.TestCase):
    def test_decimated_memp_ranks_events_against_subset(self):
        event_values = [10.0, -1.0]
        subset_ref = [2.0, -3.0, 5.0]   # |.| = 2.0, 3.0, 5.0
        memp = i2f.decimated_memp(event_values, subset_ref)
        # |10| above all -> 1.0 ; |1| below all -> 0.0 ; median -> 0.5
        self.assertEqual(memp, 0.5)

    def test_f4_counts_metric_signs_with_zero_bucket(self):
        memps = {"raw_return": 0.7, "spy_relative_ar": 0.6,
                 "sector_relative_ar": 0.4, "sar": 0.5}
        out = i2f.f4_summary(memps)
        self.assertEqual(out["sign_counts"],
                         {"positive": 2, "zero": 1, "negative": 1})
        self.assertEqual(out["signs"]["sar"], 0)

    def test_f5_agreement_requires_one_sign_and_no_zero(self):
        self.assertTrue(i2f.f5_summary({1: 0.6, 5: 0.7})["same_across_horizons"])
        self.assertFalse(i2f.f5_summary({1: 0.6, 5: 0.4})["same_across_horizons"])
        self.assertFalse(
            i2f.f5_summary({1: 0.6, 5: 0.5})["same_across_horizons"])  # a 0

    def test_f6_inside_and_outside_inclusive_quartiles(self):
        self.assertEqual(i2f.f6_position(0.25), "inside")   # inclusive
        self.assertEqual(i2f.f6_position(0.75), "inside")
        self.assertEqual(i2f.f6_position(0.5), "inside")
        self.assertEqual(i2f.f6_position(0.2), "outside")
        self.assertEqual(i2f.f6_position(0.9), "outside")


# ---------------------------------------------------------------------------
# Live: the complete 20-cell battery over one substrate
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "local G3 price cache required")
class LiveFalsifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sub = i2a.build_substrate()
        cls.observed = i2b.build_primary(cls.sub, expect_frozen=True)
        cls.calibration = i2c.build_calibration(cls.sub, cls.observed,
                                                expect_frozen=True)
        cls.res = i2f.build_falsifiers(cls.sub, cls.observed, cls.calibration,
                                       expect_frozen=True)

    def test_20_cells_frozen_order_no_fomc_20d(self):
        cells = self.res["cells"]
        self.assertEqual(len(cells), 20)
        self.assertFalse(any(c["family"] == "FOMC" and c["horizon"] == 20
                             for c in cells))
        expected = []
        for family, hs in (("FOMC", (1, 5)), ("OPEC", (1, 5, 20))):
            for h in hs:
                for m in i2a.METRICS:
                    expected.append((family, h, m))
        self.assertEqual([(c["family"], c["horizon"], c["metric"])
                          for c in cells], expected)

    def test_observed_memps_unchanged_from_i2b(self):
        obs = {(c["family"], c["horizon"], c["metric"]): c["memp"]
               for c in self.observed["cells"]}
        for c in self.res["cells"]:
            self.assertEqual(c["observed_memp"],
                             obs[(c["family"], c["horizon"], c["metric"])])

    def test_calibration_percentiles_unchanged_from_i2c_a(self):
        cal = {(c["family"], c["horizon"], c["metric"]):
               c["calibration_percentile"] for c in self.calibration["cells"]}
        for c in self.res["cells"]:
            self.assertEqual(c["calibration_percentile"],
                             cal[(c["family"], c["horizon"], c["metric"])])

    def test_loyo_runs_are_eight_years_per_cell(self):
        for c in self.res["cells"]:
            self.assertEqual(c["loyo_runs"], 8)
            surface = self.res["loyo"][(c["family"], c["horizon"], c["metric"])]
            self.assertEqual(len(surface), 8)
            self.assertEqual(c["loyo_flips"],
                             sum(1 for r in surface if r["flip"]))

    def test_loeo_runs_match_event_denominator(self):
        for c in self.res["cells"]:
            want = 65 if c["family"] == "FOMC" else 32
            self.assertEqual(c["loeo_runs"], want)
            surface = self.res["loeo"][(c["family"], c["horizon"], c["metric"])]
            self.assertEqual(len(surface), want)
            self.assertEqual(c["loeo_flips"],
                             sum(1 for r in surface if r["flip"]))

    def test_f3_canonical_reference_counts(self):
        want = {("FOMC", 1): 927, ("FOMC", 5): 233,
                ("OPEC", 1): 960, ("OPEC", 5): 287, ("OPEC", 20): 51}
        for c in self.res["cells"]:
            self.assertEqual(c["f3_reference_n"],
                             want[(c["family"], c["horizon"])])

    def test_f3_subset_starts_at_least_h_plus_one_apart_shared_across_metrics(self):
        lanes = i1.build_universe()
        per_fh = {}
        for family, hs in (("FOMC", (1, 5)), ("OPEC", (1, 5, 20))):
            for h in hs:
                idx = i1.canonical_non_overlapping_windows(
                    lanes[family].cells[h].candidate_indices, h)
                for a, b in zip(idx, idx[1:]):
                    self.assertGreaterEqual(b - a, h + 1)
                per_fh[(family, h)] = len(idx)
        # every metric in a (family,horizon) shares the same decimated N
        seen = {}
        for c in self.res["cells"]:
            key = (c["family"], c["horizon"])
            seen.setdefault(key, set()).add(c["f3_reference_n"])
        for key, ns in seen.items():
            self.assertEqual(ns, {per_fh[key]})

    def test_f3_change_is_decimated_minus_observed(self):
        for c in self.res["cells"]:
            self.assertAlmostEqual(
                c["f3_change"], c["f3_decimated_memp"] - c["observed_memp"])

    def test_f4_is_per_family_horizon(self):
        keys = {(r["family"], r["horizon"]) for r in self.res["f4"]}
        self.assertEqual(keys, {("FOMC", 1), ("FOMC", 5),
                                ("OPEC", 1), ("OPEC", 5), ("OPEC", 20)})
        for r in self.res["f4"]:
            self.assertEqual(len(r["signs"]), 4)
            self.assertEqual(sum(r["sign_counts"].values()), 4)

    def test_f5_is_per_family_metric_feasible_horizons(self):
        for r in self.res["f5"]:
            hs = set(r["signs"])
            if r["family"] == "FOMC":
                self.assertEqual(hs, {1, 5})
            else:
                self.assertEqual(hs, {1, 5, 20})

    def test_f6_positions_match_calibration_percentile(self):
        for c in self.res["cells"]:
            inside = 0.25 <= c["calibration_percentile"] <= 0.75
            self.assertEqual(c["f6_position"],
                             "inside" if inside else "outside")
            self.assertNotIn(c["calibration_percentile"], (0.25, 0.75))

    def test_no_price_gate_called_in_falsifier_loops(self):
        import event_study_validation as esv
        saved = esv.build_event_study_validation

        def _boom(*a, **k):
            raise AssertionError("price gate called inside falsifiers")

        esv.build_event_study_validation = _boom
        try:
            i2f.build_falsifiers(self.sub, self.observed, self.calibration,
                                 expect_frozen=True)
        finally:
            esv.build_event_study_validation = saved

    def test_deterministic_rerun(self):
        again = i2f.build_falsifiers(self.sub, self.observed, self.calibration,
                                     expect_frozen=True)
        self.assertEqual(self.res["cells"], again["cells"])

    def test_no_combined_score_or_threshold_field(self):
        banned = ("score", "grade", "index", "traffic", "weighted",
                  "combined", "fragility", "robustness", "rank", "significan")
        for c in self.res["cells"]:
            for name in c:
                for b in banned:
                    self.assertNotIn(b, name)

    def test_report_lists_all_20_cells_no_winner_framing(self):
        text = i2f.render_report(self.res)
        for c in self.res["cells"]:
            self.assertIn(f"{c['family']} | {c['horizon']}d | {c['metric']}",
                          text)
        low = text.lower()
        for banned in ("validated", "proven", "causal", "predictive",
                       "tradeable", "alpha", "strongest", "winner",
                       "significant", "robust mechanism"):
            self.assertNotIn(banned, low, banned)

    def test_report_has_loyo_and_loeo_appendices(self):
        low = i2f.render_report(self.res).lower()
        self.assertIn("leave-one-year", low)
        self.assertIn("leave-one-event", low)

    def test_tracked_report_matches_regeneration(self):
        artifact = ROOT / "stats" / "I2C_FALSIFIERS.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         i2f.render_report(self.res))


if __name__ == "__main__":
    unittest.main()
