"""
tests/test_market_context_engine_blocks.py

Contract tests for the deeper macro-engine blocks surfaced on
``/market-context`` — the data feeding the Market Overview panel.

Covers:
  1. compose_market_context carries the new optional blocks through
     the composition shape.
  2. /market-context endpoint computes credit_regime, funding_stress_mode,
     sector_rotation, and finance_playbook from the same rates/stress
     inputs it already fetches (no extra provider calls).
  3. Missing composer output degrades to ``{"available": False}`` rather
     than dropping the key — the frontend can always branch on presence.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")


# ---------------------------------------------------------------------------
# Minimal fixture inputs
# ---------------------------------------------------------------------------

def _stress_with(hyg_5d=-1.5, vix=28.0) -> dict:
    """Stress-regime dict with enough raw data to drive the new composers."""
    return {
        "regime": "Undercurrent",
        "signals": {
            "vix_elevated":          vix >= 20.0,
            "term_inversion":         False,
            "credit_widening":        hyg_5d <= -1.0,
            "safe_haven_bid":         True,
            "breadth_deterioration":  True,
        },
        "raw": {
            "vix":       vix,
            "hyg_5d":    hyg_5d,
            "lqd_5d":    -0.3,
            "shy_5d":    0.1,
            "crude_5d":  3.0,
            "gold_5d":   1.5,
        },
        "detail":  {"safe_haven": {"assets": {"Dollar": 1.2}}},
        "summary": "",
    }


def _rates_with(tnx_5d=0.30) -> dict:
    return {
        "regime":          "Mixed",
        "available":       True,
        "nominal":         {"label": "10Y", "value": 4.3, "change_5d": tnx_5d},
        "real_proxy":      {"label": "TIP", "value": 110.0, "change_5d": -0.1},
        "breakeven_proxy": {"label": "BE",  "change_5d": 0.1},
        "breakeven_curve": {"available": True, "shape": "parallel_up",
                            "policy_space": "narrow_hawkish"},
        "raw":             {},
    }


# ---------------------------------------------------------------------------
# 1. Composer shape carries the new blocks
# ---------------------------------------------------------------------------

class TestComposerCarriesNewBlocks(unittest.TestCase):

    def test_compose_market_context_emits_new_keys(self):
        from market_context import compose_market_context
        out = compose_market_context(
            [], None, [],
            credit_regime={"regime": "default_risk_widening", "available": True},
            funding_stress_mode={"available": True,
                                  "primary_mode": "credit_widening",
                                  "composite_severity": "elevated"},
            sector_rotation={"available": True,
                              "broad_market_tilt": "risk_off",
                              "sectors": []},
            finance_playbook={"available": True, "headline": "test"},
        )
        for key in ("credit_regime", "funding_stress_mode",
                    "sector_rotation", "finance_playbook"):
            self.assertIn(key, out, f"{key!r} missing from market_context output")

    def test_missing_blocks_degrade_to_unavailable_sentinel(self):
        from market_context import compose_market_context
        out = compose_market_context([], None, [])
        for key in ("credit_regime", "funding_stress_mode",
                    "sector_rotation", "finance_playbook"):
            self.assertIn(key, out)
            self.assertFalse(out[key]["available"],
                             f"{key!r} should be marked unavailable")

    def test_non_dict_inputs_do_not_crash(self):
        from market_context import compose_market_context
        out = compose_market_context(
            [], None, [],
            credit_regime=None,
            funding_stress_mode="not a dict",  # type: ignore[arg-type]
            sector_rotation=[],                # type: ignore[arg-type]
            finance_playbook={"available": True, "headline": "ok"},
        )
        self.assertFalse(out["credit_regime"]["available"])
        self.assertFalse(out["funding_stress_mode"]["available"])
        self.assertFalse(out["sector_rotation"]["available"])
        self.assertTrue(out["finance_playbook"]["available"])


# ---------------------------------------------------------------------------
# 2. /market-context endpoint wires the composers
# ---------------------------------------------------------------------------

class TestMarketContextEndpointWiresEngineBlocks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as api_module
        cls.client = TestClient(api_module.app)

    def test_endpoint_emits_all_four_engine_keys(self):
        """With real rates + stress patched in, every new block must be
        present AND marked available — no silent drop."""
        with patch("api.compute_rates_context", return_value=_rates_with(tnx_5d=0.30)), \
             patch("api.compute_stress_regime", return_value=_stress_with(hyg_5d=-1.5, vix=28.0)), \
             patch("api.movers_today", return_value=[]), \
             patch("api.compute_news_uncertainty",
                   return_value={"uncertainty_scope": "global",
                                 "sector_uncertainty": [],
                                 "lead_sector": None}):
            r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()

        # Every new key is present.
        for key in ("credit_regime", "funding_stress_mode",
                    "sector_rotation", "finance_playbook"):
            self.assertIn(key, body, f"{key!r} absent from /market-context response")

        # With stress + rates populated, credit_regime + funding + rotation
        # must all be available.
        self.assertTrue(body["credit_regime"]["available"])
        self.assertTrue(body["funding_stress_mode"]["available"])
        self.assertTrue(body["sector_rotation"]["available"])
        self.assertTrue(body["finance_playbook"]["available"])

    def test_funding_mode_reflects_credit_widening(self):
        """HY down 1.5% + VIX elevated + breadth => classifier should
        fire credit_widening + liquidity_squeeze."""
        with patch("api.compute_rates_context", return_value=_rates_with(tnx_5d=0.10)), \
             patch("api.compute_stress_regime", return_value=_stress_with(hyg_5d=-1.5, vix=28.0)), \
             patch("api.movers_today", return_value=[]), \
             patch("api.compute_news_uncertainty", return_value={"uncertainty_scope": "global",
                                                                  "sector_uncertainty": [],
                                                                  "lead_sector": None}):
            r = self.client.get("/market-context")
        body = r.json()
        mode = body["funding_stress_mode"]
        self.assertIn("credit_widening", mode["active_modes"])

    def test_sector_rotation_produces_ranked_sectors(self):
        """A stress + rates tape must produce at least a few sectors
        scored with direction != neutral."""
        with patch("api.compute_rates_context", return_value=_rates_with(tnx_5d=0.35)), \
             patch("api.compute_stress_regime", return_value=_stress_with(hyg_5d=-0.2, vix=18.0)), \
             patch("api.movers_today", return_value=[]), \
             patch("api.compute_news_uncertainty", return_value={"uncertainty_scope": "global",
                                                                  "sector_uncertainty": [],
                                                                  "lead_sector": None}):
            r = self.client.get("/market-context")
        rotation = r.json()["sector_rotation"]
        directions = {s["direction"] for s in rotation["sectors"]}
        # At least one winner + at least one loser for a 0.35pp 10Y shock.
        self.assertIn("winner", directions)
        self.assertIn("loser", directions)

    def test_playbook_headline_is_populated_when_engine_fires(self):
        with patch("api.compute_rates_context", return_value=_rates_with(tnx_5d=0.35)), \
             patch("api.compute_stress_regime", return_value=_stress_with(hyg_5d=-1.8, vix=30.0)), \
             patch("api.movers_today", return_value=[]), \
             patch("api.compute_news_uncertainty", return_value={"uncertainty_scope": "global",
                                                                  "sector_uncertainty": [],
                                                                  "lead_sector": None}):
            r = self.client.get("/market-context")
        playbook = r.json()["finance_playbook"]
        self.assertTrue(playbook["available"])
        self.assertIsInstance(playbook["headline"], str)
        self.assertGreater(len(playbook["headline"]), 0)

    def test_provider_failure_still_emits_keys(self):
        """When BOTH rates and stress fail, every engine block must
        still exist as an ``available=False`` sentinel so the frontend
        renders a clean empty state."""
        with patch("api.compute_rates_context", side_effect=RuntimeError("yf down")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("yf down")), \
             patch("api.movers_today", return_value=[]), \
             patch("api.compute_news_uncertainty", return_value={"uncertainty_scope": "global",
                                                                  "sector_uncertainty": [],
                                                                  "lead_sector": None}):
            r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        for key in ("credit_regime", "funding_stress_mode",
                    "sector_rotation", "finance_playbook"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
