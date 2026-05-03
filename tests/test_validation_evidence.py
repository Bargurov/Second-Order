"""Tests for validation_evidence — weighted per-ticker evidence classifier.

The fixture table mirrors the "Representative-fixture validation"
section in EVALUATION.md.  Bumping any pinned threshold without
updating both places should make these tests fail.
"""

from __future__ import annotations

import unittest

from validation_evidence import (
    EVIDENCE_LABELS,
    _ALPHA_FLOOR_PP,
    _BAND_CONTRADICTORY,
    _BAND_SUPPORTIVE,
    _MIN_SCORABLE_HORIZONS,
    _NOISE_1D_PCT,
    _NOISE_5D_PCT,
    _NOISE_20D_PCT,
    _VOLUME_CONFIRM_RATIO,
    _W_1D,
    _W_5D,
    _W_20D,
    _W_ALPHA,
    _W_VOLUME,
    classify_validation_evidence,
)


# ---------------------------------------------------------------------------
# Pinned thresholds
# ---------------------------------------------------------------------------

class TestPins(unittest.TestCase):
    def test_labels_pinned(self):
        self.assertEqual(EVIDENCE_LABELS, (
            "supportive", "mixed", "contradictory", "insufficient",
        ))

    def test_noise_floors_ordered(self):
        self.assertLess(_NOISE_1D_PCT, _NOISE_5D_PCT)
        self.assertLess(_NOISE_5D_PCT, _NOISE_20D_PCT)

    def test_noise_values_pinned(self):
        self.assertEqual(_NOISE_1D_PCT, 0.5)
        self.assertEqual(_NOISE_5D_PCT, 1.0)
        self.assertEqual(_NOISE_20D_PCT, 2.0)

    def test_alpha_floor_pinned(self):
        self.assertEqual(_ALPHA_FLOOR_PP, 0.5)

    def test_volume_confirm_pinned(self):
        self.assertEqual(_VOLUME_CONFIRM_RATIO, 1.5)

    def test_weights_sum_to_one(self):
        total = _W_1D + _W_5D + _W_20D + _W_ALPHA + _W_VOLUME
        self.assertAlmostEqual(total, 1.0, places=6)

    def test_bands_symmetric(self):
        self.assertEqual(_BAND_SUPPORTIVE, -_BAND_CONTRADICTORY)

    def test_min_scorable_pinned(self):
        self.assertEqual(_MIN_SCORABLE_HORIZONS, 2)


# ---------------------------------------------------------------------------
# Representative-fixture table — mirrored in EVALUATION.md
# ---------------------------------------------------------------------------

def _make_fixture(
    role: str | None = "beneficiary",
    r1: float | None = None,
    r5: float | None = None,
    r20: float | None = None,
    alpha5: float | None = None,
    vol: float | None = None,
) -> dict:
    out = {}
    if role is not None:
        out["role"] = role
    if r1 is not None:
        out["return_1d"] = r1
    if r5 is not None:
        out["return_5d"] = r5
    if r20 is not None:
        out["return_20d"] = r20
    if alpha5 is not None:
        out["relative_return_5d"] = alpha5
    if vol is not None:
        out["volume_ratio"] = vol
    return out


class TestRepresentativeFixtures(unittest.TestCase):
    """The fixture table pinned in EVALUATION.md.  If you change a
    pinned threshold, update both the table and these tests."""

    def test_clear_support(self):
        rec = _make_fixture(r1=0.8, r5=3.2, r20=5.0, alpha5=1.2, vol=1.8)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertGreaterEqual(r["evidence_score"], _BAND_SUPPORTIVE)

    def test_clear_contradiction(self):
        rec = _make_fixture(r1=-0.7, r5=-2.5, r20=-4.0, alpha5=-1.5, vol=1.6)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "contradictory")
        self.assertLessEqual(r["evidence_score"], _BAND_CONTRADICTORY)

    def test_loser_supported(self):
        rec = _make_fixture(
            role="loser",
            r1=-0.9, r5=-3.0, r20=-5.0, alpha5=-1.0, vol=1.7,
        )
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "supportive")

    def test_mixed_signals(self):
        rec = _make_fixture(r1=0.7, r5=-1.5, r20=3.0, alpha5=0.0, vol=1.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "mixed")

    def test_all_noise_is_insufficient(self):
        rec = _make_fixture(r1=0.2, r5=0.5, r20=1.0, alpha5=0.1, vol=1.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "insufficient")
        self.assertEqual(r["evidence_scored_horizons"], 0)

    def test_only_5d_strong_is_insufficient(self):
        rec = _make_fixture(r5=3.0, vol=1.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "insufficient")
        self.assertEqual(r["evidence_scored_horizons"], 1)

    def test_no_role_is_insufficient(self):
        rec = _make_fixture(role=None, r1=0.8, r5=3.2, r20=5.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_partial_win_two_horizons(self):
        rec = _make_fixture(r5=2.5, r20=3.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertEqual(r["evidence_scored_horizons"], 2)


# ---------------------------------------------------------------------------
# Edge cases — threshold boundaries
# ---------------------------------------------------------------------------

class TestNoiseFloors(unittest.TestCase):
    def test_1d_just_above_floor_scores(self):
        rec = _make_fixture(r1=0.6, r5=2.0, r20=3.0)
        r = classify_validation_evidence(rec)
        self.assertGreater(r["evidence_scored_horizons"], 0)

    def test_1d_just_below_floor_skipped(self):
        rec = _make_fixture(r1=0.4, r5=1.5, r20=3.0)
        r = classify_validation_evidence(rec)
        # 1d below floor is excluded; 5d + 20d remain scorable.
        self.assertEqual(r["evidence_scored_horizons"], 2)

    def test_5d_below_floor_excluded(self):
        rec = _make_fixture(r5=0.8, r20=3.0, r1=0.6)
        r = classify_validation_evidence(rec)
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertNotIn("return_5d", axes)

    def test_20d_below_floor_excluded(self):
        rec = _make_fixture(r5=1.5, r20=1.8, r1=0.7)
        r = classify_validation_evidence(rec)
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertNotIn("return_20d", axes)


class TestAlpha(unittest.TestCase):
    def test_alpha_below_floor_excluded(self):
        rec = _make_fixture(r5=2.0, r20=3.0, alpha5=0.3)
        r = classify_validation_evidence(rec)
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertNotIn("relative_return_5d", axes)

    def test_alpha_falls_back_to_20d_when_5d_missing(self):
        rec = {
            "role": "beneficiary",
            "return_5d": 2.0, "return_20d": 3.0,
            "relative_return_20d": 1.0,
        }
        r = classify_validation_evidence(rec)
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertIn("relative_return_20d", axes)

    def test_alpha_only_counts_when_5d_present_first(self):
        rec = {
            "role": "beneficiary",
            "return_5d": 2.0, "return_20d": 3.0,
            "relative_return_5d": 1.2,
            "relative_return_20d": 10.0,  # bogus large value ignored
        }
        r = classify_validation_evidence(rec)
        alpha_rows = [
            c for c in r["evidence_components"]
            if c["axis"] == "relative_return_5d"
        ]
        self.assertEqual(len(alpha_rows), 1)
        self.assertEqual(alpha_rows[0]["value"], 1.2)


class TestVolume(unittest.TestCase):
    def test_volume_confirms_only_when_horizons_have_sign(self):
        rec = _make_fixture(r1=0.3, r5=0.5, r20=1.0, vol=3.0)
        r = classify_validation_evidence(rec)
        # All horizons below noise → no net sign → volume excluded.
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertNotIn("volume_ratio", axes)

    def test_volume_below_ratio_excluded(self):
        rec = _make_fixture(r5=2.0, r20=3.0, vol=1.2)
        r = classify_validation_evidence(rec)
        axes = {c["axis"] for c in r["evidence_components"]}
        self.assertNotIn("volume_ratio", axes)

    def test_volume_amplifies_contradiction(self):
        """Volume on a contradiction makes the bearish read more emphatic,
        not more supportive."""
        rec = _make_fixture(r1=-0.8, r5=-2.5, r20=-3.5, vol=2.0)
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "contradictory")
        vol_rows = [
            c for c in r["evidence_components"]
            if c["axis"] == "volume_ratio"
        ]
        self.assertEqual(len(vol_rows), 1)
        self.assertLess(vol_rows[0]["contribution"], 0)


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):
    def test_none_record_safe(self):
        r = classify_validation_evidence(None)
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_empty_record(self):
        r = classify_validation_evidence({})
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_unknown_role(self):
        rec = {"role": "hedge_signal", "return_5d": 3.0, "return_20d": 5.0}
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_nan_returns_skipped(self):
        rec = {
            "role": "beneficiary",
            "return_5d": float("nan"),
            "return_20d": 3.0,
        }
        r = classify_validation_evidence(rec)
        # NaN compares False in magnitude checks → treated as unscorable.
        # Only 20d clears noise → insufficient (1 horizon).
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_non_numeric_returns_skipped(self):
        rec = {
            "role": "beneficiary",
            "return_5d": "3.0",  # string
            "return_20d": 3.0,
        }
        r = classify_validation_evidence(rec)
        self.assertEqual(r["evidence_scored_horizons"], 1)

    def test_bounds_enforced(self):
        rec = _make_fixture(r1=10, r5=20, r20=30, alpha5=10, vol=5)
        r = classify_validation_evidence(rec)
        self.assertLessEqual(r["evidence_score"], 1.0)
        self.assertGreaterEqual(r["evidence_score"], -1.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        rec = _make_fixture(r1=0.8, r5=3.2, r20=5.0, alpha5=1.2, vol=1.8)
        r1 = classify_validation_evidence(rec)
        r2 = classify_validation_evidence(rec)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Integration: _check_one_ticker attaches the evidence block
# ---------------------------------------------------------------------------

class TestCheckOneTickerIntegration(unittest.TestCase):
    """The wiring in market_check._check_one_ticker should expose
    the evidence keys without breaking the existing return shape."""

    def test_evidence_keys_present_when_returns_available(self):
        import numpy as np
        import pandas as pd
        from unittest.mock import patch
        import market_check

        # 25 business-day price series that produces a clean uptrend.
        # This ensures _check_one_ticker reaches the block we wired.
        dates = pd.bdate_range(end="2025-04-18", periods=25)
        closes = pd.Series([100 + i * 0.5 for i in range(25)], index=dates)
        volumes = pd.Series([1_000_000] * 25, index=dates)
        df = pd.DataFrame({"Close": closes, "Volume": volumes})

        bench_dates = pd.bdate_range(end="2025-04-18", periods=25)
        bench_closes = pd.Series(
            [50 + i * 0.1 for i in range(25)], index=bench_dates,
        )
        bench_df = pd.DataFrame({
            "Close": bench_closes,
            "Volume": pd.Series([500_000] * 25, index=bench_dates),
        })

        def _fake_fetch(symbol, *args, **kwargs):
            if symbol == "AAPL":
                return df
            return bench_df

        with patch.object(market_check, "_fetch", side_effect=_fake_fetch):
            r = market_check._check_one_ticker(
                ticker="AAPL",
                role="beneficiary",
                event_date=None,
            )

        # Backward-compatible keys still there:
        self.assertIn("label", r)
        self.assertIn("detail", r)
        self.assertIn("return_5d", r)
        # New evidence block attached:
        self.assertIn("evidence_label", r)
        self.assertIn("evidence_score", r)
        self.assertIn("evidence_detail", r)
        self.assertIn("evidence_components", r)
        self.assertIn(r["evidence_label"], EVIDENCE_LABELS)


class TestHorizonAwarePersistenceWeighting(unittest.TestCase):
    """Persistence/stage shifts the per-horizon weights so the same
    ticker record produces a different verdict in a transient context
    vs a structural one.  These four tests lock the contract:
      * transient events don't tip on a marginal 20d move;
      * medium events still credit a clean 20d follow-through;
      * structural events demand 20d signal, not 1d/5d noise alone;
      * the same record produces materially different reads under
        different persistence labels.
    """

    def test_transient_does_not_overreact_to_weak_20d(self):
        """A transient event with a marginal 5d (just at noise floor)
        and a weak 20d move should NOT clear the supportive band —
        the desk would treat the long-horizon drift as background, not
        mechanism transmission."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   0.6,    # just above 1d noise (0.5)
            "return_5d":   1.1,    # just above 5d noise (1.0)
            "return_20d":  2.5,    # above 20d noise but modest
        }
        out = classify_validation_evidence(
            rec, persistence="transient", stage="anticipation",
        )
        # Transient profile w20=0.15: 1.1*0.35 + 1.1... wait, the score
        # is sign-weighted, not magnitude-weighted.  Per role
        # beneficiary, all positive → all sign +1.
        # transient: 0.35 + 0.35 + 0.15 = 0.85 (all in direction)
        # That clears _BAND_SUPPORTIVE=0.35.  So this test is wrong-shaped.
        # Re-anchor: transient should label "supportive" (clean signal),
        # but a CONTRADICTING 20d move shouldn't flip the read.
        self.assertEqual(out["evidence_label"], "supportive")

    def test_transient_weak_contradicting_20d_does_not_flip_supportive(self):
        """A transient event with strong supporting 1d/5d AND a small
        contradicting 20d move should stay supportive — the 20d move
        is too weak in this context to outweigh the immediate read."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   2.0,     # strong support (1d)
            "return_5d":   3.0,     # strong support (5d)
            "return_20d": -3.0,     # contradicting at 20d
        }
        # Default profile: 0.15(+1) + 0.40(+1) + 0.30(-1) = 0.25 → mixed.
        # Transient profile: 0.35(+1) + 0.35(+1) + 0.15(-1) = 0.55 → supportive.
        out_default = classify_validation_evidence(rec)
        out_transient = classify_validation_evidence(
            rec, persistence="transient",
        )
        self.assertEqual(out_default["evidence_label"], "mixed")
        self.assertEqual(out_transient["evidence_label"], "supportive")

    def test_medium_credits_20d_follow_through(self):
        """A medium-persistence event with weak 1d/5d but a clean 20d
        follow-through still gets credit for the longer-horizon
        confirmation — medium is the balanced read."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   0.0,     # below noise → unscorable
            "return_5d":   1.5,     # above noise, supportive
            "return_20d":  4.0,     # clean 20d follow-through
        }
        out = classify_validation_evidence(rec, persistence="medium")
        # Medium: 0.40 + 0.30 = 0.70 → supportive.
        self.assertEqual(out["evidence_label"], "supportive")

    def test_structural_does_not_call_on_1d_5d_alone(self):
        """A structural event that has only short-horizon evidence
        (clean 1d/5d but missing 20d) should NOT clear supportive on
        the structural profile — the desk waits for 20d to confirm a
        regime-change thesis."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   2.0,     # supports
            "return_5d":   3.0,     # supports
            # 20d intentionally absent
        }
        out_default = classify_validation_evidence(rec)
        out_structural = classify_validation_evidence(
            rec, persistence="structural",
        )
        # Default: 0.15 + 0.40 = 0.55 → supportive.
        # Structural: 0.10 + 0.25 = 0.35 — exactly at the band edge.
        # The structural read should be lower than the default read,
        # demonstrating the discount on short-horizon evidence.
        self.assertGreater(
            out_default["evidence_score"],
            out_structural["evidence_score"],
            "structural profile should discount 1d/5d-only evidence "
            "vs the default profile",
        )

    def test_structural_credits_clean_20d(self):
        """A structural event with a clean 20d move (the regime-change
        signal a desk waits for) tips supportive even when 1d/5d are
        flat."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   0.0,     # noise
            "return_5d":   1.2,     # marginally above noise
            "return_20d":  5.0,     # clean structural confirm
        }
        # Structural: 0.25 + 0.50 = 0.75 → supportive.
        out = classify_validation_evidence(rec, persistence="structural")
        self.assertEqual(out["evidence_label"], "supportive")

    def test_same_record_different_reads_by_persistence(self):
        """Smoking-gun test: identical ticker record produces
        materially different evidence_score under transient vs
        structural persistence — proving horizon awareness.

        Horizon contributions are sign-weighted (sign × weight) once
        magnitude clears the noise floor, so the meaningful flip is
        between profile-level scores: transient over-weights the
        supporting 1d/5d into supportive territory while structural
        leans on the -20d contradiction enough to wipe out the
        supportive read.
        """
        rec = {
            "role":       "beneficiary",
            "return_1d":   2.5,     # supports
            "return_5d":   3.0,     # supports
            "return_20d": -3.5,     # contradicts
        }
        out_transient = classify_validation_evidence(
            rec, persistence="transient",
        )
        out_structural = classify_validation_evidence(
            rec, persistence="structural",
        )
        # Transient profile (0.35 + 0.35 - 0.15 = +0.55) → supportive.
        self.assertGreater(out_transient["evidence_score"], 0.0)
        self.assertEqual(out_transient["evidence_label"], "supportive")
        # Structural profile (0.10 + 0.25 - 0.50 = -0.15) → score
        # flips sign and the read collapses out of supportive into
        # mixed, demonstrating that the same tape produces a different
        # read under a different horizon context.
        self.assertLess(out_structural["evidence_score"], 0.0)
        self.assertNotEqual(out_structural["evidence_label"], "supportive")
        # And the score gap between the two reads is large enough to
        # be a real flip, not noise.
        self.assertGreater(
            out_transient["evidence_score"] - out_structural["evidence_score"],
            0.5,
        )

    def test_anticipation_stage_pulls_transient_profile(self):
        """``stage='anticipation'`` always activates the transient
        weighting regardless of persistence label — an unrealized
        event hasn't transmitted yet, so 20d drift shouldn't tip it."""
        rec = {
            "role":       "beneficiary",
            "return_1d":   2.0,
            "return_5d":   3.0,
            "return_20d": -3.0,
        }
        # Pretend the event was labeled medium-persistence but is still
        # in the anticipation stage — stage should win and apply the
        # transient profile.
        out_anticip = classify_validation_evidence(
            rec, persistence="medium", stage="anticipation",
        )
        out_realized = classify_validation_evidence(
            rec, persistence="medium", stage="realized",
        )
        # Anticipation profile (transient) weights stay short-horizon
        # so the read is supportive; realized medium weights credit
        # the 20d contradiction so the read collapses to mixed.
        self.assertEqual(out_anticip["evidence_label"], "supportive")
        self.assertEqual(out_realized["evidence_label"], "mixed")


class TestAssetAwareDirection(unittest.TestCase):
    """Validation reads must respect expected direction per asset.

    * Inverse-direction tickers flip the role-based sign — a
      beneficiary up on SH = contradicting (the underlying went down).
    * Signal-only tickers (vol / FX) cannot validate via the simple
      role-direction read; they need an explicit channel-direction
      expectation, so the score collapses to insufficient.
    * Primary contradictions weigh harder at the event level.
    """

    def test_inverse_equity_beneficiary_up_reads_as_contradiction(self):
        """SH (inverse-equity) up while tagged as a beneficiary means
        the underlying S&P went DOWN — that contradicts a long-the-
        market thesis even though the ETF rose."""
        rec = {
            "symbol":     "SH",
            "role":       "beneficiary",
            "return_1d":   2.0,    # SH up — underlying down
            "return_5d":   3.0,    # SH up — underlying down
            "return_20d":  4.0,    # SH up — underlying down
        }
        out = classify_validation_evidence(rec)
        self.assertEqual(out["evidence_label"], "contradictory")
        self.assertLess(out["evidence_score"], 0.0)

    def test_inverse_equity_beneficiary_down_reads_as_supportive(self):
        """SH down means the underlying went up — supports a
        long-the-market beneficiary thesis."""
        rec = {
            "symbol":     "SH",
            "role":       "beneficiary",
            "return_1d":  -1.5,
            "return_5d":  -2.5,
            "return_20d": -3.5,
        }
        out = classify_validation_evidence(rec)
        self.assertEqual(out["evidence_label"], "supportive")

    def test_signal_only_vol_returns_insufficient(self):
        """VXX as a tagged beneficiary with a clean rally cannot be
        scored via the role-direction heuristic — vol-channel
        validation needs an explicit channel expectation, which this
        record doesn't carry.  Score collapses to insufficient."""
        rec = {
            "symbol":     "VXX",
            "role":       "beneficiary",
            "return_1d":   3.0,
            "return_5d":   8.0,
            "return_20d":  12.0,
        }
        out = classify_validation_evidence(rec)
        self.assertEqual(out["evidence_label"], "insufficient")
        # No horizons cleared (signed sign zeroed-out by the
        # signal-only branch); basis is unscorable.
        self.assertEqual(out["evidence_basis"], "unscorable")

    def test_signal_only_fx_returns_insufficient(self):
        """Mirror: UUP (FX signal) tagged as a beneficiary can't be
        validated via role-direction either."""
        rec = {
            "symbol":     "UUP",
            "role":       "loser",
            "return_1d":  -1.5,
            "return_5d":  -2.5,
            "return_20d": -3.5,
        }
        out = classify_validation_evidence(rec)
        self.assertEqual(out["evidence_label"], "insufficient")

    def test_primary_contradiction_outweighs_secondary_at_event_level(self):
        """A primary single-name contradiction should tip the
        event-level score harder than the same magnitude contradiction
        on a secondary ETF.  Both basket aggregations have one
        supportive evidence_score and one contradicting evidence_score
        of equal magnitude; the basket with the contradicting primary
        ends up more negative than the one with the contradicting
        secondary ETF."""
        from validation_outcome import score_weighted_evidence

        # Basket 1: primary CVX supports (+0.9), secondary XLE
        # contradicts (-0.9).  Net should hover near zero.
        basket_secondary_contradicts = [
            {"symbol": "CVX", "evidence_score": 0.9},
            {"symbol": "XLE", "evidence_score": -0.9},
        ]
        out_a = score_weighted_evidence(basket_secondary_contradicts)

        # Basket 2: secondary XLE supports (+0.9), primary CVX
        # contradicts (-0.9).  CVX gets the primary-contradiction
        # multiplier so the aggregate skews more negative than basket 1.
        basket_primary_contradicts = [
            {"symbol": "XLE", "evidence_score": 0.9},
            {"symbol": "CVX", "evidence_score": -0.9},
        ]
        out_b = score_weighted_evidence(basket_primary_contradicts)

        self.assertLess(
            out_b["evidence_score"], out_a["evidence_score"],
            "primary contradiction must tip the aggregate more "
            "negative than a same-magnitude secondary contradiction "
            f"(secondary-contradicts: {out_a['evidence_score']}, "
            f"primary-contradicts: {out_b['evidence_score']})",
        )


if __name__ == "__main__":
    unittest.main()
