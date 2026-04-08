"""
tests/test_reserve_stress_overlay.py

Focused tests for the Current Account + FX Reserve Stress overlay.

Covers the four cases the task brief calls out:

  1. Oil-shock pressure on deficit importers
  2. Dollar-funding stress / reserve-vulnerability case
  3. Mixed or unclear exposure
  4. Stale / unavailable context

Plus a few adjacent properties: ranking stability, driver-tag emission,
channel resolution edge cases, and contract-shape invariants.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reserve_stress_overlay as rs


# ---------------------------------------------------------------------------
# Helpers: build the minimal upstream blocks the overlay reads from
# ---------------------------------------------------------------------------


def _tot(
    *,
    crude_5d: float | None = None,
    dxy_5d: float | None = None,
    theme: str = "none",
    stale: bool = False,
    available: bool = True,
) -> dict:
    """Minimal terms_of_trade dict matching the real schema."""
    return {
        "available": available,
        "stale": stale,
        "signals": {
            "crude_5d": crude_5d,
            "dxy_5d": dxy_5d,
            "matched_theme": theme,
            "thresholds": "crude |5d|>=3% / DXY |5d|>=1.0",
        },
    }


def _rates(*, tip_5d: float | None = None, regime: str = "Mixed") -> dict:
    """Minimal rates_context dict — the overlay reads the real-yield proxy."""
    return {
        "regime": regime,
        "real_proxy": {"label": "TIP", "value": 108.0, "change_5d": tip_5d},
        "nominal": {"label": "10Y", "value": 4.2, "change_5d": 0.1},
        "breakeven_proxy": {"label": "BE proxy", "change_5d": None},
    }


def _stress(
    *,
    dollar_5d: float | None = None,
    credit_5d: float | None = None,
    regime: str | None = None,
    signals: dict | None = None,
) -> dict:
    """Minimal stress_regime dict with only the fields the overlay reads.

    Populates ``signals.credit_widening`` from ``credit_5d`` using the
    same rule ``market_check.compute_stress_regime`` applies (spread
    move >= 0.5% → True) so the overlay's structured-signal path sees
    the expected flag.  Callers can still pass an explicit ``signals``
    dict to assert specific classifier states.
    """
    auto_signals: dict = {}
    if credit_5d is not None and credit_5d >= 0.5:
        auto_signals["credit_widening"] = True
    if signals:
        auto_signals.update(signals)
    return {
        "regime": regime or "Mixed",
        "signals": auto_signals,
        "detail": {
            "safe_haven": {
                "label": "Safe Haven Flows",
                "assets": {"Gold": None, "Dollar": dollar_5d, "Long Bonds": None},
                "inflow_count": 0,
                "status": "calm",
                "explanation": "",
            },
            "credit": {
                "label": "Credit Stress",
                "spread_5d": credit_5d,
                "status": "calm",
                "explanation": "",
            },
        },
    }


# ---------------------------------------------------------------------------
# Case 1: Oil-shock pressure on deficit importers
# ---------------------------------------------------------------------------


class TestOilShockPressureOnImporters(unittest.TestCase):
    """A clean crude rally with dollar flat should route to oil_import_squeeze."""

    def test_oil_only_routes_to_oil_import_squeeze(self):
        out = rs.compute_reserve_stress(
            "OPEC slashes output by 2 mbpd",
            "Supply shock raises crude price; input costs transmit to importers.",
            terms_of_trade=_tot(crude_5d=5.5, dxy_5d=0.2, theme="oil"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress(dollar_5d=0.2, credit_5d=0.1),
        )
        self.assertTrue(out["available"])
        self.assertEqual(out["dominant_channel"], "oil_import_squeeze")
        self.assertIn("oil_squeeze", out["vulnerable"][0]["drivers"])
        # Deficit importers must dominate the vulnerable list
        countries = {v["country"] for v in out["vulnerable"]}
        self.assertTrue(
            {"Turkey", "Argentina", "Egypt"} & countries,
            "expected at least one classic deficit-importer EM in the top 4",
        )
        # Insulated side should be oil exporters / GCC
        insulated_countries = {i["country"] for i in out["insulated"]}
        self.assertTrue(
            {"Saudi Arabia", "UAE", "Norway"} & insulated_countries,
            "expected GCC/Norway on the insulated side of an oil rally",
        )

    def test_dual_oil_plus_dollar_routes_to_dual_squeeze(self):
        out = rs.compute_reserve_stress(
            "OPEC cuts coincide with dollar rally",
            "",
            terms_of_trade=_tot(crude_5d=5.0, dxy_5d=1.2, theme="oil"),
            rates_context=_rates(tip_5d=-0.3),
            # Systemic Stress (canonical classifier label) + the
            # credit_widening signal populated by _stress from
            # credit_5d >= 0.5 cross-confirm the funding pressure.
            stress_regime=_stress(dollar_5d=1.2, credit_5d=0.6,
                                   regime="Systemic Stress"),
        )
        self.assertEqual(out["dominant_channel"], "dual_oil_dollar")
        self.assertEqual(out["pressure_label"], "elevated")
        drivers = out["vulnerable"][0]["drivers"]
        self.assertIn("dual_squeeze", drivers)
        self.assertIn("dollar_rally", drivers)
        self.assertIn("oil_squeeze", drivers)
        # Pressure should be maxed out on a dual shock with credit + risk-off
        self.assertGreaterEqual(out["pressure_score"], rs._PRESSURE_ELEVATED_MIN)

    def test_oil_crash_routes_to_exporter_cushion(self):
        """Crude falling is a relief channel — exporters give back."""
        out = rs.compute_reserve_stress(
            "Crude prices tumble on demand fears",
            "",
            terms_of_trade=_tot(crude_5d=-6.0, dxy_5d=0.1, theme="oil"),
            rates_context=_rates(tip_5d=0.2),
            stress_regime=_stress(dollar_5d=0.1, credit_5d=0.0),
        )
        self.assertEqual(out["dominant_channel"], "commodity_exporter_cushion")
        self.assertEqual(out["vulnerable"], [])
        # Insulated list picks up the exporter cushion countries
        insulated_countries = {i["country"] for i in out["insulated"]}
        self.assertTrue(
            {"Saudi Arabia", "Norway", "Canada"} & insulated_countries,
            "expected exporters on the cushion side",
        )


# ---------------------------------------------------------------------------
# Case 2: Dollar-funding stress / reserve vulnerability
# ---------------------------------------------------------------------------


class TestDollarFundingStress(unittest.TestCase):
    """A DXY rally with no commodity catalyst should route to usd_funding_stress."""

    def test_pure_dollar_rally_routes_to_usd_funding_stress(self):
        out = rs.compute_reserve_stress(
            "Fed signals extended restrictive stance; dollar broad rally",
            "",
            terms_of_trade=_tot(crude_5d=0.2, dxy_5d=1.6, theme="none"),
            rates_context=_rates(tip_5d=-0.4),
            # Exact "Systemic Stress" enum + credit_widening signal
            # (auto-set by _stress from credit_5d >= 0.5) triggers the
            # structured cross-confirmation bonus.  Substring labels
            # like "Risk-off / funding stress" no longer match.
            stress_regime=_stress(dollar_5d=1.6, credit_5d=0.7,
                                   regime="Systemic Stress"),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding_stress")
        self.assertEqual(out["pressure_label"], "elevated")
        self.assertIn("dollar_rally", out["vulnerable"][0]["drivers"])
        self.assertIn("credit_widening", out["vulnerable"][0]["drivers"])
        self.assertIn("real_yield_rise", out["vulnerable"][0]["drivers"])
        self.assertIn("risk_off_regime", out["vulnerable"][0]["drivers"])
        # Deficit EMs with thin reserves top the vulnerable list
        top_country = out["vulnerable"][0]["country"]
        self.assertIn(top_country, {"Turkey", "Argentina", "Egypt", "Pakistan"})
        # Insulated set shifts to reserve-currency shelters + Asia surplus
        insulated_countries = {i["country"] for i in out["insulated"]}
        self.assertTrue(
            {"Switzerland", "Singapore", "Taiwan", "Japan"} & insulated_countries,
            "expected reserve-shelter / Asia-surplus names on a pure DXY rally",
        )

    def test_moderate_dxy_only_routes_to_funding_stress_with_moderate_label(self):
        out = rs.compute_reserve_stress(
            "Dollar firms against majors",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=0.7, theme="none"),
            rates_context=_rates(tip_5d=0.0, regime="Mixed"),
            stress_regime=_stress(dollar_5d=0.7, credit_5d=0.0, regime="Mixed"),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding_stress")
        self.assertEqual(out["pressure_label"], "contained")
        self.assertLess(out["pressure_score"], rs._PRESSURE_MODERATE_MIN)

    def test_extreme_dxy_drives_pressure_score_ceiling(self):
        """A >2% DXY rally should lift score into the elevated band
        WITHOUT a classifier cross-confirmation bonus.

        Regime label is intentionally a free-form string that is NOT
        the canonical "Systemic Stress" enum — under the structured
        rewrite it should NOT add the risk-off meta bonus.  The score
        still reaches elevated purely on the numeric signals.
        """
        out = rs.compute_reserve_stress(
            "Dollar spikes on risk-off panic",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=2.5, theme="none"),
            rates_context=_rates(tip_5d=-0.5),
            stress_regime=_stress(dollar_5d=2.5, credit_5d=0.9,
                                   regime="Risk-off / funding stress"),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding_stress")
        self.assertEqual(out["pressure_label"], "elevated")
        # Non-stacking DXY extreme (35) + credit (20) + real_yield (15)
        # = 70.  The structured rewrite does NOT fire risk_off_regime
        # on the free-form label — drivers must not contain it.
        self.assertGreaterEqual(out["pressure_score"], rs._PRESSURE_ELEVATED_MIN)
        self.assertNotIn(
            "risk_off_regime", out["vulnerable"][0]["drivers"],
            "non-canonical regime label must not trigger the cross-confirmation bonus",
        )


# ---------------------------------------------------------------------------
# Case 3: Mixed / unclear exposure
# ---------------------------------------------------------------------------


class TestMixedOrUnclearExposure(unittest.TestCase):
    """Benign tapes and non-directional moves should degrade into 'none'."""

    def test_benign_tape_returns_none_channel(self):
        out = rs.compute_reserve_stress(
            "Tech earnings beat expectations",
            "Margin expansion and AI capex guidance.",
            terms_of_trade=_tot(crude_5d=0.2, dxy_5d=0.1, theme="none"),
            rates_context=_rates(tip_5d=0.05),
            stress_regime=_stress(dollar_5d=0.1, credit_5d=0.0, regime="Calm"),
        )
        self.assertEqual(out["dominant_channel"], "none")
        self.assertEqual(out["vulnerable"], [])
        self.assertLess(out["pressure_score"], rs._PRESSURE_MODERATE_MIN)
        self.assertEqual(out["pressure_label"], "contained")

    def test_food_theme_routes_to_food_importer_stress(self):
        out = rs.compute_reserve_stress(
            "Wheat export ban triggers grain panic",
            "Global wheat supply disruption",
            terms_of_trade=_tot(crude_5d=0.1, dxy_5d=0.3, theme="food"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress(dollar_5d=0.3, credit_5d=0.0),
        )
        self.assertEqual(out["dominant_channel"], "food_importer_stress")
        countries = {v["country"] for v in out["vulnerable"]}
        self.assertIn("Egypt", countries)

    def test_metal_theme_without_dollar_move_yields_none(self):
        """Metals alone are not a reserve story — the overlay skips."""
        out = rs.compute_reserve_stress(
            "Copper rallies on China stimulus",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=0.2, theme="metal"),
            rates_context=_rates(tip_5d=0.05),
            stress_regime=_stress(dollar_5d=0.2, credit_5d=0.0),
        )
        self.assertEqual(out["dominant_channel"], "none")

    def test_metal_plus_dollar_rally_routes_to_funding_stress(self):
        out = rs.compute_reserve_stress(
            "Metals firm as dollar surges",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.2, theme="metal"),
            rates_context=_rates(tip_5d=-0.2),
            stress_regime=_stress(dollar_5d=1.2, credit_5d=0.4),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding_stress")


# ---------------------------------------------------------------------------
# Case 4: Stale / unavailable context
# ---------------------------------------------------------------------------


class TestStaleAndDegradedContext(unittest.TestCase):
    """All inputs missing → empty dict; partial inputs → stale=True."""

    def test_no_inputs_returns_empty(self):
        out = rs.compute_reserve_stress(
            "",
            "",
            terms_of_trade=None,
            rates_context=None,
            stress_regime=None,
        )
        self.assertEqual(out, {})

    def test_headline_only_returns_block_marked_stale(self):
        out = rs.compute_reserve_stress(
            "Some macro headline",
            "Mechanism text.",
            terms_of_trade=None,
            rates_context=None,
            stress_regime=None,
        )
        self.assertTrue(out["stale"])
        self.assertEqual(out["dominant_channel"], "none")
        self.assertEqual(out["pressure_score"], 0)

    def test_tot_unavailable_falls_back_to_stress_dxy(self):
        """When terms_of_trade is missing, DXY is read from stress_regime."""
        out = rs.compute_reserve_stress(
            "Dollar rally",
            "",
            terms_of_trade=None,
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress(dollar_5d=1.3, credit_5d=0.5),
        )
        self.assertEqual(out["dominant_channel"], "usd_funding_stress")
        self.assertTrue(out["stale"])
        self.assertEqual(out["signals"]["dxy_5d"], 1.3)

    def test_upstream_stale_flag_propagates(self):
        """A stale terms_of_trade block should flow stale forward."""
        out = rs.compute_reserve_stress(
            "Oil rally",
            "",
            terms_of_trade=_tot(crude_5d=4.0, dxy_5d=0.3, theme="oil", stale=True),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress(dollar_5d=0.3, credit_5d=0.0),
        )
        self.assertTrue(out["stale"])
        self.assertEqual(out["dominant_channel"], "oil_import_squeeze")


# ---------------------------------------------------------------------------
# Case 5: Output contract invariants
# ---------------------------------------------------------------------------


class TestOutputContract(unittest.TestCase):
    """Shape-preserving invariants the frontend consumes."""

    def test_all_required_keys_present(self):
        out = rs.compute_reserve_stress(
            "Oil shock",
            "",
            terms_of_trade=_tot(crude_5d=5.0, dxy_5d=1.2, theme="oil"),
            rates_context=_rates(tip_5d=-0.3),
            stress_regime=_stress(dollar_5d=1.2, credit_5d=0.5,
                                   regime="Risk-off / funding stress"),
        )
        for key in (
            "vulnerable", "insulated", "dominant_channel", "dominant_channel_label",
            "pressure_score", "pressure_label", "rationale", "key_markets",
            "available", "stale", "signals",
        ):
            self.assertIn(key, out)
        self.assertIn("crude_5d", out["signals"])
        self.assertIn("dxy_5d", out["signals"])
        self.assertIn("credit_spread_5d", out["signals"])
        self.assertIn("real_yield_5d", out["signals"])
        self.assertIn("thresholds", out["signals"])

    def test_vulnerable_entries_shape(self):
        out = rs.compute_reserve_stress(
            "DXY rally",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.5, theme="none"),
            rates_context=_rates(tip_5d=-0.3),
            stress_regime=_stress(dollar_5d=1.5, credit_5d=0.6),
        )
        self.assertGreater(len(out["vulnerable"]), 0)
        row = out["vulnerable"][0]
        for key in ("country", "region", "vulnerability", "drivers", "rationale"):
            self.assertIn(key, row)
        self.assertIsInstance(row["vulnerability"], int)
        self.assertIsInstance(row["drivers"], list)

    def test_insulated_entries_shape(self):
        out = rs.compute_reserve_stress(
            "Oil rally",
            "",
            terms_of_trade=_tot(crude_5d=5.0, dxy_5d=0.2, theme="oil"),
            rates_context=_rates(tip_5d=0.0),
            stress_regime=_stress(dollar_5d=0.2, credit_5d=0.0),
        )
        self.assertGreater(len(out["insulated"]), 0)
        row = out["insulated"][0]
        for key in ("country", "region", "strength", "drivers", "rationale"):
            self.assertIn(key, row)
        self.assertIsInstance(row["strength"], int)

    def test_vulnerable_list_capped_at_four(self):
        out = rs.compute_reserve_stress(
            "DXY rally",
            "",
            terms_of_trade=_tot(crude_5d=0.0, dxy_5d=1.5, theme="none"),
            rates_context=_rates(tip_5d=-0.3),
            stress_regime=_stress(dollar_5d=1.5, credit_5d=0.5),
        )
        self.assertLessEqual(len(out["vulnerable"]), 4)

    def test_insulated_list_capped_at_four(self):
        out = rs.compute_reserve_stress(
            "Oil shock",
            "",
            terms_of_trade=_tot(crude_5d=5.0, dxy_5d=1.2, theme="oil"),
            rates_context=_rates(tip_5d=-0.3),
            stress_regime=_stress(dollar_5d=1.2, credit_5d=0.5),
        )
        self.assertLessEqual(len(out["insulated"]), 4)

    def test_pressure_score_bounded(self):
        out = rs.compute_reserve_stress(
            "Multi-driver shock",
            "",
            terms_of_trade=_tot(crude_5d=10.0, dxy_5d=3.0, theme="oil"),
            rates_context=_rates(tip_5d=-1.0),
            stress_regime=_stress(dollar_5d=3.0, credit_5d=1.5,
                                   regime="Risk-off / funding stress"),
        )
        self.assertGreaterEqual(out["pressure_score"], 0)
        self.assertLessEqual(out["pressure_score"], 100)


# ---------------------------------------------------------------------------
# Case 6: /analyze wiring — the overlay lands on the response
# ---------------------------------------------------------------------------


class TestAnalyzeWiring(unittest.TestCase):
    """End-to-end: reserve_stress surfaces on the /analyze body."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""  # mock path
        from fastapi.testclient import TestClient
        import api
        cls.api = api
        cls.client = TestClient(api.app)

    def _fake_analyze_event(self, headline, stage, persistence, event_context="", model=None):
        return {
            "what_changed": "OPEC announced a 2 mbpd production cut.",
            "mechanism_summary": "Supply shock raises crude price; input and shipping costs transmit to importers.",
            "beneficiaries": ["XOM", "CVX"],
            "losers": ["DAL", "AAL"],
            "beneficiary_tickers": ["XOM", "CVX"],
            "loser_tickers": ["DAL", "AAL"],
            "assets_to_watch": ["XOM", "DAL"],
            "confidence": "medium",
            "transmission_chain": ["a", "b", "c", "d"],
            "if_persists": {},
            "currency_channel": {},
        }

    def _fake_market_check(self, *_args, **_kwargs):
        return {"note": "Stub.", "details": {}, "tickers": []}

    def test_reserve_stress_present_on_analyze_response(self):
        from unittest.mock import patch
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "market_check", side_effect=self._fake_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("reserve_stress", body["analysis"])
        rs_block = body["analysis"]["reserve_stress"]
        # Block may be {} when macro is entirely unavailable; must not crash.
        if rs_block:
            self.assertIn("dominant_channel", rs_block)
            self.assertIn("available", rs_block)


if __name__ == "__main__":
    unittest.main()
