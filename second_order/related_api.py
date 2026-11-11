"""Routes of Related Cases (see related_cases and related_matches) and Related research (see related_research), added to
the app by create_app.

The GET routes read the committed historical cases, check a case against its retained copy when this machine has it,
verify an event's stored match by recomputing it in memory, and select an event's related-research links from local
records; they never write or fetch. The one POST is the explicit local check for one event, from this origin with the
related-cases header; it contacts no provider or model and costs nothing. Related research has no POST.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import related_cases, related_matches, related_research
from .market_context import ContextRefused

RELATED_HEADER = "x-second-order-related"


def add_routes(app: FastAPI, folders: related_matches.Folders, sources, check_write: Callable, read_body: Callable,
               clock: Callable, library=related_research.case_library.LIBRARY_DIR) -> None:
    def call(action):
        try:
            return action()
        except (related_cases.RelatedRefused, related_matches.MatchRefused, related_research.ResearchRefused,
                ContextRefused) as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    @app.get("/api/related-cases")
    def get_related_cases() -> dict:
        """The historical cases, as the case library lists them. Reads only."""
        return call(lambda: related_cases.collection_view(folders.cases))

    @app.get("/api/related-cases/events/{kind}/{event_id}")
    def get_related_match(kind: str, event_id: str) -> dict:
        """This event's stored match, verified, or the state that it was not checked. Reads only."""
        return call(lambda: related_matches.view(kind, event_id, folders))

    @app.post("/api/related-cases/events/{kind}/{event_id}/matches")
    async def post_related_match(kind: str, event_id: str, request: Request) -> Response:
        """The explicit local check. No provider, model or network is contacted."""
        check_write(request, RELATED_HEADER, "Related-case checks")
        body = await read_body(request, related_matches.MAX_BODY, "check")
        result = await run_in_threadpool(call, lambda: related_matches.check(kind, event_id, body, folders, clock))
        return JSONResponse(result, status_code=201 if result["created"] else 200)

    @app.get("/api/related-research/events/{kind}/{event_id}")
    def get_related_research(kind: str, event_id: str) -> dict:
        """This event's links to existing library content, selected now from local records. Reads only."""
        return call(lambda: related_research.view(kind, event_id, folders, library, sources))

    @app.get("/api/related-cases/{case_id}")
    def get_related_case(case_id: str) -> dict:
        """One historical case, checked against its retained copy when this machine has it. Reads only."""
        return call(lambda: related_cases.case_view(case_id, folders.cases, sources))
