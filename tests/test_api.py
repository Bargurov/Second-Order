"""Tests for the FastAPI layer (api.py).

Uses FastAPI's TestClient so no real server is needed.
Patches LLM and market calls to avoid external dependencies.
"""

import os
import sys
import unittest
import uuid
from unittest.mock import patch

# Ensure the project root is importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import api as _api_mod  # noqa: E402 — imported after path fix
import db  # noqa: E402


def _mock_analyze(headline, stage, persistence, event_context=""):
    """Deterministic stand-in for analyze_event."""
    return {
        "what_changed": "Test policy change",
        "mechanism_summary": "Test mechanism summary for unit tests.",
        "beneficiaries": ["CompanyA"],
        "losers": ["CompanyB"],
        "beneficiary_tickers": ["AAPL"],
        "loser_tickers": ["MSFT"],
        "assets_to_watch": ["AAPL", "MSFT"],
        "confidence": "medium",
        "transmission_chain": [
            "Policy change announced",
            "Supply chain disrupted",
            "Pricing power shifts",
            "CompanyA benefits, CompanyB loses",
        ],
    }


def _mock_market(beneficiary_tickers, loser_tickers, event_date=None):
    return {
        "note": "Mock market check.",
        "details": {},
        "tickers": [
            {"symbol": "AAPL", "role": "beneficiary", "label": "flat",
             "direction_tag": None, "return_1d": 0.1, "return_5d": 0.5,
             "return_20d": 1.2, "volume_ratio": 1.0, "vs_xle_5d": None},
        ],
    }


_PATCHES = [
    patch("api.analyze_event", side_effect=_mock_analyze),
    patch("api.market_check", side_effect=_mock_market),
    patch("api.fetch_all", return_value=(
        [
            {"source": "BBC World", "title": "Test headline A", "published_at": "2025-01-01T00:00:00", "url": ""},
            {"source": "Reuters", "title": "Test headline B", "published_at": "2025-01-01T00:00:00", "url": ""},
        ],
        [
            {"name": "BBC World", "url": "https://example.com/bbc", "ok": True, "count": 1, "error": None},
            {"name": "Reuters", "url": "https://example.com/reuters", "ok": True, "count": 1, "error": None},
        ],
    )),
    patch("api.cluster_headlines", return_value=[
        {"headline": "Test headline A", "sources": [{"name": "BBC World"}], "source_count": 1},
    ]),
]


class APITestCase(unittest.TestCase):
    """Base that swaps DB_FILE to a temp file and patches external calls."""

    @classmethod
    def setUpClass(cls):
        for p in _PATCHES:
            p.start()
        # Import after patches are in place so the module sees them.
        from fastapi.testclient import TestClient
        from api import app
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        for p in _PATCHES:
            p.stop()

    def setUp(self):
        self._orig = db.DB_FILE
        self._tmp = os.path.join(
            os.path.dirname(__file__),
            f"test_api_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self._tmp
        db.init_db()
        # Clear the /news TTL cache so each test gets a fresh call.
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except (OSError, PermissionError):
            pass


class TestHealth(APITestCase):
    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class TestAnalyze(APITestCase):
    def test_analyze_returns_all_fields(self):
        r = self.client.post("/analyze", json={"headline": "US imposes new tariffs on steel"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("headline", "stage", "persistence", "analysis", "market", "is_mock"):
            self.assertIn(key, body)
        self.assertFalse(body["is_mock"])

    def test_analyze_empty_headline_rejected(self):
        r = self.client.post("/analyze", json={"headline": ""})
        self.assertEqual(r.status_code, 422)

    def test_analyze_with_event_date(self):
        r = self.client.post("/analyze", json={
            "headline": "OPEC cuts production targets",
            "event_date": "2025-03-01",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["event_date"], "2025-03-01")

    def test_analyze_without_event_date_gets_today(self):
        """When no event_date is provided, today's date should be used."""
        r = self.client.post("/analyze", json={"headline": "US imposes tariffs on steel"})
        self.assertEqual(r.status_code, 200)
        event_date = r.json()["event_date"]
        self.assertIsNotNone(event_date)
        self.assertRegex(event_date, r"^\d{4}-\d{2}-\d{2}$")

    def test_analyze_saves_event_with_date(self):
        """Saved event should always have an event_date."""
        self.client.post("/analyze", json={"headline": "OPEC cuts output again"})
        events = db.load_recent_events(1)
        self.assertEqual(len(events), 1)
        self.assertIsNotNone(events[0]["event_date"])

    def test_analyze_cache_hit_returns_same_shape(self):
        """Repeated analysis of the same headline returns a cached result with the same fields."""
        headline = "Cache test: EU restricts chip exports to China"
        r1 = self.client.post("/analyze", json={"headline": headline})
        r2 = self.client.post("/analyze", json={"headline": headline})
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        b1, b2 = r1.json(), r2.json()
        # Same response shape
        for key in ("headline", "stage", "persistence", "analysis", "market", "is_mock", "event_date"):
            self.assertIn(key, b2, f"Missing key in cached response: {key}")
        # Same content
        self.assertEqual(b1["headline"], b2["headline"])
        self.assertEqual(b1["stage"], b2["stage"])
        self.assertEqual(b1["analysis"]["what_changed"], b2["analysis"]["what_changed"])

    def test_analyze_cache_miss_for_different_headline(self):
        """Different headlines should not share a cache entry."""
        self.client.post("/analyze", json={"headline": "Cache miss test A: tariffs on steel"})
        r2 = self.client.post("/analyze", json={"headline": "Cache miss test B: OPEC cuts output"})
        self.assertEqual(r2.status_code, 200)
        self.assertNotEqual(r2.json()["headline"], "Cache miss test A: tariffs on steel")

    def test_analyze_cached_has_tickers_in_analysis(self):
        """Cached response should include beneficiary_tickers and loser_tickers."""
        headline = "Cache ticker test: sanctions on Russian oil"
        self.client.post("/analyze", json={"headline": headline})
        r2 = self.client.post("/analyze", json={"headline": headline})
        body = r2.json()
        self.assertIn("beneficiary_tickers", body["analysis"])
        self.assertIn("loser_tickers", body["analysis"])
        self.assertIsInstance(body["analysis"]["beneficiary_tickers"], list)

    def test_analyze_cached_market_has_tickers(self):
        """Cached response market field should include tickers list."""
        headline = "Cache market test: Fed signals rate cut"
        self.client.post("/analyze", json={"headline": headline})
        r2 = self.client.post("/analyze", json={"headline": headline})
        body = r2.json()
        self.assertIn("tickers", body["market"])
        self.assertIsInstance(body["market"]["tickers"], list)


    def test_analyze_cache_miss_for_different_event_date(self):
        """Same headline with different event_date should not share cache."""
        headline = "Date cache test: OPEC extends cuts"
        r1 = self.client.post("/analyze", json={
            "headline": headline, "event_date": "2025-01-15",
        })
        r2 = self.client.post("/analyze", json={
            "headline": headline, "event_date": "2025-06-01",
        })
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        # Both should have their own event_date, not reuse the first
        self.assertEqual(r1.json()["event_date"], "2025-01-15")
        self.assertEqual(r2.json()["event_date"], "2025-06-01")


class TestCachedAnalysisTTL(APITestCase):
    """Tests for find_cached_analysis TTL behavior."""

    def test_fresh_cache_hit(self):
        """A recently saved event should be returned as a cache hit."""
        headline = "TTL fresh test: EU tariff update"
        self.client.post("/analyze", json={"headline": headline})
        cached = db.find_cached_analysis(headline, event_date=None, max_age_seconds=86400)
        # find_cached_analysis matches on event_date; the /analyze endpoint
        # auto-sets event_date to today, so pass that explicitly.
        import datetime as _dt
        today = _dt.datetime.now().strftime("%Y-%m-%d")
        cached = db.find_cached_analysis(headline, event_date=today, max_age_seconds=86400)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["headline"], headline)

    def test_stale_cache_miss(self):
        """An old event should be treated as a cache miss."""
        headline = "TTL stale test: OPEC production cut"
        self.client.post("/analyze", json={"headline": headline})
        import datetime as _dt
        today = _dt.datetime.now().strftime("%Y-%m-%d")
        # Backdate the saved event's timestamp so it looks old
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET timestamp = '2020-01-01T00:00:00' WHERE headline = ?",
                (headline,),
            )
        cached = db.find_cached_analysis(headline, event_date=today, max_age_seconds=86400)
        self.assertIsNone(cached)


class TestLoadEventById(APITestCase):
    def test_load_event_by_id_returns_event(self):
        db.save_event({
            "headline": "Direct lookup test",
            "stage": "realized",
            "persistence": "structural",
        })
        events = db.load_recent_events(1)
        eid = events[0]["id"]
        result = db.load_event_by_id(eid)
        self.assertIsNotNone(result)
        self.assertEqual(result["headline"], "Direct lookup test")

    def test_load_event_by_id_returns_none_for_missing(self):
        self.assertIsNone(db.load_event_by_id(99999))

    def test_backtest_finds_old_event(self):
        """Backtest should find events beyond the most recent 100."""
        # Save one event and get its ID
        db.save_event({
            "headline": "Old event for backtest",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-01-01",
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary"}],
        })
        eid = db.load_recent_events(1)[0]["id"]
        # The endpoint should find it regardless of position
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["event_id"], eid)

    def test_related_finds_old_event(self):
        db.save_event({
            "headline": "Old event for related lookup",
            "stage": "realized",
            "persistence": "structural",
        })
        eid = db.load_recent_events(1)[0]["id"]
        r = self.client.get(f"/events/{eid}/related")
        self.assertEqual(r.status_code, 200)


    def test_analyze_returns_transmission_chain(self):
        r = self.client.post("/analyze", json={"headline": "Chain test: EU tariff update"})
        self.assertEqual(r.status_code, 200)
        chain = r.json()["analysis"].get("transmission_chain")
        self.assertIsInstance(chain, list)
        self.assertEqual(len(chain), 4)

    def test_analyze_chain_in_cached_response(self):
        headline = "Chain cache test: OPEC output"
        self.client.post("/analyze", json={"headline": headline})
        r2 = self.client.post("/analyze", json={"headline": headline})
        # Cached response should also include the chain (it's part of the analysis dict)
        chain = r2.json()["analysis"].get("transmission_chain")
        self.assertIsInstance(chain, list)

class TestAnalyzeStream(APITestCase):
    """Tests for the progressive SSE endpoint POST /analyze/stream."""

    def _parse_sse(self, text: str) -> list[dict]:
        """Parse SSE text into a list of event dicts."""
        import json
        events = []
        for line in text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def test_stream_emits_phases_in_order(self):
        headline = "Stream test: EU imposes new steel tariffs"
        r = self.client.post("/analyze/stream", json={"headline": headline})
        self.assertEqual(r.status_code, 200)
        events = self._parse_sse(r.text)
        phases = [e["_phase"] for e in events]
        self.assertEqual(phases, ["classify", "analysis", "complete"])

    def test_stream_classify_has_stage_and_persistence(self):
        headline = "Stream classify: OPEC cuts output"
        r = self.client.post("/analyze/stream", json={"headline": headline})
        events = self._parse_sse(r.text)
        classify_ev = next(e for e in events if e["_phase"] == "classify")
        self.assertIn("stage", classify_ev)
        self.assertIn("persistence", classify_ev)

    def test_stream_complete_has_full_shape(self):
        headline = "Stream complete: Federal Reserve holds rates"
        r = self.client.post("/analyze/stream", json={"headline": headline})
        events = self._parse_sse(r.text)
        complete_ev = next(e for e in events if e["_phase"] == "complete")
        for key in ("headline", "stage", "persistence", "analysis", "market", "is_mock", "event_date"):
            self.assertIn(key, complete_ev, f"Missing key in complete event: {key}")

    def test_stream_cached_returns_single_complete(self):
        """A cached headline should emit only a single 'complete' event."""
        headline = "Stream cache: sanctions on Russian banks"
        self.client.post("/analyze/stream", json={"headline": headline})
        r = self.client.post("/analyze/stream", json={"headline": headline})
        events = self._parse_sse(r.text)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["_phase"], "complete")

    def test_stream_complete_has_chain(self):
        headline = "Stream chain test: OPEC cuts output sharply"
        r = self.client.post("/analyze/stream", json={"headline": headline})
        events = self._parse_sse(r.text)
        complete = next(e for e in events if e["_phase"] == "complete")
        chain = complete.get("analysis", {}).get("transmission_chain")
        self.assertIsInstance(chain, list)
        self.assertGreater(len(chain), 0)


class TestEvents(APITestCase):
    def test_events_empty(self):
        r = self.client.get("/events")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_events_after_save(self):
        db.save_event({
            "headline": "Saved event",
            "stage": "realized",
            "persistence": "structural",
        })
        r = self.client.get("/events?limit=5")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["headline"], "Saved event")


class TestReview(APITestCase):
    def _seed(self):
        db.save_event({
            "headline": "Review target",
            "stage": "realized",
            "persistence": "structural",
        })
        return db.load_recent_events(1)[0]["id"]

    def test_patch_rating(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={"rating": "good"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["ok"])

    def test_patch_notes(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={"notes": "Looks strong"})
        self.assertEqual(r.status_code, 200)

    def test_patch_empty_body_rejected(self):
        eid = self._seed()
        r = self.client.patch(f"/events/{eid}/review", json={})
        self.assertEqual(r.status_code, 400)

    def test_patch_nonexistent_event(self):
        r = self.client.patch("/events/99999/review", json={"rating": "poor"})
        self.assertEqual(r.status_code, 404)


class TestBacktest(APITestCase):
    def _seed_with_date(self):
        db.save_event({
            "headline": "Backtest target",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "AAPL", "role": "beneficiary"},
                {"symbol": "MSFT", "role": "loser"},
            ],
        })
        return db.load_recent_events(1)[0]["id"]

    def _seed_without_date(self):
        db.save_event({
            "headline": "No date event",
            "stage": "realized",
            "persistence": "medium",
        })
        return db.load_recent_events(1)[0]["id"]

    @patch("api.followup_check", return_value=[
        {"symbol": "AAPL", "role": "beneficiary", "return_1d": 1.0,
         "return_5d": 2.5, "return_20d": 4.0, "direction": "supports \u2191",
         "anchor_date": "2025-03-03"},
        {"symbol": "MSFT", "role": "loser", "return_1d": -0.5,
         "return_5d": -1.2, "return_20d": -3.0, "direction": "supports \u2193",
         "anchor_date": "2025-03-03"},
    ])
    def test_backtest_returns_outcomes(self, _mock_fc):
        eid = self._seed_with_date()
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["event_id"], eid)
        self.assertEqual(len(body["outcomes"]), 2)

    @patch("api.followup_check", return_value=[
        {"symbol": "AAPL", "role": "beneficiary", "return_1d": 1.0,
         "return_5d": 2.5, "return_20d": 4.0, "direction": "supports \u2191",
         "anchor_date": "2025-03-03"},
        {"symbol": "MSFT", "role": "loser", "return_1d": -0.5,
         "return_5d": -1.2, "return_20d": -3.0, "direction": "supports \u2193",
         "anchor_date": "2025-03-03"},
    ])
    def test_backtest_score(self, _mock_fc):
        eid = self._seed_with_date()
        r = self.client.get(f"/events/{eid}/backtest")
        body = r.json()
        self.assertIsNotNone(body["score"])
        self.assertEqual(body["score"]["supporting"], 2)
        self.assertEqual(body["score"]["total"], 2)

    def test_backtest_no_date_returns_empty(self):
        eid = self._seed_without_date()
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["outcomes"], [])
        self.assertIsNone(body["score"])

    @patch("api.followup_check", return_value=[
        {"symbol": "AAPL", "role": "beneficiary", "return_1d": 0.5,
         "return_5d": 1.0, "return_20d": 2.0, "direction": "supports \u2191",
         "anchor_date": "2025-04-01"},
    ])
    def test_backtest_falls_back_to_timestamp(self, _mock_fc):
        """Events without event_date should use timestamp as fallback."""
        db.save_event({
            "headline": "Timestamp fallback",
            "stage": "realized",
            "persistence": "structural",
            "timestamp": "2025-04-01T10:30:00",
            "market_tickers": [{"symbol": "AAPL", "role": "beneficiary"}],
            # No event_date
        })
        eid = db.load_recent_events(1)[0]["id"]
        r = self.client.get(f"/events/{eid}/backtest")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body["outcomes"]), 1)
        # followup_check should have been called (not skipped)
        _mock_fc.assert_called_once()

    def test_backtest_nonexistent_event(self):
        r = self.client.get("/events/99999/backtest")
        self.assertEqual(r.status_code, 404)


class TestBatchBacktest(APITestCase):
    def _seed(self, headline, event_date="2025-03-01"):
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": event_date,
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary"}],
        })
        return db.load_recent_events(1)[0]["id"]

    def test_batch_returns_results_in_input_order(self):
        id1 = self._seed("Batch order A")
        id2 = self._seed("Batch order B")
        r = self.client.post("/backtest/batch", json={"event_ids": [id2, id1]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["event_id"], id2)
        self.assertEqual(body[1]["event_id"], id1)

    def test_batch_partial_failure(self):
        eid = self._seed("Batch partial")
        r = self.client.post("/backtest/batch", json={"event_ids": [eid, 99999]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 2)
        # First event should have real result
        self.assertEqual(body[0]["event_id"], eid)
        # Second event: not found → empty outcomes
        self.assertEqual(body[1]["event_id"], 99999)
        self.assertEqual(body[1]["outcomes"], [])

    def test_batch_empty_list(self):
        r = self.client.post("/backtest/batch", json={"event_ids": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


class TestSinceEventLive(APITestCase):
    """Tests for the live since-event return flow (batch backtest on market movers)."""

    def _seed_mover(self, headline="Live update mover", return_5d=5.0):
        """Seed an event that qualifies as a market mover (abs(return_5d) >= 3%)."""
        db.save_event({
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "label": "notable move",
                 "direction_tag": "supports \u2191", "return_1d": 1.0,
                 "return_5d": return_5d, "return_20d": 8.0,
                 "volume_ratio": 1.5, "vs_xle_5d": None, "spark": [0.2, 0.4, 0.6, 0.8, 1.0]},
            ],
        })
        return db.load_recent_events(1)[0]["id"]

    @patch("api.followup_check", return_value=[
        {"symbol": "GLD", "role": "beneficiary", "return_1d": 0.8,
         "return_5d": 3.2, "return_20d": 7.5, "direction": "supports \u2191",
         "anchor_date": "2025-03-03"},
    ])
    def test_since_event_return_via_batch_backtest(self, _mock_fc):
        """Batch backtest on a mover event returns fresh since-event returns."""
        eid = self._seed_mover()
        r = self.client.post("/backtest/batch", json={"event_ids": [eid]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["event_id"], eid)
        outcomes = body[0]["outcomes"]
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0]["symbol"], "GLD")
        self.assertAlmostEqual(outcomes[0]["return_5d"], 3.2)
        self.assertAlmostEqual(outcomes[0]["return_20d"], 7.5)
        self.assertIn("supports", outcomes[0]["direction"])

    @patch("api.followup_check", return_value=[
        {"symbol": "GLD", "role": "beneficiary", "return_1d": 0.8,
         "return_5d": 3.2, "return_20d": 7.5, "direction": "supports \u2191",
         "anchor_date": "2025-03-03"},
    ])
    def test_qualifying_mover_with_live_update(self, _mock_fc):
        """Full flow: event qualifies as mover, then batch backtest returns live data."""
        eid = self._seed_mover()
        # Step 1: confirm it appears in market movers
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        movers = r.json()
        self.assertTrue(any(m["event_id"] == eid for m in movers))
        # Step 2: batch backtest with the mover's event ID
        r2 = self.client.post("/backtest/batch", json={"event_ids": [eid]})
        self.assertEqual(r2.status_code, 200)
        outcomes = r2.json()[0]["outcomes"]
        self.assertEqual(outcomes[0]["symbol"], "GLD")
        self.assertIsNotNone(outcomes[0]["return_20d"])

    def test_missing_data_fallback(self):
        """Mover event with no event_date falls back to timestamp; returns null returns gracefully."""
        db.save_event({
            "headline": "No date mover for live test",
            "stage": "realized",
            "persistence": "structural",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "label": "notable move",
                 "direction_tag": "supports \u2191", "return_1d": 1.0,
                 "return_5d": 5.0, "return_20d": 8.0,
                 "volume_ratio": 1.5, "vs_xle_5d": None},
            ],
            # No event_date — falls back to auto-generated timestamp
        })
        eid = db.load_recent_events(1)[0]["id"]
        r = self.client.post("/backtest/batch", json={"event_ids": [eid]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body[0]["event_id"], eid)
        # Should return outcomes (timestamp fallback), not crash
        outcomes = body[0]["outcomes"]
        self.assertIsInstance(outcomes, list)
        # With no real price data, returns are null
        for o in outcomes:
            self.assertIn("symbol", o)
            self.assertIn("return_5d", o)

    def test_missing_event_id_fallback(self):
        """Non-existent event ID in batch returns empty outcomes, not a crash."""
        r = self.client.post("/backtest/batch", json={"event_ids": [99999]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body[0]["event_id"], 99999)
        self.assertEqual(body[0]["outcomes"], [])
        self.assertIsNone(body[0]["score"])


class TestBatchMacro(APITestCase):
    def test_batch_returns_dict_keyed_by_date(self):
        r = self.client.post("/macro/batch", json={"event_dates": ["2025-03-15"]})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("2025-03-15", body)
        self.assertIsInstance(body["2025-03-15"], list)

    def test_batch_deduplicates_dates(self):
        r = self.client.post("/macro/batch", json={
            "event_dates": ["2025-03-15", "2025-03-15", "2025-04-01"],
        })
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 2)  # deduplicated

    def test_batch_empty_dates(self):
        r = self.client.post("/macro/batch", json={"event_dates": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {})


class TestStressEndpoint(APITestCase):
    def test_stress_returns_regime(self):
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("regime", body)
        self.assertIn("signals", body)
        self.assertIn("raw", body)

    def test_stress_regime_is_string(self):
        r = self.client.get("/stress")
        self.assertIsInstance(r.json()["regime"], str)

    def test_stress_signals_are_booleans(self):
        r = self.client.get("/stress")
        for v in r.json()["signals"].values():
            self.assertIsInstance(v, bool)

    def test_stress_response_shape_stable(self):
        """Response always has regime (str), signals (dict of bool), raw (dict of numbers)."""
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body["regime"], str)
        self.assertIsInstance(body["signals"], dict)
        self.assertIsInstance(body["raw"], dict)
        for k in ("vix_elevated", "term_inversion", "credit_widening",
                   "safe_haven_bid", "breadth_deterioration"):
            self.assertIn(k, body["signals"])
        for v in body["raw"].values():
            self.assertIsInstance(v, (int, float))


class TestStressVixChange(APITestCase):
    """Tests for the VIX 5d percent-change field in /stress raw data."""

    @patch("api.compute_stress_regime", return_value={
        "regime": "Calm",
        "signals": {
            "vix_elevated": False, "term_inversion": False,
            "credit_widening": False, "safe_haven_bid": False,
            "breadth_deterioration": False,
        },
        "raw": {"vix": 18.5, "vix_avg20": 17.0, "vix_change_5d": -3.42},
    })
    def test_vix_change_present(self, _mock):
        """When VIX data is available, raw includes vix_change_5d."""
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        raw = r.json()["raw"]
        self.assertIn("vix_change_5d", raw)
        self.assertAlmostEqual(raw["vix_change_5d"], -3.42)

    @patch("api.compute_stress_regime", return_value={
        "regime": "Calm",
        "signals": {
            "vix_elevated": False, "term_inversion": False,
            "credit_widening": False, "safe_haven_bid": False,
            "breadth_deterioration": False,
        },
        "raw": {"vix": 18.5, "vix_avg20": 17.0},
    })
    def test_vix_change_missing_fallback(self, _mock):
        """When VIX 5d data is insufficient, vix_change_5d is absent from raw."""
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        raw = r.json()["raw"]
        self.assertNotIn("vix_change_5d", raw)
        # vix spot should still be present
        self.assertIn("vix", raw)


class TestMarketMovers(APITestCase):
    def test_returns_list(self):
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_returns_empty_when_no_events(self):
        r = self.client.get("/market-movers")
        self.assertEqual(r.json(), [])

    def test_qualifies_event_with_big_saved_move(self):
        """Event with a saved ticker return_5d > 3% should appear."""
        db.save_event({
            "headline": "Mover test headline",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 5.0,
                 "direction_tag": "supports \u2191", "spark": [0.1, 0.5, 0.9]},
            ],
        })
        r = self.client.get("/market-movers")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["headline"], "Mover test headline")
        self.assertGreater(body[0]["impact"], 0)
        self.assertEqual(len(body[0]["tickers"]), 1)
        self.assertEqual(body[0]["tickers"][0]["symbol"], "GLD")
        # Verify decay fields are present
        self.assertIn("decay", body[0]["tickers"][0])
        self.assertIn("decay_evidence", body[0]["tickers"][0])

    def test_mover_decay_with_both_returns(self):
        """When both 5d and 20d are present, decay should be classified."""
        db.save_event({
            "headline": "Decay test event",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "XLE", "role": "beneficiary", "return_5d": 5.0,
                 "return_20d": 6.0, "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        ticker = r.json()[0]["tickers"][0]
        self.assertEqual(ticker["decay"], "Accelerating")
        self.assertIn("5d", ticker["decay_evidence"])

    def test_excludes_small_saved_moves(self):
        """Event where all tickers have abs(return_5d) < 3% is excluded."""
        db.save_event({
            "headline": "Small mover",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 1.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        self.assertEqual(r.json(), [])

    def test_sorted_by_impact_descending(self):
        db.save_event({
            "headline": "Small impact event",
            "stage": "realized", "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "AA", "role": "beneficiary", "return_5d": 4.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        db.save_event({
            "headline": "Big impact event",
            "stage": "realized", "persistence": "structural",
            "event_date": "2025-03-02",
            "market_tickers": [
                {"symbol": "BB", "role": "beneficiary", "return_5d": 10.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["headline"], "Big impact event")

    def test_excludes_events_with_no_tickers(self):
        db.save_event({
            "headline": "No tickers event",
            "stage": "realized", "persistence": "medium",
            "event_date": "2025-03-01",
        })
        r = self.client.get("/market-movers")
        self.assertEqual(r.json(), [])

    def test_excludes_tickers_with_none_return(self):
        """Tickers where return_5d is None should not qualify."""
        db.save_event({
            "headline": "None return event",
            "stage": "realized", "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "X", "role": "beneficiary", "return_5d": None},
            ],
        })
        r = self.client.get("/market-movers")
        self.assertEqual(r.json(), [])


class TestTickerEndpoints(APITestCase):
    def test_ticker_chart_returns_list(self):
        r = self.client.get("/ticker/GLD/chart?event_date=2025-03-15")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_ticker_chart_rejects_bad_date(self):
        r = self.client.get("/ticker/GLD/chart?event_date=bad")
        self.assertEqual(r.status_code, 422)

    def test_ticker_info_returns_dict(self):
        r = self.client.get("/ticker/GLD/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("symbol", body)
        self.assertEqual(body["symbol"], "GLD")

    def test_ticker_info_has_required_keys(self):
        r = self.client.get("/ticker/AAPL/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for key in ("symbol", "name", "sector", "industry", "market_cap", "avg_volume"):
            self.assertIn(key, body)


    def test_ticker_headlines_returns_list(self):
        r = self.client.get("/ticker/GLD/headlines")
        self.assertEqual(r.status_code, 200)
        self.assertIsInstance(r.json(), list)

    def test_ticker_headlines_entries_have_required_keys(self):
        r = self.client.get("/ticker/GLD/headlines")
        self.assertEqual(r.status_code, 200)
        for entry in r.json():
            self.assertIn("headline", entry)
            self.assertIn("source_count", entry)
            self.assertIn("published_at", entry)

    def test_ticker_info_missing_symbol_returns_nulls(self):
        """Unknown ticker should return dict with null fields, not crash."""
        r = self.client.get("/ticker/ZZZZZZZ99/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["symbol"], "ZZZZZZZ99")
        # Fields may be null but the shape is stable
        for key in ("name", "sector", "industry"):
            self.assertIn(key, body)

    def test_ticker_chart_empty_for_bad_symbol(self):
        """Unknown ticker should return empty list, not 500."""
        r = self.client.get("/ticker/ZZZZZZZ99/chart?event_date=2025-03-15")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_ticker_headlines_nonempty_for_mentioned_ticker(self):
        """Headlines endpoint returns results when ticker appears in cached news."""
        import time
        _api_mod._news_cache["data"] = {
            "clusters": [
                {"headline": "GLD surges as gold demand rises", "source_count": 2, "published_at": "2025-03-15T10:00:00"},
                {"headline": "Unrelated headline about weather", "source_count": 1, "published_at": "2025-03-15T09:00:00"},
            ],
            "total_headlines": 2,
        }
        _api_mod._news_cache["ts"] = time.monotonic()

        r = self.client.get("/ticker/GLD/headlines")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertGreaterEqual(len(body), 1)
        self.assertIn("GLD", body[0]["headline"].upper())

    def test_ticker_headlines_empty_for_unmentioned_ticker(self):
        """Headlines endpoint returns empty list when ticker is absent from news."""
        import time
        _api_mod._news_cache["data"] = {
            "clusters": [
                {"headline": "Unrelated headline about weather", "source_count": 1, "published_at": "2025-03-15T09:00:00"},
            ],
            "total_headlines": 1,
        }
        _api_mod._news_cache["ts"] = time.monotonic()

        r = self.client.get("/ticker/ZZZZZZZ99/headlines")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_ticker_info_fallback_all_fields_null(self):
        """Unknown ticker should return null for all optional fields."""
        r = self.client.get("/ticker/ZZZZZZZ99/info")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["symbol"], "ZZZZZZZ99")
        for key in ("name", "sector", "industry", "market_cap", "avg_volume"):
            self.assertIn(key, body)
            self.assertIsNone(body[key], f"{key} should be null for unknown ticker")


class TestMacroValidation(APITestCase):
    def test_macro_rejects_malformed_date(self):
        r = self.client.get("/macro?event_date=not-a-date")
        self.assertEqual(r.status_code, 422)

    def test_macro_rejects_partial_date(self):
        r = self.client.get("/macro?event_date=2025-03")
        self.assertEqual(r.status_code, 422)

    def test_macro_accepts_valid_date(self):
        r = self.client.get("/macro?event_date=2025-03-15")
        self.assertEqual(r.status_code, 200)

    def test_macro_accepts_no_date(self):
        r = self.client.get("/macro")
        self.assertEqual(r.status_code, 200)


class TestNews(APITestCase):
    def test_news_returns_clusters(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("clusters", body)
        self.assertIn("total_headlines", body)
        self.assertEqual(body["total_headlines"], 2)

    def test_news_returns_feed_status(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("feed_status", body)
        self.assertIsInstance(body["feed_status"], list)
        self.assertTrue(len(body["feed_status"]) > 0)

    def test_news_cluster_shape(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        cluster = r.json()["clusters"][0]
        self.assertIn("headline", cluster)
        self.assertIn("sources", cluster)
        self.assertIn("source_count", cluster)

    def test_news_does_not_500(self):
        """Regression: fetch_all returns (records, feed_status) tuple."""
        r = self.client.get("/news")
        self.assertNotEqual(r.status_code, 500)
        self.assertEqual(r.status_code, 200)

    def test_news_cache_returns_same_data(self):
        """Second call within TTL should return cached data."""
        r1 = self.client.get("/news")
        r2 = self.client.get("/news")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json(), r2.json())

    def test_news_cache_expires(self):
        """After expiry the cache should refresh."""
        r1 = self.client.get("/news")
        self.assertEqual(r1.status_code, 200)
        # Force expiry by backdating the timestamp.
        _api_mod._news_cache["ts"] = 0.0
        r2 = self.client.get("/news")
        self.assertEqual(r2.status_code, 200)
        # Both should still return valid data.
        self.assertIn("clusters", r2.json())

    def test_news_persists_to_sqlite(self):
        """First /news call should write to the SQLite news_cache table."""
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        # Check the DB directly
        cached = db.load_news_cache(max_age_seconds=60)
        self.assertIsNotNone(cached)
        self.assertIn("clusters", cached)

    def test_news_sqlite_survives_memory_clear(self):
        """Clearing in-memory cache should fall back to SQLite."""
        r1 = self.client.get("/news")
        self.assertEqual(r1.status_code, 200)
        # Clear only in-memory cache, leave SQLite intact
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0
        r2 = self.client.get("/news")
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r1.json(), r2.json())

    def test_news_stale_sqlite_triggers_fresh_fetch(self):
        """Stale SQLite cache should trigger a fresh fetch."""
        r1 = self.client.get("/news")
        self.assertEqual(r1.status_code, 200)
        # Expire both caches
        _api_mod._news_cache["data"] = None
        _api_mod._news_cache["ts"] = 0.0
        # Backdate the SQLite row
        import sqlite3
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE news_cache SET fetched_at = '2000-01-01T00:00:00' WHERE id = 1"
            )
        r2 = self.client.get("/news")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("clusters", r2.json())

    def test_news_refresh_bypasses_cache(self):
        """POST /news/refresh should always fetch fresh data."""
        r1 = self.client.get("/news")
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post("/news/refresh")
        self.assertEqual(r2.status_code, 200)
        self.assertIn("clusters", r2.json())

    def test_news_refresh_updates_sqlite(self):
        """POST /news/refresh should update the persistent cache."""
        self.client.post("/news/refresh")
        cached = db.load_news_cache(max_age_seconds=60)
        self.assertIsNotNone(cached)
        self.assertIn("clusters", cached)


if __name__ == "__main__":
    unittest.main()
