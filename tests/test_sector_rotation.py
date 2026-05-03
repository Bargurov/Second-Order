"""
tests/test_sector_rotation.py

Contract tests for the macro→sector rotation map.

Covers:
  1. Channel plays: rates / breakevens / credit / dollar / crude / metals
     each produce the documented per-sector direction.
  2. Funding-stress mode playbook: liquidity_squeeze routes defensives
     winners + high-beta losers; severity scales contribution size.
  3. Direct vs second-order tagging: each sector's breakdown sorts
     contributions into the right bucket.
  4. Broad-market tilt is computed INDEPENDENTLY from per-sector scoring
     so the risk_on/risk_off read stays usable alongside relative
     advantage.
  5. Shape: available=False when no channels fire; sectors emitted in
     winner→loser→neutral order; winners/losers split by direct vs
     second-order dominance.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sector_rotation import (
    SECTORS,
    _WINNER_FLOOR,
    compute_sector_rotation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sector_by_symbol(card: dict, symbol: str) -> dict:
    for s in card["sectors"]:
        if s["symbol"] == symbol:
            return s
    raise AssertionError(f"sector {symbol!r} not in rotation output")


def _funding_mode(primary: str, severity: str, *others) -> dict:
    """Build a minimal funding_stress_mode dict for the classifier input.

    ``others`` is a list of (mode_name, severity) tuples to also mark
    fired on the modes dict.
    """
    modes = {
        "duration_shock":    {"fired": False, "severity": "none"},
        "credit_widening":   {"fired": False, "severity": "none"},
        "dollar_shortage":   {"fired": False, "severity": "none"},
        "liquidity_squeeze": {"fired": False, "severity": "none"},
    }
    modes[primary] = {"fired": severity != "none", "severity": severity}
    for name, sev in others:
        modes[name] = {"fired": sev != "none", "severity": sev}
    return {
        "primary_mode":       primary,
        "composite_severity": severity,
        "modes":              modes,
    }


# ---------------------------------------------------------------------------
# 1. Per-channel play direction
# ---------------------------------------------------------------------------

class TestRatesChannel(unittest.TestCase):

    def test_rates_up_helps_financials_hurts_duration_sectors(self):
        card = compute_sector_rotation(rates_5d_pp=0.30)
        self.assertEqual(_sector_by_symbol(card, "XLF")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLU")["direction"], "loser")
        self.assertEqual(_sector_by_symbol(card, "XLRE")["direction"], "loser")
        # Tech tagged as second-order duration loser.
        xlk = _sector_by_symbol(card, "XLK")
        self.assertEqual(xlk["direction"], "loser")
        self.assertTrue(any(
            c["channel"] == "rates" for c in xlk["channels_second_order"]
        ))

    def test_rates_down_flips_winners_and_losers(self):
        card = compute_sector_rotation(rates_5d_pp=-0.30)
        self.assertEqual(_sector_by_symbol(card, "XLU")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLRE")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLF")["direction"], "loser")


class TestBreakevensChannel(unittest.TestCase):

    def test_breakevens_up_helps_energy_and_materials(self):
        card = compute_sector_rotation(breakeven_5d_pp=0.20)
        self.assertEqual(_sector_by_symbol(card, "XLE")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLB")["direction"], "winner")
        # Staples face margin-squeeze second-order pressure.
        xlp = _sector_by_symbol(card, "XLP")
        self.assertEqual(xlp["direction"], "loser")
        self.assertTrue(any(
            c["channel"] == "breakevens" for c in xlp["channels_second_order"]
        ))


class TestCreditChannel(unittest.TestCase):

    def test_credit_widening_helps_defensives_hurts_regional_banks(self):
        # HY -2% → credit widening intensity ≈ 2.0
        card = compute_sector_rotation(
            credit_regime={"hy_5d": -2.0, "regime": "default_risk_widening"},
        )
        self.assertEqual(_sector_by_symbol(card, "KRE")["direction"], "loser")
        # Defensives bid.
        self.assertEqual(_sector_by_symbol(card, "XLP")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLV")["direction"], "winner")
        # XLY pressured as second-order (credit-dependent consumption).
        self.assertEqual(_sector_by_symbol(card, "XLY")["direction"], "loser")

    def test_credit_risk_on_flips_the_pattern(self):
        card = compute_sector_rotation(
            credit_regime={"hy_5d": +1.8, "regime": "risk_on"},
        )
        self.assertEqual(_sector_by_symbol(card, "KRE")["direction"], "winner")
        # Defensives lose relative advantage.
        self.assertEqual(_sector_by_symbol(card, "XLP")["direction"], "loser")


class TestDollarChannel(unittest.TestCase):

    def test_dollar_strength_hurts_materials_and_energy(self):
        card = compute_sector_rotation(dxy_5d_pct=2.0)
        self.assertEqual(_sector_by_symbol(card, "XLB")["direction"], "loser")
        self.assertEqual(_sector_by_symbol(card, "XLE")["direction"], "loser")
        # Multinational tech is tagged as second-order loser.
        xlk = _sector_by_symbol(card, "XLK")
        self.assertEqual(xlk["direction"], "loser")
        self.assertTrue(any(
            c["channel"] == "dollar" for c in xlk["channels_second_order"]
        ))


class TestCrudeChannel(unittest.TestCase):

    def test_crude_up_helps_energy_hurts_consumer(self):
        card = compute_sector_rotation(crude_5d_pct=8.0)
        self.assertEqual(_sector_by_symbol(card, "XLE")["direction"], "winner")
        # Discretionary + industrials tagged as second-order losers.
        xly = _sector_by_symbol(card, "XLY")
        self.assertEqual(xly["direction"], "loser")
        self.assertTrue(any(
            c["channel"] == "crude" for c in xly["channels_second_order"]
        ))


class TestMetalsChannel(unittest.TestCase):

    def test_metals_up_helps_materials(self):
        card = compute_sector_rotation(gold_5d_pct=4.0)
        self.assertEqual(_sector_by_symbol(card, "XLB")["direction"], "winner")


# ---------------------------------------------------------------------------
# 2. Funding-stress mode playbook
# ---------------------------------------------------------------------------

class TestFundingStressModePlaybook(unittest.TestCase):

    def test_liquidity_squeeze_routes_defensives_winners(self):
        card = compute_sector_rotation(
            funding_stress_mode=_funding_mode("liquidity_squeeze", "elevated"),
        )
        self.assertEqual(_sector_by_symbol(card, "XLP")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLV")["direction"], "winner")
        # High-beta tech + regional banks losers.
        self.assertEqual(_sector_by_symbol(card, "XLK")["direction"], "loser")
        self.assertEqual(_sector_by_symbol(card, "KRE")["direction"], "loser")

    def test_severity_scales_contribution(self):
        """Acute severity should produce bigger magnitudes than mild."""
        mild = compute_sector_rotation(
            funding_stress_mode=_funding_mode("liquidity_squeeze", "mild"),
        )
        acute = compute_sector_rotation(
            funding_stress_mode=_funding_mode("liquidity_squeeze", "acute"),
        )
        self.assertGreater(
            abs(_sector_by_symbol(acute, "XLK")["net_score"]),
            abs(_sector_by_symbol(mild, "XLK")["net_score"]),
        )

    def test_none_severity_is_no_op(self):
        card = compute_sector_rotation(
            funding_stress_mode=_funding_mode("liquidity_squeeze", "none"),
        )
        # Every sector must have zero score — no channel contributed.
        for s in card["sectors"]:
            self.assertEqual(s["net_score"], 0.0)
        self.assertFalse(card["available"])


# ---------------------------------------------------------------------------
# 3. Direct vs second-order tagging
# ---------------------------------------------------------------------------

class TestDirectVsSecondOrderTagging(unittest.TestCase):

    def test_financials_rates_contribution_is_direct(self):
        card = compute_sector_rotation(rates_5d_pp=0.30)
        xlf = _sector_by_symbol(card, "XLF")
        direct_channels = [c["channel"] for c in xlf["channels_direct"]]
        self.assertIn("rates", direct_channels)

    def test_tech_rates_contribution_is_second_order(self):
        card = compute_sector_rotation(rates_5d_pp=0.30)
        xlk = _sector_by_symbol(card, "XLK")
        second_channels = [c["channel"] for c in xlk["channels_second_order"]]
        self.assertIn("rates", second_channels)
        direct_channels = [c["channel"] for c in xlk["channels_direct"]]
        self.assertNotIn("rates", direct_channels)

    def test_discretionary_crude_is_second_order_not_direct(self):
        card = compute_sector_rotation(crude_5d_pct=8.0)
        xly = _sector_by_symbol(card, "XLY")
        # Crude hits XLY via gas-price consumer transmission — second-order.
        direct_channels = [c["channel"] for c in xly["channels_direct"]]
        second_channels = [c["channel"] for c in xly["channels_second_order"]]
        self.assertIn("crude", second_channels)
        self.assertNotIn("crude", direct_channels)

    def test_sector_can_mix_direct_and_second_order_channels(self):
        card = compute_sector_rotation(
            rates_5d_pp=0.30,    # XLE direct
            crude_5d_pct=8.0,    # XLE direct
            dxy_5d_pct=1.5,      # XLE direct (loser)
        )
        xle = _sector_by_symbol(card, "XLE")
        # All three contributions exist in the breakdown.
        channel_names = [c["channel"] for c in xle["channels_direct"]]
        self.assertIn("rates", channel_names)
        self.assertIn("crude", channel_names)
        self.assertIn("dollar", channel_names)


# ---------------------------------------------------------------------------
# 4. Broad-market tilt independence
# ---------------------------------------------------------------------------

class TestBroadMarketTiltIndependence(unittest.TestCase):

    def test_broad_tilt_reported_separately(self):
        card = compute_sector_rotation(
            credit_regime={"hy_5d": -2.0, "regime": "default_risk_widening"},
        )
        # Broad tape = risk_off even though per-sector winners still exist.
        self.assertEqual(card["broad_market_tilt"], "risk_off")
        self.assertGreater(len(card["broad_market_drivers"]), 0)

    def test_relative_advantage_persists_under_risk_off(self):
        """Under risk_off broad tilt, defensives should STILL show
        positive relative advantage — the per-sector scoring is not
        washed out by the aggregate tilt."""
        card = compute_sector_rotation(
            credit_regime={"hy_5d": -2.0, "regime": "default_risk_widening"},
            funding_stress_mode=_funding_mode("liquidity_squeeze", "elevated"),
        )
        self.assertEqual(card["broad_market_tilt"], "risk_off")
        self.assertEqual(_sector_by_symbol(card, "XLP")["direction"], "winner")
        self.assertEqual(_sector_by_symbol(card, "XLV")["direction"], "winner")

    def test_neutral_tilt_on_quiet_tape(self):
        card = compute_sector_rotation()
        self.assertEqual(card["broad_market_tilt"], "neutral")

    def test_risk_on_tilt_from_credit_tightening(self):
        card = compute_sector_rotation(
            credit_regime={"hy_5d": +2.0, "regime": "risk_on"},
        )
        self.assertEqual(card["broad_market_tilt"], "risk_on")


# ---------------------------------------------------------------------------
# 5. Shape / invariants
# ---------------------------------------------------------------------------

class TestShapeInvariants(unittest.TestCase):

    def test_all_sectors_emitted(self):
        card = compute_sector_rotation(rates_5d_pp=0.30)
        symbols = {s["symbol"] for s in card["sectors"]}
        expected = {sym for sym, _ in SECTORS}
        self.assertEqual(symbols, expected)

    def test_available_false_when_no_channels(self):
        card = compute_sector_rotation()
        self.assertFalse(card["available"])
        self.assertEqual(
            sum(abs(s["net_score"]) for s in card["sectors"]), 0.0,
        )

    def test_available_true_when_any_channel_fires(self):
        card = compute_sector_rotation(rates_5d_pp=0.30)
        self.assertTrue(card["available"])

    def test_sectors_ordered_winners_first(self):
        card = compute_sector_rotation(
            rates_5d_pp=0.30,
            credit_regime={"hy_5d": -2.0, "regime": "default_risk_widening"},
        )
        directions = [s["direction"] for s in card["sectors"]]
        # Winners come before losers; neutrals come last.
        first_loser = next((i for i, d in enumerate(directions) if d == "loser"), None)
        first_neutral = next((i for i, d in enumerate(directions) if d == "neutral"), None)
        if first_loser is not None and first_neutral is not None:
            self.assertLess(first_loser, first_neutral)
        # No winner appears after any loser.
        for i, d in enumerate(directions):
            if d == "loser":
                self.assertNotIn("winner", directions[i:])

    def test_winners_losers_split_by_direct_vs_second_order(self):
        # A tape that creates clear direct + second-order winners.
        card = compute_sector_rotation(
            rates_5d_pp=0.30,                  # XLF direct winner
            crude_5d_pct=6.0,                  # XLE direct winner
            breakeven_5d_pp=0.20,              # XLE/XLB direct winners
        )
        all_winner_syms = card["winners"]["direct"] + card["winners"]["second_order"]
        for s in card["sectors"]:
            if s["direction"] == "winner":
                self.assertIn(s["symbol"], all_winner_syms)

    def test_winner_floor_constant(self):
        """Pin the threshold constant — silent loosening would flip
        the direction labels across the archive."""
        self.assertEqual(_WINNER_FLOOR, 0.5)

    def test_confidence_escalates_with_magnitude_and_channels(self):
        """Multi-channel alignment → high confidence; single small → low."""
        small = compute_sector_rotation(rates_5d_pp=0.15)
        big = compute_sector_rotation(
            rates_5d_pp=0.50,       # large
            dxy_5d_pct=-0.1,        # trivial; just adds channel count
            breakeven_5d_pp=0.20,
        )
        xlre_small = _sector_by_symbol(small, "XLRE")
        xlre_big   = _sector_by_symbol(big,   "XLRE")
        # big has more channels + larger magnitude → higher confidence.
        self.assertIn(xlre_small["confidence"], {"low", "medium"})
        self.assertIn(xlre_big["confidence"], {"medium", "high"})


if __name__ == "__main__":
    unittest.main()
