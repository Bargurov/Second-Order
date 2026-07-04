"""Tests for the L2B-0 materiality-hygiene annotation path.

The annotation reuses the existing ``event_hygiene`` sidecar with NEW
``override_class`` values (``materiality_hygiene_firm`` / ``_held``) that are
deliberately OUTSIDE ``data_hygiene_report._VALID_HYGIENE_CLASSES`` and are NOT
``synthetic_seed`` -- so the hygiene derivation and ``db.synthetic_seed_ids``
ignore them and no accepted denominator moves.  The annotation set is the pushed
L2A-1 adjudication (stats/L2_MATERIALITY_ADJUDICATION.md, commit 7c6f6b9):
firm hygiene {49, 51, 44}; held / leaning hygiene {50, 54, 64, 70, 48}.
"""

import os
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

import db
from scripts import data_hygiene_report as dh
from scripts import materiality_annotation as ma

_ROOT = Path(__file__).resolve().parents[1]
_LIVE_DB = _ROOT / "events.db"

_FIXED_TS = "2026-07-04T00:00:00+00:00"


def _minimal_db(path):
    """A tiny DB with just the tables the annotation path touches."""
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, event_date TEXT, "
        "stage TEXT, market_tickers TEXT, model TEXT)"
    )
    conn.execute(
        "CREATE TABLE event_hygiene (event_id INTEGER PRIMARY KEY, override_class TEXT, "
        "override_reason TEXT, created_at TEXT NOT NULL, "
        "FOREIGN KEY (event_id) REFERENCES events (id))"
    )
    for eid in (2, 9, 40, 25, 26, 39, 44, 48, 49, 50, 51, 54, 64, 70):
        conn.execute("INSERT INTO events (id, headline, stage) VALUES (?,?,?)",
                     (eid, f"row {eid}", "realized"))
    conn.commit()
    conn.close()


class TierInvariantTests(unittest.TestCase):
    def test_tiers_disjoint_from_valid_hygiene_classes(self):
        # The whole denominator-safety argument: these classes must NOT be a
        # recognised hygiene class, or the derivation would act on them.
        self.assertNotIn(ma.TIER_FIRM, dh._VALID_HYGIENE_CLASSES)
        self.assertNotIn(ma.TIER_HELD, dh._VALID_HYGIENE_CLASSES)

    def test_tiers_are_not_synthetic_seed(self):
        # db.synthetic_seed_ids is the SINGLE accepted-corpus exclusion source.
        self.assertNotEqual(ma.TIER_FIRM, db.SYNTHETIC_SEED_OVERRIDE)
        self.assertNotEqual(ma.TIER_HELD, db.SYNTHETIC_SEED_OVERRIDE)


class AnnotationSetTests(unittest.TestCase):
    def test_firm_and_held_ids_match_adjudication(self):
        firm = {a["event_id"] for a in ma.L2B0_ANNOTATIONS if a["tier"] == ma.TIER_FIRM}
        held = {a["event_id"] for a in ma.L2B0_ANNOTATIONS if a["tier"] == ma.TIER_HELD}
        self.assertEqual(firm, {49, 51, 44})
        self.assertEqual(held, {50, 54, 64, 70, 48})
        self.assertEqual(len(ma.L2B0_ANNOTATIONS), 8)

    def test_every_annotation_carries_group_and_canonical_anchor(self):
        for a in ma.L2B0_ANNOTATIONS:
            self.assertTrue(a["group"].startswith("G"))
            self.assertIsInstance(a["canonical_event_id"], int)


class ApplyLoadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.gettempdir()) / f"ma_min_{uuid.uuid4().hex[:8]}.db"
        _minimal_db(self.tmp)

    def tearDown(self):
        if self.tmp.exists():
            os.remove(self.tmp)

    def test_apply_writes_eight_rows_and_load_roundtrips(self):
        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        conn.commit(); conn.close()

        loaded = ma.load_annotations(str(self.tmp))
        firm = [r for r in loaded if r["tier"] == ma.TIER_FIRM]
        held = [r for r in loaded if r["tier"] == ma.TIER_HELD]
        self.assertEqual(len(firm), 3)
        self.assertEqual(len(held), 5)
        # rationale text carries the group + canonical anchor
        by_id = {r["event_id"]: r for r in loaded}
        self.assertIn("G2", by_id[49]["reason"])
        self.assertIn("2", by_id[49]["reason"])

    def test_apply_is_idempotent(self):
        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        conn.commit()
        n = conn.execute(
            "SELECT COUNT(*) FROM event_hygiene WHERE override_class IN (?,?)",
            (ma.TIER_FIRM, ma.TIER_HELD),
        ).fetchone()[0]
        conn.close()
        self.assertEqual(n, 8)


class OverlayConsumerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.gettempdir()) / f"ma_ov_{uuid.uuid4().hex[:8]}.db"
        _minimal_db(self.tmp)

    def tearDown(self):
        if self.tmp.exists():
            os.remove(self.tmp)

    def test_overlay_empty_on_unannotated_db(self):
        ov = ma.overlay_summary(str(self.tmp))
        self.assertEqual(ov["firm_count"], 0)
        self.assertEqual(ov["held_count"], 0)
        self.assertFalse(ov["affects_accepted_denominator"])

    def test_overlay_surfaces_tiers_after_apply(self):
        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        conn.commit(); conn.close()
        ov = ma.overlay_summary(str(self.tmp))
        self.assertEqual(ov["firm_count"], 3)
        self.assertEqual(ov["held_count"], 5)
        self.assertEqual(sorted(ov["firm_hygiene_ids"]), [44, 49, 51])
        self.assertEqual(sorted(ov["held_hygiene_ids"]), [48, 50, 54, 64, 70])
        self.assertFalse(ov["affects_accepted_denominator"])
        self.assertIn("L2_MATERIALITY_ADJUDICATION", ov["source"])

    def test_overlay_note_is_descriptive_and_banned_clean(self):
        ov = ma.overlay_summary(str(self.tmp))
        note = ov["note"].lower()
        self.assertIn("descriptive", note)
        self.assertTrue("denominator" in note or "accepted-row" in note)
        for banned in ("buy", "sell", "signal", "alpha", "proof", "confirmed", "forecast"):
            self.assertNotIn(banned, note)

    def test_data_hygiene_report_includes_overlay_key(self):
        # additive key must exist on both the full and the empty report
        self.assertIn("materiality_hygiene_overlay", dh._empty_report())
        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        conn.commit(); conn.close()
        report = dh.summarize_data_hygiene(db_path=str(self.tmp))
        self.assertIn("materiality_hygiene_overlay", report)
        self.assertEqual(report["materiality_hygiene_overlay"]["firm_count"], 3)
        self.assertEqual(report["materiality_hygiene_overlay"]["held_count"], 5)


@unittest.skipUnless(_LIVE_DB.exists(), "live events.db required for the temp-DB proof")
class DenominatorInvarianceProofTests(unittest.TestCase):
    """The temp-DB proof: annotating must not move any accepted denominator."""

    def setUp(self):
        self.tmp = Path(tempfile.gettempdir()) / f"ma_proof_{uuid.uuid4().hex[:8]}.db"
        shutil.copy2(str(_LIVE_DB), str(self.tmp))

    def tearDown(self):
        if self.tmp.exists():
            os.remove(self.tmp)

    def _k2_snapshot(self):
        from scripts.effective_independent_evidence_report import (
            _assemble_rows, build_clusters)
        rows, _edq, _cov = _assemble_rows(str(self.tmp))
        clusters = build_clusters(rows)
        clusters.sort(key=lambda c: -c["size"])
        from collections import Counter
        c01 = clusters[0]
        split = Counter(r["outcome"] for r in rows if r["event_id"] in set(c01["event_ids"]))
        return {
            "accepted": len(rows),
            "clusters": len(clusters),
            "c01": c01["size"],
            "c01_split": (split["support"], split["contradiction"], split["unresolved"]),
        }

    def _seed_ids(self):
        conn = sqlite3.connect(str(self.tmp))
        try:
            return db.synthetic_seed_ids(conn)
        finally:
            conn.close()

    def test_annotating_temp_copy_leaves_accepted_denominator_unchanged(self):
        before = self._k2_snapshot()
        seed_before = self._seed_ids()
        self.assertEqual(before["accepted"], 86)  # sanity: real live baseline
        self.assertEqual(before["clusters"], 7)
        self.assertEqual(before["c01"], 79)

        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        conn.commit(); conn.close()

        # the annotations really landed (guards against a false-green live read)
        loaded = ma.load_annotations(str(self.tmp))
        self.assertEqual(len([r for r in loaded if r["tier"] == ma.TIER_FIRM]), 3)
        self.assertEqual(len([r for r in loaded if r["tier"] == ma.TIER_HELD]), 5)

        after = self._k2_snapshot()
        seed_after = self._seed_ids()
        self.assertEqual(before, after)          # every K2 figure identical
        self.assertEqual(seed_before, seed_after)  # synthetic-seed set untouched
        # and none of the annotated ids leaked into the synthetic-seed exclusion
        self.assertTrue(seed_after.isdisjoint({44, 48, 49, 50, 51, 54, 64, 70}))


class OverwriteGuardTests(unittest.TestCase):
    """apply_annotations must never silently overwrite an unrelated hygiene row."""

    def setUp(self):
        self.tmp = Path(tempfile.gettempdir()) / f"ma_guard_{uuid.uuid4().hex[:8]}.db"
        _minimal_db(self.tmp)

    def tearDown(self):
        if self.tmp.exists():
            os.remove(self.tmp)

    def _preset(self, event_id, klass, reason="preset row"):
        conn = sqlite3.connect(str(self.tmp))
        conn.execute(
            "INSERT OR REPLACE INTO event_hygiene "
            "(event_id, override_class, override_reason, created_at) VALUES (?,?,?,?)",
            (event_id, klass, reason, _FIXED_TS))
        conn.commit(); conn.close()

    def _materiality_count(self):
        conn = sqlite3.connect(str(self.tmp))
        n = conn.execute(
            "SELECT COUNT(*) FROM event_hygiene WHERE override_class IN (?,?)",
            (ma.TIER_FIRM, ma.TIER_HELD)).fetchone()[0]
        conn.close()
        return n

    def _class_of(self, event_id):
        conn = sqlite3.connect(str(self.tmp))
        row = conn.execute(
            "SELECT override_class FROM event_hygiene WHERE event_id=?",
            (event_id,)).fetchone()
        conn.close()
        return row[0] if row else None

    def test_aborts_on_existing_synthetic_seed_and_writes_nothing(self):
        # event 44 is a firm target -- pre-existing synthetic_seed must not be lost
        self._preset(44, db.SYNTHETIC_SEED_OVERRIDE)
        conn = sqlite3.connect(str(self.tmp))
        try:
            with self.assertRaises(ma.HygieneAnnotationConflict):
                ma.apply_annotations(conn, created_at=_FIXED_TS)
        finally:
            conn.rollback(); conn.close()
        self.assertEqual(self._materiality_count(), 0)
        self.assertEqual(self._class_of(44), db.SYNTHETIC_SEED_OVERRIDE)

    def test_aborts_on_different_materiality_tier(self):
        # 44 wanted as firm; pre-existing HELD must not be silently re-tiered
        self._preset(44, ma.TIER_HELD)
        conn = sqlite3.connect(str(self.tmp))
        try:
            with self.assertRaises(ma.HygieneAnnotationConflict):
                ma.apply_annotations(conn, created_at=_FIXED_TS)
        finally:
            conn.rollback(); conn.close()
        self.assertEqual(self._class_of(44), ma.TIER_HELD)
        self.assertEqual(self._materiality_count(), 1)  # only the preset held row

    def test_no_partial_write_when_one_target_conflicts(self):
        # one held target (48) blocked; the other 7 clean targets must NOT be written
        self._preset(48, db.SYNTHETIC_SEED_OVERRIDE)
        conn = sqlite3.connect(str(self.tmp))
        try:
            with self.assertRaises(ma.HygieneAnnotationConflict):
                ma.apply_annotations(conn, created_at=_FIXED_TS)
        finally:
            conn.rollback(); conn.close()
        self.assertEqual(self._materiality_count(), 0)
        self.assertEqual(self._class_of(48), db.SYNTHETIC_SEED_OVERRIDE)

    def test_reapplies_same_materiality_class_idempotently(self):
        conn = sqlite3.connect(str(self.tmp))
        ma.apply_annotations(conn, created_at=_FIXED_TS)
        ma.apply_annotations(conn, created_at="2026-07-05T00:00:00+00:00")
        conn.commit(); conn.close()
        self.assertEqual(self._materiality_count(), 8)
        self.assertEqual(self._class_of(44), ma.TIER_FIRM)

    def test_conflict_error_names_event_and_offending_class(self):
        self._preset(50, db.SYNTHETIC_SEED_OVERRIDE)
        conn = sqlite3.connect(str(self.tmp))
        try:
            with self.assertRaises(ma.HygieneAnnotationConflict) as ctx:
                ma.apply_annotations(conn, created_at=_FIXED_TS)
            msg = str(ctx.exception)
            self.assertIn("50", msg)
            self.assertIn(db.SYNTHETIC_SEED_OVERRIDE, msg)
        finally:
            conn.rollback(); conn.close()


if __name__ == "__main__":
    unittest.main()
