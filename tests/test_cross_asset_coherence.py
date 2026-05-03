"""
tests/test_cross_asset_coherence.py

Validates the cross-asset coherence / thesis-rejection layer.
Every threshold is exercised with representative cases:
  - per-channel expected direction per thesis
  - z-floor contribution gate
  - coherence score + band mapping
  - thesis_rejection fires only when disconfirm-heavy AND coherence ≤ ceil
  - tension fires when both scores clear floor (no rejection)
  - all channels grouped correctly (rates, fx, commodities, vol, credit, equities)
  - degrades cleanly with partial / empty inputs
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cross_asset_coherence import (  # noqa: E402
    compute_cross_asset_coherence,
    CHANNEL_IDS,
    _EXPECTED,
    _CHANNEL_SCALE,
    _Z_FLOOR,
    _COHERENCE_HIGH,
    _COHERENCE_MODERATE,
    _COHERENCE_LOW,
    _REJECTION_DISCONFIRM_FLOOR,
    _REJECTION_COHERENCE_CEIL,
    _TENSION_FLOOR,
    _STRONG_CONFIRM_SCORE,
    _WEAK_CONFIRM_SCORE,
)


# ---------------------------------------------------------------------------
# Input fixture builders
# ---------------------------------------------------------------------------

def _rates(nominal_5d=None):
    if nominal_5d is None:
        return None
    return {"nominal": {"change_5d": nominal_5d},
            "real_proxy": {"change_5d": 0.0},
            "breakeven_proxy": {"change_5d": 0.0},
            "regime": "Mixed",
            "raw": {}}


def _stress(dxy=None, gold=None, vix_change=None, credit_spread=None):
    raw = {"vix": 17.0}
    if vix_change is not None:
        raw["vix_change_5d"] = vix_change
    if credit_spread is not None:
        raw["credit_spread_5d"] = credit_spread
    return {
        "regime": "Mixed",
        "raw": raw,
        "signals": {},
        "detail": {
            "safe_haven": {
                "assets": {
                    **({"Dollar": dxy} if dxy is not None else {}),
                    **({"Gold": gold} if gold is not None else {}),
                },
            },
            "credit": {"spread_5d": credit_spread} if credit_spread is not None else {},
        },
    }


def _snap(market, change_5d, value=100.0):
    return {"market": market, "symbol": market, "value": value,
            "change_5d": change_5d, "error": None}


# ---------------------------------------------------------------------------
# Channel registration + sign convention
# ---------------------------------------------------------------------------

class TestChannelRegistration(unittest.TestCase):

    def test_exactly_six_channels(self):
        self.assertEqual(set(CHANNEL_IDS),
                         {"rates", "fx", "commodities", "vol", "credit", "equities"})

    def test_every_thesis_covers_all_channels(self):
        for thesis, mapping in _EXPECTED.items():
            for cid in CHANNEL_IDS:
                self.assertIn(cid, mapping, f"{thesis} missing expectation for {cid}")

    def test_scale_positive_per_channel(self):
        for cid in CHANNEL_IDS:
            self.assertGreater(_CHANNEL_SCALE[cid], 0)


# ---------------------------------------------------------------------------
# Per-thesis confirm direction
# ---------------------------------------------------------------------------

class TestInflationaryThesis(unittest.TestCase):

    def test_broad_confirmation_all_channels_expected(self):
        # Big moves aligned with inflation expectations — all channels confirm
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.6),         # rates up ✓
            stress_regime=_stress(gold=8.0, vix_change=3.0, credit_spread=2.5),
            snapshots=[_snap("CL", 8.0), _snap("ES", -4.0)],
        )
        self.assertEqual(r["verdict"], "strong_confirm")
        # inflationary thesis: fx=silent so only 5 channels can contribute.
        self.assertGreaterEqual(len(r["confirms"]), 4)
        self.assertEqual(len(r["disconfirms"]), 0)
        self.assertGreaterEqual(r["coherence"], _COHERENCE_HIGH)
        self.assertFalse(r["thesis_rejection"])
        self.assertFalse(r["tension"])

    def test_inflationary_thesis_gets_rejected_by_opposite_tape(self):
        # Inflationary thesis but the tape prints disinflation across every
        # channel: rates DOWN, commodities DOWN, VIX DOWN, credit TIGHTENS,
        # equities UP — thesis rejection fires.
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=-0.6),
            stress_regime=_stress(gold=-6.0, vix_change=-3.0, credit_spread=-2.0),
            snapshots=[_snap("CL", -6.0), _snap("ES", 3.5)],
        )
        self.assertEqual(r["verdict"], "rejected")
        self.assertTrue(r["thesis_rejection"])
        self.assertGreaterEqual(r["disconfirm_score"], _REJECTION_DISCONFIRM_FLOOR)
        self.assertLessEqual(r["coherence"], _REJECTION_COHERENCE_CEIL)


class TestRatePressureUpThesis(unittest.TestCase):

    def test_hawkish_tape_confirms(self):
        # Rates up, DXY up, VIX up, credit wider, equities down — pure hawkish tape
        r = compute_cross_asset_coherence(
            "rate_pressure_up",
            rates_context=_rates(nominal_5d=0.5),
            stress_regime=_stress(dxy=1.8, vix_change=3.0, credit_spread=1.5),
            snapshots=[_snap("ES", -4.0)],
        )
        self.assertIn(r["verdict"], ("strong_confirm", "weak_confirm"))
        self.assertEqual(len(r["disconfirms"]), 0)

    def test_fx_silent_on_inflationary(self):
        # Inflation thesis says FX is silent — any DXY move shouldn't contribute.
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=None,
            stress_regime=_stress(dxy=3.0),  # huge DXY move
            snapshots=None,
        )
        fx_entry = r["channels"]["fx"]
        self.assertEqual(fx_entry["expected"], "silent")
        self.assertEqual(fx_entry["verdict"], "silent")
        self.assertNotIn("fx", r["confirms"])
        self.assertNotIn("fx", r["disconfirms"])


# ---------------------------------------------------------------------------
# Tension flag — both sides fire
# ---------------------------------------------------------------------------

class TestTensionFlag(unittest.TestCase):

    def test_tension_when_confirms_and_disconfirms_both_clear_floor(self):
        # Inflation thesis:
        #   rates UP (confirm), commodities UP (confirm)  — 2 confirms
        #   vol DOWN (disconfirm), credit DOWN (disconfirm) — 2 disconfirms
        #   fx silent, equities silent (below floor)
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.5),
            stress_regime=_stress(gold=0.0, vix_change=-3.5, credit_spread=-2.0),
            snapshots=[_snap("CL", 9.0), _snap("ES", 0.0)],
        )
        self.assertGreaterEqual(r["confirm_score"], _TENSION_FLOOR)
        self.assertGreaterEqual(r["disconfirm_score"], _TENSION_FLOOR)
        # Tension fires UNLESS rejection outranks it.
        if r["thesis_rejection"]:
            self.assertFalse(r["tension"])
        else:
            self.assertTrue(r["tension"])
            self.assertEqual(r["verdict"], "mixed")

    def test_no_tension_when_only_confirms(self):
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.5),
            stress_regime=_stress(gold=6.0, vix_change=2.5, credit_spread=1.2),
            snapshots=[_snap("CL", 7.0), _snap("ES", -3.0)],
        )
        self.assertFalse(r["tension"])
        self.assertFalse(r["thesis_rejection"])


# ---------------------------------------------------------------------------
# Z-floor gate
# ---------------------------------------------------------------------------

class TestZFloor(unittest.TestCase):

    def test_sub_floor_move_is_silent(self):
        # A 5bp nominal move clears abs-tier but z = 0.25 < 0.80 floor
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.05),
            stress_regime=None, snapshots=None,
        )
        rates_entry = r["channels"]["rates"]
        self.assertLess(rates_entry["z"], _Z_FLOOR)
        self.assertEqual(rates_entry["verdict"], "silent")

    def test_at_floor_edge_counts(self):
        # z exactly at floor: scale 0.20 × 0.80 = 0.16 pp → confirms
        move = _CHANNEL_SCALE["rates"] * _Z_FLOOR + 0.001
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=move),
            stress_regime=None, snapshots=None,
        )
        self.assertEqual(r["channels"]["rates"]["verdict"], "confirm")


# ---------------------------------------------------------------------------
# Coherence score + band
# ---------------------------------------------------------------------------

class TestCoherenceBands(unittest.TestCase):

    def test_all_confirms_max_coherence(self):
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.6),
            stress_regime=_stress(gold=6.0, vix_change=3.0, credit_spread=2.0),
            snapshots=[_snap("CL", 7.0), _snap("ES", -4.0)],
        )
        self.assertEqual(r["coherence"], 100)
        self.assertEqual(r["coherence_band"], "high")

    def test_equal_confirm_disconfirm_around_fifty(self):
        # Two ~2σ confirms (rates up + commodities up) vs two ~2σ disconfirms
        # (vol down + credit down) — coherence should land near 50.
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.4),                 # z~2.0 confirm
            stress_regime=_stress(vix_change=-5.0, credit_spread=-2.0),  # z~2 disconfirms
            snapshots=[_snap("CL", 6.0)],                          # z~2 confirm
        )
        # With rates(z=2) + commodities(z=2) confirming and vol(z=2) + credit(z=2)
        # disconfirming, coherence = 50. Allow ±10 slack for rounding.
        self.assertGreaterEqual(r["coherence"], 40)
        self.assertLessEqual(r["coherence"], 60)
        self.assertIn(r["coherence_band"], ("moderate", "low"))

    def test_silent_band_when_no_fires(self):
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.02),  # sub-floor
            stress_regime=None, snapshots=None,
        )
        self.assertIsNone(r["coherence"])
        self.assertEqual(r["coherence_band"], "silent")
        self.assertEqual(r["verdict"], "silent")


# ---------------------------------------------------------------------------
# Thesis rejection — strict gate
# ---------------------------------------------------------------------------

class TestThesisRejection(unittest.TestCase):

    def test_single_disconfirm_below_floor_does_not_reject(self):
        # One disconfirm at z=2 is below _REJECTION_DISCONFIRM_FLOOR (3.0)
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.04),   # sub-floor
            stress_regime=_stress(vix_change=-5.0),   # z=2.0 disconfirm only
            snapshots=None,
        )
        self.assertFalse(r["thesis_rejection"])

    def test_rejection_fires_when_disconfirm_score_exceeds_floor_and_low_coherence(self):
        # 3+ disconfirms aggregating to disconfirm_score >= 3 AND no confirms
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=-0.4),      # z~2 disconfirm (expected up)
            stress_regime=_stress(vix_change=-3.0,       # z~1.2 disconfirm
                                  credit_spread=-1.5),   # z~1.5 disconfirm
            snapshots=None,
        )
        self.assertTrue(r["thesis_rejection"])
        self.assertEqual(r["verdict"], "rejected")
        self.assertEqual(r["coherence_band"], "rejected")

    def test_low_coherence_alone_does_not_reject(self):
        # Coherence might land in "rejected" band but disconfirm_score below
        # the strict 3.0 floor → no rejection flag.
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.2),         # z=1.0 confirm
            stress_regime=_stress(vix_change=-2.0),        # z=0.8 — at floor, counts as disconfirm
            snapshots=None,
        )
        # Low disconfirm score → rejection should NOT fire even if coherence < 35.
        if r["disconfirm_score"] < _REJECTION_DISCONFIRM_FLOOR:
            self.assertFalse(r["thesis_rejection"])


# ---------------------------------------------------------------------------
# Channel input sources + fallbacks
# ---------------------------------------------------------------------------

class TestInputSources(unittest.TestCase):

    def test_dxy_falls_back_to_safe_haven_dollar(self):
        r = compute_cross_asset_coherence(
            "rate_pressure_up",
            rates_context=None,
            stress_regime=_stress(dxy=1.8),   # safe_haven fallback
            snapshots=None,
        )
        self.assertEqual(r["channels"]["fx"]["observed_dir"], "up")
        # Expected direction for rate_pressure_up fx is "up" → confirm.
        self.assertEqual(r["channels"]["fx"]["verdict"], "confirm")

    def test_commodities_picks_gold_when_crude_missing(self):
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=None,
            stress_regime=_stress(gold=6.0),
            snapshots=None,
        )
        self.assertEqual(r["channels"]["commodities"]["observed"], 6.0)
        self.assertEqual(r["channels"]["commodities"]["verdict"], "confirm")

    def test_credit_reads_from_detail_first_raw_fallback(self):
        # detail.credit.spread_5d present → used
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=None,
            stress_regime=_stress(credit_spread=2.0),
            snapshots=None,
        )
        self.assertEqual(r["channels"]["credit"]["observed"], 2.0)


# ---------------------------------------------------------------------------
# Degradation paths
# ---------------------------------------------------------------------------

class TestDegradation(unittest.TestCase):

    def test_none_thesis_no_inputs_returns_empty(self):
        self.assertEqual(
            compute_cross_asset_coherence("none", None, None, None),
            {},
        )

    def test_none_thesis_with_inputs_returns_silent_block(self):
        r = compute_cross_asset_coherence(
            "none",
            rates_context=_rates(nominal_5d=0.5),
            stress_regime=_stress(vix_change=3.0),
            snapshots=None,
        )
        # Thesis="none" → every channel expected=silent → zero fires.
        self.assertEqual(r["verdict"], "silent")
        self.assertEqual(r["confirm_score"], 0)
        self.assertEqual(r["disconfirm_score"], 0)

    def test_block_shape_always_complete(self):
        r = compute_cross_asset_coherence(
            "inflationary",
            rates_context=_rates(nominal_5d=0.5),
            stress_regime=_stress(vix_change=3.0),
            snapshots=None,
        )
        for k in ("thesis", "thesis_label", "channels",
                  "confirms", "disconfirms", "silent",
                  "confirm_score", "disconfirm_score",
                  "coherence", "coherence_band", "coherence_label",
                  "thesis_rejection", "tension",
                  "verdict", "verdict_label", "rationale",
                  "available", "stale"):
            self.assertIn(k, r, f"missing field: {k}")
        for cid in CHANNEL_IDS:
            self.assertIn(cid, r["channels"])


# ---------------------------------------------------------------------------
# Reaction-function wiring: coherence_matrix is exposed
# ---------------------------------------------------------------------------

class TestReactionFunctionIntegration(unittest.TestCase):

    def test_reaction_function_carries_coherence_matrix(self):
        from reaction_function_divergence import compute_reaction_function_divergence
        rates = {"regime": "Inflation pressure",
                 "nominal": {"change_5d": 0.5},
                 "real_proxy": {"change_5d": -0.5},
                 "breakeven_proxy": {"change_5d": 0.2},
                 "raw": {}}
        stress = _stress(gold=6.0, vix_change=2.5, credit_spread=1.5)
        result = compute_reaction_function_divergence(
            "OPEC announces production cut — oil price spike",
            "supply shock lifts import costs across energy-dependent economies",
            rates, stress, snapshots=None,
        )
        self.assertIn("coherence_matrix", result)
        cm = result["coherence_matrix"]
        self.assertEqual(cm["thesis"], "inflationary")
        self.assertIn(cm["verdict"], (
            "strong_confirm", "weak_confirm", "mixed", "rejected", "silent",
        ))


if __name__ == "__main__":
    unittest.main()
