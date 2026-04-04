import io
import os
import sqlite3
import sys
import unittest
import uuid

import db


class DatabaseSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self.test_db_file = os.path.join(
            os.getcwd(),
            "tests",
            f"test_events_{uuid.uuid4().hex}.db",
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


class SchemaVersionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_db_file = db.DB_FILE
        self.test_db_file = os.path.join(
            os.getcwd(),
            "tests",
            f"test_events_{uuid.uuid4().hex}.db",
        )
        db.DB_FILE = self.test_db_file

    def tearDown(self) -> None:
        db.DB_FILE = self.original_db_file
        if os.path.exists(self.test_db_file):
            try:
                os.remove(self.test_db_file)
            except PermissionError:
                pass

    def test_fresh_database_gets_version_stamped(self):
        # A brand-new database should be stamped with SCHEMA_VERSION after init_db().
        db.init_db()
        with sqlite3.connect(self.test_db_file) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, db.SCHEMA_VERSION)

    def test_outdated_database_prints_warning(self):
        # Simulate an old database: events table exists but user_version is still 0.
        with sqlite3.connect(self.test_db_file) as conn:
            conn.execute(
                "CREATE TABLE events (id INTEGER PRIMARY KEY, headline TEXT)"
            )
            # user_version stays at 0 (SQLite default) — no stamp

        captured = io.StringIO()
        sys.stdout = captured
        try:
            db.init_db()
        finally:
            sys.stdout = sys.__stdout__

        output = captured.getvalue()
        self.assertIn("WARNING", output)
        self.assertIn("outdated schema", output)


if __name__ == "__main__":
    unittest.main()
