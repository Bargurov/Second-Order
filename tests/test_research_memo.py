# tests/test_research_memo.py
"""Tests for api._build_event_research_memo()."""
import unittest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import api


def _full_event() -> dict:
    return {
        "id": 1,
        "headline": "US imposes new tariffs on Chinese semiconductors",
        "event_date": "2026-04-10",
        "timestamp": "2026-04-10T14:32:00",
        "stage": "escalation",
        "persistence": "persistent",
        "confidence": "high",
        "what_changed": "The US announced 25% tariffs on Chinese semiconductor imports.",
        "mechanism_summary": "Higher input costs flow through to device makers, compressing margins.",
        "beneficiaries": ["INTC", "domestic fabs"],
        "losers": ["NVDA", "AAPL supply chain"],
        "market_tickers": [
            {
                "symbol": "NVDA", "role": "loser",
                "return_1d": -3.2, "return_5d": -5.1, "return_20d": -8.4,
                "volume_ratio": 2.1, "direction_tag": "supports mechanism",
            },
        ],
        "market_note": "Options market pricing further downside.",
        "shock_decomposition": {"primary": "supply_shock", "primary_label": "Supply Shock"},
        "surprise_vs_anticipation": {
            "regime_label": "Surprise Shock",
            "rationale": "Move concentrated in today's tape; VIX 5d +2.10.",
        },
        "policy_sensitivity": {
            "regime": "tightening",
            "stance": "hawkish",
            "explanation": "Fed unlikely to ease given tariff-driven inflation.",
        },
        "real_yield_context": {
            "thesis": "Real yields rising",
            "explanation": "TIP underperforming TLT on 5d basis.",
        },
    }


class TestSectionLabels(unittest.TestCase):
    def test_thesis_label_not_what_changed(self):
        result = api._build_event_research_memo(_full_event())
        self.assertIn("## Thesis", result)
        self.assertNotIn("## What Changed", result)


class TestSectionOrder(unittest.TestCase):
    def test_sections_appear_in_correct_order(self):
        result = api._build_event_research_memo(_full_event())
        positions = {
            "thesis": result.index("## Thesis"),
            "mechanism": result.index("## Mechanism"),
            "affected": result.index("## Beneficiaries"),
            "market": result.index("## Market Validation"),
            "context": result.index("## Key Context"),
        }
        ordered = sorted(positions.values())
        self.assertEqual(list(positions.values()), ordered)


class TestMissingThesis(unittest.TestCase):
    def test_thesis_section_omitted_when_what_changed_absent(self):
        ev = _full_event()
        del ev["what_changed"]
        result = api._build_event_research_memo(ev)
        self.assertNotIn("## Thesis", result)


class TestMissingBeneficiariesLosers(unittest.TestCase):
    def test_section_omitted_when_both_absent(self):
        ev = _full_event()
        ev["beneficiaries"] = []
        ev["losers"] = []
        result = api._build_event_research_memo(ev)
        self.assertNotIn("## Beneficiaries", result)


class TestMissingTickers(unittest.TestCase):
    def test_market_validation_omitted_when_no_tickers(self):
        ev = _full_event()
        ev["market_tickers"] = []
        result = api._build_event_research_memo(ev)
        self.assertNotIn("## Market Validation", result)


class TestKeyContextAllAbsent(unittest.TestCase):
    def test_key_context_section_omitted_when_all_overlays_empty(self):
        ev = _full_event()
        ev["shock_decomposition"] = {}
        ev["surprise_vs_anticipation"] = {}
        ev["policy_sensitivity"] = {}
        ev["real_yield_context"] = {}
        result = api._build_event_research_memo(ev)
        self.assertNotIn("## Key Context", result)


class TestKeyContextPartial(unittest.TestCase):
    def test_only_shock_line_rendered_when_only_shock_present(self):
        ev = _full_event()
        ev["surprise_vs_anticipation"] = {}
        ev["policy_sensitivity"] = {}
        ev["real_yield_context"] = {}
        result = api._build_event_research_memo(ev)
        self.assertIn("## Key Context", result)
        self.assertIn("Supply Shock", result)
        self.assertNotIn("Priced-in", result)
        self.assertNotIn("Policy stance", result)
        self.assertNotIn("Rates alignment", result)


class TestMarketNote(unittest.TestCase):
    def test_market_note_appears_as_blockquote(self):
        result = api._build_event_research_memo(_full_event())
        self.assertIn("> Options market pricing further downside.", result)


if __name__ == "__main__":
    unittest.main()
