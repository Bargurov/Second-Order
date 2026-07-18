"""P2-1 boundary contract: GET /news must be cache-only.

The shared reader ``api._get_news_cached`` feeds five GET paths
(routes/news.py, routes/analyze.py, routes/market.py, and two api.py
enrichment sites).  On a missing / malformed / stale cache it must NOT
reach the refresh owner: no ``_fetch_fresh_news``, no RSS ``fetch_all``,
no cluster-store persistence, no SQLite/cache write, and no refresh-lock
acquisition — regardless of concurrency.  The explicit refresh owner
(``POST /news/refresh``) keeps its lock + cooldown and remains the ONLY
path that may fetch/cluster/persist.

Honesty: a missing/malformed local cache is reported as an explicit
``availability="unavailable"`` (refresh_required=True) state, never as a
successful empty feed.  A valid empty feed stays distinguishable.

All offline: RSS/write seams are recording fakes; no real feed is hit.
"""

import os
import sqlite3
import sys
import threading
import unittest
import uuid
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

import api as _api
import db
import news_cluster_store

_TTL = 300


def _valid_payload(**overrides) -> dict:
    base = {
        "clusters": [{"headline": "x", "source_count": 1, "id": 1,
                      "published_at": "2026-05-01T10:00:00"}],
        "total_headlines": 1,
        "feed_status": [],
        "refresh_meta": {"status": "ok", "freshness": "fresh",
                         "source": "incremental",
                         "last_successful_refresh": "2026-05-01T10:00:00"},
        "_schema_version": _api._NEWS_CACHE_VERSION,
    }
    base.update(overrides)
    return base


def _empty_valid_payload() -> dict:
    """A genuine refresh that produced zero clusters — valid, not unavailable."""
    return _valid_payload(
        clusters=[], total_headlines=0,
        refresh_meta={"status": "ok", "freshness": "fresh", "source": "empty",
                      "last_successful_refresh": "2026-05-01T10:00:00"},
    )


class _SeamRecorder:
    """Records every refresh/network/write seam the GET path must never hit."""

    def __init__(self):
        self.fetch_fresh = 0
        self.fetch_all = 0
        self.save_cache = 0
        self.cluster_refresh = 0

    def patches(self):
        rec = self

        def _fresh(*a, **k):
            rec.fetch_fresh += 1
            return _valid_payload(clusters=[])

        def _fetch_all(*a, **k):
            rec.fetch_all += 1
            return ([], [{"name": "x", "url": "u", "ok": True,
                          "count": 0, "error": None}])

        def _save(*a, **k):
            rec.save_cache += 1

        def _cluster(*a, **k):
            rec.cluster_refresh += 1
            return []

        return [
            mock.patch.object(_api, "_fetch_fresh_news", _fresh),
            mock.patch.object(_api, "fetch_all", _fetch_all),
            mock.patch.object(_api, "save_news_cache", _save),
            mock.patch.object(news_cluster_store, "refresh_clusters", _cluster),
        ]


class _NewsGetBase(unittest.TestCase):
    def setUp(self):
        self._orig_hot = dict(_api._news_cache)
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0
        self.rec = _SeamRecorder()
        self._patches = self.rec.patches()
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)

    def _load_stub(self, *, fresh=None, stale=None):
        """Fake api.load_news_cache keyed on the requested max_age window.

        Models the real contract: ``max_age_seconds=None`` is the read-any-age
        request (stale fallback) and returns whatever is stored regardless of
        age; a numeric bound within the TTL returns the fresh payload.
        """
        def _fake(max_age_seconds=_TTL):
            if max_age_seconds is None:
                return stale
            return fresh if max_age_seconds <= _TTL else stale
        return mock.patch.object(_api, "load_news_cache", _fake)

    def assert_no_refresh(self, label):
        self.assertEqual(self.rec.fetch_fresh, 0, f"{label}: _fetch_fresh_news reached")
        self.assertEqual(self.rec.fetch_all, 0, f"{label}: RSS fetch_all reached")
        self.assertEqual(self.rec.save_cache, 0, f"{label}: save_news_cache written")
        self.assertEqual(self.rec.cluster_refresh, 0, f"{label}: cluster store written")


# ---------------------------------------------------------------------------
# Reader-level state contract (api.read_news_cache_state / _get_news_cached)
# ---------------------------------------------------------------------------

class TestCacheStateReader(_NewsGetBase):

    def test_missing_cache_is_unavailable_without_refresh(self):
        with self._load_stub(fresh=None, stale=None):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "unavailable")
        self.assertTrue(state.refresh_required)
        self.assertIsNone(state.payload)
        self.assert_no_refresh("missing")

    def test_malformed_cache_is_unavailable_without_refresh(self):
        bad = {"clusters": {"oops": True}, "total_headlines": 0}
        with self._load_stub(fresh=bad, stale=bad):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "unavailable")
        self.assert_no_refresh("malformed")

    def test_stale_cache_is_served_marked_stale_without_refresh(self):
        stale = _valid_payload(clusters=[{"headline": "old"}])
        with self._load_stub(fresh=None, stale=stale):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "stale")
        self.assertTrue(state.refresh_required)
        self.assertEqual(state.payload["clusters"][0]["headline"], "old")
        self.assert_no_refresh("stale")

    def test_fresh_cache_is_available(self):
        good = _valid_payload()
        with self._load_stub(fresh=good, stale=good):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "available")
        self.assertFalse(state.refresh_required)
        self.assert_no_refresh("fresh")

    def test_valid_empty_cache_is_available_not_unavailable(self):
        empty = _empty_valid_payload()
        with self._load_stub(fresh=empty, stale=empty):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "available")
        self.assertEqual(state.payload["clusters"], [])
        self.assertNotEqual(state.availability, "unavailable")
        self.assert_no_refresh("valid-empty")

    def test_persisted_records_absent_json_cache_is_unavailable(self):
        # JSON news_cache blob absent even though the cluster store may hold
        # rows: GET reads only the blob and reports unavailable — it does not
        # reconstruct (that is the refresh owner's job).
        with self._load_stub(fresh=None, stale=None):
            state = _api.read_news_cache_state()
        self.assertEqual(state.availability, "unavailable")
        self.assert_no_refresh("persisted-records-no-json")

    def test_get_news_cached_returns_empty_clusters_when_unavailable(self):
        with self._load_stub(fresh=None, stale=None):
            payload = _api._get_news_cached()
        self.assertIsInstance(payload.get("clusters"), list)
        self.assertEqual(payload["clusters"], [])
        self.assert_no_refresh("_get_news_cached unavailable")

    def test_concurrent_cold_reads_trigger_no_refresh(self):
        results = []
        barrier = threading.Barrier(2)

        def _worker():
            barrier.wait()
            with self._load_stub(fresh=None, stale=None):
                results.append(_api._get_news_cached())

        threads = [threading.Thread(target=_worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 2)
        self.assert_no_refresh("concurrent cold reads")


# ---------------------------------------------------------------------------
# Route-level contract (GET /news via TestClient) — real reader, faked seams
# ---------------------------------------------------------------------------

class TestNewsRouteBoundary(_NewsGetBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(_api.app)

    def test_get_news_unavailable_is_honest_and_offline(self):
        with self._load_stub(fresh=None, stale=None):
            r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body.get("availability"), "unavailable")
        self.assertTrue(body.get("refresh_required"))
        self.assertEqual(body.get("clusters"), [])
        self.assert_no_refresh("GET /news unavailable")

    def test_get_news_valid_empty_distinct_from_unavailable(self):
        empty = _empty_valid_payload()
        with self._load_stub(fresh=empty, stale=empty):
            r = self.client.get("/news")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body.get("availability"), "available")
        self.assertEqual(body.get("clusters"), [])
        self.assertFalse(body.get("refresh_required"))
        self.assert_no_refresh("GET /news valid-empty")

    def test_get_news_fresh_serves_clusters(self):
        good = _valid_payload()
        with self._load_stub(fresh=good, stale=good):
            r = self.client.get("/news")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body.get("availability"), "available")
        self.assertEqual(len(body.get("clusters")), 1)
        self.assert_no_refresh("GET /news fresh")

    def test_get_news_stale_marked_and_offline(self):
        stale = _valid_payload(clusters=[{"headline": "old"}])
        with self._load_stub(fresh=None, stale=stale):
            r = self.client.get("/news")
        body = r.json()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(body.get("availability"), "stale")
        self.assertTrue(body.get("refresh_required"))
        self.assert_no_refresh("GET /news stale")


class TestNewsRouteRealReaderBoundary(unittest.TestCase):
    """The reader itself is REAL — only the RSS/write seams are recorders.

    This is the regression the prior audit missed: a route-safety suite that
    left the reader unpatched reached real RSS through the read-through
    fallback.  With the cache-only reader, a cold GET must record zero.
    """

    def setUp(self):
        self._orig_hot = dict(_api._news_cache)
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0
        self.fetch_all_calls = 0
        self.save_calls = 0
        self.cluster_calls = 0

        def _fetch_all(*a, **k):
            self.fetch_all_calls += 1
            return ([], [{"name": "x", "url": "u", "ok": True,
                          "count": 0, "error": None}])

        def _save(*a, **k):
            self.save_calls += 1

        def _cluster(*a, **k):
            self.cluster_calls += 1
            return []

        # NB: _fetch_fresh_news is deliberately NOT patched — the real reader
        # must not reach it at all.
        self._patches = [
            mock.patch.object(_api, "fetch_all", _fetch_all),
            mock.patch.object(_api, "save_news_cache", _save),
            mock.patch.object(news_cluster_store, "refresh_clusters", _cluster),
            mock.patch.object(_api, "load_news_cache", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(_api.app)

    def tearDown(self):
        for p in reversed(self._patches):
            p.stop()
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)

    def test_cold_get_news_never_reaches_rss_or_writes(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.fetch_all_calls, 0,
                         "GET /news reached real RSS fetch_all")
        self.assertEqual(self.save_calls, 0, "GET /news wrote the news cache")
        self.assertEqual(self.cluster_calls, 0,
                         "GET /news wrote the cluster store")
        self.assertEqual(r.json().get("availability"), "unavailable")


class TestRefreshOwnerSingleFlight(unittest.TestCase):
    """POST /news/refresh stays the single-flight refresh owner.

    When the refresh lock is already held (a refresh in flight) the route must
    NOT start a second fetch — it returns the documented throttled response.
    When the lock is free it runs exactly one fetch.
    """

    def setUp(self):
        self._saved_payload = _api._last_refresh_payload
        self._saved_at = _api._last_refresh_at

    def tearDown(self):
        _api._last_refresh_payload = self._saved_payload
        _api._last_refresh_at = self._saved_at
        # Never leave the lock held for a later test.
        try:
            _api._refresh_lock.release()
        except RuntimeError:
            pass

    def test_refresh_skips_fetch_when_lock_already_held(self):
        from routes.news import news_refresh
        import time as _t
        _api._last_refresh_payload = _valid_payload()
        _api._last_refresh_at = _t.monotonic() - 3600  # past the cooldown window
        calls = []

        def _fresh():
            calls.append(1)
            return _valid_payload()

        with mock.patch.object(_api, "_fetch_fresh_news", _fresh):
            acquired = _api._refresh_lock.acquire(blocking=False)
            self.assertTrue(acquired)
            try:
                resp = news_refresh(None)
            finally:
                _api._refresh_lock.release()

        self.assertEqual(calls, [], "a second refresh ran while one was in flight")
        self.assertEqual(resp["refresh_meta"]["status"], "throttled")

    def test_refresh_runs_single_fetch_when_lock_free(self):
        from routes.news import news_refresh
        _api._last_refresh_payload = None
        _api._last_refresh_at = 0.0
        calls = []

        def _fresh():
            calls.append(1)
            return _valid_payload()

        with mock.patch.object(_api, "_fetch_fresh_news", _fresh):
            resp = news_refresh(None)

        self.assertEqual(calls, [1], "the sole refresh owner must run exactly once")
        self.assertTrue(_api._refresh_lock.acquire(blocking=False),
                        "refresh lock must be released after the fetch")
        _api._refresh_lock.release()
        self.assertIn("refresh_meta", resp)


# ---------------------------------------------------------------------------
# Any-age stale-cache contract (REAL db.load_news_cache against a temp DB)
# ---------------------------------------------------------------------------

class TestStaleCacheServedAtAnyAge(unittest.TestCase):
    """A shape-valid persisted cache is served as STALE regardless of age.

    Uses the REAL db.load_news_cache against a temp DB with a backdated
    fetched_at — no invented maximum-age cutoff may turn valid local evidence
    into "unavailable".  Malformed content stays unavailable at any age.  The
    read never refreshes (asserts _fetch_fresh_news is not called).
    """

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            os.path.dirname(__file__),
            f"test_news_anyage_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._tmp
        db.init_db()
        self._orig_hot = _api._news_cache.copy()
        _api._news_cache["data"] = None
        _api._news_cache["ts"] = 0.0

    def tearDown(self):
        _api._news_cache["data"] = self._orig_hot.get("data")
        _api._news_cache["ts"] = self._orig_hot.get("ts", 0.0)
        db.DB_FILE = self._orig_db
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass

    def _persist_aged(self, payload, days_old):
        db.save_news_cache(payload)
        old_iso = (datetime.now() - timedelta(days=days_old)).isoformat(
            timespec="seconds")
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute("UPDATE news_cache SET fetched_at = ? WHERE id = 1",
                         (old_iso,))
            conn.commit()

    def _read_state_no_refresh(self):
        """read_news_cache_state with a recorder on the refresh owner."""
        calls = []
        with mock.patch("api._fetch_fresh_news",
                        side_effect=lambda: calls.append(1) or _valid_payload()):
            state = _api.read_news_cache_state()
        self.assertEqual(calls, [], "a cache-only read reached _fetch_fresh_news")
        return state

    def test_366_day_valid_cache_served_stale(self):
        self._persist_aged(_valid_payload(clusters=[{"headline": "year-old"}]), 366)
        state = self._read_state_no_refresh()
        self.assertEqual(state.availability, "stale")
        self.assertTrue(state.refresh_required)
        self.assertEqual(state.payload["clusters"][0]["headline"], "year-old")

    def test_10_year_valid_cache_served_stale(self):
        self._persist_aged(_valid_payload(clusters=[{"headline": "decade-old"}]),
                           3650)
        state = self._read_state_no_refresh()
        self.assertEqual(state.availability, "stale")
        self.assertTrue(state.refresh_required)
        self.assertEqual(state.payload["clusters"][0]["headline"], "decade-old")

    def test_10_year_malformed_cache_stays_unavailable(self):
        # Age must not rescue malformed content.
        self._persist_aged({"clusters": {"oops": True}, "total_headlines": 0}, 3650)
        state = self._read_state_no_refresh()
        self.assertEqual(state.availability, "unavailable")

    def test_fresh_persisted_cache_available(self):
        db.save_news_cache(_valid_payload(clusters=[{"headline": "new"}]))
        state = self._read_state_no_refresh()
        self.assertEqual(state.availability, "available")
        self.assertFalse(state.refresh_required)

    def test_db_load_news_cache_none_reads_any_age(self):
        # The read-any-age mode returns the payload regardless of age; a numeric
        # bound still age-filters (preserved behavior for existing callers).
        self._persist_aged(_valid_payload(clusters=[{"headline": "aged"}]), 3650)
        self.assertIsNone(db.load_news_cache(max_age_seconds=300),
                          "numeric max_age must still age-filter an old row")
        any_age = db.load_news_cache(max_age_seconds=None)
        self.assertIsNotNone(any_age, "max_age_seconds=None must read any age")
        self.assertEqual(any_age["clusters"][0]["headline"], "aged")


if __name__ == "__main__":
    unittest.main()
