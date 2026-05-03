"""
tests/test_family_fallback.py

Contract tests for the post-parse mechanism-family fallback and the
LLM-alias normaliser.  The goal is to reduce false
``mechanism_family="none"`` on analyzable events without introducing
new taxonomy labels — every path here must land on a canonical id
already in ``mechanism_family.FAMILY_IDS``.

Covered:
  1. Alias normaliser collapses synonyms onto canonical ids.
  2. Keyword classifier fires on the three expansion families
     (industrial_policy / regulation / external_balance).
  3. Post-parse structured fallback reads transmission_chain,
     asset buckets, and hidden_mechanism when the keyword classifier
     alone would return "none".
  4. True-unknown cases still return "none" — an event with genuinely
     no evidence doesn't get forced into a family.
  5. A committed LLM family is NEVER overwritten by the fallback.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    _clean_mechanism_family,
    _finalize_analysis,
    _post_parse_family_fallback,
)
from mechanism_family import (
    FAMILY_IDS,
    classify_family,
    normalize_family_alias,
)


# ---------------------------------------------------------------------------
# 1. Alias normaliser
# ---------------------------------------------------------------------------


class TestFamilyAliasNormaliser(unittest.TestCase):
    def test_antitrust_is_regulation(self) -> None:
        self.assertEqual(normalize_family_alias("antitrust"), "regulation")
        # Case / punctuation tolerant.
        self.assertEqual(
            normalize_family_alias("Anti-Trust"), "regulation",
        )

    def test_chips_act_is_industrial_policy(self) -> None:
        self.assertEqual(
            normalize_family_alias("chips_act"), "industrial_policy",
        )
        self.assertEqual(
            normalize_family_alias("CHIPS ACT"), "industrial_policy",
        )

    def test_ira_maps_to_industrial_policy(self) -> None:
        self.assertEqual(normalize_family_alias("ira"), "industrial_policy")

    def test_em_stress_is_external_balance(self) -> None:
        self.assertEqual(
            normalize_family_alias("em_stress"), "external_balance",
        )
        self.assertEqual(
            normalize_family_alias("balance_of_payments"), "external_balance",
        )

    def test_ofac_is_sanction(self) -> None:
        self.assertEqual(normalize_family_alias("ofac"), "sanction")
        self.assertEqual(
            normalize_family_alias("entity_list"), "sanction",
        )

    def test_unknown_alias_returns_none(self) -> None:
        """An un-aliased string must return None, not a spurious family."""
        self.assertIsNone(normalize_family_alias("random_new_thing"))
        self.assertIsNone(normalize_family_alias(""))
        self.assertIsNone(normalize_family_alias(None))  # type: ignore[arg-type]

    def test_alias_only_maps_to_canonical_ids(self) -> None:
        """Every alias must resolve to a family id already in FAMILY_IDS —
        the alias table cannot introduce new taxonomy."""
        from mechanism_family import _FAMILY_ALIASES
        for src, target in _FAMILY_ALIASES.items():
            self.assertIn(
                target, FAMILY_IDS,
                f"alias {src!r} maps to non-canonical {target!r}",
            )


# ---------------------------------------------------------------------------
# 2. _clean_mechanism_family honours aliases
# ---------------------------------------------------------------------------


class TestCleanMechanismFamilyAliasPath(unittest.TestCase):
    def test_committed_canonical_preserved(self) -> None:
        self.assertEqual(_clean_mechanism_family("sanction"), "sanction")

    def test_synonym_normalised_to_canonical(self) -> None:
        self.assertEqual(_clean_mechanism_family("antitrust"), "regulation")
        self.assertEqual(
            _clean_mechanism_family("chips_act"), "industrial_policy",
        )
        self.assertEqual(
            _clean_mechanism_family("em_stress"), "external_balance",
        )

    def test_unknown_still_none(self) -> None:
        self.assertEqual(
            _clean_mechanism_family("not_a_family_anywhere"), "none",
        )


# ---------------------------------------------------------------------------
# 3. Keyword classifier covers the three expansion families
# ---------------------------------------------------------------------------


class TestKeywordCoverageForExpansionFamilies(unittest.TestCase):
    def test_ira_headline_hits_industrial_policy(self) -> None:
        self.assertEqual(
            classify_family(
                "Treasury finalises Inflation Reduction Act tax credit rules",
                "",
            ),
            "industrial_policy",
        )

    def test_ftc_merger_hits_regulation(self) -> None:
        self.assertEqual(
            classify_family(
                "FTC launches merger review of pharma combination",
                "",
            ),
            "regulation",
        )

    def test_em_bailout_hits_external_balance(self) -> None:
        self.assertEqual(
            classify_family(
                "Argentina sovereign CDS blows out on IMF bailout delay",
                "",
            ),
            "external_balance",
        )

    def test_no_keyword_hit_returns_none(self) -> None:
        self.assertEqual(
            classify_family("Completely unrelated topic", ""), "none",
        )


# ---------------------------------------------------------------------------
# 4. Post-parse structured fallback
# ---------------------------------------------------------------------------


def _normalized_stub(**overrides) -> dict:
    """A minimal ``_normalize_schema`` output shape for fallback testing."""
    base = {
        "mechanism_family":              "none",
        "mechanism_summary":             "",
        "transmission_chain":            [],
        "hidden_mechanism":              {},
        "primary_assets":                [],
        "expected_first_order_channels": [],
        "expected_second_order_channels": [],
    }
    base.update(overrides)
    return base


class TestPostParseFallbackTiers(unittest.TestCase):
    def test_committed_family_passes_through(self) -> None:
        """Tier 0 — if the first-pass already committed, fallback is a no-op."""
        self.assertEqual(
            _post_parse_family_fallback(
                _normalized_stub(mechanism_family="sanction"),
                headline="unrelated",
            ),
            "sanction",
        )

    def test_transmission_chain_keyword_rescues_family(self) -> None:
        """Tier 2 — a keyword buried in transmission_chain still classifies."""
        ev = _normalized_stub(
            transmission_chain=[
                "FTC issues consent decree blocking acquisition",
                "Targeted company drops sharply on regulatory hit",
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline="generic"),
            "regulation",
        )

    def test_transmission_path_dicts_read_hop_field(self) -> None:
        """Tier 2 tolerates ``transmission_path``-style dict hops."""
        ev = _normalized_stub(
            transmission_chain=[
                {"hop": "Central bank announces IMF bailout package",
                 "channel": "fx", "actor": "IMF"},
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "external_balance",
        )

    def test_bottleneck_type_reserve_bop_is_external_balance(self) -> None:
        """Tier 3 — hidden_mechanism.bottleneck_type primitive maps to family."""
        ev = _normalized_stub(
            hidden_mechanism={"bottleneck_type": "reserve_bop_stress"},
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "external_balance",
        )

    def test_bottleneck_type_export_control_is_sanction(self) -> None:
        ev = _normalized_stub(
            hidden_mechanism={"bottleneck_type": "export_control_carveout"},
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""), "sanction",
        )

    def test_bottleneck_type_shipping_chokepoint_is_commodity_squeeze(self) -> None:
        ev = _normalized_stub(
            hidden_mechanism={"bottleneck_type": "shipping_chokepoint"},
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "commodity_squeeze",
        )

    def test_currency_balance_sheet_pair_is_external_balance(self) -> None:
        """Tier 4 — channel_domain + transmission_type pair."""
        ev = _normalized_stub(
            hidden_mechanism={
                "channel_domain":   "currency",
                "transmission_type": "balance_sheet",
            },
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "external_balance",
        )

    def test_em_asset_dominance_is_external_balance(self) -> None:
        """Tier 5 — asset-bucket signature when nothing else fires."""
        ev = _normalized_stub(
            primary_assets=[
                {"symbol": "EMB", "rank": 1, "rationale": "Sovereign spreads."},
                {"symbol": "EEM", "rank": 2, "rationale": "Broad EM equity."},
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "external_balance",
        )

    def test_bank_asset_dominance_is_bank_stress(self) -> None:
        ev = _normalized_stub(
            primary_assets=[
                {"symbol": "KRE", "rank": 1, "rationale": "Regional banks."},
                {"symbol": "HYG", "rank": 2, "rationale": "HY spreads."},
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "bank_stress",
        )

    def test_semi_asset_dominance_is_industrial_policy(self) -> None:
        ev = _normalized_stub(
            primary_assets=[
                {"symbol": "SMH", "rank": 1, "rationale": "Semis beneficiary."},
                {"symbol": "TSM", "rank": 2, "rationale": "Leading node capacity."},
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""),
            "industrial_policy",
        )

    def test_single_em_marker_insufficient(self) -> None:
        """Dominance heuristic requires ≥2 markers — a single EM ticker
        is not enough to classify."""
        ev = _normalized_stub(
            primary_assets=[
                {"symbol": "EMB", "rank": 1, "rationale": "Sovereign spreads."},
            ],
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline=""), "none",
        )

    def test_genuine_unknown_stays_none(self) -> None:
        """No keyword, no bottleneck, no structured hint → stays 'none'.
        This is the contract: we only rescue analyzable events, we don't
        force a classification."""
        ev = _normalized_stub(
            mechanism_summary="An event about something general.",
        )
        self.assertEqual(
            _post_parse_family_fallback(ev, headline="Ambiguous event"),
            "none",
        )


# ---------------------------------------------------------------------------
# 5. End-to-end: _finalize_analysis routes through the fallback
# ---------------------------------------------------------------------------


def _base_parsed(**overrides) -> dict:
    parsed = {
        "what_changed": "A concrete action happened with named actors.",
        "mechanism_summary": (
            "Primary channel transmits specifically; named winners and "
            "losers reallocate along a second-order wave."
        ),
        "beneficiaries":       ["Chevron"],
        "losers":              ["Suncor"],
        "beneficiary_tickers": ["CVX"],
        "loser_tickers":       ["SU"],
        "confidence":          "medium",
    }
    parsed.update(overrides)
    return parsed


class TestFinalizeRoutesThroughFallback(unittest.TestCase):
    def test_llm_none_but_ira_headline_upgrades_family(self) -> None:
        out = _finalize_analysis(
            _base_parsed(mechanism_family="none"),
            headline="CHIPS Act disbursement lands for TSMC Arizona fab",
            stage="realized",
            persistence="medium",
        )
        self.assertEqual(out["mechanism_family"], "industrial_policy")

    def test_llm_synonym_alias_resolves_via_clean(self) -> None:
        out = _finalize_analysis(
            _base_parsed(mechanism_family="antitrust"),
            headline="smoke",
            stage="realized",
            persistence="medium",
        )
        self.assertEqual(out["mechanism_family"], "regulation")

    def test_committed_family_never_overwritten(self) -> None:
        """If the LLM commits to sanction but the headline also contains
        tariff keywords, the committed family wins — the fallback must
        not override a valid commitment."""
        out = _finalize_analysis(
            _base_parsed(mechanism_family="sanction"),
            headline="Sanctions tighten ahead of tariff increase",
            stage="realized",
            persistence="medium",
        )
        self.assertEqual(out["mechanism_family"], "sanction")

    def test_unrecoverable_stays_none(self) -> None:
        """Genuinely ambiguous event with no evidence stays 'none' after
        every tier."""
        parsed = _base_parsed(
            mechanism_family="none",
            mechanism_summary="Executive makes general comment at conference.",
        )
        out = _finalize_analysis(
            parsed,
            headline="Executive comments on market",
            stage="realized",
            persistence="medium",
        )
        self.assertEqual(out["mechanism_family"], "none")


if __name__ == "__main__":
    unittest.main()
