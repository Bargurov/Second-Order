"""Final audit-debt sweep: provider-boundary symbol cleanup + numeric
   sanitization on market-facing routes.

Covers:
  * Secondary-provider verification cleans its symbol before dispatch.
  * /macro, /macro/batch, /ticker/{symbol}/chart, /ticker/{symbol}/info,
    /stress, /rates-context, /snapshots — all JSON-clean under NaN/inf
    inputs.
  * /market-movers + /movers/* still serialization-safe (regression guard).
  * Degraded/data_quality markers on /stress and /news pass through the
    sanitization wrapper untouched.
"""

import json
import math
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import uuid


def _tmp_db() -> str:
    return os.path.join(os.path.dirname(__file__),
                        f"test_audit_{uuid.uuid4().hex}.db")


def _find_nan(obj, path="root"):
    bad = []
    if isinstance(obj, float) and not math.isfinite(obj):
        bad.append(f"{path} = {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_find_nan(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_find_nan(v, f"{path}[{i}]"))
    return bad


# ---------------------------------------------------------------------------
# Secondary-provider verification uses cleaned symbols
# ---------------------------------------------------------------------------

class TestSecondaryVerificationCleansSymbol(unittest.TestCase):
    """The dual-source verification path must strip proxy / decoration
    annotations before hitting the secondary provider — otherwise a ticker
    like 'GLD (proxy)' fails at symbol parsing instead of returning a real
    second opinion."""

    def test_proxy_annotation_stripped_before_secondary_fetch(self):
        from market_check import _verify_ticker_return_impl

        captured: dict = {}

        class _FakeSecondary:
            def fetch_daily(self, symbol, **kw):
                captured["symbol"] = symbol
                return None  # force the "no data" branch

        with patch("market_data.get_secondary_provider",
                   return_value=_FakeSecondary()):
            _verify_ticker_return_impl("GLD (proxy)", r5_primary=1.0)

        self.assertEqual(captured.get("symbol"), "GLD",
                         "Secondary provider must receive the cleaned symbol, "
                         "not the raw annotated string.")

    def test_empty_symbol_short_circuits_without_provider_call(self):
        from market_check import _verify_ticker_return_impl

        called: list[bool] = []

        class _FakeSecondary:
            def fetch_daily(self, symbol, **kw):
                called.append(True)
                return None

        with patch("market_data.get_secondary_provider",
                   return_value=_FakeSecondary()):
            res = _verify_ticker_return_impl("   ", r5_primary=1.0)

        self.assertEqual(res["status"], "unavailable")
        self.assertEqual(called, [], "Empty symbol must not call the provider")


# ---------------------------------------------------------------------------
# Market-facing routes: NaN/inf never leak through
# ---------------------------------------------------------------------------

class TestMarketRoutesSanitized(unittest.TestCase):
    """Every remaining market-facing route must JSON-round-trip cleanly
    even when the underlying data source returns NaN/inf."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = _tmp_db()
        db.init_db()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    # ----- /macro ----------------------------------------------------------

    def test_macro_route_sanitizes_nan(self):
        nan_payload = [{"market": "X", "value": float("nan"),
                        "change_5d": float("inf")}]
        with patch("routes.market.macro_snapshot", return_value=nan_payload):
            r = self.client.get("/macro")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        json.dumps(body)
        self.assertEqual(_find_nan(body), [])

    def test_macro_batch_sanitizes_nan(self):
        nan_payload = [{"market": "X", "value": float("nan")}]
        with patch("routes.market.macro_snapshot", return_value=nan_payload):
            r = self.client.post("/macro/batch",
                                 json={"event_dates": ["2025-01-01"]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    # ----- /ticker/{symbol}/* ---------------------------------------------

    def test_ticker_chart_sanitizes_nan(self):
        nan_series = [{"t": "2025-01-01", "close": float("nan"),
                       "return_5d": float("inf")}]
        with patch("routes.market.ticker_chart", return_value=nan_series):
            r = self.client.get("/ticker/CVX/chart",
                                params={"event_date": "2025-01-02"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    def test_ticker_info_sanitizes_nan(self):
        nan_info = {"name": "Chevron", "market_cap": float("nan"),
                    "beta": float("inf")}
        with patch("routes.market.ticker_info", return_value=nan_info):
            r = self.client.get("/ticker/CVX/info")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    def test_ticker_headlines_sanitizes_nan(self):
        """The headlines projection currently only forwards ints/strings, but
        must still pass through the scrub so a future cluster field carrying
        NaN (e.g. a cached score) can't sneak past."""
        bad_cluster = {
            "headline": "Chevron beats estimates",
            "source_count": 3,
            "published_at": "2025-03-01T12:00:00",
            # Hypothetical upstream leakage — belt-and-braces regression guard.
            "score": float("nan"),
            "velocity": float("inf"),
        }
        fake_info = {"name": "Chevron", "market_cap": 1.0, "beta": 1.0}
        with patch("routes.market.ticker_info", return_value=fake_info), \
             patch("api._get_news_cached", return_value={"clusters": [bad_cluster]}):
            r = self.client.get("/ticker/CVX/headlines")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    # ----- /stress ---------------------------------------------------------

    def test_stress_sanitizes_nan_in_raw_block(self):
        nan_stress = {
            "regime": "Calm",
            "signals": {"vix_elevated": False},
            "raw": {"vix": float("nan"), "hyg_5d": float("inf")},
        }
        with patch("api.compute_stress_regime", return_value=nan_stress), \
             patch("sector_uncertainty.compute_sector_uncertainty",
                   return_value={"available": False}), \
             patch("api.compute_news_uncertainty",
                   return_value={"uncertainty_scope": "global",
                                 "sector_uncertainty": [],
                                 "lead_sector": None}):
            r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    def test_stress_degraded_markers_preserved_under_sanitization(self):
        """The data_quality / degraded_fields markers must not be lost when
        _sanitize_floats wraps the response."""
        def _boom():
            raise RuntimeError("sector down")
        with patch("api.compute_stress_regime", return_value={
                    "regime": "Calm", "signals": {},
                    "raw": {"vix": 18.0}}), \
             patch("sector_uncertainty.compute_sector_uncertainty",
                   side_effect=_boom), \
             patch("api.compute_news_uncertainty",
                   return_value={"uncertainty_scope": "global",
                                 "sector_uncertainty": [],
                                 "lead_sector": None}):
            r = self.client.get("/stress")
        body = r.json()
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("sector_uncertainty", body["degraded_fields"])

    # ----- /rates-context --------------------------------------------------

    def test_rates_context_sanitizes_nan(self):
        nan_rates = {
            "regime": "Mixed", "available": True,
            "nominal": {"label": "10Y", "value": float("nan"),
                         "change_5d": float("inf")},
            "real_proxy": {"change_5d": None},
            "breakeven_proxy": {"change_5d": None},
            "raw": {"tnx": float("nan")},
        }
        with patch("api.compute_rates_context", return_value=nan_rates):
            r = self.client.get("/rates-context")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])

    # ----- /snapshots ------------------------------------------------------

    def test_snapshots_sanitizes_nan(self):
        class _FakeSnap:
            def to_dict(self):
                return {"market": "ES", "value": float("nan"),
                        "change_5d": float("inf")}

        with patch("market_snapshots.get_all_snapshots",
                   return_value=[_FakeSnap()]), \
             patch("market_snapshots.refresh_all", lambda: None):
            r = self.client.get("/snapshots")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(_find_nan(r.json()), [])


# ---------------------------------------------------------------------------
# /market-movers regression — still JSON-clean
# ---------------------------------------------------------------------------

class TestMoversRegression(unittest.TestCase):
    """Make sure the movers-sanitization path I landed previously still
    holds after this audit sweep — no NaN/inf leaks on persisted tickers."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = _tmp_db()
        db.init_db()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_market_movers_is_json_clean_even_with_nan_returns(self):
        db.save_event({
            "headline": "Audit: movers sanitization",
            "stage": "breaking",
            "persistence": "transient",
            "confidence": "medium",
            "event_date": "2025-01-01",
            "market_tickers": [
                {"symbol": "SPY", "role": "beneficiary",
                 "return_5d": 3.5, "return_20d": float("nan"),
                 "direction_tag": "supports_thesis", "spark": []},
            ],
        })
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        json.dumps(body)
        self.assertEqual(_find_nan(body), [])


if __name__ == "__main__":
    unittest.main()
