"""
tests/test_thesis_scorecard.py

Contract tests for the horizon-aware thesis scorecard.

Covers:
  1. Per-horizon classifier: support / contradict / flat / pending
     chosen correctly from role + return sign + noise band.
  2. Per-horizon status: confirmed requires a 2x support ratio;
     failed requires a 2x contradict ratio; mixed otherwise;
     pending when all returns at that horizon are None.
  3. Aggregate: all pending → pending; 5d or 20d failure → breaking;
     all confirmed → on_track; anything else → drifting (1d failure
     alone is drifting, not breaking).
  4. Shape: LLM-written criteria forwarded into per-horizon blocks
     even when the tickers are empty; scorecard always emits 1d/5d/20d.
  5. Revisit preference: a revisit snapshot for day N takes precedence
     over the rolling return on the initial ticker list.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from thesis_scorecard import (
    _NOISE_BAND,
    _RATIO_GATE,
    compute_thesis_scorecard,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _checkpoints(**per_horizon_kwargs) -> dict:
    """Build a minimal horizon_checkpoints payload.

    Pass per-horizon overrides like::

        _checkpoints(oned=dict(expected=["..."]), fived=dict(falsifies_if=["..."]))
    """
    def _block(name: str, kw: dict) -> dict:
        return {
            "horizon":      name,
            "expected":     kw.get("expected", [f"{name} expected default"]),
            "confirms_if":  kw.get("confirms_if", [f"{name} confirms default"]),
            "falsifies_if": kw.get("falsifies_if", [f"{name} falsifies default"]),
        }
    return {
        "timing_profile": "fast_shock",
        "horizons": [
            _block("1d",  per_horizon_kwargs.get("oned", {})),
            _block("5d",  per_horizon_kwargs.get("fived", {})),
            _block("20d", per_horizon_kwargs.get("twentyd", {})),
        ],
    }


def _ticker(symbol: str, role: str,
            r1d: float | None = None,
            r5d: float | None = None,
            r20d: float | None = None) -> dict:
    return {
        "symbol":     symbol,
        "role":       role,
        "return_1d":  r1d,
        "return_5d":  r5d,
        "return_20d": r20d,
    }


def _by_horizon(card: dict, horizon: str) -> dict:
    for h in card["per_horizon"]:
        if h["horizon"] == horizon:
            return h
    raise AssertionError(f"horizon {horizon!r} not in scorecard")


# ---------------------------------------------------------------------------
# 1. Per-horizon classifier
# ---------------------------------------------------------------------------

class TestPerHorizonClassification(unittest.TestCase):

    def test_beneficiary_positive_return_supports(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=6.0)],
        )
        for h in ("1d", "5d", "20d"):
            row = _by_horizon(card, h)
            self.assertEqual(len(row["realized"]["supporting"]), 1)
            self.assertEqual(row["realized"]["supporting"][0]["symbol"], "XOM")

    def test_loser_positive_return_contradicts(self):
        """A ticker flagged as a loser that RALLIES contradicts the thesis."""
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("VNQ", "loser", r1d=1.5, r5d=3.0, r20d=6.0)],
        )
        for h in ("1d", "5d", "20d"):
            row = _by_horizon(card, h)
            self.assertEqual(len(row["realized"]["contradicting"]), 1)

    def test_return_inside_noise_band_is_flat(self):
        # 1d noise band is 0.3; a beneficiary with 0.1% return is flat.
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("XOM", "beneficiary", r1d=0.1, r5d=0.5, r20d=1.0)],
        )
        self.assertEqual(len(_by_horizon(card, "1d")["realized"]["flat"]), 1)
        # 5d band is 0.8 → 0.5 is also flat
        self.assertEqual(len(_by_horizon(card, "5d")["realized"]["flat"]), 1)
        # 20d band is 2.0 → 1.0 is still flat
        self.assertEqual(len(_by_horizon(card, "20d")["realized"]["flat"]), 1)

    def test_none_return_is_pending(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("XOM", "beneficiary", r1d=1.5, r5d=None, r20d=None)],
        )
        self.assertEqual(len(_by_horizon(card, "1d")["realized"]["supporting"]), 1)
        self.assertEqual(len(_by_horizon(card, "5d")["realized"]["pending"]), 1)
        self.assertEqual(len(_by_horizon(card, "20d")["realized"]["pending"]), 1)

    def test_unknown_role_is_skipped(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("SPY", "unspecified", r1d=1.5)],
        )
        row = _by_horizon(card, "1d")
        # Unknown role → skipped entirely from support/contradict/flat/pending.
        total = (
            len(row["realized"]["supporting"])
            + len(row["realized"]["contradicting"])
            + len(row["realized"]["flat"])
            + len(row["realized"]["pending"])
        )
        self.assertEqual(total, 0)


# ---------------------------------------------------------------------------
# 2. Per-horizon status thresholds
# ---------------------------------------------------------------------------

class TestPerHorizonStatus(unittest.TestCase):

    def test_confirmed_when_ratio_gate_met(self):
        """2 supporters vs 0 contradictors is confirmed."""
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=6.0),
                _ticker("CVX", "beneficiary", r1d=1.2, r5d=2.5, r20d=5.5),
            ],
        )
        for h in ("1d", "5d", "20d"):
            self.assertEqual(_by_horizon(card, h)["status"], "confirmed")

    def test_failed_when_contradict_ratio_gate_met(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=-1.5, r5d=-3.0, r20d=-6.0),
                _ticker("CVX", "beneficiary", r1d=-1.2, r5d=-2.5, r20d=-5.5),
            ],
        )
        for h in ("1d", "5d", "20d"):
            self.assertEqual(_by_horizon(card, h)["status"], "failed")

    def test_mixed_when_neither_side_dominates(self):
        """One supporter, one contradictor → mixed."""
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=6.0),
                _ticker("CVX", "beneficiary", r1d=-1.2, r5d=-2.5, r20d=-5.5),
            ],
        )
        for h in ("1d", "5d", "20d"):
            self.assertEqual(_by_horizon(card, h)["status"], "mixed")

    def test_pending_when_all_returns_none(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("XOM", "beneficiary", r1d=None, r5d=None, r20d=None)],
        )
        for h in ("1d", "5d", "20d"):
            self.assertEqual(_by_horizon(card, h)["status"], "pending")

    def test_ratio_gate_is_two_to_one(self):
        """At exactly 1:1 the verdict is mixed; at 2:0 it should be confirmed."""
        # Explicit check that the module ratio gate matches the expectation.
        self.assertEqual(_RATIO_GATE, 2.0)


# ---------------------------------------------------------------------------
# 3. Aggregate rollup
# ---------------------------------------------------------------------------

class TestAggregateStatus(unittest.TestCase):

    def test_all_pending_aggregates_pending(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [_ticker("XOM", "beneficiary")],  # all returns None
        )
        self.assertEqual(card["aggregate"]["status"], "pending")
        self.assertEqual(card["aggregate"]["resolved_horizons"], 0)

    def test_all_confirmed_aggregates_on_track(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=6.0),
                _ticker("CVX", "beneficiary", r1d=1.2, r5d=2.5, r20d=5.5),
            ],
        )
        self.assertEqual(card["aggregate"]["status"], "on_track")
        self.assertEqual(card["aggregate"]["resolved_horizons"], 3)

    def test_5d_failure_aggregates_breaking(self):
        """Failure at 5d alone lights the breaking beacon."""
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=-3.0, r20d=None),
                _ticker("CVX", "beneficiary", r1d=1.2, r5d=-2.5, r20d=None),
            ],
        )
        self.assertEqual(card["aggregate"]["status"], "breaking")

    def test_20d_failure_aggregates_breaking(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=-6.0),
                _ticker("CVX", "beneficiary", r1d=1.2, r5d=2.5, r20d=-5.5),
            ],
        )
        self.assertEqual(card["aggregate"]["status"], "breaking")

    def test_1d_failure_alone_is_drifting_not_breaking(self):
        """First-day contradiction is noise / positioning, not a break
        signal — the aggregate must be 'drifting' while 5d/20d mature."""
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                _ticker("XOM", "beneficiary", r1d=-1.5, r5d=None, r20d=None),
                _ticker("CVX", "beneficiary", r1d=-1.2, r5d=None, r20d=None),
            ],
        )
        self.assertEqual(card["aggregate"]["status"], "drifting")

    def test_confirmed_plus_mixed_aggregates_drifting(self):
        card = compute_thesis_scorecard(
            _checkpoints(),
            [
                # 1d & 20d confirmed; 5d split (mixed)
                _ticker("XOM", "beneficiary", r1d=1.5, r5d=1.0, r20d=6.0),
                _ticker("CVX", "beneficiary", r1d=1.2, r5d=-1.0, r20d=5.5),
            ],
        )
        self.assertEqual(card["aggregate"]["status"], "drifting")


# ---------------------------------------------------------------------------
# 4. Shape + criteria forwarding
# ---------------------------------------------------------------------------

class TestScorecardShape(unittest.TestCase):

    def test_always_emits_three_horizons_in_order(self):
        card = compute_thesis_scorecard({}, [])
        names = [h["horizon"] for h in card["per_horizon"]]
        self.assertEqual(names, ["1d", "5d", "20d"])

    def test_empty_inputs_mark_unavailable(self):
        card = compute_thesis_scorecard({}, [])
        self.assertFalse(card["available"])
        self.assertEqual(card["aggregate"]["status"], "pending")

    def test_llm_criteria_forwarded_into_each_horizon(self):
        hc = _checkpoints(
            oned=dict(expected=["spike +2%"], confirms_if=["volume up"],
                      falsifies_if=["close red"]),
            fived=dict(expected=["follow-through"]),
        )
        card = compute_thesis_scorecard(hc, [])
        one = _by_horizon(card, "1d")
        self.assertIn("spike +2%", one["expected_criteria"])
        self.assertIn("volume up", one["confirmation_criteria"])
        self.assertIn("close red", one["falsification_criteria"])
        # 5d still carries its expected even without tickers to score.
        five = _by_horizon(card, "5d")
        self.assertIn("follow-through", five["expected_criteria"])

    def test_missing_horizon_block_from_llm_degrades_cleanly(self):
        """If the LLM omits the 20d block entirely the scorecard still
        emits the 20d row with empty criteria and a pending status."""
        hc = {
            "timing_profile": "fast_shock",
            "horizons": [
                {"horizon": "1d", "expected": ["a"],
                 "confirms_if": [], "falsifies_if": []},
                # 5d + 20d omitted
            ],
        }
        card = compute_thesis_scorecard(hc, [])
        twenty = _by_horizon(card, "20d")
        self.assertEqual(twenty["expected_criteria"], [])
        self.assertEqual(twenty["status"], "pending")

    def test_timing_profile_is_echoed(self):
        hc = _checkpoints()
        hc["timing_profile"] = "slow_grind"
        card = compute_thesis_scorecard(hc, [])
        self.assertEqual(card["timing_profile"], "slow_grind")


# ---------------------------------------------------------------------------
# 5. Revisit snapshot preference
# ---------------------------------------------------------------------------

class TestRevisitPreference(unittest.TestCase):

    def test_revisit_snapshot_overrides_initial_ticker_returns(self):
        """When a revisit snapshot exists for day 5, its returns
        supersede the rolling return_5d on the original tickers."""
        # Initial tickers say return_5d = +3 (supporting).
        initial = [
            _ticker("XOM", "beneficiary", r1d=1.5, r5d=3.0, r20d=None),
            _ticker("CVX", "beneficiary", r1d=1.2, r5d=2.5, r20d=None),
        ]
        # But the day-5 revisit snapshot says the realised returns were
        # -3 on both — enough to clear the 2:0 ratio gate for failed.
        revisits = [
            {
                "day": 5,
                "tickers": [
                    {"symbol": "XOM", "role": "beneficiary", "return_5d": -3.0},
                    {"symbol": "CVX", "role": "beneficiary", "return_5d": -2.5},
                ],
            },
        ]
        card = compute_thesis_scorecard(_checkpoints(), initial, revisits)
        five = _by_horizon(card, "5d")
        # The revisit-derived measurement wins; 5d is now failed.
        self.assertEqual(five["status"], "failed")
        # 1d still reads from the initial tickers (no day-1 snapshot).
        self.assertEqual(_by_horizon(card, "1d")["status"], "confirmed")

    def test_noise_band_constants_match_documentation(self):
        """Pin the noise bands; accidental loosening would silently
        demote confirmed horizons to flat across the archive."""
        self.assertEqual(_NOISE_BAND["1d"], 0.3)
        self.assertEqual(_NOISE_BAND["5d"], 0.8)
        self.assertEqual(_NOISE_BAND["20d"], 2.0)


if __name__ == "__main__":
    unittest.main()
