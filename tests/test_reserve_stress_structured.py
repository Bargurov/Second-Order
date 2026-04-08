"""
tests/test_reserve_stress_structured.py

Focused tests for the reserve-stress overlay structured-signal rewrite.

Covers the four cases the task brief calls out:

  1. Systemic Stress with real credit/funding pressure → meta-bonus fires.
  2. Geopolitical Stress without credit widening → NO meta-bonus,
     no reserve-stress boost.
  3. Dollar move scoring does not double-count through stacked
     threshold bonuses (non-stacking tiered DXY contribution).
  4. Stale / partial stress payload degrades cleanly without crashing
     or emitting bogus signals.

These complement the scenario-level test_reserve_stress_overlay.py
suite — that file exercises channel routing + country ranking, these
pin down the structured parsing + scoring rules the audit flagged.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reserve_stress_overlay as rs


# ---------------------------------------------------------------------------
# Helpers — mirror the real ``market_check.compute_stress_regime`` shape
# so we can test the overlay's parsing against payloads that match what
# the live pipeline actually produces.
# ---------------------------------------------------------------------------


def _tot(*, crude_5d: float, dxy_5d: float, theme: str = "none") -> dict:
    return {
        "available": True,
        "stale": False,
        "signals": {
            "crude_5d": crude_5d,
            "dxy_5d": dxy_5d,
            "matched_theme": theme,
            "thresholds": "",
        },
    }


def _rates(*, tip_5d: float) -> dict:
    return {
        "regime": "Mixed",
        "real_proxy": {"label": "TIP", "value": 108.0, "change_5d": tip_5d},
        "nominal": {"label": "10Y", "value": 4.2, "change_5d": 0.1},
        "breakeven_proxy": {"label": "BE", "change_5d": None},
    }


def _stress_systemic(
    *, dollar_5d: float, credit_5d: float,
) -> dict:
    """A payload shaped like market_check's 'Systemic Stress' output:
    VIX elevated + term inversion + credit widening all firing."""
    return {
        "regime": "Systemic Stress",
        "signals": {
            "vix_elevated":        True,
            "term_inversion":      True,
            "credit_widening":     True,
            "safe_haven_bid":      True,
            "breadth_deterioration": False,
        },
        "detail": {
            "safe_haven": {
                "label": "Safe Haven Flows",
                "assets": {"Gold": 1.2, "Dollar": dollar_5d, "Long Bonds": 0.5},
            },
            "credit": {
                "label": "Credit Stress",
                "spread_5d": credit_5d,
            },
        },
    }


def _stress_geopolitical(
    *, dollar_5d: float, credit_5d: float,
) -> dict:
    """A payload shaped like market_check's 'Geopolitical Stress' output:
    VIX elevated + safe-haven flows but credit widening EXPLICITLY off
    — the regime that used to false-positive under the label-scraping
    implementation."""
    return {
        "regime": "Geopolitical Stress",
        "signals": {
            "vix_elevated":        True,
            "term_inversion":      False,
            "credit_widening":     False,   # ← the key guard
            "safe_haven_bid":      True,
            "breadth_deterioration": False,
        },
        "detail": {
            "safe_haven": {
                "label": "Safe Haven Flows",
                "assets": {"Gold": 1.5, "Dollar": dollar_5d, "Long Bonds": 0.3},
            },
            "credit": {
                "label": "Credit Stress",
                "spread_5d": credit_5d,
            },
        },
    }


def _drivers_of(out: dict) -> set:
    if not out.get("vulnerable"):
        return set()
    return set(out["vulnerable"][0]["drivers"])


# ---------------------------------------------------------------------------
# Case 1: Systemic Stress with real credit/funding pressure
# ---------------------------------------------------------------------------


class TestSystemicStressMetaBonus(unittest.TestCase):
    """Systemic Stress + credit_widening should fire the structured
    cross-confirmation bonus and add ``risk_off_regime`` to drivers."""

    def test_systemic_stress_with_credit_widening_fires_bonus(self):
        out = rs.compute_reserve_stress(
            "Credit blow-out with vol spike and term backwardation",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.6, theme="none"),
            rates_context=_rates(tip_5d=-0.4),
            stress_regime=_stress_systemic(dollar_5d=1.6, credit_5d=0.9),
        )
        drivers = _drivers_of(out)
        self.assertIn("risk_off_regime", drivers)
        self.assertIn("credit_widening", drivers)
        self.assertIn("dollar_rally", drivers)
        self.assertIn("real_yield_rise", drivers)
        self.assertEqual(out["pressure_label"], "elevated")

    def test_systemic_stress_without_credit_widening_does_not_fire_bonus(self):
        """Systemic Stress regime label but the structured flag is
        somehow off (stub / misconfigured mock): the meta-bonus must
        NOT fire.  Both conditions — label enum AND signal — must hold.
        """
        stress = _stress_systemic(dollar_5d=1.6, credit_5d=0.0)
        stress["signals"]["credit_widening"] = False
        out = rs.compute_reserve_stress(
            "Label says Systemic but credit flag is off",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.6, theme="none"),
            rates_context=_rates(tip_5d=-0.4),
            stress_regime=stress,
        )
        drivers = _drivers_of(out)
        self.assertNotIn(
            "risk_off_regime", drivers,
            "meta-bonus must require BOTH the label enum and the signal",
        )


# ---------------------------------------------------------------------------
# Case 2: Geopolitical Stress without funding stress → no boost
# ---------------------------------------------------------------------------


class TestGeopoliticalStressDoesNotBoost(unittest.TestCase):
    """The audit false-positive: a 'Geopolitical Stress' regime
    (VIX + safe-haven, no credit widening) was matching the old
    substring scrape on ``"stress"`` and adding +15.  Under the
    structured rewrite the overlay must NOT add any funding bonus."""

    def test_geopolitical_stress_no_credit_no_dollar_boost(self):
        """VIX spike + safe-haven bid + NO credit widening, NO dollar
        rally — reserve stress should sit at zero."""
        out = rs.compute_reserve_stress(
            "Middle East conflict escalates",
            "Risk-off flows into gold and Treasuries on flight-to-safety.",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=0.1, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress_geopolitical(dollar_5d=0.1, credit_5d=0.0),
        )
        drivers = _drivers_of(out)
        self.assertNotIn("risk_off_regime", drivers)
        self.assertNotIn("credit_widening", drivers)
        self.assertEqual(out["pressure_score"], 0)
        self.assertEqual(out["pressure_label"], "contained")

    def test_geopolitical_stress_with_dollar_move_only_counts_dollar(self):
        """A Geopolitical Stress regime with a 1.2% DXY move should
        score only the dollar tier — NOT the label-scrape bonus."""
        out = rs.compute_reserve_stress(
            "Regional conflict drives dollar bid",
            "",
            terms_of_trade=_tot(crude_5d=0.2, dxy_5d=1.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress_geopolitical(dollar_5d=1.2, credit_5d=0.0),
        )
        drivers = _drivers_of(out)
        self.assertIn("dollar_rally", drivers)
        self.assertNotIn("risk_off_regime", drivers)
        self.assertNotIn("credit_widening", drivers)
        # Only the DXY strong tier should fire: 25.
        self.assertEqual(out["pressure_score"], rs._W_DXY_STRONG)

    def test_geopolitical_label_with_credit_widening_still_not_bonus(self):
        """Even if credit_widening is somehow TRUE on a Geopolitical
        regime (stub mismatch), the cross-confirmation bonus requires
        BOTH the exact "Systemic Stress" enum and the signal.  It
        should still not fire — the credit_widening driver alone is
        enough to reflect the actual credit move.
        """
        stress = _stress_geopolitical(dollar_5d=1.6, credit_5d=0.9)
        stress["signals"]["credit_widening"] = True
        out = rs.compute_reserve_stress(
            "Geopolitical shock with credit stress",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.6, theme="none"),
            rates_context=_rates(tip_5d=-0.4),
            stress_regime=stress,
        )
        drivers = _drivers_of(out)
        self.assertIn("credit_widening", drivers)
        self.assertNotIn(
            "risk_off_regime", drivers,
            "the cross-confirmation bonus is gated on BOTH regime enum "
            "and signal; Geopolitical label fails the enum check",
        )

    def test_generic_stress_label_substring_does_not_match(self):
        """Free-form regime strings like 'Risk-off / funding stress'
        no longer match — the old substring scrape is gone.
        """
        stress = {
            "regime": "Risk-off / funding stress",
            "signals": {"credit_widening": True},
            "detail": {
                "safe_haven": {"assets": {"Dollar": 1.2}},
                "credit": {"spread_5d": 0.8},
            },
        }
        out = rs.compute_reserve_stress(
            "Label scraping regression test",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=stress,
        )
        drivers = _drivers_of(out)
        self.assertIn("credit_widening", drivers)
        self.assertNotIn(
            "risk_off_regime", drivers,
            "substring label matching on 'stress' must not fire the bonus",
        )


# ---------------------------------------------------------------------------
# Case 3: Dollar move scoring — non-stacking tiers
# ---------------------------------------------------------------------------


class TestDollarNonStacking(unittest.TestCase):
    """DXY contribution is now a non-stacking tier lookup.  A 2.5%
    print contributes 35 (extreme tier only), not 15+15+20 = 50."""

    def _isolated_dxy_score(self, dxy_5d: float) -> int:
        """Run the overlay with DXY as the only active signal and
        return the resulting pressure_score."""
        out = rs.compute_reserve_stress(
            "dollar isolation test",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=dxy_5d, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime={
                "regime": "Calm",
                "signals": {"credit_widening": False},
                "detail": {
                    "safe_haven": {"assets": {"Dollar": dxy_5d}},
                    "credit": {"spread_5d": 0.0},
                },
            },
        )
        return out["pressure_score"]

    def test_dxy_below_moderate_contributes_zero(self):
        self.assertEqual(self._isolated_dxy_score(0.3), 0)

    def test_dxy_at_moderate_tier_alone(self):
        self.assertEqual(self._isolated_dxy_score(0.7), rs._W_DXY_MODERATE)

    def test_dxy_at_strong_tier_alone(self):
        """1.5% must fire the strong tier, NOT moderate + strong."""
        self.assertEqual(self._isolated_dxy_score(1.5), rs._W_DXY_STRONG)
        self.assertNotEqual(
            self._isolated_dxy_score(1.5),
            rs._W_DXY_MODERATE + rs._W_DXY_STRONG,
            "DXY tiers must not stack",
        )

    def test_dxy_at_extreme_tier_alone(self):
        """2.5% must fire the extreme tier alone — no stacking."""
        self.assertEqual(self._isolated_dxy_score(2.5), rs._W_DXY_EXTREME)
        self.assertNotEqual(
            self._isolated_dxy_score(2.5),
            rs._W_DXY_MODERATE + rs._W_DXY_STRONG + rs._W_DXY_EXTREME,
            "DXY tiers must not stack",
        )

    def test_dxy_tier_monotonic_in_move_size(self):
        """Bigger move → score at least as high as smaller move."""
        s_mod = self._isolated_dxy_score(0.8)
        s_str = self._isolated_dxy_score(1.3)
        s_ext = self._isolated_dxy_score(2.7)
        self.assertLessEqual(s_mod, s_str)
        self.assertLessEqual(s_str, s_ext)

    def test_total_pressure_bounded_even_with_every_driver(self):
        """A multi-driver shock must still cap at 100 after the
        non-stacking rewrite."""
        out = rs.compute_reserve_stress(
            "Everything at once",
            "",
            terms_of_trade=_tot(crude_5d=10.0, dxy_5d=3.0, theme="oil"),
            rates_context=_rates(tip_5d=-1.0),
            stress_regime=_stress_systemic(dollar_5d=3.0, credit_5d=1.5),
        )
        self.assertLessEqual(out["pressure_score"], 100)
        self.assertEqual(out["pressure_label"], "elevated")

    def test_dxy_extreme_ceiling_below_old_stacked_ceiling(self):
        """Regression guard: the extreme tier must not reach the old
        stacked total (moderate + strong + extreme = 50 under the
        original weights).  The whole point of the fix is that a
        single DXY signal can no longer consume 50 points.
        """
        self.assertLess(self._isolated_dxy_score(2.5), 50)


# ---------------------------------------------------------------------------
# Case 4: Stale / partial stress payload
# ---------------------------------------------------------------------------


class TestStaleOrPartialStressPayload(unittest.TestCase):
    """The overlay must never crash or emit bogus drivers when the
    stress_regime payload is missing, partial, or shaped unexpectedly."""

    def test_none_stress_regime_degrades_cleanly(self):
        out = rs.compute_reserve_stress(
            "Dollar rally with no stress payload",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=None,
        )
        self.assertNotIn("risk_off_regime", _drivers_of(out))
        self.assertNotIn("credit_widening", _drivers_of(out))
        self.assertTrue(out.get("stale"))
        self.assertIn("dollar_rally", _drivers_of(out))

    def test_missing_signals_dict_falls_back_to_numeric(self):
        """A payload without a signals dict should still pick up
        credit widening from the numeric detail.credit.spread_5d.

        We pair the credit widening with a DXY move large enough to
        resolve the usd_funding_stress channel so the vulnerable list
        is non-empty and the drivers surface through.  Without a
        channel the overlay ranks no countries and the driver set is
        not observable, which is a separate code path.
        """
        stress = {
            "regime": "Calm",
            # signals key omitted entirely — force the numeric fallback
            "detail": {
                "safe_haven": {"assets": {"Dollar": 1.2}},
                "credit": {"spread_5d": 0.8},
            },
        }
        out = rs.compute_reserve_stress(
            "Credit widening without a signals dict",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=stress,
        )
        drivers = _drivers_of(out)
        self.assertIn("credit_widening", drivers)
        self.assertNotIn(
            "risk_off_regime", drivers,
            "no regime enum → no meta bonus even if credit widens",
        )

    def test_missing_detail_dict_does_not_crash(self):
        stress = {"regime": "Calm", "signals": {}}
        out = rs.compute_reserve_stress(
            "Stress payload missing detail block",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=0.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=stress,
        )
        # No crash is the main assertion; drivers should be empty.
        self.assertEqual(out["pressure_score"], 0)

    def test_stress_regime_wrong_type_degrades_cleanly(self):
        """A stress_regime that isn't a dict (e.g. a stringified
        payload from a broken upstream) must not raise."""
        out = rs.compute_reserve_stress(
            "Stress payload wrong type",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=0.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime="this-is-not-a-dict",  # type: ignore[arg-type]
        )
        self.assertNotIn("risk_off_regime", _drivers_of(out))
        self.assertNotIn("credit_widening", _drivers_of(out))

    def test_empty_regime_string_does_not_fire_bonus(self):
        stress = {
            "regime": "",
            "signals": {"credit_widening": True},
            "detail": {
                "safe_haven": {"assets": {"Dollar": 1.2}},
                "credit": {"spread_5d": 0.9},
            },
        }
        out = rs.compute_reserve_stress(
            "Empty regime label",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.2, theme="none"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=stress,
        )
        drivers = _drivers_of(out)
        self.assertNotIn("risk_off_regime", drivers)
        # credit_widening still fires from the structured signal
        self.assertIn("credit_widening", drivers)


if __name__ == "__main__":
    unittest.main()
