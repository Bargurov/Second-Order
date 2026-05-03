"""Tests for credit_transmission — the funding-stress + equity/credit separator."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from credit_regime import classify_credit_regime
from credit_transmission import (
    compute_credit_transmission,
    _FUNDING_STRESS_LABELS,
    _EQUITY_VS_CREDIT_LABELS,
)


def _stress(vix_elevated=False, safe_haven_bid=False):
    return {
        "regime": "Calm",
        "signals": {
            "vix_elevated": vix_elevated,
            "safe_haven_bid": safe_haven_bid,
            "term_inversion": False,
            "credit_widening": False,
            "breadth_deterioration": False,
        },
        "raw": {},
    }


def _rates(tip_5d=0.0):
    return {
        "regime": "Mixed",
        "nominal": {"change_5d": 0.0},
        "real_proxy": {"change_5d": tip_5d},
        "breakeven_proxy": {"change_5d": 0.0},
        "raw": {},
    }


# ---------------------------------------------------------------------------
# Funding-stress classifier
# ---------------------------------------------------------------------------

class TestFundingStress(unittest.TestCase):
    def test_acute_when_default_widening_and_vix_elevated(self):
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(vix_elevated=True), _rates())
        self.assertEqual(res["funding_stress"], "acute")
        self.assertEqual(res["funding_stress_label"],
                         _FUNDING_STRESS_LABELS["acute"])

    def test_elevated_when_default_widening_but_vix_calm(self):
        """Credit deterioration without equity stress — still a real signal."""
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(vix_elevated=False), _rates())
        self.assertEqual(res["funding_stress"], "elevated")

    def test_elevated_on_duration_widening_with_real_yields_rising(self):
        """Duration widening + real rates up → rate-led financial tightening."""
        cr = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)
        # TIP falling = real yields rising (−0.5 clears −0.3 threshold).
        res = compute_credit_transmission(cr, _stress(), _rates(tip_5d=-0.5))
        self.assertEqual(res["funding_stress"], "elevated")
        self.assertTrue(res["signals"]["real_yield_rising"])

    def test_contained_on_duration_widening_without_rate_pressure(self):
        cr = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)
        res = compute_credit_transmission(cr, _stress(), _rates(tip_5d=0.0))
        self.assertEqual(res["funding_stress"], "contained")

    def test_insulated_on_risk_on(self):
        cr = classify_credit_regime(hy_5d=+1.1, ig_5d=+0.2)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertEqual(res["funding_stress"], "insulated")

    def test_unavailable_when_credit_regime_unavailable(self):
        cr = classify_credit_regime(hy_5d=None, ig_5d=None)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertEqual(res["funding_stress"], "unavailable")
        self.assertFalse(res["available"])


# ---------------------------------------------------------------------------
# Equity-vs-credit separator
# ---------------------------------------------------------------------------

class TestEquityVsCredit(unittest.TestCase):
    def test_equity_only_riskoff_when_vix_elevated_but_credit_quiet(self):
        cr = classify_credit_regime(hy_5d=-0.1, ig_5d=-0.1)  # quiet
        res = compute_credit_transmission(cr, _stress(vix_elevated=True), _rates())
        self.assertEqual(res["equity_vs_credit"], "equity_only_riskoff")

    def test_credit_only_deterioration_when_credit_wide_but_vix_calm(self):
        """The insidious case — credit bleeding, equity complacent."""
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(vix_elevated=False,
                                                      safe_haven_bid=False), _rates())
        self.assertEqual(res["equity_vs_credit"], "credit_only_deterioration")

    def test_synchronized_stress_when_both_firing(self):
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(vix_elevated=True,
                                                      safe_haven_bid=True), _rates())
        self.assertEqual(res["equity_vs_credit"], "synchronized_stress")

    def test_synchronized_calm_when_nothing_firing(self):
        cr = classify_credit_regime(hy_5d=+0.3, ig_5d=+0.1)  # tightening-ish
        # hy=+0.3 above floor=0.5? No — 0.3 < 0.5 noise floor so regime='quiet'
        # Need regime 'quiet' or a tightening for synchronized_calm.
        cr_quiet = classify_credit_regime(hy_5d=0.1, ig_5d=-0.05)
        res = compute_credit_transmission(cr_quiet, _stress(), _rates())
        self.assertEqual(res["equity_vs_credit"], "synchronized_calm")

    def test_synchronized_calm_on_risk_on_tightening(self):
        cr = classify_credit_regime(hy_5d=+1.1, ig_5d=+0.2)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertEqual(res["equity_vs_credit"], "synchronized_calm")

    def test_all_equity_vs_credit_labels_registered(self):
        valid = set(_EQUITY_VS_CREDIT_LABELS.keys())
        cr = classify_credit_regime(hy_5d=None, ig_5d=None)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertIn(res["equity_vs_credit"], valid)


# ---------------------------------------------------------------------------
# Sector exposures
# ---------------------------------------------------------------------------

class TestSectorExposures(unittest.TestCase):
    def test_default_led_sectors_on_default_risk_widening(self):
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertIn("hy_issuers", res["sector_exposures"])
        self.assertIn("leveraged_growth", res["sector_exposures"])

    def test_rate_led_sectors_on_duration_widening(self):
        cr = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertIn("banks", res["sector_exposures"])
        self.assertIn("reits", res["sector_exposures"])

    def test_empty_on_risk_on(self):
        cr = classify_credit_regime(hy_5d=+1.1, ig_5d=+0.2)
        res = compute_credit_transmission(cr, _stress(), _rates())
        self.assertEqual(res["sector_exposures"], [])

    def test_real_yield_rise_amplifies_rate_led_cohort(self):
        """Real yields rising adds REITs/banks even on a default-led regime."""
        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_credit_transmission(cr, _stress(), _rates(tip_5d=-0.6))
        self.assertIn("reits", res["sector_exposures"])

    def test_sector_exposures_deduplicated(self):
        cr = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)
        res = compute_credit_transmission(cr, _stress(), _rates(tip_5d=-0.6))
        self.assertEqual(len(res["sector_exposures"]),
                         len(set(res["sector_exposures"])))


# ---------------------------------------------------------------------------
# Reserve-stress tiered integration
# ---------------------------------------------------------------------------

class TestReserveStressUsesTieredCredit(unittest.TestCase):
    """reserve_stress's credit contribution should rise for default-risk widening
    and drop for duration-only widening, compared to the legacy binary signal."""

    def _stress_with_spread(self, spread_5d: float) -> dict:
        return {
            "regime": "Calm",
            "signals": {"credit_widening": spread_5d >= 0.5,
                        "vix_elevated": False, "term_inversion": False,
                        "safe_haven_bid": False, "breadth_deterioration": False},
            "raw": {"credit_spread_5d": spread_5d,
                    "shy_5d": 0.0, "hyg_5d": -spread_5d},
            "detail": {
                "credit": {"spread_5d": spread_5d},
                "safe_haven": {"assets": {"Dollar": 0.0}},
            },
        }

    def test_default_widening_scores_higher_than_duration(self):
        from reserve_stress_overlay import _credit_score_from_regime
        default_cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        duration_cr = classify_credit_regime(hy_5d=-0.9, ig_5d=-0.8)

        default_score, default_tag = _credit_score_from_regime(default_cr)
        duration_score, duration_tag = _credit_score_from_regime(duration_cr)

        self.assertGreater(default_score, duration_score)
        self.assertEqual(default_tag, "credit_default_widening")
        self.assertEqual(duration_tag, "credit_duration_widening")

    def _drivers_from_response(self, res: dict) -> list[str]:
        """Drivers surface on each vulnerable/insulated entry.  Pull the union."""
        drivers: list[str] = []
        for bucket_key in ("vulnerable", "insulated"):
            for entry in res.get(bucket_key) or []:
                for d in entry.get("drivers") or []:
                    if d not in drivers:
                        drivers.append(d)
        return drivers

    def test_regime_tiered_driver_replaces_binary_driver(self):
        from reserve_stress_overlay import compute_reserve_stress

        cr = classify_credit_regime(hy_5d=-1.5, ig_5d=-0.3)
        res = compute_reserve_stress(
            headline="Bond market signals default stress",
            mechanism_text="high-yield spreads widening relative to IG",
            terms_of_trade={"available": True, "signals": {
                "crude_5d": 0.0, "dxy_5d": 1.2,    # trigger a channel so vulnerable list populates
                "matched_theme": "none"}},
            rates_context=_rates(),
            stress_regime=self._stress_with_spread(0.6),
            credit_regime=cr,
        )
        drivers = self._drivers_from_response(res)
        self.assertIn("credit_default_widening", drivers)
        # The legacy binary driver should NOT double-fire when the tiered
        # signal has already contributed.
        self.assertNotIn("credit_widening", drivers)

    def test_legacy_binary_driver_used_when_credit_regime_missing(self):
        from reserve_stress_overlay import compute_reserve_stress
        res = compute_reserve_stress(
            headline="h",
            mechanism_text="m",
            terms_of_trade={"available": True, "signals": {
                "crude_5d": 0.0, "dxy_5d": 1.2,
                "matched_theme": "none"}},
            rates_context=_rates(),
            stress_regime=self._stress_with_spread(0.6),
            credit_regime=None,
        )
        drivers = self._drivers_from_response(res)
        self.assertIn("credit_widening", drivers)


if __name__ == "__main__":
    unittest.main()
