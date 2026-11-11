"""The public routes of onboarding-api-0.1 (docs/onboarding-contract.md), added to the app by create_app.

Both are public: anyone may read the credit terms and submit a registration. The registration is a write, so it needs
this server's own page (its Origin, same-origin fetch metadata when sent, JSON and X-Second-Order-Session: 1), like
sign-in. It creates only a pending ordinary account; it sets no cookie and starts no session. Every reply, refusals
included, is in the onboarding contract's shape and names no other account.
"""
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import auth, credit_terms, registration
from .accounts import Accounts, AccountsRefused
from .analysis_flow import FlowRefused, strict_object

CONTRACT = auth.ONBOARDING_CONTRACT
MAX_BODY = 4_096


def add_routes(app: FastAPI, accounts: Accounts | None, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:

    def store() -> Accounts:
        if accounts is None:
            raise auth.ContractError(503, "accounts_unavailable")
        return accounts

    def call(action):
        try:
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    @app.get("/api/public/credit-terms")
    def get_credit_terms() -> dict:
        """The active credit policy in points, with three synthetic examples quoted by the real formula."""
        return call(lambda: credit_terms.public_terms(store()))

    @app.post("/api/public/registrations")
    async def post_registration(request: Request) -> Response:
        check_write(request, auth.SESSION_HEADER, "Registrations")
        accounts = store()
        body = await read_body(request, MAX_BODY, "registration")
        try:
            form = strict_object(body, registration.FIELDS, "registration")
        except FlowRefused:
            raise auth.ContractError(422, "invalid_request", "A registration has exactly username, display_name, "
                                                             "password and note.") from None
        shown, duplicate = await run_in_threadpool(call, lambda: registration.register(accounts, form, clock()))
        return JSONResponse({"contract": CONTRACT, "duplicate": duplicate, "registration": shown},
                            status_code=200 if duplicate else 201)
