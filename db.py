import os
import sqlite3
import json
from datetime import datetime, timedelta

DB_FILE = "events.db"

# Increment this whenever the events table schema changes.
# init_db() stamps a fresh database with this version and renames
# outdated databases to .bak so the app never runs against a wrong schema.
SCHEMA_VERSION = 3

# Module-level flag — set to True only after init_db() succeeds.
# save_event() and load_recent_events() check this before touching the DB.
_db_ready: bool = False


def init_db() -> None:
    """Create the events table if it doesn't exist yet.

    Uses PRAGMA user_version to detect schema mismatches.  When an outdated
    or mismatched database is found, it is renamed to ``events.db.bak``
    (overwriting any previous backup) and a fresh database is created.  This
    ensures the app never silently runs against a schema that's missing
    columns needed by save_event / load_recent_events.
    """
    global _db_ready
    _db_ready = False

    if not _handle_outdated_db():
        # Rename was needed but failed (e.g. Windows file lock).
        # Do NOT stamp the old schema or set _db_ready — the DB is unusable.
        return

    with sqlite3.connect(DB_FILE) as conn:
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

        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version != SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        # Safe migrations: add columns that older schema-version-3 databases
        # may be missing.  ALTER TABLE ADD COLUMN is non-destructive — existing
        # rows get the default value.  The try/except makes each call
        # idempotent (silently no-ops when the column already exists).
        _migrations = [
            "ALTER TABLE events ADD COLUMN market_tickers TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN event_date TEXT DEFAULT NULL",
            "ALTER TABLE events ADD COLUMN notes TEXT DEFAULT ''",
            "ALTER TABLE events ADD COLUMN rating TEXT DEFAULT NULL",
        ]
        for sql in _migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # column already exists

    _db_ready = True


def _handle_outdated_db() -> bool:
    """Detect and rename an outdated database before the app opens it.

    Cases handled:
    - Fresh file (doesn't exist or user_version==0 with no events table):
      nothing to do — init_db will create the schema.
    - Old database (user_version==0 but events table exists): pre-versioning
      schema — rename to .bak.
    - Wrong version (user_version != SCHEMA_VERSION): rename to .bak.
    - Current (user_version == SCHEMA_VERSION): nothing to do.

    Returns True if init_db is safe to proceed (DB is current, fresh, or was
    successfully renamed).  Returns False if the DB is outdated and the rename
    failed — init_db must NOT stamp or use the broken schema.
    """
    if not os.path.exists(DB_FILE):
        return True

    # Probe the version.  Must fully close the connection before any rename
    # attempt — on Windows, sqlite3 holds the file handle open until close()
    # is called.  The ``with`` statement only commits; it does NOT close.
    needs_rename = False
    current_version = 0
    conn = sqlite3.connect(DB_FILE)
    try:
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]

        if current_version == SCHEMA_VERSION:
            return True  # all good

        if current_version == 0:
            existing = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='events'"
            ).fetchone()
            if not existing:
                return True  # brand-new empty file — init_db will create schema

        needs_rename = True
    finally:
        conn.close()          # release the file handle before rename

    if not needs_rename:
        return True

    # If we reach here the DB is outdated or mismatched — rename it.
    backup_path = DB_FILE + ".bak"
    try:
        os.replace(DB_FILE, backup_path)
        print(
            f"[db] Outdated database renamed to {backup_path} "
            f"(had schema version {current_version}, need {SCHEMA_VERSION})."
        )
        return True
    except OSError as e:
        print(
            f"[db] WARNING: could not rename outdated {DB_FILE}: {e}\n"
            f"[db] Delete or rename it manually to avoid errors."
        )
        return False


def _is_duplicate(conn: sqlite3.Connection, headline: str,
                   event_date: str | None) -> bool:
    """Check whether a near-identical row already exists.

    A duplicate is defined as: same headline text AND same event_date, saved
    within the last 10 minutes.  The time window avoids blocking a legitimate
    re-analysis hours or days later while catching the common case of
    Streamlit reruns or accidental double-clicks.
    """
    ten_min_ago = (
        datetime.now().replace(microsecond=0) - timedelta(minutes=10)
    ).isoformat(timespec="seconds")

    if event_date is None:
        row = conn.execute(
            "SELECT 1 FROM events "
            "WHERE headline = ? AND event_date IS NULL AND timestamp >= ? "
            "LIMIT 1",
            (headline, ten_min_ago),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM events "
            "WHERE headline = ? AND event_date = ? AND timestamp >= ? "
            "LIMIT 1",
            (headline, event_date, ten_min_ago),
        ).fetchone()
    return row is not None


def save_event(event: dict) -> None:
    """Insert one event record into the database.

    Skips the insert (and prints a note) when the same headline + event_date
    was already saved within the last 10 minutes.  Lists are stored as JSON
    strings — SQLite has no array type.

    Raises RuntimeError if init_db() has not been called or did not succeed.
    """
    if not _db_ready:
        raise RuntimeError(
            "Database not initialised. Call init_db() before save_event()."
        )

    with sqlite3.connect(DB_FILE) as conn:
        headline   = event["headline"]
        event_date = event.get("event_date")

        if _is_duplicate(conn, headline, event_date):
            print(f"[db] Skipped duplicate save for: {headline[:80]}")
            return

        conn.execute("""
            INSERT INTO events (
                timestamp, headline, stage, persistence,
                what_changed, mechanism_summary, beneficiaries, losers,
                assets_to_watch, confidence, market_note, market_tickers, event_date, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            event.get("timestamp", datetime.now().isoformat(timespec="seconds")),
            headline,
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
            event_date,
            event.get("notes", ""),
        ))
    print(f"Saved to {DB_FILE}.")


def update_review(event_id: int, rating: str = None, notes: str = None) -> bool:
    """Update the rating and/or notes for an existing event.

    rating: 'good', 'mixed', 'poor', or None to leave unchanged.
    notes: free-text research note, or None to leave unchanged.
    Returns True if the event existed and was updated, False otherwise.
    Raises RuntimeError if init_db() has not been called.
    """
    if not _db_ready:
        raise RuntimeError(
            "Database not initialised. Call init_db() before update_review()."
        )
    with sqlite3.connect(DB_FILE) as conn:
        # Build SET clause dynamically so we only touch supplied fields.
        sets = []
        params = []
        if rating is not None:
            sets.append("rating = ?")
            params.append(rating or None)
        if notes is not None:
            sets.append("notes = ?")
            params.append(notes)
        if not sets:
            return False
        params.append(event_id)
        cur = conn.execute(
            f"UPDATE events SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Timeline: link related saved events
# ---------------------------------------------------------------------------

_STOP_WORDS: set[str] = {
    "the", "a", "an", "in", "on", "at", "to", "for", "of", "and", "or",
    "is", "are", "was", "were", "by", "with", "from", "as", "its", "it",
    "that", "this", "be", "has", "have", "had", "not", "but", "will",
    "would", "could", "should", "may", "might", "after", "before", "over",
    "new", "says", "said", "about", "into", "up", "out", "more", "than",
}

# Similarity threshold for linking saved events — deliberately stricter than
# the 0.30 used for inbox clustering.  Better to miss a link than to create
# a bad one between unrelated analyses.
_RELATED_THRESHOLD: float = 0.35


def _headline_words(title: str) -> set[str]:
    """Content words from a headline (lowercase, stop-words removed)."""
    return set(title.lower().split()) - _STOP_WORDS


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def find_related_events(event_id: int, headline: str,
                        limit: int = 5) -> list[dict]:
    """Return saved events related to the given one, newest-first.

    Uses Jaccard similarity on headline words.  Only events with a different
    id are considered (the event itself is excluded).  Returns at most
    ``limit`` results above the similarity threshold.
    """
    if not _db_ready:
        return []

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, headline, stage, persistence, confidence, "
            "       timestamp, event_date "
            "FROM events WHERE id != ? ORDER BY id DESC",
            (event_id,),
        ).fetchall()

    target_words = _headline_words(headline)
    if not target_words:
        return []

    scored: list[tuple[float, dict]] = []
    for row in rows:
        sim = _jaccard(target_words, _headline_words(row["headline"]))
        if sim >= _RELATED_THRESHOLD:
            scored.append((sim, dict(row)))

    # Sort by similarity descending, then newest first as tiebreaker
    scored.sort(key=lambda pair: (-pair[0], -(pair[1].get("id") or 0)))
    return [ev for _, ev in scored[:limit]]


def load_recent_events(limit: int = 10) -> list[dict]:
    """Return the most recent events, newest first.

    Returns an empty list if init_db() has not been called or did not succeed
    (avoids crashing the Recent Events section in Streamlit).
    """
    if not _db_ready:
        return []

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
