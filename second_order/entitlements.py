"""Credits, daily limits, quotes and attempt reservations (docs/admin-user-contract.md, sections 7 and 8).

Everything lives in the accounts store (see accounts). The admin sets every number: credit policy versions, grants and
corrections, and each user's daily analysis limit. Nothing has a built-in value; without a policy nothing is quoted,
and without a daily limit nothing runs.

The ledger is append-only and is the only balance: available credits are the sum of its amounts. A reservation is one
``BEGIN IMMEDIATE`` transaction that rechecks the quote, the policy, the daily limit and the balance and then inserts
the attempt (unique per request and per quote), its daily slot (the attempt's quota day) and a hold of the quoted
credits. Each attempt is resolved at most once (the ``resolutions`` primary key, and the ledger's idempotency key):
charged (never more than it reserved; a trigger enforces it) or returned (its credits and daily slot released). A
duplicate approval finds the attempt its quote already made and changes nothing.

These limits govern use of this application. They are not a verified monetary billing ceiling.
"""
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
import secrets
import sqlite3
from zoneinfo import ZoneInfo

from .accounts import (Accounts, AccountsRefused, checked_reason, current_timezone, now, pid, refuse_unapproved,
                       stamp)
from .store import canonical

FLOW = "research-analysis"
SETTLEMENT = "quoted"
EFFORT_ORDER = ("low", "medium", "high", "xhigh", "max")
# The output_config.effort levels each model accepts, verified from the provider's documentation (the Claude API
# reference for Claude Sonnet 5.5: low, medium, high, xhigh and max; default high), without a live request. A level
# not listed here is never offered, whatever a policy enables, and there is no fallback to another level or model.
PROVIDER_EFFORTS = {"claude-sonnet-5-5": EFFORT_ORDER}
EFFORT_SOURCE = ("Claude API documentation for Claude Sonnet 5.5 (output_config.effort accepts low, medium, high, xhigh "
                 "and max; the API default is high), read during implementation on 2026-10-14; no request was sent.")
MAX_CREDITS = 1_000_000
MIN_QUOTE_SECONDS, MAX_QUOTE_SECONDS = 60, 86_400
MAX_REQUEST_USD = 100.0
# How long an attempt without an outcome waits before an administrator may resolve it. This is only an age: the HTTP
# client's timeouts limit each read and connect, not a whole call, and a process can pause. Whether a worker can still
# send or record is decided by the attempt's execution lock (attempt_locks), which a live worker holds.
STALE_AFTER = timedelta(minutes=15)
POLICY_FIELDS = ("model", "efforts", "credits", "max_request_usd", "quote_valid_seconds")
RATE_FIELDS = ("base", "per_1k_input_tokens", "per_1k_output_tokens")
SYSTEM = "system"


def _count(value: object, label: str, low: int = 0, high: int = MAX_CREDITS) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AccountsRefused(422, "invalid_request", f"{label} must be a whole number from {low} to {high}")
    return value


# ---------------------------------------------------------------- the credit policy

def checked_policy(body: object) -> dict:
    """An admin's new policy version, validated: a verified model, enabled levels it accepts, integer rates, the
    admin's per-request planning-estimate limit and the quote validity. Settlement is always "quoted"."""
    if not isinstance(body, dict) or set(body) != set(POLICY_FIELDS):
        raise AccountsRefused(422, "invalid_request", f"A credit policy must contain exactly {', '.join(POLICY_FIELDS)}")
    model = body["model"]
    if model not in PROVIDER_EFFORTS:
        raise AccountsRefused(422, "invalid_request", f"model must be one of {', '.join(PROVIDER_EFFORTS)}")
    efforts = body["efforts"]
    if not isinstance(efforts, dict) or any(effort not in PROVIDER_EFFORTS[model] for effort in efforts):
        raise AccountsRefused(422, "invalid_request", f"efforts may enable only {', '.join(PROVIDER_EFFORTS[model])}")
    enabled = {}
    for effort in EFFORT_ORDER:
        if effort in efforts:
            terms = efforts[effort]
            if not isinstance(terms, dict) or set(terms) != {"extra_credits"}:
                raise AccountsRefused(422, "invalid_request", f"efforts.{effort} must contain exactly extra_credits")
            enabled[effort] = {"extra_credits": _count(terms["extra_credits"], f"efforts.{effort}.extra_credits")}
    rates = body["credits"]
    if not isinstance(rates, dict) or set(rates) != set(RATE_FIELDS):
        raise AccountsRefused(422, "invalid_request", f"credits must contain exactly {', '.join(RATE_FIELDS)}")
    credits = {"base": _count(rates["base"], "credits.base", 1),
               **{field: _count(rates[field], f"credits.{field}") for field in RATE_FIELDS[1:]}}
    limit = body["max_request_usd"]
    if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not 0 < limit <= MAX_REQUEST_USD \
            or not math.isfinite(limit):
        raise AccountsRefused(422, "invalid_request", f"max_request_usd must be above 0 and at most {MAX_REQUEST_USD:g}")
    return {"flow": FLOW, "model": model, "efforts": enabled, "credits": credits, "max_request_usd": float(limit),
            "quote_valid_seconds": _count(body["quote_valid_seconds"], "quote_valid_seconds", MIN_QUOTE_SECONDS,
                                          MAX_QUOTE_SECONDS),
            "settlement": SETTLEMENT}


def _policy_row(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    return {"policy_version": row["policy_version"], **json.loads(row["body"]), "created_at": row["created_at"],
            "created_by": row["created_by"], "reason": row["reason"]}


def _current_policy(connection: sqlite3.Connection) -> dict | None:
    return _policy_row(connection.execute("SELECT * FROM credit_policies ORDER BY policy_seq DESC LIMIT 1").fetchone())


def current_policy(accounts: Accounts) -> dict | None:
    with accounts.reading() as connection:
        return _current_policy(connection)


def policies(accounts: Accounts) -> list[dict]:
    with accounts.reading() as connection:
        return [_policy_row(row) for row in connection.execute("SELECT * FROM credit_policies ORDER BY policy_seq")]


def _insert_policy(connection: sqlite3.Connection, policy: dict, actor: str, reason: str,
                   moment: datetime | None) -> str:
    sequence = connection.execute("SELECT COALESCE(MAX(policy_seq), 0) + 1 FROM credit_policies").fetchone()[0]
    version = f"credit-policy-{sequence}"
    connection.execute("INSERT INTO credit_policies (policy_seq, policy_version, body, created_at, created_by, "
                       "reason) VALUES (?, ?, ?, ?, ?, ?)",
                       (sequence, version, canonical(policy), stamp(moment or now()), actor, reason))
    return version


def add_policy(accounts: Accounts, body: object, actor: str, reason: object, moment: datetime | None = None) -> dict:
    """Append a new policy version (setup and tests; the Admin route publishes through publish_policy). It supersedes
    the previous version and every quote issued under it."""
    policy, reason = checked_policy(body), checked_reason(reason)
    with accounts.writing() as connection:
        _insert_policy(connection, policy, actor, reason, moment)
        return _current_policy(connection)


def checked_key(key: object) -> str:
    """An idempotency key: 8 to 80 ASCII letters, digits, - or _, new for each deliberate submission."""
    if not isinstance(key, str) or not 8 <= len(key) <= 80 or not key.isascii() or \
            not key.replace("-", "").replace("_", "").isalnum():
        raise AccountsRefused(422, "invalid_request", "idempotency_key must be 8 to 80 letters, digits, - or _")
    return key


def earlier_publication(connection: sqlite3.Connection, kind: str, key: str, actor: str, digest: str) -> dict | None:
    """The publication an idempotency key already made: None when the key is new. A key is bound to the administrator
    who used it and to the canonical payload: any other use is refused and writes nothing (QA-5)."""
    row = connection.execute("SELECT * FROM publications WHERE kind = ? AND idempotency_key = ?", (kind, key)).fetchone()
    if row is None:
        return None
    if row["actor"] != actor or row["payload_sha256"] != digest:
        raise AccountsRefused(409, "idempotency_conflict", "This submission's key was already used for another "
                                                           "publication. Nothing was published; reload the page and "
                                                           "submit again.")
    return dict(row)


def publish_policy(accounts: Accounts, body: object, actor: str, reason: object, key: object,
                   moment: datetime | None = None) -> tuple[dict, dict, bool]:
    """One explicit publication of a credit policy version, once per idempotency key: (the version this key published,
    the current version, created). A double click or a lost reply repeats the key and publishes nothing more; a new
    intent sends a new key. It supersedes the previous version and every quote issued under it."""
    policy, reason, key = checked_policy(body), checked_reason(reason), checked_key(key)
    digest = hashlib.sha256(canonical({"policy": policy, "reason": reason}).encode("utf-8")).hexdigest()
    with accounts.writing() as connection:
        earlier = earlier_publication(connection, "credit_policy", key, actor, digest)
        created = earlier is None
        version = _insert_policy(connection, policy, actor, reason, moment) if created else earlier["version"]
        if created:
            connection.execute("INSERT INTO publications (kind, idempotency_key, actor, payload_sha256, version, at) "
                               "VALUES ('credit_policy', ?, ?, ?, ?, ?)", (key, actor, digest, version,
                                                                            stamp(moment or now())))
        published = _policy_row(connection.execute("SELECT * FROM credit_policies WHERE policy_version = ?",
                                                   (version,)).fetchone())
        return published, _current_policy(connection), created


def offered_efforts(policy: dict | None, model: str) -> list[str]:
    """The levels a user may choose: verified for the model and enabled by the current policy for that model."""
    if policy is None or policy["model"] != model:
        return []
    return [effort for effort in EFFORT_ORDER if effort in policy["efforts"] and effort in PROVIDER_EFFORTS.get(model, ())]


def credits_for(policy: dict, effort: str, input_tokens_assumed: int, max_tokens: int) -> int:
    rates = policy["credits"]
    return (rates["base"] + math.ceil(input_tokens_assumed / 1000) * rates["per_1k_input_tokens"]
            + math.ceil(max_tokens / 1000) * rates["per_1k_output_tokens"] + policy["efforts"][effort]["extra_credits"])


# ---------------------------------------------------------------- daily limits and quota days

def quota_day(moment: datetime, zone: str) -> str:
    return moment.astimezone(ZoneInfo(zone)).date().isoformat()


def day_start(day: date, zone: str) -> datetime:
    """The first instant of a calendar day in a zone, in UTC. Midnight that a transition skips maps to the
    transition itself, and midnight that repeats to its first occurrence, so every day is covered exactly once."""
    return datetime.combine(day, time(0), tzinfo=ZoneInfo(zone)).astimezone(timezone.utc)


def next_reset(moment: datetime, zone: str) -> datetime:
    return day_start(moment.astimezone(ZoneInfo(zone)).date() + timedelta(days=1), zone)


def _daily_limit(connection: sqlite3.Connection, user_id: str) -> int | None:
    row = connection.execute("SELECT daily_limit FROM daily_limits WHERE user_id = ? ORDER BY limit_id DESC LIMIT 1",
                             (user_id,)).fetchone()
    return row["daily_limit"] if row else None


def _used_on(connection: sqlite3.Connection, user_id: str, day: str) -> int:
    return connection.execute(
        "SELECT COUNT(*) FROM attempts a WHERE a.user_id = ? AND a.quota_day = ? AND NOT EXISTS "
        "(SELECT 1 FROM resolutions r WHERE r.attempt_id = a.attempt_id AND r.slot_released = 1)",
        (user_id, day)).fetchone()[0]


def set_daily_limit(accounts: Accounts, user_id: str, limit: object, actor: str, reason: object,
                    moment: datetime | None = None) -> dict:
    limit, reason = _count(limit, "limit", 0, 10_000), checked_reason(reason)
    with accounts.writing() as connection:
        user = connection.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None or user["role"] != "user":
            raise AccountsRefused(404, "not_found", "Unknown user account")
        refuse_unapproved(connection, user_id)
        connection.execute("INSERT INTO daily_limits (user_id, daily_limit, set_at, set_by, reason) "
                           "VALUES (?, ?, ?, ?, ?)", (user_id, limit, stamp(moment or now()), actor, reason))
    return {"user_id": user_id, "daily_limit": limit}


def daily_view(connection: sqlite3.Connection, user_id: str, moment: datetime) -> dict:
    zone = current_timezone(connection)  # Fixed once a run exists (accounts.set_quota_timezone).
    day = quota_day(moment, zone)
    limit, used = _daily_limit(connection, user_id), _used_on(connection, user_id, day)
    return {"timezone": zone, "day": day, "limit": limit, "used": used,
            "remaining": None if limit is None else max(0, limit - used),
            "resets_at": stamp(next_reset(moment, zone))}


# ---------------------------------------------------------------- the ledger

def _balance(connection: sqlite3.Connection, user_id: str) -> dict:
    sums = dict(connection.execute(
        "SELECT kind, COALESCE(SUM(amount), 0) FROM ledger WHERE user_id = ? GROUP BY kind", (user_id,)).fetchall())
    held = connection.execute(
        "SELECT COALESCE(SUM(credits), 0) FROM attempts a WHERE a.user_id = ? AND NOT EXISTS "
        "(SELECT 1 FROM resolutions r WHERE r.attempt_id = a.attempt_id)", (user_id,)).fetchone()[0]
    charged = connection.execute(
        "SELECT COALESCE(SUM(r.credits_charged), 0) FROM resolutions r JOIN attempts a ON a.attempt_id = r.attempt_id "
        "WHERE a.user_id = ?", (user_id,)).fetchone()[0]
    available = sum(sums.values())
    return {"available": available, "held": held, "granted": sums.get("grant", 0),
            "corrections": sums.get("correction", 0), "charged": charged,
            "reconciles": sums.get("grant", 0) + sums.get("correction", 0) - charged - held == available}


def balance(accounts: Accounts, user_id: str) -> dict:
    with accounts.reading() as connection:
        return _balance(connection, user_id)


def add_credits(accounts: Accounts, user_id: str, kind: object, amount: object, actor: str, reason: object,
                key: object, moment: datetime | None = None) -> tuple[dict, bool]:
    """An admin grant (a positive amount) or correction (either sign, never leaving the available balance negative),
    once per idempotency key: repeating the same submission returns the entry it made."""
    reason = checked_reason(reason)
    if kind not in ("grant", "correction"):
        raise AccountsRefused(422, "invalid_request", "kind must be grant or correction")
    if isinstance(amount, bool) or not isinstance(amount, int) or abs(amount) > MAX_CREDITS or amount == 0 \
            or (kind == "grant" and amount < 0):
        raise AccountsRefused(422, "invalid_request", "credits must be a non-zero whole number (positive for a "
                                                      f"grant), at most {MAX_CREDITS} in size")
    if not isinstance(key, str) or not 8 <= len(key) <= 80 or not key.replace("-", "").replace("_", "").isalnum():
        raise AccountsRefused(422, "invalid_request", "idempotency_key must be 8 to 80 letters, digits, - or _")
    entry_key = f"admin:{key}"
    with accounts.writing() as connection:
        user = connection.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if user is None or user["role"] != "user":
            raise AccountsRefused(404, "not_found", "Unknown user account")
        refuse_unapproved(connection, user_id)
        existing = connection.execute("SELECT * FROM ledger WHERE idempotency_key = ?", (entry_key,)).fetchone()
        if existing is not None:
            if (existing["user_id"], existing["kind"], existing["amount"]) != (user_id, kind, amount):
                raise AccountsRefused(409, "invalid_request", "This idempotency key was used for another entry")
            return dict(existing), False
        if _balance(connection, user_id)["available"] + amount < 0:
            raise AccountsRefused(409, "invalid_request", "A correction cannot make the available balance negative; "
                                                          "held credits are resolved separately")
        cursor = connection.execute("INSERT INTO ledger (user_id, kind, amount, attempt_id, actor, reason, at, "
                                    "idempotency_key) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)",
                                    (user_id, kind, amount, actor, reason, stamp(moment or now()), entry_key))
        return dict(connection.execute("SELECT * FROM ledger WHERE entry_id = ?", (cursor.lastrowid,)).fetchone()), True


def ledger(accounts: Accounts, user_id: str | None = None) -> list[dict]:
    query, values = "SELECT * FROM ledger", ()
    if user_id is not None:
        query, values = query + " WHERE user_id = ?", (user_id,)
    with accounts.reading() as connection:
        return [dict(row) for row in connection.execute(query + " ORDER BY entry_id", values)]


# ---------------------------------------------------------------- quotes

def issue_quote(accounts: Accounts, *, user_id: str, request_id: str, request_sha256: str, effort: str, model: str,
                input_tokens_assumed: int, max_tokens: int, planning_estimate_usd: float,
                moment: datetime | None = None) -> dict:
    """A quote under the current policy for one prepared request. Nothing is reserved."""
    moment = moment or now()
    with accounts.writing() as connection:
        policy = _current_policy(connection)
        if policy is None:
            raise AccountsRefused(409, "no_credit_policy", "Analyses cannot be quoted yet: no credit policy is set. "
                                                           "Ask the administrator.")
        if effort not in offered_efforts(policy, model):
            raise AccountsRefused(409, "unsupported_effort", "This Effort is not offered now. Prepare the analysis "
                                                             "with one of the listed options.",
                                  efforts=offered_efforts(policy, model))
        if planning_estimate_usd > policy["max_request_usd"]:
            raise AccountsRefused(409, "request_over_budget", "This source is too long to analyse under the current "
                                                              "limits. Ask the administrator.")
        if connection.execute("SELECT 1 FROM attempts WHERE request_id = ?", (request_id,)).fetchone():
            raise AccountsRefused(409, "already_attempted", "This analysis has already been run. It is never run twice.")
        quote = {"quote_id": f"q-{secrets.token_hex(12)}", "user_id": user_id, "request_id": request_id,
                 "request_sha256": request_sha256, "effort": effort, "policy_version": policy["policy_version"],
                 "credits": credits_for(policy, effort, input_tokens_assumed, max_tokens),
                 "input_tokens_assumed": input_tokens_assumed, "max_tokens": max_tokens,
                 "planning_estimate_usd": planning_estimate_usd, "issued_at": stamp(moment),
                 "expires_at": stamp(moment + timedelta(seconds=policy["quote_valid_seconds"]))}
        connection.execute(f"INSERT INTO quotes ({', '.join(quote)}) VALUES ({', '.join('?' * len(quote))})",
                           tuple(quote.values()))
    return quote


def quote_state(connection: sqlite3.Connection, quote: dict, moment: datetime, model: str) -> str:
    if connection.execute("SELECT 1 FROM attempts WHERE quote_id = ?", (quote["quote_id"],)).fetchone():
        return "used"
    policy = _current_policy(connection)
    if policy is None or policy["policy_version"] != quote["policy_version"] or \
            quote["effort"] not in offered_efforts(policy, model):
        return "superseded"
    return "expired" if moment >= datetime.fromisoformat(quote["expires_at"]) else "active"


def latest_quote(accounts: Accounts, user_id: str, request_id: str, moment: datetime, model: str) -> dict | None:
    with accounts.reading() as connection:
        row = connection.execute("SELECT * FROM quotes WHERE user_id = ? AND request_id = ? "
                                 "ORDER BY issued_at DESC, rowid DESC LIMIT 1", (user_id, request_id)).fetchone()
        return None if row is None else {**dict(row), "state": quote_state(connection, dict(row), moment, model)}


# ---------------------------------------------------------------- reservations and resolutions

def reserve(accounts: Accounts, *, user_id: str, quote_id: object, request_id: str, request_sha256: str, model: str,
            effort: object, credits: object, moment: datetime | None = None) -> tuple[dict, bool]:
    """Reserve the quoted credits, today's daily slot and the request's one attempt, in one transaction, after
    rechecking everything. Returns (attempt, duplicate): a repeat of an approval whose quote already reserved returns
    that attempt and changes nothing."""
    moment = moment or now()
    mismatch = AccountsRefused(409, "quote_mismatch", "The approval does not match the quote. Reload and approve the "
                                                      "quote shown.")
    with accounts.writing() as connection:
        quote = connection.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone() \
            if isinstance(quote_id, str) else None
        if quote is None or quote["user_id"] != user_id or quote["request_id"] != request_id:
            raise mismatch
        if (effort, credits) != (quote["effort"], quote["credits"]) or quote["request_sha256"] != request_sha256:
            raise mismatch
        made = connection.execute("SELECT * FROM attempts WHERE quote_id = ?", (quote_id,)).fetchone()
        if made is not None:
            return dict(made), True
        if connection.execute("SELECT 1 FROM attempts WHERE request_id = ?", (request_id,)).fetchone():
            raise AccountsRefused(409, "already_attempted", "This analysis has already been run. It is never run "
                                                            "twice.")
        if moment >= datetime.fromisoformat(quote["expires_at"]):
            raise AccountsRefused(409, "quote_expired", "This quote has expired. Ask for a new quote; nothing was "
                                                        "reserved.")
        policy = _current_policy(connection)
        if policy is None or policy["policy_version"] != quote["policy_version"] or \
                quote["effort"] not in offered_efforts(policy, model):
            raise AccountsRefused(409, "quote_superseded", "The credit terms changed since this quote. Ask for a new "
                                                           "quote; nothing was reserved.")
        active = connection.execute("SELECT active FROM users WHERE user_id = ?", (user_id,)).fetchone()
        if active is None or not active["active"]:
            raise AccountsRefused(403, "forbidden", "This account is not active.")
        daily = daily_view(connection, user_id, moment)
        if daily["limit"] is None:
            raise AccountsRefused(409, "no_daily_limit", "No daily analysis limit is set for your account yet. Ask "
                                                         "the administrator.")
        if daily["used"] >= daily["limit"]:
            raise AccountsRefused(409, "daily_limit_reached", "You have used today's analysis allowance. It resets "
                                                              "at the time shown.", daily=daily,
                                  resets_at=daily["resets_at"])
        held = _balance(connection, user_id)
        if held["available"] < quote["credits"]:
            raise AccountsRefused(409, "insufficient_credits", "You do not have enough credits for this quote. "
                                                               "Nothing was reserved.",
                                  credits={"available": held["available"], "held": held["held"]})
        attempt = {"attempt_id": f"a-{secrets.token_hex(10)}", "user_id": user_id, "request_id": request_id,
                   "quote_id": quote_id, "effort": quote["effort"], "credits": quote["credits"],
                   "quota_day": daily["day"], "quota_timezone": daily["timezone"], "reserved_at": stamp(moment),
                   "pid": pid()}
        connection.execute(f"INSERT INTO attempts ({', '.join(attempt)}) VALUES ({', '.join('?' * len(attempt))})",
                           tuple(attempt.values()))
        connection.execute("INSERT INTO ledger (user_id, kind, amount, attempt_id, actor, reason, at, idempotency_key) "
                           "VALUES (?, 'hold', ?, ?, ?, ?, ?, ?)",
                           (user_id, -quote["credits"], attempt["attempt_id"], user_id,
                            f"credits reserved for an approved analysis run (quote {quote_id})", stamp(moment),
                            f"hold:{attempt['attempt_id']}"))
    return attempt, False


def mark_sent(accounts: Accounts, attempt_id: str, moment: datetime | None = None) -> bool:
    """Record that the send is starting, unless the attempt was already resolved (then nothing may be sent)."""
    with accounts.writing() as connection:
        if connection.execute("SELECT 1 FROM resolutions WHERE attempt_id = ?", (attempt_id,)).fetchone():
            return False
        connection.execute("INSERT INTO attempt_sends VALUES (?, ?)", (attempt_id, stamp(moment or now())))
    return True


def record_outcome(accounts: Accounts, attempt_id: str, outcome: str, moment: datetime | None = None) -> None:
    with accounts.writing() as connection:
        connection.execute("INSERT OR IGNORE INTO attempt_outcomes VALUES (?, ?, ?)",
                           (attempt_id, outcome, stamp(moment or now())))


def resolve(accounts: Accounts, attempt_id: str, kind: str, credits_charged: int, actor: str, reason: str,
            moment: datetime | None = None, *, unsent_only: bool = False) -> tuple[dict, bool]:
    """Resolve an attempt once: "charged" (0 to the reserved credits, the daily slot kept) or "returned" (nothing
    charged, the slot released). A second resolution returns the first. ``unsent_only`` refuses an attempt whose send
    started: only an attempt the store shows as never sent may be returned without an administrator."""
    moment = moment or now()
    with accounts.writing() as connection:
        attempt = connection.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if attempt is None:
            raise AccountsRefused(404, "not_found", "Unknown attempt")
        existing = connection.execute("SELECT * FROM resolutions WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if existing is not None:
            return dict(existing), False
        if unsent_only and connection.execute("SELECT 1 FROM attempt_sends WHERE attempt_id = ?",
                                              (attempt_id,)).fetchone():
            raise AccountsRefused(409, "invalid_request", "This attempt was sent; only an administrator resolves it")
        return _apply(connection, attempt, kind, credits_charged, actor, reason, moment), True


def _apply(connection: sqlite3.Connection, attempt: sqlite3.Row, kind: str, credits_charged: object, actor: str,
           reason: str, moment: datetime) -> dict:
    """Insert the attempt's one resolution and its ledger entry, inside the caller's write transaction."""
    if kind == "returned":
        credits_charged, released, amount, entry = 0, 1, attempt["credits"], "release"
    elif kind == "charged":
        credits_charged = _count(credits_charged, "credits_charged", 0, attempt["credits"])
        released, amount, entry = 0, attempt["credits"] - credits_charged, "settle"
    else:
        raise AccountsRefused(422, "invalid_request", "A resolution is charged or returned")
    row = {"attempt_id": attempt["attempt_id"], "kind": kind, "credits_charged": credits_charged,
           "slot_released": released, "reason": reason, "actor": actor, "resolved_at": stamp(moment)}
    connection.execute(f"INSERT INTO resolutions ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                       tuple(row.values()))
    connection.execute("INSERT INTO ledger (user_id, kind, amount, attempt_id, actor, reason, at, idempotency_key) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (attempt["user_id"], entry, amount, attempt["attempt_id"], actor, reason, stamp(moment),
                        f"resolve:{attempt['attempt_id']}"))
    return row


def observed_state(record: dict) -> dict:
    """The part of an attempt's state an administrator decides on: whether its send started and what it recorded."""
    return {"sent_at": record["sent_at"], "outcome": record["outcome"]["outcome"] if record["outcome"] else None}


def resolve_reviewed(accounts: Accounts, attempt_id: str, kind: str, credits_charged: object, actor: str,
                     reason: str, observed: object, recorded_on_disk: bool, moment: datetime | None = None) -> dict:
    """An administrator's resolution of an attempt that cannot settle on its own, applied only if, in this one write
    transaction, the attempt is still unresolved, still in the state the administrator decided on (``observed``:
    send start and recorded outcome) and eligible: an outcome is recorded, or STALE_AFTER has passed since it was
    reserved or sent. The caller holds the attempt's execution lock, so no worker can send or record meanwhile.
    Refusals report the actual state: already_resolved (with the existing resolution), state_changed (with the
    current state) or in_flight."""
    moment = moment or now()
    with accounts.writing() as connection:
        attempt = connection.execute("SELECT * FROM attempts WHERE attempt_id = ?", (attempt_id,)).fetchone()
        if attempt is None:
            raise AccountsRefused(404, "not_found", "Unknown attempt")
        record = _joined(connection, attempt)
        if record["resolution"] is not None:
            raise AccountsRefused(409, "already_resolved", "This attempt was already resolved; resolutions never "
                                  "change. Nothing new was recorded.", resolution=record["resolution"])
        current = observed_state(record)
        if observed != current:
            raise AccountsRefused(409, "state_changed", "This attempt changed since it was loaded (its send started or "
                                  "an outcome was recorded). Nothing was recorded; reload before deciding.",
                                  current=current)
        started = datetime.fromisoformat(record["sent_at"] or record["reserved_at"])
        if record["outcome"] is None and not recorded_on_disk and moment - started < STALE_AFTER:
            raise AccountsRefused(409, "in_flight", "This attempt may still be in flight. Nothing was recorded.")
        return _apply(connection, attempt, kind, credits_charged, actor, reason, moment)


def attempt_record(accounts: Accounts, *, request_id: str | None = None, attempt_id: str | None = None) -> dict | None:
    """One attempt with its quote, send, outcome and resolution, or None."""
    column, value = ("request_id", request_id) if request_id is not None else ("attempt_id", attempt_id)
    with accounts.reading() as connection:
        row = connection.execute(f"SELECT * FROM attempts WHERE {column} = ?", (value,)).fetchone()
        return None if row is None else _joined(connection, row)


def _joined(connection: sqlite3.Connection, row: sqlite3.Row) -> dict:
    attempt_id = row["attempt_id"]
    one = lambda table: connection.execute(f"SELECT * FROM {table} WHERE attempt_id = ?",  # noqa: E731
                                           (attempt_id,)).fetchone()
    send, outcome, resolution = one("attempt_sends"), one("attempt_outcomes"), one("resolutions")
    quote = connection.execute("SELECT * FROM quotes WHERE quote_id = ?", (row["quote_id"],)).fetchone()
    return {**dict(row), "quote": dict(quote), "sent_at": send["sent_at"] if send else None,
            "outcome": dict(outcome) if outcome else None, "resolution": dict(resolution) if resolution else None}


def attempts(accounts: Accounts, user_id: str | None = None) -> list[dict]:
    query, values = "SELECT * FROM attempts", ()
    if user_id is not None:
        query, values = query + " WHERE user_id = ?", (user_id,)
    with accounts.reading() as connection:
        return [_joined(connection, row) for row in connection.execute(query + " ORDER BY reserved_at", values)]


def aged(attempt: dict, moment: datetime) -> bool:
    """An unresolved attempt without a recorded outcome, reserved or sent at least STALE_AFTER ago. Age only: whether a
    worker still holds it is attempt_locks.active."""
    started = attempt["sent_at"] or attempt["reserved_at"]
    return attempt["resolution"] is None and attempt["outcome"] is None and \
        moment - datetime.fromisoformat(started) >= STALE_AFTER


def user_snapshot(accounts: Accounts, user_id: str, moment: datetime | None = None) -> dict:
    """The balance and today's allowance, read together, and whether an administrator has allocated credits at all
    (any grant or correction, whatever the balance now)."""
    moment = moment or now()
    with accounts.reading() as connection:
        held = _balance(connection, user_id)
        allocated = connection.execute("SELECT 1 FROM ledger WHERE user_id = ? AND kind IN ('grant', 'correction') "
                                       "LIMIT 1", (user_id,)).fetchone() is not None
        return {"credits": {"available": held["available"], "held": held["held"]},
                "daily": daily_view(connection, user_id, moment), "balance": held, "allocated": allocated}
