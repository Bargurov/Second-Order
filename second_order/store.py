"""Append-only SQLite storage; replay timestamps remain explicitly simulated.

Schema 1 holds hypotheses and evaluations. Schema 2 adds market snapshots and freeze bindings. Schema 3 adds freeze
actions: the interface's approved freezes, each recorded in the same transaction as its hypothesis and binding. Schema 4
adds assessment actions: the interface's approved assessments, each recorded in the same transaction as its evaluation.
A new store is created at schema 4. Writes accept schema 2, 3 or 4; an interface freeze needs schema 3 or 4 and an
interface assessment schema 4. An older store is migrated only by the explicit `store migrate` command (or the
interface's explicit upgrade action), which only adds tables and proves every existing row unchanged. Reads accept
schema 1 to 4, open the file read-only and never migrate.

Every new source-bound prospective freeze applies freshness policy B (check_freshness): the baseline must classify,
for every leg, the last expected session before the publication date. Records frozen before the policy are read and
evaluated exactly as stored.
"""
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from .data import ny_date
from .registry import binding, resolve
from .schema import Hypothesis, utc

SCHEMA_VERSION = 4
SCHEMA_1_TABLES = frozenset({"hypotheses", "evaluations"})
MARKET_TABLES = ("market_snapshots", "market_series", "market_observations", "freeze_bindings")
SCHEMA_2_TABLES = SCHEMA_1_TABLES | {"store_meta", *MARKET_TABLES}
SCHEMA_3_TABLES = SCHEMA_2_TABLES | {"freeze_actions"}
SCHEMA_4_TABLES = SCHEMA_3_TABLES | {"assessment_actions"}
SCHEMAS = {1: SCHEMA_1_TABLES, 2: SCHEMA_2_TABLES, 3: SCHEMA_3_TABLES, 4: SCHEMA_4_TABLES}
WRITABLE = (SCHEMA_2_TABLES, SCHEMA_3_TABLES, SCHEMA_4_TABLES)
FRESHNESS_POLICY = "freshness-b-1"  # Decided 2026-10-11 for new source-bound prospective freezes.

SCHEMA_1_SQL = """
    CREATE TABLE IF NOT EXISTS hypotheses (
        id TEXT PRIMARY KEY,
        request_hash TEXT NOT NULL,
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS evaluations (
        id TEXT PRIMARY KEY,
        hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
"""

SCHEMA_2_SQL = """
    CREATE TABLE IF NOT EXISTS store_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS market_snapshots (
        id TEXT PRIMARY KEY,
        provider TEXT NOT NULL,
        vintage_date TEXT NOT NULL,
        retrieved_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS market_series (
        snapshot_id TEXT NOT NULL REFERENCES market_snapshots(id),
        series_id TEXT NOT NULL,
        metadata TEXT NOT NULL,
        metadata_gzip BLOB NOT NULL,
        observations_gzip BLOB NOT NULL,
        PRIMARY KEY (snapshot_id, series_id)
    );
    CREATE TABLE IF NOT EXISTS market_observations (
        snapshot_id TEXT NOT NULL,
        series_id TEXT NOT NULL,
        date TEXT NOT NULL,
        value REAL,
        raw_value TEXT,
        status TEXT NOT NULL,
        fred_realtime_start TEXT,
        fred_realtime_end TEXT,
        PRIMARY KEY (snapshot_id, series_id, date),
        FOREIGN KEY (snapshot_id, series_id) REFERENCES market_series(snapshot_id, series_id)
    );
    CREATE TABLE IF NOT EXISTS freeze_bindings (
        hypothesis_id TEXT PRIMARY KEY REFERENCES hypotheses(id),
        baseline_snapshot_id TEXT NOT NULL REFERENCES market_snapshots(id),
        bound_at TEXT NOT NULL
    );
"""

# One row per approved interface freeze: the approval's identity (its preview SHA-256), the hypothesis it froze and
# what the approval bound (origin, review, baseline, policy). Written in the hypothesis's own transaction.
SCHEMA_3_SQL = """
    CREATE TABLE IF NOT EXISTS freeze_actions (
        action_id TEXT PRIMARY KEY,
        hypothesis_id TEXT NOT NULL UNIQUE REFERENCES hypotheses(id),
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
"""

# One row per approved interface assessment: the approval's identity (its preview SHA-256), the hypothesis, the one
# evaluation it recorded and what the approval bound (outcome snapshot, rules, cutoff, readiness). Written in the
# evaluation's own transaction.
SCHEMA_4_SQL = """
    CREATE TABLE IF NOT EXISTS assessment_actions (
        action_id TEXT PRIMARY KEY,
        hypothesis_id TEXT NOT NULL REFERENCES hypotheses(id),
        evaluation_id TEXT NOT NULL UNIQUE REFERENCES evaluations(id),
        recorded_at TEXT NOT NULL,
        payload TEXT NOT NULL
    );
"""


def append_only_triggers(tables) -> str:
    return "".join(
        f"CREATE TRIGGER IF NOT EXISTS {table}_no_{action} BEFORE {action.upper()} ON {table} "
        f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
        for table in tables for action in ("update", "delete"))


def canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(payload: dict) -> str:
    return hashlib.sha256(canonical(payload).encode()).hexdigest()


def user_tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def store_schema(connection: sqlite3.Connection) -> int | None:
    """The schema a store's tables match (1 to 4), or None for an empty or foreign database."""
    tables = user_tables(connection)
    return next((version for version, expected in SCHEMAS.items() if tables == expected), None)


def open_store(path: str = ":memory:") -> sqlite3.Connection:
    """Write access. A new store is created at schema 4; a schema-1 store must be migrated explicitly."""
    connection = sqlite3.connect(path)
    tables = user_tables(connection)
    if tables and tables not in WRITABLE:
        connection.close()
        if tables == SCHEMA_1_TABLES:
            raise ValueError("This v2 store uses schema 1; run `python -m second_order store migrate --db <path>`")
        raise ValueError("Use a new v2 database; a foreign/v1 schema was found")
    if not tables:
        connection.executescript(
            "BEGIN;" + SCHEMA_1_SQL + SCHEMA_2_SQL + SCHEMA_3_SQL + SCHEMA_4_SQL
            + append_only_triggers(sorted(SCHEMA_4_TABLES))
            + f"INSERT INTO store_meta VALUES ('schema_version', '{SCHEMA_VERSION}'); COMMIT;")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def stored_rows(connection: sqlite3.Connection, tables=SCHEMA_1_TABLES) -> str:
    """Digest of every row of the named tables, to prove a migration left them untouched."""
    rows = [list(connection.execute(f"SELECT * FROM {table} ORDER BY rowid")) for table in sorted(tables)]
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def migrate_store(path: str, now: datetime | None = None) -> dict:
    """Explicit migration to schema 4: one transaction that only adds tables (and records itself), with every
    existing row proven unchanged. Schema 1 gains the tables of schemas 2 to 4, schema 2 gains freeze_actions and
    assessment_actions, and schema 3 gains assessment_actions."""
    if not Path(path).is_file():
        raise ValueError("No v2 database at this path")
    connection = sqlite3.connect(path)
    try:
        version = store_schema(connection)
        if version == SCHEMA_VERSION:
            return {"schema_version": SCHEMA_VERSION, "migrated": False}
        if version not in (1, 2, 3):
            raise ValueError("Not a schema-1, 2 or 3 v2 database; refusing to migrate")
        existing = SCHEMAS[version]
        compared = existing - {"store_meta"}  # store_meta gains the migration's own rows; its earlier rows must stay.
        before = stored_rows(connection, compared)
        meta_before = list(connection.execute("SELECT key, value FROM store_meta")) if "store_meta" in existing else []
        counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in sorted(existing)}
        migrated_at = utc(now or datetime.now(timezone.utc)).isoformat()
        if version == 1:
            script = (SCHEMA_2_SQL + SCHEMA_3_SQL + SCHEMA_4_SQL
                      + append_only_triggers(sorted(SCHEMA_4_TABLES - SCHEMA_1_TABLES))
                      + f"INSERT INTO store_meta VALUES ('schema_version', '{SCHEMA_VERSION}');"
                      + "INSERT INTO store_meta VALUES ('migrated_from_schema', '1');"
                      + f"INSERT INTO store_meta VALUES ('migrated_at', '{migrated_at}');")
        else:  # store_meta is append-only: its schema_version row keeps the schema the store was created at.
            added = sorted(SCHEMA_4_TABLES - existing)
            script = ((SCHEMA_3_SQL if version == 2 else "") + SCHEMA_4_SQL + append_only_triggers(added)
                      + f"INSERT INTO store_meta VALUES ('schema_4_migrated_from_schema', '{version}');"
                      + f"INSERT INTO store_meta VALUES ('schema_4_migrated_at', '{migrated_at}');")
        connection.executescript("BEGIN;" + script + "COMMIT;")
        meta_after = set(connection.execute("SELECT key, value FROM store_meta"))
        if stored_rows(connection, compared) != before or not set(meta_before) <= meta_after:
            raise RuntimeError("Migration changed existing rows")
        return {"schema_version": SCHEMA_VERSION, "migrated": True, "migrated_from_schema": version,
                "preserved_rows": counts}
    finally:
        connection.close()


def connect_read_only(path: str) -> sqlite3.Connection:
    """Read access to a store of schema 1 to 4; never creates, migrates or writes."""
    database = Path(path)
    if not database.is_file():
        raise ValueError("No v2 database at this path")
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    if store_schema(connection) is None:
        connection.close()
        raise ValueError("Not a v2 database; refusing to read a foreign schema")
    return connection


def bound_provider(hypothesis: Hypothesis) -> str | None:
    """The one provider every leg is bound to, or None for fixture observables; refuses any mix."""
    bindings = [binding(leg.observable_id) for leg in hypothesis.legs]
    if any(bindings) and not all(bindings):
        raise ValueError("A hypothesis cannot mix source-bound and fixture observables")
    providers = {provider for provider, _ in filter(None, bindings)}
    if len(providers) > 1:
        raise ValueError(f"A hypothesis cannot mix market data providers ({', '.join(sorted(providers))}): one "
                         "baseline snapshot is bound to every leg")
    return providers.pop() if providers else None


def bound_series(hypothesis: Hypothesis) -> set[str]:
    """Provider series every leg needs; refuses a mix of source-bound and fixture observables, or of providers."""
    bound_provider(hypothesis)
    return {source.split(":", 1)[1] for source in (resolve(leg.observable_id).source for leg in hypothesis.legs)
            if source}


def check_baseline(connection: sqlite3.Connection, snapshot_id: str, series: set[str], frozen_at: datetime,
                   provider: str) -> None:
    row = connection.execute("SELECT payload FROM market_snapshots WHERE id=?", (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError("The baseline must be an existing market snapshot")
    snapshot = json.loads(row[0])
    if snapshot["provider"] != provider:
        raise ValueError(f"The baseline snapshot comes from {snapshot['provider']}, but the legs are bound to "
                         f"{provider}; a leg is never measured on another provider's data")
    if not series <= set(snapshot["series"]):
        raise ValueError("The baseline snapshot does not contain every series the legs need")
    if datetime.fromisoformat(snapshot["retrieved_at"]) > frozen_at:
        raise ValueError("The baseline snapshot must have been retrieved before the freeze")


def last_session_before(day: date) -> date:
    """The last expected bond-market session (SIFMA, with the versioned exceptions) dated before ``day``."""
    from .market_calendar import expected_sessions  # Needs the calendar library, as the imports do.
    sessions = expected_sessions(day - timedelta(days=21), day - timedelta(days=1))
    if not sessions:
        raise ValueError(f"No expected session in the three weeks before {day.isoformat()}")
    return max(sessions)


def check_freshness(connection: sqlite3.Connection, snapshot_id: str, hypothesis: Hypothesis) -> dict:
    """Freshness policy B: for every leg, the baseline must classify the last expected session before the
    publication date. Coverage is the snapshot's recorded classification range for that series (from its
    classification boundary to its last classified date), never its acquisition or retrieval time. A session the
    source states without a value is covered: it stays missing, nothing is filled, and the readiness check still
    applies. Returns what was checked; raises ValueError naming what is missing."""
    from .snapshots import load_snapshot  # snapshots imports this module.
    from .market_calendar import calendar_identity, load_exceptions
    snapshot = load_snapshot(connection, snapshot_id)
    published = ny_date(hypothesis.event.published_at)
    required = last_session_before(published)
    checked = {}
    for leg in hypothesis.legs:
        _, series_id = binding(leg.observable_id)
        coverage = snapshot.coverage(series_id, required)  # The one coverage test; research_readiness reads it too.
        start, through = coverage["classified_from"], coverage["classified_through"]
        if not coverage["covered"]:
            covered = f"from {start.isoformat()} through {through.isoformat()}" if start else "nowhere"
            raise ValueError(
                f"Freshness policy B: baseline {snapshot_id[:12]} classifies {series_id} {covered}, but the last "
                f"expected session before the publication date {published.isoformat()} is {required.isoformat()}. "
                "Choose or import a baseline that covers that session; freezing never downloads anything.")
        checked[series_id] = {"observable_id": leg.observable_id, "classified_from": start.isoformat(),
                              "classified_through": through.isoformat(), "required_session_status": coverage["status"]}
    return {"policy": FRESHNESS_POLICY, "published_date": published.isoformat(),
            "required_session": required.isoformat(), "calendar": calendar_identity(load_exceptions()),
            "series": checked}


def check_history(connection: sqlite3.Connection, snapshot_id: str, hypothesis: Hypothesis) -> None:
    """Refuse a baseline that cannot give every leg the reference windows its scoring requires."""
    from .snapshots import load_snapshot, snapshot_readiness  # snapshots imports this module.
    report = snapshot_readiness(load_snapshot(connection, snapshot_id), before=ny_date(hypothesis.event.published_at))
    for leg in hypothesis.legs:
        series_id = resolve(leg.observable_id).source.split(":", 1)[1]
        horizon = report["series"][series_id]["horizons"][str(leg.horizon)]
        if not horizon["scorable"]:
            raise ValueError(f"Baseline history is insufficient for {leg.observable_id} at horizon {leg.horizon}: "
                             f"{horizon['reference_windows']} usable reference windows before the publication "
                             f"date; rules {report['rules_version']} require {horizon['required_reference_windows']}")


def request_identity(hypothesis: Hypothesis) -> str:
    """Same event, engine, class and usage: the same request, whatever its freeze time."""
    payload = hypothesis.model_dump(mode="json")
    return digest({"event": payload["event"], "engine": payload["engine"],
                   "evidence_class": hypothesis.evidence_class, "usage": hypothesis.usage})


def freeze(connection: sqlite3.Connection, hypothesis: Hypothesis, recorded_at: datetime,
           baseline_snapshot_id: str | None = None) -> str:
    """Append a hypothesis; source-bound legs also bind an existing baseline snapshot, atomically."""
    identity, rows = checked_freeze(connection, hypothesis, recorded_at, baseline_snapshot_id)
    if rows:
        with connection:
            for statement, values in rows:
                connection.execute(statement, values)
    return identity


def checked_freeze(connection: sqlite3.Connection, hypothesis: Hypothesis, recorded_at: datetime,
                   baseline_snapshot_id: str | None) -> tuple[str, list]:
    """Every freeze check, then the rows a new freeze inserts (none when this exact hypothesis is already stored).
    Writes nothing; the caller inserts the rows in one transaction."""
    recorded_at = utc(recorded_at)
    if hypothesis.frozen_at > recorded_at:
        raise ValueError("Freeze time cannot be in the future")
    series = bound_series(hypothesis)
    if series and hypothesis.evidence_class == "replay":
        raise ValueError("Source-bound replays are not supported: a replay scores from the last date before "
                         "publication, which a baseline snapshot does not guarantee to contain")
    if series and baseline_snapshot_id is None:
        raise ValueError("Source-bound legs need a baseline snapshot bound at freeze")
    if baseline_snapshot_id is not None and not series:
        raise ValueError("A baseline snapshot applies only to source-bound legs")
    payload = hypothesis.model_dump(mode="json")
    identity = digest(payload)
    if connection.execute("SELECT 1 FROM hypotheses WHERE id=?", (identity,)).fetchone():
        if series:
            bound = connection.execute("SELECT baseline_snapshot_id FROM freeze_bindings WHERE hypothesis_id=?",
                                       (identity,)).fetchone()
            if bound != (baseline_snapshot_id,):
                raise ValueError("This hypothesis is already frozen with a different baseline")
        return identity, []
    if hypothesis.evidence_class == "prospective" and abs((recorded_at - hypothesis.frozen_at).total_seconds()) > 60:
        raise ValueError("Prospective freeze must be recorded now, not backdated")
    if hypothesis.supersedes:
        previous = connection.execute("SELECT payload FROM hypotheses WHERE id=?", (hypothesis.supersedes,)).fetchone()
        if previous is None:
            raise ValueError("Superseded hypothesis does not exist")
        old = Hypothesis.model_validate_json(previous[0])
        if old.event != hypothesis.event or hypothesis.frozen_at <= old.frozen_at:
            raise ValueError("A new version must keep the event and have a later freeze")
    if series:
        check_baseline(connection, baseline_snapshot_id, series, hypothesis.frozen_at, bound_provider(hypothesis))
        check_freshness(connection, baseline_snapshot_id, hypothesis)  # Policy B, for every new freeze.
        check_history(connection, baseline_snapshot_id, hypothesis)
    rows = [("INSERT INTO hypotheses VALUES (?,?,?,?)",
             (identity, request_identity(hypothesis), recorded_at.isoformat(), canonical(payload)))]
    if series:
        rows.append(("INSERT INTO freeze_bindings VALUES (?,?,?)",
                     (identity, baseline_snapshot_id, recorded_at.isoformat())))
    return identity, rows


def freeze_with_action(connection: sqlite3.Connection, hypothesis: Hypothesis, recorded_at: datetime,
                       baseline_snapshot_id: str, action_id: str, action: dict) -> dict:
    """The interface's freeze: hypothesis, baseline binding and action record in one write transaction.

    BEGIN IMMEDIATE serializes writers across connections and processes. The approval's identity (action_id) is
    looked up first: repeating an approval returns the freeze it already made, never a second one or a new time.
    A different approval for the same request (same event, engine, class and usage) is refused, so a frozen record
    is never restamped or duplicated. Every freeze check, freshness policy B included, runs inside the
    transaction; a refusal writes nothing."""
    if store_schema(connection) not in (3, 4):
        raise ValueError("This store has no freeze-action table: upgrade it with the explicit store upgrade action "
                         "(or `python -m second_order store migrate`) before freezing from the interface")
    connection.execute("BEGIN IMMEDIATE")
    try:
        done = connection.execute("SELECT hypothesis_id, recorded_at FROM freeze_actions WHERE action_id=?",
                                  (action_id,)).fetchone()
        if done is not None:
            connection.rollback()
            return {"created": False, "hypothesis_id": done[0], "recorded_at": done[1]}
        same = connection.execute("SELECT id, recorded_at FROM hypotheses WHERE request_hash=?",
                                  (request_identity(hypothesis),)).fetchone()
        if same is not None:
            raise ValueError(f"This request (the same event, engine, evidence class and usage) is already frozen as "
                             f"{same[0]} at {same[1]}; a frozen record is never restamped or frozen twice")
        identity, rows = checked_freeze(connection, hypothesis, recorded_at, baseline_snapshot_id)
        if not rows:
            raise ValueError(f"This exact hypothesis is already frozen as {identity}")
        for statement, values in rows:
            connection.execute(statement, values)
        connection.execute("INSERT INTO freeze_actions VALUES (?,?,?,?)",
                           (action_id, identity, utc(recorded_at).isoformat(),
                            canonical({**action, "hypothesis_id": identity})))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"created": True, "hypothesis_id": identity, "recorded_at": utc(recorded_at).isoformat()}


def record_assessment(connection: sqlite3.Connection, hypothesis_id: str, result: dict, recorded_at: datetime,
                      action_id: str, action: dict, prior: list[str]) -> dict:
    """The interface's assessment: one evaluation and its action record, in one write transaction.

    BEGIN IMMEDIATE serializes writers across connections and processes. The approval's identity (action_id) is looked
    up first: repeating an approval returns the evaluation it already recorded, never a second one. The approval bound
    the hypothesis's recorded evaluations (prior); if they changed since, nothing is written, so a further assessment
    always needs a decision made knowing the earlier ones. An evaluation identical to a recorded one is never recorded
    twice. Earlier evaluations are never changed: a new assessment only appends."""
    if store_schema(connection) != 4:
        raise ValueError("This store has no assessment-action table: upgrade it to schema 4 with the explicit store "
                         "upgrade action (or `python -m second_order store migrate`) before assessing from the "
                         "interface")
    if result.get("hypothesis_id") != hypothesis_id:
        raise ValueError("Evaluation does not belong to this hypothesis")
    recorded_at = utc(recorded_at)
    if datetime.fromisoformat(result["as_of"]) > recorded_at:
        raise ValueError("Cannot persist a future evaluation")
    payload = {"hypothesis_id": hypothesis_id, **result}
    identity = digest(payload)
    connection.execute("BEGIN IMMEDIATE")
    try:
        done = connection.execute("SELECT evaluation_id, recorded_at FROM assessment_actions WHERE action_id=?",
                                  (action_id,)).fetchone()
        if done is not None:
            connection.rollback()
            return {"created": False, "evaluation_id": done[0], "recorded_at": done[1]}
        current = sorted(row[0] for row in connection.execute("SELECT id FROM evaluations WHERE hypothesis_id=?",
                                                              (hypothesis_id,)))
        if current != sorted(prior):
            raise ValueError("The hypothesis's recorded assessments changed since the preview; review them before "
                             "deciding on another")
        if identity in current:
            raise ValueError(f"This exact assessment is already recorded as {identity}")
        connection.execute("INSERT INTO evaluations VALUES (?,?,?,?)",
                           (identity, hypothesis_id, recorded_at.isoformat(), canonical(payload)))
        connection.execute("INSERT INTO assessment_actions VALUES (?,?,?,?,?)",
                           (action_id, hypothesis_id, identity, recorded_at.isoformat(),
                            canonical({**action, "evaluation_id": identity})))
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"created": True, "evaluation_id": identity, "recorded_at": recorded_at.isoformat()}


def save_evaluation(connection: sqlite3.Connection, hypothesis_id: str, result: dict,
                    recorded_at: datetime) -> str:
    if result.get("hypothesis_id") != hypothesis_id:
        raise ValueError("Evaluation does not belong to this hypothesis")
    if datetime.fromisoformat(result["as_of"]) > utc(recorded_at):
        raise ValueError("Cannot persist a future evaluation")
    payload = {"hypothesis_id": hypothesis_id, **result}
    identity = digest(payload)
    with connection:
        connection.execute("INSERT OR IGNORE INTO evaluations VALUES (?,?,?,?)",
                           (identity, hypothesis_id, utc(recorded_at).isoformat(), canonical(payload)))
    return identity


def read_evaluations(path: str) -> list[dict]:
    """Read stored evaluations without creating, migrating or writing the database."""
    connection = connect_read_only(path)
    try:
        return [json.loads(payload) for (payload,) in
                connection.execute("SELECT payload FROM evaluations ORDER BY recorded_at, id")]
    finally:
        connection.close()
