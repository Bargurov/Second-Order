"""Tests for explicit /analyze persistence-failure surfacing.

The pre-fix behaviour: ``api._persist_event`` swallowed every exception
from ``save_event`` with a single ``print()`` line.  Both ``/analyze``
and ``/analyze/stream`` then returned their normal success response,
so a caller had no way to tell that the row was lost.

These tests pin the explicit-failure contract:

* ``_persist_event`` returns ``(None, saved_id)`` on success and
  ``(short error message, None)`` on failure (without re-raising —
  every existing caller relies on the function not raising past the
  boundary).
* ``/analyze`` JSON response carries ``persistence_failed: bool``.
  When the underlying ``save_event`` raises, ``persistence_failed`` is
  ``True`` and ``persistence_error`` carries a short reason string.
  On a clean run, ``persistence_failed`` is ``False`` and
  ``persistence_error`` is ``None``.
* ``/analyze/stream``'s final ``complete`` SSE event carries the same
  two fields with the same semantics.
* The mock-fallback path is untouched — it never invokes
  ``_persist_event``, so the new fields are absent from the failure
  response (matching the pre-fix shape).

No provider seam (``market_check``, ``analyze_event``,
``compute_*``, ``classify_*``) is reached — every external boundary
is patched out.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# A real-shaped LLM analysis stub — every field ``_persist_event``
# reads from ``analysis`` is populated, so the persist path runs all
# the way to ``save_event`` instead of hitting an early ``KeyError``.
_REAL_ANALYSIS: dict = {
    "what_changed":        "Synthetic test mechanism",
    "mechanism_summary":   "Test mechanism for persistence failure",
    "beneficiaries":       [],
    "losers":              [],
    "beneficiary_tickers": [],
    "loser_tickers":       [],
    "assets_to_watch":     [],
    "confidence":          "low",
    "transmission_chain":  [],
    "if_persists":         {},
    "currency_channel":    {},
}


def _patched_pipeline_no_provider():
    """Stack of patches that lets the analyze flow run end-to-end
    against in-memory stubs.

    No provider seam is reached: ``analyze_event`` (LLM) returns a
    real-shaped analysis, ``market_check`` returns an empty fixture,
    ``find_cached_analysis`` and ``load_event_by_id`` return ``None``
    so the flow proceeds to the persist step, and every macro overlay
    composer that would otherwise touch yfinance / market_data is
    patched to a no-op stub.

    Tests then layer one more patch on top — typically
    ``api.save_event`` — to control the persistence outcome.
    """
    return _PatchStack()


class _PatchStack:
    """Context manager wrapping the no-provider patch stack."""

    def __enter__(self):
        from contextlib import ExitStack
        self._stack = ExitStack().__enter__()

        # Cache lookups must miss so the flow proceeds to the persist
        # step.  ``load_event_by_id`` always returns None because the
        # tests don't pass ``event_id`` in the request, but patching
        # it explicitly keeps the stack hermetic.
        self._stack.enter_context(patch(
            "api.find_cached_analysis", return_value=None,
        ))
        self._stack.enter_context(patch(
            "api.load_event_by_id", return_value=None,
        ))

        # LLM seam.
        self._stack.enter_context(patch(
            "api.analyze_event", return_value=dict(_REAL_ANALYSIS),
        ))

        # Pure classifiers — return literal values so the flow
        # doesn't depend on keyword-matching against the synthetic
        # headline.
        self._stack.enter_context(patch(
            "api.classify_stage", return_value="developing",
        ))
        self._stack.enter_context(patch(
            "api.classify_persistence", return_value="medium",
        ))

        # Provider boundary.
        self._stack.enter_context(patch(
            "api.market_check", return_value={
                "tickers": [], "note": "test", "rejected": [],
            },
        ))

        # Macro overlays — return empty dicts so the composers don't
        # run their full code path against missing rates/stress data.
        for name in (
            "compute_rates_context",
            "build_real_yield_context",
            "compute_stress_regime",
            "compute_shock_decomposition",
            "compute_policy_constraint",
            "compute_reaction_function_divergence",
            "classify_credit_regime",
            "build_regime_vector",
            "classify_inventory_context",
            "find_historical_analogs",
            "compute_pre_event_drift",
            "compute_surprise_vs_anticipation",
            "compute_terms_of_trade",
            "compute_reserve_stress",
            "compute_narrative_divergence",
            "compute_credit_transmission",
            "classify_thesis",
            "compute_cross_asset_confirmation",
            "compute_sector_passthrough",
            "get_confidence_calibration_stats",
            "classify_policy_sensitivity",
            "load_recent_events",
            "build_macro_context_for_prompt",
        ):
            if hasattr(api, name):
                self._stack.enter_context(patch.object(
                    api, name, return_value={},
                ))

        # ``find_historical_analogs`` returns a list, not a dict.
        # Override the {} stub above with [].
        self._stack.enter_context(patch(
            "api.find_historical_analogs", return_value=[],
        ))
        # Same for load_recent_events.
        self._stack.enter_context(patch(
            "api.load_recent_events", return_value=[],
        ))

        return self

    def __exit__(self, *exc_info):
        return self._stack.__exit__(*exc_info)


# ---------------------------------------------------------------------------
# _persist_event return-contract — pinned at the function boundary so
# both /analyze and /analyze/stream can read a single value to decide
# whether to surface the failure flag.
# ---------------------------------------------------------------------------


class TestPersistEventReturnContract(unittest.TestCase):

    def _minimal_args(self) -> dict:
        return dict(
            headline="t", stage="developing", persistence="medium",
            analysis=dict(_REAL_ANALYSIS),
            mkt={"tickers": [], "note": "t", "rejected": []},
            effective_date="2026-01-01",
            model="test-model",
        )

    def test_returns_none_error_and_the_saved_id_on_success(self) -> None:
        # save_event returning normally must surface a ``None`` error so
        # callers can treat a truthy error == failure, and hand back the
        # numeric id the save produced — the only id a candidate link may
        # ever be stamped with.
        with patch("api.save_event", return_value=41):
            error, event_id = api._persist_event(**self._minimal_args())
        self.assertIsNone(error)
        self.assertEqual(event_id, 41)

    def test_returns_error_string_and_no_id_on_save_event_failure(self) -> None:
        with patch(
            "api.save_event",
            side_effect=RuntimeError("disk full"),
        ):
            error, event_id = api._persist_event(**self._minimal_args())
        self.assertIsInstance(error, str)
        self.assertIn("disk full", error)
        self.assertIsNone(event_id)

    def test_does_not_propagate_save_event_exception(self) -> None:
        # Existing callers (movers backfill, /analyze, /analyze/stream)
        # depend on _persist_event never raising past the boundary.
        # Surfacing failure via the return value preserves that.
        with patch(
            "api.save_event",
            side_effect=RuntimeError("disk full"),
        ):
            try:
                api._persist_event(**self._minimal_args())
            except Exception as exc:  # pragma: no cover - assertion path
                self.fail(
                    f"_persist_event must not propagate save_event "
                    f"exceptions; raised {type(exc).__name__}: {exc}"
                )


# ---------------------------------------------------------------------------
# /analyze JSON — explicit persistence_failed/error fields
# ---------------------------------------------------------------------------


class TestAnalyzePersistenceFailure(unittest.TestCase):

    def test_save_event_failure_marks_persistence_failed_true(self) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            resp = api.analyze(api.AnalyzeRequest(headline="Test headline", confirm_paid=True))
        self.assertTrue(
            resp.get("persistence_failed"),
            f"persistence_failed must be True on save_event failure; "
            f"got {resp.get('persistence_failed')!r}",
        )

    def test_save_event_failure_carries_error_message(self) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            resp = api.analyze(api.AnalyzeRequest(headline="Test headline", confirm_paid=True))
        self.assertIn("disk full", resp.get("persistence_error") or "")

    def test_save_event_success_marks_persistence_failed_false(self) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", return_value=None,
        ):
            resp = api.analyze(api.AnalyzeRequest(headline="Test headline", confirm_paid=True))
        self.assertIn("persistence_failed", resp)
        self.assertFalse(
            resp["persistence_failed"],
            "persistence_failed must be False on a clean run",
        )
        self.assertIsNone(
            resp.get("persistence_error"),
            "persistence_error must be None on a clean run",
        )

    def test_failure_response_still_carries_normal_payload(self) -> None:
        # The brief calls for an "explicit persistence_failed/degraded
        # response" — additive, not replacing the rest of the payload.
        # Operators need the analysis output even when the row was
        # lost so they can investigate without re-running the LLM.
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            resp = api.analyze(api.AnalyzeRequest(headline="Test headline", confirm_paid=True))
        for key in (
            "headline", "stage", "persistence", "analysis",
            "market", "freshness", "is_mock", "event_date",
        ):
            self.assertIn(key, resp, f"missing key on failure response: {key}")

    def test_failure_path_does_not_invoke_provider_seams(self) -> None:
        # Defense-in-depth: even with save_event raising, the failure
        # plumbing must not retry or invoke any provider seam.  Patch
        # the dangerous seams to raise on call so an accidental retry
        # would trip here.
        forbidden = [
            "market_check._fetch",
            "market_check._fetch_since",
            "price_cache.fetch_daily_cached",
        ]
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            from contextlib import ExitStack
            with ExitStack() as stack:
                for dotted in forbidden:
                    mod_name, attr = dotted.rsplit(".", 1)
                    try:
                        mod = __import__(mod_name)
                    except Exception:
                        continue
                    if not hasattr(mod, attr):
                        continue
                    stack.enter_context(patch.object(
                        mod, attr,
                        side_effect=AssertionError(
                            f"persistence-failure path must not call {dotted}",
                        ),
                    ))
                resp = api.analyze(
                    api.AnalyzeRequest(headline="Test headline", confirm_paid=True),
                )
        self.assertTrue(resp.get("persistence_failed"))


# ---------------------------------------------------------------------------
# /analyze/stream — final ``complete`` SSE event carries the same
# fields so streaming consumers see the failure too.
# ---------------------------------------------------------------------------


class TestAnalyzeStreamPersistenceFailure(unittest.TestCase):

    def _post_stream(self, body: dict) -> str:
        client = TestClient(api.app)
        return client.post(
            "/analyze/stream", json={**body, "confirm_paid": True}).text

    def _parse_events(self, body: str) -> list[dict]:
        events: list[dict] = []
        for line in body.strip().split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
        return events

    def test_stream_save_event_failure_marks_complete_event_failed(
        self,
    ) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            body = self._post_stream({"headline": "Test stream headline"})

        events = self._parse_events(body)
        complete = [e for e in events if e.get("_phase") == "complete"]
        self.assertTrue(
            complete,
            f"expected at least one complete event, got phases "
            f"{[e.get('_phase') for e in events]}",
        )
        last = complete[-1]
        self.assertTrue(
            last.get("persistence_failed"),
            f"complete event must mark persistence_failed=True; got "
            f"{last.get('persistence_failed')!r}",
        )
        self.assertIn("disk full", last.get("persistence_error") or "")

    def test_stream_save_event_success_marks_complete_event_clean(self) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", return_value=None,
        ):
            body = self._post_stream({"headline": "Test stream healthy"})

        events = self._parse_events(body)
        complete = [e for e in events if e.get("_phase") == "complete"]
        self.assertTrue(complete)
        last = complete[-1]
        self.assertIn("persistence_failed", last)
        self.assertFalse(last["persistence_failed"])
        self.assertIsNone(last.get("persistence_error"))

    def test_stream_failure_event_still_carries_full_complete_payload(
        self,
    ) -> None:
        with _patched_pipeline_no_provider(), patch(
            "api.save_event", side_effect=RuntimeError("disk full"),
        ):
            body = self._post_stream({"headline": "Test stream payload"})

        events = self._parse_events(body)
        complete = [e for e in events if e.get("_phase") == "complete"]
        self.assertTrue(complete)
        last = complete[-1]
        for key in (
            "headline", "stage", "persistence", "analysis",
            "market", "freshness", "is_mock", "event_date",
        ):
            self.assertIn(key, last, f"missing key on stream failure: {key}")


# ---------------------------------------------------------------------------
# Mock-fallback regression guard
# ---------------------------------------------------------------------------


class TestMockFallbackUnaffected(unittest.TestCase):
    """The mock-fallback short-circuit (LLM unavailable / overloaded)
    never reaches ``_persist_event`` — the failure path is owned by
    ``_mock_failure_response``.  These tests pin that the new
    ``persistence_failed`` field stays absent on that path so an
    operator can still distinguish "LLM mock fallback" from "save_event
    blew up after a real LLM run."
    """

    def test_mock_fallback_response_omits_persistence_fields(self) -> None:
        from analyze_event import _mock

        persist_mock = MagicMock(return_value=(None, 1))  # (error, saved id)
        with patch("api.analyze_event", return_value=_mock("overloaded")), \
             patch("api.classify_stage", return_value="developing"), \
             patch("api.classify_persistence", return_value="medium"), \
             patch("api._persist_event", persist_mock), \
             patch("api.market_check") as market_mock, \
             patch("api.find_cached_analysis", return_value=None), \
             patch("api.load_event_by_id", return_value=None):
            resp = api.analyze(
                api.AnalyzeRequest(headline="Mock fallback headline", confirm_paid=True),
            )

        # Mock fallback never reaches the persist step or the provider.
        persist_mock.assert_not_called()
        market_mock.assert_not_called()

        # The mock failure path is owned by _mock_failure_response,
        # which carries its own analysis_failed/is_mock fields and
        # does NOT learn the persistence_failed field — its persist
        # step never ran.
        self.assertTrue(resp.get("is_mock"))
        self.assertTrue(resp.get("analysis_failed"))
        self.assertNotIn(
            "persistence_failed", resp,
            "mock-fallback response must not carry persistence_failed; "
            f"got {resp!r}",
        )


if __name__ == "__main__":
    unittest.main()
