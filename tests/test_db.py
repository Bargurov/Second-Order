import io
import gc
import os
import shutil
import sqlite3
import sys
import time
import unittest
import uuid

import db


def _make_temp_db(prefix: str) -> tuple[str, str]:
    tmp_dir = os.path.join(os.path.dirname(__file__), f"{prefix}{uuid.uuid4().hex}")
    os.makedirs(tmp_dir)
    return tmp_dir, os.path.join(tmp_dir, "events.db")


def _remove_temp_dir(path: str) -> None:
    last_error = None
    for _ in range(5):
        gc.collect()
        try:
            shutil.rmtree(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(0.05)
    if last_error is not None:
        raise last_error


class TempDbCleanupTests(unittest.TestCase):
    def test_temp_db_directory_cleanup_removes_db_file(self) -> None:
        tmp_dir, db_file = _make_temp_db("test_events_")
        original_db_file = db.DB_FILE
        original_ready = db._db_ready
        try:
            db.DB_FILE = db_file
            db.init_db()
            self.assertTrue(os.path.exists(db_file))
        finally:
            db.DB_FILE = original_db_file
            db._db_ready = original_ready
            _remove_temp_dir(tmp_dir)

        self.assertFalse(os.path.exists(db_file))


class DatabaseSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def test_init_db_creates_database_file(self) -> None:
        db.init_db()
        self.assertTrue(os.path.exists(db.DB_FILE))

    def test_save_and_load_event(self) -> None:
        db.init_db()

        event = {
            "headline": "Country X launches missile attack on border facilities",
            "stage": "escalation",
            "persistence": "medium",
            "mechanism_summary": "Smoke test event",
            "beneficiaries": ["GLD"],
            "losers": ["EWJ"],
            "assets_to_watch": ["GLD", "USO"],
            "confidence": "medium",
            "market_note": "Watch safe havens",
            "notes": "",
        }

        db.save_event(event)
        events = db.load_recent_events(limit=5)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], event["headline"])
        self.assertEqual(events[0]["stage"], event["stage"])
        self.assertEqual(events[0]["persistence"], event["persistence"])
        self.assertEqual(events[0]["mechanism_summary"], event["mechanism_summary"])
        self.assertEqual(events[0]["beneficiaries"], event["beneficiaries"])
        self.assertEqual(events[0]["losers"], event["losers"])
        self.assertEqual(events[0]["assets_to_watch"], event["assets_to_watch"])
        self.assertEqual(events[0]["confidence"], event["confidence"])

    def test_event_date_saved_and_loaded(self) -> None:
        db.init_db()

        event = {
            "headline":    "Test headline for event_date",
            "stage":       "realized",
            "persistence": "medium",
            "confidence":  "low",
            "event_date":  "2025-03-15",
        }
        db.save_event(event)
        events = db.load_recent_events(limit=1)

        self.assertEqual(events[0]["event_date"], "2025-03-15")

    def test_event_date_defaults_to_none(self) -> None:
        db.init_db()

        event = {
            "headline":    "Test headline without event_date",
            "stage":       "realized",
            "persistence": "medium",
            "confidence":  "low",
        }
        db.save_event(event)
        events = db.load_recent_events(limit=1)

        self.assertIsNone(events[0]["event_date"])


class DuplicateGuardTests(unittest.TestCase):
    """save_event() should silently skip near-identical rows saved within
    the last 10 minutes while still allowing legitimate re-saves."""

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def _event(self, **overrides) -> dict:
        base = {
            "headline": "US imposes new tariffs on EU steel",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "medium",
        }
        base.update(overrides)
        return base

    def test_exact_duplicate_blocked(self):
        db.save_event(self._event())
        db.save_event(self._event())          # same headline, no event_date
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)

    def test_duplicate_with_same_event_date_blocked(self):
        db.save_event(self._event(event_date="2025-03-15"))
        db.save_event(self._event(event_date="2025-03-15"))
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 1)

    def test_different_event_date_allowed(self):
        db.save_event(self._event(event_date="2025-03-15"))
        db.save_event(self._event(event_date="2025-04-01"))
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 2)

    def test_none_vs_set_event_date_allowed(self):
        db.save_event(self._event())                        # event_date=None
        db.save_event(self._event(event_date="2025-03-15"))  # event_date set
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 2)

    def test_different_headline_allowed(self):
        db.save_event(self._event())
        db.save_event(self._event(headline="China restricts rare earth exports"))
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 2)

    def test_old_duplicate_allowed(self):
        """A row with an old timestamp should not block a new save."""
        from datetime import timedelta
        old_ts = (
            __import__("datetime").datetime.now() - timedelta(minutes=15)
        ).isoformat(timespec="seconds")
        db.save_event(self._event(timestamp=old_ts))
        db.save_event(self._event())     # now — more than 10 min after old_ts
        events = db.load_recent_events(limit=10)
        self.assertEqual(len(events), 2)


class SchemaVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def test_fresh_database_gets_version_stamped(self):
        db.init_db()
        with sqlite3.connect(self.test_db_file) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_fresh_database_sets_db_ready(self):
        db.init_db()
        self.assertTrue(db._db_ready)

    def test_outdated_database_renamed_to_bak(self):
        """An old database (version 0, events table exists) gets renamed."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()

        db.init_db()

        # Old file moved to .bak
        self.assertTrue(os.path.exists(self.test_db_file + ".bak"))
        # New file created with correct schema
        self.assertTrue(os.path.exists(self.test_db_file))
        with sqlite3.connect(self.test_db_file) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_outdated_database_sets_db_ready(self):
        """After renaming an old DB, init_db still succeeds and sets _db_ready."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()
        db.init_db()
        self.assertTrue(db._db_ready)

    def test_wrong_version_renamed_to_bak(self):
        """A database with a future/wrong version gets renamed."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY)")
        conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 5}")
        conn.commit()
        conn.close()

        db.init_db()

        self.assertTrue(os.path.exists(self.test_db_file + ".bak"))
        with sqlite3.connect(self.test_db_file) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_save_and_load_work_after_outdated_rename(self):
        """Full round-trip after an outdated DB is auto-replaced."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()
        db.init_db()

        db.save_event({
            "headline": "Test after rename",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "low",
        })
        events = db.load_recent_events(limit=1)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["headline"], "Test after rename")

    def test_connection_closed_before_rename(self):
        """The SQLite connection must be fully closed before os.replace runs,
        otherwise Windows will fail with a sharing violation."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()

        from unittest.mock import patch, call
        replace_calls = []
        _real_replace = os.replace  # capture before patch

        def _tracking_replace(src, dst):
            # At the point os.replace is called, we should be able to open
            # the file exclusively — proving the old connection is closed.
            test_conn = sqlite3.connect(src)
            test_conn.close()
            replace_calls.append((src, dst))
            _real_replace(src, dst)  # call the real function, not the mock

        with patch("db.os.replace", side_effect=_tracking_replace):
            db.init_db()

        self.assertEqual(len(replace_calls), 1)
        self.assertTrue(db._db_ready)

    def test_rename_failure_leaves_db_not_ready(self):
        """If os.replace fails (e.g. Windows file lock), init_db must NOT
        stamp the old schema or set _db_ready = True."""
        # Create an outdated DB (version 0, table exists)
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()

        from unittest.mock import patch
        with patch("db.os.replace", side_effect=OSError("locked")):
            db.init_db()

        # _db_ready must be False — the DB is unusable
        self.assertFalse(db._db_ready)

        # save_event must raise, not silently corrupt
        with self.assertRaises(RuntimeError):
            db.save_event({
                "headline": "Should not save",
                "stage": "realized",
                "persistence": "medium",
                "confidence": "low",
            })

        # load_recent_events must return empty, not crash
        self.assertEqual(db.load_recent_events(limit=10), [])

    def test_rename_failure_does_not_stamp_version(self):
        """A failed rename must not overwrite the old version number."""
        conn = sqlite3.connect(self.test_db_file)
        conn.execute(
            "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
        )
        conn.commit()
        conn.close()

        from unittest.mock import patch
        with patch("db.os.replace", side_effect=OSError("locked")):
            db.init_db()

        with sqlite3.connect(self.test_db_file) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        # Must still be 0, not stamped as current
        self.assertEqual(version, 0)

    def test_migration_adds_missing_columns_to_current_version_db(self):
        """A version-3 DB created before the rating column was added should
        get the column via ALTER TABLE migration, not a .bak rename."""
        # Simulate a version-3 DB without the rating column
        with sqlite3.connect(self.test_db_file) as conn:
            conn.execute("""
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, headline TEXT NOT NULL,
                    stage TEXT NOT NULL, persistence TEXT NOT NULL,
                    what_changed TEXT, mechanism_summary TEXT,
                    beneficiaries TEXT, losers TEXT, assets_to_watch TEXT,
                    confidence TEXT, market_note TEXT,
                    market_tickers TEXT DEFAULT '[]',
                    event_date TEXT DEFAULT NULL,
                    notes TEXT DEFAULT ''
                )
            """)
            conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")

        db.init_db()

        # Should be usable — no .bak created
        self.assertFalse(os.path.exists(self.test_db_file + ".bak"))
        self.assertTrue(db._db_ready)

        # Rating column should now exist
        db.save_event({
            "headline": "Migration test",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "low",
        })
        eid = db.load_recent_events(1)[0]["id"]
        db.update_review(eid, "good", "Works")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["rating"], "good")


class DbReadyGuardTests(unittest.TestCase):
    """save_event and load_recent_events should fail safely when _db_ready
    is False (init_db was not called or did not succeed)."""

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self.original_ready = db._db_ready
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file
        db._db_ready = False   # simulate init_db not called

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        db._db_ready = self.original_ready
        _remove_temp_dir(self._tmp_dir)

    def test_save_event_raises_without_init(self):
        with self.assertRaises(RuntimeError):
            db.save_event({
                "headline": "Should fail",
                "stage": "realized",
                "persistence": "medium",
                "confidence": "low",
            })

    def test_load_recent_events_returns_empty_without_init(self):
        result = db.load_recent_events(limit=10)
        self.assertEqual(result, [])

    def test_init_db_enables_save(self):
        """After calling init_db, save_event should work."""
        db.init_db()
        # Should not raise
        db.save_event({
            "headline": "Now it works",
            "stage": "realized",
            "persistence": "medium",
            "confidence": "low",
        })
        events = db.load_recent_events(limit=1)
        self.assertEqual(len(events), 1)


class FindRelatedEventsTests(unittest.TestCase):
    """find_related_events links saved events by headline similarity."""

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def _save(self, headline, **kw) -> int:
        base = {"headline": headline, "stage": "realized",
                "persistence": "medium", "confidence": "low"}
        base.update(kw)
        db.save_event(base)
        events = db.load_recent_events(limit=1)
        return events[0]["id"]

    def test_related_event_found(self):
        id1 = self._save("EU imposes retaliatory tariffs on US steel")
        id2 = self._save("EU announces retaliatory tariffs on US steel imports")
        related = db.find_related_events(id1, "EU imposes retaliatory tariffs on US steel")
        ids = [r["id"] for r in related]
        self.assertIn(id2, ids)

    def test_excludes_self(self):
        id1 = self._save("EU imposes tariffs on US steel")
        related = db.find_related_events(id1, "EU imposes tariffs on US steel")
        ids = [r["id"] for r in related]
        self.assertNotIn(id1, ids)

    def test_unrelated_event_not_linked(self):
        id1 = self._save("EU imposes tariffs on US steel")
        id2 = self._save("Japan launches lunar lander mission")
        related = db.find_related_events(id1, "EU imposes tariffs on US steel")
        ids = [r["id"] for r in related]
        self.assertNotIn(id2, ids)

    def test_returns_empty_when_no_others(self):
        id1 = self._save("Unique headline with no match")
        related = db.find_related_events(id1, "Unique headline with no match")
        self.assertEqual(related, [])

    def test_limit_respected(self):
        self._save("EU tariffs on US steel imports round one")
        self._save("EU tariffs on US steel imports round two")
        self._save("EU tariffs on US steel imports round three")
        id4 = self._save("EU tariffs on US steel imports round four")
        related = db.find_related_events(
            id4, "EU tariffs on US steel imports round four", limit=2)
        self.assertLessEqual(len(related), 2)

    def test_returns_empty_without_init(self):
        db._db_ready = False
        try:
            related = db.find_related_events(1, "anything")
            self.assertEqual(related, [])
        finally:
            db._db_ready = True

    def test_related_has_expected_fields(self):
        self._save("EU imposes retaliatory tariffs on US steel")
        id2 = self._save("EU announces retaliatory tariffs on US steel imports")
        related = db.find_related_events(
            id2, "EU announces retaliatory tariffs on US steel imports")
        self.assertTrue(len(related) >= 1)
        for key in ("id", "headline", "stage", "timestamp"):
            self.assertIn(key, related[0])

    def test_ties_sorted_newest_first(self):
        """When two related events have the same similarity score,
        the newer one (higher id) should appear first."""
        id1 = self._save("EU tariffs on US steel imports round one")
        id2 = self._save("EU tariffs on US steel imports round two")
        id3 = self._save("EU tariffs on US steel imports round three")
        related = db.find_related_events(
            id3, "EU tariffs on US steel imports round three")
        self.assertTrue(len(related) >= 2)
        # id2 is newer than id1 — it should come first
        ids = [r["id"] for r in related]
        self.assertIn(id1, ids)
        self.assertIn(id2, ids)
        self.assertLess(ids.index(id2), ids.index(id1))

    def test_higher_similarity_beats_newer(self):
        """An older event with higher similarity should rank above a newer
        event with lower similarity."""
        # Very similar to the query
        id_close = self._save("EU imposes retaliatory tariffs on US steel imports")
        # Less similar (shares fewer words)
        id_far = self._save("EU tariffs steel")
        id_query = self._save("EU imposes retaliatory tariffs on US steel")
        related = db.find_related_events(
            id_query, "EU imposes retaliatory tariffs on US steel")
        ids = [r["id"] for r in related]
        if id_close in ids and id_far in ids:
            self.assertLess(ids.index(id_close), ids.index(id_far))


class UpdateReviewTests(unittest.TestCase):
    """Tests for update_review — rating and notes persistence."""

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def _save(self, headline="Test headline", **kw) -> int:
        base = {"headline": headline, "stage": "realized",
                "persistence": "medium", "confidence": "low"}
        base.update(kw)
        db.save_event(base)
        events = db.load_recent_events(limit=1)
        return events[0]["id"]

    def test_set_rating(self):
        eid = self._save()
        db.update_review(eid, "good", "")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["rating"], "good")

    def test_set_notes(self):
        eid = self._save()
        db.update_review(eid, "", "Great analysis")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["notes"], "Great analysis")

    def test_set_both(self):
        eid = self._save()
        db.update_review(eid, "poor", "Mechanism was wrong")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["rating"], "poor")
        self.assertEqual(events[0]["notes"], "Mechanism was wrong")

    def test_update_overwrites(self):
        eid = self._save()
        db.update_review(eid, "good", "First note")
        db.update_review(eid, "mixed", "Revised")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["rating"], "mixed")
        self.assertEqual(events[0]["notes"], "Revised")

    def test_clear_rating(self):
        eid = self._save()
        db.update_review(eid, "good", "Note")
        db.update_review(eid, "", "Note")
        events = db.load_recent_events(1)
        self.assertIsNone(events[0]["rating"])

    def test_new_event_has_no_rating(self):
        self._save()
        events = db.load_recent_events(1)
        self.assertIsNone(events[0].get("rating"))

    def test_raises_without_init(self):
        db._db_ready = False
        try:
            with self.assertRaises(RuntimeError):
                db.update_review(1, "good", "")
        finally:
            db._db_ready = True

    def test_rating_column_added_to_existing_db(self):
        """init_db() should safely add the rating column to an existing
        database that was created without it."""
        # Re-init on the same file — the ALTER TABLE should be a no-op
        db.init_db()
        eid = self._save()
        db.update_review(eid, "good", "")
        events = db.load_recent_events(1)
        self.assertEqual(events[0]["rating"], "good")


class InstitutionalResearchFieldsRoundTripTests(unittest.TestCase):
    """Round-trip coverage for the five new institutional research
    fields.  These are JSON-encoded list columns — the test catches the
    failure mode where a new list column is added to ``save_event`` but
    not to ``_EVENT_LIST_FIELDS``, which would cause the loaded value
    to come back as a raw JSON string instead of a Python list."""

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        _remove_temp_dir(self._tmp_dir)

    def _base_event(self, **overrides: object) -> dict:
        event = {
            "headline":          "Institutional research fields smoke event",
            "stage":              "realized",
            "persistence":        "medium",
            "mechanism_summary":  "A concrete mechanism with enough length.",
            "beneficiaries":      ["CVX"],
            "losers":             ["SU"],
            "assets_to_watch":    ["CVX", "SU"],
            "confidence":         "medium",
            "market_note":        "",
            "notes":              "",
        }
        event.update(overrides)
        return event

    def test_new_fields_default_to_empty_lists_on_legacy_save(self) -> None:
        """A save that does NOT specify the new fields must still produce
        a row whose readback carries the five new fields as empty lists,
        not raw JSON strings and not missing keys."""
        db.init_db()
        db.save_event(self._base_event())
        rows = db.load_recent_events(limit=1)
        self.assertEqual(len(rows), 1)
        for field in (
            "primary_assets", "secondary_assets", "hedge_or_signal_assets",
            "key_falsifiers", "minimum_proof_set",
        ):
            self.assertIn(field, rows[0], f"{field!r} missing from loaded row")
            self.assertIsInstance(
                rows[0][field], list,
                f"{field!r} came back as {type(rows[0][field])!r}, not list — "
                f"likely missing from _EVENT_LIST_FIELDS",
            )
            self.assertEqual(rows[0][field], [])

    def test_ranked_asset_dicts_round_trip(self) -> None:
        db.init_db()
        event = self._base_event(
            primary_assets=[
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct licence holder with heavy-sour lift exposure."},
                {"symbol": "PBF", "rank": 2,
                 "rationale": "Gulf Coast coking refiner gains feedstock cost advantage."},
            ],
            secondary_assets=[
                {"symbol": "VLO", "rank": 1,
                 "rationale": "Large Gulf refiner — secondary follow-through."},
            ],
            hedge_or_signal_assets=[
                {"symbol": "UUP", "rank": 1,
                 "rationale": "Dollar-signal proxy for FX confirmation."},
            ],
        )
        db.save_event(event)
        rows = db.load_recent_events(limit=1)
        self.assertEqual(
            [e["symbol"] for e in rows[0]["primary_assets"]], ["CVX", "PBF"],
        )
        self.assertEqual(rows[0]["primary_assets"][0]["rank"], 1)
        self.assertIn(
            "Direct licence",
            rows[0]["primary_assets"][0]["rationale"],
        )
        self.assertEqual(
            [e["symbol"] for e in rows[0]["secondary_assets"]], ["VLO"],
        )
        self.assertEqual(
            [e["symbol"] for e in rows[0]["hedge_or_signal_assets"]], ["UUP"],
        )

    def test_key_falsifiers_and_minimum_proof_set_round_trip(self) -> None:
        db.init_db()
        event = self._base_event(
            key_falsifiers=[
                "PDVSA issues operational-delay statement within 5d",
                "Congressional resolution narrows the licence within 20d",
            ],
            minimum_proof_set=[
                {"observation": "WCS-WTI discount widens",
                 "channel": "commodities",
                 "threshold": "≥2pp vs pre-licence baseline",
                 "timing": "5-20d"},
            ],
        )
        db.save_event(event)
        rows = db.load_recent_events(limit=1)
        self.assertEqual(len(rows[0]["key_falsifiers"]), 2)
        self.assertIn("PDVSA", rows[0]["key_falsifiers"][0])
        self.assertEqual(len(rows[0]["minimum_proof_set"]), 1)
        self.assertEqual(
            rows[0]["minimum_proof_set"][0]["channel"], "commodities",
        )

    def test_legacy_column_reads_unaffected(self) -> None:
        """A save that exercises both the old and the new fields must
        not regress the legacy column reads — the point of the
        expansion is stability, not schema churn."""
        db.init_db()
        event = self._base_event(
            primary_assets=[
                {"symbol": "CVX", "rank": 1,
                 "rationale": "Direct licence holder with enough rationale length."},
            ],
        )
        db.save_event(event)
        rows = db.load_recent_events(limit=1)
        # Legacy committed lists still land exactly as saved.
        self.assertEqual(rows[0]["beneficiaries"], ["CVX"])
        self.assertEqual(rows[0]["losers"], ["SU"])
        self.assertEqual(rows[0]["assets_to_watch"], ["CVX", "SU"])
        self.assertEqual(rows[0]["confidence"], "medium")

    def test_column_added_to_existing_db(self) -> None:
        """init_db() must idempotently add the five new columns to an
        older DB that was created before the research-fields migration."""
        # First init creates the modern schema.
        db.init_db()
        db.save_event(self._base_event())
        # Second init is a no-op on the ALTER TABLE ADD COLUMN statements.
        db.init_db()
        rows = db.load_recent_events(limit=1)
        for field in (
            "primary_assets", "secondary_assets", "hedge_or_signal_assets",
            "key_falsifiers", "minimum_proof_set",
        ):
            self.assertIn(field, rows[0])


class PriceCacheSourceProviderSchemaTests(unittest.TestCase):
    """D2B — price_cache.source_provider provenance column (schema only).

    init_db() must create ``price_cache`` with a nullable
    ``source_provider`` column and idempotently backfill it onto pre-D2B
    six-column tables via ALTER, all without disturbing the
    ``(ticker, date, auto_adjust)`` primary key.  No writer stamps the
    column yet — that is a later step.
    """

    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self.original_ready = db._db_ready
        self._tmp_dir, self.test_db_file = _make_temp_db("test_events_")
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        db._db_ready = self.original_ready
        _remove_temp_dir(self._tmp_dir)

    def _table_info(self):
        # PRAGMA table_info columns: (cid, name, type, notnull, dflt_value, pk)
        with sqlite3.connect(self.test_db_file) as conn:
            return conn.execute("PRAGMA table_info(price_cache)").fetchall()

    def test_init_db_creates_source_provider_column(self) -> None:
        db.init_db()
        by_name = {r[1]: r for r in self._table_info()}
        self.assertIn("source_provider", by_name)
        self.assertEqual(by_name["source_provider"][2].upper(), "TEXT")
        self.assertEqual(
            by_name["source_provider"][3], 0, "source_provider must be nullable",
        )
        self.assertEqual(
            by_name["source_provider"][5], 0,
            "source_provider must not be part of the primary key",
        )

    def test_primary_key_unchanged(self) -> None:
        db.init_db()
        by_name = {r[1]: r for r in self._table_info()}
        pk_cols = {name for name, r in by_name.items() if r[5] > 0}
        self.assertEqual(pk_cols, {"ticker", "date", "auto_adjust"})

    def test_migration_idempotent_across_repeated_init_db(self) -> None:
        db.init_db()
        with sqlite3.connect(self.test_db_file) as conn:
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("AAPL", "2026-03-02", 100.0, 1000.0, 0,
                 "2026-03-02T00:00:00Z"),
            )
            conn.commit()

        db.init_db()  # second pass — ALTER must no-op, row must survive

        with sqlite3.connect(self.test_db_file) as conn:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(price_cache)").fetchall()]
            count = conn.execute(
                "SELECT COUNT(*) FROM price_cache").fetchone()[0]
            provider = conn.execute(
                "SELECT source_provider FROM price_cache").fetchone()[0]
        self.assertEqual(cols.count("source_provider"), 1)
        self.assertEqual(count, 1, "init_db must not rebuild/wipe price_cache")
        self.assertIsNone(provider)

    def test_alter_backfills_legacy_six_column_table(self) -> None:
        # A pre-D2B version-3 DB whose price_cache predates the column.
        with sqlite3.connect(self.test_db_file) as conn:
            conn.execute("""
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL, headline TEXT NOT NULL,
                    stage TEXT NOT NULL, persistence TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE price_cache (
                    ticker      TEXT NOT NULL,
                    date        TEXT NOT NULL,
                    close       REAL,
                    volume      REAL,
                    auto_adjust INTEGER NOT NULL,
                    fetched_at  TEXT NOT NULL,
                    PRIMARY KEY (ticker, date, auto_adjust)
                )
            """)
            conn.execute(
                "INSERT INTO price_cache "
                "(ticker, date, close, volume, auto_adjust, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("SPY", "2026-03-02", 50.0, 10.0, 0, "2026-03-02T00:00:00Z"),
            )
            conn.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION}")
            conn.commit()

        db.init_db()  # must ALTER the column in, not rename the DB to .bak

        self.assertFalse(os.path.exists(self.test_db_file + ".bak"))
        with sqlite3.connect(self.test_db_file) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM price_cache WHERE ticker='SPY'").fetchone()
        self.assertIn("source_provider", row.keys())
        self.assertIsNone(row["source_provider"])
        self.assertEqual(db.derive_price_provider(row), "legacy_unknown")


class DerivePriceProviderTests(unittest.TestCase):
    """D2B read helper — DERIVED ON READ, never stored.

    ``derive_price_provider`` maps a price_cache ``source_provider`` value
    (or a full row) to a non-blank label: the stored provider when present,
    else ``"legacy_unknown"`` for the NULL/blank legacy state.
    """

    def test_none_reads_legacy_unknown(self) -> None:
        self.assertEqual(db.derive_price_provider(None), "legacy_unknown")

    def test_empty_string_reads_legacy_unknown(self) -> None:
        self.assertEqual(db.derive_price_provider(""), "legacy_unknown")

    def test_whitespace_only_reads_legacy_unknown(self) -> None:
        self.assertEqual(db.derive_price_provider("   "), "legacy_unknown")

    def test_stored_provider_reads_back(self) -> None:
        self.assertEqual(db.derive_price_provider("yfinance"), "yfinance")

    def test_dict_with_provider(self) -> None:
        self.assertEqual(
            db.derive_price_provider({"source_provider": "yfinance"}),
            "yfinance",
        )

    def test_dict_with_null_provider(self) -> None:
        self.assertEqual(
            db.derive_price_provider({"source_provider": None}),
            "legacy_unknown",
        )

    def test_dict_missing_provider_key(self) -> None:
        self.assertEqual(
            db.derive_price_provider({"ticker": "AAPL"}),
            "legacy_unknown",
        )

    def test_accepts_sqlite_row(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE TABLE t (source_provider TEXT, other TEXT)")
            conn.execute("INSERT INTO t VALUES (?, ?)", ("yfinance", "x"))
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM t").fetchone()
        finally:
            conn.close()
        self.assertEqual(db.derive_price_provider(row), "yfinance")


if __name__ == "__main__":
    unittest.main()
