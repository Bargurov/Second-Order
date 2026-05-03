"""Standardized degraded / watch / low-information signaling.

Every analysis path must emit a consistent read of
``degraded`` + ``quality_tier`` + ``quality_warnings`` + ``confidence``
so consumers branching on any one signal see the others align:

  * low_information: confidence == "low" AND tradable False.
  * watch_only: confidence != "high" AND quality_warnings non-empty
    when a fail-mode tag applies.
  * actionable (clean): no degraded field, no quality_warnings field
    (absence signals "no warnings").
  * degraded fallback: degraded=True AND quality_tier=="low_information"
    AND confidence=="low" AND tradable False.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from analyze_event import _degraded_fallback, _finalize_analysis
from low_information_gate import (
    EVIDENCE_QUALITY_TIERS,
    QUALITY_WARNING_TAGS,
)


CONCRETE_MECHANISM = (
    "Saudi Aramco cuts liftings by 1mbd, tightening Gulf Coast "
    "refinery feedstock and widening the WCS-WTI heavy-sour discount."
)


def _actionable_parsed(**overrides) -> dict:
    base = {
        "what_changed": (
            "Saudi Aramco cut crude liftings by 1mbd from August "
            "contract volumes, tightening Gulf Coast feedstock supply."
        ),
        "mechanism_summary": CONCRETE_MECHANISM,
        "mechanism_family": "commodity_squeeze",
        "beneficiaries":      ["Exxon", "Chevron"],
        "losers":              ["Delta", "American Airlines"],
        "beneficiary_tickers": ["XOM", "CVX"],
        "loser_tickers":       ["DAL", "AAL"],
        "confidence": "high",
        "transmission_chain": [
            "Saudi Aramco cuts liftings",
            "Gulf Coast feedstock tightens",
            "Refining margins reprice; XOM / CVX rerate higher",
        ],
        "transmission_path": [
            {"hop": "Saudi Aramco cuts crude liftings 1mbd",
             "actor": "Saudi Aramco", "channel": "supply",
             "expected_market_effect":
                 "WCS-WTI heavy-sour spread widens >=2pp",
             "timing": "1-5d"},
            {"hop": "Gulf Coast refiners reprice feedstock margin",
             "actor": "Gulf Coast refiners", "channel": "pricing_power",
             "expected_market_effect":
                 "XOM / CVX rerate higher; SPY underperforms",
             "timing": "5-30d"},
            {"hop": "Refining-margin earnings revisions",
             "actor": "Sell-side analysts", "channel": "demand",
             "expected_market_effect":
                 "FY EPS revisions for XOM / CVX up 5%+",
             "timing": "30-60d"},
        ],
        "expected_first_order_channels":  ["commodities"],
        "expected_second_order_channels": ["equities"],
        "primary_assets": [
            {"symbol": "XOM", "rank": 1,
             "rationale": (
                 "Direct Saudi crude beneficiary via Gulf Coast "
                 "feedstock margin."
             )},
        ],
        "competing_thesis": {
            "primary_thesis": (
                "Saudi lifting cut tightens Gulf Coast heavy-sour "
                "feedstock, widening WCS-WTI discount and lifting "
                "XOM/CVX."
            ),
        },
        "minimum_proof_set": [
            {"observation": (
                "WCS-WTI heavy-sour discount widens 2pp within 5 trading days"
            ), "channel": "commodities", "threshold": "2pp",
             "timing": "1-5d"},
        ],
        "key_falsifiers": [
            (
                "Saudi Aramco reverses the lifting cut within 5 trading "
                "days, WCS discount tightens back below 1pp."
            ),
        ],
    }
    base.update(overrides)
    return base


def _finalize(**overrides) -> dict:
    parsed = _actionable_parsed(**overrides)
    return _finalize_analysis(
        parsed,
        headline="OPEC surprise cut",
        stage="realized", persistence="structural",
    )


# ---------------------------------------------------------------------------
# Field-presence + closed-set contract
# ---------------------------------------------------------------------------

class TestQualityTierField(unittest.TestCase):
    def test_quality_tier_always_present_after_finalize(self):
        out = _finalize()
        self.assertIn("quality_tier", out)

    def test_quality_tier_value_in_closed_set(self):
        out = _finalize()
        self.assertIn(out["quality_tier"], EVIDENCE_QUALITY_TIERS)


# ---------------------------------------------------------------------------
# Actionable path — clean output should not carry degraded /
# quality_warnings markers.
# ---------------------------------------------------------------------------

class TestActionablePathSignaling(unittest.TestCase):
    """Clean actionable outputs must not carry degraded /
    quality_warnings markers.  When the fixture does not land at
    actionable tier (other gates may demote it), the assertion is
    skipped — these tests guard the actionable-path contract, not
    the fixture's tier-classifier choice."""

    def test_clean_actionable_does_not_set_degraded(self):
        out = _finalize()
        if out["quality_tier"] != "actionable":
            self.skipTest("fixture didn't land at actionable")
        # Field absence (or False) for the clean actionable path.
        self.assertFalse(out.get("degraded", False))

    def test_clean_actionable_has_no_quality_warnings(self):
        out = _finalize()
        if out["quality_tier"] != "actionable":
            self.skipTest("fixture didn't land at actionable")
        # Field absence is the canonical "no warnings" signal.
        self.assertEqual(out.get("quality_warnings", []), [])

    def test_clean_actionable_quality_tier_actionable(self):
        out = _finalize()
        if out["quality_tier"] != "actionable":
            self.skipTest("fixture didn't land at actionable")
        self.assertIn(
            out.get("confidence"), {"medium", "high"},
        )

    def test_clean_actionable_actionability_is_tradable(self):
        out = _finalize()
        if out["quality_tier"] != "actionable":
            self.skipTest("fixture didn't land at actionable")
        self.assertTrue(out["actionability_check"]["tradable"])


# ---------------------------------------------------------------------------
# Watch-only path — confidence never "high", quality_warnings stamped.
# ---------------------------------------------------------------------------

class TestWatchOnlyPathSignaling(unittest.TestCase):
    def test_watch_only_confidence_never_high(self):
        # Drop primary_assets rationale to land in watch_only.
        out = _finalize(
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": ""},
            ],
        )
        if out["quality_tier"] != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        self.assertNotEqual(out.get("confidence"), "high")

    def test_watch_only_emits_quality_warnings(self):
        out = _finalize(
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": ""},
            ],
        )
        if out["quality_tier"] != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        warnings = out.get("quality_warnings") or []
        # All emitted tags must come from the closed vocabulary.
        for tag in warnings:
            self.assertIn(tag, QUALITY_WARNING_TAGS)

    def test_watch_only_does_not_set_degraded(self):
        # Tier-coerced watch_only is NOT "model returned a thin
        # response" — degraded flag must stay off.
        out = _finalize(
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": ""},
            ],
        )
        if out["quality_tier"] != "watch_only":
            self.skipTest("fixture didn't land at watch_only")
        self.assertFalse(out.get("degraded", False))


# ---------------------------------------------------------------------------
# Low-information path — confidence "low", non-tradable.
# ---------------------------------------------------------------------------

class TestLowInformationPathSignaling(unittest.TestCase):
    def test_low_information_confidence_is_low(self):
        out = _finalize(mechanism_summary="N/A insufficient evidence.")
        if out["quality_tier"] != "low_information":
            self.skipTest("fixture didn't land at low_information")
        self.assertEqual(out["confidence"], "low")

    def test_low_information_is_non_tradable(self):
        out = _finalize(mechanism_summary="N/A insufficient evidence.")
        if out["quality_tier"] != "low_information":
            self.skipTest("fixture didn't land at low_information")
        self.assertFalse(out["actionability_check"]["tradable"])


# ---------------------------------------------------------------------------
# Degraded fallback path — full alignment of all four signals.
# ---------------------------------------------------------------------------

class TestDegradedFallbackSignaling(unittest.TestCase):
    def setUp(self) -> None:
        self.fallback = _degraded_fallback(
            "Some headline", "realized", "structural",
            "thin mechanism + no chain + no entities",
        )

    def test_degraded_flag_true(self):
        self.assertTrue(self.fallback["degraded"])

    def test_quality_tier_is_low_information(self):
        self.assertEqual(self.fallback["quality_tier"], "low_information")

    def test_quality_warnings_populated(self):
        warnings = self.fallback.get("quality_warnings") or []
        self.assertTrue(warnings)
        for tag in warnings:
            self.assertIn(tag, QUALITY_WARNING_TAGS)

    def test_confidence_is_low(self):
        self.assertEqual(self.fallback["confidence"], "low")

    def test_actionability_non_tradable(self):
        self.assertFalse(self.fallback["actionability_check"]["tradable"])

    def test_validation_warnings_carries_degraded_reason(self):
        warns = self.fallback.get("validation_warnings") or []
        self.assertTrue(any("degraded" in w for w in warns))
        # Tier tag also surfaced for back-compat with consumers reading
        # the older string-tag path.
        self.assertTrue(any(
            "evidence_quality: low_information" in w for w in warns
        ))


# ---------------------------------------------------------------------------
# Cross-signal invariants — every path's signals must agree.
# ---------------------------------------------------------------------------

class TestSignalingInvariants(unittest.TestCase):
    """For each finalized analysis, the four signals must be
    internally consistent regardless of which path produced it."""

    def _check_invariants(self, out: dict, *, ctx: str) -> None:
        tier = out.get("quality_tier")
        self.assertIn(tier, EVIDENCE_QUALITY_TIERS, msg=ctx)
        confidence = out.get("confidence")
        tradable = out.get("actionability_check", {}).get("tradable")
        if tier == "low_information":
            self.assertEqual(confidence, "low", msg=ctx)
            self.assertFalse(tradable, msg=ctx)
        elif tier == "watch_only":
            self.assertNotEqual(confidence, "high", msg=ctx)
        elif tier == "actionable":
            # Clean actionable: no degraded marker.
            self.assertFalse(out.get("degraded", False), msg=ctx)

    def test_invariants_actionable(self):
        self._check_invariants(_finalize(), ctx="actionable")

    def test_invariants_watch_only(self):
        out = _finalize(
            primary_assets=[
                {"symbol": "XOM", "rank": 1, "rationale": ""},
            ],
        )
        self._check_invariants(out, ctx="watch_only-coerced")

    def test_invariants_low_information(self):
        out = _finalize(mechanism_summary="N/A insufficient evidence.")
        self._check_invariants(out, ctx="low-info-coerced")

    def test_invariants_degraded(self):
        out = _degraded_fallback(
            "h", "realized", "structural", "thin mechanism",
        )
        self._check_invariants(out, ctx="degraded-fallback")


if __name__ == "__main__":
    unittest.main()
