"""The routes of outcome readiness, assessment, Dossier preparation and outcome retrieval (see assessment,
assessment_records and outcome_retrieval), added to the app by create_app for its one store.

GET routes read: they never import, evaluate, prepare, fetch or write. Each POST is one explicit action from this
origin with the lifecycle header: import one outcome snapshot, preview an assessment (writes nothing), approve one
assessment ("Evaluate and prepare Dossier"), prepare one stored assessment's Dossier, preview an outcome retrieval
(writes nothing), and approve one retrieval (only on a server started with market retrieval enabled).
"""
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from . import assessment, assessment_records, lifecycle, outcome_retrieval


def add_routes(app: FastAPI, folders: lifecycle.Folders | None, call: Callable, check_write: Callable,
               read_body: Callable, header: str, clock: Callable, fetcher) -> None:
    def created(result, key: str = "created") -> Response:
        return result if isinstance(result, Response) else JSONResponse(result, status_code=201 if result[key] else 200)

    async def body_of(request: Request, label: str) -> bytes:
        check_write(request, header, "Lifecycle actions")
        return await read_body(request, lifecycle.MAX_BODY, label)

    @app.get("/api/lifecycle/hypotheses/{hypothesis_id}/readiness")
    def get_readiness(hypothesis_id: str) -> dict:
        """Expected dates, outcome snapshots and packages that could serve, and recorded assessments. Reads only."""
        return call(lambda: assessment.readiness(hypothesis_id, folders, clock))

    @app.get("/api/lifecycle/hypotheses/{hypothesis_id}/assessments/{evaluation_id}")
    def get_assessment(hypothesis_id: str, evaluation_id: str) -> dict:
        return call(lambda: assessment.assessment_view(hypothesis_id, evaluation_id, folders))

    @app.get("/api/lifecycle/hypotheses/{hypothesis_id}/dossiers/{evaluation_id}")
    def get_lifecycle_dossier(hypothesis_id: str, evaluation_id: str) -> dict:
        """A prepared Dossier, verified; never evaluates, imports, prepares or fetches."""
        return call(lambda: assessment_records.dossier_view(hypothesis_id, evaluation_id, folders))

    @app.get("/api/lifecycle/assessment-actions/{action_id}")
    def get_assessment_action(action_id: str) -> dict:
        """Whether an approval recorded an assessment, for a lost reply. Reads only; nothing is sent again."""
        return call(lambda: assessment.action_state(action_id, folders))

    @app.get("/api/lifecycle/draft-links")
    def get_draft_links() -> dict:
        return call(lambda: assessment_records.draft_links(folders))

    @app.get("/api/lifecycle/retrievals/{plan_sha}/{number}")
    def get_retrieval_attempt(plan_sha: str, number: str) -> dict:
        """One outcome-retrieval attempt's records, for a lost reply. Reads only; nothing is sent again."""
        return call(lambda: outcome_retrieval.attempt_state(plan_sha, number, folders))

    @app.post("/api/lifecycle/outcome-imports")
    async def post_outcome_import(request: Request) -> Response:
        body = await body_of(request, "outcome import")
        return created(await run_in_threadpool(call, lambda: assessment.import_outcome(body, folders, clock)))

    @app.post("/api/lifecycle/assessment-preview")
    async def post_assessment_preview(request: Request) -> Response:
        """What one approval would assess and record. Writes and evaluates nothing."""
        body = await body_of(request, "preview")

        def run():
            return assessment.preview(lifecycle.strict_body(body, ("inputs",), "preview")["inputs"], folders, clock)
        result = await run_in_threadpool(call, run)
        return result if isinstance(result, Response) else JSONResponse(result)

    @app.post("/api/lifecycle/assessments")
    async def post_assessment(request: Request) -> Response:
        """Evaluate and prepare Dossier: one explicit approval of one preview."""
        body = await body_of(request, "approval")
        return created(await run_in_threadpool(call, lambda: assessment.assess(body, folders, clock)))

    @app.post("/api/lifecycle/dossier-preparations")
    async def post_dossier_preparation(request: Request) -> Response:
        """Prepare one stored assessment's Dossier; nothing is evaluated or recorded."""
        body = await body_of(request, "preparation")
        return created(await run_in_threadpool(call, lambda: assessment.prepare(body, folders, clock)))

    @app.post("/api/lifecycle/retrieval-preview")
    async def post_retrieval_preview(request: Request) -> Response:
        """The outcome-data plan for the selected hypotheses. Writes nothing and sends nothing."""
        body = await body_of(request, "retrieval preview")

        def run():
            return outcome_retrieval.plan_view(lifecycle.strict_body(body, ("hypotheses",), "retrieval preview"),
                                               folders, fetcher, clock)
        result = await run_in_threadpool(call, run)
        return result if isinstance(result, Response) else JSONResponse(result)

    @app.post("/api/lifecycle/retrievals")
    async def post_retrieval(request: Request) -> Response:
        """One approved download of the release package for the planned hypotheses."""
        body = await body_of(request, "retrieval approval")
        result = await run_in_threadpool(call, lambda: outcome_retrieval.dispatch(body, folders, fetcher, clock))
        return result if isinstance(result, Response) else JSONResponse(result, status_code=201)
