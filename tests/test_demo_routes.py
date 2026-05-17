"""Tests for the four ``/demo/*`` endpoints registered in ``api.py``.

The endpoints are thin wrappers around the four demo source modules.
These tests patch each source module to a deterministic fixture and
assert the endpoint forwards the fixture verbatim, returns HTTP 200,
and surfaces the expected ``section`` value.  They also pin that the
existing production surfaces ``/health`` and ``/movers/today`` keep
their original contract.

The endpoints must not call any provider / ``yfinance`` / ``market_data``
/ LLM module — when every source module is patched, the response body
must equal the patched fixture exactly.  Any deviation would mean the
endpoint is doing more than forwarding to the source.
"""
from __future__ import annotations

import os
import sys
import unittest
from typing import Any
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — deterministic payloads each patched source returns.
# ---------------------------------------------------------------------------


_DAILY_FIXTURE: dict[str, Any] = {
    "ok":                True,
    "section":           "daily",
    "items":             [
        {
            "candidate_id":     "fixture-daily-001",
            "headline":         "fixture daily headline",
            "event_date":       "2026-04-15",
            "mechanism_family": "supply_shock",
            "primary_ticker":   "FIX_P",
            "benchmark_ticker": "FIX_B",
            "market_relevance": "",
            "inclusion_reason": "",
            "operator_notes":   "",
            "source":           "analyzed_event_artifact",
        },
    ],
    "count":             1,
    "skipped_artifacts": [],
    "warnings":          [],
    "errors":            [],
}


_WEEKLY_FIXTURE: dict[str, Any] = {
    "ok":                         True,
    "section":                    "weekly",
    "items":                      [
        {
            "event_id":          7001,
            "headline":          "fixture weekly headline",
            "event_date":        "2026-04-15",
            "duplicate_count":   0,
            "grouped_event_ids": [7001],
            "caution_label":     "fixture caution",
        },
    ],
    "count":                      1,
    "duplicate_groups_collapsed": 0,
    "warnings":                   [],
    "errors":                     [],
}


_STILL_MOVING_FIXTURE: dict[str, Any] = {
    "ok":                True,
    "section":           "still_moving",
    "items":             [
        {
            "event_id":           8001,
            "headline":           "fixture still moving headline",
            "event_date":         "2026-04-15",
            "primary_ticker":     "FIX_S",
            "persistence_signal": "Accelerating",
            "evidence_reason":    "fixture",
        },
    ],
    "count":             1,
    "rejected_count":    0,
    "rejection_summary": {},
    "warnings":          [],
    "errors":            [],
}


_EVIDENCE_FIXTURE: dict[str, Any] = {
    "ok":                            True,
    "section":                       "evidence_summary",
    "cohort_summary":                {"fixture": True},
    "verdict_counts":                {"confirmed": 0},
    "fdr_significant_count":         0,
    "raw_p_candidate_count":         0,
    "benchmark_sensitivity_status":  "fixture",
    "limitations":                   ["fixture limitation"],
    "warnings":                      [],
    "errors":                        [],
}


_ENDPOINT_SECTION_PAIRS: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("/demo/daily-market",        "daily",            _DAILY_FIXTURE),
    ("/demo/weekly-market",       "weekly",           _WEEKLY_FIXTURE),
    ("/demo/still-moving-market", "still_moving",     _STILL_MOVING_FIXTURE),
    ("/demo/evidence-summary",    "evidence_summary", _EVIDENCE_FIXTURE),
)


def _patched_sources():
    """Context manager bundle that pins every demo source module to
    a deterministic fixture and pins ``movers_cache.get_slice`` so the
    Still Moving endpoint's upstream lookup never touches the live
    cache.
    """
    return [
        patch.object(
            api._demo_daily_mod, "build_demo_daily_market",
            return_value=_DAILY_FIXTURE,
        ),
        patch.object(
            api._demo_weekly_mod, "build_demo_weekly_market",
            return_value=_WEEKLY_FIXTURE,
        ),
        patch.object(
            api._demo_still_moving_mod, "build_demo_still_moving_market",
            return_value=_STILL_MOVING_FIXTURE,
        ),
        patch.object(
            api._demo_evidence_summary_mod, "build_demo_evidence_summary",
            return_value=_EVIDENCE_FIXTURE,
        ),
        patch.object(
            api.movers_cache, "get_slice",
            return_value=[],
        ),
    ]


class _PatchAll:
    """Context manager wrapper that enters every patch in
    :func:`_patched_sources` and exits them on scope close.
    """

    def __init__(self) -> None:
        self._patches = _patched_sources()

    def __enter__(self) -> "_PatchAll":
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in reversed(self._patches):
            p.stop()


# ---------------------------------------------------------------------------
# Endpoint status + payload forwarding
# ---------------------------------------------------------------------------


class TestDemoEndpointStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def test_all_four_endpoints_return_http_200(self) -> None:
        with _PatchAll():
            for path, _, _ in _ENDPOINT_SECTION_PAIRS:
                response = self.client.get(path)
                self.assertEqual(
                    response.status_code, 200,
                    f"{path} returned {response.status_code}: "
                    f"{response.text[:200]}",
                )

    def test_each_endpoint_returns_its_patched_fixture_verbatim(self) -> None:
        with _PatchAll():
            for path, _, fixture in _ENDPOINT_SECTION_PAIRS:
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    response.json(), fixture,
                    f"{path} body diverged from patched fixture",
                )


# ---------------------------------------------------------------------------
# Section field values
# ---------------------------------------------------------------------------


class TestSectionValues(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def test_daily_section_is_daily(self) -> None:
        with _PatchAll():
            body = self.client.get("/demo/daily-market").json()
        self.assertEqual(body["section"], "daily")

    def test_weekly_section_is_weekly(self) -> None:
        with _PatchAll():
            body = self.client.get("/demo/weekly-market").json()
        self.assertEqual(body["section"], "weekly")

    def test_still_moving_section_is_still_moving(self) -> None:
        with _PatchAll():
            body = self.client.get("/demo/still-moving-market").json()
        self.assertEqual(body["section"], "still_moving")

    def test_evidence_summary_section_is_evidence_summary(self) -> None:
        with _PatchAll():
            body = self.client.get("/demo/evidence-summary").json()
        self.assertEqual(body["section"], "evidence_summary")


# ---------------------------------------------------------------------------
# Production surfaces remain unchanged
# ---------------------------------------------------------------------------


class TestProductionSurfacesUntouched(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def test_health_returns_status_ok(self) -> None:
        # ``/health`` is documented to return ``{"status": "ok"}``;
        # the demo wiring must not have replaced it.
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_movers_today_still_returns_a_list_not_a_demo_envelope(self) -> None:
        # ``/movers/today`` returns a bare list by default — a demo
        # envelope dict here would mean the demo Daily wiring leaked
        # into the production route.
        response = self.client.get("/movers/today")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIsInstance(
            body, list,
            f"/movers/today returned a non-list ({type(body).__name__}); "
            "demo wiring may have replaced the production route",
        )

    def test_movers_today_is_distinct_from_demo_daily_market(self) -> None:
        # Stronger pin: even with the demo Daily source patched, the
        # production /movers/today endpoint MUST NOT delegate to the
        # patched fixture.  If both endpoints returned the same body
        # we would know the demo wiring had short-circuited movers.
        with _PatchAll():
            demo_body  = self.client.get("/demo/daily-market").json()
            prod_body  = self.client.get("/movers/today").json()
        self.assertNotEqual(
            demo_body, prod_body,
            "production /movers/today returned the demo Daily fixture; "
            "demo wiring must not affect /movers/today",
        )


# ---------------------------------------------------------------------------
# No provider / LLM coupling
# ---------------------------------------------------------------------------


class TestNoProviderOrLlmCoupling(unittest.TestCase):
    """When every source module is patched, the demo endpoints must
    return exactly the patched payload.  A real provider / LLM call
    inside the endpoint would either modify the payload, raise, or
    leak external module state — none of which can happen here.
    """

    def setUp(self) -> None:
        self.client = TestClient(api.app)

    def test_patched_sources_make_responses_byte_for_byte_deterministic(self) -> None:
        with _PatchAll():
            first  = [self.client.get(p).json() for p, _, _ in _ENDPOINT_SECTION_PAIRS]
            second = [self.client.get(p).json() for p, _, _ in _ENDPOINT_SECTION_PAIRS]
        self.assertEqual(first, second)
        for response, (_, _, fixture) in zip(first, _ENDPOINT_SECTION_PAIRS):
            self.assertEqual(response, fixture)

    def test_each_source_function_called_exactly_once_per_request(self) -> None:
        # If an endpoint inadvertently fanned out to other providers,
        # the source mock's call_count would not be exactly 1.  The
        # Still Moving endpoint also exercises ``movers_cache.get_slice``
        # exactly once for the persistent slice.
        with patch.object(
            api._demo_daily_mod, "build_demo_daily_market",
            return_value=_DAILY_FIXTURE,
        ) as daily_mock, patch.object(
            api._demo_weekly_mod, "build_demo_weekly_market",
            return_value=_WEEKLY_FIXTURE,
        ) as weekly_mock, patch.object(
            api._demo_still_moving_mod, "build_demo_still_moving_market",
            return_value=_STILL_MOVING_FIXTURE,
        ) as still_mock, patch.object(
            api._demo_evidence_summary_mod, "build_demo_evidence_summary",
            return_value=_EVIDENCE_FIXTURE,
        ) as evidence_mock, patch.object(
            api.movers_cache, "get_slice",
            return_value=[],
        ) as cache_mock:
            self.client.get("/demo/daily-market")
            self.client.get("/demo/weekly-market")
            self.client.get("/demo/still-moving-market")
            self.client.get("/demo/evidence-summary")
        self.assertEqual(daily_mock.call_count,    1)
        self.assertEqual(weekly_mock.call_count,   1)
        self.assertEqual(still_mock.call_count,    1)
        self.assertEqual(evidence_mock.call_count, 1)
        # Still Moving is the only demo endpoint that consults
        # ``movers_cache.get_slice``; the other three must not.
        self.assertEqual(cache_mock.call_count, 1)
        args, kwargs = cache_mock.call_args
        self.assertEqual(args[0], "persistent")


if __name__ == "__main__":
    unittest.main()
