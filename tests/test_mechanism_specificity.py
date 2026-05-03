"""
tests/test_mechanism_specificity.py

Focused tests for the mechanism-specificity / asset-discipline upgrade
in analyze_event.  Four behaviors:

  1. One clear mechanism is preserved end-to-end through the pipeline.
  2. Asset entries require a concrete rationale; missing rationale is dropped.
  3. Vague filler asset rationales are removed by the sanitizer.
  4. A weak / blended mechanism stays low-information — no broad-proxy padding.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    _clean_assets,
    _clean_ranked_asset_list,
    _finalize_analysis,
    _is_blended_mechanism,
    _is_generic_rationale,
)


# ---------------------------------------------------------------------------
# 1. One primary mechanism is chosen
# ---------------------------------------------------------------------------


class TestOnePrimaryMechanismChosen(unittest.TestCase):
    def test_clean_single_mechanism_is_preserved(self) -> None:
        parsed = {
            "what_changed": "US Treasury issued a Chevron licence for Venezuelan crude liftings.",
            "mechanism_summary": (
                "Restored heavy-sour supply to Gulf Coast coking refineries "
                "lowers marginal feedstock cost; Canadian WCS sellers lose "
                "outlet share at the marginal barrel."
            ),
            "beneficiaries": ["Chevron"],
            "losers": ["Suncor"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers": ["SU"],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
            "primary_assets": [
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct licence holder — restored lift volumes lift equity."},
            ],
        }
        out = _finalize_analysis(
            parsed, headline="Treasury licence", stage="realized",
            persistence="medium",
        )
        # The chosen mechanism family is preserved (not coerced to "none").
        self.assertEqual(out["mechanism_family"], "supply_normalization")
        # The single mechanism-tied primary asset survives.
        self.assertEqual([e["symbol"] for e in out["primary_assets"]], ["CVX"])
        # Confidence not forced down on a clean, single-channel read.
        self.assertEqual(out["confidence"], "medium")

    def test_blended_mechanism_text_is_detected(self) -> None:
        # Multi-channel mash → True.
        for blended in (
            "Broad-based impact across multiple channels with ripple effects "
            "spreading through markets via various transmission pathways.",
            "Effects propagate via multiple mechanisms simultaneously, with "
            "ripple effects spreading throughout the market.",
            "Wide-ranging impacts touch many sectors at once.",
            "Diffuse effect across various pathways that are hard to isolate.",
        ):
            with self.subTest(text=blended[:50]):
                self.assertTrue(_is_blended_mechanism(blended))

        # Clean single-channel → False.
        for ok in (
            "Restored heavy-sour supply to Gulf Coast coking refineries "
            "lowers feedstock cost.",
            "Entity List restricts EUV access; non-Chinese fabs gain "
            "scarcity premium.",
            "",
            None,
        ):
            with self.subTest(text=str(ok)[:50]):
                self.assertFalse(_is_blended_mechanism(ok))


# ---------------------------------------------------------------------------
# 2. Asset entries require a concrete rationale
# ---------------------------------------------------------------------------


class TestAssetsRequireRationale(unittest.TestCase):
    def test_entry_without_rationale_dropped(self) -> None:
        raw = [
            {"symbol": "CVX", "rank": 1, "rationale": ""},
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf Coast heavy-sour coking refiner — feedstock drop."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["symbol"] for e in out], ["PBF"])

    def test_whitespace_only_rationale_dropped(self) -> None:
        raw = [
            {"symbol": "CVX", "rank": 1, "rationale": "   "},
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf coker; feedstock cost drops."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertNotIn("CVX", [e["symbol"] for e in out])

    def test_missing_rationale_key_dropped(self) -> None:
        raw = [
            {"symbol": "CVX", "rank": 1},  # no rationale key at all
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf coker; feedstock cost drops."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["symbol"] for e in out], ["PBF"])


# ---------------------------------------------------------------------------
# 3. Vague filler assets are removed
# ---------------------------------------------------------------------------


class TestVagueFillerAssetsRemoved(unittest.TestCase):
    def test_full_string_filler_rationales_flagged(self) -> None:
        for filler in (
            "Broad sector exposure",
            "Direct beneficiary",
            "Direct beneficiary of the sector",
            "Major beneficiary of the trend",
            "Pure-play exposure to the theme",
            "Pure-play exposure",
            "Thematic play on the trend",
            "Thematic proxy",
            "Indirect exposure to the broader market",
            "Sector proxy",
            "Sector proxy.",
            "Sector ETF",
            "Sector tailwind",
            "Diversified sector etf",
            "Key player in the industry",
            "Leading player in the space",
            "General sector exposure",
            "General sector beneficiary",
            "Broader market exposure",
            "Broad market reaction",
            "Exposure to the trend",
        ):
            with self.subTest(rationale=filler):
                self.assertTrue(
                    _is_generic_rationale(filler),
                    f"expected to flag as filler: {filler!r}",
                )

    def test_specific_rationales_preserved(self) -> None:
        for keep in (
            "Direct licence holder — restored lift volumes lift equity.",
            "Gulf Coast heavy-sour coking refiner — feedstock drop on Venezuelan barrels.",
            "Largest US Gulf coker by capacity; marginal feedstock cost drops directly.",
            "Sole-source EUV provider — accelerated non-China orders offset lost China revenue.",
            "Process-step share at 7nm node hits LRCX revenue line.",
            "Direct counterparty exposure to the contract change at Jose terminal.",
            "Etch-equipment revenue to the 28 named Chinese fabs is the gated line.",
        ):
            with self.subTest(rationale=keep):
                self.assertFalse(
                    _is_generic_rationale(keep),
                    f"expected to keep: {keep!r}",
                )

    def test_filler_entries_dropped_from_ranked_bucket(self) -> None:
        raw = [
            {"symbol": "XLE", "rank": 1, "rationale": "Broad sector exposure"},
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf Coast coker — heavy-sour feedstock drop."},
            {"symbol": "ITA", "rank": 3, "rationale": "Sector proxy."},
            {"symbol": "GLD", "rank": 4,
             "rationale": "Direct beneficiary of the trend"},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        # Only the specific PBF entry survives; XLE/ITA/GLD are filler.
        self.assertEqual([e["symbol"] for e in out], ["PBF"])

    def test_ranks_recompute_after_filler_drops(self) -> None:
        raw = [
            {"symbol": "XLE", "rank": 1, "rationale": "Broad sector exposure"},
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf coker — heavy-sour feedstock drop."},
            {"symbol": "VLO", "rank": 3,
             "rationale": "Largest Gulf heavy-sour refiner by capacity."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        # XLE dropped; PBF / VLO get rank 1 / 2 after re-indexing.
        self.assertEqual([e["rank"] for e in out], [1, 2])
        self.assertEqual([e["symbol"] for e in out], ["PBF", "VLO"])


# ---------------------------------------------------------------------------
# 4. Weak analysis stays low-information
# ---------------------------------------------------------------------------


class TestWeakAnalysisStaysLowInformation(unittest.TestCase):
    """A blended or filler mechanism must not pad with broad-sector
    proxies, and the structured shape must collapse to low-info."""

    def test_skip_proxy_backfill_param_suppresses_padding(self) -> None:
        # Without skip: backfill kicks in for a known keyword.
        with_pad = _clean_assets([], context="oil semiconductor defense")
        self.assertGreater(len(with_pad), 0)
        # With skip: no broad sector ETFs added.
        without_pad = _clean_assets(
            [], context="oil semiconductor defense",
            skip_proxy_backfill=True,
        )
        self.assertEqual(without_pad, [])

    def test_blended_mechanism_skips_proxy_backfill_in_pipeline(self) -> None:
        parsed = {
            "what_changed": (
                "Some action with widely diffused implications across many sectors."
            ),
            "mechanism_summary": (
                "Broad-based impact across multiple channels with ripple effects "
                "spreading throughout markets via various transmission pathways."
            ),
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "confidence": "medium",
            "mechanism_family": "none",
        }
        out = _finalize_analysis(
            parsed,
            headline="oil semiconductor defense headline",
            stage="realized",
            persistence="medium",
        )
        # No broad sector ETF proxies were padded in.  These are the
        # symbols `_PROXY_MAP` would otherwise inject for the given context.
        bad_proxies = {"XLE", "USO", "BNO", "SMH", "SOXX", "ITA", "XAR", "GLD", "FXI"}
        self.assertEqual(
            set(out.get("beneficiary_tickers", [])) & bad_proxies,
            set(),
            f"weak mechanism padded with broad proxies: {out.get('beneficiary_tickers')}",
        )

    def test_blended_mechanism_coerces_to_low_information_shape(self) -> None:
        parsed = {
            "what_changed": "Generic widespread headline with multiple effects.",
            "mechanism_summary": (
                "Broad-based effects across multiple channels with ripple effects "
                "spreading throughout the market via various pathways."
            ),
            "beneficiaries": ["Chevron"],
            "losers": ["Suncor"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers": ["SU"],
            "confidence": "high",
            "mechanism_family": "supply_normalization",
            "primary_assets": [
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct licence holder — restored lift volumes."},
            ],
            "minimum_proof_set": [
                {"observation": "Chevron loadings tracked at Jose terminal",
                 "channel": "commodities", "threshold": "≥1 cargo / week",
                 "timing": "1-5d"},
            ],
            "key_falsifiers": [
                "Chevron reports zero new Venezuelan loadings within 5 days",
            ],
        }
        out = _finalize_analysis(
            parsed, headline="x", stage="realized", persistence="medium",
        )
        # Coerced to the low-information shape.
        self.assertEqual(out["confidence"], "low")
        self.assertEqual(out["mechanism_family"], "none")
        self.assertEqual(out["minimum_proof_set"], [])
        self.assertEqual(out["key_falsifiers"], [])
        # Ranked buckets cleared — the rationale can't be trusted to
        # tie back to any single primary mechanism on a blended read.
        self.assertEqual(out["primary_assets"], [])
        self.assertEqual(out["secondary_assets"], [])
        self.assertEqual(out["hedge_or_signal_assets"], [])
        # Validation warning recorded for downstream visibility.
        self.assertIn(
            "blended mechanism — coerced to low-information",
            out.get("validation_warnings") or [],
        )

    def test_short_filler_mechanism_skips_proxy_backfill(self) -> None:
        parsed = {
            "what_changed": "Some headline.",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "confidence": "low",
            "mechanism_family": "none",
        }
        out = _finalize_analysis(
            parsed,
            headline="oil chip defense",
            stage="realized",
            persistence="medium",
        )
        bad_proxies = {"XLE", "USO", "BNO", "SMH", "SOXX", "ITA", "XAR", "GLD"}
        self.assertEqual(
            set(out.get("beneficiary_tickers", [])) & bad_proxies,
            set(),
        )

    def test_loser_inverse_proxy_also_skipped_on_weak_mechanism(self) -> None:
        parsed = {
            "what_changed": "Some headline with diffused effect.",
            "mechanism_summary": (
                "Broad-based reaction across multiple sectors with ripple "
                "effects propagating throughout."
            ),
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "confidence": "medium",
            "mechanism_family": "none",
        }
        out = _finalize_analysis(
            parsed,
            headline="oil semiconductor headline",
            stage="realized",
            persistence="medium",
        )
        # No inverse-ETF proxies (DUG, SOXS, SH, etc.) get padded in.
        joined = " ".join(out.get("loser_tickers", []) or [])
        self.assertNotIn("(proxy)", joined.lower())

    def test_clean_mechanism_still_gets_proxy_backfill(self) -> None:
        """Sanity check the gate doesn't over-fire — a clean mechanism
        text with empty tickers still gets the existing proxy backfill."""
        parsed = {
            "what_changed": "Specific named action by a specific named actor.",
            "mechanism_summary": (
                "Restored heavy-sour supply to Gulf Coast coking refineries "
                "lowers marginal feedstock cost via the standard refining "
                "pass-through channel — single-channel transmission."
            ),
            "beneficiaries": ["Refiners"],
            "losers": ["WCS sellers"],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
        }
        out = _finalize_analysis(
            parsed,
            headline="oil crude refining headline",
            stage="realized",
            persistence="medium",
        )
        # Backfill should have added at least one proxy from `_PROXY_MAP`.
        self.assertGreater(len(out.get("beneficiary_tickers", [])), 0)


if __name__ == "__main__":
    unittest.main()
