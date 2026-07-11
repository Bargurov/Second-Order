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
from market_check_freshness import compute_staleness
from portfolio_flags import portfolio_flags
from relevance_ranking import (
    _LOW_INFO_PENALTY,
    _PROOF_DISCIPLINE_BONUS,
    _STALENESS_PENALTY,
    _quality_adjust,
    compute_relevance_score,
    rank_with_diversity,
)


_NOW = datetime(2026, 4, 20, 12, 0, 0)


def _checked_at(now: datetime, *, days_ago: int = 0, minutes_ago: int = 0) -> str:
    """ISO market-check timestamp derived from the INJECTED scoring clock.

    Every age-sensitive fixture in this module must use this helper.
    Earlier revisions built ``last_market_check_at`` from the machine
    wall clock while scoring with ``now=_NOW``; once calendar time
    advanced past ``_NOW`` the "80-day-old" check landed in the scoring
    clock's FUTURE, the freshness helper clamped elapsed time to zero,
    and the intended stale event was silently classified fresh.
    """
    return (now - timedelta(days=days_ago, minutes=minutes_ago)).isoformat(
        timespec="seconds",
    )


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
            last_market_check_at=_checked_at(_NOW, days_ago=80),
        )
        fresh_proof = _base_event(
            event_id=2,
            last_market_check_at=_checked_at(_NOW, minutes_ago=30),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        # The fixture really is stale-vs-fresh under the scoring clock.
        self.assertEqual(compute_staleness(stale_low, now=_NOW)["status"],
                         "stale")
        self.assertEqual(compute_staleness(fresh_proof, now=_NOW)["status"],
                         "fresh")
        ranked = rank_with_diversity(
            [stale_low, fresh_proof], limit=2, now=_NOW,
        )
        self.assertEqual(ranked[0]["event"]["id"], 2)
        self.assertEqual(ranked[1]["event"]["id"], 1)

    def test_proof_bonus_compounds_with_staleness_penalty(self):
        stale_proof = _base_event(
            event_id=1,
            last_market_check_at=_checked_at(_NOW, days_ago=80),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        fresh_plain = _base_event(
            event_id=2,
            last_market_check_at=_checked_at(_NOW, minutes_ago=30),
        )
        # Status is asserted directly so the comparison can never again
        # silently degrade into fresh-vs-fresh.
        self.assertEqual(compute_staleness(stale_proof, now=_NOW)["status"],
                         "stale")
        self.assertEqual(compute_staleness(fresh_plain, now=_NOW)["status"],
                         "fresh")
        # Multipliers reconcile with the pinned constants:
        #   stale × proof_bonus = 0.80 × 1.08 = 0.864;  fresh plain = 1.00.
        self.assertAlmostEqual(
            _quality_adjust(stale_proof, now=_NOW)["multiplier"],
            _STALENESS_PENALTY * _PROOF_DISCIPLINE_BONUS, places=6,
        )
        self.assertAlmostEqual(
            _quality_adjust(fresh_plain, now=_NOW)["multiplier"], 1.0,
            places=6,
        )
        # Fresh plain still wins despite no proof bonus; rank 1 is the
        # top selection and effective scores are best-to-worst.
        ranked = rank_with_diversity(
            [stale_proof, fresh_plain], limit=2, now=_NOW,
        )
        self.assertEqual(ranked[0]["event"]["id"], 2)
        self.assertEqual(ranked[1]["event"]["id"], 1)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)
        self.assertGreater(ranked[0]["effective_score"],
                           ranked[1]["effective_score"])

    def test_low_info_penalty_deepens_stale_gap(self):
        """Stale AND low-info should compound both penalties."""
        double_penalty = _base_event(
            event_id=1,
            confidence="low",
            mechanism_summary="Insufficient evidence.",
            last_market_check_at=_checked_at(_NOW, days_ago=80),
        )
        just_stale = _base_event(
            event_id=2,
            last_market_check_at=_checked_at(_NOW, days_ago=80),
        )
        # Both really are stale under the scoring clock.
        self.assertEqual(compute_staleness(double_penalty, now=_NOW)["status"],
                         "stale")
        self.assertEqual(compute_staleness(just_stale, now=_NOW)["status"],
                         "stale")
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
# Clock determinism — the ranking contract depends on RELATIVE time only.
# ---------------------------------------------------------------------------

class TestClockDeterminism(unittest.TestCase):
    """T3E — every age-sensitive timestamp derives from the injected
    scoring clock, so the same relative scenario is invariant to the
    calendar date the suite runs on."""

    @staticmethod
    def _scenario(anchor: datetime):
        """Controlled stale-proof vs fresh-plain pair anchored entirely
        at ``anchor``: event date, timestamps, and market checks all
        shift together with the scoring clock."""
        event_iso = (anchor - timedelta(days=2)).date().isoformat()
        ts_iso = (anchor - timedelta(days=2)).isoformat(timespec="seconds")
        stale_proof = _base_event(
            event_id=1,
            event_date=event_iso,
            timestamp=ts_iso,
            last_market_check_at=_checked_at(anchor, days_ago=80),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        fresh_plain = _base_event(
            event_id=2,
            event_date=event_iso,
            timestamp=ts_iso,
            last_market_check_at=_checked_at(anchor, minutes_ago=30),
        )
        ranked = rank_with_diversity(
            [stale_proof, fresh_plain], limit=2, now=anchor,
        )
        return {
            "statuses": (
                compute_staleness(stale_proof, now=anchor)["status"],
                compute_staleness(fresh_plain, now=anchor)["status"],
            ),
            "multipliers": (
                round(_quality_adjust(stale_proof, now=anchor)["multiplier"], 6),
                round(_quality_adjust(fresh_plain, now=anchor)["multiplier"], 6),
            ),
            "ranked": [
                (r["event"]["id"], r["rank"],
                 r["overall_score"], r["effective_score"])
                for r in ranked
            ],
        }

    def test_clock_shift_invariance_2026_vs_2030(self):
        a = self._scenario(datetime(2026, 4, 20, 12, 0, 0))
        b = self._scenario(datetime(2030, 4, 20, 12, 0, 0))
        self.assertEqual(a["statuses"], ("stale", "fresh"))
        self.assertEqual(a["statuses"], b["statuses"])
        self.assertEqual(a["multipliers"], b["multipliers"])
        self.assertEqual(a["ranked"], b["ranked"])

    def test_staleness_boundary_is_deterministic(self):
        """Classification around the shared freshness threshold, read
        from the policy itself — never hardcoded here."""
        probe = _base_event(
            event_id=1, last_market_check_at=_checked_at(_NOW, minutes_ago=1),
        )
        threshold_h = compute_staleness(probe, now=_NOW)[
            "refresh_threshold_hours"
        ]
        threshold_min = int(threshold_h * 60)
        cases = (
            (threshold_min - 5, "fresh"),   # just inside the window
            (threshold_min,     "stale"),   # boundary is inclusive-stale
            (threshold_min + 5, "stale"),   # just beyond
        )
        for minutes_ago, expected in cases:
            with self.subTest(minutes_ago=minutes_ago):
                ev = _base_event(
                    event_id=1,
                    last_market_check_at=_checked_at(
                        _NOW, minutes_ago=minutes_ago,
                    ),
                )
                self.assertEqual(
                    compute_staleness(ev, now=_NOW)["status"], expected,
                )

    def test_fresh_proof_outranks_fresh_plain(self):
        """The proof bonus itself stays active when both are fresh."""
        fresh_proof = _base_event(
            event_id=1,
            last_market_check_at=_checked_at(_NOW, minutes_ago=30),
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        )
        fresh_plain = _base_event(
            event_id=2,
            last_market_check_at=_checked_at(_NOW, minutes_ago=30),
        )
        ranked = rank_with_diversity(
            [fresh_plain, fresh_proof], limit=2, now=_NOW,
        )
        self.assertEqual(ranked[0]["event"]["id"], 1)  # proof-backed first
        self.assertEqual(ranked[1]["event"]["id"], 2)
        self.assertEqual(ranked[0]["rank"], 1)
        self.assertEqual(ranked[1]["rank"], 2)

    def test_multiplier_ordering_across_all_four_variants(self):
        """fresh proof > fresh plain > stale proof > stale plain — the
        composed multipliers (1.08 > 1.00 > 0.864 > 0.80) order the
        overall scores when every other input is equal."""
        def _score(event_id, *, stale, proof):
            kwargs = {
                "last_market_check_at": _checked_at(
                    _NOW, days_ago=80 if stale else 0,
                    minutes_ago=0 if stale else 30,
                ),
            }
            if proof:
                kwargs["minimum_proof_set"] = [
                    {"observation": "X", "channel": "commodities"}]
                kwargs["key_falsifiers"] = [
                    {"observation": "Y", "channel": "commodities"}]
            ev = _base_event(event_id=event_id, **kwargs)
            return compute_relevance_score(ev, now=_NOW)["overall_score"]

        fresh_proof = _score(1, stale=False, proof=True)
        fresh_plain = _score(2, stale=False, proof=False)
        stale_proof = _score(3, stale=True, proof=True)
        stale_plain = _score(4, stale=True, proof=False)
        self.assertGreater(fresh_proof, fresh_plain)
        self.assertGreater(fresh_plain, stale_proof)
        self.assertGreater(stale_proof, stale_plain)


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
