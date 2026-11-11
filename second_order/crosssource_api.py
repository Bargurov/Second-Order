"""Routes of the cross-source comparisons (see crosssource_insights), added to the app by create_app.

The GET route validates the retained sources and verifies the stored result by recomputing it in memory; it never
writes or fetches. The one POST is the explicit local computation, from this origin with the insights header; it
contacts no provider and costs nothing.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import crosssource_insights
from .insight_api import INSIGHTS_HEADER

MAX_BODY = 1_000


def add_routes(app: FastAPI, folders: crosssource_insights.Folders, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:
    def call(action):
        try:
            return action()
        except crosssource_insights.CrossSourceRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    @app.get("/api/insights/cross-source")
    def get_cross_source() -> dict:
        """The stored cross-source comparisons for the retained sources, verified. Reads only."""
        return call(lambda: crosssource_insights.view(folders))

    @app.post("/api/insights/cross-source/checks")
    async def post_cross_source_check(request: Request) -> Response:
        """The explicit local computation. No provider, model or network is contacted."""
        check_write(request, INSIGHTS_HEADER, "Cross-source comparison checks")
        body = await read_body(request, MAX_BODY, "check")
        result = await run_in_threadpool(call, lambda: crosssource_insights.check(body, folders, clock))
        return JSONResponse(result, status_code=201 if result["created"] else 200)
