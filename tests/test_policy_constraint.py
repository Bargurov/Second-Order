"""
tests/test_policy_constraint.py

Focused tests for the Policy Constraint Engine.

Four core scenarios required by the task:
  1. Inflation-bound case
  2. Growth-bound case
  3. Conflicting / mixed constraints
  4. Stale or unavailable macro context

Plus a small set of supporting tests for the scoring, policy_room
classification, and the api.py wiring path so the block survives an
end-to-end /analyze call.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from policy_constraint import (  # noqa: E402
    CONSTRAINT_IDS,
    compute_policy_constraint,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures — mirror compute_rates_context / compute_stress_regime
# ---------------------------------------------------------------------------

def _rates(regime: str, nominal_5d=0.2, real_5d=0.1, breakeven_5d=0.1) -> dict:
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
    vix_elevated: bool = False,
    credit_widening: bool = False,
    term_inversion: bool = False,
    safe_haven_bid: bool = False,
    breadth_deterioration: bool = False,
) -> dict:
    return {
        "regime": regime,
        "signals": {
            "vix_elevated": vix_elevated,
            "credit_widening": credit_widening,
            "term_inversion": term_inversion,
            "safe_haven_bid": safe_haven_bid,
            "breadth_deterioration": breadth_deterioration,
        },
        "raw": {"VIX": 17.4, "HYG": 77.0, "SHY": 82.3},
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
# Required scenario 1 — inflation-bound case
# ---------------------------------------------------------------------------

class TestInflationBound(unittest.TestCase):

    def test_inflation_pressure_regime_binds_inflation(self):
        result = compute_policy_constraint(
            "OPEC slashes output by 2 mbpd",
            "Supply shock lifts crude price; tariff and shipping cost "
            "transmit to consumers via passthrough.",
            rates_context=_rates("Inflation pressure", 0.5, 0.05, 0.75),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("GC", 2.5), _snap("CL", 4.0)],
        )
        self.assertEqual(result["binding"], "inflation")
        self.assertEqual(result["binding_label"], "Inflation")
        self.assertIn("10Y", result["key_markets"])
        self.assertIn("TIP", result["key_markets"])
        self.assertIn("GC", result["key_markets"])
        self.assertTrue(result["available"])
        self.assertFalse(result["stale"])
        # Reaction function must be non-empty and mention hawkish posture.
        self.assertIn("hawkish", result["reaction_function"].lower())
        # Signals object exposes raw scores for transparency.
        self.assertIn("inflation", result["signals"])
        self.assertGreaterEqual(result["signals"]["inflation"], 3.0)

    def test_inflation_bound_policy_room_ample_when_isolated(self):
        # Only inflation scores — no growth / fin-stab / fiscal pressure.
        result = compute_policy_constraint(
            "Energy price surge after pipeline outage",
            "Crude price rallies on supply shock; input cost passes through.",
            rates_context=_rates("Inflation pressure", 0.3, 0.0, 0.5),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("GC", 2.5), _snap("CL", 4.0)],
        )
        self.assertEqual(result["binding"], "inflation")
        self.assertIn(result["policy_room"], ("ample", "limited"))
        self.assertEqual(result["secondary"], [])


# ---------------------------------------------------------------------------
# Required scenario 2 — growth-bound case
# ---------------------------------------------------------------------------

class TestGrowthBound(unittest.TestCase):

    def test_risk_off_regime_with_equity_selloff_binds_growth(self):
        result = compute_policy_constraint(
            "ISM plunges into contraction",
            "PMI and payrolls soften; consumer pullback drives slowdown and recession fears.",
            rates_context=_rates("Risk-off / growth scare", -0.3, 0.2, -0.4),
            stress_regime=_stress("Calm", safe_haven_bid=True),
            snapshots=[_snap("ES", -2.8), _snap("DXY", 0.3)],
        )
        self.assertEqual(result["binding"], "growth")
        self.assertEqual(result["binding_label"], "Growth")
        self.assertIn("ES", result["key_markets"])
        self.assertIn("HYG", result["key_markets"])
        self.assertIn("dovish", result["reaction_function"].lower())
        self.assertTrue(result["available"])
        self.assertFalse(result["stale"])

    def test_growth_score_dominates_inflation(self):
        result = compute_policy_constraint(
            "Payrolls miss and jobless claims spike",
            "Labor softening and demand destruction feed recession talk.",
            rates_context=_rates("Risk-off / growth scare", -0.4, 0.1, -0.3),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("ES", -3.1)],
        )
        self.assertEqual(result["binding"], "growth")
        self.assertGreater(result["signals"]["growth"], result["signals"]["inflation"])


# ---------------------------------------------------------------------------
# Required scenario 3 — conflicting / mixed constraints
# ---------------------------------------------------------------------------

class TestMixedConstraints(unittest.TestCase):

    def test_inflation_and_growth_both_active_yields_conflict(self):
        # Stagflation shape: tariff + import cost keywords (inflation) colliding
        # with risk-off regime + equity selloff (growth).
        result = compute_policy_constraint(
            "Tariff shock meets recession fears",
            "Tariff and import cost passthrough collide with recession and "
            "payrolls softening; growth scare alongside supply shock.",
            rates_context=_rates("Inflation pressure", 0.4, 0.05, 0.55),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("ES", -2.5), _snap("CL", 3.5)],
        )
        # With inflation regime + crude rally + inflation keywords, inflation
        # usually wins, but growth must show up as a strong secondary and
        # policy_room should signal conflict.
        self.assertIn(result["binding"], ("inflation", "growth"))
        self.assertIn(result["policy_room"], ("constrained", "mixed"))
        # Secondary list must be populated — this is the whole point of
        # the conflict surface.
        self.assertTrue(result["secondary"])
        secondary_ids = {item["id"] for item in result["secondary"]}
        # Whichever of {inflation, growth} isn't binding must show up as secondary.
        other = "growth" if result["binding"] == "inflation" else "inflation"
        self.assertIn(other, secondary_ids)

    def test_financial_stability_vs_inflation_constrained(self):
        # Inflation thesis, but credit is blowing out and VIX is elevated.
        result = compute_policy_constraint(
            "OPEC output cut lands mid-credit-stress",
            "Supply shock and crude price surge feed input cost passthrough.",
            rates_context=_rates("Inflation pressure", 0.3, 0.0, 0.5),
            stress_regime=_stress(
                "Systemic Stress",
                vix_elevated=True,
                credit_widening=True,
                term_inversion=True,
            ),
            snapshots=[_snap("GC", 2.8)],
        )
        self.assertIn(result["policy_room"], ("constrained", "mixed"))
        # Both inflation and financial_stability must score meaningfully.
        self.assertGreaterEqual(result["signals"]["inflation"], 3.0)
        self.assertGreaterEqual(result["signals"]["financial_stability"], 3.0)
        # Why-sentence must mention the competing mandate when constrained.
        if result["policy_room"] == "constrained":
            self.assertIn("constrained", result["why"].lower())


# ---------------------------------------------------------------------------
# Required scenario 4 — stale / unavailable macro
# ---------------------------------------------------------------------------

class TestStaleMacro(unittest.TestCase):

    def test_no_macro_but_strong_keywords_returns_stale_block(self):
        result = compute_policy_constraint(
            "OPEC supply shock lifts crude",
            "Tariff and input cost drive passthrough; sticky inflation keywords.",
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        # Keywords alone → block is returned but flagged stale/unavailable.
        self.assertTrue(result)  # not {}
        self.assertEqual(result["binding"], "inflation")
        self.assertFalse(result["available"])
        self.assertTrue(result["stale"])
        self.assertEqual(result["policy_room"], "unknown")

    def test_empty_dict_rates_and_stress_degrades(self):
        result = compute_policy_constraint(
            "Payrolls soft; recession risk rising",
            "Layoffs and softening demand feed growth scare.",
            rates_context={},
            stress_regime={},
            snapshots=None,
        )
        self.assertTrue(result)
        self.assertEqual(result["binding"], "growth")
        self.assertFalse(result["available"])
        self.assertTrue(result["stale"])

    def test_no_signal_no_macro_returns_empty_dict(self):
        # Non-macro event AND no usable macro → nothing to render.
        result = compute_policy_constraint(
            "Tech CEO resigns abruptly",
            "Board names interim leader; no near-term financial impact.",
            rates_context=None,
            stress_regime=None,
            snapshots=None,
        )
        self.assertEqual(result, {})

    def test_usable_stress_without_rates_partial_degrade(self):
        result = compute_policy_constraint(
            "Credit spreads blow out on funding stress",
            "HY spreads widen and dealer balance sheets show strain.",
            rates_context=None,
            stress_regime=_stress(
                "Elevated",
                vix_elevated=True,
                credit_widening=True,
            ),
            snapshots=None,
        )
        self.assertTrue(result)
        self.assertEqual(result["binding"], "financial_stability")
        # One leg usable → available but flagged stale (not both legs healthy).
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])

    def test_usable_rates_without_stress_partial_degrade(self):
        result = compute_policy_constraint(
            "Energy price surge",
            "Crude price and tariff drive input cost passthrough.",
            rates_context=_rates("Inflation pressure", 0.5, 0.0, 0.7),
            stress_regime=None,
            snapshots=None,
        )
        self.assertTrue(result)
        self.assertEqual(result["binding"], "inflation")
        self.assertTrue(result["available"])
        self.assertTrue(result["stale"])


# ---------------------------------------------------------------------------
# Structural contract — shape of the returned block
# ---------------------------------------------------------------------------

class TestBlockShape(unittest.TestCase):

    def test_all_required_fields_present_in_full_block(self):
        result = compute_policy_constraint(
            "OPEC output cut",
            "Supply shock drives crude price; input cost passthrough.",
            rates_context=_rates("Inflation pressure", 0.4, 0.05, 0.6),
            stress_regime=_stress("Calm"),
            snapshots=[_snap("GC", 2.5)],
        )
        for key in (
            "binding",
            "binding_label",
            "secondary",
            "policy_room",
            "why",
            "reaction_function",
            "key_markets",
            "signals",
            "available",
            "stale",
        ):
            self.assertIn(key, result, f"missing field: {key}")

        # Signals must cover every constraint id so the UI never KeyErrors.
        for cid in CONSTRAINT_IDS:
            self.assertIn(cid, result["signals"])

        # Secondary entries (if any) must be well-formed.
        for item in result["secondary"]:
            for k in ("id", "label", "score", "rationale"):
                self.assertIn(k, item)

    def test_key_markets_are_stable_strings(self):
        # Sanity: we ship canonical market IDs the frontend already knows.
        result = compute_policy_constraint(
            "OPEC output cut",
            "Supply shock drives crude price.",
            rates_context=_rates("Inflation pressure", 0.5, 0.0, 0.6),
            stress_regime=_stress("Calm"),
            snapshots=None,
        )
        self.assertTrue(all(isinstance(m, str) for m in result["key_markets"]))
        self.assertGreater(len(result["key_markets"]), 0)


# ---------------------------------------------------------------------------
# api.py wiring — ensure the block reaches the /analyze response
# ---------------------------------------------------------------------------

class TestAnalyzeWiring(unittest.TestCase):
    """End-to-end check that policy_constraint lands on the analyze payload.

    We patch analyze_event(), compute_rates_context(), compute_stress_regime(),
    and market_check() so no LLM or network call happens, then call /analyze
    via TestClient.
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
                "Supply shock lifts crude price; tariff and input cost "
                "transmit to consumers via passthrough."
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

    def _fake_rates_inflation(self):
        return _rates("Inflation pressure", 0.5, 0.05, 0.7)

    def _fake_rates_stale(self):
        return _rates("Mixed", None, None, None)

    def _fake_stress_calm(self):
        return _stress("Calm")

    def _fake_stress_none(self):
        return None

    def _stub_market_check(self, *_args, **_kwargs):
        return {"note": "", "details": {}, "tickers": []}

    def test_policy_constraint_present_on_analyze(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_inflation), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress_calm), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        pc = r.json()["analysis"].get("policy_constraint")
        self.assertIsInstance(pc, dict)
        self.assertEqual(pc["binding"], "inflation")
        self.assertTrue(pc["available"])

    def test_policy_constraint_degrades_when_macro_stale(self):
        with patch.object(self.api, "analyze_event", side_effect=self._fake_analyze_event), \
             patch.object(self.api, "compute_rates_context", side_effect=self._fake_rates_stale), \
             patch.object(self.api, "compute_stress_regime", side_effect=self._fake_stress_none), \
             patch.object(self.api, "market_check", side_effect=self._stub_market_check):
            r = self.client.post(
                "/analyze",
                json={"headline": "OPEC slashes output by 2 mbpd"},
            )
        self.assertEqual(r.status_code, 200)
        pc = r.json()["analysis"].get("policy_constraint")
        self.assertIsInstance(pc, dict)
        self.assertTrue(pc.get("stale"))


if __name__ == "__main__":
    unittest.main()
