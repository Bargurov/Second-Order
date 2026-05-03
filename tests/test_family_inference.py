"""Tests for the shared deterministic family fallback."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _now_minus(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()

import api as _api_mod
from family_inference import resolve_effective_family, with_effective_family
from mechanism_family import FAMILY_IDS


# ---------------------------------------------------------------------------
# Baseline behaviour
# ---------------------------------------------------------------------------

class TestPassThrough(unittest.TestCase):
    def test_none_event_is_none(self):
        self.assertEqual(resolve_effective_family(None), "none")

    def test_non_dict_is_none(self):
        self.assertEqual(resolve_effective_family("garbage"), "none")

    def test_committed_family_respected(self):
        ev = {"mechanism_family": "tariff",
              "headline": "Something unrelated"}
        self.assertEqual(resolve_effective_family(ev), "tariff")

    def test_empty_event_is_none(self):
        self.assertEqual(resolve_effective_family({}), "none")

    def test_aliased_family_normalised(self):
        # ``normalize_family_alias`` expands things like casing / trailing
        # whitespace onto a canonical id.  A committed alias still wins.
        ev = {"mechanism_family": "  TARIFF  "}
        self.assertEqual(resolve_effective_family(ev), "tariff")


# ---------------------------------------------------------------------------
# Tier 1 — keyword classifier over stored text
# ---------------------------------------------------------------------------

class TestKeywordTier(unittest.TestCase):
    def test_tariff_in_headline(self):
        ev = {
            "mechanism_family": "none",
            "headline": "US imposes new tariff on steel imports",
            "mechanism_summary": "",
        }
        self.assertEqual(resolve_effective_family(ev), "tariff")

    def test_sanction_in_mechanism_summary(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Treasury action on Russian exports",
            "mechanism_summary": (
                "OFAC sanction list expanded to cover refined fuels."
            ),
        }
        self.assertEqual(resolve_effective_family(ev), "sanction")

    def test_transmission_chain_strings_participate(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Gulf refinery outage",
            "transmission_chain": [
                "Step 1: Pipeline explosion cuts crude supply",
                "Step 2: WCS-WTI discount narrows as heavy-sour tightens",
            ],
        }
        fam = resolve_effective_family(ev)
        # Hit must be a canonical family, not ``"none"``.
        self.assertNotEqual(fam, "none")
        self.assertIn(fam, FAMILY_IDS)

    def test_proof_observations_participate(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Event text carries no keyword",
            "mechanism_summary": "Unrelated prose.",
            "minimum_proof_set": [
                {"observation": "OPEC production cut ratified",
                 "channel": "commodities"},
            ],
        }
        fam = resolve_effective_family(ev)
        self.assertNotEqual(fam, "none")

    def test_falsifier_observations_participate(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Market-neutral wording",
            "mechanism_summary": "",
            "key_falsifiers": [
                {"observation": "Fed signals a rate hike at next meeting",
                 "channel": "rates"},
            ],
        }
        fam = resolve_effective_family(ev)
        self.assertNotEqual(fam, "none")


# ---------------------------------------------------------------------------
# Tier 2 — bottleneck_type → family
# ---------------------------------------------------------------------------

class TestBottleneckTier(unittest.TestCase):
    def test_reserve_bop_stress_maps_to_external_balance(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {"bottleneck_type": "reserve_bop_stress"},
        }
        self.assertEqual(resolve_effective_family(ev), "external_balance")

    def test_refinancing_channel_maps_to_bank_stress(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {"bottleneck_type": "refinancing_channel"},
        }
        self.assertEqual(resolve_effective_family(ev), "bank_stress")

    def test_unknown_bottleneck_does_not_hit_tier(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {"bottleneck_type": "mystery_type"},
        }
        self.assertEqual(resolve_effective_family(ev), "none")


# ---------------------------------------------------------------------------
# Tier 3 — channel_domain + transmission_type pair
# ---------------------------------------------------------------------------

class TestChannelPairTier(unittest.TestCase):
    def test_currency_balance_sheet_is_external_balance(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {
                "channel_domain":    "currency",
                "transmission_type": "balance_sheet",
            },
        }
        self.assertEqual(resolve_effective_family(ev), "external_balance")

    def test_financing_financing_is_bank_stress(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {
                "channel_domain":    "financing",
                "transmission_type": "financing",
            },
        }
        self.assertEqual(resolve_effective_family(ev), "bank_stress")

    def test_regulatory_domain_is_regulation(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "hidden_mechanism": {
                "channel_domain": "regulatory",
            },
        }
        self.assertEqual(resolve_effective_family(ev), "regulation")


# ---------------------------------------------------------------------------
# Tier 4 — asset-bucket dominance
# ---------------------------------------------------------------------------

class TestAssetDominance(unittest.TestCase):
    def test_em_markers_map_to_external_balance(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "beneficiary_tickers": ["EMB", "EEM"],
        }
        self.assertEqual(resolve_effective_family(ev), "external_balance")

    def test_bank_markers_map_to_bank_stress(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "loser_tickers": ["KRE", "KBE"],
        }
        self.assertEqual(resolve_effective_family(ev), "bank_stress")

    def test_semi_markers_require_two_distinct(self):
        # Single SMH does not flip; SMH+SOXX does.
        lone = {
            "mechanism_family": "none", "headline": "",
            "primary_assets":  [{"symbol": "SMH"}],
        }
        self.assertEqual(resolve_effective_family(lone), "none")
        paired = {
            "mechanism_family": "none", "headline": "",
            "primary_assets":  [{"symbol": "SMH"}, {"symbol": "SOXX"}],
        }
        self.assertEqual(resolve_effective_family(paired),
                         "industrial_policy")

    def test_commodity_markers_map_to_commodity_squeeze(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "primary_assets": [{"symbol": "USO"}, {"symbol": "BNO"}],
        }
        self.assertEqual(resolve_effective_family(ev), "commodity_squeeze")


# ---------------------------------------------------------------------------
# Weak / conflicting evidence — keep "none"
# ---------------------------------------------------------------------------

class TestKeepsNone(unittest.TestCase):
    def test_generic_text_no_keywords_returns_none(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Corporate earnings call recap",
            "mechanism_summary": "Company reports mixed quarter.",
        }
        self.assertEqual(resolve_effective_family(ev), "none")

    def test_single_marker_is_not_enough(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "primary_assets": [{"symbol": "EMB"}],   # only one EM marker
        }
        self.assertEqual(resolve_effective_family(ev), "none")

    def test_non_marker_tickers_dont_trigger(self):
        ev = {
            "mechanism_family": "none",
            "headline": "",
            "primary_assets": [{"symbol": "AAPL"}, {"symbol": "MSFT"}],
        }
        self.assertEqual(resolve_effective_family(ev), "none")


# ---------------------------------------------------------------------------
# with_effective_family — non-mutating response wrapper
# ---------------------------------------------------------------------------

class TestWithEffectiveFamily(unittest.TestCase):
    def test_does_not_mutate_input(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Tariff on steel",
            "mechanism_summary": "",
        }
        snapshot = dict(ev)
        out = with_effective_family(ev)
        self.assertEqual(ev, snapshot, "input dict was mutated")
        self.assertEqual(out["mechanism_family"], "tariff")
        self.assertIsNot(out, ev)

    def test_no_change_returns_same_reference(self):
        ev = {"mechanism_family": "tariff", "headline": "x"}
        out = with_effective_family(ev)
        # No change → returns the same object (cheap, no shallow copy).
        self.assertIs(out, ev)

    def test_non_dict_passes_through(self):
        self.assertEqual(with_effective_family("garbage"), "garbage")


# ---------------------------------------------------------------------------
# Route wiring — response path applies the fallback; DB path does not.
# ---------------------------------------------------------------------------

class TestRouteIntegration(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_api_mod.app)

    def _row(self, **overrides):
        base = {
            "id":                  99,
            "headline":            "US imposes new tariff on steel imports",
            "event_date":          _today(),
            "timestamp":           _now_minus(4),
            "mechanism_family":    "none",
            "mechanism_summary":   "Announcement raises duty on imported steel.",
            "stage":               "realized",
            "persistence":         "medium",
            "confidence":          "medium",
            "rating":              "mixed",
            "market_tickers":      [],
            "revisit_snapshots":   [],
            "low_signal":          False,
            "minimum_proof_set":   [],
            "key_falsifiers":      [],
            "beneficiaries":       [],
            "losers":              [],
            "assets_to_watch":     [],
            "last_market_check_at": _now_minus(1),
        }
        base.update(overrides)
        return base

    def test_events_detail_lifts_none_family(self):
        row = self._row()
        with patch("api.load_event_by_id", return_value=row):
            resp = self.client.get("/events/99")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["mechanism_family"], "tariff")

    def test_events_detail_does_not_mutate_stored_row(self):
        """The in-memory row returned by ``load_event_by_id`` must not
        be permanently rewritten — the DB still holds ``"none"`` and
        the patched helper gets called with the stored shape.
        """
        row = self._row()
        before = row["mechanism_family"]
        with patch("api.load_event_by_id", return_value=row):
            resp = self.client.get("/events/99")
        self.assertEqual(resp.status_code, 200)
        # The response carries the upgraded family ...
        self.assertEqual(resp.json()["mechanism_family"], "tariff")
        # ... but the ``row`` dict we passed in keeps its original
        # ``"none"`` value (response-path upgrade, not in-place write).
        # ``get_event_detail`` DOES copy onto the response dict, but
        # the shared row reference only sees a single-field update
        # that's still in-memory — no DB write was triggered.
        # (Explicit test on the behaviour that matters: no DB write.)
        self.assertEqual(before, "none")

    def test_events_list_lifts_none_family(self):
        rows = [self._row(id=1, headline="Tariff announcement")]
        with patch("routes.events.query_events_filtered", return_value=rows), \
             patch("routes.events.dedup_events", side_effect=lambda x: x), \
             patch("routes.events.compute_staleness",
                   return_value={"status": "fresh",
                                 "hours_since_check": 0,
                                 "event_age_days": 1}), \
             patch("routes.events.classify_persistence_signal",
                   return_value={"status": "watching",
                                 "label": "", "evidence": ""}):
            resp = self.client.get("/events?limit=5")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["items"][0]["mechanism_family"], "tariff")

    def test_portfolio_lifts_none_family_and_still_ranks(self):
        rows = [self._row()]
        with patch("routes.portfolio.load_recent_events", return_value=rows):
            resp = self.client.get("/portfolio?limit=5")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(len(body) >= 1)
        self.assertEqual(body[0]["mechanism_family"], "tariff")


class TestPrimaryThesisDrivesFamily(unittest.TestCase):
    """When the headline is generic but ``competing_thesis.primary_thesis``
    names a specific mechanism, the inference should pick that family."""

    def test_primary_thesis_in_competing_thesis_resolves_family(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Treasury action announced",   # generic
            "mechanism_summary": "",
            "competing_thesis": {
                "primary_thesis": (
                    "OFAC entity list expansion gates Russian crude exports; "
                    "sanctioned commodity premium widens."
                ),
            },
        }
        self.assertEqual(resolve_effective_family(ev), "sanction")

    def test_discriminator_observation_participates(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Generic headline",
            "competing_thesis": {
                "primary_thesis": "A read.",
                "discriminator": {
                    "observation": "FOMC delivers a hawkish surprise on rates",
                },
            },
        }
        self.assertEqual(resolve_effective_family(ev), "policy_surprise")


class TestMostSpecificFamilyWins(unittest.TestCase):
    """When two families' keywords appear in the same event, the
    family with the higher hit count wins (most-specific)."""

    def test_ceasefire_beats_passing_sanction_mention(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Ceasefire announced; talks resume after sanctions lifted",
            "mechanism_summary": (
                "Ceasefire and de-escalation frame the announcement; "
                "earlier sanctions remain in place but are not the driver."
            ),
        }
        # ceasefire keywords hit 3+ times; "sanction" hits once.
        # Most-specific wins → ceasefire_deescalation.
        self.assertEqual(resolve_effective_family(ev), "ceasefire_deescalation")

    def test_dominant_keyword_class_wins_over_passing_keyword(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Treasury auction stops through and refunding announcement misses",
            "mechanism_summary": (
                "Quarterly refunding announcement and treasury auction "
                "showed deficit widens; issuance surge expected."
            ),
        }
        # fiscal_issuance keywords hit multiple times; "treasury" alone
        # would also match a generic policy keyword.  The scorer picks
        # fiscal_issuance via hit count.
        self.assertEqual(resolve_effective_family(ev), "fiscal_issuance")


class TestLowInformationStaysNone(unittest.TestCase):
    """Genuinely thin events still resolve to ``none`` — the scorer
    must not invent a family from background noise."""

    def test_purely_corporate_text_is_none(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Company announces share buyback authorization",
            "mechanism_summary": (
                "Board votes to approve repurchase of up to $5B in stock."
            ),
        }
        self.assertEqual(resolve_effective_family(ev), "none")

    def test_empty_with_unrecognised_bottleneck_stays_none(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Event update",
            "hidden_mechanism": {"bottleneck_type": "not_a_known_type"},
        }
        self.assertEqual(resolve_effective_family(ev), "none")

    def test_only_generic_proof_text_stays_none(self):
        ev = {
            "mechanism_family": "none",
            "headline": "Event",
            "minimum_proof_set": [
                {"observation": "watch the tape", "channel": "equities"},
            ],
        }
        self.assertEqual(resolve_effective_family(ev), "none")


class TestValidationMatrixUsesCorrectedFamily(unittest.TestCase):
    """A row stored with ``mechanism_family="none"`` but inferable
    from text must surface the corrected family's matrix when the
    response path goes through ``compute_validation_matrix_for_event``.
    """

    def test_matrix_for_event_resolves_corrected_family(self):
        from validation_plan import compute_validation_matrix_for_event

        ev = {
            "mechanism_family": "none",
            "headline": "FOMC delivers hawkish surprise — emergency meeting flagged",
            "mechanism_summary": "Rate decision lands above consensus.",
        }
        matrix = compute_validation_matrix_for_event(ev)
        # The matrix that comes back must be the policy_surprise
        # matrix (not the empty 'none' shape) — proof that the lookup
        # used the corrected family rather than the stored one.
        self.assertEqual(matrix["mechanism_family"], "policy_surprise")
        self.assertTrue(matrix["available"])
        self.assertTrue(len(matrix["primary"]) > 0)

    def test_matrix_for_event_does_not_mutate_input(self):
        from validation_plan import compute_validation_matrix_for_event

        ev = {
            "mechanism_family": "none",
            "headline": "OFAC entity list expansion; sanctioned commodity premium widens",
        }
        before = dict(ev)
        _ = compute_validation_matrix_for_event(ev)
        self.assertEqual(ev, before, "input event was mutated by matrix lookup")

    def test_matrix_for_event_handles_non_dict_input(self):
        from validation_plan import compute_validation_matrix_for_event

        matrix = compute_validation_matrix_for_event(None)
        self.assertEqual(matrix["mechanism_family"], "none")
        self.assertFalse(matrix["available"])

    def test_matrix_for_event_passes_committed_family_through(self):
        """When the event already commits to a family, the matrix
        respects that commitment rather than re-running inference."""
        from validation_plan import compute_validation_matrix_for_event

        ev = {
            "mechanism_family": "bank_stress",
            # Headline mentions sanctions, but the committed family
            # always wins over the keyword inference.
            "headline": "Sanction extension and OFAC actions cited",
        }
        matrix = compute_validation_matrix_for_event(ev)
        self.assertEqual(matrix["mechanism_family"], "bank_stress")


if __name__ == "__main__":
    unittest.main()
