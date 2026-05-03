"""Tests for the enriched rates_pack curve decomposition fields.

Covers: parallel_component_pp, twist_component_pp, driver, magnitude_tier.
No network; all inputs are synthetic.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shock_decomposition import _build_rates_pack, _magnitude_tier, _leg_driver


class TestRatesPackDecomposition(unittest.TestCase):
    """Curve decomposition derived from 10Y and SHY-implied 2Y moves."""

    def test_parallel_and_twist_components_sum_correctly(self):
        """parallel + twist must reconstruct 10Y; parallel − twist must reconstruct 2Y."""
        # SHY −0.2% → twoy_pp ≈ +0.105 (via _SHY_DURATION=1.9, sign inverted)
        pack = _build_rates_pack(tenyr_pp=0.20, shy_pct_5d=-0.2)
        self.assertTrue(pack["available"])
        # Reconstruction identities (within rounding).
        tenyr = pack["tenyr_5d_pp"]
        twoy = pack["twoy_5d_pp"]
        parallel = pack["parallel_component_pp"]
        twist = pack["twist_component_pp"]
        self.assertAlmostEqual(parallel + twist, tenyr, places=2)
        self.assertAlmostEqual(parallel - twist, twoy, places=2)

    def test_unavailable_when_inputs_missing(self):
        pack = _build_rates_pack(tenyr_pp=None, shy_pct_5d=None)
        self.assertFalse(pack["available"])
        self.assertIsNone(pack["slope_5d_pp"])
        self.assertIsNone(pack["parallel_component_pp"])
        self.assertIsNone(pack["twist_component_pp"])
        self.assertEqual(pack["driver"], "unavailable")
        self.assertEqual(pack["magnitude_tier"], "unavailable")

    def test_driver_long_end_when_10y_dominates(self):
        """10Y moves +0.30pp, 2Y essentially flat → driver='long_end'."""
        pack = _build_rates_pack(tenyr_pp=0.30, shy_pct_5d=0.0)
        self.assertEqual(pack["driver"], "long_end")

    def test_driver_short_end_when_2y_dominates(self):
        """SHY −1.0% → twoy ≈ +0.53pp; 10Y quiet → driver='short_end'."""
        pack = _build_rates_pack(tenyr_pp=0.02, shy_pct_5d=-1.0)
        self.assertEqual(pack["driver"], "short_end")

    def test_driver_both_when_legs_comparable(self):
        pack = _build_rates_pack(tenyr_pp=0.25, shy_pct_5d=-0.4)  # 2y ≈ 0.21
        self.assertEqual(pack["driver"], "both")

    def test_driver_flat_when_both_under_floor(self):
        pack = _build_rates_pack(tenyr_pp=0.02, shy_pct_5d=0.05)
        self.assertEqual(pack["driver"], "flat")


class TestMagnitudeTier(unittest.TestCase):
    def test_small_under_slope_floor(self):
        self.assertEqual(_magnitude_tier(0.05), "small")

    def test_medium_between_slope_and_2x_leg(self):
        self.assertEqual(_magnitude_tier(0.15), "medium")

    def test_large_beyond_2x_leg(self):
        self.assertEqual(_magnitude_tier(0.30), "large")

    def test_unavailable_on_none(self):
        self.assertEqual(_magnitude_tier(None), "unavailable")


class TestLegDriver(unittest.TestCase):
    def test_unavailable_on_missing_leg(self):
        self.assertEqual(_leg_driver(None, 0.1), "unavailable")
        self.assertEqual(_leg_driver(0.1, None), "unavailable")


if __name__ == "__main__":
    unittest.main()
