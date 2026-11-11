"""Routes of the industry findings from retained G.17 releases (see g17_insights), added to the app by create_app.

GET routes read and verify the stored records only: they never parse sources, compute new results or write. The one
POST is the explicit local check, from this origin with the insights header; it contacts no provider and costs nothing.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import g17_insights
from .insight_api import INSIGHTS_HEADER

MAX_BODY = 1_000


def add_routes(app: FastAPI, folders: g17_insights.Folders, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:
    def call(action):
        try:
            return action()
        except g17_insights.G17Refused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    @app.get("/api/insights/g17")
    def get_g17() -> dict:
        """The latest G.17 check, its releases and selected cards. Reads only."""
        return call(lambda: g17_insights.listing(folders))

    @app.get("/api/insights/g17/tables")
    def get_g17_tables() -> dict:
        """Every comparison and revision chain of the latest G.17 check. Reads only."""
        return call(lambda: g17_insights.tables(folders))

    @app.post("/api/insights/g17/checks")
    async def post_g17_check(request: Request) -> Response:
        """The explicit local check of retained G.17 releases. No provider, model or network is contacted."""
        check_write(request, INSIGHTS_HEADER, "Industry findings checks")
        body = await read_body(request, MAX_BODY, "check")
        result = await run_in_threadpool(call, lambda: g17_insights.check(body, folders, clock))
        return JSONResponse(result, status_code=201 if result["created"] else 200)
