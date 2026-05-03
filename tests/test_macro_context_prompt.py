"""
tests/test_macro_context_prompt.py

Tests for build_macro_context_for_prompt() — the function that converts
compute_rates_context() / compute_stress_regime() output into a compact
structured string for LLM prompt injection.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from market_check import build_macro_context_for_prompt


def _rates(regime="risk-off", tnx=4.45, tnx_chg=-0.12, tip_chg=-0.8, be=0.06):
    return {
        "regime": regime,
        "nominal": tnx_chg,
        "real_proxy": tip_chg,
        "breakeven_proxy": be,
        "raw": {
            "tnx": tnx,
            "tnx_change_5d": tnx_chg,
            "tip_change_5d": tip_chg,
            "breakeven_proxy_5d": be,
        },
    }


def _stress(regime="risk-off", vix=23.4, vix_avg20=18.2, signals=None):
    if signals is None:
        signals = {"vix_elevated": True, "term_inversion": False,
                   "credit_widening": False, "safe_haven_bid": False,
                   "breadth_deterioration": False}
    return {
        "regime": regime,
        "signals": signals,
        "raw": {"vix": vix, "vix_avg20": vix_avg20},
    }


class BuildMacroContextForPromptTest(unittest.TestCase):

    def test_empty_dicts_returns_empty_string(self):
        result = build_macro_context_for_prompt(rates={}, stress={})
        self.assertEqual(result, "")

    def test_none_dicts_returns_empty_string(self):
        """Passing both as empty-like dicts (no data) → empty string."""
        result = build_macro_context_for_prompt(rates={"raw": {}}, stress={"signals": {}, "raw": {}})
        self.assertEqual(result, "")

    def test_contains_header_when_data_present(self):
        result = build_macro_context_for_prompt(_rates(), _stress())
        self.assertIn("Macro backdrop", result)

    def test_contains_regime(self):
        result = build_macro_context_for_prompt(_rates(regime="risk-off"), _stress())
        self.assertIn("risk-off", result)

    def test_contains_10y_nominal(self):
        result = build_macro_context_for_prompt(_rates(tnx=4.45, tnx_chg=-0.12), _stress())
        self.assertIn("4.45%", result)
        self.assertIn("-0.12pp", result)

    def test_contains_vix(self):
        result = build_macro_context_for_prompt(_rates(), _stress(vix=23.4))
        self.assertIn("23.4", result)

    def test_vix_elevated_label(self):
        result = build_macro_context_for_prompt(
            _rates(),
            _stress(signals={"vix_elevated": True, "term_inversion": False,
                              "credit_widening": False, "safe_haven_bid": False,
                              "breadth_deterioration": False}),
        )
        self.assertIn("VIX elevated", result)

    def test_active_signals_listed(self):
        stress = _stress(signals={
            "vix_elevated": True,
            "term_inversion": True,
            "credit_widening": False,
            "safe_haven_bid": False,
            "breadth_deterioration": False,
        })
        result = build_macro_context_for_prompt(_rates(), stress)
        self.assertIn("VIX elevated", result)
        self.assertIn("yield curve inverted", result)
        self.assertNotIn("credit spreads", result)

    def test_no_active_signals_omits_signals_line(self):
        stress = _stress(signals={
            "vix_elevated": False, "term_inversion": False,
            "credit_widening": False, "safe_haven_bid": False,
            "breadth_deterioration": False,
        })
        result = build_macro_context_for_prompt(_rates(), stress)
        self.assertNotIn("Active stress signals", result)

    def test_breakeven_direction_widening(self):
        result = build_macro_context_for_prompt(_rates(be=0.10), _stress())
        self.assertIn("widening", result)

    def test_breakeven_direction_narrowing(self):
        result = build_macro_context_for_prompt(_rates(be=-0.05), _stress())
        self.assertIn("narrowing", result)

    def test_real_yield_rising_when_tip_positive(self):
        # TIP price up → real yields falling (bond prices up = yields down)
        # Our label: "falling real yields" when tip_chg > 0
        result = build_macro_context_for_prompt(_rates(tip_chg=0.5), _stress())
        self.assertIn("falling real yields", result)

    def test_real_yield_rising_when_tip_negative(self):
        # TIP price down → real yields rising
        result = build_macro_context_for_prompt(_rates(tip_chg=-0.8), _stress())
        self.assertIn("rising real yields", result)

    def test_graceful_on_missing_optional_fields(self):
        """Partial rates data — only tnx present — should still work."""
        rates = {"regime": "neutral", "raw": {"tnx": 4.20}}
        stress = {"signals": {}, "raw": {}}
        result = build_macro_context_for_prompt(rates, stress)
        self.assertIn("4.20%", result)
        self.assertNotIn("Real yield", result)
        self.assertNotIn("Breakeven", result)

    def test_underscore_regime_converted_to_dash(self):
        result = build_macro_context_for_prompt(_rates(regime="risk_off"), _stress())
        self.assertIn("risk-off", result)
        self.assertNotIn("risk_off", result)


if __name__ == "__main__":
    unittest.main()
