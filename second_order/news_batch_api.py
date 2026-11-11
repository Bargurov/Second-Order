"""The News desk's coverage and batch routes (admin-api-0.4 amendments, docs/news-stories-contract.md section 6).

Administrators only, like every desk route: the coverage and a batch's status only read; a preview records the
batch's selection (and, for a paid batch, each item's exact request) and sends nothing; an approval sends each item's
saved request at most once, only on a server started with paid brief drafting; a publication publishes each item's
publishable version with the operator's reason, recording a review only when the operator says they read them. The
assisted path's drafts are imported from a file with ``python -m second_order news batch import`` (news_batches).
"""
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import accounts as acc, auth, news_batches, news_views

CONTRACT = auth.ADMIN_CONTRACT


def add_routes(app: FastAPI, accounts: acc.Accounts | None, desk: news_views.Desk, admin: Callable, call: Callable,
               write: Callable, story_now: Callable, clock: Callable) -> None:

    @app.get("/api/admin/news/coverage")
    def get_coverage(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "coverage": call(lambda: news_batches.coverage(desk, clock(), accounts))}

    @app.post("/api/admin/news/batches")
    async def post_batch(request: Request) -> Response:
        identity, form = await write(request, ("method", "limit", "story_ids"), "batch preview")
        story_ids = form["story_ids"]
        if story_ids is not None and (not isinstance(story_ids, list) or not all(isinstance(row, str)
                                                                                  for row in story_ids)):
            raise auth.ContractError(422, "invalid_request", "story_ids is null or a list of story IDs.")
        batch, created = await run_in_threadpool(call, lambda: news_batches.preview(
            desk, clock(), form["method"], form["limit"], story_ids, identity.user_id))
        return JSONResponse({"contract": CONTRACT, "batch": batch, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/news/batches/{batch_id}")
    def get_batch(batch_id: str, request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "batch": call(lambda: news_batches.load(desk, batch_id)),
                "status": call(lambda: news_batches.status(desk, batch_id, clock()))}

    @app.get("/api/admin/news/batches/{batch_id}/packet")
    def get_packet(batch_id: str, request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "packet": call(lambda: news_batches.packet(desk, batch_id, clock()))}

    @app.post("/api/admin/news/batches/{batch_id}/approval")
    async def post_approval(batch_id: str, request: Request) -> Response:
        identity, form = await write(request, ("batch_id", "approve_paid_requests", "estimated_max_usd_total"),
                                     "batch approval")
        done = await run_in_threadpool(call, lambda: news_batches.approve(desk, batch_id, form, story_now,
                                                                          identity.user_id, clock))
        return JSONResponse({"contract": CONTRACT, "approval": done})

    @app.post("/api/admin/news/batches/{batch_id}/publication")
    async def post_publication(batch_id: str, request: Request) -> Response:
        identity, form = await write(request, ("reason", "reviewed"), "batch publication")
        done = await run_in_threadpool(call, lambda: news_batches.publish(desk, batch_id, form, identity.user_id,
                                                                          clock))
        return JSONResponse({"contract": CONTRACT, "publication": done})

