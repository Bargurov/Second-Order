"""
tests/test_conviction_rank.py

Contract tests for the evidence-quality × persistence-quality
conviction-ranking layer on top of evidence_ladder.

Covers:
  1. Evidence-quality factor — each ladder tier maps to its
     documented quality in [0, 1].
  2. Persistence-quality factor — each repricing_state maps to the
     right signed factor; fallback to ``status`` when the richer
     repricing block is absent.
  3. Conviction class — five buckets (conviction / secondary /
     lagging / noisy_mix / breaking / pending) fire on the right
     evidence × persistence combinations.
  4. Ranking invariants — primary + second_leg beats primary alone;
     primary alone beats lagging; lagging beats noisy_mix; noisy_mix
     beats breaking; invalidation collapses even primary to pending.
  5. Explanation — ``why_ranks_here`` names the specific drivers in
     the right order.
  6. End-to-end wiring — ``_build_mover_summary`` emits the
     conviction block and the ``impact`` field now equals
     ``conviction_score`` (what the surface actually sorts on).
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from movers_ranking import (
    CONVICTION_CLASSES,
    _EVIDENCE_QUALITY,
    _REPRICING_QUALITY,
    compute_conviction_rank,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _evidence(tier: str = "primary_confirmation",
              reason_code: str = "primary_proxy_confirming",
              reason_label: str = "Direct / bottleneck proxies confirming") -> dict:
    return {
        "tier":         tier,
        "rung":         None,  # not used by the conviction layer
        "reason_code":  reason_code,
        "reason_label": reason_label,
        "status":       "active",
    }


def _persistence_repricing(state: str, status: str = "active") -> dict:
    return {
        "status":        status,
        "label":         status.capitalize(),
        "evidence":      "",
        "repricing":     {"state": state, "label": state,
                          "evidence": ""},
        "repricing_state": state,
    }


def _persistence_status(status: str) -> dict:
    """Legacy persistence signal — no repricing block."""
    return {"status": status, "label": status.capitalize(), "evidence": ""}


# ---------------------------------------------------------------------------
# 1. Evidence-quality factor
# ---------------------------------------------------------------------------

class TestEvidenceQualityFactor(unittest.TestCase):

    def test_canonical_quality_ordering(self):
        """primary > secondary > lagging > mixed > contradicted; the
        insufficient sentinel sits between mixed and secondary (honest
        uncertainty isn't a penalty)."""
        self.assertGreater(_EVIDENCE_QUALITY["primary_confirmation"],
                           _EVIDENCE_QUALITY["secondary_confirmation"])
        self.assertGreater(_EVIDENCE_QUALITY["secondary_confirmation"],
                           _EVIDENCE_QUALITY["lagging"])
        self.assertGreater(_EVIDENCE_QUALITY["lagging"],
                           _EVIDENCE_QUALITY["mixed"])
        self.assertGreater(_EVIDENCE_QUALITY["mixed"],
                           _EVIDENCE_QUALITY["contradicted"])

    def test_unknown_tier_falls_back_to_neutral(self):
        r = compute_conviction_rank({"tier": "unknown_tier"}, max_move=3.0)
        # Shouldn't crash; should carry a neutral-ish factor.
        self.assertGreaterEqual(r["evidence_quality"], 0.0)
        self.assertLessEqual(r["evidence_quality"], 1.0)


# ---------------------------------------------------------------------------
# 2. Persistence-quality factor
# ---------------------------------------------------------------------------

class TestPersistenceQualityFactor(unittest.TestCase):

    def test_repricing_state_dominates_when_present(self):
        """The richer repricing state wins over the coarse status."""
        r_positive = compute_conviction_rank(
            _evidence(),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg",
                                                       status="active"),
        )
        r_negative = compute_conviction_rank(
            _evidence(),
            max_move=3.0,
            persistence_signal=_persistence_repricing("invalidation",
                                                       status="active"),
        )
        self.assertGreater(r_positive["persistence_quality"], 0.0)
        self.assertLess(r_negative["persistence_quality"], 0.0)
        self.assertEqual(r_positive["repricing_state"], "second_leg")
        self.assertEqual(r_negative["repricing_state"], "invalidation")

    def test_repricing_state_ordering(self):
        """second_leg > gap_and_hold > grind > watching > retrace >
        fade > invalidation/resolved."""
        self.assertGreater(_REPRICING_QUALITY["second_leg"],
                           _REPRICING_QUALITY["gap_and_hold"])
        self.assertGreater(_REPRICING_QUALITY["gap_and_hold"],
                           _REPRICING_QUALITY["grind"])
        self.assertGreater(_REPRICING_QUALITY["grind"],
                           _REPRICING_QUALITY["watching"])
        self.assertGreater(_REPRICING_QUALITY["watching"],
                           _REPRICING_QUALITY["retrace"])
        self.assertGreater(_REPRICING_QUALITY["retrace"],
                           _REPRICING_QUALITY["fade"])
        self.assertGreater(_REPRICING_QUALITY["fade"],
                           _REPRICING_QUALITY["invalidation"])

    def test_legacy_status_used_when_no_repricing_block(self):
        r = compute_conviction_rank(
            _evidence(),
            max_move=3.0,
            persistence_signal=_persistence_status("fading"),
        )
        # Status-based fallback returns negative persistence_quality.
        self.assertLess(r["persistence_quality"], 0.0)
        self.assertEqual(r["repricing_state"], "fading")

    def test_missing_persistence_is_neutral(self):
        r = compute_conviction_rank(_evidence(), max_move=3.0)
        self.assertEqual(r["persistence_quality"], 0.0)
        self.assertIsNone(r["repricing_state"])


# ---------------------------------------------------------------------------
# 3. Conviction class firing
# ---------------------------------------------------------------------------

class TestConvictionClass(unittest.TestCase):

    def test_primary_plus_second_leg_is_conviction(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        self.assertEqual(r["conviction_class"], "conviction")

    def test_primary_alone_is_secondary_not_conviction(self):
        """Primary without durable follow-through shouldn't claim the
        top conviction label — it sits in secondary."""
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
        )
        self.assertEqual(r["conviction_class"], "secondary")

    def test_secondary_tier_is_secondary(self):
        r = compute_conviction_rank(
            _evidence("secondary_confirmation",
                       reason_code="tape_confirming_primary_lagging"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("gap_and_hold"),
        )
        self.assertEqual(r["conviction_class"], "secondary")

    def test_lagging_tier_is_lagging(self):
        r = compute_conviction_rank(
            _evidence("lagging", reason_code="cascade_lag"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("grind"),
        )
        self.assertEqual(r["conviction_class"], "lagging")

    def test_mixed_is_noisy_mix(self):
        r = compute_conviction_rank(
            _evidence("mixed", reason_code="split_evidence"),
            max_move=3.0,
        )
        self.assertEqual(r["conviction_class"], "noisy_mix")

    def test_contradicted_is_breaking(self):
        r = compute_conviction_rank(
            _evidence("contradicted", reason_code="direct_miss"),
            max_move=3.0,
        )
        self.assertEqual(r["conviction_class"], "breaking")

    def test_insufficient_is_pending(self):
        r = compute_conviction_rank(
            _evidence("insufficient", reason_code="insufficient_evidence"),
            max_move=3.0,
        )
        self.assertEqual(r["conviction_class"], "pending")

    def test_invalidation_repricing_collapses_primary(self):
        """Even a primary-confirmation card with an invalidation repricing
        collapses out of the conviction bucket — don't overstate live
        setups once the follow-through has broken."""
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("invalidation"),
        )
        self.assertNotEqual(r["conviction_class"], "conviction")

    def test_classes_are_canonical(self):
        self.assertEqual(
            CONVICTION_CLASSES,
            ("conviction", "secondary", "lagging", "noisy_mix",
             "breaking", "pending"),
        )


# ---------------------------------------------------------------------------
# 4. Ranking invariants — the conviction_score ordering matters
# ---------------------------------------------------------------------------

class TestRankingInvariants(unittest.TestCase):

    def test_primary_plus_second_leg_beats_primary_alone(self):
        top = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        alone = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
        )
        self.assertGreater(top["conviction_score"], alone["conviction_score"])

    def test_primary_alone_beats_lagging_at_equal_magnitude(self):
        primary = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
        )
        lagging = compute_conviction_rank(
            _evidence("lagging", reason_code="cascade_lag"),
            max_move=3.0,
        )
        self.assertGreater(primary["conviction_score"], lagging["conviction_score"])

    def test_lagging_beats_noisy_mix_at_equal_magnitude(self):
        lagging = compute_conviction_rank(
            _evidence("lagging", reason_code="cascade_lag"),
            max_move=3.0,
        )
        mixed = compute_conviction_rank(
            _evidence("mixed", reason_code="split_evidence"),
            max_move=3.0,
        )
        self.assertGreater(lagging["conviction_score"], mixed["conviction_score"])

    def test_noisy_mix_beats_breaking_at_equal_magnitude(self):
        mixed = compute_conviction_rank(
            _evidence("mixed"),
            max_move=3.0,
        )
        breaking = compute_conviction_rank(
            _evidence("contradicted", reason_code="direct_miss"),
            max_move=3.0,
        )
        self.assertGreater(mixed["conviction_score"], breaking["conviction_score"])

    def test_smaller_primary_plus_second_leg_beats_bigger_noisy_mix(self):
        """A clean 2% primary with second-leg repricing should outrank
        a 4% noisy mixed case — the whole point of the upgrade."""
        clean_small = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=2.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        noisy_big = compute_conviction_rank(
            _evidence("mixed"),
            max_move=4.0,
        )
        self.assertGreater(clean_small["conviction_score"],
                           noisy_big["conviction_score"])

    def test_conviction_score_clamps_at_zero(self):
        """Even a deep negative persistence can't take the score below zero."""
        r = compute_conviction_rank(
            _evidence("contradicted"),
            max_move=5.0,
            persistence_signal=_persistence_repricing("invalidation"),
        )
        self.assertGreaterEqual(r["conviction_score"], 0.0)


# ---------------------------------------------------------------------------
# 5. why_ranks_here explanation
# ---------------------------------------------------------------------------

class TestWhyRanksHere(unittest.TestCase):

    def test_primary_explanation_leads_with_primary_label(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        self.assertIn("Primary confirmation", r["why_ranks_here"][0])

    def test_second_leg_tag_appears_when_repricing_is_second_leg(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        joined = " | ".join(r["why_ranks_here"])
        self.assertIn("Second-leg", joined)

    def test_fading_tag_appears_when_repricing_is_fade(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("fade"),
        )
        joined = " | ".join(r["why_ranks_here"])
        self.assertIn("fading", joined.lower())

    def test_lagging_class_includes_reason_label(self):
        r = compute_conviction_rank(
            _evidence("lagging", reason_code="cascade_lag",
                       reason_label="Direct proxies confirming; tape cascade hasn't arrived"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("grind"),
        )
        joined = " | ".join(r["why_ranks_here"])
        self.assertIn("cascade", joined.lower())

    def test_rationale_includes_math(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence_repricing("second_leg"),
        )
        self.assertIn("primary_confirmation", r["rationale"])
        self.assertIn("second_leg", r["rationale"])


# ---------------------------------------------------------------------------
# 6. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def _ev(self, **overrides) -> dict:
        base = {
            "id":                 1,
            "headline":           "OPEC cuts output",
            "mechanism_summary":  "tighter supply",
            "mechanism_family":   "supply_shock",
            "event_date":         "2026-04-19",
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["XOM"],
            "losers":             [],
            "transmission_path":  [
                {"actor": "XOM", "channel": "equities", "hop": "XOM benefits"},
            ],
            "transmission_chain": [],
            "if_persists":         {},
        }
        base.update(overrides)
        return base

    def test_summary_emits_conviction_block(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0,
             "return_20d": 5.0,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.5,
             "return_20d": 4.5,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis",
             "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
        ]
        ev = self._ev(persistence_signal={
            "status": "active", "label": "Active", "evidence": "",
            "repricing": {"state": "second_leg", "label": "Second Leg",
                           "evidence": ""},
            "repricing_state": "second_leg",
        })
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        self.assertIn("conviction", summary)
        self.assertEqual(summary["conviction"]["conviction_class"], "conviction")
        # ``impact`` now reflects conviction score — the surface sort
        # key changes without touching the movers_cache callsites.
        self.assertEqual(summary["impact"], summary["conviction"]["conviction_score"])

    def test_primary_plus_second_leg_outranks_bigger_mixed(self):
        from api import _build_mover_summary

        clean_small = _build_mover_summary(
            self._ev(id=1, persistence_signal={
                "status": "active",
                "repricing": {"state": "second_leg"},
                "repricing_state": "second_leg",
            }),
            [
                {"symbol": "XOM", "role": "beneficiary", "return_5d": 2.0,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis",
                 "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
                {"symbol": "CVX", "role": "beneficiary", "return_5d": 1.9,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis",
                 "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
            ],
            support_ratio=1.0,
        )
        noisy_big = _build_mover_summary(
            self._ev(id=2),
            [
                {"symbol": "XOM", "role": "beneficiary", "return_5d": 4.0,
                 "validation_quality": "alpha_support",
                 "direction_tag": "supports thesis",
                 "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
                {"symbol": "BP", "role": "beneficiary", "return_5d": -4.0,
                 "validation_quality": "alpha_contradicts",
                 "direction_tag": "contradicts thesis",
                 "spark": [0.1] * 20, "anchor_date": "2026-04-13"},
            ],
            support_ratio=0.5,
        )
        self.assertGreater(clean_small["impact"], noisy_big["impact"])


if __name__ == "__main__":
    unittest.main()
