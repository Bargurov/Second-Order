"""
tests/test_breakeven_curve.py

Validates the breakeven-curve decomposition + inflation-path classifier.
Coverage:
  - Per-tenor Fisher decomposition (nominal − real = breakeven) behaviour
  - Short-end vs long-end aggregation
  - Shape classifier at every band (front_loaded, term_premium_like,
    parallel_up/down, twist, flat, unavailable)
  - Threshold edge cases (_TENOR_NOISE_PP, _SHAPE_GAP_FLOOR_PP,
    _PARALLEL_BAND_PP)
  - Policy-space interpretation per shape and sign
  - TIPS ETF % → real-yield pp helper (duration inversion)
  - Degradation paths (all None, partial tenors)
  - Integration with compute_rates_context + shock_decomposition
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from breakeven_curve import (  # noqa: E402
    compute_breakeven_curve,
    real_pp_from_tips_pct,
    TENORS,
    _TIPS_DURATION_BY_TENOR,
    _TENOR_NOISE_PP,
    _SHAPE_GAP_FLOOR_PP,
    _PARALLEL_BAND_PP,
    _POLICY_FRONT_MAG_PP,
    _POLICY_LONG_MAG_PP,
    _SHAPE_LABEL,
)


# ---------------------------------------------------------------------------
# Per-tenor Fisher decomposition
# ---------------------------------------------------------------------------

class TestTenorDecomposition(unittest.TestCase):

    def test_all_tenors_present_when_inputs_supplied(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={"2Y": 0.10, "5Y": 0.08, "10Y": 0.05, "30Y": 0.02},
            real_5d_pp={"2Y": 0.02, "5Y": 0.01, "10Y": 0.00, "30Y": -0.01},
        )
        for t in TENORS:
            self.assertIn(t, result["tenors"])
            self.assertTrue(result["tenors"][t]["available"])

    def test_fisher_decomposition_nominal_minus_real(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={"10Y": 0.30},
            real_5d_pp={"10Y": 0.10},
        )
        self.assertAlmostEqual(
            result["tenors"]["10Y"]["breakeven_5d_pp"], 0.20, places=3,
        )

    def test_missing_real_marks_tenor_unavailable(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={"10Y": 0.10}, real_5d_pp={},
        )
        t10 = result["tenors"]["10Y"]
        self.assertFalse(t10["available"])
        self.assertIsNone(t10["breakeven_5d_pp"])

    def test_missing_nominal_marks_tenor_unavailable(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={}, real_5d_pp={"10Y": 0.05},
        )
        self.assertFalse(result["tenors"]["10Y"]["available"])


# ---------------------------------------------------------------------------
# Shape classifier
# ---------------------------------------------------------------------------

def _curve(short_be: float, long_be: float) -> dict:
    """Construct a breakeven curve with controlled short/long breakevens.

    Sets nominal at each tenor and zero real yield so breakeven == nominal.
    """
    return compute_breakeven_curve(
        nominal_5d_pp={"2Y": short_be, "5Y": short_be,
                       "10Y": long_be, "30Y": long_be},
        real_5d_pp={t: 0.0 for t in TENORS},
    )


class TestShapeClassifier(unittest.TestCase):

    def test_front_loaded_short_bigger_than_long(self):
        # Short breakevens +0.25, long +0.05 → gap 0.20 > 0.08 floor
        result = _curve(short_be=0.25, long_be=0.05)
        self.assertEqual(result["shape"], "front_loaded")

    def test_term_premium_like_long_bigger_than_short(self):
        result = _curve(short_be=0.05, long_be=0.25)
        self.assertEqual(result["shape"], "term_premium_like")

    def test_parallel_up_both_rising_similar(self):
        result = _curve(short_be=0.15, long_be=0.17)
        self.assertEqual(result["shape"], "parallel_up")

    def test_parallel_down_both_falling_similar(self):
        result = _curve(short_be=-0.15, long_be=-0.13)
        self.assertEqual(result["shape"], "parallel_down")

    def test_twist_opposing_signs(self):
        # Short up + long down, both clear opposing floor
        result = _curve(short_be=0.15, long_be=-0.12)
        self.assertEqual(result["shape"], "twist")

    def test_flat_both_sub_noise(self):
        result = _curve(short_be=0.02, long_be=-0.03)
        self.assertEqual(result["shape"], "flat")

    def test_unavailable_when_no_data(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={}, real_5d_pp={},
        )
        self.assertEqual(result["shape"], "unavailable")


class TestShapeEdgeCases(unittest.TestCase):

    def test_gap_at_parallel_band_edge_is_parallel(self):
        # Gap exactly at parallel band → parallel (strict <)
        gap = _PARALLEL_BAND_PP - 0.001
        result = _curve(short_be=0.15, long_be=0.15 - gap)
        self.assertIn(result["shape"], ("parallel_up", "parallel_down"))

    def test_gap_at_shape_floor_is_front_loaded(self):
        # Gap ≥ _SHAPE_GAP_FLOOR_PP → front_loaded
        gap = _SHAPE_GAP_FLOOR_PP + 0.001
        result = _curve(short_be=0.15, long_be=0.15 - gap)
        self.assertEqual(result["shape"], "front_loaded")


# ---------------------------------------------------------------------------
# Policy-space interpretation
# ---------------------------------------------------------------------------

class TestPolicySpace(unittest.TestCase):

    def test_front_loaded_up_is_narrow_hawkish(self):
        result = _curve(short_be=0.20, long_be=0.05)
        self.assertEqual(result["shape"], "front_loaded")
        self.assertEqual(result["policy_space"], "narrow_hawkish")

    def test_front_loaded_down_is_ease_room(self):
        result = _curve(short_be=-0.20, long_be=-0.05)
        self.assertEqual(result["shape"], "front_loaded")
        self.assertEqual(result["policy_space"], "ease_room")

    def test_term_premium_up_is_look_through(self):
        result = _curve(short_be=0.05, long_be=0.25)
        self.assertEqual(result["policy_space"], "look_through")

    def test_term_premium_down_is_behind_the_curve(self):
        result = _curve(short_be=-0.05, long_be=-0.25)
        self.assertEqual(result["policy_space"], "behind_the_curve")

    def test_twist_short_up_long_down_is_behind_the_curve(self):
        result = _curve(short_be=0.15, long_be=-0.12)
        self.assertEqual(result["shape"], "twist")
        self.assertEqual(result["policy_space"], "behind_the_curve")

    def test_twist_short_down_long_up_is_look_through(self):
        result = _curve(short_be=-0.12, long_be=0.15)
        self.assertEqual(result["shape"], "twist")
        self.assertEqual(result["policy_space"], "look_through")

    def test_parallel_up_broad_hawkish(self):
        result = _curve(short_be=0.20, long_be=0.22)
        self.assertEqual(result["policy_space"], "narrow_hawkish")

    def test_parallel_down_broad_ease(self):
        result = _curve(short_be=-0.20, long_be=-0.22)
        self.assertEqual(result["policy_space"], "ease_room")

    def test_flat_is_neutral(self):
        result = _curve(short_be=0.02, long_be=0.02)
        self.assertEqual(result["policy_space"], "neutral")


# ---------------------------------------------------------------------------
# TIPS ETF → real-yield pp helper
# ---------------------------------------------------------------------------

class TestRealPpFromTipsPct(unittest.TestCase):

    def test_tip_fall_produces_real_yield_rise(self):
        # TIP price -1% / 5d → real yield up ~ 1/7.5 = +0.133 pp
        out = real_pp_from_tips_pct(tip_pct_5d=-1.0)
        expected = 1.0 / _TIPS_DURATION_BY_TENOR["10Y"]
        self.assertAlmostEqual(out["10Y"], expected, places=3)

    def test_tip_rise_produces_real_yield_fall(self):
        out = real_pp_from_tips_pct(tip_pct_5d=+1.0)
        expected = -1.0 / _TIPS_DURATION_BY_TENOR["10Y"]
        self.assertAlmostEqual(out["10Y"], expected, places=3)

    def test_stip_drives_short_end_tenors(self):
        out = real_pp_from_tips_pct(stip_pct_5d=-0.5)
        self.assertAlmostEqual(
            out["2Y"], 0.5 / _TIPS_DURATION_BY_TENOR["2Y"], places=3,
        )
        self.assertAlmostEqual(
            out["5Y"], 0.5 / _TIPS_DURATION_BY_TENOR["5Y"], places=3,
        )

    def test_ltpz_drives_30y(self):
        out = real_pp_from_tips_pct(ltpz_pct_5d=-2.0)
        self.assertAlmostEqual(
            out["30Y"], 2.0 / _TIPS_DURATION_BY_TENOR["30Y"], places=3,
        )

    def test_mid_tips_override_preferred_over_stip(self):
        # When mid_tips_pct_5d is supplied, 5Y uses it instead of STIP.
        out = real_pp_from_tips_pct(stip_pct_5d=-0.5, mid_tips_pct_5d=-1.0)
        expected = 1.0 / _TIPS_DURATION_BY_TENOR["5Y"]
        self.assertAlmostEqual(out["5Y"], expected, places=3)

    def test_none_inputs_return_none(self):
        out = real_pp_from_tips_pct()
        for t in TENORS:
            self.assertIsNone(out[t])


# ---------------------------------------------------------------------------
# Aggregates + degradation paths
# ---------------------------------------------------------------------------

class TestAggregates(unittest.TestCase):

    def test_short_end_and_long_end_averaged(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={"2Y": 0.20, "5Y": 0.30, "10Y": 0.08, "30Y": 0.06},
            real_5d_pp={t: 0.0 for t in TENORS},
        )
        self.assertAlmostEqual(result["short_end_be_5d"], 0.25, places=3)
        self.assertAlmostEqual(result["long_end_be_5d"], 0.07, places=3)
        self.assertAlmostEqual(result["shape_change_5d"], -0.18, places=3)

    def test_single_tenor_missing_does_not_drop_aggregate(self):
        # Only 5Y (short) + 10Y (long) available — still compose aggregates.
        result = compute_breakeven_curve(
            nominal_5d_pp={"5Y": 0.30, "10Y": 0.10},
            real_5d_pp={"5Y": 0.00, "10Y": 0.00},
        )
        self.assertAlmostEqual(result["short_end_be_5d"], 0.30, places=3)
        self.assertAlmostEqual(result["long_end_be_5d"], 0.10, places=3)

    def test_one_side_only_yields_unavailable_shape(self):
        # Short-end populated, long-end totally missing → shape unavailable.
        result = compute_breakeven_curve(
            nominal_5d_pp={"2Y": 0.20, "5Y": 0.20},
            real_5d_pp={"2Y": 0.0, "5Y": 0.0},
        )
        self.assertEqual(result["shape"], "unavailable")
        self.assertEqual(result["policy_space"], "unavailable")
        self.assertIsNone(result["long_end_be_5d"])

    def test_empty_inputs_return_shape_unavailable(self):
        result = compute_breakeven_curve(
            nominal_5d_pp={}, real_5d_pp={},
        )
        self.assertEqual(result["shape"], "unavailable")
        self.assertEqual(result["policy_space"], "unavailable")
        self.assertIsNone(result["shape_change_5d"])


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------

class TestOutputContract(unittest.TestCase):

    def test_block_always_has_required_fields(self):
        result = compute_breakeven_curve({}, {})
        for key in (
            "available", "stale", "tenors",
            "short_end_be_5d", "long_end_be_5d", "shape_change_5d",
            "shape", "shape_label", "policy_space", "policy_label",
            "rationale",
        ):
            self.assertIn(key, result, f"missing field: {key}")

    def test_shape_label_matches_shape(self):
        result = _curve(short_be=0.25, long_be=0.05)
        self.assertEqual(result["shape_label"],
                         _SHAPE_LABEL[result["shape"]])


# ---------------------------------------------------------------------------
# Integration with shock_decomposition
# ---------------------------------------------------------------------------

class TestShockDecompositionIntegration(unittest.TestCase):

    def test_breakeven_curve_propagates_from_rates_context(self):
        from shock_decomposition import compute_shock_decomposition

        rates_context = {
            "regime": "Inflation pressure",
            "nominal": {"label": "10Y", "value": 4.0, "change_5d": 0.30},
            "real_proxy": {"label": "TIP", "value": 108, "change_5d": -0.40},
            "breakeven_proxy": {"change_5d": 0.25},
            "raw": {},
            "breakeven_curve": compute_breakeven_curve(
                nominal_5d_pp={"2Y": 0.25, "5Y": 0.22,
                               "10Y": 0.08, "30Y": 0.05},
                real_5d_pp={t: 0.0 for t in TENORS},
            ),
        }
        result = compute_shock_decomposition(
            rates_context=rates_context,
            stress_regime=None,
            snapshots=None,
        )
        self.assertIn("breakeven_curve", result)
        self.assertEqual(result["breakeven_curve"]["shape"], "front_loaded")
        self.assertEqual(result["breakeven_curve"]["policy_space"],
                         "narrow_hawkish")

    def test_missing_breakeven_curve_degrades_cleanly(self):
        from shock_decomposition import compute_shock_decomposition

        rates_context = {
            "regime": "Mixed",
            "nominal": {"change_5d": 0.10},
            "real_proxy": {"change_5d": 0.0},
            "breakeven_proxy": {"change_5d": 0.0},
            "raw": {},
            # breakeven_curve intentionally missing
        }
        result = compute_shock_decomposition(
            rates_context=rates_context,
            stress_regime=None,
            snapshots=None,
        )
        # Passthrough should still expose the field (as empty dict) so
        # downstream consumers don't need to branch on its presence.
        self.assertIn("breakeven_curve", result)
        self.assertEqual(result["breakeven_curve"], {})


if __name__ == "__main__":
    unittest.main()
