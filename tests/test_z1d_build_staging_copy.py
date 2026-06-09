"""AD1 — copy-build-then-swap rehearsal for Z1D live staging (safety tests).

Pins the gated contract for ``scripts/z1d_build_staging_copy.py``.  The script
implements steps 2-4 of the future live process (backup -> build working copy ->
verify) and produces a swap-ready verdict; it NEVER performs step 5 (replacing
live ``events.db``).  Every test runs on a temp source DB; the live archive is
never read for mutation and never replaced.

Contract:

* DRY RUN opens the source ``mode=ro``, derives/echoes the backup and
  working-copy paths, reuses the AC1 plan, reports required exclusions and
  collisions, and writes nothing.
* BUILD-COPY requires the full gate set (``--ack-live-staging``, an explicit
  backup path, an explicit working-copy path, and the required exclusions) and
  refuses otherwise.  It additionally HARD-REFUSES (raises) when a backup or
  working-copy path is the live archive, or when source / backup / working are
  not three distinct paths (so AC1 apply can never mutate the rollback backup).
* BUILD-COPY copies source -> backup (verifying the backup hash equals the
  source hash), copies backup -> working copy, and runs the AC1 apply on the
  WORKING COPY ONLY.  The source DB stays byte-identical.
* The working copy is swap-ready only when the source is unchanged, the backup
  matches the source, the working copy passes an integrity check, the staged
  rows are present (only in the working copy), the required exclusions were
  applied, there are no unexcluded collisions, the analysis denominators exclude
  the staged rows, the default ``/events`` listing hides them (explicit stage
  surfaces them), there are no duplicate candidate source_urls, and the
  delisted X ticker did not fail the build.
* The script labels the final live swap as NOT executed and prints an operator
  checklist only.  ``db.DB_FILE`` is restored after every call.  No paid /
  confirm path; no claim-upgrade language.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
_TESTS = os.path.dirname(os.path.abspath(__file__))
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import db  # noqa: E402
from scripts import z1d_build_staging_copy as BUILD  # noqa: E402
from test_z1d_live_staging_promotion import (  # noqa: E402
    _FakeProvider, _seed_collision_db, _PACK, _STEEL_ID, _SECTION301_ID,
)


def _tmp_name(tag: str) -> str:
    """A path in the temp dir that does NOT yet exist (build creates it)."""
    return os.path.join(tempfile.gettempdir(), f"z1d_{tag}_{uuid.uuid4().hex}.db")


def _staged_count(path: str) -> int:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return con.execute(
            "SELECT COUNT(*) FROM events WHERE stage='z1a_candidate_pack'").fetchone()[0]
    finally:
        con.close()


class _SourceBase(unittest.TestCase):
    """Each test gets a fresh temp source DB seeded with the two live duplicates."""

    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._src = _tmp_name("src")
        db.DB_FILE = self._src
        db.init_db()
        db.DB_FILE = self._orig_db
        _seed_collision_db(self._src)
        self._paths = [self._src]

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _track(self, *paths) -> None:
        self._paths.extend(paths)

    def _full(self, **over):
        bak = _tmp_name("bak")
        work = _tmp_name("work")
        self._track(bak, work)
        kw = dict(
            source_db=self._src, candidates_path=_PACK,
            backup_path=bak, working_copy_path=work,
            exclude=(_STEEL_ID, _SECTION301_ID), ack_live_staging=True,
            provider=_FakeProvider(), confirm=True,
        )
        kw.update(over)
        return kw


# ---------------------------------------------------------------------------
# Dry run — read-only
# ---------------------------------------------------------------------------

class TestDryRun(_SourceBase):
    def test_dry_run_writes_nothing(self):
        bak, work = _tmp_name("bak"), _tmp_name("work")
        from scripts.z1d_live_staging_promotion import sha256_file
        before = sha256_file(self._src)
        BUILD.plan_build(source_db=self._src, candidates_path=_PACK,
                         backup_path=bak, working_copy_path=work)
        self.assertEqual(sha256_file(self._src), before)
        self.assertFalse(os.path.exists(bak))
        self.assertFalse(os.path.exists(work))

    def test_dry_run_reports_required_exclusions_and_collisions(self):
        plan = BUILD.plan_build(source_db=self._src, candidates_path=_PACK)
        self.assertEqual(set(plan["missing_required_exclusions"]),
                         {_STEEL_ID, _SECTION301_ID})
        self.assertTrue(plan["has_unexcluded_collisions"])

    def test_dry_run_plan_has_backup_and_working_paths(self):
        plan = BUILD.plan_build(source_db=self._src, candidates_path=_PACK)
        self.assertTrue(plan["backup_path"])
        self.assertTrue(plan["working_copy_path"])
        self.assertNotEqual(plan["backup_path"], plan["working_copy_path"])

    def test_dry_run_restores_db_file(self):
        BUILD.plan_build(source_db=self._src, candidates_path=_PACK)
        self.assertEqual(db.DB_FILE, self._orig_db)


# ---------------------------------------------------------------------------
# Build gates — refuse / raise, never mutate
# ---------------------------------------------------------------------------

class TestBuildGates(_SourceBase):
    def _assert_clean_refuse(self, res, working_path):
        self.assertIsNotNone(res["refuse_reason"])
        self.assertFalse(res["swap_ready"])
        self.assertFalse(os.path.exists(working_path))
        self.assertEqual(db.DB_FILE, self._orig_db)

    def test_refuses_without_ack(self):
        kw = self._full(ack_live_staging=False)
        res = BUILD.build_staging_copy(**kw)
        self._assert_clean_refuse(res, kw["working_copy_path"])

    def test_refuses_missing_backup_path(self):
        kw = self._full(backup_path=None)
        res = BUILD.build_staging_copy(**kw)
        self.assertIsNotNone(res["refuse_reason"])
        self.assertEqual(db.DB_FILE, self._orig_db)

    def test_refuses_missing_working_copy_path(self):
        kw = self._full(working_copy_path=None)
        res = BUILD.build_staging_copy(**kw)
        self.assertIsNotNone(res["refuse_reason"])
        self.assertEqual(db.DB_FILE, self._orig_db)

    def test_raises_on_live_backup_path(self):
        kw = self._full(backup_path=db.LIVE_DB_FILE)
        with self.assertRaises(ValueError):
            BUILD.build_staging_copy(**kw)

    def test_raises_on_live_working_copy_path(self):
        kw = self._full(working_copy_path=db.LIVE_DB_FILE)
        with self.assertRaises(ValueError):
            BUILD.build_staging_copy(**kw)

    def test_raises_when_backup_equals_source(self):
        kw = self._full(backup_path=self._src)
        with self.assertRaises(ValueError):
            BUILD.build_staging_copy(**kw)

    def test_raises_when_working_equals_backup(self):
        bak = _tmp_name("shared")
        self._track(bak)
        kw = self._full(backup_path=bak, working_copy_path=bak)
        with self.assertRaises(ValueError):
            BUILD.build_staging_copy(**kw)

    def test_refuses_backup_exists_and_differs_from_source(self):
        bak = _tmp_name("bak")
        with open(bak, "wb") as fh:
            fh.write(b"a different backup file, not the source db")
        self._track(bak)
        kw = self._full(backup_path=bak)
        res = BUILD.build_staging_copy(**kw)
        self.assertIsNotNone(res["refuse_reason"])
        self.assertFalse(os.path.exists(kw["working_copy_path"]))
        self.assertEqual(db.DB_FILE, self._orig_db)

    def test_refuses_missing_required_exclusions(self):
        kw = self._full(exclude=(_STEEL_ID,))
        res = BUILD.build_staging_copy(**kw)
        self._assert_clean_refuse(res, kw["working_copy_path"])

    def test_refuses_unexcluded_collision(self):
        kw = self._full(exclude=())
        res = BUILD.build_staging_copy(**kw)
        self._assert_clean_refuse(res, kw["working_copy_path"])


# ---------------------------------------------------------------------------
# Build success — one expensive build shared across read-only assertions
# ---------------------------------------------------------------------------

class TestBuildSuccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._orig_db = db.DB_FILE
        cls.src = _tmp_name("src")
        db.DB_FILE = cls.src
        db.init_db()
        db.DB_FILE = cls._orig_db
        _seed_collision_db(cls.src)
        cls.backup = _tmp_name("bak")
        cls.working = _tmp_name("work")
        cls.res = BUILD.build_staging_copy(
            source_db=cls.src, candidates_path=_PACK,
            backup_path=cls.backup, working_copy_path=cls.working,
            exclude=(_STEEL_ID, _SECTION301_ID), ack_live_staging=True,
            provider=_FakeProvider(), confirm=True,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        db.DB_FILE = cls._orig_db
        for p in (cls.src, cls.backup, cls.working):
            try:
                os.remove(p)
            except OSError:
                pass

    def test_creates_backup_and_working_copy(self):
        self.assertTrue(os.path.exists(self.backup))
        self.assertTrue(os.path.exists(self.working))

    def test_backup_hash_equals_source_hash(self):
        self.assertTrue(self.res["backup_matches_source"])

    def test_working_copy_has_thirteen_staged_rows(self):
        self.assertEqual(_staged_count(self.working), 13)
        self.assertEqual(self.res["verify"]["staged_in_working"], 13)

    def test_source_db_unchanged_after_build(self):
        self.assertTrue(self.res["source_unchanged"])
        self.assertEqual(self.res["source_hash_after"], self.res["source_hash_before"])
        self.assertEqual(_staged_count(self.src), 0)

    def test_apply_ran_only_on_working_copy(self):
        self.assertTrue(self.res["apply"]["write_attempted"])
        self.assertEqual(self.res["apply"]["inserted_count"], 13)
        self.assertEqual(_staged_count(self.src), 0)

    def test_swap_ready_verdict_true(self):
        self.assertTrue(self.res["swap_ready"])

    def test_swap_is_not_executed(self):
        self.assertFalse(self.res["swap_executed"])
        self.assertTrue(self.res["swap_checklist"])
        text = BUILD.summarize_build(self.res).lower()
        self.assertIn("not executed", text)

    def test_db_file_restored_after_success(self):
        self.assertEqual(db.DB_FILE, self._orig_db)

    def test_x_unavailable_surfaced_without_failing_build(self):
        self.assertIn("X", self.res["apply"]["unavailable_tickers"])
        self.assertTrue(self.res["swap_ready"])

    def test_no_duplicate_candidate_source_url_in_working_copy(self):
        self.assertTrue(self.res["verify"]["no_duplicate_source_url"])
        con = sqlite3.connect(f"file:{self.working}?mode=ro", uri=True)
        try:
            dupes = con.execute(
                "SELECT source_url, COUNT(*) c FROM event_provenance "
                "WHERE intake_path='z1a_candidate_pack' GROUP BY source_url HAVING c > 1"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(dupes, [])

    def test_before_after_measurement_present(self):
        m = self.res["apply"]["measurements"]
        self.assertEqual(m["events_before"], 2)
        self.assertEqual(m["events_after"], 15)

    # ---- defense-in-depth: independently re-prove suppression on the built copy
    def test_default_events_hides_staged_explicit_surfaces(self):
        self.assertTrue(self.res["verify"]["events_default_hides_staged"])
        self.assertTrue(self.res["verify"]["events_explicit_surfaces_staged"])

        import api
        import movers_cache
        from fastapi.testclient import TestClient

        orig = db.DB_FILE
        try:
            db.DB_FILE = self.working
            movers_cache.invalidate()
            client = TestClient(api.app)
            default_ids = {e["id"] for e in client.get("/events").json()["items"]}
            staged_ids = {e["id"] for e in
                          client.get("/events?stage=z1a_candidate_pack").json()["items"]}
            movers_cache.invalidate()
        finally:
            db.DB_FILE = orig
        self.assertTrue(staged_ids)
        self.assertEqual(default_ids & staged_ids, set())

    def test_denominators_exclude_staged_rows(self):
        self.assertTrue(self.res["verify"]["denominators_exclude_staged"])

        from scripts import event_study_coverage_report as cov
        events, excluded = cov._load_events(self.working)
        staged = {r["id"] for r in events if r.get("stage") == "z1a_candidate_pack"}
        self.assertEqual(staged, set())
        self.assertGreaterEqual(excluded, 13)


# ---------------------------------------------------------------------------
# Static safety
# ---------------------------------------------------------------------------

class TestStaticSafety(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO, "scripts", "z1d_build_staging_copy.py"),
                  encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_paid_provider_or_confirm_paid_path(self):
        for forbidden in ("confirm_paid", "PolygonProvider", "Polygon", "polygon"):
            self.assertNotIn(forbidden, self.src,
                             f"build script must not reference {forbidden!r}")

    def test_no_significance_or_claim_language(self):
        low = self.src.lower()
        for banned in ("significant", "edge", "signal", "forecast", "alpha",
                       "outperform", "proves", "buy ", "sell "):
            self.assertNotIn(banned, low, f"script must not use {banned!r}")


if __name__ == "__main__":
    unittest.main()
