"""Backend-only regression smoke tests for frozen API/product routes.

Covers safe-shape contracts on routes the product surface depends on:
    * GET  /health
    * GET  /health/detail
    * GET  /portfolio          (bare-list default + filtered envelope)
    * GET  /market-context
    * GET  /stats/track-record
    * GET  /stats/track-record/breakdown
    * GET  /stats/track-record/breakdown/export?format=...

No live network, no LLM, no yfinance.  External seams are stubbed in the
same style as ``tests/test_smoke_integration.py``.  Assertions check
shape and JSON cleanliness — never fragile exact values — so the file
flags only real product regressions.
"""

import json
import math
import os
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402


# ---------------------------------------------------------------------------
# JSON-cleanliness helper (NaN/Inf leaks fail the response on the wire).
# ---------------------------------------------------------------------------

def _find_nan_paths(obj, path="root"):
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


def _assert_json_clean(test, body, label=""):
    try:
        json.dumps(body)
    except (TypeError, ValueError) as exc:
        test.fail(f"Response not JSON-serializable ({label}): {exc}")
    bad = _find_nan_paths(body)
    if bad:
        test.fail(f"NaN/Inf leak in response ({label}):\n" + "\n".join(bad))


# ---------------------------------------------------------------------------
# Stubs — kept aligned with tests/test_smoke_integration.py so both files
# patch the same external seams in the same way.
# ---------------------------------------------------------------------------

def _stub_analyze(_inp):
    return {
        "what_changed": "Stub policy shift",
        "mechanism_summary": "Stub mechanism for backend contract smoke.",
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


_STUB_STRESS = {
    "regime": "Undercurrent",
    "signals": {
        "vix_elevated": False, "term_inversion": False,
        "credit_widening": False, "safe_haven_bid": False,
        "breadth_deterioration": False,
    },
    "raw": {"vix": 18.5},
    "detail": {},
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


_PATCHES = [
    patch("api.analyze_event", side_effect=_stub_analyze),
    patch("api.market_check", side_effect=_stub_market),
    patch("api.fetch_all", return_value=(
        [
            {"source": "Reuters", "title": "Stub headline",
             "published_at": "2025-01-01T00:00:00", "url": ""},
        ],
        [{"name": "Reuters", "url": "https://example.com", "ok": True,
          "count": 1, "error": None}],
    )),
    patch("api.cluster_headlines", return_value=[]),
    patch("api.compute_stress_regime", return_value=_STUB_STRESS),
    patch("api.compute_rates_context", return_value=_STUB_RATES),
    patch("api.build_regime_vector", return_value=_STUB_REGIME_VEC),
    patch("market_context.compose_market_context", return_value=_STUB_MARKET_CONTEXT),
    patch("market_snapshots.get_all_snapshots", return_value=[]),
    patch("sector_uncertainty.compute_sector_uncertainty",
          return_value=_STUB_SECTOR_UNCERTAINTY),
]


# ---------------------------------------------------------------------------
# Base class — temp DB per test, all stubs active.
# ---------------------------------------------------------------------------

class BackendContractSmokeBase(unittest.TestCase):
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
            f"test_backend_contract_{uuid.uuid4().hex}.db",
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

    def _analyze(self, headline, **kwargs):
        r = self.client.post("/analyze", json={"headline": headline, **kwargs})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def _get_ok(self, path, **params):
        r = self.client.get(path, params=params)
        self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
        return r.json()


# ---------------------------------------------------------------------------
# /health  +  /health/detail
# ---------------------------------------------------------------------------

class TestHealthContract(BackendContractSmokeBase):
    def test_health_status_ok(self):
        body = self._get_ok("/health")
        self.assertEqual(body, {"status": "ok"})

    def test_health_detail_shape_no_data(self):
        """Cold cache should still respond with the documented envelope."""
        body = self._get_ok("/health/detail")
        _assert_json_clean(self, body, "GET /health/detail")
        for key in ("api_status", "feed_health", "pipeline", "overall"):
            self.assertIn(key, body, f"Missing /health/detail key: {key}")
        self.assertIn("ok", body["feed_health"])
        self.assertIn("failed", body["feed_health"])
        self.assertIn("clusters_cached", body["pipeline"])


# ---------------------------------------------------------------------------
# /portfolio — bare-list default + filtered envelope
# ---------------------------------------------------------------------------

class TestPortfolioContract(BackendContractSmokeBase):
    def test_portfolio_default_returns_list(self):
        """Frontend handles a bare list when no filters applied."""
        body = self._get_ok("/portfolio")
        _assert_json_clean(self, body, "GET /portfolio")
        self.assertIsInstance(body, list)

    def test_portfolio_with_quality_tier_returns_envelope(self):
        """Any filter param flips the response into the {items, ...counts} shape."""
        body = self._get_ok("/portfolio", quality_tier="actionable")
        _assert_json_clean(self, body, "GET /portfolio?quality_tier=actionable")
        self.assertIsInstance(body, dict)
        for key in (
            "items",
            "thesis_state_counts",
            "proof_quality_counts",
            "quality_tier_counts",
            "tradable_counts",
            "mechanism_subtype_counts",
        ):
            self.assertIn(key, body, f"Missing /portfolio envelope key: {key}")
        self.assertIsInstance(body["items"], list)
        self.assertIsInstance(body["quality_tier_counts"], dict)

    def test_portfolio_tradable_filter_envelope(self):
        body = self._get_ok("/portfolio", tradable=True)
        self.assertIsInstance(body, dict)
        self.assertIn("items", body)
        self.assertIn("tradable_counts", body)
        # Both string keys must be present so the UI can size the facet.
        self.assertIn("true", body["tradable_counts"])
        self.assertIn("false", body["tradable_counts"])

    def test_portfolio_invalid_quality_tier_rejected(self):
        """Unknown enum values surface as 400 instead of silently filtering to []."""
        r = self.client.get("/portfolio", params={"quality_tier": "not_a_real_tier"})
        self.assertEqual(r.status_code, 400, r.text)

    def test_portfolio_populated_default_shape(self):
        """After a saved event the bare-list entries carry the documented fields."""
        self._analyze("Backend smoke: Fed signals rate cut")
        body = self._get_ok("/portfolio")
        _assert_json_clean(self, body, "GET /portfolio populated")
        self.assertIsInstance(body, list)
        if body:
            entry = body[0]
            for key in (
                "id",
                "headline",
                "quality_tier",
                "actionability_check",
                "mechanism_subtype",
                "validation_outcome",
                "persistence_signal",
            ):
                self.assertIn(key, entry, f"Missing portfolio entry key: {key}")


# ---------------------------------------------------------------------------
# /market-context
# ---------------------------------------------------------------------------

class TestMarketContextContract(BackendContractSmokeBase):
    def test_market_context_returns_dict(self):
        body = self._get_ok("/market-context")
        _assert_json_clean(self, body, "GET /market-context")
        self.assertIsInstance(body, dict)

    def test_market_context_carries_stub_blocks(self):
        """compose_market_context is stubbed — its top-level blocks must surface."""
        body = self._get_ok("/market-context")
        for key in ("stress", "rates", "regime_vector"):
            self.assertIn(key, body, f"Missing /market-context key: {key}")

    def test_market_context_highlight_limit_param_accepted(self):
        """highlight_limit is a documented query param — non-default must not 500."""
        body = self._get_ok("/market-context", highlight_limit=1)
        _assert_json_clean(self, body, "GET /market-context?highlight_limit=1")
        self.assertIsInstance(body, dict)


# ---------------------------------------------------------------------------
# /stats/track-record  (+ breakdown + breakdown export)
# ---------------------------------------------------------------------------

class TestTrackRecordContract(BackendContractSmokeBase):
    def test_track_record_returns_dict(self):
        body = self._get_ok("/stats/track-record")
        _assert_json_clean(self, body, "GET /stats/track-record")
        self.assertIsInstance(body, dict)

    def test_track_record_breakdown_returns_dict(self):
        body = self._get_ok("/stats/track-record/breakdown")
        _assert_json_clean(self, body, "GET /stats/track-record/breakdown")
        self.assertIsInstance(body, dict)

    def test_track_record_breakdown_export_json(self):
        body = self._get_ok("/stats/track-record/breakdown/export", format="json")
        _assert_json_clean(self, body, "GET /stats/track-record/breakdown/export?format=json")
        self.assertIsInstance(body, dict)

    def test_track_record_breakdown_export_csv(self):
        r = self.client.get(
            "/stats/track-record/breakdown/export", params={"format": "csv"},
        )
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("text/csv", r.headers.get("content-type", ""))
        # Body is bytes/str — just verify non-empty so a regression in the
        # serializer (returning None / empty) trips the test.
        self.assertTrue(len(r.content) > 0)

    def test_track_record_breakdown_export_rejects_bad_format(self):
        r = self.client.get(
            "/stats/track-record/breakdown/export", params={"format": "xml"},
        )
        self.assertEqual(r.status_code, 422, r.text)


# ---------------------------------------------------------------------------
# /stats/confidence-calibration — same frozen stats family.
# ---------------------------------------------------------------------------

class TestConfidenceCalibrationContract(BackendContractSmokeBase):
    def test_confidence_calibration_returns_dict(self):
        body = self._get_ok("/stats/confidence-calibration")
        _assert_json_clean(self, body, "GET /stats/confidence-calibration")
        self.assertIsInstance(body, dict)


if __name__ == "__main__":
    unittest.main()
