"""The accounts store: identities, roles, sessions, record ownership and settings (docs/admin-user-contract.md).

One SQLite database, separate from the research store (data/accounts/accounts.db unless ``serve --accounts`` names
another). It is created only by an explicit command (``python -m second_order accounts add-admin``) or by a test; a
server never creates it. Every operation opens its own connection, and every write is one ``BEGIN IMMEDIATE``
transaction, so threads, tabs and separate server processes over the same file are serialized by SQLite and a restart
keeps everything.

``users`` and ``sessions`` hold current state (a password hash, whether an account is active, when a session ended);
every change to an account is also appended to ``account_events`` with its actor, reason and time. Ownership, settings,
registrations and their decisions and the entitlement tables (see entitlements) are append-only: triggers refuse UPDATE
and DELETE.

A public self-registration (see registration) is an ordinary inactive ``user`` row plus a ``registrations`` row; it
becomes active only through an administrator's one recorded approval. Until then it is ``pending`` (or, after a
rejection, ``rejected``): it cannot sign in, and triggers refuse its activation without that approval and any credit,
daily limit, record ownership, quote or attempt for it. Accounts an administrator created have no registration row and
are ``active`` or ``disabled`` exactly as before (docs/onboarding-contract.md).

Passwords are stored as scrypt hashes with a random salt; session tokens are random and only their SHA-256 is stored.
Nothing here reads a credential from the environment, a file or an argument: the first admin's password is typed at a
prompt, and later accounts are created by an admin.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_PATH = ROOT / "data" / "accounts" / "accounts.db"  # Runtime records; data/ is ignored by git.
SCHEMA_VERSION = "accounts-3"
# Earlier stores `accounts upgrade` brings to SCHEMA_VERSION, keeping every row: accounts-1 had no registrations,
# accounts-2 no publications, usage policies, usage events or news interests.
PREVIOUS_SCHEMAS = ("accounts-1", "accounts-2")
PREVIOUS_SCHEMA = "accounts-1"  # The first version (kept for its tests and messages).
ROLES = ("admin", "user")
USERNAME = re.compile(r"[a-z0-9][a-z0-9._-]{2,39}")
USER_ID = re.compile(r"u-[0-9a-f]{16}")
MIN_PASSWORD = 10
MAX_PASSWORD = 256
MAX_NAME = 80
MAX_REASON = 500
SESSION_HOURS = 12
DEFAULT_TIMEZONE = "Asia/Jerusalem"  # The operator's initial quota time zone; an admin setting changes it.
OWNED_KINDS = ("capture",)
SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
CONTROL = re.compile(r"[\x00-\x1f\x7f]")

APPEND_ONLY = ("account_events", "record_owners", "settings", "credit_policies", "daily_limits", "quotes",
               "attempts", "attempt_sends", "attempt_outcomes", "resolutions", "ledger")
REGISTRATION_TABLES = ("registrations", "registration_decisions")
USAGE_TABLES = ("publications", "usage_policies", "usage_events", "usage_releases", "news_interests")

SCHEMA = """
CREATE TABLE accounts_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
    password TEXT NOT NULL,
    active INTEGER NOT NULL CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL
);
CREATE TABLE sessions (
    token_sha256 TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ended_at TEXT,
    end_reason TEXT
);
CREATE TABLE account_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    kind TEXT NOT NULL,
    detail TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE record_owners (
    kind TEXT NOT NULL,
    record_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    assigned_at TEXT NOT NULL,
    assigned_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    PRIMARY KEY (kind, record_id)
);
CREATE TABLE settings (
    setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    set_at TEXT NOT NULL,
    set_by TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE credit_policies (
    policy_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_version TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE daily_limits (
    limit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    daily_limit INTEGER NOT NULL CHECK (daily_limit >= 0),
    set_at TEXT NOT NULL,
    set_by TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE quotes (
    quote_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    request_id TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    effort TEXT NOT NULL,
    policy_version TEXT NOT NULL REFERENCES credit_policies (policy_version),
    credits INTEGER NOT NULL CHECK (credits >= 1),
    input_tokens_assumed INTEGER NOT NULL,
    max_tokens INTEGER NOT NULL,
    planning_estimate_usd REAL NOT NULL,
    issued_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE attempts (
    attempt_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    request_id TEXT NOT NULL UNIQUE,
    quote_id TEXT NOT NULL UNIQUE REFERENCES quotes (quote_id),
    effort TEXT NOT NULL,
    credits INTEGER NOT NULL CHECK (credits >= 1),
    quota_day TEXT NOT NULL,
    quota_timezone TEXT NOT NULL,
    reserved_at TEXT NOT NULL,
    pid INTEGER NOT NULL
);
CREATE TABLE attempt_sends (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts (attempt_id),
    sent_at TEXT NOT NULL
);
CREATE TABLE attempt_outcomes (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts (attempt_id),
    outcome TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE TABLE resolutions (
    attempt_id TEXT PRIMARY KEY REFERENCES attempts (attempt_id),
    kind TEXT NOT NULL CHECK (kind IN ('charged', 'returned')),
    credits_charged INTEGER NOT NULL CHECK (credits_charged >= 0),
    slot_released INTEGER NOT NULL CHECK (slot_released IN (0, 1)),
    reason TEXT NOT NULL,
    actor TEXT NOT NULL,
    resolved_at TEXT NOT NULL
);
CREATE TABLE ledger (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users (user_id),
    kind TEXT NOT NULL CHECK (kind IN ('grant', 'correction', 'hold', 'release', 'settle')),
    amount INTEGER NOT NULL,
    attempt_id TEXT REFERENCES attempts (attempt_id),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    at TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE
);
CREATE TRIGGER resolutions_within_reserved BEFORE INSERT ON resolutions
WHEN NEW.credits_charged > (SELECT credits FROM attempts WHERE attempt_id = NEW.attempt_id)
BEGIN SELECT RAISE(ABORT, 'a resolution cannot charge more than the attempt reserved'); END;
CREATE TRIGGER returned_charges_nothing BEFORE INSERT ON resolutions
WHEN NEW.kind = 'returned' AND (NEW.credits_charged != 0 OR NEW.slot_released != 1)
BEGIN SELECT RAISE(ABORT, 'a returned attempt charges nothing and releases its daily slot'); END;
CREATE INDEX ledger_user ON ledger (user_id);
CREATE INDEX attempts_user_day ON attempts (user_id, quota_day);
CREATE INDEX quotes_request ON quotes (request_id);
"""
# A registration without an approval (pending or rejected), for the row a trigger is about to write.
_UNAPPROVED = ("EXISTS (SELECT 1 FROM registrations r WHERE r.user_id = NEW.user_id) AND NOT EXISTS "
               "(SELECT 1 FROM registration_decisions d WHERE d.user_id = NEW.user_id AND d.decision = 'approved')")
REGISTRATION_SCHEMA = """
CREATE TABLE registrations (
    user_id TEXT PRIMARY KEY REFERENCES users (user_id),
    submitted_at TEXT NOT NULL,
    note TEXT NOT NULL
);
CREATE TABLE registration_decisions (
    user_id TEXT PRIMARY KEY REFERENCES registrations (user_id),
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    decided_at TEXT NOT NULL
);
CREATE TRIGGER registrations_are_inactive_users BEFORE INSERT ON registrations
WHEN NOT EXISTS (SELECT 1 FROM users WHERE user_id = NEW.user_id AND role = 'user' AND active = 0)
BEGIN SELECT RAISE(ABORT, 'a registration is an inactive user account'); END;
CREATE TRIGGER users_role_fixed BEFORE UPDATE OF role ON users WHEN NEW.role IS NOT OLD.role
BEGIN SELECT RAISE(ABORT, 'an account keeps its role'); END;
""" + "".join(f"""CREATE TRIGGER {name} BEFORE {event}
WHEN {condition}{_UNAPPROVED}
BEGIN SELECT RAISE(ABORT, '{message}'); END;
""" for name, event, condition, message in (
    ("registration_active_only_by_approval", "UPDATE OF active ON users", "NEW.active = 1 AND ",
     "a registration becomes active only by an approval"),
    ("ledger_needs_approval", "INSERT ON ledger", "", "no credits for a registration that is not approved"),
    ("daily_limits_need_approval", "INSERT ON daily_limits", "",
     "no daily limit for a registration that is not approved"),
    ("owners_need_approval", "INSERT ON record_owners", "", "no records for a registration that is not approved"),
    ("quotes_need_approval", "INSERT ON quotes", "", "no quote for a registration that is not approved"),
    ("attempts_need_approval", "INSERT ON attempts", "", "no attempt for a registration that is not approved")))


USAGE_SCHEMA = """
CREATE TABLE publications (
    kind TEXT NOT NULL CHECK (kind IN ('credit_policy', 'usage_policy')),
    idempotency_key TEXT NOT NULL,
    actor TEXT NOT NULL REFERENCES users (user_id),
    payload_sha256 TEXT NOT NULL,
    version TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (kind, idempotency_key)
);
CREATE TABLE usage_policies (
    policy_seq INTEGER PRIMARY KEY AUTOINCREMENT,
    policy_version TEXT NOT NULL UNIQUE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    reason TEXT NOT NULL
);
CREATE TABLE usage_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL CHECK (scope IN ('account', 'server')),
    user_id TEXT NOT NULL REFERENCES users (user_id),
    operation TEXT NOT NULL CHECK (operation IN ('search', 'import', 'source', 'preparation', 'publication_fetch',
                                                 'refresh')),
    quota_day TEXT NOT NULL,
    quota_timezone TEXT NOT NULL,
    request_key TEXT,
    payload_sha256 TEXT,
    at TEXT NOT NULL,
    UNIQUE (user_id, operation, request_key)
);
CREATE TABLE usage_releases (
    event_id INTEGER PRIMARY KEY REFERENCES usage_events (event_id),
    reason TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE news_interests (
    user_id TEXT NOT NULL REFERENCES users (user_id),
    version INTEGER NOT NULL CHECK (version >= 1),
    interests TEXT NOT NULL,
    saved_at TEXT NOT NULL,
    PRIMARY KEY (user_id, version)
);
CREATE INDEX usage_events_counts ON usage_events (scope, operation, quota_day, user_id);
""" + "".join(f"""CREATE TRIGGER {name} BEFORE INSERT ON {table}
WHEN {_UNAPPROVED}
BEGIN SELECT RAISE(ABORT, '{message}'); END;
""" for name, table, message in (
    ("usage_needs_approval", "usage_events", "no counted use for a registration that is not approved"),
    ("interests_need_approval", "news_interests", "no interests for a registration that is not approved")))


class AccountsRefused(ValueError):
    """A refusal with a user-contract code (docs/admin-user-contract.md, section 9)."""

    def __init__(self, status: int, code: str, detail: str, **extra):
        super().__init__(detail)
        self.status, self.code, self.extra = status, code, extra


@dataclass(frozen=True)
class Identity:
    user_id: str
    username: str
    display_name: str
    role: str
    expires_at: str | None = None

    def view(self) -> dict:
        return {"user_id": self.user_id, "username": self.username, "display_name": self.display_name,
                "role": self.role}


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _append_only(tables: tuple[str, ...] = APPEND_ONLY + REGISTRATION_TABLES + USAGE_TABLES) -> str:
    return "".join(f"CREATE TRIGGER {table}_no_{action} BEFORE {action.upper()} ON {table} "
                   f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;\n"
                   for table in tables for action in ("update", "delete"))


def _connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def create_store(path: Path) -> None:
    """Create a new, empty accounts store. Refused when the file exists: a store is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise AccountsRefused(409, "invalid_request", f"An accounts store already exists at {path}")
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript("BEGIN;" + SCHEMA + REGISTRATION_SCHEMA + USAGE_SCHEMA + _append_only()
                                 + f"INSERT INTO accounts_meta VALUES ('schema', '{SCHEMA_VERSION}'); COMMIT;")
    finally:
        connection.close()


def store_version(path: Path) -> str | None:
    connection = _connect(path)
    try:
        row = connection.execute("SELECT value FROM accounts_meta WHERE key = 'schema'").fetchone()
    except sqlite3.DatabaseError:
        row = None
    finally:
        connection.close()
    return row["value"] if row else None


def upgrade_store(path: Path) -> bool:
    """Bring an earlier store to SCHEMA_VERSION in one transaction: an accounts-1 store gains the registration tables
    and their guards, and an accounts-1 or accounts-2 store the publications, usage policies and events and news
    interests (empty). Every existing account, session, ledger entry and record is kept as it is; existing accounts
    have no registration, so each stays active or disabled. False when the store is already current. Run only by an
    explicit command, never by a server."""
    if not path.is_file():
        raise AccountsRefused(503, "accounts_unavailable", f"No accounts store exists at {path}")
    version = store_version(path)
    if version == SCHEMA_VERSION:
        return False
    if version not in PREVIOUS_SCHEMAS:
        raise AccountsRefused(503, "accounts_unavailable",
                              f"{path} is not an {' or '.join(PREVIOUS_SCHEMAS)} accounts store")
    added = (REGISTRATION_SCHEMA + _append_only(REGISTRATION_TABLES) if version == "accounts-1" else "") + \
        USAGE_SCHEMA + _append_only(USAGE_TABLES)
    connection = sqlite3.connect(path, isolation_level=None)
    try:
        connection.executescript("BEGIN IMMEDIATE;" + added
                                 + f"UPDATE accounts_meta SET value = '{SCHEMA_VERSION}' WHERE key = 'schema' "
                                   f"AND value = '{version}'; COMMIT;")
    except sqlite3.DatabaseError:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()
    return True


@dataclass(frozen=True)
class Accounts:
    """The accounts store at one path. Holds no connection: each call opens, uses and closes its own."""
    path: Path

    @property
    def lock_dir(self) -> Path:
        """Execution locks of running attempts (see attempt_locks), beside the store."""
        return self.path.parent / "attempt-locks"

    @classmethod
    def open(cls, path: Path) -> "Accounts":
        if not path.is_file():
            raise AccountsRefused(503, "accounts_unavailable", f"No accounts store exists at {path}. Create the first "
                                  "administrator: python -m second_order accounts add-admin --username NAME")
        accounts = cls(path)
        with accounts.reading() as connection:
            row = connection.execute("SELECT value FROM accounts_meta WHERE key = 'schema'").fetchone()
        if row is not None and row["value"] in PREVIOUS_SCHEMAS:
            raise AccountsRefused(503, "accounts_unavailable", f"{path} is an {row['value']} accounts store, from "
                                  "before this version of the accounts. Upgrade it (every account and record is kept): "
                                  "python -m second_order accounts upgrade")
        if row is None or row["value"] != SCHEMA_VERSION:
            raise AccountsRefused(503, "accounts_unavailable", f"{path} is not an {SCHEMA_VERSION} accounts store")
        return accounts

    @contextmanager
    def reading(self) -> Iterator[sqlite3.Connection]:
        connection = _connect(self.path)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def writing(self) -> Iterator[sqlite3.Connection]:
        """One serialized write transaction: every check inside it sees and holds the current state."""
        connection = _connect(self.path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.execute("ROLLBACK")
                raise
            connection.execute("COMMIT")
        finally:
            connection.close()


# ---------------------------------------------------------------- passwords, names and reasons

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **SCRYPT)
    return f"scrypt${SCRYPT['n']}${SCRYPT['r']}${SCRYPT['p']}${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored: str) -> bool:
    try:
        name, n, r, p, salt, expected = stored.split("$")
        if name != "scrypt":
            return False
        digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                                dklen=32, maxmem=64 * 1024 * 1024)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), expected)


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))  # Compared against for unknown users, so timing reveals nothing.


def checked_password(password: object) -> str:
    if not isinstance(password, str) or not MIN_PASSWORD <= len(password) <= MAX_PASSWORD or CONTROL.search(password):
        raise AccountsRefused(422, "invalid_request", f"A password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters "
                                                      "without control characters")
    return password


def checked_username(username: object) -> str:
    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise AccountsRefused(422, "invalid_request", "A username is 3 to 40 lowercase letters, digits, dots, hyphens "
                                                      "or underscores, starting with a letter or digit")
    return username


def checked_text(value: object, label: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or CONTROL.search(value):
        raise AccountsRefused(422, "invalid_request", f"{label} must be text of 1 to {limit} characters without "
                                                      "control characters")
    return value.strip()


def checked_reason(value: object) -> str:
    return checked_text(value, "A reason", MAX_REASON)


# ---------------------------------------------------------------- accounts

def _event(connection: sqlite3.Connection, user_id: str, kind: str, detail: str, actor: str, reason: str,
           moment: datetime) -> None:
    connection.execute("INSERT INTO account_events (user_id, kind, detail, actor, reason, at) VALUES (?, ?, ?, ?, ?, ?)",
                       (user_id, kind, detail, actor, reason, stamp(moment)))


def create_user(accounts: Accounts, username: object, display_name: object, role: object, password: object,
                actor: str, moment: datetime | None = None) -> dict:
    """A new active account. ``actor`` is the creating admin's user ID (or ``local-command`` for the first admin)."""
    moment = moment or now()
    username = checked_username(username)
    display_name = checked_text(display_name, "A display name", MAX_NAME)
    if role not in ROLES:
        raise AccountsRefused(422, "invalid_request", "role must be admin or user")
    hashed = hash_password(checked_password(password))
    user_id = f"u-{secrets.token_hex(8)}"
    with accounts.writing() as connection:
        if connection.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AccountsRefused(409, "invalid_request", f"The username {username} is taken")
        connection.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
                           (user_id, username, display_name, role, hashed, stamp(moment), actor))
        _event(connection, user_id, "created", f"role {role}", actor, "account created", moment)
    return user_view(accounts, user_id)


_ACCOUNT = ("SELECT u.user_id, u.username, u.display_name, u.role, u.active, u.created_at, u.created_by, "
            "r.submitted_at, r.note, d.decision, d.actor AS decided_by, d.reason AS decision_reason, d.decided_at "
            "FROM users u LEFT JOIN registrations r ON r.user_id = u.user_id "
            "LEFT JOIN registration_decisions d ON d.user_id = u.user_id")


def status_of(row: sqlite3.Row) -> str:
    """pending or rejected for a registration without an approval; otherwise active or disabled, as before."""
    if row["submitted_at"] is not None and row["decision"] != "approved":
        return "rejected" if row["decision"] == "rejected" else "pending"
    return "active" if row["active"] else "disabled"


def _account(row: sqlite3.Row) -> dict:
    registration = None
    if row["submitted_at"] is not None:
        decision = None if row["decision"] is None else {
            "decision": row["decision"], "decided_at": row["decided_at"], "decided_by": row["decided_by"],
            "reason": row["decision_reason"]}
        registration = {"submitted_at": row["submitted_at"], "note": row["note"], "decision": decision}
    return {key: row[key] for key in ("user_id", "username", "display_name", "role", "created_at", "created_by")} | {
        "active": bool(row["active"]), "status": status_of(row), "registration": registration}


def account_row(connection: sqlite3.Connection, user_id: str) -> sqlite3.Row | None:
    return connection.execute(_ACCOUNT + " WHERE u.user_id = ?", (user_id,)).fetchone()


def account_status(connection: sqlite3.Connection, user_id: str) -> str | None:
    row = account_row(connection, user_id)
    return None if row is None else status_of(row)


def refuse_unapproved(connection: sqlite3.Connection, user_id: str) -> None:
    """Credits, limits and records are for approved accounts: refuse a pending or rejected registration."""
    if account_status(connection, user_id) in ("pending", "rejected"):
        raise AccountsRefused(409, "account_not_approved", "This account is a registration that an administrator has "
                                                           "not approved. Nothing was recorded.")


def user_view(accounts: Accounts, user_id: str) -> dict:
    with accounts.reading() as connection:
        row = account_row(connection, user_id)
    if row is None:
        raise AccountsRefused(404, "not_found", "Unknown account")
    return _account(row)


def list_users(accounts: Accounts) -> list[dict]:
    with accounts.reading() as connection:
        rows = connection.execute(_ACCOUNT + " ORDER BY u.created_at, u.username").fetchall()
    return [_account(row) for row in rows]


def set_active(accounts: Accounts, user_id: str, active: object, actor: str, reason: object,
               moment: datetime | None = None) -> dict:
    """Activate or deactivate an account. Deactivating ends its open sessions; an admin cannot deactivate itself."""
    moment = moment or now()
    reason = checked_reason(reason)
    if not isinstance(active, bool):
        raise AccountsRefused(422, "invalid_request", "active must be true or false")
    if user_id == actor and not active:
        raise AccountsRefused(409, "invalid_request", "An administrator cannot deactivate their own account")
    with accounts.writing() as connection:
        status = account_status(connection, user_id)
        if status is None:
            raise AccountsRefused(404, "not_found", "Unknown account")
        if status in ("pending", "rejected"):
            raise AccountsRefused(409, "not_approved", "This account is a registration: approve or reject it instead. "
                                                       "Nothing was recorded.")
        connection.execute("UPDATE users SET active = ? WHERE user_id = ?", (int(active), user_id))
        if not active:
            connection.execute("UPDATE sessions SET ended_at = ?, end_reason = 'account deactivated' "
                               "WHERE user_id = ? AND ended_at IS NULL", (stamp(moment), user_id))
        _event(connection, user_id, "activated" if active else "deactivated", "", actor, reason, moment)
    return user_view(accounts, user_id)


def admin_count(accounts: Accounts) -> int:
    with accounts.reading() as connection:
        return connection.execute("SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1").fetchone()[0]


# ---------------------------------------------------------------- sessions

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


REGISTRATION_DETAIL = {
    "pending": "Your registration is waiting for an administrator's approval. Nothing can be used until it is "
               "approved; sign in later to see its status.",
    "rejected": "Your registration was not approved, so this account cannot be used.",
}


def registration_status(row: sqlite3.Row) -> dict:
    """A registrant's own view of their registration: no user ID, role, password, reason, credits or limit."""
    status = status_of(row)
    return {"username": row["username"], "display_name": row["display_name"], "status": status,
            "submitted_at": row["submitted_at"], "decided_at": row["decided_at"],
            "detail": REGISTRATION_DETAIL[status]}


def sign_in(accounts: Accounts, username: object, password: object, moment: datetime | None = None,
            hours: int = SESSION_HOURS) -> tuple[str, Identity]:
    """A new session for valid credentials of an active account: the raw token (for the cookie only) and who it is.
    One refusal for an unknown user, a wrong password and an inactive account. The right password of a pending or
    rejected registration is refused with that registration's own status, and no session is made."""
    moment = moment or now()
    refused = AccountsRefused(401, "invalid_credentials", "The username or password is not correct, or the account "
                                                          "is not active.")
    if not isinstance(username, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
        raise refused
    with accounts.reading() as connection:
        row = connection.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
        account = account_row(connection, row["user_id"]) if row is not None else None
    if row is None:
        password_matches(password, _DUMMY_HASH)
        raise refused
    if not password_matches(password, row["password"]):
        raise refused
    status = status_of(account)
    if status in ("pending", "rejected"):  # Only the right password learns a registration's own status.
        raise AccountsRefused(403, f"registration_{status}", REGISTRATION_DETAIL[status],
                              registration=registration_status(account))
    if not row["active"]:
        raise refused
    token = secrets.token_urlsafe(32)
    expires = moment + timedelta(hours=hours)
    with accounts.writing() as connection:
        connection.execute("INSERT INTO sessions (token_sha256, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                           (token_hash(token), row["user_id"], stamp(moment), stamp(expires)))
    return token, Identity(row["user_id"], row["username"], row["display_name"], row["role"], stamp(expires))


def identify(accounts: Accounts, token: str | None, moment: datetime | None = None) -> tuple[Identity | None, str]:
    """Who a session token belongs to, read only: (identity, "") or (None, why): not_signed_in for no or an unknown
    token, session_expired for an ended or expired session or an inactive account."""
    if not token:
        return None, "not_signed_in"
    moment = moment or now()
    with accounts.reading() as connection:
        row = connection.execute(
            "SELECT s.expires_at, s.ended_at, u.user_id, u.username, u.display_name, u.role, u.active "
            "FROM sessions s JOIN users u ON u.user_id = s.user_id WHERE s.token_sha256 = ?",
            (token_hash(token),)).fetchone()
    if row is None:
        return None, "not_signed_in"
    if row["ended_at"] is not None or not row["active"] or datetime.fromisoformat(row["expires_at"]) <= moment:
        return None, "session_expired"
    return Identity(row["user_id"], row["username"], row["display_name"], row["role"], row["expires_at"]), ""


def sign_out(accounts: Accounts, token: str | None, moment: datetime | None = None) -> None:
    if not token:
        return
    with accounts.writing() as connection:
        connection.execute("UPDATE sessions SET ended_at = ?, end_reason = 'signed out' "
                           "WHERE token_sha256 = ? AND ended_at IS NULL", (stamp(moment or now()), token_hash(token)))


# ---------------------------------------------------------------- ownership

def owner_of(accounts: Accounts, kind: str, record_id: str) -> str | None:
    """The user who owns a record, or None: a record without an owner row is the operator's (admin-owned)."""
    with accounts.reading() as connection:
        row = connection.execute("SELECT user_id FROM record_owners WHERE kind = ? AND record_id = ?",
                                 (kind, record_id)).fetchone()
    return row["user_id"] if row else None


def owned(accounts: Accounts, kind: str, user_id: str) -> list[str]:
    with accounts.reading() as connection:
        rows = connection.execute("SELECT record_id FROM record_owners WHERE kind = ? AND user_id = ? "
                                  "ORDER BY record_id", (kind, user_id)).fetchall()
    return [row["record_id"] for row in rows]


def all_owners(accounts: Accounts, kind: str) -> dict[str, str]:
    with accounts.reading() as connection:
        rows = connection.execute("SELECT record_id, user_id FROM record_owners WHERE kind = ?", (kind,)).fetchall()
    return {row["record_id"]: row["user_id"] for row in rows}


def assign(accounts: Accounts, kind: str, record_id: str, user_id: str, actor: str, reason: object,
           moment: datetime | None = None) -> dict:
    """Give one record an owner, once. Records are never reassigned; an unowned record stays the operator's."""
    moment = moment or now()
    reason = checked_reason(reason)
    if kind not in OWNED_KINDS:
        raise AccountsRefused(422, "invalid_request", f"kind must be one of {', '.join(OWNED_KINDS)}")
    with accounts.writing() as connection:
        user = connection.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None or user["role"] != "user":
            raise AccountsRefused(422, "invalid_request", "Records can be assigned only to a user account")
        refuse_unapproved(connection, user_id)
        if connection.execute("SELECT 1 FROM record_owners WHERE kind = ? AND record_id = ?",
                              (kind, record_id)).fetchone():
            raise AccountsRefused(409, "invalid_request", "This record already has an owner; owners never change")
        connection.execute("INSERT INTO record_owners VALUES (?, ?, ?, ?, ?, ?)",
                           (kind, record_id, user_id, stamp(moment), actor, reason))
    return {"kind": kind, "record_id": record_id, "user_id": user_id, "assigned_at": stamp(moment),
            "assigned_by": actor, "reason": reason}


# ---------------------------------------------------------------- settings

def current_timezone(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT value FROM settings WHERE name = 'quota_timezone' "
                             "ORDER BY setting_id DESC LIMIT 1").fetchone()
    return row["value"] if row else DEFAULT_TIMEZONE


def quota_timezone(accounts: Accounts) -> str:
    with accounts.reading() as connection:
        return current_timezone(connection)


def timezone_fixed(accounts: Accounts) -> bool:
    """Whether the quota time zone can no longer change: a run or a counted use has been recorded on its days (see
    set_quota_timezone)."""
    with accounts.reading() as connection:
        return _counted(connection)


def _counted(connection: sqlite3.Connection) -> bool:
    """Whether anything has been counted on a quota day: an analysis run or a counted use (usage)."""
    return connection.execute("SELECT 1 FROM attempts UNION ALL SELECT 1 FROM usage_events LIMIT 1").fetchone() \
        is not None


def set_quota_timezone(accounts: Accounts, name: object, actor: str, reason: object,
                       moment: datetime | None = None) -> tuple[str, bool]:
    """Configure the quota time zone, or keep it: returns (zone, changed).

    Allowance is counted per calendar day in this zone, from each run's recorded quota day. Changing the zone after a
    run has been counted would count the same hours again under another day, so the zone can change only while no run
    exists; afterwards only the zone already in force is accepted (unchanged, nothing recorded). The check runs in the
    same serialized write transaction as every reservation, so a change and a reservation never interleave."""
    reason = checked_reason(reason)
    try:
        if not isinstance(name, str) or not name or name != name.strip():
            raise ZoneInfoNotFoundError(name)
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise AccountsRefused(422, "invalid_request", "timezone must be an IANA time zone name such as "
                                                      "Asia/Jerusalem") from None
    with accounts.writing() as connection:
        current = current_timezone(connection)
        if name == current:
            return current, False
        if _counted(connection):
            raise AccountsRefused(409, "quota_timezone_fixed", f"The quota time zone stays {current}: analysis runs or "
                                  "other daily uses have already been counted on its calendar days, and another zone "
                                  "would count the same hours again. It can be chosen only before the first count.")
        connection.execute("INSERT INTO settings (name, value, set_at, set_by, reason) VALUES (?, ?, ?, ?, ?)",
                           ("quota_timezone", name, stamp(moment or now()), actor, reason))
    return name, True


def settings_history(accounts: Accounts) -> list[dict]:
    with accounts.reading() as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM settings ORDER BY setting_id")]


def pid() -> int:
    return os.getpid()
