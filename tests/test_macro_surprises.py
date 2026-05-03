"""
tests/test_macro_surprises.py

Contract tests for the macro-surprises storage layer.

Covers:
  * Pure classifier — direction convention per category, raw inline
    band, z-score computation, thin-history None floor, all-identical-
    priors edge case.
  * Schema + natural key — UNIQUE(series, release_time) enforced, event
    FK column migrates in cleanly.
  * Upsert CRUD — insert / update round-trips, unknown series rejected,
    ill-formed release_time rejected.
  * Frozen magnitude — inserting a later outlier does NOT rewrite the
    direction/magnitude that was frozen on an earlier row.
  * Listing filters — series / category / country / time window all
    compose, ordering is newest-first.
  * Event linkage — link / unlink / list_events_for_release work;
    delete_release nulls dangling FKs.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import macro_surprises as _ms


class _TempDBMixin:
    """Route every SQLite read/write to a throwaway file per test."""

    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="macro_surprises_test_")
        os.close(fd)
        os.unlink(path)
        self._tmp_path = path
        self._patchers = [
            mock.patch.object(_db, "DB_FILE", path),
            mock.patch.object(_ms, "DB_FILE", path),
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
# Pure classifier — no DB.
# ---------------------------------------------------------------------------


class TestComputeSurpriseDirection(unittest.TestCase):
    def test_hawkish_on_high_inflation(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=3.4, category="inflation",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "hawkish")
        self.assertAlmostEqual(out["surprise"], 0.4, places=5)

    def test_dovish_on_low_inflation(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=2.5, category="inflation",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "dovish")

    def test_up_on_strong_sentiment(self) -> None:
        out = _ms.compute_surprise(
            expected=100.0, realized=112.0, category="sentiment",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "up")

    def test_down_on_weak_housing(self) -> None:
        out = _ms.compute_surprise(
            expected=1_400.0, realized=1_300.0, category="housing",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "down")

    def test_inline_when_surprise_is_zero(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=3.0, category="inflation",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "inline")

    def test_inline_within_relative_band(self) -> None:
        # 0.1 / 3.0 = 3.3% < 5% band → "inline"
        out = _ms.compute_surprise(
            expected=3.0, realized=3.1, category="inflation",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "inline")

    def test_direction_when_expected_is_zero(self) -> None:
        # Degenerate expected=0 — fall back to sign of surprise.
        out = _ms.compute_surprise(
            expected=0.0, realized=0.25, category="monetary_policy",
            prior_surprises=[],
        )
        self.assertEqual(out["surprise_direction"], "hawkish")

    def test_none_when_inputs_missing(self) -> None:
        out = _ms.compute_surprise(
            expected=None, realized=3.0, category="inflation",
            prior_surprises=[],
        )
        self.assertIsNone(out["surprise"])
        self.assertIsNone(out["surprise_direction"])
        self.assertIsNone(out["surprise_magnitude"])

    def test_unknown_category_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ms.compute_surprise(
                expected=1.0, realized=1.0, category="not_a_category",
                prior_surprises=[],
            )


class TestComputeSurpriseMagnitude(unittest.TestCase):
    def test_none_when_priors_are_thin(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=3.5, category="inflation",
            prior_surprises=[0.0, 0.1, 0.0],  # n=3, below floor of 5
        )
        self.assertIsNone(out["surprise_zscore"])
        self.assertIsNone(out["surprise_magnitude"])

    def test_magnitude_large_on_tail_zscore(self) -> None:
        priors = [0.0, 0.0, 0.1, -0.1, 0.0]  # std ~ 0.063
        out = _ms.compute_surprise(
            expected=3.0, realized=3.5, category="inflation",
            prior_surprises=priors,
        )
        # Surprise = 0.5, mean ~ 0, std ~ 0.063 → z ~ 7.9 → large
        self.assertEqual(out["surprise_magnitude"], "large")
        self.assertIsNotNone(out["surprise_zscore"])
        self.assertGreater(abs(out["surprise_zscore"]), 2.0)

    def test_magnitude_inline_on_small_zscore(self) -> None:
        priors = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5, 0.5, -0.5]  # std ~ 0.5
        out = _ms.compute_surprise(
            expected=3.0, realized=3.1, category="inflation",
            prior_surprises=priors,
        )
        # Surprise = 0.1; but inline band triggers first (0.1 / 3.0 ≈ 3.3 %).
        self.assertEqual(out["surprise_direction"], "inline")
        self.assertEqual(out["surprise_magnitude"], "inline")

    def test_magnitude_moderate_zone(self) -> None:
        # Surprise 0.8, priors stdev ≈ 0.5 → z ≈ 1.6 → "moderate".
        priors = [0.5, -0.5, 0.5, -0.5, 0.5, -0.5]
        out = _ms.compute_surprise(
            expected=3.0, realized=3.8, category="inflation",
            prior_surprises=priors,
        )
        self.assertEqual(out["surprise_magnitude"], "moderate")

    def test_all_identical_priors_nonzero_surprise(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=3.5, category="inflation",
            prior_surprises=[0.0] * 6,
        )
        self.assertEqual(out["surprise_magnitude"], "large")
        self.assertEqual(out["surprise_zscore"], float("inf"))

    def test_all_identical_priors_zero_surprise(self) -> None:
        out = _ms.compute_surprise(
            expected=3.0, realized=3.0, category="inflation",
            prior_surprises=[0.0] * 6,
        )
        self.assertEqual(out["surprise_zscore"], 0.0)
        self.assertEqual(out["surprise_magnitude"], "inline")


# ---------------------------------------------------------------------------
# Schema + CRUD.
# ---------------------------------------------------------------------------


class TestSchemaMigration(_TempDBMixin, unittest.TestCase):
    def test_macro_releases_table_exists(self) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='macro_releases'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_events_has_macro_release_id_column(self) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            cols = [
                r[1] for r in conn.execute("PRAGMA table_info(events)")
            ]
        self.assertIn("macro_release_id", cols)

    def test_unique_series_release_time_enforced(self) -> None:
        _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1, country="US",
        )
        # Same natural key should update, not insert a second row.
        _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.2, country="US",
        )
        rows = _ms.list_releases(series="us_cpi_yoy")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["realized"], 3.2, places=6)


class TestUpsertRoundTrip(_TempDBMixin, unittest.TestCase):
    def test_insert_and_fetch(self) -> None:
        stored = _ms.upsert_release(
            series="us_nfp",
            release_time="2026-04-04T12:30:00+00:00",
            expected=170.0, realized=220.0,
            unit="K", country="US",
            release_id="us_nfp_2026-03",
            notes="March payrolls",
        )
        self.assertEqual(stored["series"], "us_nfp")
        self.assertEqual(stored["category"], "employment")
        self.assertEqual(stored["country"], "US")
        self.assertEqual(stored["unit"], "K")
        self.assertEqual(stored["release_id"], "us_nfp_2026-03")
        self.assertAlmostEqual(stored["surprise"], 50.0, places=5)
        self.assertEqual(stored["surprise_direction"], "hawkish")

        by_id = _ms.get_release(stored["id"])
        self.assertEqual(by_id, stored)

        by_key = _ms.get_release_by_key(
            "us_nfp", "2026-04-04T12:30:00+00:00",
        )
        self.assertEqual(by_key["id"], stored["id"])

    def test_missing_expected_or_realized_still_stores(self) -> None:
        stored = _ms.upsert_release(
            series="us_fomc_rate",
            release_time="2026-05-01T18:00:00+00:00",
            expected=5.25, realized=None,
        )
        self.assertIsNone(stored["surprise"])
        self.assertIsNone(stored["surprise_direction"])

    def test_update_on_duplicate_key(self) -> None:
        first = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=None,
        )
        second = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertIsNone(first["realized"])
        self.assertAlmostEqual(second["realized"], 3.1, places=6)
        self.assertIsNotNone(second["surprise"])

    def test_unknown_series_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ms.upsert_release(
                series="not_a_series",
                release_time="2026-01-01T00:00:00+00:00",
                expected=1.0, realized=1.0,
            )

    def test_bad_release_time_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ms.upsert_release(
                series="us_cpi_yoy",
                release_time="not-a-timestamp",
                expected=1.0, realized=1.0,
            )

    def test_nan_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ms.upsert_release(
                series="us_cpi_yoy",
                release_time="2026-01-01T00:00:00+00:00",
                expected=float("nan"), realized=1.0,
            )

    def test_bool_rejected_as_number(self) -> None:
        with self.assertRaises(ValueError):
            _ms.upsert_release(
                series="us_cpi_yoy",
                release_time="2026-01-01T00:00:00+00:00",
                expected=True, realized=1.0,
            )

    def test_trailing_z_accepted_as_iso(self) -> None:
        # "Z" suffix is common in wire protocols; upsert should tolerate.
        stored = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00Z",
            expected=2.9, realized=3.0,
        )
        self.assertEqual(stored["release_time"], "2026-03-12T12:30:00Z")


class TestFrozenMagnitude(_TempDBMixin, unittest.TestCase):
    def test_old_row_magnitude_not_rewritten_by_later_outlier(self) -> None:
        # Insert 6 early benign prints so the 7th has a history floor.
        for i in range(6):
            _ms.upsert_release(
                series="us_cpi_yoy",
                release_time=f"2026-01-{i + 1:02d}T12:30:00+00:00",
                expected=3.0, realized=3.0 + (i - 2.5) * 0.05,
            )
        benign = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-02-01T12:30:00+00:00",
            expected=3.0, realized=3.05,
        )
        # Now insert a huge outlier.
        _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-01T12:30:00+00:00",
            expected=3.0, realized=4.5,
        )
        # The benign row's magnitude is preserved — not rewritten against
        # the new, wider distribution.
        refetched = _ms.get_release(benign["id"])
        self.assertEqual(
            refetched["surprise_magnitude"], benign["surprise_magnitude"],
        )
        self.assertEqual(
            refetched["prior_sample_size"], benign["prior_sample_size"],
        )


class TestListingFilters(_TempDBMixin, unittest.TestCase):
    def _seed(self) -> None:
        _ms.upsert_release(
            series="us_cpi_yoy", country="US",
            release_time="2026-02-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        _ms.upsert_release(
            series="us_nfp", country="US",
            release_time="2026-03-07T12:30:00+00:00",
            expected=180.0, realized=210.0,
        )
        _ms.upsert_release(
            series="eu_cpi_yoy", country="EU",
            release_time="2026-03-20T10:00:00+00:00",
            expected=2.4, realized=2.2,
        )

    def test_newest_first_ordering(self) -> None:
        self._seed()
        rows = _ms.list_releases()
        self.assertEqual(
            [r["series"] for r in rows],
            ["eu_cpi_yoy", "us_nfp", "us_cpi_yoy"],
        )

    def test_filter_by_series(self) -> None:
        self._seed()
        rows = _ms.list_releases(series="us_nfp")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["series"], "us_nfp")

    def test_filter_by_category(self) -> None:
        self._seed()
        rows = _ms.list_releases(category="inflation")
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["category"] == "inflation" for r in rows))

    def test_filter_by_country(self) -> None:
        self._seed()
        rows = _ms.list_releases(country="EU")
        self.assertEqual(len(rows), 1)

    def test_time_window(self) -> None:
        self._seed()
        rows = _ms.list_releases(
            since="2026-03-01T00:00:00+00:00",
            until="2026-03-31T23:59:59+00:00",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            {r["series"] for r in rows}, {"us_nfp", "eu_cpi_yoy"},
        )

    def test_limit_rejected_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            _ms.list_releases(limit=0)
        with self.assertRaises(ValueError):
            _ms.list_releases(limit=10_000)

    def test_unknown_series_or_category_rejected(self) -> None:
        with self.assertRaises(ValueError):
            _ms.list_releases(series="nope")
        with self.assertRaises(ValueError):
            _ms.list_releases(category="nope")


class TestEventLinkage(_TempDBMixin, unittest.TestCase):
    def _insert_event(self) -> int:
        with sqlite3.connect(self._tmp_path) as conn:
            cur = conn.execute(
                "INSERT INTO events "
                "(timestamp, headline, stage, persistence) "
                "VALUES (?, ?, ?, ?)",
                ("2026-03-12T13:00:00+00:00", "CPI hot — 3.1 vs 2.9",
                 "realized", "medium"),
            )
            return cur.lastrowid

    def test_link_event_to_release_round_trip(self) -> None:
        release = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        event_id = self._insert_event()
        _ms.link_event_to_release(event_id, release["id"])
        events = _ms.list_events_for_release(release["id"])
        self.assertEqual(events, [event_id])

    def test_multiple_events_per_release(self) -> None:
        release = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        ids = [self._insert_event() for _ in range(3)]
        for eid in ids:
            _ms.link_event_to_release(eid, release["id"])
        self.assertEqual(
            sorted(_ms.list_events_for_release(release["id"])),
            sorted(ids),
        )

    def test_unlink_event(self) -> None:
        release = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        event_id = self._insert_event()
        _ms.link_event_to_release(event_id, release["id"])
        _ms.unlink_event(event_id)
        self.assertEqual(_ms.list_events_for_release(release["id"]), [])

    def test_link_unknown_release_raises(self) -> None:
        event_id = self._insert_event()
        with self.assertRaises(ValueError):
            _ms.link_event_to_release(event_id, 99999)

    def test_link_unknown_event_raises(self) -> None:
        release = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        with self.assertRaises(ValueError):
            _ms.link_event_to_release(99999, release["id"])

    def test_delete_release_nulls_dangling_fks(self) -> None:
        release = _ms.upsert_release(
            series="us_cpi_yoy",
            release_time="2026-03-12T12:30:00+00:00",
            expected=2.9, realized=3.1,
        )
        event_id = self._insert_event()
        _ms.link_event_to_release(event_id, release["id"])
        self.assertTrue(_ms.delete_release(release["id"]))
        with sqlite3.connect(self._tmp_path) as conn:
            row = conn.execute(
                "SELECT macro_release_id FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
        self.assertIsNone(row[0])

    def test_delete_missing_returns_false(self) -> None:
        self.assertFalse(_ms.delete_release(99999))


if __name__ == "__main__":
    unittest.main()
