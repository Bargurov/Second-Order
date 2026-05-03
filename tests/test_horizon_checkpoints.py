"""Tests for the horizon-aware checkpoints field on analysis output.

Covers:
  - _clean_horizon_checkpoints normalization (shape, timing profile,
    canonical 1d/5d/20d horizons, list caps, dedup, tolerance to
    missing / dict-form / legacy inputs)
  - horizon_checkpoints flows through _normalize_schema into the LLM
    analysis result
  - DB save/load roundtrip preserves the dict structure (no JSON-string
    leakage on readback)
  - mock / degraded-fallback paths emit a stable shape
"""

import json
import os
import sqlite3
import sys
import unittest
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze_event import (
    LLM_CORE_FIELDS,
    _LLM_CORE_DEFAULTS,
    _clean_horizon_checkpoints,
    _normalize_schema,
    _degraded_fallback,
    _mock,
    _TIMING_PROFILE_ENUM,
    _CANONICAL_HORIZONS,
)
import db


def _tmp_db() -> str:
    return os.path.join(os.path.dirname(__file__),
                        f"test_horizon_{uuid.uuid4().hex}.db")


class TestCleanHorizonCheckpoints(unittest.TestCase):
    """Normalization of the raw LLM output into a stable shape."""

    def test_none_returns_empty_shape_with_unknown_timing(self):
        res = _clean_horizon_checkpoints(None)
        self.assertEqual(res["timing_profile"], "unknown")
        self.assertEqual(len(res["horizons"]), 3)
        self.assertEqual([h["horizon"] for h in res["horizons"]],
                         list(_CANONICAL_HORIZONS))
        for h in res["horizons"]:
            self.assertEqual(h["expected"], [])
            self.assertEqual(h["confirms_if"], [])
            self.assertEqual(h["falsifies_if"], [])

    def test_non_dict_falls_back_to_empty_shape(self):
        for bad in ("string", 42, ["list"], True):
            res = _clean_horizon_checkpoints(bad)
            self.assertEqual(res["timing_profile"], "unknown")
            self.assertEqual(len(res["horizons"]), 3)

    def test_full_well_formed_payload_preserved(self):
        raw = {
            "timing_profile": "fast_shock",
            "horizons": [
                {"horizon": "1d",  "expected": ["crude +2-4%"],
                 "confirms_if": ["CVX green on high volume"],
                 "falsifies_if": ["CVX closes red"]},
                {"horizon": "5d",  "expected": ["WCS-WTI widens 2-4pp"],
                 "confirms_if": ["first Chevron cargoes lifted"],
                 "falsifies_if": ["PDVSA delay statement"]},
                {"horizon": "20d", "expected": ["monthly imports ≥50kbd"],
                 "confirms_if": ["EIA monthly data confirms"],
                 "falsifies_if": ["Congress narrows licence"]},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        self.assertEqual(res["timing_profile"], "fast_shock")
        labels = [h["horizon"] for h in res["horizons"]]
        self.assertEqual(labels, ["1d", "5d", "20d"])
        self.assertEqual(res["horizons"][0]["confirms_if"],
                         ["CVX green on high volume"])

    def test_missing_horizon_filled_in(self):
        raw = {
            "timing_profile": "slow_grind",
            "horizons": [
                {"horizon": "5d", "expected": ["later check"],
                 "confirms_if": [], "falsifies_if": []},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        labels = [h["horizon"] for h in res["horizons"]]
        self.assertEqual(labels, ["1d", "5d", "20d"])
        self.assertEqual(res["horizons"][1]["expected"], ["later check"])
        # Missing 1d / 20d fall back to empty string lists.
        self.assertEqual(res["horizons"][0]["expected"], [])
        self.assertEqual(res["horizons"][2]["expected"], [])

    def test_dict_form_horizons_accepted(self):
        raw = {
            "timing_profile": "delayed_pass_through",
            "horizons": {
                "1d":  {"expected": ["x"]},
                "20d": {"confirms_if": ["y"]},
            },
        }
        res = _clean_horizon_checkpoints(raw)
        by_horizon = {h["horizon"]: h for h in res["horizons"]}
        self.assertEqual(by_horizon["1d"]["expected"], ["x"])
        self.assertEqual(by_horizon["20d"]["confirms_if"], ["y"])
        self.assertEqual(by_horizon["5d"]["expected"], [])

    def test_unknown_horizon_labels_dropped(self):
        raw = {
            "timing_profile": "fast_shock",
            "horizons": [
                {"horizon": "60d", "expected": ["out of cadence"],
                 "confirms_if": [], "falsifies_if": []},
                {"horizon": "1d",  "expected": ["kept"],
                 "confirms_if": [], "falsifies_if": []},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        by_horizon = {h["horizon"]: h for h in res["horizons"]}
        self.assertEqual(by_horizon["1d"]["expected"], ["kept"])
        self.assertEqual(by_horizon["5d"]["expected"], [])
        self.assertEqual(by_horizon["20d"]["expected"], [])
        # No stray "60d" horizon on the output.
        self.assertNotIn("60d", by_horizon)

    def test_timing_profile_normalized(self):
        for token in _TIMING_PROFILE_ENUM:
            res = _clean_horizon_checkpoints({"timing_profile": token,
                                              "horizons": []})
            self.assertEqual(res["timing_profile"], token)
        # Unknown tokens fall back to "unknown".
        res = _clean_horizon_checkpoints({"timing_profile": "lightning_fast",
                                          "horizons": []})
        self.assertEqual(res["timing_profile"], "unknown")

    def test_null_like_strings_dropped(self):
        raw = {
            "timing_profile": "slow_grind",
            "horizons": [
                {"horizon": "1d",  "expected": ["valid", "", "N/A", "none"],
                 "confirms_if": [], "falsifies_if": []},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        self.assertEqual(res["horizons"][0]["expected"], ["valid"])

    def test_list_cap_of_four(self):
        raw = {
            "timing_profile": "unknown",
            "horizons": [
                {"horizon": "1d",  "expected": [f"item{i}" for i in range(10)],
                 "confirms_if": [], "falsifies_if": []},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        self.assertEqual(len(res["horizons"][0]["expected"]), 4)

    def test_dedup_case_insensitive(self):
        raw = {
            "timing_profile": "unknown",
            "horizons": [
                {"horizon": "1d", "expected": ["CVX up", "cvx up", "CVX UP"],
                 "confirms_if": [], "falsifies_if": []},
            ],
        }
        res = _clean_horizon_checkpoints(raw)
        self.assertEqual(res["horizons"][0]["expected"], ["CVX up"])


class TestNormalizeSchemaEmitsHorizonCheckpoints(unittest.TestCase):
    """_normalize_schema must surface horizon_checkpoints in its output."""

    def test_field_present_on_valid_input(self):
        raw = {
            "what_changed": "x",
            "mechanism_summary": "y",
            "horizon_checkpoints": {
                "timing_profile": "fast_shock",
                "horizons": [
                    {"horizon": "1d", "expected": ["a"], "confirms_if": [], "falsifies_if": []},
                ],
            },
        }
        result = _normalize_schema(raw, "headline")
        self.assertIn("horizon_checkpoints", result)
        self.assertEqual(result["horizon_checkpoints"]["timing_profile"],
                         "fast_shock")

    def test_field_present_even_when_missing_on_input(self):
        result = _normalize_schema({"what_changed": "x"}, "headline")
        self.assertIn("horizon_checkpoints", result)
        self.assertEqual(result["horizon_checkpoints"]["timing_profile"],
                         "unknown")
        self.assertEqual(len(result["horizon_checkpoints"]["horizons"]), 3)

    def test_field_registered_in_llm_core_fields(self):
        self.assertIn("horizon_checkpoints", LLM_CORE_FIELDS)
        self.assertIn("horizon_checkpoints", _LLM_CORE_DEFAULTS)


class TestFallbackPathsEmitHorizonCheckpoints(unittest.TestCase):
    """Mock + degraded fallback paths must include a stable horizon_checkpoints."""

    def test_mock_carries_field(self):
        mock = _mock("test reason")
        self.assertIn("horizon_checkpoints", mock)
        self.assertEqual(mock["horizon_checkpoints"]["timing_profile"], "unknown")
        self.assertEqual(len(mock["horizon_checkpoints"]["horizons"]), 3)

    def test_degraded_fallback_carries_field(self):
        fb = _degraded_fallback("h", "s", "p", "why")
        self.assertIn("horizon_checkpoints", fb)
        self.assertEqual(fb["horizon_checkpoints"]["timing_profile"], "unknown")


class TestDbRoundtrip(unittest.TestCase):
    """Persistence layer encodes + decodes horizon_checkpoints cleanly."""

    def setUp(self):
        self._orig = db.DB_FILE
        db.DB_FILE = _tmp_db()
        db.init_db()

    def tearDown(self):
        try:
            os.remove(db.DB_FILE)
        except OSError:
            pass
        db.DB_FILE = self._orig

    def test_schema_has_column(self):
        with sqlite3.connect(db.DB_FILE) as conn:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(events)").fetchall()}
        self.assertIn("horizon_checkpoints", cols)

    def test_roundtrip_preserves_structure(self):
        payload = _clean_horizon_checkpoints({
            "timing_profile": "delayed_pass_through",
            "horizons": [
                {"horizon": "1d",  "expected": ["CVX +1-2%"],
                 "confirms_if": ["green close"], "falsifies_if": ["red close"]},
                {"horizon": "5d",  "expected": ["spread widens"],
                 "confirms_if": ["WCS-WTI +2pp"], "falsifies_if": ["no move"]},
                {"horizon": "20d", "expected": ["monthly imports confirm"],
                 "confirms_if": ["EIA data"], "falsifies_if": ["licence narrowed"]},
            ],
        })
        db.save_event({
            "headline": "Horizon roundtrip",
            "stage": "breaking",
            "persistence": "transient",
            "event_date": "2025-01-01",
            "horizon_checkpoints": payload,
        })
        events = db.load_recent_events(1)
        self.assertEqual(len(events), 1)
        loaded = events[0].get("horizon_checkpoints")
        # Must be a dict, not a raw JSON string (the narrative_divergence bug class).
        self.assertIsInstance(loaded, dict)
        self.assertEqual(loaded["timing_profile"], "delayed_pass_through")
        self.assertEqual(len(loaded["horizons"]), 3)
        self.assertEqual(loaded["horizons"][0]["confirms_if"], ["green close"])

    def test_missing_field_defaults_to_empty_dict(self):
        db.save_event({
            "headline": "Horizon defaults",
            "stage": "breaking",
            "persistence": "transient",
            "event_date": "2025-01-02",
        })
        events = db.load_recent_events(1)
        loaded = events[0].get("horizon_checkpoints")
        # The DB default is '{}' — decoder yields {}, not None or a string.
        self.assertEqual(loaded, {})


if __name__ == "__main__":
    unittest.main()
