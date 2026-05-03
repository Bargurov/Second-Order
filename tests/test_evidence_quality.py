"""
tests/test_evidence_quality.py

Contract tests for the evidence-quality weighting layer.

Covers:
  1. Per-ticker tier classification — alpha + liquid + clean move =
     high; alpha + modest = provisional; drift / noise floor / thin
     volume = low.
  2. Weighted score — high-tier contributions dominate low-tier
     noise; sign preserved; clamp to [-1, 1].
  3. Confidence basis — strong_evidence / mixed_quality /
     fragile_basket / thin fire on their canonical distributions.
  4. Rationale text — evidence-memo-style names high-quality symbols
     and surfaces fragile baskets explicitly.
  5. Defensive behaviour — empty / None / non-dict inputs return
     the documented sentinel.
  6. End-to-end wiring via _build_mover_summary — ``quality`` block
     rides alongside agreement / evidence / attribution / conviction.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from evidence_quality import (
    CONFIDENCE_BASES,
    QUALITY_TIERS,
    _MODEST_FLOOR_PCT,
    _NOISE_FLOOR_PCT,
    _VOLUME_LIQUID_FLOOR,
    _VOLUME_THIN_FLOOR,
    _WEIGHT_HIGH,
    _WEIGHT_LOW,
    _WEIGHT_PROVISIONAL,
    classify_evidence_quality,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _t(symbol: str,
       return_5d: float | None = 2.0,
       validation_quality: str | None = "alpha_support",
       direction_tag: str | None = None,
       volume_ratio: float | None = 1.2) -> dict:
    return {
        "symbol":              symbol,
        "role":                "beneficiary",
        "return_5d":           return_5d,
        "validation_quality":  validation_quality,
        "direction_tag":       direction_tag,
        "volume_ratio":        volume_ratio,
        "benchmark_sector":    "energy",
    }


def _by_symbol(r: dict, symbol: str) -> dict:
    for entry in r["per_ticker"]:
        if entry["symbol"] == symbol:
            return entry
    raise AssertionError(f"{symbol} not found in per_ticker")


# ---------------------------------------------------------------------------
# 1. Per-ticker tier classification
# ---------------------------------------------------------------------------

class TestPerTickerClassification(unittest.TestCase):

    def test_alpha_clean_liquid_is_high(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=2.5, validation_quality="alpha_support",
                volume_ratio=1.2),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "high")

    def test_alpha_modest_magnitude_is_provisional(self):
        """Alpha tag but move is between noise floor and modest floor
        → provisional (not enough magnitude for high)."""
        r = classify_evidence_quality([
            _t("XOM", return_5d=0.50, validation_quality="alpha_support",
                volume_ratio=1.2),
        ])
        # 0.5% is above noise floor (0.3) but below modest floor (1.0).
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "provisional")

    def test_alpha_noise_floor_is_low(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=0.10, validation_quality="alpha_support"),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_thin_volume_demotes_even_clean_alpha(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support",
                volume_ratio=0.30),   # below _VOLUME_THIN_FLOOR
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_alpha_modest_liquidity_is_provisional(self):
        """Between thin floor and liquid floor → provisional."""
        r = classify_evidence_quality([
            _t("XOM", return_5d=2.0, validation_quality="alpha_support",
                volume_ratio=0.70),   # above thin, below liquid
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "provisional")

    def test_beta_signal_is_provisional_when_clean(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=1.8, validation_quality="beta_aligned",
                volume_ratio=1.0),
        ])
        self.assertEqual(_by_symbol(r, "SPY")["tier"], "provisional")

    def test_beta_signal_is_low_when_marginal(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=0.5, validation_quality="beta_aligned",
                volume_ratio=1.0),
        ])
        self.assertEqual(_by_symbol(r, "SPY")["tier"], "low")

    def test_drift_is_low_regardless_of_magnitude(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=2.5, validation_quality="drift"),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_flat_is_low(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=0.05, validation_quality="flat"),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_unavailable_is_low(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=None, validation_quality="unavailable"),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_legacy_direction_tag_gets_provisional_with_clean_move(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=2.0,
                validation_quality=None,
                direction_tag="supports thesis", volume_ratio=1.0),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "provisional")

    def test_legacy_direction_tag_is_low_when_marginal(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=0.4,
                validation_quality=None,
                direction_tag="supports thesis"),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "low")

    def test_no_liquidity_signal_still_upgrades_high(self):
        """Volume unknown shouldn't block high tier — only thin volume
        should demote.  Real tickers often miss volume_ratio."""
        r = classify_evidence_quality([
            _t("XOM", return_5d=2.5, validation_quality="alpha_support",
                volume_ratio=None),
        ])
        self.assertEqual(_by_symbol(r, "XOM")["tier"], "high")


# ---------------------------------------------------------------------------
# 2. Weighted score
# ---------------------------------------------------------------------------

class TestWeightedScore(unittest.TestCase):

    def test_high_quality_alpha_support_drives_positive_score(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("CVX", return_5d=2.5, validation_quality="alpha_support"),
        ])
        self.assertGreater(r["weighted_score"], 0.8)

    def test_high_support_beats_low_contradiction(self):
        """Two high-quality supports + one low-quality drift-like
        contradict should read positive overall."""
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("CVX", return_5d=2.5, validation_quality="alpha_support"),
            _t("SPY", return_5d=0.2, validation_quality="drift"),
        ])
        self.assertGreater(r["weighted_score"], 0.5)

    def test_low_quality_contradict_cannot_overwhelm_clean_alpha(self):
        """Key invariant: a high-quality alpha support should outweigh
        several low-quality / noisy contradictions."""
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("SPY", return_5d=-0.1, validation_quality="drift"),
            _t("QQQ", return_5d=-0.2, validation_quality="unavailable"),
            _t("DIA", return_5d=-0.05, validation_quality="flat"),
        ])
        self.assertGreater(r["weighted_score"], 0.5)

    def test_clamp_at_bounds(self):
        """All-high all-support → ≤ +1.0; all-high all-contradict → ≥ -1.0."""
        high_sup = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("CVX", return_5d=3.0, validation_quality="alpha_support"),
        ])
        high_con = classify_evidence_quality([
            _t("XOM", return_5d=-3.0, validation_quality="alpha_contradicts"),
            _t("CVX", return_5d=-3.0, validation_quality="alpha_contradicts"),
        ])
        self.assertAlmostEqual(high_sup["weighted_score"], +1.0, places=3)
        self.assertAlmostEqual(high_con["weighted_score"], -1.0, places=3)

    def test_weights_are_ordered(self):
        self.assertGreater(_WEIGHT_HIGH, _WEIGHT_PROVISIONAL)
        self.assertGreater(_WEIGHT_PROVISIONAL, _WEIGHT_LOW)


# ---------------------------------------------------------------------------
# 3. Confidence basis
# ---------------------------------------------------------------------------

class TestConfidenceBasis(unittest.TestCase):

    def test_canonical_bases(self):
        self.assertEqual(
            set(CONFIDENCE_BASES),
            {"strong_evidence", "mixed_quality", "fragile_basket", "thin"},
        )

    def test_strong_evidence_on_two_plus_high(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("CVX", return_5d=2.5, validation_quality="alpha_support"),
        ])
        self.assertEqual(r["confidence_basis"], "strong_evidence")

    def test_mixed_quality_with_high_and_provisional(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("SPY", return_5d=1.5, validation_quality="beta_aligned"),
        ])
        self.assertEqual(r["confidence_basis"], "mixed_quality")

    def test_fragile_basket_on_provisionals_only(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=1.5, validation_quality="beta_aligned"),
            _t("QQQ", return_5d=1.5, validation_quality="beta_aligned"),
        ])
        self.assertEqual(r["confidence_basis"], "fragile_basket")

    def test_thin_basket_when_low_dominates(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=0.1, validation_quality="drift"),
            _t("QQQ", return_5d=0.05, validation_quality="flat"),
        ])
        self.assertEqual(r["confidence_basis"], "thin")

    def test_thin_when_single_ticker(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
        ])
        self.assertEqual(r["confidence_basis"], "thin")


# ---------------------------------------------------------------------------
# 4. Rationale text
# ---------------------------------------------------------------------------

class TestRationale(unittest.TestCase):

    def test_strong_evidence_names_symbols(self):
        r = classify_evidence_quality([
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
            _t("CVX", return_5d=2.5, validation_quality="alpha_support"),
        ])
        self.assertIn("XOM", r["rationale"])
        self.assertIn("CVX", r["rationale"])
        self.assertIn("high-quality", r["rationale"].lower())

    def test_fragile_basket_says_fragile(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=1.5, validation_quality="beta_aligned"),
            _t("QQQ", return_5d=1.5, validation_quality="beta_aligned"),
        ])
        self.assertIn("fragile", r["rationale"].lower())

    def test_thin_basket_says_thin_or_noise(self):
        r = classify_evidence_quality([
            _t("SPY", return_5d=0.1, validation_quality="drift"),
            _t("QQQ", return_5d=0.05, validation_quality="flat"),
            _t("DIA", return_5d=None, validation_quality="unavailable"),
        ])
        self.assertIn(
            "thin", r["rationale"].lower(),
        )


# ---------------------------------------------------------------------------
# 5. Defensive behaviour
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):

    def test_empty_tickers_returns_thin_sentinel(self):
        r = classify_evidence_quality([])
        self.assertFalse(r["available"])
        self.assertEqual(r["confidence_basis"], "thin")
        self.assertEqual(r["weighted_score"], 0.0)

    def test_none_input_does_not_raise(self):
        r = classify_evidence_quality(None)
        self.assertEqual(r["confidence_basis"], "thin")

    def test_non_dict_entries_skipped(self):
        r = classify_evidence_quality([
            None, "not a ticker", 42,
            _t("XOM", return_5d=3.0, validation_quality="alpha_support"),
        ])
        # 3 junk + 1 XOM → dist should have 3 low (junk classified low)
        # and 1 high from XOM.
        self.assertEqual(r["quality_distribution"]["high"], 1)

    def test_constants_pinned(self):
        self.assertEqual(_NOISE_FLOOR_PCT, 0.30)
        self.assertEqual(_MODEST_FLOOR_PCT, 1.00)
        self.assertEqual(_VOLUME_THIN_FLOOR, 0.50)
        self.assertEqual(_VOLUME_LIQUID_FLOOR, 0.80)

    def test_tier_ordering_pinned(self):
        self.assertEqual(QUALITY_TIERS, ("high", "provisional", "low"))


# ---------------------------------------------------------------------------
# 6. End-to-end wiring
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def test_summary_emits_quality_block(self):
        from api import _build_mover_summary
        ev = {
            "id":                1,
            "headline":          "OPEC cuts output",
            "mechanism_summary": "tighter supply",
            "mechanism_family":  "supply_shock",
            "event_date":        "2026-04-19",
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["XOM", "CVX"],
            "losers":             [],
            "transmission_chain": [],
            "if_persists":         {},
        }
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "benchmark_sector": "energy", "volume_ratio": 1.2,
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.5,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "benchmark_sector": "energy", "volume_ratio": 1.1,
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
        ]
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        self.assertIn("quality", summary)
        q = summary["quality"]
        self.assertEqual(q["confidence_basis"], "strong_evidence")
        self.assertEqual(q["quality_distribution"]["high"], 2)
        self.assertGreater(q["weighted_score"], 0.8)


if __name__ == "__main__":
    unittest.main()
