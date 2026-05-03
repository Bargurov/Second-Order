"""Tests for presentation_deck.build_presentation_deck().

All tests are pure / offline — no network, no DB, no mocks.
"""
import unittest

from presentation_deck import build_presentation_deck


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _ev(
    headline="China restricts rare earth exports",
    event_date="2026-04-10",
    stage="escalation",
    persistence="persistent",
    confidence="high",
    rating="good",
    what_changed="China announced new restrictions on rare earth exports. Effective immediately.",
    mechanism_summary="Supply constraints raise input costs for Western defence and EV manufacturers.",
    beneficiaries=None,
    losers=None,
    market_tickers=None,
    shock_decomposition=None,
    policy_sensitivity=None,
    policy_constraint=None,
    if_persists=None,
):
    return {
        "id": 1,
        "headline": headline,
        "event_date": event_date,
        "timestamp": f"{event_date}T10:00:00",
        "stage": stage,
        "persistence": persistence,
        "confidence": confidence,
        "rating": rating,
        "what_changed": what_changed,
        "mechanism_summary": mechanism_summary,
        "beneficiaries": beneficiaries or ["MP Materials", "Lynas"],
        "losers": losers or ["NVDA", "Lockheed Martin"],
        "market_tickers": market_tickers if market_tickers is not None else [
            {"symbol": "NVDA", "role": "loser", "return_1d": -3.2,
             "return_5d": -5.1, "return_20d": -8.4, "direction_tag": "supports mechanism"},
            {"symbol": "MP", "role": "beneficiary", "return_1d": 4.1,
             "return_5d": 6.2, "return_20d": None, "direction_tag": "supports mechanism"},
        ],
        "shock_decomposition": shock_decomposition if shock_decomposition is not None else {
            "primary": "supply_shock", "primary_label": "Supply Shock",
        },
        "policy_sensitivity": policy_sensitivity or {
            "regime": "tightening", "stance": "hawkish",
            "explanation": "Fed unlikely to ease given supply-driven inflation.",
        },
        "policy_constraint": policy_constraint or {"binding": True, "binding_label": "inflation ceiling"},
        "if_persists": if_persists if if_persists is not None else {
            "substitution": "substitute to domestic rare earth suppliers",
            "delayed_winners": ["MP Materials"],
            "delayed_losers": ["INTC"],
        },
    }


def _low_ev(**kwargs):
    """Low-confidence variant."""
    return _ev(**{"confidence": "low", "rating": "mixed", **kwargs})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTitleSection(unittest.TestCase):
    def test_title_and_event_count_present(self):
        result = build_presentation_deck([_ev(), _ev(headline="Second event", event_date="2026-04-11")])
        self.assertIn("Briefing Deck", result)
        self.assertIn("2", result)  # event count


class TestExecutiveSummary(unittest.TestCase):
    def test_uses_only_high_confidence_events_when_available(self):
        high = _ev(headline="High conf event", confidence="high",
                   what_changed="Major supply shock announced.")
        low = _low_ev(headline="Low conf event",
                      what_changed="Minor adjustment noted.")
        result = build_presentation_deck([high, low])
        self.assertIn("High conf event", result)
        # low-confidence should not appear in exec summary
        exec_section = result.split("## Key Themes")[0]
        self.assertNotIn("Low conf event", exec_section)

    def test_falls_back_to_all_events_when_no_high_confidence(self):
        ev1 = _low_ev(headline="Medium event one", confidence="medium")
        ev2 = _low_ev(headline="Medium event two", confidence="medium")
        result = build_presentation_deck([ev1, ev2])
        exec_section = result.split("## Key Themes")[0]
        self.assertIn("Medium event one", exec_section)
        self.assertIn("Medium event two", exec_section)


class TestKeyThemes(unittest.TestCase):
    def test_deduplicates_stages(self):
        evs = [
            _ev(stage="escalation"),
            _ev(stage="escalation"),
            _ev(stage="anticipation"),
        ]
        result = build_presentation_deck(evs)
        themes = result.split("## 1.")[0]
        # "escalation" should appear once in themes, not twice
        self.assertEqual(themes.count("escalation"), 1)
        self.assertIn("anticipation", themes)

    def test_entity_frequency_shows_recurring_entities(self):
        # NVDA appears in losers of both events → should show with ×2
        ev1 = _ev(losers=["NVDA", "AAPL"])
        ev2 = _ev(losers=["NVDA", "Boeing"])
        result = build_presentation_deck([ev1, ev2])
        themes = result.split("## 1.")[0]
        self.assertIn("NVDA", themes)
        self.assertIn("×2", themes)

    def test_entity_appearing_once_excluded_from_frequency(self):
        ev1 = _ev(losers=["NVDA", "AAPL"])
        ev2 = _ev(losers=["NVDA", "Boeing"])
        result = build_presentation_deck([ev1, ev2])
        themes = result.split("## 1.")[0]
        # AAPL and Boeing each appear once — should not be in recurring entities
        self.assertNotIn("AAPL ×", themes)
        self.assertNotIn("Boeing ×", themes)


class TestPerEventSection(unittest.TestCase):
    def test_all_expected_bullet_labels_present(self):
        result = build_presentation_deck([_ev()])
        self.assertIn("**Thesis:**", result)
        self.assertIn("**Mechanism:**", result)
        self.assertIn("**Beneficiaries:**", result)
        self.assertIn("**Losers:**", result)
        self.assertIn("**Top signal:**", result)
        self.assertIn("**Policy:**", result)
        self.assertIn("**Shock type:**", result)

    def test_missing_tickers_omits_top_signal_bullet(self):
        ev = _ev(market_tickers=[])
        result = build_presentation_deck([ev])
        self.assertNotIn("**Top signal:**", result)

    def test_missing_shock_decomposition_omits_shock_type_bullet(self):
        ev = _ev(shock_decomposition={})
        result = build_presentation_deck([ev])
        self.assertNotIn("**Shock type:**", result)


class TestRisksSection(unittest.TestCase):
    def test_risks_is_union_of_all_losers_deduped(self):
        ev1 = _ev(losers=["NVDA", "AAPL"])
        ev2 = _ev(losers=["NVDA", "Boeing"])
        result = build_presentation_deck([ev1, ev2])
        risks_section = result.split("## Risks")[1].split("##")[0]
        self.assertIn("NVDA", risks_section)
        self.assertIn("AAPL", risks_section)
        self.assertIn("Boeing", risks_section)
        # NVDA should appear once, not twice
        self.assertEqual(risks_section.count("NVDA"), 1)


class TestEdgeCases(unittest.TestCase):
    def test_empty_events_list_renders_without_error(self):
        result = build_presentation_deck([])
        self.assertIsInstance(result, str)
        self.assertIn("Briefing Deck", result)

    def test_single_event_produces_complete_output(self):
        result = build_presentation_deck([_ev()])
        self.assertIn("## Executive Summary", result)
        self.assertIn("## Key Themes", result)
        self.assertIn("## Risks", result)
        self.assertIn("## Closing", result)


if __name__ == "__main__":
    unittest.main()
