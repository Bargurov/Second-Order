"""
tests/test_market_context.py

Tests for the unified market_context surface and the /market-context endpoint.

Covers:
  - Pure compose_market_context with full / partial / empty inputs
  - Section summarisers (snapshots / stress / highlights)
  - Provider name detection
  - End-to-end /market-context endpoint via FastAPI TestClient
  - Stale snapshot behaviour through the endpoint
  - Partial availability (snapshots fail / stress fails / highlights fail)
  - Endpoint never raises on provider failure
"""

import os
import sys
import time
import unittest
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

sys.path.insert(0, ".")

import api as api_module
import market_check
import market_snapshots
from market_context import (
    _normalize_stress,
    _provider_name,
    _summarize_highlights,
    _summarize_snapshots,
    compose_market_context,
)
from market_data import (
    PolygonProvider,
    YFinanceProvider,
    get_provider,
    set_provider,
)
from market_snapshots import (
    SNAPSHOT_MAX_AGE_SECONDS,
    get_store,
    refresh_all,
    stop_background_refresh,
)
from market_universe import LIQUID_MARKETS


def _make_df(closes):
    n = len(closes)
    return pd.DataFrame(
        {"Close": closes, "Volume": [1_000_000.0] * n},
        index=pd.date_range("2026-03-01", periods=n, freq="B"),
    )


def _good_df():
    return _make_df([100.0 + i * 0.5 for i in range(30)])


def _make_snapshot(market: str, value=100.0, change=1.5,
                   stale=False, error=None) -> dict:
    return {
        "market": market,
        "symbol": f"{market}-SYM",
        "label": f"{market} label",
        "unit": "idx",
        "asset_class": "equity_index",
        "source": "yfinance",
        "value": value,
        "change_1d": 0.5,
        "change_5d": change,
        "fetched_at": "2026-04-07T12:00:00+00:00",
        "error": error,
        "stale": stale,
    }


def _full_snapshots() -> list[dict]:
    return [_make_snapshot(m, value=100.0 + i, change=1.0 + i * 0.1)
            for i, m in enumerate(LIQUID_MARKETS)]


def _stress_dict() -> dict:
    return {
        "regime": "Calm",
        "summary": "Markets stable",
        "signals": {"vix_elevated": False},
        "raw": {"vix": 14.5},
        "detail": {"volatility": {"label": "Volatility"}},
    }


def _highlights() -> list[dict]:
    return [
        {"event_id": 1, "headline": "Test event 1", "impact": 4.5,
         "support_ratio": 1.0, "tickers": []},
        {"event_id": 2, "headline": "Test event 2", "impact": 3.2,
         "support_ratio": 0.5, "tickers": []},
    ]


# ---------------------------------------------------------------------------
# Section summarisers
# ---------------------------------------------------------------------------

class TestSummarizeSnapshots(unittest.TestCase):

    def test_empty(self):
        meta = _summarize_snapshots([])
        self.assertEqual(meta, {"total": 0, "fresh": 0, "stale": 0, "unavailable": 0})

    def test_all_fresh(self):
        snaps = _full_snapshots()
        meta = _summarize_snapshots(snaps)
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["fresh"], 8)
        self.assertEqual(meta["stale"], 0)
        self.assertEqual(meta["unavailable"], 0)

    def test_mixed(self):
        snaps = _full_snapshots()
        snaps[0]["stale"] = True
        snaps[1]["value"] = None
        snaps[1]["error"] = "no data"
        meta = _summarize_snapshots(snaps)
        self.assertEqual(meta["total"], 8)
        self.assertEqual(meta["fresh"], 6)
        self.assertEqual(meta["stale"], 1)
        self.assertEqual(meta["unavailable"], 1)

    def test_all_unavailable(self):
        snaps = [_make_snapshot(m, value=None, error="no data") for m in LIQUID_MARKETS]
        meta = _summarize_snapshots(snaps)
        self.assertEqual(meta["unavailable"], 8)
        self.assertEqual(meta["fresh"], 0)


class TestNormalizeStress(unittest.TestCase):

    def test_normal_dict(self):
        result = _normalize_stress(_stress_dict())
        self.assertEqual(result["regime"], "Calm")
        self.assertTrue(result["available"])

    def test_none_returns_degraded(self):
        result = _normalize_stress(None)
        self.assertEqual(result["regime"], "Unknown")
        self.assertFalse(result["available"])
        # Required keys still present
        for key in ("regime", "summary", "signals", "raw", "detail"):
            self.assertIn(key, result)

    def test_non_dict_returns_degraded(self):
        result = _normalize_stress("not a dict")  # type: ignore
        self.assertEqual(result["regime"], "Unknown")
        self.assertFalse(result["available"])

    def test_explicit_available_preserved(self):
        stress = _stress_dict()
        stress["available"] = True
        result = _normalize_stress(stress)
        self.assertTrue(result["available"])


class TestSummarizeHighlights(unittest.TestCase):

    def test_count(self):
        meta = _summarize_highlights(_highlights())
        self.assertEqual(meta["count"], 2)
        self.assertEqual(meta["source"], "movers/today")

    def test_empty(self):
        meta = _summarize_highlights([])
        self.assertEqual(meta["count"], 0)


# ---------------------------------------------------------------------------
# compose_market_context — pure function tests
# ---------------------------------------------------------------------------

class TestComposeMarketContext(unittest.TestCase):

    def test_full_data_shape(self):
        result = compose_market_context(
            _full_snapshots(), _stress_dict(), _highlights(), source="yfinance",
        )
        # Top-level keys
        for key in ("built_at", "source", "snapshots", "snapshots_meta",
                    "stress", "highlights", "highlights_meta"):
            self.assertIn(key, result)

    def test_built_at_is_iso_string(self):
        result = compose_market_context([], None, [], source="yfinance")
        self.assertIsInstance(result["built_at"], str)
        # Basic ISO sanity check
        self.assertIn("T", result["built_at"])

    def test_source_param_used(self):
        result = compose_market_context([], None, [], source="polygon")
        self.assertEqual(result["source"], "polygon")

    def test_full_snapshots_meta(self):
        result = compose_market_context(_full_snapshots(), None, [])
        self.assertEqual(result["snapshots_meta"]["total"], 8)
        self.assertEqual(result["snapshots_meta"]["fresh"], 8)

    def test_full_data_carries_freshness_per_snapshot(self):
        result = compose_market_context(_full_snapshots(), None, [])
        for snap in result["snapshots"]:
            self.assertIn("fetched_at", snap)
            self.assertIn("stale", snap)
            self.assertIn("source", snap)

    def test_stress_normalized_when_none(self):
        result = compose_market_context([], None, [])
        self.assertEqual(result["stress"]["regime"], "Unknown")
        self.assertFalse(result["stress"]["available"])

    def test_stress_passthrough_when_present(self):
        result = compose_market_context([], _stress_dict(), [])
        self.assertEqual(result["stress"]["regime"], "Calm")
        self.assertTrue(result["stress"]["available"])

    def test_empty_inputs_no_crash(self):
        result = compose_market_context([], None, [])
        self.assertEqual(result["snapshots"], [])
        self.assertEqual(result["highlights"], [])
        self.assertEqual(result["snapshots_meta"]["total"], 0)
        self.assertEqual(result["highlights_meta"]["count"], 0)

    def test_none_inputs_treated_as_empty(self):
        result = compose_market_context(None, None, None)  # type: ignore
        self.assertEqual(result["snapshots"], [])
        self.assertEqual(result["highlights"], [])

    def test_partial_snapshots(self):
        snaps = _full_snapshots()[:4]  # only 4 of 8
        snaps[0]["stale"] = True
        result = compose_market_context(snaps, _stress_dict(), _highlights())
        self.assertEqual(result["snapshots_meta"]["total"], 4)
        self.assertEqual(result["snapshots_meta"]["stale"], 1)
        self.assertEqual(result["snapshots_meta"]["fresh"], 3)

    def test_stale_snapshot_propagated(self):
        snaps = _full_snapshots()
        snaps[0]["stale"] = True
        result = compose_market_context(snaps, None, [])
        es = next(s for s in result["snapshots"] if s["market"] == "ES")
        self.assertTrue(es["stale"])
        self.assertEqual(result["snapshots_meta"]["stale"], 1)


# ---------------------------------------------------------------------------
# Provider name detection
# ---------------------------------------------------------------------------

class TestProviderName(unittest.TestCase):

    def setUp(self):
        self._saved = get_provider()

    def tearDown(self):
        set_provider(self._saved)

    def test_yfinance(self):
        set_provider(YFinanceProvider())
        self.assertEqual(_provider_name(), "yfinance")

    def test_polygon(self):
        set_provider(PolygonProvider(api_key="test"))
        self.assertEqual(_provider_name(), "polygon")


# ---------------------------------------------------------------------------
# /market-context endpoint — end-to-end via TestClient
# ---------------------------------------------------------------------------

class MarketContextEndpointBase(unittest.TestCase):

    def setUp(self):
        os.environ.pop("MARKET_SNAPSHOTS_ENABLED", None)
        get_store().clear()
        market_check._cache_clear()
        self._saved_provider = get_provider()
        set_provider(YFinanceProvider())
        self.client = TestClient(api_module.app)

    def tearDown(self):
        stop_background_refresh()
        get_store().clear()
        market_check._cache_clear()
        set_provider(self._saved_provider)


class TestEndpointFullData(MarketContextEndpointBase):

    def test_returns_200(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)

    def test_response_has_all_top_level_keys(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        for key in ("built_at", "source", "snapshots", "snapshots_meta",
                    "stress", "highlights", "highlights_meta"):
            self.assertIn(key, data)

    def test_full_snapshots_section(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        self.assertEqual(len(data["snapshots"]), 8)
        self.assertEqual(data["snapshots_meta"]["total"], 8)
        self.assertEqual(data["snapshots_meta"]["fresh"], 8)
        self.assertEqual(data["snapshots_meta"]["stale"], 0)
        self.assertEqual(data["snapshots_meta"]["unavailable"], 0)

    def test_stress_section_populated(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        self.assertIn("regime", data["stress"])
        self.assertIn("signals", data["stress"])
        self.assertTrue(data["stress"]["available"])

    def test_highlights_section_present(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        self.assertIn("highlights", data)
        self.assertIsInstance(data["highlights"], list)
        self.assertIn("count", data["highlights_meta"])

    def test_source_is_yfinance(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        self.assertEqual(response.json()["source"], "yfinance")


# ---------------------------------------------------------------------------
# /market-context — partial availability
# ---------------------------------------------------------------------------

class TestEndpointPartialAvailability(MarketContextEndpointBase):

    def test_no_snapshots_warm_returns_empty_section(self):
        """When the warm store is empty, snapshots come back empty but
        the rest of the context should still populate."""
        with patch("market_check._fetch", return_value=_good_df()):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["snapshots_meta"]["total"], 0)
        # Stress should still compute since it goes through _fetch
        self.assertIn("regime", data["stress"])

    def test_some_snapshots_unavailable(self):
        """If a couple of markets fail to refresh, they appear with errors."""
        def _flaky(symbol):
            if symbol in {"NQ=F", "GC=F"}:
                return None
            return _good_df()

        with patch("market_check._fetch", side_effect=_flaky):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        self.assertEqual(data["snapshots_meta"]["total"], 8)
        self.assertEqual(data["snapshots_meta"]["unavailable"], 2)
        self.assertEqual(data["snapshots_meta"]["fresh"], 6)

    def test_stress_failure_does_not_crash(self):
        """A stress computation failure should leave the rest of the context."""
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        # Now poison stress for the next call
        with patch("api.compute_stress_regime", side_effect=RuntimeError("boom")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Snapshots still present
        self.assertEqual(len(data["snapshots"]), 8)
        # Stress degraded
        self.assertEqual(data["stress"]["regime"], "Unknown")
        self.assertFalse(data["stress"]["available"])

    def test_highlights_failure_does_not_crash(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        with patch("api.movers_today", side_effect=RuntimeError("kaboom")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["highlights"], [])
        self.assertEqual(data["highlights_meta"]["count"], 0)
        # Other sections still present
        self.assertEqual(len(data["snapshots"]), 8)

    def test_all_sections_fail_endpoint_still_200(self):
        """Even when every fetch fails, the endpoint must not 500."""
        with patch("market_snapshots.get_all_snapshots", side_effect=RuntimeError("snap fail")), \
             patch("api.compute_stress_regime", side_effect=RuntimeError("stress fail")), \
             patch("api.movers_today", side_effect=RuntimeError("movers fail")):
            response = self.client.get("/market-context")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["snapshots"], [])
        self.assertEqual(data["highlights"], [])
        self.assertFalse(data["stress"]["available"])
        # Top-level metadata still present
        self.assertIn("built_at", data)
        self.assertIn("source", data)


# ---------------------------------------------------------------------------
# /market-context — stale snapshot behaviour
# ---------------------------------------------------------------------------

class TestEndpointStaleSnapshots(MarketContextEndpointBase):

    def test_stale_snapshots_passed_through(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        # Backdate every entry
        store = get_store()
        with store._lock:
            for k, (snap, _ts) in list(store._entries.items()):
                store._entries[k] = (
                    snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
                )
        response = self.client.get("/market-context")
        data = response.json()
        self.assertEqual(data["snapshots_meta"]["total"], 8)
        self.assertEqual(data["snapshots_meta"]["stale"], 8)
        self.assertEqual(data["snapshots_meta"]["fresh"], 0)
        for snap in data["snapshots"]:
            self.assertTrue(snap["stale"])
            # Data still present
            self.assertIsNotNone(snap["value"])

    def test_mixed_fresh_and_stale(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
        store = get_store()
        # Backdate only ES
        with store._lock:
            snap, _ = store._entries["ES"]
            store._entries["ES"] = (
                snap, time.monotonic() - SNAPSHOT_MAX_AGE_SECONDS - 5,
            )
        data = self.client.get("/market-context").json()
        self.assertEqual(data["snapshots_meta"]["stale"], 1)
        self.assertEqual(data["snapshots_meta"]["fresh"], 7)


# ---------------------------------------------------------------------------
# /market-context — highlight_limit param
# ---------------------------------------------------------------------------

class TestEndpointHighlightLimit(MarketContextEndpointBase):

    def test_default_limit(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context")
        data = response.json()
        # We don't control how many highlights exist, but the count
        # should be ≤ default limit of 3
        self.assertLessEqual(data["highlights_meta"]["count"], 3)

    def test_custom_limit(self):
        with patch("market_check._fetch", return_value=_good_df()):
            refresh_all()
            response = self.client.get("/market-context?highlight_limit=5")
        data = response.json()
        self.assertLessEqual(data["highlights_meta"]["count"], 5)


if __name__ == "__main__":
    unittest.main()
