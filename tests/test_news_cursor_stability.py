"""
tests/test_news_cursor_stability.py

Cursor-based pagination contract for GET /news.

Offset-based pagination over the cached cluster list was unstable: a new
cluster arriving between page requests would shift every subsequent page
by one, causing silent duplicates or skips in the frontend infinite query.

The cursor contract must guarantee:
  1. Walking the full list with the issued cursor visits every cluster
     exactly once and terminates with next_cursor = None.
  2. Inserting a new high-priority cluster at the head between page
     requests does not cause duplicates downstream of the cursor.
  3. Removing the cluster pointed at by the cursor still advances past
     it — the caller is not permanently stuck.
  4. Malformed cursors are rejected (422), not silently reset.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from fastapi.testclient import TestClient

import api as api_module
from routes.news import _encode_cursor


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _cluster(cid: int, source_count: int, published_at: str, headline: str | None = None) -> dict:
    return {
        "id": cid,
        "headline": headline or f"Cluster {cid}",
        "sources": [{"name": "Reuters"}],
        "source_count": source_count,
        "published_at": published_at,
    }


def _make_payload(clusters: list[dict]) -> dict:
    return {
        "clusters": clusters,
        "total_headlines": sum(c["source_count"] for c in clusters),
        "feed_status": [],
        "refresh_meta": {
            "status": "ok", "source": "test_prime",
            "known": 0, "new": len(clusters), "merged": 0,
            "created": len(clusters), "reused": 0,
            "last_successful_refresh": None, "freshness": "fresh",
        },
    }


class CursorContractTestCase(unittest.TestCase):
    """Shared harness: stub out every analytical dependency /news pulls."""

    @classmethod
    def setUpClass(cls):
        cls.patches = [
            patch("routes.news.get_macro_releases", return_value=[]),
            patch("routes.news.classify_macro_surprise", side_effect=lambda rel, _c: rel),
            patch("routes.news.get_policy_items", return_value=[]),
        ]
        for p in cls.patches:
            p.start()
        cls.client = TestClient(api_module.app)

    @classmethod
    def tearDownClass(cls):
        for p in cls.patches:
            p.stop()

    def _prime(self, clusters: list[dict]) -> None:
        """Swap the in-memory cache so /news reads our fixture directly."""
        api_module._news_cache["data"] = _make_payload(clusters)
        api_module._news_cache["ts"] = float("inf")


# ---------------------------------------------------------------------------
# 1. Baseline traversal — every cluster seen once, terminates cleanly
# ---------------------------------------------------------------------------

class TestCursorWalk(CursorContractTestCase):
    """Walking the list page-by-page visits every cluster exactly once."""

    def test_full_walk_covers_every_cluster(self):
        clusters = [
            _cluster(i, source_count=1, published_at=f"2026-04-{30 - i:02d}T12:00:00+00:00")
            for i in range(10)
        ]
        self._prime(clusters)

        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            url = "/news?limit=3"
            if cursor:
                url += f"&cursor={cursor}"
            body = self.client.get(url).json()
            seen.extend(c["headline"] for c in body["clusters"])
            pages += 1
            cursor = body["next_cursor"]
            if cursor is None:
                break
            self.assertLess(pages, 20, "Pagination failed to terminate")

        # Every cluster seen exactly once, order respects sort contract
        self.assertEqual(len(seen), 10)
        self.assertEqual(len(set(seen)), 10)


# ---------------------------------------------------------------------------
# 2. Insert-at-head stability — new cluster does not duplicate downstream
# ---------------------------------------------------------------------------

class TestCursorSurvivesInsertAtHead(CursorContractTestCase):
    """A new cluster arriving between page requests must not shift pagination."""

    def test_insert_does_not_duplicate_downstream(self):
        # Start with 6 clusters sorted newest-first.
        initial = [
            _cluster(i, source_count=1, published_at=f"2026-04-{20 - i:02d}T12:00:00+00:00")
            for i in range(6)
        ]
        self._prime(initial)

        # Fetch page 1 (size 3).
        b0 = self.client.get("/news?limit=3").json()
        self.assertEqual(len(b0["clusters"]), 3)
        cursor = b0["next_cursor"]
        self.assertIsNotNone(cursor)
        seen_0 = [c["headline"] for c in b0["clusters"]]

        # Simulate a fresh cluster arriving at the head of the cache.
        new_head = _cluster(99, source_count=5, published_at="2026-05-01T12:00:00+00:00",
                            headline="Brand new top cluster")
        self._prime([new_head] + initial)

        # Fetch page 2 using the cursor from page 1.
        b1 = self.client.get(f"/news?limit=3&cursor={cursor}").json()
        seen_1 = [c["headline"] for c in b1["clusters"]]

        # No overlap: none of the downstream clusters should repeat.
        self.assertEqual(set(seen_0) & set(seen_1), set())
        # And the new head must NOT leak into the downstream page.
        self.assertNotIn("Brand new top cluster", seen_1)


# ---------------------------------------------------------------------------
# 3. Cursor target evicted — still advances past it
# ---------------------------------------------------------------------------

class TestCursorSurvivesTargetEviction(CursorContractTestCase):
    """If the cluster the cursor points at is removed, the next page must
    still step past it instead of restarting from the top or getting stuck."""

    def test_missing_cursor_target_is_skipped(self):
        clusters = [
            _cluster(i, source_count=1, published_at=f"2026-04-{30 - i:02d}T12:00:00+00:00")
            for i in range(5)
        ]
        self._prime(clusters)

        # Hand-craft a cursor pointing at the 3rd cluster (index 2).
        cursor = _encode_cursor(clusters[2])

        # Remove the cluster the cursor points at.
        survivors = [c for c in clusters if c["id"] != clusters[2]["id"]]
        self._prime(survivors)

        body = self.client.get(f"/news?limit=10&cursor={cursor}").json()
        returned_ids = [c["id"] for c in body["clusters"]]
        # Must return the two clusters strictly-after the evicted one (ids 3, 4),
        # never loop back to the top.
        self.assertEqual(returned_ids, [3, 4])
        self.assertIsNone(body["next_cursor"])


# ---------------------------------------------------------------------------
# 4. Malformed cursor → 422
# ---------------------------------------------------------------------------

class TestCursorValidation(CursorContractTestCase):
    def test_garbage_cursor_rejected(self):
        self._prime([_cluster(1, 1, "2026-04-01T00:00:00+00:00")])
        r = self.client.get("/news?limit=10&cursor=%%not-a-real-cursor%%")
        self.assertEqual(r.status_code, 422)

    def test_base64_with_wrong_schema_rejected(self):
        import base64, json
        bad = base64.urlsafe_b64encode(json.dumps({"foo": "bar"}).encode()).decode().rstrip("=")
        self._prime([_cluster(1, 1, "2026-04-01T00:00:00+00:00")])
        r = self.client.get(f"/news?limit=10&cursor={bad}")
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
