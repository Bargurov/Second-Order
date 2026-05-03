"""
tests/test_curve_shape.py

Validates the curve-shape classifier + rates_pack field added to
shock_decomposition.  Representative cases for every shape label plus
threshold edge cases.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shock_decomposition import (  # noqa: E402
    _classify_curve_shape,
    _twoy_change_pp_from_shy,
    _build_rates_pack,
    _CURVE_LEG_FLOOR,
    _CURVE_SLOPE_FLOOR,
    _SHY_DURATION,
    compute_shock_decomposition,
)


def _rates(nominal_5d=None, real_5d=None, breakeven_5d=None, regime="Mixed"):
    return {
        "regime": regime,
        "nominal": {"label": "10Y yield", "value": 4.25, "change_5d": nominal_5d},
        "real_proxy": {"label": "TIP", "value": 108.5, "change_5d": real_5d},
        "breakeven_proxy": {"label": "BE proxy", "change_5d": breakeven_5d},
        "raw": {"^TNX": 4.25, "TIP": 108.5},
    }


def _stress_with_shy(shy_5d):
    return {
        "regime": "Calm",
        "signals": {},
        "raw": {"shy_5d": shy_5d, "vix": 17.0},
        "detail": {"safe_haven": {"assets": {}}},
    }


class TestShyDurationProxy(unittest.TestCase):

    def test_shy_up_means_twoy_yield_down(self):
        # SHY +1% → 2Y yield ≈ -1/1.9 = -0.53 pp
        twoy = _twoy_change_pp_from_shy(1.0)
        self.assertAlmostEqual(twoy, -1.0 / _SHY_DURATION, places=3)
        self.assertLess(twoy, 0)

    def test_shy_down_means_twoy_yield_up(self):
        twoy = _twoy_change_pp_from_shy(-0.8)
        self.assertAlmostEqual(twoy, 0.8 / _SHY_DURATION, places=3)
        self.assertGreater(twoy, 0)

    def test_none_passes_through(self):
        self.assertIsNone(_twoy_change_pp_from_shy(None))


class TestCurveShapeClassification(unittest.TestCase):

    def test_bear_steepener_long_end_leads(self):
        # 10Y +0.30, 2Y +0.05 → slope widens 0.25, both up
        shape = _classify_curve_shape(0.30, 0.05)
        self.assertEqual(shape, "bear_steepener")

    def test_bull_steepener_front_end_leads_down(self):
        # 10Y -0.05, 2Y -0.30 → slope widens 0.25, both down
        shape = _classify_curve_shape(-0.05, -0.30)
        self.assertEqual(shape, "bull_steepener")

    def test_bear_flattener_front_end_rises_faster(self):
        # 10Y +0.05, 2Y +0.30 → slope narrows -0.25, both up
        shape = _classify_curve_shape(0.05, 0.30)
        self.assertEqual(shape, "bear_flattener")

    def test_bull_flattener_long_end_falls_faster(self):
        # 10Y -0.30, 2Y -0.05 → slope narrows -0.25, both down
        shape = _classify_curve_shape(-0.30, -0.05)
        self.assertEqual(shape, "bull_flattener")

    def test_parallel_up_legs_move_together_up(self):
        # Both +0.20, slope change ~0 → parallel
        shape = _classify_curve_shape(0.20, 0.18)
        self.assertEqual(shape, "parallel_up")

    def test_parallel_down_legs_move_together_down(self):
        shape = _classify_curve_shape(-0.22, -0.20)
        self.assertEqual(shape, "parallel_down")

    def test_flat_when_both_legs_below_noise(self):
        shape = _classify_curve_shape(0.05, -0.04)
        self.assertEqual(shape, "flat")

    def test_unavailable_when_either_leg_missing(self):
        self.assertEqual(_classify_curve_shape(None, 0.2), "unavailable")
        self.assertEqual(_classify_curve_shape(0.2, None), "unavailable")
        self.assertEqual(_classify_curve_shape(None, None), "unavailable")


class TestCurveShapeThresholds(unittest.TestCase):
    """Threshold contract: validate that the documented cutoffs behave as claimed."""

    def test_leg_floor_exactly_at_boundary_still_flat(self):
        # Both legs exactly at floor → still classified as flat (strict <).
        val = _CURVE_LEG_FLOOR - 0.001
        self.assertEqual(_classify_curve_shape(val, val), "flat")

    def test_leg_floor_just_over_flips_to_parallel(self):
        val = _CURVE_LEG_FLOOR + 0.001
        # Move just over floor with tiny slope diff → parallel.
        self.assertEqual(_classify_curve_shape(val, val), "parallel_up")

    def test_slope_floor_edge_case_parallel(self):
        # Slope change exactly at the slope floor → still parallel.
        # tenyr=0.20, twoy=0.20 - _CURVE_SLOPE_FLOOR + tiny  → diff < floor
        twoy = 0.20 - _CURVE_SLOPE_FLOOR + 0.001
        self.assertEqual(_classify_curve_shape(0.20, twoy), "parallel_up")

    def test_slope_floor_just_over_flips_to_steepener(self):
        twoy = 0.20 - _CURVE_SLOPE_FLOOR - 0.001
        self.assertEqual(_classify_curve_shape(0.20, twoy), "bear_steepener")


class TestRatesPackBuild(unittest.TestCase):

    def test_pack_exposes_all_fields(self):
        pack = _build_rates_pack(0.30, -1.0)  # 10Y +30bps, SHY -1% → 2Y +0.53
        self.assertEqual(pack["tenyr_5d_pp"], 0.30)
        self.assertAlmostEqual(pack["twoy_5d_pp"], 1.0 / _SHY_DURATION, places=3)
        self.assertTrue(pack["available"])
        self.assertEqual(pack["curve_shape"], "bear_flattener")

    def test_pack_available_false_when_inputs_missing(self):
        pack = _build_rates_pack(None, -1.0)
        self.assertFalse(pack["available"])
        self.assertEqual(pack["curve_shape"], "unavailable")


class TestShockDecompositionRatesPackIntegration(unittest.TestCase):

    def test_rates_pack_present_when_shy_in_stress_raw(self):
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.35, real_5d=-0.5, breakeven_5d=0.3),
            stress_regime=_stress_with_shy(shy_5d=-0.8),
            snapshots=None,
        )
        pack = result.get("rates_pack")
        self.assertIsNotNone(pack)
        self.assertTrue(pack["available"])
        self.assertEqual(pack["tenyr_5d_pp"], 0.35)
        self.assertIn(pack["curve_shape"],
                      ("bear_steepener", "bear_flattener", "parallel_up"))

    def test_rates_pack_from_snapshot_2y(self):
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=-0.30),
            stress_regime=None,
            snapshots=[{"market": "2Y", "symbol": "SHY",
                        "value": 82.0, "change_5d": 0.4, "error": None}],
        )
        pack = result["rates_pack"]
        # 10Y -0.30, SHY +0.4 → 2Y ≈ -0.21 pp → bull_flattener (10Y fell more)
        self.assertEqual(pack["curve_shape"], "bull_flattener")

    def test_rates_pack_unavailable_when_no_2y_input(self):
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.30),
            stress_regime={"regime": "Calm", "signals": {},
                           "raw": {"vix": 15}, "detail": {"safe_haven": {"assets": {}}}},
            snapshots=None,
        )
        pack = result["rates_pack"]
        self.assertFalse(pack["available"])
        self.assertEqual(pack["curve_shape"], "unavailable")


if __name__ == "__main__":
    unittest.main()
