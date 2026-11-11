"""Routes of the Treasury findings pilot (see insights), added to the app by create_app.

GET routes read the stored records and the retained sources only: they never extract a package, fetch or write (each
result is verified by recomputing it from its stored inputs; see insights). The one POST is the explicit local check,
from this origin with the insights header; it contacts no provider and costs nothing.
"""
import re
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import insights

INSIGHTS_HEADER = "x-second-order-insights"
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_BODY = 1_000


def add_routes(app: FastAPI, folders: insights.Folders, check_write: Callable, read_body: Callable,
               clock: Callable) -> None:
    def call(action):
        try:
            return action()
        except insights.InsightRefused as exc:
            raise HTTPException(exc.status, str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    @app.get("/api/insights")
    def get_insights() -> dict:
        """The latest check, its occasions and the retained events. Reads only."""
        return call(lambda: insights.listing(folders))

    @app.get("/api/insights/occasions/{day}")
    def get_occasion(day: str) -> dict:
        if not DAY.fullmatch(day):
            raise HTTPException(404, "Unknown date")
        return call(lambda: insights.occasion_view(day, folders))

    @app.get("/api/insights/events/{kind}/{item_id}")
    def get_event_band(kind: str, item_id: str) -> dict:
        if kind not in ("inbox", "capture"):
            raise HTTPException(404, "Unknown event kind")
        return call(lambda: insights.event_band(kind, item_id, folders))

    @app.post("/api/insights/checks")
    async def post_check(request: Request) -> Response:
        """The explicit local check of retained evidence. No provider, model or network is contacted."""
        check_write(request, INSIGHTS_HEADER, "Findings checks")
        body = await read_body(request, MAX_BODY, "check")
        result = await run_in_threadpool(call, lambda: insights.check(body, folders, clock))
        return JSONResponse(result, status_code=201 if result["created"] else 200)
