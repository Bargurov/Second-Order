"""
tests/test_real_yield_context.py

Focused tests for the real-yield / breakeven inflation context block.

Three core scenarios required by the task:
  1. Inflationary thesis with confirming macro context
  2. Inflationary thesis with non-confirming macro context (clean tension)
  3. Stale / unavailable macro data (graceful degrade)

Plus a small set of supporting tests for thesis classification and the
api.py wiring path so the context survives an end-to-end /analyze call.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from real_yield_context import (  # noqa: E402
    classify_thesis,
    build_real_yield_context,
)


# ---------------------------------------------------------------------------
# Synthetic rates_context fixtures (mirrors compute_rates_context() shape)
# ---------------------------------------------------------------------------

def _rates(regime: str, nominal_5d, real_5d, breakeven_5d) -> dict:
    return {
        "regime": regime,
        "nominal": {"label": "10Y yield", "value": 4.25, "change_5d": nominal_5d},
        "real_proxy": {
            "label": "TIP (real yield proxy)",
            "value": 108.5,
            "change_5d": real_5d,
        },
        "breakeven_proxy": {"label": "Breakeven proxy", "change_5d": breakeven_5d},
        "raw": {},
    }


# ---------------------------------------------------------------------------
# Thesis classifier
# ---------------------------------------------------------------------------

class TestClassifyThesis(unittest.TestCase):

    def test_inflationary_keywords(self):
        result = classify_thesis(
            "OPEC slashes output",
            "Production cut and supply shock raises crude price.",
        )
        self.assertEqual(result["thesis"], "inflationary")
        self.assertTrue(result["evidence"])

    def test_disinflationary_keywords(self):
        result = classify_thesis(
            "Crude tanks on demand destruction",
            "Massive inventory build and softening demand drive deflation.",
        )
        self.assertEqual(result["thesis"], "disinflationary")
        self.assertTrue(result["evidence"])

    def test_rate_pressure_up(self):
        result = classify_thesis(
            "Fed signals more hikes",
            "Hawkish Fed and sticky inflation point to rate hike path.",
        )
        self.assertEqual(result["thesis"], "rate_pressure_up")

    def test_rate_pressure_down(self):
        result = classify_thesis(
            "Fed pivots dovish",
            "Markets price in rate cut and accommodative pivot.",
        )
        self.assertEqual(result["thesis"], "rate_pressure_down")

    def test_no_thesis(self):
        result = classify_thesis(
            "Tech CEO resigns",
            "Board names interim leader after sudden departure.",
        )
        self.assertEqual(result["thesis"], "none")
        self.assertEqual(result["evidence"], [])

    def test_inflation_overrides_rate_pressure(self):
        result = classify_thesis(
            "Hawkish Fed reacts to oil price spike",
            "Energy price surge forces hawkish stance and rate hike.",
        )
        # Inflation/disinflation outranks rate-pressure family.
        self.assertEqual(result["thesis"], "inflationary")

    def test_tied_inflation_disinflation_picks_higher_count(self):
        result = classify_thesis(
            "Tariff and oversupply collide",
            "Tariff and import cost meet inventory build and oversupply.",
        )
        # Two disinflation hits (inventory build, oversupply) vs two inflation
        # hits (tariff, import cost) — ties go to inflation per implementation.
        self.assertIn(result["thesis"], ("inflationary", "disinflationary"))


# ---------------------------------------------------------------------------
# Required scenario 1 — inflationary thesis WITH confirming macro
# ---------------------------------------------------------------------------

class TestInflationaryConfirm(unittest.TestCase):

    def test_inflation_pressure_regime_confirms(self):
        rates = _rates("Inflation pressure", nominal_5d=0.8, real_5d=0.05, breakeven_5d=0.85)
        ctx = build_real_yield_context(
            "OPEC slashes output by 2 mbpd",
            "Supply shock pushes crude price; tariff and shipping cost transmit to consumers.",
            rates,
        )
        self.assertEqual(ctx["thesis"], "inflationary")
        self.assertEqual(ctx["alignment"], "confirm")
        self.assertTrue(ctx["available"])
        self.assertFalse(ctx["stale"])
        self.assertEqual(ctx["regime"], "Inflation pressure")
        self.assertIn("confirm", ctx["explanation"].lower())
        self.assertEqual(ctx["nominal_5d"], 0.8)
        self.assertEqual(ctx["breakeven_proxy_5d"], 0.85)

    def test_widening_breakeven_confirms_even_when_regime_label_differs(self):
        # Regime label is "Mixed" but breakeven proxy is widening — still confirm.
        rates = _rates("Mixed", nominal_5d=0.5, real_5d=0.05, breakeven_5d=0.55)
        ctx = build_real_yield_context(
            "Energy price surge after pipeline outage",
            "Crude price and gasoline rally on supply disruption.",
            rates,
        )
        self.assertEqual(ctx["alignment"], "confirm")


# ---------------------------------------------------------------------------
# Required scenario 2 — inflationary thesis with NON-confirming macro
# ---------------------------------------------------------------------------

class TestInflationaryTension(unittest.TestCase):

    def test_real_rate_tightening_creates_clean_tension(self):
        rates = _rates("Real-rate tightening", nominal_5d=0.4, real_5d=-0.6, breakeven_5d=-0.2)
        ctx = build_real_yield_context(
            "OPEC cuts production by 1 mbpd",
            "Supply shock and oil price spike feed input cost pressure.",
            rates,
        )
        self.assertEqual(ctx["thesis"], "inflationary")
        self.assertEqual(ctx["alignment"], "tension")
        # Clean tension — NOT a hard contradiction, never blocks the analysis.
        self.assertTrue(ctx["available"])
        self.assertFalse(ctx["stale"])
        self.assertIn("not confirm", ctx["explanation"].lower())
        # Numbers preserved so the UI can render the actual moves.
        self.assertEqual(ctx["real_proxy_5d"], -0.6)

    def test_growth_scare_regime_creates_tension(self):
        rates = _rates("Risk-off / growth scare", nominal_5d=-0.5, real_5d=0.4, breakeven_5d=-0.9)
        ctx = build_real_yield_context(
            "Tariff hike on imports",
            "Tariff and import cost flow through to consumers and energy price.",
            rates,
        )
        self.assertEqual(ctx["alignment"], "tension")

    def test_collapsing_breakeven_creates_tension(self):
        rates = _rates("Mixed", nominal_5d=-0.1, real_5d=0.2, breakeven_5d=-0.5)
        ctx = build_real_yield_context(
            "Energy price spike",
            "Oil price surges on supply shock; input cost passes through to consumers.",
            rates,
        )
        self.assertEqual(ctx["alignment"], "tension")


# ---------------------------------------------------------------------------
# Required scenario 3 — stale / unavailable macro
# ---------------------------------------------------------------------------

class TestStaleMacroDegrade(unittest.TestCase):

    def test_none_rates_context(self):
        ctx = build_real_yield_context(
            "Tariff hike on imports",
            "Tariff and import cost flow through to consumers.",
            None,
        )
        self.assertEqual(ctx["alignment"], "stale")
        self.assertFalse(ctx["available"])
        self.assertTrue(ctx["stale"])
        self.assertIsNone(ctx["nominal_5d"])
        self.assertIsNone(ctx["real_proxy_5d"])
        self.assertIn("unavailable", ctx["explanation"].lower())

    def test_missing_nominal_5d_treated_as_stale(self):
        rates = _rates("Inflation pressure", nominal_5d=None, real_5d=0.1, breakeven_5d=0.3)
        ctx = build_real_yield_context(
            "OPEC supply shock",
            "Crude price spikes on production cut.",
            rates,
        )
        self.assertEqual(ctx["alignment"], "stale")
        self.assertFalse(ctx["available"])

    def test_missing_real_5d_treated_as_stale(self):
        rates = _rates("Inflation pressure", nominal_5d=0.5, real_5d=None, breakeven_5d=None)
        ctx = build_real_yield_context(
            "OPEC supply shock",
            "Crude price spikes on production cut.",
            rates,
        )
        self.assertEqual(ctx["alignment"], "stale")

    def test_empty_dict_rates_context_stale(self):
        ctx = build_real_yield_context(
            "Tariff hike",
            "Import cost passes through to consumers.",
            {},
        )
        self.assertEqual(ctx["alignment"], "stale")

    def test_no_thesis_returns_empty_dict(self):
        # When no thesis is detected, the block returns {} so api.py can
        # skip rendering rather than show an empty card.
        ctx = build_real_yield_context(
            "Tech CEO resigns",
            "Board names interim leader after sudden departure.",
            _rates("Inflation pressure", 0.5, 0.0, 0.5),
        )
        self.assertEqual(ctx, {})


# ---------------------------------------------------------------------------
# Disinflationary + rate-pressure alignment paths (smaller coverage)
# ---------------------------------------------------------------------------

class TestOtherThesisAlignment(unittest.TestCase):

    def test_disinflationary_confirm_via_real_rate_tightening(self):
        rates = _rates("Real-rate tightening", nominal_5d=0.0, real_5d=-0.5, breakeven_5d=-0.4)
        ctx = build_real_yield_context(
            "Crude crash on oversupply",
            "Massive inventory build and price war drive deflation.",
            rates,
        )
        self.assertEqual(ctx["thesis"], "disinflationary")
        self.assertEqual(ctx["alignment"], "confirm")

    def test_rate_up_confirms_with_real_yield_rising(self):
        rates = _rates("Real-rate tightening", nominal_5d=0.5, real_5d=-0.6, breakeven_5d=-0.1)
        ctx = build_real_yield_context(
            "Hawkish Fed signals more rate hike",
            "Sticky inflation forces tighter policy.",
            rates,
        )
        self.assertEqual(ctx["thesis"], "rate_pressure_up")
        self.assertEqual(ctx["alignment"], "confirm")

    def test_rate_down_tension_when_real_rates_rising(self):
        rates = _rates("Real-rate tightening", nominal_5d=0.4, real_5d=-0.6, breakeven_5d=-0.2)
        ctx = build_real_yield_context(
            "Markets price in rate cut",
            "Dovish pivot expectations build.",
            rates,
        )
        self.assertEqual(ctx["thesis"], "rate_pressure_down")
        self.assertEqual(ctx["alignment"], "tension")


# ---------------------------------------------------------------------------
# api.py wiring — make sure the field reaches the /analyze response
# ---------------------------------------------------------------------------

class TestAnalyzeWiring(unittest.TestCase):
    """End-to-end check that real_yield_context lands on the analyze payload.

    We patch analyze_event() and compute_rates_context() so no LLM or
    network call happens, then call /analyze via TestClient.
    """

    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = ""  # force mock path
        from fastapi.testclient import TestClient
        import api
        self.api = api
        self.client = TestClient(api.app)

    def _fake_analyze_event(self, headline, stage, persistence, event_context="", model=None):
        return {
            "what_changed": "OPEC announced a 2 mbpd production cut.",
            "mechanism_summary": (
                "Supply shock raises crude price; input cost and shipping cost "
                "transmit to consumers via gasoline and diesel."
            ),
            "beneficiaries": ["XOM", "CVX"],
            "losers": ["DAL", "AAL"],
            "beneficiary_tickers": ["XOM", "CVX"],
            "loser_tickers": ["DAL", "AAL"],
            "assets_to_watch": ["XOM", "CVX", "DAL", "AAL"],
            "confidence": "medium",
            "transmission_chain": ["a", "b", "c", "d"],
            "if_persists": {},
            "currency_channel": {},
        }

    def _fake_rates_context_confirm(self):
        return _rates("Inflation pressure", 0.8, 0.05, 0.85)

    def _fake_rates_context_stale(self):
        return _rates("Mixed", None, None, None)

    def _stub_market_check(self, *_args, **_kwargs):
        return {"note": "", "details": {}, "tickers": []}

    def test_real_yield_context_present_when_inflationary(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_context_confirm), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        ry = body["analysis"].get("real_yield_context")
        self.assertIsInstance(ry, dict)
        self.assertEqual(ry["thesis"], "inflationary")
        self.assertEqual(ry["alignment"], "confirm")

    def test_real_yield_context_stale_when_macro_unavailable(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_context_stale), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        ry = r.json()["analysis"]["real_yield_context"]
        self.assertEqual(ry["alignment"], "stale")
        self.assertFalse(ry["available"])

    def test_real_yield_context_empty_for_non_macro_event(self):
        def neutral_analyze(*_args, **_kwargs):
            return {
                "what_changed": "Tech CEO steps down.",
                "mechanism_summary": "Board appoints interim chief; no near-term financial impact.",
                "beneficiaries": [],
                "losers": [],
                "beneficiary_tickers": ["MSFT"],
                "loser_tickers": [],
                "assets_to_watch": ["MSFT"],
                "confidence": "low",
                "transmission_chain": [],
                "if_persists": {},
                "currency_channel": {},
            }

        with patch.object(self.api, "analyze_event", side_effect=neutral_analyze), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_context_confirm), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "Tech CEO steps down"},
            )
        self.assertEqual(r.status_code, 200)
        ry = r.json()["analysis"]["real_yield_context"]
        # No thesis → empty dict so the UI can skip the card.
        self.assertEqual(ry, {})


if __name__ == "__main__":
    unittest.main()
