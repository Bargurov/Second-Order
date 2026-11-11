"""Routes of the evidence-first research analysis mode (see research_analysis), added to the app by create_app.

The GET routes read and verify the prepared research requests, their attempts and review versions; they never send,
write or repair anything. Four explicit local actions write, each from this server's own page with the research
header: prepare one capture's research request (nothing is sent), approve one local mock response ($0), send one
explicitly approved paid request (only on a server started with --enable-paid-drafts), and append a review version.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import research_analysis
from .analysis_flow import FlowRefused, MAX_FORM_BYTES
from .paid_drafts import PaidSender

RESEARCH_HEADER = "x-second-order-research"
SUBJECT = "Research-analysis actions"


def add_routes(app: FastAPI, folders: research_analysis.Folders, paid: PaidSender | None, check_write: Callable,
               read_body: Callable) -> None:
    def with_modes(shown: dict) -> dict:  # What this server offers; offering a mode is not an approval.
        return {**shown, "modes": {"mock": {"enabled": True, "detail": "Local mock: $0, no provider contacted; "
                                                                        "synthetic content for testing the workflow."},
                                   "paid": research_analysis.paid_status(paid)}}

    def call(action):
        try:
            return action()
        except FlowRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local research records could not be read or written "
                                     f"({type(exc).__name__}); check the attempt state before approving again") \
                from None

    @app.get("/api/research-analyses")
    def list_research(capture_id: str = Query(...)) -> dict:
        """The research requests prepared from one capture, each verified. Reads only."""
        return {"flow_version": research_analysis.FLOW_VERSION, "capture_id": capture_id, "provider_called": False,
                "requests": call(lambda: research_analysis.requests_for(capture_id, folders))}

    @app.post("/api/research-analyses")
    async def post_research(request: Request) -> Response:
        """Prepare one capture's research request, or show the one already prepared. Nothing is sent."""
        check_write(request, RESEARCH_HEADER, SUBJECT)
        body = await read_body(request, MAX_FORM_BYTES, "research request")

        def run():
            verified, created = research_analysis.prepare(body, folders)
            return research_analysis.show(verified["request_id"], folders), created

        shown, created = await run_in_threadpool(call, run)
        return JSONResponse({**with_modes(shown), "created": created}, status_code=201 if created else 200)

    @app.get("/api/research-analyses/{request_id}")
    def get_research(request_id: str) -> dict:
        """One research request with its cost decision, attempt state, result view and reviews. Reads only."""
        return with_modes(call(lambda: research_analysis.show(request_id, folders)))

    @app.post("/api/research-analyses/{request_id}/mock")
    async def post_research_mock(request_id: str, request: Request) -> Response:
        check_write(request, RESEARCH_HEADER, SUBJECT)
        body = await read_body(request, MAX_FORM_BYTES, "mock approval")
        result = await run_in_threadpool(call, lambda: research_analysis.dispatch_mock(request_id, body, folders))
        return JSONResponse(result, status_code=201)

    @app.post("/api/research-analyses/{request_id}/paid")
    async def post_research_paid(request_id: str, request: Request) -> Response:
        check_write(request, RESEARCH_HEADER, SUBJECT)
        if paid is None:
            raise HTTPException(409, research_analysis.NOT_ENABLED)
        body = await read_body(request, MAX_FORM_BYTES, "paid approval")
        # In a worker thread: a send can take minutes, and reads such as the attempt state must still answer.
        result = await run_in_threadpool(call, lambda: research_analysis.dispatch_paid(request_id, body, paid,
                                                                                       folders))
        return JSONResponse(result, status_code=201)

    @app.post("/api/research-analyses/{request_id}/reviews")
    async def post_research_review(request_id: str, request: Request) -> Response:
        check_write(request, RESEARCH_HEADER, SUBJECT)
        body = await read_body(request, research_analysis.MAX_REVIEW_BODY, "review")
        record = await run_in_threadpool(call, lambda: research_analysis.save_review(request_id, body, folders))
        return JSONResponse(record, status_code=201)
