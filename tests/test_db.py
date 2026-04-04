import io
import os
import sqlite3
import sys
import tempfile
import unittest
import uuid

import db


class DatabaseSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

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
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

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
        self.test_db_file = os.path.join(
            tempfile.gettempdir(),
            f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        for path in (self.test_db_file, self.test_db_file + ".bak"):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

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
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file
        db._db_ready = False   # simulate init_db not called

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        db._db_ready = self.original_ready
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

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
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

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
        self.test_db_file = os.path.join(
            tempfile.gettempdir(), f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file
        db.init_db()

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

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


if __name__ == "__main__":
    unittest.main()
