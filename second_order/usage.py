"""Usage limits (docs/news-usage-contract.md, sections 2 and 3): the administrator's usage policy, the operations
counted per account and quota day, storage, the server's shared budgets for publication requests and feed refreshes,
and the protective request-rate and concurrency limits.

The policy is versioned and append-only like the credit policy, published only by an administrator with a reason and
an idempotency key; no value is built in and none is selected here. A missing policy is never unlimited: every counted
operation is refused (409 no_usage_policy).

Counting is durable and atomic: a counted request reserves its event in one serialized accounts-store transaction
before it writes or requests anything, and releases it (an append-only release row) when it ends without a write or a
request, so two requests at a limit never both pass and nothing is counted twice. Days are the quota days of the fixed
quota time zone (entitlements.quota_day), as for the daily analysis limit; counted events fix the zone too. Storage is
measured from the account's own recorded sources; source writes of one account are serialized in this process
(account_lock), so two cannot both pass the storage check. The request-rate and concurrency limits are protective
only: kept in this server process's memory, never charged or refunded, and reset by a restart.
"""
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from typing import Callable, Iterator

from .accounts import Accounts, AccountsRefused, checked_reason, current_timezone, now, stamp
from .entitlements import checked_key, earlier_publication, next_reset, quota_day
from .store import canonical

ACCOUNT_BOUNDS = {"searches_per_day": (0, 10_000), "imports_per_day": (0, 1_000), "sources_per_day": (0, 1_000),
                  "preparations_per_day": (0, 1_000), "max_sources": (0, 100_000),
                  "max_source_bytes": (0, 1_000_000_000), "requests_per_minute": (1, 10_000),
                  "concurrent_requests": (1, 64)}
SERVER_BOUNDS = {"publication_fetches_per_day": (0, 1_000), "refreshes_per_day": (0, 1_000),
                 "refresh_cooldown_seconds": (0, 86_400)}
OPERATIONS = ("search", "import", "source", "preparation")
DAILY_FIELD = {"search": "searches_per_day", "import": "imports_per_day", "source": "sources_per_day",
               "preparation": "preparations_per_day"}
LABELS = {"search": "Searches", "import": "Publication imports", "source": "New sources",
          "preparation": "Prepared analyses"}
NO_POLICY = ("Searches, imports and new sources are not available yet: no usage limits are set on this server. Ask "
             "the administrator.")
DONE = {"search": "today's searches", "import": "today's publication imports", "source": "today's new sources",
        "preparation": "today's prepared analyses"}


def checked_policy(body: object) -> dict:
    """A usage policy: exactly the account and server fields, each a whole number within its bounds."""
    if not isinstance(body, dict) or set(body) != {"account", "server"}:
        raise AccountsRefused(422, "invalid_request", "A usage policy has exactly account and server")
    checked = {}
    for part, bounds in (("account", ACCOUNT_BOUNDS), ("server", SERVER_BOUNDS)):
        values = body[part]
        if not isinstance(values, dict) or set(values) != set(bounds):
            raise AccountsRefused(422, "invalid_request", f"{part} has exactly {', '.join(bounds)}")
        for name, (low, high) in bounds.items():
            value = values[name]
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise AccountsRefused(422, "invalid_request", f"{part}.{name} must be a whole number from {low:,} to "
                                                              f"{high:,}")
        checked[part] = {name: values[name] for name in bounds}
    return checked


def _row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {"policy_version": row["policy_version"], **json.loads(row["body"]), "created_at": row["created_at"],
            "created_by": row["created_by"], "reason": row["reason"]}


def _current(connection: sqlite3.Connection) -> dict | None:
    return _row(connection.execute("SELECT * FROM usage_policies ORDER BY policy_seq DESC LIMIT 1").fetchone())


def current_policy(accounts: Accounts) -> dict | None:
    with accounts.reading() as connection:
        return _current(connection)


def policies(accounts: Accounts) -> list[dict]:
    with accounts.reading() as connection:
        return [_row(row) for row in connection.execute("SELECT * FROM usage_policies ORDER BY policy_seq")]


def add_policy(accounts: Accounts, body: object, actor: str, reason: object, moment: datetime | None = None) -> dict:
    """Append a usage policy version without a key (setup and tests; the Admin route publishes through
    publish_policy)."""
    policy, reason = checked_policy(body), checked_reason(reason)
    with accounts.writing() as connection:
        _insert(connection, policy, actor, reason, moment)
        return _current(connection)


def _insert(connection: sqlite3.Connection, policy: dict, actor: str, reason: str, moment: datetime | None) -> str:
    sequence = connection.execute("SELECT COALESCE(MAX(policy_seq), 0) + 1 FROM usage_policies").fetchone()[0]
    version = f"usage-policy-{sequence}"
    connection.execute("INSERT INTO usage_policies (policy_seq, policy_version, body, created_at, created_by, reason) "
                       "VALUES (?, ?, ?, ?, ?, ?)",
                       (sequence, version, canonical(policy), stamp(moment or now()), actor, reason))
    return version


def publish_policy(accounts: Accounts, body: object, actor: str, reason: object, key: object,
                   moment: datetime | None = None) -> tuple[dict, dict, bool]:
    """One explicit publication of a usage policy version per idempotency key (as entitlements.publish_policy):
    (the version this key published, the current version, created)."""
    policy, reason, key = checked_policy(body), checked_reason(reason), checked_key(key)
    digest = hashlib.sha256(canonical({"policy": policy, "reason": reason}).encode("utf-8")).hexdigest()
    with accounts.writing() as connection:
        earlier = earlier_publication(connection, "usage_policy", key, actor, digest)
        created = earlier is None
        version = _insert(connection, policy, actor, reason, moment) if created else earlier["version"]
        if created:
            connection.execute("INSERT INTO publications (kind, idempotency_key, actor, payload_sha256, version, at) "
                               "VALUES ('usage_policy', ?, ?, ?, ?, ?)", (key, actor, digest, version,
                                                                           stamp(moment or now())))
        published = _row(connection.execute("SELECT * FROM usage_policies WHERE policy_version = ?",
                                            (version,)).fetchone())
        return published, _current(connection), created


# ---------------------------------------------------------------- counted operations

@dataclass
class Reservation:
    """The events one request reserved (none for a repeat of a counted search), and what its `write` returned."""
    event_ids: list[int] = field(default_factory=list)
    duplicate: bool = False
    written: object = None


def _today(connection: sqlite3.Connection, moment: datetime) -> tuple[str, str]:
    zone = current_timezone(connection)
    return quota_day(moment, zone), zone


def _used(connection: sqlite3.Connection, scope: str, operation: str, day: str, user_id: str | None = None) -> int:
    query = ("SELECT COUNT(*) FROM usage_events e LEFT JOIN usage_releases r ON r.event_id = e.event_id "
             "WHERE r.event_id IS NULL AND e.scope = ? AND e.operation = ? AND e.quota_day = ?")
    values: tuple = (scope, operation, day)
    if user_id is not None:
        query, values = query + " AND e.user_id = ?", values + (user_id,)
    return connection.execute(query, values).fetchone()[0]


def _event(connection: sqlite3.Connection, scope: str, user_id: str, operation: str, day: str, zone: str,
           moment: datetime, request_key: str | None = None, payload_sha256: str | None = None) -> int:
    cursor = connection.execute("INSERT INTO usage_events (scope, user_id, operation, quota_day, quota_timezone, "
                                "request_key, payload_sha256, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                (scope, user_id, operation, day, zone, request_key, payload_sha256, stamp(moment)))
    return cursor.lastrowid


def _policy_or_refuse(connection: sqlite3.Connection) -> dict:
    policy = _current(connection)
    if policy is None:
        raise AccountsRefused(409, "no_usage_policy", NO_POLICY)
    return policy


def reserve(accounts: Accounts, user_id: str, operation: str, moment: datetime | None = None, *,
            request_key: str | None = None, payload_sha256: str | None = None, fetch: bool = False,
            storage: Callable[[dict], None] | None = None, write: Callable[[], object] | None = None) -> Reservation:
    """Reserve one counted operation for an account today, in one serialized transaction; with `fetch`, also one of the
    server's publication requests. A search repeating its request key and body is answered as a duplicate (nothing
    reserved); the key with another body is refused. `storage` checks the policy's storage limits (it raises). `write`
    is the write the count is for, made inside the same transaction once everything else passed: when it raises, the
    count is rolled back with it, so a write refused only by the write itself records nothing."""
    moment = moment or now()
    with accounts.writing() as connection:
        policy = _policy_or_refuse(connection)
        day, zone = _today(connection, moment)
        if request_key is not None:
            earlier = connection.execute("SELECT payload_sha256 FROM usage_events WHERE user_id = ? AND operation = ? "
                                         "AND request_key = ?", (user_id, operation, request_key)).fetchone()
            if earlier is not None:
                if earlier["payload_sha256"] != payload_sha256:
                    raise AccountsRefused(409, "request_key_reused", "This search key was already used for another "
                                                                     "search. Nothing was counted.")
                return Reservation(duplicate=True)
        limit, used = policy["account"][DAILY_FIELD[operation]], _used(connection, "account", operation, day, user_id)
        if used >= limit:
            raise AccountsRefused(409, "usage_limit_reached", f"You have used {DONE[operation]} ({used} of {limit}). "
                                  f"They reset at midnight in {zone}.",
                                  quota={"operation": operation, "limit": limit, "used": used, "day": day,
                                         "timezone": zone, "resets_at": stamp(next_reset(moment, zone))})
        if storage is not None:
            storage(policy)
        ids = [_event(connection, "account", user_id, operation, day, zone, moment, request_key, payload_sha256)]
        if fetch:
            budget = policy["server"]["publication_fetches_per_day"]
            if _used(connection, "server", "publication_fetch", day) >= budget:
                raise AccountsRefused(409, "fetch_budget_reached", "This server has made today's publication requests. "
                                      "Nothing was requested; you can open the official page and paste its text into "
                                      "a new source instead.", resets_at=stamp(next_reset(moment, zone)))
            ids.append(_event(connection, "server", user_id, "publication_fetch", day, zone, moment))
        return Reservation(ids, written=None if write is None else write())


def release(accounts: Accounts, reservation: Reservation, reason: str, moment: datetime | None = None,
            operations: set[str] | None = None) -> None:
    """Uncount a reservation's events (append-only release rows), once each; with `operations`, only those."""
    if not reservation.event_ids:
        return
    with accounts.writing() as connection:
        for event_id in reservation.event_ids:
            row = connection.execute("SELECT operation FROM usage_events WHERE event_id = ?", (event_id,)).fetchone()
            if operations is not None and (row is None or row["operation"] not in operations):
                continue
            connection.execute("INSERT OR IGNORE INTO usage_releases (event_id, reason, at) VALUES (?, ?, ?)",
                               (event_id, reason, stamp(moment or now())))


def quota_now(accounts: Accounts, user_id: str, operation: str, moment: datetime | None = None) -> dict:
    """One counted operation's figures for an account now (QuotaNow)."""
    moment = moment or now()
    with accounts.reading() as connection:
        policy, (day, _) = _current(connection), _today(connection, moment)
        used = _used(connection, "account", operation, day, user_id)
    limit = None if policy is None else policy["account"][DAILY_FIELD[operation]]
    return {"operation": operation, "label": LABELS[operation], "limit": limit, "used": used,
            "remaining": None if limit is None else max(0, limit - used)}


# ---------------------------------------------------------------- storage

_LOCKS: dict[str, threading.Lock] = defaultdict(threading.Lock)
_LOCKS_GUARD = threading.Lock()


@contextmanager
def account_lock(user_id: str) -> Iterator[None]:
    """Serialize one account's source writes in this process, so two cannot both pass the storage check."""
    with _LOCKS_GUARD:
        lock = _LOCKS[user_id]
    with lock:
        yield


def stored(accounts: Accounts, intake: Path, user_id: str) -> dict:
    """The account's own recorded sources: how many, and the UTF-8 bytes of their texts."""
    with accounts.reading() as connection:
        rows = connection.execute("SELECT record_id FROM record_owners WHERE kind = 'capture' AND user_id = ?",
                                  (user_id,)).fetchall()
    sizes = []
    for row in rows:
        try:
            sizes.append((intake / row["record_id"] / "source.txt").stat().st_size)
        except OSError:
            sizes.append(0)  # A missing copy holds nothing here; reading it is the research flow's concern.
    return {"sources": len(sizes), "source_bytes": sum(sizes)}


def storage_check(held: dict, adding: int) -> Callable[[dict], None]:
    """The policy's storage limits for one more source of `adding` bytes (refuses with the figures)."""
    def check(policy: dict) -> None:
        for measure, limit, more in (("sources", policy["account"]["max_sources"], 1),
                                     ("source_bytes", policy["account"]["max_source_bytes"], adding)):
            if held[measure] + more > limit:
                what = "sources" if measure == "sources" else "bytes of source text"
                raise AccountsRefused(409, "storage_limit_reached", f"This source would exceed what your account may "
                                      f"hold ({limit:,} {what}). Nothing was saved.",
                                      storage={"measure": measure, "limit": limit, "used": held[measure],
                                               "adding": more})
    return check


# ---------------------------------------------------------------- views

def limits_view(accounts: Accounts, intake: Path, user_id: str, moment: datetime | None = None) -> dict:
    """The account's limits and use today (Limits)."""
    moment = moment or now()
    with accounts.reading() as connection:
        policy, (day, zone) = _current(connection), _today(connection, moment)
        used = {operation: _used(connection, "account", operation, day, user_id) for operation in OPERATIONS}
    held = stored(accounts, intake, user_id)
    account = policy["account"] if policy else None
    return {"state": "set" if policy else "no_policy", "detail": None if policy else NO_POLICY,
            "policy_version": policy["policy_version"] if policy else None, "day": day, "timezone": zone,
            "resets_at": stamp(next_reset(moment, zone)),
            "operations": [{"operation": operation, "label": LABELS[operation],
                            "limit": account[DAILY_FIELD[operation]] if account else None, "used": used[operation],
                            "remaining": max(0, account[DAILY_FIELD[operation]] - used[operation]) if account else None}
                           for operation in OPERATIONS],
            "storage": {"sources": {"used": held["sources"], "limit": account["max_sources"] if account else None},
                        "source_bytes": {"used": held["source_bytes"],
                                         "limit": account["max_source_bytes"] if account else None}},
            "rate": {"requests_per_minute": account["requests_per_minute"] if account else None,
                     "concurrent_requests": account["concurrent_requests"] if account else None}}


def overview(accounts: Accounts, intake: Path, moment: datetime | None = None) -> dict:
    """For administrators: the policy, every user account's use today and storage, and the server's budgets."""
    moment = moment or now()
    with accounts.reading() as connection:
        policy, (day, zone) = _current(connection), _today(connection, moment)
        users = [row["user_id"] for row in connection.execute("SELECT user_id FROM users WHERE role = 'user' "
                                                              "ORDER BY created_at, user_id")]
        fetches = _used(connection, "server", "publication_fetch", day)
        refreshes = _used(connection, "server", "refresh", day)
        last = _last_refresh(connection)
    server = policy["server"] if policy else None
    rows = []
    for user_id in users:
        view = limits_view(accounts, intake, user_id, moment)
        rows.append({"user_id": user_id, "operations": view["operations"], "storage": view["storage"]})
    next_allowed = None
    if last is not None and server is not None:
        next_allowed = stamp(datetime.fromisoformat(last) + timedelta(seconds=server["refresh_cooldown_seconds"]))
    return {"policy": policy, "day": day, "timezone": zone, "resets_at": stamp(next_reset(moment, zone)),
            "accounts": rows,
            "server": {"publication_fetches": {"used": fetches,
                                               "limit": server["publication_fetches_per_day"] if server else None},
                       "refreshes": {"used": refreshes, "limit": server["refreshes_per_day"] if server else None},
                       "last_refresh_started_at": last, "next_refresh_allowed_at": next_allowed}}


# ---------------------------------------------------------------- the shared feed refresh

def _last_refresh(connection: sqlite3.Connection) -> str | None:
    row = connection.execute("SELECT e.at FROM usage_events e LEFT JOIN usage_releases r ON r.event_id = e.event_id "
                             "WHERE r.event_id IS NULL AND e.scope = 'server' AND e.operation = 'refresh' "
                             "ORDER BY e.event_id DESC LIMIT 1").fetchone()
    return row["at"] if row else None


def reserve_server_fetches(accounts: Accounts, actor: str, count: int, moment: datetime | None = None) -> Reservation:
    """``count`` of the server's daily publication requests, for an administrator's explicit retrieval of official
    publication texts (news_texts); refused whole, requesting nothing, when the day's budget cannot hold them all."""
    moment = moment or now()
    with accounts.writing() as connection:
        policy = _current(connection)
        if policy is None:
            raise AccountsRefused(409, "no_usage_policy", "No usage policy is set, so no publication is requested: "
                                                          "publish one under Policy & settings first.")
        day, zone = _today(connection, moment)
        budget, used = policy["server"]["publication_fetches_per_day"], _used(connection, "server", "publication_fetch",
                                                                              day)
        if used + count > budget:
            raise AccountsRefused(409, "fetch_budget_reached", f"This server has {max(0, budget - used)} of today's "
                                  f"{budget} publication requests left and this needs {count}. Nothing was requested.",
                                  resets_at=stamp(next_reset(moment, zone)))
        return Reservation([_event(connection, "server", actor, "publication_fetch", day, zone, moment)
                            for _ in range(count)])


def reserve_refresh(accounts: Accounts, actor: str, moment: datetime | None = None) -> Reservation:
    """One feed refresh for the whole server: needs a usage policy, waits the cooldown after the previous start and
    stops at the day's budget. Refusals request nothing."""
    moment = moment or now()
    with accounts.writing() as connection:
        policy = _current(connection)
        if policy is None:
            raise AccountsRefused(409, "no_usage_policy", "No usage policy is set, so the feeds are not refreshed: "
                                                          "publish one under Policy & settings first.")
        day, zone = _today(connection, moment)
        server, last = policy["server"], _last_refresh(connection)
        if last is not None:
            wait = datetime.fromisoformat(last) + timedelta(seconds=server["refresh_cooldown_seconds"]) - moment
            if wait > timedelta(0):
                seconds = max(1, math.ceil(wait.total_seconds()))
                raise AccountsRefused(409, "refresh_cooldown", f"The feeds were refreshed recently; the next refresh is "
                                      f"allowed in {seconds} seconds. Nothing was requested.",
                                      retry_after_seconds=seconds)
        if _used(connection, "server", "refresh", day) >= server["refreshes_per_day"]:
            raise AccountsRefused(409, "refresh_budget_reached", f"Today's {server['refreshes_per_day']} feed "
                                  "refreshes are used. Nothing was requested.",
                                  resets_at=stamp(next_reset(moment, zone)))
        return Reservation([_event(connection, "server", actor, "refresh", day, zone, moment)])


# ---------------------------------------------------------------- protective limits

class Throttle:
    """An account's requests in any 60 seconds and its requests in progress, in this process's memory. Protective
    only: refusals are 429 with a wait, never a charge."""

    def __init__(self, ticks: Callable[[], float] = time.monotonic):
        self.ticks, self.lock = ticks, threading.Lock()
        self.recent: dict[str, deque] = defaultdict(deque)
        self.running: dict[str, int] = defaultdict(int)

    def enter(self, user_id: str, per_minute: int, concurrent: int) -> None:
        with self.lock:
            moment, recent = self.ticks(), self.recent[user_id]
            while recent and moment - recent[0] >= 60:
                recent.popleft()
            if len(recent) >= per_minute:
                wait = max(1, math.ceil(60 - (moment - recent[0])))
                raise AccountsRefused(429, "rate_limited", "Too many requests in a short time. Wait a moment, then "
                                                           "read the page again.", retry_after_seconds=wait)
            if self.running[user_id] >= concurrent:
                raise AccountsRefused(429, "too_many_requests", "Too many requests are in progress for your account. "
                                                                "Wait for them to finish.", retry_after_seconds=1)
            recent.append(moment)
            self.running[user_id] += 1

    def leave(self, user_id: str) -> None:
        with self.lock:
            self.running[user_id] = max(0, self.running[user_id] - 1)
