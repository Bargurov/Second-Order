"""The lifecycle routes (see lifecycle and assessment), added to the app by create_app for its one research store.

GET routes read the store's state and journal, the baselines, the freezable drafts, frozen hypotheses, whether a
freeze approval froze anything, and research readiness (research_readiness: what can be frozen prospectively for a
publication date, what is missing and the next explicit action): they never import, migrate, freeze or fetch anything.
Each POST is one explicit action from this origin with the lifecycle header: upgrade an older store, import a kept H.15
package as a baseline snapshot, preview a freeze (which writes nothing) and approve one freeze, which the server stamps.
A server started without a store answers 503 on every lifecycle route. The assessment routes (see assessment_api) run
through the same ``caller``.
"""
from typing import Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import assessment, draft_catalog, lifecycle, research_readiness
from .analysis_flow import FlowRefused
from .event_intake import IntakeRefused
from .human_review import ReviewRefused

LIFECYCLE_HEADER = "x-second-order-lifecycle"


def caller(folders: lifecycle.Folders | None) -> Callable:
    """How lifecycle and assessment routes run one action: 503 without a store, each refusal as its own status."""
    def lifecycle_call(action):
        if folders is None:
            raise HTTPException(503, "This server was started without a research store; lifecycle pages need one")
        try:
            return action()
        except lifecycle.LifecycleRefused as exc:
            if exc.extra:
                return JSONResponse({"detail": str(exc), **exc.extra}, status_code=exc.status)
            raise HTTPException(exc.status, str(exc)) from None
        except (FlowRefused, IntakeRefused, ReviewRefused, draft_catalog.CatalogRefused) as exc:
            raise HTTPException(getattr(exc, "status", 409), str(exc)) from None
        except OSError as exc:
            raise HTTPException(500, f"The local records could not be read or written ({type(exc).__name__})") \
                from None

    return lifecycle_call


def add_routes(app: FastAPI, folders: lifecycle.Folders | None, call: Callable, check_write: Callable,
               read_body: Callable, clock: Callable) -> None:
    @app.get("/api/lifecycle")
    def get_lifecycle() -> dict:
        """The store's state and the journal: every frozen hypothesis with its lifecycle state. Reads only."""
        return call(lambda: assessment.journal(folders, clock))

    @app.get("/api/lifecycle/baselines")
    def get_baselines() -> dict:
        """The store's H.15 snapshots and the kept packages; nothing is imported or validated."""
        return call(lambda: lifecycle.baselines(folders))

    @app.get("/api/lifecycle/readiness")
    def get_research_readiness(published: str | None = None) -> dict:
        """What can be frozen prospectively for a publication date (default: today in New York), what is missing and
        the next explicit action. Reads only: nothing is imported, validated, frozen or fetched."""
        return call(lambda: research_readiness.report(folders, clock, research_readiness.parse_published(published)))

    @app.get("/api/lifecycle/drafts")
    def get_freezable_drafts() -> dict:
        return call(lambda: lifecycle.drafts_listing(folders))

    @app.get("/api/lifecycle/hypotheses/{hypothesis_id}")
    def get_frozen_hypothesis(hypothesis_id: str) -> dict:
        return call(lambda: lifecycle.hypothesis_view(hypothesis_id, folders))

    @app.get("/api/lifecycle/actions/{action_id}")
    def get_freeze_action(action_id: str) -> dict:
        """Whether an approval froze a hypothesis, for a lost reply. Reads only; nothing is sent again."""
        return call(lambda: lifecycle.action_state(action_id, folders))

    @app.post("/api/lifecycle/store-upgrade")
    async def post_store_upgrade(request: Request) -> Response:
        check_write(request, LIFECYCLE_HEADER, "Lifecycle actions")
        body = await read_body(request, lifecycle.MAX_BODY, "upgrade")
        result = call(lambda: lifecycle.upgrade_store(body, folders, clock))
        return result if isinstance(result, Response) else JSONResponse(result, status_code=201 if result["migrated"]
                                                                        else 200)

    @app.post("/api/lifecycle/baselines")
    async def post_baseline(request: Request) -> Response:
        check_write(request, LIFECYCLE_HEADER, "Lifecycle actions")
        body = await read_body(request, lifecycle.MAX_BODY, "import")
        result = await run_in_threadpool(call, lambda: lifecycle.import_baseline(body, folders, clock))
        return result if isinstance(result, Response) else JSONResponse(result, status_code=201 if result["created"]
                                                                        else 200)

    @app.post("/api/lifecycle/preview")
    async def post_freeze_preview(request: Request) -> Response:
        """What one approval would freeze. Writes nothing."""
        check_write(request, LIFECYCLE_HEADER, "Lifecycle actions")
        body = await read_body(request, lifecycle.MAX_BODY, "preview")

        def run():
            return lifecycle.preview(lifecycle.strict_body(body, ("inputs",), "preview")["inputs"], folders, clock)
        result = await run_in_threadpool(call, run)
        return result if isinstance(result, Response) else JSONResponse(result)

    @app.post("/api/lifecycle/freezes")
    async def post_freeze(request: Request) -> Response:
        """One explicit approval of one preview; the server stamps the freeze time."""
        check_write(request, LIFECYCLE_HEADER, "Lifecycle actions")
        body = await read_body(request, lifecycle.MAX_BODY, "approval")
        result = await run_in_threadpool(call, lambda: lifecycle.freeze(body, folders, clock))
        return result if isinstance(result, Response) else JSONResponse(result, status_code=201 if result["created"]
                                                                        else 200)
