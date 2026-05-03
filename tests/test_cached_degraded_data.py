"""
tests/test_cached_degraded_data.py

Focused tests for two cache-correctness fixes:

  1. data_quality / data_quality_note survive cache hits
     (refresh_market_for_saved_event + _build_cached_response).

  2. /movers/today in-memory cache is invalidated when a new event is
     persisted via _persist_event.
"""

from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_check
import market_check_freshness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _degraded_ticker(symbol: str, role: str = "beneficiary") -> dict:
    """Ticker that returned no price data — contributes to degraded signal."""
    return {
        "symbol": symbol,
        "role": role,
        "label": "needs more evidence",
        "return_1d": None,
        "return_5d": None,
        "return_20d": None,
        "volume_ratio": None,
        "spark": [],
        "direction_tag": None,
    }


def _healthy_ticker(symbol: str, role: str = "beneficiary") -> dict:
    """Ticker with real return data — does not degrade quality signal."""
    return {
        "symbol": symbol,
        "role": role,
        "label": "in motion",
        "return_1d": 0.5,
        "return_5d": 1.2,
        "return_20d": 2.4,
        "volume_ratio": 1.1,
        "spark": [0.1] * 20,
        "direction_tag": "up",
    }


def _minimal_saved_event(tickers: list) -> dict:
    """Minimal event dict as returned by db.load_event_by_id."""
    return {
        "id": 42,
        "headline": "Test event",
        "stage": "realized",
        "persistence": "medium",
        "timestamp": (datetime.now() - timedelta(hours=2)).isoformat(timespec="seconds"),
        "event_date": (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"),
        "market_tickers": tickers,
        "market_note": "Test note",
        "last_market_check_at": datetime.now().isoformat(timespec="seconds"),
        "what_changed": "Something changed",
        "mechanism_summary": "Mechanism",
        "beneficiaries": [],
        "losers": [],
        "assets_to_watch": [],
        "confidence": "medium",
        "transmission_chain": [],
        "if_persists": {},
        "currency_channel": {},
        "policy_sensitivity": {},
        "inventory_context": {},
        "regime_snapshot": {},
        "real_yield_context": {},
        "policy_constraint": {},
        "shock_decomposition": {},
        "reaction_function_divergence": {},
        "surprise_vs_anticipation": {},
        "terms_of_trade": {},
        "reserve_stress": {},
    }


# ---------------------------------------------------------------------------
# 1. data_quality on the market_check_freshness non-refresh path
# ---------------------------------------------------------------------------

class TestDataQualityOnNonRefreshPath(unittest.TestCase):
    """refresh_market_for_saved_event returns data_quality from stored tickers
    even when the staleness check says no refresh is needed (fresh/frozen)."""

    def _call_no_refresh(self, tickers: list) -> dict:
        """Force the non-refresh (fast-return) path."""
        event = _minimal_saved_event(tickers)
        # Patch should_refresh to always return False → exercises base_payload path.
        with patch.object(market_check_freshness, "should_refresh", return_value=False):
            return market_check_freshness.refresh_market_for_saved_event(event)

    def test_all_degraded_tickers_sets_degraded(self):
        tickers = [_degraded_ticker("A"), _degraded_ticker("B")]
        result = self._call_no_refresh(tickers)
        self.assertEqual(result.get("data_quality"), "degraded")
        self.assertIn("data_quality_note", result)

    def test_all_healthy_tickers_sets_ok(self):
        tickers = [_healthy_ticker("A"), _healthy_ticker("B")]
        result = self._call_no_refresh(tickers)
        self.assertEqual(result.get("data_quality"), "ok")
        self.assertNotIn("data_quality_note", result)

    def test_empty_tickers_sets_ok(self):
        result = self._call_no_refresh([])
        self.assertEqual(result.get("data_quality"), "ok")


# ---------------------------------------------------------------------------
# 2. data_quality on the market_check_freshness refresh path
# ---------------------------------------------------------------------------

class TestDataQualityOnRefreshPath(unittest.TestCase):
    """After a followup_check refresh, data_quality is derived from the
    merged tickers (not just the stored ones)."""

    def test_degraded_after_refresh_all_null_returns(self):
        tickers = [_degraded_ticker("X"), _degraded_ticker("Y")]
        event = _minimal_saved_event(tickers)

        # followup_check returns tickers with no return data → still degraded
        def fake_followup(stored, event_date):
            return [{"symbol": t["symbol"], "return_1d": None, "return_5d": None}
                    for t in stored]

        with patch.object(market_check_freshness, "should_refresh", return_value=True), \
             patch.object(market_check_freshness, "compute_staleness",
                          return_value={"status": "stale", "natural_status": "stale",
                                        "reason": "stale", "event_age_days": 3}):
            result = market_check_freshness.refresh_market_for_saved_event(
                event,
                followup_check_fn=fake_followup,
                market_check_fn=MagicMock(),
                persist_fn=MagicMock(),
            )

        self.assertEqual(result.get("data_quality"), "degraded")

    def test_ok_after_refresh_with_returns(self):
        tickers = [_degraded_ticker("X"), _degraded_ticker("Y")]
        event = _minimal_saved_event(tickers)

        # followup_check returns healthy data → quality recovers to ok
        def fake_followup(stored, event_date):
            return [{"symbol": t["symbol"], "return_1d": 0.5, "return_5d": 1.2}
                    for t in stored]

        with patch.object(market_check_freshness, "should_refresh", return_value=True), \
             patch.object(market_check_freshness, "compute_staleness",
                          return_value={"status": "stale", "natural_status": "stale",
                                        "reason": "stale", "event_age_days": 3}):
            result = market_check_freshness.refresh_market_for_saved_event(
                event,
                followup_check_fn=fake_followup,
                market_check_fn=MagicMock(),
                persist_fn=MagicMock(),
            )

        self.assertEqual(result.get("data_quality"), "ok")
        self.assertNotIn("data_quality_note", result)


# ---------------------------------------------------------------------------
# 3. _build_cached_response forwards data_quality into the market block
# ---------------------------------------------------------------------------

class TestBuildCachedResponseDataQuality(unittest.TestCase):
    """_build_cached_response includes data_quality / data_quality_note in the
    returned market dict, sourced from the market block."""

    def _call_build_cached(self, market_block_extra: dict) -> dict:
        import api

        event = _minimal_saved_event([_degraded_ticker("XYZ")])

        degraded_block = {
            "tickers": event["market_tickers"],
            "note": "Test note",
            "details": {},
            "last_market_check_at": event["last_market_check_at"],
            "market_check_staleness": "fresh",
            "freshness_reason": "fresh",
            "event_age_days": 1,
            **market_block_extra,
        }

        with patch("api.refresh_market_for_saved_event", return_value=degraded_block), \
             patch("api.find_historical_analogs", return_value=[]), \
             patch("api.compute_rates_context", side_effect=Exception("no rates")), \
             patch("api.compute_stress_regime", side_effect=Exception("no stress")), \
             patch("api.build_regime_vector", return_value=None), \
             patch("api.compute_shock_decomposition", return_value={}), \
             patch("api.compute_reaction_function_divergence", return_value={}), \
             patch("api.compute_surprise_vs_anticipation", return_value={}), \
             patch("api.compute_terms_of_trade", return_value={}), \
             patch("api.compute_reserve_stress", return_value={}), \
             patch("api.classify_policy_sensitivity", return_value={}), \
             patch("api.classify_inventory_context", return_value={}), \
             patch("api.build_real_yield_context", return_value={}), \
             patch("api.compute_policy_constraint", return_value={}):
            return api._build_cached_response(
                event, event["headline"], event["event_date"],
            )

    def test_degraded_quality_forwarded(self):
        resp = self._call_build_cached({
            "data_quality": "degraded",
            "data_quality_note": "2/2 tickers returned no price data — market validation is incomplete",
        })
        self.assertEqual(resp["market"]["data_quality"], "degraded")
        self.assertEqual(
            resp["market"]["data_quality_note"],
            "2/2 tickers returned no price data — market validation is incomplete",
        )

    def test_ok_quality_forwarded(self):
        resp = self._call_build_cached({"data_quality": "ok"})
        self.assertEqual(resp["market"]["data_quality"], "ok")
        self.assertIsNone(resp["market"].get("data_quality_note"))

    def test_missing_quality_defaults_to_ok(self):
        """Legacy market blocks without data_quality → safe fallback."""
        resp = self._call_build_cached({})
        self.assertEqual(resp["market"]["data_quality"], "ok")


# ---------------------------------------------------------------------------
# 4. _persist_event invalidates today-movers cache on successful save
# ---------------------------------------------------------------------------

class TestPersistEventBustsTodayMoversCache(unittest.TestCase):

    def _call_persist(self, *, save_raises: bool = False) -> None:
        import api

        analysis = {
            "what_changed": "X", "mechanism_summary": "M",
            "beneficiaries": ["AAPL"], "losers": ["GOOG"],
            "assets_to_watch": [], "confidence": "medium",
            "transmission_chain": [], "if_persists": {},
            "currency_channel": {}, "policy_sensitivity": {},
            "inventory_context": {}, "regime_snapshot": {},
            "real_yield_context": {}, "policy_constraint": {},
            "shock_decomposition": {}, "reaction_function_divergence": {},
            "surprise_vs_anticipation": {}, "terms_of_trade": {},
            "reserve_stress": {},
        }
        mkt = {"note": "note", "tickers": []}

        if save_raises:
            with patch("api.save_event", side_effect=RuntimeError("db down")):
                api._persist_event("Test headline", "realized", "medium",
                                   analysis, mkt, "2026-04-13")
        else:
            with patch("api.save_event"):
                api._persist_event("Test headline", "realized", "medium",
                                   analysis, mkt, "2026-04-13")

    def test_cache_busted_on_successful_save(self):
        import api
        api._TODAYS_MOVERS_CACHE["data"] = [{"headline": "stale"}]
        self._call_persist(save_raises=False)
        self.assertIsNone(api._TODAYS_MOVERS_CACHE["data"])

    def test_cache_not_busted_when_save_fails(self):
        import api
        api._TODAYS_MOVERS_CACHE["data"] = [{"headline": "still valid"}]
        self._call_persist(save_raises=True)
        self.assertIsNotNone(api._TODAYS_MOVERS_CACHE["data"])


if __name__ == "__main__":
    unittest.main()
