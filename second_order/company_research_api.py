"""The FCX company page's routes (company_research_view, company_scenarios), added to the app by create_app.

GET /api/companies/fcx returns the whole view: the committed research package, with its four retained documents
verified on every read. POST /api/companies/fcx/scenario computes one scenario of the Scenarios tab on the records
verified now, and writes and stores nothing. Both are /api routes, so the app's access check keeps them to
administrators; the POST accepts only same-origin JSON from this server's own page with the scenario action header
(api.check_local_write). Nothing here fetches, calls a model or costs anything. A refusal keeps its status; a local read
error or a record that breaks while the view is built is a 500 naming the exception type only.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

from . import company_research_view, company_scenarios

SCENARIO_HEADER = "x-second-order-scenario"
SUBJECT = "Company scenarios"
MAX_BODY = 4_000


def _served(call, *args):
    try:
        return call(*args)
    except company_research_view.CompanyRefused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except OSError as exc:
        raise HTTPException(500, f"The local research files could not be read ({type(exc).__name__})") from None
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(500, f"The local research files are malformed ({type(exc).__name__})") from None


def add_routes(app: FastAPI, research: Path, sources_root: Path, check_local_write, limited_body) -> None:
    @app.get("/api/companies/fcx")
    def company_fcx() -> dict:
        return _served(company_research_view.view, research, sources_root)

    @app.post("/api/companies/fcx/scenario")
    async def company_fcx_scenario(request: Request) -> dict:
        """One scenario computed exactly on the verified records; writes nothing, stores nothing."""
        check_local_write(request, SCENARIO_HEADER, SUBJECT)
        raw = await limited_body(request, MAX_BODY, "scenario request")
        try:
            body = company_research_view._strict(raw.decode("utf-8"), "The scenario request")
        except (UnicodeDecodeError, company_research_view.CompanyRefused):
            raise HTTPException(400, "The scenario request is not one strict JSON object") from None
        return _served(company_scenarios.compute, body, research, sources_root)
