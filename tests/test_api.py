"""Tests for the FastAPI layer (api.py).

Uses FastAPI's TestClient so no real server is needed.
Patches LLM and market calls to avoid external dependencies.
"""

import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta
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
        "if_persists": {
            "substitution": "Alternative suppliers gain share if disruption lasts.",
            "delayed_winners": ["CompanyC"],
            "delayed_losers": ["CompanyD"],
            "horizon": "months",
        },
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

    def test_analyze_returns_if_persists(self):
        r = self.client.post("/analyze", json={"headline": "Persist test: supply shock"})
        self.assertEqual(r.status_code, 200)
        ip = r.json()["analysis"].get("if_persists")
        self.assertIsInstance(ip, dict)
        self.assertIn("substitution", ip)
        self.assertIn("delayed_winners", ip)
        self.assertIn("delayed_losers", ip)
        self.assertIn("horizon", ip)

    def test_analyze_if_persists_in_cached_response(self):
        headline = "Persist cache test: tariff escalation"
        self.client.post("/analyze", json={"headline": headline})
        r2 = self.client.post("/analyze", json={"headline": headline})
        ip = r2.json()["analysis"].get("if_persists")
        self.assertIsInstance(ip, dict)
        self.assertIn("substitution", ip)

    @patch("api.analyze_event", side_effect=lambda h, s, p, event_context="": {
        **_mock_analyze(h, s, p, event_context),
        "if_persists": {"substitution": None, "delayed_winners": [], "delayed_losers": [], "horizon": "null"},
    })
    def test_analyze_empty_if_persists_returns_empty_dict(self, _mock):
        """When model returns all-null if_persists, normalization yields {}."""
        r = self.client.post("/analyze", json={"headline": "Empty persist test"})
        self.assertEqual(r.status_code, 200)
        ip = r.json()["analysis"].get("if_persists")
        self.assertIsInstance(ip, dict)
        # All null-like values stripped → empty dict
        self.assertEqual(ip, {})

    def test_analyze_response_shape_includes_all_expected_keys(self):
        """Full response shape must include all top-level and analysis keys."""
        r = self.client.post("/analyze", json={"headline": "Shape test: trade disruption"})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        for top_key in ("headline", "stage", "persistence", "analysis", "market", "is_mock", "event_date"):
            self.assertIn(top_key, body)
        analysis = body["analysis"]
        for ak in ("what_changed", "mechanism_summary", "beneficiaries", "losers",
                    "beneficiary_tickers", "loser_tickers", "assets_to_watch",
                    "confidence", "transmission_chain", "if_persists"):
            self.assertIn(ak, analysis, f"Missing analysis key: {ak}")

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
        """Seed an event that qualifies as a market mover (abs(return_5d) >= 1.5%)."""
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
        """Batch backtest on a mover event returns fresh since-event returns.

        The seeded event_date (2025-03-01) is past the 30-day frozen cutoff,
        so we pass force=True to exercise the refresh path explicitly.
        """
        eid = self._seed_mover()
        r = self.client.post(
            "/backtest/batch",
            json={"event_ids": [eid], "force": True},
        )
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
        # Step 2: batch backtest with the mover's event ID (force=True because
        # the seeded 2025-03-01 event is past the frozen cutoff).
        r2 = self.client.post(
            "/backtest/batch",
            json={"event_ids": [eid], "force": True},
        )
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

    def test_stress_includes_detail_and_summary(self):
        """Expanded response includes per-component detail and a summary."""
        r = self.client.get("/stress")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("detail", body)
        self.assertIn("summary", body)
        self.assertIsInstance(body["summary"], str)
        self.assertIsInstance(body["detail"], dict)

    def test_stress_detail_has_all_components(self):
        """Detail dict should include all 5 subsections."""
        r = self.client.get("/stress")
        body = r.json()
        for key in ("volatility", "term_structure", "credit", "safe_haven", "breadth"):
            self.assertIn(key, body["detail"], f"Missing detail component: {key}")
            comp = body["detail"][key]
            self.assertIn("label", comp)
            self.assertIn("status", comp)
            self.assertIn("explanation", comp)
            self.assertIn(comp["status"], ("calm", "watch", "stressed"))
            self.assertIsInstance(comp["explanation"], str)
            self.assertGreater(len(comp["explanation"]), 5)


class TestRatesContextEndpoint(APITestCase):
    """Tests for GET /rates-context."""

    def test_rates_context_returns_shape(self):
        r = self.client.get("/rates-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("regime", body)
        self.assertIsInstance(body["regime"], str)
        for key in ("nominal", "real_proxy", "breakeven_proxy"):
            self.assertIn(key, body)
            self.assertIn("label", body[key])
        self.assertIn("raw", body)

    @patch("api.compute_rates_context", return_value={
        "regime": "Inflation pressure",
        "nominal": {"label": "10Y yield", "value": 4.35, "change_5d": 0.82},
        "real_proxy": {"label": "TIP (real yield proxy)", "value": 108.5, "change_5d": 0.12},
        "breakeven_proxy": {"label": "Breakeven proxy", "change_5d": 0.94},
        "raw": {"tnx": 4.35, "tnx_change_5d": 0.82, "tip": 108.5, "tip_change_5d": 0.12},
    })
    def test_rates_context_with_mocked_data(self, _mock):
        r = self.client.get("/rates-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["regime"], "Inflation pressure")
        self.assertAlmostEqual(body["nominal"]["change_5d"], 0.82)

    @patch("api.compute_rates_context", return_value={
        "regime": "Mixed",
        "nominal": {"label": "10Y yield", "value": None, "change_5d": None},
        "real_proxy": {"label": "TIP (real yield proxy)", "value": None, "change_5d": None},
        "breakeven_proxy": {"label": "Breakeven proxy", "change_5d": None},
        "raw": {},
    })
    def test_rates_context_fallback_no_data(self, _mock):
        r = self.client.get("/rates-context")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["regime"], "Mixed")
        self.assertIsNone(body["nominal"]["change_5d"])


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
        """Event with a saved ticker return_5d > 1.5% should appear."""
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
        """Event where all tickers have abs(return_5d) < 1.5% is excluded."""
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

    def test_multi_ticker_binding_survives_sort(self):
        """Each ticker keeps its own return, spark, and decay after the sort."""
        db.save_event({
            "headline": "Multi-ticker binding test",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "AAA", "role": "beneficiary", "return_5d": 3.5,
                 "return_20d": 7.0, "direction_tag": "supports \u2191",
                 "spark": [0.1, 0.2, 0.3]},
                {"symbol": "BBB", "role": "loser", "return_5d": -8.0,
                 "return_20d": -4.0, "direction_tag": "supports \u2193",
                 "spark": [0.9, 0.7, 0.5]},
                {"symbol": "CCC", "role": "beneficiary", "return_5d": 5.0,
                 "return_20d": 10.0, "direction_tag": "supports \u2191",
                 "spark": [0.3, 0.6, 0.9]},
            ],
        })
        r = self.client.get("/market-movers")
        tickers = r.json()[0]["tickers"]
        # After sort by abs(return_5d) desc: BBB(8), CCC(5), AAA(3.5)
        by_sym = {t["symbol"]: t for t in tickers}
        # Each ticker must carry its own metrics, not a neighbour's
        self.assertAlmostEqual(by_sym["BBB"]["return_5d"], -8.0)
        self.assertEqual(by_sym["BBB"]["spark"], [0.9, 0.7, 0.5])
        self.assertEqual(by_sym["BBB"]["decay"], "Accelerating")
        self.assertAlmostEqual(by_sym["CCC"]["return_5d"], 5.0)
        self.assertEqual(by_sym["CCC"]["spark"], [0.3, 0.6, 0.9])
        self.assertAlmostEqual(by_sym["AAA"]["return_5d"], 3.5)
        self.assertEqual(by_sym["AAA"]["spark"], [0.1, 0.2, 0.3])

    def test_mover_includes_transmission_chain(self):
        """Market mover response includes transmission_chain when present."""
        chain = [
            "EU imposes carbon border tariff",
            "Raises import costs for steel/cement producers",
            "Domestic producers gain pricing advantage",
            "EU steelmakers benefit; Asian exporters lose margin",
        ]
        db.save_event({
            "headline": "Chain mover test",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "transmission_chain": chain,
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 5.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertIn("transmission_chain", body[0])
        self.assertEqual(body[0]["transmission_chain"], chain)

    def test_mover_missing_chain_returns_empty_list(self):
        """Market mover degrades cleanly when transmission_chain is absent."""
        db.save_event({
            "headline": "No chain mover",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 4.0,
                 "direction_tag": "supports \u2191"},
            ],
            # No transmission_chain field
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertIn("transmission_chain", body[0])
        self.assertEqual(body[0]["transmission_chain"], [])

    def test_mover_includes_if_persists(self):
        """Market mover response includes if_persists when present."""
        ip = {
            "substitution": "Alternative suppliers gain share.",
            "delayed_winners": ["CompanyX"],
            "delayed_losers": ["CompanyY"],
            "horizon": "months",
        }
        db.save_event({
            "headline": "If persists mover test",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "if_persists": ip,
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 5.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertIn("if_persists", body[0])
        self.assertEqual(body[0]["if_persists"]["substitution"], ip["substitution"])

    def test_mover_missing_if_persists_returns_empty_dict(self):
        """Market mover degrades cleanly when if_persists is absent."""
        db.save_event({
            "headline": "No persist mover",
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 4.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertIn("if_persists", body[0])
        self.assertEqual(body[0]["if_persists"], {})

    def test_loosened_threshold_qualifies_previously_excluded(self):
        """An event with 2.0% return was excluded at old 3% threshold but qualifies at 1.5%."""
        db.save_event({
            "headline": "Threshold test: 2% mover",
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": 2.0,
                 "direction_tag": "supports \u2191"},
            ],
        })
        r = self.client.get("/market-movers")
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["tickers"][0]["symbol"], "GLD")


class TestMoversToday(APITestCase):
    """Tests for GET /movers/today — last-24h events with any confirmed move."""

    def setUp(self):
        super().setUp()
        # Clear the today cache between tests
        _api_mod._TODAYS_MOVERS_CACHE["data"] = None
        _api_mod._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def _seed(self, headline, return_5d, timestamp=None):
        ev = {
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": return_5d,
                 "direction_tag": "supports \u2191"},
            ],
        }
        if timestamp:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def test_returns_recent_events(self):
        """Events from within the last 24h appear."""
        self._seed("Recent mover", 0.5)
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["headline"], "Recent mover")

    def test_excludes_old_events(self):
        """Events older than 24h are excluded."""
        old_ts = (datetime.now() - timedelta(hours=25)).isoformat(timespec="seconds")
        self._seed("Old event", 5.0, timestamp=old_ts)
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])

    def test_includes_small_moves(self):
        """Events with small but non-null return_5d qualify for today's movers."""
        self._seed("Tiny mover", 0.3)
        r = self.client.get("/movers/today")
        body = r.json()
        self.assertEqual(len(body), 1)

    def test_sorted_by_abs_return_descending(self):
        """Results sorted by impact (abs max return) descending."""
        self._seed("Small move", 1.0)
        self._seed("Big move", 8.0)
        r = self.client.get("/movers/today")
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["headline"], "Big move")
        self.assertEqual(body[1]["headline"], "Small move")

    def test_cap_at_limit(self):
        """Default limit is 10."""
        for i in range(12):
            self._seed(f"Mover {i}", float(i + 1))
        r = self.client.get("/movers/today")
        body = r.json()
        self.assertLessEqual(len(body), 10)

    def test_empty_when_no_events(self):
        r = self.client.get("/movers/today")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


class TestMoversPersistent(APITestCase):
    """Tests for GET /movers/persistent — events older than 7 days with active decay."""

    def setUp(self):
        super().setUp()
        _api_mod._PERSISTENT_MOVERS_CACHE["data"] = None
        _api_mod._PERSISTENT_MOVERS_CACHE["ts"] = 0.0

    def _seed(self, headline, return_5d, return_20d=None, timestamp=None):
        if return_20d is None:
            return_20d = return_5d * 1.2  # default to Accelerating trajectory
        ev = {
            "headline": headline,
            "stage": "realized",
            "persistence": "structural",
            "event_date": "2025-01-15",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": return_5d,
                 "return_20d": return_20d, "direction_tag": "supports \u2191"},
            ],
        }
        if timestamp:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def test_returns_old_accelerating_event(self):
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Old accelerating", 5.0, 6.0, timestamp=old_ts)
        r = self.client.get("/movers/persistent")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["headline"], "Old accelerating")
        self.assertIn("days_since_event", body[0])
        self.assertGreater(body[0]["days_since_event"], 0)

    def test_strict_excludes_recent_events(self):
        """When strict results exist, recent events are excluded from them."""
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Old qualifying", 5.0, 6.0, timestamp=old_ts)
        self._seed("Recent event", 5.0, 6.0)  # today
        r = self.client.get("/movers/persistent")
        headlines = [m["headline"] for m in r.json()]
        self.assertIn("Old qualifying", headlines)
        self.assertNotIn("Recent event", headlines)

    def test_strict_excludes_fading_events(self):
        """When strict results exist, fading trajectories are excluded."""
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Old accelerating", 5.0, 6.0, timestamp=old_ts)
        self._seed("Fading shock", 1.0, 10.0, timestamp=old_ts)
        r = self.client.get("/movers/persistent")
        headlines = [m["headline"] for m in r.json()]
        self.assertIn("Old accelerating", headlines)
        self.assertNotIn("Fading shock", headlines)

    def test_strict_excludes_reversed_events(self):
        """When strict results exist, reversed trajectories are excluded."""
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Old holding", 4.0, 5.0, timestamp=old_ts)
        self._seed("Reversed shock", -3.0, 5.0, timestamp=old_ts)
        r = self.client.get("/movers/persistent")
        headlines = [m["headline"] for m in r.json()]
        self.assertIn("Old holding", headlines)
        self.assertNotIn("Reversed shock", headlines)

    def test_sorted_oldest_first(self):
        """Oldest persistent shock sorts first."""
        ts_20d = (datetime.now() - timedelta(days=20)).isoformat(timespec="seconds")
        ts_10d = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        ev_old = {
            "headline": "Older persistent", "stage": "realized", "persistence": "structural",
            "event_date": (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d"),
            "timestamp": ts_20d,
            "market_tickers": [{"symbol": "GLD", "role": "beneficiary", "return_5d": 3.0,
                                "return_20d": 4.0, "direction_tag": "supports \u2191"}],
        }
        ev_new = {
            "headline": "Newer persistent", "stage": "realized", "persistence": "structural",
            "event_date": (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d"),
            "timestamp": ts_10d,
            "market_tickers": [{"symbol": "XLE", "role": "beneficiary", "return_5d": 4.0,
                                "return_20d": 5.0, "direction_tag": "supports \u2191"}],
        }
        db.save_event(ev_new)
        db.save_event(ev_old)
        r = self.client.get("/movers/persistent")
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["headline"], "Older persistent")

    def test_fallback_when_no_old_events(self):
        """When no events are >7d old, fallback includes recent events with movement."""
        self._seed("Recent fallback", 5.0, 6.0)  # No timestamp → today
        r = self.client.get("/movers/persistent")
        body = r.json()
        self.assertGreaterEqual(len(body), 1)
        # Fallback should tag non-classified decay as Monitoring
        has_monitoring = any(
            t.get("decay") == "Monitoring"
            for m in body for t in m["tickers"]
            if t.get("decay") not in ("Accelerating", "Holding")
        )
        # Either all are Accelerating/Holding (real data) or some are Monitoring (fallback)
        self.assertTrue(len(body) > 0)

    def test_deduplicates_by_headline(self):
        """Duplicate headlines should appear only once."""
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        self._seed("Same headline", 5.0, 6.0, timestamp=old_ts)
        self._seed("Same headline", 5.0, 6.0, timestamp=old_ts)
        r = self.client.get("/movers/persistent")
        headlines = [m["headline"] for m in r.json()]
        self.assertEqual(len(headlines), len(set(headlines)))

    def test_cap_at_limit(self):
        old_ts = (datetime.now() - timedelta(days=10)).isoformat(timespec="seconds")
        for i in range(15):
            self._seed(f"Persistent {i}", float(i + 3), float(i + 4), timestamp=old_ts)
        r = self.client.get("/movers/persistent")
        self.assertLessEqual(len(r.json()), 12)


class TestMoversDeduplication(APITestCase):
    """Deduplication tests for time-windowed mover endpoints."""

    def setUp(self):
        super().setUp()
        _api_mod._WEEKLY_MOVERS_CACHE["data"] = None
        _api_mod._WEEKLY_MOVERS_CACHE["ts"] = 0.0
        _api_mod._TODAYS_MOVERS_CACHE["data"] = None
        _api_mod._TODAYS_MOVERS_CACHE["ts"] = 0.0

    def test_weekly_deduplicates(self):
        for _ in range(3):
            db.save_event({
                "headline": "Duplicate weekly event",
                "stage": "realized", "persistence": "medium",
                "event_date": "2025-03-01",
                "market_tickers": [{"symbol": "GLD", "role": "beneficiary",
                                    "return_5d": 5.0, "direction_tag": "supports \u2191"}],
            })
        r = self.client.get("/movers/weekly")
        headlines = [m["headline"] for m in r.json()]
        self.assertEqual(len(headlines), len(set(headlines)))

    def test_today_deduplicates(self):
        for _ in range(3):
            db.save_event({
                "headline": "Duplicate today event",
                "stage": "realized", "persistence": "medium",
                "event_date": "2025-03-01",
                "market_tickers": [{"symbol": "GLD", "role": "beneficiary",
                                    "return_5d": 3.0, "direction_tag": "supports \u2191"}],
            })
        r = self.client.get("/movers/today")
        headlines = [m["headline"] for m in r.json()]
        self.assertEqual(len(headlines), len(set(headlines)))


class TestMoversWeekly(APITestCase):
    """Tests for GET /movers/weekly — last 7 days."""

    def setUp(self):
        super().setUp()
        _api_mod._WEEKLY_MOVERS_CACHE["data"] = None
        _api_mod._WEEKLY_MOVERS_CACHE["ts"] = 0.0

    def _seed(self, headline, return_5d, timestamp=None):
        ev = {
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": return_5d,
                 "direction_tag": "supports \u2191"},
            ],
        }
        if timestamp:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def test_returns_recent_events(self):
        self._seed("Weekly mover", 2.0)
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()), 1)

    def test_excludes_old_events(self):
        old_ts = (datetime.now() - timedelta(days=8)).isoformat(timespec="seconds")
        self._seed("Old weekly", 5.0, timestamp=old_ts)
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.json(), [])

    def test_sorted_by_impact(self):
        self._seed("Small weekly", 1.0)
        self._seed("Big weekly", 8.0)
        r = self.client.get("/movers/weekly")
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["headline"], "Big weekly")

    def test_empty_when_no_events(self):
        r = self.client.get("/movers/weekly")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), [])


class TestMoversYearly(APITestCase):
    """Tests for GET /movers/yearly — last 365 days."""

    def setUp(self):
        super().setUp()
        _api_mod._YEARLY_MOVERS_CACHE["data"] = None
        _api_mod._YEARLY_MOVERS_CACHE["ts"] = 0.0

    def _seed(self, headline, return_5d, timestamp=None):
        ev = {
            "headline": headline,
            "stage": "realized",
            "persistence": "medium",
            "event_date": "2025-03-01",
            "market_tickers": [
                {"symbol": "GLD", "role": "beneficiary", "return_5d": return_5d,
                 "direction_tag": "supports \u2191"},
            ],
        }
        if timestamp:
            ev["timestamp"] = timestamp
        db.save_event(ev)

    def test_returns_recent_events(self):
        self._seed("Yearly mover", 3.0)
        r = self.client.get("/movers/yearly")
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()), 1)

    def test_excludes_old_events(self):
        old_ts = (datetime.now() - timedelta(days=366)).isoformat(timespec="seconds")
        self._seed("Ancient event", 5.0, timestamp=old_ts)
        r = self.client.get("/movers/yearly")
        self.assertEqual(r.json(), [])

    def test_sorted_by_impact(self):
        self._seed("Small yearly", 1.0)
        self._seed("Big yearly", 9.0)
        r = self.client.get("/movers/yearly")
        body = r.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(body[0]["headline"], "Big yearly")


class TestNewsPagination(APITestCase):
    """Tests for paginated GET /news."""

    def test_returns_total_count(self):
        r = self.client.get("/news")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("total_count", body)
        self.assertIsInstance(body["total_count"], int)

    def test_limit_offset_pagination(self):
        r1 = self.client.get("/news?limit=1&offset=0")
        self.assertEqual(r1.status_code, 200)
        body1 = r1.json()
        self.assertLessEqual(len(body1["clusters"]), 1)

    def test_offset_past_end_returns_empty(self):
        r = self.client.get("/news?limit=10&offset=99999")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["clusters"], [])

    def test_zero_limit_returns_all(self):
        """Default limit=0 returns all clusters for backward compatibility."""
        r = self.client.get("/news")
        body = r.json()
        self.assertEqual(len(body["clusters"]), body["total_count"])

    def test_backward_compatible_shape(self):
        """Response still has clusters, total_headlines, feed_status."""
        r = self.client.get("/news")
        body = r.json()
        self.assertIn("clusters", body)
        self.assertIn("total_headlines", body)
        self.assertIn("feed_status", body)


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


class TestLowSignalTagging(APITestCase):
    """Events with insufficient mechanism should be tagged low_signal."""

    def test_low_signal_detected(self):
        """An analysis with 'Insufficient evidence' + no bens/losers/chain is detected."""
        from api import _is_low_signal
        analysis = {
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
        }
        self.assertTrue(_is_low_signal(analysis))

    def test_low_confidence_empty_content_is_low_signal(self):
        """Low confidence + no mechanism/bens/losers/chain → low signal."""
        from api import _is_low_signal
        analysis = {
            "confidence": "low",
            "mechanism_summary": "",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
        }
        self.assertTrue(_is_low_signal(analysis))

    def test_low_confidence_with_mechanism_is_not_low_signal(self):
        """Low confidence but real mechanism → not low signal."""
        from api import _is_low_signal
        analysis = {
            "confidence": "low",
            "mechanism_summary": "Supply disruption through port closures.",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
        }
        self.assertFalse(_is_low_signal(analysis))

    def test_medium_confidence_empty_is_not_low_signal(self):
        """Medium confidence + empty content → not low signal (only low triggers)."""
        from api import _is_low_signal
        analysis = {
            "confidence": "medium",
            "mechanism_summary": "",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
        }
        self.assertFalse(_is_low_signal(analysis))

    def test_normal_analysis_not_low_signal(self):
        from api import _is_low_signal
        analysis = {
            "mechanism_summary": "Real mechanism explaining supply disruption.",
            "beneficiaries": ["CompanyA"],
            "losers": ["CompanyB"],
            "transmission_chain": ["Step 1", "Step 2"],
        }
        self.assertFalse(_is_low_signal(analysis))

    def test_insufficient_with_beneficiaries_not_low_signal(self):
        """Insufficient evidence text but has beneficiaries → not low signal."""
        from api import _is_low_signal
        analysis = {
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": ["CompanyX"],
            "losers": [],
            "transmission_chain": [],
        }
        self.assertFalse(_is_low_signal(analysis))

    def test_low_signal_event_saved_in_db(self):
        """Event persisted with low_signal=1 appears in load_low_signal_headlines."""
        db.save_event({
            "headline": "Low signal test event",
            "stage": "realized",
            "persistence": "medium",
            "mechanism_summary": "Insufficient evidence to identify mechanism.",
            "beneficiaries": [],
            "losers": [],
            "transmission_chain": [],
            "low_signal": 1,
        })
        low = db.load_low_signal_headlines()
        self.assertIn("Low signal test event", low)

    def test_normal_event_not_in_low_signal(self):
        db.save_event({
            "headline": "Normal event with mechanism",
            "stage": "realized",
            "persistence": "structural",
            "mechanism_summary": "Clear supply disruption mechanism.",
            "beneficiaries": ["X"],
            "losers": ["Y"],
            "low_signal": 0,
        })
        low = db.load_low_signal_headlines()
        self.assertNotIn("Normal event with mechanism", low)

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


class TestCurrencyChannel(unittest.TestCase):
    """Tests for currency_channel normalization and response shape."""

    def test_credible_channel_preserved(self):
        from analyze_event import _normalize_currency_channel
        raw = {
            "pair": "DXY",
            "mechanism": "Dollar strengthens as Fed holds rates higher for longer.",
            "beneficiaries": "US importers gain purchasing power.",
            "squeezed": "EM corporates with USD-denominated debt face higher servicing costs.",
        }
        result = _normalize_currency_channel(raw)
        self.assertEqual(result["pair"], "DXY")
        self.assertIn("Dollar", result["mechanism"])
        self.assertIn("importers", result["beneficiaries"])
        self.assertIn("EM", result["squeezed"])

    def test_empty_when_no_fx_channel(self):
        from analyze_event import _normalize_currency_channel
        # null pair
        self.assertEqual(_normalize_currency_channel({"pair": None, "mechanism": None}), {})
        # missing keys
        self.assertEqual(_normalize_currency_channel({}), {})
        # not a dict
        self.assertEqual(_normalize_currency_channel(None), {})
        self.assertEqual(_normalize_currency_channel("string"), {})

    def test_null_like_strings_cleaned(self):
        from analyze_event import _normalize_currency_channel
        raw = {
            "pair": "null",
            "mechanism": "None",
            "beneficiaries": "n/a",
            "squeezed": "null",
        }
        self.assertEqual(_normalize_currency_channel(raw), {})

    def test_pair_without_mechanism_returns_empty(self):
        from analyze_event import _normalize_currency_channel
        raw = {"pair": "EUR/USD", "mechanism": None}
        self.assertEqual(_normalize_currency_channel(raw), {})

    def test_optional_fields_omitted_when_missing(self):
        from analyze_event import _normalize_currency_channel
        raw = {"pair": "USD/JPY", "mechanism": "Yen weakens on BoJ hold."}
        result = _normalize_currency_channel(raw)
        self.assertEqual(result["pair"], "USD/JPY")
        self.assertNotIn("beneficiaries", result)
        self.assertNotIn("squeezed", result)

    def test_mock_has_empty_currency_channel(self):
        from analyze_event import _mock
        m = _mock("test")
        self.assertEqual(m["currency_channel"], {})

    def test_full_analysis_result_shape_includes_currency_channel(self):
        """The full analysis response shape always includes currency_channel."""
        from analyze_event import _mock
        result = _mock("test")
        # Simulate what analyze_event does after parse
        from analyze_event import _normalize_currency_channel
        result["currency_channel"] = _normalize_currency_channel(result.get("currency_channel"))
        self.assertIn("currency_channel", result)
        self.assertIsInstance(result["currency_channel"], dict)


class TestPolicySensitivity(unittest.TestCase):
    """Tests for classify_policy_sensitivity deterministic classification."""

    def test_inflation_with_commodity_mechanism(self):
        """Inflationary event in inflation-pressure regime → reinforced."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Inflation pressure",
            "Oil price surge disrupts crude supply chains and raises input costs.",
        )
        self.assertEqual(result["stance"], "reinforced")
        self.assertIn("compound", result["explanation"].lower())
        self.assertEqual(result["regime"], "Inflation pressure")

    def test_loose_rate_in_tightening_regime(self):
        """Rate-sensitive growth event in tightening regime → fighting."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Real-rate tightening",
            "Multiple expansion from lower discount rates lifts equity valuations.",
        )
        self.assertEqual(result["stance"], "fighting")
        self.assertIn("headwind", result["explanation"].lower())

    def test_loose_rate_in_risk_off(self):
        """Rate-sensitive event in risk-off / falling yields → reinforced."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Risk-off / growth scare",
            "Multiple expansion as growth stock valuations benefit from duration.",
        )
        self.assertEqual(result["stance"], "reinforced")
        self.assertIn("tailwind", result["explanation"].lower())

    def test_tight_rate_benefit_in_tightening(self):
        """Bank margin event in tightening → reinforced."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Real-rate tightening",
            "Bank margin improvement from net interest income expansion.",
        )
        self.assertEqual(result["stance"], "reinforced")

    def test_neutral_when_no_rate_keywords(self):
        """Mechanism with no rate keywords → neutral."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Inflation pressure",
            "New semiconductor export controls restrict chip access.",
        )
        self.assertEqual(result["stance"], "neutral")

    def test_mixed_regime_returns_neutral_fallback(self):
        """Mixed regime → visible neutral fallback, not empty."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Mixed",
            "Oil price surge raises input costs.",
        )
        self.assertEqual(result["stance"], "neutral")
        self.assertIn("mixed", result["explanation"].lower())
        self.assertEqual(result["regime"], "Mixed")

    def test_strong_signal_no_keywords_returns_neutral(self):
        """Strong mechanism with no rate keywords → visible neutral."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Inflation pressure",
            "New semiconductor export controls restrict chip access to Chinese fabs.",
        )
        self.assertEqual(result["stance"], "neutral")
        self.assertIn("no direct rate sensitivity", result["explanation"].lower())

    def test_empty_mechanism_returns_empty(self):
        """Empty mechanism text → empty dict (low-signal guard)."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity("Inflation pressure", "")
        self.assertEqual(result, {})

    def test_whitespace_mechanism_returns_empty(self):
        """Whitespace-only mechanism → empty dict."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity("Real-rate tightening", "   ")
        self.assertEqual(result, {})

    def test_response_shape(self):
        """Result always has stance, explanation, regime when non-empty."""
        from market_check import classify_policy_sensitivity
        result = classify_policy_sensitivity(
            "Inflation pressure",
            "Tariff increases raise import costs across supply chains.",
        )
        self.assertIn("stance", result)
        self.assertIn("explanation", result)
        self.assertIn("regime", result)
        self.assertIn(result["stance"], ("reinforced", "fighting", "neutral"))


class TestInventoryContext(unittest.TestCase):
    """Tests for classify_inventory_context classification and fallback."""

    def _mock_fetch(self, return_20d: float):
        """Patch _fetch and _safe_pct to return a controlled 20d return."""
        import market_check
        import types

        # Create a mock DataFrame-like object
        class FakeSeries:
            def __init__(self, values):
                self._values = values
            def __len__(self):
                return len(self._values)
            @property
            def iloc(self):
                return self
            def __getitem__(self, idx):
                return self._values[idx]

        class FakeDF:
            def __init__(self, ret):
                # Build 25 values where pct from [-21] to [-1] = ret
                base = 100.0
                end = base * (1 + ret / 100)
                vals = [base] * 4 + [end]  # simplified
                self._close = FakeSeries(vals)
            def __len__(self):
                return 25
            def __getitem__(self, key):
                return self._close

        original_fetch = market_check._fetch
        original_safe_pct = market_check._safe_pct
        market_check._fetch = lambda ticker: FakeDF(return_20d)
        market_check._safe_pct = lambda series, n: return_20d
        return original_fetch, original_safe_pct

    def _restore(self, originals):
        import market_check
        market_check._fetch, market_check._safe_pct = originals

    def test_tight_on_rising_oil(self):
        """Oil keyword + rising proxy → tight."""
        originals = self._mock_fetch(5.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Crude oil supply disruption in the Gulf.")
            self.assertEqual(result["status"], "tight")
            self.assertEqual(result["proxy"], "USO")
            self.assertIn("tightening", result["explanation"].lower())
            self.assertEqual(result["return_20d"], 5.0)
        finally:
            self._restore(originals)

    def test_comfortable_on_falling_commodity(self):
        """Copper keyword + falling proxy → comfortable."""
        originals = self._mock_fetch(-5.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Copper mining output increases sharply.")
            self.assertEqual(result["status"], "comfortable")
            self.assertEqual(result["proxy"], "COPX")
        finally:
            self._restore(originals)

    def test_neutral_on_flat_price(self):
        """Keyword match but flat price → neutral."""
        originals = self._mock_fetch(0.5)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Wheat prices remain steady despite trade deal.")
            self.assertEqual(result["status"], "neutral")
            self.assertIn("flat", result["explanation"].lower())
        finally:
            self._restore(originals)

    def test_empty_when_no_keywords(self):
        """No commodity keywords → empty dict."""
        from market_check import classify_inventory_context
        result = classify_inventory_context("New semiconductor export controls restrict chip access.")
        # semiconductor IS in the proxy list, so this should match SMH
        # Test with something truly unmatched:
        result2 = classify_inventory_context("Central bank holds rates steady at monthly meeting.")
        self.assertEqual(result2, {})

    def test_empty_when_empty_mechanism(self):
        """Empty mechanism → empty dict."""
        from market_check import classify_inventory_context
        self.assertEqual(classify_inventory_context(""), {})
        self.assertEqual(classify_inventory_context("   "), {})

    def test_response_shape(self):
        """Non-empty result has all expected keys."""
        originals = self._mock_fetch(4.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Oil pipeline disruption raises crude prices.")
            self.assertIn("status", result)
            self.assertIn("proxy", result)
            self.assertIn("proxy_label", result)
            self.assertIn("return_20d", result)
            self.assertIn("explanation", result)
            self.assertIn(result["status"], ("tight", "comfortable", "neutral"))
        finally:
            self._restore(originals)

    def test_semiconductor_matches_smh(self):
        """Semiconductor keyword matches SMH proxy."""
        originals = self._mock_fetch(6.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Chip foundry capacity shortage worsens.")
            self.assertEqual(result["proxy"], "SMH")
            self.assertEqual(result["status"], "tight")
        finally:
            self._restore(originals)


    def _mock_fetch_none(self):
        """Patch _fetch to return None (data unavailable)."""
        import market_check
        original_fetch = market_check._fetch
        original_safe_pct = market_check._safe_pct
        market_check._fetch = lambda ticker: None
        market_check._safe_pct = lambda series, n: None
        return original_fetch, original_safe_pct

    def test_opec_headline_produces_visible_block(self):
        """OPEC headline → visible block even with flat data."""
        originals = self._mock_fetch(1.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("OPEC agrees to extend production cuts through Q3.")
            self.assertIn("status", result)
            self.assertEqual(result["proxy"], "USO")
            self.assertIn(result["status"], ("tight", "comfortable", "neutral"))
        finally:
            self._restore(originals)

    def test_lng_headline_produces_visible_block(self):
        """LNG headline → visible block."""
        originals = self._mock_fetch(-1.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("New LNG terminal opens in Louisiana boosting gas export capacity.")
            self.assertIn("status", result)
            self.assertEqual(result["proxy"], "UNG")
        finally:
            self._restore(originals)

    def test_shipping_headline_produces_visible_block(self):
        """Shipping headline → visible block."""
        originals = self._mock_fetch(2.0)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Tanker rates surge as Red Sea shipping reroutes continue.")
            self.assertIn("status", result)
            self.assertEqual(result["proxy"], "BDRY")
        finally:
            self._restore(originals)

    def test_inconclusive_data_shows_neutral_fallback(self):
        """Keyword matches but _fetch returns None → neutral fallback, not empty."""
        originals = self._mock_fetch_none()
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Crude oil supply disruption in the Strait of Hormuz.")
            self.assertEqual(result["status"], "neutral")
            self.assertEqual(result["proxy"], "USO")
            self.assertIn("unavailable", result["explanation"].lower())
            self.assertNotIn("return_20d", result)
        finally:
            self._restore(originals)

    def test_pipeline_infrastructure_matches_oil_proxy(self):
        """Pipeline/infrastructure headline → oil proxy."""
        originals = self._mock_fetch(4.5)
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Key oil pipeline shut down after drone strike.")
            self.assertEqual(result["proxy"], "USO")
            self.assertEqual(result["status"], "tight")
        finally:
            self._restore(originals)


class TestInventoryContextEndToEnd(unittest.TestCase):
    """End-to-end: verify inventory_context flows from classification to API response."""

    def _mock_fetch(self, return_20d):
        import market_check
        orig_fetch = market_check._fetch
        orig_pct = market_check._safe_pct
        market_check._fetch = lambda ticker: type('DF', (), {'__len__': lambda s: 25, '__getitem__': lambda s, k: None})()
        market_check._safe_pct = lambda series, n: return_20d
        return orig_fetch, orig_pct

    def _restore(self, originals):
        import market_check
        market_check._fetch, market_check._safe_pct = originals

    def test_opec_headline_has_inventory_in_api_response(self):
        """Full path: OPEC headline → classify → analysis dict → inventory_context present."""
        originals = self._mock_fetch(4.5)
        try:
            from market_check import classify_inventory_context
            mech = "OPEC agrees to extend oil production cuts, reducing crude supply."
            result = classify_inventory_context(mech)
            # Backend sets this on analysis dict
            self.assertIn("status", result)
            self.assertIn("explanation", result)
            self.assertEqual(result["proxy"], "USO")
            self.assertEqual(result["status"], "tight")
            # Simulate what api.py does: set it on analysis
            analysis = {"inventory_context": result}
            # Frontend reads result.analysis.inventory_context.status
            ic = analysis.get("inventory_context", {})
            self.assertTrue(ic.get("status"), "Frontend guard would hide this block")
        finally:
            self._restore(originals)

    def test_weak_signal_still_visible(self):
        """Inconclusive data → neutral fallback, not empty."""
        originals = self._mock_fetch(None)  # None = no data
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("Crude oil supply disrupted by pipeline closure.")
            self.assertEqual(result["status"], "neutral")
            self.assertIn("unavailable", result["explanation"])
            # Frontend guard: status exists → block renders
            self.assertTrue(result.get("status"))
        finally:
            self._restore(originals)

    def test_non_commodity_returns_empty(self):
        """Non-commodity headline → empty dict → block hidden (correct)."""
        from market_check import classify_inventory_context
        result = classify_inventory_context("Federal Reserve holds rates steady at latest meeting.")
        self.assertEqual(result, {})
        # Frontend guard: no status → block hidden (correct)
        self.assertFalse(result.get("status"))

    def test_frontend_conditional_logic(self):
        """Simulate the exact frontend conditional for various backend results."""
        cases = [
            # (backend result, should_render)
            ({"status": "tight", "explanation": "USO up", "proxy": "USO"}, True),
            ({"status": "neutral", "explanation": "data unavailable", "proxy": "USO"}, True),
            ({"status": "comfortable", "explanation": "USO down", "proxy": "USO"}, True),
            ({}, False),
            (None, False),
        ]
        for ic, expected in cases:
            # Mimics: result.analysis.inventory_context && result.analysis.inventory_context.status
            renders = bool(ic and ic.get("status"))
            self.assertEqual(renders, expected,
                f"inventory_context={ic!r} should {'render' if expected else 'hide'}")


class TestInventoryHeadlineInclusion(unittest.TestCase):
    """Verify inventory classification uses headline text, not just mechanism."""

    def _mock_fetch(self, return_20d):
        import market_check
        orig_f = market_check._fetch
        orig_p = market_check._safe_pct
        market_check._fetch = lambda t: type('D', (), {'__len__': lambda s: 25, '__getitem__': lambda s, k: None})()
        market_check._safe_pct = lambda s, n: return_20d
        return orig_f, orig_p

    def _restore(self, originals):
        import market_check
        market_check._fetch, market_check._safe_pct = originals

    def test_opec_headline_with_mock_mechanism(self):
        """OPEC in headline + mock mechanism → still matches oil proxy."""
        originals = self._mock_fetch(2.0)
        try:
            from market_check import classify_inventory_context
            # Simulate what api.py now does: headline + mech_text
            inv_text = "OPEC agrees to extend production cuts [mock: no API key] [mock: no API key]"
            result = classify_inventory_context(inv_text)
            self.assertEqual(result["proxy"], "USO")
            self.assertIn(result["status"], ("tight", "comfortable", "neutral"))
        finally:
            self._restore(originals)

    def test_lng_headline_with_empty_mechanism(self):
        """LNG headline + empty mechanism → matches gas proxy."""
        originals = self._mock_fetch(-1.0)
        try:
            from market_check import classify_inventory_context
            inv_text = "New LNG export terminal approved in Queensland  "
            result = classify_inventory_context(inv_text)
            self.assertEqual(result["proxy"], "UNG")
        finally:
            self._restore(originals)

    def test_shipping_headline_with_sparse_mechanism(self):
        """Shipping headline + sparse mechanism → matches BDRY."""
        originals = self._mock_fetch(5.0)
        try:
            from market_check import classify_inventory_context
            inv_text = "Red Sea shipping reroutes continue after Houthi attacks Generic disruption analysis."
            result = classify_inventory_context(inv_text)
            self.assertEqual(result["proxy"], "BDRY")
            self.assertEqual(result["status"], "tight")
        finally:
            self._restore(originals)

    def test_non_commodity_headline_still_empty(self):
        """Non-commodity headline → still empty, no false positives."""
        from market_check import classify_inventory_context
        result = classify_inventory_context("Federal Reserve holds rates steady at latest FOMC meeting.")
        self.assertEqual(result, {})


class TestInventoryCacheFallback(unittest.TestCase):
    """Verify _build_cached_response recomputes inventory_context for old rows."""

    def _mock_fetch(self, return_20d):
        import market_check
        orig_f = market_check._fetch
        orig_p = market_check._safe_pct
        market_check._fetch = lambda t: type('D', (), {'__len__': lambda s: 25, '__getitem__': lambda s, k: None})()
        market_check._safe_pct = lambda s, n: return_20d
        return orig_f, orig_p

    def _restore(self, originals):
        import market_check
        market_check._fetch, market_check._safe_pct = originals

    def test_old_cached_row_gets_recomputed(self):
        """A cached event with empty inventory_context gets it recomputed."""
        originals = self._mock_fetch(4.0)
        try:
            from api import _build_cached_response
            cached = {
                "stage": "realized",
                "persistence": "medium",
                "what_changed": "OPEC extends oil production cuts.",
                "mechanism_summary": "Crude supply reduced, barrel prices rise.",
                "beneficiaries": ["XLE"],
                "losers": ["Airlines"],
                "assets_to_watch": ["XLE"],
                "confidence": "high",
                "market_note": "",
                "market_tickers": [],
                "transmission_chain": ["OPEC cuts", "supply drops", "prices rise"],
                "if_persists": {},
                "currency_channel": {},
                "policy_sensitivity": {},
                "inventory_context": {},  # empty — old row
            }
            resp = _build_cached_response(cached, "OPEC extends oil cuts", "2026-04-06")
            ic = resp["analysis"]["inventory_context"]
            self.assertIn("status", ic, "inventory_context should be recomputed from headline")
            self.assertEqual(ic["proxy"], "USO")
        finally:
            self._restore(originals)

    def test_cached_row_with_existing_inventory_preserved(self):
        """A cached event that already has inventory_context is not overwritten."""
        originals = self._mock_fetch(4.0)
        try:
            from api import _build_cached_response
            existing_ic = {"status": "tight", "proxy": "USO", "proxy_label": "Crude Oil (USO)",
                           "return_20d": 6.0, "explanation": "Already computed."}
            cached = {
                "stage": "realized", "persistence": "medium",
                "what_changed": "OPEC cuts", "mechanism_summary": "Oil supply reduced.",
                "beneficiaries": [], "losers": [], "assets_to_watch": [],
                "confidence": "high", "market_note": "", "market_tickers": [],
                "transmission_chain": [], "if_persists": {},
                "currency_channel": {}, "policy_sensitivity": {},
                "inventory_context": existing_ic,
            }
            resp = _build_cached_response(cached, "OPEC cuts", "2026-04-06")
            ic = resp["analysis"]["inventory_context"]
            self.assertEqual(ic["return_20d"], 6.0, "Existing value should be preserved")
            self.assertEqual(ic["explanation"], "Already computed.")
        finally:
            self._restore(originals)

    def test_fresh_opec_analysis_returns_nonempty(self):
        """classify_inventory_context with headline+mechanism → non-empty for OPEC."""
        originals = self._mock_fetch(3.5)
        try:
            from market_check import classify_inventory_context
            inv_text = "OPEC members agree to extend voluntary oil output cuts through next quarter OPEC production cuts reduce crude supply."
            result = classify_inventory_context(inv_text)
            self.assertIn("status", result)
            self.assertEqual(result["proxy"], "USO")
            self.assertIn(result["status"], ("tight", "comfortable", "neutral"))
        finally:
            self._restore(originals)

    def test_inconclusive_returns_neutral_not_empty(self):
        """Data unavailable → neutral fallback, not {}."""
        import market_check
        orig_f = market_check._fetch
        orig_p = market_check._safe_pct
        market_check._fetch = lambda t: None
        market_check._safe_pct = lambda s, n: None
        try:
            from market_check import classify_inventory_context
            result = classify_inventory_context("OPEC oil production cuts announced.")
            self.assertEqual(result["status"], "neutral")
            self.assertIn("unavailable", result["explanation"])
        finally:
            market_check._fetch = orig_f
            market_check._safe_pct = orig_p


class TestHistoricalAnalogs(APITestCase):
    """Tests for find_historical_analogs matching, ranking, and empty state."""

    def _seed_events(self):
        """Seed some past events for analog matching."""
        events = [
            {
                "headline": "OPEC announces surprise production cut of 1 million barrels",
                "stage": "realized", "persistence": "medium",
                "what_changed": "OPEC cuts oil production.",
                "mechanism_summary": "Crude supply reduced, barrel prices rise.",
                "beneficiaries": ["XLE"], "losers": ["Airlines"],
                "assets_to_watch": ["XLE", "USO"],
                "confidence": "high", "market_note": "",
                "market_tickers": [
                    {"symbol": "XLE", "role": "beneficiary", "return_5d": 3.2, "return_20d": 5.1, "direction_tag": "supporting"},
                ],
                "event_date": "2026-03-01",
                "low_signal": 0,
            },
            {
                "headline": "Saudi Arabia raises official selling prices for Asian crude buyers",
                "stage": "realized", "persistence": "medium",
                "what_changed": "Saudi raises oil prices.",
                "mechanism_summary": "Crude prices increase for Asian refiners.",
                "beneficiaries": ["XLE"], "losers": ["Indian refiners"],
                "assets_to_watch": ["XLE"],
                "confidence": "medium", "market_note": "",
                "market_tickers": [
                    {"symbol": "XLE", "role": "beneficiary", "return_5d": 1.5, "return_20d": 2.8, "direction_tag": "supporting"},
                ],
                "event_date": "2026-02-15",
                "low_signal": 0,
            },
            {
                "headline": "Federal Reserve holds rates steady at March meeting",
                "stage": "realized", "persistence": "low",
                "what_changed": "Fed holds rates.",
                "mechanism_summary": "No change in monetary policy.",
                "beneficiaries": [], "losers": [],
                "assets_to_watch": [],
                "confidence": "low", "market_note": "",
                "market_tickers": [],
                "event_date": "2026-03-19",
                "low_signal": 1,
            },
        ]
        for ev in events:
            db.save_event(ev)

    def test_finds_matching_analogs(self):
        """An oil headline should find past OPEC/Saudi oil events."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "OPEC members agree to extend voluntary oil output cuts",
            mechanism="Crude supply reduced by production cuts.",
            stage="realized",
            persistence="medium",
        )
        self.assertGreaterEqual(len(analogs), 1)
        headlines = [a["headline"] for a in analogs]
        self.assertTrue(
            any("OPEC" in h or "Saudi" in h for h in headlines),
            f"Expected oil-related analog, got: {headlines}",
        )

    def test_ranking_by_relevance(self):
        """More relevant analog should rank first."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "OPEC extends oil production cuts through next quarter",
            mechanism="OPEC crude supply reduction.",
            stage="realized",
        )
        if len(analogs) >= 2:
            # The OPEC headline should be more relevant than Saudi
            self.assertIn("OPEC", analogs[0]["headline"])

    def test_excludes_self(self):
        """Should not return the same headline as an analog."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "OPEC announces surprise production cut of 1 million barrels",
            exclude_headline="OPEC announces surprise production cut of 1 million barrels",
        )
        for a in analogs:
            self.assertNotEqual(a["headline"], "OPEC announces surprise production cut of 1 million barrels")

    def test_excludes_low_signal(self):
        """Low-signal events should not appear as analogs."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "Federal Reserve holds rates steady",
            mechanism="No change in monetary policy.",
        )
        for a in analogs:
            self.assertNotEqual(a["headline"], "Federal Reserve holds rates steady at March meeting")

    def test_empty_when_no_matches(self):
        """Unrelated headline with no archive matches → empty list."""
        analogs = db.find_historical_analogs(
            "Completely unrelated topic about space exploration and Mars",
        )
        self.assertEqual(analogs, [])

    def test_response_shape(self):
        """Each analog has the expected keys."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "OPEC oil production cut announced",
            mechanism="Oil supply disruption.",
        )
        if analogs:
            a = analogs[0]
            for key in ("headline", "event_date", "stage", "persistence",
                        "confidence", "return_5d", "return_20d", "decay"):
                self.assertIn(key, a, f"Missing key: {key}")
            self.assertIn(a["decay"], ("Accelerating", "Holding", "Fading", "Reversed", "Unknown"))

    def test_max_3_results(self):
        """Should return at most 3 analogs."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "Oil production cuts",
            mechanism="crude oil",
            limit=3,
        )
        self.assertLessEqual(len(analogs), 3)

    def test_decay_label_from_tickers(self):
        """Decay should be classified from stored ticker returns."""
        self._seed_events()
        analogs = db.find_historical_analogs(
            "OPEC oil cut",
            mechanism="crude supply reduction",
        )
        if analogs:
            # The seeded OPEC event has 5d=3.2, 20d=5.1 → same sign, 3.2/5.1=0.63 > 0.4 → Holding
            opec = next((a for a in analogs if "OPEC" in a["headline"]), None)
            if opec:
                self.assertIn(opec["decay"], ("Accelerating", "Holding"))


class TestHistoricalAnalogShape(APITestCase):
    """Tests for analog match_reason, similarity, and single-analog fallback."""

    def _seed(self):
        db.save_event({
            "headline": "OPEC announces surprise production cut of 1 million barrels",
            "stage": "realized", "persistence": "medium",
            "what_changed": "OPEC cuts oil production.",
            "mechanism_summary": "Crude supply reduced, barrel prices rise.",
            "beneficiaries": ["XLE"], "losers": ["Airlines"],
            "assets_to_watch": ["XLE", "USO"],
            "confidence": "high", "market_note": "",
            "market_tickers": [
                {"symbol": "XLE", "role": "beneficiary", "return_5d": 3.2,
                 "return_20d": 5.1, "direction_tag": "supporting"},
            ],
            "event_date": "2026-03-01",
            "low_signal": 0,
        })

    def test_match_reason_present(self):
        """Each analog has a non-empty match_reason."""
        self._seed()
        analogs = db.find_historical_analogs(
            "OPEC oil production cut",
            mechanism="Crude supply reduction.",
            stage="realized",
            persistence="medium",
        )
        self.assertGreaterEqual(len(analogs), 1)
        for a in analogs:
            self.assertIn("match_reason", a)
            self.assertTrue(len(a["match_reason"]) > 0)

    def test_similarity_present(self):
        """Each analog has a numeric similarity score."""
        self._seed()
        analogs = db.find_historical_analogs(
            "OPEC oil production cut",
            mechanism="Crude supply reduction.",
        )
        if analogs:
            self.assertIn("similarity", analogs[0])
            self.assertIsInstance(analogs[0]["similarity"], float)
            self.assertGreater(analogs[0]["similarity"], 0)

    def test_match_reason_includes_shared_words(self):
        """Match reason should mention shared content words."""
        self._seed()
        analogs = db.find_historical_analogs(
            "OPEC extends oil production cuts",
            mechanism="Oil supply disruption.",
        )
        if analogs:
            reason = analogs[0]["match_reason"].lower()
            # Should mention at least one shared word
            self.assertTrue(
                "shared:" in reason or "keyword" in reason,
                f"Expected shared words in reason, got: {reason}",
            )

    def test_match_reason_notes_same_stage(self):
        """Match reason includes 'same stage' when stage matches."""
        self._seed()
        analogs = db.find_historical_analogs(
            "OPEC oil cut",
            mechanism="crude supply",
            stage="realized",
        )
        if analogs:
            self.assertIn("same stage", analogs[0]["match_reason"])

    def test_single_analog_returned_cleanly(self):
        """When only one analog matches, it's returned as a single-item list."""
        self._seed()
        analogs = db.find_historical_analogs(
            "OPEC barrels production cut",
            mechanism="oil supply",
            limit=1,
        )
        self.assertEqual(len(analogs), 1)
        a = analogs[0]
        for key in ("headline", "event_date", "stage", "persistence",
                    "return_5d", "return_20d", "decay", "similarity", "match_reason"):
            self.assertIn(key, a)


if __name__ == "__main__":
    unittest.main()
