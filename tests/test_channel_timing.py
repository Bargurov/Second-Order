"""
tests/test_channel_timing.py

Contract tests for the time-aware channel-scoring layer.

Covers:
  1. Validation matrix — per-channel windows carry the canonical
     early/peak/late anchors.
  2. Phase classification — days_elapsed + channel → one of
     pre_window / early_window / peak_window / late_window / expired.
  3. Family-aware shift — ``supply_shock`` accelerates commodities;
     ``fiscal_issuance`` stretches rates.  Same ticker / same age
     classifies to different phases under different families.
  4. Scoring weights — contradiction in pre_window is softened,
     peak contradiction counts full, late support is partial credit.
  5. Aggregate status — five-way classifier fires on the right
     evidence patterns (early_confirming / in_window_confirming /
     delayed_on_track / late_and_failing / pending / insufficient).
  6. End-to-end wiring — ``_build_mover_summary`` emits the
     ``channel_timing`` block with a status + per-channel observations.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from channel_timing import (
    PHASES,
    TIMING_STATUSES,
    _CANONICAL_WINDOWS,
    _FAMILY_CHANNEL_SHIFT,
    _PHASE_DIRECTION_WEIGHT,
    classify_thesis_timing,
    score_channel_observation,
)


# ---------------------------------------------------------------------------
# 1. Validation matrix
# ---------------------------------------------------------------------------

class TestValidationMatrix(unittest.TestCase):

    def test_every_channel_has_ordered_anchors(self):
        """early_day ≤ peak_start ≤ peak_end ≤ late_day — the
        monotonicity the phase classifier relies on."""
        for channel, w in _CANONICAL_WINDOWS.items():
            self.assertLessEqual(w["early_day"], w["peak_start"],
                                  f"{channel}: early_day > peak_start")
            self.assertLessEqual(w["peak_start"], w["peak_end"],
                                  f"{channel}: peak_start > peak_end")
            self.assertLessEqual(w["peak_end"], w["late_day"],
                                  f"{channel}: peak_end > late_day")

    def test_canonical_channel_ordering(self):
        """vol / rates confirm fastest; downstream equities slowest."""
        self.assertLess(_CANONICAL_WINDOWS["rates"]["peak_end"],
                        _CANONICAL_WINDOWS["credit"]["peak_end"])
        self.assertLess(_CANONICAL_WINDOWS["credit"]["peak_end"],
                        _CANONICAL_WINDOWS["equities_downstream"]["peak_end"])
        self.assertLess(_CANONICAL_WINDOWS["vol"]["peak_end"],
                        _CANONICAL_WINDOWS["commodities"]["peak_end"])

    def test_phases_are_canonical(self):
        self.assertEqual(
            PHASES,
            ("pre_window", "early_window", "peak_window",
             "late_window", "expired"),
        )

    def test_timing_statuses_are_canonical(self):
        self.assertEqual(
            set(TIMING_STATUSES),
            {"early_confirming", "in_window_confirming",
             "delayed_on_track", "late_and_failing", "pending",
             "insufficient"},
        )


# ---------------------------------------------------------------------------
# 2. Phase classification
# ---------------------------------------------------------------------------

class TestPhaseClassification(unittest.TestCase):

    def test_rates_peak_window_at_2d(self):
        r = score_channel_observation("rates", 2, +1.0)
        self.assertEqual(r["phase"], "peak_window")

    def test_commodities_early_at_2d(self):
        """Commodities peak is 3-10d; day 2 is early_window."""
        r = score_channel_observation("commodities", 2, +1.0)
        self.assertEqual(r["phase"], "early_window")

    def test_equities_downstream_pre_window_at_1d(self):
        """Downstream equities don't start until day 3."""
        r = score_channel_observation("equities_downstream", 1, +1.0)
        self.assertEqual(r["phase"], "pre_window")

    def test_credit_expired_at_30d(self):
        r = score_channel_observation("credit", 30, -1.0)
        self.assertEqual(r["phase"], "expired")

    def test_rates_late_at_8d(self):
        r = score_channel_observation("rates", 8, +1.0)
        self.assertEqual(r["phase"], "late_window")

    def test_unknown_channel_returns_unknown_phase(self):
        r = score_channel_observation("telepathy", 2, +1.0)
        self.assertEqual(r["phase"], "unknown")
        self.assertEqual(r["factor"], 0.0)

    def test_missing_age_folds_to_zero_factor(self):
        r = score_channel_observation("rates", None, +1.0)
        self.assertEqual(r["factor"], 0.0)

    def test_negative_age_clamps_to_zero(self):
        """commodities early_day=1 → clamped day 0 lands in pre_window."""
        r = score_channel_observation("commodities", -5, +1.0)
        self.assertEqual(r["phase"], "pre_window")


# ---------------------------------------------------------------------------
# 3. Family-aware shift
# ---------------------------------------------------------------------------

class TestFamilyShift(unittest.TestCase):

    def test_supply_shock_accelerates_commodities(self):
        """With shift 0.7, commodities peak at 3-10d → 2-7d.  Day 8
        lands in late_window under supply_shock but peak_window under
        the default timeline."""
        default = score_channel_observation("commodities", 8, +1.0)
        shocked = score_channel_observation(
            "commodities", 8, +1.0, mechanism_family="supply_shock",
        )
        self.assertEqual(default["phase"], "peak_window")
        self.assertEqual(shocked["phase"], "late_window")

    def test_fiscal_issuance_stretches_rates(self):
        """Rates base peak is 1-3d; under fiscal_issuance (×1.2) peak
        stretches to 1-4d.  Day 4 should land IN peak under
        fiscal_issuance but in late_window otherwise."""
        default = score_channel_observation("rates", 4, +1.0)
        stretched = score_channel_observation(
            "rates", 4, +1.0, mechanism_family="fiscal_issuance",
        )
        self.assertEqual(default["phase"], "late_window")
        self.assertEqual(stretched["phase"], "peak_window")

    def test_unknown_family_uses_canonical_windows(self):
        r = score_channel_observation(
            "rates", 2, +1.0, mechanism_family="not_a_family",
        )
        self.assertEqual(r["phase"], "peak_window")

    def test_shift_table_has_no_no_op_entries(self):
        """Every entry in FAMILY_CHANNEL_SHIFT should be != 1.0 so
        the table stays audit-free of silent no-ops."""
        for fam, shifts in _FAMILY_CHANNEL_SHIFT.items():
            for chan, val in shifts.items():
                self.assertNotEqual(
                    val, 1.0,
                    f"{fam}.{chan} = 1.0 is a no-op — drop the entry",
                )


# ---------------------------------------------------------------------------
# 4. Scoring weights — pre-window softening, peak full credit
# ---------------------------------------------------------------------------

class TestScoringWeights(unittest.TestCase):

    def test_peak_contradiction_outweighs_pre_window_contradiction(self):
        """A contradiction in the peak window is a real negative;
        the same contradiction in pre_window is softened."""
        peak_con    = _PHASE_DIRECTION_WEIGHT[("peak_window",  "contradict")]
        pre_con     = _PHASE_DIRECTION_WEIGHT[("pre_window",   "contradict")]
        self.assertLess(peak_con, pre_con)  # -1.0 < -0.3

    def test_peak_support_full_credit(self):
        self.assertEqual(
            _PHASE_DIRECTION_WEIGHT[("peak_window", "support")],
            +1.0,
        )

    def test_late_support_is_partial_credit(self):
        late_sup = _PHASE_DIRECTION_WEIGHT[("late_window", "support")]
        peak_sup = _PHASE_DIRECTION_WEIGHT[("peak_window", "support")]
        self.assertLess(late_sup, peak_sup)
        self.assertGreater(late_sup, 0.0)

    def test_zero_direction_sign_contributes_zero(self):
        r = score_channel_observation("rates", 2, 0.0)
        self.assertEqual(r["factor"], 0.0)

    def test_note_mentions_channel_and_day(self):
        r = score_channel_observation("rates", 2, +1.0)
        self.assertIn("rates", r["note"])
        self.assertIn("day 2", r["note"])
        self.assertIn("peak", r["note"].lower())


# ---------------------------------------------------------------------------
# 5. Aggregate status classification
# ---------------------------------------------------------------------------

class TestAggregateStatus(unittest.TestCase):

    def test_empty_observations_is_insufficient(self):
        r = classify_thesis_timing(5, [])
        self.assertEqual(r["status"], "insufficient")

    def test_all_flat_observations_is_pending(self):
        obs = [score_channel_observation("rates", 2, 0.0)]
        r = classify_thesis_timing(2, obs)
        self.assertEqual(r["status"], "pending")

    def test_in_window_confirming_on_peak_positives(self):
        obs = [
            score_channel_observation("rates", 2, +1.0),
            score_channel_observation("equities", 3, +1.0),
        ]
        r = classify_thesis_timing(3, obs)
        self.assertEqual(r["status"], "in_window_confirming")

    def test_early_confirming_when_signals_fire_in_early_phase(self):
        """Two commodity observations on day 2 (early_window under the
        default timeline) with support — nothing contradicting in peak."""
        obs = [
            score_channel_observation("commodities", 2, +1.0),
            score_channel_observation("equities", 1, +1.0),
        ]
        r = classify_thesis_timing(2, obs)
        # equities day 1 = peak_window (1-5d), commodities day 2 = early.
        # Mixed phases but net positive with no contradictions.
        self.assertIn(r["status"],
                       {"early_confirming", "in_window_confirming"})

    def test_late_and_failing_on_peak_contradictions(self):
        obs = [
            score_channel_observation("rates", 2, -1.0),
            score_channel_observation("equities", 3, -1.0),
        ]
        r = classify_thesis_timing(3, obs)
        self.assertEqual(r["status"], "late_and_failing")

    def test_delayed_on_track_on_late_positives_no_peak_negative(self):
        """Equities confirm at day 12 — past peak (1-5d) but before
        late_day (15).  Nothing contradicts; status = delayed_on_track."""
        obs = [
            score_channel_observation("equities", 12, +1.0),
            score_channel_observation("credit", 14, +1.0),  # late_window
        ]
        r = classify_thesis_timing(12, obs)
        self.assertEqual(r["status"], "delayed_on_track")

    def test_pre_window_dominated_sample_is_pending(self):
        """Downstream equities observation at day 2 — pre_window; status
        should be pending, not decisive."""
        obs = [
            score_channel_observation("equities_downstream", 2, -1.0),
        ]
        r = classify_thesis_timing(2, obs)
        self.assertEqual(r["status"], "pending")

    def test_raw_dict_observations_are_scored_inline(self):
        """Callers can hand in raw {channel, days_elapsed, direction_sign}
        dicts; classify_thesis_timing re-scores them inline."""
        r = classify_thesis_timing(2, [
            {"channel": "rates", "days_elapsed": 2, "direction_sign": +1.0},
            {"channel": "equities", "days_elapsed": 3, "direction_sign": +1.0},
        ])
        self.assertEqual(r["status"], "in_window_confirming")

    def test_rationale_mentions_timing(self):
        obs = [
            score_channel_observation("rates", 2, -1.0),
            score_channel_observation("equities", 3, -1.0),
        ]
        r = classify_thesis_timing(3, obs)
        # Rationale names the specific failure pattern.
        self.assertTrue(
            "time" in r["rationale"].lower()
            or "peak" in r["rationale"].lower()
            or "late" in r["rationale"].lower(),
        )

    def test_phase_summary_carried(self):
        obs = [
            score_channel_observation("rates", 2, +1.0),
            score_channel_observation("credit", 30, -1.0),
        ]
        r = classify_thesis_timing(30, obs)
        self.assertEqual(r["phase_summary"]["peak_window"], 1)
        self.assertEqual(r["phase_summary"]["expired"], 1)


# ---------------------------------------------------------------------------
# 6. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def _ev(self, **overrides) -> dict:
        base = {
            "id":                 9,
            "headline":           "OPEC cuts output",
            "mechanism_summary":  "tighter supply",
            "mechanism_family":   "supply_shock",
            "event_date":         "2026-04-12",   # recent
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["XOM"],
            "losers":             [],
            "transmission_path":  [],
            "transmission_chain": [],
            "if_persists":         {},
            "persistence_signal": {
                "status":       "active",
                "days_elapsed": 3,
                "repricing":    {"state": "second_leg"},
                "repricing_state": "second_leg",
            },
        }
        base.update(overrides)
        return base

    def test_summary_emits_channel_timing_block(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "benchmark_sector": "energy",         # → commodities channel
             "spark": [0.1] * 20, "anchor_date": "2026-04-12"},
            {"symbol": "XLE", "role": "beneficiary", "return_5d": 2.5,
             "validation_quality": "beta_aligned",
             "direction_tag": "supports thesis",
             "benchmark_sector": "energy",         # → commodities channel
             "spark": [0.1] * 20, "anchor_date": "2026-04-12"},
        ]
        summary = _build_mover_summary(self._ev(), big_moves, support_ratio=1.0)
        ct = summary["channel_timing"]
        self.assertIn("status", ct)
        self.assertIn(ct["status"], TIMING_STATUSES)
        self.assertIsInstance(ct["observations"], list)
        # At least one observation should carry a non-unknown phase.
        non_unknown = [o for o in ct["observations"] if o["phase"] != "unknown"]
        self.assertGreater(len(non_unknown), 0)


if __name__ == "__main__":
    unittest.main()
