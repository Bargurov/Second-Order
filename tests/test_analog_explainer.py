"""Tests for the regime-aware analog explainer.

Covers:
  * Each analog gains four match dimensions (mechanism_family, regime,
    inflation_rates, credit) with the correct three-state status
  * Mechanism family match / mismatch / unknown handling
  * Single-axis (credit) and multi-axis (regime, inflation_rates)
    dimensions report consistent axes_matched / axes_comparable
  * topic_vs_regime_mismatch flag fires only when topic is similar AND
    overall regime alignment is weak
  * explainer produces a readable summary even when every input is None
  * Pure composer: input dict is not mutated
  * Graceful degrade when regime snapshots are missing on either side
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analog_explainer import (
    explain_analog,
    explain_analogs,
    _topic_regime_divergence,
    _TOPIC_SIMILAR_FLOOR,
    _REGIME_WEAK_RATIO,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _regime(**overrides) -> dict:
    base = {
        "available":      True,
        "inflation":      "hot",
        "policy_stance":  "hawkish",
        "fx":             "dollar_strong",
        "growth_stress":  "calm",
        "credit":         "risk_on",
        "curve_shape":    "front_loaded",
        "inflation_path": "hawkish_constraint",
    }
    base.update(overrides)
    return base


def _analog(**overrides) -> dict:
    base = {
        "headline":         "Past event",
        "event_date":       "2025-02-14",
        "stage":            "realized",
        "persistence":      "medium",
        "confidence":       "medium",
        "return_5d":        2.3,
        "return_20d":       1.1,
        "decay":            "Holding",
        "similarity":       0.45,
        "match_reason":     "shared: cpi, hot",
        "regime_snapshot":  _regime(),
        "mechanism_family": "supply_shock",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Shape + non-mutation
# ---------------------------------------------------------------------------

class TestOutputShape(unittest.TestCase):
    def test_input_not_mutated(self):
        analog = _analog()
        snapshot_before = dict(analog)
        explain_analog(analog, current_regime=_regime(),
                       current_mechanism_family="supply_shock")
        # Original dict is untouched.
        self.assertEqual(analog, snapshot_before)

    def test_every_expected_field_present(self):
        out = explain_analog(_analog(), current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        for key in ("match_dimensions", "topic_vs_regime_mismatch",
                    "mismatch_note", "explainer"):
            self.assertIn(key, out)

    def test_four_dimensions_always_emitted(self):
        out = explain_analog(_analog(), current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        dims = {d["dimension"] for d in out["match_dimensions"]}
        self.assertEqual(dims, {"mechanism_family", "regime",
                                "inflation_rates", "credit"})


# ---------------------------------------------------------------------------
# Mechanism family dimension
# ---------------------------------------------------------------------------

class TestMechanismFamilyDimension(unittest.TestCase):
    def _dim(self, out: dict) -> dict:
        return next(d for d in out["match_dimensions"]
                    if d["dimension"] == "mechanism_family")

    def test_match_when_same_family(self):
        out = explain_analog(
            _analog(mechanism_family="supply_shock"),
            current_mechanism_family="supply_shock",
        )
        d = self._dim(out)
        self.assertEqual(d["status"], "match")
        self.assertIn("supply_shock", d["note"])

    def test_mismatch_when_different_family(self):
        out = explain_analog(
            _analog(mechanism_family="supply_shock"),
            current_mechanism_family="policy_surprise",
        )
        d = self._dim(out)
        self.assertEqual(d["status"], "mismatch")

    def test_unknown_when_either_side_missing(self):
        out_a = explain_analog(_analog(mechanism_family="none"),
                               current_mechanism_family="supply_shock")
        out_b = explain_analog(_analog(mechanism_family="supply_shock"),
                               current_mechanism_family=None)
        self.assertEqual(self._dim(out_a)["status"], "unknown")
        self.assertEqual(self._dim(out_b)["status"], "unknown")


# ---------------------------------------------------------------------------
# Regime + credit + inflation_rates dimensions
# ---------------------------------------------------------------------------

class TestRegimeDimensions(unittest.TestCase):
    def _get(self, out: dict, dimension: str) -> dict:
        return next(d for d in out["match_dimensions"] if d["dimension"] == dimension)

    def test_overall_regime_matches_when_all_axes_agree(self):
        analog = _analog(regime_snapshot=_regime())
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        d = self._get(out, "regime")
        self.assertEqual(d["status"], "match")
        self.assertEqual(d["axes_matched"], d["axes_comparable"])
        self.assertEqual(d["match_ratio"], 1.0)

    def test_overall_regime_mismatch_when_axes_diverge(self):
        analog = _analog(regime_snapshot=_regime(
            inflation="cool", policy_stance="dovish",
            fx="dollar_weak", growth_stress="stressed",
            credit="risk_off", curve_shape="term_premium",
            inflation_path="dovish_space",
        ))
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        d = self._get(out, "regime")
        self.assertEqual(d["status"], "mismatch")
        self.assertEqual(d["axes_matched"], 0)

    def test_credit_dimension_is_single_axis(self):
        analog = _analog(regime_snapshot=_regime(credit="risk_off"))
        out = explain_analog(analog, current_regime=_regime(credit="risk_on"),
                             current_mechanism_family="supply_shock")
        d = self._get(out, "credit")
        self.assertEqual(d["status"], "mismatch")
        self.assertEqual(d["current"], "risk_on")
        self.assertEqual(d["analog"], "risk_off")

    def test_inflation_rates_partial(self):
        """Half the inflation/rates axes agree → status partial."""
        analog = _analog(regime_snapshot=_regime(
            inflation="hot", policy_stance="dovish",
            inflation_path="dovish_space", curve_shape="front_loaded",
        ))
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        d = self._get(out, "inflation_rates")
        self.assertEqual(d["status"], "partial")
        self.assertEqual(d["axes_matched"], 2)
        self.assertEqual(d["axes_comparable"], 4)

    def test_unavailable_regime_reports_unknown(self):
        """Analog has no regime_snapshot → each regime dimension is unknown."""
        analog = _analog(regime_snapshot=None)
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertEqual(self._get(out, "regime")["status"], "unknown")
        self.assertEqual(self._get(out, "credit")["status"], "unknown")
        self.assertEqual(self._get(out, "inflation_rates")["status"], "unknown")

    def test_current_regime_missing_reports_unknown(self):
        out = explain_analog(_analog(), current_regime=None,
                             current_mechanism_family="supply_shock")
        for dim in ("regime", "credit", "inflation_rates"):
            self.assertEqual(
                next(d for d in out["match_dimensions"]
                     if d["dimension"] == dim)["status"],
                "unknown",
            )


# ---------------------------------------------------------------------------
# Topic-vs-regime mismatch flag — the task's headline feature
# ---------------------------------------------------------------------------

class TestTopicVsRegimeMismatch(unittest.TestCase):
    def test_fires_when_topic_strong_and_regime_weak(self):
        """Analog: high topic overlap, opposite regime → flag active."""
        analog = _analog(
            similarity=0.55,
            regime_snapshot=_regime(
                inflation="cool", policy_stance="dovish",
                fx="dollar_weak", growth_stress="stressed",
                credit="risk_off", curve_shape="term_premium",
                inflation_path="dovish_space",
            ),
        )
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertTrue(out["topic_vs_regime_mismatch"])
        self.assertIsInstance(out["mismatch_note"], str)
        self.assertIn("past playbook", out["mismatch_note"])

    def test_silent_when_topic_weak(self):
        """Low topic similarity → not a "same topic, different regime" case."""
        analog = _analog(
            similarity=0.15,  # well below _TOPIC_SIMILAR_FLOOR
            regime_snapshot=_regime(
                inflation="cool", policy_stance="dovish",
                credit="risk_off",
            ),
        )
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertFalse(out["topic_vs_regime_mismatch"])
        self.assertIsNone(out["mismatch_note"])

    def test_silent_when_regime_aligned(self):
        """Topic AND regime agree → no mismatch warning needed."""
        analog = _analog(similarity=0.6, regime_snapshot=_regime())
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertFalse(out["topic_vs_regime_mismatch"])

    def test_silent_when_regime_unavailable(self):
        """Can't diverge on regime when the analog's regime is absent."""
        analog = _analog(similarity=0.6, regime_snapshot=None)
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertFalse(out["topic_vs_regime_mismatch"])

    def test_pure_function_direct_call(self):
        """_topic_regime_divergence returns (False, '') for weak topic."""
        active, _ = _topic_regime_divergence(
            topic_similarity=_TOPIC_SIMILAR_FLOOR - 0.05,
            overall_matched=0, overall_comparable=7,
        )
        self.assertFalse(active)


# ---------------------------------------------------------------------------
# Explainer sentence
# ---------------------------------------------------------------------------

class TestExplainerSentence(unittest.TestCase):
    def test_lead_mentions_family_match(self):
        out = explain_analog(_analog(mechanism_family="supply_shock"),
                             current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertIn("same mechanism family", out["explainer"])

    def test_lead_mentions_family_mismatch(self):
        out = explain_analog(_analog(mechanism_family="supply_shock"),
                             current_regime=_regime(),
                             current_mechanism_family="policy_surprise")
        self.assertIn("different family", out["explainer"])

    def test_tail_mentions_decay_and_return(self):
        analog = _analog(return_5d=3.2, decay="Holding")
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertIn("last time", out["explainer"])
        self.assertIn("+3.2%", out["explainer"])
        self.assertIn("Holding", out["explainer"])

    def test_mismatch_note_appended_to_explainer(self):
        analog = _analog(
            similarity=0.6,
            regime_snapshot=_regime(
                inflation="cool", policy_stance="dovish",
                credit="risk_off", curve_shape="term_premium",
                inflation_path="dovish_space", fx="dollar_weak",
                growth_stress="stressed",
            ),
        )
        out = explain_analog(analog, current_regime=_regime(),
                             current_mechanism_family="supply_shock")
        self.assertIn("past playbook may not transfer", out["explainer"])


# ---------------------------------------------------------------------------
# Batch helper
# ---------------------------------------------------------------------------

class TestExplainAnalogsBatch(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(explain_analogs([]), [])

    def test_applies_to_each_entry(self):
        analogs = [_analog(headline=f"A{i}") for i in range(3)]
        out = explain_analogs(
            analogs, current_regime=_regime(),
            current_mechanism_family="supply_shock",
        )
        self.assertEqual(len(out), 3)
        for a in out:
            self.assertIn("match_dimensions", a)
            self.assertIn("explainer", a)

    def test_none_safe(self):
        """None inputs don't raise — composer degrades to unknown status."""
        out = explain_analogs([_analog()], current_regime=None,
                              current_mechanism_family=None)
        self.assertEqual(len(out), 1)
        self.assertIn("explainer", out[0])


if __name__ == "__main__":
    unittest.main()
