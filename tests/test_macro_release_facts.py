"""Focused tests for the release-facts cache and its consumers.

Covers:
  * released value present  → calendar surfaces actual / prior / consensus
  * revision present        → revised_prior round-trips and is surfaced
  * no-data fallback        → calendar shape stable, surprise heuristic still wins
  * surprise label driven by stored facts overrides headline guess
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
from macro_surprise import classify_macro_surprise


class _TempDBMixin:
    """Route every SQLite read/write to a throwaway file per test."""

    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="release_facts_test_")
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


# ---------------------------------------------------------------------------
# Released value present — calendar surfaces it
# ---------------------------------------------------------------------------

class TestCalendarSurfacesStoredFacts(_TempDBMixin, unittest.TestCase):
    def test_actual_and_consensus_round_trip_to_calendar(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.2, prior=3.0, consensus=3.0,
            source="BLS",
        )
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        cpi = [r for r in rows if r["name"] == "CPI" and r["release_date"] == "2026-04-10"]
        self.assertEqual(len(cpi), 1)
        row = cpi[0]
        self.assertTrue(row["has_release_facts"])
        self.assertEqual(row["actual"], 3.2)
        self.assertEqual(row["prior"], 3.0)
        self.assertEqual(row["consensus"], 3.0)
        self.assertEqual(row["release_facts_source"], "BLS")


# ---------------------------------------------------------------------------
# Revision present — revised_prior surfaces alongside the original prior
# ---------------------------------------------------------------------------

class TestRevisionSurfaced(_TempDBMixin, unittest.TestCase):
    def test_revised_prior_surfaces_distinct_from_prior(self) -> None:
        _facts.upsert_release_facts(
            release_key="NFP:2026-04-03",
            release_time="2026-04-03T12:30:00Z",
            actual=180_000, prior=200_000, revised_prior=185_000,
            consensus=190_000, source="BLS",
        )
        rows = get_macro_releases(today=date(2026, 4, 3), days_before=0, days_after=0)
        nfp = next(
            r for r in rows
            if r["name"] == "NFP" and r["release_date"] == "2026-04-03"
        )
        self.assertEqual(nfp["prior"], 200_000)
        self.assertEqual(nfp["revised_prior"], 185_000)
        self.assertNotEqual(nfp["prior"], nfp["revised_prior"])


# ---------------------------------------------------------------------------
# No-data fallback — shape stays stable, surprise still heuristic-driven
# ---------------------------------------------------------------------------

class TestNoDataFallback(_TempDBMixin, unittest.TestCase):
    def test_calendar_shape_stable_with_empty_store(self) -> None:
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        self.assertTrue(rows)
        for row in rows:
            for key in ("name", "release_date", "period", "status", "days_until",
                        "release_key", "actual", "prior", "revised_prior",
                        "consensus", "release_facts_source", "has_release_facts"):
                self.assertIn(key, row, msg=key)
            self.assertIsNone(row["actual"])
            self.assertIsNone(row["prior"])
            self.assertIsNone(row["revised_prior"])
            self.assertIsNone(row["consensus"])
            self.assertEqual(row["release_facts_source"], "")
            self.assertFalse(row["has_release_facts"])

    def test_surprise_falls_back_to_headline_when_no_facts(self) -> None:
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        clusters = [{"headline": "US CPI rose 3.2%, above the 3.0% consensus"}]
        out = classify_macro_surprise(rows, clusters)
        cpi = next(
            r for r in out
            if r["name"] == "CPI" and r["release_date"] == "2026-04-10"
        )
        self.assertEqual(cpi["surprise_signal"], "beat")
        self.assertEqual(cpi["signal_source"], "headline")
        self.assertIsNotNone(cpi["headline_evidence"])

    def test_old_row_without_facts_keeps_signal_source_none_outside_window(self) -> None:
        # Far-future release: outside the [-3, 0] window — signal_source stays None
        # even with the new fields present.
        rows = get_macro_releases(today=date(2026, 4, 1), days_before=0, days_after=30)
        future = [r for r in rows if r["days_until"] > 0]
        self.assertTrue(future)
        out = classify_macro_surprise(future, [])
        for entry in out:
            self.assertIsNone(entry["surprise_signal"])
            self.assertIsNone(entry["signal_source"])


# ---------------------------------------------------------------------------
# Stored facts override the headline guess
# ---------------------------------------------------------------------------

class TestStoredFactsBeatHeadlineGuess(_TempDBMixin, unittest.TestCase):
    def test_official_beat_overrides_in_line_headline(self) -> None:
        # Headline says "in line" — without facts, that would win.
        # With facts (actual > consensus), the stored numeric verdict wins.
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.5, prior=3.0, consensus=3.0,
            source="BLS",
        )
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        clusters = [{"headline": "US CPI in line with expectations for March"}]
        out = classify_macro_surprise(rows, clusters)
        cpi = next(
            r for r in out
            if r["name"] == "CPI" and r["release_date"] == "2026-04-10"
        )
        self.assertEqual(cpi["surprise_signal"], "beat")
        self.assertEqual(cpi["signal_source"], "official")
        self.assertIsNone(cpi["headline_evidence"])

    def test_official_in_line_overrides_beat_headline(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.0, prior=2.9, consensus=3.0,
            source="BLS",
        )
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        clusters = [{"headline": "CPI beat expectations significantly"}]
        out = classify_macro_surprise(rows, clusters)
        cpi = next(
            r for r in out
            if r["name"] == "CPI" and r["release_date"] == "2026-04-10"
        )
        self.assertEqual(cpi["surprise_signal"], "in_line")
        self.assertEqual(cpi["signal_source"], "official")

    def test_official_miss_when_actual_below_consensus(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=2.5, prior=3.0, consensus=3.0,
            source="BLS",
        )
        rows = get_macro_releases(today=date(2026, 4, 10), days_before=0, days_after=0)
        clusters = [{"headline": "CPI tops forecasts"}]  # would be 'beat' under headline path
        out = classify_macro_surprise(rows, clusters)
        cpi = next(
            r for r in out
            if r["name"] == "CPI" and r["release_date"] == "2026-04-10"
        )
        self.assertEqual(cpi["surprise_signal"], "miss")
        self.assertEqual(cpi["signal_source"], "official")


# ---------------------------------------------------------------------------
# Cache CRUD direct contract
# ---------------------------------------------------------------------------

class TestFactsStoreCRUD(_TempDBMixin, unittest.TestCase):
    def test_upsert_round_trip(self) -> None:
        stored = _facts.upsert_release_facts(
            release_key="PCE:2026-04-30",
            release_time="2026-04-30T12:30:00Z",
            actual=2.6, prior=2.5, revised_prior=2.4,
            consensus=2.5, source="BEA",
        )
        loaded = _facts.get_release_facts("PCE:2026-04-30")
        self.assertEqual(loaded, stored)
        self.assertEqual(loaded["actual"], 2.6)
        self.assertEqual(loaded["revised_prior"], 2.4)
        self.assertEqual(loaded["source"], "BEA")

    def test_upsert_overwrites_in_place(self) -> None:
        first = _facts.upsert_release_facts(
            release_key="PPI:2026-04-09",
            release_time="2026-04-09T12:30:00Z",
            actual=1.0, prior=0.9, source="BLS",
        )
        updated = _facts.upsert_release_facts(
            release_key="PPI:2026-04-09",
            release_time="2026-04-09T12:30:00Z",
            actual=1.1, prior=0.9, revised_prior=1.0, source="BLS",
        )
        self.assertEqual(first["created_at"], updated["created_at"])
        self.assertEqual(updated["actual"], 1.1)
        self.assertEqual(updated["revised_prior"], 1.0)

    def test_get_missing_returns_none(self) -> None:
        self.assertIsNone(_facts.get_release_facts("NFP:1999-01-01"))

    def test_facts_map_skips_missing_keys(self) -> None:
        _facts.upsert_release_facts(
            release_key="CPI:2026-04-10",
            release_time="2026-04-10T12:30:00Z",
            actual=3.2, source="BLS",
        )
        out = _facts.get_release_facts_map([
            "CPI:2026-04-10", "PPI:1999-01-01",
        ])
        self.assertIn("CPI:2026-04-10", out)
        self.assertNotIn("PPI:1999-01-01", out)

    def test_rejects_non_finite_numeric(self) -> None:
        with self.assertRaises(ValueError):
            _facts.upsert_release_facts(
                release_key="CPI:2026-04-10",
                release_time="2026-04-10T12:30:00Z",
                actual=float("nan"),
            )


if __name__ == "__main__":
    unittest.main()
