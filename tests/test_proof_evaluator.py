"""
tests/test_proof_evaluator.py

Contract tests for the proof-set / falsifier evaluator and its
persistence hooks (save_event / update_event_market_refresh /
append_revisit_snapshot).

Covers:
  * Pure composers — status rollup (met / partial / unmet / none),
    shape contract, channel-scoped evidence attribution, falsifier
    classification from the shared validation label.
  * DB round-trip — the two derived blocks persist as dicts across
    all three hooks and come back decoded (not raw JSON strings).
  * Old-row fallback — rows that pre-date these columns read back
    with stable empty-dict defaults.
  * No collateral damage to ``weighted_evidence`` /
    ``validation_outcome`` — the derived statuses do not alter those.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
from proof_evaluator import (
    compute_statuses,
    evaluate_falsifier_status,
    evaluate_proof_status,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _ticker(symbol: str, *, direction_tag: str | None, return_5d: float = 0.0) -> dict:
    return {"symbol": symbol, "return_5d": return_5d, "direction_tag": direction_tag}


def _proof(channel: str, observation: str = "Concrete proof observation") -> dict:
    return {
        "observation": observation,
        "channel":     channel,
        "threshold":   "≥1σ move",
        "timing":      "1-5d",
    }


# ---------------------------------------------------------------------------
# Pure proof composer
# ---------------------------------------------------------------------------


class TestProofStatusShape(unittest.TestCase):
    def test_missing_proof_set_returns_not_available(self) -> None:
        out = evaluate_proof_status({})
        self.assertEqual(out["available"], False)
        self.assertEqual(out["status"], "none")
        self.assertEqual(out["total_count"], 0)
        self.assertEqual(out["matched_items"], [])
        self.assertEqual(out["unmet_items"], [])

    def test_every_output_has_required_keys(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities")],
            "market_tickers": [_ticker("XLE", direction_tag="supports thesis")],
        })
        for key in ("available", "status", "matched_count", "total_count",
                    "matched_items", "unmet_items"):
            self.assertIn(key, out)


class TestProofStatusRollup(unittest.TestCase):
    def test_all_met_returns_met(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities"), _proof("commodities")],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                _ticker("USO", direction_tag="supports thesis"),
            ],
        })
        self.assertEqual(out["status"], "met")
        self.assertEqual(out["matched_count"], 2)
        self.assertEqual(out["total_count"], 2)

    def test_some_met_returns_partial(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities"), _proof("commodities")],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                # No commodity ticker — that proof entry is unmet.
            ],
        })
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["matched_count"], 1)
        self.assertEqual(out["total_count"], 2)

    def test_none_met_returns_unmet(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities"), _proof("commodities")],
            "market_tickers": [
                _ticker("XLE", direction_tag="contradicts thesis"),
                _ticker("USO", direction_tag="contradicts thesis"),
            ],
        })
        self.assertEqual(out["status"], "unmet")
        self.assertEqual(out["matched_count"], 0)

    def test_mixed_evidence_on_channel_is_unmet(self) -> None:
        """A proof entry with both supporting AND contradicting tags on
        the same channel is treated as unmet — mixed evidence doesn't
        count as a met proof."""
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities")],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                _ticker("XLF", direction_tag="contradicts thesis"),
            ],
        })
        self.assertEqual(out["status"], "unmet")
        self.assertTrue(any(
            "mixed evidence" in (e.get("evidence") or "")
            for e in out["unmet_items"]
        ))

    def test_no_tagged_tickers_on_channel_is_unmet(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("rates")],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
            ],
        })
        self.assertEqual(out["status"], "unmet")
        self.assertEqual(out["matched_count"], 0)
        self.assertEqual(out["total_count"], 1)

    def test_unknown_channel_ticker_ignored(self) -> None:
        """A ticker whose symbol doesn't map to any channel is dropped."""
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities")],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                _ticker("FOOBARXYZ", direction_tag="contradicts thesis"),
            ],
        })
        # FOOBARXYZ has no channel mapping → ignored; XLE carries the day.
        self.assertEqual(out["status"], "met")


# ---------------------------------------------------------------------------
# Falsifier composer
# ---------------------------------------------------------------------------


class TestFalsifierStatus(unittest.TestCase):
    def test_missing_falsifiers_returns_not_available(self) -> None:
        out = evaluate_falsifier_status({})
        self.assertEqual(out["available"], False)
        self.assertEqual(out["status"], "none")
        self.assertEqual(out["triggered"], [])
        self.assertEqual(out["watching"], [])

    def test_contradicted_label_triggers(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["Named falsifier with enough length to keep"],
            "market_tickers": [
                _ticker("XLE", direction_tag="contradicts thesis"),
                _ticker("USO", direction_tag="contradicts thesis"),
            ],
        })
        self.assertEqual(out["status"], "triggered")
        self.assertEqual(len(out["triggered"]), 1)
        self.assertEqual(out["watching"], [])

    def test_unresolved_label_is_watch(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A falsifier that watches for a break"],
            "market_tickers": [
                _ticker("XLE", direction_tag=None),  # untagged
            ],
        })
        self.assertEqual(out["status"], "watch")
        self.assertEqual(out["triggered"], [])
        self.assertEqual(len(out["watching"]), 1)

    def test_validated_label_is_none(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A falsifier that watches for a break"],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                _ticker("USO", direction_tag="supports thesis"),
            ],
        })
        self.assertEqual(out["status"], "none")
        self.assertEqual(out["triggered"], [])
        self.assertEqual(out["watching"], [])


# ---------------------------------------------------------------------------
# compute_statuses composite
# ---------------------------------------------------------------------------


class TestComputeStatusesComposite(unittest.TestCase):
    def test_returns_both_blocks(self) -> None:
        both = compute_statuses({
            "minimum_proof_set": [_proof("equities")],
            "key_falsifiers":    ["Falsifier with enough length here"],
            "market_tickers":    [
                _ticker("XLE", direction_tag="supports thesis"),
            ],
        })
        self.assertIn("proof_status", both)
        self.assertIn("falsifier_status", both)
        self.assertEqual(both["proof_status"]["status"], "met")
        self.assertEqual(both["falsifier_status"]["status"], "none")


# ---------------------------------------------------------------------------
# DB persistence — all three hooks
# ---------------------------------------------------------------------------


class ProofPersistenceBase(unittest.TestCase):
    def setUp(self) -> None:
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(
            tempfile.gettempdir(), f"prooftest_{uuid.uuid4().hex}.db",
        )
        _db.DB_FILE = self._tmp
        _db._db_ready = False
        _db.init_db()

    def tearDown(self) -> None:
        _db.DB_FILE = self._orig
        _db._db_ready = False
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass

    def _base_event(self, **overrides) -> dict:
        ev = {
            "headline":          "Proof-hook event",
            "stage":              "realized",
            "persistence":        "medium",
            "mechanism_summary":  "A mechanism with enough length to pass.",
            "beneficiaries":      ["CVX"],
            "losers":             ["SU"],
            "assets_to_watch":    ["CVX", "SU"],
            "confidence":         "medium",
            "market_tickers":     [],
            "notes":              "",
        }
        ev.update(overrides)
        return ev


class TestSaveComputesAndPersistsStatus(ProofPersistenceBase):
    def test_save_writes_proof_and_falsifier_blocks(self) -> None:
        _db.save_event(self._base_event(
            minimum_proof_set=[_proof("equities")],
            key_falsifiers=["Named falsifier with enough length here"],
            market_tickers=[
                _ticker("XLE", direction_tag="supports thesis"),
            ],
        ))
        rows = _db.load_recent_events(limit=1)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        # Blocks come back as dicts, not raw strings.
        self.assertIsInstance(r["proof_status"], dict)
        self.assertIsInstance(r["falsifier_status"], dict)
        self.assertTrue(r["proof_status"]["available"])
        self.assertEqual(r["proof_status"]["status"], "met")
        self.assertEqual(r["falsifier_status"]["status"], "none")

    def test_save_without_proof_set_yields_not_available(self) -> None:
        _db.save_event(self._base_event())
        rows = _db.load_recent_events(limit=1)
        r = rows[0]
        self.assertIsInstance(r["proof_status"], dict)
        self.assertFalse(r["proof_status"].get("available", False))
        self.assertFalse(r["falsifier_status"].get("available", False))


class TestRefreshMarketRecomputesStatus(ProofPersistenceBase):
    def test_refresh_updates_proof_status(self) -> None:
        _db.save_event(self._base_event(
            minimum_proof_set=[_proof("equities")],
            key_falsifiers=["Named falsifier with enough length here"],
            market_tickers=[
                _ticker("XLE", direction_tag="contradicts thesis"),
            ],
        ))
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]
        # Sanity: save-time proof_status is unmet (contradicting evidence).
        self.assertEqual(rows[0]["proof_status"]["status"], "unmet")

        # Refresh with fresh supporting tickers — proof should flip met.
        _db.update_event_market_refresh(
            eid,
            market_tickers=[
                _ticker("XLE", direction_tag="supports thesis"),
            ],
            market_note="refreshed",
            last_market_check_at="2026-04-20T12:00:00",
        )
        rows = _db.load_recent_events(limit=1)
        self.assertEqual(rows[0]["proof_status"]["status"], "met")
        # falsifier_status should now be "none" since thesis is validating.
        self.assertEqual(rows[0]["falsifier_status"]["status"], "none")


class TestRevisitRecomputesStatus(ProofPersistenceBase):
    def test_revisit_snapshot_refreshes_status(self) -> None:
        _db.save_event(self._base_event(
            minimum_proof_set=[_proof("equities")],
            key_falsifiers=["Named falsifier with enough length here"],
            market_tickers=[
                _ticker("XLE", direction_tag="contradicts thesis"),
            ],
        ))
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]
        # After save: contradicting → proof unmet, falsifier triggered.
        self.assertEqual(rows[0]["proof_status"]["status"], "unmet")
        self.assertEqual(rows[0]["falsifier_status"]["status"], "triggered")

        # Append a revisit snapshot — this must re-persist the derived
        # blocks.  Even though the tickers list hasn't changed, the
        # revisit hook must compute a valid block (not leave the row's
        # derived status stale or NULL).
        _db.append_revisit_snapshot(eid, {
            "day": 5, "captured_at": "2026-04-25T00:00:00",
            "tickers": [{"symbol": "XLE", "role": "beneficiary",
                         "return_5d": -1.5, "direction": "down"}],
        })
        rows = _db.load_recent_events(limit=1)
        # Still a dict (not raw JSON / not NULL).
        self.assertIsInstance(rows[0]["proof_status"], dict)
        self.assertIsInstance(rows[0]["falsifier_status"], dict)
        # Classifier reads the same ticker set, so status values hold.
        self.assertEqual(rows[0]["proof_status"]["status"], "unmet")
        self.assertEqual(rows[0]["falsifier_status"]["status"], "triggered")


# ---------------------------------------------------------------------------
# Old-row fallback — columns NULL from pre-migration era
# ---------------------------------------------------------------------------


class TestOldRowFallback(ProofPersistenceBase):
    def test_null_columns_decode_to_empty_dicts(self) -> None:
        _db.save_event(self._base_event())
        # Simulate a pre-migration row by zapping both columns to NULL.
        with sqlite3.connect(_db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET proof_status = NULL, "
                "falsifier_status = NULL"
            )
        rows = _db.load_recent_events(limit=1)
        r = rows[0]
        self.assertEqual(r["proof_status"], {})
        self.assertEqual(r["falsifier_status"], {})


# ---------------------------------------------------------------------------
# No side effect on weighted_evidence / validation_outcome
# ---------------------------------------------------------------------------


class TestNoCollateralDamage(unittest.TestCase):
    """The new evaluator must not alter the existing validation_label
    or weighted_evidence helpers — it only reads them."""

    def test_validation_label_call_is_read_only(self) -> None:
        from validation_outcome import (
            score_validation_label,
            score_validation_outcome,
        )
        tickers = [
            _ticker("XLE", direction_tag="supports thesis"),
            _ticker("USO", direction_tag="contradicts thesis"),
        ]
        # Capture baseline before calling the evaluator.
        before_label = score_validation_label(tickers)
        before_outcome = score_validation_outcome(tickers)
        evaluate_falsifier_status({
            "key_falsifiers":  ["Falsifier with length enough"],
            "market_tickers":  tickers,
        })
        # Call again — identical output.
        self.assertEqual(score_validation_label(tickers), before_label)
        self.assertEqual(score_validation_outcome(tickers), before_outcome)


# ---------------------------------------------------------------------------
# Item-level evaluation rows — proof_status.items / falsifier_status.items
# ---------------------------------------------------------------------------


PROOF_ITEM_KEYS = {
    "channel", "expected_direction", "timing", "why_it_matters",
    "status", "matched_evidence",
}
FALSIFIER_ITEM_KEYS = {
    "channel", "trigger_condition", "timing", "why_it_breaks_thesis",
    "status", "matched_evidence",
}
PROOF_ITEM_STATUSES = {"met", "unmet", "insufficient"}
FALSIFIER_ITEM_STATUSES = {"triggered", "watch", "clear", "insufficient"}


class TestProofItemsShape(unittest.TestCase):
    def test_empty_block_has_empty_items_list(self) -> None:
        self.assertEqual(evaluate_proof_status({})["items"], [])

    def test_one_item_per_input_proof_entry(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [
                _proof("equities"), _proof("commodities"), _proof("rates"),
            ],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
            ],
        })
        self.assertEqual(len(out["items"]), 3)

    def test_every_item_has_exact_six_keys(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities")],
            "market_tickers":    [_ticker("XLE", direction_tag="supports thesis")],
        })
        for row in out["items"]:
            self.assertEqual(
                set(row.keys()), PROOF_ITEM_KEYS,
                f"item keys mismatch: {sorted(row.keys())}",
            )

    def test_item_status_vocabulary(self) -> None:
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities"), _proof("rates")],
            "market_tickers":    [_ticker("XLE", direction_tag="supports thesis")],
        })
        for row in out["items"]:
            self.assertIn(row["status"], PROOF_ITEM_STATUSES)

    def test_insufficient_vs_unmet_distinct(self) -> None:
        """No tagged tickers on the channel → ``insufficient``.
        Contradicting tags present → ``unmet``."""
        out = evaluate_proof_status({
            "minimum_proof_set": [
                _proof("equities"),   # will be unmet (contradicting below)
                _proof("rates"),      # will be insufficient (no rates ticker)
            ],
            "market_tickers": [
                _ticker("XLE", direction_tag="contradicts thesis"),
            ],
        })
        by_channel = {r["channel"]: r["status"] for r in out["items"]}
        self.assertEqual(by_channel["equities"], "unmet")
        self.assertEqual(by_channel["rates"], "insufficient")

    def test_legacy_summary_keys_still_present(self) -> None:
        """items was added alongside the legacy summary fields — none
        of the old keys are removed."""
        out = evaluate_proof_status({
            "minimum_proof_set": [_proof("equities")],
            "market_tickers":    [_ticker("XLE", direction_tag="supports thesis")],
        })
        for key in ("available", "status", "matched_count", "total_count",
                    "matched_items", "unmet_items", "items"):
            self.assertIn(key, out)

    def test_why_it_matters_falls_back_to_observation(self) -> None:
        """LLM-emitted items don't carry ``why_it_matters``; evaluator
        must fall back to ``observation`` so the field is never empty
        when source text exists."""
        out = evaluate_proof_status({
            "minimum_proof_set": [{
                "observation": "Specific proof observation on equities",
                "channel":     "equities",
                "threshold":   "≥1σ",
                "timing":      "1d",
            }],
            "market_tickers": [_ticker("XLE", direction_tag="supports thesis")],
        })
        self.assertEqual(len(out["items"]), 1)
        self.assertIn(
            "Specific proof observation",
            out["items"][0]["why_it_matters"],
        )


class TestFalsifierItemsShape(unittest.TestCase):
    def test_empty_block_has_empty_items_list(self) -> None:
        self.assertEqual(evaluate_falsifier_status({})["items"], [])

    def test_one_item_per_input_falsifier(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": [
                "First falsifier with enough length here",
                "Second falsifier that is concrete enough",
            ],
            "market_tickers": [_ticker("XLE", direction_tag="supports thesis")],
        })
        self.assertEqual(len(out["items"]), 2)

    def test_every_item_has_exact_six_keys(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A single concrete falsifier string"],
            "market_tickers": [_ticker("XLE", direction_tag="supports thesis")],
        })
        for row in out["items"]:
            self.assertEqual(set(row.keys()), FALSIFIER_ITEM_KEYS)

    def test_item_status_vocabulary(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A single concrete falsifier string"],
            "market_tickers": [_ticker("XLE", direction_tag="contradicts thesis"),
                                _ticker("USO", direction_tag="contradicts thesis")],
        })
        for row in out["items"]:
            self.assertIn(row["status"], FALSIFIER_ITEM_STATUSES)

    def test_contradicted_label_items_triggered(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A concrete thesis-breaking observation"],
            "market_tickers": [
                _ticker("XLE", direction_tag="contradicts thesis"),
                _ticker("USO", direction_tag="contradicts thesis"),
            ],
        })
        self.assertTrue(all(r["status"] == "triggered" for r in out["items"]))

    def test_validated_label_items_clear(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A concrete thesis-breaking observation"],
            "market_tickers": [
                _ticker("XLE", direction_tag="supports thesis"),
                _ticker("USO", direction_tag="supports thesis"),
            ],
        })
        self.assertTrue(all(r["status"] == "clear" for r in out["items"]))

    def test_no_data_label_items_insufficient(self) -> None:
        out = evaluate_falsifier_status({
            "key_falsifiers": ["A concrete thesis-breaking observation"],
            "market_tickers": [],  # no tickers at all
        })
        self.assertTrue(all(r["status"] == "insufficient" for r in out["items"]))

    def test_dict_form_falsifier_preserves_structured_fields(self) -> None:
        """When a falsifier is already the deterministic dict form
        (from ``falsifier_set_for_family``), its channel / timing /
        why_it_breaks_thesis must pass through onto the evaluated row."""
        out = evaluate_falsifier_status({
            "key_falsifiers": [{
                "channel":              "equities",
                "trigger_condition":    "Targeted name recovers ≥50% within 5d",
                "timing":               "1-5d",
                "why_it_breaks_thesis": "Thesis requires sustained discount on the targeted name.",
            }],
            "market_tickers": [_ticker("XLE", direction_tag="supports thesis")],
        })
        row = out["items"][0]
        self.assertEqual(row["channel"], "equities")
        self.assertEqual(row["timing"], "1-5d")
        self.assertIn("Thesis requires", row["why_it_breaks_thesis"])


# ---------------------------------------------------------------------------
# DB backfill — old rows without ``items`` still load cleanly
# ---------------------------------------------------------------------------


class TestOldRowItemsBackfill(ProofPersistenceBase):
    def test_pre_items_block_backfills_empty_items_list(self) -> None:
        """An event written before the item-level evaluator existed
        stored ``proof_status`` / ``falsifier_status`` dicts without an
        ``items`` key.  The read path must coerce them to have
        ``items=[]`` so downstream consumers can always iterate."""
        _db.save_event(self._base_event())

        # Overwrite the stored block with the pre-items shape
        # (available=True summary but no items key).
        pre_items_proof = json.dumps({
            "available":     True,
            "status":        "met",
            "matched_count": 1,
            "total_count":   1,
            "matched_items": [{"observation": "x", "channel": "equities",
                               "threshold": "y", "timing": "1d",
                               "evidence": "legacy"}],
            "unmet_items":   [],
        })
        pre_items_fals = json.dumps({
            "available": True,
            "status":    "none",
            "triggered": [],
            "watching":  [],
        })
        with sqlite3.connect(_db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET proof_status = ?, falsifier_status = ?",
                (pre_items_proof, pre_items_fals),
            )
        rows = _db.load_recent_events(limit=1)
        r = rows[0]
        self.assertIn("items", r["proof_status"])
        self.assertEqual(r["proof_status"]["items"], [])
        self.assertIn("items", r["falsifier_status"])
        self.assertEqual(r["falsifier_status"]["items"], [])

    def test_null_column_still_decodes_to_empty_dict(self) -> None:
        """A truly NULL column (pre-migration event, evaluator never
        ran) must stay ``{}`` — no synthetic ``items`` key is added,
        matching the contract that empty means 'not evaluated at all'."""
        _db.save_event(self._base_event())
        with sqlite3.connect(_db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET proof_status = NULL, "
                "falsifier_status = NULL"
            )
        rows = _db.load_recent_events(limit=1)
        self.assertEqual(rows[0]["proof_status"], {})
        self.assertEqual(rows[0]["falsifier_status"], {})


# ---------------------------------------------------------------------------
# /events/{event_id} surfaces the item-level detail
# ---------------------------------------------------------------------------


class TestEventsDetailReturnsItems(ProofPersistenceBase):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def test_get_event_detail_returns_proof_and_falsifier_items(self) -> None:
        _db.save_event(self._base_event(
            minimum_proof_set=[_proof("equities"), _proof("rates")],
            key_falsifiers=["Concrete thesis-breaking observation one",
                             "Concrete thesis-breaking observation two"],
            market_tickers=[_ticker("XLE", direction_tag="supports thesis")],
        ))
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]

        r = self.client.get(f"/events/{eid}")
        self.assertEqual(r.status_code, 200)
        body = r.json()

        # Existing keys untouched.
        for key in ("available", "status", "matched_count", "total_count",
                    "matched_items", "unmet_items", "items"):
            self.assertIn(key, body["proof_status"])
        for key in ("available", "status", "triggered", "watching", "items"):
            self.assertIn(key, body["falsifier_status"])

        # Item-level detail is present and carries the new fields.
        self.assertEqual(len(body["proof_status"]["items"]), 2)
        self.assertEqual(len(body["falsifier_status"]["items"]), 2)
        for row in body["proof_status"]["items"]:
            self.assertIn(row["status"], ["met", "unmet", "insufficient"])
        for row in body["falsifier_status"]["items"]:
            self.assertIn(row["status"],
                          ["triggered", "watch", "clear", "insufficient"])


# ---------------------------------------------------------------------------
# /events/{event_id} always emits shaped proof / falsifier defaults
# ---------------------------------------------------------------------------


class TestEventDetailAlwaysShapedStatus(ProofPersistenceBase):
    def setUp(self) -> None:
        super().setUp()
        from fastapi.testclient import TestClient
        import api as _api_mod
        self.client = TestClient(_api_mod.app)

    def test_low_info_event_returns_shaped_proof_status(self) -> None:
        """An event with no ``minimum_proof_set`` (low-info row) must
        still get the full proof_status shape on the detail endpoint,
        never a bare ``{}``."""
        _db.save_event(self._base_event())
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]

        body = self.client.get(f"/events/{eid}").json()
        ps = body["proof_status"]
        for key in ("available", "status", "matched_count", "total_count",
                    "matched_items", "unmet_items", "items"):
            self.assertIn(key, ps,
                          f"proof_status missing {key!r} on low-info row")
        self.assertIsInstance(ps["items"], list)
        self.assertIsInstance(ps["matched_items"], list)
        self.assertIsInstance(ps["unmet_items"], list)

    def test_low_info_event_returns_shaped_falsifier_status(self) -> None:
        _db.save_event(self._base_event())
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]

        body = self.client.get(f"/events/{eid}").json()
        fs = body["falsifier_status"]
        for key in ("available", "status", "triggered", "watching", "items"):
            self.assertIn(key, fs,
                          f"falsifier_status missing {key!r} on low-info row")
        self.assertIsInstance(fs["items"], list)
        self.assertIsInstance(fs["triggered"], list)
        self.assertIsInstance(fs["watching"], list)

    def test_null_column_event_returns_shaped_defaults(self) -> None:
        """Pre-migration rows where the column is literally NULL must
        still get the full shape on the HTTP response."""
        _db.save_event(self._base_event())
        with sqlite3.connect(_db.DB_FILE) as conn:
            conn.execute(
                "UPDATE events SET proof_status = NULL, "
                "falsifier_status = NULL"
            )
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]

        body = self.client.get(f"/events/{eid}").json()
        self.assertEqual(body["proof_status"]["available"], False)
        self.assertEqual(body["proof_status"]["status"], "none")
        self.assertEqual(body["proof_status"]["matched_count"], 0)
        self.assertEqual(body["proof_status"]["total_count"], 0)
        self.assertEqual(body["proof_status"]["items"], [])
        self.assertEqual(body["proof_status"]["matched_items"], [])
        self.assertEqual(body["proof_status"]["unmet_items"], [])
        self.assertEqual(body["falsifier_status"]["available"], False)
        self.assertEqual(body["falsifier_status"]["status"], "none")
        self.assertEqual(body["falsifier_status"]["items"], [])
        self.assertEqual(body["falsifier_status"]["triggered"], [])
        self.assertEqual(body["falsifier_status"]["watching"], [])

    def test_populated_event_status_passes_through_unchanged(self) -> None:
        """An event with a real proof set + supporting evidence must
        land on ``available=True``, ``status="met"`` in the response —
        coercion doesn't clobber populated blocks."""
        _db.save_event(self._base_event(
            minimum_proof_set=[_proof("equities")],
            key_falsifiers=["Concrete thesis-breaking observation one"],
            market_tickers=[
                _ticker("XLE", direction_tag="supports thesis"),
            ],
        ))
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]

        body = self.client.get(f"/events/{eid}").json()
        self.assertEqual(body["proof_status"]["available"], True)
        self.assertEqual(body["proof_status"]["status"], "met")
        self.assertEqual(len(body["proof_status"]["items"]), 1)
        self.assertEqual(body["falsifier_status"]["available"], True)
        self.assertEqual(body["falsifier_status"]["status"], "none")

    def test_top_level_event_fields_unchanged(self) -> None:
        """Coercion must only touch proof_status / falsifier_status —
        every other top-level key passes through unmodified."""
        _db.save_event(self._base_event(
            headline="Coercion should not touch top-level fields",
        ))
        rows = _db.load_recent_events(limit=1)
        eid = rows[0]["id"]
        body = self.client.get(f"/events/{eid}").json()
        self.assertEqual(
            body["headline"], "Coercion should not touch top-level fields",
        )
        self.assertEqual(body["confidence"], "medium")
        self.assertEqual(body["beneficiaries"], ["CVX"])


# ---------------------------------------------------------------------------
# Coercion helpers in isolation — pure contract
# ---------------------------------------------------------------------------


class TestCoerceHelpers(unittest.TestCase):
    def test_coerce_proof_status_fills_empty_dict(self) -> None:
        from proof_evaluator import coerce_proof_status
        out = coerce_proof_status({})
        for key in ("available", "status", "matched_count", "total_count",
                    "matched_items", "unmet_items", "items"):
            self.assertIn(key, out)
        self.assertEqual(out["items"], [])

    def test_coerce_proof_status_fills_none(self) -> None:
        from proof_evaluator import coerce_proof_status
        out = coerce_proof_status(None)
        self.assertEqual(out["status"], "none")
        self.assertEqual(out["items"], [])

    def test_coerce_proof_status_preserves_populated_block(self) -> None:
        from proof_evaluator import coerce_proof_status
        src = {
            "available":     True,
            "status":        "met",
            "matched_count": 1,
            "total_count":   1,
            "matched_items": [{"channel": "equities"}],
            "unmet_items":   [],
            "items":         [{"channel": "equities", "status": "met"}],
        }
        out = coerce_proof_status(src)
        self.assertEqual(out, src)

    def test_coerce_falsifier_status_fills_empty_dict(self) -> None:
        from proof_evaluator import coerce_falsifier_status
        out = coerce_falsifier_status({})
        for key in ("available", "status", "triggered", "watching", "items"):
            self.assertIn(key, out)
        self.assertEqual(out["items"], [])

    def test_coerce_falsifier_status_fills_none(self) -> None:
        from proof_evaluator import coerce_falsifier_status
        out = coerce_falsifier_status(None)
        self.assertEqual(out["status"], "none")
        self.assertEqual(out["triggered"], [])
        self.assertEqual(out["watching"], [])

    def test_coerce_coerces_non_list_items_to_list(self) -> None:
        """If a malformed block has ``items`` as a non-list (dict, None,
        etc), coerce it to an empty list."""
        from proof_evaluator import coerce_falsifier_status, coerce_proof_status
        out = coerce_proof_status({"available": True, "items": "oops"})
        self.assertEqual(out["items"], [])
        out = coerce_falsifier_status({"available": True, "items": None})
        self.assertEqual(out["items"], [])


if __name__ == "__main__":
    unittest.main()
