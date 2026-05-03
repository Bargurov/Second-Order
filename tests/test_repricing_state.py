"""
tests/test_repricing_state.py

Validates the repricing-state classifier added to persistence_signal.
Representative cases for every label + edge cases on the thresholds.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from persistence_signal import (  # noqa: E402
    REPRICING_STATES,
    _classify_repricing_state,
    _aligned_returns,
    _role_sign,
    _GAP_SIGNIFICANCE_PP,
    _HOLD_BAND_LOW,
    _HOLD_BAND_HIGH,
    _RETRACE_MAX_FRACTION,
    _SECOND_LEG_MULT,
    _GRIND_R1_MAX_PP,
    _GRIND_R5_MIN_PP,
    _INVALIDATION_FLOOR_PP,
    classify_persistence_signal,
)


def _tkr(symbol, role, r1=None, r5=None, r20=None, direction_tag="supports_thesis"):
    return {
        "symbol": symbol, "role": role, "direction_tag": direction_tag,
        "return_1d": r1, "return_5d": r5, "return_20d": r20,
    }


def _event(now: datetime, tickers=None, age_days=5, persistence="medium",
           revisit_snapshots=None):
    return {
        "persistence": persistence,
        "event_date": (now - timedelta(days=age_days)).strftime("%Y-%m-%d"),
        "market_tickers": tickers or [],
        "revisit_snapshots": revisit_snapshots or [],
    }


class TestRoleAlignment(unittest.TestCase):

    def test_beneficiary_sign_positive(self):
        self.assertEqual(_role_sign("beneficiary"), 1.0)

    def test_loser_sign_negative(self):
        self.assertEqual(_role_sign("loser"), -1.0)

    def test_unknown_defaults_to_beneficiary(self):
        self.assertEqual(_role_sign(""), 1.0)

    def test_aligned_returns_flips_loser_signs(self):
        tickers = [
            _tkr("AAA", "beneficiary", r1=+2.0, r5=+2.2),
            _tkr("BBB", "loser",       r1=-1.0, r5=-1.2),
        ]
        agg = _aligned_returns(tickers)
        # Loser's -1/-1.2 get flipped to +1/+1.2; averaged with +2/+2.2
        self.assertAlmostEqual(agg["r1"], 1.5, places=3)
        self.assertAlmostEqual(agg["r5"], 1.7, places=3)
        self.assertEqual(agg["n"], 2)


class TestRepricingStates(unittest.TestCase):

    def test_gap_and_hold_r1_holds_through_r5(self):
        # r1 = +2.0%, r5 = +1.9% → ratio 0.95 → inside hold band
        agg = {"r1": 2.0, "r5": 1.9, "r20": None, "n": 1}
        state, evidence = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "gap_and_hold")
        self.assertIn("held", evidence.lower())

    def test_retrace_r5_material_give_back(self):
        # r1 = +2.0%, r5 = +0.7% → ratio 0.35 → retrace (< _RETRACE_MAX_FRACTION)
        agg = {"r1": 2.0, "r5": 0.7, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "retrace")

    def test_second_leg_r20_extends_past_r5(self):
        # r5 = +1.5%, r20 = +2.5% → 2.5/1.5 = 1.67 > _SECOND_LEG_MULT
        agg = {"r1": 0.5, "r5": 1.5, "r20": 2.5, "n": 1}
        state, evidence = _classify_repricing_state(agg, age_days=20, past_horizon=False)
        self.assertEqual(state, "second_leg")
        self.assertIn("extending", evidence.lower())

    def test_fade_sign_flip_between_r1_and_r5(self):
        # r1 = +1.5%, r5 = -1.0% → fade
        agg = {"r1": 1.5, "r5": -1.0, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "fade")

    def test_invalidation_r20_against_thesis(self):
        # r20 below _INVALIDATION_FLOOR_PP → invalidation regardless of r5
        agg = {"r1": 0.5, "r5": 0.7, "r20": -1.5, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=25, past_horizon=True)
        self.assertEqual(state, "invalidation")

    def test_grind_small_r1_builds_large_r5(self):
        # r1 = +0.3%, r5 = +1.8% → grind
        agg = {"r1": 0.3, "r5": 1.8, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "grind")

    def test_watching_when_no_returns(self):
        agg = {"r1": None, "r5": None, "r20": None, "n": 0}
        state, _ = _classify_repricing_state(agg, age_days=1, past_horizon=False)
        self.assertEqual(state, "watching")

    def test_resolved_past_horizon_no_other_pattern(self):
        # tiny moves, past horizon → resolved
        agg = {"r1": 0.05, "r5": 0.05, "r20": 0.05, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=25, past_horizon=True)
        self.assertEqual(state, "resolved")


class TestThresholdEdges(unittest.TestCase):

    def test_gap_edge_just_below_significance_is_not_gap(self):
        # r1 just below _GAP_SIGNIFICANCE_PP
        r1 = _GAP_SIGNIFICANCE_PP - 0.01
        agg = {"r1": r1, "r5": r1, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertNotEqual(state, "gap_and_hold")

    def test_hold_band_high_edge(self):
        # ratio at upper band edge should still be gap_and_hold
        r1 = 2.0
        r5 = 2.0 * _HOLD_BAND_HIGH  # exactly at top of band
        agg = {"r1": r1, "r5": r5, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "gap_and_hold")

    def test_hold_band_low_edge(self):
        r1 = 2.0
        r5 = 2.0 * _HOLD_BAND_LOW
        agg = {"r1": r1, "r5": r5, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "gap_and_hold")

    def test_retrace_edge_just_below_max_fraction(self):
        # ratio just below _RETRACE_MAX_FRACTION → retrace
        r1 = 2.0
        r5 = 2.0 * (_RETRACE_MAX_FRACTION - 0.01)
        agg = {"r1": r1, "r5": r5, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "retrace")

    def test_second_leg_edge_just_above_multiplier(self):
        r5 = 1.0
        r20 = r5 * (_SECOND_LEG_MULT + 0.01)
        agg = {"r1": 0.3, "r5": r5, "r20": r20, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=20, past_horizon=False)
        self.assertEqual(state, "second_leg")

    def test_grind_edge_r1_at_cap(self):
        r1 = _GRIND_R1_MAX_PP
        r5 = _GRIND_R5_MIN_PP + 0.1
        agg = {"r1": r1, "r5": r5, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "grind")

    def test_invalidation_edge_exactly_at_floor(self):
        # r20 at exactly _INVALIDATION_FLOOR_PP should trigger (≤ rule)
        agg = {"r1": 0.5, "r5": 0.5, "r20": _INVALIDATION_FLOOR_PP, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=25, past_horizon=True)
        self.assertEqual(state, "invalidation")


class TestPriorityOrder(unittest.TestCase):
    """Invalidation > fade > second_leg > gap/retrace > grind."""

    def test_invalidation_trumps_positive_r5(self):
        # r5 is positive but r20 crashes → invalidation still wins
        agg = {"r1": 1.5, "r5": 1.0, "r20": -2.0, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=25, past_horizon=True)
        self.assertEqual(state, "invalidation")

    def test_fade_trumps_gap_when_r5_flipped(self):
        # r1 clears gap threshold but r5 is negative → fade
        agg = {"r1": 2.0, "r5": -0.5, "r20": None, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=5, past_horizon=False)
        self.assertEqual(state, "fade")

    def test_second_leg_trumps_grind_when_r20_extends(self):
        # Grind pattern BUT r20 extends → second_leg (evaluated first)
        agg = {"r1": 0.3, "r5": 1.5, "r20": 2.5, "n": 1}
        state, _ = _classify_repricing_state(agg, age_days=20, past_horizon=False)
        self.assertEqual(state, "second_leg")


class TestPublicIntegration(unittest.TestCase):

    def test_public_output_includes_repricing_block(self):
        now = datetime(2026, 4, 18, 12, 0)
        ev = _event(now, tickers=[
            _tkr("AAA", "beneficiary", r1=+2.0, r5=+2.1, r20=None),
        ], age_days=5, persistence="medium")
        result = classify_persistence_signal(ev, now=now)
        self.assertIn("repricing", result)
        rep = result["repricing"]
        for k in ("state", "label", "evidence", "source", "metrics"):
            self.assertIn(k, rep)
        self.assertIn(rep["state"], REPRICING_STATES)
        # Shortcuts exposed at top level for easy UI consumption.
        self.assertIn("repricing_state", result)
        self.assertIn("repricing_label", result)

    def test_public_uses_revisit_when_available(self):
        now = datetime(2026, 4, 18, 12, 0)
        snap = {
            "day": 20,
            "tickers": [
                _tkr("AAA", "beneficiary", r1=+0.1, r5=+0.1, r20=+2.5,
                     direction_tag="supports_thesis"),
            ],
        }
        ev = _event(now, tickers=[
            _tkr("AAA", "beneficiary", r1=+2.0, r5=+2.0),
        ], age_days=22, persistence="medium", revisit_snapshots=[snap])
        result = classify_persistence_signal(ev, now=now)
        # Revisit tickers preferred — source should be "revisit"
        self.assertEqual(result["repricing"]["source"], "revisit")
        self.assertEqual(result["repricing"]["metrics"]["thesis_aligned_r20"], 2.5)

    def test_backward_compat_legacy_fields_preserved(self):
        # Ensure legacy consumers still see status/label/evidence/horizon_days/days_elapsed.
        now = datetime(2026, 4, 18, 12, 0)
        ev = _event(now, tickers=[], age_days=1, persistence="medium")
        result = classify_persistence_signal(ev, now=now)
        for k in ("status", "label", "evidence", "horizon_days", "days_elapsed"):
            self.assertIn(k, result)


if __name__ == "__main__":
    unittest.main()
