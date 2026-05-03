"""
tests/test_mechanism_specific_reads.py

Validates the mechanism-specific reaction reads that replaced the old
bulk hawk/dove point accumulator in reaction_function_divergence.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reaction_function_divergence import (  # noqa: E402
    _channel_reads,
    _priced_direction,
    _HAWKISH_EXPECT,
    _CHANNEL_Z_FLOOR,
    compute_reaction_function_divergence,
)


def _ch(label, move, z, available=True, unit="pp"):
    return {"label": label, "move_5d": move, "available": available,
            "unit": unit, "z": z}


def _channels(nom=(0.0, 0.0), real=(0.0, 0.0), fx=(0.0, 0.0),
              credit=(0.0, 0.0), be=(0.0, 0.0), cmdty=(0.0, 0.0)):
    """Build a 6-channel dict as produced by shock_decomposition."""
    return {
        "nominal_yield": _ch("Nominal yields", nom[0], nom[1]),
        "real_yield":    _ch("Real yields", real[0], real[1], unit="%"),
        "breakeven":     _ch("Breakeven", be[0], be[1]),
        "fx":            _ch("Dollar / FX", fx[0], fx[1], unit="%"),
        "credit":        _ch("Credit spreads", credit[0], credit[1]),
        "commodity":     _ch("Commodities", cmdty[0], cmdty[1], unit="%"),
    }


class TestChannelReadsEmpty(unittest.TestCase):

    def test_all_silent_when_no_moves(self):
        reads, hawk, dove = _channel_reads(_channels())
        # Only the channels in _HAWKISH_EXPECT are returned.
        self.assertEqual(len(reads), len(_HAWKISH_EXPECT))
        for r in reads:
            self.assertEqual(r["verdict"], "silent")
            self.assertEqual(r["contribution"], 0.0)
        self.assertEqual(hawk, 0.0)
        self.assertEqual(dove, 0.0)


class TestChannelReadsDirectional(unittest.TestCase):

    def test_nominal_up_big_move_adds_to_hawk(self):
        # 10Y +0.40pp / 5d = 2σ hawkish
        reads, hawk, dove = _channel_reads(_channels(nom=(0.40, 2.0)))
        nom_read = next(r for r in reads if r["channel"] == "nominal_yield")
        self.assertEqual(nom_read["verdict"], "hawkish")
        self.assertEqual(nom_read["contribution"], 2.0)
        self.assertGreater(hawk, 0)
        self.assertEqual(dove, 0)

    def test_real_yield_down_is_hawkish_tip_falling(self):
        # TIP -1.5% = 2σ → real yields UP → hawkish
        reads, hawk, dove = _channel_reads(_channels(real=(-1.5, 2.0)))
        real_read = next(r for r in reads if r["channel"] == "real_yield")
        self.assertEqual(real_read["verdict"], "hawkish")
        self.assertGreater(hawk, 0)

    def test_dxy_up_is_hawkish_fx(self):
        reads, hawk, dove = _channel_reads(_channels(fx=(1.8, 2.0)))
        fx_read = next(r for r in reads if r["channel"] == "fx")
        self.assertEqual(fx_read["verdict"], "hawkish")

    def test_credit_widening_is_hawkish(self):
        reads, hawk, dove = _channel_reads(_channels(credit=(2.0, 2.0)))
        credit_read = next(r for r in reads if r["channel"] == "credit")
        self.assertEqual(credit_read["verdict"], "hawkish")
        self.assertGreater(hawk, 0)

    def test_opposing_move_counts_as_dovish(self):
        # 10Y -0.40 → opposite of hawkish-expected "up" → dovish
        reads, hawk, dove = _channel_reads(_channels(nom=(-0.40, 2.0)))
        nom_read = next(r for r in reads if r["channel"] == "nominal_yield")
        self.assertEqual(nom_read["verdict"], "dovish")
        self.assertGreater(dove, 0)
        self.assertEqual(hawk, 0)

    def test_below_z_floor_counts_as_silent(self):
        z = _CHANNEL_Z_FLOOR - 0.1
        reads, hawk, dove = _channel_reads(_channels(nom=(0.10, z)))
        nom_read = next(r for r in reads if r["channel"] == "nominal_yield")
        self.assertEqual(nom_read["verdict"], "silent")
        self.assertEqual(hawk, 0.0)
        self.assertEqual(dove, 0.0)


class TestPricedDirection(unittest.TestCase):

    def test_hawkish_when_multiple_channels_confirm(self):
        # 10Y +0.4pp (2σ) + TIP -1.5% (2σ) → both hawkish; dove=0
        shock_channels = _channels(nom=(0.40, 2.0), real=(-1.5, 2.0))
        direction, basis, lead, reads = _priced_direction(
            shock_channels, rates_context=None, stress_regime=None,
        )
        self.assertEqual(direction, "hawkish")
        self.assertGreater(lead, 0)
        # Mechanism reads include per-channel details.
        nom = next(r for r in reads if r["channel"] == "nominal_yield")
        self.assertEqual(nom["verdict"], "hawkish")

    def test_dovish_when_multiple_channels_oppose(self):
        shock_channels = _channels(nom=(-0.4, 2.0), fx=(-2.0, 2.2))
        direction, _basis, _lead, _reads = _priced_direction(
            shock_channels, rates_context=None, stress_regime=None,
        )
        self.assertEqual(direction, "dovish")

    def test_neutral_when_mixed_below_margin(self):
        # One hawkish (nom +0.40, z=2) + one dovish (TIP +1.5%, z=2) → tie
        shock_channels = _channels(nom=(0.40, 2.0), real=(1.5, 2.0))
        direction, _basis, _lead, _reads = _priced_direction(
            shock_channels, rates_context=None, stress_regime=None,
        )
        self.assertEqual(direction, "neutral")

    def test_regime_nudge_tips_direction(self):
        # No channel clears the z-floor, so only the Risk-off regime nudge
        # contributes — that 1.0 dovish nudge is enough to tip direction.
        shock_channels = _channels(nom=(0.15, 0.7))  # sub-floor → silent
        direction, _basis, _lead, _reads = _priced_direction(
            shock_channels,
            rates_context={"regime": "Risk-off / growth scare"},
            stress_regime=None,
        )
        self.assertEqual(direction, "dovish")


class TestReactionFunctionBackwardCompat(unittest.TestCase):
    """Top-level shape of compute_reaction_function_divergence stays stable."""

    def test_fields_present_after_refactor(self):
        rates = {
            "regime": "Real-rate tightening",
            "nominal": {"change_5d": 0.35},
            "real_proxy": {"change_5d": -1.2},
            "breakeven_proxy": {"change_5d": 0.0},
            "raw": {},
        }
        stress = {
            "regime": "Calm", "signals": {}, "raw": {"vix": 17},
            "detail": {"safe_haven": {"assets": {}}},
        }
        result = compute_reaction_function_divergence(
            "OPEC announces production cut", "supply shock",
            rates, stress, snapshots=None,
        )
        for k in ("implied", "priced", "divergence", "rationale",
                  "macro_read", "key_markets",
                  "mechanism_reads", "confirmation_matrix", "priced_lead"):
            self.assertIn(k, result, f"missing field: {k}")
        # Matrix exposes confirms/disconfirms separately.
        matrix = result["confirmation_matrix"]
        self.assertIn("confirm_score", matrix)
        self.assertIn("disconfirm_score", matrix)

    def test_inflationary_thesis_hawkish_tape_is_aligned(self):
        # Headline implies inflation (OPEC cut); macro consistent.
        rates = {
            "regime": "Inflation pressure",
            "nominal": {"change_5d": 0.30},
            "real_proxy": {"change_5d": -1.0},
            "breakeven_proxy": {"change_5d": 0.25},
            "raw": {},
        }
        stress = {
            "regime": "Calm", "signals": {}, "raw": {"vix": 17},
            "detail": {"safe_haven": {"assets": {}}},
        }
        result = compute_reaction_function_divergence(
            "OPEC announces production cut — oil price spike",
            "Tariff-style supply shock lifts import costs",
            rates, stress, snapshots=None,
        )
        self.assertEqual(result["implied"], "hawkish")
        self.assertEqual(result["priced"], "hawkish")
        self.assertEqual(result["divergence"], "aligned")


if __name__ == "__main__":
    unittest.main()
