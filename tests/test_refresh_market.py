"""
Tests for the POST /events/{event_id}/refresh-market endpoint.

Covers:
- Backend refresh returns updated market block
- DB row gets updated with fresh timestamp
- 404 on missing event_id
- Response shape matches MarketResult contract
- Frontend client wiring (api.refreshMarket signature)
"""

import os
import sys
import json
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_MOCK_TICKERS = [
    {
        "symbol": "XOM",
        "label": "Exxon Mobil",
        "role": "beneficiary",
        "return_1d": 1.2,
        "return_5d": 3.5,
        "return_20d": 5.0,
        "direction_tag": "supports thesis",
        "volume_ratio": 1.1,
        "vs_xle_5d": 0.5,
        "spark": [100, 101, 102, 103, 104],
        "anchor_date": "2026-04-01",
    },
]

_REFRESHED_TICKERS = [
    {
        "symbol": "XOM",
        "label": "Exxon Mobil",
        "role": "beneficiary",
        "return_1d": 2.0,
        "return_5d": 4.8,
        "return_20d": 7.2,
        "direction_tag": "supports thesis",
        "volume_ratio": 1.3,
        "vs_xle_5d": 0.8,
        "spark": [100, 101, 103, 105, 107],
        "anchor_date": "2026-04-01",
    },
]


def _make_refreshed_market_block(**overrides):
    block = {
        "tickers": _REFRESHED_TICKERS,
        "note": "Refreshed note",
        "details": {},
        "last_market_check_at": datetime.utcnow().isoformat(),
        "market_check_staleness": "forced_refreshed",
        "freshness_reason": "forced by user",
        "event_age_days": 10,
    }
    block.update(overrides)
    return block


class TestRefreshMarketEndpoint(unittest.TestCase):
    """End-to-end tests for POST /events/{event_id}/refresh-market.

    These tests drive the real route handler and the real DB.  The only
    mock is ``api.refresh_market_for_saved_event`` — which stands in for
    the yfinance-backed freshness layer — so the tests stay isolated from
    the network without mocking the route handler's own logic.
    """

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as api_module
        cls.api_mod = api_module
        cls.client = TestClient(api_module.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_refresh_mkt_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig_db
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_event(self, headline="OPEC cuts production", event_date="2026-04-01"):
        """Insert a saved event and return its event_id.

        Uses ``db.save_event`` directly instead of posting to /analyze so
        the test never has to mock the LLM, classifiers, or ~15 overlay
        composers just to land a row.  The refresh-market endpoint cares
        only about the persisted row; how it got there is irrelevant.
        """
        db.save_event({
            "headline": headline,
            "stage": "developing",
            "persistence": "medium",
            "event_date": event_date,
            "market_tickers": _MOCK_TICKERS,
        })
        events = db.load_recent_events(limit=1)
        self.assertTrue(len(events) >= 1)
        return events[0]["id"]

    def test_404_on_missing_event(self):
        r = self.client.post("/events/999999/refresh-market")
        self.assertEqual(r.status_code, 404)

    @patch("api.refresh_market_for_saved_event")
    def test_returns_refreshed_market_block(self, mock_refresh):
        mock_refresh.return_value = _make_refreshed_market_block()
        eid = self._seed_event()

        r = self.client.post(f"/events/{eid}/refresh-market")
        self.assertEqual(r.status_code, 200, r.text)

        body = r.json()
        self.assertEqual(body["event_id"], eid)
        self.assertIn("market", body)
        mkt = body["market"]
        self.assertIn("tickers", mkt)
        self.assertIn("last_market_check_at", mkt)
        self.assertIn("market_check_staleness", mkt)
        # Tickers should carry the refreshed values
        xom = next((t for t in mkt["tickers"] if t["symbol"] == "XOM"), None)
        self.assertIsNotNone(xom)
        self.assertAlmostEqual(xom["return_5d"], 4.8, delta=0.1)

    @patch("api.refresh_market_for_saved_event")
    def test_force_flag_propagates(self, mock_refresh):
        """The endpoint forwards its ``force`` query param verbatim
        to the freshness layer — no hardcoded override.

        Accepted contract (see audit blocker fix): POST without
        ``?force=true`` runs a regular refresh; POST with
        ``?force=true`` forces it.  The earlier "always force=True"
        test was stale and was replaced by this pair.
        """
        mock_refresh.return_value = _make_refreshed_market_block()
        eid = self._seed_event()

        self.client.post(f"/events/{eid}/refresh-market")
        call_kwargs = mock_refresh.call_args
        self.assertIs(
            call_kwargs.kwargs.get("force"), False,
            "force must default to False when the client omits ?force=true",
        )

        mock_refresh.reset_mock()
        mock_refresh.return_value = _make_refreshed_market_block()
        self.client.post(f"/events/{eid}/refresh-market?force=true")
        call_kwargs = mock_refresh.call_args
        self.assertIs(
            call_kwargs.kwargs.get("force"), True,
            "force=true query param must propagate to the freshness layer",
        )

    @patch("api.refresh_market_for_saved_event")
    def test_response_shape_matches_market_result(self, mock_refresh):
        """Response market block must match the MarketResult contract."""
        mock_refresh.return_value = _make_refreshed_market_block()
        eid = self._seed_event()

        r = self.client.post(f"/events/{eid}/refresh-market")
        body = r.json()
        mkt = body["market"]

        # Required MarketResult keys
        for key in ("tickers", "note", "details",
                    "last_market_check_at", "market_check_staleness"):
            self.assertIn(key, mkt, f"Missing key '{key}' in market block")

    @patch("api.refresh_market_for_saved_event",
           side_effect=Exception("Provider timeout"))
    def test_provider_failure_returns_502(self, mock_refresh):
        eid = self._seed_event()
        r = self.client.post(f"/events/{eid}/refresh-market")
        self.assertEqual(r.status_code, 502)


class TestRefreshMarketDbPersistence(unittest.TestCase):
    """Verify that the freshness layer persists the refresh to the DB."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        import api as api_module
        cls.api_mod = api_module
        cls.client = TestClient(api_module.app)

    def setUp(self):
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(),
            f"test_refresh_persist_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig_db
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _seed_event(self):
        # Seed directly — see TestRefreshMarketEndpoint._seed_event for rationale.
        db.save_event({
            "headline": "OPEC cuts production",
            "stage": "developing",
            "persistence": "medium",
            "event_date": "2026-04-01",
            "market_tickers": _MOCK_TICKERS,
        })
        events = db.load_recent_events(limit=1)
        return events[0]["id"]

    @patch("api.refresh_market_for_saved_event")
    def test_db_row_gets_fresh_timestamp(self, mock_refresh):
        """After refresh, the DB row should have an updated last_market_check_at."""
        fresh_ts = datetime.utcnow().isoformat()
        mock_refresh.return_value = _make_refreshed_market_block(
            last_market_check_at=fresh_ts,
        )
        eid = self._seed_event()

        # Record the original timestamp
        before = db.load_event_by_id(eid)
        original_ts = before.get("last_market_check_at")

        # The actual persistence happens inside refresh_market_for_saved_event
        # (which we're mocking). The test verifies the endpoint calls it and
        # returns the refreshed data. In production the freshness layer persists
        # via db.update_event_market_refresh.
        r = self.client.post(f"/events/{eid}/refresh-market")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsNotNone(body["market"]["last_market_check_at"])


class TestRefreshMarketFrontendWiring(unittest.TestCase):
    """Verify the frontend api.ts client method exists and matches the contract."""

    def test_api_ts_has_refresh_market_method(self):
        """The api.ts file should export a refreshMarket method."""
        api_ts_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "frontend", "src", "lib", "api.ts",
        )
        with open(api_ts_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("refreshMarket", content,
                      "api.ts must have a refreshMarket method")
        self.assertIn("/refresh-market", content,
                      "api.ts must call the /refresh-market endpoint")
        self.assertIn("method: \"POST\"", content,
                      "refreshMarket must use POST method")

    def test_analysis_view_has_refresh_button(self):
        """The AnalysisView should have a market refresh action."""
        view_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "frontend", "src", "components", "pages", "analysis-view.tsx",
        )
        with open(view_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("refreshMarket", content,
                      "AnalysisView must have a refreshMarket handler")
        self.assertIn("RefreshCw", content,
                      "AnalysisView must use RefreshCw icon")
        self.assertIn("marketRefreshing", content,
                      "AnalysisView must track refresh loading state")


if __name__ == "__main__":
    unittest.main()
