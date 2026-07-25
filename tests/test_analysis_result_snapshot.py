"""A1-3R — the immutable saved-analysis result snapshot.

A saved analysis must reopen showing what the successful run actually
reported.  Before this repair `_build_event_record` silently dropped most of
the structured result, so reopening displayed "Not reported" for information
the analysis DID produce — persistence loss wearing the costume of honest
missingness.

The snapshot records validated OUTPUT.  It is not evidence that the output is
correct, and it is deliberately separate from `analysis_provenance`, which
records the INPUTS.  Nothing here reads or writes that table.

No provider is reached and no live database is touched.
"""

import json
import os
import sqlite3
import tempfile
import unittest
import uuid

import analysis_result_snapshot as ars
import db as _db


def _analysis(**over) -> dict:
    base = {
        "what_changed": "Outage removed 400kb/d of refining capacity.",
        "mechanism_summary": "The regional diesel balance tightens.",
        "transmission_chain": ["outage", "cracks widen", "costs rise"],
        "transmission_path": [
            {"step": 1, "node": "Refinery capacity", "so_what": "Supply removed"},
            {"step": 2, "node": "Crack spreads", "so_what": "Margins widen"},
        ],
        "hidden_mechanism": {
            "transmission_type": "physical_supply",
            "bottleneck_type": "processing_capacity",
            "substitution_escape_path": "Seaborne imports within 3 weeks",
            "critical_breakpoints": ["Restart before day 10"],
            "optional_confirming_evidence": ["Freight rate divergence"],
            "source_quality": {"tier": "single_outlet",
                               "evidence_limitations": ["One outlet only"]},
            "regime_caveats": {"evidence_to_revisit": ["Demand prints"]},
        },
        "beneficiaries": ["independent refiners"],
        "losers": ["road hauliers"],
        "primary_assets": ["VLO", "PSX"],
        "secondary_assets": ["ODFL"],
        "hedge_or_signal_assets": ["XLE"],
        "expected_second_order_channels": ["SUPPLY_CHAIN", "INFLATION"],
        "counterforces": [{"force": "SPR release", "effect": "Could offset",
                           "likelihood": "medium"}],
        "substitution_barriers": [{"barrier": "Import berths", "severity": "high"}],
        "competing_thesis": {"thesis": "Demand weakness dominates",
                             "evidence": "Freight volumes falling"},
        "adversarial_challenge": "The outage may be repaired faster.",
        "key_falsifiers": ["Cracks flat after 5 sessions"],
        "minimum_proof_set": ["Diesel crack > +8%"],
        "proof_status": {"status": "not_yet_observed"},
        "falsifier_status": {"status": "not_yet_observed"},
        "horizon_checkpoints": {"1d": "Crack reaction", "5d": "Inventory print"},
        "monitor_plan": ["Weekly EIA inventory print"],
        "quality_tier": "actionable",
        "quality_warnings": ["Single-outlet estimate"],
        "validation_warnings": ["Ticker set unconfirmed"],
        "degraded": False,
        "regime_conditioned_caveat": "Holds while imports stay constrained.",
        # Volatile / retrieval-only — must NOT enter the snapshot.
        "confidence_calibration": {"bucket": "medium"},
        "validation_status_v2": {"status": "pending"},
        "reaction_profile_v1": {"profile": "x"},
    }
    base.update(over)
    return base


class _DbBase(unittest.TestCase):
    def setUp(self):
        self._orig = _db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(),
                                 f"test_ars_{uuid.uuid4().hex}.db")
        _db.DB_FILE = self._tmp
        _db.init_db()

    def tearDown(self):
        _db.DB_FILE = self._orig
        if os.path.exists(self._tmp):
            try:
                os.remove(self._tmp)
            except PermissionError:
                pass


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class TestSnapshotSchema(_DbBase):

    def test_table_is_additive_at_the_existing_schema_version(self):
        conn = sqlite3.connect(self._tmp)
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.close()
        self.assertIn("analysis_result_snapshot", names)
        # The A1-2 provenance table is a DIFFERENT concept and must survive.
        self.assertIn("analysis_provenance", names)
        self.assertEqual(version, _db.SCHEMA_VERSION)

    def test_an_existing_database_gains_the_table_without_data_loss(self):
        conn = sqlite3.connect(self._tmp)
        conn.execute("DROP TABLE analysis_result_snapshot")
        conn.execute("INSERT INTO events (timestamp, headline, stage, persistence)"
                     " VALUES ('2026-01-01T00:00:00','legacy row','s','p')")
        conn.commit()
        conn.close()
        _db.init_db()
        conn = sqlite3.connect(self._tmp)
        has = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                           " AND name='analysis_result_snapshot'").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        conn.close()
        self.assertEqual((has, rows), (1, 1))


# ---------------------------------------------------------------------------
# The inclusion boundary
# ---------------------------------------------------------------------------

class TestSnapshotContent(unittest.TestCase):

    def test_captures_every_required_readout_field(self):
        snap = ars.build_result_snapshot(_analysis())
        for f in ars.RESULT_SNAPSHOT_FIELDS:
            self.assertIn(f, snap["result"], f"{f} missing from the snapshot")

    def test_nested_hidden_mechanism_survives_exactly(self):
        source = _analysis()
        snap = ars.build_result_snapshot(source)
        self.assertEqual(snap["result"]["hidden_mechanism"],
                         source["hidden_mechanism"])

    def test_arrays_and_objects_retain_order_and_values(self):
        source = _analysis()
        snap = ars.build_result_snapshot(source)
        self.assertEqual([s["node"] for s in snap["result"]["transmission_path"]],
                         ["Refinery capacity", "Crack spreads"])
        self.assertEqual(snap["result"]["primary_assets"], ["VLO", "PSX"])
        self.assertEqual(snap["result"]["expected_second_order_channels"],
                         ["SUPPLY_CHAIN", "INFLATION"])

    def test_excludes_volatile_retrieval_only_fields(self):
        snap = ars.build_result_snapshot(_analysis())
        for volatile in ("confidence_calibration", "validation_status_v2",
                         "reaction_profile_v1"):
            self.assertNotIn(volatile, snap["result"],
                             f"{volatile} is retrieval state, not saved output")

    def test_an_absent_field_stays_absent_rather_than_being_invented(self):
        source = _analysis()
        del source["monitor_plan"]
        del source["competing_thesis"]
        snap = ars.build_result_snapshot(source)
        self.assertNotIn("monitor_plan", snap["result"])
        self.assertNotIn("competing_thesis", snap["result"])

    def test_an_explicit_false_is_preserved_not_dropped_as_empty(self):
        snap = ars.build_result_snapshot(_analysis(degraded=False))
        self.assertIn("degraded", snap["result"])
        self.assertIs(snap["result"]["degraded"], False)

    def test_serialization_is_deterministic(self):
        a = ars.serialize_snapshot(ars.build_result_snapshot(_analysis()))
        b = ars.serialize_snapshot(ars.build_result_snapshot(_analysis()))
        self.assertEqual(a, b)
        self.assertEqual(ars.serialize_snapshot({"b": 1, "a": 2}),
                         ars.serialize_snapshot({"a": 2, "b": 1}))

    def test_the_snapshot_carries_its_schema_version(self):
        snap = ars.build_result_snapshot(_analysis())
        self.assertEqual(snap["schema_version"], ars.RESULT_SNAPSHOT_VERSION)

    def test_a_snapshot_of_an_empty_analysis_is_empty_not_fabricated(self):
        snap = ars.build_result_snapshot({})
        self.assertEqual(snap["result"], {})


# ---------------------------------------------------------------------------
# Persistence, immutability, validation
# ---------------------------------------------------------------------------

class TestSnapshotPersistence(_DbBase):

    def _save(self, event_id: int, analysis: dict | None = None):
        _db.save_analysis_result_snapshot(
            event_id, ars.build_result_snapshot(analysis or _analysis()),
            created_at="2026-07-26T12:00:00")

    def test_one_event_receives_exactly_one_snapshot(self):
        self._save(5)
        with self.assertRaises(Exception):
            self._save(5)

    def test_an_existing_snapshot_is_never_silently_overwritten(self):
        self._save(6, _analysis(quality_tier="watch_only"))
        try:
            self._save(6, _analysis(quality_tier="actionable"))
        except Exception:
            pass
        stored = _db.load_analysis_result_snapshot(6)
        self.assertEqual(stored["result"]["quality_tier"], "watch_only")

    def test_a_round_trip_preserves_the_result_exactly(self):
        source = _analysis()
        self._save(7, source)
        stored = _db.load_analysis_result_snapshot(7)
        expected = ars.build_result_snapshot(source)["result"]
        self.assertEqual(stored["result"], expected)

    def test_a_missing_snapshot_reads_as_none_never_fabricated(self):
        self.assertIsNone(_db.load_analysis_result_snapshot(999))

    def test_an_absent_or_unusable_id_fails_closed_instead_of_raising(self):
        # _build_cached_response is also called directly with hand-built rows
        # that carry no ``id``; a reader that raised there would take the
        # whole cached response down over an absent optional record.
        for bad in (None, "", "not-an-int", object()):
            with self.subTest(event_id=repr(bad)):
                self.assertIsNone(_db.load_analysis_result_snapshot(bad))

    def test_malformed_stored_json_fails_closed(self):
        self._save(8)
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE analysis_result_snapshot SET result_json = '{not json'"
                     " WHERE analysis_event_id = 8")
        conn.commit()
        conn.close()
        self.assertIsNone(_db.load_analysis_result_snapshot(8))

    def test_a_tampered_snapshot_fails_closed(self):
        self._save(9)
        conn = sqlite3.connect(self._tmp)
        conn.execute("UPDATE analysis_result_snapshot "
                     "SET result_json = '{\"quality_tier\": \"actionable\"}' "
                     "WHERE analysis_event_id = 9")
        conn.commit()
        conn.close()
        self.assertIsNone(_db.load_analysis_result_snapshot(9),
                          "a hash mismatch must not be served as saved output")


# ---------------------------------------------------------------------------
# Restoring onto a cached analysis block
# ---------------------------------------------------------------------------

class TestSnapshotRestore(unittest.TestCase):

    def test_saved_values_replace_empty_column_defaults(self):
        cached = {"mechanism_summary": "stored", "primary_assets": [],
                  "key_falsifiers": [], "transmission_path": []}
        merged = ars.apply_result_snapshot(cached, ars.build_result_snapshot(_analysis()))
        self.assertEqual(merged["primary_assets"], ["VLO", "PSX"])
        self.assertEqual(merged["key_falsifiers"], ["Cracks flat after 5 sessions"])
        self.assertEqual(len(merged["transmission_path"]), 2)

    def test_fields_outside_the_snapshot_are_left_untouched(self):
        cached = {"validation_status_v2": {"status": "validated"},
                  "policy_constraint": {"available": True},
                  "confidence": "high"}
        merged = ars.apply_result_snapshot(cached, ars.build_result_snapshot(_analysis()))
        self.assertEqual(merged["validation_status_v2"], {"status": "validated"})
        self.assertEqual(merged["policy_constraint"], {"available": True})
        self.assertEqual(merged["confidence"], "high")

    def test_restoring_does_not_mutate_the_stored_snapshot(self):
        snap = ars.build_result_snapshot(_analysis())
        before = json.dumps(snap, sort_keys=True)
        merged = ars.apply_result_snapshot({}, snap)
        merged["primary_assets"].append("MUTATED")
        self.assertEqual(json.dumps(snap, sort_keys=True), before)

    def test_a_missing_snapshot_leaves_the_legacy_block_alone(self):
        cached = {"mechanism_summary": "stored", "primary_assets": []}
        self.assertEqual(ars.apply_result_snapshot(cached, None), cached)

    def test_a_malformed_snapshot_leaves_the_legacy_block_alone(self):
        cached = {"mechanism_summary": "stored"}
        for bad in ({}, {"result": "not a dict"}, {"no_result": 1}, "text", None):
            self.assertEqual(ars.apply_result_snapshot(cached, bad), cached)


if __name__ == "__main__":
    unittest.main()
