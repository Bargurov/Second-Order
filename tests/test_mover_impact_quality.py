"""
tests/test_mover_impact_quality.py

Quality gates on mover impact / conviction.

The conviction layer must respect existing evidence-quality signals
beyond the agreement / persistence pair already wired in:

  * ``weighted_evidence.evidence_label`` — the validation aggregate
    (supportive / mixed / contradictory / insufficient).
  * ``proof_status.status``               — proof-coverage discipline
    (met / partial / unmet / none).
  * ``thesis_state``                      — composite state word
    (confirming / partial / watching / weakening / falsified / stale /
    low_information).

Contract enforced here:

  1. Low-information rows cannot be classified ``high`` impact, no
     matter how big the move.
  2. Mixed / unsupported / contradictory weighted evidence cannot
     become ``high`` impact from move magnitude alone.
  3. The numeric ``impact`` field stays backward-compatible: still a
     float, still equal to ``conviction["conviction_score"]``.
  4. A representative high-impact mover (primary evidence +
     supportive weighted evidence + proof met + viable thesis state +
     durable follow-through + meaningful magnitude) is classifiable.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from movers_ranking import compute_conviction_rank


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _evidence(tier: str = "primary_confirmation",
              reason_code: str = "primary_proxy_confirming") -> dict:
    return {
        "tier":         tier,
        "reason_code":  reason_code,
        "reason_label": reason_code.replace("_", " ").capitalize(),
        "status":       "active",
    }


def _persistence(state: str = "second_leg", status: str = "active") -> dict:
    return {
        "status":   status,
        "label":    status.capitalize(),
        "evidence": "",
        "repricing": {"state": state, "label": state, "evidence": ""},
        "repricing_state": state,
    }


def _weighted(label: str, score: float = 0.6) -> dict:
    return {
        "evidence_label": label,
        "evidence_score": score,
        "scored_tickers": 4,
        "total_tickers":  4,
        "evidence_basis": "evidence_scores",
    }


def _proof(status: str) -> dict:
    return {"status": status, "items": []}


# ---------------------------------------------------------------------------
# 1. Representative high-impact mover
# ---------------------------------------------------------------------------

class TestHighImpactClassifiable(unittest.TestCase):

    def test_primary_supportive_proof_met_confirming_classifies_high(self):
        """A mover with the full evidence stack — primary confirmation,
        supportive weighted evidence, proof met, confirming thesis,
        second-leg follow-through, ~3% move — must classify as high."""
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("supportive", 0.7),
            proof_status=_proof("met"),
            thesis_state="confirming",
        )
        self.assertEqual(r["impact_level"], "high")
        self.assertEqual(r["conviction_class"], "conviction")

    def test_high_impact_score_is_positive_finite_float(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("supportive", 0.7),
            proof_status=_proof("met"),
            thesis_state="confirming",
        )
        self.assertIsInstance(r["conviction_score"], float)
        self.assertGreater(r["conviction_score"], 0.0)


# ---------------------------------------------------------------------------
# 2. Low-information cannot be high — regardless of magnitude
# ---------------------------------------------------------------------------

class TestLowInformationCannotBeHigh(unittest.TestCase):

    def test_huge_move_with_low_information_state_is_not_high(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=10.0,  # exaggerated magnitude
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("supportive", 0.6),
            proof_status=_proof("met"),
            thesis_state="low_information",
        )
        self.assertNotEqual(r["impact_level"], "high")
        self.assertEqual(r["impact_level"], "low")

    def test_low_information_numeric_score_heavily_capped(self):
        capped = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=5.0,
            persistence_signal=_persistence("second_leg"),
            thesis_state="low_information",
        )
        full = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=5.0,
            persistence_signal=_persistence("second_leg"),
            thesis_state="confirming",
        )
        self.assertLess(capped["conviction_score"], full["conviction_score"] * 0.5)


# ---------------------------------------------------------------------------
# 3. Mixed / unsupported evidence cannot be high
# ---------------------------------------------------------------------------

class TestMixedCannotBeHighFromMagnitude(unittest.TestCase):

    def test_huge_move_with_mixed_weighted_evidence_is_not_high(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=12.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("mixed", 0.05),
            proof_status=_proof("met"),
            thesis_state="partial",
        )
        self.assertNotEqual(r["impact_level"], "high")

    def test_huge_move_with_contradictory_weighted_evidence_is_low(self):
        r = compute_conviction_rank(
            _evidence("contradicted", reason_code="direct_miss"),
            max_move=8.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("contradictory", -0.6),
            proof_status=_proof("unmet"),
            thesis_state="weakening",
        )
        self.assertEqual(r["impact_level"], "low")

    def test_huge_move_with_insufficient_weighted_evidence_is_not_high(self):
        r = compute_conviction_rank(
            _evidence("insufficient", reason_code="insufficient_evidence"),
            max_move=10.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("insufficient", 0.0),
            proof_status=_proof("none"),
            thesis_state="watching",
        )
        self.assertNotEqual(r["impact_level"], "high")


# ---------------------------------------------------------------------------
# 4. Falsified / stale thesis state floors conviction
# ---------------------------------------------------------------------------

class TestThesisStateGates(unittest.TestCase):

    def test_falsified_thesis_state_classifies_low(self):
        r = compute_conviction_rank(
            _evidence("contradicted", reason_code="broken"),
            max_move=4.0,
            persistence_signal=_persistence("invalidation"),
            weighted_evidence=_weighted("contradictory", -0.7),
            proof_status=_proof("met"),
            thesis_state="falsified",
        )
        self.assertEqual(r["impact_level"], "low")

    def test_stale_thesis_state_caps_high_classification(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=5.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("supportive", 0.6),
            proof_status=_proof("met"),
            thesis_state="stale",
        )
        self.assertNotEqual(r["impact_level"], "high")

    def test_weakening_thesis_state_not_high(self):
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=4.0,
            persistence_signal=_persistence("second_leg"),
            weighted_evidence=_weighted("supportive", 0.6),
            proof_status=_proof("met"),
            thesis_state="weakening",
        )
        self.assertNotEqual(r["impact_level"], "high")


# ---------------------------------------------------------------------------
# 5. Backward-compatible numeric ``impact`` field
# ---------------------------------------------------------------------------

class TestNumericImpactBackwardCompat(unittest.TestCase):

    def test_legacy_callers_no_quality_kwargs_unchanged(self):
        """Existing callers — ``compute_conviction_rank(evidence, max_move,
        persistence_signal=...)`` with no quality kwargs — must keep
        producing the documented score / class shape."""
        r = compute_conviction_rank(
            _evidence("primary_confirmation"),
            max_move=3.0,
            persistence_signal=_persistence("second_leg"),
        )
        self.assertIn("conviction_score", r)
        self.assertIn("conviction_class", r)
        self.assertEqual(r["conviction_class"], "conviction")
        self.assertIsInstance(r["conviction_score"], float)
        # impact_level still emitted but defaults safely.
        self.assertIn(r["impact_level"], ("low", "medium", "high"))

    def test_impact_field_remains_float(self):
        r = compute_conviction_rank(
            _evidence("mixed"),
            max_move=3.0,
            weighted_evidence=_weighted("mixed", 0.05),
            thesis_state="watching",
        )
        self.assertIsInstance(r["conviction_score"], float)


# ---------------------------------------------------------------------------
# 6. End-to-end wiring through ``_build_mover_summary``
# ---------------------------------------------------------------------------

class TestMoverSummaryQualityWiring(unittest.TestCase):
    """``api._build_mover_summary`` must thread weighted_evidence /
    proof_status / thesis_state into ``compute_conviction_rank`` so the
    surface output carries the categorical gate."""

    def _ev(self, **overrides) -> dict:
        from datetime import datetime, timedelta
        recent = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        base = {
            "id":                 1,
            "headline":           "OPEC cuts output",
            "mechanism_summary":  "tighter supply",
            "mechanism_family":   "supply_shock",
            "event_date":         recent,
            "timestamp":          recent + "T12:00:00",
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["XOM", "CVX"],
            "losers":             [],
            "transmission_path":  [
                {"actor": "XOM", "channel": "equities", "hop": "XOM benefits"},
            ],
            "transmission_chain": [],
            "if_persists":        {},
            "minimum_proof_set":  ["XOM up over 5d"],
            "key_falsifiers":     ["XOM down over 20d"],
            "confidence":         "medium",
            "primary_assets":     ["XOM", "CVX"],
            "stale_signal":       "ok",
            "last_market_check_at": recent + "T12:00:00",
        }
        base.update(overrides)
        return base

    def test_high_impact_mover_classifiable_end_to_end(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.0,
             "return_20d": 5.0,
             "validation_quality": "alpha_support",
             "evidence_score":     0.65,
             "direction_tag":      "supports thesis",
             "spark":              [0.1] * 20, "anchor_date": "2026-04-13"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.5,
             "return_20d": 4.5,
             "validation_quality": "alpha_support",
             "evidence_score":     0.55,
             "direction_tag":      "supports thesis",
             "spark":              [0.1] * 20, "anchor_date": "2026-04-13"},
        ]
        ev = self._ev(persistence_signal={
            "status": "active", "label": "Active", "evidence": "",
            "repricing": {"state": "second_leg", "label": "Second Leg",
                           "evidence": ""},
            "repricing_state": "second_leg",
        }, proof_status={"status": "met", "items": []})
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        # impact field is the conviction_score — a float — preserved.
        self.assertIsInstance(summary["impact"], float)
        self.assertEqual(summary["impact"], summary["conviction"]["conviction_score"])
        # categorical level is wired through.
        self.assertIn("impact_level", summary["conviction"])
        self.assertEqual(summary["conviction"]["impact_level"], "high")

    def test_low_information_event_not_high_end_to_end(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "AAA", "role": "beneficiary", "return_5d": 8.0,
             "return_20d": 9.0,
             "validation_quality": "alpha_support",
             "evidence_score":     0.6,
             "direction_tag":      "supports thesis",
             "spark":              [0.1] * 20, "anchor_date": "2026-04-13"},
        ]
        ev = self._ev(
            mechanism_summary="Insufficient evidence to identify mechanism.",
            confidence="low",
            beneficiaries=[],
            losers=[],
            transmission_path=[],
            primary_assets=[],
            minimum_proof_set=[],
            key_falsifiers=[],
            low_information=True,
            thesis_state="low_information",
        )
        summary = _build_mover_summary(ev, big_moves, support_ratio=0.0)
        self.assertNotEqual(summary["conviction"]["impact_level"], "high")


if __name__ == "__main__":
    unittest.main()
