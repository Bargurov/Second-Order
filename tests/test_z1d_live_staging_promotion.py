"""AC1 / Z1D-Prep — gated candidate-staging promotion script (safety tests).

Pins the gated contract for ``scripts/z1d_live_staging_promotion.py``.  The
script turns the manual Z1D sequence (backup -> collision check -> staged
candidate insertion -> free backfill -> SPY densify -> before/after report) into
a safe, operator-approved workflow.  Every test runs on a temp / copy DB only;
the live archive is never mutated.

Gated contract:

* DRY RUN is the default and is strictly read-only: it validates the pack, runs
  the collision report, prints planned exclusions / inserts / expected staged
  count, and refuses to mutate.  A dry run may read the live archive ``mode=ro``.
* APPLY requires the FULL gate set and refuses otherwise: ``--apply``,
  ``--ack-live-staging``, a FRESH ``--backup-path`` (sha256 must match the target
  DB before any write), and explicit exclusions that MUST include the two known
  duplicates (steel proclamation 9705 -> live event 296, section 301 -> live
  event 297).  It also refuses if the collision report finds any *unexcluded*
  collision, or if the pack fails the reused Z1A validators.
* APPLY additionally refuses the live archive outright (``_assert_copy_target``
  backstop) — in-place live mutation is impossible in this committed script.
* Inserted rows stay at stage ``z1a_candidate_pack`` (a non-analysis,
  candidate-only stage), preserve provenance/source_url, are idempotent by
  source_url, and price_cache writes are additive only.
* X / United States Steel is labelled unavailable/delisted and is never treated
  as a required successful ticker.
* The module uses the FREE yfinance provider only — no ``confirm_paid``, no
  Polygon / paid path — and carries the null / non-claim discipline (no
  significance / edge / signal / forecast / alpha / outperform language).
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
import uuid

import pandas as pd
import yaml

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

import db  # noqa: E402
from scripts import z1d_live_staging_promotion as Z1D  # noqa: E402
from scripts.z1b_candidate_pack_copy_ingest import _load_candidates  # noqa: E402

_PACK = os.path.join(_REPO, "data", "candidates", "z1a_multi_regime_candidates.yaml")

_STEEL_ID = "section232-steel-proclamation-9705-2018-03-08"
_SECTION301_ID = "section301-china-tariff-increase-2024-05-14"
_STEEL_URL = (
    "https://www.federalregister.gov/documents/2018/03/15/"
    "2018-05478/adjusting-imports-of-steel-into-the-united-states"
)
_SECTION301_URL = (
    "https://bidenwhitehouse.archives.gov/briefing-room/statements-releases/"
    "2024/05/14/fact-sheet-president-biden-takes-action-to-protect-american-"
    "workers-and-businesses-from-chinas-unfair-trade-practices/"
)


class _FakeProvider:
    """In-process FREE provider stand-in (no network).  ``provider_name`` is
    ``yfinance`` so it passes the free-provider guard; closes dodge the
    price_cache suspect-fixture fingerprint."""
    provider_name = "yfinance"

    def __init__(self):
        self.calls = []

    def fetch_daily(self, ticker, *, period=None, start=None, end=None, auto_adjust=True):
        self.calls.append((ticker, start, end, auto_adjust))
        idx = pd.bdate_range(start=start, end=end)
        if len(idx) == 0:
            return None
        close = [100.0 + i * 0.37 for i in range(len(idx))]
        vol = [2_000_000.0] * len(idx)
        return pd.DataFrame({"Close": close, "Volume": vol}, index=idx)


def _seed_collision_db(path: str) -> None:
    """Seed the two live-duplicate events (steel->296, section301->297) so the
    collision report fires on exactly those two candidate ids by source_url."""
    with sqlite3.connect(path) as con:
        for headline, ed, url in (
            ("Section 232 25% steel tariff proclamation (live observation)", "2018-03-01", _STEEL_URL),
            ("Section 301 China tariff increases (live observation)", "2024-05-14", _SECTION301_URL),
        ):
            cur = con.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date) VALUES (?,?,?,?,?,?)",
                ("2018-01-01T00:00:00", headline, "curated_observation", "structural", "[]", ed),
            )
            eid = int(cur.lastrowid)
            con.execute(
                "INSERT INTO event_provenance (event_id, source_type, source_publisher, "
                "source_url, mechanism_label_provenance, intake_path, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (eid, "official", "primary", url, "curated", "test", "2018-01-01T00:00:00"),
            )
        con.commit()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._orig_db = db.DB_FILE
        self._tmp = os.path.join(tempfile.gettempdir(), f"z1d_target_{uuid.uuid4().hex}.db")
        db.DB_FILE = self._tmp
        db.init_db()
        db.DB_FILE = self._orig_db  # helpers take an explicit db_path, not db.DB_FILE
        _seed_collision_db(self._tmp)
        self._paths = [self._tmp]

    def tearDown(self) -> None:
        db.DB_FILE = self._orig_db
        for p in self._paths:
            try:
                os.remove(p)
            except OSError:
                pass

    def _fresh_backup(self) -> str:
        bak = os.path.join(tempfile.gettempdir(), f"z1d_backup_{uuid.uuid4().hex}.db")
        shutil.copy2(self._tmp, bak)
        self._paths.append(bak)
        return bak

    def _count(self, table: str, where: str = "") -> int:
        con = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table} {where}").fetchone()[0]
        finally:
            con.close()


# ---------------------------------------------------------------------------
# Required gate constants
# ---------------------------------------------------------------------------

class TestRequiredConstants(unittest.TestCase):
    def test_required_exclusions_cover_steel_and_section301(self):
        self.assertIn(_STEEL_ID, Z1D.REQUIRED_EXCLUSIONS)
        self.assertIn(_SECTION301_ID, Z1D.REQUIRED_EXCLUSIONS)

    def test_us_steel_x_is_an_unavailable_ticker(self):
        self.assertIn("X", Z1D.UNAVAILABLE_TICKERS)

    def test_staged_stage_is_candidate_pack_non_analysis(self):
        self.assertEqual(Z1D.STAGED_STAGE, "z1a_candidate_pack")
        self.assertIn(Z1D.STAGED_STAGE, db.NON_ANALYSIS_STAGES)


# ---------------------------------------------------------------------------
# Dry run — strictly read-only
# ---------------------------------------------------------------------------

class TestDryRunReadOnly(_Base):
    def test_dry_run_writes_nothing(self):
        before_events = self._count("events")
        before_prices = self._count("price_cache")
        before_mtime = os.path.getmtime(self._tmp)
        Z1D.plan_promotion(candidates_path=_PACK, db_path=self._tmp)
        self.assertEqual(self._count("events"), before_events)
        self.assertEqual(self._count("price_cache"), before_prices)
        self.assertEqual(os.path.getmtime(self._tmp), before_mtime)

    def test_plan_flags_unexcluded_collisions_without_exclusions(self):
        plan = Z1D.plan_promotion(candidates_path=_PACK, db_path=self._tmp)
        self.assertTrue(plan["has_unexcluded_collisions"])
        colliding = {c["id"] for c in plan["unexcluded_collisions"]}
        self.assertIn(_STEEL_ID, colliding)
        self.assertIn(_SECTION301_ID, colliding)
        self.assertEqual(set(plan["missing_required_exclusions"]),
                         {_STEEL_ID, _SECTION301_ID})

    def test_plan_with_required_exclusions_has_no_unexcluded_collisions(self):
        plan = Z1D.plan_promotion(
            candidates_path=_PACK, db_path=self._tmp,
            exclude=(_STEEL_ID, _SECTION301_ID))
        self.assertFalse(plan["has_unexcluded_collisions"])
        self.assertEqual(plan["missing_required_exclusions"], [])
        # 15 candidates - 2 excluded = 13 to stage; none already present by URL.
        self.assertEqual(plan["expected_staged_event_count"], 13)
        self.assertEqual(set(plan["excluded"]), {_STEEL_ID, _SECTION301_ID})

    def test_plan_surfaces_unavailable_x_ticker(self):
        plan = Z1D.plan_promotion(candidates_path=_PACK, db_path=self._tmp)
        self.assertIn("X", plan["unavailable_tickers"])

    def test_plan_validates_pack_ok(self):
        plan = Z1D.plan_promotion(candidates_path=_PACK, db_path=self._tmp)
        self.assertTrue(plan["ok"])
        self.assertEqual(plan["rejected"], [])


# ---------------------------------------------------------------------------
# Apply-mode gates — every refusal writes nothing
# ---------------------------------------------------------------------------

class TestApplyGates(_Base):
    def _full_kwargs(self, **over):
        kw = dict(
            candidates_path=_PACK, db_path=self._tmp,
            backup_path=self._fresh_backup(), ack_live_staging=True,
            exclude=(_STEEL_ID, _SECTION301_ID), provider=_FakeProvider(),
            confirm=True,
        )
        kw.update(over)
        return kw

    def _assert_no_writes(self, res):
        self.assertFalse(res["write_attempted"])
        self.assertEqual(self._count("events", "WHERE stage='z1a_candidate_pack'"), 0)

    def test_apply_refuses_live_target_outright(self):
        # Distinct hard backstop: the live archive is refused regardless of gates.
        with self.assertRaises(ValueError):
            Z1D.apply_promotion(
                candidates_path=_PACK, db_path=db.LIVE_DB_FILE,
                backup_path=self._fresh_backup(), ack_live_staging=True,
                exclude=(_STEEL_ID, _SECTION301_ID), provider=_FakeProvider(),
                confirm=True)

    def test_apply_refuses_without_ack(self):
        res = Z1D.apply_promotion(**self._full_kwargs(ack_live_staging=False))
        self.assertIsNotNone(res["refuse_reason"])
        self._assert_no_writes(res)

    def test_apply_refuses_missing_backup_path(self):
        res = Z1D.apply_promotion(**self._full_kwargs(backup_path=None))
        self.assertIsNotNone(res["refuse_reason"])
        self._assert_no_writes(res)

    def test_apply_refuses_stale_backup(self):
        bak = self._fresh_backup()
        # Mutate the target after the backup so the backup no longer matches.
        with sqlite3.connect(self._tmp) as con:
            con.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date) VALUES (?,?,?,?,?,?)",
                ("t", "drift", "realized", "structural", "[]", "2025-01-01"))
            con.commit()
        res = Z1D.apply_promotion(**self._full_kwargs(backup_path=bak))
        self.assertIsNotNone(res["refuse_reason"])
        self.assertFalse(res["write_attempted"])
        self.assertEqual(self._count("events", "WHERE stage='z1a_candidate_pack'"), 0)

    def test_apply_refuses_missing_required_exclusions(self):
        # Excluding only steel leaves section301 colliding -> refuse.
        res = Z1D.apply_promotion(**self._full_kwargs(exclude=(_STEEL_ID,)))
        self.assertIsNotNone(res["refuse_reason"])
        self._assert_no_writes(res)

    def test_apply_refuses_unexcluded_collisions(self):
        res = Z1D.apply_promotion(**self._full_kwargs(exclude=()))
        self.assertIsNotNone(res["refuse_reason"])
        self._assert_no_writes(res)

    def test_collisions_gate_fires_independently_of_required_exclusions(self):
        # Required exclusions ARE satisfied, but a DIFFERENT candidate
        # (ftc-v-amazon) collides with a freshly-seeded event by source_url.
        # The collisions gate must refuse on its own, distinct from the
        # missing-required-exclusions gate.
        amazon_url = (
            "https://www.ftc.gov/news-events/news/press-releases/2023/09/"
            "ftc-sues-amazon-illegally-maintaining-monopoly-power"
        )
        with sqlite3.connect(self._tmp) as con:
            cur = con.execute(
                "INSERT INTO events (timestamp, headline, stage, persistence, "
                "market_tickers, event_date) VALUES (?,?,?,?,?,?)",
                ("t", "FTC v Amazon (already archived)", "curated_observation",
                 "structural", "[]", "2023-09-26"))
            con.execute(
                "INSERT INTO event_provenance (event_id, source_type, source_url, "
                "mechanism_label_provenance, intake_path, created_at) VALUES (?,?,?,?,?,?)",
                (int(cur.lastrowid), "official", amazon_url, "curated", "test", "t"))
            con.commit()
        res = Z1D.apply_promotion(**self._full_kwargs(exclude=(_STEEL_ID, _SECTION301_ID)))
        self.assertIsNotNone(res["refuse_reason"])
        self.assertIn("collision", res["refuse_reason"].lower())
        self.assertEqual(res["missing_required_exclusions"], [])
        self._assert_no_writes(res)


# ---------------------------------------------------------------------------
# Apply success on a temp DB with all gates satisfied
# ---------------------------------------------------------------------------

class TestApplySuccess(_Base):
    def _apply_ok(self, **over):
        kw = dict(
            candidates_path=_PACK, db_path=self._tmp,
            backup_path=self._fresh_backup(), ack_live_staging=True,
            exclude=(_STEEL_ID, _SECTION301_ID), provider=_FakeProvider(),
            confirm=True,
        )
        kw.update(over)
        return Z1D.apply_promotion(**kw)

    def test_apply_succeeds_and_stages_thirteen(self):
        res = self._apply_ok()
        self.assertIsNone(res["refuse_reason"])
        self.assertTrue(res["write_attempted"])
        self.assertEqual(res["inserted_count"], 13)
        self.assertEqual(self._count("events", "WHERE stage='z1a_candidate_pack'"), 13)

    def test_inserted_rows_have_candidate_pack_stage(self):
        self._apply_ok()
        con = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            stages = {r[0] for r in con.execute(
                "SELECT DISTINCT stage FROM events WHERE persistence='unscored'")}
        finally:
            con.close()
        self.assertEqual(stages, {"z1a_candidate_pack"})

    def test_provenance_inserted_and_source_url_preserved(self):
        self._apply_ok()
        con = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            urls = {r[0] for r in con.execute(
                "SELECT source_url FROM event_provenance WHERE intake_path='z1a_candidate_pack'")}
        finally:
            con.close()
        self.assertEqual(len(urls), 13)
        # The excluded duplicates' URLs are NOT among the freshly staged rows.
        self.assertNotIn(_STEEL_URL, urls)
        self.assertNotIn(_SECTION301_URL, urls)

    def test_no_duplicate_source_url_rows(self):
        self._apply_ok()
        con = sqlite3.connect(f"file:{self._tmp}?mode=ro", uri=True)
        try:
            dupes = con.execute(
                "SELECT source_url, COUNT(*) c FROM event_provenance "
                "WHERE intake_path='z1a_candidate_pack' GROUP BY source_url HAVING c > 1"
            ).fetchall()
        finally:
            con.close()
        self.assertEqual(dupes, [])

    def test_price_cache_writes_are_additive_only(self):
        before = self._count("price_cache")
        res = self._apply_ok()
        after = self._count("price_cache")
        self.assertGreaterEqual(after, before)
        self.assertEqual(after - before, res["measurements"]["price_cache_delta"])

    def test_second_apply_refuses_via_collision_gate_and_writes_nothing(self):
        # Re-run semantics on an already-staged copy: the 13 staged rows now
        # carry their candidates' source_urls in event_provenance, so a second
        # apply sees 13 source_url_exact collisions and REFUSES via the collision
        # gate (the safer order — the collision check fires before the no-op
        # branch). Nothing is written; the staged count is unchanged. Recovery is
        # to discard the copy and restore from backup, not to "re-apply cleanly".
        self._apply_ok()
        res2 = self._apply_ok(backup_path=self._fresh_backup())
        self.assertEqual(res2["inserted_count"], 0)
        self.assertFalse(res2["write_attempted"])
        self.assertIsNotNone(res2["refuse_reason"])
        self.assertIn("collision", res2["refuse_reason"].lower())
        self.assertEqual(self._count("events", "WHERE stage='z1a_candidate_pack'"), 13)

    def test_unavailable_x_reported_without_failing_promotion(self):
        res = self._apply_ok()
        self.assertTrue(res["write_attempted"])
        self.assertIn("X", res["unavailable_tickers"])

    def test_candidate_readiness_present(self):
        res = self._apply_ok()
        self.assertTrue(res["measurements"]["candidate_readiness"])

    def test_measurements_report_before_after_counts(self):
        res = self._apply_ok()
        m = res["measurements"]
        self.assertEqual(m["events_before"], 2)        # the two seeded duplicates
        self.assertEqual(m["events_after"], 15)         # + 13 staged
        self.assertEqual(m["staged_after"], 13)


# ---------------------------------------------------------------------------
# Staged rows stay out of analysis denominators
# ---------------------------------------------------------------------------

class TestDenominatorExclusion(_Base):
    def test_staged_rows_excluded_from_coverage_and_track_record(self):
        Z1D.apply_promotion(
            candidates_path=_PACK, db_path=self._tmp,
            backup_path=self._fresh_backup(), ack_live_staging=True,
            exclude=(_STEEL_ID, _SECTION301_ID), provider=_FakeProvider(), confirm=True)

        from scripts import event_study_coverage_report as cov
        events, excluded = cov._load_events(self._tmp)
        staged_ids = {r["id"] for r in events if r.get("stage") == "z1a_candidate_pack"}
        self.assertEqual(staged_ids, set())
        self.assertGreaterEqual(excluded, 13)

        orig = db.DB_FILE
        try:
            db.DB_FILE = self._tmp
            tr = db.compute_track_record()
        finally:
            db.DB_FILE = orig
        # 13 unscored candidate stubs must not appear as unresolved theses.
        self.assertEqual(tr["unresolved"], 0)


# ---------------------------------------------------------------------------
# Default /events suppression
# ---------------------------------------------------------------------------

class TestEventsSuppression(_Base):
    def test_staged_rows_hidden_from_default_events_listing(self):
        Z1D.apply_promotion(
            candidates_path=_PACK, db_path=self._tmp,
            backup_path=self._fresh_backup(), ack_live_staging=True,
            exclude=(_STEEL_ID, _SECTION301_ID), provider=_FakeProvider(), confirm=True)

        import api
        import movers_cache
        from fastapi.testclient import TestClient

        orig = db.DB_FILE
        try:
            db.DB_FILE = self._tmp
            movers_cache.invalidate()
            client = TestClient(api.app)
            default_ids = {e["id"] for e in client.get("/events").json()["items"]}
            staged_ids = {e["id"] for e in
                          client.get("/events?stage=z1a_candidate_pack").json()["items"]}
            # Clear caches while still bound to the temp DB (which has the
            # movers_cache table) so we never touch the live archive on restore.
            movers_cache.invalidate()
        finally:
            db.DB_FILE = orig
        self.assertTrue(staged_ids)
        self.assertEqual(default_ids & staged_ids, set())


# ---------------------------------------------------------------------------
# Static safety: no paid path, no claim-upgrade language
# ---------------------------------------------------------------------------

class TestStaticSafety(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(_REPO, "scripts", "z1d_live_staging_promotion.py"),
                  encoding="utf-8") as fh:
            self.src = fh.read()

    def test_no_paid_provider_or_confirm_paid_path(self):
        for forbidden in ("confirm_paid", "PolygonProvider", "Polygon", "polygon"):
            self.assertNotIn(forbidden, self.src,
                             f"promotion script must not reference {forbidden!r}")

    def test_no_significance_or_claim_language(self):
        low = self.src.lower()
        for banned in ("significant", "edge", "signal", "forecast", "alpha",
                       "outperform", "proves", "buy ", "sell "):
            self.assertNotIn(banned, low, f"script must not use {banned!r}")


if __name__ == "__main__":
    unittest.main()
