"""Tests for validation_outcome.score_weighted_evidence.

The fixture table mirrors the "Weighted Event Evidence" section of
EVALUATION.md.  Bumping any pinned threshold without updating both
places should make these tests fail.

All fetches are mocked.  Route wiring is covered by a thin
integration test at the bottom.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api  # noqa: F401  — import-order fix for route circulars

from validation_outcome import (
    EVIDENCE_LABELS,
    _EVT_CONTRADICTORY,
    _EVT_SUPPORTIVE,
    _eligibility_tier,
    _MIN_AGGREGATE_WEIGHT,
    _MIN_SCORABLE_TICKERS,
    _TAG_CONTRIBUTION,
    _tag_sign,
    _W_DIRECTION_TAG,
    _W_EVIDENCE_SCORE,
    score_validation_label,
    score_validation_outcome,
    score_weighted_evidence,
)


# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------

class TestPins(unittest.TestCase):
    def test_labels_pinned(self):
        self.assertEqual(EVIDENCE_LABELS, (
            "supportive", "mixed", "contradictory", "insufficient",
        ))

    def test_band_symmetry(self):
        self.assertEqual(_EVT_SUPPORTIVE, -_EVT_CONTRADICTORY)

    def test_weights_ordered(self):
        # Evidence-score tickers must weigh more than tag-only rows.
        self.assertGreater(_W_EVIDENCE_SCORE, _W_DIRECTION_TAG)

    def test_tag_contribution_matches_band(self):
        # A unanimous tag-only basket must land at the supportive band.
        # ±0.5 contribution × 0.5 weight → aggregate = 0.5 after weight
        # normalisation (per-fixture assertion below).
        self.assertEqual(_TAG_CONTRIBUTION, 0.5)

    def test_min_ticker_floor_pinned(self):
        self.assertEqual(_MIN_SCORABLE_TICKERS, 2)
        self.assertEqual(_MIN_AGGREGATE_WEIGHT, 1.0)


class TestDirectValidationOutcomeCoverage(unittest.TestCase):
    """Direct branch coverage for validation-outcome scoring.

    These tests stay local to validation_outcome.py and avoid live market
    data. They make the validation/result contract explicit without changing
    engine or route behavior.
    """

    def test_eligibility_tier_transitions_with_explicit_primary_set(self):
        explicit = {"CVX"}

        self.assertEqual(
            _eligibility_tier("CVX", explicit_primary=explicit),
            "primary",
        )
        self.assertEqual(
            _eligibility_tier("XOM", explicit_primary=explicit),
            "secondary",
        )
        self.assertEqual(
            _eligibility_tier("XLE", explicit_primary=explicit),
            "secondary",
        )
        self.assertEqual(
            _eligibility_tier("VXX", explicit_primary=explicit),
            "signal",
        )
        self.assertEqual(
            _eligibility_tier("SPY", explicit_primary=explicit),
            "rejected",
        )
        self.assertEqual(
            _eligibility_tier("7203.T", explicit_primary=explicit),
            "rejected",
        )

    def test_direction_tag_enum_branches_drive_majority_outcome(self):
        self.assertEqual(_tag_sign("supports up"), 1)
        self.assertEqual(_tag_sign("supports down"), 1)
        self.assertEqual(_tag_sign("contradicts up"), -1)
        self.assertEqual(_tag_sign("contradicts down"), -1)
        self.assertEqual(_tag_sign("neutral"), 0)

        label, ratio = score_validation_outcome([
            {"direction_tag": "supports up"},
            {"direction_tag": "supports down"},
            {"direction_tag": "contradicts down"},
        ])
        self.assertEqual(label, "validated")
        self.assertAlmostEqual(ratio or 0.0, 2 / 3, places=6)

        label, ratio = score_validation_outcome([
            {"direction_tag": "supports up"},
            {"direction_tag": "contradicts up"},
        ])
        self.assertEqual(label, "contradicted")
        self.assertAlmostEqual(ratio or 0.0, 0.5, places=6)

        self.assertEqual(
            score_validation_outcome([{"direction_tag": "pending"}]),
            ("unresolved", 0.0),
        )
        self.assertEqual(score_validation_outcome([]), ("no_data", None))
        self.assertEqual(score_validation_label([]), "unresolved")

    def test_confidence_ceiling_blocks_single_asset_overstatement(self):
        out = score_weighted_evidence([
            {"symbol": "CVX", "evidence_score": 0.99},
        ])

        self.assertEqual(out["evidence_label"], "insufficient")
        self.assertEqual(out["scored_tickers"], 1)

    def test_confidence_ceiling_blocks_secondary_only_support(self):
        out = score_weighted_evidence([
            {"symbol": "XLE", "evidence_score": 0.95},
            {"symbol": "USO", "evidence_score": 0.95},
        ])

        self.assertGreater(out["evidence_score"], _EVT_SUPPORTIVE)
        self.assertEqual(out["evidence_label"], "mixed")

    def test_rejected_assets_excluded_from_validation_score(self):
        out = score_weighted_evidence([
            {"symbol": "CVX", "evidence_score": 0.65},
            {"symbol": "XOM", "evidence_score": 0.65},
            {"symbol": "SPY", "evidence_score": -0.95},
        ])

        self.assertEqual(out["evidence_label"], "supportive")
        self.assertEqual(out["scored_tickers"], 2)
        self.assertEqual(out["total_tickers"], 3)

    def test_signal_only_assets_have_lower_event_weight(self):
        out = score_weighted_evidence(
            [
                {"symbol": "CVX", "evidence_score": 0.70},
                {"symbol": "XOM", "evidence_score": 0.70},
                {"symbol": "VXX", "evidence_score": -0.95},
                {"symbol": "UUP", "evidence_score": -0.95},
            ],
            explicit_primary={"CVX", "XOM"},
        )

        self.assertEqual(_eligibility_tier("VXX"), "signal")
        self.assertEqual(_eligibility_tier("UUP"), "signal")
        self.assertEqual(out["evidence_label"], "supportive")
        self.assertEqual(out["scored_tickers"], 2)

    def test_explicit_primary_assets_weighted_higher_than_secondaries(self):
        basket = [
            {"symbol": "CVX", "evidence_score": 0.90},
            {"symbol": "XOM", "evidence_score": -0.20},
        ]

        cvx_primary = score_weighted_evidence(
            basket,
            explicit_primary={"CVX"},
        )
        xom_primary = score_weighted_evidence(
            basket,
            explicit_primary={"XOM"},
        )

        self.assertGreater(
            cvx_primary["evidence_score"],
            xom_primary["evidence_score"],
        )


# ---------------------------------------------------------------------------
# Representative fixtures (mirrored in EVALUATION.md)
# ---------------------------------------------------------------------------

class TestFixtureTable(unittest.TestCase):
    def test_all_supportive_evidence(self):
        basket = [
            {"symbol": "A", "evidence_score": 0.85,
             "evidence_label": "supportive",
             "direction_tag": "supports up"},
            {"symbol": "B", "evidence_score": 0.75,
             "evidence_label": "supportive",
             "direction_tag": "supports up"},
            {"symbol": "C", "evidence_score": 0.65,
             "evidence_label": "supportive",
             "direction_tag": "supports up"},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertGreaterEqual(r["evidence_score"], _EVT_SUPPORTIVE)
        self.assertEqual(r["evidence_basis"], "evidence_scores")

    def test_all_contradictory_evidence(self):
        basket = [
            {"symbol": "A", "evidence_score": -0.70,
             "evidence_label": "contradictory"},
            {"symbol": "B", "evidence_score": -0.80,
             "evidence_label": "contradictory"},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "contradictory")
        self.assertLessEqual(r["evidence_score"], _EVT_CONTRADICTORY)

    def test_mixed_evidence(self):
        basket = [
            {"symbol": "A", "evidence_score": 0.8},
            {"symbol": "B", "evidence_score": -0.6},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "mixed")

    def test_majority_support_with_strong_counter_lands_mixed(self):
        """Two weak supporters + one strong contradictor is NOT
        supportive under the weighted rule."""
        basket = [
            {"symbol": "A", "evidence_score": 0.5},
            {"symbol": "B", "evidence_score": 0.5},
            {"symbol": "C", "evidence_score": -0.9},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "mixed")

    def test_tags_only_supports(self):
        basket = [
            {"symbol": "A", "direction_tag": "supports up"},
            {"symbol": "B", "direction_tag": "supports up"},
            {"symbol": "C", "direction_tag": "supports up"},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertEqual(r["evidence_basis"], "tags_only")

    def test_tags_only_mixed(self):
        """A and B are both single-name primary tickers.  Per the
        primary-contradiction asymmetry, B's contradicting tag carries
        the 1.5× multiplier while A's supporting tag stays at base —
        the aggregate tilts slightly negative even with one supporter
        and one contradictor.  Label still resolves to ``mixed`` since
        |score| < _EVT_SUPPORTIVE."""
        basket = [
            {"symbol": "A", "direction_tag": "supports up"},
            {"symbol": "B", "direction_tag": "contradicts down"},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "mixed")
        self.assertLess(r["evidence_score"], 0.0)

    def test_single_ticker_is_insufficient(self):
        r = score_weighted_evidence([{"evidence_score": 0.9}])
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_empty_basket_is_insufficient(self):
        r = score_weighted_evidence([])
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_no_evidence_no_tags_is_insufficient(self):
        r = score_weighted_evidence([
            {"symbol": "A"}, {"symbol": "B"},
        ])
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_thin_evidence_is_mixed_not_insufficient(self):
        # Both tickers scorable but signs cancel — the aggregate sits
        # in the middle band.  Still a verdict because the tickers
        # carry real (if small) horizon evidence.
        basket = [
            {"symbol": "A", "evidence_score": 0.1},
            {"symbol": "B", "evidence_score": -0.1},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "mixed")


# ---------------------------------------------------------------------------
# Weighting + fallback semantics
# ---------------------------------------------------------------------------

class TestWeightingSemantics(unittest.TestCase):
    def test_evidence_score_beats_tag_when_both_present(self):
        """When a ticker has both evidence_score and direction_tag the
        score takes precedence; the tag never dilutes a strong horizon
        read."""
        basket = [
            {"symbol": "A", "evidence_score": 0.9,
             "direction_tag": "contradicts down"},  # tag disagrees
            {"symbol": "B", "evidence_score": 0.9},
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "supportive")

    def test_tag_only_half_weight(self):
        """Mixing evidence-scored + tag-only tickers must not let the
        tag-only rows dominate.  Both A and B are single-name primary
        tickers; B's contradicting tag therefore carries the
        primary-contradiction multiplier (1.5×).

        Aggregate:
            A:  0.9 × 1.0                            = +0.90
            B: -1 × 0.5 × 0.5 × 1.5 (primary penalty) = -0.375
            sum / weight  = 0.525 / 1.5              = 0.35
        """
        basket = [
            {"symbol": "A", "evidence_score": 0.9},       # full weight
            {"symbol": "B", "direction_tag": "contradicts"},  # half weight
        ]
        r = score_weighted_evidence(basket)
        self.assertAlmostEqual(r["evidence_score"], 0.35, places=2)
        self.assertEqual(r["evidence_basis"], "mixed")

    def test_unknown_tag_ignored(self):
        basket = [
            {"symbol": "A", "direction_tag": "unknown"},
            {"symbol": "B", "direction_tag": "supports up"},
        ]
        r = score_weighted_evidence(basket)
        # Only B contributes → 1 scorable, below the 2-ticker floor.
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_non_dict_entries_skipped(self):
        # Tickers without a symbol now collapse to ``rejected`` tier
        # (zero weight) per the tightened primary-weighting rule —
        # missing/empty symbols can no longer default to primary.
        # Provide explicit alpha symbols so the surviving dicts still
        # contribute through the legacy single-name heuristic.
        basket = ["garbage", None, 42,
                  {"symbol": "AAPL", "evidence_score": 0.9},
                  {"symbol": "MSFT", "evidence_score": 0.8}]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertEqual(r["scored_tickers"], 2)


# ---------------------------------------------------------------------------
# Reasons output
# ---------------------------------------------------------------------------

class TestReasons(unittest.TestCase):
    def test_reasons_surface_top_contributors(self):
        basket = [
            {"symbol": "NVDA", "evidence_score": 0.9,
             "evidence_label": "supportive"},
            {"symbol": "AMD",  "evidence_score": 0.4,
             "evidence_label": "mixed"},
            {"symbol": "INTC", "evidence_score": 0.1,
             "evidence_label": "mixed"},
        ]
        r = score_weighted_evidence(basket)
        self.assertTrue(r["evidence_reasons"])
        # The strongest contributor must appear first.
        self.assertIn("NVDA", r["evidence_reasons"][0])

    def test_counter_signal_noted_when_verdict_is_firm(self):
        basket = [
            {"symbol": "A", "evidence_score": 0.9},
            {"symbol": "B", "evidence_score": 0.8},
            {"symbol": "C", "evidence_score": 0.7},
            {"symbol": "D", "evidence_score": -0.4},  # counter
        ]
        r = score_weighted_evidence(basket)
        self.assertEqual(r["evidence_label"], "supportive")
        # "counter:" reason only fires when the counter-signal isn't
        # already in the top-3.  Top 3 by |contrib| are A, B, C
        # (|0.9| > |0.8| > |0.7| > |0.4|).  D should appear as counter.
        self.assertTrue(
            any("counter" in line.lower() for line in r["evidence_reasons"]),
            msg=f"no counter reason in {r['evidence_reasons']!r}",
        )

    def test_reasons_empty_on_insufficient(self):
        r = score_weighted_evidence([])
        self.assertEqual(r["evidence_reasons"], [])


# ---------------------------------------------------------------------------
# Defensive
# ---------------------------------------------------------------------------

class TestDefensive(unittest.TestCase):
    def test_none_input(self):
        r = score_weighted_evidence(None)
        self.assertEqual(r["evidence_label"], "insufficient")
        self.assertEqual(r["total_tickers"], 0)

    def test_non_list_input(self):
        r = score_weighted_evidence({"not": "a list"})
        self.assertEqual(r["evidence_label"], "insufficient")

    def test_nan_evidence_score_falls_back_to_tag(self):
        # Symbols required after the primary-weighting tightening —
        # missing-symbol rows now land in ``rejected`` tier instead of
        # silently inheriting primary weight.
        basket = [
            {"symbol": "AAPL", "evidence_score": float("nan"),
             "direction_tag": "supports up"},
            {"symbol": "MSFT", "direction_tag": "supports up"},
        ]
        r = score_weighted_evidence(basket)
        # NaN treated as missing; both tickers fall through to
        # tag-only path → supportive.
        self.assertEqual(r["evidence_label"], "supportive")
        self.assertEqual(r["evidence_basis"], "tags_only")

    def test_bool_evidence_score_ignored(self):
        basket = [
            {"symbol": "AAPL", "evidence_score": True,
             "direction_tag": "supports up"},
            {"symbol": "MSFT", "evidence_score": False,
             "direction_tag": "supports up"},
        ]
        r = score_weighted_evidence(basket)
        # True/False are not honest floats; fall through to tag path.
        self.assertEqual(r["evidence_basis"], "tags_only")

    def test_score_bounded(self):
        basket = [{"evidence_score": 10.0}, {"evidence_score": 10.0}]
        r = score_weighted_evidence(basket)
        self.assertLessEqual(r["evidence_score"], 1.0)
        self.assertGreaterEqual(r["evidence_score"], -1.0)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------

class TestDeterminism(unittest.TestCase):
    def test_same_input_same_output(self):
        basket = [
            {"symbol": "A", "evidence_score": 0.8},
            {"symbol": "B", "evidence_score": -0.4},
            {"symbol": "C", "direction_tag": "supports up"},
        ]
        r1 = score_weighted_evidence(basket)
        r2 = score_weighted_evidence(basket)
        self.assertEqual(r1, r2)


# ---------------------------------------------------------------------------
# Route wiring — /events row decoration attaches the block
# ---------------------------------------------------------------------------

class TestEventsRouteWiring(unittest.TestCase):
    def test_weighted_evidence_attached_to_decorated_row(self):
        from routes.events import _decorate_row
        row = {
            "id": 1,
            "headline": "sample",
            "event_date": "2026-04-20",
            "timestamp": "2026-04-20T12:00:00",
            "market_tickers": [
                {"symbol": "A", "evidence_score": 0.8,
                 "direction_tag": "supports up"},
                {"symbol": "B", "evidence_score": 0.6,
                 "direction_tag": "supports up"},
            ],
        }
        with patch("routes.events.compute_staleness",
                   return_value={"status": "fresh",
                                 "hours_since_check": 0,
                                 "event_age_days": 1}), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "watching",
                                 "label": "", "evidence": ""}):
            _decorate_row(row)
        self.assertIn("weighted_evidence", row)
        self.assertEqual(row["weighted_evidence"]["evidence_label"],
                         "supportive")
        # The flat validation_status field must remain stable.
        self.assertEqual(row["validation_status"], "validated")


class TestEligibilityTierWeights(unittest.TestCase):
    """Per-tier validation weights:
      * primary single-name → 1.0×
      * secondary ETF       → 0.7×
      * hedge / signal      → 0.0× (dropped from the event aggregator)
      * rejected            → 0.0× (broad market, foreign, etc.)

    The tier weight prevents an off-thesis hedge from tilting the
    basket score and prevents a noisy / off-channel proxy from
    overriding direct primary evidence.
    """

    def test_primary_supports_outweighs_secondary_supports(self):
        """A primary single-name (CVX) supporting at +0.6 contributes
        more than a secondary ETF (XLE) supporting at +0.6.  Both are
        scored, but their per-ticker contributions to the aggregate
        should differ in the primary's favour."""
        basket = [
            {"symbol": "CVX", "evidence_score": 0.6},
            {"symbol": "XLE", "evidence_score": 0.6},
        ]
        out = score_weighted_evidence(basket)
        # Aggregate: CVX (1.0×) 0.6 + XLE (0.7×) 0.42 = 1.02; weight
        # 1.7 → score ~0.6.  Both same scaled contribution sign, so
        # supportive label.
        self.assertEqual(out["evidence_label"], "supportive")
        # Both tickers count, but the primary carries more weight.
        self.assertEqual(out["scored_tickers"], 2)

    def test_signal_asset_drops_from_event_score(self):
        """VXX (vol signal) supplied with a strong evidence_score must
        not contribute at the event level — signal assets validate
        only through their named channel via cross_asset_confirmation."""
        # Two primaries supporting + a vol signal contradicting hard.
        basket = [
            {"symbol": "CVX", "evidence_score":  0.5},
            {"symbol": "XOM", "evidence_score":  0.5},
            {"symbol": "VXX", "evidence_score": -0.9},  # signal — drops
        ]
        out = score_weighted_evidence(basket)
        # Without the signal drop, VXX's -0.9 would tank the basket;
        # with the drop, only the two primaries count and the basket
        # reads supportive.
        self.assertEqual(out["evidence_label"], "supportive")
        self.assertEqual(out["scored_tickers"], 2)   # VXX excluded

    def test_rejected_broad_market_drops_from_event_score(self):
        """SPY (broad-market index) is rejected by the tier classifier
        and contributes nothing at the event level."""
        basket = [
            {"symbol": "CVX", "evidence_score":  0.5},
            {"symbol": "XOM", "evidence_score":  0.5},
            {"symbol": "SPY", "evidence_score": -0.9},  # rejected — drops
        ]
        out = score_weighted_evidence(basket)
        self.assertEqual(out["evidence_label"], "supportive")
        self.assertEqual(out["scored_tickers"], 2)

    def test_primary_direct_overrides_high_noise_secondary_contradict(self):
        """A primary direct supporting at +0.6 must not be flipped by
        a single secondary contradiction at -0.6.  The 0.7× secondary
        weight + the 1.5× primary-contradiction multiplier (which
        does NOT apply to primary supports) keep the aggregate
        positive when direct primary evidence supports."""
        basket = [
            {"symbol": "CVX", "evidence_score":  0.6},   # primary support
            {"symbol": "XLE", "evidence_score": -0.6},   # secondary contradict
        ]
        out = score_weighted_evidence(basket)
        # CVX: +0.6 × 1.0 = +0.60
        # XLE: -0.6 × 0.7 = -0.42 (secondary, no primary multiplier)
        # weight: 1.0 + 0.7 = 1.7
        # score:  0.18 / 1.7 ≈ +0.11
        self.assertGreater(out["evidence_score"], 0.0)

    def test_primary_contradiction_still_dominates_over_secondary_support(self):
        """Mirror: a primary contradicting at -0.6 (gets the 1.5×
        multiplier) must override a secondary supporting at +0.6
        (gets the 0.7× tier weight).  The primary evidence dominates."""
        basket = [
            {"symbol": "CVX", "evidence_score": -0.6},   # primary contradict
            {"symbol": "XLE", "evidence_score":  0.6},   # secondary support
        ]
        out = score_weighted_evidence(basket)
        self.assertLess(out["evidence_score"], 0.0)


class TestBroadBetaDowngrade(unittest.TestCase):
    """A ``supportive`` aggregate built only from secondary ETF
    tape-following must not ship as supportive.  Without a primary
    direct supporter, the read is broad-market beta — downgrade to
    ``mixed`` so consumers can't read a false positive."""

    def test_secondary_only_support_downgrades_to_mixed(self):
        """Two ETFs (XLE, USO) supporting +0.85 each.  No primary
        direct in the basket — label collapses to mixed even though
        the aggregate score clears the supportive band."""
        basket = [
            {"symbol": "XLE", "evidence_score": 0.85},
            {"symbol": "USO", "evidence_score": 0.85},
        ]
        out = score_weighted_evidence(basket)
        # Aggregate would be > +0.5 (well above _EVT_SUPPORTIVE) but
        # the broad-beta filter forces mixed since no primary supports.
        self.assertGreater(out["evidence_score"], 0.35)
        self.assertEqual(out["evidence_label"], "mixed")

    def test_primary_plus_secondary_support_stays_supportive(self):
        """When at least one primary single-name supports, the
        basket can read supportive — the secondary ETF is corroboration,
        not the only source of the read."""
        basket = [
            {"symbol": "CVX", "evidence_score": 0.85},   # primary
            {"symbol": "XLE", "evidence_score": 0.85},   # secondary
        ]
        out = score_weighted_evidence(basket)
        self.assertEqual(out["evidence_label"], "supportive")

    def test_all_etf_basket_cannot_read_supportive(self):
        """Three ETFs all moving in the supportive direction can never
        clear supportive — no thesis-specific read is being made."""
        basket = [
            {"symbol": "SMH", "evidence_score": 0.85},
            {"symbol": "XLE", "evidence_score": 0.85},
            {"symbol": "ITA", "evidence_score": 0.85},
        ]
        out = score_weighted_evidence(basket)
        self.assertEqual(out["evidence_label"], "mixed")

    def test_primary_contradiction_unaffected_by_broad_beta_filter(self):
        """The broad-beta filter only downgrades supportive labels.
        A contradictory aggregate (primary contradicts) keeps its
        label."""
        basket = [
            {"symbol": "CVX", "evidence_score": -0.85},   # primary contradicts
            {"symbol": "XOM", "evidence_score": -0.85},   # primary contradicts
        ]
        out = score_weighted_evidence(basket)
        self.assertEqual(out["evidence_label"], "contradictory")

    def test_tag_only_basket_with_no_primary_support_downgrades(self):
        """Even on tag-only baskets, a supportive aggregate built
        without primary support downgrades to mixed."""
        basket = [
            {"symbol": "XLE", "direction_tag": "supports up"},
            {"symbol": "USO", "direction_tag": "supports up"},
            {"symbol": "ITA", "direction_tag": "supports up"},
        ]
        out = score_weighted_evidence(basket)
        # Aggregate would otherwise read as fully aligned support; the
        # broad-beta filter blocks the supportive label.
        self.assertNotEqual(out["evidence_label"], "supportive")


if __name__ == "__main__":
    unittest.main()
