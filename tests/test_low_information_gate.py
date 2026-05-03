"""Tests for the strict low-information gate."""

from __future__ import annotations

import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from low_information_gate import (
    apply_low_information_gate,
    clear_weak_chain_proof,
    compute_causal_strength,
    enforce_thesis_consistency,
    evaluate_blocker_discipline,
    evaluate_chain_family_consistency,
    evaluate_consistency,
    evaluate_low_information,
    evaluate_mechanism_quality,
    has_concrete_asset,
    is_low_information_mechanism,
    normalize_low_information,
    primary_thesis_inconsistent,
    regime_caveats_weaken_thesis,
)


CONCRETE_MECHANISM = (
    "Saudi Aramco cuts liftings by 1mbd, tightening Gulf Coast "
    "refinery feedstock and widening WCS-WTI heavy-sour discount."
)


def _event(**overrides):
    base = {
        "id":                 1,
        "headline":           "OPEC surprise cut",
        "what_changed":       (
            "Saudi Aramco cut crude liftings by 1mbd from August "
            "contract volumes, tightening Gulf Coast feedstock supply."
        ),
        "mechanism_summary":  CONCRETE_MECHANISM,
        "confidence":         "medium",
        "rating":             "good",
        "mechanism_family":   "commodity_squeeze",
        "market_tickers":     [],
        "beneficiaries":      ["XOM", "CVX"],
        "losers":             [],
        "assets_to_watch":    ["CL"],
        "beneficiary_tickers": ["XOM", "CVX"],
        "loser_tickers":       [],
        # Five-prong mechanism gate needs a named transmission channel
        # — give the base event a minimal first-order channel so test
        # cases that don't override transmission_path still clear.
        "expected_first_order_channels": ["commodities"],
        "expected_second_order_channels": ["equities"],
        "minimum_proof_set":  [{"observation": "WCS discount widens 2pp",
                                "channel": "commodities"}],
        "key_falsifiers":     [{"observation": "Saudis walk back",
                                "channel": "commodities"}],
        "critical_breakpoints": [],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Mechanism-text prong
# ---------------------------------------------------------------------------

class TestMechanismConcreteness(unittest.TestCase):
    def test_empty_is_low_info(self):
        self.assertTrue(is_low_information_mechanism(""))
        self.assertTrue(is_low_information_mechanism(None))

    def test_filler_markers_trip_gate(self):
        for marker in (
            "Insufficient evidence to characterise the mechanism.",
            "No clear mechanism identified yet.",
            "Mechanism is unclear at this stage.",
            "N/A",
            "Too early to tell.",
            "Cannot determine the driver.",
        ):
            self.assertTrue(
                is_low_information_mechanism(marker),
                msg=f"expected low-info for: {marker!r}",
            )

    def test_short_text_is_low_info(self):
        self.assertTrue(is_low_information_mechanism("brief note"))
        # Exactly below the 40-char floor
        self.assertTrue(
            is_low_information_mechanism("Supply tightens a little."),
        )

    def test_real_mechanism_passes(self):
        self.assertFalse(is_low_information_mechanism(CONCRETE_MECHANISM))

    def test_content_word_floor(self):
        # Long but no content words ≥ 5 chars — rejected.
        noise = "a b c d e " * 20
        self.assertTrue(is_low_information_mechanism(noise))


# ---------------------------------------------------------------------------
# Asset prong
# ---------------------------------------------------------------------------

class TestAssetConcreteness(unittest.TestCase):
    def test_non_dict_is_not_concrete(self):
        self.assertFalse(has_concrete_asset(None))
        self.assertFalse(has_concrete_asset("nope"))

    def test_ticker_in_beneficiary_list(self):
        self.assertTrue(has_concrete_asset(
            {"beneficiary_tickers": ["XOM"]},
        ))

    def test_ticker_in_loser_list(self):
        self.assertTrue(has_concrete_asset(
            {"loser_tickers": ["TSLA"]},
        ))

    def test_ticker_in_assets_to_watch(self):
        self.assertTrue(has_concrete_asset(
            {"assets_to_watch": ["CL", "GC"]},
        ))

    def test_placeholders_rejected(self):
        self.assertFalse(has_concrete_asset(
            {"beneficiary_tickers": ["N/A", "TBD", "NONE"]},
        ))

    def test_empty_buckets_reject(self):
        self.assertFalse(has_concrete_asset(
            {"beneficiary_tickers": [], "loser_tickers": [],
             "assets_to_watch": []},
        ))

    def test_dict_symbol_shape_accepted(self):
        self.assertTrue(has_concrete_asset(
            {"assets_to_watch": [{"symbol": "XLE"}]},
        ))

    def test_lowercase_ticker_accepted(self):
        """Ticker regex is upper-cased before match."""
        self.assertTrue(has_concrete_asset(
            {"beneficiary_tickers": ["xom"]},
        ))


# ---------------------------------------------------------------------------
# Gate evaluation
# ---------------------------------------------------------------------------

class TestEvaluateGate(unittest.TestCase):
    def test_clean_event_clears_gate(self):
        result = evaluate_low_information(_event())
        self.assertFalse(result["is_low_info"])
        self.assertEqual(result["reason"], "")

    def test_filler_mechanism_trips(self):
        ev = _event(mechanism_summary="Insufficient evidence.")
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "filler_mechanism")

    def test_no_concrete_asset_trips(self):
        ev = _event(
            beneficiary_tickers=[], loser_tickers=[], assets_to_watch=[],
        )
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "no_concrete_asset")

    def test_non_dict_input_is_low_info(self):
        self.assertTrue(evaluate_low_information("garbage")["is_low_info"])

    def test_mechanism_check_runs_before_asset_check(self):
        """When both prongs fail, the mechanism reason reports first."""
        ev = _event(
            mechanism_summary="N/A",
            beneficiary_tickers=[], loser_tickers=[], assets_to_watch=[],
        )
        self.assertEqual(
            evaluate_low_information(ev)["reason"], "filler_mechanism",
        )


# ---------------------------------------------------------------------------
# Mechanism-quality gate — five-prong structural check + vague filter
# ---------------------------------------------------------------------------

class TestMechanismQualityGate(unittest.TestCase):
    """A valid mechanism must explicitly name trigger, transmission
    channel, affected constraint / pricing relationship, affected
    actor, and an expected market expression.  Vague placeholders
    ('markets price risk', 'investors react', 'sector benefits',
    'uncertainty rises') are gate-rejected."""

    def test_valid_mechanism_accepted(self):
        """All five elements present — gate clears, evaluate_low_info
        returns a clean read."""
        quality = evaluate_mechanism_quality(_event())
        self.assertTrue(quality["is_valid"])
        self.assertEqual(quality["missing"], [])
        self.assertFalse(quality["vague"])
        # End-to-end: evaluate_low_information also clears.
        self.assertFalse(evaluate_low_information(_event())["is_low_info"])

    def test_vague_mechanism_text_rejected(self):
        """Mechanism prose using a forbidden placeholder phrase fires
        the gate even when the structural fields look fine."""
        ev = _event(
            mechanism_summary=(
                "Markets price risk into the curve and investors react "
                "as broader market reaction unfolds across the sector."
            ),
        )
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "weak_mechanism")

    def test_sector_benefits_phrase_rejected(self):
        """'sector benefits' / 'uncertainty rises' are gate-rejected."""
        ev = _event(
            mechanism_summary=(
                "The energy sector benefits as uncertainty rises across "
                "global markets and risk appetite shifts."
            ),
        )
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "weak_mechanism")

    def test_missing_trigger_drops_score_to_watch_only_band(self):
        """No what_changed → trigger prong fails → causal score 4/5;
        the tier system places this in the watch_only band rather
        than firing low-info on a single missing prong."""
        ev = _event(what_changed="")
        quality = evaluate_mechanism_quality(ev)
        self.assertFalse(quality["is_valid"])
        self.assertIn("trigger", quality["missing"])
        result = evaluate_low_information(ev)
        self.assertFalse(result["is_low_info"])

    def test_missing_channel_marks_low_information(self):
        """No transmission channel and no first-order channel pack →
        channel prong fails → low-info fallback."""
        ev = _event(
            transmission_path=[],
            expected_first_order_channels=[],
        )
        quality = evaluate_mechanism_quality(ev)
        self.assertFalse(quality["is_valid"])
        self.assertIn("channel", quality["missing"])

    def test_missing_constraint_marks_low_information(self):
        """A mechanism with no spread / margin / capacity / chokepoint
        marker, no substitution_barriers, and no hidden_mechanism
        bottleneck fails the constraint prong."""
        ev = _event(
            what_changed=(
                "Saudi Aramco's board met to discuss future plans."
            ),
            mechanism_summary=(
                "The board discussed future plans, and members offered "
                "their views during the routine meeting."
            ),
            substitution_barriers=[],
            hidden_mechanism={"bottleneck_type": "none"},
        )
        quality = evaluate_mechanism_quality(ev)
        self.assertFalse(quality["is_valid"])
        self.assertIn("constraint", quality["missing"])

    def test_missing_actor_marks_low_information(self):
        """No beneficiaries, no losers, no transmission-path actor →
        actor prong fails."""
        ev = _event(
            beneficiaries=[],
            losers=[],
            transmission_path=[],
        )
        quality = evaluate_mechanism_quality(ev)
        self.assertFalse(quality["is_valid"])
        self.assertIn("actor", quality["missing"])

    def test_low_information_fallback_normalizes_event(self):
        """When the mechanism gate fires, apply_low_information_gate
        coerces the event to the canonical low-info shape."""
        ev = _event(
            mechanism_summary=(
                "Markets price risk and investors react across the "
                "broader sector reaction."
            ),
            confidence="high",
        )
        result = apply_low_information_gate(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "weak_mechanism")
        self.assertEqual(ev["confidence"], "low")
        self.assertEqual(ev["minimum_proof_set"], [])
        self.assertEqual(ev["key_falsifiers"], [])


class TestPrimaryThesisConsistency(unittest.TestCase):
    """competing_thesis.primary_thesis must overlap on at least one
    content token with the mechanism narrative — a primary_thesis
    talking about something the mechanism never reaches is a self-
    contradiction and should fire the gate."""

    def test_consistent_primary_thesis_clears_gate(self):
        """primary_thesis tokens overlap with mechanism / actors —
        gate doesn't fire on consistency grounds."""
        ev = _event(
            competing_thesis={
                "primary_thesis": (
                    "Saudi Aramco lifting cut tightens Gulf Coast "
                    "feedstock; XOM and CVX margins widen on the "
                    "WCS-WTI spread."
                ),
            },
        )
        self.assertFalse(primary_thesis_inconsistent(ev))
        self.assertFalse(evaluate_low_information(ev)["is_low_info"])

    def test_disjoint_primary_thesis_fires_gate(self):
        """primary_thesis names completely unrelated entities —
        zero token overlap → gate fires with consistency reason."""
        ev = _event(
            competing_thesis={
                "primary_thesis": (
                    "Apple announces revised earnings guidance; "
                    "smartphone unit shipments decline in Asia."
                ),
            },
        )
        self.assertTrue(primary_thesis_inconsistent(ev))
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "primary_thesis_inconsistent")

    def test_no_primary_thesis_does_not_fire_consistency(self):
        """No competing_thesis → no primary_thesis to check → gate
        clears via the consistency prong."""
        ev = _event(competing_thesis={})
        self.assertFalse(primary_thesis_inconsistent(ev))


# ---------------------------------------------------------------------------
# Cross-field consistency — thesis vs assets vs proof / falsifier
# ---------------------------------------------------------------------------

def _consistency_event(**overrides):
    """Builder for consistency tests — adds primary_assets / proof /
    falsifier shapes the audit operates on."""
    base = _event(
        competing_thesis={
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "WCS-WTI heavy-sour discount widens; XOM and CVX margins "
                "expand on cheaper marginal-barrel supply."
            ),
            "evidence_favoring_primary": [],
        },
        primary_assets=[
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops as WCS discount widens."},
            {"symbol": "CVX", "rank": 2,
             "rationale": "Gulf Coast coker exposure to widening WCS-WTI heavy-sour discount."},
        ],
        secondary_assets=[],
        hedge_or_signal_assets=[],
        minimum_proof_set=[
            {"observation": "WCS-WTI discount widens by 2pp",
             "channel": "commodities", "threshold": "≥2pp",
             "timing": "5-20d"},
        ],
        key_falsifiers=[
            {"observation": "Saudis publicly walk back the lifting cut",
             "channel": "commodities", "threshold": "any reversal",
             "timing": "1-5d"},
        ],
        critical_breakpoints=[],
    )
    base.update(overrides)
    return base


class TestCrossFieldConsistency(unittest.TestCase):
    """Audit drops asset entries / proof / falsifier items that don't
    share content tokens with the primary thesis + mechanism
    narrative.  Hedge / signal assets are exempt by construction."""

    def test_aligned_items_kept(self):
        """A clean event whose assets and proof / falsifier all
        reference the thesis is left untouched."""
        ev = _consistency_event()
        before_assets = list(ev["primary_assets"])
        before_proof = list(ev["minimum_proof_set"])
        before_falsifiers = list(ev["key_falsifiers"])

        result = enforce_thesis_consistency(ev)

        self.assertEqual(result["dropped"], 0)
        self.assertIsNone(result["downgrade"])
        self.assertEqual(ev["primary_assets"], before_assets)
        self.assertEqual(ev["minimum_proof_set"], before_proof)
        self.assertEqual(ev["key_falsifiers"], before_falsifiers)

    def test_off_thesis_assets_dropped(self):
        """An asset entry whose symbol AND rationale share no thesis
        tokens is dropped from primary_assets."""
        ev = _consistency_event(
            primary_assets=[
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct Gulf Coast heavy-sour refiner."},
                # Off-thesis: smartphone supply chain has nothing to
                # do with Saudi crude liftings.
                {"symbol": "AAPL", "rank": 2,
                 "rationale": "Smartphone unit shipments improve in Asia next quarter."},
            ],
        )
        result = enforce_thesis_consistency(ev)
        symbols = [e["symbol"] for e in ev["primary_assets"]]
        self.assertEqual(symbols, ["XOM"])
        self.assertEqual(result["per_field"]["primary_assets"]["dropped"], 1)

    def test_off_thesis_proof_items_removed(self):
        """A proof_set entry whose observation tests a different
        thesis is dropped from minimum_proof_set."""
        ev = _consistency_event(
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities"},
                # Off-thesis: TSMC capacity has nothing to do with
                # Saudi crude liftings or Gulf Coast refiners.
                {"observation": "TSMC announces leading-node capacity expansion",
                 "channel": "equities"},
            ],
        )
        result = enforce_thesis_consistency(ev)
        kept_observations = [
            i["observation"] for i in ev["minimum_proof_set"]
        ]
        self.assertEqual(kept_observations, ["WCS-WTI discount widens by 2pp"])
        self.assertEqual(
            result["per_field"]["minimum_proof_set"]["dropped"], 1,
        )

    def test_off_thesis_falsifier_removed(self):
        ev = _consistency_event(
            key_falsifiers=[
                {"observation": "Saudis walk back the cut",
                 "channel": "commodities"},
                {"observation": "Apple announces revised earnings guidance",
                 "channel": "equities"},
            ],
        )
        enforce_thesis_consistency(ev)
        kept = [i["observation"] for i in ev["key_falsifiers"]]
        self.assertEqual(kept, ["Saudis walk back the cut"])

    def test_hedge_signal_assets_exempt(self):
        """hedge_or_signal_assets are non-thesis exposures by
        construction — the audit must NOT drop them."""
        ev = _consistency_event(
            hedge_or_signal_assets=[
                # UUP / VIX share no overlap with the Saudi lifting
                # thesis; a generic dollar-signal hedge is fine.
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
                {"symbol": "VIX", "rank": 2,
                 "rationale": "Vol watch instrument — tape-level signal."},
            ],
        )
        before = list(ev["hedge_or_signal_assets"])
        enforce_thesis_consistency(ev)
        self.assertEqual(ev["hedge_or_signal_assets"], before)

    def test_full_collapse_normalizes_to_low_information(self):
        """When most of the structure is off-thesis, the audit signals
        a low_information downgrade (the wrapper in _finalize_analysis
        then calls normalize_low_information)."""
        ev = _consistency_event(
            primary_assets=[
                {"symbol": "AAPL", "rank": 1,
                 "rationale": "Smartphone shipments improve next quarter."},
                {"symbol": "TSLA", "rank": 2,
                 "rationale": "EV demand recovers in mainland China."},
            ],
            minimum_proof_set=[
                {"observation": "TSMC capacity expansion confirms",
                 "channel": "equities"},
                {"observation": "iPhone unit shipments rise",
                 "channel": "equities"},
            ],
            key_falsifiers=[
                {"observation": "Apple guidance trimmed",
                 "channel": "equities"},
            ],
        )
        result = enforce_thesis_consistency(ev)
        self.assertGreaterEqual(result["rate"], 0.6)
        self.assertEqual(result["downgrade"], "low_information")

    def test_emptied_primary_assets_signals_watch_only(self):
        """When the audit drops the only primary asset entry but
        proof / falsifier survive, the signal is ``watch_only`` —
        the mechanism still has tradable verifications, just no
        ranked direct exposure."""
        ev = _consistency_event(
            primary_assets=[
                # Off-thesis primary — gets dropped.
                {"symbol": "AAPL", "rank": 1,
                 "rationale": "Smartphone shipments improve next quarter."},
            ],
            # Proof / falsifier still on-thesis.
        )
        result = enforce_thesis_consistency(ev)
        self.assertEqual(ev["primary_assets"], [])
        self.assertEqual(result["downgrade"], "watch_only")

    def test_evaluate_consistency_does_not_mutate(self):
        """Read-only audit returns the same numbers without changing
        the event."""
        ev = _consistency_event(
            primary_assets=[
                {"symbol": "AAPL", "rank": 1,
                 "rationale": "Smartphone shipments improve."},
                {"symbol": "XOM", "rank": 2,
                 "rationale": "Direct Gulf Coast heavy-sour refiner."},
            ],
        )
        before = copy.deepcopy(ev["primary_assets"])
        result = evaluate_consistency(ev)
        self.assertEqual(result["per_field"]["primary_assets"]["dropped"], 1)
        self.assertEqual(ev["primary_assets"], before)

    def test_response_shape_unchanged(self):
        """The audit only drops items from existing list fields —
        every key the input event carried is still present, and no
        new top-level keys appear."""
        ev = _consistency_event(
            primary_assets=[
                {"symbol": "AAPL", "rank": 1,
                 "rationale": "Smartphone shipments improve next quarter."},
            ],
        )
        before_keys = set(ev.keys())
        enforce_thesis_consistency(ev)
        self.assertEqual(set(ev.keys()), before_keys)
        # The dropped asset just becomes an empty list — no schema break.
        self.assertIsInstance(ev["primary_assets"], list)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

class TestNormalization(unittest.TestCase):
    def test_confidence_forced_low(self):
        ev = _event(confidence="high")
        normalize_low_information(ev)
        self.assertEqual(ev["confidence"], "low")

    def test_proof_and_falsifier_emptied(self):
        ev = _event()
        normalize_low_information(ev)
        self.assertEqual(ev["minimum_proof_set"], [])
        self.assertEqual(ev["key_falsifiers"], [])
        self.assertEqual(ev["critical_breakpoints"], [])

    def test_vague_asset_narrative_stripped(self):
        ev = _event(
            beneficiaries=["Saudi Aramco", "the sector", "XOM"],
            losers=["relevant oil importers", "refiners"],
            assets_to_watch=["the industry", "Brent crude"],
        )
        normalize_low_information(ev)
        self.assertEqual(
            sorted(ev["beneficiaries"]), ["Saudi Aramco", "XOM"],
        )
        self.assertEqual(ev["losers"], ["refiners"])
        self.assertEqual(ev["assets_to_watch"], ["Brent crude"])

    def test_ticker_lists_preserved_when_mechanism_is_filler(self):
        """Gate firing on mechanism-text prong alone must not erase
        legitimate ticker buckets."""
        ev = _event(mechanism_summary="Insufficient evidence.")
        normalize_low_information(ev)
        self.assertEqual(ev["beneficiary_tickers"], ["XOM", "CVX"])

    def test_idempotent(self):
        ev = _event(mechanism_summary="Insufficient evidence.")
        normalize_low_information(ev)
        snapshot = copy.deepcopy(ev)
        normalize_low_information(ev)
        self.assertEqual(ev, snapshot)

    def test_non_dict_input_passes_through(self):
        self.assertEqual(normalize_low_information("x"), "x")


# ---------------------------------------------------------------------------
# apply_low_information_gate — evaluate + optional normalize wrapper
# ---------------------------------------------------------------------------

class TestApplyGate(unittest.TestCase):
    def test_clean_event_not_mutated(self):
        ev = _event()
        before = copy.deepcopy(ev)
        out = apply_low_information_gate(ev)
        self.assertFalse(out["is_low_info"])
        self.assertEqual(ev, before)

    def test_low_info_event_normalised_in_place(self):
        ev = _event(
            mechanism_summary="Insufficient evidence.",
            confidence="medium",
        )
        out = apply_low_information_gate(ev)
        self.assertTrue(out["is_low_info"])
        self.assertEqual(ev["confidence"], "low")
        self.assertEqual(ev["minimum_proof_set"], [])
        self.assertEqual(ev["key_falsifiers"], [])


# ---------------------------------------------------------------------------
# Wiring — _normalize_schema applies the gate at analysis save-time
# ---------------------------------------------------------------------------

class TestAnalyzeEventIntegration(unittest.TestCase):
    """Exercise ``analyze_event._finalize_analysis`` — the save-time
    path that runs the gate after ticker buckets are populated."""

    def _finalize(self, raw: dict, headline: str = "Sample event") -> dict:
        from analyze_event import _finalize_analysis
        return _finalize_analysis(
            parsed=raw, headline=headline,
            stage=raw.get("stage") or "realized",
            persistence=raw.get("persistence") or "medium",
        )

    def test_insufficient_mechanism_gates(self):
        raw = {
            "stage":              "realized",
            "persistence":        "medium",
            "what_changed":       "Minor note.",
            "mechanism_summary":  "Insufficient evidence to characterise.",
            "beneficiaries":      ["XOM"],
            "losers":             [],
            "assets_to_watch":    ["CL"],
            "confidence":         "medium",
            "market_note":        "",
            "mechanism_family":   "commodity_squeeze",
            "beneficiary_tickers": ["XOM"],
        }
        out = self._finalize(raw, "Sample event")
        self.assertEqual(out["confidence"], "low")
        self.assertEqual(out["mechanism_family"], "none")
        self.assertEqual(out["minimum_proof_set"], [])
        self.assertEqual(out["key_falsifiers"], [])

    def test_no_concrete_asset_gates_via_unit_call(self):
        """At finalize-time the inverse-proxy backfill populates
        tickers from mechanism text, so the route rarely sees an
        empty-asset event at the gate.  The asset prong is still
        exercised — at the unit level, where backfill doesn't run —
        by ``TestEvaluateGate.test_no_concrete_asset_trips``.  Here
        we just assert the wiring: when the gate fires on a raw
        event with no assets and no proxy-triggering mechanism text,
        ``apply_low_information_gate`` coerces the empty shape."""
        from low_information_gate import apply_low_information_gate
        event = {
            "mechanism_summary": CONCRETE_MECHANISM,
            "confidence":        "high",
            "beneficiary_tickers": [],
            "loser_tickers":       [],
            "assets_to_watch":     [],
            "minimum_proof_set":   [{"observation": "X", "channel": "x"}],
            "key_falsifiers":      [{"observation": "Y", "channel": "y"}],
        }
        out = apply_low_information_gate(event)
        self.assertTrue(out["is_low_info"])
        self.assertEqual(event["confidence"], "low")
        self.assertEqual(event["minimum_proof_set"], [])
        self.assertEqual(event["key_falsifiers"], [])

    def test_real_study_passes_through_untouched(self):
        raw = {
            "stage":              "realized",
            "persistence":        "medium",
            "what_changed":       "OPEC cut ratified.",
            "mechanism_summary": CONCRETE_MECHANISM,
            "beneficiaries":      ["XOM", "CVX"],
            "losers":             [],
            "assets_to_watch":    ["CL"],
            "confidence":         "high",
            "market_note":        "",
            "mechanism_family":   "commodity_squeeze",
            "beneficiary_tickers": ["XOM", "CVX"],
        }
        out = self._finalize(raw, "OPEC surprise cut")
        # The gate did not fire: confidence is preserved (not forced to
        # "low") and the family stays on the analyst's commit.  The
        # exact confidence token may be rewritten by downstream
        # sanitizers (``high`` → ``medium`` when adversarial challenge
        # is thin etc.), so we only assert the negative invariant.
        self.assertNotEqual(out["confidence"], "low")
        self.assertEqual(out["mechanism_family"], "commodity_squeeze")

    def test_vague_entity_padding_stripped_on_low_info(self):
        raw = {
            "stage":              "realized",
            "persistence":        "medium",
            "what_changed":       "Note.",
            "mechanism_summary":  "Insufficient evidence.",
            "beneficiaries":      ["the sector", "XOM"],
            "losers":             ["relevant oil importers"],
            "assets_to_watch":    ["the industry", "Brent"],
            "confidence":         "medium",
            "market_note":        "",
            "mechanism_family":   "commodity_squeeze",
            "beneficiary_tickers": ["XOM"],
        }
        out = self._finalize(raw, "Sample event")
        self.assertNotIn("the sector", out["beneficiaries"])
        self.assertNotIn("the industry", out["assets_to_watch"])
        self.assertNotIn("relevant oil importers", out["losers"])


# ---------------------------------------------------------------------------
# portfolio_flags sharing the gate
# ---------------------------------------------------------------------------

class TestPortfolioFlagsDelegation(unittest.TestCase):
    def test_low_conf_plus_filler_marker_flagged(self):
        from portfolio_flags import portfolio_flags
        ev = {"confidence": "low",
              "mechanism_summary": "Insufficient evidence to characterise."}
        self.assertTrue(portfolio_flags(ev)["low_information"])

    def test_low_conf_plus_sparse_text_flagged(self):
        from portfolio_flags import portfolio_flags
        ev = {"confidence": "low",
              "mechanism_summary": "too short."}
        self.assertTrue(portfolio_flags(ev)["low_information"])

    def test_high_conf_not_flagged_regardless_of_text(self):
        from portfolio_flags import portfolio_flags
        ev = {"confidence": "high",
              "mechanism_summary": "Insufficient evidence."}
        self.assertFalse(portfolio_flags(ev)["low_information"])


class TestEvidenceQualityTier(unittest.TestCase):
    """Three-state internal tier classification: actionable / watch_only
    / low_information.  Tier is read internally to gate confidence and
    to keep weak outputs from generating overconfident proof/asset
    plans; it's surfaced via ``validation_warnings`` rather than as a
    new top-level enum field.
    """

    def _full_actionable(self):
        """Event with valid mechanism, primary_thesis, concrete asset
        rationale, and proof+falsifier coverage."""
        ev = _event()
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi liftings cut tightens Gulf coker feedstock; "
                "WCS heavy-sour discount widens; CVX margins lift."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "CVX", "rank": 1,
             "rationale": "Gulf coker — heavy-sour feedstock benefits."},
        ]
        return ev

    def test_actionable_tier_when_all_prongs_pass(self):
        from low_information_gate import evidence_quality_tier
        self.assertEqual(
            evidence_quality_tier(self._full_actionable()),
            "actionable",
        )

    def test_watch_only_when_proof_and_falsifier_empty(self):
        """Valid mechanism + asset + primary_thesis but no proof or
        falsifier item → watch_only, not actionable."""
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        ev["minimum_proof_set"] = []
        ev["key_falsifiers"]    = []
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_watch_only_when_primary_thesis_missing(self):
        """Valid mechanism + asset + proof, but no committed
        primary_thesis → watch_only."""
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        ev["competing_thesis"] = {}   # no primary_thesis
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_watch_only_when_asset_rationale_missing(self):
        """Valid mechanism + proof + primary_thesis but no concrete
        asset rationale (primary_assets empty / no rationale)."""
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        ev["primary_assets"] = []   # no rationale to read
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_low_information_when_mechanism_filler(self):
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        ev["mechanism_summary"] = "Insufficient evidence to call this."
        self.assertEqual(evidence_quality_tier(ev), "low_information")

    def test_low_information_when_no_concrete_asset(self):
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        ev["beneficiary_tickers"] = []
        ev["loser_tickers"]       = []
        ev["assets_to_watch"]     = []
        self.assertEqual(evidence_quality_tier(ev), "low_information")

    def test_non_dict_input_is_low_information(self):
        from low_information_gate import evidence_quality_tier
        self.assertEqual(evidence_quality_tier(None), "low_information")
        self.assertEqual(evidence_quality_tier("garbage"), "low_information")

    def test_tier_is_read_only(self):
        """``evidence_quality_tier`` must not mutate the input event."""
        from low_information_gate import evidence_quality_tier
        ev = self._full_actionable()
        before = copy.deepcopy(ev)
        _ = evidence_quality_tier(ev)
        self.assertEqual(ev, before)

    def test_tier_vocabulary_is_closed(self):
        """The function returns one of the three pinned tier values
        regardless of input shape."""
        from low_information_gate import (
            EVIDENCE_QUALITY_TIERS, evidence_quality_tier,
        )
        for ev in (None, {}, self._full_actionable()):
            self.assertIn(evidence_quality_tier(ev), EVIDENCE_QUALITY_TIERS)


# ---------------------------------------------------------------------------
# Counterforce / blocker discipline
# ---------------------------------------------------------------------------

def _force(force, **overrides):
    base = {
        "force": force, "actor": "Saudi Aramco", "likelihood": "medium",
    }
    base.update(overrides)
    return base


def _discipline_event(**overrides):
    """Builder for blocker-discipline tests — base event has the
    standard Gulf-Coast supply-cut thesis with one counterforce."""
    base = _consistency_event(
        counterforces=[
            _force("Saudi cabinet votes to walk back the lifting cut",
                   actor="Saudi Council", likelihood="medium"),
        ],
    )
    base.update(overrides)
    return base


class TestCounterforceBlockerDiscipline(unittest.TestCase):
    """counterforces / blockers must be concrete and, when high-
    likelihood, must be reflected in proof / falsifier coverage."""

    def test_concrete_counterforce_kept(self):
        ev = _discipline_event()
        from analyze_event import _clean_counterforces
        cleaned = _clean_counterforces(ev["counterforces"])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["actor"], "Saudi Council")

    def test_generic_uncertainty_dropped_by_sanitizer(self):
        from analyze_event import _clean_counterforces
        cleaned = _clean_counterforces([
            _force("Geopolitical tensions persist", actor="Various"),
            _force("Macro headwinds may pressure margins", actor="Markets"),
            _force("Risk factors remain", actor="Investors"),
            _force("Sentiment shifts negative", actor="The market"),
            _force("Concrete: PDVSA issues operational-delay statement",
                   actor="PDVSA", likelihood="high"),
        ])
        # Only the concrete entry survives.
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["actor"], "PDVSA")

    def test_blocker_kind_and_chain_hop_preserved(self):
        from analyze_event import _clean_counterforces
        cleaned = _clean_counterforces([
            {
                "force": "PDVSA infrastructure failure interrupts liftings",
                "actor": "PDVSA", "likelihood": "high",
                "kind": "blocker",
                "chain_hop": "step 2: heavy-sour feedstock supply",
            },
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["kind"], "blocker")
        self.assertEqual(
            cleaned[0]["chain_hop"], "step 2: heavy-sour feedstock supply",
        )

    def test_invalid_kind_dropped_keeps_legacy_shape(self):
        """An unknown ``kind`` token is dropped; the legacy three-key
        triplet still passes through."""
        from analyze_event import _clean_counterforces
        cleaned = _clean_counterforces([
            {
                "force": "Concrete blocker text",
                "actor": "Saudi Aramco", "likelihood": "medium",
                "kind": "obstacle",  # not in enum
            },
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertNotIn("kind", cleaned[0])

    def test_high_risk_blocker_with_proof_coverage_clears(self):
        """A high-likelihood blocker covered by a proof item that
        names the same actor / signal — discipline gate passes."""
        ev = _discipline_event(
            counterforces=[
                {
                    "force": "PDVSA infrastructure failure interrupts liftings",
                    "actor": "PDVSA", "likelihood": "high",
                    "kind": "blocker",
                },
            ],
            minimum_proof_set=[
                {"observation": "PDVSA issues operational-delay statement",
                 "channel": "commodities", "threshold": "any reversal",
                 "timing": "1-5d"},
            ],
        )
        result = evaluate_blocker_discipline(ev)
        self.assertEqual(result["blocker_count"], 1)
        self.assertEqual(result["high_risk_uncovered"], [])
        self.assertIsNone(result["downgrade"])

    def test_high_risk_blocker_without_coverage_signals_watch_only(self):
        """A high-likelihood blocker that has no proof / falsifier
        item naming its actor / signal flips the audit to
        watch_only."""
        ev = _discipline_event(
            counterforces=[
                {
                    "force": "PDVSA infrastructure failure interrupts liftings",
                    "actor": "PDVSA", "likelihood": "high",
                    "kind": "blocker",
                },
            ],
            # Proof item tests a different signal (the WCS spread),
            # not the blocker.
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities"},
            ],
            key_falsifiers=[],
        )
        result = evaluate_blocker_discipline(ev)
        self.assertEqual(len(result["high_risk_uncovered"]), 1)
        self.assertEqual(result["downgrade"], "watch_only")

    def test_multiple_uncovered_blockers_no_proof_signals_low_info(self):
        """≥2 high-likelihood blockers AND no proof / falsifier text
        anywhere → the thesis is structurally untestable, downgrade
        to low_information."""
        ev = _discipline_event(
            counterforces=[
                {
                    "force": "PDVSA capacity collapse cuts liftings to zero",
                    "actor": "PDVSA", "likelihood": "high",
                    "kind": "blocker",
                },
                {
                    "force": "Congress revokes the Treasury licence",
                    "actor": "US Congress", "likelihood": "high",
                    "kind": "blocker",
                },
            ],
            minimum_proof_set=[],
            key_falsifiers=[],
            critical_breakpoints=[],
        )
        result = evaluate_blocker_discipline(ev)
        self.assertEqual(result["downgrade"], "low_information")

    def test_medium_likelihood_blocker_does_not_require_coverage(self):
        """Discipline only fires on HIGH-likelihood entries — a
        medium-likelihood blocker is observation, not invalidator."""
        ev = _discipline_event(
            counterforces=[
                {
                    "force": "PDVSA may have minor operational issues",
                    "actor": "PDVSA", "likelihood": "medium",
                    "kind": "blocker",
                },
            ],
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities"},
            ],
        )
        result = evaluate_blocker_discipline(ev)
        self.assertEqual(result["blocker_count"], 1)
        self.assertIsNone(result["downgrade"])

    def test_response_shape_unchanged(self):
        """The discipline gate is read-only; counterforces dict shape
        stays stable (legacy keys present, new keys optional)."""
        ev = _discipline_event(
            counterforces=[
                {
                    "force": "Concrete blocker text",
                    "actor": "PDVSA", "likelihood": "high",
                    "kind": "blocker",
                    "chain_hop": "step 2",
                },
            ],
        )
        before_keys = set(ev["counterforces"][0].keys())
        evaluate_blocker_discipline(ev)
        self.assertEqual(set(ev["counterforces"][0].keys()), before_keys)


class TestTierAwareProofGenerator(unittest.TestCase):
    """``proof_set_for_event`` and ``falsifier_set_for_event`` scope
    the deterministic family-level generators by evidence-quality tier
    and by the event's named transmission channel.  Stable item shape
    across all three tiers; only the count and the watch-prefix differ.
    """

    def _actionable_event(self):
        """Event in the actionable tier — passes the low-info gate AND
        carries primary_thesis + asset rationale + proof/falsifier.
        Channels are named via ``expected_first_order_channels`` so the
        chain validator's strict 5-field hop contract isn't relevant."""
        ev = _event(mechanism_family="commodity_squeeze")
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi liftings cut tightens Gulf coker feedstock; "
                "WCS heavy-sour discount widens; CVX margins lift."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "CVX", "rank": 1,
             "rationale": "Gulf coker — heavy-sour feedstock benefits."},
        ]
        ev["expected_first_order_channels"]  = ["commodities", "equities"]
        ev["expected_second_order_channels"] = ["rates", "fx"]
        ev["transmission_path"] = []
        return ev

    def _watch_only_event(self):
        """Tier collapses to watch_only: valid mechanism + asset but
        lacks committed primary_thesis OR proof/falsifier."""
        ev = self._actionable_event()
        ev["competing_thesis"] = {}
        ev["minimum_proof_set"] = []
        ev["key_falsifiers"]    = []
        return ev

    def _low_info_event(self):
        ev = self._actionable_event()
        ev["mechanism_summary"] = "Insufficient evidence to characterise."
        return ev

    # ------- proof_set_for_event -------

    def test_actionable_returns_full_family_set(self):
        from low_information_gate import proof_set_for_event
        from mechanism_family import proof_set_for_family

        ev = self._actionable_event()
        full_family = proof_set_for_family("commodity_squeeze")
        # Channels named on the event: commodities + equities. The
        # family's primary rows live on those channels, so the channel
        # filter is a no-op here.
        out = proof_set_for_event(ev)
        # Same item shape (channel/expected_direction/timing/why_it_matters).
        for item in out:
            self.assertEqual(
                set(item.keys()),
                {"channel", "expected_direction", "timing", "why_it_matters"},
            )
        # Actionable should not be capped — at least as many items as
        # the family generator emits for in-channel rows.
        self.assertGreaterEqual(len(out), 2)
        # No "Watch:" prefix on actionable items.
        for item in out:
            self.assertFalse(item["why_it_matters"].startswith("Watch:"))
        # Items came from the family-level generator (subset relation).
        family_keys = {(i["channel"], i["expected_direction"], i["timing"])
                       for i in full_family}
        out_keys    = {(i["channel"], i["expected_direction"], i["timing"])
                       for i in out}
        self.assertTrue(out_keys.issubset(family_keys))

    def test_watch_only_capped_at_two_with_watch_prefix(self):
        from low_information_gate import proof_set_for_event
        out = proof_set_for_event(self._watch_only_event())
        self.assertLessEqual(len(out), 2)
        self.assertGreaterEqual(len(out), 1)
        for item in out:
            self.assertTrue(
                item["why_it_matters"].startswith("Watch:"),
                f"watch_only item missing 'Watch:' prefix: {item}",
            )
            # Item shape unchanged.
            self.assertEqual(
                set(item.keys()),
                {"channel", "expected_direction", "timing", "why_it_matters"},
            )

    def test_low_information_returns_empty(self):
        from low_information_gate import proof_set_for_event
        out = proof_set_for_event(self._low_info_event())
        self.assertEqual(out, [])

    def test_proof_items_map_to_named_transmission_channel(self):
        """Generated items must land on a channel the event's chain
        actually names — never an off-chain channel."""
        from low_information_gate import proof_set_for_event

        ev = self._actionable_event()
        # Restrict the chain to commodities only.
        ev["expected_first_order_channels"]  = ["commodities"]
        ev["expected_second_order_channels"] = []
        ev["transmission_path"] = []
        out = proof_set_for_event(ev)
        self.assertGreater(len(out), 0)
        for item in out:
            self.assertEqual(item["channel"], "commodities")

    # ------- falsifier_set_for_event -------

    def test_falsifier_actionable_returns_family_subset(self):
        from low_information_gate import falsifier_set_for_event
        out = falsifier_set_for_event(self._actionable_event())
        self.assertGreater(len(out), 0)
        for item in out:
            self.assertEqual(
                set(item.keys()),
                {"channel", "trigger_condition", "timing",
                 "why_it_breaks_thesis"},
            )
            self.assertFalse(item["why_it_breaks_thesis"].startswith("Watch:"))

    def test_falsifier_watch_only_capped_with_prefix(self):
        from low_information_gate import falsifier_set_for_event
        out = falsifier_set_for_event(self._watch_only_event())
        self.assertLessEqual(len(out), 2)
        for item in out:
            self.assertTrue(
                item["why_it_breaks_thesis"].startswith("Watch:"),
                f"watch_only falsifier missing prefix: {item}",
            )

    def test_falsifier_low_information_returns_empty(self):
        from low_information_gate import falsifier_set_for_event
        out = falsifier_set_for_event(self._low_info_event())
        self.assertEqual(out, [])

    def test_non_dict_input_returns_empty(self):
        from low_information_gate import (
            falsifier_set_for_event, proof_set_for_event,
        )
        self.assertEqual(proof_set_for_event(None), [])
        self.assertEqual(proof_set_for_event("garbage"), [])
        self.assertEqual(falsifier_set_for_event(None), [])
        self.assertEqual(falsifier_set_for_event(123), [])


# ---------------------------------------------------------------------------
# Causal-strength scoring + weak-chain proof clearing
# ---------------------------------------------------------------------------

class TestCausalStrength(unittest.TestCase):
    """Internal 5-prong score that drives the actionable / watch_only /
    low_information tier choice and clears proof / falsifier structure
    for chains too thin to support testable claims."""

    def test_full_score_on_well_formed_event(self):
        cs = compute_causal_strength(_event())
        self.assertEqual(cs["score"], 5.0)
        self.assertEqual(cs["max_score"], 5.0)
        for prong in (
            "trigger", "channel", "constraint", "actor", "market_expression",
        ):
            self.assertTrue(
                cs["components"][prong],
                f"prong {prong!r} should be satisfied on a clean event",
            )

    def test_missing_prong_drops_score_by_one(self):
        ev = _event(what_changed="")
        cs = compute_causal_strength(ev)
        self.assertEqual(cs["score"], 4.0)
        self.assertFalse(cs["components"]["trigger"])

    def test_vague_mechanism_collapses_score(self):
        ev = _event(
            mechanism_summary=(
                "Markets price risk into the curve and investors react."
            ),
        )
        cs = compute_causal_strength(ev)
        self.assertEqual(cs["score"], 0.0)

    def test_score_drives_low_info_threshold(self):
        """≥3 prongs missing → score < 3 → low_information."""
        ev = _event(
            what_changed="",
            transmission_path=[],
            expected_first_order_channels=[],
            beneficiaries=[],
            losers=[],
        )
        cs = compute_causal_strength(ev)
        self.assertLess(cs["score"], 3.0)
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "weak_mechanism")

    def test_score_4_drives_watch_only_not_low_info(self):
        """1 prong missing → score 4 → watch_only band; the boolean
        gate explicitly does NOT fire low_info on a single missing
        prong any more."""
        from low_information_gate import evidence_quality_tier
        ev = _event(what_changed="")
        # Add the actionable surface so the watch_only fallback path
        # is what's left after the score-band check.
        ev.update({
            "competing_thesis": {"primary_thesis": "Saudi cut tightens Gulf feedstock; XOM margins widen on WCS spread."},
            "primary_assets": [
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct Gulf Coast heavy-sour refiner — WCS spread widens."},
            ],
        })
        self.assertFalse(evaluate_low_information(ev)["is_low_info"])
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_score_5_with_actionable_surface_returns_actionable(self):
        from low_information_gate import evidence_quality_tier
        ev = _event(
            competing_thesis={
                "primary_thesis": (
                    "Saudi Aramco lifting cut tightens Gulf Coast "
                    "feedstock; XOM and CVX margins widen on the "
                    "WCS-WTI spread."
                ),
            },
            primary_assets=[
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct heavy-sour Gulf Coast refiner — WCS spread widens."},
            ],
        )
        cs = compute_causal_strength(ev)
        self.assertEqual(cs["score"], 5.0)
        self.assertEqual(evidence_quality_tier(ev), "actionable")

    def test_clear_weak_chain_proof_strips_lists_below_floor(self):
        """A chain at score < 4 cannot carry proof / falsifier
        structure — the helper empties the lists in place."""
        ev = _event(
            what_changed="",
            transmission_path=[],
            expected_first_order_channels=[],
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens 2pp",
                 "channel": "commodities"},
            ],
            key_falsifiers=[
                {"observation": "Saudis walk back the cut",
                 "channel": "commodities"},
            ],
            critical_breakpoints=[
                {"signal": "Aramco public statement", "channel": "commodities"},
            ],
        )
        cleared = clear_weak_chain_proof(ev)
        self.assertTrue(cleared)
        self.assertEqual(ev["minimum_proof_set"], [])
        self.assertEqual(ev["key_falsifiers"], [])
        self.assertEqual(ev["critical_breakpoints"], [])

    def test_clear_weak_chain_proof_noop_when_score_above_floor(self):
        """A chain with score 4 or 5 keeps its proof / falsifier
        structure — the helper returns False and mutates nothing."""
        ev = _event(
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens 2pp",
                 "channel": "commodities"},
            ],
        )
        before = list(ev["minimum_proof_set"])
        cleared = clear_weak_chain_proof(ev)
        self.assertFalse(cleared)
        self.assertEqual(ev["minimum_proof_set"], before)

    def test_response_shape_unchanged_by_score(self):
        """Score is INTERNAL — it must not be written onto the event."""
        ev = _event()
        before_keys = set(ev.keys())
        compute_causal_strength(ev)
        self.assertEqual(set(ev.keys()), before_keys)


# ---------------------------------------------------------------------------
# Regime-conditioned caveats
# ---------------------------------------------------------------------------

def _caveat(condition, effect, evidence, domain=None):
    out = {
        "condition": condition,
        "effect_on_thesis": effect,
        "evidence_to_revisit": evidence,
    }
    if domain:
        out["domain"] = domain
    return out


class TestRegimeCaveatSanitizer(unittest.TestCase):
    """Caveats live in ``hidden_mechanism.regime_caveats`` (optional
    list; output shape stays stable).  Each entry must carry the three
    required fields and may carry an enum ``domain``."""

    def test_concrete_caveats_pass_through(self):
        from analyze_event import _clean_regime_caveats
        cleaned = _clean_regime_caveats([
            _caveat(
                "HY spreads above 450bp",
                "Margin-stress pass-through amplified — banks fail to extend credit",
                "HY spreads tighten below 380bp within 5d",
                domain="credit",
            ),
            _caveat(
                "Real yields above 1.8% on the 5y",
                "Long-duration semi multiples already compressed; reprice faster",
                "Real yields drop >20bp within 5d",
                domain="rates",
            ),
        ])
        self.assertEqual(len(cleaned), 2)
        self.assertEqual(cleaned[0]["domain"], "credit")
        self.assertEqual(cleaned[1]["domain"], "rates")
        for entry in cleaned:
            self.assertIn("condition", entry)
            self.assertIn("effect_on_thesis", entry)
            self.assertIn("evidence_to_revisit", entry)

    def test_vague_caveat_dropped(self):
        from analyze_event import _clean_regime_caveats
        cleaned = _clean_regime_caveats([
            # Vague condition — broader market conditions placeholder.
            _caveat(
                "Broader market conditions remain stable",
                "Thesis amplified",
                "Watch credit spreads",
            ),
            # Vague effect — sentiment-shift placeholder.
            _caveat(
                "Real yields above 1.8%",
                "Sentiment shifts away from the thesis",
                "Real yields drop >20bp",
            ),
            # Vague evidence — depends-on-outcome placeholder.
            _caveat(
                "HY spreads above 450bp",
                "Thesis weakens as credit tightens",
                "Outcome depends on response from policy",
            ),
            # Concrete entry — survives.
            _caveat(
                "DXY above 105",
                "Dollar-strength regime blunts the cascade",
                "DXY closes below 102 within 5d",
                domain="fx",
            ),
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]["domain"], "fx")

    def test_missing_required_field_drops_entry(self):
        from analyze_event import _clean_regime_caveats
        cleaned = _clean_regime_caveats([
            {
                "condition": "Real yields above 1.8%",
                "effect_on_thesis": "Thesis amplified",
                # missing evidence_to_revisit
            },
            _caveat(
                "Real yields above 1.8%",
                "Thesis amplified — front-end already restrictive",
                "Real yields drop >20bp",
            ),
        ])
        self.assertEqual(len(cleaned), 1)

    def test_invalid_domain_dropped_entry_kept(self):
        from analyze_event import _clean_regime_caveats
        cleaned = _clean_regime_caveats([
            _caveat(
                "Real yields above 1.8%",
                "Thesis amplified",
                "Real yields drop >20bp",
                domain="random_token",
            ),
        ])
        self.assertEqual(len(cleaned), 1)
        self.assertNotIn("domain", cleaned[0])

    def test_caveats_capped_at_three(self):
        from analyze_event import _clean_regime_caveats
        cleaned = _clean_regime_caveats([
            _caveat(
                f"Condition {i}", f"Effect {i} amplified",
                f"Evidence {i} watch closely",
                domain="rates",
            )
            for i in range(6)
        ])
        self.assertLessEqual(len(cleaned), 3)


class TestRegimeCaveatMateriality(unittest.TestCase):
    """When a caveat materially weakens the thesis (regime flip would
    break / blunt / reverse the chain), the tier system must NOT
    return ``actionable``."""

    def _actionable_event(self, **caveat_overrides):
        ev = _consistency_event()
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "XOM and CVX margins widen on the WCS-WTI spread."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops."},
        ]
        if caveat_overrides:
            ev.setdefault("hidden_mechanism", {})
            ev["hidden_mechanism"] = {
                **ev["hidden_mechanism"],
                "regime_caveats": [caveat_overrides],
            }
        return ev

    def test_no_caveats_does_not_weaken(self):
        ev = self._actionable_event()
        self.assertFalse(regime_caveats_weaken_thesis(ev))

    def test_weakening_verb_signals_weakening(self):
        for verb_phrase in (
            "Thesis weakens as credit tightens",
            "Cascade blunts at the second-order leg",
            "Spread move reverses on policy backstop",
            "Pass-through stalls in tight liquidity",
            "Margin signal fades within 5d",
            "No transmission to refining margins",
        ):
            ev = self._actionable_event(
                condition="HY spreads above 450bp",
                effect_on_thesis=verb_phrase,
                evidence_to_revisit="HY spreads tighten below 380bp",
            )
            self.assertTrue(
                regime_caveats_weaken_thesis(ev),
                f"weakening phrase {verb_phrase!r} should be detected",
            )

    def test_amplifying_caveat_does_not_weaken(self):
        """A regime that AMPLIFIES the thesis isn't a weakening
        signal — actionable can still be reached."""
        ev = self._actionable_event(
            condition="Real yields above 1.8%",
            effect_on_thesis=(
                "Thesis amplified — long-duration multiples reprice faster"
            ),
            evidence_to_revisit="Real yields drop >20bp within 5d",
        )
        self.assertFalse(regime_caveats_weaken_thesis(ev))

    def test_weakening_caveat_caps_tier_at_watch_only(self):
        """End-to-end: a weakening caveat keeps the tier from reaching
        ``actionable`` even when the rest of the analysis would qualify."""
        from low_information_gate import evidence_quality_tier
        ev = self._actionable_event(
            condition="HY spreads above 450bp",
            effect_on_thesis="Thesis breaks the chain at margin pass-through",
            evidence_to_revisit="HY spreads tighten below 380bp within 5d",
            domain="credit",
        )
        # The base actionable event would otherwise reach actionable
        # — assert the caveat caps it to watch_only.
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_response_shape_stable(self):
        """Adding regime_caveats inside hidden_mechanism keeps the
        outer shape unchanged — no new top-level keys."""
        ev = self._actionable_event(
            condition="HY spreads above 450bp",
            effect_on_thesis="Thesis amplified",
            evidence_to_revisit="HY spreads tighten below 380bp",
        )
        before_keys = set(ev.keys())
        # Materiality check is read-only.
        regime_caveats_weaken_thesis(ev)
        self.assertEqual(set(ev.keys()), before_keys)


# ---------------------------------------------------------------------------
# Chain-family consistency
# ---------------------------------------------------------------------------

def _hop(channel, *, action="actor takes action", actor="Saudi Aramco",
         effect="WCS-WTI spread widens"):
    return {
        "hop": action,
        "action": action,
        "actor": actor,
        "channel": channel,
        "expected_market_effect": effect,
        "timing": "1-5d",
    }


class TestChainFamilyConsistency(unittest.TestCase):
    """``transmission_path`` channels must match the committed
    ``mechanism_family``.  An off-family share signals the LLM picked
    the wrong family or articulated the wrong cascade."""

    def test_clean_chain_no_downgrade(self):
        ev = {
            "mechanism_family": "supply_shock",
            "transmission_path": [
                _hop("supply"),
                _hop("pricing_power"),
                _hop("substitution"),
            ],
        }
        result = evaluate_chain_family_consistency(ev)
        self.assertEqual(result["off_family"], 0)
        self.assertIsNone(result["downgrade"])

    def test_no_family_skips_audit(self):
        """Family ``"none"`` (or empty) means no committed family —
        the audit returns the empty result without flagging anything."""
        ev = {
            "mechanism_family": "none",
            "transmission_path": [
                _hop("rate_transmission"),
                _hop("capital_flow"),
            ],
        }
        result = evaluate_chain_family_consistency(ev)
        self.assertEqual(result["off_family"], 0)
        self.assertIsNone(result["downgrade"])

    def test_unclassified_hop_counts_as_off_family(self):
        """A hop whose channel is 'unclassified' (sanitizer fallback
        for a non-canonical token like 'risk sentiment') is always
        off-family for any committed canonical family."""
        ev = {
            "mechanism_family": "supply_shock",
            "transmission_path": [
                _hop("supply"),
                _hop("unclassified"),  # generic hop
                _hop("substitution"),
            ],
        }
        result = evaluate_chain_family_consistency(ev)
        self.assertEqual(result["off_family"], 1)

    def test_partial_off_family_signals_watch_only(self):
        """≥40% off-family but <60% → watch_only."""
        ev = {
            "mechanism_family": "supply_shock",
            "transmission_path": [
                _hop("supply"),                # on-family
                _hop("rate_transmission"),     # off-family
                _hop("capital_flow"),          # off-family
                _hop("substitution"),          # on-family
                _hop("pricing_power"),         # on-family
            ],
        }
        result = evaluate_chain_family_consistency(ev)
        self.assertGreaterEqual(result["rate"], 0.4)
        self.assertLess(result["rate"], 0.6)
        self.assertEqual(result["downgrade"], "watch_only")

    def test_majority_off_family_signals_low_information(self):
        """≥60% off-family → low_information."""
        ev = {
            "mechanism_family": "supply_shock",
            "transmission_path": [
                _hop("rate_transmission"),     # off-family
                _hop("capital_flow"),          # off-family
                _hop("regulatory"),            # off-family
                _hop("supply"),                # on-family
            ],
        }
        result = evaluate_chain_family_consistency(ev)
        self.assertGreaterEqual(result["rate"], 0.6)
        self.assertEqual(result["downgrade"], "low_information")

    def test_off_family_chain_caps_tier_at_watch_only(self):
        """End-to-end: an event whose chain conflicts with its family
        cannot reach ``actionable`` — tier caps at watch_only."""
        from low_information_gate import evidence_quality_tier
        ev = _consistency_event()
        ev["mechanism_family"] = "supply_shock"
        ev["transmission_path"] = [
            _hop("supply"),                # on-family
            _hop("rate_transmission"),     # off-family
            _hop("capital_flow"),          # off-family
        ]
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "XOM and CVX margins widen on the WCS-WTI spread."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops."},
        ]
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_response_shape_unchanged(self):
        """Audit is read-only — does not mutate the event dict."""
        ev = {
            "mechanism_family": "supply_shock",
            "transmission_path": [
                _hop("supply"),
                _hop("rate_transmission"),
            ],
        }
        before_keys = set(ev.keys())
        evaluate_chain_family_consistency(ev)
        self.assertEqual(set(ev.keys()), before_keys)


class TestSubtypeAwareProofGenerator(unittest.TestCase):
    """``proof_set_for_event`` and ``falsifier_set_for_event`` honour
    a stored ``mechanism_subtype`` (or one inferred from prose) and
    produce subtype-tightened items.  Output shape is identical to
    the family-level generators."""

    def _actionable_event(self, **overrides):
        ev = _event(mechanism_family="sanction")
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Russian crude sanction tightens supply; USO premium widens."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "CVX", "rank": 1,
             "rationale": "Gulf coker — heavy-sour beneficiary."},
        ]
        # Channels must live on the first-order pack — that's what
        # ``_named_transmission_channels`` reads for the channel
        # filter.  Cover the full sanction matrix here so the
        # fall-back test can compare against the family default.
        ev["expected_first_order_channels"]  = [
            "commodities", "fx", "equities", "credit", "vol",
        ]
        ev["expected_second_order_channels"] = []
        ev["transmission_path"] = []
        ev.update(overrides)
        return ev

    def test_stored_subtype_specializes_named_assets(self):
        """When ``mechanism_subtype`` is stored on the event, the
        proof set pulls the subtype's primary_overrides — for
        oil_sanction the named_assets become USO/BNO and the rationale
        references them."""
        from low_information_gate import proof_set_for_event

        ev = self._actionable_event()
        ev["mechanism_subtype"] = "oil_sanction"
        out = proof_set_for_event(ev)
        self.assertTrue(out)
        commodities_items = [i for i in out if i["channel"] == "commodities"]
        self.assertTrue(commodities_items)
        why = commodities_items[0]["why_it_matters"]
        self.assertTrue(
            "USO" in why or "BNO" in why,
            f"expected USO/BNO in oil_sanction rationale: {why!r}",
        )

    def test_subtype_can_be_inferred_from_prose(self):
        """When ``mechanism_subtype`` is missing the generator infers
        it from mechanism_summary + what_changed via
        ``infer_mechanism_subtype``."""
        from low_information_gate import proof_set_for_event

        ev = self._actionable_event(
            mechanism_summary=(
                "Russian oil sanction tightens crude supply; refining "
                "feedstock cost rises and the spread widens."
            ),
            what_changed="Russian oil sanction announced overnight.",
        )
        out = proof_set_for_event(ev)
        commodities_items = [i for i in out if i["channel"] == "commodities"]
        self.assertTrue(commodities_items)
        self.assertTrue(
            any("USO" in i["why_it_matters"] or "BNO" in i["why_it_matters"]
                for i in commodities_items),
            "inferred oil_sanction subtype should specialize commodities rationale",
        )

    def test_no_subtype_falls_back_to_family_level(self):
        """When the family has subtypes but none match, the generator
        returns the family-level matrix unchanged — preserves prior
        behaviour for callers that haven't been threaded through."""
        from low_information_gate import proof_set_for_event
        from mechanism_family import proof_set_for_family

        ev = self._actionable_event(
            mechanism_summary=(
                "Generic sanction announcement on a counterparty; "
                "premium widens via standard supply-side discount."
            ),
            what_changed="Generic sanction announcement.",
        )
        out = proof_set_for_event(ev)
        family_default = proof_set_for_family("sanction")
        out_channels    = sorted({i["channel"] for i in out})
        family_channels = sorted({i["channel"] for i in family_default
                                  if i["channel"] in
                                  {"commodities", "fx", "equities",
                                   "credit", "vol"}})
        self.assertEqual(out_channels, family_channels)

    def test_off_subtype_channel_rejected(self):
        """When subtype is oil_sanction (commodities-focused) and the
        transmission chain restricts to commodities, every emitted
        proof item must land on commodities — items targeting any
        other subtype's channel are rejected."""
        from low_information_gate import proof_set_for_event

        ev = self._actionable_event()
        ev["mechanism_subtype"] = "oil_sanction"
        ev["expected_first_order_channels"]  = ["commodities"]
        ev["expected_second_order_channels"] = []
        out = proof_set_for_event(ev)
        for item in out:
            self.assertEqual(
                item["channel"], "commodities",
                f"off-subtype-channel item leaked: {item}",
            )

    def test_multi_channel_coverage_preserved_under_subtype(self):
        """When the event's chain spans the subtype channel +
        cascade channels, the subtype filter does not collapse to
        empty — multi-channel coverage rule still holds."""
        from low_information_gate import proof_set_for_event

        ev = self._actionable_event()
        ev["mechanism_subtype"] = "oil_sanction"
        ev["expected_first_order_channels"]  = ["commodities", "credit"]
        ev["expected_second_order_channels"] = []
        out = proof_set_for_event(ev)
        channels = {i["channel"] for i in out}
        self.assertIn("commodities", channels)
        self.assertGreater(
            len(channels), 0,
            "subtype filter must not collapse to empty when cascade is allowed",
        )

    def test_falsifier_subtype_aware(self):
        """``falsifier_set_for_event`` passes subtype through to the
        family generator AND applies the subtype channel filter."""
        from low_information_gate import falsifier_set_for_event

        ev = self._actionable_event()
        ev["mechanism_subtype"] = "oil_sanction"
        ev["expected_first_order_channels"]  = ["commodities"]
        ev["expected_second_order_channels"] = []
        out = falsifier_set_for_event(ev)
        for item in out:
            self.assertEqual(item["channel"], "commodities")
            self.assertEqual(
                set(item.keys()),
                {"channel", "trigger_condition", "timing",
                 "why_it_breaks_thesis"},
            )


# ---------------------------------------------------------------------------
# Confidence calibration — derived from evidence quality
# ---------------------------------------------------------------------------

class TestCalibrateConfidence(unittest.TestCase):
    """``calibrate_confidence`` maps the evidence-quality tier + proof /
    falsifier coverage back to the existing ``low | medium | high``
    enum.  Replaces the previous LLM-prose-derived value with one
    anchored to the structural-evidence quality."""

    def _full_actionable(self, **overrides):
        ev = _consistency_event()
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "XOM and CVX margins widen on the WCS-WTI spread."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops."},
        ]
        ev.update(overrides)
        return ev

    def test_low_information_event_is_low_confidence(self):
        from low_information_gate import calibrate_confidence
        ev = _event(mechanism_summary="Insufficient evidence.")
        self.assertEqual(calibrate_confidence(ev), "low")

    def test_watch_only_event_is_medium_confidence(self):
        from low_information_gate import calibrate_confidence
        # Single missing prong → watch_only band → medium.
        ev = self._full_actionable(what_changed="")
        self.assertEqual(calibrate_confidence(ev), "medium")

    def test_actionable_with_proof_and_falsifier_is_high(self):
        from low_information_gate import calibrate_confidence
        ev = self._full_actionable()
        self.assertEqual(calibrate_confidence(ev), "high")

    def test_actionable_with_only_proof_is_medium(self):
        """Proof without a falsifier lacks the fast-break invalidator
        a high-conviction call needs — calibrated to medium."""
        from low_information_gate import calibrate_confidence
        ev = self._full_actionable(key_falsifiers=[])
        self.assertEqual(calibrate_confidence(ev), "medium")

    def test_actionable_with_only_falsifier_is_medium(self):
        from low_information_gate import calibrate_confidence
        ev = self._full_actionable(minimum_proof_set=[])
        self.assertEqual(calibrate_confidence(ev), "medium")

    def test_actionable_with_neither_is_medium(self):
        from low_information_gate import calibrate_confidence
        ev = self._full_actionable(
            minimum_proof_set=[], key_falsifiers=[],
        )
        self.assertEqual(calibrate_confidence(ev), "medium")

    def test_non_dict_input_returns_low(self):
        from low_information_gate import calibrate_confidence
        for bad in (None, "x", 5, []):
            self.assertEqual(calibrate_confidence(bad), "low")

    def test_calibrate_does_not_mutate_event(self):
        from low_information_gate import calibrate_confidence
        ev = self._full_actionable(confidence="high")
        before_keys = set(ev.keys())
        before_confidence = ev["confidence"]
        calibrate_confidence(ev)
        self.assertEqual(set(ev.keys()), before_keys)
        self.assertEqual(ev["confidence"], before_confidence)


class TestCalibrationFinalizeWiring(unittest.TestCase):
    """End-to-end: ``_finalize_analysis`` overrides ``confidence``
    with the calibrated value regardless of what the LLM emitted."""

    def _build(self, parsed_overrides) -> dict:
        from analyze_event import _finalize_analysis
        parsed = {
            "what_changed": (
                "Saudi Aramco cut crude liftings by 1mbd from August "
                "contract volumes, tightening Gulf Coast feedstock supply."
            ),
            "mechanism_summary": (
                "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
                "Coast refinery feedstock and widening WCS-WTI heavy-sour "
                "discount."
            ),
            "beneficiaries": ["XOM"],
            "losers": ["SU"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["SU"],
            "mechanism_family": "supply_normalization",
            "confidence": "high",
            # Existing _validate_result downgrade rule: transmission_chain
            # must be >=3 steps to keep "high".  Supply enough so the
            # post-calibration step doesn't strip back to medium.
            "transmission_chain": [
                "Saudi Aramco cuts crude liftings by 1mbd",
                "Gulf Coast refinery feedstock supply tightens",
                "WCS-WTI heavy-sour discount widens; XOM margins lift",
            ],
            "competing_thesis": {
                "primary_thesis": (
                    "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                    "XOM and SU margins reprice on the WCS-WTI spread."
                ),
            },
            "primary_assets": [
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops as WCS discount widens."},
            ],
            "minimum_proof_set": [
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities", "threshold": "≥2pp",
                 "timing": "5-20d"},
            ],
            "key_falsifiers": [
                "Saudis publicly walk back the lifting cut within 5d",
            ],
        }
        parsed.update(parsed_overrides)
        return _finalize_analysis(
            parsed, headline="Saudi Aramco cuts crude liftings",
            stage="realized", persistence="medium",
        )

    def test_actionable_keeps_high_when_coverage_present(self):
        out = self._build({"confidence": "high"})
        self.assertEqual(out["confidence"], "high")

    def test_low_info_path_forces_low_regardless_of_llm(self):
        """LLM emits 'high' but the low-info gate fires — confidence
        is forced to low at finalize-time."""
        out = self._build({
            "confidence": "high",
            "mechanism_summary": "Insufficient evidence.",
        })
        self.assertEqual(out["confidence"], "low")

    def test_watch_only_caps_high_at_medium(self):
        """LLM emits 'high' but the missing-falsifier path drops the
        tier to actionable-without-coverage → calibrated medium."""
        out = self._build({
            "confidence": "high",
            "key_falsifiers": [],
        })
        self.assertEqual(out["confidence"], "medium")

    def test_warning_logged_when_confidence_was_changed(self):
        out = self._build({
            "confidence": "high",
            "key_falsifiers": [],
        })
        warnings = out.get("validation_warnings") or []
        self.assertTrue(
            any("confidence calibrated" in w for w in warnings),
            f"expected calibration warning in {warnings!r}",
        )

    def test_response_shape_unchanged(self):
        """Calibration changes the value at the existing ``confidence``
        key — no new top-level fields appear."""
        out = self._build({"confidence": "high"})
        # Confidence value is one of the canonical enum tokens.
        self.assertIn(out["confidence"], ("low", "medium", "high"))


class TestQualityWarningTags(unittest.TestCase):
    """Compact machine-readable warning tags for watch_only and
    low_information events.  Vocabulary closed; actionable events
    emit no tags."""

    def _watch_only_event(self, **overrides):
        """Base event that lands in watch_only or actionable depending
        on overrides — valid mechanism + tickers, with primary_thesis,
        rationale, proof, and falsifier so the actionable prongs
        clear by default."""
        ev = _event(
            mechanism_family="commodity_squeeze",
            beneficiary_tickers=["CVX"],
            primary_assets=[
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct-name primary."},
            ],
            minimum_proof_set=[
                {"observation": "spread widens", "channel": "commodities"},
            ],
            key_falsifiers=[
                {"observation": "spread collapses", "channel": "commodities"},
            ],
            competing_thesis={
                "primary_thesis": (
                    "Saudi crude liftings cut tightens Gulf coker "
                    "feedstock and widens WCS-WTI spread."
                ),
            },
        )
        ev.update(overrides)
        return ev

    def test_actionable_event_has_no_warnings(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        self.assertEqual(quality_warnings(ev), [])

    def test_weak_mechanism_tag(self):
        """Strip the channel + actor + market expression so the
        5-prong gate fails → mechanism judged weak."""
        from low_information_gate import quality_warnings
        ev = self._watch_only_event(
            mechanism_summary="Markets price risk on the announcement.",
            what_changed="Markets price risk on the announcement.",
        )
        self.assertIn("weak_mechanism", quality_warnings(ev))

    def test_missing_asset_rationale_tag(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        ev["primary_assets"] = []
        ev["competing_thesis"] = {}
        self.assertIn("missing_asset_rationale", quality_warnings(ev))

    def test_invalid_chain_tag(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        ev["transmission_path"] = [{"hop": "stuff happens"}]
        self.assertIn("invalid_chain", quality_warnings(ev))

    def test_no_observable_condition_tag(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        ev["minimum_proof_set"] = []
        ev["key_falsifiers"]    = []
        self.assertIn("no_observable_condition", quality_warnings(ev))

    def test_inconsistent_proof_tag(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Brazilian elections drive sovereign yields wider "
                "across Latin American counterparts overnight."
            ),
        }
        self.assertIn("inconsistent_proof", quality_warnings(ev))

    def test_broad_beta_only_tag(self):
        from low_information_gate import quality_warnings
        ev = self._watch_only_event()
        ev["primary_assets"] = []
        ev["competing_thesis"] = {}
        ev["market_tickers"] = [
            {"symbol": "XLE", "evidence_score": 0.85},
            {"symbol": "USO", "evidence_score": 0.85},
            {"symbol": "ITA", "evidence_score": 0.85},
        ]
        self.assertIn("broad_beta_only", quality_warnings(ev))

    def test_warning_vocabulary_is_closed(self):
        """Every emitted tag is in the controlled vocabulary."""
        from low_information_gate import (
            QUALITY_WARNING_TAGS, quality_warnings,
        )
        ev = self._watch_only_event()
        ev["primary_assets"]    = []
        ev["competing_thesis"]  = {}
        ev["minimum_proof_set"] = []
        ev["key_falsifiers"]    = []
        ev["transmission_path"] = [{"hop": "x"}]
        tags = quality_warnings(ev)
        self.assertGreater(len(tags), 0)
        for tag in tags:
            self.assertIn(tag, QUALITY_WARNING_TAGS)

    def test_non_dict_input_returns_empty(self):
        from low_information_gate import quality_warnings
        self.assertEqual(quality_warnings(None), [])
        self.assertEqual(quality_warnings("garbage"), [])

    def test_low_information_event_emits_warnings(self):
        """A low_information event also surfaces warnings — the field
        isn't gated to watch_only alone.  Use vague-mechanism prose
        ('markets price risk') to trip the 5-prong gate's vague
        check so weak_mechanism fires reliably."""
        from low_information_gate import quality_warnings
        ev = self._watch_only_event(
            mechanism_summary="Markets price risk on the announcement.",
            what_changed="Markets price risk on the announcement.",
        )
        tags = quality_warnings(ev)
        self.assertIn("weak_mechanism", tags)


# ---------------------------------------------------------------------------
# Source-quality discipline
# ---------------------------------------------------------------------------

class TestSourceQualitySanitizer(unittest.TestCase):
    """``hidden_mechanism.source_quality`` is an optional dict with
    enum-validated source_type / specificity / uncertainty_level
    plus optional ``evidence_limitations`` text."""

    def test_concrete_block_passes_through(self):
        from analyze_event import _clean_source_quality
        out = _clean_source_quality({
            "source_type":          "official_release",
            "specificity":          "high",
            "uncertainty_level":    "low",
            "evidence_limitations": "",
        })
        self.assertEqual(out["source_type"], "official_release")
        self.assertEqual(out["specificity"], "high")
        self.assertEqual(out["uncertainty_level"], "low")

    def test_rumor_low_specificity_kept(self):
        from analyze_event import _clean_source_quality
        out = _clean_source_quality({
            "source_type":          "rumor",
            "specificity":          "low",
            "uncertainty_level":    "high",
            "evidence_limitations": "Anonymous sources only.",
        })
        self.assertEqual(out["source_type"], "rumor")
        self.assertEqual(out["specificity"], "low")
        self.assertEqual(
            out["evidence_limitations"], "Anonymous sources only.",
        )

    def test_unknown_source_type_drops_block(self):
        from analyze_event import _clean_source_quality
        self.assertEqual(_clean_source_quality({
            "source_type":       "made_up",
            "specificity":       "high",
            "uncertainty_level": "low",
        }), {})

    def test_unknown_specificity_drops_block(self):
        from analyze_event import _clean_source_quality
        self.assertEqual(_clean_source_quality({
            "source_type":       "official_release",
            "specificity":       "vague",
            "uncertainty_level": "low",
        }), {})

    def test_missing_required_field_drops_block(self):
        from analyze_event import _clean_source_quality
        self.assertEqual(_clean_source_quality({
            "source_type": "official_release",
            "specificity": "high",
            # uncertainty_level missing
        }), {})

    def test_non_dict_drops_block(self):
        from analyze_event import _clean_source_quality
        self.assertEqual(_clean_source_quality(None), {})
        self.assertEqual(_clean_source_quality("text"), {})


class TestSourceQualityInference(unittest.TestCase):
    """``_infer_source_quality`` is a cheap keyword-based classifier
    that fills the source_quality block when the LLM didn't emit one.
    It reads only headline + what_changed text."""

    def test_high_specificity_marker_picks_official_release(self):
        from analyze_event import _infer_source_quality
        out = _infer_source_quality(
            "US Treasury issued a 6-month licence for Venezuelan crude liftings",
            "Treasury announced the policy at a press conference.",
        )
        self.assertEqual(out["specificity"], "high")
        self.assertEqual(out["source_type"], "official_release")
        self.assertEqual(out["uncertainty_level"], "low")

    def test_low_specificity_marker_picks_rumor(self):
        from analyze_event import _infer_source_quality
        out = _infer_source_quality(
            "Treasury reportedly considering carve-outs for Venezuelan crude",
            "Anonymous sources say a decision could come soon.",
        )
        self.assertEqual(out["specificity"], "low")
        self.assertEqual(out["source_type"], "rumor")
        self.assertEqual(out["uncertainty_level"], "high")

    def test_no_markers_fall_back_to_medium(self):
        from analyze_event import _infer_source_quality
        out = _infer_source_quality(
            "Crude oil markets in focus this week",
            "Multiple cross-currents shape the read.",
        )
        self.assertEqual(out["specificity"], "medium")
        self.assertEqual(out["source_type"], "analyst_view")

    def test_empty_input_returns_medium_default(self):
        from analyze_event import _infer_source_quality
        out = _infer_source_quality("", "")
        self.assertEqual(out["specificity"], "medium")
        self.assertEqual(out["source_type"], "analyst_view")


class TestSourceQualityTierGate(unittest.TestCase):
    """A low-specificity headline caps the tier at watch_only — it
    cannot ship as actionable regardless of the rest of the
    structure."""

    def test_low_specificity_caps_tier_at_watch_only(self):
        from low_information_gate import (
            evidence_quality_tier, source_quality_blocks_actionable,
        )
        ev = _consistency_event()
        ev["competing_thesis"] = {
            "primary_thesis": (
                "Saudi Aramco lifting cut tightens Gulf Coast feedstock; "
                "XOM and CVX margins widen on the WCS-WTI spread."
            ),
        }
        ev["primary_assets"] = [
            {"symbol": "XOM", "rank": 1,
             "rationale": "Direct heavy-sour Gulf Coast refiner — feedstock cost drops as WCS discount widens."},
        ]
        ev["hidden_mechanism"] = {
            "source_quality": {
                "source_type":          "rumor",
                "specificity":          "low",
                "uncertainty_level":    "high",
                "evidence_limitations": "Anonymous sources only.",
            },
        }
        self.assertTrue(source_quality_blocks_actionable(ev))
        self.assertEqual(evidence_quality_tier(ev), "watch_only")

    def test_high_specificity_does_not_block(self):
        from low_information_gate import source_quality_blocks_actionable
        ev = {
            "hidden_mechanism": {
                "source_quality": {
                    "source_type":       "official_release",
                    "specificity":       "high",
                    "uncertainty_level": "low",
                },
            },
        }
        self.assertFalse(source_quality_blocks_actionable(ev))

    def test_absent_block_does_not_block(self):
        from low_information_gate import source_quality_blocks_actionable
        self.assertFalse(source_quality_blocks_actionable({}))
        self.assertFalse(source_quality_blocks_actionable(
            {"hidden_mechanism": {}}
        ))


class TestSourceQualityFinalizeWiring(unittest.TestCase):
    """``_finalize_analysis`` infers source_quality from the headline
    when the LLM doesn't emit one, then runs the tier gate so a
    low-specificity headline cannot ship as actionable."""

    def _build(self, headline, **parsed_overrides):
        from analyze_event import _finalize_analysis
        parsed = {
            "what_changed": parsed_overrides.pop(
                "what_changed",
                "Treasury reportedly considering Venezuelan crude carve-outs",
            ),
            "mechanism_summary": (
                "Reported policy under consideration would tighten heavy-sour "
                "feedstock supply through the WCS-WTI heavy-sour discount."
            ),
            "beneficiaries": ["XOM"],
            "losers": ["SU"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["SU"],
            "mechanism_family": "supply_normalization",
            "confidence": "high",
            "transmission_chain": [
                "Treasury floats licence carve-out",
                "Heavy-sour feedstock supply tightens",
                "WCS-WTI discount widens",
            ],
            "competing_thesis": {
                "primary_thesis": (
                    "Reported Treasury carve-out tightens Gulf Coast "
                    "feedstock supply; XOM margins widen on the "
                    "WCS-WTI spread."
                ),
            },
            "primary_assets": [
                {"symbol": "XOM", "rank": 1,
                 "rationale": "Direct heavy-sour Gulf Coast refiner — "
                              "feedstock cost drops as WCS discount widens."},
            ],
            "minimum_proof_set": [
                {"observation": "WCS-WTI discount widens by 2pp",
                 "channel": "commodities", "threshold": "≥2pp",
                 "timing": "5-20d"},
            ],
            "key_falsifiers": [
                "Saudis publicly walk back the lifting cut within 5d",
            ],
        }
        parsed.update(parsed_overrides)
        return _finalize_analysis(
            parsed, headline=headline, stage="anticipation",
            persistence="medium",
        )

    def test_rumor_headline_blocks_actionable(self):
        out = self._build(
            "Treasury reportedly weighing Venezuelan crude carve-outs",
        )
        sq = (out.get("hidden_mechanism") or {}).get("source_quality") or {}
        self.assertEqual(sq.get("specificity"), "low")
        # Confidence calibrated down from "high" because tier was
        # capped at watch_only by the source-quality gate.
        self.assertNotEqual(out["confidence"], "high")

    def test_official_release_keeps_actionable_path(self):
        out = self._build(
            "US Treasury issued 6-month licence for Venezuelan crude liftings",
            what_changed=(
                "US Treasury issued a 6-month licence for Venezuelan crude "
                "liftings; restoration of heavy-sour feedstock supply."
            ),
        )
        sq = (out.get("hidden_mechanism") or {}).get("source_quality") or {}
        self.assertEqual(sq.get("specificity"), "high")
        self.assertEqual(sq.get("source_type"), "official_release")

    def test_inferred_block_does_not_overwrite_llm_value(self):
        """When the LLM emitted a source_quality block, the
        finalize-time inference must NOT overwrite it."""
        out = self._build(
            "Treasury reportedly considering carve-outs",
            hidden_mechanism={
                "source_quality": {
                    "source_type":       "official_release",
                    "specificity":       "high",
                    "uncertainty_level": "low",
                },
            },
        )
        sq = (out.get("hidden_mechanism") or {}).get("source_quality") or {}
        # LLM-emitted "high" survives even though headline reads as
        # rumor — explicit beats inference.
        self.assertEqual(sq.get("specificity"), "high")

    def test_response_shape_unchanged(self):
        """Source quality lives inside hidden_mechanism — no new
        top-level keys appear."""
        out = self._build(
            "US Treasury issued 6-month licence for Venezuelan crude liftings",
        )
        self.assertNotIn("source_quality", out)
        self.assertIn(
            "source_quality",
            out.get("hidden_mechanism") or {},
        )


if __name__ == "__main__":
    unittest.main()
