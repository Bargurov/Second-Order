"""
tests/test_monitor_plan.py

Contract tests for the monitoring-plan layer.

Two surfaces:
  1. Sanitizer — ``_clean_monitor_plan`` enforces the shape of the two
     net-new LLM-emitted fields (first_decisive_tell, no_call_signals)
     and collapses cleanly when both are missing.
  2. Composer — ``compute_monitor_plan`` unifies the LLM-emitted fields
     with derived views of horizon_checkpoints + competing_thesis so
     consumers can read one block instead of three.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

from analyze_event import (
    LLM_CORE_FIELDS,
    _clean_monitor_plan,
    _clean_first_decisive_tell,
    _clean_no_call_signal,
    build_analysis_dict,
)
from validation_plan import compute_monitor_plan


def _valid_tell() -> dict:
    return {
        "observation":   "CVX opens green on above-average volume and holds ≥+1%",
        "channel":       "equities",
        "what_it_means": "Desk is pricing the licence at face value — momentum into 5d",
    }


def _valid_no_call() -> dict:
    return {
        "observation": "Global crude rallies broadly across light-sweet and heavy-sour",
        "channel":     "commodities",
        "why_no_call": "Macro-wide commodity rally can't be explained by either thesis",
    }


# ---------------------------------------------------------------------------
# 1a. Sanitizer — first_decisive_tell
# ---------------------------------------------------------------------------

class TestFirstDecisiveTell(unittest.TestCase):

    def test_valid_tell_passes_with_forced_1d_timing(self):
        out = _clean_first_decisive_tell(_valid_tell())
        self.assertEqual(out["channel"], "equities")
        # Timing is always "1d" by definition — the sanitizer forces it
        # so an LLM that emits a longer timing gets corrected.
        self.assertEqual(out["timing"], "1d")

    def test_missing_meaning_rejects(self):
        raw = _valid_tell()
        raw["what_it_means"] = ""
        self.assertEqual(_clean_first_decisive_tell(raw), {})

    def test_invalid_channel_rejects(self):
        raw = _valid_tell()
        raw["channel"] = "sentiment"
        self.assertEqual(_clean_first_decisive_tell(raw), {})

    def test_non_dict_returns_empty(self):
        self.assertEqual(_clean_first_decisive_tell(None), {})
        self.assertEqual(_clean_first_decisive_tell("string"), {})


# ---------------------------------------------------------------------------
# 1b. Sanitizer — no_call_signal entries
# ---------------------------------------------------------------------------

class TestNoCallSignal(unittest.TestCase):

    def test_valid_entry_passes(self):
        out = _clean_no_call_signal(_valid_no_call())
        self.assertEqual(out["channel"], "commodities")
        self.assertIn("why_no_call", out)

    def test_missing_why_rejects(self):
        raw = _valid_no_call()
        raw["why_no_call"] = ""
        self.assertIsNone(_clean_no_call_signal(raw))

    def test_null_like_why_rejects(self):
        raw = _valid_no_call()
        raw["why_no_call"] = "N/A"
        self.assertIsNone(_clean_no_call_signal(raw))


# ---------------------------------------------------------------------------
# 1c. Sanitizer — top-level _clean_monitor_plan
# ---------------------------------------------------------------------------

class TestCleanMonitorPlan(unittest.TestCase):

    def test_valid_block_passes(self):
        out = _clean_monitor_plan({
            "first_decisive_tell": _valid_tell(),
            "no_call_signals":     [_valid_no_call()],
        })
        self.assertIn("first_decisive_tell", out)
        self.assertEqual(len(out["no_call_signals"]), 1)

    def test_both_empty_collapses_to_empty_dict(self):
        out = _clean_monitor_plan({
            "first_decisive_tell": {},
            "no_call_signals":     [],
        })
        self.assertEqual(out, {})

    def test_no_call_list_capped_at_three(self):
        raw = {"no_call_signals": [_valid_no_call() for _ in range(6)]}
        out = _clean_monitor_plan(raw)
        self.assertLessEqual(len(out["no_call_signals"]), 3)

    def test_only_no_call_still_emits(self):
        out = _clean_monitor_plan({"no_call_signals": [_valid_no_call()]})
        self.assertIn("no_call_signals", out)
        self.assertNotIn("first_decisive_tell", out)

    def test_non_dict_input_returns_empty(self):
        self.assertEqual(_clean_monitor_plan(None), {})
        self.assertEqual(_clean_monitor_plan("string"), {})


# ---------------------------------------------------------------------------
# 2. Registry
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):

    def test_monitor_plan_in_llm_core_fields(self):
        self.assertIn("monitor_plan", LLM_CORE_FIELDS)

    def test_missing_defaults_to_empty_dict(self):
        result = build_analysis_dict({"what_changed": "x"})
        self.assertEqual(result["monitor_plan"], {})


# ---------------------------------------------------------------------------
# 3. Composer — compute_monitor_plan unified view
# ---------------------------------------------------------------------------

class TestUnifiedComposer(unittest.TestCase):

    def test_empty_analysis_returns_unavailable(self):
        out = compute_monitor_plan({})
        self.assertFalse(out["available"])
        self.assertEqual(out["first_decisive_tell"], {})
        self.assertEqual(out["no_call_signals"], [])
        self.assertEqual(out["key_monitor_signals"], [])

    def test_llm_fields_flow_through(self):
        out = compute_monitor_plan({
            "monitor_plan": {
                "first_decisive_tell": _valid_tell() | {"timing": "1d"},
                "no_call_signals":     [_valid_no_call()],
            },
        })
        self.assertTrue(out["available"])
        self.assertEqual(out["first_decisive_tell"]["channel"], "equities")
        self.assertEqual(len(out["no_call_signals"]), 1)

    def test_key_monitor_signals_derived_from_horizon_expected(self):
        out = compute_monitor_plan({
            "horizon_checkpoints": {
                "horizons": [
                    {"horizon": "1d",  "expected": ["CVX +1-2%", "WCS-WTI flat"]},
                    {"horizon": "5d",  "expected": ["WCS-WTI widens ≥2pp"]},
                    {"horizon": "20d", "expected": ["Monthly imports ≥50kbd"]},
                ],
            },
        })
        # Only 1d + 5d expected bullets are flattened into key_monitor_signals
        horizons = {s["horizon"] for s in out["key_monitor_signals"]}
        self.assertEqual(horizons, {"1d", "5d"})
        self.assertEqual(len(out["key_monitor_signals"]), 3)

    def test_shift_to_alternative_reuses_competing_thesis_evidence(self):
        out = compute_monitor_plan({
            "competing_thesis": {
                "evidence_favoring_alternative": [
                    {"observation": "LRCX flat on carve-out rumours", "channel": "equities"},
                ],
            },
        })
        self.assertEqual(len(out["shift_to_alternative"]), 1)

    def test_confirm_first_vs_later_splits_by_horizon(self):
        out = compute_monitor_plan({
            "horizon_checkpoints": {
                "horizons": [
                    {"horizon": "1d",  "confirms_if": ["CVX closes green"]},
                    {"horizon": "5d",  "confirms_if": ["WCS-WTI widens"]},
                    {"horizon": "20d", "confirms_if": ["Monthly imports confirm"]},
                ],
            },
        })
        first_obs = [e["observation"] for e in out["confirm_first_vs_later"]["first"]]
        later_obs = [e["observation"] for e in out["confirm_first_vs_later"]["later"]]
        self.assertIn("CVX closes green", first_obs)
        self.assertIn("WCS-WTI widens", later_obs)
        self.assertIn("Monthly imports confirm", later_obs)
        # 1d split from 5d/20d — no cross-contamination
        self.assertNotIn("CVX closes green", later_obs)

    def test_missing_sources_still_returns_shaped_dict(self):
        out = compute_monitor_plan({"what_changed": "x"})  # nothing else
        self.assertIn("confirm_first_vs_later", out)
        self.assertIn("first", out["confirm_first_vs_later"])
        self.assertIn("later", out["confirm_first_vs_later"])


if __name__ == "__main__":
    unittest.main()
