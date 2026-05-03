"""
tests/test_candidates_endpoint.py

Focused tests for the read-only ``/candidates/unanalyzed`` diagnostic.

Invariants:
  1) Endpoint returns 200 with the expected envelope shape.
  2) Already-analyzed clusters (matched against the saved-event archive)
     are filtered out — using the same ``_find_recent_saved_event`` path
     the backfill uses.
  3) Ranking respects priority_score descending, then source_count
     descending.
  4) Endpoint never invokes ``_api.analyze_event`` or ``_api.market_check``
     — even if those raise on call.
  5) Diagnostics carry the per-gate filter counts so an operator can see
     how the working set was trimmed without spending an LLM call.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


def _iso(hours_ago: float) -> str:
    return (datetime.now() - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def _cluster(
    *,
    headline: str,
    source_count: int = 3,
    hours_ago: float = 1.0,
    cluster_id: int = 1,
    sources: list[str] | None = None,
) -> dict:
    return {
        "id": cluster_id,
        "headline": headline,
        "summary": "Demo cluster summary.",
        "published_at": _iso(hours_ago),
        "source_count": source_count,
        "sources": [
            {"name": s} for s in (sources or ["Reuters", "FT", "Bloomberg"])
        ],
        "evidence": [],
        "low_signal": False,
    }


class _CandidatesBase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as _api
        cls._api = _api
        cls.client = TestClient(_api.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"test_cand_{uuid.uuid4().hex}.db"
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Seed the in-memory news cache via the shared hot path.  Each
        # test rebuilds the cluster list on its own setUp.
        self._api._news_cache.update({
            "data": {
                "clusters": [],
                "total_headlines": 0,
                "refresh_meta": {"status": "ok"},
            },
            "ts": time.monotonic(),
        })

    def tearDown(self):
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _set_clusters(self, clusters: list[dict]) -> None:
        self._api._news_cache.update({
            "data": {
                "clusters": clusters,
                "total_headlines": len(clusters),
                "refresh_meta": {"status": "ok"},
            },
            "ts": time.monotonic(),
        })


class TestEndpointShape(_CandidatesBase):

    def test_returns_200_with_expected_envelope(self):
        self._set_clusters([_cluster(
            headline="OPEC cuts crude output unexpectedly",
            source_count=4, hours_ago=0.5, cluster_id=1,
        )])
        r = self.client.get("/candidates/unanalyzed?limit=10")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("status"), "ok")
        self.assertIsInstance(body.get("candidates"), list)
        self.assertIsInstance(body.get("diagnostics"), dict)
        self.assertIn("notes", body)

    def test_diagnostics_count_filter_buckets(self):
        self._set_clusters([
            _cluster(headline="OPEC cuts crude output unexpectedly",
                     source_count=4, hours_ago=0.5, cluster_id=1),
            _cluster(headline="Lifestyle column on celebrity gossip",
                     source_count=2, hours_ago=1.0, cluster_id=2),
            _cluster(headline="Fed rate decision expected next week",
                     source_count=2, hours_ago=72.0, cluster_id=3),
        ])
        r = self.client.get(
            "/candidates/unanalyzed?limit=10&since_hours=24"
        )
        diag = r.json().get("diagnostics") or {}
        self.assertEqual(diag.get("clusters_in_cache"), 3)
        self.assertGreaterEqual(diag.get("filtered_outside_window", 0), 1)
        self.assertGreaterEqual(diag.get("filtered_irrelevant", 0), 1)
        self.assertGreaterEqual(diag.get("candidates_returned", 0), 1)


class TestRanking(_CandidatesBase):

    def test_priority_score_descending(self):
        self._set_clusters([
            _cluster(headline="Lower-priority oil sanctions update",
                     source_count=2, hours_ago=10.0, cluster_id=1),
            _cluster(headline="Major OPEC oil supply cut announcement",
                     source_count=8, hours_ago=0.3, cluster_id=2),
            _cluster(headline="Mid-priority gold sanctions story",
                     source_count=4, hours_ago=4.0, cluster_id=3),
        ])
        r = self.client.get("/candidates/unanalyzed?limit=10")
        candidates = r.json().get("candidates") or []
        scores = [c["priority_score"] for c in candidates]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertEqual(candidates[0]["headline"],
                         "Major OPEC oil supply cut announcement")

    def test_explicit_ticker_lifts_score(self):
        # Two clusters, identical except the second mentions $NVDA.
        self._set_clusters([
            _cluster(headline="Semi sanctions tighten on China",
                     source_count=3, hours_ago=2.0, cluster_id=1),
            _cluster(headline="$NVDA caught in tighter China semi sanctions",
                     source_count=3, hours_ago=2.0, cluster_id=2),
        ])
        r = self.client.get("/candidates/unanalyzed?limit=10")
        candidates = r.json().get("candidates") or []
        # Score lookup
        by_h = {c["headline"]: c for c in candidates}
        self.assertGreater(
            by_h["$NVDA caught in tighter China semi sanctions"]["priority_score"],
            by_h["Semi sanctions tighten on China"]["priority_score"],
        )


class TestAlreadyAnalyzedDedup(_CandidatesBase):

    def test_filters_out_already_analyzed_cluster(self):
        # Save an event whose headline matches a cluster headline exactly.
        analyzed_headline = "OPEC cuts crude output unexpectedly"
        db.save_event({
            "headline": analyzed_headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": datetime.now().strftime("%Y-%m-%d"),
            "timestamp": _iso(0.5),
            "what_changed": "Pre-existing analysis",
            "mechanism_summary": "Analyzed already.",
            "market_tickers": [],
        })
        self._set_clusters([
            _cluster(headline=analyzed_headline,
                     source_count=4, hours_ago=0.5, cluster_id=1),
            _cluster(headline="Iran oil sanctions tighten further",
                     source_count=2, hours_ago=1.0, cluster_id=2),
        ])
        r = self.client.get("/candidates/unanalyzed?limit=10")
        body = r.json()
        headlines = [c["headline"] for c in (body.get("candidates") or [])]
        self.assertNotIn(analyzed_headline, headlines)
        diag = body.get("diagnostics") or {}
        self.assertGreaterEqual(diag.get("filtered_already_analyzed", 0), 1)


class TestNoLLMCalls(_CandidatesBase):

    def test_endpoint_returns_200_when_llm_paths_raise(self):
        """Behavioural: the endpoint must work even if every LLM-side
        helper is wired to raise.  This proves the endpoint cannot
        silently spend a paid call on the operator's behalf.
        """
        self._set_clusters([_cluster(
            headline="OPEC cuts crude output unexpectedly",
            source_count=4, hours_ago=0.5, cluster_id=1,
        )])

        def _boom(*_a, **_kw):
            raise AssertionError("LLM/market_check was invoked")

        with patch.object(self._api, "analyze_event", _boom), \
             patch.object(self._api, "market_check", _boom):
            r = self.client.get("/candidates/unanalyzed?limit=10")
        self.assertEqual(r.status_code, 200)
        candidates = r.json().get("candidates") or []
        self.assertGreaterEqual(len(candidates), 1)


class TestMinSourceCountFilter(_CandidatesBase):

    def test_min_source_count_drops_thin_clusters(self):
        self._set_clusters([
            _cluster(headline="Major OPEC oil supply cut",
                     source_count=5, hours_ago=1.0, cluster_id=1),
            _cluster(headline="Singleton oil rumour from minor blog",
                     source_count=1, hours_ago=1.0, cluster_id=2),
        ])
        r = self.client.get(
            "/candidates/unanalyzed?limit=10&min_source_count=3"
        )
        body = r.json()
        headlines = [c["headline"] for c in (body.get("candidates") or [])]
        self.assertIn("Major OPEC oil supply cut", headlines)
        self.assertNotIn("Singleton oil rumour from minor blog", headlines)
        diag = body.get("diagnostics") or {}
        self.assertGreaterEqual(
            diag.get("filtered_below_min_source_count", 0), 1,
        )


if __name__ == "__main__":
    unittest.main()
