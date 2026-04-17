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
            "ALTER TABLE events ADD COLUMN model TEXT DEFAULT NULL",
            "ALTER TABLE events ADD COLUMN transmission_chain TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN if_persists TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN low_signal INTEGER DEFAULT 0",
            "ALTER TABLE events ADD COLUMN currency_channel TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN policy_sensitivity TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN inventory_context TEXT DEFAULT '{}'",
            # Regime snapshot — compact macro vector captured at analyse time
            # so the regime-conditioned analog re-ranker can compare past
            # backdrops to the current one.  See regime_vector.py.
            "ALTER TABLE events ADD COLUMN regime_snapshot TEXT DEFAULT '{}'",
            # Market-check freshness — when the ticker returns were last
            # refreshed against the provider.  NULL on legacy rows; newly
            # saved rows are stamped at save time.  Consumed by
            # market_check_freshness.compute_staleness to decide whether
            # a /analyze or /backtest hit should reuse the stored tickers
            # or pull fresh numbers.
            "ALTER TABLE events ADD COLUMN last_market_check_at TEXT DEFAULT NULL",
            # Persisted macro overlay blocks — so the frozen-cached
            # response path in api._build_cached_response can surface
            # the macro snapshot the event was analysed under instead
            # of rendering empty blocks.  JSON-encoded; every field is
            # optional and defaults to '{}'.
            "ALTER TABLE events ADD COLUMN real_yield_context TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN policy_constraint TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN shock_decomposition TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN reaction_function_divergence TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN surprise_vs_anticipation TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN terms_of_trade TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN reserve_stress TEXT DEFAULT '{}'",
            # Revisit timeline — JSON array of follow-through snapshots
            # captured at 1d/5d/20d after event.  Each entry is a dict:
            # {day: int, captured_at: str, tickers: [{symbol, return_Nd, direction}]}
            "ALTER TABLE events ADD COLUMN revisit_snapshots TEXT DEFAULT '[]'",
            # Narrative divergence — thesis vs market price-action discrepancy.
            # Computed in routes/analyze.py after market_check; persisted so
            # the frozen-archive response path can surface the original reading.
            "ALTER TABLE events ADD COLUMN narrative_divergence TEXT DEFAULT '{}'",
        ]
        for sql in _migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    pass  # expected — column already exists
                else:
                    print(f"[db] Migration warning: {e} — SQL: {sql}")

        # Separate cache table for news payloads — not versioned with events.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_cache (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                payload    TEXT NOT NULL,
                fetched_at TEXT NOT NULL
            )
        """)

        # Persistent daily price cache — not versioned with events.  Routed
        # through by market_check._fetch / _fetch_since / ticker_chart via
        # price_cache.fetch_daily_cached().  Keyed by (ticker, date,
        # auto_adjust) because adjusted and unadjusted closes coexist:
        # live rolling reads use auto_adjust=True, while event-anchored
        # backtests use auto_adjust=False to avoid retroactive lookahead.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS price_cache (
                ticker      TEXT NOT NULL,
                date        TEXT NOT NULL,
                close       REAL,
                volume      REAL,
                auto_adjust INTEGER NOT NULL,
                fetched_at  TEXT NOT NULL,
                PRIMARY KEY (ticker, date, auto_adjust)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_price_cache_ticker_range
            ON price_cache (ticker, auto_adjust, date)
        """)

        # Precomputed movers slices — each row is the full payload a
        # /movers/<slice> endpoint returns, plus a small fingerprint
        # (max_event_id + event_count) that lets the cache layer detect
        # when a slice is stale without re-reading every row of ``events``.
        # See movers_cache.py for the read/refresh logic.  One row per
        # named slice ("weekly", "yearly", "persistent", ...).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS movers_cache (
                slice            TEXT PRIMARY KEY,
                payload          TEXT NOT NULL,
                built_at         TEXT NOT NULL,
                event_count      INTEGER NOT NULL DEFAULT 0,
                max_event_id     INTEGER NOT NULL DEFAULT 0,
                compute_version  INTEGER NOT NULL DEFAULT 0
            )
        """)
        # Migration for existing DBs that lack the compute_version column.
        try:
            conn.execute(
                "ALTER TABLE movers_cache ADD COLUMN compute_version INTEGER DEFAULT 0"
            )
        except sqlite3.OperationalError:
            pass  # column already exists (fresh DB or already migrated)

        # Persisted news clusters — one row per live cluster.  See
        # news_cluster_store.py.  ``payload_json`` carries the full
        # frontend-visible cluster dict (headline, summary, consensus,
        # sources, evidence, agreement, ...); ``records_json`` carries
        # the compact list of (source, title, published_at, url) triples
        # for every headline that has ever joined the cluster so a
        # metadata rebuild can re-run over the true union when a new
        # source joins.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_clusters (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                headline            TEXT NOT NULL,
                payload_json        TEXT NOT NULL,
                records_json        TEXT NOT NULL DEFAULT '[]',
                latest_published_at TEXT,
                updated_at          TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_clusters_latest
            ON news_clusters (latest_published_at)
        """)

        # Headline-to-cluster assignments.  Primary key is
        # ``(source, title_key)`` so the same title from different
        # publishers is tracked separately (that's how fetch_all dedups
        # — see news_sources._dedup_key).  A row here is the "this
        # headline has already been clustered" marker the incremental
        # path uses to skip reclustering.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news_headline_assignments (
                source      TEXT NOT NULL,
                title_key   TEXT NOT NULL,
                cluster_id  INTEGER NOT NULL,
                assigned_at TEXT NOT NULL,
                PRIMARY KEY (source, title_key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_headline_assignments_cluster
            ON news_headline_assignments (cluster_id)
        """)

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

    Atomicity
    ---------
    Two concurrent ``save_event`` calls with the same headline used to
    race: both SELECTs could run before either INSERT, both would see
    zero duplicates, and both would succeed.  We fix that by opening
    the connection in autocommit mode (``isolation_level=None``) and
    issuing ``BEGIN IMMEDIATE`` explicitly so the write lock is held
    for the duration of the check-then-insert.  Concurrent writers
    serialise on the lock; the second one sees the first one's row
    inside the dedup window and exits cleanly.

    Raises RuntimeError if init_db() has not been called or did not succeed.
    """
    if not _db_ready:
        raise RuntimeError(
            "Database not initialised. Call init_db() before save_event()."
        )

    conn = sqlite3.connect(DB_FILE, isolation_level=None, timeout=30.0)
    try:
        # BEGIN IMMEDIATE acquires the SQLite write lock right now —
        # any concurrent save_event call will block here until this
        # transaction commits (or rolls back).  Without this the
        # default deferred transaction only upgrades to a write lock
        # on the first INSERT, leaving a race window between _is_duplicate
        # and the INSERT itself.
        conn.execute("BEGIN IMMEDIATE")
        try:
            headline   = event["headline"]
            event_date = event.get("event_date")

            if _is_duplicate(conn, headline, event_date):
                conn.execute("COMMIT")
                print(f"[db] Skipped duplicate save for: {headline[:80]}")
                return

            ts_value = event.get(
                "timestamp",
                datetime.now().isoformat(timespec="seconds"),
            )
            # A newly-saved event has, by definition, just had its market
            # tickers computed — stamp the freshness timestamp so subsequent
            # reads can reuse the stored tickers without a refresh.
            last_check = event.get("last_market_check_at") or ts_value

            conn.execute("""
                INSERT INTO events (
                    timestamp, headline, stage, persistence,
                    what_changed, mechanism_summary, beneficiaries, losers,
                    assets_to_watch, confidence, market_note, market_tickers,
                    event_date, notes, model, transmission_chain, if_persists,
                    low_signal, currency_channel, policy_sensitivity, inventory_context,
                    regime_snapshot, last_market_check_at,
                    real_yield_context, policy_constraint, shock_decomposition,
                    reaction_function_divergence, surprise_vs_anticipation,
                    terms_of_trade, reserve_stress, narrative_divergence
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
            """, (
                ts_value,
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
                event.get("model"),
                json.dumps(event.get("transmission_chain", [])),
                json.dumps(event.get("if_persists", {})),
                event.get("low_signal", 0),
                json.dumps(event.get("currency_channel", {})),
                json.dumps(event.get("policy_sensitivity", {})),
                json.dumps(event.get("inventory_context", {})),
                json.dumps(event.get("regime_snapshot", {})),
                last_check,
                json.dumps(event.get("real_yield_context", {})),
                json.dumps(event.get("policy_constraint", {})),
                json.dumps(event.get("shock_decomposition", {})),
                json.dumps(event.get("reaction_function_divergence", {})),
                json.dumps(event.get("surprise_vs_anticipation", {})),
                json.dumps(event.get("terms_of_trade", {})),
                json.dumps(event.get("reserve_stress", {})),
                json.dumps(event.get("narrative_divergence", {})),
            ))
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        conn.close()
    print(f"Saved to {DB_FILE}.")


def update_event_market_refresh(
    event_id: int,
    market_tickers: list[dict],
    market_note: str,
    last_market_check_at: str,
) -> bool:
    """Persist a fresh market snapshot onto an existing event row.

    Called by market_check_freshness.refresh_market_for_saved_event after a
    stale row has been re-validated against the provider.  We overwrite the
    whole ``market_tickers`` payload (numerics + direction tags) along with
    the human-readable ``market_note`` and stamp ``last_market_check_at`` so
    follow-up reads see the row as fresh.

    Movers-cache invalidation
    -------------------------
    An in-place UPDATE does not change the ``(event_count, max_event_id)``
    fingerprint the movers cache uses to detect new events, so without an
    explicit invalidation the /movers/* endpoints would keep serving the
    pre-refresh ticker numbers until TTL expired (up to 2 hours).  On a
    successful write we invalidate every persisted mover slice so the
    next read recomputes from the refreshed row.  The late import keeps
    this function decoupled from the movers_cache module at import time.

    Returns True if the row existed and was updated.
    """
    if not _db_ready:
        return False
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "UPDATE events SET market_tickers = ?, market_note = ?, "
            "last_market_check_at = ? WHERE id = ?",
            (
                json.dumps(market_tickers or []),
                market_note or "",
                last_market_check_at,
                event_id,
            ),
        )
        updated = cur.rowcount > 0

    if updated:
        # Late import to avoid a circular db → movers_cache → db bootstrap.
        try:
            import movers_cache
            movers_cache.invalidate()
        except Exception:
            # Invalidation failures are non-fatal: the refresh itself
            # succeeded, and the movers cache will recover on the next
            # TTL expiry even if we can't drop the row now.
            pass

    return updated


def append_revisit_snapshot(event_id: int, snapshot: dict) -> bool:
    """Append a revisit follow-through snapshot to an event's timeline.

    Each snapshot is a dict: {day, captured_at, tickers}.
    Deduplicates by ``day`` — if a snapshot for the same day already
    exists it is replaced with the new one (re-capture).

    Returns True if the row existed and was updated.

    Atomicity
    ---------
    The read-modify-write (SELECT → mutate → UPDATE) is wrapped in
    ``BEGIN IMMEDIATE`` so concurrent captures for the same event
    serialise on SQLite's write lock instead of racing.  Without this,
    two concurrent calls could both read the same snapshot list, each
    append its own entry, and the second writer would silently clobber
    the first one's snapshot.
    """
    if not _db_ready:
        return False
    conn = sqlite3.connect(DB_FILE, isolation_level=None, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT revisit_snapshots FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False
            raw = row["revisit_snapshots"] if row["revisit_snapshots"] else "[]"
            try:
                existing = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                existing = []
            # Replace any entry for the same day.
            day = snapshot.get("day")
            existing = [s for s in existing if s.get("day") != day]
            existing.append(snapshot)
            existing.sort(key=lambda s: s.get("day", 0))
            conn.execute(
                "UPDATE events SET revisit_snapshots = ? WHERE id = ?",
                (json.dumps(existing), event_id),
            )
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
    finally:
        conn.close()
    return True


def load_revisit_snapshots(event_id: int) -> list[dict]:
    """Return the revisit timeline snapshots for an event.

    Returns [] if event not found or no snapshots stored.
    """
    if not _db_ready:
        return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT revisit_snapshots FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
    if row is None:
        return []
    raw = row["revisit_snapshots"] if row["revisit_snapshots"] else "[]"
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


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


def delete_event(event_id: int) -> bool:
    """Delete a saved event by primary key.

    Returns True if the event existed and was deleted, False if not found.
    Raises RuntimeError if init_db() has not been called.
    """
    if not _db_ready:
        raise RuntimeError(
            "Database not initialised. Call init_db() before delete_event()."
        )
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Track record — aggregate thesis outcomes across all saved events
# ---------------------------------------------------------------------------


def _resolve_direction_tag(t: dict) -> str:
    """Extract the direction string from a ticker dict regardless of key name.

    market_tickers rows use ``direction_tag``, revisit snapshot tickers
    use ``direction``.  This helper tries both in a fixed order so the
    scoring logic never silently falls back to unresolved just because
    the upstream path chose a different key name.
    """
    return t.get("direction_tag") or t.get("direction") or ""


def _score_directions(ticker_list: list[dict]) -> tuple[bool, bool, int, int]:
    """Score a list of ticker dicts for supports/contradicts.

    Returns (has_supports, has_contradicts, supporting_count, with_direction_count).

    Works with both ``direction_tag`` (market_tickers) and ``direction``
    (revisit snapshots) via ``_resolve_direction_tag`` — callers no
    longer need to specify which key to read.
    """
    has_supports = False
    has_contradicts = False
    supporting = 0
    with_direction = 0
    for t in ticker_list:
        if not isinstance(t, dict):
            continue
        tag = _resolve_direction_tag(t)
        if not tag:
            continue
        with_direction += 1
        if tag.startswith("supports"):
            has_supports = True
            supporting += 1
        elif tag.startswith("contradicts"):
            has_contradicts = True
    return has_supports, has_contradicts, supporting, with_direction


def _best_revisit_snapshot(snapshots: list) -> list[dict] | None:
    """Return the longest-horizon revisit snapshot's tickers, or None.

    Prefers 20d > 5d > 1d.  Returns None if no snapshots exist or
    the best snapshot has no tickers.
    """
    if not snapshots:
        return None
    # Sort descending by day; pick the first with tickers.
    for snap in sorted(snapshots, key=lambda s: s.get("day", 0), reverse=True):
        tickers = snap.get("tickers")
        if tickers:
            return tickers
    return None


def compute_track_record() -> dict:
    """Aggregate thesis outcomes and user ratings across all events.

    Scoring per event — prefers revisit snapshots when available:
      1. If the event has revisit_snapshots, use the longest-horizon
         snapshot (20d > 5d > 1d) to classify the outcome.
      2. Otherwise fall back to the initial market_tickers direction_tag.

    Classification (same for both sources):
      validated    = at least 1 ticker direction starts with "supports"
      contradicted = at least 1 "contradicts" AND zero "supports"
      unresolved   = all direction tags are null / empty

    Returns a flat dict of counts + avg_support_ratio + revisit_scored.
    """
    if not _db_ready:
        return {
            "total": 0, "validated": 0, "contradicted": 0, "unresolved": 0,
            "avg_support_ratio": None, "revisit_scored": 0,
            "rated_good": 0, "rated_mixed": 0, "rated_poor": 0,
        }

    with sqlite3.connect(DB_FILE) as conn:
        # Include revisit_snapshots in the query.
        try:
            rows = conn.execute(
                "SELECT market_tickers, rating, revisit_snapshots FROM events"
            ).fetchall()
        except sqlite3.OperationalError:
            # Column may not exist yet on ancient DBs.
            rows = conn.execute(
                "SELECT market_tickers, rating FROM events"
            ).fetchall()
            rows = [(r[0], r[1], None) for r in rows]

    total = len(rows)
    validated = 0
    contradicted = 0
    unresolved = 0
    revisit_scored = 0
    rated_good = 0
    rated_mixed = 0
    rated_poor = 0
    support_ratios: list[float] = []

    for row in rows:
        raw_tickers = row[0]
        rating = row[1]
        raw_revisit = row[2] if len(row) > 2 else None

        # --- Try revisit snapshots first ---
        try:
            revisit_snaps = json.loads(raw_revisit or "[]")
        except (json.JSONDecodeError, TypeError):
            revisit_snaps = []

        best_revisit = _best_revisit_snapshot(revisit_snaps)
        used_revisit = False

        if best_revisit is not None:
            has_sup, has_con, sup_cnt, dir_cnt = _score_directions(
                best_revisit,
            )
            if dir_cnt > 0:
                used_revisit = True
                revisit_scored += 1

        # --- Fall back to market_tickers ---
        if not used_revisit:
            try:
                tickers = json.loads(raw_tickers or "[]")
            except (json.JSONDecodeError, TypeError):
                tickers = []
            has_sup, has_con, sup_cnt, dir_cnt = _score_directions(tickers)

        # --- Classify ---
        if has_sup:
            validated += 1
        elif has_con:
            contradicted += 1
        else:
            unresolved += 1

        if dir_cnt > 0:
            support_ratios.append(sup_cnt / dir_cnt)

        if rating == "good":
            rated_good += 1
        elif rating == "mixed":
            rated_mixed += 1
        elif rating == "poor":
            rated_poor += 1

    avg_sr = round(sum(support_ratios) / len(support_ratios), 3) if support_ratios else None

    return {
        "total": total,
        "validated": validated,
        "contradicted": contradicted,
        "unresolved": unresolved,
        "avg_support_ratio": avg_sr,
        "revisit_scored": revisit_scored,
        "rated_good": rated_good,
        "rated_mixed": rated_mixed,
        "rated_poor": rated_poor,
    }


def get_confidence_calibration_stats(min_events: int = 3) -> dict:
    """Per-bucket validation rate for events with usable directional outcomes.

    An event has a usable outcome if at least one ticker has a direction_tag
    of 'supports ...' or 'contradicts ...'.  Uses the same source-preference
    logic as compute_track_record (revisit snapshots preferred, market_tickers
    as fallback).

    Returns::

        {
            "low":    {"hit_rate": 0.35, "n": 45},  # present when n >= min_events
            "medium": {"hit_rate": 0.52, "n": 67},
            "high":   {"hit_rate": 0.68, "n": 23},
        }

    Buckets with fewer than ``min_events`` usable events are omitted.
    """
    if not _db_ready:
        return {}

    with sqlite3.connect(DB_FILE) as conn:
        try:
            rows = conn.execute(
                "SELECT confidence, market_tickers, revisit_snapshots FROM events "
                "WHERE confidence IN ('low', 'medium', 'high')"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT confidence, market_tickers FROM events "
                "WHERE confidence IN ('low', 'medium', 'high')"
            ).fetchall()
            rows = [(r[0], r[1], None) for r in rows]

    buckets: dict[str, dict] = {
        "low":    {"validated": 0, "total": 0},
        "medium": {"validated": 0, "total": 0},
        "high":   {"validated": 0, "total": 0},
    }

    for row in rows:
        conf = row[0] or "low"
        raw_tickers = row[1]
        raw_revisit = row[2] if len(row) > 2 else None

        # Prefer the best revisit snapshot; fall back to initial tickers.
        try:
            revisit_snaps = json.loads(raw_revisit or "[]")
        except (json.JSONDecodeError, TypeError):
            revisit_snaps = []

        best = _best_revisit_snapshot(revisit_snaps)
        if best is not None:
            has_sup, _has_con, _sup_cnt, dir_cnt = _score_directions(best)
        else:
            try:
                tickers = json.loads(raw_tickers or "[]")
            except (json.JSONDecodeError, TypeError):
                tickers = []
            has_sup, _has_con, _sup_cnt, dir_cnt = _score_directions(tickers)

        if dir_cnt == 0:
            continue  # no usable outcome for this event

        b = buckets.get(conf)
        if b is None:
            continue
        b["total"] += 1
        if has_sup:
            b["validated"] += 1

    result: dict = {}
    for bucket, s in buckets.items():
        if s["total"] >= min_events:
            result[bucket] = {
                "hit_rate": round(s["validated"] / s["total"], 3),
                "n": s["total"],
            }
    return result


# ---------------------------------------------------------------------------
# Timeline: link related saved events
# ---------------------------------------------------------------------------

from token_norm import _STOP_WORDS, _normalize_token, _headline_words
from news_relevance import _is_calendar_headline

# Similarity threshold for linking saved events — deliberately stricter than
# the 0.30 used for inbox clustering.  Better to miss a link than to create
# a bad one between unrelated analyses.
_RELATED_THRESHOLD: float = 0.35


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# Minimum shared content-tokens required when the *shorter* headline
# (after stop-word removal) has very few words.  A single shared generic
# term like "oil" or "tariff" between two 2-word headlines yields a
# Jaccard of 0.33 — above the related-events threshold — but carries
# almost no semantic signal.  Requiring ≥2 shared tokens for short
# headlines blocks these false positives while preserving genuine
# matches like "OPEC cuts output" ↔ "OPEC production cut" (shared:
# opec, cut).
_MIN_SHARED_TOKENS: int = 2
_SHORT_HEADLINE_THRESHOLD: int = 4  # applies when min(len(a), len(b)) <= this


def _short_headline_guard(a: set[str], b: set[str]) -> bool:
    """Return True if the match should be KEPT, False to suppress.

    When both sets are above ``_SHORT_HEADLINE_THRESHOLD`` content words
    the guard always passes — Jaccard alone is discriminating enough for
    longer headlines.  For short headlines, require at least
    ``_MIN_SHARED_TOKENS`` shared words.
    """
    if min(len(a), len(b)) > _SHORT_HEADLINE_THRESHOLD:
        return True
    return len(a & b) >= _MIN_SHARED_TOKENS


def load_low_signal_headlines() -> set[str]:
    """Return a set of headlines that were analyzed and tagged as low_signal."""
    if not _db_ready:
        return set()
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT headline FROM events WHERE low_signal = 1"
        ).fetchall()
    return {row[0] for row in rows}


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
        if _is_calendar_headline(row["headline"]):
            continue
        row_words = _headline_words(row["headline"])
        sim = _jaccard(target_words, row_words)
        if sim >= _RELATED_THRESHOLD and _short_headline_guard(target_words, row_words):
            scored.append((sim, dict(row)))

    # Sort by similarity descending, then newest first as tiebreaker
    scored.sort(key=lambda pair: (-pair[0], -(pair[1].get("id") or 0)))
    return [ev for _, ev in scored[:limit]]


def get_event_cascade(
    event_id: int,
    per_level: int = 5,
    hop2_per_parent: int = 2,
) -> dict:
    """BFS cascade: root → hop-1 (direct Jaccard-related) → hop-2 (follow-on from hop-1).

    Returns { "root": dict | None, "nodes": list[dict] }.
    Each node carries: id, headline, stage, persistence, confidence,
    timestamp, event_date, mechanism_summary, hop, parent_id, similarity.
    Nodes are sorted chronologically by event_date / timestamp.
    """
    if not _db_ready:
        return {"root": None, "nodes": []}

    _COLS = (
        "id, headline, stage, persistence, confidence, "
        "timestamp, event_date, mechanism_summary"
    )

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        root_row = conn.execute(
            f"SELECT {_COLS} FROM events WHERE id = ?", (event_id,)
        ).fetchone()
        if not root_row:
            return {"root": None, "nodes": []}
        root = dict(root_row)

        all_rows = conn.execute(
            f"SELECT {_COLS} FROM events WHERE id != ? ORDER BY id DESC",
            (event_id,),
        ).fetchall()
    all_rows = [dict(r) for r in all_rows]

    root_words = _headline_words(root["headline"])
    if not root_words:
        return {"root": root, "nodes": []}

    # Pre-compute word sets for non-calendar events
    row_words: dict[int, set[str]] = {}
    for r in all_rows:
        if not _is_calendar_headline(r["headline"]):
            row_words[r["id"]] = _headline_words(r["headline"])

    # Hop 1
    hop1_scored: list[tuple[float, dict]] = []
    for r in all_rows:
        rw = row_words.get(r["id"])
        if rw is None:
            continue
        sim = _jaccard(root_words, rw)
        if sim >= _RELATED_THRESHOLD and _short_headline_guard(root_words, rw):
            hop1_scored.append((sim, r))
    hop1_scored.sort(key=lambda p: (-p[0], -(p[1]["id"] or 0)))
    hop1_scored = hop1_scored[:per_level]

    seen: set[int] = {event_id} | {r["id"] for _, r in hop1_scored}
    nodes: list[dict] = []
    for sim, r in hop1_scored:
        nodes.append({**r, "hop": 1, "parent_id": event_id, "similarity": round(sim, 3)})

    # Hop 2
    for _sim1, h1_row in hop1_scored:
        h1_id = h1_row["id"]
        h1_words = row_words.get(h1_id)
        if not h1_words:
            continue
        hop2_scored: list[tuple[float, dict]] = []
        for r in all_rows:
            if r["id"] in seen:
                continue
            rw = row_words.get(r["id"])
            if rw is None:
                continue
            sim = _jaccard(h1_words, rw)
            if sim >= _RELATED_THRESHOLD and _short_headline_guard(h1_words, rw):
                hop2_scored.append((sim, r))
        hop2_scored.sort(key=lambda p: (-p[0], -(p[1]["id"] or 0)))
        for sim2, h2_row in hop2_scored[:hop2_per_parent]:
            seen.add(h2_row["id"])
            nodes.append({**h2_row, "hop": 2, "parent_id": h1_id, "similarity": round(sim2, 3)})

    # Sort chronologically
    def _chron_key(n: dict) -> str:
        return n.get("event_date") or n.get("timestamp") or ""

    nodes.sort(key=_chron_key)
    return {"root": root, "nodes": nodes}


# ---------------------------------------------------------------------------
# Read-time deduplication
# ---------------------------------------------------------------------------

_DEDUP_THRESHOLD: float = 0.65
_DEDUP_DATE_WINDOW_DAYS: int = 2


def _event_dates_close(
    d1: str | None, d2: str | None,
    ts1: str = "", ts2: str = "",
) -> bool:
    """Return True when two event_dates are close enough to be the same event."""
    if d1 is not None and d2 is not None:
        try:
            dt1 = datetime.fromisoformat(d1).date()
            dt2 = datetime.fromisoformat(d2).date()
            return abs((dt1 - dt2).days) <= _DEDUP_DATE_WINDOW_DAYS
        except (ValueError, TypeError):
            return d1 == d2
    if d1 is None and d2 is None:
        # Fall back to save-timestamp proximity for legacy rows without event_date
        try:
            t1 = datetime.fromisoformat(ts1[:19]) if ts1 else None
            t2 = datetime.fromisoformat(ts2[:19]) if ts2 else None
            if t1 and t2:
                return abs((t1 - t2).days) <= 7
        except (ValueError, TypeError):
            pass
        return True
    return False  # one has event_date, the other doesn't → distinct events


def dedup_events(events: list[dict]) -> list[dict]:
    """Collapse near-duplicate saved events at read time.

    Input must be sorted newest-first (by id DESC).  The first (newest)
    event per duplicate group is kept as canonical; older near-duplicates
    are suppressed.  Pure filter — no DB writes.

    Two events are collapsed when BOTH:
    - Headline Jaccard similarity >= _DEDUP_THRESHOLD (0.65)
    - event_date within _DEDUP_DATE_WINDOW_DAYS of each other (or both
      None with timestamps within 7 days for legacy rows)
    """
    if len(events) <= 1:
        return events

    word_sets = [_headline_words(ev.get("headline") or "") for ev in events]
    keep = [True] * len(events)

    for i in range(len(events)):
        if not keep[i]:
            continue
        wi = word_sets[i]
        if not wi:
            continue
        di = events[i].get("event_date")
        ti = events[i].get("timestamp", "")

        for j in range(i + 1, len(events)):
            if not keep[j]:
                continue
            dj = events[j].get("event_date")
            if not _event_dates_close(di, dj, ti, events[j].get("timestamp", "")):
                continue
            wj = word_sets[j]
            sim = _jaccard(wi, wj)
            if sim >= _DEDUP_THRESHOLD and _short_headline_guard(wi, wj):
                keep[j] = False

    return [ev for ev, k in zip(events, keep) if k]


def find_historical_analogs(
    headline: str,
    mechanism: str = "",
    stage: str = "",
    persistence: str = "",
    exclude_headline: str = "",
    limit: int = 3,
    current_regime_vector: dict | None = None,
) -> list[dict]:
    """Find past events similar to the current analysis.

    Uses Jaccard on headline words + stage/persistence bonus scoring.
    Extracts follow-through (best ticker 5d/20d returns) and decay label
    from each analog's stored market_tickers.

    When ``current_regime_vector`` is provided and available, the
    candidate list is widened, each candidate's persisted
    ``regime_snapshot`` is decoded, and the list is re-ranked by the
    regime-conditioned layer before being truncated to ``limit``.
    This lets same-topic / different-regime analogs fall down the list
    while lower-topic / better-regime analogs rise up.  When the regime
    vector is missing or unavailable, the function falls back to the
    existing topic-only ordering so stale macro degrades cleanly.

    Returns up to ``limit`` analogs sorted by relevance then recency.
    Each analog: {headline, event_date, stage, persistence,
                  return_5d, return_20d, decay, confidence, ...}
    Returns [] when there are not enough matches.
    """
    if not _db_ready:
        return []

    # When regime rerank is active we want a wider candidate pool so the
    # rerank layer has something to reshuffle.  Topic-only mode keeps the
    # tight pool to preserve historical behaviour.
    regime_active = bool(
        current_regime_vector
        and current_regime_vector.get("available")
    )
    candidate_limit = max(limit * 3, limit) if regime_active else limit

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT headline, event_date, stage, persistence, confidence, "
            "       market_tickers, mechanism_summary, low_signal, "
            "       regime_snapshot "
            "FROM events ORDER BY id DESC LIMIT 500"
        ).fetchall()

    target_hl_words = _headline_words(headline)
    target_words = set(target_hl_words)
    if mechanism:
        target_words |= _headline_words(mechanism)
    if not target_words:
        return []

    # Lower threshold than find_related_events — we want more candidates
    _ANALOG_THRESHOLD = 0.15

    scored: list[tuple[float, dict]] = []
    for row in rows:
        row_hl = row["headline"]
        # Skip self and low-signal events
        if row_hl == exclude_headline or row_hl == headline:
            continue
        if row["low_signal"]:
            continue

        row_hl_words = _headline_words(row_hl)

        # Guard fires on headline-only words BEFORE mechanism expansion so
        # mechanism-text overlap alone can never rescue a short-headline pair
        # that lacks sufficient headline-word agreement.
        if not _short_headline_guard(target_hl_words, row_hl_words):
            continue

        row_words = set(row_hl_words)
        mech_text = row["mechanism_summary"] or ""
        if mech_text:
            row_words |= _headline_words(mech_text)

        sim = _jaccard(target_words, row_words)
        if sim < _ANALOG_THRESHOLD:
            continue

        # Bonus for matching stage/persistence
        if stage and row["stage"] == stage:
            sim += 0.05
        if persistence and row["persistence"] == persistence:
            sim += 0.03

        # Extract follow-through — pick best 5d and best 20d independently
        # so a ticker with great r5 but missing r20 doesn't shadow another
        # ticker that has valid 20d data.
        tickers = json.loads(row["market_tickers"] or "[]")
        best_5d = None
        best_20d = None
        for t in tickers:
            r5 = t.get("return_5d")
            r20 = t.get("return_20d")
            if r5 is not None and (best_5d is None or abs(r5) > abs(best_5d)):
                best_5d = r5
            if r20 is not None and (best_20d is None or abs(r20) > abs(best_20d)):
                best_20d = r20

        # Classify decay — delegate to the canonical function in market_check
        # to avoid duplicated logic.
        from market_check import classify_decay as _classify_decay
        decay = _classify_decay(best_5d, best_20d)["label"]

        # Build deterministic match reason from shared metadata
        shared_words = target_words & row_words
        top_shared = sorted(shared_words, key=len, reverse=True)[:4]
        reasons: list[str] = []
        if top_shared:
            reasons.append("shared: " + ", ".join(top_shared))
        if stage and row["stage"] == stage:
            reasons.append("same stage")
        if persistence and row["persistence"] == persistence:
            reasons.append("same persistence")
        match_reason = " · ".join(reasons) if reasons else "keyword overlap"

        # Decode the persisted regime snapshot if present.  Old rows
        # default to '{}' which decodes to an empty dict — the rerank
        # layer treats that as "no historical regime".
        try:
            row_regime = json.loads(row["regime_snapshot"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            row_regime = {}
        if not isinstance(row_regime, dict):
            row_regime = {}

        scored.append((sim, {
            "headline": row_hl,
            "event_date": row["event_date"],
            "stage": row["stage"],
            "persistence": row["persistence"],
            "confidence": row["confidence"],
            "return_5d": round(best_5d, 2) if best_5d is not None else None,
            "return_20d": round(best_20d, 2) if best_20d is not None else None,
            "decay": decay,
            "similarity": round(sim, 3),
            "match_reason": match_reason,
            "regime_snapshot": row_regime if row_regime else None,
        }))

    # Sort by relevance desc, then recency desc as tiebreaker
    # Use stable two-pass: first by date desc, then by score desc
    scored.sort(key=lambda pair: pair[1].get("event_date") or "", reverse=True)
    scored.sort(key=lambda pair: pair[0], reverse=True)

    # Story-family dedup BEFORE truncation/rerank.  Two analogs that
    # share the same normalised content-word set + event_date are the
    # same story (re-analysis, slight rewording, case differences).
    # Walking the already-sorted list and keeping the first occurrence
    # per key preserves the highest-scoring representative without
    # touching the rerank logic.
    seen_keys: set[tuple] = set()
    deduped: list[tuple[float, dict]] = []
    for sim_score, ev in scored:
        words_key = frozenset(_headline_words(ev.get("headline") or ""))
        date_key = ev.get("event_date") or ""
        key = (words_key or (ev.get("headline") or "").lower(), date_key)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append((sim_score, ev))

    candidates = [ev for _, ev in deduped[:candidate_limit]]

    # Regime-conditioned re-rank as a layer over topic similarity.  Falls
    # back to no-op when current_regime_vector is unavailable.
    if regime_active:
        from regime_vector import rerank_analogs
        candidates = rerank_analogs(candidates, current_regime_vector)

    return candidates[:limit]


# JSON-encoded columns grouped by default shape.  `_decode_event_row`
# reads these lists so every read path (load_recent_events,
# load_event_by_id, find_cached_analysis) decodes the exact same set
# of fields — no more per-call ad-hoc json.loads calls that silently
# diverge when a new column is added.
_EVENT_LIST_FIELDS: tuple[str, ...] = (
    "beneficiaries", "losers", "assets_to_watch",
    "market_tickers", "transmission_chain",
    "revisit_snapshots",
)
_EVENT_DICT_FIELDS: tuple[str, ...] = (
    "if_persists", "currency_channel", "policy_sensitivity",
    "inventory_context", "regime_snapshot",
    # Macro overlays persisted so the frozen cached-response path can
    # reuse them without re-running live-macro computations.
    "real_yield_context", "policy_constraint", "shock_decomposition",
    "reaction_function_divergence", "surprise_vs_anticipation",
    "terms_of_trade", "reserve_stress",
)


def _decode_event_row(row: sqlite3.Row) -> dict:
    """Turn a ``sqlite3.Row`` into a fully decoded event dict.

    Every JSON-encoded column is decoded with a safe fallback: list
    columns default to ``[]``, dict columns default to ``{}``.  Unknown
    columns pass through untouched.  This is the one read-path
    decoder; keep it in lockstep with ``save_event`` whenever the
    schema gains a new JSON column.
    """
    event = dict(row)
    for field in _EVENT_LIST_FIELDS:
        raw = event.get(field)
        try:
            event[field] = json.loads(raw) if raw else []
        except (json.JSONDecodeError, TypeError):
            event[field] = []
    for field in _EVENT_DICT_FIELDS:
        raw = event.get(field)
        try:
            event[field] = json.loads(raw) if raw else {}
        except (json.JSONDecodeError, TypeError):
            event[field] = {}
    return event


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

    return [_decode_event_row(row) for row in rows]


def load_events_since(since_ts: str) -> list[dict]:
    """Return every event with ``timestamp >= since_ts``, newest first.

    Unlike ``load_recent_events`` this is bounded by *time*, not by a
    row count, so a burst of low-value rows can never push relevant
    events out of the result set.  ``since_ts`` must be an ISO-8601
    timestamp string (the same format ``save_event`` writes).

    Returns an empty list when the DB is uninitialised or no events
    fall inside the window — callers never need to handle None.
    """
    if not _db_ready:
        return []

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events WHERE timestamp >= ? ORDER BY id DESC",
            (since_ts,),
        ).fetchall()

    return [_decode_event_row(row) for row in rows]


def query_events_filtered(
    *,
    search: str | None = None,
    stage: str | None = None,
    persistence: str | None = None,
    confidence: str | None = None,
    rating: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """Return events matching the provided filters, newest first.

    All parameters are optional. With no parameters the function returns
    every event in the database (equivalent to load_recent_events with no
    limit). The caller is responsible for dedup and pagination.

    search     — LIKE match on headline, mechanism_summary, beneficiaries, losers
    stage      — exact match
    persistence — exact match
    confidence — exact match
    rating     — exact match
    date_from  — inclusive lower bound on timestamp (ISO date "YYYY-MM-DD")
    date_to    — inclusive upper bound on timestamp (ISO date "YYYY-MM-DD")
    """
    if not _db_ready:
        return []

    clauses: list[str] = []
    params: list[object] = []

    if search:
        term = f"%{search}%"
        clauses.append(
            "(headline LIKE ? OR mechanism_summary LIKE ? OR beneficiaries LIKE ? OR losers LIKE ?)"
        )
        params.extend([term, term, term, term])
    if stage:
        clauses.append("stage = ?")
        params.append(stage)
    if persistence:
        clauses.append("persistence = ?")
        params.append(persistence)
    if confidence:
        clauses.append("confidence = ?")
        params.append(confidence)
    if rating:
        clauses.append("rating = ?")
        params.append(rating)
    if date_from:
        clauses.append("timestamp >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("timestamp <= ?")
        params.append(date_to + "T23:59:59")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM events {where} ORDER BY id DESC"

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_decode_event_row(r) for r in rows]


def load_event_by_id(event_id: int) -> dict | None:
    """Return a single event by primary key, or None if not found.

    Unlike load_recent_events, this is not limited to the N most recent rows.
    """
    if not _db_ready:
        return None

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM events WHERE id = ?", (event_id,),
        ).fetchone()

    if row is None:
        return None
    return _decode_event_row(row)


# ---------------------------------------------------------------------------
# Analysis cache — reuse saved events for repeated headlines
# ---------------------------------------------------------------------------

def find_cached_analysis(
    headline: str,
    event_date: str | None = None,
    model: str | None = None,
    max_age_seconds: int = 86400,
) -> dict | None:
    """Return the most recent saved event matching headline + date + model.

    event_date: when provided, only matches events with the same anchor date.
    model: when provided, only matches events analyzed with this model.
    max_age_seconds: rows older than this are treated as stale (default 24 h).
    Returns a dict with the saved fields, or None if no match or stale.
    """
    if not _db_ready:
        return None

    cutoff = (
        datetime.now() - timedelta(seconds=max_age_seconds)
    ).isoformat(timespec="seconds")

    # Build WHERE clause dynamically based on which keys are provided.
    conditions = ["headline = ?", "timestamp >= ?"]
    params: list = [headline, cutoff]

    if event_date is not None:
        conditions.append("event_date = ?")
        params.append(event_date)
    else:
        conditions.append("event_date IS NULL")

    if model is not None:
        conditions.append("model = ?")
        params.append(model)
    # When model is None we match any model — backward compat for old rows.

    # Exclude mock/fallback rows — they contain placeholder text, not
    # real analysis, and must never be served as cache hits.  Legacy
    # rows persisted before the mock-guard was added carry
    # what_changed = "[mock: <reason>]".
    conditions.append("what_changed NOT LIKE '%[mock:%'")

    sql = f"SELECT * FROM events WHERE {' AND '.join(conditions)} ORDER BY id DESC LIMIT 1"

    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(sql, params).fetchone()

    if row is None:
        return None
    return _decode_event_row(row)


# ---------------------------------------------------------------------------
# News cache — persistent storage for /news payloads
# ---------------------------------------------------------------------------

def load_news_cache(max_age_seconds: int = 300) -> dict | None:
    """Return the cached news payload if it exists and is fresh enough.

    Returns None if the cache is empty, stale, or the DB is not ready.
    """
    if not _db_ready:
        return None

    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT payload, fetched_at FROM news_cache WHERE id = 1"
        ).fetchone()

    if row is None:
        return None

    payload_json, fetched_at = row
    try:
        fetched = datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return None

    age = (datetime.now() - fetched).total_seconds()
    if age > max_age_seconds:
        return None

    try:
        return json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None


def save_news_cache(payload: dict) -> None:
    """Persist a news payload to the cache table.

    Uses INSERT OR REPLACE on id=1 so there is always at most one row.
    """
    if not _db_ready:
        return

    now = datetime.now().isoformat(timespec="seconds")
    payload_json = json.dumps(payload)

    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO news_cache (id, payload, fetched_at) VALUES (1, ?, ?)",
            (payload_json, now),
        )


# ---------------------------------------------------------------------------
# Movers cache — persistent storage for precomputed /movers/<slice> payloads
# ---------------------------------------------------------------------------


def get_events_fingerprint() -> tuple[int, int]:
    """Return (event_count, max_event_id) for the events table.

    Used by ``movers_cache.get_slice`` to decide whether a cached payload
    is still valid: if neither number has changed since the cache was
    built, no new event has been saved and no row has been deleted, so
    the cached payload still matches the current events state.
    """
    if not _db_ready:
        return (0, 0)
    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT COUNT(*), COALESCE(MAX(id), 0) FROM events"
        ).fetchone()
    if not row:
        return (0, 0)
    return (int(row[0] or 0), int(row[1] or 0))


def load_movers_cache(slice_name: str) -> dict | None:
    """Return the cached row for a named slice, or None if absent.

    The returned dict contains:
        payload       — list[dict] of mover summaries (decoded JSON)
        built_at      — ISO-8601 timestamp the payload was computed at
        event_count   — fingerprint: events table row count at build time
        max_event_id  — fingerprint: max events.id at build time

    Returns None on legacy / missing cache, corrupt JSON, or a DB that
    was never initialised.  The caller is expected to treat None as
    "bootstrap the cache on this read".
    """
    if not _db_ready:
        return None

    with sqlite3.connect(DB_FILE) as conn:
        row = conn.execute(
            "SELECT payload, built_at, event_count, max_event_id, compute_version "
            "FROM movers_cache WHERE slice = ?",
            (slice_name,),
        ).fetchone()

    if row is None:
        return None

    payload_json, built_at, event_count, max_event_id, compute_version = row
    try:
        payload = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None

    return {
        "payload": payload,
        "built_at": built_at,
        "event_count": int(event_count or 0),
        "max_event_id": int(max_event_id or 0),
        "compute_version": int(compute_version or 0),
    }


def save_movers_cache(
    slice_name: str,
    payload: list,
    built_at: str,
    event_count: int,
    max_event_id: int,
    *,
    compute_version: int = 0,
) -> None:
    """Persist a precomputed mover slice.  One row per slice name."""
    if not _db_ready:
        return

    payload_json = json.dumps(payload or [])
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO movers_cache "
            "(slice, payload, built_at, event_count, max_event_id, compute_version) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slice_name, payload_json, built_at, int(event_count),
             int(max_event_id), int(compute_version)),
        )


def clear_movers_cache(slice_name: str | None = None) -> None:
    """Drop all rows from movers_cache, or just one slice when named.

    Called from tests and from the analyse path when a new event has
    been saved (so the next /movers/* read picks up the fresh row).
    """
    if not _db_ready:
        return
    with sqlite3.connect(DB_FILE) as conn:
        if slice_name is None:
            conn.execute("DELETE FROM movers_cache")
        else:
            conn.execute(
                "DELETE FROM movers_cache WHERE slice = ?",
                (slice_name,),
            )


# ---------------------------------------------------------------------------
# News cluster store — persisted incremental clustering
# ---------------------------------------------------------------------------


def load_news_clusters(recency_cutoff: str | None = None) -> list[dict]:
    """Return persisted clusters newest-first.

    ``recency_cutoff`` — when provided, drop clusters whose
    ``latest_published_at`` is strictly older than the cutoff.  None
    returns every stored cluster regardless of age (used by the
    validation script and by a full-recluster fallback).

    Each dict carries:
        id                  — integer primary key
        headline            — representative headline
        payload             — decoded cluster output (frontend-visible dict)
        records             — list of (source, title, published_at, url)
        latest_published_at — ISO-8601, may be ""
        updated_at          — ISO-8601
    """
    if not _db_ready:
        return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        if recency_cutoff:
            rows = conn.execute(
                "SELECT id, headline, payload_json, records_json, "
                "       latest_published_at, updated_at "
                "FROM news_clusters "
                "WHERE latest_published_at >= ? "
                "ORDER BY latest_published_at DESC, id DESC",
                (recency_cutoff,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, headline, payload_json, records_json, "
                "       latest_published_at, updated_at "
                "FROM news_clusters "
                "ORDER BY latest_published_at DESC, id DESC",
            ).fetchall()

    out: list[dict] = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        try:
            records = json.loads(row["records_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            records = []
        out.append({
            "id":                  int(row["id"]),
            "headline":            row["headline"] or "",
            "payload":             payload,
            "records":             records,
            "latest_published_at": row["latest_published_at"] or "",
            "updated_at":          row["updated_at"] or "",
        })
    return out


def insert_news_cluster(
    headline: str,
    payload: dict,
    records: list[dict],
    latest_published_at: str,
    updated_at: str,
) -> int | None:
    """Insert a brand-new cluster row.  Returns the assigned cluster id."""
    if not _db_ready:
        return None
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "INSERT INTO news_clusters "
            "(headline, payload_json, records_json, latest_published_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                headline or "",
                json.dumps(payload or {}),
                json.dumps(records or []),
                latest_published_at or "",
                updated_at or "",
            ),
        )
        return int(cur.lastrowid)


def update_news_cluster(
    cluster_id: int,
    headline: str,
    payload: dict,
    records: list[dict],
    latest_published_at: str,
    updated_at: str,
) -> bool:
    """Replace an existing cluster row by id."""
    if not _db_ready:
        return False
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "UPDATE news_clusters SET "
            "  headline = ?, payload_json = ?, records_json = ?, "
            "  latest_published_at = ?, updated_at = ? "
            "WHERE id = ?",
            (
                headline or "",
                json.dumps(payload or {}),
                json.dumps(records or []),
                latest_published_at or "",
                updated_at or "",
                int(cluster_id),
            ),
        )
        return cur.rowcount > 0


def delete_news_cluster(cluster_id: int) -> bool:
    if not _db_ready:
        return False
    with sqlite3.connect(DB_FILE) as conn:
        cur = conn.execute(
            "DELETE FROM news_clusters WHERE id = ?", (int(cluster_id),),
        )
        conn.execute(
            "DELETE FROM news_headline_assignments WHERE cluster_id = ?",
            (int(cluster_id),),
        )
        return cur.rowcount > 0


def get_trending_clusters(
    window_hours: int = 72,
    min_sources: int = 3,
    limit: int = 8,
) -> list[dict]:
    """Return top trending clusters scored by source_count * sqrt(1 + record_count)."""
    if not _db_ready:
        return []
    import math
    cutoff = (datetime.now() - timedelta(hours=window_hours)).isoformat(timespec="seconds")
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT headline, payload_json, records_json, latest_published_at "
            "FROM news_clusters WHERE latest_published_at >= ? "
            "ORDER BY latest_published_at DESC",
            (cutoff,),
        ).fetchall()
    results = []
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        source_count = int(payload.get("source_count") or 0)
        if source_count < min_sources:
            continue
        try:
            records = json.loads(row["records_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            records = []
        record_count = len(records)
        score = source_count * math.sqrt(1 + record_count)
        results.append({
            "headline": row["headline"] or "",
            "source_count": source_count,
            "record_count": record_count,
            "latest_published_at": row["latest_published_at"] or "",
            "score": round(score, 2),
        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:limit]


def load_news_headline_assignments() -> dict[tuple[str, str], int]:
    """Return { (source, title_key): cluster_id } for every stored headline."""
    if not _db_ready:
        return {}
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT source, title_key, cluster_id "
            "FROM news_headline_assignments"
        ).fetchall()
    return {(r[0], r[1]): int(r[2]) for r in rows}


def upsert_news_headline_assignments(
    assignments: list[tuple[str, str, int]],
    assigned_at: str,
) -> None:
    """Insert-or-replace a batch of (source, title_key, cluster_id) rows."""
    if not _db_ready or not assignments:
        return
    with sqlite3.connect(DB_FILE) as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO news_headline_assignments "
            "(source, title_key, cluster_id, assigned_at) "
            "VALUES (?, ?, ?, ?)",
            [(s, k, int(cid), assigned_at) for (s, k, cid) in assignments],
        )


def clear_news_cluster_store() -> None:
    """Drop everything from both cluster tables.  Test-only."""
    if not _db_ready:
        return
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("DELETE FROM news_headline_assignments")
        conn.execute("DELETE FROM news_clusters")
