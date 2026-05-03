"""Tightened primary-asset weighting — unmapped / typo / dotted /
signal-only / rejected tickers must NOT default to primary weight.

Mirrors the audit recommendation: primary status requires either
explicit classification (symbol in event.primary_assets) or trusted
direct exposure (a strict single-name shape with no registry hit on a
non-primary tier).  These tests exercise the contract boundary in
``validation_outcome._eligibility_tier`` /
``validation_outcome._is_primary_asset`` and verify the same rule
holds end-to-end through ``score_weighted_evidence``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from validation_outcome import (
    _eligibility_tier,
    _extract_primary_set,
    _is_primary_asset,
    _ticker_contribution,
    score_weighted_evidence,
)


class TestExtractPrimarySet(unittest.TestCase):
    def test_extracts_symbols_from_primary_assets_dicts(self):
        ev = {
            "primary_assets": [
                {"symbol": "XOM", "rank": 1, "rationale": "direct"},
                {"symbol": "cvx", "rank": 2, "rationale": "direct"},
            ],
        }
        self.assertEqual(_extract_primary_set(ev), {"XOM", "CVX"})

    def test_handles_string_entries(self):
        ev = {"primary_assets": ["XOM", "CVX"]}
        self.assertEqual(_extract_primary_set(ev), {"XOM", "CVX"})

    def test_returns_none_when_field_missing(self):
        # Field absence signals "no explicit classification" so callers
        # fall back to the tightened single-name heuristic.  An empty
        # list (vs. a missing field) returns set() — strict mode with
        # no primaries named.
        self.assertIsNone(_extract_primary_set({}))
        self.assertIsNone(_extract_primary_set(None))
        self.assertEqual(_extract_primary_set({"primary_assets": []}), set())


class TestUnmappedTickerNotPrimary(unittest.TestCase):
    """Unmapped ETF / typo tickers must not default to primary tier."""

    def test_typo_etf_not_primary_when_explicit_set_provided(self):
        # "VXX2" is a typo of the VXX hedge ETF — alpha+digit, 4 chars.
        # Old heuristic: `_ticker_channel(VXX2) is None and "." not in "VXX2"`
        # would have classified it as primary.  Tightened rule rejects
        # off-shape (digits) symbols outright.
        explicit = {"XOM"}
        self.assertFalse(
            _is_primary_asset("VXX2", explicit_primary=explicit),
        )
        self.assertEqual(
            _eligibility_tier("VXX2", explicit_primary=explicit),
            "rejected",
        )

    def test_unmapped_alpha_outside_explicit_set_is_secondary(self):
        # Alpha-only 4-char "FAKE" passes the shape heuristic but is
        # NOT in the explicit primary set.  Must downgrade to secondary
        # (not primary) so it cannot override real primary evidence.
        explicit = {"XOM"}
        self.assertFalse(
            _is_primary_asset("FAKE", explicit_primary=explicit),
        )
        self.assertEqual(
            _eligibility_tier("FAKE", explicit_primary=explicit),
            "secondary",
        )

    def test_known_etf_not_primary_even_when_explicitly_listed(self):
        # An LLM-emitted primary_assets entry pointing at a sector ETF
        # (XLE) is a role-discipline violation — the registries are
        # authoritative and demote it to secondary regardless of the
        # explicit set.
        explicit = {"XLE"}
        self.assertFalse(
            _is_primary_asset("XLE", explicit_primary=explicit),
        )
        self.assertEqual(
            _eligibility_tier("XLE", explicit_primary=explicit),
            "secondary",
        )


class TestDottedTickerNotPrimaryByDefault(unittest.TestCase):
    """Dotted symbols (foreign listings, share classes) never primary."""

    def test_dotted_ticker_is_not_primary_legacy(self):
        # Without explicit_primary supplied, the legacy heuristic
        # path must still reject dotted symbols outright.
        self.assertFalse(_is_primary_asset("BRK.B"))
        self.assertEqual(_eligibility_tier("BRK.B"), "rejected")

    def test_foreign_suffix_is_rejected(self):
        # Foreign listings (.T = Tokyo) are rejected at the registry
        # level — explicit_primary cannot override.
        explicit = {"7203.T"}
        self.assertFalse(
            _is_primary_asset("7203.T", explicit_primary=explicit),
        )
        self.assertEqual(
            _eligibility_tier("7203.T", explicit_primary=explicit),
            "rejected",
        )


class TestExplicitPrimaryStillPrimary(unittest.TestCase):
    """Symbols in event.primary_assets retain primary status."""

    def test_explicit_single_name_is_primary(self):
        explicit = {"XOM", "CVX"}
        self.assertTrue(
            _is_primary_asset("XOM", explicit_primary=explicit),
        )
        self.assertEqual(
            _eligibility_tier("XOM", explicit_primary=explicit),
            "primary",
        )

    def test_extract_set_round_trips_through_is_primary(self):
        ev = {
            "primary_assets": [
                {"symbol": "XOM", "rank": 1, "rationale": "direct beneficiary"},
            ],
        }
        explicit = _extract_primary_set(ev)
        self.assertTrue(
            _is_primary_asset("XOM", explicit_primary=explicit),
        )
        self.assertFalse(
            _is_primary_asset("CVX", explicit_primary=explicit),
        )


class TestSignalOnlyLowerWeight(unittest.TestCase):
    """Hedge / FX / vol ETFs are signal tier — zero weight in the
    event-level aggregator."""

    def test_vxx_is_signal_tier(self):
        self.assertEqual(_eligibility_tier("VXX"), "signal")
        # Even when explicitly listed, the registry stays authoritative.
        self.assertEqual(
            _eligibility_tier("VXX", explicit_primary={"VXX"}),
            "signal",
        )

    def test_signal_ticker_does_not_contribute(self):
        # A VXX ticker with a contradicting tag must not pull the
        # event-level aggregate down — signal tier weight is 0.
        row = _ticker_contribution(
            {"symbol": "VXX", "direction_tag": "contradicts down"},
        )
        self.assertIsNone(row)

    def test_signal_cannot_override_primary_evidence(self):
        # Two primary tickers supporting + one signal ticker
        # contradicting must still resolve to a non-contradictory
        # aggregate — the signal ticker contributes zero weight.
        explicit = {"XOM", "CVX"}
        basket = [
            {"symbol": "XOM", "evidence_score":  0.8,
             "direction_tag": "supports up"},
            {"symbol": "CVX", "evidence_score":  0.7,
             "direction_tag": "supports up"},
            {"symbol": "VXX", "evidence_score": -0.9,
             "direction_tag": "contradicts down"},
        ]
        out = score_weighted_evidence(basket, explicit_primary=explicit)
        self.assertEqual(out["evidence_label"], "supportive")


class TestRejectedAssetExcluded(unittest.TestCase):
    """Broad-market indices and foreign listings get zero weight."""

    def test_broad_market_is_rejected(self):
        self.assertEqual(_eligibility_tier("SPY"), "rejected")
        self.assertEqual(_eligibility_tier("QQQ"), "rejected")

    def test_rejected_does_not_contribute(self):
        row = _ticker_contribution(
            {"symbol": "SPY", "evidence_score": -0.9},
        )
        self.assertIsNone(row)

    def test_rejected_does_not_override_primary_evidence(self):
        # A primary contradiction with rejected tape-followers around
        # it must drive the verdict — rejected tickers contribute zero.
        explicit = {"XOM"}
        basket = [
            {"symbol": "XOM", "evidence_score": -0.85,
             "direction_tag": "contradicts down"},
            {"symbol": "AMZN", "evidence_score": -0.5,
             "direction_tag": "contradicts down"},
            {"symbol": "SPY", "evidence_score":  0.9,
             "direction_tag": "supports up"},
        ]
        out = score_weighted_evidence(basket, explicit_primary=explicit)
        # SPY is rejected and zero-weighted; the surviving basket is
        # a primary contradiction (XOM, weighted-up) plus a secondary
        # contradiction (AMZN, alpha-but-not-explicit) — both negative.
        self.assertEqual(out["evidence_label"], "contradictory")


class TestUnknownChannelDoesNotOverridePrimary(unittest.TestCase):
    """An unknown-channel asset (passes shape heuristic but isn't in
    the explicit primary set) must not flip a primary contradiction
    into a supportive aggregate."""

    def test_unknown_alpha_does_not_override_primary_contradiction(self):
        explicit = {"XOM"}
        basket = [
            # Primary picks contradicting (heavy weight, primary
            # contradiction multiplier stacks).
            {"symbol": "XOM", "evidence_score": -0.85,
             "direction_tag": "contradicts down"},
            # Non-primary alpha tickers supporting — get secondary
            # weight (0.7×) so their aggregate cannot override the
            # primary contradiction.
            {"symbol": "MSFT", "evidence_score": 0.6,
             "direction_tag": "supports up"},
            {"symbol": "GOOGL", "evidence_score": 0.6,
             "direction_tag": "supports up"},
        ]
        out = score_weighted_evidence(basket, explicit_primary=explicit)
        # Primary contradiction should be the dominant signal — must
        # not land on "supportive".
        self.assertNotEqual(out["evidence_label"], "supportive")


if __name__ == "__main__":
    unittest.main()
