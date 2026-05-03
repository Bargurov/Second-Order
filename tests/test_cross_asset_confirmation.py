"""
tests/test_cross_asset_confirmation.py

Validates the cross-asset confirmation matrix: per-channel expected vs
observed verdicts, confirms and disconfirms scored **separately**, and
aggregate verdict thresholds.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cross_asset_confirmation import (  # noqa: E402
    compute_cross_asset_confirmation,
    _Z_FLOOR,
    _STRONG_SCORE,
    _WEAK_SCORE,
)


def _ch(label, move, z, available=True, unit="pp"):
    return {"label": label, "move_5d": move, "available": available,
            "unit": unit, "z": z}


def _full_channels(nom_z=0.0, nom_sign=1, real_z=0.0, real_sign=-1,
                   be_z=0.0, be_sign=1, fx_z=0.0, fx_sign=1,
                   credit_z=0.0, credit_sign=1, cmdty_z=0.0, cmdty_sign=1):
    """Build a full 6-channel dict. Sign arguments let us flip directions."""
    return {
        "nominal_yield": _ch("Nominal yields", nom_sign * nom_z * 0.20, nom_z),
        "real_yield":    _ch("Real yields",    real_sign * real_z * 0.75, real_z, unit="%"),
        "breakeven":     _ch("Breakeven inflation", be_sign * be_z * 0.20, be_z),
        "fx":            _ch("Dollar / FX",    fx_sign * fx_z * 0.90, fx_z, unit="%"),
        "credit":        _ch("Credit spreads", credit_sign * credit_z * 1.00, credit_z),
        "commodity":     _ch("Commodities",    cmdty_sign * cmdty_z * 5.00, cmdty_z, unit="%"),
    }


class TestChannelVerdicts(unittest.TestCase):

    def test_inflationary_all_channels_confirm(self):
        # nominal up, TIP down (real_yield negative move = "down"), BE up,
        # commodity up — four confirming moves
        channels = _full_channels(
            nom_z=2.0, nom_sign=+1,
            real_z=2.0, real_sign=-1,   # move_5d = -1.5 (TIP fell) → dir "down" = expected "down"
            be_z=2.0, be_sign=+1,
            cmdty_z=2.0, cmdty_sign=+1,
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertEqual(
            set(result["confirms"]),
            {"nominal_yield", "real_yield", "breakeven", "commodity"},
        )
        self.assertGreaterEqual(result["confirm_score"], _STRONG_SCORE)
        self.assertLess(result["disconfirm_score"], _WEAK_SCORE)
        self.assertEqual(result["verdict"], "strong_confirm")

    def test_inflationary_thesis_all_disconfirm(self):
        # Thesis inflationary, but nominal down, TIP up, BE down, commodity down
        channels = _full_channels(
            nom_z=2.0, nom_sign=-1,
            real_z=2.0, real_sign=+1,
            be_z=2.0, be_sign=-1,
            cmdty_z=2.0, cmdty_sign=-1,
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertEqual(
            set(result["disconfirms"]),
            {"nominal_yield", "real_yield", "breakeven", "commodity"},
        )
        self.assertGreaterEqual(result["disconfirm_score"], _STRONG_SCORE)
        self.assertEqual(result["verdict"], "strong_disconfirm")

    def test_mixed_when_both_sides_fire(self):
        # Two strong confirms (nominal up, commodity up) + two strong
        # disconfirms (real yield up, BE down) → mixed verdict.
        channels = _full_channels(
            nom_z=2.0, nom_sign=+1,     # confirm inflationary
            real_z=2.0, real_sign=+1,    # disconfirm (TIP up = real down, expected down means TIP-down)
            be_z=2.0, be_sign=-1,        # disconfirm
            cmdty_z=2.0, cmdty_sign=+1,  # confirm
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertGreaterEqual(result["confirm_score"], 1.5)
        self.assertGreaterEqual(result["disconfirm_score"], 1.5)
        self.assertEqual(result["verdict"], "mixed")

    def test_silent_below_z_floor(self):
        # All channels moving in confirming direction but all sub-floor.
        channels = _full_channels(
            nom_z=0.4, nom_sign=+1,       # below _Z_FLOOR=0.8
            real_z=0.4, real_sign=-1,
            be_z=0.4, be_sign=+1,
            cmdty_z=0.4, cmdty_sign=+1,
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertEqual(result["confirm_score"], 0)
        self.assertEqual(result["disconfirm_score"], 0)
        self.assertEqual(result["verdict"], "silent")
        # All should show as silent in per-channel verdicts.
        for cid in ("nominal_yield", "real_yield", "breakeven", "commodity"):
            self.assertEqual(
                result["channels"][cid]["verdict"], "silent",
                f"{cid} should be silent below z-floor",
            )

    def test_expected_silent_channel_never_contributes(self):
        # For rate_pressure_up, commodity is expected=silent. Even a huge
        # commodity move must NOT show up as confirm or disconfirm.
        channels = _full_channels(cmdty_z=3.0, cmdty_sign=+1)
        result = compute_cross_asset_confirmation("rate_pressure_up", channels)
        self.assertEqual(result["channels"]["commodity"]["verdict"], "silent")
        self.assertNotIn("commodity", result["confirms"])
        self.assertNotIn("commodity", result["disconfirms"])


class TestVerdictThresholds(unittest.TestCase):

    def test_weak_confirm_at_low_score(self):
        # One confirming channel clearing z-floor minimally.
        channels = _full_channels(nom_z=1.6, nom_sign=+1)
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertGreaterEqual(result["confirm_score"], _WEAK_SCORE)
        self.assertLess(result["confirm_score"], _STRONG_SCORE)
        self.assertEqual(result["verdict"], "weak_confirm")

    def test_just_above_floor_does_not_trigger_silent(self):
        channels = _full_channels(nom_z=_Z_FLOOR + 0.01, nom_sign=+1)
        result = compute_cross_asset_confirmation("inflationary", channels)
        # Score below WEAK threshold → still silent (one small confirm only)
        self.assertLess(result["confirm_score"], _WEAK_SCORE)
        self.assertEqual(result["verdict"], "silent")


class TestNoneThesisAndUnavailable(unittest.TestCase):

    def test_none_thesis_returns_silent(self):
        channels = _full_channels(nom_z=3.0, nom_sign=+1)
        result = compute_cross_asset_confirmation("none", channels)
        self.assertEqual(result["verdict"], "silent")
        # No channels counted against "none" thesis.
        self.assertEqual(result["confirm_score"], 0)
        self.assertEqual(result["disconfirm_score"], 0)

    def test_all_channels_unavailable(self):
        channels = {
            "nominal_yield": _ch("Nominal", None, 0.0, available=False),
            "real_yield":    _ch("Real", None, 0.0, available=False, unit="%"),
            "breakeven":     _ch("BE", None, 0.0, available=False),
            "fx":            _ch("FX", None, 0.0, available=False, unit="%"),
            "credit":        _ch("Credit", None, 0.0, available=False),
            "commodity":     _ch("Cmdty", None, 0.0, available=False, unit="%"),
        }
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertFalse(result["available"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["verdict"], "silent")


class TestCurveShapeRead(unittest.TestCase):

    def test_curve_aligned_with_inflationary(self):
        channels = _full_channels()
        result = compute_cross_asset_confirmation(
            "inflationary", channels,
            rates_pack={"curve_shape": "bear_steepener", "available": True},
        )
        self.assertEqual(result["curve_shape_read"], "aligned")

    def test_curve_diverges_from_thesis(self):
        channels = _full_channels()
        result = compute_cross_asset_confirmation(
            "inflationary", channels,
            rates_pack={"curve_shape": "bull_flattener", "available": True},
        )
        self.assertEqual(result["curve_shape_read"], "diverges")

    def test_curve_silent_when_flat(self):
        channels = _full_channels()
        result = compute_cross_asset_confirmation(
            "inflationary", channels,
            rates_pack={"curve_shape": "flat", "available": True},
        )
        self.assertEqual(result["curve_shape_read"], "silent")


class TestConfirmsAndDisconfirmsScoredSeparately(unittest.TestCase):
    """Critical contract: confirms and disconfirms are NOT netted into a single
    signed score.  This test locks that in."""

    def test_both_scores_reported_independently(self):
        # Two confirms of z=2.0 and two disconfirms of z=2.0.
        # Net = 0, but separate scores must both be ~4.0.
        channels = _full_channels(
            nom_z=2.0, nom_sign=+1,       # confirm
            cmdty_z=2.0, cmdty_sign=+1,    # confirm
            real_z=2.0, real_sign=+1,      # disconfirm
            be_z=2.0, be_sign=-1,          # disconfirm
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        self.assertAlmostEqual(result["confirm_score"], 4.0, places=1)
        self.assertAlmostEqual(result["disconfirm_score"], 4.0, places=1)
        # Verdict is "mixed", not "silent" — confirms AND disconfirms fire.
        self.assertEqual(result["verdict"], "mixed")


class TestDisconfirmPenaltyHurtsHarder(unittest.TestCase):
    """Asymmetric weighting: a contradictory cross-asset read has to
    tip the verdict harder than an equal-magnitude confirm.  A confirm
    of z=2.0 paired with a disconfirm of z=1.4 (raw) used to read as
    weak_confirm because raw disconfirm fell below the _MIXED_BOTH
    floor; with the penalty multiplier it now lifts above the floor
    and the verdict reads mixed."""

    def test_disconfirm_below_floor_is_lifted_into_mixed(self):
        # confirm score 2.0, raw disconfirm 1.4 (below _MIXED_BOTH=1.5).
        # nom_z=2.0 confirms inflationary; real_sign=+1 → real_yield
        # disconfirms inflationary.
        channels = _full_channels(
            nom_z=2.0, nom_sign=+1,    # confirm
            real_z=1.4, real_sign=+1,   # disconfirm (TIP up vs expected down)
        )
        result = compute_cross_asset_confirmation("inflationary", channels)
        # Raw scores reported unchanged in the output.
        self.assertAlmostEqual(result["confirm_score"], 2.0, places=1)
        self.assertAlmostEqual(result["disconfirm_score"], 1.4, places=1)
        # But the verdict reads mixed because the penalty multiplier
        # lifts disconfirm above the _MIXED_BOTH floor.
        self.assertEqual(result["verdict"], "mixed")


if __name__ == "__main__":
    unittest.main()
