"""Backend-only contract smoke tests for the Headlines / news surface.

Pins the wire-shape rules the Headlines page depends on:

  * GET  /news           — empty + populated payload, pagination shape,
                           bad-cursor rejection, degradation flagging.
  * POST /news/refresh   — runs without exploding when the news pipeline
                           is stubbed; returns the documented payload.
  * GET  /news/trends    — list shape on cold DB.

No live network, no LLM, no yfinance.  External seams are stubbed in
the same style as ``tests/test_smoke_integration.py``.  Assertions
check shape and JSON-cleanliness — never exact headline text or
scores — so the file flags only real product regressions.
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
# JSON-cleanliness helper.
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
# Stub clusters for the /news in-memory cache.
#
# Distinct ``source_count`` + ``published_at`` so the cursor sort key
# (source_count desc, published_at desc, id desc) has a deterministic
# total ordering — pagination tests need the cursor to skip past
# already-seen rows without ambiguity.
# ---------------------------------------------------------------------------

_STUB_CLUSTERS = [
    {
        "id": 100 + i,
        "headline": f"Stub headline {i}",
        "sources": [{"name": "Reuters"}],
        "source_count": 12 - i,
        "published_at": f"2026-04-{20 - i:02d}T12:00:00+00:00",
    }
    for i in range(10)
]


def _stub_payload(clusters=None):
    """Return a /news cache payload with the documented top-level keys."""
    cs = list(clusters if clusters is not None else _STUB_CLUSTERS)
    return {
        "clusters": cs,
        "total_headlines": len(cs),
        "feed_status": [],
        "refresh_meta": {
            "status": "ok",
            "source": "test_prime",
            "known": 0, "new": len(cs), "merged": 0,
            "created": len(cs), "reused": 0,
            "last_successful_refresh": None,
            "freshness": "fresh",
        },
    }


_PATCHES = [
    # Anything that would otherwise reach the real news pipeline.
    patch("api.fetch_all", return_value=(
        [{"source": "Reuters", "title": "Stub headline",
          "published_at": "2025-01-01T00:00:00", "url": ""}],
        [{"name": "Reuters", "url": "https://example.com",
          "ok": True, "count": 1, "error": None}],
    )),
    patch("api.cluster_headlines", return_value=_STUB_CLUSTERS),
]


# ---------------------------------------------------------------------------
# Base — temp DB per test, shared TestClient.
# ---------------------------------------------------------------------------

class HeadlinesContractBase(unittest.TestCase):
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
        self._api_mod = _api_mod
        self._orig_db = db.DB_FILE
        self._tmp_db = os.path.join(
            os.path.dirname(__file__),
            f"test_headlines_{uuid.uuid4().hex}.db",
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

    def _prime_news(self, clusters=None):
        """Seed the in-memory /news cache with a known payload."""
        self._api_mod._news_cache["data"] = _stub_payload(clusters)
        self._api_mod._news_cache["ts"] = float("inf")  # never expires in test

    def _get_ok(self, path, **params):
        r = self.client.get(path, params=params)
        self.assertEqual(r.status_code, 200, f"{path}: {r.text}")
        return r.json()


# ---------------------------------------------------------------------------
# /news — top-level shape + degradation.
# ---------------------------------------------------------------------------

class TestNewsShape(HeadlinesContractBase):
    """The Headlines page reads /news; every documented top-level key
    must be present even on an empty cache so the UI can branch on
    ``data_quality`` / ``degraded_fields`` instead of a missing field
    crashing the page."""

    def test_empty_cache_returns_full_envelope(self):
        # No prime — cache miss.  The cache-only route returns its declared
        # envelope with an explicit unavailable state (never a fabricated
        # empty-success feed).  setUp guarantees an empty hot + fresh temp DB.
        body = self._get_ok("/news")
        _assert_json_clean(self, body, "GET /news empty")
        for key in (
            "clusters", "next_cursor", "total_headlines", "total_count",
            "feed_status", "refresh_meta",
            "macro_releases", "policy_items",
            "data_quality", "degraded_fields",
            "availability", "refresh_required",
        ):
            self.assertIn(key, body, f"Missing /news key: {key}")
        self.assertEqual(body["clusters"], [])
        self.assertEqual(body["total_count"], 0)
        self.assertIsNone(body["next_cursor"])
        self.assertIsInstance(body["feed_status"], list)
        self.assertIsInstance(body["macro_releases"], list)
        self.assertIsInstance(body["policy_items"], list)
        self.assertIn(body["data_quality"], ("ok", "degraded"))
        self.assertIsInstance(body["degraded_fields"], list)
        # Honest availability: an empty cache is unavailable, not empty-success.
        self.assertEqual(body["availability"], "unavailable")
        self.assertTrue(body["refresh_required"])

    def test_populated_cache_response_shape(self):
        self._prime_news()
        body = self._get_ok("/news")
        _assert_json_clean(self, body, "GET /news populated")
        self.assertEqual(body["total_count"], len(_STUB_CLUSTERS))
        self.assertEqual(len(body["clusters"]), len(_STUB_CLUSTERS))

    def test_cluster_carries_required_fields(self):
        """Every cluster row must carry the keys the Headlines page reads —
        regardless of which enrichment passes succeed.  This catches a
        regression where attach_policy_timing_blocks (or any enricher) drops
        the original fields on its way through."""
        self._prime_news()
        body = self._get_ok("/news", limit=3)
        self.assertGreater(len(body["clusters"]), 0)
        for c in body["clusters"]:
            for key in ("id", "headline", "source_count", "published_at"):
                self.assertIn(key, c, f"Missing cluster key: {key}")

    def test_data_quality_marker_is_pinned_enum(self):
        self._prime_news()
        body = self._get_ok("/news")
        self.assertIn(body["data_quality"], ("ok", "degraded"))

    def test_degraded_when_enricher_fails(self):
        """A failing enrichment hop must surface as ``data_quality='degraded'``
        with the failed name in ``degraded_fields`` — not as a silent empty
        list that the UI would render as if it were the truth."""
        self._prime_news()
        with patch("routes.news.get_macro_releases", side_effect=RuntimeError("boom")):
            body = self._get_ok("/news")
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("macro_releases", body["degraded_fields"])
        # The cluster list itself must still come through — one failed hop
        # should not break the rest of the response.
        self.assertEqual(body["total_count"], len(_STUB_CLUSTERS))

    def test_policy_items_failure_marks_degraded(self):
        self._prime_news()
        with patch("routes.news.get_policy_items", side_effect=RuntimeError("boom")):
            body = self._get_ok("/news")
        self.assertEqual(body["data_quality"], "degraded")
        self.assertIn("policy_items", body["degraded_fields"])
        self.assertEqual(body["policy_items"], [])


# ---------------------------------------------------------------------------
# /news pagination — cursor stability + bad-cursor handling.
# ---------------------------------------------------------------------------

class TestNewsPagination(HeadlinesContractBase):
    def test_limit_zero_returns_all(self):
        self._prime_news()
        body = self._get_ok("/news", limit=0)
        self.assertEqual(len(body["clusters"]), body["total_count"])
        self.assertIsNone(body["next_cursor"])

    def test_limit_slices_and_emits_cursor(self):
        self._prime_news()
        body = self._get_ok("/news", limit=4)
        self.assertEqual(len(body["clusters"]), 4)
        self.assertEqual(body["total_count"], len(_STUB_CLUSTERS))
        self.assertIsInstance(body["next_cursor"], str)
        self.assertTrue(body["next_cursor"])

    def test_cursor_advances_without_overlap(self):
        self._prime_news()
        b0 = self._get_ok("/news", limit=4)
        b1 = self._get_ok("/news", limit=4, cursor=b0["next_cursor"])
        ids_0 = {c["id"] for c in b0["clusters"]}
        ids_1 = {c["id"] for c in b1["clusters"]}
        self.assertEqual(ids_0 & ids_1, set(), "pages must not overlap")

    def test_last_page_emits_null_cursor(self):
        self._prime_news()
        body = self._get_ok("/news", limit=500)
        self.assertIsNone(body["next_cursor"])

    def test_total_count_stable_across_pages(self):
        self._prime_news()
        b0 = self._get_ok("/news", limit=4)
        b1 = self._get_ok("/news", limit=4, cursor=b0["next_cursor"])
        self.assertEqual(b0["total_count"], b1["total_count"])

    def test_bad_cursor_rejected_with_422(self):
        self._prime_news()
        r = self.client.get("/news", params={"cursor": "not-a-real-cursor"})
        self.assertEqual(r.status_code, 422, r.text)


# ---------------------------------------------------------------------------
# /news/refresh — happy path + cooldown.
# ---------------------------------------------------------------------------

class TestNewsRefresh(HeadlinesContractBase):
    def test_refresh_returns_200_and_envelope(self):
        r = self.client.post("/news/refresh")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        _assert_json_clean(self, body, "POST /news/refresh")
        self.assertIn("clusters", body)
        self.assertIn("refresh_meta", body)
        self.assertIsInstance(body["clusters"], list)
        self.assertIsInstance(body["refresh_meta"], dict)
        self.assertIn("status", body["refresh_meta"])

    def test_cooldown_returns_recent_status(self):
        """A second refresh inside the cooldown window must return the
        cached payload tagged ``status='recent'`` — never trigger a
        second live fetch and never crash."""
        original_cooldown = self._api_mod._REFRESH_COOLDOWN_SECONDS
        self._api_mod._REFRESH_COOLDOWN_SECONDS = 3600
        try:
            self.client.post("/news/refresh")  # prime
            r2 = self.client.post("/news/refresh")
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r2.json()["refresh_meta"]["status"], "recent")
        finally:
            self._api_mod._REFRESH_COOLDOWN_SECONDS = original_cooldown


# ---------------------------------------------------------------------------
# /news/trends — list shape.
# ---------------------------------------------------------------------------

class TestNewsTrendsShape(HeadlinesContractBase):
    def test_trends_returns_list_on_empty_db(self):
        body = self._get_ok("/news/trends")
        self.assertIsInstance(body, list)
        _assert_json_clean(self, body, "GET /news/trends")

    def test_trends_accepts_param_overrides(self):
        body = self._get_ok(
            "/news/trends",
            window_hours=24, min_sources=2, limit=5,
        )
        self.assertIsInstance(body, list)


if __name__ == "__main__":
    unittest.main()
