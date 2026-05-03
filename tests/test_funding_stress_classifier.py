"""
tests/test_funding_stress_classifier.py

Contract tests for the funding / liquidity stress mode classifier.

Covers:
  1. Per-mode thresholds: each mode (duration, credit, dollar, liquidity)
     escalates cleanly across none → mild → elevated → acute.
  2. Amplifiers: curve-parallel shift, HY-IG differential, USDCNY break,
     and uniform dispersion each escalate by one tier.
  3. Liquidity corroboration: isolated VIX spike without breadth or
     safe-haven firing is demoted.
  4. Aggregation: primary mode + composite severity + active_modes list
     honour severity rank and priority tie-break.
  5. Availability: all-missing inputs return available=False; partial
     inputs still classify the modes they can.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from funding_stress_classifier import (
    _MODE_PRIORITY,
    _SEVERITY_ORDER,
    classify_funding_stress,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _rates(change_5d_pp: float, *, curve_shape: str = "flat") -> dict:
    return {
        "nominal":          {"change_5d": change_5d_pp, "value": 4.3},
        "real_proxy":       {"change_5d": 0.0},
        "breakeven_proxy":  {"change_5d": 0.0},
        "breakeven_curve":  {"shape": curve_shape, "available": True},
        "regime":           "Mixed",
        "raw":              {},
    }


def _stress(
    *, vix: float = 17.0, hyg_5d: float = 0.0,
    safe_haven: bool = False, breadth: bool = False,
    dollar_5d: float | None = None,
) -> dict:
    detail: dict = {}
    if dollar_5d is not None:
        detail["safe_haven"] = {"assets": {"Dollar": dollar_5d}}
    return {
        "regime": "Calm",
        "signals": {
            "vix_elevated":           vix >= 20.0,
            "term_inversion":         False,
            "credit_widening":        hyg_5d <= -1.0,
            "safe_haven_bid":         safe_haven,
            "breadth_deterioration":  breadth,
        },
        "raw":     {"vix": vix, "hyg_5d": hyg_5d},
        "detail":  detail,
        "summary": "",
    }


def _credit(*, regime: str = "quiet", hy_ig_diff: float | None = None) -> dict:
    return {
        "regime":                  regime,
        "hy_ig_differential_5d":   hy_ig_diff,
    }


def _fx(
    *, dxy_5d: float | None = None,
    usdcny_5d: float | None = None,
    dispersion: str = "mixed",
) -> dict:
    pairs: dict = {}
    if usdcny_5d is not None:
        pairs["USDCNY"] = {"usd_5d": usdcny_5d}
    return {
        "dxy_5d":          dxy_5d,
        "pairs":           pairs,
        "dispersion_tag":  dispersion,
    }


# ---------------------------------------------------------------------------
# 1. Per-mode thresholds
# ---------------------------------------------------------------------------

class TestDurationShockMode(unittest.TestCase):

    def test_flat_10y_is_none(self):
        r = classify_funding_stress(_rates(0.05), _stress(), {}, {})
        self.assertEqual(r["modes"]["duration_shock"]["severity"], "none")
        self.assertFalse(r["modes"]["duration_shock"]["fired"])

    def test_moderate_10y_move_is_elevated(self):
        r = classify_funding_stress(_rates(0.30), _stress(), {}, {})
        self.assertEqual(r["modes"]["duration_shock"]["severity"], "elevated")

    def test_large_10y_move_is_acute(self):
        r = classify_funding_stress(_rates(0.55), _stress(), {}, {})
        self.assertEqual(r["modes"]["duration_shock"]["severity"], "acute")

    def test_negative_and_positive_moves_both_fire(self):
        pos = classify_funding_stress(_rates(0.30), _stress(), {}, {})
        neg = classify_funding_stress(_rates(-0.30), _stress(), {}, {})
        self.assertEqual(pos["modes"]["duration_shock"]["severity"], "elevated")
        self.assertEqual(neg["modes"]["duration_shock"]["severity"], "elevated")

    def test_parallel_up_amplifier_escalates_elevated_to_acute(self):
        r = classify_funding_stress(
            _rates(0.30, curve_shape="parallel_up"),
            _stress(), {}, {},
        )
        # 0.30pp alone is elevated; parallel_up on a positive move → acute.
        self.assertEqual(r["modes"]["duration_shock"]["severity"], "acute")


class TestCreditWideningMode(unittest.TestCase):

    def test_small_hy_move_is_none(self):
        r = classify_funding_stress({}, _stress(hyg_5d=-0.2), {}, {})
        self.assertEqual(r["modes"]["credit_widening"]["severity"], "none")

    def test_moderate_hy_drop_is_elevated(self):
        r = classify_funding_stress({}, _stress(hyg_5d=-1.2), {}, {})
        self.assertEqual(r["modes"]["credit_widening"]["severity"], "elevated")

    def test_large_hy_drop_is_acute(self):
        r = classify_funding_stress({}, _stress(hyg_5d=-2.5), {}, {})
        self.assertEqual(r["modes"]["credit_widening"]["severity"], "acute")

    def test_default_risk_differential_escalates(self):
        """HY underperforming IG escalates elevated to acute — isolates
        default-risk driven from duration-driven credit widening."""
        r = classify_funding_stress(
            {}, _stress(hyg_5d=-1.2),
            _credit(hy_ig_diff=-0.8), {},
        )
        self.assertEqual(r["modes"]["credit_widening"]["severity"], "acute")
        # Driver must name the differential so the UI can show the cause.
        drivers = r["modes"]["credit_widening"]["drivers"]
        self.assertTrue(any("differential" in d for d in drivers))

    def test_credit_regime_label_fires_mode_without_raw_hyg(self):
        """If HYG isn't in raw but credit_regime already classified
        default_risk_widening, the mode should still fire mildly."""
        r = classify_funding_stress(
            {}, {"regime": "Calm", "signals": {}, "raw": {}, "detail": {}},
            _credit(regime="default_risk_widening"), {},
        )
        self.assertEqual(r["modes"]["credit_widening"]["severity"], "mild")


class TestDollarShortageMode(unittest.TestCase):

    def test_flat_dollar_is_none(self):
        r = classify_funding_stress({}, {}, {}, _fx(dxy_5d=0.2))
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "none")

    def test_meaningful_dxy_move_is_elevated(self):
        r = classify_funding_stress({}, {}, {}, _fx(dxy_5d=1.3))
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "elevated")

    def test_large_dxy_move_is_acute(self):
        r = classify_funding_stress({}, {}, {}, _fx(dxy_5d=2.5))
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "acute")

    def test_uniform_dispersion_escalates(self):
        r = classify_funding_stress(
            {}, {}, {},
            _fx(dxy_5d=1.3, dispersion="uniform"),
        )
        # 1.3% alone is elevated; uniform dispersion escalates to acute.
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "acute")

    def test_usdcny_break_amplifies_one_tier(self):
        r = classify_funding_stress(
            {}, {}, {},
            _fx(dxy_5d=1.3, usdcny_5d=0.8),
        )
        # 1.3% DXY → elevated; USDCNY break → acute.
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "acute")

    def test_usdcny_break_alone_fires_mild_mode(self):
        r = classify_funding_stress(
            {}, {}, {},
            _fx(dxy_5d=0.3, usdcny_5d=0.7),
        )
        # DXY alone below mild; USDCNY break pushes to mild.
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "mild")

    def test_falls_back_to_stress_regime_dollar_when_fx_pack_missing(self):
        r = classify_funding_stress(
            {},
            _stress(dollar_5d=1.5),
            {},
            None,
        )
        self.assertEqual(r["modes"]["dollar_shortage"]["severity"], "elevated")


class TestLiquiditySqueezeMode(unittest.TestCase):

    def test_low_vix_is_none(self):
        r = classify_funding_stress({}, _stress(vix=15.0), {}, {})
        self.assertEqual(r["modes"]["liquidity_squeeze"]["severity"], "none")

    def test_vix_spike_requires_corroboration_to_escalate(self):
        """VIX at 28 alone should not fire elevated — needs breadth
        or safe-haven corroboration to be a regime."""
        r = classify_funding_stress({}, _stress(vix=28.0), {}, {})
        self.assertEqual(r["modes"]["liquidity_squeeze"]["severity"], "mild")
        drivers = r["modes"]["liquidity_squeeze"]["drivers"]
        self.assertTrue(any("corroboration" in d for d in drivers))

    def test_vix_with_safe_haven_is_elevated(self):
        r = classify_funding_stress(
            {}, _stress(vix=28.0, safe_haven=True), {}, {},
        )
        self.assertEqual(r["modes"]["liquidity_squeeze"]["severity"], "elevated")

    def test_vix_with_breadth_and_safe_haven_at_tail_is_acute(self):
        r = classify_funding_stress(
            {}, _stress(vix=32.0, breadth=True, safe_haven=True), {}, {},
        )
        self.assertEqual(r["modes"]["liquidity_squeeze"]["severity"], "acute")


# ---------------------------------------------------------------------------
# 2. Aggregation (primary + composite + active_modes)
# ---------------------------------------------------------------------------

class TestAggregation(unittest.TestCase):

    def test_nothing_firing_is_none(self):
        r = classify_funding_stress(
            _rates(0.02), _stress(vix=14.0, hyg_5d=-0.1),
            _credit(), _fx(dxy_5d=0.1),
        )
        self.assertEqual(r["primary_mode"], "none")
        self.assertEqual(r["composite_severity"], "none")
        self.assertEqual(r["active_modes"], [])

    def test_single_mode_fires_as_primary(self):
        r = classify_funding_stress(
            _rates(0.30),                      # duration: elevated
            _stress(vix=15.0, hyg_5d=-0.1),    # quiet elsewhere
            _credit(), _fx(dxy_5d=0.1),
        )
        self.assertEqual(r["primary_mode"], "duration_shock")
        self.assertEqual(r["composite_severity"], "elevated")
        self.assertEqual(r["active_modes"], ["duration_shock"])

    def test_composite_is_max_severity(self):
        # Duration elevated + credit acute → composite acute.
        r = classify_funding_stress(
            _rates(0.30),
            _stress(hyg_5d=-2.5),
            _credit(hy_ig_diff=-0.9),
            {},
        )
        self.assertEqual(r["composite_severity"], "acute")
        self.assertEqual(r["primary_mode"], "credit_widening")
        self.assertIn("duration_shock", r["active_modes"])
        self.assertIn("credit_widening", r["active_modes"])

    def test_priority_tie_break_favours_duration(self):
        """When duration + liquidity fire at the same severity, duration
        wins because it's first in _MODE_PRIORITY."""
        # Duration elevated + liquidity mild+corroborated (elevated).
        r = classify_funding_stress(
            _rates(0.30),                                # duration elevated
            _stress(vix=27.0, safe_haven=True),          # liquidity elevated
            _credit(),
            _fx(dxy_5d=0.1),
        )
        self.assertEqual(r["composite_severity"], "elevated")
        self.assertEqual(r["primary_mode"], "duration_shock")

    def test_active_modes_returned_in_priority_order(self):
        """All four firing → active_modes sorted by _MODE_PRIORITY."""
        r = classify_funding_stress(
            _rates(0.30),
            _stress(vix=28.0, hyg_5d=-1.3, breadth=True, safe_haven=True),
            _credit(hy_ig_diff=-0.9),
            _fx(dxy_5d=1.5, dispersion="uniform"),
        )
        self.assertEqual(
            r["active_modes"],
            list(_MODE_PRIORITY),  # all four in priority order
        )


# ---------------------------------------------------------------------------
# 3. Availability signal
# ---------------------------------------------------------------------------

class TestAvailability(unittest.TestCase):

    def test_all_inputs_missing_returns_unavailable(self):
        r = classify_funding_stress(None, None, None, None)
        self.assertFalse(r["available"])
        # Every mode should carry an "unavailable" rationale.
        for name, mode in r["modes"].items():
            self.assertIn("unavailable", mode["rationale"],
                          f"{name} should flag unavailable input")

    def test_quiet_tape_is_available_but_nothing_firing(self):
        """Available=True when there's enough input to classify, even
        if nothing stresses — distinct from "we couldn't look"."""
        r = classify_funding_stress(
            _rates(0.02),
            _stress(vix=14.0, hyg_5d=0.2),
            _credit(),
            _fx(dxy_5d=0.1),
        )
        self.assertTrue(r["available"])
        self.assertEqual(r["composite_severity"], "none")

    def test_partial_inputs_still_classify(self):
        """Only rates input: duration fires normally, others degrade."""
        r = classify_funding_stress(_rates(0.30), None, None, None)
        self.assertEqual(r["modes"]["duration_shock"]["severity"], "elevated")
        self.assertFalse(r["modes"]["credit_widening"]["fired"])
        self.assertFalse(r["modes"]["dollar_shortage"]["fired"])
        self.assertFalse(r["modes"]["liquidity_squeeze"]["fired"])
        self.assertTrue(r["available"])


# ---------------------------------------------------------------------------
# 4. Invariants
# ---------------------------------------------------------------------------

class TestInvariants(unittest.TestCase):

    def test_severity_order_is_canonical(self):
        self.assertEqual(_SEVERITY_ORDER, ("none", "mild", "elevated", "acute"))

    def test_mode_priority_covers_all_modes(self):
        """Every mode name emitted by the classifier must appear in
        _MODE_PRIORITY or the tie-break logic will crash."""
        r = classify_funding_stress(
            _rates(0.30),
            _stress(vix=28.0, hyg_5d=-1.3, breadth=True, safe_haven=True),
            _credit(hy_ig_diff=-0.9),
            _fx(dxy_5d=1.5, dispersion="uniform"),
        )
        for name in r["modes"]:
            self.assertIn(name, _MODE_PRIORITY, f"{name} not in priority list")


if __name__ == "__main__":
    unittest.main()
