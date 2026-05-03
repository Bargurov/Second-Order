"""Tests for the shared ``thesis_state`` composer and route wiring."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api  # noqa: F401  — resolve route circulars
from thesis_state import THESIS_STATES, derive_thesis_state


def _ev(**overrides):
    base = {
        "id":                7,
        "headline":          "Sample event",
        "event_date":        "2026-04-18",
        "timestamp":         "2026-04-18T09:00:00",
        "mechanism_family":  "commodity_squeeze",
        "mechanism_summary": "Refinery outage tightens capacity.",
        "confidence":        "medium",
        "market_tickers":    [],
        "minimum_proof_set": [],
        "key_falsifiers":    [],
    }
    base.update(overrides)
    return base


def _evidence(label, score=0.8):
    return {
        "evidence_label":  label,
        "evidence_score":  score,
        "evidence_reasons": [],
        "scored_tickers": 2,
        "total_tickers": 2,
        "tag_only_tickers": 0,
        "evidence_basis": "evidence_scores",
    }


# ---------------------------------------------------------------------------
# Enum + defensive
# ---------------------------------------------------------------------------

class TestContract(unittest.TestCase):
    def test_states_pinned(self):
        self.assertEqual(THESIS_STATES, (
            "confirming", "partial", "watching", "weakening",
            "falsified", "stale", "low_information",
        ))

    def test_non_dict_input_returns_watching(self):
        self.assertEqual(derive_thesis_state(None), "watching")
        self.assertEqual(derive_thesis_state("garbage"), "watching")

    def test_default_empty_event_is_watching(self):
        self.assertEqual(derive_thesis_state({}), "watching")


# ---------------------------------------------------------------------------
# State assignment — precedence
# ---------------------------------------------------------------------------

class TestPrecedence(unittest.TestCase):
    def test_falsified_overrides_positive_signals(self):
        """Contradictory evidence + named falsifier beats supportive-
        looking proof set and confirming-looking persistence."""
        ev = _ev(
            weighted_evidence=_evidence("contradictory", score=-0.7),
            has_proof_set=True,
            has_falsifiers=True,
            low_information=False,
            persistence_signal={"status": "active"},
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "falsified")

    def test_falsified_requires_named_falsifier(self):
        """Contradictory evidence without a named falsifier falls to
        ``weakening`` — the thesis didn't fail on its own stated
        terms because it never stated them."""
        ev = _ev(
            weighted_evidence=_evidence("contradictory", score=-0.7),
            has_proof_set=False,
            has_falsifiers=False,
            low_information=False,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "weakening")

    def test_low_information_beats_stale_and_below(self):
        ev = _ev(
            has_proof_set=False,
            has_falsifiers=False,
            low_information=True,
            stale_signal="legacy",
            weighted_evidence=_evidence("mixed", score=0.0),
        )
        self.assertEqual(derive_thesis_state(ev), "low_information")

    def test_stale_when_market_check_stale(self):
        ev = _ev(
            stale_signal="stale",
            weighted_evidence=_evidence("supportive", score=0.7),
            has_proof_set=True,
            has_falsifiers=True,
        )
        self.assertEqual(derive_thesis_state(ev), "stale")

    def test_stale_when_legacy(self):
        ev = _ev(
            stale_signal="legacy",
            weighted_evidence=_evidence("supportive", score=0.7),
        )
        self.assertEqual(derive_thesis_state(ev), "stale")

    def test_frozen_event_is_not_stale(self):
        """A frozen event has a completed historical check — the
        evidence isn't 'too old to trust' in the stale sense."""
        ev = _ev(
            stale_signal="frozen",
            weighted_evidence=_evidence("supportive", score=0.7),
            has_proof_set=True,
            has_falsifiers=True,
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_persistence_fading_maps_to_weakening(self):
        ev = _ev(
            persistence_signal={"status": "fading"},
            weighted_evidence=_evidence("supportive", score=0.6),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "weakening")


# ---------------------------------------------------------------------------
# Positive states
# ---------------------------------------------------------------------------

class TestPositiveStates(unittest.TestCase):
    def test_confirming_needs_proof_plus_supportive(self):
        ev = _ev(
            weighted_evidence=_evidence("supportive", score=0.8),
            has_proof_set=True,
            has_falsifiers=True,
            low_information=False,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_supportive_without_full_proof_is_partial(self):
        ev = _ev(
            weighted_evidence=_evidence("supportive", score=0.7),
            has_proof_set=False,
            has_falsifiers=False,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "partial")

    def test_partial_proof_alone_is_partial(self):
        ev = _ev(
            weighted_evidence=_evidence("mixed", score=0.1),
            has_proof_set=True,
            has_falsifiers=False,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "partial")

    def test_falsifiers_without_proof_set_is_partial(self):
        ev = _ev(
            weighted_evidence=_evidence("mixed", score=0.0),
            has_proof_set=False,
            has_falsifiers=True,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "partial")

    def test_watching_is_default(self):
        ev = _ev(
            weighted_evidence=_evidence("mixed", score=0.0),
            has_proof_set=False,
            has_falsifiers=False,
            low_information=False,
            stale_signal="fresh",
            persistence_signal={"status": "watching"},
        )
        self.assertEqual(derive_thesis_state(ev), "watching")

    def test_insufficient_evidence_does_not_flip_positive(self):
        """An event with no horizon-backed evidence and no proof
        structure just sits in ``watching`` — no positive claim
        without supporting signal."""
        ev = _ev(
            weighted_evidence=_evidence("insufficient", score=0.0),
            has_proof_set=False,
            has_falsifiers=False,
            stale_signal="fresh",
        )
        self.assertEqual(derive_thesis_state(ev), "watching")


# ---------------------------------------------------------------------------
# Fallback to on-the-fly derivation when decorated fields absent
# ---------------------------------------------------------------------------

class TestLazyDerivation(unittest.TestCase):
    def test_derives_flags_from_stored_fields(self):
        """Event not decorated with portfolio flag keys — composer
        computes them from ``minimum_proof_set`` / ``key_falsifiers``
        / ``confidence`` via ``portfolio_flags``.  Basket includes a
        primary direct (CVX) so the broad-beta filter doesn't strip
        the supportive read."""
        ev = _ev(
            minimum_proof_set=[
                {"observation": "spread widens", "channel": "commodities"},
            ],
            key_falsifiers=[
                {"observation": "spread collapses", "channel": "commodities"},
            ],
            market_tickers=[
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.85,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.80,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
            ],
            last_market_check_at="2026-04-20T09:00:00",
        )
        # No decorated flag fields present — composer fills them in.
        import datetime as _dt
        state = derive_thesis_state(
            ev, now=_dt.datetime(2026, 4, 20, 12, 0, 0),
        )
        self.assertEqual(state, "confirming")


# ---------------------------------------------------------------------------
# Route wiring
# ---------------------------------------------------------------------------

class TestEventsDecoration(unittest.TestCase):
    def test_decorated_row_carries_thesis_state(self):
        from routes.events import _decorate_row
        row = _ev(
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
            market_tickers=[
                # Include a primary single-name so the broad-beta filter
                # doesn't strip the supportive label.
                {"symbol": "CVX", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.85,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.80,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
            ],
        )
        with patch("routes.events.compute_staleness",
                   return_value={"status": "fresh",
                                 "hours_since_check": 0,
                                 "event_age_days": 1}), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "active",
                                 "label": "", "evidence": ""}):
            _decorate_row(row)
        self.assertIn("thesis_state", row)
        self.assertIn(row["thesis_state"], THESIS_STATES)
        self.assertEqual(row["thesis_state"], "confirming")

    def test_event_detail_route_emits_thesis_state(self):
        from routes.events import get_event_detail
        ev = _ev(
            id=123,
            minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
            key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
            market_tickers=[
                {"symbol": "USO", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.85,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
                {"symbol": "XLE", "role": "beneficiary",
                 "return_5d": 3.0, "evidence_score": 0.80,
                 "evidence_label": "supportive",
                 "direction_tag": "supports up"},
            ],
            last_market_check_at="2026-04-20T09:00:00",
        )
        with patch("api.load_event_by_id", return_value=ev):
            resp = get_event_detail(event_id=123)
        self.assertIn("thesis_state", resp)
        self.assertIn(resp["thesis_state"], THESIS_STATES)


class TestCrossAssetCoherenceRejection(unittest.TestCase):
    """When primary single-name picks contradict the thesis and only
    secondary / signal proxies support it, ``thesis_state`` must NOT
    resolve to ``confirming`` — the supportive aggregate is incoherent
    with the desk's direct picks.  Mixed primary reads (some support,
    some contradict) preserve their normal mixed/partial state."""

    def _ev(self, **overrides):
        # Stamp every event with a fresh staleness signal so the
        # test never trips the stale-evidence rung; we want to lock
        # the coherence-rejection branch, not interact with staleness.
        base = {
            "event_date":            "2026-04-20",
            "timestamp":             "2026-04-20T10:00:00",
            "last_market_check_at":  "2026-04-20T11:00:00",
            "stale_signal":          "fresh",
            "persistence_signal":    {"status": "watching"},
            "minimum_proof_set":     [{"observation": "x", "channel": "equities"}],
            "key_falsifiers":        [{"observation": "y", "channel": "equities"}],
            "confidence":            "medium",
            "mechanism_summary":     (
                "Saudi liftings cut tightens Gulf coker feedstock and "
                "widens the WCS-WTI heavy-sour discount."
            ),
        }
        base.update(overrides)
        return base

    def test_primary_contradicts_with_only_signal_support_blocks_confirming(self):
        """CVX (primary single-name) contradicts; XLE (secondary ETF)
        supports.  Aggregate evidence still reads supportive but the
        coherence check overrides — state cannot be confirming."""
        ev = self._ev(
            market_tickers=[
                {"symbol": "CVX",  "evidence_score": -0.6,
                 "direction_tag": "contradicts down"},
                {"symbol": "XLE",  "evidence_score":  0.6,
                 "direction_tag": "supports up"},
                {"symbol": "USO",  "evidence_score":  0.6,
                 "direction_tag": "supports up"},
            ],
            # Pre-decorate weighted_evidence as supportive so the test
            # locks the override behaviour, not the aggregate math.
            weighted_evidence={"evidence_label": "supportive"},
        )
        state = derive_thesis_state(ev)
        # Coherence rejection promotes effective evidence to
        # contradictory, so the falsifier present → falsified.
        self.assertEqual(state, "falsified")

    def test_primary_contradicts_only_signals_support_no_falsifier_weakens(self):
        """Same coherence rejection but no falsifier — effective
        evidence becomes contradictory and the state is weakening."""
        ev = self._ev(
            key_falsifiers=[],
            market_tickers=[
                {"symbol": "CVX",  "evidence_score": -0.6,
                 "direction_tag": "contradicts down"},
                {"symbol": "XLE",  "evidence_score":  0.6,
                 "direction_tag": "supports up"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
        )
        state = derive_thesis_state(ev)
        self.assertEqual(state, "weakening")

    def test_mixed_primary_picks_preserve_normal_state(self):
        """Some primary supports, some primary contradicts → genuinely
        ambiguous cross-asset read.  Coherence rejection does NOT fire;
        state resolves via the normal ladder (supportive + proof + fals
        → confirming)."""
        ev = self._ev(
            market_tickers=[
                {"symbol": "CVX", "evidence_score":  0.6,
                 "direction_tag": "supports up"},
                {"symbol": "XOM", "evidence_score": -0.6,
                 "direction_tag": "contradicts down"},
                {"symbol": "XLE", "evidence_score":  0.6,
                 "direction_tag": "supports up"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
        )
        state = derive_thesis_state(ev)
        # At least one primary supports → coherence does NOT reject.
        # Normal supportive + proof + falsifier ladder → confirming.
        self.assertEqual(state, "confirming")

    def test_primary_supports_signal_contradicts_holds_confirming(self):
        """Primary picks support, signal proxy contradicts.  Coherence
        rejection requires PRIMARY to contradict — so this is not
        rejected.  State stays at confirming."""
        ev = self._ev(
            market_tickers=[
                {"symbol": "CVX", "evidence_score":  0.6,
                 "direction_tag": "supports up"},
                {"symbol": "VXX", "evidence_score": -0.4,
                 "direction_tag": "contradicts down"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
        )
        state = derive_thesis_state(ev)
        self.assertEqual(state, "confirming")

    def test_all_signal_basket_no_primary_does_not_trigger(self):
        """No primary single-name picks at all → coherence has nothing
        to reject.  An all-ETF basket with supportive aggregate
        resolves through the normal ladder."""
        ev = self._ev(
            market_tickers=[
                {"symbol": "XLE",  "evidence_score":  0.6,
                 "direction_tag": "supports up"},
                {"symbol": "USO",  "evidence_score":  0.6,
                 "direction_tag": "supports up"},
            ],
            weighted_evidence={"evidence_label": "supportive"},
        )
        state = derive_thesis_state(ev)
        # No primary contradiction → coherence not triggered →
        # supportive + proof + falsifier → confirming.
        self.assertEqual(state, "confirming")


class TestThesisStateReason(unittest.TestCase):
    """``derive_thesis_state_reason`` returns a short non-empty string
    explaining what dominated each state.  Reads only stored fields
    (weighted_evidence label, proof / falsifier flags, stale_signal,
    persistence_signal)."""

    _MAX_LEN = 140

    def test_falsified_reason_mentions_contradictory(self):
        from thesis_state import derive_thesis_state_reason
        ev = {
            "has_falsifiers": True,
            "weighted_evidence": {"evidence_label": "contradictory"},
        }
        reason = derive_thesis_state_reason(ev)
        self.assertGreater(len(reason), 0)
        self.assertLessEqual(len(reason), self._MAX_LEN)
        low = reason.lower()
        self.assertTrue(
            "falsifi" in low and ("contradictory" in low or "stated terms" in low),
            f"falsified reason missing dominant cause: {reason!r}",
        )

    def test_low_information_reason_mentions_thin_evidence(self):
        from thesis_state import derive_thesis_state_reason
        ev = {"low_information": True}
        reason = derive_thesis_state_reason(ev)
        low = reason.lower()
        self.assertIn("low information", low)

    def test_stale_reason_mentions_stale_signal(self):
        from thesis_state import derive_thesis_state_reason
        ev = {
            "event_date": "2026-04-20",
            "timestamp":  "2026-04-20T10:00:00",
            "stale_signal": "stale",
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
        }
        reason = derive_thesis_state_reason(ev)
        low = reason.lower()
        self.assertIn("stale", low)

    def test_weakening_reason_distinguishes_contradictory_vs_fading(self):
        from thesis_state import derive_thesis_state_reason
        ev_contra = {
            "weighted_evidence": {"evidence_label": "contradictory"},
            "has_falsifiers": False,
        }
        r_contra = derive_thesis_state_reason(ev_contra)
        self.assertIn("contradictory", r_contra.lower())

        ev_fade = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
            "persistence_signal": {"status": "fading"},
            "stale_signal": "fresh",
        }
        r_fade = derive_thesis_state_reason(ev_fade)
        self.assertIn("fading", r_fade.lower())

    def test_confirming_reason_names_supportive_with_coverage(self):
        from thesis_state import derive_thesis_state_reason
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
            "stale_signal": "fresh",
            "persistence_signal": {"status": "active"},
        }
        reason = derive_thesis_state_reason(ev)
        low = reason.lower()
        self.assertTrue(
            "supportive" in low and (
                "proof" in low or "falsifier" in low
            ),
            f"confirming reason should name coverage: {reason!r}",
        )

    def test_partial_reason_distinguishes_subcase(self):
        from thesis_state import derive_thesis_state_reason
        # Supportive but no proof/falsifier coverage.
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set":  False,
            "has_falsifiers": False,
            "stale_signal":   "fresh",
            "persistence_signal": {"status": "active"},
        }
        reason = derive_thesis_state_reason(ev)
        self.assertIn("partial", reason.lower())

    def test_watching_reason_returns_default(self):
        from thesis_state import derive_thesis_state_reason
        ev = {
            "weighted_evidence": {"evidence_label": "insufficient"},
            "has_proof_set":  False,
            "has_falsifiers": False,
            "stale_signal":   "fresh",
            "persistence_signal": {"status": "watching"},
        }
        reason = derive_thesis_state_reason(ev)
        self.assertIn("watching", reason.lower())

    def test_non_dict_input_returns_friendly_string(self):
        from thesis_state import derive_thesis_state_reason
        self.assertGreater(len(derive_thesis_state_reason(None)), 0)
        self.assertGreater(len(derive_thesis_state_reason("garbage")), 0)

    def test_reason_max_length_enforced(self):
        """Every reason fits within the 140-char budget regardless of
        input."""
        from thesis_state import (
            THESIS_STATES, derive_thesis_state_reason,
        )
        # Fixture that triggers each state via the state= override.
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
        }
        for s in THESIS_STATES:
            reason = derive_thesis_state_reason(ev, state=s)
            self.assertLessEqual(
                len(reason), self._MAX_LEN,
                f"state={s} reason exceeds 140 chars: {reason!r}",
            )

    def test_with_reason_helper_returns_pair(self):
        from thesis_state import derive_thesis_state_with_reason
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
            "stale_signal": "fresh",
            "persistence_signal": {"status": "active"},
        }
        state, reason = derive_thesis_state_with_reason(ev)
        self.assertEqual(state, "confirming")
        self.assertGreater(len(reason), 0)


# ---------------------------------------------------------------------------
# Follow-through decay — 5d → 20d trajectory check
# ---------------------------------------------------------------------------

def _ticker(symbol, *, return_5d, return_20d, direction="supports"):
    """Build a market_tickers entry with explicit 5d/20d returns."""
    return {
        "symbol":         symbol,
        "return_5d":      return_5d,
        "return_20d":     return_20d,
        "direction_tag":  f"{direction} thesis",
    }


class TestFollowThroughDecayHelper(unittest.TestCase):
    """``_follow_through_decayed`` returns True when a majority of
    thesis-aligned tickers show a 5d→20d sign flip or a massive fade.
    Persistence-aware — structural events tolerate a higher decay
    rate before the gate fires."""

    def test_no_decay_when_returns_hold(self):
        from thesis_state import _follow_through_decayed
        ev = _ev(market_tickers=[
            _ticker("XOM", return_5d=2.5, return_20d=3.1),
            _ticker("CVX", return_5d=2.0, return_20d=2.4),
        ])
        self.assertFalse(_follow_through_decayed(ev))

    def test_majority_sign_flip_signals_decay_transient(self):
        """Three out of three movers reverse sign on the 20d leg —
        decay rate 1.0, triggers regardless of persistence."""
        from thesis_state import _follow_through_decayed
        ev = _ev(
            persistence="medium",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=-1.5),
                _ticker("CVX", return_5d=2.0, return_20d=-1.2),
                _ticker("PBF", return_5d=3.0, return_20d=-2.0),
            ],
        )
        self.assertTrue(_follow_through_decayed(ev))

    def test_massive_fade_signals_decay(self):
        """5d cleared the noise floor but 20d retained <20% — fade."""
        from thesis_state import _follow_through_decayed
        ev = _ev(
            persistence="medium",
            market_tickers=[
                _ticker("XOM", return_5d=3.0, return_20d=0.4),
                _ticker("CVX", return_5d=2.5, return_20d=0.3),
            ],
        )
        self.assertTrue(_follow_through_decayed(ev))

    def test_structural_persistence_tolerates_partial_fade(self):
        """A structural event with one fade out of three movers is
        below the structural threshold (50%) — not flagged."""
        from thesis_state import _follow_through_decayed
        ev = _ev(
            persistence="structural",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=2.7),
                _ticker("CVX", return_5d=2.0, return_20d=2.3),
                _ticker("PBF", return_5d=3.0, return_20d=-2.0),
            ],
        )
        self.assertFalse(_follow_through_decayed(ev))

    def test_transient_persistence_flags_partial_fade(self):
        """Same partial fade pattern on a transient (one_off) event —
        the lower threshold (34%) catches it."""
        from thesis_state import _follow_through_decayed
        ev = _ev(
            persistence="one_off",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=2.7),
                _ticker("CVX", return_5d=2.0, return_20d=2.3),
                _ticker("PBF", return_5d=3.0, return_20d=-2.0),
            ],
        )
        self.assertTrue(_follow_through_decayed(ev))

    def test_below_noise_movers_skipped(self):
        """Tickers whose 5d is below the noise floor aren't counted
        as aligned movers — they have no early-confirm stake to fade."""
        from thesis_state import _follow_through_decayed
        ev = _ev(market_tickers=[
            _ticker("XOM", return_5d=0.1, return_20d=-0.5),
            _ticker("CVX", return_5d=0.05, return_20d=-0.3),
        ])
        self.assertFalse(_follow_through_decayed(ev))

    def test_insufficient_tickers_returns_false(self):
        from thesis_state import _follow_through_decayed
        ev = _ev(market_tickers=[
            _ticker("XOM", return_5d=2.5, return_20d=-1.5),
        ])
        self.assertFalse(_follow_through_decayed(ev))

    def test_missing_returns_skip_gracefully(self):
        from thesis_state import _follow_through_decayed
        ev = _ev(market_tickers=[
            {"symbol": "XOM", "direction_tag": "supports thesis"},
            {"symbol": "CVX", "direction_tag": "supports thesis"},
        ])
        self.assertFalse(_follow_through_decayed(ev))

    def test_non_dict_returns_false(self):
        from thesis_state import _follow_through_decayed
        for bad in (None, "x", 5, []):
            self.assertFalse(_follow_through_decayed(bad))


class TestFollowThroughDecayStateGate(unittest.TestCase):
    """End-to-end: when follow-through decays, the state composer
    must NOT promote to ``confirming`` even though the rest of the
    structure (proof + falsifier + supportive aggregate) would
    otherwise qualify."""

    def _confirming_event(self, **overrides):
        ev = _ev(
            confidence="medium",
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens 2pp",
                 "channel": "commodities"},
            ],
            key_falsifiers=[
                {"observation": "Saudis walk back the cut",
                 "channel": "commodities"},
            ],
            weighted_evidence=_evidence("supportive"),
            stale_signal="fresh",
            persistence_signal={"status": "active"},
        )
        ev.update(overrides)
        return ev

    def test_decayed_evidence_blocks_confirming(self):
        ev = self._confirming_event(
            persistence="medium",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=-1.5),
                _ticker("CVX", return_5d=2.0, return_20d=-1.2),
                _ticker("PBF", return_5d=3.0, return_20d=-2.0),
            ],
        )
        # Pre-condition: would be "confirming" without decay gate.
        # Post-condition: decay demotes evidence to "mixed" → falls
        # through to partial (since proof + falsifier still present).
        state = derive_thesis_state(ev)
        self.assertNotEqual(state, "confirming")
        self.assertIn(state, ("partial", "watching"))

    def test_held_evidence_keeps_confirming(self):
        ev = self._confirming_event(
            persistence="medium",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=3.1),
                _ticker("CVX", return_5d=2.0, return_20d=2.4),
            ],
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_structural_event_holds_confirming_through_partial_fade(self):
        """A structural event whose follow-through is mixed (one fade
        in three) stays at confirming — structural cascades have
        slower follow-through."""
        ev = self._confirming_event(
            persistence="structural",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=2.7),
                _ticker("CVX", return_5d=2.0, return_20d=2.3),
                _ticker("PBF", return_5d=3.0, return_20d=-2.0),
            ],
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_stale_event_stays_stale_not_decayed(self):
        """A stale event takes the staleness branch even when the
        underlying ticker trajectory looks like decay — staleness is
        about evidence freshness, not thesis failure."""
        ev = self._confirming_event(
            persistence="medium",
            stale_signal="stale",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=-1.5),
                _ticker("CVX", return_5d=2.0, return_20d=-1.2),
            ],
        )
        self.assertEqual(derive_thesis_state(ev), "stale")

    def test_response_shape_unchanged(self):
        """Decay check is read-only — the event dict stays untouched."""
        ev = self._confirming_event(
            persistence="medium",
            market_tickers=[
                _ticker("XOM", return_5d=2.5, return_20d=-1.5),
                _ticker("CVX", return_5d=2.0, return_20d=-1.2),
            ],
        )
        before_keys = set(ev.keys())
        derive_thesis_state(ev)
        self.assertEqual(set(ev.keys()), before_keys)


# ---------------------------------------------------------------------------
# Validation rationale — names the dominant validation read
# ---------------------------------------------------------------------------


class TestValidationRationale(unittest.TestCase):
    """``derive_validation_rationale`` returns a short rationale naming
    the dominant validation read.  Five enumerated categories plus the
    off-list ``insufficient evidence`` for low-information rows."""

    _MAX_LEN = 140

    def test_low_information_names_insufficient(self):
        from thesis_state import derive_validation_rationale
        rationale = derive_validation_rationale({"low_information": True})
        self.assertIn("insufficient", rationale.lower())

    def test_stale_names_stale_evidence(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "event_date": "2026-04-18",
            "timestamp":  "2026-04-18T09:00:00",
            "stale_signal": "stale",
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("stale evidence", rationale.lower())

    def test_falsified_primary_contradiction(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "has_falsifiers": True,
            "weighted_evidence": {"evidence_label": "contradictory"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "contradicts thesis"},
                {"symbol": "CVX", "direction_tag": "contradicts thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("primary asset contradiction", rationale.lower())

    def test_falsified_cross_asset_rejection(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "has_falsifiers": True,
            "weighted_evidence": {"evidence_label": "contradictory"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "contradicts thesis"},
                {"symbol": "USO", "direction_tag": "supports thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("cross-asset rejection", rationale.lower())

    def test_cross_asset_rejection_outside_falsified(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "contradicts thesis"},
                {"symbol": "USO", "direction_tag": "supports thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("cross-asset rejection", rationale.lower())

    def test_priced_in_risk(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "supports thesis"},
                {"symbol": "CVX", "direction_tag": "supports thesis"},
            ],
        }
        with patch(
            "reaction_window.reaction_window_blocks_confirmation",
            return_value=True,
        ):
            rationale = derive_validation_rationale(ev)
        self.assertIn("priced-in", rationale.lower())

    def test_signal_only_support(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "market_tickers": [
                {"symbol": "USO", "direction_tag": "supports thesis"},
                {"symbol": "XLE", "direction_tag": "supports thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("signal-only support", rationale.lower())

    def test_primary_asset_support(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "supports thesis"},
                {"symbol": "CVX", "direction_tag": "supports thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("primary asset support", rationale.lower())

    def test_primary_asset_contradiction(self):
        from thesis_state import derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "contradictory"},
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "contradicts thesis"},
                {"symbol": "CVX", "direction_tag": "contradicts thesis"},
            ],
        }
        rationale = derive_validation_rationale(ev)
        self.assertIn("primary asset contradiction", rationale.lower())

    def test_length_cap_enforced(self):
        from thesis_state import THESIS_STATES, derive_validation_rationale
        ev = {
            "weighted_evidence": {"evidence_label": "supportive"},
            "has_proof_set": True,
            "has_falsifiers": True,
            "market_tickers": [
                {"symbol": "XOM", "direction_tag": "supports thesis"},
                {"symbol": "CVX", "direction_tag": "supports thesis"},
            ],
        }
        for s in THESIS_STATES:
            rationale = derive_validation_rationale(ev, state=s)
            self.assertLessEqual(
                len(rationale), self._MAX_LEN,
                f"state={s} rationale exceeds 140 chars: {rationale!r}",
            )

    def test_non_dict_returns_empty(self):
        from thesis_state import derive_validation_rationale
        self.assertEqual(derive_validation_rationale(None), "")
        self.assertEqual(derive_validation_rationale("garbage"), "")


# ---------------------------------------------------------------------------
# Falsification overrides — explicit precedence rules
# ---------------------------------------------------------------------------


class TestFalsifierStatusOverride(unittest.TestCase):
    """A triggered ``falsifier_status`` block must force ``falsified``
    when the trigger is still supported by current ``market_tickers``.
    Stale triggers (tickers deleted, retagged, or absent) no longer
    force ``falsified`` — see :class:`TestFalsifierStaleTickerGuard`.
    """

    # Two contradicting tickers on a known sector-ETF channel —
    # produces a "contradicted" event-wide label and a contradicting
    # equities-channel count, so the triggered falsifier_status block
    # is still backed by live evidence.
    _LIVE_CONTRADICTING_TICKERS = [
        {"symbol": "XLE", "direction_tag": "contradicts down"},
        {"symbol": "XOP", "direction_tag": "contradicts down"},
    ]

    def test_triggered_status_forces_falsified_over_supportive(self):
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["Saudis walk back the cut"],
                "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=self._LIVE_CONTRADICTING_TICKERS,
        )
        self.assertEqual(derive_thesis_state(ev), "falsified")

    def test_triggered_status_forces_falsified_over_mixed(self):
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("mixed", score=0.0),
            market_tickers=self._LIVE_CONTRADICTING_TICKERS,
        )
        self.assertEqual(derive_thesis_state(ev), "falsified")

    def test_watch_status_does_not_force_falsified(self):
        ev = _ev(
            falsifier_status={"available": True, "status": "watch",
                              "triggered": [], "watching": ["A"], "items": []},
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_triggered_reason_names_falsifier_status(self):
        from thesis_state import derive_thesis_state_reason
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            market_tickers=self._LIVE_CONTRADICTING_TICKERS,
        )
        reason = derive_thesis_state_reason(ev)
        self.assertIn("falsifier", reason.lower())
        self.assertIn("trigger", reason.lower())


class TestFalsifierStaleTickerGuard(unittest.TestCase):
    """Stored ``falsifier_status`` triggers must be ignored when their
    tickers/evidence are no longer present in current ``market_tickers``.
    """

    def test_stale_trigger_with_empty_tickers_is_ignored(self):
        # falsifier_status says "triggered" but market_tickers is empty
        # — the original tickers that produced the trigger have been
        # removed, so the stored block is stale and must not force
        # ``falsified``.
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=[],
        )
        self.assertNotEqual(derive_thesis_state(ev), "falsified")

    def test_stale_trigger_with_supportive_tickers_is_ignored(self):
        # market_tickers now read as supportive (basket flipped from
        # contradicted to supportive between save and read).  The
        # stored "triggered" block is stale.
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=[
                {"symbol": "XLE", "direction_tag": "supports up"},
                {"symbol": "XOP", "direction_tag": "supports up"},
            ],
        )
        self.assertNotEqual(derive_thesis_state(ev), "falsified")

    def test_current_trigger_still_falsifies(self):
        # Trigger is current — stored "triggered" + market_tickers
        # still reading "contradicted" + a contradicting ticker on the
        # named channel.  Must force ``falsified`` (back-compat with
        # the existing override behaviour).
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=[
                {"symbol": "XLE", "direction_tag": "contradicts down"},
                {"symbol": "XOP", "direction_tag": "contradicts down"},
            ],
        )
        self.assertEqual(derive_thesis_state(ev), "falsified")

    def test_stale_block_does_not_override_fresh_supportive_tickers(self):
        # Live tickers are clearly supportive (XOM/CVX explicit primary
        # picks both supporting).  A stale stored "triggered" must not
        # flip the live read to ``falsified`` — the live evidence
        # wins.
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "equities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            primary_assets=[{"symbol": "XOM", "rank": 1, "rationale": "direct"}],
            market_tickers=[
                {"symbol": "XOM", "direction_tag": "supports up",
                 "evidence_score": 0.85},
                {"symbol": "CVX", "direction_tag": "supports up",
                 "evidence_score": 0.75},
            ],
        )
        state = derive_thesis_state(ev)
        self.assertNotEqual(state, "falsified")

    def test_trigger_on_unrelated_channel_is_ignored(self):
        # Stored "triggered" item is on the ``commodities`` channel,
        # but current market_tickers only carry ``equities`` tickers
        # (the commodities ticker was removed).  Even though the
        # event-wide label still reads ``contradicted``, the item-
        # level trigger has no live channel to anchor on, so it must
        # be ignored.
        ev = _ev(
            falsifier_status={
                "available": True, "status": "triggered",
                "triggered": ["A"], "watching": [],
                "items": [{"channel": "commodities", "status": "triggered"}],
            },
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=[
                {"symbol": "XLE", "direction_tag": "contradicts down"},
                {"symbol": "XOP", "direction_tag": "contradicts down"},
            ],
        )
        self.assertNotEqual(derive_thesis_state(ev), "falsified")


class TestStrongPrimaryContradictionOverride(unittest.TestCase):
    """≥2 primary single-name picks contradicting the thesis (with
    ``primary_contradicts > primary_supports``) overrides a broad
    supportive aggregate so the state cannot resolve to confirming.
    1–1 splits are genuinely ambiguous and fall through."""

    def _ev_with(self, market_tickers, **overrides):
        base = _ev(
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=market_tickers,
        )
        base.update(overrides)
        return base

    def test_two_primary_contradictions_override_supportive(self):
        ev = self._ev_with([
            {"symbol": "XOM", "direction_tag": "contradicts thesis"},
            {"symbol": "CVX", "direction_tag": "contradicts thesis"},
            {"symbol": "USO", "direction_tag": "supports thesis"},
        ])
        state = derive_thesis_state(ev)
        self.assertNotEqual(state, "confirming")
        self.assertIn(state, ("weakening", "falsified"))

    def test_two_contradicts_one_support_still_overrides(self):
        ev = self._ev_with([
            {"symbol": "XOM", "direction_tag": "contradicts thesis"},
            {"symbol": "CVX", "direction_tag": "contradicts thesis"},
            {"symbol": "PBF", "direction_tag": "supports thesis"},
        ])
        state = derive_thesis_state(ev)
        self.assertNotEqual(state, "confirming")
        self.assertIn(state, ("weakening", "falsified"))

    def test_one_one_primary_split_does_not_override(self):
        """1 supports, 1 contradicts on primaries → genuinely ambiguous,
        falls through to the normal ladder (confirming when proof and
        falsifier are present)."""
        ev = self._ev_with([
            {"symbol": "XOM", "direction_tag": "supports thesis"},
            {"symbol": "CVX", "direction_tag": "contradicts thesis"},
        ])
        # Without strong-primary override the 1-1 split + supportive
        # aggregate + proof + falsifier resolves to confirming.
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_rationale_does_not_say_primary_support_when_overridden(self):
        """Regression hatch — when ``weighted_evidence.evidence_label``
        is ``supportive`` but the state was overridden by strong-primary
        contradiction, the rationale must NOT describe primary support."""
        from thesis_state import derive_validation_rationale
        ev = self._ev_with([
            {"symbol": "XOM", "direction_tag": "contradicts thesis"},
            {"symbol": "CVX", "direction_tag": "contradicts thesis"},
            {"symbol": "PBF", "direction_tag": "supports thesis"},
        ])
        rationale = derive_validation_rationale(ev).lower()
        self.assertNotIn("primary asset support", rationale)
        self.assertIn("primary asset contradiction", rationale)


# ---------------------------------------------------------------------------
# Market-vs-macro conflict handling
# ---------------------------------------------------------------------------


def _hostile_macro_caveats():
    return [{
        "condition":           "central bank pivots dovish",
        "effect_on_thesis":    "would weaken the thesis as policy stance reverses",
        "evidence_to_revisit": "first dovish dot-plot revision",
    }]


def _supportive_macro_caveats():
    return [{
        "condition":           "credit spreads widen further",
        "effect_on_thesis":    "amplifies the thesis as funding pressure deepens",
        "evidence_to_revisit": "HYG / IG spread widening past 50bp",
    }]


class TestMacroMarketConflict(unittest.TestCase):
    """Market-vs-macro conflict gating — primary tape supports the
    thesis but the analyst's regime caveats flag a hostile macro;
    confirming should hold only when ``proof_status.status == 'met'``.
    Mirror direction (primary contradicts vs supportive macro caveats)
    surfaces in the weakening reason."""

    def _confirming_event(self, **overrides):
        ev = _ev(
            weighted_evidence=_evidence("supportive"),
            has_proof_set=True,
            has_falsifiers=True,
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            market_tickers=[
                {"symbol": "XOM", "direction_tag": "supports thesis"},
                {"symbol": "CVX", "direction_tag": "supports thesis"},
            ],
        )
        ev.update(overrides)
        return ev

    def test_hostile_macro_with_weak_proof_demotes_to_partial(self):
        ev = self._confirming_event(
            hidden_mechanism={"regime_caveats": _hostile_macro_caveats()},
            proof_status={"status": "partial"},
        )
        self.assertEqual(derive_thesis_state(ev), "partial")

    def test_hostile_macro_with_strong_proof_holds_confirming(self):
        ev = self._confirming_event(
            hidden_mechanism={"regime_caveats": _hostile_macro_caveats()},
            proof_status={"status": "met"},
        )
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_hostile_macro_missing_proof_status_demotes_to_partial(self):
        """Defensive default — legacy rows without a stored
        ``proof_status`` block must NOT bypass the demotion."""
        ev = self._confirming_event(
            hidden_mechanism={"regime_caveats": _hostile_macro_caveats()},
        )
        ev.pop("proof_status", None)
        self.assertEqual(derive_thesis_state(ev), "partial")

    def test_no_hostile_macro_no_regression(self):
        """Without any regime caveats the new gate must not fire — the
        canonical confirming case still resolves to confirming."""
        ev = self._confirming_event()
        self.assertEqual(derive_thesis_state(ev), "confirming")

    def test_partial_reason_names_macro_conflict(self):
        from thesis_state import derive_thesis_state_reason
        ev = self._confirming_event(
            hidden_mechanism={"regime_caveats": _hostile_macro_caveats()},
            proof_status={"status": "partial"},
        )
        reason = derive_thesis_state_reason(ev).lower()
        self.assertIn("macro", reason)
        self.assertIn("partial", reason)

    def test_weakening_reason_names_conflict_when_macro_supports(self):
        """Mirror direction — primary contradiction with supportive
        regime caveats produces a weakening reason that names the
        market-vs-macro conflict."""
        from thesis_state import derive_thesis_state_reason
        ev = _ev(
            weighted_evidence=_evidence("supportive"),
            stale_signal="fresh",
            persistence_signal={"status": "active"},
            hidden_mechanism={"regime_caveats": _supportive_macro_caveats()},
            market_tickers=[
                {"symbol": "XOM", "direction_tag": "contradicts thesis"},
                {"symbol": "CVX", "direction_tag": "contradicts thesis"},
                {"symbol": "PBF", "direction_tag": "supports thesis"},
            ],
        )
        # Pre-condition: state demoted to weakening by strong-primary.
        self.assertEqual(derive_thesis_state(ev), "weakening")
        reason = derive_thesis_state_reason(ev).lower()
        self.assertIn("market-vs-macro", reason)


if __name__ == "__main__":
    unittest.main()
