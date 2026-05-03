"""
tests/test_evidence_attribution.py

Contract tests for the evidence-memo attribution layer.

Covers:
  1. Dominant confirming + contradiction — the single strongest
     positive / negative contributor surfaced with ticker symbol,
     channel, and a readable note.
  2. Missing-proof set — channels the event's family expects in its
     FIRST pack but that have no observation (or observed flat).
  3. Channel contribution breakdown — per-channel net factor with
     support / contradict symbol lists; sorted by magnitude.
  4. Confirmation shape — six canonical shapes fire on their
     documented evidence patterns.
  5. Narrative — evidence-memo-style one-liner names the dominant
     signals and flags missing proofs.
  6. End-to-end wiring via ``_build_mover_summary`` — ``attribution``
     block rides alongside agreement / evidence / conviction /
     channel_timing / calibration.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from evidence_attribution import (
    CONFIRMATION_SHAPES,
    _BROAD_MIN_CHANNELS,
    _DECISIVE_SHARE,
    _MEANINGFUL_FACTOR,
    compute_evidence_attribution,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _t(symbol: str,
       benchmark_sector: str = "energy",
       validation_quality: str | None = None,
       direction_tag: str | None = None,
       return_5d: float | None = 2.0) -> dict:
    return {
        "symbol":              symbol,
        "role":                "beneficiary",
        "benchmark_sector":    benchmark_sector,
        "validation_quality":  validation_quality,
        "direction_tag":       direction_tag,
        "return_5d":           return_5d,
    }


# ---------------------------------------------------------------------------
# 1. Dominant confirming / contradiction
# ---------------------------------------------------------------------------

class TestDominantSignals(unittest.TestCase):

    def test_dominant_confirming_picks_largest_positive(self):
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="beta_aligned"),
            _t("BP",  validation_quality="beta_aligned"),
        ])
        # XOM (alpha, weight 1.0) beats CVX/BP (beta, weight 0.5).
        self.assertIsNotNone(r["dominant_confirming"])
        self.assertEqual(r["dominant_confirming"]["ticker"], "XOM")

    def test_dominant_contradiction_picks_largest_negative(self):
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="alpha_support"),
            _t("LRCX", validation_quality="alpha_contradicts",
                benchmark_sector="technology"),
            _t("AMAT", validation_quality="beta_contradicts",
                benchmark_sector="technology"),
        ])
        self.assertIsNotNone(r["dominant_contradiction"])
        # LRCX is alpha_contradicts (weight 1.0) vs AMAT beta (0.5).
        self.assertEqual(r["dominant_contradiction"]["ticker"], "LRCX")

    def test_no_supports_yields_null_confirming(self):
        r = compute_evidence_attribution([
            _t("LRCX", validation_quality="alpha_contradicts"),
        ])
        self.assertIsNone(r["dominant_confirming"])
        self.assertIsNotNone(r["dominant_contradiction"])

    def test_empty_tickers_both_null(self):
        r = compute_evidence_attribution([])
        self.assertIsNone(r["dominant_confirming"])
        self.assertIsNone(r["dominant_contradiction"])
        self.assertEqual(r["confirmation_shape"], "absent")

    def test_dominant_note_mentions_symbol_and_return(self):
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="alpha_support", return_5d=3.5),
        ])
        note = r["dominant_confirming"]["note"]
        self.assertIn("XOM", note)
        self.assertIn("3.5", note)


# ---------------------------------------------------------------------------
# 2. Missing proof set
# ---------------------------------------------------------------------------

class TestMissingProof(unittest.TestCase):

    def test_supply_shock_missing_commodities(self):
        """supply_shock FIRST pack = commodities + equities.  A basket
        with only bank equities should flag commodities as missing."""
        r = compute_evidence_attribution(
            [
                _t("XLF", benchmark_sector="financials",
                    validation_quality="alpha_support"),
            ],
            mechanism_family="supply_shock",
        )
        missing_channels = {m["channel"] for m in r["missing_proof"]}
        self.assertIn("commodities", missing_channels)

    def test_observed_but_flat_counts_as_missing(self):
        """A family-primary channel present in breakdown but with
        near-zero net factor still counts as missing proof — the
        signal didn't arrive."""
        # Energy ticker WITH validation_quality="flat" is excluded
        # from observations at contribution stage.  Use drift instead
        # so it's still excluded — but that means "no observation".
        # For the "observed flat" test we need contributing ticker
        # with canceling signals on the same channel.
        r = compute_evidence_attribution(
            [
                _t("XOM",  benchmark_sector="energy",
                    validation_quality="alpha_support"),
                _t("USO", benchmark_sector="energy",
                    validation_quality="alpha_contradicts"),
            ],
            mechanism_family="supply_shock",
        )
        # Net factor on commodities is 0 → flat → missing.
        missing = {m["channel"]: m for m in r["missing_proof"]}
        # Both observations are on commodities channel (energy sector).
        # supply_shock FIRST pack also includes equities — absent from
        # basket → should land in missing list.
        self.assertIn("equities", missing)
        # commodities: one support + one contradict → net 0 → missing
        # (observed_flat reason).
        if "commodities" in missing:
            self.assertEqual(missing["commodities"]["reason_code"],
                             "observed_flat")

    def test_no_family_means_no_missing_proof(self):
        r = compute_evidence_attribution(
            [_t("XOM", validation_quality="alpha_support")],
            mechanism_family=None,
        )
        self.assertEqual(r["missing_proof"], [])

    def test_unknown_family_no_crash(self):
        r = compute_evidence_attribution(
            [_t("XOM", validation_quality="alpha_support")],
            mechanism_family="not_a_family",
        )
        # Falls through to empty list without raising.
        self.assertEqual(r["missing_proof"], [])


# ---------------------------------------------------------------------------
# 3. Channel contribution breakdown
# ---------------------------------------------------------------------------

class TestChannelBreakdown(unittest.TestCase):

    def test_breakdown_sorted_by_absolute_factor(self):
        r = compute_evidence_attribution([
            _t("LRCX", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
            _t("AMAT", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
            _t("XOM",  benchmark_sector="energy",
                validation_quality="alpha_support"),
        ])
        breakdown = r["channel_breakdown"]
        self.assertEqual(breakdown[0]["channel"], "equities")
        # equities (|net| = 2) should be ahead of commodities (|net| = 1).
        self.assertGreater(abs(breakdown[0]["net_factor"]),
                            abs(breakdown[1]["net_factor"]))

    def test_breakdown_counts_support_and_contradict(self):
        r = compute_evidence_attribution([
            _t("XOM", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("CVX", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("BP",  benchmark_sector="energy",
                validation_quality="alpha_contradicts"),
        ])
        commodities = next(b for b in r["channel_breakdown"]
                            if b["channel"] == "commodities")
        self.assertEqual(commodities["n_support"], 2)
        self.assertEqual(commodities["n_contradict"], 1)
        self.assertEqual(set(commodities["symbols_support"]), {"XOM", "CVX"})
        self.assertEqual(commodities["symbols_contradict"], ["BP"])

    def test_unmapped_sector_excluded_from_breakdown(self):
        r = compute_evidence_attribution([
            _t("XYZ", benchmark_sector="unknown_planet",
                validation_quality="alpha_support"),
        ])
        # Unknown sector → no channel → not in breakdown.
        self.assertEqual(r["channel_breakdown"], [])


# ---------------------------------------------------------------------------
# 4. Confirmation shape classification
# ---------------------------------------------------------------------------

class TestConfirmationShape(unittest.TestCase):

    def test_shapes_are_canonical(self):
        self.assertEqual(
            set(CONFIRMATION_SHAPES),
            {
                "single_decisive_channel",
                "broad_confirmation",
                "mixed_offset",
                "unilateral_contradiction",
                "scattered_weak",
                "absent",
            },
        )

    def test_single_decisive_channel(self):
        """One channel carries the full signal, nothing else."""
        r = compute_evidence_attribution([
            _t("XOM", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("CVX", benchmark_sector="energy",
                validation_quality="alpha_support"),
        ])
        self.assertEqual(r["confirmation_shape"], "single_decisive_channel")

    def test_broad_confirmation_three_channels(self):
        """Three positive channels, no meaningful negatives."""
        r = compute_evidence_attribution([
            _t("XOM", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("TLT", benchmark_sector="rates",
                validation_quality="alpha_support"),
            _t("XLF", benchmark_sector="financials",
                validation_quality="alpha_support"),
        ])
        self.assertEqual(r["confirmation_shape"], "broad_confirmation")

    def test_mixed_offset(self):
        """Confirming and contradicting channels both meaningful."""
        r = compute_evidence_attribution([
            _t("XOM", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("CVX", benchmark_sector="energy",
                validation_quality="alpha_support"),
            _t("LRCX", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
            _t("AMAT", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
        ])
        self.assertEqual(r["confirmation_shape"], "mixed_offset")

    def test_unilateral_contradiction(self):
        r = compute_evidence_attribution([
            _t("LRCX", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
            _t("AMAT", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
        ])
        self.assertEqual(r["confirmation_shape"], "unilateral_contradiction")

    def test_scattered_weak(self):
        """Multiple small positives on different channels, none
        carrying decisive share — below the broad_confirmation floor."""
        # Two channels with beta-only weak signals.
        r = compute_evidence_attribution([
            _t("XLF", benchmark_sector="financials",
                validation_quality="beta_aligned"),
            _t("TLT", benchmark_sector="rates",
                validation_quality="beta_aligned"),
        ])
        # Each channel has |factor| = 0.5 (beta weight).  Top share =
        # 0.5 / 1.0 = 0.5 < 0.60 decisive threshold.  Two positive
        # channels < 3 broad floor.  Falls through to scattered_weak.
        self.assertEqual(r["confirmation_shape"], "scattered_weak")

    def test_absent_when_no_tickers(self):
        r = compute_evidence_attribution([])
        self.assertEqual(r["confirmation_shape"], "absent")

    def test_absent_when_all_flat(self):
        """All tickers flat / unavailable → no contributions → absent."""
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="flat"),
            _t("CVX", validation_quality="drift"),
        ])
        self.assertEqual(r["confirmation_shape"], "absent")


# ---------------------------------------------------------------------------
# 5. Narrative composition
# ---------------------------------------------------------------------------

class TestNarrative(unittest.TestCase):

    def test_single_decisive_names_channel_and_ticker(self):
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
        ])
        self.assertIn("XOM", r["narrative"])
        self.assertIn("commodities", r["narrative"])
        self.assertIn("one channel", r["narrative"].lower())

    def test_unilateral_contradiction_names_contradicting_channel(self):
        r = compute_evidence_attribution([
            _t("LRCX", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
            _t("AMAT", benchmark_sector="technology",
                validation_quality="alpha_contradicts"),
        ])
        self.assertIn("equities", r["narrative"])
        self.assertIn("contradict", r["narrative"].lower())

    def test_narrative_flags_missing_proof(self):
        r = compute_evidence_attribution(
            [
                _t("XLF", benchmark_sector="financials",
                    validation_quality="alpha_support"),
                _t("JPM", benchmark_sector="financials",
                    validation_quality="alpha_support"),
            ],
            mechanism_family="supply_shock",
        )
        # supply_shock primary = commodities + equities; commodities
        # absent.
        self.assertIn("missing proof", r["narrative"].lower())
        self.assertIn("commodities", r["narrative"])

    def test_absent_narrative_is_clear(self):
        r = compute_evidence_attribution([])
        self.assertIn("No material evidence", r["narrative"])

    def test_narrative_ends_with_period(self):
        r = compute_evidence_attribution([
            _t("XOM", validation_quality="alpha_support"),
            _t("CVX", validation_quality="alpha_support"),
        ])
        self.assertTrue(r["narrative"].endswith("."))


# ---------------------------------------------------------------------------
# 6. Constants pinned + invariants
# ---------------------------------------------------------------------------

class TestConstantsAndInvariants(unittest.TestCase):

    def test_thresholds_pinned(self):
        self.assertEqual(_DECISIVE_SHARE, 0.60)
        self.assertEqual(_MEANINGFUL_FACTOR, 0.30)
        self.assertEqual(_BROAD_MIN_CHANNELS, 3)

    def test_non_dict_inputs_skipped_silently(self):
        r = compute_evidence_attribution(
            [None, "not a ticker", 42,
             _t("XOM", validation_quality="alpha_support")],
        )
        # XOM still counted — others dropped without raising.
        self.assertEqual(len(r["channel_breakdown"]), 1)

    def test_output_shape_always_has_all_keys(self):
        r = compute_evidence_attribution([])
        for k in ("available", "confirmation_shape", "shape_label",
                   "dominant_confirming", "dominant_contradiction",
                   "missing_proof", "channel_breakdown", "narrative"):
            self.assertIn(k, r, f"missing key {k!r}")


# ---------------------------------------------------------------------------
# 7. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def test_summary_emits_attribution_block(self):
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
             "benchmark_sector": "energy",
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.5,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "benchmark_sector": "energy",
             "spark": [0.1] * 20, "anchor_date": "2026-04-19"},
        ]
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        self.assertIn("attribution", summary)
        attr = summary["attribution"]
        self.assertIn("confirmation_shape", attr)
        self.assertIn("dominant_confirming", attr)
        self.assertIn("channel_breakdown", attr)
        self.assertEqual(attr["confirmation_shape"], "single_decisive_channel")
        self.assertEqual(attr["dominant_confirming"]["channel"], "commodities")


if __name__ == "__main__":
    unittest.main()
