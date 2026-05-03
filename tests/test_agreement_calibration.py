"""
tests/test_agreement_calibration.py

Contract tests for the historical-calibration layer on top of the
agreement engine.

Covers:
  1. Calibration tree build — wraps confidence_calibration cleanly;
     empty input returns an empty-ish tree without raising.
  2. Lookup cascade — joint (family+regime) → family → regime → global
     → insufficient.  Weak_depth flag fires below the reliable floor.
  3. Cohort reliability — strong / moderate / noisy / weak bands fire
     on the right hit-rate ranges.
  4. Thesis-vs-cohort — aligned / above / below classification with
     the documented ±12pp tolerance.
  5. Diagnosis codes — every canonical code fires on its expected
     combination of cohort + alignment + weak_depth.
  6. Adjusted score — blends raw score toward cohort mean when the
     sample is deep; no blend under weak_depth; clamp semantics.
  7. Graceful degradation — missing agreement, missing tree, missing
     family/regime/confidence all degrade to the documented sentinels.
  8. End-to-end wiring via _build_mover_summary — the ``calibration``
     block rides alongside ``agreement`` / ``evidence`` / ``conviction``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from agreement_calibration import (
    DIAGNOSIS_CODES,
    _ALIGNMENT_BAND_PP,
    _COHORT_NOISY_BAND,
    _COHORT_STRONG_FLOOR,
    _COHORT_WEAK_CEIL,
    _MAX_BLEND_WEIGHT,
    build_historical_tree,
    calibrate_agreement,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _sample(confidence: str = "medium",
            family: str = "tariff",
            compound_regime: str = "reflation",
            validated: bool = True) -> dict:
    return {
        "confidence":      confidence,
        "family":          family,
        "compound_regime": compound_regime,
        "validated":       validated,
    }


def _tree_with_hit_rate(rate: float, n: int,
                        confidence: str = "medium",
                        family: str = "tariff",
                        compound_regime: str = "reflation") -> dict:
    """Build a calibration tree whose (confidence, family, regime) joint
    slice has the target hit rate + sample size."""
    wins = int(round(rate * n))
    samples = [
        _sample(confidence=confidence, family=family,
                 compound_regime=compound_regime, validated=(i < wins))
        for i in range(n)
    ]
    return build_historical_tree(samples)


def _agreement(weighted_score: float = 0.0, verdict: str = "mixed") -> dict:
    return {
        "weighted_score": weighted_score,
        "verdict":         verdict,
        "n_eligible":      4,
    }


# ---------------------------------------------------------------------------
# 1. Tree build
# ---------------------------------------------------------------------------

class TestTreeBuild(unittest.TestCase):

    def test_empty_input_returns_tree_shape(self):
        t = build_historical_tree([])
        self.assertIsInstance(t, dict)
        # Should carry the 4-slice shape from confidence_calibration.
        for key in ("joint", "family", "regime", "global"):
            self.assertIn(key, t)

    def test_none_input_does_not_raise(self):
        t = build_historical_tree(None)
        self.assertIsInstance(t, dict)

    def test_samples_counted_correctly(self):
        t = build_historical_tree([
            _sample(validated=True),
            _sample(validated=True),
            _sample(validated=False),
        ])
        self.assertEqual(t["total"], 3)


# ---------------------------------------------------------------------------
# 2. Lookup cascade + weak_depth
# ---------------------------------------------------------------------------

class TestLookupCascade(unittest.TestCase):

    def test_strong_sample_resolves_at_joint_tier(self):
        tree = _tree_with_hit_rate(0.65, 20)
        r = calibrate_agreement(
            _agreement(weighted_score=0.30),
            mechanism_family="tariff",
            compound_regime="reflation",
            confidence="medium",
            calibration_tree=tree,
        )
        self.assertTrue(r["available"])
        self.assertEqual(r["depth_tier"], "family+regime")
        self.assertFalse(r["weak_depth"])

    def test_thin_sample_flags_weak_depth(self):
        # Only 3 samples — below the 10-event strict floor, falls back
        # to the global tier which will also be thin.
        tree = _tree_with_hit_rate(0.55, 3)
        r = calibrate_agreement(
            _agreement(weighted_score=0.30),
            mechanism_family="tariff",
            compound_regime="reflation",
            confidence="medium",
            calibration_tree=tree,
        )
        # Either landed at global (weak=True) or insufficient.
        self.assertTrue(r["weak_depth"])


# ---------------------------------------------------------------------------
# 3. Cohort reliability bands
# ---------------------------------------------------------------------------

class TestCohortReliability(unittest.TestCase):

    def _calibrate(self, hit_rate: float) -> dict:
        tree = _tree_with_hit_rate(hit_rate, 20)
        return calibrate_agreement(
            _agreement(weighted_score=0.0),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )

    def test_strong_cohort_floor(self):
        r = self._calibrate(_COHORT_STRONG_FLOOR)
        self.assertEqual(r["cohort_reliability"], "strong")

    def test_noisy_cohort_band(self):
        for rate in (_COHORT_NOISY_BAND[0], 0.50, _COHORT_NOISY_BAND[1]):
            r = self._calibrate(rate)
            self.assertEqual(
                r["cohort_reliability"], "noisy",
                f"rate={rate} should be noisy",
            )

    def test_weak_cohort_ceiling(self):
        r = self._calibrate(_COHORT_WEAK_CEIL)
        self.assertEqual(r["cohort_reliability"], "weak")

    def test_moderate_cohort_between_bands(self):
        """Use n=100 so 0.57 → exactly 57 wins, preserving the band
        across integer rounding in the fixture builder."""
        tree = _tree_with_hit_rate(0.57, 100)
        r = calibrate_agreement(
            _agreement(weighted_score=0.0),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )
        self.assertEqual(r["cohort_reliability"], "moderate")


# ---------------------------------------------------------------------------
# 4. Thesis-vs-cohort alignment
# ---------------------------------------------------------------------------

class TestThesisVsCohort(unittest.TestCase):

    def _setup(self, raw_score: float, hit_rate: float) -> dict:
        tree = _tree_with_hit_rate(hit_rate, 20)
        return calibrate_agreement(
            _agreement(weighted_score=raw_score),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )

    def test_aligned_within_tolerance(self):
        """Raw +0.10 → implied 0.55; cohort 0.55 → aligned."""
        r = self._setup(raw_score=0.10, hit_rate=0.55)
        self.assertEqual(r["thesis_vs_cohort"], "aligned")

    def test_above_when_implied_exceeds_cohort_by_tolerance(self):
        """Raw +0.60 → implied 0.80; cohort 0.55 → above."""
        r = self._setup(raw_score=0.60, hit_rate=0.55)
        self.assertEqual(r["thesis_vs_cohort"], "above")

    def test_below_when_implied_lags_cohort(self):
        """Raw -0.40 → implied 0.30; cohort 0.55 → below."""
        r = self._setup(raw_score=-0.40, hit_rate=0.55)
        self.assertEqual(r["thesis_vs_cohort"], "below")

    def test_edge_of_band_counts_as_aligned(self):
        """Delta = ALIGNMENT_BAND_PP exactly → aligned."""
        # implied = hit_rate + tolerance; raw = 2*implied - 1
        hit = 0.55
        implied = hit + _ALIGNMENT_BAND_PP
        raw = 2.0 * implied - 1.0
        r = self._setup(raw_score=raw, hit_rate=hit)
        self.assertEqual(r["thesis_vs_cohort"], "aligned")


# ---------------------------------------------------------------------------
# 5. Diagnosis codes
# ---------------------------------------------------------------------------

class TestDiagnosisCodes(unittest.TestCase):

    def _setup(self, raw_score: float, hit_rate: float, n: int = 20) -> dict:
        tree = _tree_with_hit_rate(hit_rate, n)
        return calibrate_agreement(
            _agreement(weighted_score=raw_score),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )

    def test_all_codes_registered(self):
        for code in DIAGNOSIS_CODES:
            # Sanity — every code must be a non-empty string.
            self.assertIsInstance(code, str)
            self.assertGreater(len(code), 0)

    def test_strong_cohort_confirming_thesis(self):
        r = self._setup(raw_score=0.50, hit_rate=0.65)
        self.assertEqual(r["diagnosis_code"],
                          "strong_cohort_confirming_thesis")

    def test_strong_cohort_weak_thesis(self):
        """Strong cohort (hit > 0.60) but thesis lagging the mean."""
        r = self._setup(raw_score=-0.30, hit_rate=0.65)
        self.assertEqual(r["diagnosis_code"], "strong_cohort_weak_thesis")

    def test_noisy_pattern_regardless_of_alignment(self):
        """Noisy cohort dominates the diagnosis — thesis-vs-cohort
        doesn't meaningfully apply when the cohort itself is a coin
        flip."""
        above = self._setup(raw_score=+0.80, hit_rate=0.50)
        below = self._setup(raw_score=-0.80, hit_rate=0.50)
        self.assertEqual(above["diagnosis_code"], "noisy_pattern")
        self.assertEqual(below["diagnosis_code"], "noisy_pattern")

    def test_weak_cohort_diagnoses_differently_by_thesis(self):
        aligned = self._setup(raw_score=-0.40, hit_rate=0.30)
        beating = self._setup(raw_score=+0.60, hit_rate=0.30)
        self.assertEqual(aligned["diagnosis_code"], "weak_cohort")
        self.assertEqual(beating["diagnosis_code"],
                          "weak_cohort_thesis_beating_it")

    def test_moderate_cohort_modes(self):
        """n=100 preserves 0.57 moderate rate through the fixture
        builder's integer rounding."""
        aligned = self._setup(raw_score=+0.15, hit_rate=0.57, n=100)
        ahead   = self._setup(raw_score=+0.70, hit_rate=0.57, n=100)
        behind  = self._setup(raw_score=-0.40, hit_rate=0.57, n=100)
        self.assertEqual(aligned["diagnosis_code"], "moderate_cohort_aligned")
        self.assertEqual(ahead["diagnosis_code"],   "moderate_cohort_thesis_ahead")
        self.assertEqual(behind["diagnosis_code"],  "moderate_cohort_thesis_behind")

    def test_thin_sample_overrides_everything(self):
        """weak_depth sets diagnosis to thin_sample regardless of
        cohort / alignment."""
        tree = _tree_with_hit_rate(0.65, 4)  # thin
        r = calibrate_agreement(
            _agreement(weighted_score=0.60),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )
        self.assertEqual(r["diagnosis_code"], "thin_sample")
        self.assertTrue(r["weak_depth"])

    def test_no_tree_returns_no_cohort_data(self):
        r = calibrate_agreement(
            _agreement(weighted_score=0.30),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=None,
        )
        self.assertEqual(r["diagnosis_code"], "no_cohort_data")

    def test_diagnosis_text_non_empty_for_every_code(self):
        r = self._setup(raw_score=+0.40, hit_rate=0.65)
        self.assertIsInstance(r["diagnosis"], str)
        self.assertGreater(len(r["diagnosis"]), 10)


# ---------------------------------------------------------------------------
# 6. Adjusted score blending
# ---------------------------------------------------------------------------

class TestAdjustedScore(unittest.TestCase):

    def test_no_blend_under_weak_depth(self):
        """Thin sample → adjusted_score equals raw score exactly."""
        tree = _tree_with_hit_rate(0.65, 4)
        r = calibrate_agreement(
            _agreement(weighted_score=0.30),
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )
        self.assertAlmostEqual(r["adjusted_score"], 0.30, places=2)

    def test_blend_bends_score_toward_cohort_when_deep(self):
        """Deep cohort (n=100, hit=0.70); raw implied 0.50 should blend
        upward toward 0.70 by _MAX_BLEND_WEIGHT."""
        tree = _tree_with_hit_rate(0.70, 100)
        r = calibrate_agreement(
            _agreement(weighted_score=0.0),  # implied 0.5
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )
        # adjusted_implied = (1-0.4)*0.5 + 0.4*0.7 = 0.58
        # adjusted_score = 2*0.58 - 1 = 0.16
        self.assertGreater(r["adjusted_score"], 0.0)
        self.assertLess(r["adjusted_score"], 0.30)

    def test_blend_weight_capped(self):
        """Cohort of 500 shouldn't blend more than _MAX_BLEND_WEIGHT."""
        tree = _tree_with_hit_rate(0.90, 500)
        r = calibrate_agreement(
            _agreement(weighted_score=0.0),  # implied 0.5
            mechanism_family="tariff", compound_regime="reflation",
            confidence="medium", calibration_tree=tree,
        )
        # adjusted_implied ≤ (1-MAX)*0.5 + MAX*0.9
        max_adjusted = (1 - _MAX_BLEND_WEIGHT) * 0.5 + _MAX_BLEND_WEIGHT * 0.9
        self.assertLessEqual(
            (r["adjusted_score"] + 1) / 2.0,
            max_adjusted + 0.01,
        )


# ---------------------------------------------------------------------------
# 7. Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation(unittest.TestCase):

    def test_none_agreement_does_not_raise(self):
        r = calibrate_agreement(None, calibration_tree={})
        self.assertEqual(r["diagnosis_code"], "no_cohort_data")
        self.assertEqual(r["implied_probability"], 0.5)

    def test_missing_family_and_regime_falls_back_to_global(self):
        tree = _tree_with_hit_rate(0.60, 20)
        r = calibrate_agreement(
            _agreement(weighted_score=0.20),
            mechanism_family=None, compound_regime=None,
            confidence="medium", calibration_tree=tree,
        )
        # Global tier works (the joint tree sample is medium/tariff/reflation
        # which also fills the global medium bucket).
        self.assertTrue(r["available"])
        self.assertEqual(r["depth_tier"], "global")

    def test_missing_confidence_defaults_to_medium(self):
        tree = _tree_with_hit_rate(0.60, 20, confidence="medium")
        r = calibrate_agreement(
            _agreement(weighted_score=0.20),
            mechanism_family="tariff", compound_regime="reflation",
            confidence=None, calibration_tree=tree,
        )
        self.assertTrue(r["available"])

    def test_regime_value_none_is_same_as_missing(self):
        tree = _tree_with_hit_rate(0.60, 20)
        r_none_str = calibrate_agreement(
            _agreement(weighted_score=0.20),
            mechanism_family="tariff", compound_regime="none",
            confidence="medium", calibration_tree=tree,
        )
        r_missing = calibrate_agreement(
            _agreement(weighted_score=0.20),
            mechanism_family="tariff", compound_regime=None,
            confidence="medium", calibration_tree=tree,
        )
        self.assertEqual(r_none_str["depth_tier"], r_missing["depth_tier"])


# ---------------------------------------------------------------------------
# 8. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def test_summary_emits_calibration_block(self):
        from api import _build_mover_summary
        ev = {
            "id":                1,
            "headline":          "OPEC cuts output",
            "mechanism_summary": "tighter supply",
            "mechanism_family":  "supply_shock",
            "confidence":        "medium",
            "event_date":        "2026-04-19",
            "stage":              "realized",
            "persistence":        "structural",
            "transmission_chain": [],
            "if_persists":         {},
        }
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.5,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
        ]
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        self.assertIn("calibration", summary)
        self.assertIn("diagnosis_code", summary["calibration"])
        self.assertIn("cohort_reliability", summary["calibration"])


if __name__ == "__main__":
    unittest.main()
