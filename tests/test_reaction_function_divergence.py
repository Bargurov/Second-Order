"""
tests/test_reaction_function_divergence.py

Focused tests for the Reaction Function Divergence composer.

Three required scenarios:
  1. Aligned case (event and market pricing point the same way)
  2. Divergence case (event implies one direction, markets price the other)
  3. Stale / unavailable macro context

Plus a small set of supporting tests for the directional scorers, the
mild-divergence neutral path, and api.py wiring.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from reaction_function_divergence import (  # noqa: E402
    compute_reaction_function_divergence,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures — mirror compute_rates_context / compute_stress_regime
# ---------------------------------------------------------------------------

def _rates(regime: str = "Mixed", nominal_5d=None, real_5d=None,
           breakeven_5d=None) -> dict:
    return {
        "regime": regime,
        "nominal": {"label": "10Y yield", "value": 4.25, "change_5d": nominal_5d},
        "real_proxy": {
            "label": "TIP (real yield proxy)",
            "value": 108.5,
            "change_5d": real_5d,
        },
        "breakeven_proxy": {"label": "Breakeven proxy", "change_5d": breakeven_5d},
        "raw": {"^TNX": 4.25, "TIP": 108.5},
    }


def _stress(
    regime: str = "Calm",
    *,
    safe_haven_bid: bool = False,
    credit_widening: bool = False,
    vix_elevated: bool = False,
) -> dict:
    return {
        "regime": regime,
        "signals": {
            "vix_elevated": vix_elevated,
            "term_inversion": False,
            "credit_widening": credit_widening,
            "safe_haven_bid": safe_haven_bid,
            "breadth_deterioration": False,
        },
        "raw": {"vix": 17.0},
    }


def _snap(market: str, change_5d: float, value: float = 100.0) -> dict:
    return {
        "market": market,
        "symbol": market,
        "value": value,
        "change_5d": change_5d,
        "error": None,
    }


# ---------------------------------------------------------------------------
# Required scenario 1 — aligned
# ---------------------------------------------------------------------------

class TestAligned(unittest.TestCase):

    def test_hawkish_event_with_hawkish_pricing_aligns(self):
        # Inflationary event (OPEC supply shock) + markets pricing tightening
        # (10Y up, TIP down → real yields rising, DXY firming).
        result = compute_reaction_function_divergence(
            "OPEC slashes output by 2 mbpd",
            "Supply shock and crude price spike feed input cost passthrough.",
            rates_context=_rates("Inflation pressure",
                                 nominal_5d=0.5, real_5d=-0.6, breakeven_5d=0.4),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("DXY", 1.2)],
        )
        self.assertEqual(result["implied"], "hawkish")
        self.assertEqual(result["priced"], "hawkish")
        self.assertEqual(result["divergence"], "aligned")
        self.assertEqual(result["divergence_label"], "Aligned")
        self.assertIn("clean hawkish mandate", result["macro_read"])
        self.assertTrue(result["available"])
        # Aligned case still surfaces a watch list.
        self.assertIn("10Y", result["key_markets"])

    def test_dovish_event_with_dovish_pricing_aligns(self):
        # Disinflationary event + risk-off pricing.
        result = compute_reaction_function_divergence(
            "Crude collapses on demand destruction",
            "Massive inventory build and softening demand drive deflation.",
            rates_context=_rates("Risk-off / growth scare",
                                 nominal_5d=-0.5, real_5d=0.5, breakeven_5d=-0.6),
            stress_regime=_stress("Calm", safe_haven_bid=True),
            snapshots=[_snap("ES", -2.5)],
        )
        self.assertEqual(result["implied"], "dovish")
        self.assertEqual(result["priced"], "dovish")
        self.assertEqual(result["divergence"], "aligned")
        self.assertIn("clean dovish mandate", result["macro_read"])


# ---------------------------------------------------------------------------
# Required scenario 2 — divergence
# ---------------------------------------------------------------------------

class TestDivergence(unittest.TestCase):

    def test_sharp_divergence_hawkish_event_dovish_pricing(self):
        # Inflationary thesis but markets are pricing cuts: TIP rallying,
        # 10Y falling, S&P selling off, safe-haven bid.
        result = compute_reaction_function_divergence(
            "OPEC supply shock and tariff expansion",
            "Crude price and input cost passthrough lift inflation pressure.",
            rates_context=_rates("Risk-off / growth scare",
                                 nominal_5d=-0.5, real_5d=0.6, breakeven_5d=-0.4),
            stress_regime=_stress("Geopolitical Stress", safe_haven_bid=True),
            snapshots=[_snap("ES", -2.5)],
        )
        self.assertEqual(result["implied"], "hawkish")
        self.assertEqual(result["priced"], "dovish")
        self.assertEqual(result["divergence"], "sharp")
        self.assertIn("opposite", result["rationale"].lower())
        # Sharp divergence widens the watch list to include the front-end.
        self.assertIn("2Y", result["key_markets"])

    def test_sharp_divergence_dovish_event_hawkish_pricing(self):
        # Disinflationary thesis but markets pricing tightening.
        result = compute_reaction_function_divergence(
            "Crude crashes on oversupply and demand destruction",
            "Massive inventory build and price war drive deflation.",
            rates_context=_rates("Real-rate tightening",
                                 nominal_5d=0.6, real_5d=-0.7, breakeven_5d=-0.1),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("DXY", 1.5)],
        )
        self.assertEqual(result["implied"], "dovish")
        self.assertEqual(result["priced"], "hawkish")
        self.assertEqual(result["divergence"], "sharp")

    def test_mild_divergence_when_markets_silent(self):
        # Inflationary event but rates barely moving — markets haven't
        # repriced yet, so we expect mild divergence.
        result = compute_reaction_function_divergence(
            "OPEC supply shock lifts crude",
            "Tariff and input cost passthrough.",
            rates_context=_rates("Mixed",
                                 nominal_5d=0.05, real_5d=0.02, breakeven_5d=0.03),
            stress_regime=_stress("Calm"),
            snapshots=None,
        )
        self.assertEqual(result["implied"], "hawkish")
        self.assertEqual(result["priced"], "neutral")
        self.assertEqual(result["divergence"], "mild")

    def test_mild_divergence_when_event_neutral(self):
        # No policy thesis, but markets are pricing dovish (recession scare).
        result = compute_reaction_function_divergence(
            "Tech CEO resigns abruptly",
            "Board names interim leader.",
            rates_context=_rates("Risk-off / growth scare",
                                 nominal_5d=-0.5, real_5d=0.5, breakeven_5d=-0.4),
            stress_regime=_stress("Calm", safe_haven_bid=True),
            snapshots=[_snap("ES", -2.4)],
        )
        self.assertEqual(result["implied"], "neutral")
        self.assertEqual(result["priced"], "dovish")
        self.assertEqual(result["divergence"], "mild")


# ---------------------------------------------------------------------------
# Required scenario 3 — stale / unavailable macro
# ---------------------------------------------------------------------------

class TestStaleMacro(unittest.TestCase):

    def test_stale_macro_with_thesis_returns_block_priced_neutral(self):
        # Strong thesis but macro completely unavailable.
        result = compute_reaction_function_divergence(
            "OPEC supply shock and tariff expansion",
            "Crude price and input cost passthrough.",
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        self.assertTrue(result)  # not {}
        self.assertEqual(result["implied"], "hawkish")
        self.assertEqual(result["priced"], "neutral")
        # Implied vs neutral → mild divergence.
        self.assertEqual(result["divergence"], "mild")
        # Block flagged stale; available=False because macro is fully gone.
        self.assertTrue(result["stale"])
        self.assertFalse(result["available"])
        self.assertIn("unavailable", result["priced_basis"].lower())

    def test_no_thesis_no_macro_returns_empty_dict(self):
        result = compute_reaction_function_divergence(
            "Tech CEO resigns abruptly",
            "Board names interim leader; no near-term financial impact.",
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        self.assertEqual(result, {})

    def test_partial_macro_marks_stale_but_keeps_available(self):
        # Rates usable but stress missing → partial.
        result = compute_reaction_function_divergence(
            "OPEC supply shock",
            "Crude price spike feeds input cost passthrough.",
            rates_context=_rates("Inflation pressure",
                                 nominal_5d=0.5, real_5d=-0.5, breakeven_5d=0.5),
            stress_regime=None,
            snapshots=None,
        )
        self.assertTrue(result)
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["implied"], "hawkish")

    def test_empty_dict_inputs_treated_as_unavailable(self):
        result = compute_reaction_function_divergence(
            "Tariff hike on imports",
            "Tariff and import cost passthrough.",
            rates_context={},
            stress_regime={},
            snapshots=None,
        )
        # Thesis present → block returned with priced=neutral and stale flag.
        self.assertTrue(result)
        self.assertEqual(result["priced"], "neutral")
        self.assertFalse(result["available"])


# ---------------------------------------------------------------------------
# Block shape contract
# ---------------------------------------------------------------------------

class TestBlockShape(unittest.TestCase):

    def test_full_block_has_required_fields(self):
        result = compute_reaction_function_divergence(
            "OPEC slashes output",
            "Supply shock and tariff feed input cost passthrough.",
            rates_context=_rates("Inflation pressure",
                                 nominal_5d=0.5, real_5d=-0.6, breakeven_5d=0.4),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("DXY", 1.0)],
        )
        for key in (
            "implied", "implied_label", "implied_basis",
            "priced", "priced_label", "priced_basis",
            "divergence", "divergence_label",
            "rationale", "macro_read", "key_markets",
            "available", "stale",
        ):
            self.assertIn(key, result, f"missing field: {key}")

    def test_direction_labels_are_stable(self):
        result = compute_reaction_function_divergence(
            "OPEC supply shock",
            "Crude price spike on production cut.",
            rates_context=_rates("Inflation pressure",
                                 nominal_5d=0.5, real_5d=-0.6, breakeven_5d=0.4),
            stress_regime=_stress("Calm"),
            snapshots=None,
        )
        self.assertEqual(result["implied_label"], "Hawkish (tighter)")
        self.assertEqual(result["priced_label"], "Hawkish (tightening priced)")


# ---------------------------------------------------------------------------
# api.py wiring
# ---------------------------------------------------------------------------

class TestAnalyzeWiring(unittest.TestCase):

    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = ""  # force mock path
        from fastapi.testclient import TestClient
        import api
        self.api = api
        self.client = TestClient(api.app)

    def _fake_analyze_event(self, headline, stage, persistence,
                            event_context="", model=None):
        return {
            "what_changed": "OPEC announced a 2 mbpd production cut.",
            "mechanism_summary": (
                "Supply shock lifts crude price; tariff and input cost "
                "transmit to consumers via passthrough."
            ),
            "beneficiaries": ["XOM"],
            "losers": ["DAL"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["DAL"],
            "assets_to_watch": ["XOM", "DAL"],
            "confidence": "medium",
            "transmission_chain": ["a", "b", "c", "d"],
            "if_persists": {},
            "currency_channel": {},
        }

    def _fake_rates_aligned(self):
        return _rates("Inflation pressure",
                      nominal_5d=0.5, real_5d=-0.6, breakeven_5d=0.4)

    def _fake_rates_diverge(self):
        return _rates("Risk-off / growth scare",
                      nominal_5d=-0.5, real_5d=0.6, breakeven_5d=-0.4)

    def _fake_stress_calm(self):
        return _stress("Calm")

    def _fake_stress_haven(self):
        return _stress("Geopolitical Stress", safe_haven_bid=True)

    def _stub_market_check(self, *_args, **_kwargs):
        return {"note": "", "details": {}, "tickers": []}

    def test_aligned_case_reaches_response(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_aligned), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress_calm), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        rfd = r.json()["analysis"].get("reaction_function_divergence")
        self.assertIsInstance(rfd, dict)
        self.assertEqual(rfd["divergence"], "aligned")
        self.assertEqual(rfd["implied"], "hawkish")
        self.assertEqual(rfd["priced"], "hawkish")

    def test_sharp_divergence_case_reaches_response(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_diverge), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress_haven), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        rfd = r.json()["analysis"].get("reaction_function_divergence")
        self.assertIsInstance(rfd, dict)
        self.assertEqual(rfd["divergence"], "sharp")
        self.assertEqual(rfd["implied"], "hawkish")
        self.assertEqual(rfd["priced"], "dovish")


if __name__ == "__main__":
    unittest.main()
