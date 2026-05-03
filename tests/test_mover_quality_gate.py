"""Focused tests for tightened mover surfacing.

Covers:
  * stale / legacy demotion on /movers/today + /movers/weekly
  * low-information + weighted_evidence=insufficient demotion on same
  * /movers/persistent eligibility (no stale, legacy, low-info, falsified)
  * /market-movers cluster-best representative selection
  * explicit ``surfaced_reason`` vocabulary (4 pinned phrases)

All fixtures are raw mover-card dicts — no live data fetches.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mover_card_normalizer import (
    SURFACED_REASONS,
    enrich_mover_cards,
    is_high_conviction_persistent,
    to_ui_card,
)


def _we(label: str, score: float = 0.7) -> dict:
    return {
        "evidence_label":   label,
        "evidence_score":   score,
        "evidence_reasons": [],
        "scored_tickers":   2,
        "total_tickers":    2,
        "tag_only_tickers": 0,
        "evidence_basis":   "evidence_scores",
    }


def _card(
    *, event_id: int,
    headline: str = "OPEC cuts oil supply",
    mechanism_family: str = "commodity_squeeze",
    thesis_state: str = "partial",
    stale_signal: str = "fresh",
    weighted_evidence: dict | None = None,
    has_proof_set: bool = True,
    has_falsifiers: bool = True,
    low_information: bool = False,
    tickers: list | None = None,
    return_5d_main: float = 3.0,
) -> dict:
    return {
        "event_id":         event_id,
        "headline":         headline,
        "mechanism_family": mechanism_family,
        "thesis_state":     thesis_state,
        "stale_signal":     stale_signal,
        "weighted_evidence": weighted_evidence or _we("supportive", 0.7),
        "has_proof_set":    has_proof_set,
        "has_falsifiers":   has_falsifiers,
        "low_information":  low_information,
        "tickers": tickers or [
            {"symbol": "USO", "role": "beneficiary",
             "return_5d": return_5d_main},
            {"symbol": "XLE", "role": "beneficiary",
             "return_5d": return_5d_main * 0.8},
        ],
    }


# ---------------------------------------------------------------------------
# Stale / legacy / low-info / insufficient demotion (today + weekly)
# ---------------------------------------------------------------------------

class TestQualityDemotion(unittest.TestCase):
    def _ids(self, cards: list[dict]) -> list[int]:
        return [c["id"] for c in cards if isinstance(c, dict)]

    def test_today_demotes_stale_to_tail(self):
        fresh = _card(event_id=1, headline="Fresh tariff headline A")
        stale = _card(event_id=2, headline="Stale tariff headline B",
                      stale_signal="stale")
        out = enrich_mover_cards([stale, fresh], window="today")
        # Fresh card must end up before the stale one regardless of
        # input order.
        self.assertEqual(self._ids(out), [1, 2])

    def test_weekly_demotes_legacy_to_tail(self):
        fresh  = _card(event_id=1, headline="Fresh weekly read D")
        legacy = _card(event_id=2, headline="Legacy weekly read E",
                       stale_signal="legacy")
        out = enrich_mover_cards([legacy, fresh], window="weekly")
        self.assertEqual(self._ids(out), [1, 2])

    def test_today_demotes_low_information(self):
        strong = _card(event_id=1, headline="Strong alpha read")
        low    = _card(event_id=2, headline="Low-info stub study",
                       low_information=True,
                       thesis_state="low_information",
                       weighted_evidence=_we("insufficient", 0.0))
        out = enrich_mover_cards([low, strong], window="today")
        self.assertEqual(self._ids(out), [1, 2])

    def test_today_demotes_weighted_evidence_insufficient(self):
        strong = _card(event_id=1, headline="Strong alpha read")
        weak   = _card(event_id=2, headline="Insufficient evidence study",
                       weighted_evidence=_we("insufficient", 0.0))
        out = enrich_mover_cards([weak, strong], window="today")
        self.assertEqual(self._ids(out), [1, 2])

    def test_demoted_cards_are_not_filtered_out(self):
        """Today + weekly still carry demoted cards — they just sit at
        the end of the list so the reader can see why trust was lost."""
        fresh = _card(event_id=1, headline="Fresh alpha read")
        stale = _card(event_id=2, headline="Stale companion read",
                      stale_signal="stale")
        out = enrich_mover_cards([fresh, stale], window="today")
        self.assertEqual(len(out), 2)
        self.assertEqual(self._ids(out), [1, 2])


# ---------------------------------------------------------------------------
# Persistent surface — filter, not demote
# ---------------------------------------------------------------------------

class TestPersistentEligibility(unittest.TestCase):
    def _ids(self, cards: list[dict]) -> list[int]:
        return [c["id"] for c in cards if isinstance(c, dict)]

    def test_stale_dropped_from_persistent(self):
        ok    = _card(event_id=1, headline="Active persistent read")
        stale = _card(event_id=2, headline="Persistent stale study",
                      stale_signal="stale")
        out = enrich_mover_cards([ok, stale], window="persistent")
        self.assertEqual(self._ids(out), [1])

    def test_legacy_dropped_from_persistent(self):
        ok     = _card(event_id=1, headline="Active persistent read")
        legacy = _card(event_id=2, headline="Legacy persistent read",
                       stale_signal="legacy")
        out = enrich_mover_cards([ok, legacy], window="persistent")
        self.assertEqual(self._ids(out), [1])

    def test_low_information_dropped_from_persistent(self):
        ok  = _card(event_id=1, headline="Active persistent read")
        low = _card(event_id=2, headline="Low-info persistent read",
                    low_information=True)
        out = enrich_mover_cards([ok, low], window="persistent")
        self.assertEqual(self._ids(out), [1])

    def test_falsified_dropped_from_persistent(self):
        ok  = _card(event_id=1, headline="Active persistent read")
        bad = _card(event_id=2, headline="Falsified persistent thesis",
                    thesis_state="falsified",
                    weighted_evidence=_we("contradictory", -0.7))
        out = enrich_mover_cards([ok, bad], window="persistent")
        self.assertEqual(self._ids(out), [1])

    def test_healthy_persistent_row_kept(self):
        ok = _card(event_id=1, headline="Healthy persistent read",
                   thesis_state="confirming")
        out = enrich_mover_cards([ok], window="persistent")
        self.assertEqual(self._ids(out), [1])


# ---------------------------------------------------------------------------
# /movers/persistent — strict high-conviction gate
# ---------------------------------------------------------------------------


def _high_conviction_card(**overrides) -> dict:
    """Default raw mover card that satisfies ``is_high_conviction_persistent``.

    Layer the gate-passing keys on top of the loose fixture so each
    test below can mutate one field at a time and confirm the gate
    rejects the result.
    """
    base = _card(event_id=1, headline="Healthy persistent read",
                 thesis_state="confirming")
    base["conviction"] = {"conviction_class": "conviction",
                          "impact_level": "high"}
    base.update(overrides)
    return base


class TestHighConvictionPersistentGate(unittest.TestCase):
    """``is_high_conviction_persistent`` is the rule the
    ``/movers/persistent`` route applies before sanitisation.  Each
    test isolates one disqualifying mutation."""

    def test_passes_with_all_required_fields(self):
        self.assertTrue(is_high_conviction_persistent(_high_conviction_card()))

    def test_rejects_when_conviction_block_missing(self):
        card = _high_conviction_card()
        card.pop("conviction", None)
        self.assertFalse(is_high_conviction_persistent(card))

    def test_rejects_lower_conviction_class(self):
        for cls in ("secondary", "lagging", "noisy_mix", "breaking", "pending"):
            card = _high_conviction_card(conviction={"conviction_class": cls})
            self.assertFalse(
                is_high_conviction_persistent(card),
                f"conviction_class={cls!r} should fail the gate",
            )

    def test_rejects_non_supportive_weighted_evidence(self):
        for label in ("contradictory", "mixed", "insufficient"):
            card = _high_conviction_card(
                weighted_evidence=_we(label, 0.0),
            )
            self.assertFalse(
                is_high_conviction_persistent(card),
                f"evidence_label={label!r} should fail the gate",
            )

    def test_rejects_thesis_state_outside_confirming_partial(self):
        for state in ("watching", "weakening", "falsified", "stale",
                      "low_information", "unknown"):
            card = _high_conviction_card(thesis_state=state)
            self.assertFalse(
                is_high_conviction_persistent(card),
                f"thesis_state={state!r} should fail the gate",
            )

    def test_partial_thesis_state_passes(self):
        card = _high_conviction_card(thesis_state="partial")
        self.assertTrue(is_high_conviction_persistent(card))

    def test_rejects_stale_card(self):
        card = _high_conviction_card(stale_signal="stale")
        self.assertFalse(is_high_conviction_persistent(card))

    def test_rejects_legacy_card(self):
        card = _high_conviction_card(stale_signal="legacy")
        self.assertFalse(is_high_conviction_persistent(card))

    def test_rejects_low_information_card(self):
        card = _high_conviction_card(low_information=True)
        self.assertFalse(is_high_conviction_persistent(card))

    def test_rejects_falsified_card(self):
        card = _high_conviction_card(thesis_state="falsified")
        self.assertFalse(is_high_conviction_persistent(card))

    def test_rejects_non_dict_input(self):
        self.assertFalse(is_high_conviction_persistent(None))
        self.assertFalse(is_high_conviction_persistent("nope"))
        self.assertFalse(is_high_conviction_persistent(42))


# ---------------------------------------------------------------------------
# /market-movers cluster-best representative
# ---------------------------------------------------------------------------

class TestClusterRepresentativeSelection(unittest.TestCase):
    def _ids(self, cards: list[dict]) -> list[int]:
        return [c["id"] for c in cards if isinstance(c, dict)]

    def test_best_sibling_kept_across_cluster(self):
        # Same headline prefix + family → same cluster signature.
        weak = _card(
            event_id=1, headline="OPEC crude cut tightens supply A",
            weighted_evidence=_we("supportive", 0.2),
            return_5d_main=1.0,
        )
        strong = _card(
            event_id=2, headline="OPEC crude cut tightens supply B",
            weighted_evidence=_we("supportive", 0.9),
            return_5d_main=4.5,
        )
        out = enrich_mover_cards([weak, strong], window="market")
        # The stronger sibling must survive regardless of input order.
        self.assertEqual(self._ids(out), [2])

    def test_order_independence_for_cluster_selection(self):
        weak = _card(
            event_id=1, headline="OPEC crude cut tightens supply A",
            weighted_evidence=_we("supportive", 0.2),
            return_5d_main=1.0,
        )
        strong = _card(
            event_id=2, headline="OPEC crude cut tightens supply B",
            weighted_evidence=_we("supportive", 0.9),
            return_5d_main=4.5,
        )
        out1 = enrich_mover_cards([weak, strong], window="market")
        out2 = enrich_mover_cards([strong, weak], window="market")
        self.assertEqual(self._ids(out1), self._ids(out2))

    def test_different_cluster_siblings_both_kept(self):
        oil = _card(
            event_id=1, headline="OPEC crude cut tightens supply",
            mechanism_family="commodity_squeeze",
        )
        bank = _card(
            event_id=2, headline="Regional bank stress flares again",
            mechanism_family="bank_stress",
        )
        out = enrich_mover_cards([oil, bank], window="market")
        self.assertEqual(set(self._ids(out)), {1, 2})

    def test_non_market_window_keeps_first_seen(self):
        """/movers/today retains first-seen dedup — we don't upgrade
        to best-per-cluster there because daily feeds are already
        time-ordered by the mover builder."""
        a = _card(event_id=1, headline="OPEC crude cut A",
                  weighted_evidence=_we("supportive", 0.2),
                  return_5d_main=1.0)
        b = _card(event_id=2, headline="OPEC crude cut B",
                  weighted_evidence=_we("supportive", 0.9),
                  return_5d_main=4.5)
        out = enrich_mover_cards([a, b], window="today")
        self.assertEqual(self._ids(out), [1])


# ---------------------------------------------------------------------------
# surfaced_reason vocabulary
# ---------------------------------------------------------------------------

class TestSurfacedReason(unittest.TestCase):
    def test_contradiction_priority(self):
        card = _card(
            event_id=1, headline="Thesis got blown up by price",
            thesis_state="falsified",
            weighted_evidence=_we("contradictory", -0.6),
        )
        ui = to_ui_card(card, "today")
        self.assertEqual(ui["surfaced_reason"], "contradiction worth attention")

    def test_contradictory_evidence_without_falsifier_also_flags(self):
        card = _card(
            event_id=1, headline="Weakening thesis",
            thesis_state="weakening",
            weighted_evidence=_we("contradictory", -0.5),
        )
        ui = to_ui_card(card, "weekly")
        self.assertEqual(ui["surfaced_reason"], "contradiction worth attention")

    def test_proof_backed_confirmation(self):
        card = _card(
            event_id=1, headline="Proof-backed confirming read",
            thesis_state="confirming",
            has_proof_set=True, has_falsifiers=True,
            weighted_evidence=_we("supportive", 0.8),
        )
        ui = to_ui_card(card, "today")
        self.assertEqual(ui["surfaced_reason"], "proof-backed confirmation")

    def test_persistent_follow_through(self):
        card = _card(
            event_id=1, headline="Quiet tape still following through",
            thesis_state="partial",
            has_proof_set=False, has_falsifiers=False,
            weighted_evidence=_we("mixed", 0.1),
        )
        ui = to_ui_card(card, "persistent")
        self.assertEqual(ui["surfaced_reason"], "persistent follow-through")

    def test_strongest_move_default_on_today(self):
        card = _card(
            event_id=1, headline="Clean move on today surface",
            thesis_state="partial",
            has_proof_set=False, has_falsifiers=False,
            weighted_evidence=_we("mixed", 0.1),
        )
        ui = to_ui_card(card, "today")
        self.assertEqual(ui["surfaced_reason"], "strongest move")

    def test_reason_always_from_pinned_vocabulary(self):
        for window in ("today", "weekly", "persistent", "market"):
            ui = to_ui_card(_card(event_id=1, headline="Sample"), window)
            self.assertIn(
                ui["surfaced_reason"], SURFACED_REASONS,
                msg=f"{window}: {ui['surfaced_reason']!r} not in pinned set",
            )

    def test_vocabulary_pinned(self):
        self.assertEqual(SURFACED_REASONS, (
            "strongest move",
            "persistent follow-through",
            "proof-backed confirmation",
            "contradiction worth attention",
        ))


# ---------------------------------------------------------------------------
# Shape stability — legacy keys preserved on the raw card
# ---------------------------------------------------------------------------

class TestShapeStability(unittest.TestCase):
    def test_raw_fields_preserved(self):
        card = _card(event_id=1, headline="Sample study")
        card["custom_legacy_field"] = "still here"
        out = enrich_mover_cards([card], window="today")
        self.assertEqual(out[0]["custom_legacy_field"], "still here")
        # Core UI keys layered on top.
        for key in ("id", "headline", "mechanism_family", "thesis_state",
                    "proof_quality", "stale_signal", "mover_window",
                    "weighted_evidence", "surfaced_reason", "moved_tickers",
                    "strongest_move_5d"):
            self.assertIn(key, out[0])


if __name__ == "__main__":
    unittest.main()
