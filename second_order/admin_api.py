"""The administrator's routes (admin-api-0.3, docs/admin-user-contract.md section 10, docs/account-binding-contract.md
and docs/news-usage-contract.md), added to the app by create_app.

Every route needs an admin session (the app's access check refuses anyone else before a route runs). Reads only read.
Each write is one explicit action from this server's own page with the X-Second-Order-Admin header, recorded with the
acting admin, a reason and the time: accounts and their status, the decision on a registration, credit grants and
corrections (idempotent), daily limits, credit policy versions, the quota time zone, record ownership, and the
resolution of an attempt under review. A policy preview writes nothing. Nothing here sends, retries or refunds anything
on its own, and an approval grants nothing but the account's activation (docs/onboarding-contract.md).
"""
from typing import Callable

from fastapi import FastAPI, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import (accounts as acc, admin_views, attempt_locks, auth, credit_terms, entitlements, event_intake,
               registration, research_analysis as ra, usage)
from .accounts import AccountsRefused
from .analysis_flow import FlowRefused, strict_object
from .model_draft import strict_json

CONTRACT = admin_views.CONTRACT
MAX_BODY = 16_384


def _fields(body: bytes, fields: tuple[str, ...], label: str) -> dict:
    try:
        return strict_object(body, fields, label)
    except FlowRefused:
        raise auth.ContractError(422, "invalid_request", f"A {label} has exactly {', '.join(fields)}") from None


def add_routes(app: FastAPI, accounts: acc.Accounts | None, folders: ra.Folders, check_write: Callable,
               read_body: Callable, clock: Callable = acc.now) -> None:

    def admin(request: Request) -> acc.Identity:
        identity = auth.identity_of(request)
        if accounts is None:
            raise auth.ContractError(503, "accounts_unavailable")
        if identity is None or identity.role != "admin":  # The access check already refused; this is a second guard.
            raise auth.ContractError(403, "forbidden")
        return identity

    def call(action):
        try:
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    async def write(request: Request, label: str) -> tuple[acc.Identity, bytes]:
        check_write(request, auth.ADMIN_HEADER, "Administrator actions")
        identity = admin(request)
        return identity, await read_body(request, MAX_BODY, label)

    @app.get("/api/admin/users")
    def get_users(request: Request) -> dict:
        admin(request)
        return call(lambda: admin_views.users(accounts, clock())) | {
            "allocation_presets": [credit_terms.INITIAL_ALLOCATION_PRESET]}

    @app.post("/api/admin/users")
    async def post_user(request: Request) -> Response:
        identity, body = await write(request, "new account")
        form = _fields(body, ("username", "display_name", "role", "password"), "new account")
        created = await run_in_threadpool(call, lambda: acc.create_user(
            accounts, form["username"], form["display_name"], form["role"], form["password"], identity.user_id,
            clock()))
        return JSONResponse({"contract": CONTRACT, "user": created}, status_code=201)

    @app.post("/api/admin/users/{user_id}/status")
    async def post_status(user_id: str, request: Request) -> Response:
        identity, body = await write(request, "status change")
        form = _fields(body, ("active", "reason"), "status change")
        changed = await run_in_threadpool(call, lambda: acc.set_active(accounts, user_id, form["active"],
                                                                       identity.user_id, form["reason"], clock()))
        return JSONResponse({"contract": CONTRACT, "user": changed})

    @app.get("/api/admin/registrations")
    def get_registrations(request: Request, status: str | None = Query(default=None)) -> dict:
        admin(request)
        if status is not None and status not in ("pending", "rejected", "active", "disabled"):
            raise auth.ContractError(422, "invalid_request", "status must be pending, rejected, active or disabled")
        return {"contract": CONTRACT, "registrations": call(lambda: registration.registrations(accounts, status))}

    @app.post("/api/admin/registrations/{user_id}/decision")
    async def post_decision(user_id: str, request: Request) -> Response:
        """Approve or reject one registration, once, with a reason. Approval activates the account and nothing else."""
        identity, body = await write(request, "registration decision")
        form = _fields(body, ("decision", "reason"), "registration decision")
        user = await run_in_threadpool(call, lambda: registration.decide(accounts, user_id, form["decision"],
                                                                         identity.user_id, form["reason"], clock()))
        return JSONResponse({"contract": CONTRACT, "applied": True, "user": user}, status_code=201)

    @app.post("/api/admin/users/{user_id}/credits")
    async def post_credits(user_id: str, request: Request) -> Response:
        identity, body = await write(request, "ledger entry")
        form = _fields(body, ("kind", "credits", "reason", "idempotency_key"), "ledger entry")
        entry, created = await run_in_threadpool(call, lambda: entitlements.add_credits(
            accounts, user_id, form["kind"], form["credits"], identity.user_id, form["reason"],
            form["idempotency_key"], clock()))
        return JSONResponse({"contract": CONTRACT, "entry": entry, "created": created,
                             "balance": entitlements.balance(accounts, user_id)}, status_code=201 if created else 200)

    @app.post("/api/admin/users/{user_id}/daily-limit")
    async def post_limit(user_id: str, request: Request) -> Response:
        identity, body = await write(request, "daily limit")
        form = _fields(body, ("limit", "reason"), "daily limit")
        result = await run_in_threadpool(call, lambda: entitlements.set_daily_limit(
            accounts, user_id, form["limit"], identity.user_id, form["reason"], clock()))
        return JSONResponse({"contract": CONTRACT, **result}, status_code=201)

    @app.get("/api/admin/ledger")
    def get_ledger(request: Request, user_id: str | None = Query(default=None)) -> dict:
        admin(request)
        return call(lambda: admin_views.ledger(accounts, user_id))

    @app.get("/api/admin/holds")
    def get_holds(request: Request) -> dict:
        admin(request)
        return call(lambda: admin_views.holds(folders, accounts, clock()))

    @app.post("/api/admin/attempts/{attempt_id}/resolve")
    async def post_resolution(attempt_id: str, request: Request) -> Response:
        """Resolve one attempt that holds credits and cannot settle on its own: charge 0 to its quoted credits, or
        return them (and its daily slot), once. ``observed`` repeats the state the page showed (its send start and
        recorded outcome). The attempt's execution lock is taken first, so no worker can send or record meanwhile,
        and the store rechecks state, eligibility and any earlier resolution in the same write transaction. Nothing is
        reported as saved unless it was applied."""
        identity, body = await write(request, "resolution")
        form = _fields(body, ("resolution", "credits_charged", "reason", "observed"), "resolution")

        def resolve():
            kinds = {"return": "returned", "charge": "charged"}
            if form["resolution"] not in kinds:
                raise AccountsRefused(422, "invalid_request", "resolution must be charge or return")
            if form["resolution"] == "return" and form["credits_charged"] not in (0, None):
                raise AccountsRefused(422, "invalid_request", "A return charges nothing; send credits_charged 0")
            observed = form["observed"]
            if not isinstance(observed, dict) or set(observed) != {"sent_at", "outcome"}:
                raise AccountsRefused(422, "invalid_request", "observed must repeat the attempt's sent_at and outcome "
                                                              "as loaded")
            reason = acc.checked_reason(form["reason"])
            record = entitlements.attempt_record(accounts, attempt_id=attempt_id)
            if record is None:
                raise AccountsRefused(404, "not_found", "Unknown attempt")
            try:
                with attempt_locks.hold(accounts.lock_dir, attempt_id, wait=attempt_locks.ADMIN_WAIT):
                    on_disk = ra.attempt_state(record["request_id"], folders)["state"] == "recorded"
                    return entitlements.resolve_reviewed(
                        accounts, attempt_id, kinds[form["resolution"]],
                        0 if form["resolution"] == "return" else form["credits_charged"], identity.user_id, reason,
                        observed, on_disk, clock())
            except attempt_locks.Busy:
                raise AccountsRefused(409, "in_flight", "A worker is still running this attempt; it can be resolved "
                                                        "only after that worker has stopped. Nothing was recorded.") \
                    from None
        resolution = await run_in_threadpool(call, resolve)
        return JSONResponse({"contract": CONTRACT, "resolution": resolution, "applied": True}, status_code=201)

    @app.get("/api/admin/policy")
    def get_policy(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "current": call(lambda: entitlements.current_policy(accounts)),
                "versions": call(lambda: entitlements.policies(accounts)),
                "verified_efforts": {model: list(levels) for model, levels in entitlements.PROVIDER_EFFORTS.items()},
                "effort_source": entitlements.EFFORT_SOURCE, "output_bound_tokens": ra.MAX_TOKENS,
                "settlement": entitlements.SETTLEMENT,
                "formula": ("credits = base + ceil(input_tokens_assumed / 1000) * per_1k_input_tokens + "
                            "ceil(max_tokens / 1000) * per_1k_output_tokens + efforts[effort].extra_credits"),
                "presets": [credit_terms.PILOT_POLICY_PRESET]}

    @app.post("/api/admin/policy/preview")
    async def post_policy_preview(request: Request) -> Response:
        """What a draft policy would quote for the synthetic examples. Checked like a new version; nothing recorded."""
        _, body = await write(request, "policy preview")
        form = _fields(body, ("policy",), "policy preview")
        shown = await run_in_threadpool(call, lambda: credit_terms.preview(form["policy"]))
        return JSONResponse({"contract": CONTRACT, **shown})

    @app.post("/api/admin/policy")
    async def post_policy(request: Request) -> Response:
        identity, body = await write(request, "credit policy")
        try:
            form = strict_json(body)
        except Exception:
            form = None
        if not isinstance(form, dict) or set(form) != {"policy", "reason", "idempotency_key"}:
            raise auth.ContractError(422, "invalid_request", "A new policy version has exactly policy, reason and "
                                                             "idempotency_key")
        published, current, created = await run_in_threadpool(call, lambda: entitlements.publish_policy(
            accounts, form["policy"], identity.user_id, form["reason"], form["idempotency_key"], clock()))
        return JSONResponse({"contract": CONTRACT, "current": current, "published": published, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/usage-policy")
    def get_usage_policy(request: Request) -> dict:
        admin(request)
        bounds = {part: {name: {"min": low, "max": high} for name, (low, high) in values.items()}
                  for part, values in (("account", usage.ACCOUNT_BOUNDS), ("server", usage.SERVER_BOUNDS))}
        return {"contract": CONTRACT, "current": call(lambda: usage.current_policy(accounts)),
                "versions": call(lambda: usage.policies(accounts)), "bounds": bounds}

    @app.post("/api/admin/usage-policy")
    async def post_usage_policy(request: Request) -> Response:
        """One explicit publication of a usage policy version per idempotency key (docs/news-usage-contract.md)."""
        identity, body = await write(request, "usage policy")
        form = _fields(body, ("policy", "reason", "idempotency_key"), "usage policy")
        published, current, created = await run_in_threadpool(call, lambda: usage.publish_policy(
            accounts, form["policy"], identity.user_id, form["reason"], form["idempotency_key"], clock()))
        return JSONResponse({"contract": CONTRACT, "current": current, "published": published, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/usage")
    def get_usage(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, **call(lambda: usage.overview(accounts, folders.intake, clock()))}

    @app.get("/api/admin/settings")
    def get_settings(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "quota_timezone": call(lambda: acc.quota_timezone(accounts)),
                "fixed": call(lambda: acc.timezone_fixed(accounts)),
                "history": call(lambda: acc.settings_history(accounts))}

    @app.post("/api/admin/settings")
    async def post_settings(request: Request) -> Response:
        identity, body = await write(request, "setting")
        form = _fields(body, ("quota_timezone", "reason"), "setting")
        zone, changed = await run_in_threadpool(call, lambda: acc.set_quota_timezone(
            accounts, form["quota_timezone"], identity.user_id, form["reason"], clock()))
        return JSONResponse({"contract": CONTRACT, "quota_timezone": zone, "changed": changed},
                            status_code=201 if changed else 200)

    @app.get("/api/admin/actions")
    def get_actions(request: Request) -> dict:
        admin(request)
        return call(lambda: admin_views.actions(folders, accounts, clock()))

    @app.post("/api/admin/ownership")
    async def post_ownership(request: Request) -> Response:
        """Assign one operator capture to a user account, once, with a reason. Nothing else moves."""
        identity, body = await write(request, "ownership")
        form = _fields(body, ("kind", "record_id", "user_id", "reason"), "ownership")

        def assign():
            if form["kind"] == "capture":
                try:
                    event_intake.verified(folders.intake, str(form["record_id"]))
                except (event_intake.IntakeRefused, OSError):
                    raise AccountsRefused(404, "not_found", "Unknown or unreadable capture") from None
            return acc.assign(accounts, form["kind"], form["record_id"], form["user_id"], identity.user_id,
                              form["reason"], clock())
        assigned = await run_in_threadpool(call, assign)
        return JSONResponse({"contract": CONTRACT, "assignment": assigned}, status_code=201)
