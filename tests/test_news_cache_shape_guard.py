"""Tests for the news-cache shape guard.

Covers:
  * _is_valid_news_payload accepts well-formed payloads
  * missing required keys → guard rejects
  * non-list clusters / feed_status → guard rejects
  * wrong _schema_version → guard rejects
  * legacy payload (no _schema_version) passes when shape is valid
  * _get_news_cached is cache-only: a payload that fails the guard reads as
    unavailable (no refresh), never a fresh RSS fetch from a GET path
  * _fetch_fresh_news stamps every emitted payload with _schema_version
  * load_news_cache + save_news_cache roundtrip preserves the stamp
"""

import os
import sys
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import api as _api
from api import (
    _is_valid_news_payload,
    _NEWS_CACHE_VERSION,
    _NEWS_PAYLOAD_REQUIRED_LIST_KEYS,
)


def _valid_payload(**overrides) -> dict:
    base = {
        "clusters": [{"headline": "x"}],
        "total_headlines": 1,
        "feed_status": [],
        "refresh_meta": {"status": "ok"},
        "_schema_version": _NEWS_CACHE_VERSION,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Shape guard — pure function
# ---------------------------------------------------------------------------

class TestIsValidNewsPayload(unittest.TestCase):
    def test_valid_stamped_payload_passes(self):
        self.assertTrue(_is_valid_news_payload(_valid_payload()))

    def test_none_rejected(self):
        self.assertFalse(_is_valid_news_payload(None))

    def test_non_dict_rejected(self):
        self.assertFalse(_is_valid_news_payload([]))
        self.assertFalse(_is_valid_news_payload("payload"))

    def test_every_required_list_key_must_be_list(self):
        """Each key in _NEWS_PAYLOAD_REQUIRED_LIST_KEYS must be shaped as a
        list.  A non-list value for any of them triggers guard rejection."""
        for key in _NEWS_PAYLOAD_REQUIRED_LIST_KEYS:
            payload = _valid_payload()
            payload[key] = {"not": "list"}
            self.assertFalse(_is_valid_news_payload(payload),
                             f"expected rejection when {key!r} is non-list")

    def test_missing_refresh_meta_tolerated(self):
        """refresh_meta is synthesized by the /news route when absent, so the
        guard must NOT reject a cache payload that omits it (legacy rows)."""
        payload = _valid_payload()
        del payload["refresh_meta"]
        self.assertTrue(_is_valid_news_payload(payload))

    def test_missing_total_headlines_tolerated(self):
        payload = _valid_payload()
        del payload["total_headlines"]
        self.assertTrue(_is_valid_news_payload(payload))

    def test_missing_feed_status_tolerated(self):
        """feed_status defaults to [] on the /news route — guard doesn't
        require it."""
        payload = _valid_payload()
        del payload["feed_status"]
        self.assertTrue(_is_valid_news_payload(payload))

    def test_clusters_must_be_list(self):
        self.assertFalse(_is_valid_news_payload(_valid_payload(clusters={"not": "list"})))

    def test_missing_clusters_rejected(self):
        """clusters is the one load-bearing field — the route iterates it
        directly."""
        payload = _valid_payload()
        del payload["clusters"]
        self.assertFalse(_is_valid_news_payload(payload))

    def test_wrong_schema_version_rejected(self):
        self.assertFalse(_is_valid_news_payload(_valid_payload(_schema_version=999)))

    def test_legacy_payload_without_version_still_passes(self):
        """A pre-guard row (no _schema_version key) whose shape is still
        valid is accepted — the guard upgrades in place without forcing
        every deploy to refresh immediately."""
        legacy = _valid_payload()
        del legacy["_schema_version"]
        self.assertTrue(_is_valid_news_payload(legacy))


# ---------------------------------------------------------------------------
# _get_news_cached — behavior under guard failures
# ---------------------------------------------------------------------------

class TestGetNewsCachedGuarded(unittest.TestCase):

    def setUp(self):
        self._orig_hot = _api._news_cache.copy()
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0

    def tearDown(self):
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)

    def test_malformed_hot_cache_does_not_refresh(self):
        # Cache-only contract: a mis-shaped hot entry (clusters is a dict) must
        # NOT trigger a refresh.  With no persisted payload the read is honestly
        # unavailable — the pre-repair read-through called _fetch_fresh_news here.
        bad = {"clusters": {"oops": True}, "total_headlines": 0, "feed_status": []}
        _api._news_cache["data"] = bad
        _api._news_cache["ts"] = 1e18  # pretend very fresh

        fresh_calls: list[bool] = []

        def _fake_fresh():
            fresh_calls.append(True)
            return _valid_payload(clusters=[{"headline": "fresh"}])

        with patch("api.load_news_cache", return_value=None), \
             patch("api._fetch_fresh_news", side_effect=_fake_fresh):
            out = _api._get_news_cached()
            state = _api.read_news_cache_state()

        self.assertEqual(fresh_calls, [])            # no refresh from a GET read
        self.assertEqual(out["clusters"], [])         # explicit empty payload
        self.assertEqual(state.availability, "unavailable")

    def test_malformed_persisted_cache_does_not_refresh(self):
        # Wrong shape: clusters is a dict instead of a list.  Under the
        # cache-only contract a malformed persisted payload reads as
        # unavailable instead of forcing a fresh fetch.
        bad_persisted = {"clusters": {"oops": True}, "total_headlines": 0}
        fresh_calls: list[bool] = []

        def _fake_fresh():
            fresh_calls.append(True)
            return _valid_payload()

        with patch("api.load_news_cache", return_value=bad_persisted), \
             patch("api._fetch_fresh_news", side_effect=_fake_fresh):
            out = _api._get_news_cached()
            state = _api.read_news_cache_state()

        self.assertEqual(fresh_calls, [])
        self.assertEqual(out["clusters"], [])
        self.assertEqual(state.availability, "unavailable")

    def test_valid_persisted_cache_served_without_refresh(self):
        good = _valid_payload()
        fresh_calls: list[bool] = []

        def _fake_fresh():
            fresh_calls.append(True)
            return _valid_payload(clusters=[{"headline": "should-not-run"}])

        with patch("api.load_news_cache", return_value=good), \
             patch("api._fetch_fresh_news", side_effect=_fake_fresh):
            out = _api._get_news_cached()

        self.assertEqual(fresh_calls, [])
        self.assertEqual(out["_schema_version"], _NEWS_CACHE_VERSION)


# ---------------------------------------------------------------------------
# _fetch_fresh_news stamps the payload it writes
# ---------------------------------------------------------------------------

class TestFreshPayloadStamped(unittest.TestCase):
    """Every payload returned from _fetch_fresh_news carries the version
    stamp the guard will check on the next read."""

    def setUp(self):
        self._orig_hot = _api._news_cache.copy()
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0

    def tearDown(self):
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)

    def test_fresh_payload_carries_schema_version(self):
        with patch("api.fetch_all", return_value=(
                    [{"source": "Test", "title": "Hello",
                      "published_at": "2025-01-01T00:00:00", "url": ""}],
                    [{"name": "Test", "url": "https://x", "ok": True,
                      "count": 1, "error": None}],
                  )), \
             patch("api.cluster_headlines", return_value=[]), \
             patch("api.load_low_signal_headlines", return_value=set()), \
             patch("api.save_news_cache", lambda _p: None):
            payload = _api._fetch_fresh_news()

        self.assertEqual(payload["_schema_version"], _NEWS_CACHE_VERSION)
        self.assertTrue(_is_valid_news_payload(payload))


# ---------------------------------------------------------------------------
# DB roundtrip preserves the stamp
# ---------------------------------------------------------------------------

class TestSaveLoadRoundtripKeepsStamp(unittest.TestCase):
    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = os.path.join(
            os.path.dirname(__file__),
            f"test_news_cache_{uuid.uuid4().hex}.db",
        )
        db.init_db()

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except (OSError, PermissionError):
            pass
        db.DB_FILE = self._orig

    def test_roundtrip_preserves_schema_version(self):
        payload = _valid_payload(clusters=[{"headline": "stamp check"}])
        db.save_news_cache(payload)
        loaded = db.load_news_cache(max_age_seconds=60)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["_schema_version"], _NEWS_CACHE_VERSION)
        self.assertTrue(_is_valid_news_payload(loaded))


# ---------------------------------------------------------------------------
# Cold-start fallback — incremental returns empty, full recluster fires
# ---------------------------------------------------------------------------

class TestColdStartReclusterFallback(unittest.TestCase):
    """When incremental clustering returns 0 clusters from >0 records,
    _fetch_fresh_news must fall back to a full recluster so the /news
    endpoint never shows an empty headlines strip when live feeds have
    data."""

    def setUp(self):
        self._orig_hot = _api._news_cache.copy()
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0

    def tearDown(self):
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)

    def _fake_records(self, n=3):
        return [
            {"source": f"Feed{i}", "title": f"Headline {i}",
             "published_at": "2026-05-01T10:00:00", "url": ""}
            for i in range(n)
        ]

    def _fake_feed_status(self, n=1):
        return [{"name": f"Feed{i}", "ok": True, "headlines": 3}
                for i in range(n)]

    def test_fallback_fires_when_incremental_returns_empty(self):
        records = self._fake_records(5)
        recluster_clusters = [
            {"headline": "Cluster A", "sources": ["Feed0"], "source_count": 1},
            {"headline": "Cluster B", "sources": ["Feed1"], "source_count": 1},
        ]

        def _fake_incremental_empty(recs, *, cluster_fn=None, meta=None):
            if meta is not None:
                meta.update(known=5, new=0, merged=0, created=0,
                            reused=0, source="stored")
            return []

        with patch("api.fetch_all",
                   return_value=(records, self._fake_feed_status())), \
             patch("news_cluster_store.refresh_clusters",
                   side_effect=_fake_incremental_empty), \
             patch("api.cluster_headlines",
                   return_value=list(recluster_clusters)) as mock_ch, \
             patch("api.load_low_signal_headlines", return_value=set()), \
             patch("api.save_news_cache", lambda _p: None):
            payload = _api._fetch_fresh_news()

        mock_ch.assert_called_once_with(records)
        self.assertEqual(len(payload["clusters"]), 2)
        self.assertEqual(payload["clusters"][0]["headline"], "Cluster A")
        self.assertEqual(
            payload["refresh_meta"]["source"], "full_recluster_fallback")

    def test_no_fallback_when_incremental_returns_clusters(self):
        records = self._fake_records(3)
        incremental_clusters = [
            {"headline": "Incremental C", "sources": ["Feed0"],
             "source_count": 1},
        ]

        def _fake_incremental_ok(recs, *, cluster_fn=None, meta=None):
            if meta is not None:
                meta.update(known=0, new=3, merged=0, created=1,
                            reused=0, source="incremental")
            return list(incremental_clusters)

        with patch("api.fetch_all",
                   return_value=(records, self._fake_feed_status())), \
             patch("news_cluster_store.refresh_clusters",
                   side_effect=_fake_incremental_ok), \
             patch("api.cluster_headlines") as mock_ch, \
             patch("api.load_low_signal_headlines", return_value=set()), \
             patch("api.save_news_cache", lambda _p: None):
            payload = _api._fetch_fresh_news()

        mock_ch.assert_not_called()
        self.assertEqual(len(payload["clusters"]), 1)
        self.assertEqual(payload["clusters"][0]["headline"], "Incremental C")
        self.assertEqual(payload["refresh_meta"]["source"], "incremental")

    def test_no_fallback_when_records_empty(self):
        with patch("api.fetch_all",
                   return_value=([], self._fake_feed_status())), \
             patch("news_cluster_store.refresh_clusters",
                   return_value=[]) as mock_inc, \
             patch("api.cluster_headlines") as mock_ch, \
             patch("api.load_low_signal_headlines", return_value=set()), \
             patch("api.save_news_cache", lambda _p: None):
            payload = _api._fetch_fresh_news()

        mock_ch.assert_not_called()
        self.assertEqual(len(payload["clusters"]), 0)


if __name__ == "__main__":
    unittest.main()
