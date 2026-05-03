"""
tests/test_mover_card_normalizer.py

Contract tests for ``mover_card_normalizer`` — the pure projection
from raw mover cards to the UI-ready 11-field shape, plus the
sibling dedup helper.

Covers:
  * Exact field contract on every emitted card.
  * Closed ``mover_window`` vocabulary (today / weekly / persistent / market).
  * ``moved_tickers`` truncates to top 1–3 by |return_5d| and ordering
    is deterministic under ties.
  * ``strongest_move_5d`` matches the max |return_5d| of moved_tickers.
  * ``proof_quality`` / ``stale_signal`` / ``surfaced_reason`` derive
    from documented source keys with safe fallbacks.
  * Dedup collapses near-identical studies by
    ``(mechanism_family, headline prefix)`` signature.
  * HTTP endpoints return the canonical shape on each surface with
    the correct ``mover_window`` tag.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from mover_card_normalizer import (
    MOVER_WINDOWS,
    apply_diversity_guardrails,
    compute_mover_meta,
    dedup_mover_cards,
    to_ui_card,
    to_ui_cards,
)


REQUIRED_KEYS = {
    "id", "headline", "mechanism_family", "thesis_state",
    "proof_quality", "stale_signal", "mover_window",
    "weighted_evidence", "surfaced_reason", "moved_tickers",
    "strongest_move_5d",
}


def _raw_card(**overrides) -> dict:
    """Build a raw mover card shaped like ``_build_mover_summary`` output."""
    card = {
        "event_id":         1,
        "headline":         "OPEC cuts oil production through year-end",
        "mechanism_family": "commodity_squeeze",
        "thesis_state":     "priced",
        "weighted_evidence": {"label": "validated", "ratio": 0.7},
        "data_quality":     "ok",
        "why_still_moving": "Supply premium still holding on physical scarcity.",
        "tickers": [
            {"symbol": "USO", "role": "beneficiary",
             "return_5d": 3.2, "direction_tag": "supports thesis"},
            {"symbol": "XLE", "role": "beneficiary",
             "return_5d": 1.8, "direction_tag": "supports thesis"},
            {"symbol": "JETS", "role": "loser",
             "return_5d": -0.7, "direction_tag": "supports thesis"},
        ],
        "proof_status":     {"status": "met"},
        "quality":          {"confidence_basis": "strong_evidence"},
    }
    card.update(overrides)
    return card


# ---------------------------------------------------------------------------
# 1. Field contract
# ---------------------------------------------------------------------------


class TestUICardShape(unittest.TestCase):
    def test_every_required_key_present(self) -> None:
        out = to_ui_card(_raw_card(), window="today")
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)

    def test_empty_raw_input_still_shaped(self) -> None:
        """Malformed / empty input must not crash and must still emit
        the full shape so the UI never sees a ragged response."""
        out = to_ui_card({}, window="market")
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)
        self.assertEqual(out["mover_window"], "market")
        self.assertEqual(out["mechanism_family"], "none")
        self.assertEqual(out["thesis_state"], "unknown")
        self.assertEqual(out["moved_tickers"], [])
        self.assertIsNone(out["strongest_move_5d"])

    def test_none_card_does_not_crash(self) -> None:
        out = to_ui_card(None, window="today")
        self.assertEqual(set(out.keys()), REQUIRED_KEYS)


class TestMoverWindowVocab(unittest.TestCase):
    def test_canonical_set(self) -> None:
        self.assertEqual(
            set(MOVER_WINDOWS), {"today", "weekly", "persistent", "market"},
        )

    def test_unknown_window_raises(self) -> None:
        with self.assertRaises(ValueError):
            to_ui_card(_raw_card(), window="yearly")
        with self.assertRaises(ValueError):
            to_ui_card(_raw_card(), window="")


# ---------------------------------------------------------------------------
# 2. moved_tickers truncation + ordering
# ---------------------------------------------------------------------------


class TestMovedTickers(unittest.TestCase):
    def test_caps_at_three(self) -> None:
        ticks = [
            {"symbol": f"T{i}", "return_5d": float(i),
             "direction_tag": "supports"}
            for i in range(1, 8)
        ]
        out = to_ui_card(_raw_card(tickers=ticks), window="today")
        self.assertEqual(len(out["moved_tickers"]), 3)

    def test_ordered_by_abs_return_descending(self) -> None:
        ticks = [
            {"symbol": "A", "return_5d": 0.5,  "direction_tag": "supports"},
            {"symbol": "B", "return_5d": -4.0, "direction_tag": "supports"},
            {"symbol": "C", "return_5d": 1.2,  "direction_tag": "supports"},
        ]
        out = to_ui_card(_raw_card(tickers=ticks), window="today")
        syms = [t["symbol"] for t in out["moved_tickers"]]
        self.assertEqual(syms, ["B", "C", "A"])

    def test_tiebreak_by_symbol_ascending(self) -> None:
        ticks = [
            {"symbol": "Z", "return_5d": 2.0, "direction_tag": "supports"},
            {"symbol": "A", "return_5d": 2.0, "direction_tag": "supports"},
            {"symbol": "M", "return_5d": 2.0, "direction_tag": "supports"},
        ]
        out = to_ui_card(_raw_card(tickers=ticks), window="today")
        self.assertEqual(
            [t["symbol"] for t in out["moved_tickers"]], ["A", "M", "Z"],
        )

    def test_nan_return_dropped(self) -> None:
        ticks = [
            {"symbol": "GOOD", "return_5d": 1.5, "direction_tag": "supports"},
            {"symbol": "BAD",  "return_5d": float("nan"),
             "direction_tag": "supports"},
        ]
        out = to_ui_card(_raw_card(tickers=ticks), window="today")
        self.assertEqual(len(out["moved_tickers"]), 1)
        self.assertEqual(out["moved_tickers"][0]["symbol"], "GOOD")

    def test_empty_tickers_yields_none_strongest(self) -> None:
        out = to_ui_card(_raw_card(tickers=[]), window="today")
        self.assertIsNone(out["strongest_move_5d"])

    def test_strongest_matches_max_abs_of_moved(self) -> None:
        ticks = [
            {"symbol": "A", "return_5d": -3.5, "direction_tag": "supports"},
            {"symbol": "B", "return_5d":  1.2, "direction_tag": "supports"},
        ]
        out = to_ui_card(_raw_card(tickers=ticks), window="today")
        self.assertAlmostEqual(out["strongest_move_5d"], -3.5, places=5)


# ---------------------------------------------------------------------------
# 3. Derived fields
# ---------------------------------------------------------------------------


class TestProofQualityFallback(unittest.TestCase):
    def test_uses_proof_status_status_when_present(self) -> None:
        out = to_ui_card(
            _raw_card(proof_status={"status": "partial"}),
            window="weekly",
        )
        self.assertEqual(out["proof_quality"], "partial")

    def test_falls_back_to_quality_confidence_basis(self) -> None:
        out = to_ui_card(
            _raw_card(proof_status={}, quality={"confidence_basis": "fragile_basket"}),
            window="weekly",
        )
        self.assertEqual(out["proof_quality"], "fragile_basket")

    def test_defaults_to_unknown_when_both_absent(self) -> None:
        out = to_ui_card(
            _raw_card(proof_status={}, quality={}),
            window="weekly",
        )
        self.assertEqual(out["proof_quality"], "unknown")


class TestStaleSignalFallback(unittest.TestCase):
    def test_uses_data_quality_first(self) -> None:
        out = to_ui_card(_raw_card(data_quality="stale"), window="today")
        self.assertEqual(out["stale_signal"], "stale")

    def test_falls_back_to_stale_signal_field(self) -> None:
        card = _raw_card(stale_signal="stale")
        card.pop("data_quality", None)
        out = to_ui_card(card, window="today")
        self.assertEqual(out["stale_signal"], "stale")

    def test_defaults_to_ok_when_both_absent(self) -> None:
        card = _raw_card()
        card.pop("data_quality", None)
        card.pop("stale_signal", None)
        out = to_ui_card(card, window="today")
        self.assertEqual(out["stale_signal"], "ok")


# ``surfaced_reason`` is a controlled 4-token vocabulary
# (``SURFACED_REASONS``) emitted by ``_explicit_surfaced_reason``.
# The vocabulary contract is exhaustively covered in
# ``test_mover_quality_gate.TestSurfacedReason`` so this file does not
# duplicate it.


# ---------------------------------------------------------------------------
# 4. Dedup
# ---------------------------------------------------------------------------


class TestDedupe(unittest.TestCase):
    def test_near_identical_studies_collapsed(self) -> None:
        # Same family + same five leading content-words → same cluster.
        # The signature intentionally looks at the first ~5 content
        # words so late-appended punctuation / trailing clauses
        # collapse; here both headlines share that prefix.
        a = to_ui_card(_raw_card(
            event_id=1,
            headline="OPEC extends production cuts through Q3",
        ), window="today")
        b = to_ui_card(_raw_card(
            event_id=2,
            headline="OPEC extends production cuts through Q3, Saudi leads",
        ), window="today")
        c = to_ui_card(_raw_card(
            event_id=3,
            headline="Fed keeps rates on hold in split vote",
            mechanism_family="policy_surprise",
        ), window="today")
        deduped = dedup_mover_cards([a, b, c])
        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0]["id"], 1)
        self.assertEqual(deduped[1]["id"], 3)

    def test_same_headline_different_family_not_deduped(self) -> None:
        a = to_ui_card(_raw_card(
            event_id=1, headline="China tightens policy on strategic minerals",
            mechanism_family="tariff",
        ), window="today")
        b = to_ui_card(_raw_card(
            event_id=2, headline="China tightens policy on strategic minerals",
            mechanism_family="sanction",
        ), window="today")
        deduped = dedup_mover_cards([a, b])
        self.assertEqual(len(deduped), 2)

    def test_first_seen_wins_preserves_rank_order(self) -> None:
        a = to_ui_card(_raw_card(event_id=10), window="today")
        b = to_ui_card(_raw_card(event_id=11), window="today")
        # Both have the same headline + family → same signature.
        deduped = dedup_mover_cards([a, b])
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["id"], 10)

    def test_empty_signature_card_passes_through(self) -> None:
        """A card with family=none and no content-words can't be
        clustered — passing it through beats collapsing everything
        empty into one slot."""
        empty_a = to_ui_card({"event_id": 1, "headline": ""}, window="today")
        empty_b = to_ui_card({"event_id": 2, "headline": ""}, window="today")
        deduped = dedup_mover_cards([empty_a, empty_b])
        self.assertEqual(len(deduped), 2)


class TestToUICardsComposite(unittest.TestCase):
    def test_projects_and_dedupes(self) -> None:
        raws = [
            _raw_card(event_id=1,
                      headline="OPEC cuts oil production through year-end"),
            _raw_card(event_id=2,
                      headline="OPEC cuts oil production through year-end"),
            _raw_card(event_id=3,
                      headline="Fed holds rates unchanged",
                      mechanism_family="policy_surprise"),
        ]
        out = to_ui_cards(raws, window="weekly")
        self.assertEqual(len(out), 2)
        for card in out:
            self.assertEqual(set(card.keys()), REQUIRED_KEYS)
            self.assertEqual(card["mover_window"], "weekly")


# ---------------------------------------------------------------------------
# 5. HTTP surface — every endpoint returns the canonical shape
# ---------------------------------------------------------------------------


class TestMoverEndpointsUICardShape(unittest.TestCase):
    """Full HTTP smoke: each endpoint returns a list of UI-ready cards
    with the right ``mover_window`` tag.  Mocks the underlying slice /
    today readers so the test doesn't depend on DB state."""

    def setUp(self) -> None:
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)
        # A reasonable raw card the slice mock returns.
        self._raw = _raw_card()

    def _assert_bare_list_shape(self, body, *, window: str) -> None:
        # Mover surfaces default to a bare list of UI-ready cards.
        # The {"items": [...], "meta": {...}} envelope is opt-in via
        # ``?include_meta=true`` (exercised in
        # ``_assert_envelope_shape``).
        self.assertIsInstance(body, list)
        self.assertGreater(len(body), 0)
        for card in body:
            missing = REQUIRED_KEYS - set(card.keys())
            self.assertFalse(
                missing,
                f"{window}: card missing required keys {missing}",
            )
            self.assertEqual(card["mover_window"], window)

    def _assert_envelope_shape(self, body, *, window: str) -> None:
        # When the caller opts into the envelope, the meta block
        # carries surfaced_count / unique_clusters / unique_families
        # for the diversity-guardrail response contract; items still
        # carry the stable UI card shape.
        self.assertIsInstance(body, dict)
        self.assertIn("items", body)
        self.assertIn("meta", body)
        meta = body["meta"]
        self.assertIsInstance(meta, dict)
        for key in ("surfaced_count", "unique_clusters", "unique_families"):
            self.assertIn(key, meta)
        items = body["items"]
        self.assertIsInstance(items, list)
        self.assertGreater(len(items), 0)
        for card in items:
            missing = REQUIRED_KEYS - set(card.keys())
            self.assertFalse(
                missing,
                f"{window}: card missing required keys {missing}",
            )
            self.assertEqual(card["mover_window"], window)
        self.assertEqual(meta["surfaced_count"], len(items))

    def test_market_movers_endpoint(self) -> None:
        with patch("movers_cache.get_slice", return_value=[self._raw]):
            r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        self._assert_bare_list_shape(r.json(), window="market")

    def test_market_movers_endpoint_include_meta(self) -> None:
        with patch("movers_cache.get_slice", return_value=[self._raw]):
            r = self.client.get("/market-movers?include_meta=true")
        self.assertEqual(r.status_code, 200)
        self._assert_envelope_shape(r.json(), window="market")

    def test_movers_today_endpoint(self) -> None:
        with patch("api.movers_today", return_value=[self._raw]):
            r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        self._assert_bare_list_shape(r.json(), window="today")

    def test_movers_today_endpoint_include_meta(self) -> None:
        with patch("api.movers_today", return_value=[self._raw]):
            r = self.client.get("/movers/today?include_meta=true")
        self.assertEqual(r.status_code, 200)
        self._assert_envelope_shape(r.json(), window="today")

    def test_movers_weekly_endpoint(self) -> None:
        with patch("movers_cache.get_slice", return_value=[self._raw]):
            r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        self._assert_bare_list_shape(r.json(), window="weekly")

    def test_movers_weekly_endpoint_include_meta(self) -> None:
        with patch("movers_cache.get_slice", return_value=[self._raw]):
            r = self.client.get("/movers/weekly?include_meta=true")
        self.assertEqual(r.status_code, 200)
        self._assert_envelope_shape(r.json(), window="weekly")

    def test_movers_persistent_endpoint(self) -> None:
        # /movers/persistent enforces a high-conviction gate
        # (``conviction.conviction_class == "conviction"`` +
        # ``conviction.impact_level == "high"`` + supportive
        # weighted_evidence + confirming/partial thesis_state).  The
        # default raw fixture is shaped for the loose surfaces; layer
        # the gate-passing fields on top so the contract test still
        # exercises a populated response on the persistent surface.
        gated = {
            **self._raw,
            "thesis_state":      "confirming",
            "weighted_evidence": {"evidence_label": "supportive",
                                   "evidence_score": 0.8},
            "conviction":        {"conviction_class": "conviction",
                                   "impact_level": "high"},
        }
        with patch("movers_cache.get_slice", return_value=[gated]):
            r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        self._assert_bare_list_shape(r.json(), window="persistent")

    def test_movers_persistent_endpoint_include_meta(self) -> None:
        gated = {
            **self._raw,
            "thesis_state":      "confirming",
            "weighted_evidence": {"evidence_label": "supportive",
                                   "evidence_score": 0.8},
            "conviction":        {"conviction_class": "conviction",
                                   "impact_level": "high"},
        }
        with patch("movers_cache.get_slice", return_value=[gated]):
            r = self.client.get("/movers/persistent?include_meta=true")
        self.assertEqual(r.status_code, 200)
        self._assert_envelope_shape(r.json(), window="persistent")


# ---------------------------------------------------------------------------
# 6. Diversity guardrails (today / weekly / market-movers)
# ---------------------------------------------------------------------------


class TestDiversityGuardrails(unittest.TestCase):
    """The guardrail keeps one mechanism family from flooding a mover
    surface while leaving a genuinely strong lead mover at the top."""

    def _card(self, *, fam: str, impact: float, eid: int) -> dict:
        return {
            "event_id": eid,
            "mechanism_family": fam,
            "impact": impact,
            "headline": f"headline {eid} words placeholder content",
        }

    def test_family_flood_is_broken_up(self) -> None:
        # Four cards, three share a family; the outsider should be
        # promoted above at least one sibling despite a lower raw score.
        cards = [
            self._card(fam="tariff",   impact=5.0, eid=1),
            self._card(fam="tariff",   impact=4.9, eid=2),
            self._card(fam="tariff",   impact=4.8, eid=3),
            self._card(fam="sanction", impact=3.0, eid=4),
        ]
        out = apply_diversity_guardrails(cards)
        fams = [c["mechanism_family"] for c in out]
        # Leader preserved (strongest raw mover wins slot 1).
        self.assertEqual(fams[0], "tariff")
        # The outsider family must surface before the last tariff
        # sibling — that's the whole point of the guardrail.
        self.assertIn("sanction", fams[:3])

    def test_strong_leader_not_hidden(self) -> None:
        # A genuinely dominant card (impact 100) must still lead even
        # when three cards from another family trail it — guardrail
        # demotes siblings, never hides strong movers.
        cards = [
            self._card(fam="tariff",   impact=100.0, eid=1),
            self._card(fam="sanction", impact=2.0, eid=2),
            self._card(fam="sanction", impact=1.9, eid=3),
            self._card(fam="sanction", impact=1.8, eid=4),
        ]
        out = apply_diversity_guardrails(cards)
        self.assertEqual(out[0]["event_id"], 1)
        # All four cards must still be present — guardrail is a
        # re-rank, never a filter.
        self.assertEqual(len(out), 4)

    def test_no_data_loss_on_nondict_entries(self) -> None:
        cards = [
            self._card(fam="tariff", impact=1.0, eid=1),
            None,
            "stray",
        ]
        out = apply_diversity_guardrails(cards)
        self.assertEqual(len(out), 3)


class TestMoverMeta(unittest.TestCase):
    """``compute_mover_meta`` carries the response-level diversity
    signal (surfaced_count / unique_clusters / unique_families)."""

    def test_counts_unique_families_and_clusters(self) -> None:
        a = to_ui_card(_raw_card(
            event_id=1,
            headline="OPEC extends production cuts through Q3",
        ), window="today")
        b = to_ui_card(_raw_card(
            event_id=2,
            headline="Fed holds rates steady in split vote",
            mechanism_family="policy_surprise",
        ), window="today")
        c = to_ui_card(_raw_card(
            event_id=3,
            headline="Saudi deepens oil output curbs for Q4",
            mechanism_family="commodity_squeeze",
        ), window="today")
        meta = compute_mover_meta([a, b, c])
        self.assertEqual(meta["surfaced_count"], 3)
        self.assertEqual(meta["unique_families"], 2)
        self.assertEqual(meta["unique_clusters"], 3)

    def test_empty_meta_is_zeros(self) -> None:
        meta = compute_mover_meta([])
        self.assertEqual(meta, {
            "surfaced_count": 0,
            "unique_clusters": 0,
            "unique_families": 0,
        })


if __name__ == "__main__":
    unittest.main()
