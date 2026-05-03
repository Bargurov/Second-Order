"""
Tests for the market regime layer additions.

Covers:
- compose_market_context includes rates + regime_vector fields
- Normalization when rates/regime_vector are None
- /market-context endpoint returns the new fields
- regime_vector axis values are valid labels
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_context import compose_market_context
from regime_vector import build_regime_vector


# ---------------------------------------------------------------------------
# compose_market_context — new fields
# ---------------------------------------------------------------------------

class TestComposeMarketContextRegimeFields(unittest.TestCase):

    def _compose(self, **kw):
        return compose_market_context([], None, [], **kw)

    def test_rates_present_when_provided(self):
        rates = {"regime": "Inflation pressure", "nominal": {}, "real_proxy": {}, "breakeven_proxy": {}, "raw": {}}
        ctx = self._compose(rates=rates)
        self.assertIn("rates", ctx)
        self.assertTrue(ctx["rates"]["available"])
        self.assertEqual(ctx["rates"]["regime"], "Inflation pressure")

    def test_rates_unavailable_when_none(self):
        ctx = self._compose(rates=None)
        self.assertIn("rates", ctx)
        self.assertFalse(ctx["rates"]["available"])
        self.assertEqual(ctx["rates"]["regime"], "Unknown")

    def test_regime_vector_present_when_provided(self):
        vec = {"inflation": "hot", "policy_stance": "hawkish", "fx": "neutral", "growth_stress": "calm", "available": True}
        ctx = self._compose(regime_vector=vec)
        self.assertIn("regime_vector", ctx)
        self.assertTrue(ctx["regime_vector"]["available"])
        self.assertEqual(ctx["regime_vector"]["inflation"], "hot")

    def test_regime_vector_unavailable_when_none(self):
        ctx = self._compose(regime_vector=None)
        self.assertIn("regime_vector", ctx)
        self.assertFalse(ctx["regime_vector"]["available"])

    def test_existing_fields_preserved(self):
        ctx = self._compose()
        for key in ("built_at", "source", "snapshots", "snapshots_meta", "stress", "highlights", "highlights_meta"):
            self.assertIn(key, ctx, f"Missing existing field: {key}")


# ---------------------------------------------------------------------------
# build_regime_vector — axis classification
# ---------------------------------------------------------------------------

_VALID_INFLATION = {"hot", "cool", "neutral"}
_VALID_POLICY = {"hawkish", "dovish", "neutral"}
_VALID_FX = {"dollar_strong", "dollar_weak", "neutral"}
_VALID_GROWTH = {"calm", "watch", "stressed", "neutral"}


class TestRegimeVectorClassification(unittest.TestCase):

    def test_none_inputs_returns_unavailable(self):
        vec = build_regime_vector(None, None, None)
        self.assertFalse(vec["available"])

    def test_rates_only_produces_partial(self):
        rates = {
            "regime": "Inflation pressure",
            "nominal": {"change_5d": 0.25},
            "real_proxy": {"change_5d": -0.1},
            "breakeven_proxy": {"change_5d": 0.35},
            "raw": {},
        }
        vec = build_regime_vector(rates, None, None)
        self.assertIn(vec["inflation"], _VALID_INFLATION)
        self.assertIn(vec["policy_stance"], _VALID_POLICY)
        self.assertTrue(vec.get("stale", False), "Should be stale with only rates")

    def test_stress_only_produces_partial(self):
        stress = {
            "regime": "Calm",
            "signals": {
                "vix_elevated": False,
                "term_inversion": False,
                "credit_widening": False,
                "safe_haven_bid": False,
                "breadth_deterioration": False,
            },
            "raw": {},
            "detail": {},
            "summary": "calm",
        }
        vec = build_regime_vector(None, stress, None)
        self.assertIn(vec["growth_stress"], _VALID_GROWTH)
        self.assertTrue(vec.get("stale", False))

    def test_both_inputs_not_stale(self):
        rates = {
            "regime": "Mixed",
            "nominal": {"change_5d": 0.05},
            "real_proxy": {"change_5d": 0.02},
            "breakeven_proxy": {"change_5d": 0.03},
            "raw": {},
        }
        stress = {
            "regime": "Calm",
            "signals": {
                "vix_elevated": False,
                "term_inversion": False,
                "credit_widening": False,
                "safe_haven_bid": False,
                "breadth_deterioration": False,
            },
            "raw": {},
            "detail": {},
            "summary": "calm",
        }
        vec = build_regime_vector(rates, stress, None)
        self.assertTrue(vec["available"])
        self.assertFalse(vec.get("stale", False))

    def test_all_axes_have_valid_labels(self):
        rates = {
            "regime": "Inflation pressure",
            "nominal": {"change_5d": 0.5},
            "real_proxy": {"change_5d": -0.3},
            "breakeven_proxy": {"change_5d": 0.8},
            "raw": {},
        }
        stress = {
            "regime": "Systemic Stress",
            "signals": {
                "vix_elevated": True,
                "term_inversion": True,
                "credit_widening": True,
                "safe_haven_bid": True,
                "breadth_deterioration": True,
            },
            "raw": {},
            "detail": {},
            "summary": "stress",
        }
        vec = build_regime_vector(rates, stress, None)
        self.assertIn(vec["inflation"], _VALID_INFLATION)
        self.assertIn(vec["policy_stance"], _VALID_POLICY)
        self.assertIn(vec["fx"], _VALID_FX)
        self.assertIn(vec["growth_stress"], _VALID_GROWTH)


# ---------------------------------------------------------------------------
# /market-context endpoint — new fields in response
# ---------------------------------------------------------------------------

class TestMarketContextEndpoint(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        from fastapi.testclient import TestClient
        import api
        cls.client = TestClient(api.app)

    @patch("api.compute_stress_regime", return_value={
        "regime": "Calm", "signals": {
            "vix_elevated": False, "term_inversion": False,
            "credit_widening": False, "safe_haven_bid": False,
            "breadth_deterioration": False,
        }, "raw": {}, "detail": {}, "summary": "calm",
    })
    @patch("api.compute_rates_context", return_value={
        "regime": "Mixed", "nominal": {}, "real_proxy": {},
        "breakeven_proxy": {}, "raw": {},
    })
    def test_response_has_rates_and_regime_vector(self, _mock_rates, _mock_stress):
        r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("rates", body)
        self.assertIn("regime_vector", body)
        self.assertIn("available", body["rates"])
        self.assertIn("available", body["regime_vector"])

    @patch("api.compute_stress_regime", side_effect=Exception("boom"))
    @patch("api.compute_rates_context", side_effect=Exception("boom"))
    def test_graceful_degradation(self, _mock_rates, _mock_stress):
        r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["rates"]["available"])
        self.assertFalse(body["regime_vector"]["available"])


if __name__ == "__main__":
    unittest.main()
