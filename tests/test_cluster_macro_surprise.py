"""Focused tests for the per-cluster macro_surprise block.

Covers the additive contract described in the task:

  * stored release fact is shown on the cluster
  * no-data fallback — no block attached, cluster shape unchanged
  * revised_prior surfaces on the cluster block when present
  * stored facts override the headline guess (block always reflects
    the official label, never a keyword interpretation)
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import macro_release_facts as _facts
from macro_calendar import get_macro_releases
from macro_surprise import (
    attach_cluster_macro_blocks,
    classify_macro_surprise,
)


class _TempDBMixin:
    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="cluster_macro_test_")
        os.close(fd)
        os.unlink(path)
        self._tmp_path = path
        self._patchers = [
            mock.patch.object(_db, "DB_FILE", path),
            mock.patch.object(_facts, "DB_FILE", path),
        ]
        for p in self._patchers:
            p.start()
        _db.init_db()

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        try:
            os.unlink(self._tmp_path)
        except OSError:
            pass

    def _classify(self, *, today: date, clusters: list[dict]) -> tuple[list[dict], list[dict]]:
        rows = get_macro_releases(today=today, days_before=0, days_after=0)
        enriched = classify_macro_surprise(rows, clusters)
        attached = attach_cluster_macro_blocks(enriched, clusters)
        return enriched, attached


# ---------------------------------------------------------------------------
# Stored release fact shown
# ---------------------------------------------------------------------------

class TestStoredFactShown(_TempDBMixin, unittest.TestCase):
    def test_block_present_with_official_label_and_source(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, prior=3.0, consensus=3.0,
            source="BLS",
        )
        clusters = [
            {"headline": "US CPI rose 3.5% in March, hottest in months",
             "source_count": 4},
        ]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        self.assertEqual(len(attached), 1)
        block = attached[0]["macro_surprise"]
        self.assertEqual(block["release_key"], "CPI:2026-04-10")
        self.assertEqual(block["release_time"], "2026-04-10T12:30:00Z")
        self.assertEqual(block["actual"], 3.5)
        self.assertEqual(block["prior"], 3.0)
        self.assertEqual(block["consensus"], 3.0)
        self.assertEqual(block["surprise_label"], "beat")
        self.assertEqual(block["source"], "BLS")

    def test_only_matching_cluster_gets_block(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, consensus=3.0, source="BLS",
        )
        clusters = [
            {"headline": "US CPI rose 3.5% in March", "source_count": 4},
            {"headline": "Tech stocks rally as bond yields slip",
             "source_count": 2},
        ]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        self.assertIn("macro_surprise", attached[0])
        self.assertNotIn("macro_surprise", attached[1])


# ---------------------------------------------------------------------------
# No-data fallback — cluster shape unchanged
# ---------------------------------------------------------------------------

class TestNoDataFallback(_TempDBMixin, unittest.TestCase):
    def test_no_facts_means_no_block_attached(self) -> None:
        clusters = [
            {"headline": "US CPI rose 3.5%, above the 3.0% consensus",
             "source_count": 4},
            {"headline": "Tech earnings beat expectations",
             "source_count": 3},
        ]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        for cluster in attached:
            self.assertNotIn("macro_surprise", cluster)

    def test_cluster_dicts_are_not_mutated_in_place(self) -> None:
        clusters = [
            {"headline": "US CPI rose 3.5% in March", "source_count": 4},
        ]
        original = clusters[0]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        # Even though no block was attached (no facts), the helper
        # should still return shallow copies — not mutate the inputs.
        self.assertIsNot(attached[0], original)
        self.assertNotIn("macro_surprise", original)

    def test_attach_is_noop_when_no_official_signals(self) -> None:
        # Releases enriched purely by the headline heuristic
        # (signal_source="headline") must NOT produce a cluster block.
        clusters = [
            {"headline": "US CPI rose 3.5%, above the 3.0% consensus",
             "source_count": 4},
        ]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        for cluster in attached:
            self.assertNotIn("macro_surprise", cluster)


# ---------------------------------------------------------------------------
# Revision present
# ---------------------------------------------------------------------------

class TestRevisionDisplayed(_TempDBMixin, unittest.TestCase):
    def test_revised_prior_surfaces_on_cluster_block(self) -> None:
        _facts.upsert_release_facts(
            release_key="NFP:2026-04-03",
            release_time="2026-04-03T12:30:00Z",
            actual=180_000, prior=200_000, revised_prior=185_000,
            consensus=190_000, source="BLS",
        )
        clusters = [
            {"headline": "Nonfarm payrolls miss estimates as job growth slows",
             "source_count": 5},
        ]
        _, attached = self._classify(today=date(2026, 4, 3), clusters=clusters)
        block = attached[0]["macro_surprise"]
        self.assertEqual(block["prior"], 200_000)
        self.assertEqual(block["revised_prior"], 185_000)
        self.assertNotEqual(block["prior"], block["revised_prior"])
        self.assertEqual(block["surprise_label"], "miss")


# ---------------------------------------------------------------------------
# Stored facts override the headline guess (label is the official one)
# ---------------------------------------------------------------------------

class TestOfficialLabelWinsOnCluster(_TempDBMixin, unittest.TestCase):
    def test_block_label_follows_facts_not_headline(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=2.5, prior=3.0, consensus=3.0,
            source="BLS",
        )
        clusters = [
            {"headline": "CPI tops forecasts", "source_count": 4},
        ]
        _, attached = self._classify(today=date(2026, 4, 10), clusters=clusters)
        block = attached[0]["macro_surprise"]
        self.assertEqual(block["surprise_label"], "miss")


if __name__ == "__main__":
    unittest.main()
