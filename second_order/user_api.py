"""The session and user routes of user-api-0.3 (docs/admin-user-contract.md and docs/account-binding-contract.md),
added to the app by create_app.

The session routes are public; the user routes need a signed-in user (the app's access check enforces it before any
route runs, and each route reads the identity it left, never a client-sent one). Reads only read. Writes need this
server's own page and the route's header (sign-in and sign-out: X-Second-Order-Session; user actions:
X-Second-Order-User). Every reply, refusals included, is in the contract's shape, and none carries a model or provider
name, money, token count, provider ID or operational log.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import accounts as acc, auth, user_research
from .accounts import Accounts, AccountsRefused
from .analysis_flow import FlowRefused, strict_object

MAX_LOGIN_BODY = 2_048
# Runs wait minutes on the provider. They run on their own threads, so they never take the threads that every other
# request (and the access check of every request) uses; more concurrent runs than this wait their turn.
RUN_THREADS = 8
RUNS = ThreadPoolExecutor(max_workers=RUN_THREADS, thread_name_prefix="second-order-run")


def add_routes(app: FastAPI, context: user_research.UserResearch | None, check_write: Callable, read_body: Callable,
               session_hours: int = acc.SESSION_HOURS) -> None:
    accounts: Accounts | None = context.accounts if context else None
    mode = "accounts" if context else "local-operator"

    def user(request: Request) -> acc.Identity:
        identity = auth.identity_of(request)
        if context is None:
            raise auth.ContractError(503, "accounts_unavailable")
        if identity is None or identity.role != "user":  # The access check already refused; this is a second guard.
            raise auth.ContractError(403, "forbidden")
        return identity

    @app.get("/api/session")
    def get_session(request: Request) -> Response:
        """Who is signed in. Without an accounts store, always the local operator (admin)."""
        if context is None:
            return JSONResponse(auth.local_operator_session())
        identity = auth.identity_of(request)
        reason = getattr(request.state, "signed_out", "") or "not_signed_in"
        response = JSONResponse(auth.session_payload(mode, identity, reason))
        if identity is None and request.cookies.get(auth.SESSION_COOKIE):
            response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.post("/api/session/login")
    async def post_login(request: Request) -> Response:
        check_write(request, auth.SESSION_HEADER, "Sign-in")
        if context is None:
            raise auth.ContractError(503, "accounts_unavailable")
        body = await read_body(request, MAX_LOGIN_BODY, "sign-in")
        try:
            form = strict_object(body, ("username", "password"), "sign-in")
        except FlowRefused:
            raise auth.ContractError(422, "invalid_request", "Sign in with exactly a username and a password.") \
                from None
        token, identity = await run_in_threadpool(acc.sign_in, accounts, form["username"], form["password"],
                                                  context.clock(), session_hours)
        previous = request.cookies.get(auth.SESSION_COOKIE)
        if previous:
            await run_in_threadpool(acc.sign_out, accounts, previous, context.clock())
        response = JSONResponse(auth.session_payload(mode, identity))
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=session_hours * 3600, path="/", httponly=True,
                            samesite="strict")
        return response

    @app.post("/api/session/logout")
    async def post_logout(request: Request) -> Response:
        check_write(request, auth.SESSION_HEADER, "Sign-out")
        if context is None:
            raise auth.ContractError(503, "accounts_unavailable")
        await read_body(request, 64, "sign-out")
        await run_in_threadpool(acc.sign_out, accounts, request.cookies.get(auth.SESSION_COOKIE), context.clock())
        response = JSONResponse(auth.session_payload(mode, None, "signed_out"))
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    def call(action):
        try:
            return action()
        except AccountsRefused as exc:
            raise auth.ContractError(exc.status, exc.code, str(exc), **exc.extra) from None

    @app.get("/api/user/account")
    def get_account(request: Request) -> dict:
        identity = user(request)
        return call(lambda: user_research.account_payload(context, identity))

    @app.get("/api/user/sources")
    def get_sources(request: Request) -> dict:
        identity = user(request)
        return call(lambda: user_research.list_sources(context, identity))

    @app.post("/api/user/sources")
    async def post_source(request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, user_research.MAX_SOURCE_BODY, "source")
        result = await run_in_threadpool(call, lambda: user_research.add_source(context, identity, body))
        return JSONResponse(result, status_code=201)

    @app.get("/api/user/sources/{source_id}")
    def get_source(source_id: str, request: Request) -> dict:
        identity = user(request)
        return call(lambda: user_research.source_detail(context, identity, source_id))

    @app.get("/api/user/analyses")
    def get_analyses(request: Request) -> dict:
        identity = user(request)
        return call(lambda: user_research.list_analyses(context, identity))

    @app.post("/api/user/analyses")
    async def post_analysis(request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, user_research.MAX_BODY, "analysis")
        result, created = await run_in_threadpool(call, lambda: user_research.prepare(context, identity, body))
        return JSONResponse(result, status_code=201 if created else 200)

    @app.get("/api/user/analyses/{analysis_id}")
    def get_analysis(analysis_id: str, request: Request) -> dict:
        identity = user(request)
        return call(lambda: user_research.read_analysis(context, identity, analysis_id))

    @app.get("/api/user/analyses/{analysis_id}/export")
    def get_export(analysis_id: str, request: Request) -> Response:
        identity = user(request)
        exported = call(lambda: user_research.export(context, identity, analysis_id))
        return JSONResponse(exported, headers={"Content-Disposition": "attachment; filename=\"analysis.json\""})

    @app.post("/api/user/analyses/{analysis_id}/quotes")
    async def post_quote(analysis_id: str, request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, 64, "quote request")
        result = await run_in_threadpool(call, lambda: user_research.quote(context, identity, analysis_id, body))
        return JSONResponse(result, status_code=201)

    @app.post("/api/user/analyses/{analysis_id}/runs")
    async def post_run(analysis_id: str, request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, 1_024, "approval")
        # On the runs' own threads: a send can take minutes, and reads such as the analysis state must still answer.
        result, duplicate = await asyncio.wrap_future(RUNS.submit(
            call, lambda: user_research.run(context, identity, analysis_id, body)))
        return JSONResponse(result, status_code=200 if duplicate else 201)

    @app.post("/api/user/analyses/{analysis_id}/reviews")
    async def post_review(analysis_id: str, request: Request) -> Response:
        check_write(request, auth.USER_HEADER, "Account actions")
        identity = user(request)
        body = await read_body(request, user_research.ra.MAX_REVIEW_BODY, "review")
        result = await run_in_threadpool(call, lambda: user_research.save_review(context, identity, analysis_id, body))
        return JSONResponse(result, status_code=201)
