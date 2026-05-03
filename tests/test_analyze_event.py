"""
tests/test_analyze_event.py

Focused contract tests for the institutional research-field upgrade:

  * ``_mock`` and ``_degraded_fallback`` include every new field as an
    empty list so downstream code never hits KeyError / NoneType on
    a mock-key or thin-output path.
  * The ranked-asset sanitizer normalises messy LLM output:
      - Tolerates the "insufficient_evidence" sentinel at the whole-field
        level (collapses to []).
      - Rewrites clashing / missing ranks into a strict 1..N sequence.
      - Drops entries missing a rationale (a ticker without the 'why'
        isn't an institutional research field, it's just a ticker).
  * The key_falsifiers + top-level minimum_proof_set sanitizers enforce
    channel / timing enums and reject malformed entries.
  * ``_finalize_analysis`` merges the new asset buckets into
    ``assets_to_watch`` AFTER beneficiary_tickers + loser_tickers so
    the existing ``assets_to_watch[0]`` contract (first beneficiary)
    holds byte-for-byte when the LLM emits no new exposures.
  * The full registry carries the five new fields so
    ``build_analysis_dict`` round-trips them via defaults.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    LLM_CORE_FIELDS,
    _LLM_CORE_DEFAULTS,
    _clean_key_falsifiers,
    _clean_ranked_asset_list,
    _clean_top_level_proof_set,
    _clean_transmission_path,
    _degraded_fallback,
    _finalize_analysis,
    _is_valid_transmission_chain,
    _mock,
    build_analysis_dict,
    is_mock,
)


NEW_FIELDS = (
    "primary_assets",
    "secondary_assets",
    "hedge_or_signal_assets",
    "key_falsifiers",
    "minimum_proof_set",
)


# ---------------------------------------------------------------------------
# 1. Registry / defaults carry the new fields
# ---------------------------------------------------------------------------


class TestRegistryCarriesNewFields(unittest.TestCase):
    def test_llm_core_fields_registers_all_five(self) -> None:
        for f in NEW_FIELDS:
            self.assertIn(f, LLM_CORE_FIELDS)

    def test_defaults_are_empty_lists(self) -> None:
        for f in NEW_FIELDS:
            self.assertIn(f, _LLM_CORE_DEFAULTS)
            self.assertEqual(_LLM_CORE_DEFAULTS[f], [])

    def test_build_analysis_dict_fills_missing_new_fields(self) -> None:
        out = build_analysis_dict({})
        for f in NEW_FIELDS:
            self.assertIn(f, out)
            self.assertEqual(out[f], [])


# ---------------------------------------------------------------------------
# 2. Fallback shape — mock + degraded are safe
# ---------------------------------------------------------------------------


class TestMockShape(unittest.TestCase):
    def test_mock_carries_every_new_field(self) -> None:
        m = _mock("no API key")
        for f in NEW_FIELDS:
            self.assertIn(f, m, f"mock missing {f!r}")
            self.assertEqual(m[f], [], f"mock {f!r} should default to []")

    def test_mock_is_mock_flag_holds(self) -> None:
        # is_mock looks at the what_changed prefix; must still work after
        # the schema expansion.
        self.assertTrue(is_mock(_mock("any reason")))


class TestDegradedFallbackShape(unittest.TestCase):
    def test_degraded_carries_every_new_field(self) -> None:
        d = _degraded_fallback(
            headline="some headline",
            stage="realized",
            persistence="medium",
            reason="thin mechanism",
        )
        for f in NEW_FIELDS:
            self.assertIn(f, d, f"degraded missing {f!r}")
            self.assertEqual(d[f], [])

    def test_degraded_flag_still_set(self) -> None:
        d = _degraded_fallback(
            headline="x", stage="realized", persistence="medium",
            reason="test",
        )
        self.assertIs(d["degraded"], True)
        # is_mock should still return False — degraded output is a real
        # LLM response, not a stub.
        self.assertFalse(is_mock(d))


# ---------------------------------------------------------------------------
# 3. Ranked-asset sanitizer
# ---------------------------------------------------------------------------


class TestRankedAssetSanitizer(unittest.TestCase):
    def test_insufficient_evidence_string_collapses_to_empty(self) -> None:
        self.assertEqual(
            _clean_ranked_asset_list("insufficient_evidence", max_items=4),
            [],
        )
        # Also tolerate the human-readable spaced variant.
        self.assertEqual(
            _clean_ranked_asset_list("insufficient evidence", max_items=4),
            [],
        )

    def test_list_of_valid_entries_round_trips(self) -> None:
        raw = [
            {"symbol": "CVX", "rank": 1,
             "rationale": "Direct licence holder — equity tracks lift volumes."},
            {"symbol": "PBF", "rank": 2,
             "rationale": "Gulf Coast coking refiner with heavy-sour feedstock."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["symbol"] for e in out], ["CVX", "PBF"])
        self.assertEqual([e["rank"] for e in out], [1, 2])

    def test_clashing_ranks_reassigned_to_one_through_n(self) -> None:
        raw = [
            {"symbol": "A", "rank": 1, "rationale": "Direct proxy for thesis channel."},
            {"symbol": "B", "rank": 1, "rationale": "Second proxy in same channel."},
            {"symbol": "C", "rank": 7, "rationale": "Third exposure with rationale."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["rank"] for e in out], [1, 2, 3])

    def test_entries_missing_rationale_dropped(self) -> None:
        raw = [
            {"symbol": "A", "rank": 1, "rationale": ""},
            {"symbol": "B", "rank": 2, "rationale": "Real rationale about channel."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["symbol"] for e in out], ["B"])

    def test_max_items_respected(self) -> None:
        raw = [
            {"symbol": f"T{i}", "rank": i + 1,
             "rationale": "Rationale for T with enough length to keep."}
            for i in range(10)
        ]
        out = _clean_ranked_asset_list(raw, max_items=3)
        self.assertEqual(len(out), 3)

    def test_duplicate_symbols_deduped(self) -> None:
        raw = [
            {"symbol": "CVX", "rank": 1, "rationale": "First rationale here."},
            {"symbol": "cvx", "rank": 2, "rationale": "Duplicate but lowercased."},
        ]
        out = _clean_ranked_asset_list(raw, max_items=4)
        self.assertEqual([e["symbol"] for e in out], ["CVX"])

    def test_non_list_input_collapses(self) -> None:
        for bad in (None, 42, {"not": "a list"}, ""):
            self.assertEqual(
                _clean_ranked_asset_list(bad, max_items=4), [],
            )


# ---------------------------------------------------------------------------
# 4. key_falsifiers + top-level minimum_proof_set sanitizers
# ---------------------------------------------------------------------------


class TestKeyFalsifiersSanitizer(unittest.TestCase):
    def test_flat_strings_accepted(self) -> None:
        raw = [
            "PDVSA issues operational-delay statement within 5d",
            "Congressional resolution narrows or revokes the licence",
        ]
        out = _clean_key_falsifiers(raw)
        self.assertEqual(len(out), 2)

    def test_short_strings_dropped(self) -> None:
        raw = ["too short", "Concrete observation with enough length to keep."]
        out = _clean_key_falsifiers(raw)
        self.assertEqual(out, ["Concrete observation with enough length to keep."])

    def test_duplicate_strings_deduped(self) -> None:
        raw = [
            "Concrete observation that would falsify",
            "CONCRETE OBSERVATION THAT WOULD FALSIFY",
        ]
        out = _clean_key_falsifiers(raw)
        self.assertEqual(len(out), 1)

    def test_insufficient_evidence_collapses(self) -> None:
        self.assertEqual(_clean_key_falsifiers("insufficient_evidence"), [])


class TestTopLevelMinimumProofSanitizer(unittest.TestCase):
    def test_valid_entries_kept(self) -> None:
        raw = [
            {"observation": "WCS-WTI discount widens materially",
             "channel": "commodities",
             "threshold": "≥2pp vs baseline",
             "timing": "5-20d"},
        ]
        out = _clean_top_level_proof_set(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["channel"], "commodities")
        self.assertEqual(out[0]["timing"], "5-20d")

    def test_unknown_channel_rejected(self) -> None:
        raw = [
            {"observation": "Long enough observation for sanitizer",
             "channel": "crypto",
             "threshold": "arbitrary",
             "timing": "1d"},
        ]
        self.assertEqual(_clean_top_level_proof_set(raw), [])

    def test_unknown_timing_rejected(self) -> None:
        raw = [
            {"observation": "Long enough observation for sanitizer",
             "channel": "equities",
             "threshold": "arbitrary",
             "timing": "next week"},
        ]
        self.assertEqual(_clean_top_level_proof_set(raw), [])

    def test_insufficient_evidence_collapses(self) -> None:
        self.assertEqual(_clean_top_level_proof_set("insufficient_evidence"), [])


# ---------------------------------------------------------------------------
# 5. Merge into assets_to_watch preserves legacy contract
# ---------------------------------------------------------------------------


class TestAssetsToWatchMerge(unittest.TestCase):
    def _build(self, raw_extras: dict) -> dict:
        parsed = {
            "what_changed": "A concrete action happened to a named actor.",
            "mechanism_summary": (
                "Primary supply channel transmits specifically; named winners "
                "and losers reallocate along a second-order wave."
            ),
            "beneficiaries": ["Chevron"],
            "losers": ["Suncor"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers": ["SU"],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
            **raw_extras,
        }
        return _finalize_analysis(
            parsed, headline="smoke headline", stage="realized",
            persistence="medium",
        )

    def test_beneficiary_is_first_byte_for_byte(self) -> None:
        out = self._build({})  # no new buckets at all
        self.assertEqual(out["assets_to_watch"][0], "CVX")
        self.assertEqual(out["assets_to_watch"], ["CVX", "SU"])

    def test_new_buckets_append_net_new_symbols(self) -> None:
        out = self._build({
            "primary_assets": [
                {"symbol": "PBF", "rank": 1,
                 "rationale": "Gulf Coast heavy-sour coking refiner."},
            ],
            "hedge_or_signal_assets": [
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
            ],
        })
        # CVX + SU must come first; PBF + UUP appended.
        self.assertEqual(out["assets_to_watch"][0], "CVX")
        self.assertEqual(out["assets_to_watch"][1], "SU")
        self.assertIn("PBF", out["assets_to_watch"])
        self.assertIn("UUP", out["assets_to_watch"])

    def test_bucket_symbols_already_in_beneficiary_not_duplicated(self) -> None:
        out = self._build({
            "primary_assets": [
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Ranked re-read of the committed universe."},
            ],
        })
        # Appears once even though it's in both the ticker list and the bucket.
        self.assertEqual(out["assets_to_watch"].count("CVX"), 1)

    def test_insufficient_evidence_buckets_do_not_crash_merge(self) -> None:
        out = self._build({
            "primary_assets": "insufficient_evidence",
            "secondary_assets": "insufficient_evidence",
            "hedge_or_signal_assets": "insufficient_evidence",
        })
        self.assertEqual(out["primary_assets"], [])
        self.assertEqual(out["secondary_assets"], [])
        self.assertEqual(out["hedge_or_signal_assets"], [])
        # assets_to_watch still carries the ticker lists.
        self.assertEqual(out["assets_to_watch"][0], "CVX")


# ---------------------------------------------------------------------------
# 6. Backward-compat — legacy-only LLM output still produces a valid
#    response, and the response shape always carries the legacy keys.
# ---------------------------------------------------------------------------


class TestLegacyResponseShapeStable(unittest.TestCase):
    """An LLM that only emits the *original* schema (no ranked assets,
    no key_falsifiers, no minimum_proof_set) must still produce a valid
    analysis — every new field surfaces as an empty list default and
    every legacy field is present byte-for-byte."""

    def _run_legacy(self) -> dict:
        parsed = {
            "what_changed": "Named actor took a concrete action on a specific object.",
            "mechanism_summary": (
                "Primary supply channel hits; named winners and losers "
                "reallocate along a second-order wave."
            ),
            "beneficiaries": ["Chevron", "PBF"],
            "losers": ["Suncor"],
            "beneficiary_tickers": ["CVX", "PBF"],
            "loser_tickers": ["SU"],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
        }
        return _finalize_analysis(
            parsed, headline="smoke", stage="realized",
            persistence="medium",
        )

    def test_legacy_output_preserves_all_legacy_fields(self) -> None:
        out = self._run_legacy()
        self.assertEqual(out["beneficiaries"], ["Chevron", "PBF"])
        self.assertEqual(out["losers"], ["Suncor"])
        self.assertEqual(out["beneficiary_tickers"], ["CVX", "PBF"])
        self.assertEqual(out["loser_tickers"], ["SU"])
        # assets_to_watch = beneficiary + loser tickers, exactly the
        # pre-upgrade shape.
        self.assertEqual(out["assets_to_watch"], ["CVX", "PBF", "SU"])
        self.assertEqual(out["confidence"], "medium")

    def test_legacy_output_carries_new_fields_as_empty_defaults(self) -> None:
        out = self._run_legacy()
        for f in NEW_FIELDS:
            self.assertIn(f, out, f"{f!r} missing from legacy response")
            self.assertEqual(
                out[f], [],
                f"{f!r} should default to [] when LLM omits it entirely",
            )


# ---------------------------------------------------------------------------
# 7. Derivation — rich ranked structure backfills thin legacy fields.
# ---------------------------------------------------------------------------


class TestLegacyFieldsDerivedFromRanked(unittest.TestCase):
    """When the LLM emits ranked primary_assets but leaves the legacy
    ``beneficiary_tickers`` / ``beneficiaries`` lists empty, derivation
    should populate the legacy shape from the richer structure so
    downstream consumers (Telegram, CLI, charts) stay populated."""

    def _run_thin_legacy(self, **overrides) -> dict:
        parsed = {
            "what_changed": "A concrete action by a named actor.",
            "mechanism_summary": (
                "Primary supply channel transmits specifically; named winners "
                "and losers reallocate along a distinct second-order wave."
            ),
            "beneficiaries": [],
            "losers": ["Suncor"],
            "beneficiary_tickers": [],
            "loser_tickers": ["SU"],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
            "primary_assets": [
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct licence holder — restored lift volumes."},
                {"symbol": "PBF", "rank": 2,
                 "rationale": "Gulf Coast heavy-sour coking refiner with feedstock drop."},
            ],
            "secondary_assets": [
                {"symbol": "VLO", "rank": 1,
                 "rationale": "Largest Gulf heavy-sour refiner — follow-through."},
            ],
            "hedge_or_signal_assets": [
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
            ],
            **overrides,
        }
        return _finalize_analysis(
            parsed, headline="smoke", stage="realized",
            persistence="medium",
        )

    def test_empty_beneficiary_tickers_backfilled_from_primary(self) -> None:
        out = self._run_thin_legacy()
        # CVX and PBF hoisted out of primary_assets in rank order.
        self.assertEqual(out["beneficiary_tickers"][:2], ["CVX", "PBF"])

    def test_empty_beneficiaries_backfilled_with_rationale(self) -> None:
        out = self._run_thin_legacy()
        self.assertEqual(len(out["beneficiaries"]), 2)
        self.assertTrue(out["beneficiaries"][0].startswith("CVX"))
        self.assertIn("licence", out["beneficiaries"][0].lower())

    def test_populated_legacy_list_is_not_overwritten(self) -> None:
        out = self._run_thin_legacy(
            beneficiary_tickers=["HES", "EOG"],
            beneficiaries=["Hess Corp", "EOG Resources"],
        )
        # Derivation must NOT hoist primary_assets symbols when the
        # legacy list is already populated.
        self.assertEqual(out["beneficiary_tickers"], ["HES", "EOG"])
        self.assertEqual(out["beneficiaries"], ["Hess Corp", "EOG Resources"])

    def test_hedge_assets_are_never_treated_as_beneficiaries(self) -> None:
        """UUP / VIX / DXY are hedge or signal proxies, not beneficiaries."""
        out = self._run_thin_legacy(
            primary_assets=[],      # no primary; only hedges available
            secondary_assets=[],
            hedge_or_signal_assets=[
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy — never a beneficiary."},
            ],
        )
        self.assertNotIn("UUP", out["beneficiary_tickers"])

    def test_assets_to_watch_still_begins_with_derived_beneficiaries(self) -> None:
        """When derivation kicks in, the derived tickers must still
        sort to the front of assets_to_watch so the ``assets_to_watch[0]``
        contract keeps holding — the first element is always the
        highest-conviction long exposure."""
        out = self._run_thin_legacy()
        self.assertEqual(out["assets_to_watch"][0], "CVX")
        # Loser still in the list (was already populated pre-derivation).
        self.assertIn("SU", out["assets_to_watch"])
        # Hedge proxy shows up but strictly AFTER the committed universe.
        self.assertGreater(
            out["assets_to_watch"].index("UUP"),
            out["assets_to_watch"].index("SU"),
        )


# ---------------------------------------------------------------------------
# 8. competing_thesis — institutional field sanitizer behaviour
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 9. Hardening tripwires — one compact test per invariant the upgraded
#    analysis contract promises.  Any future regression across these
#    four axes will fail a named, targeted test here.
# ---------------------------------------------------------------------------


class TestContractHardeningTripwires(unittest.TestCase):
    """Four invariants the upgraded analysis contract must preserve:

      1. Ranked asset buckets survive the full pipeline byte-for-byte.
      2. assets_to_watch merge keeps legacy ordering: beneficiary +
         loser tickers FIRST, then net-new symbols from primary →
         secondary → hedge_or_signal, no duplicates.
      3. Normal (non-thin) analyses do NOT carry ``degraded``.
      4. A finalised analysis is not a mock — `is_mock()` is False on
         anything that reached `_finalize_analysis` successfully.
    """

    def _rich_parsed(self) -> dict:
        return {
            "what_changed": "Named actor takes a concrete action on a specific object.",
            "mechanism_summary": (
                "Primary supply channel transmits specifically; named winners "
                "and losers reallocate along a distinct second-order wave."
            ),
            "beneficiaries": ["Chevron"],
            "losers":        ["Suncor"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers":       ["SU"],
            "confidence":          "medium",
            "mechanism_family":    "supply_normalization",
            "primary_assets": [
                {"symbol": "PBF", "rank": 1,
                 "rationale": "Gulf Coast heavy-sour coking refiner — feedstock drop."},
            ],
            "hedge_or_signal_assets": [
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
            ],
        }

    def _finalized(self) -> dict:
        return _finalize_analysis(
            self._rich_parsed(),
            headline="smoke",
            stage="realized",
            persistence="medium",
        )

    def test_1_ranked_buckets_survive_pipeline(self) -> None:
        out = self._finalized()
        self.assertEqual(
            [e["symbol"] for e in out["primary_assets"]], ["PBF"],
            "ranked primary_assets bucket lost its entry through finalize",
        )
        self.assertEqual(
            [e["symbol"] for e in out["hedge_or_signal_assets"]], ["UUP"],
        )

    def test_2_assets_to_watch_keeps_legacy_ordering(self) -> None:
        out = self._finalized()
        self.assertEqual(
            out["assets_to_watch"][:2], ["CVX", "SU"],
            "legacy beneficiary+loser ordering at head of assets_to_watch broke",
        )
        self.assertGreater(
            out["assets_to_watch"].index("PBF"),
            out["assets_to_watch"].index("SU"),
            "net-new ranked symbols must land AFTER the committed universe",
        )
        self.assertGreater(
            out["assets_to_watch"].index("UUP"),
            out["assets_to_watch"].index("PBF"),
            "hedge/signal symbols must land LAST in assets_to_watch",
        )
        # No duplicates slipped through.
        self.assertEqual(
            len(out["assets_to_watch"]),
            len(set(out["assets_to_watch"])),
        )

    def test_3_normal_analysis_has_no_degraded_flag(self) -> None:
        out = self._finalized()
        self.assertNotIn(
            "degraded", out,
            "normal finalize emitted a degraded flag; degraded is reserved "
            "for the _degraded_fallback path only",
        )

    def test_4_finalized_is_not_mock(self) -> None:
        out = self._finalized()
        self.assertFalse(
            is_mock(out),
            "a successful finalize path should never surface as a mock",
        )


class TestCompetingThesisBackwardCompat(unittest.TestCase):
    """competing_thesis carries a single primary_thesis with optional
    alternative_thesis / discriminator layers.  primary_thesis alone is
    sufficient; the rival layer attaches only when materially distinct
    and decisively resolvable."""

    def _build(self, **overrides) -> dict:
        parsed = {
            "what_changed": "Action by named actor hit a specific object.",
            "mechanism_summary": (
                "Primary supply channel transmits specifically; named winners "
                "and losers reallocate along a second-order wave."
            ),
            "beneficiaries": ["Chevron"],
            "losers": ["Suncor"],
            "beneficiary_tickers": ["CVX"],
            "loser_tickers": ["SU"],
            "confidence": "medium",
            "mechanism_family": "supply_normalization",
            **overrides,
        }
        return _finalize_analysis(
            parsed, headline="smoke", stage="realized",
            persistence="medium",
        )

    def test_competing_thesis_absent_yields_empty_dict(self) -> None:
        out = self._build()
        self.assertEqual(out.get("competing_thesis"), {})

    def test_competing_thesis_without_discriminator_keeps_alternative(self) -> None:
        # Partial block lacking discriminator → primary + alternative
        # survive; only the discriminator object drops.
        out = self._build(competing_thesis={
            "primary_thesis": (
                "Treasury licence restores Chevron Venezuelan heavy-sour "
                "liftings; refining margins widen on cheaper feedstock."
            ),
            "alternative_thesis": (
                "PDVSA infrastructure constraints cap delivered volumes; "
                "WCS-WTI spread barely moves and refiner margins stay flat."
            ),
            "evidence_favoring_primary": [],
            "evidence_favoring_alternative": [],
            # No discriminator — discriminator drops, rest survives.
        })
        ct = out["competing_thesis"]
        self.assertTrue(ct)
        self.assertIn("primary_thesis", ct)
        self.assertIn("alternative_thesis", ct)
        self.assertNotIn("discriminator", ct)

    def test_competing_thesis_primary_only_round_trips(self) -> None:
        out = self._build(competing_thesis={
            "primary_thesis": "Single committed read of the event.",
        })
        ct = out["competing_thesis"]
        self.assertTrue(ct)
        self.assertEqual(ct["primary_thesis"], "Single committed read of the event.")
        self.assertNotIn("alternative_thesis", ct)

    def test_competing_thesis_with_discriminator_round_trips(self) -> None:
        out = self._build(competing_thesis={
            "primary_thesis": "Primary read of the market reaction.",
            "alternative_thesis": "Rival read that would explain the tape.",
            "evidence_favoring_primary": [
                {"observation": "Concrete evidence on named ticker",
                 "channel": "equities"},
            ],
            "evidence_favoring_alternative": [
                {"observation": "Rival observation on named market",
                 "channel": "equities"},
            ],
            "discriminator": {
                "observation": "Single decisive observation on SPY",
                "channel": "equities",
                "outcome_if_primary": "SPY closes up ≥1% on volume",
                "outcome_if_alternative": "SPY closes flat-to-down",
                "timing": "1d",
            },
        })
        ct = out["competing_thesis"]
        self.assertTrue(ct)
        self.assertIn("discriminator", ct)
        self.assertEqual(ct["discriminator"]["timing"], "1d")


# ---------------------------------------------------------------------------
# 10. Structural transmission-chain validation
# ---------------------------------------------------------------------------


def _hop(action: str, *,
         actor: str = "US Treasury OFAC",
         channel: str = "sanction",
         effect: str = "CVX equity prices in restored production volumes; "
                       "WCS-WTI spread widens >=2pp.") -> dict:
    """Build a minimally-valid hop dict for the transmission chain."""
    return {
        "hop": action,
        "action": action,
        "actor": actor,
        "channel": channel,
        "expected_market_effect": effect,
        "timing": "1-5d",
    }


def _valid_chain() -> list[dict]:
    """Two-hop chain: starts at concrete change, ends at asset effect."""
    return [
        _hop(
            "US Treasury issues 6-month licence for Venezuelan crude liftings.",
            channel="sanction",
            effect="Brent-WTI light-heavy diff narrows on incremental supply.",
        ),
        _hop(
            "Chevron resumes direct equity-and-lift arrangement with PDVSA.",
            actor="Chevron", channel="supply",
            effect="CVX equity rallies; WCS-WTI discount widens >=2pp within 5d.",
        ),
    ]


class TestTransmissionChainStructure(unittest.TestCase):
    """Each transmission_path hop must carry actor + action + channel +
    expected_market_effect (timing optional but enum-checked).  Vague
    hops are sanitizer-rejected; the validator additionally enforces
    that the chain starts at a concrete actor and lands at an asset
    proxy."""

    def test_full_hop_with_all_fields_passes(self) -> None:
        cleaned = _clean_transmission_path(_valid_chain())
        self.assertEqual(len(cleaned), 2)
        first = cleaned[0]
        for key in (
            "hop", "action", "actor", "channel",
            "expected_market_effect", "timing",
        ):
            self.assertIn(key, first, f"hop missing structured field {key!r}")
        self.assertTrue(_is_valid_transmission_chain(cleaned))

    def test_vague_action_dropped_by_sanitizer(self) -> None:
        """'markets react' / 'investors price risk' are placeholder
        verbs — the sanitizer drops the hop before the validator
        runs."""
        chain = _valid_chain() + [
            _hop("Markets react to the news", channel="pricing_power"),
            _hop("Investors price risk into the curve", channel="pricing_power"),
        ]
        cleaned = _clean_transmission_path(chain)
        self.assertEqual(
            len(cleaned), 2,
            "vague hops should be dropped before validation",
        )

    def test_chain_must_start_with_concrete_actor(self) -> None:
        """First hop's actor must be concrete — 'investors' /
        'the market' / 'stakeholders' are not concrete enough."""
        chain = [
            _hop(
                "Investors absorb the announcement.",
                actor="investors react",  # vague-hop pattern in actor
            ),
            _hop(
                "Equity flows shift to defensive names.",
                actor="defensive sector funds",
                effect="XLU outperforms SPY by 1pp.",
            ),
        ]
        cleaned = _clean_transmission_path(chain)
        self.assertFalse(
            _is_valid_transmission_chain(cleaned),
            "chain starting with a vague actor must fail validation",
        )

    def test_chain_must_end_with_asset_proxy(self) -> None:
        """Last hop's expected_market_effect must reference a ticker /
        ETF / spread / yield / credit / FX / market-proxy noun."""
        chain = [
            _hop(
                "US Commerce adds 28 fabs to Entity List.",
                actor="US Commerce Dept BIS", channel="policy_gate",
                effect="LRCX and AMAT close down >=3% on revenue-hit framing.",
            ),
            _hop(
                "Chinese fab capex cycle stalls.",
                actor="Chinese fabs", channel="supply",
                # Generic narrative — no asset / proxy reference.
                effect="The cascade plays out over a longer horizon.",
            ),
        ]
        cleaned = _clean_transmission_path(chain)
        self.assertFalse(
            _is_valid_transmission_chain(cleaned),
            "chain ending without an asset/proxy implication must fail",
        )

    def test_single_hop_chain_invalid(self) -> None:
        cleaned = _clean_transmission_path([_valid_chain()[0]])
        self.assertFalse(
            _is_valid_transmission_chain(cleaned),
            "a 1-hop chain has no transmission — must fail validation",
        )

    def test_invalid_chain_marks_event_low_information(self) -> None:
        """End-to-end: when transmission_path is non-empty but fails
        structural validation, the low-info gate fires with reason
        ``invalid_transmission_chain``."""
        from low_information_gate import evaluate_low_information

        # Provide a populated transmission_path that won't survive the
        # validator (last hop's effect has no asset/proxy reference).
        invalid_path = [
            _hop("US Treasury issues 6-month Venezuelan crude licence."),
            _hop(
                "Chevron resumes direct PDVSA liftings.",
                actor="Chevron",
                channel="supply",
                effect="The cascade unfolds across the broader market.",
            ),
        ]
        ev = {
            "mechanism_summary": (
                "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
                "Coast feedstock and widening WCS-WTI."
            ),
            "beneficiary_tickers": ["XOM", "CVX"],
            "loser_tickers": [],
            "assets_to_watch": ["XOM", "CVX"],
            "transmission_path": invalid_path,
        }
        result = evaluate_low_information(ev)
        self.assertTrue(result["is_low_info"])
        self.assertEqual(result["reason"], "invalid_transmission_chain")

    def test_output_shape_unchanged_for_valid_chain(self) -> None:
        """The new optional hop fields are added inside existing dicts
        — the legacy {hop, channel, actor} keys are still emitted, and
        no new top-level keys appear on the analysis."""
        out = _finalize_analysis(
            {
                "what_changed": "Treasury issues a Venezuelan crude licence.",
                "mechanism_summary": (
                    "Treasury licence restores Chevron Venezuelan heavy-sour "
                    "liftings; Gulf Coast cokers gain cheaper feedstock; "
                    "WCS-WTI discount widens."
                ),
                "beneficiaries": ["Chevron"],
                "losers": ["Suncor"],
                "beneficiary_tickers": ["CVX"],
                "loser_tickers": ["SU"],
                "confidence": "medium",
                "mechanism_family": "supply_normalization",
                "transmission_path": _valid_chain(),
            },
            headline="smoke", stage="realized", persistence="medium",
        )
        path = out["transmission_path"]
        self.assertTrue(path)
        # Legacy keys preserved; new keys added inside the same dict.
        first = path[0]
        for legacy in ("hop", "channel", "actor"):
            self.assertIn(legacy, first)
        for added in ("action", "expected_market_effect"):
            self.assertIn(added, first)


# ---------------------------------------------------------------------------
# 11. Mechanism subtype inference at finalize-time
# ---------------------------------------------------------------------------


class TestMechanismSubtypeFinalize(unittest.TestCase):
    """``_finalize_analysis`` should infer ``mechanism_subtype`` from
    the mechanism prose when it matches a registered subtype, and
    leave the field absent when nothing matches — preserving
    family-level behavior in the fallback case."""

    def _build(self, **overrides) -> dict:
        parsed = {
            "what_changed": (
                "US Trade Representative announces a Section 301 tariff "
                "on Chinese imports."
            ),
            "mechanism_summary": (
                "Section 301 tariff on Chinese imports widens the "
                "trade-balance drag; KWEB-style baskets reprice the supply chokepoint."
            ),
            "beneficiaries": ["US domestic producers"],
            "losers": ["China-exposed importers"],
            "beneficiary_tickers": ["VLO"],
            "loser_tickers": ["KWEB"],
            "confidence": "medium",
            "mechanism_family": "tariff",
            **overrides,
        }
        return _finalize_analysis(
            parsed, headline="US imposes Section 301 tariff",
            stage="realized", persistence="medium",
        )

    def test_subtype_inferred_when_keywords_match(self):
        out = self._build()
        self.assertEqual(out.get("mechanism_subtype"), "import_tariff_china")

    def test_subtype_absent_when_no_keywords_match(self):
        """Generic tariff prose without china-specific markers leaves
        the optional field absent — family-level behavior preserved."""
        out = self._build(
            what_changed="Council votes on dairy duties for Mediterranean producers.",
            mechanism_summary=(
                "Dairy duty wedge tightens supply for processed-cheese "
                "imports across the Mediterranean."
            ),
        )
        self.assertNotIn("mechanism_subtype", out)

    def test_response_shape_unchanged_when_subtype_absent(self):
        """Output dict carries no ``mechanism_subtype`` key when no
        subtype matched — adding the field is purely additive."""
        out = self._build(
            mechanism_family="none",
            what_changed="Generic event happens.",
            mechanism_summary=(
                "Generic mechanism without a specific transmission "
                "variant — supply channels named in passing."
            ),
        )
        self.assertNotIn("mechanism_subtype", out)


class TestMechanismSubtypeNormalization(unittest.TestCase):
    """LLM-emitted ``mechanism_subtype`` values must be validated
    against the resolved family.  Conflicts are dropped with a
    validation warning; valid values are preserved; family fallback
    re-checks against the corrected family."""

    def _build(self, **overrides) -> dict:
        parsed = {
            "what_changed": (
                "US Trade Representative announces a Section 301 "
                "tariff on Chinese imports."
            ),
            "mechanism_summary": (
                "Section 301 tariff on Chinese imports widens the "
                "trade-balance drag; KWEB / FXI baskets reprice the "
                "supply chokepoint."
            ),
            "beneficiaries": ["US domestic producers"],
            "losers": ["China-exposed importers"],
            "beneficiary_tickers": ["VLO"],
            "loser_tickers": ["KWEB"],
            "confidence": "medium",
            "mechanism_family": "tariff",
            **overrides,
        }
        return _finalize_analysis(
            parsed, headline="US imposes Section 301 tariff",
            stage="realized", persistence="medium",
        )

    def test_valid_llm_subtype_kept_byte_for_byte(self):
        """LLM-emitted subtype that matches the resolved family is
        preserved verbatim — no warning, no re-inference."""
        out = self._build(mechanism_subtype="import_tariff_china")
        self.assertEqual(out.get("mechanism_subtype"), "import_tariff_china")
        warnings = out.get("validation_warnings") or []
        self.assertFalse(any(
            "mechanism_subtype dropped" in w for w in warnings
        ))

    def test_invalid_llm_subtype_dropped_with_warning(self):
        """LLM emits a subtype that's not registered for the
        committed family — sanitizer drops it AND records a warning."""
        out = self._build(
            # Override prose so inference doesn't quietly replace.
            what_changed="Generic tariff announcement.",
            mechanism_summary=(
                "Targeted tariff wedge tightens supply for processed "
                "consumer goods across Eastern markets."
            ),
            mechanism_subtype="oil_supply_shock",  # not a tariff subtype
        )
        self.assertNotEqual(
            out.get("mechanism_subtype"), "oil_supply_shock",
        )
        warnings = out.get("validation_warnings") or []
        self.assertTrue(any(
            "mechanism_subtype dropped" in w for w in warnings
        ), f"expected drop warning in {warnings!r}")

    def test_invalid_subtype_replaced_by_inference_when_signals_match(self):
        """When the LLM emits an invalid subtype but the prose
        signals a different valid subtype, the sanitizer drops the
        bad value AND substitutes the inferred one."""
        out = self._build(
            mechanism_subtype="oil_supply_shock",  # invalid for tariff
        )
        self.assertEqual(
            out.get("mechanism_subtype"), "import_tariff_china",
            "inference should rescue a corrected subtype after dropping invalid",
        )
        warnings = out.get("validation_warnings") or []
        self.assertTrue(any(
            "mechanism_subtype dropped" in w for w in warnings
        ))

    def test_subtype_dropped_when_family_resolves_to_none(self):
        """When the family resolves to ``"none"`` (and the post-parse
        fallback can't upgrade it), any LLM subtype is dropped — the
        ``"none"`` family has no registered subtypes."""
        # Avoid any tariff / china signals so the fallback stays at "none".
        from analyze_event import _finalize_analysis
        parsed = {
            "what_changed": "Generic announcement happens.",
            "mechanism_summary": (
                "Generic mechanism with no specific channel named in "
                "this analysis blob."
            ),
            "beneficiaries": [],
            "losers": [],
            "beneficiary_tickers": [],
            "loser_tickers": [],
            "confidence": "low",
            "mechanism_family": "none",
            "mechanism_subtype": "import_tariff_china",
        }
        out = _finalize_analysis(
            parsed, headline="Generic announcement",
            stage="realized", persistence="medium",
        )
        # Family stays "none" → subtype dropped because no subtypes
        # registered for the "none" family.
        self.assertEqual(out.get("mechanism_family"), "none")
        self.assertNotIn("mechanism_subtype", out)
        warnings = out.get("validation_warnings") or []
        self.assertTrue(any(
            "mechanism_subtype dropped" in w for w in warnings
        ))

    def test_subtype_revalidated_against_fallback_corrected_family(self):
        """When the post-parse fallback upgrades family from ``"none"``
        to a real family, ``mechanism_subtype`` is re-validated
        against the corrected family — a subtype that's valid for
        the upgraded family survives even when the LLM tagged the
        family as ``"none"``."""
        out = self._build(
            mechanism_family="none",        # gets upgraded by fallback
            mechanism_subtype="import_tariff_china",
        )
        self.assertNotEqual(out.get("mechanism_family"), "none")
        # Subtype kept because it matches the corrected family.
        self.assertEqual(out.get("mechanism_subtype"), "import_tariff_china")

    def test_subtype_uses_richer_signal_blob(self):
        """Inference reads primary_thesis + transmission_chain in
        addition to mechanism_summary / what_changed — keywords that
        only appear in those fields should still match."""
        out = self._build(
            what_changed="US announces a tariff package.",
            mechanism_summary=(
                "Tariff-driven wedge tightens trade balances across "
                "the Asian export complex."
            ),
            transmission_chain=[
                "USTR adds Section 301 designations on Chinese imports",
                "Affected China baskets reprice at the wedge",
                "KWEB lags broad equity tape on the announcement",
            ],
        )
        self.assertEqual(
            out.get("mechanism_subtype"), "import_tariff_china",
            "transmission_chain text alone should drive subtype inference",
        )


class TestCriticalBreakpointShape(unittest.TestCase):
    """``critical_breakpoints`` entries can carry the optional new
    fields {condition, threshold_or_observation, why_it_changes_thesis,
    linked_proof_or_falsifier}.  Generic content on those fields
    rejects the entry.  Legacy entries (just signal+channel+threshold+
    timing) still survive."""

    def _hidden_mechanism(self, breakpoints):
        from analyze_event import _clean_hidden_mechanism
        out = _clean_hidden_mechanism(
            {"critical_breakpoints": breakpoints},
            set(),  # valid_tickers — not exercised on this path
        )
        return out.get("critical_breakpoints") or []

    def test_full_shape_breakpoint_survives(self):
        breakpoints = self._hidden_mechanism([
            {
                "signal": "WCS-WTI discount widens >3pp within 5d",
                "channel": "commodities",
                "timing": "1-5d",
                "condition": "if WCS-WTI heavy-sour discount widens >3pp",
                "threshold_or_observation": "discount > 3pp on Bloomberg WCS print",
                "why_it_changes_thesis": (
                    "wider discount confirms the Gulf Coast feedstock "
                    "tightening that drives the refining-margin lift"
                ),
                "linked_proof_or_falsifier": "minimum_proof_set:0",
            },
        ])
        self.assertEqual(len(breakpoints), 1)
        bp = breakpoints[0]
        # Legacy fields preserved.
        self.assertIn("channel", bp)
        self.assertEqual(bp["channel"], "commodities")
        self.assertEqual(bp["timing"], "1-5d")
        # New optional fields preserved.
        self.assertIn("condition", bp)
        self.assertIn("threshold_or_observation", bp)
        self.assertIn("why_it_changes_thesis", bp)
        self.assertEqual(bp["linked_proof_or_falsifier"], "minimum_proof_set:0")

    def test_generic_condition_rejects_entry(self):
        """A breakpoint whose ``condition`` is generic ('market
        sentiment changes') is dropped — it doesn't pass even though
        the legacy fields are clean."""
        breakpoints = self._hidden_mechanism([
            {
                "signal": "WCS-WTI discount widens >3pp within 5d",
                "channel": "commodities",
                "timing": "1-5d",
                "condition": "market sentiment changes",
                "threshold_or_observation": "discount > 3pp on Bloomberg WCS print",
                "why_it_changes_thesis": "wider discount confirms tightening",
            },
        ])
        self.assertEqual(breakpoints, [])

    def test_generic_threshold_or_observation_rejects(self):
        breakpoints = self._hidden_mechanism([
            {
                "signal": "WCS-WTI discount widens >3pp within 5d",
                "channel": "commodities",
                "timing": "1-5d",
                "condition": "if WCS-WTI heavy-sour discount widens",
                "threshold_or_observation": "narrative shifts in commentary",
                "why_it_changes_thesis": "tightening confirms thesis",
            },
        ])
        self.assertEqual(breakpoints, [])

    def test_legacy_breakpoint_without_new_fields_passes(self):
        """A breakpoint with only the legacy {signal/channel/timing}
        fields survives — back-compat preserved."""
        breakpoints = self._hidden_mechanism([
            {
                "signal": "Commodity reverses >50% of headline move intraday",
                "channel": "commodities",
                "timing": "1d",
            },
        ])
        self.assertEqual(len(breakpoints), 1)
        bp = breakpoints[0]
        self.assertIn("signal", bp)
        # New fields absent — not stamped when not provided.
        self.assertNotIn("condition", bp)
        self.assertNotIn("why_it_changes_thesis", bp)


class TestProofItemLinkedBreakpoint(unittest.TestCase):
    """Proof / falsifier items can carry an optional
    ``linked_breakpoint`` reference back to a critical_breakpoints
    entry.  Pass-through only; generic strings rejected."""

    def test_proof_item_linked_breakpoint_preserved(self):
        from analyze_event import _clean_proof_entry, _BREAKPOINT_TIMING_ENUM

        entry = _clean_proof_entry(
            {
                "observation": "WCS-WTI discount widens 2pp within 5d",
                "channel": "commodities",
                "threshold": "≥2pp move",
                "timing": "1-5d",
                "linked_breakpoint": "critical_breakpoints:0",
            },
            require_threshold=False,
            timing_enum=_BREAKPOINT_TIMING_ENUM,
        )
        self.assertIsNotNone(entry)
        self.assertEqual(entry["linked_breakpoint"], "critical_breakpoints:0")

    def test_generic_linked_breakpoint_dropped(self):
        from analyze_event import _clean_proof_entry, _BREAKPOINT_TIMING_ENUM

        entry = _clean_proof_entry(
            {
                "observation": "WCS-WTI discount widens 2pp within 5d",
                "channel": "commodities",
                "threshold": "≥2pp move",
                "timing": "1-5d",
                "linked_breakpoint": "market sentiment changes",
            },
            require_threshold=False,
            timing_enum=_BREAKPOINT_TIMING_ENUM,
        )
        # Entry survives (other fields valid); only the generic
        # linked_breakpoint is silently dropped.
        self.assertIsNotNone(entry)
        self.assertNotIn("linked_breakpoint", entry)


if __name__ == "__main__":
    unittest.main()
