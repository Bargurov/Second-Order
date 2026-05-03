"""
tests/test_saved_studies.py

Contract tests for the saved-study CRUD layer.  Each test uses a
unique temporary DB file (monkey-patched into ``db.DB_FILE`` *and*
``saved_studies.DB_FILE`` — both modules hold their own references to
the constant) so the run never mutates the production ``events.db``.

Surface exercised:
  * save/load round-trip preserves every field and normalises config
  * save rejects unknown study_type, unknown config keys, bad values
  * save rejects duplicate (study_type, name) without overwrite=True
  * save with overwrite=True updates in place, keeping the same id
  * list_studies filters by type and returns newest-first ordering
  * delete_study removes the row and reports whether anything changed
  * created_at / updated_at are populated and updated_at advances on
    overwrite
  * config is stored as JSON, not mutated in place
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ANTHROPIC_API_KEY", "")

import db as _db
import saved_studies as _ss


class _TempDBMixin:
    """Route every SQLite read/write to a throwaway file per test."""

    def setUp(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".db", prefix="saved_studies_test_")
        os.close(fd)
        os.unlink(path)  # init_db wants to create it fresh
        self._tmp_path = path
        self._patchers = [
            mock.patch.object(_db, "DB_FILE", path),
            mock.patch.object(_ss, "DB_FILE", path),
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


class TestSchemaMigration(_TempDBMixin, unittest.TestCase):
    def test_saved_studies_table_exists(self) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='saved_studies'"
            ).fetchone()
        self.assertIsNotNone(row)

    def test_unique_constraint_enforced_at_db_level(self) -> None:
        with sqlite3.connect(self._tmp_path) as conn:
            now = "2026-04-19T00:00:00+00:00"
            conn.execute(
                "INSERT INTO saved_studies "
                "(study_type, name, description, config_json, "
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("cohort_comparison", "A", "", "{}", now, now),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO saved_studies "
                    "(study_type, name, description, config_json, "
                    " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("cohort_comparison", "A", "", "{}", now, now),
                )


class TestSaveLoadRoundTrip(_TempDBMixin, unittest.TestCase):
    def test_cohort_comparison_round_trip(self) -> None:
        saved = _ss.save_study(
            "cohort_comparison", "tariff vs sanction",
            {
                "filter_a": {"family": "tariff"},
                "filter_b": {"family": "sanction"},
                "label_a": "tariff cycles",
                "label_b": "sanction cycles",
            },
            description="paired diff",
        )
        self.assertEqual(saved["study_type"], "cohort_comparison")
        self.assertEqual(saved["name"], "tariff vs sanction")
        self.assertEqual(saved["description"], "paired diff")
        self.assertEqual(saved["config"]["filter_a"], {"family": "tariff"})
        self.assertEqual(saved["config"]["filter_b"], {"family": "sanction"})
        self.assertEqual(saved["config"]["label_a"], "tariff cycles")

        loaded = _ss.load_study(saved["id"])
        self.assertEqual(loaded, saved)

    def test_correlation_study_round_trip(self) -> None:
        saved = _ss.save_study(
            "correlation_study", "default",
            {"limit": 250},
        )
        loaded = _ss.load_study(saved["id"])
        self.assertEqual(loaded["config"], {"limit": 250})

    def test_scenario_pack_research_round_trip(self) -> None:
        saved = _ss.save_study(
            "scenario_pack_research", "tariffs",
            {"pack_name": "tariff_cycle"},
        )
        loaded = _ss.load_study(saved["id"])
        self.assertEqual(loaded["config"]["pack_name"], "tariff_cycle")

    def test_cascade_view_round_trip(self) -> None:
        saved = _ss.save_study(
            "cascade_view", "tariff cascade",
            {
                "family": "tariff",
                "min_weight": 0.35,
                "active_only": True,
                "focal_event_id": 123,
            },
        )
        loaded = _ss.load_study(saved["id"])
        self.assertEqual(loaded["config"]["family"], "tariff")
        self.assertEqual(loaded["config"]["min_weight"], 0.35)
        self.assertIs(loaded["config"]["active_only"], True)
        self.assertEqual(loaded["config"]["focal_event_id"], 123)

    def test_load_missing_returns_none(self) -> None:
        self.assertIsNone(_ss.load_study(99999))

    def test_load_rejects_non_int_id(self) -> None:
        with self.assertRaises(ValueError):
            _ss.load_study("abc")  # type: ignore[arg-type]

    def test_config_is_deep_copied_not_referenced(self) -> None:
        config = {
            "filter_a": {"family": "tariff"},
            "filter_b": {"family": "sanction"},
        }
        saved = _ss.save_study("cohort_comparison", "x", config)
        # Mutate the caller's dict — stored payload must not change.
        config["filter_a"]["family"] = "bank_stress"
        loaded = _ss.load_study(saved["id"])
        self.assertEqual(loaded["config"]["filter_a"], {"family": "tariff"})


class TestValidation(_TempDBMixin, unittest.TestCase):
    def test_unknown_study_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study("not_a_type", "x", {})

    def test_blank_name_raises(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cohort_comparison", "   ",
                {"filter_a": {}, "filter_b": {}},
            )

    def test_cohort_comparison_requires_both_filters(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cohort_comparison", "x",
                {"filter_a": {"family": "tariff"}},
            )

    def test_cohort_comparison_rejects_unknown_filter_key(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cohort_comparison", "x",
                {
                    "filter_a": {"not_a_filter_key": "foo"},
                    "filter_b": {},
                },
            )

    def test_cohort_comparison_rejects_unknown_family(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cohort_comparison", "x",
                {
                    "filter_a": {"family": "not_a_family"},
                    "filter_b": {},
                },
            )

    def test_correlation_study_rejects_out_of_range_limit(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study("correlation_study", "x", {"limit": 5})
        with self.assertRaises(ValueError):
            _ss.save_study("correlation_study", "y", {"limit": 5000})

    def test_scenario_pack_research_rejects_unknown_pack(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "scenario_pack_research", "x",
                {"pack_name": "not_a_pack"},
            )

    def test_scenario_pack_research_requires_pack_name(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study("scenario_pack_research", "x", {})

    def test_cascade_view_rejects_unknown_family(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cascade_view", "x",
                {"family": "not_a_family"},
            )

    def test_cascade_view_rejects_out_of_range_min_weight(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cascade_view", "x", {"min_weight": 1.5},
            )

    def test_cascade_view_rejects_non_bool_active_only(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cascade_view", "x", {"active_only": "yes"},
            )

    def test_config_must_be_dict(self) -> None:
        with self.assertRaises(ValueError):
            _ss.save_study("correlation_study", "x", "not a dict")


class TestOverwriteSemantics(_TempDBMixin, unittest.TestCase):
    def test_duplicate_without_overwrite_raises(self) -> None:
        _ss.save_study(
            "cohort_comparison", "pair",
            {"filter_a": {"family": "tariff"}, "filter_b": {}},
        )
        with self.assertRaises(ValueError):
            _ss.save_study(
                "cohort_comparison", "pair",
                {"filter_a": {"family": "sanction"}, "filter_b": {}},
            )

    def test_overwrite_updates_in_place_same_id(self) -> None:
        first = _ss.save_study(
            "cohort_comparison", "pair",
            {"filter_a": {"family": "tariff"}, "filter_b": {}},
        )
        time.sleep(1.1)  # ensure updated_at moves (iso seconds resolution)
        second = _ss.save_study(
            "cohort_comparison", "pair",
            {"filter_a": {"family": "sanction"}, "filter_b": {}},
            description="updated",
            overwrite=True,
        )
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertNotEqual(first["updated_at"], second["updated_at"])
        self.assertEqual(
            second["config"]["filter_a"], {"family": "sanction"}
        )
        self.assertEqual(second["description"], "updated")

    def test_same_name_different_type_allowed(self) -> None:
        _ss.save_study(
            "cohort_comparison", "shared",
            {"filter_a": {}, "filter_b": {}},
        )
        _ss.save_study(
            "correlation_study", "shared",
            {"limit": 100},
        )
        rows = _ss.list_studies()
        self.assertEqual(len(rows), 2)


class TestListAndDelete(_TempDBMixin, unittest.TestCase):
    def _seed(self) -> dict[str, int]:
        a = _ss.save_study(
            "cohort_comparison", "a",
            {"filter_a": {}, "filter_b": {}},
        )["id"]
        time.sleep(1.1)
        b = _ss.save_study(
            "correlation_study", "b", {"limit": 100},
        )["id"]
        time.sleep(1.1)
        c = _ss.save_study(
            "cohort_comparison", "c",
            {"filter_a": {}, "filter_b": {}},
        )["id"]
        return {"a": a, "b": b, "c": c}

    def test_empty_list(self) -> None:
        self.assertEqual(_ss.list_studies(), [])

    def test_list_newest_first(self) -> None:
        ids = self._seed()
        rows = _ss.list_studies()
        self.assertEqual([r["id"] for r in rows], [ids["c"], ids["b"], ids["a"]])

    def test_list_filtered_by_type(self) -> None:
        self._seed()
        rows = _ss.list_studies("cohort_comparison")
        self.assertEqual({r["name"] for r in rows}, {"a", "c"})
        self.assertTrue(all(r["study_type"] == "cohort_comparison" for r in rows))

    def test_list_rejects_unknown_type(self) -> None:
        with self.assertRaises(ValueError):
            _ss.list_studies("not_a_type")

    def test_delete_removes_row(self) -> None:
        ids = self._seed()
        self.assertTrue(_ss.delete_study(ids["b"]))
        self.assertIsNone(_ss.load_study(ids["b"]))
        remaining = {r["id"] for r in _ss.list_studies()}
        self.assertEqual(remaining, {ids["a"], ids["c"]})

    def test_delete_missing_returns_false(self) -> None:
        self.assertFalse(_ss.delete_study(99999))

    def test_delete_rejects_non_int(self) -> None:
        with self.assertRaises(ValueError):
            _ss.delete_study("abc")  # type: ignore[arg-type]


class TestTimestamps(_TempDBMixin, unittest.TestCase):
    def test_created_and_updated_populated(self) -> None:
        saved = _ss.save_study(
            "correlation_study", "t", {"limit": 100},
        )
        self.assertTrue(saved["created_at"])
        self.assertTrue(saved["updated_at"])
        self.assertEqual(saved["created_at"], saved["updated_at"])


class TestStoredJSONShape(_TempDBMixin, unittest.TestCase):
    def test_config_json_is_valid_json(self) -> None:
        saved = _ss.save_study(
            "cohort_comparison", "x",
            {
                "filter_a": {"family": "tariff"},
                "filter_b": {"family": "sanction"},
            },
        )
        with sqlite3.connect(self._tmp_path) as conn:
            row = conn.execute(
                "SELECT config_json FROM saved_studies WHERE id = ?",
                (saved["id"],),
            ).fetchone()
        parsed = json.loads(row[0])
        self.assertEqual(parsed["filter_a"], {"family": "tariff"})


if __name__ == "__main__":
    unittest.main()
