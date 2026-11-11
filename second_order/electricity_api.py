"""Routes of the electricity findings from retained EIA Table 7.6 (see electricity_insights), added to the app by
create_app.

The GET route validates the retained sources and verifies the stored result by recomputing it in memory; it never
writes or fetches. The one POST is the explicit local check, from this origin with the insights header; it contacts no
provider and costs nothing.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import electricity_insights
from .insight_api import INSIGHTS_HEADER

MAX_BODY = 1_000


def add_routes(app: FastAPI, folders: electricity_insights.Folders, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:
    def call(action):
        try:
            return action()
        except electricity_insights.ElectricityRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    @app.get("/api/insights/electricity")
    def get_electricity() -> dict:
        """The stored electricity result for the retained sources, verified. Reads only."""
        return call(lambda: electricity_insights.view(folders))

    @app.post("/api/insights/electricity/checks")
    async def post_electricity_check(request: Request) -> Response:
        """The explicit local check of the retained Table 7.6 sources. No provider, model or network is contacted."""
        check_write(request, INSIGHTS_HEADER, "Electricity findings checks")
        body = await read_body(request, MAX_BODY, "check")
        result = await run_in_threadpool(call, lambda: electricity_insights.check(body, folders, clock))
        return JSONResponse(result, status_code=201 if result["created"] else 200)
