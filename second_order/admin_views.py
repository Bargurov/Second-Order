"""The administrator's projections (admin-api-0.2, docs/admin-user-contract.md section 10). Reads only.

Accounts with their balances, limits and today's use; the credit ledger with reconciling totals; the holds and the
attempts an administrator must resolve; and the actions: every evidence-first research request and attempt, the
operator's and the users', with its type, account, model, Effort, state, locally measured times, reported usage, the
planning estimate and the usage-derived cost. A usage-derived cost is a local calculation at published rates, never
verified provider billing; missing usage or cost stays null, never zero. None of this reaches a user payload.
"""
from datetime import datetime
import json

from . import accounts as acc, attempt_locks, entitlements, research_analysis as ra
from .accounts import Accounts
from .model_draft import DraftRefused, strict_json

CONTRACT = "admin-api-0.4"
COST_BASIS = ("A local calculation from the usage the provider reported, at the published rates read on the date shown "
              "with the estimate; not verified provider billing. The Console is authoritative.")
UNAVAILABLE_TIMING = ["provider processing time", "time queued at the provider", "network transfer time"]


def users(accounts: Accounts, moment: datetime) -> dict:
    rows = []
    for user in acc.list_users(accounts):
        row = dict(user)
        if user["role"] == "user":
            snapshot = entitlements.user_snapshot(accounts, user["user_id"], moment)
            row |= {"credits": snapshot["balance"], "daily": snapshot["daily"], "allocated": snapshot["allocated"]}
        rows.append(row)
    return {"contract": CONTRACT, "users": rows, "quota_timezone": acc.quota_timezone(accounts)}


def ledger(accounts: Accounts, user_id: str | None) -> dict:
    entries = entitlements.ledger(accounts, user_id)
    totals = {}
    for user in acc.list_users(accounts):
        if user["role"] == "user" and (user_id is None or user["user_id"] == user_id):
            totals[user["user_id"]] = entitlements.balance(accounts, user["user_id"])
    return {"contract": CONTRACT, "entries": entries, "totals": totals,
            "identity": "granted + corrections - charged - held = available"}


def _disk(request_id: str, folders: ra.Folders) -> dict:
    """What the attempt folder recorded: its state, and the manifest (when there is one) read as recorded."""
    state = ra.attempt_state(request_id, folders)
    manifest = None
    if state["state"] == "recorded":
        try:
            manifest = strict_json((folders.attempts / request_id / "manifest.json").read_bytes())
        except (OSError, DraftRefused):
            manifest = None
    reservation = None
    if state["state"] != "none":
        try:
            reservation = json.loads((folders.attempts / request_id / "reservation.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            reservation = None
    return {"state": state, "manifest": manifest if isinstance(manifest, dict) else None,
            "reservation": reservation if isinstance(reservation, dict) else None}


def _usage(manifest: dict | None) -> dict | None:
    response = manifest.get("response") if manifest else None
    usage = response.get("usage") if isinstance(response, dict) else None
    if not isinstance(usage, dict):
        return None
    return {key: usage.get(key) for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                                            "cache_read_input_tokens") if isinstance(usage.get(key), int)} or None


def _entitlement(record: dict | None, folders: ra.Folders, accounts: Accounts, moment: datetime) -> dict | None:
    if record is None:
        return None
    resolution = record["resolution"]
    if resolution is not None:
        state = resolution["kind"]
    else:
        state = "needs_review" if resolvable(record, folders, accounts, moment) else "held"
    return {"attempt_id": record["attempt_id"], "quote_id": record["quote_id"], "credits_quoted": record["credits"],
            "credits_charged": resolution["credits_charged"] if resolution else None,
            "quota_day": record["quota_day"], "quota_timezone": record["quota_timezone"], "state": state,
            "sent_recorded_at": record["sent_at"], "outcome": record["outcome"], "resolution": resolution,
            "worker_active": attempt_locks.active(accounts.lock_dir, record["attempt_id"]),
            "observed": entitlements.observed_state(record),
            "quote": {key: record["quote"][key] for key in ("policy_version", "issued_at", "expires_at",
                                                            "planning_estimate_usd", "input_tokens_assumed",
                                                            "max_tokens")}}


def action_row(request_id: str, folders: ra.Folders, accounts: Accounts | None, names: dict[str, dict],
               moment: datetime) -> dict:
    try:
        verified = ra.verified_request(request_id, folders)
    except (ra.FlowRefused, OSError) as exc:
        return {"request_id": request_id, "action": "unreadable", "problem": str(exc)}
    request = verified["request"]
    disk = _disk(request_id, folders)
    manifest, reservation = disk["manifest"], disk["reservation"]
    mode = disk["state"]["mode"]
    owner = verified["prepared_by"]
    record = entitlements.attempt_record(accounts, request_id=request_id) if accounts and owner else None
    estimate = ra.research_cost(verified["request_bytes"])
    cost = manifest.get("estimated_cost") if manifest and isinstance(manifest.get("estimated_cost"), dict) else None
    action = "provider_call" if mode == "paid" else "local_mock" if mode == "mock" else "prepare"
    account = names.get(owner) if owner else None
    return {
        "request_id": request_id, "capture_id": verified["capture_id"], "action": action,
        "charge_kind": {"provider_call": "provider call (billed by the provider)",
                        "local_mock": "local mock: no provider contacted, $0",
                        "prepare": "local preparation: nothing sent, no charge"}[action],
        "requested_by": ({"kind": "user", "user_id": owner, "username": account["username"] if account else None,
                          "display_name": account["display_name"] if account else None} if owner
                         else {"kind": "operator"}),
        "request_version": verified["request_version"], "model": request.get("model"), "effort": verified["effort"],
        "max_tokens": request.get("max_tokens"), "request_sha256": verified["request_sha256"],
        "attempt_state": disk["state"]["state"],
        "outcome": manifest.get("outcome") if manifest else None,
        "timing": {"prepared_at": verified["manifest"]["prepared_at"],
                   "reserved_at": (manifest or reservation or {}).get("reserved_at"),
                   "sent_at": (manifest or {}).get("sent_at") or disk["state"]["sent_at"],
                   "received_at": (manifest or {}).get("received_at"),
                   "elapsed_seconds": (manifest or {}).get("elapsed_seconds"),
                   "measured_by": "this server's clock, from just before the send to the reply's arrival",
                   "unavailable": UNAVAILABLE_TIMING},
        "usage": _usage(manifest),
        "http_status": (manifest or {}).get("http_status"),
        "provider_request_id": (manifest or {}).get("request_id_provider"),
        "planning_estimate_usd": (manifest or {}).get("planning_estimate_usd") if mode == "paid"
        else estimate["estimated_real_run_if_output_reaches_max_usd"],
        "planning_estimate_basis": estimate["caveat"],
        "usage_cost_usd": cost.get("usd") if cost else None,
        "usage_cost_basis": (cost.get("basis") if mode == "mock" else COST_BASIS) if cost else None,
        "entitlement": _entitlement(record, folders, accounts, moment) if record else None,
    }


def actions(folders: ra.Folders, accounts: Accounts | None, moment: datetime) -> dict:
    names = {user["user_id"]: user for user in acc.list_users(accounts)} if accounts else {}
    folder = folders.requests
    rows = [action_row(path.name, folders, accounts, names, moment)
            for path in (sorted(folder.iterdir()) if folder.is_dir() else [])
            if ra.REQUEST_ID_PATTERN.fullmatch(path.name)]
    rows.sort(key=lambda row: (row.get("timing") or {}).get("prepared_at") or "", reverse=True)
    return {"contract": CONTRACT, "flow": entitlements.FLOW, "actions": rows,
            "note": ("Every evidence-first research request and attempt, the operator's and the users'. Costs are "
                     "local calculations, not verified billing; a missing value is unknown, not zero.")}


def holds(folders: ra.Folders, accounts: Accounts, moment: datetime) -> dict:
    """Attempts still holding credits, and those an administrator must resolve."""
    names = {user["user_id"]: user for user in acc.list_users(accounts)}
    rows = []
    for record in entitlements.attempts(accounts):
        if record["resolution"] is not None:
            continue
        row = action_row(record["request_id"], folders, accounts, names, moment)
        rows.append({**row, "user_id": record["user_id"], "attempt_id": record["attempt_id"],
                     "credits": record["credits"], "reserved_at": record["reserved_at"],
                     "observed": entitlements.observed_state(record),
                     "worker_active": attempt_locks.active(accounts.lock_dir, record["attempt_id"]),
                     "resolvable": resolvable(record, folders, accounts, moment)})
    return {"contract": CONTRACT, "holds": rows}


def resolvable(record: dict, folders: ra.Folders, accounts: Accounts, moment: datetime) -> bool:
    """Whether an administrator may resolve an attempt now, as a page hint: it is unresolved, no worker holds its
    execution lock, and an outcome is recorded or it has aged past STALE_AFTER. The resolution itself checks all of
    this again under the lock and in one write transaction (admin_api, entitlements.resolve_reviewed)."""
    if record["resolution"] is not None or attempt_locks.active(accounts.lock_dir, record["attempt_id"]):
        return False
    if record["outcome"] is not None or ra.attempt_state(record["request_id"], folders)["state"] == "recorded":
        return True
    return entitlements.aged(record, moment)
