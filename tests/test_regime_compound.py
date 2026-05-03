"""
tests/test_regime_compound.py

Contract tests for the compound-regime layer built on top of the
7-axis regime vector.

Covers:
  1. classify_compound_regime: every labelled rule fires on a clean
     vector, the confidence floor gates low-confidence candidates,
     unavailable vectors return the "none" sentinel.
  2. detect_regime_transition: stable / shifting / flipping / unavailable
     states are returned for the right axis-diff patterns and
     opposite-pair axis flips are always detected.
  3. baseline_from_events: modal axis values are selected; small
     samples return None; events without a usable regime_snapshot are
     ignored.
  4. enrich_with_compound_regime: additive — never strips existing
     vector keys; attaches compound + transition; safe on None input.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from regime_compound import (
    _COMPOUND_CONFIDENCE_FLOOR,
    baseline_from_events,
    classify_compound_regime,
    detect_regime_transition,
    enrich_with_compound_regime,
)
from regime_vector import REGIME_AXES


# ---------------------------------------------------------------------------
# Fixture helper — start from a fully-neutral available vector and override.
# ---------------------------------------------------------------------------

def _vec(**overrides) -> dict:
    base: dict = {axis: "neutral" for axis in REGIME_AXES}
    base["available"] = True
    base["stale"] = False
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. classify_compound_regime
# ---------------------------------------------------------------------------

class TestClassifyCompoundRegime(unittest.TestCase):
    """Every labelled rule must fire on its canonical axis pattern."""

    def test_unavailable_vector_returns_none_sentinel(self):
        out = classify_compound_regime(None)
        self.assertEqual(out["label"], "none")
        self.assertEqual(out["confidence"], 0.0)
        self.assertIn("unavailable", out["rationale"].lower())

    def test_vector_missing_available_flag_returns_none(self):
        out = classify_compound_regime(_vec(available=False))
        self.assertEqual(out["label"], "none")

    def test_reflation_canonical_vector(self):
        out = classify_compound_regime(_vec(
            inflation="hot", growth_stress="calm",
            credit="risk_on", curve_shape="parallel", fx="dollar_weak",
        ))
        self.assertEqual(out["label"], "reflation")
        self.assertGreaterEqual(out["confidence"], _COMPOUND_CONFIDENCE_FLOOR)
        self.assertIn("inflation", out["matched_axes"])

    def test_stagflation_pulse_canonical_vector(self):
        out = classify_compound_regime(_vec(
            inflation="hot", policy_stance="hawkish",
            growth_stress="stressed", curve_shape="front_loaded",
            inflation_path="hawkish_constraint",
        ))
        self.assertEqual(out["label"], "stagflation_pulse")
        self.assertGreaterEqual(out["confidence"], _COMPOUND_CONFIDENCE_FLOOR)

    def test_funding_stress_canonical_vector(self):
        out = classify_compound_regime(_vec(
            growth_stress="stressed", credit="risk_off",
            fx="dollar_strong", policy_stance="hawkish",
        ))
        self.assertEqual(out["label"], "funding_stress")

    def test_growth_scare_canonical_vector(self):
        out = classify_compound_regime(_vec(
            growth_stress="stressed", inflation="cool",
            policy_stance="dovish", credit="risk_off",
            curve_shape="parallel", inflation_path="dovish_space",
        ))
        self.assertEqual(out["label"], "growth_scare")

    def test_supply_squeeze_canonical_vector(self):
        out = classify_compound_regime(_vec(
            inflation="hot", curve_shape="front_loaded",
            inflation_path="hawkish_constraint",
            growth_stress="calm", policy_stance="hawkish",
        ))
        self.assertEqual(out["label"], "supply_squeeze")

    def test_disinflation_relief_canonical_vector(self):
        out = classify_compound_regime(_vec(
            inflation="cool", policy_stance="dovish",
            credit="risk_on", curve_shape="parallel",
            fx="dollar_weak", inflation_path="dovish_space",
        ))
        self.assertEqual(out["label"], "disinflation_relief")

    def test_all_neutral_vector_returns_none(self):
        """A vector where every axis is neutral matches no rule."""
        out = classify_compound_regime(_vec())
        self.assertEqual(out["label"], "none")

    def test_partial_match_below_floor_returns_none_with_candidate(self):
        """A vector that satisfies only the HARD gate of one rule but
        carries no supporting axes should stay below the floor."""
        # reflation requires inflation=hot and growth_stress in {calm, watch}.
        # Supply none of the supports; confidence should be 2 / (2 + 0.5*3)
        # = 0.571 which is below the 0.60 floor.
        out = classify_compound_regime(_vec(
            inflation="hot", growth_stress="calm",
        ))
        self.assertEqual(out["label"], "none")
        self.assertLess(out["confidence"], _COMPOUND_CONFIDENCE_FLOOR)
        # The would-be match must surface as a candidate so callers can
        # see the near-miss.
        labels = [c["label"] for c in out["candidates"]]
        self.assertIn("reflation", labels)


# ---------------------------------------------------------------------------
# 2. detect_regime_transition
# ---------------------------------------------------------------------------

class TestDetectRegimeTransition(unittest.TestCase):

    def test_unavailable_current(self):
        out = detect_regime_transition(None, _vec())
        self.assertEqual(out["state"], "unavailable")

    def test_unavailable_baseline(self):
        out = detect_regime_transition(_vec(), None)
        self.assertEqual(out["state"], "unavailable")

    def test_identical_vectors_are_stable(self):
        v = _vec(inflation="hot", policy_stance="hawkish")
        out = detect_regime_transition(v, v)
        self.assertEqual(out["state"], "stable")
        self.assertEqual(out["changed_axes"], [])

    def test_single_axis_change_is_stable(self):
        """<=1 axis diff stays within the stable band (so long as it's
        not an opposite-pair flip)."""
        a = _vec(inflation="hot")
        b = _vec(inflation="hot", fx="dollar_weak")  # fx drifts neutral→weak
        out = detect_regime_transition(a, b)
        self.assertEqual(out["state"], "stable")

    def test_multi_axis_change_is_shifting(self):
        a = _vec(inflation="hot", policy_stance="hawkish")
        b = _vec(inflation="hot", policy_stance="hawkish",
                 fx="dollar_weak", growth_stress="watch",
                 curve_shape="front_loaded")
        out = detect_regime_transition(b, a)
        self.assertEqual(out["state"], "shifting")
        self.assertGreaterEqual(len(out["changed_axes"]), 2)

    def test_opposite_pair_flip_is_flipping(self):
        """Even a single opposite-pair flip dominates the verdict."""
        a = _vec(credit="risk_on")
        b = _vec(credit="risk_off")
        out = detect_regime_transition(b, a)
        self.assertEqual(out["state"], "flipping")
        # changed_axes entry must carry the "flip" direction tag.
        axes = {c["axis"]: c["direction"] for c in out["changed_axes"]}
        self.assertEqual(axes.get("credit"), "flip")

    def test_inflation_path_flip_detected(self):
        """Covers the new-axis opposite pair added by the breadth expansion."""
        a = _vec(inflation_path="hawkish_constraint")
        b = _vec(inflation_path="dovish_space")
        out = detect_regime_transition(b, a)
        self.assertEqual(out["state"], "flipping")

    def test_drift_to_neutral_is_not_a_flip(self):
        a = _vec(credit="risk_on")
        b = _vec(credit="neutral")
        out = detect_regime_transition(b, a)
        # Single axis change, not a flip → stable state.
        self.assertEqual(out["state"], "stable")
        axes = {c["axis"]: c["direction"] for c in out["changed_axes"]}
        self.assertEqual(axes.get("credit"), "toward_neutral")


# ---------------------------------------------------------------------------
# 3. baseline_from_events
# ---------------------------------------------------------------------------

class TestBaselineFromEvents(unittest.TestCase):

    def _event(self, **axes) -> dict:
        return {"regime_snapshot": _vec(**axes)}

    def test_none_and_empty_input(self):
        self.assertIsNone(baseline_from_events(None))
        self.assertIsNone(baseline_from_events([]))

    def test_below_min_sample_returns_none(self):
        events = [self._event(inflation="hot"), self._event(inflation="hot")]
        self.assertIsNone(baseline_from_events(events))

    def test_unavailable_snapshots_ignored(self):
        good = self._event(inflation="hot")
        bad = {"regime_snapshot": {"available": False}}
        events = [good, bad, bad]
        # Only 1 usable snapshot → below min_sample → None.
        self.assertIsNone(baseline_from_events(events))

    def test_mode_selection(self):
        events = [
            self._event(inflation="hot", credit="risk_on"),
            self._event(inflation="hot", credit="risk_off"),
            self._event(inflation="cool", credit="risk_on"),
        ]
        b = baseline_from_events(events)
        self.assertIsNotNone(b)
        self.assertTrue(b["available"])
        self.assertEqual(b["inflation"], "hot")    # 2 vs 1
        self.assertEqual(b["credit"], "risk_on")   # 2 vs 1

    def test_tie_break_toward_most_recent(self):
        """With a tie, the most-recent (first-listed) value wins."""
        events = [
            self._event(inflation="hot"),    # newest
            self._event(inflation="cool"),   # 1 each → tie
        ]
        # 2 events total is below min_sample=3; raise the event count.
        events = events + [self._event(inflation="neutral")]
        b = baseline_from_events(events)
        self.assertIsNotNone(b)
        # All three appear once → mode by count is tied; tie-break picks
        # the newest, which is "hot" (first in list).
        self.assertEqual(b["inflation"], "hot")


# ---------------------------------------------------------------------------
# 4. enrich_with_compound_regime
# ---------------------------------------------------------------------------

class TestEnrichWithCompoundRegime(unittest.TestCase):

    def test_none_vector_returns_shape_with_unavailable_markers(self):
        out = enrich_with_compound_regime(None, None)
        self.assertIsInstance(out, dict)
        self.assertEqual(out["compound"]["label"], "none")
        self.assertEqual(out["transition"]["state"], "unavailable")

    def test_preserves_existing_axis_keys(self):
        v = _vec(inflation="hot", credit="risk_on", growth_stress="calm")
        out = enrich_with_compound_regime(v, None)
        for axis in REGIME_AXES:
            self.assertEqual(out[axis], v[axis],
                             f"axis {axis!r} overwritten")

    def test_attaches_compound_and_transition(self):
        current = _vec(
            inflation="hot", growth_stress="calm",
            credit="risk_on", curve_shape="parallel", fx="dollar_weak",
        )
        baseline = _vec(
            inflation="cool", growth_stress="stressed", credit="risk_off",
        )
        out = enrich_with_compound_regime(current, baseline)
        self.assertEqual(out["compound"]["label"], "reflation")
        self.assertIn(out["transition"]["state"], {"shifting", "flipping"})


if __name__ == "__main__":
    unittest.main()
