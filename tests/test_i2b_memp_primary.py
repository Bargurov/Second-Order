"""Tests for Mission I2B - the frozen MEMP primary comparison.

Contract under test (I0 protocol i0-v1 section 13; task I2B):

* the magnitude percentile of an event response is the FROZEN mid-rank rule
  pct = (#{|r| < |y|} + 0.5 * #{|r| = |y|}) / |R| against the ordinary
  reference multiset R(F, m, h) of that exact cell;
* MEMP(F, m, h) is the MEDIAN across the family's events of that magnitude
  percentile; the signed-percentile median uses the same mid-rank rule on
  signed values and is a diagnostic beside MEMP, never a replacement;
* the closed family is exactly 20 cells (FOMC x 4 metrics x {1d,5d} +
  OPEC x 4 metrics x {1d,5d,20d}); no FOMC 20d cell; families never pooled;
* denominators reconcile exactly (event 65/32; reference 1816/1299,
  1903/1631/889); the full uncurated per-event surface is 904 rows;
* frozen order only - never sorted by result; no calibration / falsifier /
  significance field or vocabulary anywhere.

Percentile / tie tests use tiny hand-calculated distributions. Live
denominator / 904-row / report tests build the I2A substrate once and are
skipped without the local price cache.
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

LIVE_DB = i1.default_db_path()
LIVE_READY = LIVE_DB.exists()


# ---------------------------------------------------------------------------
# Frozen mid-rank percentile and tie discipline (hand-calculated)
# ---------------------------------------------------------------------------


class MidRankPercentileTests(unittest.TestCase):
    def test_event_below_every_reference(self):
        self.assertEqual(
            i2b.mid_rank_percentile(1.0, [2.0, 3.0, 4.0], absolute=True), 0.0)

    def test_event_above_every_reference(self):
        self.assertEqual(
            i2b.mid_rank_percentile(5.0, [2.0, 3.0, 4.0], absolute=True), 1.0)

    def test_exact_tie_with_one_reference(self):
        # lt = 1 (the 2), eq = 1 (the 3) -> (1 + 0.5) / 3
        self.assertEqual(
            i2b.mid_rank_percentile(3.0, [2.0, 3.0, 4.0], absolute=True),
            (1 + 0.5) / 3)

    def test_tie_with_multiple_duplicate_references(self):
        # lt = 1 (the 2), eq = 3 (the three 3s) -> (1 + 1.5) / 5
        self.assertEqual(
            i2b.mid_rank_percentile(3.0, [2.0, 3.0, 3.0, 3.0, 4.0],
                                    absolute=True),
            (1 + 1.5) / 5)

    def test_all_reference_values_equal(self):
        self.assertEqual(
            i2b.mid_rank_percentile(2.0, [2.0, 2.0, 2.0], absolute=True), 0.5)
        self.assertEqual(
            i2b.mid_rank_percentile(3.0, [2.0, 2.0, 2.0], absolute=True), 1.0)
        self.assertEqual(
            i2b.mid_rank_percentile(1.0, [2.0, 2.0, 2.0], absolute=True), 0.0)

    def test_absolute_and_signed_diverge(self):
        # y = -10 vs ref [-5, -8, 3].
        # absolute: |y|=10 above |ref|=[5,8,3] -> 1.0
        # signed:   -10 below every signed ref -> 0.0
        self.assertEqual(
            i2b.mid_rank_percentile(-10.0, [-5.0, -8.0, 3.0], absolute=True),
            1.0)
        self.assertEqual(
            i2b.mid_rank_percentile(-10.0, [-5.0, -8.0, 3.0], absolute=False),
            0.0)

    def test_signed_midrange_differs_from_absolute(self):
        # y = -6 vs ref [-5, -8, 3]
        # absolute: |y|=6 vs [5,8,3] -> lt {5,3}=2 -> 2/3
        # signed:   -6 vs [-8,-5,3] -> lt {-8}=1 -> 1/3
        self.assertAlmostEqual(
            i2b.mid_rank_percentile(-6.0, [-5.0, -8.0, 3.0], absolute=True),
            2 / 3)
        self.assertAlmostEqual(
            i2b.mid_rank_percentile(-6.0, [-5.0, -8.0, 3.0], absolute=False),
            1 / 3)

    def test_empty_reference_raises(self):
        with self.assertRaises(ValueError):
            i2b.mid_rank_percentile(1.0, [], absolute=True)


class MedianAggregationTests(unittest.TestCase):
    def test_median_is_the_frozen_aggregator(self):
        # odd count -> middle; even count -> mean of the two middle
        self.assertEqual(i2b.memp_of_percentiles([0.1, 0.5, 0.9]), 0.5)
        self.assertEqual(i2b.memp_of_percentiles([0.2, 0.4, 0.6, 0.8]),
                         statistics.median([0.2, 0.4, 0.6, 0.8]))

    def test_memp_is_not_the_mean(self):
        # a skewed set where mean != median, proving we use median
        vals = [0.0, 0.0, 0.0, 0.9]
        self.assertEqual(i2b.memp_of_percentiles(vals), 0.0)
        self.assertNotEqual(i2b.memp_of_percentiles(vals),
                            sum(vals) / len(vals))


# ---------------------------------------------------------------------------
# Structure over a tiny synthetic substrate (no price cache needed)
# ---------------------------------------------------------------------------


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

    fams = {"FOMC": (1, 5), "OPEC": (1, 5, 20)}
    for family, hs in fams.items():
        base = 0.0 if family == "FOMC" else 100.0  # disjoint ranges: no pooling
        for h in hs:
            for mi, metric in enumerate(i2a.METRICS):
                for e in range(3):
                    add(family, "event", f"{family}-ev-{e}",
                        f"2020-01-0{e + 1}", h, metric,
                        base + 1.0 * e + 0.1 * h + mi)
                for rr in range(5):
                    add(family, "reference", f"2019-02-0{rr + 1}",
                        f"2019-02-0{rr + 1}", h, metric,
                        base + 0.5 * rr + 0.1 * h + mi)
    return {"substrate_version": "synthetic", "records": recs,
            "reconciliation": {}}


class SyntheticStructureTests(unittest.TestCase):
    def setUp(self):
        self.res = i2b.build_primary(_synthetic_substrate(), expect_frozen=False)

    def test_exactly_20_cells(self):
        self.assertEqual(len(self.res["cells"]), 20)

    def test_no_fomc_20d_cell(self):
        self.assertFalse(any(c["family"] == "FOMC" and c["horizon"] == 20
                             for c in self.res["cells"]))

    def test_cells_in_frozen_order(self):
        expected = []
        for family, hs in (("FOMC", (1, 5)), ("OPEC", (1, 5, 20))):
            for h in hs:
                for metric in i2a.METRICS:
                    expected.append((family, h, metric))
        actual = [(c["family"], c["horizon"], c["metric"])
                  for c in self.res["cells"]]
        self.assertEqual(actual, expected)

    def test_families_not_pooled(self):
        # FOMC references live in [0..], OPEC in [100..]; a FOMC event never
        # ranks against OPEC values. With disjoint ranges every FOMC event is
        # inside its own family band, never at 100-band extremes.
        for c in self.res["cells"]:
            self.assertEqual(c["event_n"], 3)
            self.assertEqual(c["reference_n"], 5)
        fomc_ids = {r["identity"] for r in self.res["event_percentiles"]
                    if r["family"] == "FOMC"}
        self.assertTrue(all(i.startswith("FOMC") for i in fomc_ids))

    def test_event_percentile_rows_count(self):
        # 3 events x (FOMC 2 + OPEC 3) horizons x 4 metrics
        self.assertEqual(len(self.res["event_percentiles"]),
                         3 * 2 * 4 + 3 * 3 * 4)

    def test_cell_and_row_schema_has_no_outcome_inference_fields(self):
        for c in self.res["cells"]:
            self.assertEqual(set(c), set(i2b.CELL_FIELDS))
        for r in self.res["event_percentiles"]:
            self.assertEqual(set(r), set(i2b.EVENT_PCT_FIELDS))
        banned = ("percentile_of_placements", "calibration", "p_value",
                  "pvalue", "significant", "fdr", "q_value", "rank",
                  "winner", "strongest")
        for name in i2b.CELL_FIELDS + i2b.EVENT_PCT_FIELDS:
            for b in banned:
                self.assertNotIn(b, name)

    def test_event_rows_deterministic_frozen_order(self):
        rows = self.res["event_percentiles"]
        keys = [(("FOMC", "OPEC").index(r["family"]), r["identity"],
                 r["horizon"], i2a.METRICS.index(r["metric"])) for r in rows]
        self.assertEqual(keys, sorted(keys))

    def test_rebuild_is_identical(self):
        again = i2b.build_primary(_synthetic_substrate(), expect_frozen=False)
        self.assertEqual(self.res, again)

    def test_memp_matches_hand_computation_for_one_cell(self):
        # FOMC 1d raw_return: events 0.1,1.1,2.1 vs refs 0.1,0.6,1.1,1.6,2.1
        cell = next(c for c in self.res["cells"]
                    if c["family"] == "FOMC" and c["horizon"] == 1
                    and c["metric"] == "raw_return")
        refs = [0.1, 0.6, 1.1, 1.6, 2.1]
        evs = [0.1, 1.1, 2.1]
        pcts = [i2b.mid_rank_percentile(e, refs, absolute=True) for e in evs]
        self.assertAlmostEqual(cell["memp"], statistics.median(pcts))


# ---------------------------------------------------------------------------
# Live: the frozen denominators, the 904-row surface, and the tracked report
# ---------------------------------------------------------------------------


@unittest.skipUnless(LIVE_READY, "local G3 price cache required")
class LiveMempPrimaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sub = i2a.build_substrate()
        cls.res = i2b.build_primary(cls.sub, expect_frozen=True)

    def test_exactly_20_cells_no_fomc_20d(self):
        self.assertEqual(len(self.res["cells"]), 20)
        self.assertFalse(any(c["family"] == "FOMC" and c["horizon"] == 20
                             for c in self.res["cells"]))

    def test_event_denominators_65_32(self):
        for c in self.res["cells"]:
            self.assertEqual(c["event_n"],
                             65 if c["family"] == "FOMC" else 32,
                             f"{c['family']} {c['horizon']} {c['metric']}")

    def test_reference_denominators_by_horizon(self):
        expected = {("FOMC", 1): 1816, ("FOMC", 5): 1299,
                    ("OPEC", 1): 1903, ("OPEC", 5): 1631, ("OPEC", 20): 889}
        for c in self.res["cells"]:
            self.assertEqual(c["reference_n"],
                             expected[(c["family"], c["horizon"])],
                             f"{c['family']} {c['horizon']} {c['metric']}")

    def test_event_percentile_surface_is_904_rows(self):
        self.assertEqual(len(self.res["event_percentiles"]), 904)

    def test_no_missing_event_percentile(self):
        for r in self.res["event_percentiles"]:
            self.assertIsNotNone(r["abs_percentile"])
            self.assertIsNotNone(r["signed_percentile"])
            self.assertTrue(0.0 <= r["abs_percentile"] <= 1.0)

    def test_opec_register_never_leaks_into_events(self):
        opec_ids = {r["identity"] for r in self.res["event_percentiles"]
                    if r["family"] == "OPEC"}
        self.assertEqual(len(opec_ids), 32)

    def test_every_memp_in_unit_interval(self):
        for c in self.res["cells"]:
            self.assertTrue(0.0 <= c["memp"] <= 1.0)
            self.assertTrue(0.0 <= c["signed_percentile_median"] <= 1.0)

    def test_report_lists_all_20_cells_in_frozen_order(self):
        text = i2b.render_report(self.res)
        # every frozen cell label appears, in order
        order_pos = []
        for c in self.res["cells"]:
            label = f"{c['family']} | {c['horizon']}d | {c['metric']}"
            self.assertIn(label, text)
            order_pos.append(text.index(label))
        self.assertEqual(order_pos, sorted(order_pos))

    def test_report_has_no_winner_or_significance_framing(self):
        low = i2b.render_report(self.res).lower()
        for banned in ("strongest", "weakest", "winner", "significant",
                       "robust", "unusual", "surprising", "confirmed",
                       "validated", "mechanism-consistent", "p-value",
                       "p value", "★", "🌟"):
            if banned in ("p-value", "p value"):
                continue  # allowed only inside the explicit non-claim
            self.assertNotIn(banned, low, banned)

    def test_report_states_multiplicity_disclosure(self):
        low = i2b.render_report(self.res).lower()
        self.assertIn("20 primary", low)
        self.assertIn("no p-value", low)
        self.assertIn("calibration", low)  # deferred-to-I2C mention

    def test_tracked_report_matches_regeneration(self):
        artifact = ROOT / "stats" / "I2B_MEMP_PRIMARY_COMPARISON.md"
        if not artifact.exists():
            self.skipTest("report not yet generated")
        self.assertEqual(artifact.read_text(encoding="utf-8"),
                         i2b.render_report(self.res))


if __name__ == "__main__":
    unittest.main()
