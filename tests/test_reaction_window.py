"""Tests for reaction_window — priced-in / reaction-window detection.

Covers:
  * High priced_in_risk fires when pre-event drift dominates the
    post-event move on a non-anticipation event.
  * Anticipation events tolerate larger pre-event drift before the
    gate fires.
  * Low priced_in_risk when post-event tape leads.
  * thesis_state demotes "supportive" to "mixed" when the
    reaction_window blocks confirmation.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from reaction_window import (
    compute_reaction_window,
    reaction_window_blocks_confirmation,
)
from thesis_state import THESIS_STATES, derive_thesis_state


def _ev(**overrides):
    base = {
        "event_date":            "2026-04-25",
        "timestamp":             "2026-04-25T10:00:00",
        "last_market_check_at":  "2026-04-25T11:00:00",
        "stale_signal":          "fresh",
        "persistence_signal":    {"status": "watching"},
        "minimum_proof_set":     [
            {"observation": "spread widens", "channel": "commodities"},
        ],
        "key_falsifiers":        [
            {"observation": "spread collapses", "channel": "commodities"},
        ],
        "confidence":            "medium",
        "mechanism_summary":     (
            "Saudi liftings cut tightens Gulf coker feedstock and "
            "widens the WCS-WTI heavy-sour discount."
        ),
        "stage":                 "realized",
        "beneficiary_tickers":   ["CVX"],
        "loser_tickers":         [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Composer behaviour
# ---------------------------------------------------------------------------


class TestReactionWindowComposer(unittest.TestCase):
    def test_high_risk_when_pre_drift_dominates(self):
        """Realized event with +4% pre-drift and only +0.4% post → high
        priced_in_risk."""
        ev = _ev(
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 0.4},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": 4.0},
            },
        )
        out = compute_reaction_window(ev)
        self.assertTrue(out["available"])
        self.assertEqual(out["priced_in_risk"], "high")
        self.assertAlmostEqual(out["pre_event_move"], 4.0, places=2)

    def test_anticipation_tolerates_larger_pre_drift(self):
        """Same +4% pre-drift on an anticipation event → not high
        (anticipation events are *expected* to drift before the
        headline)."""
        ev = _ev(
            stage="anticipation",
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 0.4},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": 4.0},
            },
        )
        out = compute_reaction_window(ev)
        self.assertEqual(out["priced_in_risk"], "medium")

    def test_anticipation_high_when_pre_drift_clears_higher_threshold(self):
        """Anticipation events still flag high when pre-drift is
        large enough (≥5%) and post-event is weak."""
        ev = _ev(
            stage="anticipation",
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 0.5},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": 6.0},
            },
        )
        out = compute_reaction_window(ev)
        self.assertEqual(out["priced_in_risk"], "high")

    def test_post_event_lead_collapses_priced_in_risk(self):
        """Pre-drift +4% but post-event +5% (post leads) → low risk."""
        ev = _ev(
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 5.0},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": 4.0},
            },
        )
        out = compute_reaction_window(ev)
        self.assertEqual(out["priced_in_risk"], "low")

    def test_negative_pre_drift_low_risk(self):
        """Aligned pre-drift was against the thesis (-3%) → not priced
        in; risk low."""
        ev = _ev(
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 1.0},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": -3.0},
            },
        )
        out = compute_reaction_window(ev)
        self.assertEqual(out["priced_in_risk"], "low")

    def test_no_data_returns_empty_shape(self):
        """No SVA debug, no per-ticker pre_event_drift, no
        market_tickers → stable empty shape."""
        ev = _ev(market_tickers=[])
        out = compute_reaction_window(ev)
        self.assertFalse(out["available"])
        self.assertEqual(
            set(out.keys()),
            {"available", "pre_event_move", "post_event_move",
             "priced_in_risk", "rationale"},
        )

    def test_non_dict_input_returns_empty(self):
        for bad in (None, "garbage", 123, []):
            out = compute_reaction_window(bad)
            self.assertFalse(out["available"])

    def test_loser_role_aligned_for_pre_drift(self):
        """Loser role: a positive 5d return is contradicting (loser
        rallied), so the aligned post-event move flips negative."""
        ev = _ev(
            beneficiary_tickers=[],
            loser_tickers=["XOM"],
            market_tickers=[
                {"symbol": "XOM", "role": "loser", "return_5d": 1.0},
            ],
            surprise_vs_anticipation={
                "debug": {"pre_event_drift_pct": 1.0},
            },
        )
        out = compute_reaction_window(ev)
        # Aligned post move: loser up by +1% → role-aligned -1%.
        self.assertAlmostEqual(out["post_event_move"], -1.0, places=2)


# ---------------------------------------------------------------------------
# thesis_state gate
# ---------------------------------------------------------------------------


class TestThesisStatePricedInGate(unittest.TestCase):
    """When ``reaction_window`` reports high priced_in_risk and the
    weighted_evidence is supportive, the state must NOT resolve to
    ``confirming`` — the supportive read is anticipation tape, not
    fresh confirmation.  Mirror of the broad-beta downgrade."""

    def test_high_priced_in_risk_blocks_confirming(self):
        ev = _ev(
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary",
                 "evidence_score": 0.85, "return_5d": 0.4,
                 "direction_tag": "supports up"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
            reaction_window={
                "available":       True,
                "pre_event_move":  4.0,
                "post_event_move": 0.4,
                "priced_in_risk":  "high",
                "rationale":       "test",
            },
        )
        state = derive_thesis_state(ev)
        # No falsifier overrides → supportive → demoted to mixed →
        # falls through to partial / watching ladder, NOT confirming.
        self.assertNotEqual(state, "confirming")
        self.assertIn(state, THESIS_STATES)

    def test_low_priced_in_risk_does_not_block(self):
        """Same fixture but reaction_window flags low risk →
        confirming holds."""
        ev = _ev(
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary",
                 "evidence_score": 0.85, "return_5d": 4.0,
                 "direction_tag": "supports up"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
            reaction_window={
                "available":       True,
                "pre_event_move":  1.0,
                "post_event_move": 4.0,
                "priced_in_risk":  "low",
                "rationale":       "test",
            },
        )
        state = derive_thesis_state(ev)
        self.assertEqual(state, "confirming")

    def test_blocks_confirmation_helper_returns_false_without_block(self):
        """Helper returns False when the event has no reaction_window
        block — the gate doesn't fire on legacy events."""
        ev = _ev(market_tickers=[])
        # No SVA debug, no per-ticker pre-drift → reaction_window
        # composer returns available=False.
        self.assertFalse(reaction_window_blocks_confirmation(ev))


if __name__ == "__main__":
    unittest.main()
