"""Cached-analysis and event-block safety contracts.

Covers:
  * ``find_cached_analysis(event_id=…)`` prefers the id route over the
    legacy headline + date + model path; collisions, missing ids, and
    stale ids never serve a wrong row.
  * Corrupted ``proof_status`` / ``falsifier_status`` columns on disk
    decode to stable shaped defaults via ``_coerce_status_block``;
    valid blocks round-trip unchanged.
  * Composer-level ``actionability_check`` / ``counterfactual_check``
    handle corrupted inputs (non-dict, wrong-type ``minimum_proof_set``
    / ``key_falsifiers``) without raising and emit stable shapes;
    valid inputs round-trip the populated shape.

These tests exist to lock the saved-event compatibility contract —
hand-edited rows, partial migrations, and corrupted JSON columns must
never crash the read path.
"""

from __future__ import annotations

import gc
import json
import os
import shutil
import sqlite3
import sys
import time
import unittest
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db
from low_information_gate import (
    compose_actionability_check,
    compose_counterfactual_check,
)


# ---------------------------------------------------------------------------
# Test scaffolding — isolated tmp DB per test class
# ---------------------------------------------------------------------------

def _make_temp_db(prefix: str) -> tuple[str, str]:
    tmp_dir = os.path.join(
        os.path.dirname(__file__), f"{prefix}{uuid.uuid4().hex}",
    )
    os.makedirs(tmp_dir)
    return tmp_dir, os.path.join(tmp_dir, "events.db")


def _remove_temp_dir(path: str) -> None:
    last_error: Exception | None = None
    for _ in range(5):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


def _minimal_event(headline: str, **overrides) -> dict:
    base = {
        "headline":           headline,
        "stage":              "realized",
        "persistence":        "structural",
        "what_changed":       f"x for {headline}",
        "mechanism_summary":  f"y for {headline}",
        "confidence":         "medium",
    }
    base.update(overrides)
    return base


class _IsolatedDb(unittest.TestCase):
    """Per-class tmp DB — keeps cache + block tests independent."""

    def setUp(self) -> None:
        self._original_db = db.DB_FILE
        self._original_ready = db._db_ready
        self._tmp_dir, self._tmp_db = _make_temp_db("test_cb_safety_")
        db.DB_FILE = self._tmp_db
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self._original_db
        db._db_ready = self._original_ready
        _remove_temp_dir(self._tmp_dir)


# ---------------------------------------------------------------------------
# 1. find_cached_analysis(event_id=…) prefers id over headline/time-window
# ---------------------------------------------------------------------------

class TestFindCachedAnalysisEventIdRoute(_IsolatedDb):
    def _insert_collision(self) -> tuple[int, int, str]:
        """Insert two rows with the SAME headline (different event_dates
        so the dedup window doesn't fire) and return their ids + the
        shared headline."""
        headline = "OPEC surprise cut"
        ev_a = _minimal_event(
            headline,
            event_date="2025-01-10", what_changed="OPEC A",
        )
        ev_b = _minimal_event(
            headline,
            event_date="2025-02-10", what_changed="OPEC B",
        )
        db.save_event(ev_a)
        db.save_event(ev_b)
        with sqlite3.connect(db.DB_FILE) as conn:
            rows = conn.execute(
                "SELECT id, what_changed FROM events ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        return rows[0][0], rows[1][0], headline

    def test_event_id_route_returns_exact_row_under_headline_collision(self):
        id_a, id_b, headline = self._insert_collision()
        cached = db.find_cached_analysis(headline, event_id=id_a)
        self.assertIsNotNone(cached)
        self.assertEqual(cached["id"], id_a)
        self.assertEqual(cached["what_changed"], "OPEC A")

    def test_event_id_route_does_not_fall_through_to_headline(self):
        # A non-existent event_id must NOT fall back to the headline
        # path — that fallback would re-introduce the collision the
        # event_id route was added to fix.
        _, _, headline = self._insert_collision()
        cached = db.find_cached_analysis(headline, event_id=99999)
        self.assertIsNone(cached)

    def test_event_id_route_ignores_headline_string(self):
        id_a, _, _ = self._insert_collision()
        # Wrong headline + correct event_id → still finds the row.
        cached = db.find_cached_analysis(
            "wrong headline", event_id=id_a,
        )
        self.assertIsNotNone(cached)
        self.assertEqual(cached["id"], id_a)

    def test_event_id_route_respects_ttl(self):
        id_a, _, _ = self._insert_collision()
        # Force the row's timestamp older than the TTL window.
        old_ts = (
            datetime.now() - timedelta(seconds=2 * 86400)
        ).isoformat(timespec="seconds")
        with sqlite3.connect(db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET timestamp = ? WHERE id = ?",
                (old_ts, id_a),
            )
            conn.commit()
        cached = db.find_cached_analysis(
            "any headline", event_id=id_a, max_age_seconds=86400,
        )
        self.assertIsNone(cached)

    def test_event_id_route_skips_mock_rows(self):
        # Insert a mock row directly — the cache must not serve it
        # even when the event_id matches.
        ev = _minimal_event(
            "mock headline", what_changed="[mock: missing key]",
        )
        db.save_event(ev)
        with sqlite3.connect(db.DB_FILE) as conn:
            row_id = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        cached = db.find_cached_analysis(
            "mock headline", event_id=row_id,
        )
        self.assertIsNone(cached)

    def test_no_event_id_falls_through_to_headline_path(self):
        # Without event_id, the legacy headline + date path is used
        # and returns the row that matches BOTH headline and date.
        _, _, headline = self._insert_collision()
        cached = db.find_cached_analysis(
            headline, event_date="2025-01-10",
        )
        self.assertIsNotNone(cached)
        self.assertEqual(cached["what_changed"], "OPEC A")


# ---------------------------------------------------------------------------
# 2. proof_status / falsifier_status — corrupted columns load safely
# ---------------------------------------------------------------------------

class TestStatusBlockCorruption(_IsolatedDb):
    def _insert_and_corrupt(
        self, *, field: str, raw_value: str,
    ) -> int:
        """Save an event then UPDATE the column to ``raw_value`` (the
        literal string stored in SQLite — represents a hand-edited or
        mid-migration corruption).  Returns the row id."""
        ev = _minimal_event("corruption test")
        db.save_event(ev)
        with sqlite3.connect(db.DB_FILE) as conn:
            row_id = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
            conn.execute(
                f"UPDATE events SET {field} = ? WHERE id = ?",
                (raw_value, row_id),
            )
            conn.commit()
        return row_id

    # -- proof_status corruption shapes --

    def test_proof_status_invalid_json_decodes_to_empty_dict(self):
        row_id = self._insert_and_corrupt(
            field="proof_status", raw_value="{not valid json",
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"], {})

    def test_proof_status_json_null_decodes_to_empty_dict(self):
        row_id = self._insert_and_corrupt(
            field="proof_status", raw_value="null",
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"], {})

    def test_proof_status_json_string_decodes_to_empty_dict(self):
        row_id = self._insert_and_corrupt(
            field="proof_status", raw_value='"a string"',
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"], {})

    def test_proof_status_json_list_decodes_to_empty_dict(self):
        row_id = self._insert_and_corrupt(
            field="proof_status", raw_value="[]",
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"], {})

    def test_proof_status_dict_missing_items_gets_items_default(self):
        row_id = self._insert_and_corrupt(
            field="proof_status",
            raw_value=json.dumps({"status": "met", "matched_count": 1}),
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"]["status"], "met")
        self.assertEqual(loaded["proof_status"]["items"], [])

    def test_proof_status_dict_with_non_list_items_gets_items_default(self):
        row_id = self._insert_and_corrupt(
            field="proof_status",
            raw_value=json.dumps({"status": "met", "items": "not a list"}),
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"]["items"], [])

    # -- falsifier_status corruption shapes (mirror) --

    def test_falsifier_status_invalid_json_decodes_to_empty_dict(self):
        row_id = self._insert_and_corrupt(
            field="falsifier_status", raw_value="{garbage",
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["falsifier_status"], {})

    def test_falsifier_status_dict_missing_items_gets_items_default(self):
        row_id = self._insert_and_corrupt(
            field="falsifier_status",
            raw_value=json.dumps({"status": "triggered"}),
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["falsifier_status"]["status"], "triggered")
        self.assertEqual(loaded["falsifier_status"]["items"], [])

    # -- valid block round-trip --

    def test_valid_proof_status_round_trips(self):
        valid_block = {
            "available":     True,
            "status":        "met",
            "matched_count": 1,
            "total_count":   1,
            "items": [
                {"channel": "commodities", "expected_direction": "up",
                 "timing": "1-5d", "why_it_matters": "supply tightens",
                 "status": "met",
                 "matched_evidence": "1 supporting ticker tag"},
            ],
        }
        row_id = self._insert_and_corrupt(
            field="proof_status", raw_value=json.dumps(valid_block),
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["proof_status"], valid_block)

    def test_valid_falsifier_status_round_trips(self):
        valid_block = {
            "available": True,
            "status":    "triggered",
            "triggered": ["A reverses within 5d"],
            "watching":  [],
            "items": [
                {"channel": "commodities", "trigger_condition":
                 "A reverses within 5d", "timing": "1-5d",
                 "why_it_breaks_thesis": "Original move undone",
                 "status": "triggered",
                 "matched_evidence": "event-wide validation: contradicted"},
            ],
        }
        row_id = self._insert_and_corrupt(
            field="falsifier_status", raw_value=json.dumps(valid_block),
        )
        loaded = db.load_event_by_id(row_id)
        self.assertEqual(loaded["falsifier_status"], valid_block)


# ---------------------------------------------------------------------------
# 3. actionability_check / counterfactual_check — composers handle
#    corrupted inputs without raising; emit stable shapes.
# ---------------------------------------------------------------------------

class TestComposerCorruptionDefaults(unittest.TestCase):
    _ACTIONABILITY_KEYS = {
        "tradable", "why_tradable_or_not", "required_confirmation",
        "sizing_caveat", "risk_level",
        "max_confidence_before_confirmation", "invalidation_trigger",
    }
    _COUNTERFACTUAL_KEYS = {
        "what_should_not_happen", "why_it_would_break_thesis",
        "evidence_to_watch",
    }

    def test_actionability_non_dict_returns_empty(self):
        for bad in (None, "string", 42, [], object()):
            self.assertEqual(compose_actionability_check(bad), {})

    def test_counterfactual_non_dict_returns_empty(self):
        for bad in (None, "string", 42, [], object()):
            self.assertEqual(compose_counterfactual_check(bad), {})

    def test_actionability_with_corrupted_proof_set_emits_shape(self):
        ev = {
            "headline": "x",
            "mechanism_summary": "x" * 50,
            "minimum_proof_set": "this should be a list",
            "key_falsifiers": "this too",
        }
        block = compose_actionability_check(ev)
        self.assertEqual(set(block.keys()), self._ACTIONABILITY_KEYS)

    def test_counterfactual_with_corrupted_falsifiers_emits_shape(self):
        ev = {
            "headline": "x",
            "mechanism_summary": "x" * 50,
            "key_falsifiers": {"not": "a list"},
            "minimum_proof_set": 42,
            "hidden_mechanism": "should be a dict",
        }
        block = compose_counterfactual_check(ev)
        self.assertEqual(set(block.keys()), self._COUNTERFACTUAL_KEYS)

    def test_actionability_with_dict_proof_entries_emits_shape(self):
        ev = {
            "headline": "x",
            "mechanism_summary": "x" * 50,
            # List but with non-dict / non-string entries — must be
            # tolerated.
            "minimum_proof_set": [42, None, {"observation": ""}],
            "key_falsifiers": [None, ""],
        }
        block = compose_actionability_check(ev)
        self.assertEqual(set(block.keys()), self._ACTIONABILITY_KEYS)


# ---------------------------------------------------------------------------
# 4. Round-trip: a saved event's DERIVED actionability_check /
#    counterfactual_check, when recomposed on the loaded row, matches the
#    pre-save composer output (saved-event compatibility).
# ---------------------------------------------------------------------------

class TestDerivedBlockRoundTrip(_IsolatedDb):
    """The save path doesn't persist actionability_check or
    counterfactual_check — they're recomputed via ``build_analysis_dict``
    at read time.  This test confirms the recomputed shapes match the
    original composer outputs when the underlying inputs round-trip
    cleanly through save/load.
    """

    def test_actionability_check_derives_consistently_after_save_load(self):
        # ``beneficiary_tickers`` is not a separate persisted column —
        # the production save path merges all ticker buckets into
        # ``assets_to_watch`` first.  Use the production shape so the
        # round-trip mirrors what the live save flow produces.
        ev = _minimal_event(
            "round-trip headline",
            mechanism_summary=(
                "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
                "Coast feedstock and widening WCS-WTI."
            ),
            mechanism_family="commodity_squeeze",
            assets_to_watch=["XOM"],
            primary_assets=[{"symbol": "XOM", "rank": 1,
                             "rationale": "direct beneficiary"}],
            minimum_proof_set=[{
                "observation": "WCS-WTI widens 2pp within 5 days",
                "channel": "commodities",
                "threshold": "2pp", "timing": "1-5d",
            }],
            key_falsifiers=["Saudi reverses cut within 5 days"],
        )
        before = compose_actionability_check(ev)
        db.save_event(ev)
        with sqlite3.connect(db.DB_FILE) as conn:
            row_id = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        loaded = db.load_event_by_id(row_id)
        # Recompose the actionability_check from the LOADED row — the
        # inputs (proof, falsifier, mechanism) should round-trip
        # cleanly so the composer output stays identical.
        after = compose_actionability_check(loaded)
        self.assertEqual(set(before.keys()), set(after.keys()))
        # Closed-set fields that should not drift across save/load.
        for key in ("tradable", "risk_level",
                    "max_confidence_before_confirmation"):
            self.assertEqual(before[key], after[key])

    def test_counterfactual_check_derives_consistently_after_save_load(self):
        ev = _minimal_event(
            "round-trip headline 2",
            mechanism_summary=(
                "Saudi Aramco cuts liftings by 1mbd, tightening Gulf "
                "Coast feedstock and widening WCS-WTI."
            ),
            mechanism_family="commodity_squeeze",
            assets_to_watch=["XOM"],
            primary_assets=[{"symbol": "XOM", "rank": 1,
                             "rationale": "direct beneficiary"}],
            minimum_proof_set=[{
                "observation": "WCS-WTI widens 2pp within 5 days",
                "channel": "commodities",
                "threshold": "2pp", "timing": "1-5d",
            }],
            key_falsifiers=["Saudi reverses cut within 5 days"],
        )
        before = compose_counterfactual_check(ev)
        db.save_event(ev)
        with sqlite3.connect(db.DB_FILE) as conn:
            row_id = conn.execute(
                "SELECT id FROM events ORDER BY id DESC LIMIT 1"
            ).fetchone()[0]
        loaded = db.load_event_by_id(row_id)
        after = compose_counterfactual_check(loaded)
        self.assertEqual(set(before.keys()), set(after.keys()))


if __name__ == "__main__":
    unittest.main()
