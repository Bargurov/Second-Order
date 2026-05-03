"""Focused tests for proof-discipline flags + ranking side-effects.

Covers only the new behaviour:
  * ``portfolio_flags`` — classification rules.
  * Ranking lift when an event is proof-backed.
  * Stale low-info vs fresh proof-backed ordering.
  * ``/events`` + ``/portfolio`` wiring surfaces the flags.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api  # noqa: F401  — resolve circular imports between routes
from portfolio_flags import portfolio_flags
from relevance_ranking import (
    _LOW_INFO_PENALTY,
    _PROOF_DISCIPLINE_BONUS,
    _STALENESS_PENALTY,
    compute_relevance_score,
    rank_with_diversity,
)


_NOW = datetime(2026, 4, 20, 12, 0, 0)


def _ticker(symbol: str, *, return_5d: float = 2.0,
            direction_tag: str = "supports thesis") -> dict:
    return {
        "symbol":        symbol,
        "return_5d":     return_5d,
        "direction_tag": direction_tag,
    }


def _base_event(event_id: int = 1, **overrides) -> dict:
    ev = {
        "id":                  event_id,
        "headline":            f"Event {event_id}",
        "event_date":          "2026-04-18",
        "timestamp":           "2026-04-18T09:00:00",
        "stage":               "realized",
        "persistence":         "medium",
        "confidence":          "medium",
        "rating":              "mixed",
        "mechanism_family":    "commodity_squeeze",
        "mechanism_summary":   "Refinery outage tightens Gulf Coast capacity.",
        "market_tickers":      [_ticker("USO"), _ticker("XLE")],
        "revisit_snapshots":   [],
        "low_signal":          False,
        "minimum_proof_set":   [],
        "key_falsifiers":      [],
        "critical_breakpoints": [],
    }
    ev.update(overrides)
    return ev


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestFlagClassification(unittest.TestCase):
    def test_none_safe(self):
        self.assertEqual(
            portfolio_flags(None),
            {"has_proof_set": False, "has_falsifiers": False,
             "low_information": False},
        )

    def test_non_dict_safe(self):
        self.assertEqual(
            portfolio_flags("garbage"),
            {"has_proof_set": False, "has_falsifiers": False,
             "low_information": False},
        )

    def test_proof_set_detected(self):
        ev = _base_event(
            minimum_proof_set=[
                {"observation": "WCS-WTI spread widens ≥2pp",
                 "channel": "commodities", "timing": "1-5d"},
            ],
        )
        self.assertTrue(portfolio_flags(ev)["has_proof_set"])

    def test_empty_proof_set_not_detected(self):
        self.assertFalse(portfolio_flags(_base_event())["has_proof_set"])

    def test_falsifiers_from_key_falsifiers(self):
        ev = _base_event(
            key_falsifiers=[
                {"observation": "USO drops >3% intraday",
                 "channel": "commodities"},
            ],
        )
        self.assertTrue(portfolio_flags(ev)["has_falsifiers"])

    def test_falsifiers_from_critical_breakpoints(self):
        ev = _base_event(
            critical_breakpoints=[
                {"observation": "OPEC reverses cut", "timing": "1-5d"},
            ],
        )
        self.assertTrue(portfolio_flags(ev)["has_falsifiers"])

    def test_low_information_low_conf_plus_marker(self):
        ev = _base_event(
            confidence="low",
            mechanism_summary="Insufficient evidence to characterise.",
        )
        self.assertTrue(portfolio_flags(ev)["low_information"])

    def test_low_information_low_conf_empty_mechanism(self):
        ev = _base_event(confidence="low", mechanism_summary="")
        self.assertTrue(portfolio_flags(ev)["low_information"])

    def test_low_information_requires_low_confidence(self):
        ev = _base_event(
            confidence="high",
            mechanism_summary="Insufficient evidence.",
        )
        self.assertFalse(portfolio_flags(ev)["low_information"])

    def test_low_information_requires_marker_when_mechanism_present(self):
        ev = _base_event(
            confidence="low",
            mechanism_summary="Refinery outage tightens Gulf Coast capacity.",
        )
        self.assertFalse(portfolio_flags(ev)["low_information"])


# ---------------------------------------------------------------------------
# Ranking side-effects
# ---------------------------------------------------------------------------

class TestRankingAdjustments(unittest.TestCase):
    def test_proof_backed_lifts_overall_score(self):
        bare = _base_event(event_id=1)
        proof = _base_event(
            event_id=2,
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        bare_score  = compute_relevance_score(bare,  now=_NOW)["overall_score"]
        proof_score = compute_relevance_score(proof, now=_NOW)["overall_score"]
        self.assertGreater(proof_score, bare_score)

    def test_only_proof_set_alone_no_bonus(self):
        """Lift requires BOTH proof set and falsifiers, per task."""
        bare = _base_event(event_id=1)
        partial = _base_event(
            event_id=2,
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        )
        bare_score    = compute_relevance_score(bare,    now=_NOW)["overall_score"]
        partial_score = compute_relevance_score(partial, now=_NOW)["overall_score"]
        self.assertAlmostEqual(bare_score, partial_score, places=4)

    def test_low_information_penalised(self):
        clean = _base_event(event_id=1)
        low_info = _base_event(
            event_id=2,
            confidence="low",
            mechanism_summary="Insufficient evidence.",
        )
        clean_score    = compute_relevance_score(clean,    now=_NOW)["overall_score"]
        low_info_score = compute_relevance_score(low_info, now=_NOW)["overall_score"]
        self.assertGreater(clean_score, low_info_score)

    def test_stale_low_info_ranks_below_fresh_proof_backed(self):
        stale_low = _base_event(
            event_id=1,
            confidence="low",
            mechanism_summary="Insufficient evidence.",
            last_market_check_at=(datetime.now() - timedelta(days=80)).isoformat(timespec="seconds"),
        )
        fresh_proof = _base_event(
            event_id=2,
            last_market_check_at=(datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        ranked = rank_with_diversity(
            [stale_low, fresh_proof], limit=2, now=_NOW,
        )
        self.assertEqual(ranked[0]["event"]["id"], 2)
        self.assertEqual(ranked[1]["event"]["id"], 1)

    def test_proof_bonus_compounds_with_staleness_penalty(self):
        stale_proof = _base_event(
            event_id=1,
            last_market_check_at=(datetime.now() - timedelta(days=80)).isoformat(timespec="seconds"),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        fresh_plain = _base_event(
            event_id=2,
            last_market_check_at=(datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"),
        )
        # Stale × proof_bonus = 0.80 × 1.08 = 0.864
        # Fresh plain       = 1.00
        # Fresh plain still wins despite no proof bonus.
        ranked = rank_with_diversity(
            [stale_proof, fresh_plain], limit=2, now=_NOW,
        )
        self.assertEqual(ranked[0]["event"]["id"], 2)

    def test_low_info_penalty_deepens_stale_gap(self):
        """Stale AND low-info should compound both penalties."""
        double_penalty = _base_event(
            event_id=1,
            confidence="low",
            mechanism_summary="Insufficient evidence.",
            last_market_check_at=(datetime.now() - timedelta(days=80)).isoformat(timespec="seconds"),
        )
        just_stale = _base_event(
            event_id=2,
            last_market_check_at=(datetime.now() - timedelta(days=80)).isoformat(timespec="seconds"),
        )
        double_score = compute_relevance_score(
            double_penalty, now=_NOW,
        )["overall_score"]
        stale_score = compute_relevance_score(
            just_stale, now=_NOW,
        )["overall_score"]
        # Both carry the staleness penalty; only the first also gets the
        # low-info penalty → it must score strictly lower.
        self.assertLess(double_score, stale_score)

    def test_constants_pinned(self):
        # Bonus and penalty magnitudes are pinned so the fixture table
        # below stays meaningful across refactors.
        self.assertAlmostEqual(_PROOF_DISCIPLINE_BONUS, 1.08, places=6)
        self.assertAlmostEqual(_LOW_INFO_PENALTY,       0.75, places=6)
        self.assertAlmostEqual(_STALENESS_PENALTY,      0.80, places=6)


# ---------------------------------------------------------------------------
# Broad-topic preservation — duplicate oil cluster with proof bonus
# doesn't sweep the top when a novel non-proof event is competitive.
# ---------------------------------------------------------------------------

class TestBroadTopicPreservation(unittest.TestCase):
    def test_proof_bonus_does_not_override_cluster_decay(self):
        """Five proof-backed oils all sharing a transmission signature
        still can't own the whole top because cluster decay applies."""
        duplicates = []
        for i in range(5):
            ev = _base_event(
                event_id=i + 1,
                minimum_proof_set=[
                    {"observation": "spread widens", "channel": "commodities"},
                ],
                key_falsifiers=[
                    {"observation": "spread collapses", "channel": "commodities"},
                ],
            )
            ev["transmission_path"] = [
                {"hop": "step1", "channel": "supply",        "actor": "x"},
                {"hop": "step2", "channel": "pricing_power", "actor": "y"},
            ]
            duplicates.append(ev)
        novel = _base_event(
            event_id=100,
            mechanism_family="bank_stress",
            market_tickers=[_ticker("HYG"), _ticker("LQD")],
        )
        ranked = rank_with_diversity(duplicates + [novel], limit=3, now=_NOW)
        families = [r["mechanism_family"] for r in ranked]
        self.assertIn(
            "bank_stress", families,
            msg=f"novel event crowded out of top-3 by proof-backed cluster: {families}",
        )


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------

class TestEventsDecorationWiring(unittest.TestCase):
    def test_decorated_row_carries_flags(self):
        from routes.events import _decorate_row
        row = _base_event(
            event_id=7,
            minimum_proof_set=[
                {"observation": "X", "channel": "commodities"},
            ],
            key_falsifiers=[
                {"observation": "Y", "channel": "commodities"},
            ],
        )
        with patch("routes.events.compute_staleness",
                   return_value={"status": "fresh",
                                 "hours_since_check": 0,
                                 "event_age_days": 1}), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "watching",
                                 "label": "", "evidence": ""}):
            _decorate_row(row)
        self.assertTrue(row["has_proof_set"])
        self.assertTrue(row["has_falsifiers"])
        self.assertFalse(row["low_information"])


if __name__ == "__main__":
    unittest.main()
