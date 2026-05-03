"""
tests/test_movers_ranking.py

Contract tests for the tier-aware mover ranking + explanation composer.

Covers:
  1. ``classify_tier`` — every agreement verdict maps to a user-facing
     tier; unknown verdicts degrade to "mixed"; missing input stays
     "insufficient".
  2. ``compute_rank_score`` — strong confirmation on a smaller move
     can out-rank a contradicted tier on a bigger move.  Mixed /
     partial tiers stay in the middle band (not collapsed to 0).
  3. Persistence overlay — active setups bonus, fading setups penalty.
  4. ``build_why_still_moving`` — headline names the top ticker,
     reason_lines include the agreement reason + persistence evidence
     + proxy split, watch_signals reflect the tier.
  5. ``_build_mover_summary`` end-to-end wiring — emits the tier,
     rank_score, and why_still_moving fields; impact now reflects the
     tier-aware score so sort-by-impact surfaces the right rows first.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from movers_ranking import (
    TIER_ORDER,
    build_why_still_moving,
    classify_tier,
    compute_rank_score,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _verdict(
    verdict: str = "confirmed",
    *,
    direct_support: int = 2,
    direct_contradict: int = 0,
    second_order_support: int = 0,
    second_order_contradict: int = 0,
    reason: str = "test",
) -> dict:
    return {
        "verdict":  verdict,
        "weighted_score": 0.7,
        "n_eligible": direct_support + direct_contradict
                       + second_order_support + second_order_contradict,
        "direct_support":          direct_support,
        "direct_contradict":       direct_contradict,
        "second_order_support":    second_order_support,
        "second_order_contradict": second_order_contradict,
        "reason":                  reason,
    }


def _ticker(symbol: str, return_5d: float) -> dict:
    return {"symbol": symbol, "return_5d": return_5d, "role": "beneficiary"}


def _persistence(status: str, evidence: str = "") -> dict:
    return {
        "status":   status,
        "label":    status.capitalize(),
        "evidence": evidence,
    }


# ---------------------------------------------------------------------------
# 1. Tier classification
# ---------------------------------------------------------------------------

class TestClassifyTier(unittest.TestCase):

    def test_canonical_verdict_map(self):
        cases = {
            "confirmed":         "strong_confirmation",
            "partial":           "partial_confirmation",
            "second_order_only": "tape_confirmation",
            "mixed":             "mixed",
            "weak":              "weak_lean",
            "direct_miss":       "weak_lean",
            "contradicted":      "contradicted",
            "insufficient":      "insufficient",
        }
        for verdict, tier in cases.items():
            self.assertEqual(
                classify_tier(_verdict(verdict)), tier,
                f"{verdict} should map to {tier}",
            )

    def test_unknown_verdict_maps_to_mixed(self):
        """Future agreement-engine verdicts shouldn't crash the surface."""
        self.assertEqual(classify_tier({"verdict": "not_a_real_one"}), "mixed")

    def test_missing_agreement_is_insufficient(self):
        self.assertEqual(classify_tier(None), "insufficient")
        self.assertEqual(classify_tier({}), "insufficient")

    def test_tier_order_is_canonical(self):
        self.assertEqual(
            TIER_ORDER,
            (
                "strong_confirmation", "partial_confirmation",
                "tape_confirmation", "mixed", "weak_lean",
                "contradicted", "insufficient",
            ),
        )


# ---------------------------------------------------------------------------
# 2. Rank score
# ---------------------------------------------------------------------------

class TestComputeRankScore(unittest.TestCase):

    def test_strong_confirmation_preserves_magnitude(self):
        """Confirmed tier = weight 1.0 → score equals magnitude."""
        r = compute_rank_score(_verdict("confirmed"), max_move=3.0)
        self.assertAlmostEqual(r["rank_score"], 3.0, places=2)
        self.assertEqual(r["tier"], "strong_confirmation")

    def test_contradicted_floors_at_ten_percent_of_magnitude(self):
        r = compute_rank_score(_verdict("contradicted"), max_move=3.0)
        self.assertAlmostEqual(r["rank_score"], 0.3, places=2)
        self.assertEqual(r["tier"], "contradicted")

    def test_strong_small_move_outranks_contradicted_big_move(self):
        """The point of the tier system: a clean 2% alpha beats a
        contradicted 5% print on the Still Moving Markets surface."""
        strong_small = compute_rank_score(
            _verdict("confirmed"), max_move=2.0,
        )
        contradicted_big = compute_rank_score(
            _verdict("contradicted"), max_move=5.0,
        )
        self.assertGreater(strong_small["rank_score"], contradicted_big["rank_score"])

    def test_mixed_and_partial_stay_in_middle_band(self):
        """Preserve mixed / partial states instead of flat-lining."""
        mixed = compute_rank_score(_verdict("mixed"), max_move=3.0)
        partial = compute_rank_score(_verdict("partial"), max_move=3.0)
        strong = compute_rank_score(_verdict("confirmed"), max_move=3.0)
        contradicted = compute_rank_score(_verdict("contradicted"), max_move=3.0)
        # Mid-band: above contradicted, below strong.
        for r in (mixed, partial):
            self.assertGreater(r["rank_score"], contradicted["rank_score"])
            self.assertLess(r["rank_score"], strong["rank_score"])
        # Partial is still above mixed — user shouldn't see them collapsed.
        self.assertGreater(partial["rank_score"], mixed["rank_score"])

    def test_tape_confirmation_ranks_between_partial_and_mixed(self):
        tape = compute_rank_score(_verdict("second_order_only"), max_move=3.0)
        partial = compute_rank_score(_verdict("partial"), max_move=3.0)
        mixed = compute_rank_score(_verdict("mixed"), max_move=3.0)
        self.assertLess(tape["rank_score"], partial["rank_score"])
        self.assertGreater(tape["rank_score"], mixed["rank_score"])

    def test_insufficient_not_flatlined_to_zero(self):
        """Honest uncertainty isn't a penalty — insufficient sits
        between weak_lean and mixed, not at zero."""
        r = compute_rank_score(_verdict("insufficient"), max_move=3.0)
        self.assertGreater(r["rank_score"], 0.0)

    def test_zero_magnitude_is_zero_score(self):
        r = compute_rank_score(_verdict("confirmed"), max_move=0.0)
        self.assertEqual(r["rank_score"], 0.0)

    def test_negative_move_is_clamped_to_zero_magnitude(self):
        """``max_move`` is an absolute magnitude; negatives shouldn't
        flip to negative scores."""
        r = compute_rank_score(_verdict("confirmed"), max_move=-3.0)
        self.assertGreaterEqual(r["rank_score"], 0.0)


# ---------------------------------------------------------------------------
# 3. Persistence overlay
# ---------------------------------------------------------------------------

class TestPersistenceOverlay(unittest.TestCase):

    def test_active_setup_gets_bonus(self):
        base = compute_rank_score(_verdict("confirmed"), max_move=3.0)
        active = compute_rank_score(
            _verdict("confirmed"), max_move=3.0,
            persistence_signal=_persistence("active", "XOM new high on volume"),
        )
        self.assertGreater(active["rank_score"], base["rank_score"])

    def test_fading_setup_takes_penalty(self):
        base = compute_rank_score(_verdict("confirmed"), max_move=3.0)
        fading = compute_rank_score(
            _verdict("confirmed"), max_move=3.0,
            persistence_signal=_persistence("fading", "5d alpha has rolled over"),
        )
        self.assertLess(fading["rank_score"], base["rank_score"])

    def test_resolved_setup_takes_bigger_penalty(self):
        fading = compute_rank_score(
            _verdict("confirmed"), max_move=3.0,
            persistence_signal=_persistence("fading"),
        )
        resolved = compute_rank_score(
            _verdict("confirmed"), max_move=3.0,
            persistence_signal=_persistence("resolved"),
        )
        self.assertLess(resolved["rank_score"], fading["rank_score"])

    def test_watching_status_is_no_op(self):
        base = compute_rank_score(_verdict("confirmed"), max_move=3.0)
        watching = compute_rank_score(
            _verdict("confirmed"), max_move=3.0,
            persistence_signal=_persistence("watching"),
        )
        self.assertAlmostEqual(
            base["rank_score"], watching["rank_score"], places=3,
        )


# ---------------------------------------------------------------------------
# 4. "Why still moving" explanation
# ---------------------------------------------------------------------------

class TestWhyStillMoving(unittest.TestCase):

    def test_headline_names_top_ticker_and_tier(self):
        why = build_why_still_moving(
            {"headline": "OPEC cut"},
            _verdict("confirmed"),
            [_ticker("XOM", 3.5), _ticker("CVX", 2.1)],
        )
        self.assertIn("XOM", why["headline"])
        self.assertIn("+3.5", why["headline"])
        self.assertIn("Strong", why["headline"])
        self.assertEqual(why["tier"], "strong_confirmation")

    def test_reason_lines_include_agreement_reason(self):
        why = build_why_still_moving(
            {"headline": "OPEC cut"},
            _verdict("partial", reason="XOM supports but SPY beta pushback"),
            [_ticker("XOM", 3.5)],
        )
        # At least one reason line quotes the agreement reason.
        joined = " | ".join(why["reason_lines"])
        self.assertIn("XOM supports", joined)

    def test_reason_lines_include_persistence_evidence(self):
        why = build_why_still_moving(
            {"headline": "Fed hike"},
            _verdict("confirmed"),
            [_ticker("TLT", -2.0)],
            persistence_signal=_persistence(
                "active", "Rates continuing to price the hike 20d later",
            ),
        )
        joined = " | ".join(why["reason_lines"])
        self.assertIn("Persistence", joined)
        self.assertIn("Rates continuing", joined)

    def test_reason_lines_include_proxy_split(self):
        why = build_why_still_moving(
            {"headline": "h"},
            _verdict("partial", direct_support=1, second_order_contradict=2),
            [_ticker("XOM", 2.0)],
        )
        joined = " | ".join(why["reason_lines"])
        # "1/0 direct, 0/2 tape"
        self.assertIn("Proxy split", joined)
        self.assertIn("1/0", joined)
        self.assertIn("0/2", joined)

    def test_watch_signals_match_tier(self):
        partial = build_why_still_moving(
            {}, _verdict("partial"), [_ticker("XOM", 2.0)],
        )
        contradicted = build_why_still_moving(
            {}, _verdict("contradicted"), [_ticker("XOM", 2.0)],
        )
        mixed = build_why_still_moving(
            {}, _verdict("mixed"), [_ticker("XOM", 2.0)],
        )
        self.assertTrue(any("partial" in s.lower() or "strong" in s.lower()
                            for s in partial["watch_signals"]))
        self.assertTrue(any("broken" in s.lower() or "concede" in s.lower()
                            for s in contradicted["watch_signals"]))
        self.assertTrue(any("direct-proxy" in s.lower() or "resolve" in s.lower()
                            for s in mixed["watch_signals"]))

    def test_missing_big_moves_degrades_cleanly(self):
        why = build_why_still_moving({}, _verdict("mixed"), None)
        self.assertIn("tier", why)
        self.assertIsInstance(why["reason_lines"], list)

    def test_fading_persistence_adds_watch_signal(self):
        why = build_why_still_moving(
            {}, _verdict("confirmed"), [_ticker("XOM", 3.0)],
            persistence_signal=_persistence("fading"),
        )
        self.assertTrue(any("fading" in s.lower() for s in why["watch_signals"]))


# ---------------------------------------------------------------------------
# 5. End-to-end wiring into _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryIntegration(unittest.TestCase):

    def _ev(self, **overrides) -> dict:
        base = {
            "id": 42,
            "headline": "OPEC cuts output",
            "mechanism_summary": "tighter supply → crude up",
            "mechanism_family": "supply_shock",
            "event_date": "2026-04-19",
            "stage": "realized",
            "persistence": "structural",
            "transmission_chain": [],
            "if_persists": {},
        }
        base.update(overrides)
        return base

    def test_summary_emits_tier_and_rank_fields(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary",
             "return_5d": 3.0, "return_20d": 6.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20},
            {"symbol": "CVX", "role": "beneficiary",
             "return_5d": 2.5, "return_20d": 5.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20},
        ]
        summary = _build_mover_summary(self._ev(), big_moves, support_ratio=1.0)
        self.assertEqual(summary["agreement_tier"], "strong_confirmation")
        self.assertEqual(summary["agreement_tier_label"], "Strong confirmation")
        self.assertIn("rank_score", summary)
        self.assertIn("why_still_moving", summary)
        self.assertIn("headline", summary["why_still_moving"])
        # Impact is now the conviction_score (evidence × persistence ×
        # thesis_state quality gates) — see test_conviction_rank for the
        # canonical contract.  rank_score is still emitted for backward
        # compatibility but no longer drives the ``impact`` field.
        self.assertEqual(summary["impact"], summary["conviction"]["conviction_score"])

    def test_strong_small_outranks_contradicted_big(self):
        """The whole point — a clean 2% alpha beats a contradicted 5%
        on the impact field the surface sorts on."""
        from api import _build_mover_summary

        strong_small = _build_mover_summary(
            self._ev(id=1),
            [
                {"symbol": "XOM", "role": "beneficiary", "return_5d": 2.0,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis", "spark": [0.1] * 20},
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 1.9,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis", "spark": [0.1] * 20},
            ],
            support_ratio=1.0,
        )
        contradicted_big = _build_mover_summary(
            self._ev(id=2),
            [
                {"symbol": "XOM", "role": "beneficiary", "return_5d": -5.0,
                 "validation_quality": "alpha_contradicts",
                 "direction_tag": "contradicts thesis", "spark": [0.1] * 20},
                {"symbol": "CVX", "role": "beneficiary", "return_5d": -4.5,
                 "validation_quality": "alpha_contradicts",
                 "direction_tag": "contradicts thesis", "spark": [0.1] * 20},
            ],
            support_ratio=0.0,
        )
        self.assertGreater(strong_small["impact"], contradicted_big["impact"])

    def test_mixed_tier_preserved_not_flatlined(self):
        from api import _build_mover_summary
        summary = _build_mover_summary(
            self._ev(),
            [
                {"symbol": "XOM", "role": "beneficiary", "return_5d": 2.0,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis", "spark": [0.1] * 20},
                {"symbol": "BP", "role": "beneficiary", "return_5d": -2.0,
                 "validation_quality": "alpha_contradicts",
                 "direction_tag": "contradicts thesis", "spark": [0.1] * 20},
            ],
            support_ratio=0.5,
        )
        self.assertEqual(summary["agreement_tier"], "mixed")
        # Mixed preserves SOME impact — not collapsed to 0.
        self.assertGreater(summary["impact"], 0.0)


if __name__ == "__main__":
    unittest.main()
