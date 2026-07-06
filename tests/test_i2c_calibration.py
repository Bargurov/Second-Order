"""Tests for Mission I2C-A - the frozen era-matched placement calibration.

Contract under test (I0 protocol i0-v1 section 14; task I2C-A):

* one pseudo-event PLACEMENT reproduces the family's per-year event-count
  vector (on the ANCHOR-SESSION year, the pool basis), drawn WITHOUT
  replacement from that year's eligible ordinary sessions FOR THE GIVEN
  HORIZON (the I1 reference pool, which already excludes real event anchors);
* placements are per (family, horizon); the SAME drawn calendar feeds all 4
  metrics (no per-metric redraw); B = 2,000; fixed seed 20180101;
* the pseudo-MEMP uses the identical section-13 pipeline - each drawn session
  is ranked (self-included, reading A) against the fixed ordinary reference R;
* the observed MEMP's calibration position is its mid-rank percentile within
  the 2,000 placement MEMPs, denominator 2,000, observed EXTERNAL (never the
  (r+1)/(B+1) p-value guard); only the 20 absolute-magnitude MEMPs are
  calibrated - the signed-percentile median is NOT;
* observed I2B denominators are preserved (65/32; 1816/1299; 1903/1631/889);
  no family pooling; no FOMC 20d cell; frozen I2B order; no falsifier fields.

Percentile / tie tests use hand distributions; RNG-determinism and structure
tests use a tiny synthetic substrate; live B=2,000 tests build the I2A
substrate once and skip without the local price cache.
"""
from __future__ import annotations

import random
import statistics
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import i1_candidate_universe as i1  # noqa: E402
from scripts import i2a_response_substrate as i2a  # noqa: E402
from scripts import i2b_memp_primary as i2b  # noqa: E402
from scripts import i2c_calibration as i2c  # noqa: E402

LIVE_DB = i1.default_db_path()
LIVE_READY = LIVE_DB.exists()


# ---------------------------------------------------------------------------
# Observed percentile-of-placements: frozen mid-rank, denominator B, external
# ---------------------------------------------------------------------------


class CalibrationPercentileTests(unittest.TestCase):
    def test_observed_below_all_placements(self):
        self.assertEqual(i2c.calibration_percentile(0.1, [0.2, 0.3, 0.4]), 0.0)

    def test_observed_above_all_placements(self):
        self.assertEqual(i2c.calibration_percentile(0.9, [0.2, 0.3, 0.4]), 1.0)

    def test_single_exact_tie(self):
        # lt=1 (0.2), eq=1 (0.3) -> (1 + 0.5) / 3
        self.assertEqual(i2c.calibration_percentile(0.3, [0.2, 0.3, 0.4]),
                         (1 + 0.5) / 3)

    def test_multiple_duplicate_ties(self):
        self.assertEqual(
            i2c.calibration_percentile(0.3, [0.2, 0.3, 0.3, 0.3, 0.4]),
            (1 + 1.5) / 5)

    def test_all_placements_equal(self):
        self.assertEqual(i2c.calibration_percentile(0.3, [0.3, 0.3, 0.3]), 0.5)
        self.assertEqual(i2c.calibration_percentile(0.9, [0.3, 0.3, 0.3]), 1.0)
        self.assertEqual(i2c.calibration_percentile(0.1, [0.3, 0.3, 0.3]), 0.0)

    def test_denominator_is_B_not_B_plus_one(self):
        # observed is external: a value strictly between all placements sits at
        # (#below)/B, never (#below+1)/(B+1).
        placements = [0.1, 0.2, 0.3, 0.4]
        self.assertEqual(i2c.calibration_percentile(0.25, placements), 2 / 4)

    def test_matches_frozen_i2b_mid_rank(self):
        placements = [0.1, 0.2, 0.2, 0.5, 0.9]
        for obs in (0.05, 0.2, 0.5, 0.95):
            self.assertEqual(
                i2c.calibration_percentile(obs, placements),
                i2b.mid_rank_percentile(obs, placements, absolute=False))


class SelfPercentileTests(unittest.TestCase):
    def test_self_percentiles_match_i2b_absolute_mid_rank(self):
        vals = [-3.0, 1.0, 1.0, -2.0, 5.0, 0.0]
        got = i2c.self_percentiles(vals)
        want = [i2b.mid_rank_percentile(v, vals, absolute=True) for v in vals]
        self.assertEqual(got, want)


# ---------------------------------------------------------------------------
# Tiny synthetic substrate (no price cache): structure + RNG determinism
# ---------------------------------------------------------------------------

_SYN = {"FOMC": {"hs": (1, 5), "ev_per_year": 2},
        "OPEC": {"hs": (1, 5, 20), "ev_per_year": 1}}
_SYN_YEARS = ("2018", "2019")
_SYN_POOL = 8


def _synthetic_substrate():
    recs = []

    def add(family, membership, identity, anchor, h, metric, value):
        recs.append({
            "family": family, "membership": membership, "identity": identity,
            "source_date": anchor, "anchor_session": anchor, "horizon": h,
            "metric": metric, "value": value, "basis": "adjusted",
            "primary_ticker": "X", "benchmark_used": "Y",
            "contract_version": "synthetic", "status": "available",
            "failure_reason": None})

    for family, cfg in _SYN.items():
        base = 0.0 if family == "FOMC" else 100.0
        for h in cfg["hs"]:
            for mi, metric in enumerate(i2a.METRICS):
                for y in _SYN_YEARS:
                    for e in range(cfg["ev_per_year"]):
                        add(family, "event", f"{family}-ev-{y}-{e}",
                            f"{y}-06-0{e + 1}", h, metric,
                            base + mi + e + 0.1 * h)  # event anchors: 06-xx
                    for r in range(_SYN_POOL):
                        add(family, "reference", f"{y}-03-{r + 1:02d}",
                            f"{y}-03-{r + 1:02d}", h, metric,
                            base + mi + 0.3 * r + 0.1 * h)  # pool: 03-xx
    return {"substrate_version": "synthetic", "records": recs,
            "reconciliation": {}}


class SyntheticStructureTests(unittest.TestCase):
    def setUp(self):
        self.res = i2c.build_calibration(_synthetic_substrate(),
                                         expect_frozen=False, b=100)

    def test_exactly_20_cells_no_fomc_20d(self):
        self.assertEqual(len(self.res["cells"]), 20)
        self.assertFalse(any(c["family"] == "FOMC" and c["horizon"] == 20
                             for c in self.res["cells"]))

    def test_cells_in_frozen_i2b_order(self):
        expected = []
        for family, hs in (("FOMC", (1, 5)), ("OPEC", (1, 5, 20))):
            for h in hs:
                for metric in i2a.METRICS:
                    expected.append((family, h, metric))
        self.assertEqual([(c["family"], c["horizon"], c["metric"])
                          for c in self.res["cells"]], expected)

    def test_per_year_event_counts_on_anchor_year(self):
        for (family, h), pl in self.res["placements"].items():
            per_year = pl["per_year_event_counts"]
            ev = _SYN[family]["ev_per_year"]
            self.assertEqual(per_year, {y: ev for y in _SYN_YEARS})

    def test_each_placement_matches_year_counts_without_replacement(self):
        for (family, h), pl in self.res["placements"].items():
            total = sum(pl["per_year_event_counts"].values())
            for sess in pl["sessions"]:
                self.assertEqual(len(sess), total)
                self.assertEqual(len(set(sess)), total)  # no replacement

    def test_no_real_event_anchor_leaks_into_placements(self):
        # every drawn session is a pool (03-xx) date, never an event (06-xx)
        for (family, h), pl in self.res["placements"].items():
            for sess in pl["sessions"]:
                for d in sess:
                    self.assertIn("-03-", d)
                    self.assertNotIn("-06-", d)

    def test_same_calendar_reused_across_all_four_metrics(self):
        for (family, h), pl in self.res["placements"].items():
            self.assertEqual(set(pl["memp"]), set(i2a.METRICS))
            for m in i2a.METRICS:
                self.assertEqual(len(pl["memp"][m]), 100)
            # one shared sessions list, not four
            self.assertEqual(len(pl["sessions"]), 100)

    def test_families_not_pooled(self):
        fomc_ids = {d for (f, h), pl in self.res["placements"].items()
                    if f == "FOMC" for sess in pl["sessions"] for d in sess}
        self.assertTrue(all(not d.startswith("100") for d in fomc_ids))

    def test_schema_has_no_falsifier_fields(self):
        for c in self.res["cells"]:
            self.assertEqual(set(c), set(i2c.CELL_FIELDS))
        banned = ("loyo", "loeo", "leave_one", "decimation", "falsifier",
                  "f1", "f2", "f3", "f6", "sign_flip", "p_value",
                  "significant")
        for name in i2c.CELL_FIELDS:
            for b in banned:
                self.assertNotIn(b, name)


class RngDeterminismTests(unittest.TestCase):
    def test_same_seed_identical(self):
        a = i2c.build_calibration(_synthetic_substrate(), expect_frozen=False,
                                  b=64)
        b = i2c.build_calibration(_synthetic_substrate(), expect_frozen=False,
                                  b=64)
        self.assertEqual(a["cells"], b["cells"])
        for key in a["placements"]:
            self.assertEqual(a["placements"][key]["sessions"],
                             b["placements"][key]["sessions"])
            self.assertEqual(a["placements"][key]["memp"],
                             b["placements"][key]["memp"])

    def test_immune_to_unrelated_global_rng_activity(self):
        base = i2c.build_calibration(_synthetic_substrate(),
                                     expect_frozen=False, b=64)
        np.random.seed(999)
        np.random.random(5000)
        random.seed(12345)
        [random.random() for _ in range(5000)]
        after = i2c.build_calibration(_synthetic_substrate(),
                                      expect_frozen=False, b=64)
        for key in base["placements"]:
            self.assertEqual(base["placements"][key]["sessions"],
                             after["placements"][key]["sessions"])

    def test_different_seed_changes_placements(self):
        a = i2c.build_calibration(_synthetic_substrate(), expect_frozen=False,
                                  b=64, seed=20180101)
        b = i2c.build_calibration(_synthetic_substrate(), expect_frozen=False,
                                  b=64, seed=20180102)
        # at least one (family,horizon) draws a different first calendar
        differ = any(a["placements"][k]["sessions"][0]
                     != b["placements"][k]["sessions"][0]
                     for k in a["placements"])
        self.assertTrue(differ)


# ---------------------------------------------------------------------------
# Live: B=2,000, frozen denominators, byte-identical report
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "local G3 price cache required")
class LiveCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sub = i2a.build_substrate()
        cls.res = i2c.build_calibration(cls.sub, expect_frozen=True)

    def test_seed_and_B(self):
        self.assertEqual(self.res["seed"], 20180101)
        self.assertEqual(self.res["B"], 2000)

    def test_exactly_2000_placements_per_family_horizon(self):
        for (family, h), pl in self.res["placements"].items():
            self.assertEqual(len(pl["sessions"]), 2000)
            for m in i2a.METRICS:
                self.assertEqual(len(pl["memp"][m]), 2000)

    def test_20_cells_no_fomc_20d(self):
        self.assertEqual(len(self.res["cells"]), 20)
        self.assertFalse(any(c["family"] == "FOMC" and c["horizon"] == 20
                             for c in self.res["cells"]))

    def test_observed_denominators_preserved(self):
        exp_ref = {("FOMC", 1): 1816, ("FOMC", 5): 1299,
                   ("OPEC", 1): 1903, ("OPEC", 5): 1631, ("OPEC", 20): 889}
        for c in self.res["cells"]:
            self.assertEqual(c["event_n"],
                             65 if c["family"] == "FOMC" else 32)
            self.assertEqual(c["reference_n"],
                             exp_ref[(c["family"], c["horizon"])])

    def test_per_year_counts_match_real_event_anchor_years(self):
        # FOMC 8/8/9/8/8/8/8/8 = 65; OPEC 2/2/3/3/4/3/5/10 = 32
        fomc = {"2018": 8, "2019": 8, "2020": 9, "2021": 8, "2022": 8,
                "2023": 8, "2024": 8, "2025": 8}
        opec = {"2018": 2, "2019": 2, "2020": 3, "2021": 3, "2022": 4,
                "2023": 3, "2024": 5, "2025": 10}
        for (family, h), pl in self.res["placements"].items():
            want = fomc if family == "FOMC" else opec
            self.assertEqual(pl["per_year_event_counts"], want)
            self.assertEqual(sum(pl["per_year_event_counts"].values()),
                             65 if family == "FOMC" else 32)

    def test_no_real_event_anchor_leaks(self):
        lanes = i1.build_universe()
        for family in ("FOMC", "OPEC"):
            ev_anchors = set(lanes[family].study_event_dates)
            for (f, h), pl in self.res["placements"].items():
                if f != family:
                    continue
                for sess in pl["sessions"]:
                    self.assertEqual(set(sess) & ev_anchors, set())

    def test_calibration_percentiles_in_unit_interval(self):
        for c in self.res["cells"]:
            self.assertTrue(0.0 <= c["calibration_percentile"] <= 1.0)
            # signed median carried for display but NOT calibrated
            self.assertNotIn("signed_calibration_percentile", c)

    def test_report_lists_all_20_cells_in_frozen_order(self):
        text = i2c.render_report(self.res)
        pos = []
        for c in self.res["cells"]:
            label = f"{c['family']} | {c['horizon']}d | {c['metric']}"
            self.assertIn(label, text)
            pos.append(text.index(label))
        self.assertEqual(pos, sorted(pos))

    def test_report_declares_frozen_scope_no_significance(self):
        low = i2c.render_report(self.res).lower()
        self.assertIn("20", low)
        self.assertIn("2,000", i2c.render_report(self.res))
        self.assertIn("20180101", low)
        self.assertIn("no p-value", low)
        for banned in ("strongest", "weakest", "winner", "significant",
                       "robust", "unusual", "confirmed", "validated", "★"):
            self.assertNotIn(banned, low, banned)

    def test_report_states_falsifier_boundary(self):
        low = i2c.render_report(self.res).lower()
        for f in ("loyo", "loeo", "overlap decimation", "cross-metric",
                  "cross-horizon", "central"):
            self.assertIn(f, low)

    def test_tracked_report_matches_regeneration(self):
        artifact = ROOT / "stats" / "I2C_CALIBRATION.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         i2c.render_report(self.res))

    def test_deterministic_rerun_from_same_substrate(self):
        again = i2c.build_calibration(self.sub, expect_frozen=True)
        self.assertEqual(self.res["cells"], again["cells"])


if __name__ == "__main__":
    unittest.main()
