"""The headline-triage routes (see triage_plan, triage_flow and triage_recheck), added to the app by create_app.

GET routes read the saved triage requests, what each recorded and what a selection would need: no model is called,
nothing is fetched and nothing is written. Each POST is one explicit action from this origin with the triage header:
preview a selection of Inbox entries (which saves a request only when missing work needs one), re-check one recorded
response that was not accepted under the current validation policy (nothing is sent), approve one local simulated
response, and send one explicitly approved paid request (only on a server started with --enable-paid-triage).
"""
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import triage_flow, triage_plan, triage_recheck

TRIAGE_HEADER = "x-second-order-triage"


def add_routes(app: FastAPI, inbox: Path, triage: Path, senders: triage_flow.TriageSenders | None,
               check_write: Callable, read_body: Callable) -> None:
    """``inbox`` is the Event Inbox cache the selections read; ``triage`` holds the triage records. ``senders``
    (default: the local simulation only, paid triage off) is chosen at startup only."""
    senders = senders or triage_flow.TriageSenders()

    def with_triage_modes(view: dict) -> dict:  # What this server offers; offering a mode is not an approval.
        return {**view, "modes": {
            "simulated": {"enabled": True, "detail": "Local simulation: $0, no provider contacted, no model reads the "
                                                     "entries."},
            "paid": triage_flow.paid_status(senders.paid)}}

    @app.get("/api/triage")
    def get_triage_list() -> dict:
        """Saved triage requests and what each recorded: read only, no model is called and nothing is written."""
        try:
            return with_triage_modes(triage_flow.listing(triage))
        except OSError as exc:
            raise HTTPException(500, f"The saved triage requests could not be read ({type(exc).__name__})") from None

    @app.get("/api/triage/selection")
    def get_triage_selection(mode: str = "simulated", ids: list[str] = Query(default=[]),
                             reprocess: list[str] = Query(default=[])) -> dict:
        """What a selection already has and the one request (or none) its missing work needs. Reads only: no model
        is called, nothing is fetched and nothing is written."""
        try:
            return with_triage_modes(triage_plan.selection_view(ids, mode, reprocess, inbox, triage))
        except triage_flow.TriageRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The saved triage could not be read ({type(exc).__name__})") from None

    @app.post("/api/triage")
    async def post_triage(request: Request) -> Response:
        check_write(request, TRIAGE_HEADER, "Triage actions")
        body = await read_body(request, triage_flow.MAX_BODY, "triage selection")
        try:
            result = triage_plan.prepare(body, inbox, triage)
        except triage_flow.TriageRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The triage request could not be saved locally ({type(exc).__name__}); "
                                     "previewing the same selection again completes it") from None
        return JSONResponse(with_triage_modes(result), status_code=201 if result["prepared_now"] else 200)

    @app.get("/api/triage/{triage_id}")
    def get_triage(triage_id: str) -> dict:
        try:
            return with_triage_modes(triage_flow.request_view(triage_id, triage))
        except triage_flow.TriageRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None

    @app.post("/api/triage/{triage_id}/{attempt}/revalidate")
    async def post_triage_recheck(triage_id: str, attempt: str, request: Request) -> Response:
        """An explicit local re-check of one recorded response that was not accepted, under the current validation
        policy. Nothing is sent or regenerated; the outcome is recorded apart from the attempt's own files."""
        check_write(request, TRIAGE_HEADER, "Triage actions")
        body = await read_body(request, triage_flow.MAX_BODY, "local re-check")
        try:
            result = triage_recheck.revalidate(triage_id, attempt, body, triage)
        except triage_flow.TriageRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local re-check could not be recorded ({type(exc).__name__})") from None
        return JSONResponse(with_triage_modes(result), status_code=201 if result["revalidated_now"] else 200)

    @app.post("/api/triage/{triage_id}/{mode}")
    async def post_triage_response(triage_id: str, mode: str, request: Request) -> Response:
        check_write(request, TRIAGE_HEADER, "Triage actions")
        if mode not in triage_flow.MODES:
            raise HTTPException(404, "Unknown triage mode")
        if mode == "paid" and senders.paid is None:
            raise HTTPException(409, triage_flow.NOT_ENABLED)
        body = await read_body(request, triage_flow.MAX_BODY, f"{mode} approval")
        try:  # In a worker thread: a paid send can take a while, and reads must still answer.
            result = await run_in_threadpool(triage_flow.dispatch, triage_id, mode, body, senders, triage)
        except triage_flow.TriageRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:  # Raised only before the attempt is reserved; afterwards dispatch reports it.
            raise HTTPException(500, f"The {mode} attempt could not be started locally ({type(exc).__name__}); "
                                     "read the triage again before approving") from None
        return JSONResponse(with_triage_modes(result), status_code=201)
