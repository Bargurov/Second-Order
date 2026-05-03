"""
tests/test_evidence_ladder.py

Contract tests for the 5-rung evidence-ladder layer on top of the
agreement engine.

Covers:
  1. Tier mapping — each agreement-verdict / counter pattern maps to
     the expected ladder rung (primary / secondary / mixed / lagging /
     contradicted / insufficient).
  2. Reason codes — the canonical enum fires on its pattern:
     primary_proxy_confirming, tape_confirming_primary_lagging,
     cascade_lag, split_evidence, bad_primary_basket, direct_miss,
     broken, insufficient_evidence.
  3. Status + persistence overlay — active / partially_active /
     breaking / pending; fading persistence downgrades active →
     partially_active but doesn't gloss over a contradiction.
  4. Narrative — one-line, mentions named bottleneck actors when
     present, tags persistence state.
  5. End-to-end wiring — _build_mover_summary emits the ``evidence``
     block alongside the existing ``agreement_tier`` / ``rank_score``.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from evidence_ladder import (
    EVIDENCE_TIERS,
    REASON_CODES,
    classify_evidence,
)


# ---------------------------------------------------------------------------
# Fixture helpers — mimic an agreement-engine verdict dict
# ---------------------------------------------------------------------------

def _agreement(
    verdict: str = "confirmed",
    *,
    bottleneck_support: int = 0,
    bottleneck_contradict: int = 0,
    direct_support: int = 0,
    direct_contradict: int = 0,
    second_order_support: int = 0,
    second_order_contradict: int = 0,
    bottleneck_symbols: list[str] | None = None,
) -> dict:
    n = (bottleneck_support + bottleneck_contradict
         + direct_support + direct_contradict
         + second_order_support + second_order_contradict)
    return {
        "verdict":                 verdict,
        "n_eligible":              n,
        "bottleneck_support":      bottleneck_support,
        "bottleneck_contradict":   bottleneck_contradict,
        "bottleneck_symbols":      bottleneck_symbols or [],
        "direct_support":          direct_support,
        "direct_contradict":       direct_contradict,
        "second_order_support":    second_order_support,
        "second_order_contradict": second_order_contradict,
    }


def _persistence(status: str) -> dict:
    return {"status": status, "label": status.capitalize(), "evidence": ""}


# ---------------------------------------------------------------------------
# 1. Tier mapping
# ---------------------------------------------------------------------------

class TestTierMapping(unittest.TestCase):

    def test_tiers_are_canonical(self):
        self.assertEqual(
            EVIDENCE_TIERS,
            (
                "primary_confirmation",
                "secondary_confirmation",
                "mixed",
                "lagging",
                "contradicted",
            ),
        )

    def test_confirmed_direct_support_is_primary(self):
        r = classify_evidence(_agreement(
            verdict="confirmed", direct_support=2,
        ))
        self.assertEqual(r["tier"], "primary_confirmation")
        self.assertEqual(r["rung"], 1)

    def test_bottleneck_support_is_primary(self):
        r = classify_evidence(_agreement(
            verdict="confirmed", bottleneck_support=1, direct_support=1,
            bottleneck_symbols=["LRCX"],
        ))
        self.assertEqual(r["tier"], "primary_confirmation")

    def test_second_order_only_is_secondary(self):
        r = classify_evidence(_agreement(
            verdict="second_order_only", second_order_support=2,
        ))
        self.assertEqual(r["tier"], "secondary_confirmation")
        self.assertEqual(r["rung"], 2)

    def test_partial_with_direct_and_tape_is_secondary(self):
        """Direct supporting with tape corroborating = secondary
        confirmation (rather than forcing partial into 'lagging')."""
        r = classify_evidence(_agreement(
            verdict="partial",
            direct_support=1, second_order_support=1,
        ))
        self.assertEqual(r["tier"], "secondary_confirmation")

    def test_partial_with_direct_alone_is_lagging(self):
        r = classify_evidence(_agreement(
            verdict="partial", direct_support=1,
            second_order_support=0, second_order_contradict=0,
        ))
        self.assertEqual(r["tier"], "lagging")
        self.assertEqual(r["rung"], 4)

    def test_mixed_tape_is_mixed(self):
        r = classify_evidence(_agreement(
            verdict="mixed",
            second_order_support=1, second_order_contradict=1,
        ))
        self.assertEqual(r["tier"], "mixed")
        self.assertEqual(r["rung"], 3)

    def test_contradicted_verdict_is_contradicted(self):
        r = classify_evidence(_agreement(
            verdict="contradicted", direct_contradict=2,
        ))
        self.assertEqual(r["tier"], "contradicted")
        self.assertEqual(r["rung"], 5)

    def test_weak_verdict_with_direct_contradict_is_contradicted(self):
        """A weak verdict where direct proxies opposed still lands on
        the contradicted rung — the ladder doesn't pretend it's mixed."""
        r = classify_evidence(_agreement(
            verdict="weak", direct_contradict=1, second_order_support=1,
        ))
        self.assertEqual(r["tier"], "contradicted")

    def test_insufficient_has_no_rung(self):
        r = classify_evidence(_agreement(verdict="insufficient"))
        self.assertEqual(r["tier"], "insufficient")
        self.assertIsNone(r["rung"])

    def test_missing_agreement_is_insufficient(self):
        self.assertEqual(classify_evidence(None)["tier"], "insufficient")
        self.assertEqual(classify_evidence({})["tier"], "insufficient")


# ---------------------------------------------------------------------------
# 2. Reason codes
# ---------------------------------------------------------------------------

class TestReasonCodes(unittest.TestCase):

    def test_reason_codes_are_canonical(self):
        self.assertEqual(
            set(REASON_CODES),
            {
                "primary_proxy_confirming",
                "tape_confirming_primary_lagging",
                "cascade_lag",
                "split_evidence",
                "bad_primary_basket",
                "direct_miss",
                "broken",
                "insufficient_evidence",
            },
        )

    def test_primary_confirmation_emits_primary_proxy_confirming(self):
        r = classify_evidence(_agreement(
            verdict="confirmed", direct_support=2,
        ))
        self.assertEqual(r["reason_code"], "primary_proxy_confirming")

    def test_second_order_only_emits_tape_confirming(self):
        r = classify_evidence(_agreement(
            verdict="second_order_only", second_order_support=2,
        ))
        self.assertEqual(r["reason_code"], "tape_confirming_primary_lagging")

    def test_direct_confirms_tape_silent_emits_cascade_lag(self):
        r = classify_evidence(_agreement(
            verdict="partial", direct_support=1,
        ))
        self.assertEqual(r["reason_code"], "cascade_lag")

    def test_bottleneck_contradict_emits_broken(self):
        """Broken reason code fires when a NAMED bottleneck actor
        opposed — sharper than plain direct_miss."""
        r = classify_evidence(_agreement(
            verdict="contradicted", bottleneck_contradict=1,
            bottleneck_symbols=["LRCX"],
        ))
        self.assertEqual(r["reason_code"], "broken")

    def test_generic_direct_contradict_emits_direct_miss(self):
        r = classify_evidence(_agreement(
            verdict="contradicted", direct_contradict=2,
        ))
        self.assertEqual(r["reason_code"], "direct_miss")

    def test_mixed_tape_emits_split_evidence(self):
        r = classify_evidence(_agreement(
            verdict="mixed",
            second_order_support=1, second_order_contradict=1,
        ))
        self.assertEqual(r["reason_code"], "split_evidence")

    def test_insufficient_emits_insufficient_evidence(self):
        r = classify_evidence({})
        self.assertEqual(r["reason_code"], "insufficient_evidence")


# ---------------------------------------------------------------------------
# 3. Status + persistence overlay
# ---------------------------------------------------------------------------

class TestStatusAndPersistence(unittest.TestCase):

    def test_primary_confirmation_is_active(self):
        r = classify_evidence(_agreement(
            verdict="confirmed", direct_support=2,
        ))
        self.assertEqual(r["status"], "active")

    def test_contradicted_is_breaking(self):
        r = classify_evidence(_agreement(
            verdict="contradicted", direct_contradict=2,
        ))
        self.assertEqual(r["status"], "breaking")

    def test_lagging_is_partially_active(self):
        r = classify_evidence(_agreement(
            verdict="partial", direct_support=1,
        ))
        self.assertEqual(r["status"], "partially_active")

    def test_insufficient_is_pending(self):
        r = classify_evidence({})
        self.assertEqual(r["status"], "pending")

    def test_fading_persistence_downgrades_active(self):
        """An active setup with fading persistence is partially_active —
        don't overstate liveness."""
        r = classify_evidence(
            _agreement(verdict="confirmed", direct_support=2),
            persistence_signal=_persistence("fading"),
        )
        self.assertEqual(r["status"], "partially_active")

    def test_resolved_persistence_demotes_to_pending(self):
        r = classify_evidence(
            _agreement(verdict="partial", direct_support=1),
            persistence_signal=_persistence("resolved"),
        )
        self.assertEqual(r["status"], "pending")

    def test_active_persistence_on_contradicted_stays_breaking(self):
        """Persistence doesn't gloss over a contradiction — a broken
        thesis with 'active' persistence is still breaking."""
        r = classify_evidence(
            _agreement(verdict="contradicted", direct_contradict=2),
            persistence_signal=_persistence("active"),
        )
        self.assertEqual(r["status"], "breaking")


# ---------------------------------------------------------------------------
# 4. Narrative
# ---------------------------------------------------------------------------

class TestNarrative(unittest.TestCase):

    def test_narrative_starts_with_status_head(self):
        r = classify_evidence(_agreement(
            verdict="confirmed", direct_support=2,
        ))
        self.assertTrue(r["narrative"].startswith("Thesis is active"))

    def test_narrative_breaking_for_contradicted(self):
        r = classify_evidence(_agreement(
            verdict="contradicted", direct_contradict=2,
        ))
        self.assertTrue(r["narrative"].startswith("Thesis is breaking"))

    def test_narrative_names_bottleneck_actors_on_primary(self):
        r = classify_evidence(_agreement(
            verdict="confirmed",
            bottleneck_support=2, direct_support=0,
            bottleneck_symbols=["LRCX", "AMAT"],
        ))
        self.assertIn("LRCX", r["narrative"])
        self.assertIn("AMAT", r["narrative"])

    def test_narrative_names_bottleneck_actors_on_contradicted(self):
        r = classify_evidence(_agreement(
            verdict="contradicted",
            bottleneck_contradict=2,
            bottleneck_symbols=["LRCX", "AMAT"],
        ))
        self.assertIn("LRCX", r["narrative"])
        self.assertIn("against", r["narrative"].lower())

    def test_narrative_embeds_persistence_state(self):
        r = classify_evidence(
            _agreement(verdict="confirmed", direct_support=2),
            persistence_signal=_persistence("fading"),
        )
        self.assertIn("fading", r["narrative"].lower())

    def test_narrative_insufficient_is_pending(self):
        r = classify_evidence({})
        self.assertIn("pending", r["narrative"].lower())


# ---------------------------------------------------------------------------
# 5. End-to-end wiring via _build_mover_summary
# ---------------------------------------------------------------------------

class TestMoverSummaryWiring(unittest.TestCase):

    def _ev(self, **overrides) -> dict:
        base = {
            "id":                 7,
            "headline":           "Commerce targets semi fabs",
            "mechanism_summary":  "LRCX revenue exposure hit",
            "mechanism_family":   "sanction",
            "event_date":         "2026-04-19",
            "stage":              "realized",
            "persistence":        "structural",
            "beneficiaries":      ["TSM"],
            "losers":             ["LRCX", "AMAT"],
            "transmission_path":  [
                {"actor": "LRCX", "channel": "equities",
                 "hop":   "LRCX revenue exposure"},
                {"actor": "AMAT", "channel": "equities",
                 "hop":   "AMAT margin compression"},
            ],
            "transmission_chain": [],
            "if_persists":         {},
        }
        base.update(overrides)
        return base

    def test_summary_emits_evidence_block(self):
        from api import _build_mover_summary
        big_moves = [
            {"symbol": "LRCX", "role": "loser", "return_5d": -4.0,
             "validation_quality": "alpha_contradicts",
             "direction_tag": "contradicts thesis", "spark": [0.1] * 20,
             "anchor_date": "2026-04-13"},
            {"symbol": "AMAT", "role": "loser", "return_5d": -3.5,
             "validation_quality": "alpha_contradicts",
             "direction_tag": "contradicts thesis", "spark": [0.1] * 20,
             "anchor_date": "2026-04-13"},
        ]
        summary = _build_mover_summary(self._ev(), big_moves, support_ratio=0.0)
        ev = summary["evidence"]
        self.assertEqual(ev["tier"], "contradicted")
        self.assertEqual(ev["rung"], 5)
        self.assertEqual(ev["reason_code"], "broken")  # bottleneck named
        self.assertEqual(ev["status"], "breaking")
        self.assertIn("LRCX", ev["narrative"])
        self.assertIn("AMAT", ev["narrative"])

    def test_primary_confirmation_wiring(self):
        from api import _build_mover_summary
        ev = self._ev(
            beneficiaries=["XOM"], losers=[],
            transmission_path=[
                {"actor": "XOM", "channel": "equities",
                 "hop": "XOM benefits from crude lift"},
            ],
        )
        big_moves = [
            {"symbol": "XOM", "role": "beneficiary", "return_5d": 3.2,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis", "spark": [0.1] * 20,
             "anchor_date": "2026-04-13"},
            {"symbol": "CVX", "role": "beneficiary", "return_5d": 2.8,
             "validation_quality": "alpha_support",
             "direction_tag": "supports thesis", "spark": [0.1] * 20,
             "anchor_date": "2026-04-13"},
        ]
        summary = _build_mover_summary(ev, big_moves, support_ratio=1.0)
        evd = summary["evidence"]
        self.assertEqual(evd["tier"], "primary_confirmation")
        self.assertEqual(evd["status"], "active")
        self.assertTrue(evd["narrative"].startswith("Thesis is active"))


if __name__ == "__main__":
    unittest.main()
