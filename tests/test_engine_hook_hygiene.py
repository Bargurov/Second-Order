"""Engine hook hygiene — silent except blocks must log warnings, and
returned analysis dicts must not leak internal scratch fields.

Covers:
  * ``_strip_scratch_fields`` removes any ``_*`` key.
  * ``_finalize_analysis`` does NOT return underscore-prefixed scratch
    fields (``_raw_beneficiary_tickers`` / ``_raw_loser_tickers``).
  * ``_degraded_fallback`` does NOT leak scratch fields either.
  * AnalysisResult TypedDict declares ``degraded``,
    ``validation_warnings``, ``evidence_sources``.
  * Engine validation/traceability hook failures emit a logger
    warning instead of silently swallowing the exception.
"""

from __future__ import annotations

import logging
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import analyze_event
import thesis_state
from analyze_event import (
    AnalysisResult,
    _degraded_fallback,
    _finalize_analysis,
    _strip_scratch_fields,
)


# ---------------------------------------------------------------------------
# Scratch-field strip helper
# ---------------------------------------------------------------------------

class TestStripScratchFields(unittest.TestCase):
    def test_drops_underscore_prefixed_keys(self):
        d = {
            "what_changed": "x",
            "_raw_beneficiary_tickers": ["XOM"],
            "_raw_loser_tickers": ["DAL"],
            "_some_other_scratch": {"a": 1},
            "mechanism_summary": "y",
        }
        out = _strip_scratch_fields(d)
        self.assertNotIn("_raw_beneficiary_tickers", out)
        self.assertNotIn("_raw_loser_tickers", out)
        self.assertNotIn("_some_other_scratch", out)
        self.assertEqual(out["what_changed"], "x")
        self.assertEqual(out["mechanism_summary"], "y")

    def test_preserves_non_underscore_keys(self):
        d = {"a": 1, "b": 2, "_c": 3}
        out = _strip_scratch_fields(d)
        self.assertEqual(out, {"a": 1, "b": 2})

    def test_non_dict_input_returned_as_is(self):
        self.assertIsNone(_strip_scratch_fields(None))
        self.assertEqual(_strip_scratch_fields("string"), "string")


# ---------------------------------------------------------------------------
# End-to-end pipeline never leaks scratch fields
# ---------------------------------------------------------------------------

_PARSED_GOOD = {
    "what_changed": (
        "The US Commerce Department added 28 Chinese semiconductor firms "
        "to the Entity List, restricting export of advanced chips."
    ),
    "mechanism_summary": (
        "Entity List restrictions cut Chinese fabs off from US-origin "
        "semiconductor capital equipment, tightening capex pipelines and "
        "shifting orders toward TSM and Korean foundries."
    ),
    "beneficiaries": ["TSMC"],
    "losers":         ["SMIC"],
    "beneficiary_tickers": ["TSM"],
    "loser_tickers":       ["LRCX", "AMAT"],
    "confidence": "medium",
    "transmission_chain": [
        "US Commerce expands Entity List",
        "TSMC absorbs reallocated demand",
        "Lam / AMAT lose Chinese order book",
    ],
    "transmission_path": [
        {"hop": "Commerce expands Entity List",
         "actor": "US Commerce", "channel": "policy",
         "expected_market_effect": "Chinese fab capex restricted",
         "timing": "0-5d"},
        {"hop": "Order reallocation to TSM",
         "actor": "TSMC", "channel": "equities",
         "expected_market_effect": "TSM rerates higher",
         "timing": "5-30d"},
    ],
    "mechanism_family": "tariff",
    "expected_first_order_channels":  ["policy"],
    "expected_second_order_channels": ["equities"],
}


class TestPipelineNoScratchLeak(unittest.TestCase):
    def test_finalize_analysis_strips_raw_ticker_fields(self):
        out = _finalize_analysis(
            _PARSED_GOOD,
            headline="US Commerce expands Entity List",
            stage="realized", persistence="structural",
        )
        self.assertNotIn("_raw_beneficiary_tickers", out)
        self.assertNotIn("_raw_loser_tickers", out)
        # Sanity: no underscore-prefixed key whatsoever.
        for key in out:
            self.assertFalse(
                isinstance(key, str) and key.startswith("_"),
                msg=f"scratch field {key!r} leaked into finalize output",
            )

    def test_finalize_analysis_preserves_public_fields(self):
        out = _finalize_analysis(
            _PARSED_GOOD,
            headline="US Commerce expands Entity List",
            stage="realized", persistence="structural",
        )
        # Public ticker lists must survive the strip pass.
        self.assertIn("beneficiary_tickers", out)
        self.assertIn("loser_tickers", out)
        self.assertTrue(out["beneficiary_tickers"])

    def test_degraded_fallback_has_no_scratch_fields(self):
        # Trigger the degraded path with intentionally thin parsed input.
        out = _finalize_analysis(
            {"what_changed": "x", "mechanism_summary": "y"},
            headline="thin", stage="realized", persistence="structural",
        )
        for key in out:
            self.assertFalse(
                isinstance(key, str) and key.startswith("_"),
                msg=f"scratch field {key!r} leaked into degraded fallback",
            )

    def test_degraded_fallback_direct_call_has_no_scratch_fields(self):
        out = _degraded_fallback(
            "thin headline", "realized", "structural",
            "thin mechanism + no chain + no entities",
        )
        for key in out:
            self.assertFalse(
                isinstance(key, str) and key.startswith("_"),
                msg=f"scratch field {key!r} leaked into degraded fallback",
            )


# ---------------------------------------------------------------------------
# TypedDict declarations
# ---------------------------------------------------------------------------

class TestAnalysisResultTypedDictDeclarations(unittest.TestCase):
    def test_typed_dict_declares_validation_flags(self):
        annotations = AnalysisResult.__annotations__
        self.assertIn("degraded", annotations)
        self.assertIn("validation_warnings", annotations)

    def test_typed_dict_declares_evidence_sources(self):
        # Top-level evidence_sources is read by eval.py and produced by
        # several engine modules (evidence_attribution, evidence_ladder,
        # reaction_function_divergence) — must be declared.
        annotations = AnalysisResult.__annotations__
        self.assertIn("evidence_sources", annotations)


# ---------------------------------------------------------------------------
# Hook failures emit warnings (no silent passes)
# ---------------------------------------------------------------------------

class TestHookFailuresLogWarnings(unittest.TestCase):
    def test_persistence_signal_hook_failure_logs_warning(self):
        # _get_persistence_status falls back through the
        # classify_persistence_signal import; a failure must surface
        # as a warning, not a silent pass.
        with patch(
            "persistence_signal.classify_persistence_signal",
            side_effect=RuntimeError("simulated hook failure"),
        ):
            with self.assertLogs(
                "second_order.thesis_state", level=logging.WARNING,
            ) as cm:
                result = thesis_state._get_persistence_status({})
        self.assertIsNone(result)
        self.assertTrue(any(
            "persistence_signal" in line for line in cm.output
        ))

    def test_evidence_sources_import_failure_logs_warning(self):
        # When the evidence_sources traceability module is unavailable,
        # _validate_result must log a warning rather than silently
        # skipping the high-confidence cap.  Setting the module entry
        # in sys.modules to None forces the ``from evidence_sources
        # import …`` statement to raise ImportError, simulating a
        # missing / broken traceability dependency.
        result = {
            "mechanism_summary": "x" * 50,
            "beneficiaries": ["Exxon"],
            "losers": ["Delta"],
            "beneficiary_tickers": ["XOM"],
            "loser_tickers": ["DAL"],
            "confidence": "high",
            "transmission_chain": [
                "step one", "step two", "step three",
            ],
            "competing_thesis": {
                "evidence_sources": [
                    {"source_url": "http://example.com",
                     "source_quality": "primary"},
                ],
            },
        }
        with patch.dict("sys.modules", {"evidence_sources": None}):
            with self.assertLogs(
                "second_order.analyze_event", level=logging.WARNING,
            ) as cm:
                analyze_event._validate_result(result, stage="realized")
        self.assertTrue(any(
            "evidence_sources" in line for line in cm.output
        ))


if __name__ == "__main__":
    unittest.main()
