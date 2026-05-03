"""
tests/test_proof_status_decode.py

Read-path defensive contract for the ``proof_status`` and
``falsifier_status`` blocks.

The save path always serialises a dict (``json.dumps(dict)``), but a
hand-edited DB, a botched migration, or a partial restore can leave
the column carrying invalid JSON, ``"null"``, a quoted string, or a
list.  Consumers of ``GET /events/{id}`` iterate ``items`` and call
``.get(...)`` on the block unconditionally — they must never crash on
that bit-rot.

These tests cover the contract:
  1. ``_coerce_status_block`` collapses every non-dict shape to ``{}``.
  2. Empty ``{}`` is preserved as the "never evaluated" signal.
  3. A non-empty dict missing ``items`` (or with a non-list ``items``)
     gets ``items`` set to ``[]``.
  4. Valid blocks with ``items`` as a list pass through untouched.
  5. End-to-end through ``_decode_event_row``: corrupted JSON, valid
     JSON shapes, and round-trip save/load all converge on the
     defensive contract.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as db_module
from db import _coerce_status_block, _decode_event_row, init_db, save_event


# ---------------------------------------------------------------------------
# 1. Helpers
# ---------------------------------------------------------------------------


def _minimal_event(headline: str = "Headline", **overrides) -> dict:
    base = {
        "headline":          headline,
        "stage":              "test",
        "persistence":        "1d",
        "what_changed":       "x",
        "mechanism_summary":  "y",
        "beneficiaries":      ["A"],
        "losers":             ["B"],
        "assets_to_watch":    [],
        "confidence":         "medium",
        "market_note":        "",
        "market_tickers":     [],
        "event_date":         "2025-01-15",
        "notes":              "",
        "model":              "test-model",
    }
    base.update(overrides)
    return base


class _IsolatedDbTestCase(unittest.TestCase):
    """Each test runs against a throw-away SQLite file."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self._orig_db = db_module.DB_FILE
        db_module.DB_FILE = self._tmp.name
        db_module._db_ready = False
        init_db()

    def tearDown(self) -> None:
        db_module.DB_FILE = self._orig_db
        db_module._db_ready = False
        try:
            os.unlink(self._tmp.name)
        except (PermissionError, OSError):
            pass


# ---------------------------------------------------------------------------
# 2. _coerce_status_block — unit-level contract
# ---------------------------------------------------------------------------


class CoerceStatusBlockTests(unittest.TestCase):

    def test_none_collapses_to_empty_dict(self) -> None:
        self.assertEqual(_coerce_status_block(None), {})

    def test_string_collapses_to_empty_dict(self) -> None:
        self.assertEqual(_coerce_status_block("not a dict"), {})

    def test_list_collapses_to_empty_dict(self) -> None:
        self.assertEqual(_coerce_status_block([1, 2, 3]), {})

    def test_scalar_collapses_to_empty_dict(self) -> None:
        self.assertEqual(_coerce_status_block(42), {})
        self.assertEqual(_coerce_status_block(False), {})

    def test_empty_dict_preserved(self) -> None:
        # The "never evaluated" signal — must NOT be re-shaped to
        # {"items": []} because consumers branch on emptiness.
        self.assertEqual(_coerce_status_block({}), {})

    def test_dict_with_items_list_passes_through(self) -> None:
        block = {"verdict": "confirmed", "items": [{"id": 1}], "score": 0.7}
        out = _coerce_status_block(block)
        self.assertEqual(out, block)

    def test_dict_with_empty_items_list_passes_through(self) -> None:
        block = {"verdict": "pending", "items": []}
        self.assertEqual(_coerce_status_block(block), block)

    def test_dict_missing_items_gets_empty_list(self) -> None:
        out = _coerce_status_block({"verdict": "confirmed"})
        self.assertEqual(out, {"verdict": "confirmed", "items": []})

    def test_dict_with_non_list_items_coerced(self) -> None:
        for bad_items in (None, "string", {"k": "v"}, 5):
            out = _coerce_status_block({"verdict": "confirmed", "items": bad_items})
            self.assertEqual(out["items"], [])
            self.assertEqual(out["verdict"], "confirmed")

    def test_other_keys_preserved_when_items_coerced(self) -> None:
        out = _coerce_status_block({
            "verdict":    "broken",
            "score":      0.2,
            "as_of":      "2025-01-15",
            "items":      "not a list",
        })
        self.assertEqual(out["verdict"], "broken")
        self.assertEqual(out["score"], 0.2)
        self.assertEqual(out["as_of"], "2025-01-15")
        self.assertEqual(out["items"], [])

    def test_does_not_mutate_input(self) -> None:
        block = {"verdict": "ok"}
        _coerce_status_block(block)
        self.assertNotIn("items", block)


# ---------------------------------------------------------------------------
# 3. End-to-end via _decode_event_row over a sqlite row
# ---------------------------------------------------------------------------


class DecodeEventRowDefensiveTests(_IsolatedDbTestCase):
    """Verify _decode_event_row routes every corrupt-shape stored
    blob through the coercer."""

    def _save_then_overwrite(self, *, raw_proof: str, raw_falsifier: str) -> dict:
        """Save a minimal event then overwrite the proof/falsifier
        columns directly with the supplied raw strings (bypassing the
        save-side serialiser).  Returns the decoded row."""
        save_event(_minimal_event(headline="defensive-decode test"))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET proof_status = ?, falsifier_status = ?",
                (raw_proof, raw_falsifier),
            )
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        return _decode_event_row(row)

    def test_invalid_json_collapses_to_empty_dicts(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof="{not json", raw_falsifier="also bad}",
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_json_null_collapses_to_empty_dict(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof="null", raw_falsifier="null",
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_json_string_collapses_to_empty_dict(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof=json.dumps("a string"),
            raw_falsifier=json.dumps("another"),
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_json_list_collapses_to_empty_dict(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof=json.dumps([1, 2, 3]),
            raw_falsifier=json.dumps(["a", "b"]),
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_json_scalar_collapses_to_empty_dict(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof="42", raw_falsifier="false",
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_empty_dict_preserved_through_decode(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof="{}", raw_falsifier="{}",
        )
        self.assertEqual(ev["proof_status"], {})
        self.assertEqual(ev["falsifier_status"], {})

    def test_dict_missing_items_gets_empty_list_through_decode(self) -> None:
        # Pre-item-contract row: {} with verdict but no items key.
        ev = self._save_then_overwrite(
            raw_proof=json.dumps({"verdict": "confirmed"}),
            raw_falsifier=json.dumps({"verdict": "intact"}),
        )
        self.assertEqual(ev["proof_status"]["verdict"], "confirmed")
        self.assertEqual(ev["proof_status"]["items"], [])
        self.assertEqual(ev["falsifier_status"]["verdict"], "intact")
        self.assertEqual(ev["falsifier_status"]["items"], [])

    def test_dict_with_non_list_items_coerced_through_decode(self) -> None:
        ev = self._save_then_overwrite(
            raw_proof=json.dumps({"verdict": "ok", "items": "not a list"}),
            raw_falsifier=json.dumps({"verdict": "ok", "items": None}),
        )
        self.assertEqual(ev["proof_status"]["items"], [])
        self.assertEqual(ev["falsifier_status"]["items"], [])

    def test_valid_round_trip_preserved(self) -> None:
        proof = {
            "verdict": "confirmed",
            "score":   0.7,
            "items":   [{"id": "p1", "channel": "commodities", "fired": True}],
        }
        falsifier = {
            "verdict": "intact",
            "items":   [],
        }
        ev = self._save_then_overwrite(
            raw_proof=json.dumps(proof),
            raw_falsifier=json.dumps(falsifier),
        )
        self.assertEqual(ev["proof_status"], proof)
        self.assertEqual(ev["falsifier_status"], falsifier)


# ---------------------------------------------------------------------------
# 4. Save → load round-trip through the canonical save path
# ---------------------------------------------------------------------------


class SaveLoadRoundTripTests(_IsolatedDbTestCase):
    """Stable old-row compatibility: save_event computes proof and
    falsifier blocks via the proof_evaluator; reading them back must
    yield dicts with iterable ``items``, never the bit-rot shapes."""

    def test_save_load_yields_iterable_items(self) -> None:
        save_event(_minimal_event(headline="round-trip test"))
        with sqlite3.connect(db_module.DB_FILE) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM events LIMIT 1").fetchone()
        ev = _decode_event_row(row)

        for field in ("proof_status", "falsifier_status"):
            block = ev[field]
            self.assertIsInstance(block, dict)
            if block:
                # Any non-empty block must carry a list-typed ``items``.
                self.assertIsInstance(block.get("items"), list)


if __name__ == "__main__":
    unittest.main()
