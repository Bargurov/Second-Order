"""Public self-registration and the administrator's decision (docs/onboarding-contract.md, sections 1, 3 and 6).

A registration is an ordinary ``user`` account created inactive, with a ``registrations`` row beside it (see accounts):
there is no second identity or session system. It is ``pending`` until an administrator approves or rejects it, once,
with a reason. Approval only activates the account; credits, a daily limit and record ownership stay separate explicit
admin actions, refused (and blocked by triggers) until then. A pending or rejected account cannot sign in; the right
password shows its own status (accounts.sign_in). Nothing here sends a message, sets a cookie or reads a credential.

Every write is one ``BEGIN IMMEDIATE`` transaction, so concurrent signups for one username, and concurrent decisions
on one registration, are serialized: the first applies, the others see it.
"""
from datetime import datetime
import secrets

from .accounts import (Accounts, AccountsRefused, CONTROL, MAX_NAME, _account, _event, account_row, checked_password,
                       checked_reason, checked_text, checked_username, hash_password, now, password_matches,
                       registration_status, stamp)

FIELDS = ("username", "display_name", "password", "note")
MAX_NOTE = 500
SELF = "self-registration"
# Names a registrant cannot take: they read as the server's own accounts or actors.
RESERVED = frozenset({"admin", "administrator", "operator", "local-operator", "local-command", "root", "system",
                      "self-registration", "second-order"})
DECISIONS = {"approve": "approved", "reject": "rejected"}
UNAVAILABLE = "This username is not available. Choose another, or sign in if it is your account."


def _field(name: str, check, *args):
    """One field's rule; a refusal names the field (never another account)."""
    try:
        return check(*args)
    except AccountsRefused as exc:
        raise AccountsRefused(422, "invalid_registration", str(exc), field=name) from None


def _note(note: object) -> str:
    if not isinstance(note, str) or len(note) > MAX_NOTE or CONTROL.search(note):
        raise AccountsRefused(422, "invalid_registration", f"A note must be text of at most {MAX_NOTE} characters "
                                                           "without control characters (it may be empty)")
    return note.strip()


def _checked(form: dict) -> tuple[str, str, str, str]:
    return (_field("username", checked_username, form["username"]),
            _field("display_name", checked_text, form["display_name"], "A display name", MAX_NAME),
            _field("password", checked_password, form["password"]), _field("note", _note, form["note"]))


def register(accounts: Accounts, form: dict, moment: datetime | None = None) -> tuple[dict, bool]:
    """Create a pending ordinary account, or recognise a resubmission. Returns (the registrant's status, duplicate).
    ``form`` has exactly FIELDS (the route checks the body). Refusals name no other account: every taken or reserved
    username gets the same username_unavailable."""
    moment = moment or now()
    username, display_name, password, note = _checked(form)
    hashed = hash_password(password)  # Before any lookup, so the time taken does not depend on the name.
    user_id = f"u-{secrets.token_hex(8)}"
    with accounts.writing() as connection:
        existing = connection.execute("SELECT user_id, password FROM users WHERE username = ?", (username,)).fetchone()
        if existing is not None:
            row = account_row(connection, existing["user_id"])
            if row["submitted_at"] is not None and row["decision"] is None and \
                    password_matches(password, existing["password"]):
                return registration_status(row), True
            raise AccountsRefused(409, "username_unavailable", UNAVAILABLE)
        if username in RESERVED:
            raise AccountsRefused(409, "username_unavailable", UNAVAILABLE)
        connection.execute("INSERT INTO users VALUES (?, ?, ?, 'user', ?, 0, ?, ?)",
                           (user_id, username, display_name, hashed, stamp(moment), SELF))
        connection.execute("INSERT INTO registrations VALUES (?, ?, ?)", (user_id, stamp(moment), note))
        _event(connection, user_id, "registered", "self-registration, pending approval", SELF,
               "registration submitted", moment)
        return registration_status(account_row(connection, user_id)), False


def decide(accounts: Accounts, user_id: str, decision: object, actor: str, reason: object,
           moment: datetime | None = None) -> dict:
    """An administrator's one decision on a registration: approve (the account becomes active, nothing else) or reject
    (it stays inactive for good). A second decision, concurrent or later, is refused with the one that applied."""
    moment = moment or now()
    if decision not in DECISIONS:
        raise AccountsRefused(422, "invalid_request", "decision must be approve or reject")
    reason = checked_reason(reason)
    with accounts.writing() as connection:
        row = account_row(connection, user_id)
        if row is None or row["submitted_at"] is None:
            raise AccountsRefused(404, "not_found", "Unknown registration")
        if row["decision"] is not None:
            raise AccountsRefused(409, "already_decided", "This registration was already decided; decisions never "
                                  "change. Nothing new was recorded.",
                                  decision=_account(row)["registration"]["decision"])
        kind = DECISIONS[decision]
        connection.execute("INSERT INTO registration_decisions VALUES (?, ?, ?, ?, ?)",
                           (user_id, kind, actor, reason, stamp(moment)))
        if kind == "approved":
            connection.execute("UPDATE users SET active = 1 WHERE user_id = ?", (user_id,))
        _event(connection, user_id, kind, "registration decision", actor, reason, moment)
        return _account(account_row(connection, user_id))


def registrations(accounts: Accounts, status: str | None = None) -> list[dict]:
    """Every registration with its decision, oldest first; optionally only one status."""
    with accounts.reading() as connection:
        rows = connection.execute("SELECT user_id FROM registrations ORDER BY submitted_at, user_id").fetchall()
        shown = [_account(account_row(connection, row["user_id"])) for row in rows]
    return [row for row in shown if status is None or row["status"] == status]
