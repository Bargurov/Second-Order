import sqlite3
import json
from datetime import datetime

DB_FILE = "events.db"

# Increment this whenever the events table schema changes.
# init_db() stamps a fresh database with this version and warns when
# an existing database was created with an older schema.
SCHEMA_VERSION = 3


def init_db() -> None:
    """Create the events table if it doesn't exist yet.

    Uses PRAGMA user_version (a free integer in every SQLite file header,
    default 0) to detect schema mismatches:
    - Fresh database (user_version=0, no events table): create + stamp.
    - Old database  (user_version=0, events table already exists): warn.
    - Current       (user_version matches SCHEMA_VERSION): nothing to do.
    - Future        (user_version > SCHEMA_VERSION): warn.

    No automatic migration is performed. If a warning fires, back up
    events.db and delete it so init_db() can recreate the correct schema.
    """
    with sqlite3.connect(DB_FILE) as conn:
        # PRAGMA user_version reads the 4-byte version field in the db header.
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version == 0:
            # Version 0 means either a brand-new file or a database created
            # before versioning was added. Check the events table to tell them apart.
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            if existing:
                print(
                    f"\n[db] WARNING: events.db uses an outdated schema "
                    f"(version 0, expected {SCHEMA_VERSION})."
                    "\n[db] Back up events.db and delete it to recreate with the current schema."
                    "\n[db] Saving new events may fail until the database is recreated.\n"
                )
                return   # leave the old file untouched
            # else: fresh file — fall through to CREATE TABLE + stamp

        elif current_version != SCHEMA_VERSION:
            print(
                f"\n[db] WARNING: events.db schema version {current_version} "
                f"does not match expected version {SCHEMA_VERSION}."
                "\n[db] Back up events.db and delete it to recreate with the current schema.\n"
            )
            return   # leave the mismatched file untouched

        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                headline          TEXT NOT NULL,
                stage             TEXT NOT NULL,
                persistence       TEXT NOT NULL,
                what_changed      TEXT,
                mechanism_summary TEXT,
                beneficiaries     TEXT,
                losers            TEXT,
                assets_to_watch   TEXT,
                confidence        TEXT,
                market_note       TEXT,
                market_tickers    TEXT DEFAULT '[]',
                event_date        TEXT DEFAULT NULL,
                notes             TEXT DEFAULT ''
            )
        """)

        # Stamp the version now that the schema is correct.
        # Only needed for fresh databases (current_version == 0 with no existing table).
        if current_version == 0:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def save_event(event: dict) -> None:
    """Insert one event record into the database.

    Lists are stored as JSON strings — SQLite has no array type.
    """
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            INSERT INTO events (
                timestamp, headline, stage, persistence,
                what_changed, mechanism_summary, beneficiaries, losers,
                assets_to_watch, confidence, market_note, market_tickers, event_date, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("timestamp", datetime.now().isoformat(timespec="seconds")),
            event["headline"],
            event["stage"],
            event["persistence"],
            event.get("what_changed", ""),
            event.get("mechanism_summary", ""),
            json.dumps(event.get("beneficiaries", [])),
            json.dumps(event.get("losers", [])),
            json.dumps(event.get("assets_to_watch", [])),
            event.get("confidence", "low"),
            event.get("market_note", ""),
            json.dumps(event.get("market_tickers", [])),
            event.get("event_date"),        # stored as 'YYYY-MM-DD' string or None
            event.get("notes", ""),
        ))
    print(f"Saved to {DB_FILE}.")


def load_recent_events(limit: int = 10) -> list[dict]:
    """Return the most recent events, newest first."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
            SELECT * FROM events ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()

    events = []
    for row in rows:
        event = dict(row)
        # Decode JSON strings back into Python lists/dicts
        event["beneficiaries"]  = json.loads(event["beneficiaries"]   or "[]")
        event["losers"]         = json.loads(event["losers"]          or "[]")
        event["assets_to_watch"]= json.loads(event["assets_to_watch"] or "[]")
        event["market_tickers"] = json.loads(event["market_tickers"]  or "[]")
        events.append(event)

    return events
