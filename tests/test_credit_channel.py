"""
tests/test_credit_channel.py

Validates the credit channel added to shock_decomposition as the 6th
transmission channel.  Representative cases: widening, tightening,
fallback from stress_regime, and threshold edges.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shock_decomposition import (  # noqa: E402
    CHANNEL_IDS,
    _CHANNEL_SCALE,
    _CHANNEL_MOVE_CAPS,
    compute_shock_decomposition,
)


def _rates(nominal_5d=0.05, real_5d=0.0, breakeven_5d=0.05):
    return {
        "regime": "Mixed",
        "nominal": {"label": "10Y", "value": 4.25, "change_5d": nominal_5d},
        "real_proxy": {"label": "TIP", "value": 108.5, "change_5d": real_5d},
        "breakeven_proxy": {"change_5d": breakeven_5d},
        "raw": {"^TNX": 4.25},
    }


def _stress_with_credit(spread_5d, shy_5d=0.0):
    """Stress regime with a credit-spread (SHY_5d − HYG_5d) reading."""
    return {
        "regime": "Calm",
        "signals": {"credit_widening": spread_5d > 0.5,
                    "vix_elevated": False, "term_inversion": False,
                    "safe_haven_bid": False, "breadth_deterioration": False},
        "raw": {"credit_spread_5d": spread_5d, "shy_5d": shy_5d, "hyg_5d": shy_5d - spread_5d,
                "vix": 17.0},
        "detail": {
            "credit": {"label": "Credit Stress", "spread_5d": spread_5d,
                       "status": "active" if spread_5d > 0.5 else "calm",
                       "explanation": ""},
            "safe_haven": {"assets": {}},
        },
    }


class TestCreditChannelRegistered(unittest.TestCase):

    def test_credit_in_channel_ids(self):
        self.assertIn("credit", CHANNEL_IDS)
        self.assertEqual(len(CHANNEL_IDS), 6)

    def test_credit_has_scale_and_cap(self):
        self.assertIn("credit", _CHANNEL_SCALE)
        self.assertIn("credit", _CHANNEL_MOVE_CAPS)
        # 1-sigma scale and cap are sane.
        self.assertGreater(_CHANNEL_SCALE["credit"], 0.0)
        self.assertGreater(_CHANNEL_MOVE_CAPS["credit"], _CHANNEL_SCALE["credit"])


class TestCreditFromStressRegime(unittest.TestCase):

    def test_credit_widening_populates_channel(self):
        # Spread +1.5pp → z = 1.5 / 1.0 = 1.5
        result = compute_shock_decomposition(
            rates_context=_rates(),
            stress_regime=_stress_with_credit(spread_5d=1.5),
            snapshots=None,
        )
        credit = result["channels"]["credit"]
        self.assertTrue(credit["available"])
        self.assertEqual(credit["move_5d"], 1.5)
        self.assertAlmostEqual(credit["z"], 1.5, places=1)

    def test_credit_tightening_signed_negative(self):
        # Spread -0.8pp (credit tightening)
        result = compute_shock_decomposition(
            rates_context=_rates(),
            stress_regime=_stress_with_credit(spread_5d=-0.8),
            snapshots=None,
        )
        credit = result["channels"]["credit"]
        self.assertTrue(credit["available"])
        self.assertLess(credit["move_5d"], 0)

    def test_credit_dominates_when_widening_largest(self):
        # Spread +3.0pp (z=3.0) dominates small rates moves.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.05, real_5d=0.05, breakeven_5d=0.05),
            stress_regime=_stress_with_credit(spread_5d=3.0),
            snapshots=None,
        )
        self.assertEqual(result["primary"], "credit")
        self.assertIn("credit", result["macro_read"].lower())
        self.assertIn("HYG", result["key_markets"])


class TestCreditFromSnapshots(unittest.TestCase):

    def test_credit_from_hyg_lqd_snapshots(self):
        # HYG -2.0%, LQD -0.5% → credit spread = -0.5 - (-2.0) = +1.5 (widen)
        snaps = [
            {"market": "HYG", "symbol": "HYG", "value": 74.0, "change_5d": -2.0, "error": None},
            {"market": "LQD", "symbol": "LQD", "value": 108.0, "change_5d": -0.5, "error": None},
        ]
        result = compute_shock_decomposition(
            rates_context=_rates(),
            stress_regime=None,
            snapshots=snaps,
        )
        credit = result["channels"]["credit"]
        self.assertTrue(credit["available"])
        self.assertAlmostEqual(credit["move_5d"], 1.5, places=2)

    def test_credit_from_hyg_shy_when_lqd_missing(self):
        # Fallback reference: SHY
        snaps = [
            {"market": "HYG", "symbol": "HYG", "value": 74.0, "change_5d": -1.5, "error": None},
            {"market": "SHY", "symbol": "SHY", "value": 82.0, "change_5d": 0.1, "error": None},
        ]
        result = compute_shock_decomposition(
            rates_context=_rates(),
            stress_regime=None,
            snapshots=snaps,
        )
        credit = result["channels"]["credit"]
        self.assertTrue(credit["available"])
        self.assertAlmostEqual(credit["move_5d"], 1.6, places=2)


class TestCreditCapsAndEdges(unittest.TestCase):

    def test_insane_credit_value_discarded(self):
        # Spread +50pp is well beyond any real regime; should be dropped.
        result = compute_shock_decomposition(
            rates_context=_rates(),
            stress_regime=_stress_with_credit(spread_5d=50.0),
            snapshots=None,
        )
        self.assertFalse(result["channels"]["credit"]["available"])

    def test_credit_not_available_when_no_source(self):
        # No stress credit detail, no HYG snapshot.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.3),
            stress_regime={"regime": "Calm", "signals": {},
                           "raw": {"vix": 15}, "detail": {"safe_haven": {"assets": {}}}},
            snapshots=None,
        )
        self.assertFalse(result["channels"]["credit"]["available"])


if __name__ == "__main__":
    unittest.main()
