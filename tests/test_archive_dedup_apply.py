"""Tests for ``scripts/archive_dedup_apply.py``.

Covers the guarded-write contract and the dedup plan semantics:

* dry-run (and ``confirm=False``) never mutate the DB;
* the exact-cluster collapse plan is deterministic and honours the
  readiness-aware tiebreak;
* near-duplicate / variant headlines are never merged;
* the writer refuses unless ``--write`` and ``--confirm`` are supplied
  together;
* the fresh-backup gate and the pre-delete reference scan both block a
  write, and the targeted reference scan does not false-positive on
  unrelated primary keys / version columns;
* tracked-evidence-style singleton rows are never planned for removal,
  and an inbound reference to a removed id refuses the write.

All writes are exercised against throwaway temp databases — never the
real ``events.db``.
"""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import archive_dedup_apply as dedup  # noqa: E402


def _tickers(*symbols: str) -> str:
    return json.dumps([{"symbol": s} for s in symbols])


def _make_events_db(
    path: str,
    rows: list[tuple],
    *,
    with_price_cache: bool = True,
) -> None:
    """Build a minimal events DB.  ``rows`` = (id, headline, event_date,
    market_tickers_json)."""
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT, "
            "event_date TEXT, market_tickers TEXT)"
        )
        conn.executemany(
            "INSERT INTO events (id, headline, event_date, market_tickers) "
            "VALUES (?,?,?,?)",
            rows,
        )
        if with_price_cache:
            conn.execute("CREATE TABLE price_cache (ticker TEXT, date TEXT)")
        conn.commit()
    finally:
        conn.close()


def _row_ids(path: str) -> list[int]:
    conn = sqlite3.connect(path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT id FROM events"))
    finally:
        conn.close()


# A small archive: one 3-row exact cluster + one singleton.
def _cluster_rows() -> list[tuple]:
    return [
        (10, "Turkey lira weakens", "2026-04-30", _tickers("XLE")),
        (11, "Turkey lira weakens", "2026-04-30", _tickers("XLE", "VLO")),
        (12, "Turkey lira weakens", "2026-04-30", _tickers("XLE", "VLO")),
        (20, "OPEC extends cuts",   "2026-04-30", _tickers("XLE")),  # singleton
    ]


class DryRunSafetyTest(unittest.TestCase):
    def test_dry_run_does_not_mutate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)

            out = io.StringIO()
            rc = dedup.main(["--dry-run", "--db-path", p, "--json"], out=out)

            self.assertEqual(rc, 0)
            self.assertEqual(_row_ids(p), before, "dry-run must not mutate")
            payload = json.loads(out.getvalue())
            self.assertEqual(payload["remove_count"], 2)

    def test_confirm_false_writes_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)
            env = dedup.apply_dedup(db_path=p, confirm=False)
            self.assertFalse(env["write_attempted"])
            self.assertEqual(env["applied_count"], 0)
            self.assertEqual(_row_ids(p), before)


class DeterministicPlanTest(unittest.TestCase):
    def test_plan_is_deterministic_and_tiebreaks_on_tickers(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            plan_a = dedup.plan_dedup(db_path=p)
            plan_b = dedup.plan_dedup(db_path=p)
            self.assertEqual(plan_a["keep_ids"], plan_b["keep_ids"])
            self.assertEqual(plan_a["remove_ids"], plan_b["remove_ids"])
            # No row is ready (no price_cache rows) -> tiebreak falls to
            # n_tickers desc, id asc: id 11 (2 tickers, smaller id) wins.
            self.assertEqual(plan_a["keep_ids"], [11])
            self.assertEqual(plan_a["remove_ids"], [10, 12])
            self.assertEqual(plan_a["cluster_count"], 1)

    def test_fully_ready_takes_precedence_in_tiebreak(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            # Mark id 10 (the single-ticker row) ready; it must be kept
            # despite having fewer tickers than 11/12.
            with mock.patch.object(
                dedup, "_load_readiness_map",
                return_value={10: True, 11: False, 12: False, 20: False},
            ):
                plan = dedup.plan_dedup(db_path=p)
            self.assertEqual(plan["keep_ids"], [10])
            self.assertEqual(plan["remove_ids"], [11, 12])
            # The kept row stays ready; removed rows were not ready.
            self.assertEqual(plan["readiness_projection"]["removed_ready"], 0)
            self.assertTrue(plan["clusters"][0]["keep_ready"])


class VariantNotMergedTest(unittest.TestCase):
    def test_distinct_variant_headlines_are_not_merged(self):
        import tempfile
        rows = [
            # Two paraphrase variants on the same date, each a singleton.
            (1, "Fed speakers rotate", "2026-04-30", None),
            (2, "Fed speakers rotate on inflation commentary", "2026-04-30", None),
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, rows)
            plan = dedup.plan_dedup(db_path=p)
            self.assertEqual(plan["cluster_count"], 0)
            self.assertEqual(plan["remove_ids"], [])

    def test_each_variant_dedups_independently(self):
        import tempfile
        rows = [
            (1, "Fed speakers rotate", "2026-04-30", None),
            (2, "Fed speakers rotate", "2026-04-30", None),
            (3, "Fed speakers rotate on inflation commentary", "2026-04-30", None),
            (4, "Fed speakers rotate on inflation commentary", "2026-04-30", None),
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, rows)
            plan = dedup.plan_dedup(db_path=p)
            # Two separate clusters; one survivor each, never cross-merged.
            self.assertEqual(plan["cluster_count"], 2)
            self.assertEqual(sorted(plan["keep_ids"]), [1, 3])
            self.assertEqual(sorted(plan["remove_ids"]), [2, 4])


class WriteGuardTest(unittest.TestCase):
    def test_write_alone_refuses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)
            rc = dedup.main(["--write", "--db-path", p], out=io.StringIO())
            self.assertEqual(rc, 2)
            self.assertEqual(_row_ids(p), before)

    def test_confirm_alone_refuses(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)
            rc = dedup.main(["--confirm", "--db-path", p], out=io.StringIO())
            self.assertEqual(rc, 2)
            self.assertEqual(_row_ids(p), before)

    def test_empty_plan_confirmed_write_is_clean_no_op_exit_zero(self):
        import tempfile
        # No duplicate clusters -> nothing to remove.  A confirmed write
        # must be a clean no-op (exit 0), distinct from a gate refusal,
        # and must not touch the real backups/ dir (gate is lazy).
        rows = [
            (1, "Solo headline A", "2026-04-30", None),
            (2, "Solo headline B", "2026-04-30", None),
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, rows)
            before = _row_ids(p)
            env = dedup.apply_dedup(db_path=p, confirm=True)
            self.assertFalse(env["write_attempted"])
            self.assertIsNone(env["refuse_reason"])
            rc = dedup.main(["--write", "--confirm", "--db-path", p], out=io.StringIO())
            self.assertEqual(rc, 0)
            self.assertEqual(_row_ids(p), before)

    def test_dry_run_wins_even_with_write_flags(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)
            rc = dedup.main(
                ["--dry-run", "--write", "--confirm", "--db-path", p],
                out=io.StringIO(),
            )
            self.assertEqual(rc, 0)
            self.assertEqual(_row_ids(p), before)


class FreshBackupGateTest(unittest.TestCase):
    def _backup(self, src: str, backup_dir: str, *, newer: bool) -> str:
        os.makedirs(backup_dir, exist_ok=True)
        dst = os.path.join(backup_dir, "events-20990101T000000.db")
        import shutil
        shutil.copy2(src, dst)
        db_mtime = os.stat(src).st_mtime
        os.utime(dst, (db_mtime + 50, db_mtime + 50) if newer
                 else (db_mtime - 50, db_mtime - 50))
        return dst

    def test_no_backup_dir_fails_gate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            res = dedup.check_fresh_backup(db_path=p, backup_dir=os.path.join(d, "nope"))
            self.assertFalse(res["ok"])

    def test_stale_backup_fails_gate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            bdir = os.path.join(d, "backups")
            self._backup(p, bdir, newer=False)
            res = dedup.check_fresh_backup(db_path=p, backup_dir=bdir)
            self.assertFalse(res["ok"])

    def test_fresh_valid_backup_passes_gate(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())  # has price_cache -> restore-valid
            bdir = os.path.join(d, "backups")
            self._backup(p, bdir, newer=True)
            res = dedup.check_fresh_backup(db_path=p, backup_dir=bdir)
            self.assertTrue(res["ok"], res.get("reason"))

    def test_confirmed_write_refuses_without_fresh_backup(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            before = _row_ids(p)
            env = dedup.apply_dedup(
                db_path=p, confirm=True, backup_dir=os.path.join(d, "nope"),
            )
            self.assertFalse(env["write_attempted"])
            self.assertIn("fresh-backup gate failed", env["refuse_reason"])
            self.assertEqual(_row_ids(p), before)


class ReferenceScanTest(unittest.TestCase):
    def test_no_false_positive_on_unrelated_pk_and_version_columns(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            conn = sqlite3.connect(p)
            try:
                # news_clusters.id PK overlapping a remove-id (12), and a
                # cluster_id FK to the news layer, and a version integer.
                conn.execute("CREATE TABLE news_clusters (id INTEGER PRIMARY KEY, headline TEXT)")
                conn.execute("INSERT INTO news_clusters (id, headline) VALUES (12, 'x')")
                conn.execute("CREATE TABLE news_headline_assignments (cluster_id INTEGER)")
                conn.execute("INSERT INTO news_headline_assignments (cluster_id) VALUES (12)")
                conn.execute("CREATE TABLE movers_cache (compute_version INTEGER)")
                conn.execute("INSERT INTO movers_cache (compute_version) VALUES (12)")
                conn.commit()
            finally:
                conn.close()
            conflicts = dedup.find_reference_conflicts(db_path=p, remove_ids=[10, 12])
            self.assertEqual(conflicts, [], "must not flag unrelated PK/FK/version cols")

    def test_typed_event_id_fk_is_flagged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            conn = sqlite3.connect(p)
            try:
                conn.execute("CREATE TABLE some_ref (event_id INTEGER)")
                conn.execute("INSERT INTO some_ref (event_id) VALUES (12)")
                conn.commit()
            finally:
                conn.close()
            conflicts = dedup.find_reference_conflicts(db_path=p, remove_ids=[10, 12])
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0]["table"], "some_ref")
            self.assertEqual(conflicts[0]["referenced_remove_ids"], [12])


class TrackedEvidenceTest(unittest.TestCase):
    def test_singleton_tracked_row_never_planned_for_removal(self):
        import tempfile
        # A tracked-cohort-style row that appears once is a singleton and
        # must never be in keep/remove sets.
        rows = _cluster_rows() + [
            (99, "WHR freeze-candidate canonical event", "2026-03-01", _tickers("WHR")),
        ]
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, rows)
            plan = dedup.plan_dedup(db_path=p)
            self.assertNotIn(99, plan["remove_ids"])
            self.assertNotIn(99, plan["keep_ids"])

    def test_embedded_reference_in_saved_studies_refuses_write(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            conn = sqlite3.connect(p)
            try:
                conn.execute(
                    "CREATE TABLE saved_studies (id INTEGER, config_json TEXT, description TEXT)"
                )
                conn.execute(
                    "INSERT INTO saved_studies (id, config_json, description) VALUES (1, ?, ?)",
                    (json.dumps({"event_ids": [12]}), "study referencing id 12"),
                )
                conn.commit()
            finally:
                conn.close()
            # Isolate the reference gate from the backup gate.
            env = dedup.apply_dedup(
                db_path=p, confirm=True, require_fresh_backup=False,
            )
            self.assertFalse(env["write_attempted"])
            self.assertTrue(env["reference_conflicts"])
            self.assertIn("reference scan", env["refuse_reason"])
            self.assertEqual(_row_ids(p), sorted([10, 11, 12, 20]))


class WriterCorrectnessTest(unittest.TestCase):
    """Engineering floor: prove the delete works on a throwaway temp DB."""

    def test_apply_deletes_remove_ids_and_is_idempotent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "events.db")
            _make_events_db(p, _cluster_rows())
            env = dedup.apply_dedup(
                db_path=p, confirm=True, require_fresh_backup=False,
            )
            self.assertTrue(env["write_attempted"])
            self.assertEqual(env["deleted_ids"], [10, 12])
            self.assertEqual(_row_ids(p), [11, 20])
            # Second run: no clusters remain -> no-op.
            env2 = dedup.apply_dedup(
                db_path=p, confirm=True, require_fresh_backup=False,
            )
            self.assertEqual(env2["applied_count"], 0)
            self.assertEqual(_row_ids(p), [11, 20])


if __name__ == "__main__":
    unittest.main()
