"""The News desk's update-run routes (admin-api-0.4 amendments, docs/news-stories-contract.md section 14; news_updates).

Administrators only, like every desk route. The plan, the runs and a run's report only read: nothing is requested,
sent or written. Starting a run records it. A run's refresh requests each planned source once, under the usage policy's
refresh cooldown and daily budget when the server has accounts (as the desk's own refresh), and never while another
refresh runs. A run's text retrieval requests each needed page once, counted against the server's daily publication
requests. The relevance, context and brief steps record previews and bundles and send nothing. Paid approvals,
assisted imports and publications stay the batches' own routes and commands, which the report names.
"""
import threading
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import accounts as acc, auth, news_texts, news_update_report, news_updates, news_views, usage
from .accounts import AccountsRefused

CONTRACT = auth.ADMIN_CONTRACT
PRIVATE = ("reports_before", "stories_before")


def public(run: dict) -> dict:
    """A run's record without the lists of what was held at its cutoff (kept on disk, not shown)."""
    return {key: value for key, value in run.items() if key not in PRIVATE}


def add_routes(app: FastAPI, accounts: acc.Accounts | None, desk: news_views.Desk, admin: Callable, call: Callable,
               write: Callable, clock: Callable, refreshing: threading.Lock, texting: threading.Lock,
               inbox_fetcher=None) -> None:

    @app.get("/api/admin/news/updates")
    def get_updates(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "plan": call(lambda: news_updates.plan(desk, clock())),
                "runs": call(lambda: news_updates.listing(desk))}

    @app.post("/api/admin/news/updates")
    async def post_update(request: Request) -> Response:
        identity, form = await write(request, ("label", "official", "idempotency_key"), "update run")
        run, created = await run_in_threadpool(call, lambda: news_updates.start(desk, clock(), identity.user_id, form))
        return JSONResponse({"contract": CONTRACT, "run": public(run), "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/news/updates/{run_id}")
    def get_update(run_id: str, request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "report": call(lambda: news_update_report.report(desk, run_id, clock()))}

    @app.post("/api/admin/news/updates/{run_id}/refresh")
    async def post_refresh(run_id: str, request: Request) -> Response:
        identity, _ = await write(request, (), "update refresh")
        if not refreshing.acquire(blocking=False):
            raise auth.ContractError(409, "refresh_in_progress", "A refresh is already running; wait for it to finish.")

        def run():
            news_updates.load(desk, run_id)
            reservation = usage.reserve_refresh(accounts, identity.user_id, clock()) if accounts is not None else None
            try:
                return news_updates.refresh(desk, run_id, identity.user_id, clock, inbox_fetcher)
            except (AccountsRefused, ValueError):
                if reservation is not None:  # Refused before any request: the refresh is not counted.
                    usage.release(accounts, reservation, "the update refresh did not start", clock())
                raise
        try:
            result = await run_in_threadpool(call, run)
        finally:
            refreshing.release()
        return JSONResponse({"contract": CONTRACT, "refresh": result})

    @app.post("/api/admin/news/updates/{run_id}/texts")
    async def post_texts(run_id: str, request: Request) -> Response:
        identity, _ = await write(request, (), "update text retrieval")
        if not texting.acquire(blocking=False):
            raise auth.ContractError(409, "retrieval_in_progress", "A retrieval is already running; wait for it.")

        def run():
            needed = news_updates.texts(desk, run_id, identity.user_id, clock, check=True)["requests"]
            needed = min(needed, news_texts.MAX_PER_RUN)
            reservation = usage.reserve_server_fetches(accounts, identity.user_id, needed, clock()) \
                if accounts is not None and needed else None
            try:
                done = news_updates.texts(desk, run_id, identity.user_id, clock)
            except AccountsRefused:
                if reservation is not None:
                    usage.release(accounts, reservation, "the update's text retrieval did not start", clock())
                raise
            if reservation is not None and done["requests"] < needed:  # Uncount the requests not made.
                usage.release(accounts, usage.Reservation(reservation.event_ids[done["requests"]:]),
                              "fewer publication pages were requested than reserved", clock())
            return done
        try:
            result = await run_in_threadpool(call, run)
        finally:
            texting.release()
        return JSONResponse({"contract": CONTRACT, "texts": result})

    @app.post("/api/admin/news/updates/{run_id}/relevance")
    async def post_relevance(run_id: str, request: Request) -> Response:
        identity, form = await write(request, ("method", "limit"), "update relevance batch")
        done = await run_in_threadpool(call, lambda: news_updates.relevance(desk, run_id, form["method"], form["limit"],
                                                                            identity.user_id, clock()))
        return JSONResponse({"contract": CONTRACT, "relevance": done}, status_code=201 if done["created"] else 200)

    @app.post("/api/admin/news/updates/{run_id}/context")
    async def post_context(run_id: str, request: Request) -> Response:
        identity, _ = await write(request, (), "update context")
        done = await run_in_threadpool(call, lambda: news_updates.context(desk, run_id, identity.user_id, clock()))
        return JSONResponse({"contract": CONTRACT, "context": done})

    @app.post("/api/admin/news/updates/{run_id}/briefs")
    async def post_briefs(run_id: str, request: Request) -> Response:
        identity, form = await write(request, ("method", "limit"), "update brief batch")
        done = await run_in_threadpool(call, lambda: news_updates.briefs(desk, run_id, form["method"], form["limit"],
                                                                         identity.user_id, clock()))
        return JSONResponse({"contract": CONTRACT, "briefs": done}, status_code=201 if done["created"] else 200)
