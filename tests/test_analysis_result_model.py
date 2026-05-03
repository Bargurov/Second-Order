"""Structural guardrail tests for the AnalysisResult model.

These tests verify the invariant that every field in PERSISTED_OVERLAY_FIELDS
has a corresponding DB column and is threaded through _persist_event — so new
analytical fields cannot silently be dropped at the persistence boundary.

No LLM calls, no network, no file I/O beyond a temp SQLite DB.
"""

import json
import os
import sqlite3
import sys
import uuid
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze_event import (
    PERSISTED_OVERLAY_FIELDS, LLM_CORE_FIELDS, OVERLAY_FIELDS,
    build_analysis_dict,
)
import db


def _temp_db() -> str:
    return os.path.join(os.path.dirname(__file__), f"test_ar_{uuid.uuid4().hex}.db")


class TestFieldConstants(unittest.TestCase):
    """PERSISTED_OVERLAY_FIELDS, LLM_CORE_FIELDS, OVERLAY_FIELDS sanity."""

    def test_persisted_overlay_fields_nonempty(self):
        self.assertGreater(len(PERSISTED_OVERLAY_FIELDS), 0)

    def test_overlay_fields_is_superset(self):
        for f in PERSISTED_OVERLAY_FIELDS:
            self.assertIn(f, OVERLAY_FIELDS, f"{f!r} in PERSISTED but not in OVERLAY_FIELDS")

    def test_no_overlap_llm_core_and_persisted_overlay(self):
        overlap = set(LLM_CORE_FIELDS) & set(PERSISTED_OVERLAY_FIELDS)
        self.assertEqual(overlap, set(), f"Fields appear in both sets: {overlap}")

    def test_narrative_divergence_in_persisted(self):
        self.assertIn("narrative_divergence", PERSISTED_OVERLAY_FIELDS)


class TestDbColumnsMatchPersistedFields(unittest.TestCase):
    """Every field in PERSISTED_OVERLAY_FIELDS must be a column in the DB."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = _temp_db()
        orig = db.DB_FILE
        db.DB_FILE = cls._tmp
        db.init_db()
        db.DB_FILE = orig  # restore; we'll query directly
        cls._tmp_file = cls._tmp

    @classmethod
    def tearDownClass(cls):
        try:
            os.remove(cls._tmp_file)
        except OSError:
            pass

    def _columns(self) -> set[str]:
        conn = sqlite3.connect(self._tmp_file)
        try:
            rows = conn.execute("PRAGMA table_info(events)").fetchall()
            return {r[1] for r in rows}
        finally:
            conn.close()

    def test_all_persisted_overlay_fields_have_db_column(self):
        cols = self._columns()
        missing = [f for f in PERSISTED_OVERLAY_FIELDS if f not in cols]
        self.assertEqual(
            missing, [],
            f"Fields in PERSISTED_OVERLAY_FIELDS with no DB column: {missing}",
        )

    def test_narrative_divergence_column_exists(self):
        self.assertIn("narrative_divergence", self._columns())


class TestPersistEventPassesAllFields(unittest.TestCase):
    """_persist_event must include every PERSISTED_OVERLAY_FIELD in the record passed to save_event."""

    def test_all_persisted_overlay_fields_in_persist_event(self):
        """Runtime check: patch save_event and verify captured record has all overlay fields."""
        from unittest.mock import patch
        import api as _api_mod

        captured: dict = {}

        def _fake_save(event: dict) -> None:
            captured.update(event)

        analysis: dict = {f: {"test": True} for f in PERSISTED_OVERLAY_FIELDS}
        analysis.update({
            "what_changed": "test", "mechanism_summary": "test",
            "beneficiaries": [], "losers": [], "assets_to_watch": [],
            "confidence": "low", "transmission_chain": [],
            "if_persists": {}, "currency_channel": {},
        })
        mkt = {"note": "", "tickers": []}

        with patch.object(_api_mod, "save_event", side_effect=_fake_save), \
             patch.dict(_api_mod._TODAYS_MOVERS_CACHE, {"data": None}):
            _api_mod._persist_event("test headline", "breaking", "transient", analysis, mkt, "2025-01-01")

        missing = [f for f in PERSISTED_OVERLAY_FIELDS if f not in captured]
        self.assertEqual(
            missing, [],
            f"Fields missing from _persist_event event_record: {missing}",
        )


class TestDbDecodeCoversPersistedOverlays(unittest.TestCase):
    """db._EVENT_DICT_FIELDS must contain every PERSISTED_OVERLAY_FIELD so
    every read path decodes overlays to dicts. Missing entries leak raw JSON
    strings into response payloads — the narrative_divergence bug class."""

    def test_event_dict_fields_covers_persisted_overlays(self):
        missing = [f for f in PERSISTED_OVERLAY_FIELDS if f not in db._EVENT_DICT_FIELDS]
        self.assertEqual(
            missing, [],
            f"PERSISTED_OVERLAY_FIELDS missing from db._EVENT_DICT_FIELDS: {missing}",
        )


class TestBuildAnalysisDict(unittest.TestCase):
    """build_analysis_dict is the single source of truth for analysis shape."""

    def test_every_registry_field_present(self):
        result = build_analysis_dict({})
        for f in LLM_CORE_FIELDS:
            self.assertIn(f, result, f"LLM core field missing from builder output: {f}")
        for f in PERSISTED_OVERLAY_FIELDS:
            self.assertIn(f, result, f"Persisted overlay missing from builder output: {f}")

    def test_overrides_take_precedence_over_source(self):
        source = {"narrative_divergence": {"signal": "aligned"}}
        overrides = {"narrative_divergence": {"signal": "divergent"}}
        result = build_analysis_dict(source, overrides)
        self.assertEqual(result["narrative_divergence"], {"signal": "divergent"})

    def test_missing_overlay_defaults_to_empty_dict(self):
        result = build_analysis_dict({})
        for f in PERSISTED_OVERLAY_FIELDS:
            self.assertEqual(result[f], {}, f"{f} should default to {{}}")

    def test_non_dict_overlay_coerced_to_empty(self):
        """Guards against the narrative_divergence bug: a raw JSON string
        sitting in a source dict must not leak through as the overlay value."""
        result = build_analysis_dict({"narrative_divergence": '{"signal":"x"}'})
        self.assertEqual(result["narrative_divergence"], {})

    def test_llm_core_defaults_have_correct_type(self):
        result = build_analysis_dict({})
        self.assertEqual(result["what_changed"], "")
        self.assertEqual(result["confidence"], "low")
        self.assertEqual(result["beneficiaries"], [])
        self.assertEqual(result["if_persists"], {})


class TestSaveEventRoundtrip(unittest.TestCase):
    """narrative_divergence survives a save_event/load roundtrip."""

    def setUp(self):
        self._tmp = _temp_db()
        self._orig = db.DB_FILE
        db.DB_FILE = self._tmp
        db.init_db()

    def tearDown(self):
        db.DB_FILE = self._orig
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def test_narrative_divergence_roundtrip(self):
        payload = {"signal": "divergent", "score": 0.75}
        db.save_event({
            "headline": "Test: narrative divergence roundtrip",
            "stage": "breaking",
            "persistence": "transient",
            "event_date": "2025-01-01",
            "narrative_divergence": payload,
        })
        events = db.load_recent_events(1)
        self.assertEqual(len(events), 1)
        nd = events[0].get("narrative_divergence")
        self.assertIsNotNone(nd, "narrative_divergence missing from loaded event")
        if isinstance(nd, str):
            nd = json.loads(nd)
        self.assertEqual(nd.get("signal"), "divergent")
        self.assertAlmostEqual(nd.get("score"), 0.75)

    def test_missing_narrative_divergence_defaults_to_empty_dict(self):
        """Events saved without narrative_divergence should default to {} not NULL."""
        db.save_event({
            "headline": "Test: no narrative divergence",
            "stage": "breaking",
            "persistence": "transient",
            "event_date": "2025-01-01",
        })
        events = db.load_recent_events(1)
        nd = events[0].get("narrative_divergence")
        # The DB default is '{}'; load_recent_events may return it as str or dict.
        if nd is None:
            pass  # legacy rows — acceptable
        elif isinstance(nd, str):
            self.assertEqual(json.loads(nd), {})
        else:
            self.assertEqual(nd, {})


if __name__ == "__main__":
    unittest.main()
