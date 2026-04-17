"""
Integration smoke tests for critical API paths.

Verifies:
- Routes return HTTP 200
- Responses are fully JSON-serializable (no NaN/Inf leaks)
- Core response shapes are stable
- Pagination contract is valid for /news

No live network calls — all external dependencies are stubbed.
"""

import json
import math
import os
import sys
import uuid
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


# ---------------------------------------------------------------------------
# NaN / Inf leak detector
# ---------------------------------------------------------------------------

def _find_nan_paths(obj, path="root"):
    """Recursively walk *obj* and return all key-paths where a float is NaN or Inf."""
    bad = []
    if isinstance(obj, float):
        if not math.isfinite(obj):
            bad.append(f"{path} = {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_find_nan_paths(v, f"{path}.{k}"))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            bad.extend(_find_nan_paths(v, f"{path}[{i}]"))
    return bad


def _assert_json_clean(test: unittest.TestCase, body: dict | list, label: str = ""):
    """Assert the body is JSON-serializable and contains no NaN/Inf values."""
    try:
        json.dumps(body)
    except (TypeError, ValueError) as exc:
        test.fail(f"Response not JSON-serializable ({label}): {exc}")

    bad = _find_nan_paths(body)
    if bad:
        test.fail(f"NaN/Inf leak in response ({label}):\n" + "\n".join(bad))


# ---------------------------------------------------------------------------
# Minimal stubs for external dependencies
# ---------------------------------------------------------------------------

def _stub_analyze(inp):
    return {
        "what_changed": "Stub policy shift",
        "mechanism_summary": "Stub mechanism for smoke tests.",
        "beneficiaries": ["SectorA"],
        "losers": ["SectorB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "high",
        "transmission_chain": ["Step 1", "Step 2"],
        "if_persists": {
            "substitution": "Stub substitution.",
            "delayed_winners": ["GOOG"],
            "delayed_losers": ["META"],
            "horizon": "months",
        },
    }


def _stub_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Stub market check.",
        "details": {},
        "tickers": [
            {
                "symbol": "AAPL", "role": "beneficiary", "label": "up",
                "direction_tag": "supports_thesis",
                "return_1d": 0.5, "return_5d": 2.1, "return_20d": 4.3,
                "volume_ratio": 1.2, "vs_xle_5d": None, "spark": [],
            },
        ],
    }


_STUB_CLUSTERS = [
    {"headline": f"Headline {i}", "sources": [{"name": "Reuters"}], "source_count": 1}
    for i in range(15)
]

_STUB_STRESS = {
    "regime": "Undercurrent",
    "signals": {
        "vix_elevated": False, "term_inversion": False,
        "credit_widening": False, "safe_haven_bid": False,
        "breadth_deterioration": False,
    },
    "raw": {"vix": 18.5},
    "detail": {
        "volatility": {
            "label": "Volatility", "status": "calm",
            "explanation": "VIX within normal range.", "value": 18.5, "avg20": 17.0,
        },
    },
    "summary": "Markets calm.",
}

_STUB_RATES = {
    "regime": "Neutral",
    "nominal": {"label": "10Y Treasury", "value": 4.25, "change_5d": 0.05},
    "real_proxy": {"label": "10Y TIPS", "value": 1.9, "change_5d": 0.02},
    "breakeven_proxy": {"label": "Breakeven", "value": 2.35, "change_5d": 0.03},
    "raw": {},
}

_STUB_REGIME_VEC = {"available": False}

_STUB_MARKET_CONTEXT = {
    "stress": _STUB_STRESS,
    "rates": _STUB_RATES,
    "regime_vector": _STUB_REGIME_VEC,
    "snapshots": [],
    "highlights": [],
    "generated_at": "2025-01-01T00:00:00",
}

_STUB_SECTOR_UNCERTAINTY = {"available": False}

# All patches applied to every test
_PATCHES = [
    patch("api.analyze_event", side_effect=_stub_analyze),
    patch("api.market_check", side_effect=_stub_market),
    patch("api.fetch_all", return_value=(
        [
            {"source": "Reuters", "title": "Stub headline A",
             "published_at": "2025-01-01T00:00:00", "url": ""},
        ],
        [{"name": "Reuters", "url": "https://example.com", "ok": True,
          "count": 1, "error": None}],
    )),
    patch("api.cluster_headlines", return_value=_STUB_CLUSTERS),
    patch("api.compute_stress_regime", return_value=_STUB_STRESS),
    patch("api.compute_rates_context", return_value=_STUB_RATES),
    patch("api.build_regime_vector", return_value=_STUB_REGIME_VEC),
    patch("market_context.compose_market_context", return_value=_STUB_MARKET_CONTEXT),
    patch("market_snapshots.get_all_snapshots", return_value=[]),
    patch("sector_uncertainty.compute_sector_uncertainty",
          return_value=_STUB_SECTOR_UNCERTAINTY),
]


class SmokeTestBase(unittest.TestCase):
    """Shared setup: temp DB, TestClient, all external stubs active."""

    @classmethod
    def setUpClass(cls):
        for p in _PATCHES:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        import api as _api_mod
        self._orig_db = db.DB_FILE
        self._tmp_db = os.path.join(
            os.path.dirname(__file__),
            f"test_smoke_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp_db
        db.init_db()
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0
        _api_mod._last_refresh_at = 0.0
        _api_mod._last_refresh_payload = None

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp_db)
        except (OSError, PermissionError):
            pass

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _analyze(self, headline="Smoke: Fed hikes rates by 50bp", **kwargs):
        """POST /analyze and assert 200."""
        r = self.client.post("/analyze", json={"headline": headline, **kwargs})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def get_ok(self, path, **params):
        """GET *path*, assert 200, return parsed JSON."""
        r = self.client.get(path, params=params)
        self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
        return r.json()


# ---------------------------------------------------------------------------
# 1. News refresh
# ---------------------------------------------------------------------------

class TestNewsRefresh(SmokeTestBase):
    def test_refresh_returns_200_and_clusters(self):
        r = self.client.post("/news/refresh")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        _assert_json_clean(self, body, "POST /news/refresh")
        self.assertIn("clusters", body)
        self.assertIsInstance(body["clusters"], list)

    def test_refresh_has_refresh_meta(self):
        body = self.client.post("/news/refresh").json()
        self.assertIn("refresh_meta", body)
        meta = body["refresh_meta"]
        self.assertIn("status", meta)

    def test_cooldown_returns_recent_status(self):
        """Second refresh within cooldown window returns status='recent'."""
        import api as _api_mod
        _api_mod._REFRESH_COOLDOWN_SECONDS = 3600  # force cooldown active
        self.client.post("/news/refresh")  # prime
        r2 = self.client.post("/news/refresh")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["refresh_meta"]["status"], "recent")


# ---------------------------------------------------------------------------
# 2. Analyze
# ---------------------------------------------------------------------------

class TestAnalyzeSmoke(SmokeTestBase):
    def test_analyze_shape_and_no_nan(self):
        body = self._analyze()
        _assert_json_clean(self, body, "POST /analyze")
        for key in ("headline", "stage", "persistence", "analysis", "market", "event_date"):
            self.assertIn(key, body, f"Missing key: {key}")

    def test_analyze_analysis_block_fields(self):
        body = self._analyze()
        a = body["analysis"]
        for key in ("what_changed", "mechanism_summary", "beneficiary_tickers",
                    "loser_tickers", "confidence", "transmission_chain"):
            self.assertIn(key, a, f"Missing analysis field: {key}")

    def test_analyze_market_tickers_list(self):
        body = self._analyze()
        tickers = body["market"]["tickers"]
        self.assertIsInstance(tickers, list)
        if tickers:
            t = tickers[0]
            self.assertIn("symbol", t)
            self.assertIn("return_5d", t)

    def test_analyze_persists_to_events(self):
        self._analyze(headline="Smoke persist: OPEC extends cuts")
        events = db.load_recent_events(5)
        self.assertTrue(any(e["headline"] == "Smoke persist: OPEC extends cuts" for e in events))


# ---------------------------------------------------------------------------
# 3. Events list
# ---------------------------------------------------------------------------

class TestEventsSmoke(SmokeTestBase):
    def test_events_empty_is_list(self):
        body = self.get_ok("/events")
        self.assertIn("items", body)
        self.assertIsInstance(body["items"], list)

    def test_events_shape_after_analyze(self):
        self._analyze(headline="Smoke events: EU sanctions on Russian gas")
        body = self.get_ok("/events")
        _assert_json_clean(self, body, "GET /events")
        self.assertGreater(body["total"], 0)
        ev = body["items"][0]
        for key in ("id", "headline", "event_date", "persistence_signal"):
            self.assertIn(key, ev, f"Missing events field: {key}")

    def test_events_persistence_signal_shape(self):
        self._analyze(headline="Smoke sig: chip export controls tightened")
        body = self.get_ok("/events")
        sig = body["items"][0].get("persistence_signal")
        self.assertIsNotNone(sig)
        for key in ("status", "label", "evidence", "horizon_days", "days_elapsed"):
            self.assertIn(key, sig, f"Missing persistence_signal field: {key}")
        self.assertIn(sig["status"], ("watching", "active", "fading", "resolved"))

    def test_events_no_nan_leak(self):
        self._analyze(headline="Smoke NaN: tariffs on European steel")
        body = self.get_ok("/events")
        _assert_json_clean(self, body, "GET /events")

    def test_events_limit_param(self):
        for i in range(5):
            self._analyze(headline=f"Smoke limit {i}: headline")
        body = self.get_ok("/events", limit=3)
        self.assertLessEqual(len(body["items"]), 3)


# ---------------------------------------------------------------------------
# 4. Movers / today
# ---------------------------------------------------------------------------

class TestMoversSmoke(SmokeTestBase):
    def test_movers_today_is_list(self):
        body = self.get_ok("/movers/today")
        self.assertIsInstance(body, list)
        _assert_json_clean(self, body, "GET /movers/today")

    def test_movers_today_with_events(self):
        self._analyze(headline="Smoke movers: Fed signals pivot")
        body = self.get_ok("/movers/today")
        self.assertIsInstance(body, list)

    def test_market_movers_is_list(self):
        body = self.get_ok("/market-movers")
        self.assertIsInstance(body, list)
        _assert_json_clean(self, body, "GET /market-movers")


# ---------------------------------------------------------------------------
# 5. Market-context
# ---------------------------------------------------------------------------

class TestMarketContextSmoke(SmokeTestBase):
    def test_market_context_returns_200(self):
        r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200, r.text)

    def test_market_context_json_clean(self):
        body = self.get_ok("/market-context")
        _assert_json_clean(self, body, "GET /market-context")

    def test_market_context_has_stress_key(self):
        body = self.get_ok("/market-context")
        # compose_market_context is stubbed to return _STUB_MARKET_CONTEXT
        self.assertIn("stress", body)

    def test_stress_route_shape(self):
        body = self.get_ok("/stress")
        _assert_json_clean(self, body, "GET /stress")
        self.assertIn("regime", body)
        self.assertIn("signals", body)
        # sector_uncertainty is always present (even when available=False)
        self.assertIn("sector_uncertainty", body)
        self.assertIn("available", body["sector_uncertainty"])


# ---------------------------------------------------------------------------
# 6. News pagination
# ---------------------------------------------------------------------------

class TestNewsPagination(SmokeTestBase):
    def _prime_news(self):
        """Seed the news cache with 15 stub clusters directly.

        The cluster-store pipeline wraps cluster_headlines internally, so the
        only reliable seam for testing pagination is the in-memory cache that
        the /news route reads from.
        """
        import api as _api_mod
        _api_mod._news_cache["data"] = {
            "clusters": _STUB_CLUSTERS,
            "total_headlines": len(_STUB_CLUSTERS),
            "feed_status": [],
            "refresh_meta": {
                "status": "ok", "source": "test_prime",
                "known": 0, "new": len(_STUB_CLUSTERS), "merged": 0,
                "created": len(_STUB_CLUSTERS), "reused": 0,
                "last_successful_refresh": None, "freshness": "fresh",
            },
        }
        _api_mod._news_cache["ts"] = float("inf")  # never expires within test

    def test_news_unpaginated_returns_all(self):
        self._prime_news()
        body = self.get_ok("/news")
        _assert_json_clean(self, body, "GET /news unpaginated")
        self.assertIn("clusters", body)
        self.assertIn("total_count", body)
        self.assertEqual(len(body["clusters"]), body["total_count"])

    def test_news_limit_slices_correctly(self):
        self._prime_news()
        body = self.get_ok("/news", limit=5, offset=0)
        self.assertEqual(len(body["clusters"]), 5)
        self.assertEqual(body["total_count"], 15)

    def test_news_offset_advances_page(self):
        self._prime_news()
        b0 = self.get_ok("/news", limit=5, offset=0)
        b1 = self.get_ok("/news", limit=5, offset=5)
        # No overlap between first and second page
        headlines_0 = {c["headline"] for c in b0["clusters"]}
        headlines_1 = {c["headline"] for c in b1["clusters"]}
        self.assertEqual(headlines_0 & headlines_1, set())

    def test_news_offset_beyond_end_returns_empty_clusters(self):
        self._prime_news()
        body = self.get_ok("/news", limit=5, offset=100)
        self.assertEqual(body["clusters"], [])

    def test_news_total_count_stable_across_pages(self):
        """total_count must be the same regardless of pagination params."""
        self._prime_news()
        b1 = self.get_ok("/news", limit=5, offset=0)
        b2 = self.get_ok("/news", limit=10, offset=5)
        self.assertEqual(b1["total_count"], b2["total_count"])

    def test_news_has_required_meta_keys(self):
        self._prime_news()
        body = self.get_ok("/news")
        for key in ("clusters", "total_count", "total_headlines", "feed_status", "refresh_meta"):
            self.assertIn(key, body, f"Missing /news key: {key}")


# ---------------------------------------------------------------------------
# 7. Portfolio
# ---------------------------------------------------------------------------

class TestPortfolioSmoke(SmokeTestBase):
    def test_portfolio_empty_is_list(self):
        body = self.get_ok("/portfolio")
        self.assertIsInstance(body, list)

    def test_portfolio_populated_shape(self):
        self._analyze(headline="Smoke portfolio: sanctions expand to energy sector")
        body = self.get_ok("/portfolio")
        _assert_json_clean(self, body, "GET /portfolio")
        if body:
            entry = body[0]
            for key in ("id", "headline", "persistence_signal", "validation_outcome"):
                self.assertIn(key, entry, f"Missing portfolio field: {key}")

    def test_portfolio_no_nan_leak(self):
        self._analyze(headline="Smoke portfolio NaN: bond yields spike")
        body = self.get_ok("/portfolio")
        _assert_json_clean(self, body, "GET /portfolio")


if __name__ == "__main__":
    unittest.main()
