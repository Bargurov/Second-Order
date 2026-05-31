import os
import sqlite3
import json
from datetime import datetime, timedelta
from typing import Any

DB_FILE = "events.db"

# Increment this whenever the events table schema changes.
# init_db() stamps a fresh database with this version and renames
# outdated databases to .bak so the app never runs against a wrong schema.
SCHEMA_VERSION = 3

# Module-level flag — set to True only after init_db() succeeds.
# save_event() and load_recent_events() check this before touching the DB.
_db_ready: bool = False

# ---------------------------------------------------------------------------
# Non-analysis stage markers
# ---------------------------------------------------------------------------
# A ``curated_intake`` row is a real archived event (headline + provenance)
# stamped by the guarded curated-intake writer.  It carries NO thesis, no
# market check, and no scored outcome — it is an operator-curated stub
# awaiting a later analysis phase.  Such rows must never enter an outcome /
# validation denominator (track record, statistical readiness, diagnostics
# outcome counts).  This is the single source of truth for that marker: the
# curated-intake writer and every aggregator key off these names rather than
# re-spelling the literal.
CURATED_INTAKE_STAGE = "curated_intake"
NON_ANALYSIS_STAGES = frozenset({CURATED_INTAKE_STAGE})


def get_db_path() -> str:
    """Return the active SQLite events DB path.

    Tests and local tooling rebind ``DB_FILE`` to redirect writes away
    from the live archive.  Keep all DB access behind this resolver so
    call sites read the current value instead of a stale module import.
    """
    return os.fspath(DB_FILE)


def connect_db(*args, **kwargs) -> sqlite3.Connection:
    """Open a SQLite connection to the active events DB path."""
    return sqlite3.connect(get_db_path(), *args, **kwargs)


def _connect_db(*args, **kwargs) -> sqlite3.Connection:
    return connect_db(*args, **kwargs)


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

    with _connect_db() as conn:
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
            # Credit regime — HY/IG/SHY classification (default-risk vs duration
            # widening, risk-on/off, decoupled).  Computed alongside the other
            # overlays; persisted so the frozen-archive path serves the reading
            # captured at analysis time rather than today's tape.
            "ALTER TABLE events ADD COLUMN credit_regime TEXT DEFAULT '{}'",
            # Credit transmission — funding-stress verdict, equity-vs-credit
            # separation, sector exposures derived from credit_regime + stress
            # + rates_context at analysis time.
            "ALTER TABLE events ADD COLUMN credit_transmission TEXT DEFAULT '{}'",
            # Mechanism-depth fields — structured transmission path (list of hop
            # dicts), substitution barriers / bottlenecks, counterforces /
            # blockers, and the adversarial steel-manned counter-thesis.
            # All four are LLM-core outputs produced by analyze_event.
            "ALTER TABLE events ADD COLUMN transmission_path TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN substitution_barriers TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN counterforces TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN adversarial_challenge TEXT DEFAULT ''",
            # Horizon-aware checkpoints — 1d / 5d / 20d expected / confirms_if /
            # falsifies_if entries + timing_profile.  LLM-core output, persisted
            # so cache hits surface the exact checkpoints the thesis was saved
            # under rather than regenerating them against today's tape.
            "ALTER TABLE events ADD COLUMN horizon_checkpoints TEXT DEFAULT '{}'",
            # Mechanism family + expected channel packs.  LLM commits to a
            # single archetype (tariff, sanction, bank_stress, ...) plus the
            # first / second order channel lists; a keyword-based fallback
            # fills the family when the LLM output is thin.
            "ALTER TABLE events ADD COLUMN mechanism_family TEXT DEFAULT 'none'",
            "ALTER TABLE events ADD COLUMN expected_first_order_channels TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN expected_second_order_channels TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN regime_conditioned_caveat TEXT DEFAULT ''",
            # Optional pointer from a news event to the macro release it was
            # triggered by / clustered around (e.g. a Fed decision or CPI
            # print).  NULL on events that aren't macro-tagged.  See
            # ``macro_surprises.py`` for the release-side table.
            "ALTER TABLE events ADD COLUMN macro_release_id INTEGER DEFAULT NULL",
            # Institutional research fields — ranked asset buckets and
            # flat falsifier / proof-set lists.  All five are JSON-encoded
            # list columns; _EVENT_LIST_FIELDS below walks them so
            # ``load_recent_events`` decodes them to lists (not strings).
            # Non-destructive: legacy rows default to '[]' so
            # ``analyze_event.build_analysis_dict`` fills them from
            # ``_LLM_CORE_DEFAULTS`` on read.
            "ALTER TABLE events ADD COLUMN primary_assets TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN secondary_assets TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN hedge_or_signal_assets TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN key_falsifiers TEXT DEFAULT '[]'",
            "ALTER TABLE events ADD COLUMN minimum_proof_set TEXT DEFAULT '[]'",
            # competing_thesis — head-to-head rival-read block
            # ({primary_thesis, alternative_thesis, discriminator, ...}).
            # JSON-encoded dict column; _EVENT_DICT_FIELDS below walks
            # it so _decode_event_row returns a dict, not a raw string.
            "ALTER TABLE events ADD COLUMN competing_thesis TEXT DEFAULT '{}'",
            # Derived proof / falsifier verdicts.  Computed by
            # ``proof_evaluator`` at save / refresh / revisit time from
            # already-observed evidence (market_tickers + revisit).
            # Legacy rows read back as stable empty dicts via the
            # ``_EVENT_DICT_FIELDS`` decoder below.
            "ALTER TABLE events ADD COLUMN proof_status TEXT DEFAULT '{}'",
            "ALTER TABLE events ADD COLUMN falsifier_status TEXT DEFAULT '{}'",
            # Per-event macro release context — attached when an event's
            # headline maps to a known macro release (CPI / PPI / NFP /
            # Unemployment / PCE within the release window).  JSON-encoded
            # dict carrying ``release_key / release_time / actual / prior /
            # revised_prior / consensus / surprise_label / source``.
            # Old rows default to ``{}`` and are coerced to the canonical
            # empty-shape at the HTTP boundary.  See
            # ``macro_surprise.build_event_macro_release_context``.
            "ALTER TABLE events ADD COLUMN macro_release_context TEXT DEFAULT '{}'",
            # Per-event policy timing context — attached when an event's
            # headline matches a tracked regulatory / trade / rate policy.
            # JSON-encoded dict carrying ``policy_key / announced_date /
            # effective_date / review_date / status / source``.  Mirrors
            # the macro_release_context storage pattern: old rows default
            # to ``{}`` and are coerced to the canonical empty shape at
            # the HTTP boundary.  See
            # ``policy_timing.build_event_policy_timing_context``.
            "ALTER TABLE events ADD COLUMN policy_timing_context TEXT DEFAULT '{}'",
            # Per-event country vulnerability context — attached when an
            # event's text resolves to a profiled country in
            # ``country_backdrop.COUNTRY_BACKDROP_FIXTURE``.  JSON-encoded
            # dict carrying ``country / external_balance_risk /
            # import_shock_risk / commodity_dependence /
            # overall_vulnerability / rationale / stale``.  Same storage
            # pattern as the two blocks above: empty dict for unmatched
            # rows, coerced at the HTTP boundary.  See
            # ``country_backdrop.build_event_country_vulnerability_context``.
            "ALTER TABLE events ADD COLUMN country_vulnerability_context TEXT DEFAULT '{}'",
        ]
        for sql in _migrations:
            try:
                conn.execute(sql)
            except sqlite3.OperationalError as e:
                # Only "duplicate column" is expected — every other
                # ``OperationalError`` (locked DB, malformed SQL, missing
                # table, disk-full, etc.) means the schema upgrade did
                # NOT complete and the runtime would later corrupt or
                # crash on a column it expected to exist.  Fail loudly
                # so the operator sees the problem at startup rather
                # than as a confusing read-time error.
                if "duplicate column" in str(e).lower():
                    continue
                print(f"[db] Migration FAILED: {e} — SQL: {sql}")
                raise

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

        # Headline registry — one row per ingested (source, title_key).
        # Tracks the lifecycle of every ingested headline independently
        # of the cluster store and the events table.  See
        # docs/superpowers/specs/2026-05-03-headline-registry-design.md.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS headline_registry (
                source           TEXT NOT NULL,
                title_key        TEXT NOT NULL,
                cluster_id       INTEGER,
                event_id         INTEGER,
                state            TEXT NOT NULL DEFAULT 'seen',
                last_skip_reason TEXT,
                impact_level     TEXT,
                first_seen_at    TEXT NOT NULL,
                last_seen_at     TEXT NOT NULL,
                analyzed_at      TEXT,
                expired_at       TEXT,
                PRIMARY KEY (source, title_key)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_state
            ON headline_registry (state)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_analyzed_at
            ON headline_registry (analyzed_at)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_headline_registry_cluster
            ON headline_registry (cluster_id)
        """)

        # Curated candidate staging — operator-facing intake table for
        # events that have been surfaced from existing read-only repair
        # / expansion / short-horizon reports and are awaiting manual
        # review BEFORE any analysis or backtest runs against them.
        # Conservative by construction: nothing here is "validated" —
        # status values are limited to {draft, needs_review,
        # ready_for_validation, excluded}; ``primary_ticker``,
        # ``benchmark_ticker``, and ``mechanism_family`` are filled
        # ONLY when those fields are already present in the upstream
        # report payload.  Missing required fields land in
        # ``validation_errors`` (JSON-encoded list of strings) so the
        # operator can triage gaps without the API guessing.
        # Composite UNIQUE(source_event_id, source) so the same archive
        # event_id can legitimately surface from multiple upstream
        # report sources without colliding.  See routes/curated.py.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS curated_candidates (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                source_event_id       INTEGER NOT NULL,
                event_date            TEXT,
                headline              TEXT,
                source_url            TEXT,
                primary_ticker        TEXT,
                benchmark_ticker      TEXT,
                mechanism_family      TEXT,
                mechanism_description TEXT,
                predicted_direction   TEXT,
                prediction_rationale  TEXT,
                curator_notes         TEXT,
                status                TEXT NOT NULL DEFAULT 'draft',
                source                TEXT NOT NULL,
                created_at            TEXT NOT NULL,
                validation_errors     TEXT NOT NULL DEFAULT '[]',
                UNIQUE(source_event_id, source)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_curated_candidates_status
            ON curated_candidates (status)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_curated_candidates_source
            ON curated_candidates (source)
        """)

        # Saved study definitions — persistent, deterministic research
        # configurations (cohort comparison, correlation study, scenario
        # pack research, cascade view).  Stores only inputs/filters, never
        # snapshots of computed output; callers re-execute the config on
        # load to produce fresh results.  UNIQUE(study_type, name) means
        # a user must pass overwrite=True to reuse a name.  See
        # saved_studies.py.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS saved_studies (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                study_type  TEXT NOT NULL,
                name        TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                config_json TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                UNIQUE(study_type, name)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_saved_studies_type
            ON saved_studies (study_type)
        """)

        # Persistent macro releases — one row per scheduled release (CPI,
        # NFP, FOMC, ECB, ...).  Stores the consensus ``expected`` value,
        # the actual ``realized`` value once published, the derived
        # ``surprise`` = realized − expected, and normalised
        # direction/magnitude fields computed at insert time against the
        # historical distribution of prior surprises for the same series.
        # See ``macro_surprises.py`` for semantics.
        #
        # Natural dedup key is ``(series, release_time)`` — the same
        # series cannot have two different prints at the same timestamp.
        # ``release_id`` is a convenience string the ingestion side may
        # generate for stable external references but is not the primary
        # dedup lever.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS macro_releases (
                id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                release_id         TEXT,
                series             TEXT NOT NULL,
                category           TEXT NOT NULL,
                country            TEXT NOT NULL DEFAULT '',
                release_time       TEXT NOT NULL,
                expected           REAL,
                realized           REAL,
                unit               TEXT NOT NULL DEFAULT '',
                surprise           REAL,
                surprise_zscore    REAL,
                surprise_direction TEXT,
                surprise_magnitude TEXT,
                prior_sample_size  INTEGER NOT NULL DEFAULT 0,
                notes              TEXT NOT NULL DEFAULT '',
                created_at         TEXT NOT NULL,
                updated_at         TEXT NOT NULL,
                UNIQUE(series, release_time)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_macro_releases_series_time
            ON macro_releases (series, release_time)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_macro_releases_country_time
            ON macro_releases (country, release_time)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_macro_releases_release_id
            ON macro_releases (release_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_macro_release
            ON events (macro_release_id)
        """)

        # Official release facts cache.  Keyed by ``release_key`` —
        # a synthetic string like ``"CPI:2026-04-10"`` that ties a
        # ``macro_calendar`` entry (name + date) to the official
        # values published by BLS / BEA / etc.  Separate from
        # ``macro_releases`` (which carries surprise z-scores against
        # series like ``us_cpi_yoy``) because the calendar surfaces
        # display names without the unit suffix and feeds need a
        # lightweight write target that doesn't recompute history.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS macro_release_facts (
                release_key   TEXT PRIMARY KEY,
                release_time  TEXT NOT NULL,
                actual        REAL,
                prior         REAL,
                revised_prior REAL,
                consensus     REAL,
                source        TEXT NOT NULL DEFAULT '',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_macro_release_facts_time
            ON macro_release_facts (release_time)
        """)

        # ------------------------------------------------------------------
        # event_provenance — D1A source-provenance sidecar (schema only).
        #
        # One row per source-anchored event; ``event_id`` is the PK and a
        # 1:1 FK to ``events.id``.  This lets FUTURE events record where
        # their headline + mechanism label came from WITHOUT retroactively
        # upgrading historical rows: legacy events simply have no
        # provenance row and read as ``unrecorded`` (see
        # ``derive_provenance_status``).  No writer/intake lives here — that
        # is a later step.  Notes:
        #   * ``provenance_status`` is DERIVED ON READ, never stored.
        #   * ``mechanism_label_provenance`` is NOT NULL but carries NO
        #     CHECK: no grounded label-source taxonomy exists yet, and a
        #     guessed, un-ALTERable enum would force a table rebuild later.
        #     The write layer enforces the vocabulary once the values are
        #     real.  Intended values: 'curated' (human), 'model' (LLM
        #     family commit), 'keyword_fallback' (classify_family),
        #     'unknown' (legacy/backfill).
        #   * The FK is declared for intent; PRAGMA foreign_keys is left at
        #     its default (unenforced) so no existing connection path
        #     changes behaviour.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS event_provenance (
                event_id                   INTEGER PRIMARY KEY,
                source_type                TEXT NOT NULL,
                source_publisher           TEXT,
                source_url                 TEXT,
                source_published_at        TEXT,
                mechanism_label_provenance TEXT NOT NULL,
                intake_path                TEXT NOT NULL,
                created_at                 TEXT NOT NULL,
                FOREIGN KEY (event_id) REFERENCES events (id)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_event_provenance_source_url
            ON event_provenance (source_url)
        """)

    _db_ready = True


# ---------------------------------------------------------------------------
# event_provenance — read-side helpers (D1A).  No writer/intake here.
# ---------------------------------------------------------------------------

def derive_provenance_status(prov: Any) -> str:
    """Map a provenance row to a status — DERIVED ON READ, never stored.

    ``prov`` may be a dict, a ``sqlite3.Row``, or ``None``.  Keys off the
    two external-anchor fields (``source_url`` + ``source_published_at``);
    ``source_type`` / ``source_publisher`` are intentionally ignored.

    * ``None``                            → ``"unrecorded"`` (legacy: no row)
    * source_url AND source_published_at  → ``"source_anchored"``
    * exactly one of the two              → ``"partial"``
    * neither                             → ``"unanchored"``
    """
    if prov is None:
        return "unrecorded"
    if not isinstance(prov, dict):
        # sqlite3.Row (or any keyed row) has no ``.get()`` — normalise.
        prov = {k: prov[k] for k in prov.keys()}
    has_url = bool((prov.get("source_url") or "").strip())
    has_pub = bool((prov.get("source_published_at") or "").strip())
    if has_url and has_pub:
        return "source_anchored"
    if has_url or has_pub:
        return "partial"
    return "unanchored"


def get_event_provenance(event_id: int, conn=None):
    """Return the provenance row for ``event_id`` as a dict, or ``None``.

    Read-only.  ``None`` for legacy events that have no provenance row.
    """
    own = conn is None
    if own:
        conn = _connect_db()
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM event_provenance WHERE event_id = ?", (event_id,)
        ).fetchone()
        return {k: row[k] for k in row.keys()} if row is not None else None
    finally:
        if own:
            conn.close()


def provenance_status_for_event(event_id: int, conn=None) -> str:
    """Derived provenance status for an event id (``"unrecorded"`` if no row)."""
    return derive_provenance_status(get_event_provenance(event_id, conn=conn))


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
    if not os.path.exists(get_db_path()):
        return True

    # Probe the version.  Must fully close the connection before any rename
    # attempt — on Windows, sqlite3 holds the file handle open until close()
    # is called.  The ``with`` statement only commits; it does NOT close.
    needs_rename = False
    current_version = 0
    conn = _connect_db()
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
    backup_path = get_db_path() + ".bak"
    try:
        os.replace(get_db_path(), backup_path)
        print(
            f"[db] Outdated database renamed to {backup_path} "
            f"(had schema version {current_version}, need {SCHEMA_VERSION})."
        )
        return True
    except OSError as e:
        print(
            f"[db] WARNING: could not rename outdated {get_db_path()}: {e}\n"
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


def _compute_proof_block(event: dict) -> dict:
    """Late-import wrapper for ``proof_evaluator.evaluate_proof_status``.

    Kept local so ``db`` doesn't import ``proof_evaluator`` at module
    load (which would pull ``asset_selection`` → ``validation_outcome``
    in before the DB is ready, and also risks a bootstrap loop when
    other modules import ``db``).
    """
    try:
        from proof_evaluator import evaluate_proof_status
        return evaluate_proof_status(event)
    except Exception:
        return {}


def _compute_falsifier_block(event: dict) -> dict:
    """Late-import wrapper for ``proof_evaluator.evaluate_falsifier_status``."""
    try:
        from proof_evaluator import evaluate_falsifier_status
        return evaluate_falsifier_status(event)
    except Exception:
        return {}


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

    conn = _connect_db(isolation_level=None, timeout=30.0)
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
                    terms_of_trade, reserve_stress, narrative_divergence,
                    credit_regime, credit_transmission,
                    transmission_path, substitution_barriers, counterforces,
                    adversarial_challenge, horizon_checkpoints,
                    mechanism_family, expected_first_order_channels,
                    expected_second_order_channels, regime_conditioned_caveat,
                    primary_assets, secondary_assets, hedge_or_signal_assets,
                    key_falsifiers, minimum_proof_set,
                    competing_thesis,
                    proof_status, falsifier_status,
                    macro_release_context,
                    policy_timing_context,
                    country_vulnerability_context
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?,
                    ?, ?, ?,
                    ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?,
                    ?,
                    ?, ?,
                    ?,
                    ?,
                    ?
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
                json.dumps(event.get("credit_regime", {})),
                json.dumps(event.get("credit_transmission", {})),
                json.dumps(event.get("transmission_path", [])),
                json.dumps(event.get("substitution_barriers", [])),
                json.dumps(event.get("counterforces", [])),
                event.get("adversarial_challenge", ""),
                json.dumps(event.get("horizon_checkpoints", {})),
                event.get("mechanism_family", "none"),
                json.dumps(event.get("expected_first_order_channels", [])),
                json.dumps(event.get("expected_second_order_channels", [])),
                event.get("regime_conditioned_caveat", ""),
                # Institutional research fields — stored as JSON lists.
                json.dumps(event.get("primary_assets", [])),
                json.dumps(event.get("secondary_assets", [])),
                json.dumps(event.get("hedge_or_signal_assets", [])),
                json.dumps(event.get("key_falsifiers", [])),
                json.dumps(event.get("minimum_proof_set", [])),
                # competing_thesis — dict or {} when LLM omits it.
                json.dumps(event.get("competing_thesis", {})),
                # Derived proof / falsifier verdicts — evaluated from
                # the same ticker evidence the validation layer uses.
                # Late import avoids a db → proof_evaluator →
                # validation_outcome → db bootstrap loop.
                json.dumps(_compute_proof_block(event)),
                json.dumps(_compute_falsifier_block(event)),
                # Macro release context — caller is expected to have
                # already built the block (analysis pipeline calls
                # ``macro_surprise.build_event_macro_release_context``).
                # Events that don't map to any release land as ``{}``
                # and are coerced at the HTTP boundary.
                json.dumps(event.get("macro_release_context", {})),
                # Policy timing context — same pattern as
                # macro_release_context: caller pre-builds via
                # ``policy_timing.build_event_policy_timing_context``,
                # empty dict stored for unmatched headlines, coerced
                # at the HTTP boundary.
                json.dumps(event.get("policy_timing_context", {})),
                # Country vulnerability context — same pattern again:
                # caller pre-builds via
                # ``country_backdrop.build_event_country_vulnerability_context``;
                # empty dict for events that don't mention any
                # profiled country.
                json.dumps(event.get("country_vulnerability_context", {})),
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
    print(f"Saved to {get_db_path()}.")


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
    with _connect_db() as conn:
        # Pull the proof-structure fields so we can recompute the
        # derived proof / falsifier verdicts against the refreshed
        # tickers.  No new fetches — just re-running the classifier on
        # whatever we're about to persist.
        conn.row_factory = sqlite3.Row
        existing = conn.execute(
            "SELECT minimum_proof_set, key_falsifiers "
            "FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        if existing is None:
            return False
        try:
            mps = json.loads(existing["minimum_proof_set"] or "[]")
        except (json.JSONDecodeError, TypeError):
            mps = []
        try:
            kfs = json.loads(existing["key_falsifiers"] or "[]")
        except (json.JSONDecodeError, TypeError):
            kfs = []
        refreshed_event = {
            "market_tickers":     market_tickers or [],
            "minimum_proof_set":  mps,
            "key_falsifiers":     kfs,
        }
        proof_block = _compute_proof_block(refreshed_event)
        falsifier_block = _compute_falsifier_block(refreshed_event)

        cur = conn.execute(
            "UPDATE events SET market_tickers = ?, market_note = ?, "
            "last_market_check_at = ?, "
            "proof_status = ?, falsifier_status = ? "
            "WHERE id = ?",
            (
                json.dumps(market_tickers or []),
                market_note or "",
                last_market_check_at,
                json.dumps(proof_block),
                json.dumps(falsifier_block),
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
        # Bust the today-movers in-memory TTL cache too.  An in-place
        # refresh stamps ``last_market_check_at = now`` so the row is
        # newly eligible for /movers/today (see the today-window match
        # rule); without invalidating the in-memory cache the surface
        # would lag the eligibility change by up to 5 minutes.
        try:
            import api as _api
            _api._TODAYS_MOVERS_CACHE["data"] = None
        except Exception:
            pass

    return updated


def update_event_overlays(
    event_id: int, overlays: dict[str, Any],
) -> bool:
    """Overwrite JSON-serialized overlay blocks on an existing event row.

    Unlike :func:`save_event` / :func:`update_event_market_refresh`, this
    writer ONLY touches the macro-overlay columns.  The thesis text
    (``what_changed``, ``mechanism_summary``, ``beneficiaries``, …),
    ``market_tickers``, review labels (``rating``, ``notes``, ``low_signal``),
    and the ``last_market_check_at`` stamp all stay exactly as they were
    — this is the overlay-only refresh path for frozen events, so
    historical ground-truth must not be overwritten.

    ``overlays`` keys are intersected with ``PERSISTED_OVERLAY_FIELDS``;
    unknown keys are silently dropped so callers can hand in a partial
    dict without guarding against schema drift.  Each value is JSON-
    serialized (``None`` / non-dict becomes ``{}``).

    Returns True when the UPDATE touched an existing row.
    """
    if not _db_ready or not overlays:
        return False
    from analyze_event import PERSISTED_OVERLAY_FIELDS
    allowed = set(PERSISTED_OVERLAY_FIELDS)
    writes = [(k, overlays[k]) for k in overlays if k in allowed]
    if not writes:
        return False

    set_clauses = ", ".join(f"{k} = ?" for (k, _) in writes)
    params: list[Any] = [
        json.dumps(v if isinstance(v, (dict, list)) else {})
        for (_, v) in writes
    ]
    params.append(event_id)
    with _connect_db() as conn:
        cur = conn.execute(
            f"UPDATE events SET {set_clauses} WHERE id = ?",
            params,
        )
        return cur.rowcount > 0


def update_event_country_vulnerability_context(
    event_id: int, block: dict | None,
) -> bool:
    """Rewrite the ``country_vulnerability_context`` column on one row.

    Same contract as ``update_event_macro_release_context`` /
    ``update_event_policy_timing_context``: ``{}`` clears the block
    (coerced to the canonical empty shape at the HTTP boundary);
    a populated dict rewrites in place.  Returns True when the row
    existed.
    """
    if not _db_ready:
        return False
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ValueError("country_vulnerability_context must be a dict")
    payload = json.dumps(block)
    with _connect_db() as conn:
        cur = conn.execute(
            "UPDATE events SET country_vulnerability_context = ? WHERE id = ?",
            (payload, event_id),
        )
        return cur.rowcount > 0


def update_event_policy_timing_context(
    event_id: int, block: dict | None,
) -> bool:
    """Rewrite the ``policy_timing_context`` column on one event row.

    Called by the refresh-market / refresh-overlays / revisit paths
    after they re-derive the policy match.  Passing ``{}`` clears the
    block (canonical "no match" state); the HTTP boundary coerces it
    back into the stable empty-shape dict for consumers.

    Returns True when the UPDATE touched an existing row.
    """
    if not _db_ready:
        return False
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ValueError("policy_timing_context must be a dict")
    payload = json.dumps(block)
    with _connect_db() as conn:
        cur = conn.execute(
            "UPDATE events SET policy_timing_context = ? WHERE id = ?",
            (payload, event_id),
        )
        return cur.rowcount > 0


def update_event_macro_release_context(
    event_id: int, block: dict | None,
) -> bool:
    """Rewrite the ``macro_release_context`` column on one event row.

    Called by the refresh-market / refresh-overlays / revisit paths
    after they re-query stored release facts.  Passing an empty dict
    (``{}``) clears the block, which is the canonical "no mapping"
    storage state — the HTTP boundary coerces it back into the stable
    empty-shape dict for consumers.

    Returns True when the UPDATE touched an existing row.
    """
    if not _db_ready:
        return False
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ValueError("macro_release_context must be a dict")
    payload = json.dumps(block)
    with _connect_db() as conn:
        cur = conn.execute(
            "UPDATE events SET macro_release_context = ? WHERE id = ?",
            (payload, event_id),
        )
        return cur.rowcount > 0


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
    conn = _connect_db(isolation_level=None, timeout=30.0)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT revisit_snapshots, market_tickers, "
                "       minimum_proof_set, key_falsifiers "
                "FROM events WHERE id = ?",
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

            # Re-evaluate proof / falsifier verdicts so the stored
            # status reflects the newly-appended revisit row.  Uses
            # only what we already have in hand — no new fetches.
            try:
                mps = json.loads(row["minimum_proof_set"] or "[]")
            except (json.JSONDecodeError, TypeError):
                mps = []
            try:
                kfs = json.loads(row["key_falsifiers"] or "[]")
            except (json.JSONDecodeError, TypeError):
                kfs = []
            try:
                tickers = json.loads(row["market_tickers"] or "[]")
            except (json.JSONDecodeError, TypeError):
                tickers = []
            refreshed_event = {
                "market_tickers":     tickers,
                "minimum_proof_set":  mps,
                "key_falsifiers":     kfs,
                "revisit_snapshots":  existing,
            }
            proof_block     = _compute_proof_block(refreshed_event)
            falsifier_block = _compute_falsifier_block(refreshed_event)

            conn.execute(
                "UPDATE events SET revisit_snapshots = ?, "
                "proof_status = ?, falsifier_status = ? "
                "WHERE id = ?",
                (
                    json.dumps(existing),
                    json.dumps(proof_block),
                    json.dumps(falsifier_block),
                    event_id,
                ),
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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

    with _connect_db() as conn:
        # Include revisit_snapshots + stage in the query.
        try:
            rows = conn.execute(
                "SELECT market_tickers, rating, revisit_snapshots, stage "
                "FROM events"
            ).fetchall()
        except sqlite3.OperationalError:
            # revisit_snapshots may not exist on ancient DBs; ``stage`` is a
            # core column that has always existed, so it stays in the fallback.
            rows = conn.execute(
                "SELECT market_tickers, rating, stage FROM events"
            ).fetchall()
            rows = [(r[0], r[1], None, r[2]) for r in rows]

    # Curated-intake stubs are real archived rows but carry no thesis
    # outcome — exclude every non-analysis stage from the denominator so they
    # neither inflate ``total`` nor land in the ``unresolved`` bucket.
    rows = [
        r for r in rows
        if not (isinstance(r[3], str) and r[3] in NON_ANALYSIS_STAGES)
    ]

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

    with _connect_db() as conn:
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


def collect_calibration_samples() -> list[dict]:
    """One normalised sample row per event with a usable directional outcome.

    Shape::

        {
          "confidence":       "low" | "medium" | "high",
          "family":           <mechanism_family id or "none">,
          "compound_regime":  <regime_snapshot.compound.label or "none">,
          "validated":        bool,
        }

    ``validated`` mirrors the same ``has_sup`` signal that
    :func:`get_confidence_calibration_stats` already uses — a
    revisit-snapshot-preferred, market-tickers-fallback read of whether
    at least one ticker's direction_tag supports the thesis.  Events
    with no usable directional outcome are EXCLUDED so the caller's
    bucket counts aren't diluted by no-op rows.

    Intended for the cascading-fallback lookup in
    :mod:`confidence_calibration`.  Kept here (instead of in the
    calibration module) because sample collection is a DB read; the
    interpretation layer on top of these samples is pure.
    """
    if not _db_ready:
        return []

    with _connect_db() as conn:
        # ``regime_snapshot`` and ``mechanism_family`` are both optional
        # on legacy rows.  Try the full query first; fall back when the
        # columns aren't present yet on a just-migrated archive.
        try:
            rows = conn.execute(
                "SELECT confidence, market_tickers, revisit_snapshots, "
                "mechanism_family, regime_snapshot FROM events "
                "WHERE confidence IN ('low', 'medium', 'high')"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = conn.execute(
                "SELECT confidence, market_tickers, revisit_snapshots "
                "FROM events "
                "WHERE confidence IN ('low', 'medium', 'high')"
            ).fetchall()
            rows = [(r[0], r[1], r[2], None, None) for r in rows]

    samples: list[dict] = []
    for row in rows:
        conf = row[0] or "low"
        raw_tickers = row[1]
        raw_revisit = row[2]
        raw_family = row[3] if len(row) > 3 else None
        raw_regime = row[4] if len(row) > 4 else None

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

        family = (raw_family or "none").strip() or "none"

        compound_regime = "none"
        try:
            regime = json.loads(raw_regime or "null")
        except (json.JSONDecodeError, TypeError):
            regime = None
        if isinstance(regime, dict):
            compound = regime.get("compound") or {}
            label = compound.get("label") if isinstance(compound, dict) else None
            if isinstance(label, str) and label:
                compound_regime = label

        samples.append({
            "confidence":      conf,
            "family":          family,
            "compound_regime": compound_regime,
            "validated":       bool(has_sup),
        })

    return samples


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
    with _connect_db() as conn:
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

    with _connect_db() as conn:
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


def _ticker_symbols(market_tickers_json) -> set[str]:
    """Parse a stored ``market_tickers`` JSON blob and return the set of
    upper-cased symbol strings.  Tolerant of malformed input — returns
    an empty set on parse failure or non-list payloads.  Used by
    ``find_similar_events`` to compute shared-ticker overlap without
    decoding the full event row."""
    if not market_tickers_json:
        return set()
    rows = market_tickers_json
    if isinstance(rows, str):
        try:
            rows = json.loads(rows)
        except (TypeError, ValueError):
            return set()
    if not isinstance(rows, list):
        return set()
    out: set[str] = set()
    for t in rows:
        if not isinstance(t, dict):
            continue
        sym = str(t.get("symbol") or "").strip().upper()
        if sym:
            out.add(sym)
    return out


# ---------------------------------------------------------------------------
# Similar-event retrieval — deterministic field-overlap scoring.  Pure
# read; no LLM, no yfinance, no persistence write.  Score weights are
# tuned so headline overlap dominates, mechanism text adds context,
# shared tickers reinforce a real link, and stage/persistence agreement
# acts as a tie-breaker.
# ---------------------------------------------------------------------------
_SIMILAR_W_HEADLINE:    float = 0.40
_SIMILAR_W_MECHANISM:   float = 0.25
_SIMILAR_W_TICKERS:     float = 0.20
_SIMILAR_W_STAGE:       float = 0.10
_SIMILAR_W_PERSISTENCE: float = 0.05


def find_similar_events(
    event_id: int, *, limit: int = 5,
) -> list[dict] | None:
    """Return the top ``limit`` archived events most similar to ``event_id``.

    Composite deterministic score over stored fields only:

      * Jaccard overlap on headline tokens.
      * Jaccard overlap on mechanism_summary tokens.
      * Jaccard overlap on stored ticker symbols.
      * Stage match (1 / 0).
      * Persistence match (1 / 0).

    Returns ``None`` when ``event_id`` does not exist (route boundary
    translates to HTTP 404).  When the target exists but no other row
    scores above zero, returns ``[]`` — a truthful empty signal.

    Pure read.  No LLM call, no provider call, no DB write.
    """
    if not _db_ready:
        return []
    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        target = conn.execute(
            "SELECT id, headline, mechanism_summary, stage, persistence, "
            "       timestamp, market_tickers "
            "FROM events WHERE id = ?", (event_id,),
        ).fetchone()
        if target is None:
            return None
        rows = conn.execute(
            "SELECT id, headline, mechanism_summary, stage, persistence, "
            "       timestamp, market_tickers "
            "FROM events WHERE id != ?", (event_id,),
        ).fetchall()

    target_headline_words = _headline_words(target["headline"] or "")
    target_mech_words     = _headline_words(target["mechanism_summary"] or "")
    target_terms          = target_headline_words | target_mech_words
    target_tickers        = _ticker_symbols(target["market_tickers"])
    target_stage          = (target["stage"] or "").strip()
    target_persistence    = (target["persistence"] or "").strip()

    scored: list[dict] = []
    for r in rows:
        # Calendar headlines (e.g., "ISM Manufacturing PMI") are
        # repetitive event-tagging artifacts that pollute the similar-
        # event surface; the existing ``find_related_events`` skips
        # them for the same reason and the contract here matches.
        if _is_calendar_headline(r["headline"]):
            continue

        row_h_words = _headline_words(r["headline"] or "")
        row_m_words = _headline_words(r["mechanism_summary"] or "")
        row_terms   = row_h_words | row_m_words
        row_tickers = _ticker_symbols(r["market_tickers"])

        h_sim = _jaccard(target_headline_words, row_h_words)
        m_sim = _jaccard(target_mech_words, row_m_words)
        if target_tickers and row_tickers:
            tk_sim = (
                len(target_tickers & row_tickers)
                / len(target_tickers | row_tickers)
            )
        else:
            tk_sim = 0.0
        stage_match = 1.0 if (
            target_stage and target_stage == (r["stage"] or "").strip()
        ) else 0.0
        persistence_match = 1.0 if (
            target_persistence
            and target_persistence == (r["persistence"] or "").strip()
        ) else 0.0

        score = (
            _SIMILAR_W_HEADLINE    * h_sim
            + _SIMILAR_W_MECHANISM * m_sim
            + _SIMILAR_W_TICKERS   * tk_sim
            + _SIMILAR_W_STAGE     * stage_match
            + _SIMILAR_W_PERSISTENCE * persistence_match
        )
        if score <= 0.0:
            continue

        scored.append({
            "event_id":       int(r["id"]),
            "headline":       r["headline"] or "",
            "timestamp":      r["timestamp"] or "",
            "score":          round(float(score), 4),
            "shared_terms":   sorted(target_terms & row_terms),
            "shared_tickers": sorted(target_tickers & row_tickers),
            "stage":          r["stage"] or "",
            "persistence":    r["persistence"] or "",
        })

    scored.sort(key=lambda x: (-x["score"], -x["event_id"]))
    return scored[:int(limit)]


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

    with _connect_db() as conn:
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
    current_event_mechanism: dict | None = None,
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

    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        # mechanism_family is carried forward so the analog explainer can
        # compare families directly; older rows default to 'none'.
        try:
            rows = conn.execute(
                "SELECT headline, event_date, stage, persistence, confidence, "
                "       market_tickers, mechanism_summary, low_signal, "
                "       regime_snapshot, mechanism_family, "
                "       transmission_path, expected_first_order_channels "
                "FROM events ORDER BY id DESC LIMIT 500"
            ).fetchall()
        except sqlite3.OperationalError:
            # Older DBs may lack transmission_path or mechanism_family;
            # fall back to the minimal column set and let the signature
            # composer tag those rows as thin.
            try:
                rows = conn.execute(
                    "SELECT headline, event_date, stage, persistence, confidence, "
                    "       market_tickers, mechanism_summary, low_signal, "
                    "       regime_snapshot, mechanism_family "
                    "FROM events ORDER BY id DESC LIMIT 500"
                ).fetchall()
            except sqlite3.OperationalError:
                try:
                    rows = conn.execute(
                        "SELECT headline, event_date, stage, persistence, confidence, "
                        "       market_tickers, mechanism_summary, low_signal, "
                        "       regime_snapshot "
                        "FROM events ORDER BY id DESC LIMIT 500"
                    ).fetchall()
                except sqlite3.OperationalError:
                    # Archive table may be absent/uninitialized (e.g. fresh
                    # isolated test DB before init_db ran). Degrade to no
                    # analogs rather than propagating the error.
                    rows = []

    target_hl_words = _headline_words(headline)
    target_words = set(target_hl_words)
    if mechanism:
        target_words |= _headline_words(mechanism)
    if not target_words:
        return []

    # Lower threshold than find_related_events — we want more candidates
    _ANALOG_THRESHOLD = 0.15

    # Transmission-signature boost: when the caller passes the current
    # event's mechanism metadata, candidates sharing the same
    # transmission path signature get a deterministic bump.  Keeps
    # topic match as the base signal but lets "same mechanism, different
    # headline wording" analogs rise above pure keyword neighbours.
    _TRANSMISSION_BOOST_SAME_CHAIN = 0.10
    _TRANSMISSION_BOOST_SAME_FAMILY_CHANNELS = 0.06
    _TRANSMISSION_BOOST_SAME_FAMILY = 0.03

    current_sig = None
    if isinstance(current_event_mechanism, dict):
        try:
            from transmission_cluster import transmission_signature as _tsig
            current_sig = _tsig(current_event_mechanism)
        except Exception:
            current_sig = None

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

        # mechanism_family may be absent on legacy rows (pre-column or pre-
        # stamp); default to 'none' so the explainer renders a "family
        # unavailable" dimension cleanly.
        try:
            row_family = row["mechanism_family"] or "none"
        except (IndexError, KeyError):
            row_family = "none"

        # Decode transmission metadata when the row carries it so the
        # transmission signature can be computed for the boost.  Older
        # rows that were SELECTed without these columns silently fall
        # through as empty lists → "thin" signature → no boost.
        row_tpath: list = []
        row_efoc: list = []
        try:
            row_tpath = json.loads(row["transmission_path"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError, IndexError, KeyError):
            row_tpath = []
        try:
            row_efoc = json.loads(row["expected_first_order_channels"] or "[]")
        except (TypeError, ValueError, json.JSONDecodeError, IndexError, KeyError):
            row_efoc = []

        transmission_match = None
        if current_sig is not None:
            try:
                from transmission_cluster import (
                    transmission_signature as _tsig,
                    transmission_similarity as _tsim,
                )
                row_sig = _tsig({
                    "mechanism_family": row_family,
                    "transmission_path": row_tpath,
                    "expected_first_order_channels": row_efoc,
                })
                score = _tsim(current_sig, row_sig)
                # Boost buckets mirror the signature kind so the bump
                # reflects how much the two events actually share:
                # same structured chain >> same family+channels >> same family.
                if row_sig["kind"] == current_sig["kind"] and score >= 0.60:
                    if row_sig["kind"] == "transmission_path":
                        sim += _TRANSMISSION_BOOST_SAME_CHAIN
                        transmission_match = "same_chain"
                    elif row_sig["kind"] == "family_channels":
                        sim += _TRANSMISSION_BOOST_SAME_FAMILY_CHANNELS
                        transmission_match = "same_family_channels"
                    elif row_sig["kind"] == "family_only":
                        sim += _TRANSMISSION_BOOST_SAME_FAMILY
                        transmission_match = "same_family"
            except Exception:
                transmission_match = None

        analog_entry = {
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
            "mechanism_family": row_family,
        }
        if transmission_match:
            analog_entry["transmission_match"] = transmission_match
            analog_entry["match_reason"] = (
                match_reason + " · " + transmission_match
            )
        scored.append((sim, analog_entry))

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
from analyze_event import PERSISTED_OVERLAY_FIELDS as _POF

_EVENT_LIST_FIELDS: tuple[str, ...] = (
    "beneficiaries", "losers", "assets_to_watch",
    "market_tickers", "transmission_chain",
    "transmission_path", "substitution_barriers", "counterforces",
    "expected_first_order_channels", "expected_second_order_channels",
    "revisit_snapshots",
    # Institutional research fields — all five are JSON-encoded list
    # columns; decode on read so callers see lists, not strings.
    "primary_assets", "secondary_assets", "hedge_or_signal_assets",
    "key_falsifiers", "minimum_proof_set",
)
# LLM-core dict fields + every persisted overlay.  Derived from the analyze_event
# registry so a new overlay added there is automatically JSON-decoded on readback;
# prevents the bug class where a saved overlay silently leaks through as a raw
# JSON string (and `or {}` doesn't fire because non-empty strings are truthy).
_EVENT_DICT_FIELDS: tuple[str, ...] = tuple(dict.fromkeys((
    "if_persists", "currency_channel", "horizon_checkpoints",
    # Institutional proof-structure dict fields (complement to the five
    # list-shaped proof-structure columns registered above).
    "competing_thesis",
    # Derived verdicts computed by ``proof_evaluator`` — stored as
    # dicts so ``_decode_event_row`` yields the block shape consumers
    # expect (never a raw JSON string).
    "proof_status", "falsifier_status",
    # Per-event macro release context — decoded so /events/{id}
    # consumers see the block dict, not a raw JSON string.
    "macro_release_context",
    # Per-event policy timing context — same contract.
    "policy_timing_context",
    # Per-event country vulnerability context — same contract.
    "country_vulnerability_context",
    *_POF,
)))


def _coerce_status_block(value: Any) -> dict:
    """Coerce a decoded proof_status / falsifier_status value into a
    stable dict shape.

    Defensive contract for the read path:

    * Any non-dict shape (``None``, string, list, scalar) collapses
      to ``{}`` — the canonical "never evaluated" marker.  Saving an
      uncorrupted block always produces a dict, so a non-dict here
      means the column was hand-edited, mid-migration, or otherwise
      tampered with; consumers iterating the block must not crash on
      that bit-rot.
    * An empty ``{}`` is preserved as-is — distinct from "evaluated
      with zero items" because rows from before the per-item contract
      stored ``{}`` to mean "not yet evaluated."
    * A non-empty dict whose ``items`` key is missing OR is not a list
      gets ``items`` set to ``[]``.  Consumers of ``GET /events/{id}``
      iterate the field unconditionally; coercion here is the single
      read-side guarantee that ``items`` is always iterable.

    Other keys on the dict (verdict, score, etc.) pass through
    untouched so a valid round-trip is not mutated.  Pure read; never
    raises.
    """
    if not isinstance(value, dict):
        return {}
    if not value:
        return {}
    items = value.get("items")
    if isinstance(items, list):
        return value
    out = dict(value)
    out["items"] = []
    return out


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

    # Defensive coercion for the proof_status / falsifier_status
    # blocks.  The dict-fields decode above catches invalid JSON, but
    # a successfully-decoded value can still be the wrong shape
    # (``null`` → None, scalar string, raw list).  ``_coerce_status_block``
    # collapses those to the empty-dict signal and ensures non-empty
    # blocks always carry a list-typed ``items``.
    for field in ("proof_status", "falsifier_status"):
        event[field] = _coerce_status_block(event.get(field))
    return event


def load_recent_events(limit: int = 10) -> list[dict]:
    """Return the most recent events, newest first.

    Returns an empty list if init_db() has not been called or did not succeed
    (avoids crashing the Recent Events section in Streamlit).
    """
    if not _db_ready:
        return []

    with _connect_db() as conn:
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

    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events WHERE timestamp >= ? ORDER BY id DESC",
            (since_ts,),
        ).fetchall()

    return [_decode_event_row(row) for row in rows]


def load_events_market_checked_since(since_ts: str) -> list[dict]:
    """Return events whose ``last_market_check_at >= since_ts``, newest id first.

    Companion to :func:`load_events_since`.  Backfill / refresh paths
    update ``last_market_check_at`` without touching ``timestamp``, so
    the today-mover surface needs this anchor to surface a recently
    market-checked older event alongside freshly-saved ones.  NULL
    ``last_market_check_at`` rows are filtered out by SQLite's three-
    valued comparison semantics.
    """
    if not _db_ready:
        return []

    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM events "
            "WHERE last_market_check_at >= ? "
            "ORDER BY id DESC",
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

    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()

    return [_decode_event_row(r) for r in rows]


def load_event_by_id(event_id: int) -> dict | None:
    """Return a single event by primary key, or None if not found.

    Unlike load_recent_events, this is not limited to the N most recent rows.
    """
    if not _db_ready:
        return None

    with _connect_db() as conn:
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
    *,
    event_id: int | None = None,
) -> dict | None:
    """Return the most recent saved event matching the cache key.

    Routing precedence — when ``event_id`` is provided, lookup is by
    primary key only (still TTL- and mock-guarded); ``headline`` /
    ``event_date`` / ``model`` are ignored and the headline fallback
    does NOT fire.  This avoids the near-duplicate collision where two
    different events share a headline within the 24h window.  When
    ``event_id`` is absent, behaviour is the legacy headline + date +
    model match.

    Args:
      headline: required positional for backward compatibility; ignored
        when ``event_id`` is provided.
      event_date: when provided (and ``event_id`` is not), only matches
        events with the same anchor date.
      model: when provided (and ``event_id`` is not), only matches
        events analyzed with this model.
      max_age_seconds: rows older than this are treated as stale
        (default 24 h).  Applies to both lookup paths.
      event_id: when provided, exact-id lookup takes precedence over
        the headline path; a miss returns ``None`` rather than serving
        a colliding row.

    Returns:
      A dict with the saved fields, or ``None`` if no match or stale.
    """
    if not _db_ready:
        return None

    cutoff = (
        datetime.now() - timedelta(seconds=max_age_seconds)
    ).isoformat(timespec="seconds")

    # Mock guard — applies to both lookup paths.  Legacy rows
    # persisted before the mock-guard was added carry
    # what_changed = "[mock: <reason>]".
    mock_guard = "what_changed NOT LIKE '%[mock:%'"

    if event_id is not None:
        # Exact-id route — bypass headline / date / model entirely so a
        # near-duplicate sharing the same headline within the TTL
        # window cannot be served instead of the requested row.
        sql = (
            "SELECT * FROM events "
            f"WHERE id = ? AND timestamp >= ? AND {mock_guard} "
            "LIMIT 1"
        )
        with _connect_db() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(sql, [event_id, cutoff]).fetchone()
        if row is None:
            return None
        return _decode_event_row(row)

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

    conditions.append(mock_guard)

    sql = f"SELECT * FROM events WHERE {' AND '.join(conditions)} ORDER BY id DESC LIMIT 1"

    with _connect_db() as conn:
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

    with _connect_db() as conn:
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

    with _connect_db() as conn:
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
    with _connect_db() as conn:
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

    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
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
    with _connect_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO news_headline_assignments "
            "(source, title_key, cluster_id, assigned_at) "
            "VALUES (?, ?, ?, ?)",
            [(s, k, int(cid), assigned_at) for (s, k, cid) in assignments],
        )


# ---------------------------------------------------------------------------
# Headline registry helpers
# ---------------------------------------------------------------------------

# Forward-only lifecycle. Index = "advancement rank"; advance_state never
# regresses (a higher-rank state already on the row wins).
_REGISTRY_LIFECYCLE = (
    "seen", "eligible", "analyzed", "market_checked", "surfaced",
    "expired_low_impact",
)
_REGISTRY_RANK = {s: i for i, s in enumerate(_REGISTRY_LIFECYCLE)}


def upsert_headline_registry_seen(
    rows: list[tuple[str, str, int | None]],
    now_iso: str,
) -> None:
    """UPSERT one registry row per ``(source, title_key, cluster_id)``.

    On conflict, only ``cluster_id`` and ``last_seen_at`` are updated;
    ``state``, ``event_id``, ``analyzed_at``, ``impact_level``, and
    ``expired_at`` are preserved so re-ingesting an analyzed headline
    cannot regress its lifecycle.
    """
    if not _db_ready or not rows:
        return
    payload = [
        (src, key, cluster_id, now_iso, now_iso)
        for (src, key, cluster_id) in rows
    ]
    with _connect_db() as conn:
        conn.executemany(
            "INSERT INTO headline_registry "
            "(source, title_key, cluster_id, state, "
            " first_seen_at, last_seen_at) "
            "VALUES (?, ?, ?, 'seen', ?, ?) "
            "ON CONFLICT(source, title_key) DO UPDATE SET "
            "  cluster_id   = excluded.cluster_id, "
            "  last_seen_at = excluded.last_seen_at",
            payload,
        )


def update_registry_state(
    *,
    title_key: str,
    new_state: str | None = None,
    event_id: int | None = None,
    impact_level: str | None = None,
    analyzed_at: str | None = None,
    expired_at: str | None = None,
    last_skip_reason: str | None = None,
) -> None:
    """Forward-only state advance for every registry row matching ``title_key``.

    Issued as a single atomic UPDATE so concurrent callers cannot
    interleave a SELECT/UPDATE race that would let a lower-rank state
    clobber a higher-rank advance.  The forward-only invariant lives
    inline in a CASE expression: state advances only when the row's
    current state is one of the strictly-lower-rank lifecycle members.

    ``last_skip_reason`` is overwritten on every call (most-recent-skip
    semantics).  Other fields are written unconditionally when provided
    (matches the prior behavior; idempotency for transition-tied fields
    like ``expired_at`` is enforced by the wrappers in
    ``headline_registry.py``).
    """
    if not _db_ready or not title_key:
        return

    sets: list[str] = []
    params: list[object] = []

    if new_state and new_state in _REGISTRY_RANK:
        new_rank = _REGISTRY_RANK[new_state]
        lower_states = [
            s for s, r in _REGISTRY_RANK.items() if r < new_rank
        ]
        if lower_states:
            placeholders = ",".join("?" * len(lower_states))
            sets.append(
                f"state = CASE WHEN state IN ({placeholders}) "
                f"THEN ? ELSE state END"
            )
            params.extend(lower_states)
            params.append(new_state)
    if event_id is not None:
        sets.append("event_id = ?")
        params.append(int(event_id))
    if impact_level is not None:
        sets.append("impact_level = ?")
        params.append(impact_level)
    if analyzed_at is not None:
        sets.append("analyzed_at = ?")
        params.append(analyzed_at)
    if expired_at is not None:
        sets.append("expired_at = ?")
        params.append(expired_at)
    if last_skip_reason is not None:
        sets.append("last_skip_reason = ?")
        params.append(last_skip_reason)

    if not sets:
        return

    params.append(title_key)
    with _connect_db() as conn:
        conn.execute(
            f"UPDATE headline_registry SET {', '.join(sets)} "
            f"WHERE title_key = ?",
            params,
        )


def load_registry_state_counts() -> dict[str, int]:
    """Return ``{state: count}`` for every distinct ``state`` value."""
    if not _db_ready:
        return {}
    with _connect_db() as conn:
        rows = conn.execute(
            "SELECT state, COUNT(*) FROM headline_registry GROUP BY state"
        ).fetchall()
    return {state: int(count) for state, count in rows}


def load_registry_skip_reason_counts() -> dict[str, int]:
    """Return ``{last_skip_reason: count}`` for non-null reasons only."""
    if not _db_ready:
        return {}
    with _connect_db() as conn:
        rows = conn.execute(
            "SELECT last_skip_reason, COUNT(*) FROM headline_registry "
            "WHERE last_skip_reason IS NOT NULL "
            "GROUP BY last_skip_reason"
        ).fetchall()
    return {reason: int(count) for reason, count in rows}


def load_registry_last_analyzed_at() -> str | None:
    if not _db_ready:
        return None
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT MAX(analyzed_at) FROM headline_registry"
        ).fetchone()
    return row[0] if row and row[0] else None


def load_registry_expired_count_since(since_iso: str) -> int:
    if not _db_ready:
        return 0
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE state = 'expired_low_impact' AND expired_at >= ?",
            (since_iso,),
        ).fetchone()
    return int(row[0] or 0)


def load_registry_eligible_unanalyzed_count() -> int:
    """Count of registry rows still waiting to be analyzed.

    Mirrors the predicate used by ``load_eligible_unanalyzed_candidates``
    so the count and the candidate list always describe the same
    universe (state ∈ {seen, eligible} AND ``event_id IS NULL``).
    """
    if not _db_ready:
        return 0
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE state IN ('seen', 'eligible') AND event_id IS NULL"
        ).fetchone()
    return int(row[0] or 0)


def load_registry_analyzed_count_since(since_iso: str) -> int:
    """Count rows whose ``analyzed_at >= since_iso``.

    Counts every row that has been analyzed in the window, regardless
    of where the row currently sits in the lifecycle (``analyzed`` /
    ``market_checked`` / ``surfaced``) — analysis is a one-way stamp,
    so a row that has since advanced still counts toward "analyzed
    recently".  Excludes ``expired_low_impact`` because the operator
    reads that as a separate signal.
    """
    if not _db_ready:
        return 0
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE analyzed_at IS NOT NULL "
            "  AND analyzed_at >= ? "
            "  AND state IN ('analyzed', 'market_checked', 'surfaced')",
            (since_iso,),
        ).fetchone()
    return int(row[0] or 0)


def load_registry_surfaced_count_since(since_iso: str) -> int:
    """Count surfaced rows with ``last_seen_at >= since_iso``.

    The schema has no dedicated ``surfaced_at`` column; ``last_seen_at``
    is the most recent timestamp that touches the row, so a surfaced
    row whose ``last_seen_at`` falls inside the window is the closest
    truthful proxy for "surfaced recently".  Read-only diagnostic.
    """
    if not _db_ready:
        return 0
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE state = 'surfaced' AND last_seen_at >= ?",
            (since_iso,),
        ).fetchone()
    return int(row[0] or 0)


def load_registry_expired_low_impact_count() -> int:
    """Total count of rows currently in ``expired_low_impact`` state."""
    if not _db_ready:
        return 0
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM headline_registry "
            "WHERE state = 'expired_low_impact'"
        ).fetchone()
    return int(row[0] or 0)


def load_registry_last_surfaced_at() -> str | None:
    """Latest ``last_seen_at`` across rows currently in ``surfaced`` state.

    No dedicated ``surfaced_at`` column exists; ``last_seen_at`` is the
    truthful proxy (it is the most recent activity stamp on the row).
    Returns None when no surfaced rows exist.
    """
    if not _db_ready:
        return None
    with _connect_db() as conn:
        row = conn.execute(
            "SELECT MAX(last_seen_at) FROM headline_registry "
            "WHERE state = 'surfaced'"
        ).fetchone()
    return row[0] if row and row[0] else None


def load_registry_anchors_for_keys(
    title_keys: list[str],
) -> dict[str, dict[str, str | None]]:
    """Return ``{title_key: {"analyzed_at", "impact_level"}}`` for keys.

    Used by ``headline_registry.filter_expired_low_impact`` to bulk-load
    both registry anchors for a page of events in one round trip.  When
    a title_key has multiple analyzed rows (same headline ingested from
    multiple sources), the row with the latest ``analyzed_at`` wins and
    its paired ``impact_level`` is returned alongside.  ``analyzed_at``
    NULL rows are skipped — only analyzed entries can pin TTL.
    """
    if not _db_ready or not title_keys:
        return {}
    placeholders = ",".join("?" * len(title_keys))
    out: dict[str, dict[str, str | None]] = {}
    with _connect_db() as conn:
        rows = conn.execute(
            f"SELECT title_key, analyzed_at, impact_level "
            f"FROM headline_registry "
            f"WHERE title_key IN ({placeholders}) "
            f"  AND analyzed_at IS NOT NULL "
            f"ORDER BY analyzed_at DESC",
            title_keys,
        ).fetchall()
    for tk, at, il in rows:
        if tk in out:
            # ORDER BY analyzed_at DESC — first row wins per key.
            continue
        out[tk] = {"analyzed_at": at, "impact_level": il}
    return out


def load_eligible_unanalyzed_candidates(
    *, limit: int = 50,
) -> list[dict]:
    """Major headlines ingested but not yet analyzed.

    Joins ``headline_registry`` to ``news_clusters`` so we can rank by
    the cluster's ``source_count`` (number of publishers) — that's how
    the backfill route already prioritises clusters.  Returns the top
    ``limit`` rows in source_count-then-recency order.
    """
    if not _db_ready:
        return []
    with _connect_db() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT hr.cluster_id, "
            "       MIN(hr.first_seen_at) AS first_seen_at, "
            "       MAX(hr.last_seen_at)  AS last_seen_at, "
            "       hr.last_skip_reason, "
            "       hr.state, "
            "       nc.headline, "
            "       nc.payload_json "
            "FROM headline_registry hr "
            "JOIN news_clusters nc ON nc.id = hr.cluster_id "
            "WHERE hr.state IN ('seen', 'eligible') "
            "  AND hr.event_id IS NULL "
            "GROUP BY hr.cluster_id "
            "ORDER BY json_extract(nc.payload_json, '$.source_count') DESC, "
            "         MAX(hr.last_seen_at) DESC "
            "LIMIT ?",
            (int(limit),),
        ).fetchall()
    out: list[dict] = []
    for r in rows:
        try:
            payload = json.loads(r["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        out.append({
            "headline":         r["headline"] or "",
            "cluster_id":       r["cluster_id"],
            "source_count":     int(payload.get("source_count") or 0),
            "has_asset_terms":  bool(payload.get("has_asset_terms", False)),
            "first_seen_at":    r["first_seen_at"],
            "last_seen_at":     r["last_seen_at"],
            "last_skip_reason": r["last_skip_reason"],
            "state":            r["state"],
        })
    return out


def clear_news_cluster_store() -> None:
    """Drop everything from both cluster tables.  Test-only."""
    if not _db_ready:
        return
    with _connect_db() as conn:
        conn.execute("DELETE FROM news_headline_assignments")
        conn.execute("DELETE FROM news_clusters")
