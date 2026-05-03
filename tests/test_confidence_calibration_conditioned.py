"""
tests/test_confidence_calibration_conditioned.py

Contract tests for the regime + mechanism-family-conditioned confidence
calibration layer.

Covers:
  1. build_calibration_tree: all four slice tables populated correctly;
     malformed samples skipped without poisoning the counts.
  2. lookup_calibration: cascades from joint → family → regime → global
     → insufficient, honouring the per-tier sample floors.
  3. lookup_calibration: depth_tier string is always one of the five
     canonical values and matches the slice that resolved the lookup.
  4. lookup_calibration: weak / sample_warning flags fire on thin
     samples and on every non-strict tier.
  5. db.collect_calibration_samples: reads mechanism_family + the nested
     compound.label from regime_snapshot; legacy rows degrade to "none".
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from confidence_calibration import (
    _N_FAMILY,
    _N_GLOBAL,
    _N_REGIME,
    _N_STRICT,
    _WEAK_BELOW,
    build_calibration_tree,
    lookup_calibration,
)


# ---------------------------------------------------------------------------
# Fixture helper
# ---------------------------------------------------------------------------

def _sample(
    confidence: str = "medium",
    *,
    family: str = "tariff",
    compound_regime: str = "reflation",
    validated: bool = True,
) -> dict:
    return {
        "confidence":      confidence,
        "family":          family,
        "compound_regime": compound_regime,
        "validated":       validated,
    }


# ---------------------------------------------------------------------------
# 1. build_calibration_tree
# ---------------------------------------------------------------------------

class TestBuildCalibrationTree(unittest.TestCase):

    def test_empty_input_returns_empty_tables(self):
        t = build_calibration_tree([])
        self.assertEqual(t["total"], 0)
        self.assertEqual(t["joint"], {})
        self.assertEqual(t["family"], {})
        self.assertEqual(t["regime"], {})
        self.assertEqual(t["global"], {})

    def test_joint_family_regime_global_counts_match(self):
        samples = [
            _sample("high", family="tariff", compound_regime="reflation", validated=True),
            _sample("high", family="tariff", compound_regime="reflation", validated=False),
            _sample("high", family="tariff", compound_regime="funding_stress", validated=True),
            _sample("medium", family="sanction", compound_regime="reflation", validated=True),
        ]
        t = build_calibration_tree(samples)
        self.assertEqual(t["total"], 4)

        # Joint: (high, tariff, reflation) gets 2 samples, one validated.
        j = t["joint"][("high", "tariff", "reflation")]
        self.assertEqual(j["n"], 2)
        self.assertEqual(j["validated"], 1)
        self.assertEqual(j["hit_rate"], 0.5)

        # Family marginal: (high, tariff) covers all three high/tariff rows.
        f = t["family"][("high", "tariff")]
        self.assertEqual(f["n"], 3)
        self.assertEqual(f["validated"], 2)

        # Regime marginal: (high, reflation) = 2, (medium, reflation) = 1.
        self.assertEqual(t["regime"][("high", "reflation")]["n"], 2)
        self.assertEqual(t["regime"][("medium", "reflation")]["n"], 1)

        # Global: high = 3 total, medium = 1 total.
        self.assertEqual(t["global"]["high"]["n"], 3)
        self.assertEqual(t["global"]["medium"]["n"], 1)

    def test_malformed_samples_skipped(self):
        samples = [
            _sample("high"),
            None,                                          # not a dict
            {"confidence": "unknown", "validated": True},  # bad confidence
            {"validated": True},                           # no confidence
        ]
        t = build_calibration_tree(samples)
        self.assertEqual(t["total"], 1)

    def test_missing_family_or_regime_defaults_to_none(self):
        samples = [
            {"confidence": "low", "validated": True},  # no family, no regime
        ]
        t = build_calibration_tree(samples)
        self.assertEqual(t["family"][("low", "none")]["n"], 1)
        self.assertEqual(t["regime"][("low", "none")]["n"], 1)


# ---------------------------------------------------------------------------
# 2. lookup_calibration cascade
# ---------------------------------------------------------------------------

class TestLookupCascade(unittest.TestCase):

    def _tree_with(self, joint_n=0, family_only_extra=0, regime_only_extra=0,
                   global_extra=0) -> dict:
        """Build a tree with tuned depth per tier.

        - ``joint_n`` copies of (high, tariff, reflation)
        - ``family_only_extra`` copies of (high, tariff, funding_stress) —
          contribute to family marginal but not the joint slice
        - ``regime_only_extra`` copies of (high, sanction, reflation) —
          contribute to regime marginal but not the family marginal
        - ``global_extra`` copies of (high, sanction, funding_stress) —
          contribute only to the global bucket
        """
        samples: list[dict] = []
        for _ in range(joint_n):
            samples.append(_sample("high", family="tariff",
                                   compound_regime="reflation", validated=True))
        for _ in range(family_only_extra):
            samples.append(_sample("high", family="tariff",
                                   compound_regime="funding_stress", validated=False))
        for _ in range(regime_only_extra):
            samples.append(_sample("high", family="sanction",
                                   compound_regime="reflation", validated=True))
        for _ in range(global_extra):
            samples.append(_sample("high", family="sanction",
                                   compound_regime="funding_stress", validated=True))
        return build_calibration_tree(samples)

    def test_strict_joint_when_enough_samples(self):
        t = self._tree_with(joint_n=_N_STRICT)
        r = lookup_calibration(
            t, confidence="high", family="tariff", compound_regime="reflation",
        )
        self.assertEqual(r["depth_tier"], "family+regime")
        self.assertEqual(r["n"], _N_STRICT)
        self.assertEqual(r["slice_key"], ("high", "tariff", "reflation"))

    def test_falls_back_to_family_when_joint_thin(self):
        # 4 joint (< _N_STRICT=10) + 6 family-only, so family marginal = 10
        # and joint = 4 → must cascade to family tier.
        t = self._tree_with(joint_n=4, family_only_extra=6)
        r = lookup_calibration(
            t, confidence="high", family="tariff", compound_regime="reflation",
        )
        self.assertEqual(r["depth_tier"], "family")
        self.assertGreaterEqual(r["n"], _N_FAMILY)

    def test_falls_back_to_regime_when_family_thin(self):
        # Family marginal 2 (below _N_FAMILY=5), regime marginal 7 (above 5).
        t = self._tree_with(joint_n=2, regime_only_extra=5)
        r = lookup_calibration(
            t, confidence="high", family="tariff", compound_regime="reflation",
        )
        self.assertEqual(r["depth_tier"], "regime")
        self.assertGreaterEqual(r["n"], _N_REGIME)

    def test_falls_back_to_global_when_family_and_regime_thin(self):
        # Keep joint + family + regime all below their floors but global big.
        t = self._tree_with(joint_n=1, family_only_extra=1,
                            regime_only_extra=1, global_extra=10)
        r = lookup_calibration(
            t, confidence="high", family="tariff", compound_regime="reflation",
        )
        self.assertEqual(r["depth_tier"], "global")
        self.assertGreaterEqual(r["n"], _N_GLOBAL)
        self.assertIn("Global", r["sample_warning"])

    def test_insufficient_when_global_below_floor(self):
        t = self._tree_with(joint_n=0, global_extra=0)
        r = lookup_calibration(
            t, confidence="high", family="tariff", compound_regime="reflation",
        )
        self.assertEqual(r["depth_tier"], "insufficient")
        self.assertIsNone(r["hit_rate"])
        self.assertTrue(r["weak"])
        self.assertIsNotNone(r["sample_warning"])

    def test_none_family_short_circuits_to_regime_or_global(self):
        """family=None / 'none' must skip the family-dependent tiers."""
        t = self._tree_with(joint_n=10, regime_only_extra=10)
        # Without family, the joint tier can't fire even though its
        # underlying slot has enough samples — only regime/global remain.
        r = lookup_calibration(
            t, confidence="high", family=None, compound_regime="reflation",
        )
        self.assertIn(r["depth_tier"], {"regime", "global"})

    def test_invalid_confidence_returns_insufficient(self):
        t = self._tree_with(joint_n=10)
        r = lookup_calibration(t, confidence="extreme", family="tariff",
                               compound_regime="reflation")
        self.assertEqual(r["depth_tier"], "insufficient")

    def test_none_tree_returns_insufficient(self):
        r = lookup_calibration(None, confidence="high", family="tariff",
                               compound_regime="reflation")
        self.assertEqual(r["depth_tier"], "insufficient")


# ---------------------------------------------------------------------------
# 3. weak / sample_warning signalling
# ---------------------------------------------------------------------------

class TestWeakCalibrationSignal(unittest.TestCase):

    def test_strict_tier_with_large_sample_is_not_weak(self):
        t = build_calibration_tree([
            _sample("high", family="tariff", compound_regime="reflation",
                    validated=(i % 2 == 0))
            for i in range(_WEAK_BELOW + 5)
        ])
        r = lookup_calibration(t, confidence="high", family="tariff",
                               compound_regime="reflation")
        self.assertEqual(r["depth_tier"], "family+regime")
        self.assertFalse(r["weak"])
        self.assertIsNone(r["sample_warning"])

    def test_family_tier_always_marked_weak(self):
        """Anything below family+regime carries weak=True even if the
        lower tier itself has lots of samples — the UI should always
        know it's not the tightest available read."""
        samples = (
            [_sample("high", family="tariff", compound_regime="reflation",
                     validated=True) for _ in range(4)]  # joint below _N_STRICT
            + [_sample("high", family="tariff", compound_regime="funding_stress",
                       validated=True) for _ in range(20)]  # family marginal fat
        )
        t = build_calibration_tree(samples)
        r = lookup_calibration(t, confidence="high", family="tariff",
                               compound_regime="reflation")
        self.assertEqual(r["depth_tier"], "family")
        self.assertTrue(r["weak"])
        self.assertIsNotNone(r["sample_warning"])


# ---------------------------------------------------------------------------
# 4. db.collect_calibration_samples
# ---------------------------------------------------------------------------

class TestCollectCalibrationSamples(unittest.TestCase):

    def setUp(self):
        import db
        self.db = db
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            tempfile.gettempdir(), f"test_calib_samples_{uuid.uuid4().hex}.db",
        )
        db.init_db()

    def tearDown(self):
        try:
            os.remove(self.db.DB_FILE)
        except (OSError, PermissionError):
            pass
        self.db.DB_FILE = self._orig

    def _seed(self, **overrides):
        base = {
            "headline":          f"Event {uuid.uuid4().hex[:6]}",
            "stage":             "realized",
            "persistence":       "medium",
            "confidence":        "high",
            "event_date":        datetime.now().strftime("%Y-%m-%d"),
            "mechanism_family":  "tariff",
            "regime_snapshot": {
                "available": True,
                "compound": {"label": "reflation", "confidence": 0.8},
            },
            "market_tickers":    [
                {"symbol": "XOM", "role": "beneficiary",
                 "direction_tag": "supports thesis", "return_5d": 3.0},
            ],
        }
        base.update(overrides)
        self.db.save_event(base)

    def test_reads_family_and_compound_regime(self):
        self._seed()
        samples = self.db.collect_calibration_samples()
        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertEqual(s["confidence"], "high")
        self.assertEqual(s["family"], "tariff")
        self.assertEqual(s["compound_regime"], "reflation")
        self.assertTrue(s["validated"])

    def test_events_without_directional_outcome_excluded(self):
        """A row with tickers but no direction_tag supports/contradicts
        must not appear — the calibration is only meaningful on rows
        with usable outcomes."""
        self._seed(market_tickers=[
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0},
        ])
        self.assertEqual(self.db.collect_calibration_samples(), [])

    def test_missing_regime_snapshot_yields_compound_none(self):
        self._seed(regime_snapshot={})  # no compound key
        samples = self.db.collect_calibration_samples()
        self.assertEqual(samples[0]["compound_regime"], "none")

    def test_missing_family_yields_family_none(self):
        self._seed(mechanism_family=None)
        samples = self.db.collect_calibration_samples()
        self.assertEqual(samples[0]["family"], "none")


if __name__ == "__main__":
    unittest.main()
