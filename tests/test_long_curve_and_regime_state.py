"""Tests for 5s30s decomposition + combined regime-state output.

Covers:
  - _classify_long_curve_shape: bull/bear steepener/flattener for the long end
  - _classify_regime_state: combined 2s10s + 5s30s label
  - _regime_class: level/curve/partial/quiet summary
  - _build_rates_pack: emits both sections + combined read with stable shape
  - compute_rates_context surfaces 5Y (mid_nominal) and 30Y (long_nominal)
    fields so shock_decomposition can pick them up
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shock_decomposition import (
    _build_rates_pack,
    _classify_long_curve_shape,
    _classify_regime_state,
    _regime_class,
    _REGIME_STATE_LABELS,
)


class TestClassifyLongCurveShape(unittest.TestCase):
    """5s30s classifier mirrors 2s10s behaviour."""

    def test_unavailable_when_either_missing(self):
        self.assertEqual(_classify_long_curve_shape(None, 0.1), "unavailable")
        self.assertEqual(_classify_long_curve_shape(0.1, None), "unavailable")

    def test_flat_when_both_legs_quiet(self):
        self.assertEqual(_classify_long_curve_shape(0.02, 0.03), "flat")

    def test_bear_steepener_when_slope_widens_and_rates_up(self):
        self.assertEqual(_classify_long_curve_shape(0.40, 0.15), "bear_steepener")

    def test_bull_flattener_when_slope_narrows_and_rates_down(self):
        # long rates fall MORE than short rates: 5Y −0.10, 30Y −0.40
        # → long_slope = 30Y − 5Y = −0.30 (flattening); 30Y leg down (bull)
        self.assertEqual(_classify_long_curve_shape(-0.40, -0.10), "bull_flattener")

    def test_parallel_up_when_slope_quiet_and_legs_positive(self):
        self.assertEqual(_classify_long_curve_shape(0.25, 0.22), "parallel_up")

    def test_parallel_down_when_slope_quiet_and_legs_negative(self):
        self.assertEqual(_classify_long_curve_shape(-0.25, -0.22), "parallel_down")


class TestClassifyRegimeState(unittest.TestCase):
    """Combined regime state across both curve sections."""

    def test_unavailable_when_both_sections_missing(self):
        self.assertEqual(_classify_regime_state(None, None, None, None),
                         "unavailable")

    def test_flat_quiet_when_no_leg_meaningful(self):
        # All legs below _CURVE_LEG_FLOOR = 0.10
        self.assertEqual(
            _classify_regime_state(0.03, 0.04, 0.02, 0.05),
            "flat_quiet",
        )

    def test_parallel_shift_up_when_all_tenors_rising_in_tandem(self):
        # Short slope (10Y − 2Y) and long slope (30Y − 5Y) both quiet; legs up
        res = _classify_regime_state(twoy_pp=0.22, tenyr_pp=0.24,
                                     fiveyr_pp=0.23, thirtyyr_pp=0.25)
        self.assertEqual(res, "parallel_shift_up")
        self.assertEqual(_regime_class(res), "level_move")

    def test_parallel_shift_down_when_all_tenors_falling_in_tandem(self):
        res = _classify_regime_state(twoy_pp=-0.22, tenyr_pp=-0.24,
                                     fiveyr_pp=-0.23, thirtyyr_pp=-0.25)
        self.assertEqual(res, "parallel_shift_down")
        self.assertEqual(_regime_class(res), "level_move")

    def test_bear_steepener_whole_when_both_sections_steepen_rates_up(self):
        # 2s10s slope +0.30 (10Y up more than 2Y), 5s30s slope +0.30
        res = _classify_regime_state(twoy_pp=0.10, tenyr_pp=0.40,
                                     fiveyr_pp=0.15, thirtyyr_pp=0.45)
        self.assertEqual(res, "bear_steepener_whole")
        self.assertEqual(_regime_class(res), "curve_move")

    def test_bull_flattener_whole_when_both_sections_flatten_rates_down(self):
        # 2s10s slope negative (10Y falls more), 5s30s slope negative too
        res = _classify_regime_state(twoy_pp=-0.05, tenyr_pp=-0.35,
                                     fiveyr_pp=-0.10, thirtyyr_pp=-0.40)
        self.assertEqual(res, "bull_flattener_whole")
        self.assertEqual(_regime_class(res), "curve_move")

    def test_twist_when_short_steepens_and_long_flattens(self):
        res = _classify_regime_state(twoy_pp=-0.05, tenyr_pp=0.25,
                                     fiveyr_pp=0.30, thirtyyr_pp=0.00)
        self.assertEqual(res, "twist_short_steep_long_flat")
        self.assertEqual(_regime_class(res), "curve_move")

    def test_long_end_driven_when_front_quiet_but_long_moves(self):
        # 2s10s parallel (both quiet); 5s30s steepening
        res = _classify_regime_state(twoy_pp=0.03, tenyr_pp=0.04,
                                     fiveyr_pp=0.05, thirtyyr_pp=0.35)
        self.assertEqual(res, "long_end_driven")
        self.assertEqual(_regime_class(res), "partial")

    def test_short_end_driven_when_long_quiet_but_short_moves(self):
        res = _classify_regime_state(twoy_pp=-0.30, tenyr_pp=0.05,
                                     fiveyr_pp=0.02, thirtyyr_pp=0.03)
        self.assertEqual(res, "short_end_driven")
        self.assertEqual(_regime_class(res), "partial")

    def test_degrades_gracefully_when_only_long_section_available(self):
        res = _classify_regime_state(twoy_pp=None, tenyr_pp=None,
                                     fiveyr_pp=0.15, thirtyyr_pp=0.40)
        self.assertEqual(res, "long_end_driven")

    def test_degrades_gracefully_when_only_short_section_available(self):
        res = _classify_regime_state(twoy_pp=-0.10, tenyr_pp=-0.35,
                                     fiveyr_pp=None, thirtyyr_pp=None)
        # Slope widens downward = short section classified alone as short-end driven
        self.assertEqual(res, "short_end_driven")

    def test_every_state_has_a_label(self):
        for state in _REGIME_STATE_LABELS:
            self.assertTrue(_REGIME_STATE_LABELS[state])

    def test_regime_class_domain_is_constrained(self):
        valid = {"level_move", "curve_move", "partial",
                 "flat_quiet", "mixed", "unavailable"}
        for state in _REGIME_STATE_LABELS:
            self.assertIn(_regime_class(state), valid)


class TestBuildRatesPackWithLongEnd(unittest.TestCase):
    """_build_rates_pack accepts optional 5Y/30Y and emits the full fields."""

    def test_short_only_keeps_long_fields_none(self):
        pack = _build_rates_pack(tenyr_pp=0.20, shy_pct_5d=-0.2)
        self.assertIsNotNone(pack["tenyr_5d_pp"])
        self.assertIsNone(pack["fiveyr_5d_pp"])
        self.assertIsNone(pack["thirtyyr_5d_pp"])
        self.assertIsNone(pack["long_slope_5d_pp"])
        self.assertEqual(pack["long_curve_shape"], "unavailable")
        # regime_state should still classify from the short section.
        self.assertIn(pack["regime_state"], _REGIME_STATE_LABELS)

    def test_full_pack_with_long_end(self):
        pack = _build_rates_pack(
            tenyr_pp=0.30, shy_pct_5d=-0.2,  # 2Y ~+0.105pp
            fiveyr_pp=0.20, thirtyyr_pp=0.35,
        )
        self.assertAlmostEqual(pack["long_slope_5d_pp"], 0.15, places=2)
        self.assertEqual(pack["long_curve_shape"], "bear_steepener")
        self.assertAlmostEqual(pack["long_parallel_component_pp"], 0.275, places=2)
        self.assertAlmostEqual(pack["long_twist_component_pp"], 0.075, places=2)
        self.assertIn(pack["regime_state"], _REGIME_STATE_LABELS)
        self.assertIn(pack["regime_class"],
                      ("level_move", "curve_move", "partial", "mixed"))

    def test_payload_shape_stable_even_when_everything_missing(self):
        pack = _build_rates_pack(tenyr_pp=None, shy_pct_5d=None,
                                 fiveyr_pp=None, thirtyyr_pp=None)
        # Every documented field must be present with a stable None / unavailable.
        for key in ("tenyr_5d_pp", "twoy_5d_pp", "slope_5d_pp",
                    "fiveyr_5d_pp", "thirtyyr_5d_pp", "long_slope_5d_pp"):
            self.assertIsNone(pack[key])
        self.assertEqual(pack["curve_shape"], "unavailable")
        self.assertEqual(pack["long_curve_shape"], "unavailable")
        self.assertEqual(pack["regime_state"], "unavailable")
        self.assertEqual(pack["regime_class"], "unavailable")


class TestRatesContextSurfacesNewTenors(unittest.TestCase):
    """compute_rates_context emits 5Y (mid_nominal) and 30Y (long_nominal) blocks."""

    def test_mid_and_long_nominal_keys_present_even_on_empty_fetch(self):
        """When ^FVX / ^TYX are unavailable, the keys still exist with None values."""
        import market_check

        # Patch _fetch so everything returns None — rates_context should still
        # emit mid_nominal / long_nominal blocks with None change_5d.
        with patch.object(market_check, "_fetch", return_value=None):
            ctx = market_check.compute_rates_context()

        self.assertIn("mid_nominal", ctx)
        self.assertIn("long_nominal", ctx)
        self.assertIsNone(ctx["mid_nominal"]["change_5d"])
        self.assertIsNone(ctx["long_nominal"]["change_5d"])
        self.assertEqual(ctx["mid_nominal"]["label"], "5Y yield")
        self.assertEqual(ctx["long_nominal"]["label"], "30Y yield")


if __name__ == "__main__":
    unittest.main()
