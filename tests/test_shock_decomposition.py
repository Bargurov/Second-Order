"""
tests/test_shock_decomposition.py

Focused tests for the Real vs Nominal shock decomposition composer.

Four required scenarios:
  1. Inflation-expectation-led case (breakevens dominant)
  2. Real-rate-led case (TIP move dominant)
  3. FX / commodity-led case
  4. Stale / unavailable macro context

Plus a small set of supporting tests for the secondary list, the
"all-quiet" primary='none' branch, and api.py wiring.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shock_decomposition import (  # noqa: E402
    CHANNEL_IDS,
    compute_shock_decomposition,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures — mirror compute_rates_context / compute_stress_regime
# ---------------------------------------------------------------------------

def _rates(nominal_5d=None, real_5d=None, breakeven_5d=None,
           regime: str = "Mixed") -> dict:
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


def _stress(haven_assets: dict | None = None) -> dict:
    """Mirror compute_stress_regime() with the safe_haven detail block."""
    return {
        "regime": "Calm",
        "signals": {
            "vix_elevated": False,
            "term_inversion": False,
            "credit_widening": False,
            "safe_haven_bid": False,
            "breadth_deterioration": False,
        },
        "raw": {"vix": 17.0},
        "detail": {
            "safe_haven": {
                "label": "Safe Haven Flows",
                "assets": haven_assets or {},
                "inflow_count": 0,
                "status": "calm",
                "explanation": "",
            },
        },
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
# Required scenario 1 — inflation-expectation-led
# ---------------------------------------------------------------------------

class TestBreakevenLed(unittest.TestCase):

    def test_breakeven_dominates_when_be_proxy_is_largest(self):
        # Big breakeven proxy move (0.7%, ~3.5σ) — much bigger than nominal
        # (0.2%, 1σ) and real (0.1% TIP, 0.2σ).
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.2, real_5d=0.1, breakeven_5d=0.7,
                                 regime="Inflation pressure"),
            stress_regime=_stress(),
            snapshots=None,
        )
        self.assertEqual(result["primary"], "breakeven")
        self.assertEqual(result["primary_label"], "Breakeven inflation")
        self.assertIn("inflation expectations", result["macro_read"].lower())
        self.assertTrue(result["available"])
        self.assertIn("TIP", result["key_markets"])
        # Channel grid present and exhaustive.
        for cid in CHANNEL_IDS:
            self.assertIn(cid, result["channels"])

    def test_breakeven_secondary_includes_nominal_when_close(self):
        # Nominal also moving meaningfully — should appear as secondary.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.5, real_5d=0.0, breakeven_5d=0.5,
                                 regime="Inflation pressure"),
            stress_regime=_stress(),
            snapshots=None,
        )
        # Breakeven scale = 0.2 → z=2.5; Nominal scale = 0.2 → z=2.5.
        # Tie broken by sort order; either may win, but the loser must be
        # secondary.
        self.assertIn(result["primary"], ("breakeven", "nominal_yield"))
        secondary_ids = {s["id"] for s in result["secondary"]}
        other = "nominal_yield" if result["primary"] == "breakeven" else "breakeven"
        self.assertIn(other, secondary_ids)


# ---------------------------------------------------------------------------
# Required scenario 2 — real-rate-led
# ---------------------------------------------------------------------------

class TestRealRateLed(unittest.TestCase):

    def test_real_rate_dominates_when_tip_move_largest(self):
        # TIP fell 1.5% (real yields rising fast) — z = 3.0
        # Nominal up 0.2% (1σ), breakeven down 1.3% (~6.5σ — actually larger!)
        # so let me make breakeven smaller. Use real_5d=-1.5, nominal_5d=0.1
        # → breakeven proxy = 0.1 + (-1.5) = -1.4 → 7σ. That overshoots.
        #
        # Instead, set nominal=-1.4 and real=-1.5 → breakeven_proxy=-2.9.
        # Real z = 1.5/0.5 = 3.0; nominal z = 1.4/0.2 = 7.0; breakeven=2.9/0.2=14.5.
        # Breakeven would dominate.
        #
        # The cleanest "real-rate-led" test passes the breakeven proxy
        # explicitly so we can isolate it.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.05, real_5d=-1.5, breakeven_5d=-0.1,
                                 regime="Real-rate tightening"),
            stress_regime=_stress(),
            snapshots=None,
        )
        # real_z = 1.5 / 0.5 = 3.0
        # nominal_z = 0.05 / 0.2 = 0.25
        # breakeven_z = 0.1 / 0.2 = 0.5
        self.assertEqual(result["primary"], "real_yield")
        self.assertIn("real yields", result["macro_read"].lower())
        self.assertIn("TIP", result["key_markets"])
        self.assertTrue(result["available"])

    def test_real_rate_rationale_quotes_real_move(self):
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.0, real_5d=-1.2, breakeven_5d=0.0),
            stress_regime=_stress(),
            snapshots=None,
        )
        self.assertEqual(result["primary"], "real_yield")
        self.assertIn("real yields", result["rationale"].lower())
        self.assertIn("-1.20", result["rationale"])


# ---------------------------------------------------------------------------
# Required scenario 3 — FX / commodity-led
# ---------------------------------------------------------------------------

class TestFXCommodityLed(unittest.TestCase):

    def test_fx_dominates_when_dxy_jumps(self):
        # DXY +2.0% / 5d → z = 2.0/0.7 = 2.85.
        # Rates moves modest (z < 1) — FX should win.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.1, real_5d=0.0, breakeven_5d=0.1),
            stress_regime=_stress(),
            snapshots=[_snap("DXY", 2.0)],
        )
        self.assertEqual(result["primary"], "fx")
        self.assertIn("dollar", result["macro_read"].lower())
        self.assertIn("DXY", result["key_markets"])
        self.assertTrue(result["available"])

    def test_commodity_dominates_when_crude_spikes(self):
        # Crude +6% / 5d → z = 6.0/3.0 = 2.0. Rates quiet → commodity wins.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.1, real_5d=0.0, breakeven_5d=0.1),
            stress_regime=_stress(),
            snapshots=[_snap("CL", 6.0), _snap("GC", 0.5)],
        )
        self.assertEqual(result["primary"], "commodity")
        self.assertIn("commodity", result["macro_read"].lower())
        self.assertIn("CL", result["key_markets"])
        # Internal payload exposes the leg breakdown for the UI.
        commodity = result["channels"]["commodity"]
        self.assertEqual(commodity["leader"], "crude")
        self.assertIn("crude_5d", commodity)
        self.assertIn("gold_5d", commodity)

    def test_fx_falls_back_to_safe_haven_dollar_when_no_snapshot(self):
        # No DXY snapshot, but stress_regime exposes Dollar via safe_haven.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.05, real_5d=0.0, breakeven_5d=0.05),
            stress_regime=_stress(haven_assets={"Dollar": 1.8, "Gold": 0.2,
                                                 "Long Bonds": 0.1}),
            snapshots=None,
        )
        self.assertEqual(result["primary"], "fx")
        self.assertTrue(result["channels"]["fx"]["available"])

    def test_commodity_uses_gold_when_only_gold_provided(self):
        # Crude unavailable; gold +3% / 5d → gold_z = 3.0/1.5 = 2.0.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.0, real_5d=0.0, breakeven_5d=0.0),
            stress_regime=_stress(haven_assets={"Gold": 3.0, "Dollar": 0.1,
                                                 "Long Bonds": 0.0}),
            snapshots=None,
        )
        self.assertEqual(result["primary"], "commodity")
        self.assertEqual(result["channels"]["commodity"]["leader"], "gold")


# ---------------------------------------------------------------------------
# Required scenario 4 — stale / unavailable macro
# ---------------------------------------------------------------------------

class TestStaleMacro(unittest.TestCase):

    def test_no_inputs_returns_empty_dict(self):
        result = compute_shock_decomposition(
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        # Hard short-circuit — UI skips the card.
        self.assertEqual(result, {})

    def test_partial_macro_marks_block_stale(self):
        # Only nominal yield available; everything else missing.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.6, real_5d=None, breakeven_5d=None),
            stress_regime=None,
            snapshots=None,
        )
        self.assertTrue(result)
        # Only one channel available → stale flag set.
        self.assertTrue(result["stale"])
        self.assertTrue(result["available"])
        # The available channel can still drive the primary.
        self.assertEqual(result["primary"], "nominal_yield")
        self.assertFalse(result["channels"]["real_yield"]["available"])
        self.assertFalse(result["channels"]["fx"]["available"])

    def test_empty_dict_rates_and_stress_returns_empty(self):
        result = compute_shock_decomposition(
            rates_context={},
            stress_regime={},
            snapshots=None,
        )
        # Neither leg usable → nothing to show.
        self.assertEqual(result, {})

    def test_all_quiet_yields_primary_none(self):
        # All channels available but every move below the noise band.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.05, real_5d=0.05, breakeven_5d=0.05),
            stress_regime=_stress(haven_assets={"Dollar": 0.1, "Gold": 0.1,
                                                 "Long Bonds": 0.0}),
            snapshots=[_snap("CL", 0.4), _snap("DXY", 0.1)],
        )
        self.assertTrue(result)
        self.assertEqual(result["primary"], "none")
        self.assertEqual(result["primary_label"], "No clear shock")
        self.assertEqual(result["key_markets"], [])
        self.assertIn("quiet", result["macro_read"].lower())
        # Block is "available" — macro is fine, just calm. Not "stale".
        self.assertTrue(result["available"])


# ---------------------------------------------------------------------------
# Block shape contract
# ---------------------------------------------------------------------------

class TestBlockShape(unittest.TestCase):

    def test_full_block_has_required_fields(self):
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.3, real_5d=-0.6, breakeven_5d=-0.3),
            stress_regime=_stress(),
            snapshots=[_snap("DXY", 0.4), _snap("CL", 1.0), _snap("GC", 0.5)],
        )
        for key in (
            "primary",
            "primary_label",
            "secondary",
            "rationale",
            "macro_read",
            "key_markets",
            "channels",
            "available",
            "stale",
        ):
            self.assertIn(key, result, f"missing field: {key}")

        # Channels payload covers every channel id.
        for cid in CHANNEL_IDS:
            self.assertIn(cid, result["channels"])
            entry = result["channels"][cid]
            for k in ("label", "move_5d", "available", "z"):
                self.assertIn(k, entry)

    def test_secondary_capped_and_well_formed(self):
        # Several channels active → secondary list still capped.
        result = compute_shock_decomposition(
            rates_context=_rates(nominal_5d=0.4, real_5d=-0.8, breakeven_5d=-0.4),
            stress_regime=_stress(),
            snapshots=[_snap("DXY", 1.0), _snap("CL", 4.0)],
        )
        self.assertLessEqual(len(result["secondary"]), 3)
        for s in result["secondary"]:
            for k in ("id", "label", "move_5d", "z"):
                self.assertIn(k, s)


# ---------------------------------------------------------------------------
# api.py wiring — make sure the field reaches the /analyze response
# ---------------------------------------------------------------------------

class TestAnalyzeWiring(unittest.TestCase):

    def setUp(self):
        os.environ["ANTHROPIC_API_KEY"] = ""  # force mock path
        from fastapi.testclient import TestClient
        import api
        self.api = api
        self.client = TestClient(api.app)

    def _fake_analyze_event(self, headline, stage, persistence, event_context="", model=None):
        return {
            "what_changed": "Macro shock test event.",
            "mechanism_summary": "Generic mechanism for wiring test.",
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "assets_to_watch": [],
            "confidence": "low",
            "transmission_chain": [],
            "if_persists": {},
            "currency_channel": {},
        }

    def _fake_rates(self):
        return _rates(nominal_5d=0.05, real_5d=-1.2, breakeven_5d=-0.1,
                      regime="Real-rate tightening")

    def _fake_stress(self):
        return _stress()

    def _fake_rates_stale(self):
        return _rates(nominal_5d=None, real_5d=None, breakeven_5d=None)

    def _fake_stress_none(self):
        return None

    def _stub_market_check(self, *_args, **_kwargs):
        return {"note": "", "details": {}, "tickers": []}

    def test_shock_decomposition_present_on_analyze(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "Macro shock test event"},
            )
        self.assertEqual(r.status_code, 200)
        sd = r.json()["analysis"].get("shock_decomposition")
        self.assertIsInstance(sd, dict)
        self.assertEqual(sd["primary"], "real_yield")
        self.assertTrue(sd["available"])

    def test_shock_decomposition_empty_when_macro_unavailable(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_stale), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress_none), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "Macro shock test event"},
            )
        self.assertEqual(r.status_code, 200)
        sd = r.json()["analysis"].get("shock_decomposition")
        # Either empty dict or a stale-marked block — both acceptable graceful states.
        self.assertIsInstance(sd, dict)
        if sd:
            self.assertTrue(sd.get("stale") or not sd.get("available"))


if __name__ == "__main__":
    unittest.main()
