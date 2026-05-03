"""Tests for /portfolio thesis-quality filters + summary counts."""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from datetime import datetime, timedelta
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import api as _api_mod


def _now_minus(hours: float) -> str:
    return (datetime.now() - timedelta(hours=hours)).isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().date().isoformat()
from portfolio_flags import PROOF_QUALITY_BUCKETS
from thesis_state import THESIS_STATES


def _ticker(symbol: str, *, return_5d: float = 3.0, direction_tag: str = "supports thesis",
            evidence_score: float | None = None,
            evidence_label: str | None = None,
            role: str = "beneficiary") -> dict:
    t = {
        "symbol":         symbol,
        "role":           role,
        "return_5d":      return_5d,
        "direction_tag":  direction_tag,
    }
    if evidence_score is not None:
        t["evidence_score"] = evidence_score
    if evidence_label is not None:
        t["evidence_label"] = evidence_label
    return t


def _event(
    *, event_id: int,
    mechanism_family: str = "commodity_squeeze",
    mechanism_summary: str = "Refinery outage tightens capacity.",
    confidence: str = "medium",
    rating: str = "good",
    minimum_proof_set: list | None = None,
    key_falsifiers: list | None = None,
    market_tickers: list | None = None,
    primary_assets: list | None = None,
    last_market_check_at: str | None = None,
    event_date: str | None = None,
) -> dict:
    return {
        "id":                   event_id,
        "headline":             f"Event {event_id}",
        "event_date":           event_date or _today(),
        "timestamp":            _now_minus(4),
        "mechanism_family":     mechanism_family,
        "mechanism_summary":    mechanism_summary,
        "stage":                "realized",
        "persistence":          "medium",
        "confidence":           confidence,
        "rating":               rating,
        "minimum_proof_set":    minimum_proof_set or [],
        "key_falsifiers":       key_falsifiers or [],
        "market_tickers":       market_tickers or [],
        # Direct-name single-stock picks — required so the broad-beta
        # filter in ``score_weighted_evidence`` doesn't downgrade a
        # supportive ETF basket to ``mixed`` (a primary single-name
        # contributor is needed to ride a ``supportive`` aggregate).
        "primary_assets":       primary_assets or [],
        "revisit_snapshots":    [],
        "low_signal":           False,
        "last_market_check_at": last_market_check_at or _now_minus(0.5),
        "regime_snapshot":      {"available": False},
    }


# Direct-name single-stock picks pass the channel-keyed registry
# rejection in ``_is_primary_asset`` (USO / XLE are channel-keyed and
# can't be primary); these symbols carry no channel so they classify
# as primary when listed in ``primary_assets``.
def _confirming_event(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        primary_assets=[{"symbol": "XOM"}, {"symbol": "CVX"}],
        market_tickers=[
            _ticker("XOM", evidence_score=0.85, evidence_label="supportive"),
            _ticker("CVX", evidence_score=0.80, evidence_label="supportive"),
        ],
    )


def _falsified_event(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[{"observation": "Y", "channel": "commodities"}],
        primary_assets=[{"symbol": "XOM"}, {"symbol": "CVX"}],
        market_tickers=[
            _ticker("XOM", evidence_score=-0.8, evidence_label="contradictory",
                    direction_tag="contradicts down"),
            _ticker("CVX", evidence_score=-0.7, evidence_label="contradictory",
                    direction_tag="contradicts down"),
        ],
    )


def _partial_proof_event(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[{"observation": "X", "channel": "commodities"}],
        key_falsifiers=[],
        primary_assets=[{"symbol": "XOM"}, {"symbol": "CVX"}],
        market_tickers=[
            _ticker("XOM", evidence_score=0.4, evidence_label="mixed"),
            _ticker("CVX", evidence_score=0.3, evidence_label="mixed"),
        ],
    )


def _no_proof_event(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        minimum_proof_set=[],
        key_falsifiers=[],
        primary_assets=[{"symbol": "XOM"}, {"symbol": "CVX"}],
        market_tickers=[
            _ticker("XOM", evidence_score=0.2, evidence_label="mixed"),
            _ticker("CVX", evidence_score=0.1, evidence_label="mixed"),
        ],
    )


def _low_info_event(event_id: int) -> dict:
    return _event(
        event_id=event_id,
        confidence="low",
        mechanism_summary="Insufficient evidence to characterise.",
        primary_assets=[{"symbol": "XOM"}, {"symbol": "CVX"}],
        market_tickers=[
            _ticker("XOM", evidence_score=0.2, evidence_label="mixed"),
            _ticker("CVX", evidence_score=0.1, evidence_label="mixed"),
        ],
    )


class _PortfolioFixture(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(_api_mod.app)

    def _get(self, rows: list[dict], **params) -> tuple[int, object]:
        with patch("routes.portfolio.load_recent_events", return_value=rows):
            resp = self.client.get("/portfolio", params=params)
        return resp.status_code, resp.json()


# ---------------------------------------------------------------------------
# Backward-compatibility: default shape stays a list
# ---------------------------------------------------------------------------

class TestDefaultShapeStable(_PortfolioFixture):
    def test_no_filter_returns_list(self):
        status, body = self._get(
            [_confirming_event(1), _low_info_event(2)], limit=5,
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_no_filter_items_include_new_fields(self):
        status, body = self._get(
            [_confirming_event(1), _low_info_event(2)], limit=5,
        )
        self.assertEqual(status, 200)
        for entry in body:
            self.assertIn("thesis_state",  entry)
            self.assertIn("proof_quality", entry)
            self.assertIn(entry["thesis_state"],  THESIS_STATES)
            self.assertIn(entry["proof_quality"], PROOF_QUALITY_BUCKETS)


# ---------------------------------------------------------------------------
# Per-filter behaviour
# ---------------------------------------------------------------------------

class TestThesisStateFilter(_PortfolioFixture):
    def test_filter_selects_matching_state_only(self):
        rows = [
            _confirming_event(1),
            _falsified_event(2),
            _low_info_event(3),
        ]
        status, body = self._get(
            rows, limit=10, thesis_state="confirming",
        )
        self.assertEqual(status, 200)
        self.assertIn("items", body)
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {1})

    def test_filter_can_return_empty(self):
        rows = [_confirming_event(1)]
        _, body = self._get(rows, limit=10, thesis_state="falsified")
        self.assertEqual(body["items"], [])

    def test_invalid_thesis_state_is_400(self):
        status, _ = self._get([], thesis_state="not_a_state")
        self.assertEqual(status, 400)


class TestProofQualityFilter(_PortfolioFixture):
    def test_filter_selects_matching_bucket_only(self):
        rows = [
            _confirming_event(1),   # proof_backed
            _partial_proof_event(2),  # partial_proof
            _no_proof_event(3),     # no_proof
            _low_info_event(4),     # low_information
            _falsified_event(5),    # falsified
        ]
        _, body = self._get(rows, limit=10, proof_quality="proof_backed")
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {1})

    def test_filter_partial_proof_bucket(self):
        rows = [_confirming_event(1), _partial_proof_event(2)]
        _, body = self._get(rows, limit=10, proof_quality="partial_proof")
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {2})

    def test_invalid_proof_quality_is_400(self):
        status, _ = self._get([], proof_quality="not_a_bucket")
        self.assertEqual(status, 400)


class TestLowInformationFilter(_PortfolioFixture):
    def test_true_returns_only_low_info(self):
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(rows, limit=10, low_information="true")
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {2})

    def test_false_excludes_low_info(self):
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(rows, limit=10, low_information="false")
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {1})


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------

class TestCombinedFilters(_PortfolioFixture):
    def test_all_three_must_agree(self):
        rows = [
            _confirming_event(1),
            _partial_proof_event(2),
            _low_info_event(3),
            _falsified_event(4),
        ]
        _, body = self._get(
            rows, limit=10,
            thesis_state="confirming",
            proof_quality="proof_backed",
            low_information="false",
        )
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {1})

    def test_conflicting_filters_return_empty(self):
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(
            rows, limit=10,
            thesis_state="confirming",
            low_information="true",
        )
        self.assertEqual(body["items"], [])


# ---------------------------------------------------------------------------
# Summary counts
# ---------------------------------------------------------------------------

class TestSummaryCounts(_PortfolioFixture):
    def test_counts_block_present_when_filter_active(self):
        _, body = self._get(
            [_confirming_event(1)], limit=5, thesis_state="confirming",
        )
        self.assertIn("thesis_state_counts",  body)
        self.assertIn("proof_quality_counts", body)

    def test_counts_cover_full_enum(self):
        _, body = self._get(
            [_confirming_event(1)], limit=5, thesis_state="confirming",
        )
        self.assertEqual(
            set(body["thesis_state_counts"].keys()),
            set(THESIS_STATES),
        )
        self.assertEqual(
            set(body["proof_quality_counts"].keys()),
            set(PROOF_QUALITY_BUCKETS),
        )

    def test_counts_match_filtered_items(self):
        rows = [
            _confirming_event(1),
            _confirming_event(2),
            _partial_proof_event(3),
        ]
        _, body = self._get(rows, limit=10, thesis_state="confirming")
        items = body["items"]
        self.assertEqual(len(items), 2)
        self.assertEqual(body["thesis_state_counts"]["confirming"], 2)
        # Unmatched states are zero, not missing.
        self.assertEqual(body["thesis_state_counts"]["falsified"], 0)
        self.assertEqual(body["proof_quality_counts"]["proof_backed"], 2)

    def test_counts_only_reflect_rendered_items_not_full_archive(self):
        """Counts come from the filtered + ranked result set, not the
        pre-filter archive."""
        rows = [
            _confirming_event(1),
            _low_info_event(2),
            _low_info_event(3),
        ]
        _, body = self._get(rows, limit=10, low_information="true")
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["thesis_state_counts"]["low_information"], 2)
        self.assertEqual(body["thesis_state_counts"]["confirming"], 0)


# ---------------------------------------------------------------------------
# Engine-phase filters: quality_tier / tradable / mechanism_subtype
# ---------------------------------------------------------------------------


class TestQualityTierFilter(_PortfolioFixture):
    def test_invalid_quality_tier_is_400(self):
        status, _ = self._get([], quality_tier="not_a_tier")
        self.assertEqual(status, 400)

    def test_filter_returns_only_matching_tier(self):
        """Filter contract: every kept row must carry the requested
        tier.  We do NOT assert which synthetic event lands where —
        the gate's tier classification depends on prose specificity
        and would be brittle to pin to specific ids here."""
        rows = [_confirming_event(1), _low_info_event(2)]
        status, body = self._get(rows, limit=10, quality_tier="low_information")
        self.assertEqual(status, 200)
        self.assertIn("items", body)
        for e in body["items"]:
            self.assertEqual(e["quality_tier"], "low_information")


class TestTradableFilter(_PortfolioFixture):
    def test_true_excludes_non_tradable(self):
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(rows, limit=10, tradable="true")
        for e in body["items"]:
            self.assertTrue(e["actionability_check"]["tradable"])

    def test_false_excludes_tradable(self):
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(rows, limit=10, tradable="false")
        for e in body["items"]:
            self.assertFalse(e["actionability_check"]["tradable"])


class TestMechanismSubtypeFilter(_PortfolioFixture):
    def test_unknown_subtype_returns_empty(self):
        """An unknown subtype is allowed (no global enum) — it just
        yields zero results rather than 400."""
        rows = [_confirming_event(1), _low_info_event(2)]
        status, body = self._get(rows, limit=10, mechanism_subtype="not_a_real_subtype")
        self.assertEqual(status, 200)
        self.assertEqual(body["items"], [])


# ---------------------------------------------------------------------------
# Combination with existing filters
# ---------------------------------------------------------------------------


class TestEngineFilterCombination(_PortfolioFixture):
    def test_quality_tier_combines_with_low_information(self):
        """Both filters must agree — a low_information row should be
        kept by ``low_information=true`` AND ``quality_tier=low_information``."""
        rows = [_confirming_event(1), _low_info_event(2)]
        _, body = self._get(
            rows, limit=10,
            low_information="true", quality_tier="low_information",
        )
        ids = {e["id"] for e in body["items"]}
        self.assertEqual(ids, {2})

    def test_tradable_true_with_low_information_true_returns_empty(self):
        """A low_information row is never tradable; the combination
        must therefore yield zero results."""
        rows = [_low_info_event(1), _low_info_event(2)]
        _, body = self._get(
            rows, limit=10,
            low_information="true", tradable="true",
        )
        self.assertEqual(body["items"], [])


# ---------------------------------------------------------------------------
# Default shape preservation + new count blocks
# ---------------------------------------------------------------------------


class TestNewCountBlocks(_PortfolioFixture):
    def test_default_shape_remains_a_bare_list_with_no_filters(self):
        """The new filter params don't add count blocks unless one of
        them (or any other filter) is active."""
        status, body = self._get(
            [_confirming_event(1), _low_info_event(2)], limit=5,
        )
        self.assertEqual(status, 200)
        self.assertIsInstance(body, list)

    def test_quality_tier_counts_present_and_full_enum(self):
        _, body = self._get(
            [_confirming_event(1), _low_info_event(2)],
            limit=10, quality_tier="low_information",
        )
        self.assertIn("quality_tier_counts", body)
        # Archive-wide tally — every tier in the closed enum has a row.
        self.assertEqual(
            set(body["quality_tier_counts"].keys()),
            {"actionable", "watch_only", "low_information"},
        )
        # Counts are pre-filter (archive-wide), so a tier-restricted
        # response still surfaces every tier's true archive count.
        self.assertGreaterEqual(body["quality_tier_counts"]["low_information"], 1)

    def test_tradable_counts_carry_both_string_keys(self):
        _, body = self._get(
            [_confirming_event(1), _low_info_event(2)],
            limit=10, tradable="false",
        )
        self.assertIn("tradable_counts", body)
        self.assertEqual(
            set(body["tradable_counts"].keys()), {"true", "false"},
        )
        # Post-filter contract — since we filtered to tradable=false,
        # every kept row contributes to the "false" bucket only.
        for e in body["items"]:
            self.assertFalse(e["actionability_check"]["tradable"])
        self.assertEqual(body["tradable_counts"]["true"], 0)

    def test_mechanism_subtype_counts_open_dict_only_observed_keys(self):
        """``mechanism_subtype_counts`` must NOT pre-fill the global
        registry — only subtypes that actually appear in the rendered
        items get a row."""
        _, body = self._get(
            [_confirming_event(1), _low_info_event(2)],
            limit=10, low_information="false",
        )
        self.assertIn("mechanism_subtype_counts", body)
        observed = {
            e.get("mechanism_subtype")
            for e in body["items"]
            if e.get("mechanism_subtype")
        }
        self.assertEqual(set(body["mechanism_subtype_counts"].keys()), observed)


if __name__ == "__main__":
    unittest.main()
