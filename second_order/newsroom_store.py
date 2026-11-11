"""The newsroom store: shared editorial records for the news, apart from every private record (newsroom-4).

One SQLite file, data/newsroom/newsroom.db, beside (never inside) the accounts store and the research store. It holds
what the operator's explicit actions decide about the news that every user reads: which reports cover one development
(a story), which stories belong to an ongoing subject (a topic, with its timeline), which are marked as major and until
when, and each story's shared brief, prepared and published in versions. It holds no account, credit, source, analysis,
hypothesis or result, and nothing in it belongs to a user: a user's deeper analysis is their own source and analysis,
recorded where those always are.

Every table is append-only (triggers refuse UPDATE and DELETE): a membership, link or priority changes by a later row,
a brief by a new version, a publication by a later publication, so every relationship can be traced to who decided it,
when, why and by which rule. The current state is the fold of those rows (``state``). Every operator write carries an
idempotency key bound to its kind and canonical payload: repeating it returns the first result and records nothing; the
same key with another payload is refused. Reads only read: a missing store is an empty newsroom, never created by a
read. The first explicit write creates it.

newsroom-2 adds two append-only tables: ``brief_reviews`` (an editor's explicit statement that they read a brief
version: nothing else says a person reviewed a brief) and ``material_assessments`` (a recorded judgement that a story's
material, identified by its SHA-256, cannot support a useful brief, or later that it can). A newsroom-1 store is read as
it is (no reviews, no assessments); writing to it is refused until ``python -m second_order news upgrade`` adds the two
tables in one transaction, keeping every row.

newsroom-3 adds two more append-only tables for economic relevance (news_relevance): ``relevance_annotations`` (each
annotation of a story's material, by the AI model in this application, an AI assistant outside it or a SYNTHETIC test,
bound to the material's SHA-256 and the prompt, schema and scope versions, with its evidence check; or a failed
attempt, recorded as such so a failure never reads as a judgement) and ``relevance_reviews`` (an editor's judgement of a
story's relevance with a reason, or the clearing of one). A newsroom-1 or newsroom-2 store is read as it is; writing to
it is refused until ``news upgrade`` adds what it lacks in one transaction.

newsroom-4 adds ``match_decisions`` (news_matching): an editor's, or a declared AI assistant's, decision that two stories
report the same development (then merged), separate developments of one ongoing subject (then linked to a topic), or
different developments, with the reason, so a decided pair is not suggested again.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from .accounts import AccountsRefused
from .store import canonical

SCHEMA_VERSION = "newsroom-4"
READABLE = ("newsroom-1", "newsroom-2", "newsroom-3", "newsroom-4")  # Older stores are read as they are; only an upgraded one is
# written.
ROOT = Path(__file__).resolve().parent.parent
NEWSROOM_DIR = ROOT / "data" / "newsroom"  # Runtime records; data/ is ignored by git.
STORE_NAME = "newsroom.db"
TABLES = ("stories", "story_members", "story_titles", "story_merges", "topics", "topic_links", "priorities", "briefs",
          "brief_publications", "operations", "brief_reviews", "material_assessments", "relevance_annotations",
          "relevance_reviews", "match_decisions")
ADDED_IN_2 = ("brief_reviews", "material_assessments")
ADDED_IN_3 = ("relevance_annotations", "relevance_reviews")
ADDED_IN_4 = ("match_decisions",)
TABLES_2 = """
CREATE TABLE brief_reviews (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            story_id TEXT NOT NULL REFERENCES stories (story_id), version INTEGER NOT NULL,
                            reviewer TEXT NOT NULL, at TEXT NOT NULL, note TEXT NOT NULL,
                            FOREIGN KEY (story_id, version) REFERENCES briefs (story_id, version));
CREATE TABLE material_assessments (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                   story_id TEXT NOT NULL REFERENCES stories (story_id),
                                   material_sha256 TEXT NOT NULL,
                                   verdict TEXT NOT NULL CHECK (verdict IN ('insufficient', 'sufficient')),
                                   reason TEXT NOT NULL, method TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
"""
TABLES_3 = """
CREATE TABLE relevance_annotations (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                    story_id TEXT NOT NULL REFERENCES stories (story_id),
                                    material_sha256 TEXT NOT NULL,
                                    method TEXT NOT NULL CHECK (method IN ('model', 'assisted', 'synthetic')),
                                    outcome TEXT NOT NULL CHECK (outcome IN ('annotated', 'failed')),
                                    annotation TEXT, evidence TEXT NOT NULL, versions TEXT NOT NULL,
                                    preparation TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL,
                                    CHECK ((outcome = 'annotated') = (annotation IS NOT NULL)));
CREATE TABLE relevance_reviews (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                story_id TEXT NOT NULL REFERENCES stories (story_id),
                                material_sha256 TEXT NOT NULL,
                                verdict TEXT NOT NULL CHECK (verdict IN ('relevant', 'outside_scope',
                                                                         'insufficient_information', 'cleared')),
                                reason TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL);
"""
TABLES_4 = """
CREATE TABLE match_decisions (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                              story_a TEXT NOT NULL REFERENCES stories (story_id),
                              story_b TEXT NOT NULL REFERENCES stories (story_id),
                              decision TEXT NOT NULL CHECK (decision IN ('same', 'related', 'different')),
                              method TEXT NOT NULL CHECK (method IN ('editor', 'assisted', 'synthetic')),
                              topic_id TEXT, evidence TEXT NOT NULL, preparation TEXT NOT NULL,
                              reason TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL,
                              CHECK (story_a < story_b), CHECK ((decision = 'related') = (topic_id IS NOT NULL)));
"""


def _triggers(tables: tuple[str, ...]) -> str:
    return "".join(f"CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
                   for table in tables for action in ("update", "delete"))


SCHEMA = """
CREATE TABLE newsroom_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE stories (story_id TEXT PRIMARY KEY, founder_entry_id TEXT NOT NULL, basis TEXT NOT NULL,
                      actor TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE story_members (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                            story_id TEXT NOT NULL REFERENCES stories (story_id), entry_id TEXT NOT NULL,
                            action TEXT NOT NULL CHECK (action IN ('add', 'remove')), basis TEXT NOT NULL,
                            actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE story_titles (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                           story_id TEXT NOT NULL REFERENCES stories (story_id), title TEXT NOT NULL,
                           actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE story_merges (story_id TEXT PRIMARY KEY REFERENCES stories (story_id),
                           into_story_id TEXT NOT NULL REFERENCES stories (story_id),
                           actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL,
                           CHECK (story_id <> into_story_id));
CREATE TABLE topics (topic_id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL, actor TEXT NOT NULL,
                     at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE topic_links (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                          topic_id TEXT NOT NULL REFERENCES topics (topic_id),
                          story_id TEXT NOT NULL REFERENCES stories (story_id),
                          action TEXT NOT NULL CHECK (action IN ('link', 'unlink')), label TEXT NOT NULL,
                          actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL);
CREATE TABLE priorities (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                         target_kind TEXT NOT NULL CHECK (target_kind IN ('story', 'topic')), target_id TEXT NOT NULL,
                         level TEXT NOT NULL CHECK (level IN ('major', 'none')), until TEXT,
                         actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL,
                         CHECK ((level = 'major') = (until IS NOT NULL)));
CREATE TABLE briefs (story_id TEXT NOT NULL REFERENCES stories (story_id), version INTEGER NOT NULL CHECK (version >= 1),
                     based_on INTEGER, method TEXT NOT NULL, content TEXT NOT NULL, content_sha256 TEXT NOT NULL,
                     material TEXT NOT NULL, material_sha256 TEXT NOT NULL, preparation TEXT NOT NULL,
                     guard TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL,
                     PRIMARY KEY (story_id, version));
CREATE TABLE brief_publications (event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                                 story_id TEXT NOT NULL REFERENCES stories (story_id), version INTEGER,
                                 actor TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL,
                                 FOREIGN KEY (story_id, version) REFERENCES briefs (story_id, version));
CREATE TABLE operations (idempotency_key TEXT PRIMARY KEY, kind TEXT NOT NULL, actor TEXT NOT NULL,
                         payload_sha256 TEXT NOT NULL, result TEXT NOT NULL, at TEXT NOT NULL);
""" + TABLES_2 + TABLES_3 + TABLES_4 + _triggers(TABLES)
UPGRADES = {"newsroom-1": TABLES_2 + TABLES_3 + TABLES_4 + _triggers(ADDED_IN_2 + ADDED_IN_3 + ADDED_IN_4),
            "newsroom-2": TABLES_3 + TABLES_4 + _triggers(ADDED_IN_3 + ADDED_IN_4),
            "newsroom-3": TABLES_4 + _triggers(ADDED_IN_4)}
ADDED_SINCE = {"newsroom-1": ADDED_IN_2 + ADDED_IN_3 + ADDED_IN_4, "newsroom-2": ADDED_IN_3 + ADDED_IN_4,
               "newsroom-3": ADDED_IN_4}


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


def sha256_of(value: object) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


@dataclass(frozen=True)
class Newsroom:
    """The newsroom store at one path. Holds no connection: each call opens, uses and closes its own."""
    path: Path

    def exists(self) -> bool:
        return self.path.is_file()

    def version(self, connection: sqlite3.Connection) -> str:
        row = connection.execute("SELECT value FROM newsroom_meta WHERE key = 'schema'").fetchone()
        if row is None or row["value"] not in READABLE:
            raise AccountsRefused(503, "newsroom_unreadable", f"{self.path} is not a newsroom store this server reads.")
        return row["value"]

    def _checked(self, connection: sqlite3.Connection) -> None:
        if self.version(connection) != SCHEMA_VERSION:
            raise AccountsRefused(409, "newsroom_needs_upgrade", (
                f"{self.path} is a {self.version(connection)} store; nothing was written. Back it up (news backup) "
                "and run `python -m second_order news upgrade`, which keeps every row."))

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        connection = _connect(self.path)
        try:
            self.version(connection)
            yield connection
        finally:
            connection.close()

    def upgrade(self) -> dict:
        """Bring an older store to newsroom-4 in one transaction (the tables it lacks; every row kept). Explicit
        only."""
        if not self.exists():
            raise AccountsRefused(404, "not_found", f"No newsroom store exists at {self.path}.")
        connection = _connect(self.path)
        try:
            found = self.version(connection)
            if found == SCHEMA_VERSION:
                return {"store": str(self.path), "from": found, "to": SCHEMA_VERSION, "upgraded": False}
            counts = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                      for table in TABLES if table not in ADDED_SINCE[found]}
            connection.executescript("BEGIN IMMEDIATE;" + UPGRADES[found] +
                                     f"UPDATE newsroom_meta SET value = '{SCHEMA_VERSION}' WHERE key = 'schema';"
                                     " COMMIT;")
            after = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in counts}
            if after != counts:
                raise AccountsRefused(500, "upgrade_mismatch", "The rows changed during the upgrade.")
            return {"store": str(self.path), "from": found, "to": SCHEMA_VERSION, "upgraded": True, "rows": counts}
        finally:
            connection.close()

    def create(self) -> None:
        """Create the empty store; only an explicit operator write calls this, never a read."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript("BEGIN;" + SCHEMA +
                                     f"INSERT INTO newsroom_meta VALUES ('schema', '{SCHEMA_VERSION}'); COMMIT;")
        finally:
            connection.close()

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        """One serialized write transaction (BEGIN IMMEDIATE); the first explicit write creates the store."""
        if not self.exists():
            self.create()
        connection = _connect(self.path)
        try:
            self._checked(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()


def open_at(folder: Path) -> Newsroom:
    return Newsroom(folder / STORE_NAME)


# ---------------------------------------------------------------- idempotent operations

def operation(connection: sqlite3.Connection, key: object, kind: str, actor: str, payload: object) -> dict | None:
    """The first result of this idempotency key, or None when the key is new. Another payload or kind under the key
    is refused, and so is a malformed key."""
    if not isinstance(key, str) or not 8 <= len(key) <= 80 or not all(char.isalnum() or char in "-_" for char in key):
        raise AccountsRefused(422, "invalid_request", "idempotency_key must be 8 to 80 letters, digits, - or _.")
    row = connection.execute("SELECT * FROM operations WHERE idempotency_key = ?", (key,)).fetchone()
    if row is None:
        return None
    if (row["kind"], row["actor"], row["payload_sha256"]) != (kind, actor, sha256_of(payload)):
        raise AccountsRefused(409, "idempotency_conflict", "This idempotency key was already used for another action. "
                                                           "Nothing was changed.")
    return json.loads(row["result"])


def record_operation(connection: sqlite3.Connection, key: str, kind: str, actor: str, payload: object, result: dict,
                     at: str) -> None:
    connection.execute("INSERT INTO operations VALUES (?, ?, ?, ?, ?, ?)",
                       (key, kind, actor, sha256_of(payload), json.dumps(result, sort_keys=True), at))


# ---------------------------------------------------------------- the current state (the fold of every row)

def _rows(connection: sqlite3.Connection, table: str, order: str) -> list[dict]:
    return [dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def state(newsroom: Newsroom) -> dict:
    """Everything the newsroom has decided, as of its last row. An absent store is the empty newsroom."""
    empty = {"exists": False, "stories": {}, "entry_story": {}, "topics": {}, "links": {}, "priorities": {},
             "briefs": {}, "publications": {}, "merged_into": {}, "reviews": {}, "assessments": {}, "relevance": {},
             "relevance_reviews": {}, "match_decisions": [], "schema": None}
    if not newsroom.exists():
        return empty
    with newsroom.reading() as connection:
        schema = newsroom.version(connection)
        reviews = _rows(connection, "brief_reviews", "event_id") if schema != "newsroom-1" else []
        assessments = _rows(connection, "material_assessments", "event_id") if schema != "newsroom-1" else []
        third = schema not in ("newsroom-1", "newsroom-2")
        annotations = _rows(connection, "relevance_annotations", "event_id") if third else []
        relevance_reviews = _rows(connection, "relevance_reviews", "event_id") if third else []
        matches = _rows(connection, "match_decisions", "event_id") if schema == "newsroom-4" else []
        stories = _rows(connection, "stories", "at, story_id")
        members = _rows(connection, "story_members", "event_id")
        titles = _rows(connection, "story_titles", "event_id")
        merges = _rows(connection, "story_merges", "at, story_id")
        topics = _rows(connection, "topics", "at, topic_id")
        links = _rows(connection, "topic_links", "event_id")
        priorities = _rows(connection, "priorities", "event_id")
        briefs = _rows(connection, "briefs", "story_id, version")
        publications = _rows(connection, "brief_publications", "event_id")
    folded = {**empty, "exists": True, "schema": schema}
    for row in stories:
        folded["stories"][row["story_id"]] = {**row, "basis": json.loads(row["basis"]), "title": None,
                                              "title_event": None, "members": {}, "history": []}
    for row in members:
        story = folded["stories"][row["story_id"]]
        event = {**row, "basis": json.loads(row["basis"])}
        story["history"].append(event)
        if row["action"] == "add":
            story["members"][row["entry_id"]] = event
            folded["entry_story"][row["entry_id"]] = row["story_id"]
        else:
            story["members"].pop(row["entry_id"], None)
            if folded["entry_story"].get(row["entry_id"]) == row["story_id"]:
                del folded["entry_story"][row["entry_id"]]
    for row in titles:
        folded["stories"][row["story_id"]].update(title=row["title"], title_event=row)
    for row in merges:
        folded["merged_into"][row["story_id"]] = row
    for row in topics:
        folded["topics"][row["topic_id"]] = row
    for row in links:
        key = (row["topic_id"], row["story_id"])
        if row["action"] == "link":
            folded["links"][key] = row
        else:
            folded["links"].pop(key, None)
    for row in priorities:
        folded["priorities"][(row["target_kind"], row["target_id"])] = row
    for row in briefs:
        folded["briefs"].setdefault(row["story_id"], []).append(
            {**row, **{field: json.loads(row[field]) for field in ("content", "material", "preparation", "guard")}})
    for row in publications:
        folded["publications"].setdefault(row["story_id"], []).append(row)
    for row in reviews:
        folded["reviews"].setdefault((row["story_id"], row["version"]), []).append(row)
    for row in assessments:
        folded["assessments"].setdefault(row["story_id"], []).append(row)
    for row in annotations:
        folded["relevance"].setdefault(row["story_id"], []).append(
            {**row, **{field: json.loads(row[field]) if row[field] is not None else None
                       for field in ("annotation", "evidence", "versions", "preparation")}})
    for row in relevance_reviews:
        folded["relevance_reviews"].setdefault(row["story_id"], []).append(row)
    folded["match_decisions"] = [{**row, "evidence": json.loads(row["evidence"]),
                                  "preparation": json.loads(row["preparation"])} for row in matches]
    return folded


def assessment(folded: dict, story_id: str, material_sha256: str) -> dict | None:
    """The latest recorded judgement of this exact material for this story, or None."""
    rows = [row for row in folded["assessments"].get(story_id, []) if row["material_sha256"] == material_sha256]
    return rows[-1] if rows else None


def resolve_story(folded: dict, story_id: str) -> str | None:
    """The story an address names now: itself, or the story it was merged into (followed to the end)."""
    seen = set()
    while story_id in folded["merged_into"] and story_id not in seen:
        seen.add(story_id)
        story_id = folded["merged_into"][story_id]["into_story_id"]
    return story_id if story_id in folded["stories"] else None


def published_brief(folded: dict, story_id: str) -> tuple[dict | None, dict | None]:
    """(the brief version users read now, its publication), or (None, the withdrawal or None)."""
    publications = folded["publications"].get(story_id, [])
    if not publications:
        return None, None
    latest = publications[-1]
    if latest["version"] is None:
        return None, latest
    version = next(row for row in folded["briefs"][story_id] if row["version"] == latest["version"])
    return version, latest
