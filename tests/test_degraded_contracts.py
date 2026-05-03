"""Focused tests for the hardened degradation contracts.

Covers:
  - /market-movers output passes through _sanitize_floats (no NaN/Inf leak)
  - /news emits data_quality + degraded_fields when an enrichment block fails
  - /stress emits data_quality + degraded_fields when sector_uncertainty fails
  - frozen-archive cached responses strip NaN from persisted overlay blocks

No live network calls; all external dependencies stubbed.
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


def _tmp_db() -> str:
    return os.path.join(os.path.dirname(__file__), f"test_degraded_{uuid.uuid4().hex}.db")


def _find_nan(obj, path="root"):
    bad = []
    if isinstance(obj, float):
        if not math.isfinite(obj):
            bad.append(f"{path} = {obj}")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            bad.extend(_find_nan(v, f"{path}.{k}"))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            bad.extend(_find_nan(v, f"{path}[{i}]"))
    return bad


class MoversSanitizationTest(unittest.TestCase):
    """Persisted NaN ticker returns must not leak through /market-movers."""

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

    def _seed_mover_with_nan(self):
        """Seed an event that _score_event will qualify, with one NaN-tainted value."""
        db.save_event({
            "headline": "Mover: Fed cuts 50bp, risk assets surge",
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

    def test_market_movers_response_is_json_clean(self):
        self._seed_mover_with_nan()
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        # Round-trip through json.dumps to catch any non-finite floats.
        json.dumps(body)
        self.assertEqual(_find_nan(body), [])

    def test_market_movers_rejects_out_of_range_limit(self):
        r = self.client.get("/market-movers", params={"limit": 0})
        self.assertEqual(r.status_code, 422)
        r = self.client.get("/market-movers", params={"limit": 1000})
        self.assertEqual(r.status_code, 422)


class NewsDegradedContractTest(unittest.TestCase):
    """/news must flag enrichment failures in data_quality / degraded_fields."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = _tmp_db()
        db.init_db()
        self._patches = [
            patch("api.fetch_all", return_value=(
                [{"source": "Reuters", "title": "Stub",
                  "published_at": "2025-01-01T00:00:00", "url": ""}],
                [{"name": "Reuters", "url": "https://x", "ok": True,
                  "count": 1, "error": None}],
            )),
            patch("api.cluster_headlines", return_value=[]),
        ]
        for p in self._patches:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)
        import api as _api_mod
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0

    def tearDown(self):
        for p in self._patches:
            p.stop()
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_news_ok_when_enrichment_succeeds(self):
        with patch("routes.news.get_macro_releases", return_value=[]), \
             patch("routes.news.get_policy_items", return_value=[]), \
             patch("routes.news.classify_macro_surprise", side_effect=lambda m, c: m):
            r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data_quality"], "ok")
        self.assertEqual(body["degraded_fields"], [])

    def test_news_degraded_when_macro_fails(self):
        def _boom():
            raise RuntimeError("calendar offline")
        with patch("routes.news.get_macro_releases", side_effect=_boom), \
             patch("routes.news.get_policy_items", return_value=[]):
            r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("macro_releases", body["degraded_fields"])

    def test_news_degraded_when_policy_fails(self):
        def _boom():
            raise RuntimeError("policy offline")
        with patch("routes.news.get_macro_releases", return_value=[]), \
             patch("routes.news.classify_macro_surprise", side_effect=lambda m, c: m), \
             patch("routes.news.get_policy_items", side_effect=_boom):
            r = self.client.get("/news")
        body = r.json()
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("policy_items", body["degraded_fields"])


class StressDegradedContractTest(unittest.TestCase):
    """/stress must flag enrichment failures in data_quality / degraded_fields."""

    def setUp(self):
        from fastapi.testclient import TestClient
        from api import app
        self.client = TestClient(app)
        # Stable stress regime so the test isolates enrichment behaviour.
        self._stress_patch = patch("api.compute_stress_regime", return_value={
            "regime": "Calm", "signals": {}, "raw": {}, "summary": "ok",
        })
        self._stress_patch.start()

    def tearDown(self):
        self._stress_patch.stop()

    def test_stress_ok_when_enrichment_succeeds(self):
        with patch("sector_uncertainty.compute_sector_uncertainty",
                   return_value={"available": False}), \
             patch("api.compute_news_uncertainty",
                   return_value={"uncertainty_scope": "global",
                                 "sector_uncertainty": [], "lead_sector": None}):
            r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data_quality"], "ok")
        self.assertEqual(body["degraded_fields"], [])

    def test_stress_degraded_when_sector_fails(self):
        def _boom():
            raise RuntimeError("sector data offline")
        with patch("sector_uncertainty.compute_sector_uncertainty", side_effect=_boom), \
             patch("api.compute_news_uncertainty",
                   return_value={"uncertainty_scope": "global",
                                 "sector_uncertainty": [], "lead_sector": None}):
            r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("sector_uncertainty", body["degraded_fields"])


class FrozenOverlaySanitizationTest(unittest.TestCase):
    """Frozen-archive reads must scrub NaN/Inf out of persisted overlay blocks."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = _tmp_db()
        db.init_db()

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_nan_in_persisted_overlay_scrubbed_on_frozen_read(self):
        """A frozen event with NaN inside policy_constraint must not leak it."""
        from datetime import datetime, timedelta
        from api import _build_cached_response

        old_date = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        db.save_event({
            "headline": "Archived: legacy row with tainted overlays",
            "stage": "realized",
            "persistence": "structural",
            "event_date": old_date,
            "confidence": "medium",
            "policy_constraint": {"score": float("nan"), "label": "tight"},
            "reaction_function_divergence": {"divergence": float("inf")},
            "narrative_divergence": {"score": float("nan"), "signal": "divergent"},
            "market_tickers": [
                {"symbol": "SPY", "role": "beneficiary",
                 "return_5d": 1.0, "return_20d": 2.0, "direction_tag": "supports_thesis"},
            ],
        })
        cached = db.find_cached_analysis(
            "Archived: legacy row with tainted overlays",
            event_date=old_date, max_age_seconds=365 * 86400,
        )
        self.assertIsNotNone(cached)

        # Patch out the live-branch helpers so we stay on the frozen path.
        with patch("api.refresh_market_for_saved_event", return_value={
                    "tickers": cached.get("market_tickers", []),
                    "note": "", "details": {},
                    "last_market_check_at": None,
                    "market_check_staleness": "ok",
                    "data_quality": "ok",
                    "data_quality_note": None,
                  }), \
             patch("api.find_historical_analogs", return_value=[]), \
             patch("api.build_regime_vector", return_value={"available": False}):
            resp = _build_cached_response(cached, cached["headline"], old_date, force=False)

        bad = _find_nan(resp)
        self.assertEqual(
            bad, [],
            f"NaN/Inf leaked through frozen-archive response: {bad}",
        )


if __name__ == "__main__":
    unittest.main()
