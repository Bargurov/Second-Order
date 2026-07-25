"""Parity tests for /analyze and /analyze/stream ticker selection.

Both endpoints must run the same post-LLM asset-selection discipline
before the market-check call:

* Broad-market indices (SPY/QQQ/...), price benchmarks (^VIX/^TNX/...),
  foreign-listing suffixes, and inverse / vol / FX hedge ETFs MUST be
  filtered out of the ticker list that ships to ``market_check``.
* The ``asset_selection`` block from
  ``asset_selection.classify_and_rank_assets`` MUST appear on the
  ``analysis`` payload — both in the JSON response (``/analyze``) and
  in the streaming ``analysis`` and ``complete`` events
  (``/analyze/stream``).
* The cleaned beneficiary / loser ticker lists passed to
  ``market_check`` MUST be byte-identical between the two endpoints
  for the same input.

Pre-fix behaviour: ``/analyze`` already does this (routes/analyze.py
lines 460-477 of the pre-fix file).  ``/analyze/stream`` shipped the
RAW LLM lists straight to ``market_check``, never invoking
``classify_and_rank_assets`` and never populating
``analysis["asset_selection"]``.  That's the divergence these tests
pin closed.

No provider seam (``market_check``, ``analyze_event``, ``compute_*``,
``classify_*``) is reached — every external boundary is patched out so
the suite stays no-paid and yfinance-free.
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "")

import api  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic LLM analysis carrying a deliberately polluted ticker mix:
#
#   beneficiary_tickers:
#     XOM   -> direct single-name (kept)
#     SPY   -> broad-market index (dropped, "too_broad")
#     VXX   -> vol hedge (dropped from cleaned list — hedge_signal tier)
#     ^VIX  -> price benchmark (dropped, "too_broad")
#   loser_tickers:
#     PBF   -> direct single-name (kept)
#     QQQ   -> broad-market index (dropped, "too_broad")
#     7203.T -> foreign suffix (dropped, "weak_exposure")
#
# The cleaned lists must therefore be exactly:
#     beneficiaries: ["XOM"]
#     losers:        ["PBF"]
# regardless of whether the request hit /analyze or /analyze/stream.
#
# mechanism_family is None so sector-ETF promotion does NOT come into
# play — the assertions are family-agnostic.
# ---------------------------------------------------------------------------
_POLLUTED_ANALYSIS: dict = {
    "what_changed":        "Synthetic ticker-selection parity event",
    "mechanism_summary":   "Test mechanism for parity coverage",
    "beneficiaries":       [],
    "losers":              [],
    "beneficiary_tickers": ["XOM", "SPY", "VXX", "^VIX"],
    "loser_tickers":       ["PBF", "QQQ", "7203.T"],
    "assets_to_watch":     [],
    "confidence":          "low",
    "transmission_chain":  [],
    "if_persists":         {},
    "currency_channel":    {},
    "mechanism_family":    None,
}


_EXPECTED_CLEANED_BENEFICIARIES: tuple[str, ...] = ("XOM",)
_EXPECTED_CLEANED_LOSERS:        tuple[str, ...] = ("PBF",)


class _PatchStack:
    """Context manager wrapping the no-provider patch stack used by both
    /analyze and /analyze/stream parity tests.

    Mirrors the stub strategy in test_analyze_persistence_failure.py so
    every external seam — LLM, market_check, macro overlays — is patched
    to an in-memory return value.  ``api.market_check`` is wrapped with
    a ``MagicMock`` so the test can inspect ``call_args`` and prove
    which ticker list reached the provider boundary.
    """

    def __enter__(self):
        self._stack = ExitStack().__enter__()

        # Cache misses: force the flow past the headline / event_id
        # short-circuits and into the analyze pipeline proper.
        self._stack.enter_context(patch(
            "api.find_cached_analysis", return_value=None,
        ))
        self._stack.enter_context(patch(
            "api.load_event_by_id", return_value=None,
        ))

        # LLM seam.  Each call returns a fresh dict so per-test mutation
        # of ``analysis`` doesn't bleed across cases.
        self._stack.enter_context(patch(
            "api.analyze_event",
            side_effect=lambda *a, **k: dict(_POLLUTED_ANALYSIS),
        ))

        # Pure classifiers — return literal values.
        self._stack.enter_context(patch(
            "api.classify_stage", return_value="developing",
        ))
        self._stack.enter_context(patch(
            "api.classify_persistence", return_value="medium",
        ))

        # Provider boundary.  MagicMock so call_args is captured.
        self.market_mock = MagicMock(return_value={
            "tickers": [], "note": "test", "rejected": [],
        })
        self._stack.enter_context(patch(
            "api.market_check", new=self.market_mock,
        ))

        # Persistence: succeed silently so the response carries the
        # post-market analysis dict the test reads.
        self._stack.enter_context(patch(
            "api.save_event", return_value=None,
        ))

        # Macro overlays — return empty dicts so the composers don't
        # spider into rates / stress data the test isn't pinning.
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
            "build_macro_context_for_prompt",
        ):
            if hasattr(api, name):
                self._stack.enter_context(patch.object(
                    api, name, return_value={},
                ))

        # Helpers that must return list-shaped values.
        self._stack.enter_context(patch(
            "api.find_historical_analogs", return_value=[],
        ))
        self._stack.enter_context(patch(
            "api.load_recent_events", return_value=[],
        ))

        return self

    def __exit__(self, *exc_info):
        return self._stack.__exit__(*exc_info)


def _market_check_call_lists(market_mock: MagicMock) -> tuple[list[str], list[str]]:
    """Extract (beneficiary_list, loser_list) actually passed to
    ``api.market_check`` so the test can compare against the expected
    cleaned lists.  Reads positional or keyword form."""
    assert market_mock.call_args is not None, (
        "market_check was never called — pipeline must reach the "
        "provider boundary for the parity assertion to be meaningful"
    )
    args, kwargs = market_mock.call_args
    if len(args) >= 2:
        ben, los = args[0], args[1]
    else:
        ben = kwargs.get("beneficiary_tickers") or kwargs.get("ben") or []
        los = kwargs.get("loser_tickers") or kwargs.get("los") or []
    return list(ben), list(los)


# ---------------------------------------------------------------------------
# /analyze JSON
# ---------------------------------------------------------------------------


class TestAnalyzeJsonTickerSelection(unittest.TestCase):

    def test_market_check_receives_cleaned_lists(self) -> None:
        with _PatchStack() as stack:
            api.analyze(api.AnalyzeRequest(headline="Parity test JSON", confirm_paid=True))
            ben, los = _market_check_call_lists(stack.market_mock)
        self.assertEqual(
            ben, list(_EXPECTED_CLEANED_BENEFICIARIES),
            f"market_check received uncleaned beneficiaries: {ben!r}",
        )
        self.assertEqual(
            los, list(_EXPECTED_CLEANED_LOSERS),
            f"market_check received uncleaned losers: {los!r}",
        )

    def test_response_carries_asset_selection_block(self) -> None:
        with _PatchStack():
            resp = api.analyze(api.AnalyzeRequest(headline="Parity test JSON", confirm_paid=True))
        analysis = resp.get("analysis") or {}
        sel = analysis.get("asset_selection") or {}
        self.assertEqual(
            list(sel.get("cleaned_beneficiary_tickers") or []),
            list(_EXPECTED_CLEANED_BENEFICIARIES),
        )
        self.assertEqual(
            list(sel.get("cleaned_loser_tickers") or []),
            list(_EXPECTED_CLEANED_LOSERS),
        )
        excluded_symbols = {
            e.get("symbol") for e in (sel.get("excluded") or [])
        }
        # Every polluted symbol must show up in the audit trail.
        for sym in ("SPY", "^VIX", "QQQ", "7203.T"):
            self.assertIn(
                sym, excluded_symbols,
                f"{sym} must appear in asset_selection.excluded",
            )


# ---------------------------------------------------------------------------
# /analyze/stream SSE
# ---------------------------------------------------------------------------


def _post_stream(body: dict) -> str:
    return TestClient(api.app).post(
        "/analyze/stream", json={**body, "confirm_paid": True}).text


def _parse_events(raw: str) -> list[dict]:
    out: list[dict] = []
    for line in raw.strip().split("\n"):
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


class TestAnalyzeStreamTickerSelection(unittest.TestCase):

    def test_stream_market_check_receives_cleaned_lists(self) -> None:
        with _PatchStack() as stack:
            _post_stream({"headline": "Parity test stream"})
            ben, los = _market_check_call_lists(stack.market_mock)
        self.assertEqual(
            ben, list(_EXPECTED_CLEANED_BENEFICIARIES),
            f"stream market_check received uncleaned beneficiaries: "
            f"{ben!r} — broad-market / hedge / index tickers slipped "
            f"through to the provider",
        )
        self.assertEqual(
            los, list(_EXPECTED_CLEANED_LOSERS),
            f"stream market_check received uncleaned losers: {los!r}",
        )

    def test_stream_complete_event_carries_asset_selection(self) -> None:
        with _PatchStack():
            body = _post_stream({"headline": "Parity test stream"})
        events = _parse_events(body)
        complete = [e for e in events if e.get("_phase") == "complete"]
        self.assertTrue(complete, f"missing complete event: {events!r}")
        analysis = (complete[-1].get("analysis") or {})
        sel = analysis.get("asset_selection") or {}
        self.assertEqual(
            list(sel.get("cleaned_beneficiary_tickers") or []),
            list(_EXPECTED_CLEANED_BENEFICIARIES),
        )
        self.assertEqual(
            list(sel.get("cleaned_loser_tickers") or []),
            list(_EXPECTED_CLEANED_LOSERS),
        )

    def test_stream_analysis_event_carries_asset_selection(self) -> None:
        # The mid-stream "analysis" event currently fires immediately
        # after pre-market overlays.  The fix moves the asset-selection
        # step to BEFORE that emit so streaming clients see the cleaned
        # lists in the same SSE event they already consume — without
        # introducing a new event type.
        with _PatchStack():
            body = _post_stream({"headline": "Parity test stream"})
        events = _parse_events(body)
        analysis_events = [e for e in events if e.get("_phase") == "analysis"]
        self.assertTrue(
            analysis_events, f"missing analysis event: {events!r}",
        )
        sel = (analysis_events[-1].get("analysis") or {}).get("asset_selection") or {}
        self.assertEqual(
            list(sel.get("cleaned_beneficiary_tickers") or []),
            list(_EXPECTED_CLEANED_BENEFICIARIES),
        )
        self.assertEqual(
            list(sel.get("cleaned_loser_tickers") or []),
            list(_EXPECTED_CLEANED_LOSERS),
        )


# ---------------------------------------------------------------------------
# Cross-endpoint parity — strongest single assertion: same input, same
# cleaned lists at the provider boundary on both endpoints.
# ---------------------------------------------------------------------------


class TestEndpointParity(unittest.TestCase):

    def test_market_check_lists_identical_across_endpoints(self) -> None:
        with _PatchStack() as stack:
            api.analyze(api.AnalyzeRequest(headline="Parity duplicate", confirm_paid=True))
            json_ben, json_los = _market_check_call_lists(stack.market_mock)

        with _PatchStack() as stack:
            _post_stream({"headline": "Parity duplicate"})
            stream_ben, stream_los = _market_check_call_lists(stack.market_mock)

        self.assertEqual(
            json_ben, stream_ben,
            f"beneficiary lists diverge: JSON={json_ben!r} stream={stream_ben!r}",
        )
        self.assertEqual(
            json_los, stream_los,
            f"loser lists diverge: JSON={json_los!r} stream={stream_los!r}",
        )

    def test_asset_selection_block_present_on_both_endpoints(self) -> None:
        with _PatchStack():
            json_resp = api.analyze(
                api.AnalyzeRequest(headline="Parity duplicate", confirm_paid=True),
            )

        with _PatchStack():
            stream_body = _post_stream({"headline": "Parity duplicate"})
        stream_complete = [
            e for e in _parse_events(stream_body)
            if e.get("_phase") == "complete"
        ]
        self.assertTrue(stream_complete)

        json_sel = (json_resp.get("analysis") or {}).get("asset_selection") or {}
        stream_sel = (
            (stream_complete[-1].get("analysis") or {}).get("asset_selection")
            or {}
        )

        for label, sel in (("/analyze", json_sel), ("/analyze/stream", stream_sel)):
            self.assertTrue(
                sel,
                f"{label} response must carry analysis.asset_selection",
            )
            self.assertIn("cleaned_beneficiary_tickers", sel)
            self.assertIn("cleaned_loser_tickers", sel)


if __name__ == "__main__":
    unittest.main()
