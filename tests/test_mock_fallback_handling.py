"""
tests/test_mock_fallback_handling.py

Focused tests for mock-fallback handling:

  1) Mock/overload fallback is not persisted as a real event.
  2) API returns explicit failure/degraded state (analysis_failed + failure_reason).
  3) Healthy analysis still works and is persisted normally.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import _mock, is_mock


# ---------------------------------------------------------------------------
# Unit: is_mock detection
# ---------------------------------------------------------------------------

class TestIsMockDetection(unittest.TestCase):

    def test_mock_detected(self):
        self.assertTrue(is_mock(_mock("overloaded")))

    def test_mock_reason_variations(self):
        self.assertTrue(is_mock(_mock("no API key")))
        self.assertTrue(is_mock(_mock("anthropic not installed")))
        self.assertTrue(is_mock(_mock("JSON parse error")))

    def test_real_analysis_not_mock(self):
        real = {"what_changed": "Fed raised rates by 25bp", "mechanism_summary": "Real mechanism"}
        self.assertFalse(is_mock(real))

    def test_empty_analysis_not_mock(self):
        self.assertFalse(is_mock({}))


# ---------------------------------------------------------------------------
# Unit: _mock_failure_response shape
# ---------------------------------------------------------------------------

class TestMockFailureResponse(unittest.TestCase):

    def setUp(self):
        import api
        self.api = api

    def test_failure_response_shape(self):
        resp = self.api._mock_failure_response(
            "Test headline", _mock("overloaded"), "2026-04-13",
        )
        self.assertTrue(resp["is_mock"])
        self.assertTrue(resp["analysis_failed"])
        self.assertEqual(resp["failure_reason"], "overloaded")
        self.assertEqual(resp["headline"], "Test headline")
        self.assertEqual(resp["event_date"], "2026-04-13")
        # analysis and market are empty stubs — not mock garbage
        self.assertEqual(resp["analysis"], {})
        self.assertEqual(resp["market"]["tickers"], [])

    def test_failure_reason_extracted_from_mock(self):
        resp = self.api._mock_failure_response(
            "H", _mock("no API key"), "2026-01-01",
        )
        self.assertEqual(resp["failure_reason"], "no API key")

    def test_stable_keys_present(self):
        """Response has all the same top-level keys as a normal response."""
        resp = self.api._mock_failure_response("H", _mock("x"), "2026-01-01")
        for key in ("headline", "stage", "persistence", "analysis",
                     "market", "is_mock", "event_date"):
            self.assertIn(key, resp, f"Missing key: {key}")

    def test_failure_reason_defaults_when_mock_reason_empty(self):
        """A message-less exception yields ``_mock(str(e))`` with ``str(e)==""``
        → ``what_changed == "[mock: ]"`` → an empty extracted reason.  The
        response must still carry a non-empty, human-readable failure_reason so
        the streamed terminal is not rejected by the frontend validator."""
        self.assertEqual(_mock("").get("what_changed"), "[mock: ]")
        resp = self.api._mock_failure_response("H", _mock(""), "2026-01-01")
        self.assertTrue(resp["analysis_failed"])
        self.assertTrue(resp["is_mock"])
        self.assertNotEqual((resp["failure_reason"] or "").strip(), "")
        self.assertEqual(resp["failure_reason"], "model unavailable")


# ---------------------------------------------------------------------------
# Integration: /analyze does not persist mock and returns failure
# ---------------------------------------------------------------------------

class TestAnalyzeEndpointMockNotPersisted(unittest.TestCase):

    def test_mock_not_persisted_and_returns_failure(self):
        import api

        persist_mock = MagicMock(return_value=(None, 1))  # (error, saved id)

        with patch("api.analyze_event", return_value=_mock("overloaded")), \
             patch("api.classify_stage", return_value="developing"), \
             patch("api.classify_persistence", return_value="medium"), \
             patch("api._persist_event", persist_mock), \
             patch("api.market_check") as market_mock:

            resp = api.analyze(api.AnalyzeRequest(headline="Test overload", confirm_paid=True))

        # Must NOT have persisted
        persist_mock.assert_not_called()
        # Must NOT have run market_check (wasted quota)
        market_mock.assert_not_called()
        # Response has failure fields
        self.assertTrue(resp["analysis_failed"])
        self.assertTrue(resp["is_mock"])
        self.assertEqual(resp["failure_reason"], "overloaded")

    def test_healthy_analysis_persisted_and_no_failure(self):
        import api

        real_analysis = {
            "what_changed": "Fed raised rates",
            "mechanism_summary": "Higher borrowing costs",
            "beneficiaries": ["Banks"],
            "losers": ["REITs"],
            "beneficiary_tickers": ["XLF"],
            "loser_tickers": ["VNQ"],
            "assets_to_watch": [],
            "confidence": "medium",
            "transmission_chain": [],
            "if_persists": {},
            "currency_channel": {},
        }
        persist_mock = MagicMock(return_value=(None, 1))  # (error, saved id)

        # Only the true external boundaries are mocked: the LLM
        # (``api.analyze_event``) and the market data provider
        # (``market_check._fetch``).  classify_stage / classify_persistence
        # are pure keyword matchers — they run for real.  Every macro
        # overlay composer (rates / stress / regime / shock / reaction /
        # surprise / terms_of_trade / reserve_stress / …) also runs for
        # real against a starved data provider, so each composer's own
        # graceful-degradation branch is exercised instead of being
        # stubbed out.  ``_persist_event`` stays mocked as an observation
        # probe so the assertion below can inspect call count.
        with patch("api.analyze_event", return_value=real_analysis), \
             patch("api._persist_event", persist_mock), \
             patch("market_check._fetch", return_value=None):

            resp = api.analyze(api.AnalyzeRequest(headline="Fed raises rates", confirm_paid=True))

        # Must have persisted
        persist_mock.assert_called_once()
        # No failure fields
        self.assertFalse(resp.get("is_mock", False))
        self.assertFalse(resp.get("analysis_failed", False))


# ---------------------------------------------------------------------------
# Integration: /analyze/stream mock short-circuits
# ---------------------------------------------------------------------------

class TestAnalyzeStreamMockShortCircuit(unittest.TestCase):

    def test_stream_mock_emits_failure_complete(self):
        import api
        import json

        persist_mock = MagicMock(return_value=(None, 1))  # (error, saved id)

        with patch("api.analyze_event", return_value=_mock("overloaded")), \
             patch("api.classify_stage", return_value="developing"), \
             patch("api.classify_persistence", return_value="medium"), \
             patch("api._persist_event", persist_mock), \
             patch("api.market_check") as market_mock, \
             patch("api.find_cached_analysis", return_value=None), \
             patch("api.load_event_by_id", return_value=None):

            from fastapi.testclient import TestClient
            client = TestClient(api.app)
            resp = client.post("/analyze/stream", json={
                "headline": "Test overload stream",
                "confirm_paid": True,
            })
            body = resp.text

        # Should not have persisted
        persist_mock.assert_not_called()
        # Should not have called market_check
        market_mock.assert_not_called()

        # Parse SSE events — expect classify + complete (with failure)
        events = []
        for line in body.strip().split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        # The last event should be the failure complete
        complete = [e for e in events if e.get("_phase") == "complete"]
        self.assertTrue(len(complete) >= 1)
        fail_event = complete[-1]
        self.assertTrue(fail_event.get("analysis_failed"))
        self.assertTrue(fail_event.get("is_mock"))
        self.assertEqual(fail_event.get("failure_reason"), "overloaded")


if __name__ == "__main__":
    unittest.main()
