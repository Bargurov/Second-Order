"""
tests/test_cross_rate_fx.py

Validates the cross-rate FX composer — sign convention, bucket boundaries,
regional stress tagging, driver decomposition, dispersion classifier,
carry-unwind fingerprint, and DXY-only fallback.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cross_rate_fx import (  # noqa: E402
    compute_cross_rate_fx,
    _usd_strength,
    _bucket,
    _dispersion,
    _driver,
    _PAIR_FLOOR_PP,
    _PAIR_MODERATE_PP,
    _PAIR_STRONG_PP,
    _PAIR_EXTREME_PP,
    _DISPERSION_UNIFORM,
    _DISPERSION_MIXED,
    _DRIVER_DOMINANCE_PP,
    _CARRY_UNWIND_RISK_PP,
    _CARRY_UNWIND_SAFE_PP,
    PAIR_IDS,
)


# ---------------------------------------------------------------------------
# Sign convention: normalize every pair to USD-strength
# ---------------------------------------------------------------------------

class TestUSDStrengthNormalization(unittest.TestCase):

    def test_eurusd_sign_flipped(self):
        # EURUSD falls when dollar strengthens → flip sign
        self.assertAlmostEqual(_usd_strength("EURUSD", -1.5), 1.5)
        self.assertAlmostEqual(_usd_strength("EURUSD", 0.8), -0.8)

    def test_usdjpy_sign_preserved(self):
        self.assertAlmostEqual(_usd_strength("USDJPY", 1.5), 1.5)
        self.assertAlmostEqual(_usd_strength("USDJPY", -0.8), -0.8)

    def test_usdcny_sign_preserved(self):
        self.assertAlmostEqual(_usd_strength("USDCNY", 0.7), 0.7)

    def test_none_passes_through(self):
        self.assertIsNone(_usd_strength("EURUSD", None))


# ---------------------------------------------------------------------------
# Bucket boundaries
# ---------------------------------------------------------------------------

class TestBucketClassifier(unittest.TestCase):

    def test_flat_just_below_floor(self):
        self.assertEqual(_bucket(_PAIR_FLOOR_PP - 0.001), "flat")

    def test_moderate_at_floor(self):
        self.assertEqual(_bucket(_PAIR_FLOOR_PP + 0.001), "moderate")

    def test_strong_at_moderate_ceiling(self):
        self.assertEqual(_bucket(_PAIR_MODERATE_PP + 0.001), "strong")

    def test_very_strong_at_strong_ceiling(self):
        self.assertEqual(_bucket(_PAIR_STRONG_PP + 0.001), "very_strong")

    def test_extreme_at_extreme_floor(self):
        self.assertEqual(_bucket(_PAIR_EXTREME_PP + 0.001), "extreme")

    def test_sign_symmetric(self):
        # Negative USD-strength classified by magnitude, not sign.
        self.assertEqual(_bucket(-2.0), _bucket(2.0))

    def test_unavailable_for_none(self):
        self.assertEqual(_bucket(None), "unavailable")


# ---------------------------------------------------------------------------
# Driver decomposition
# ---------------------------------------------------------------------------

class TestDriverDecomposition(unittest.TestCase):

    def test_single_cross_dominant(self):
        # USDCNY +2.2, EURUSD 0.3, USDJPY -0.2 → CNY dominant
        moves = {"EURUSD": 0.3, "USDJPY": -0.2, "USDCNY": 2.2}
        driver, label = _driver(moves)
        self.assertEqual(driver, "cny")
        self.assertIn("USDCNY", label)

    def test_mixed_no_clear_driver(self):
        # Two pairs equally strong → no single driver
        moves = {"EURUSD": 2.0, "USDJPY": 1.9, "USDCNY": 0.1}
        driver, _label = _driver(moves)
        self.assertIsNone(driver)

    def test_small_move_no_driver(self):
        # All pairs below strong floor → no driver
        moves = {"EURUSD": 0.5, "USDJPY": 0.4, "USDCNY": 0.3}
        driver, _label = _driver(moves)
        self.assertIsNone(driver)

    def test_dominance_margin_exact(self):
        # Top at strong floor, next just below margin → top wins
        top = _PAIR_STRONG_PP + 0.2
        second = top - _DRIVER_DOMINANCE_PP - 0.01
        moves = {"EURUSD": top, "USDJPY": second}
        driver, _ = _driver(moves)
        self.assertEqual(driver, "eur")


# ---------------------------------------------------------------------------
# Dispersion classifier
# ---------------------------------------------------------------------------

class TestDispersion(unittest.TestCase):

    def test_uniform_stdev_under_threshold(self):
        # Three pairs all around +1% → uniform
        values = [1.0, 1.1, 0.9]
        s = _dispersion(values)
        self.assertLess(s, _DISPERSION_UNIFORM)

    def test_mixed_stdev_in_middle_band(self):
        # Spread of ~1.0% → mixed
        values = [2.0, 0.5, 1.0]
        s = _dispersion(values)
        self.assertGreaterEqual(s, _DISPERSION_UNIFORM)
        self.assertLess(s, _DISPERSION_MIXED)


# ---------------------------------------------------------------------------
# compute_cross_rate_fx — full pipeline
# ---------------------------------------------------------------------------

def _pack(eur=None, jpy=None, cny=None, dxy=None) -> dict:
    """Build an explicit fx_pack override for testing."""
    p = {}
    if eur is not None: p["EURUSD"] = eur
    if jpy is not None: p["USDJPY"] = jpy
    if cny is not None: p["USDCNY"] = cny
    if dxy is not None: p["DXY"] = dxy
    return p


class TestComposerFullPipeline(unittest.TestCase):

    def test_broad_usd_strength_uniform(self):
        # Uniform ~+1% USD strength across all three pairs
        result = compute_cross_rate_fx(
            fx_pack=_pack(eur=-1.0, jpy=1.0, cny=1.0, dxy=1.0),
        )
        self.assertTrue(result["available"])
        self.assertEqual(result["dispersion_tag"], "uniform")
        # All three pairs should be in "strong" bucket
        for pid in PAIR_IDS:
            self.assertEqual(result["pairs"][pid]["bucket"], "strong")
        self.assertIn("broad USD move", result["rationale"])

    def test_em_asia_stress_single_driver(self):
        # USDCNY spikes, EUR/JPY quiet → EM Asia regional stress flag
        result = compute_cross_rate_fx(
            fx_pack=_pack(eur=-0.2, jpy=0.1, cny=2.2, dxy=0.8),
        )
        self.assertEqual(result["driver"], "cny")
        self.assertIn("em_asia", result["regional_stress"])
        self.assertNotIn("dm_majors", result["regional_stress"])
        # Dispersion should NOT be uniform (only one pair strong)
        self.assertNotEqual(result["dispersion_tag"], "uniform")

    def test_carry_unwind_fingerprint(self):
        # EM weak (USDCNY up), JPY strong (USDJPY down) → carry unwind
        result = compute_cross_rate_fx(
            fx_pack=_pack(eur=-0.3, jpy=-0.8, cny=1.2, dxy=0.3),
        )
        self.assertTrue(result["carry_unwind"])
        self.assertIn("GC", result["key_markets"])

    def test_dxy_only_when_no_pairs(self):
        # No cross-rate data; DXY present only
        result = compute_cross_rate_fx(fx_pack=_pack(dxy=1.0))
        self.assertFalse(result["available"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["driver"], "dxy_only")
        self.assertEqual(result["dxy_5d"], 1.0)

    def test_empty_when_no_data_at_all(self):
        self.assertEqual(compute_cross_rate_fx(), {})

    def test_reads_from_stress_regime_raw(self):
        # When no fx_pack override, read from stress_regime.raw
        stress = {
            "raw": {
                "eurusd_5d": -1.5,
                "usdjpy_5d":  1.8,
                "usdcny_5d":  0.8,
            },
            "detail": {"safe_haven": {"assets": {"Dollar": 1.2}}},
        }
        result = compute_cross_rate_fx(stress_regime=stress)
        self.assertTrue(result["available"])
        self.assertAlmostEqual(result["pairs"]["EURUSD"]["usd_5d"], 1.5)
        self.assertAlmostEqual(result["pairs"]["USDJPY"]["usd_5d"], 1.8)
        self.assertAlmostEqual(result["dxy_5d"], 1.2)


class TestDriverLabels(unittest.TestCase):

    def test_label_tag_for_each_pair(self):
        for pid, tag in [("EURUSD", "eur"), ("USDJPY", "jpy"), ("USDCNY", "cny")]:
            strong = _PAIR_STRONG_PP + 0.5
            moves = {pid: strong}
            driver, _ = _driver(moves)
            self.assertEqual(driver, tag)


if __name__ == "__main__":
    unittest.main()
