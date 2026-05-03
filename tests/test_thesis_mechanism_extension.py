"""Tests for the extended mechanism-type classifiers.

Covers:
  - classify_thesis now fires supply_shock, flight_to_quality, reflation
    when policy/inflation keywords are silent.
  - cross_asset_confirmation._EXPECTED has entries for the new thesis types.
  - compute_cross_asset_confirmation returns confirms/disconfirms using the
    new per-mechanism expected-direction maps.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_yield_context import classify_thesis, THESIS_LABELS
from cross_asset_confirmation import (
    compute_cross_asset_confirmation,
    _EXPECTED,
    _THESIS_LABELS,
    _CURVE_EXPECTED,
)


class TestExtendedThesisClassifier(unittest.TestCase):
    """classify_thesis now covers supply_shock / flight_to_quality / reflation."""

    def test_flight_to_quality_fires_on_war(self):
        res = classify_thesis("Missile strike escalates into regional war",
                              "military strike on oil infrastructure")
        # Crisis/war keywords take priority over supply_shock.
        self.assertEqual(res["thesis"], "flight_to_quality")

    def test_supply_shock_fires_on_shipping_disruption(self):
        res = classify_thesis(
            "Houthi attacks disrupt Red Sea shipping corridor", "",
        )
        self.assertEqual(res["thesis"], "supply_shock")

    def test_reflation_fires_on_stimulus(self):
        res = classify_thesis(
            "China unveils 500bn yuan stimulus package and tax cut",
            "infrastructure bill approved",
        )
        self.assertEqual(res["thesis"], "reflation")

    def test_inflation_keywords_still_take_precedence_over_mechanism(self):
        """Inflation thesis beats supply_shock when both keywords fire."""
        res = classify_thesis(
            "Red Sea shipping disruption drives fuel cost spike", "",
        )
        # "fuel cost" is in _INFLATIONARY_KW; that axis wins over supply_shock.
        self.assertEqual(res["thesis"], "inflationary")

    def test_none_when_no_keyword_matches(self):
        res = classify_thesis("Local company releases earnings report", "")
        self.assertEqual(res["thesis"], "none")

    def test_all_labels_registered(self):
        for thesis in ("supply_shock", "flight_to_quality", "reflation"):
            self.assertIn(thesis, THESIS_LABELS)


class TestExpectedMapsForNewMechanisms(unittest.TestCase):
    """_EXPECTED must have an entry for every new mechanism the classifier can emit."""

    def test_every_new_mechanism_has_expected_map(self):
        for mech in ("supply_shock", "flight_to_quality", "reflation"):
            self.assertIn(mech, _EXPECTED)
            self.assertIn(mech, _THESIS_LABELS)
            self.assertIn(mech, _CURVE_EXPECTED)

    def test_supply_shock_expects_commodity_up_and_breakeven_up(self):
        expected = _EXPECTED["supply_shock"]
        self.assertEqual(expected["commodity"], "up")
        self.assertEqual(expected["breakeven"], "up")
        self.assertEqual(expected["credit"], "up")

    def test_flight_to_quality_expects_bonds_bid_and_dxy_up(self):
        expected = _EXPECTED["flight_to_quality"]
        self.assertEqual(expected["nominal_yield"], "down")
        self.assertEqual(expected["real_yield"], "up")   # TIP rallies
        self.assertEqual(expected["fx"], "up")           # USD safe-haven
        self.assertEqual(expected["credit"], "up")       # spreads widen

    def test_reflation_expects_bear_steepener_with_commodity_up(self):
        expected = _EXPECTED["reflation"]
        self.assertEqual(expected["nominal_yield"], "up")
        self.assertEqual(expected["commodity"], "up")
        self.assertEqual(expected["credit"], "down")     # HY outperforms


class TestConfirmationMatrixWithNewMechanisms(unittest.TestCase):
    """compute_cross_asset_confirmation must produce confirms for new mechanisms."""

    def _channel(self, move, z, available=True):
        return {"move_5d": move, "z": z, "available": available,
                "label": "x", "unit": "%"}

    def test_supply_shock_confirmed_by_commodity_and_breakeven(self):
        channels = {
            "nominal_yield": self._channel(0.05, 0.2),
            "real_yield":    self._channel(-0.1, 0.2),
            "breakeven":     self._channel(0.25, 1.2),   # up → confirm
            "fx":            self._channel(0.3, 0.5),
            "credit":        self._channel(0.6, 1.0),    # up → confirm
            "commodity":     self._channel(4.0, 1.4),    # up → confirm
        }
        res = compute_cross_asset_confirmation("supply_shock", channels)
        self.assertIn("breakeven", res["confirms"])
        self.assertIn("commodity", res["confirms"])
        self.assertIn("credit", res["confirms"])
        self.assertGreater(res["confirm_score"], res["disconfirm_score"])
        self.assertIn(res["verdict"], ("strong_confirm", "weak_confirm"))

    def test_flight_to_quality_disconfirmed_by_risk_on_move(self):
        # Risk-on tape: nominals up, real yields up, equity-favorable.
        channels = {
            "nominal_yield": self._channel(0.25, 1.3),   # up — disconfirms flight
            "real_yield":    self._channel(-0.7, 1.4),   # TIP down — disconfirms
            "breakeven":     self._channel(0.05, 0.3),
            "fx":            self._channel(-0.9, 1.3),   # DXY down — disconfirms
            "credit":        self._channel(-0.8, 1.0),   # tightening — disconfirms
            "commodity":     self._channel(0.5, 0.3),
        }
        res = compute_cross_asset_confirmation("flight_to_quality", channels)
        self.assertGreater(res["disconfirm_score"], res["confirm_score"])
        self.assertIn(res["verdict"], ("weak_disconfirm", "strong_disconfirm", "mixed"))

    def test_reflation_mixed_when_commodity_up_but_real_yields_up(self):
        channels = {
            "nominal_yield": self._channel(0.30, 1.5),   # up → confirm
            "real_yield":    self._channel(+0.8, 1.4),   # TIP up → disconfirm (expected down)
            "breakeven":     self._channel(0.05, 0.3),
            "fx":            self._channel(0.3, 0.4),
            "credit":        self._channel(0.0, 0.2),
            "commodity":     self._channel(2.5, 0.9),    # up → confirm
        }
        res = compute_cross_asset_confirmation("reflation", channels)
        # Confirm on nominal_yield + commodity; disconfirm on real_yield.
        self.assertIn("nominal_yield", res["confirms"])
        self.assertIn("real_yield", res["disconfirms"])


if __name__ == "__main__":
    unittest.main()
