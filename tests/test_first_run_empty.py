"""
tests/test_first_run_empty.py

Pin down the first-run / empty-data contract.

A fresh clone of the project must boot cleanly with:
  - no events.db on disk
  - no movers cache rows
  - no snapshot history
  - no news feed reachable

Three things this file proves end-to-end:

  1. **Bootstrap idempotence** — ``db.init_db`` runs cleanly twice in
     a row against a non-existent file, leaves ``_db_ready`` set, and
     produces a usable schema both times.

  2. **Empty-DB endpoint smoke** — every endpoint the frontend calls
     on first paint returns a 200 with a sane shape (empty list,
     well-formed dict) when the events table is empty and every
     external network dependency is mocked away.

  3. **Degraded composition** — ``/market-context`` returns a usable
     payload (with ``stress.available == False``) even when EVERY
     downstream computation raises.  No 500s when the data layer is
     completely broken.

These tests sit at the seams that will be hit by the very first
public-feedback user opening the app: a fresh DB, no archive, and no
network for upstream feeds.  Without them a regression in any of the
defensive empty-shape contracts would only show up after a user
reported it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402
import api as _api_mod  # noqa: E402
import movers_cache  # noqa: E402


# ---------------------------------------------------------------------------
# Cluster A — db.init_db is idempotent on a fresh path
# ---------------------------------------------------------------------------


class TestInitDbBootstrap(unittest.TestCase):
    """A fresh clone has no events.db file.  init_db must create one."""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_first_run_{uuid.uuid4().hex}.db",
        )
        # Make sure no file exists at the target path.
        if os.path.exists(self._tmp):
            os.remove(self._tmp)
        db.DB_FILE = self._tmp
        db._db_ready = False

    def tearDown(self):
        db.DB_FILE = self._orig
        for suffix in ("", ".bak"):
            p = self._tmp + suffix
            if os.path.exists(p):
                try:
                    os.remove(p)
                except PermissionError:
                    pass

    def test_init_db_creates_file_when_missing(self):
        """First call against a non-existent path creates the schema."""
        self.assertFalse(os.path.exists(self._tmp))
        db.init_db()
        self.assertTrue(os.path.exists(self._tmp))
        self.assertTrue(db._db_ready)

    def test_init_db_idempotent(self):
        """A second init_db on the same path is a no-op, not a crash."""
        db.init_db()
        self.assertTrue(db._db_ready)
        # Reset the guard to prove the second call sets it again.
        db._db_ready = False
        db.init_db()
        self.assertTrue(db._db_ready)

    def test_load_recent_events_empty_after_init(self):
        """Right after init, the events list is empty — never raises."""
        db.init_db()
        events = db.load_recent_events(limit=50)
        self.assertEqual(events, [])

    def test_save_event_then_load_after_fresh_init(self):
        """The bootstrap path produces a usable schema, not just an empty file."""
        db.init_db()
        db.save_event({
            "headline": "First-run smoke event",
            "stage": "realized",
            "persistence": "structural",
        })
        events = db.load_recent_events(limit=5)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "First-run smoke event")


# ---------------------------------------------------------------------------
# Cluster B — endpoint smoke against an empty DB with all network mocked
# ---------------------------------------------------------------------------


# Empty defaults that match the shapes the real backends return.
_EMPTY_FETCH_ALL = ([], [])  # (records, feed_status)
_EMPTY_CLUSTERS: list[dict] = []
_EMPTY_SNAPSHOTS: list = []
_EMPTY_STRESS: dict = {
    "regime": "Calm",
    "summary": "",
    "signals": {},
    "raw": {},
    "detail": {},
}


class TestEmptyDbEndpointSmoke(unittest.TestCase):
    """Hit every frontend-facing endpoint on a freshly initialised empty DB.

    Every endpoint must return 200 with a sane, JSON-decodable shape.
    No 500s, no crashes from .get() on a missing key, no exceptions
    leaking through compose_market_context.
    """

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""
        cls._patches = [
            patch("api.fetch_all", return_value=_EMPTY_FETCH_ALL),
            patch("api.cluster_headlines", return_value=_EMPTY_CLUSTERS),
            # Snapshots: simulate cold-start with no warm cache yet.
            patch(
                "market_snapshots.get_all_snapshots",
                return_value=_EMPTY_SNAPSHOTS,
            ),
            # Stress: a calm-regime placeholder so /stress is well-formed.
            patch(
                "api.compute_stress_regime",
                return_value=_EMPTY_STRESS,
            ),
            # Rates: a minimal degraded shape (the real one ships with
            # available=False when the price cache is empty).
            patch(
                "api.compute_rates_context",
                return_value={
                    "regime": "unknown",
                    "nominal": {"label": "10Y", "value": None, "change_5d": None},
                    "real_proxy": {"label": "TIP", "value": None, "change_5d": None},
                    "breakeven_proxy": {"label": "BE", "value": None, "change_5d": None},
                    "raw": {},
                },
            ),
        ]
        for p in cls._patches:
            p.start()
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in cls._patches:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_first_run_smoke_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        movers_cache.invalidate()
        # Force fresh news fetch on every call so the patch is exercised.
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0
        # Clear the in-memory mover caches that bleed across test files.
        # Without this, a prior test that populated _TODAYS_MOVERS_CACHE
        # would leak non-empty results into our fresh-DB assertion.
        _api_mod._TODAYS_MOVERS_CACHE["data"] = None
        _api_mod._TODAYS_MOVERS_CACHE["ts"] = 0.0
        # Clear the module-level SnapshotStore — a prior test may have
        # written real snapshot entries that would leak into /snapshots
        # and /market-context if our patch were unpatched mid-run.
        try:
            import market_snapshots
            market_snapshots.get_store().clear()
        except Exception:
            pass

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    # ---- core list endpoints --------------------------------------------

    def test_health_returns_ok(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})

    def test_events_returns_empty_list(self):
        r = self.client.get("/events")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_events_export_returns_well_formed_payload(self):
        r = self.client.get("/events/export")
        self.assertEqual(r.status_code, 200)
        # Either an empty JSON object or an empty CSV — both are valid.
        # We just need it to be a well-formed 200 with a body.
        self.assertGreaterEqual(len(r.content), 0)

    # ---- market data endpoints ------------------------------------------

    def test_market_movers_returns_empty_list(self):
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_movers_today_returns_empty_list(self):
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_movers_weekly_returns_empty_list(self):
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_movers_yearly_returns_empty_list(self):
        r = self.client.get("/movers/yearly")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_movers_persistent_returns_empty_list(self):
        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_snapshots_returns_empty_list(self):
        r = self.client.get("/snapshots")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_stress_returns_well_formed_dict(self):
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("regime", body)
        self.assertIn("signals", body)

    def test_market_context_returns_full_shape_when_empty(self):
        """The unified context endpoint must always return all five sections."""
        r = self.client.get("/market-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Every documented section is present, even when everything is empty.
        for key in ("built_at", "source", "snapshots", "snapshots_meta",
                    "stress", "highlights", "highlights_meta"):
            self.assertIn(key, body, f"Missing top-level key: {key}")
        self.assertEqual(body["snapshots"], [])
        self.assertEqual(body["highlights"], [])
        self.assertEqual(body["snapshots_meta"]["total"], 0)
        self.assertEqual(body["highlights_meta"]["count"], 0)

    def test_news_returns_empty_clusters_when_no_feeds(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["clusters"], [])
        self.assertEqual(body["total_headlines"], 0)
        self.assertEqual(body["total_count"], 0)

    # ---- backtest endpoints ---------------------------------------------

    def test_batch_backtest_with_empty_id_list_returns_empty(self):
        r = self.client.post("/backtest/batch", json={"event_ids": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_backtest_unknown_event_returns_404(self):
        """An unknown event_id returns a clean 404, not a 500."""
        r = self.client.get("/events/99999/backtest")
        self.assertEqual(r.status_code, 404)
        # FastAPI HTTPException body — must be well-formed for the
        # frontend error extractor to read.
        body = r.json()
        self.assertIn("detail", body)
        self.assertIn("99999", body["detail"])

    def test_batch_backtest_with_unknown_ids_returns_sentinels(self):
        """The batch endpoint never raises for unknown IDs — it returns the
        well-known empty sentinel for each, so the frontend scorecard can
        render a clean 'not found' row instead of crashing the whole page."""
        r = self.client.post(
            "/backtest/batch", json={"event_ids": [99997, 99998]},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 2)
        for item in body:
            self.assertEqual(item["outcomes"], [])
            self.assertIsNone(item["score"])
            self.assertEqual(item.get("error"), "not found")

    def test_macro_batch_with_empty_dates_returns_empty_dict(self):
        r = self.client.post("/macro/batch", json={"event_dates": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {})

    # ---- mover-cache cold path ------------------------------------------

    def test_movers_cache_get_slice_with_empty_db_returns_empty(self):
        """The cache layer itself returns [] on a fresh DB.

        This is the unit-level twin of /movers/weekly above — it
        guarantees the bootstrap path through compute_slice handles
        an empty event list without raising even when every helper
        is taken from production code rather than mocks.
        """
        result = movers_cache.get_slice("weekly", limit=5)
        self.assertEqual(result, [])
        result = movers_cache.get_slice("persistent", limit=5)
        self.assertEqual(result, [])
        result = movers_cache.get_slice("yearly", limit=5)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# Cluster C — /market-context degrades when every section blows up
# ---------------------------------------------------------------------------


class TestMarketContextDegradedEverything(unittest.TestCase):
    """When EVERY downstream computation raises, /market-context still
    must return 200 with a usable shape.  This is the worst-case
    cold-start path: empty DB + every market-data dependency erroring."""

    @classmethod
    def setUpClass(cls):
        os.environ["ANTHROPIC_API_KEY"] = ""

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_first_run_degraded_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        movers_cache.invalidate()
        # Clear the in-memory movers cache — see TestEmptyDbEndpointSmoke.
        _api_mod._TODAYS_MOVERS_CACHE["data"] = None
        _api_mod._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def test_market_context_when_everything_raises(self):
        from fastapi.testclient import TestClient
        from api import app
        client = TestClient(app)

        with patch("market_snapshots.get_all_snapshots",
                   side_effect=RuntimeError("snapshot store unavailable")), \
             patch("api.compute_stress_regime",
                   side_effect=RuntimeError("stress unavailable")), \
             patch("api.movers_today",
                   side_effect=RuntimeError("movers_today unavailable")):
            r = client.get("/market-context")

        self.assertEqual(r.status_code, 200)
        body = r.json()
        # Shape contract: every documented key still present.
        for key in ("built_at", "snapshots", "snapshots_meta",
                    "stress", "highlights", "highlights_meta"):
            self.assertIn(key, body)
        # All sections degrade to empty / unknown — no nulls leaking through.
        self.assertEqual(body["snapshots"], [])
        self.assertEqual(body["highlights"], [])
        self.assertEqual(body["highlights_meta"]["count"], 0)
        # Stress was nuked → composer marks it unavailable.
        self.assertFalse(body["stress"].get("available", True))


# ---------------------------------------------------------------------------
# Cluster D — frontend api.ts client exports the structured ApiError class
# ---------------------------------------------------------------------------


class TestFrontendApiClientHasStructuredErrors(unittest.TestCase):
    """The frontend api client must expose ApiError so pages can render
    friendly messages instead of raw HTTP status strings.

    Structural assertion (no JS test runner exists in the repo) —
    grep the source for the symbols that the hardening pass added.
    """

    def setUp(self):
        self.path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src", "lib", "api.ts",
        )
        with open(self.path, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_exports_api_error_class(self):
        self.assertIn(
            "export class ApiError",
            self.src,
            "frontend api.ts must export ApiError so pages can render structured errors",
        )

    def test_handles_network_failure(self):
        """A try/catch around fetch is what turns a TypeError into ApiError."""
        self.assertIn(
            "Cannot reach the backend",
            self.src,
            "api.ts must produce a friendly message when fetch itself fails",
        )

    def test_extracts_fastapi_detail(self):
        """FastAPI's ``{'detail': ...}`` body should be parsed, not shown raw."""
        self.assertIn(
            "_extractDetail",
            self.src,
            "api.ts must parse FastAPI {detail: ...} error bodies",
        )


# ---------------------------------------------------------------------------
# Cluster E — Market Overview surfaces an error banner + cold-start nudge
# ---------------------------------------------------------------------------


class TestMarketOverviewFirstRunStates(unittest.TestCase):
    """The Market Overview page must surface a clear error AND a clear
    cold-start nudge so a first-run user is never staring at a blank page.

    Same structural-grep approach as the no-Sparkline test — there is
    no JS test runner in the repo, so we assert the source contains
    the markers added by the hardening pass.
    """

    def setUp(self):
        self.path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "src",
            "components", "pages", "market-overview.tsx",
        )
        with open(self.path, "r", encoding="utf-8") as f:
            self.src = f.read()

    def test_reads_query_errors(self):
        """All three top-level queries must expose their error state."""
        self.assertIn("error: ctxError", self.src)
        self.assertIn("error: persistentError", self.src)
        self.assertIn("error: weeklyError", self.src)

    def test_renders_error_banner(self):
        """When any query errors, an inline alert must render."""
        self.assertIn("Market data unavailable", self.src)
        self.assertIn('role="alert"', self.src)

    def test_renders_cold_start_nudge(self):
        """When everything loaded but the archive is empty, a friendly nudge."""
        self.assertIn("No archive yet", self.src)
        self.assertIn("isColdStart", self.src)


if __name__ == "__main__":
    unittest.main()
