"""The News desk's relevance routes (admin-api-0.4 amendments, docs/news-stories-contract.md section 11).

Administrators only, like every desk route. The queue and a batch's status or packet only read. A preview records a
batch's selection (and, for a paid batch, each exact request) and sends nothing; an approval sends each saved request
at most once, only on a server started with paid news preparation and a key; an editor's judgement is recorded with its
reason and an idempotency key. An assistant's annotations are imported with ``python -m second_order news relevance
import`` (relevance_batches).
"""
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import auth, news_relevance, news_views, relevance_batches

CONTRACT = auth.ADMIN_CONTRACT


def add_routes(app: FastAPI, desk: news_views.Desk, admin: Callable, call: Callable, write: Callable,
               story_now: Callable, clock: Callable) -> None:

    @app.get("/api/admin/news/relevance")
    def get_queue(request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "relevance": call(lambda: relevance_batches.queue(desk, clock()))}

    @app.post("/api/admin/news/relevance/batches")
    async def post_batch(request: Request) -> Response:
        identity, form = await write(request, ("method", "limit", "story_ids", "retry_failed"), "relevance batch")
        story_ids = form["story_ids"]
        if story_ids is not None and (not isinstance(story_ids, list) or not all(isinstance(row, str)
                                                                                  for row in story_ids)):
            raise auth.ContractError(422, "invalid_request", "story_ids is null or a list of story IDs.")
        batch, created = await run_in_threadpool(call, lambda: relevance_batches.preview(
            desk, clock(), form["method"], form["limit"], story_ids, form["retry_failed"], identity.user_id))
        return JSONResponse({"contract": CONTRACT, "batch": batch, "created": created},
                            status_code=201 if created else 200)

    @app.get("/api/admin/news/relevance/batches/{batch_id}")
    def get_batch(batch_id: str, request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "batch": call(lambda: relevance_batches.load(desk, batch_id)),
                "status": call(lambda: relevance_batches.status(desk, batch_id, clock()))}

    @app.get("/api/admin/news/relevance/batches/{batch_id}/packet")
    def get_packet(batch_id: str, request: Request) -> dict:
        admin(request)
        return {"contract": CONTRACT, "packet": call(lambda: relevance_batches.packet(desk, batch_id, clock()))}

    @app.post("/api/admin/news/relevance/batches/{batch_id}/approval")
    async def post_approval(batch_id: str, request: Request) -> Response:
        identity, form = await write(request, ("batch_id", "approve_paid_requests", "estimated_max_usd_total"),
                                     "relevance batch approval")
        done = await run_in_threadpool(call, lambda: relevance_batches.approve(desk, batch_id, form, story_now,
                                                                               identity.user_id, clock))
        return JSONResponse({"contract": CONTRACT, "approval": done})

    @app.post("/api/admin/news/stories/{story_id}/relevance")
    async def post_review(story_id: str, request: Request) -> Response:
        identity, form = await write(request, ("verdict", "reason", "idempotency_key"), "relevance judgement")

        def judge():
            story = story_now(story_id)
            return news_relevance.review(desk.newsroom, story["story_id"], form, story["material"]["material_sha256"],
                                         identity.user_id, clock())
        result, created = await run_in_threadpool(call, judge)
        return JSONResponse({"contract": CONTRACT, "relevance": result, "created": created},
                            status_code=201 if created else 200)
