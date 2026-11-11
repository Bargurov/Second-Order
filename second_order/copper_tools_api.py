"""The routes of the copper tools (copper_tools_view, copper_coverage, copper_scenarios), added to the app by create_app.

GET /api/tools/copper reads the whole view; GET /api/tools/copper/scenarios reads the saved records, each checked again.
POST /api/tools/copper/preview computes a scenario and the record it would save, and writes nothing. POST
/api/tools/copper/scenarios saves that record once (201, or 200 when it exists). POST /api/tools/copper/capital-charge
computes the capital-recovery panel for an entered rate and life and writes nothing (its inputs are never stored).
The whole read and the panel also read Bagdad's later statement from the FCX research folders (copper_linked); the
preview, the save and the scenarios list never do, so no fault there can reach a scenario.
Every POST accepts only same-origin JSON from this server's own page with the scenario action header
(api.check_local_write). No route fetches, calls a model or costs anything; only the save writes, and only under the
scenarios folder chosen at startup.
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import (bis_snapshot, company_research_view, copper_coverage as cc, copper_linked, copper_producers,
               copper_scenarios, copper_tools_view)
from .thesis_rules import ThesisRefused

SCENARIO_HEADER = "x-second-order-scenario"
SUBJECT = "Copper scenarios"
MAX_BODY = 16_000
PREVIEW_VERSION = "copper-scenario-preview-0.1"
SAVED_VERSION = "copper-scenario-saved-0.1"
LIST_VERSION = "copper-scenarios-0.1"
PANEL_FIELDS = {"rate_pct", "years"}
REQUEST_FIELDS = {"scenario", "year", "assumptions", "label"}


def _served(call, *args):
    try:
        return call(*args)
    except ThesisRefused as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except OSError as exc:
        raise HTTPException(500, f"The local records could not be read ({type(exc).__name__})") from None


def _request(raw: bytes, label_required: bool) -> dict:
    try:
        body = bis_snapshot._strict_json(raw.decode("utf-8"), "The scenario request")
    except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
        raise HTTPException(400, "The scenario request is not one strict JSON object") from None
    if not isinstance(body, dict):
        raise HTTPException(422, "The scenario request is a JSON object")
    for key in body:
        if cc.RECYCLING.search(str(key)):
            raise HTTPException(422, cc.RECYCLING_REFUSED)
    missing = sorted({"scenario", "year", "assumptions"} - set(body))
    if label_required and "label" not in body:
        missing.append("label")
    extra = sorted(set(body) - REQUEST_FIELDS)
    if missing or extra:
        raise HTTPException(422, "The scenario request holds exactly scenario, year, assumptions and label"
                                 + (" (a label is required to save)" if label_required else " (label optional)"))
    return body


def add_routes(app: FastAPI, inputs: Path, sources_root: Path, scenarios: Path, check_local_write, limited_body,
               clock=copper_scenarios.now, research: Path = company_research_view.RESEARCH_DIR,
               company_sources: Path = company_research_view.SOURCES_DIR) -> None:
    def state():
        catalog, digest, source_states, states, values = copper_tools_view.loaded(inputs, sources_root)
        copper_tools_view.required(catalog)
        return catalog, digest, source_states, states, values

    def listed() -> dict:
        catalog, digest, source_states, states, values = state()
        return {**copper_scenarios.read_all(scenarios, catalog, digest, values, states, source_states),
                "view_version": LIST_VERSION, "provider_called": False}

    @app.get("/api/tools/copper")
    def get_copper_tools() -> dict:
        """The copper tools: every input checked against its retained source, the published baselines, and the saved
        scenarios checked again. Reads only."""
        return _served(copper_tools_view.view, inputs, sources_root, scenarios, research, company_sources)

    @app.get("/api/tools/copper/scenarios")
    def get_copper_scenarios() -> dict:
        """The saved scenario records, each checked again on today's verified sources. Reads only."""
        return _served(listed)

    @app.post("/api/tools/copper/preview")
    async def preview_copper_scenario(request: Request) -> dict:
        """A scenario computed, with the record it would save; writes nothing."""
        check_local_write(request, SCENARIO_HEADER, SUBJECT)
        body = _request(await limited_body(request, MAX_BODY, "scenario request"), label_required=False)

        def compute():
            catalog, digest, _, _, values = state()
            result = cc.assess(values, body["scenario"], body["year"], body["assumptions"])
            record = None
            if "label" in body:
                record = copper_scenarios.build(catalog, digest, values, body["scenario"], body["year"],
                                                body["assumptions"], body["label"])
            identity = None if record is None else copper_scenarios.record_id(record)
            exists = identity is not None and (Path(scenarios) / f"{identity}.json").exists()
            return {"view_version": PREVIEW_VERSION, "result": result, "record": record, "id": identity,
                    "complete": None if record is None else copper_scenarios.complete(record),
                    "exists": exists, "written": False, "provider_called": False}
        return _served(compute)

    @app.post("/api/tools/copper/scenarios")
    async def save_copper_scenario(request: Request):
        """Save one scenario record, once: 201 when created, 200 when it already exists."""
        check_local_write(request, SCENARIO_HEADER, SUBJECT)
        body = _request(await limited_body(request, MAX_BODY, "scenario request"), label_required=True)

        def store():
            catalog, digest, source_states, states, values = state()
            record = copper_scenarios.build(catalog, digest, values, body["scenario"], body["year"],
                                            body["assumptions"], body["label"])
            status, envelope = copper_scenarios.save(scenarios, record, clock)
            checked = copper_scenarios.check(envelope, catalog, values, states, source_states)
            return status, {"view_version": SAVED_VERSION, "status": "created" if status == 201 else "unchanged",
                            "id": envelope["id"], "created_at": envelope["created_at"], "record": envelope["record"],
                            "state": checked["state"], "problems": checked["problems"], "provider_called": False}
        status, payload = _served(store)
        return JSONResponse(payload, status_code=status)

    @app.post("/api/tools/copper/capital-charge")
    async def copper_capital_charge(request: Request) -> dict:
        """The capital-recovery panel for an entered rate (percent) and life (years); writes nothing, stores nothing."""
        check_local_write(request, SCENARIO_HEADER, SUBJECT)
        raw = await limited_body(request, MAX_BODY, "panel request")
        try:
            body = bis_snapshot._strict_json(raw.decode("utf-8"), "The panel request")
        except (UnicodeDecodeError, bis_snapshot.SnapshotRefused):
            raise HTTPException(400, "The panel request is not one strict JSON object") from None
        if not isinstance(body, dict) or set(body) != PANEL_FIELDS:
            raise HTTPException(422, "The panel request holds exactly rate_pct and years, both written as text")

        def compute():
            catalog, _, _, _, values = state()
            linked = copper_linked.linked_values(copper_linked.linked(research, company_sources))
            return copper_producers.capital_charge(values | linked, body["rate_pct"], body["years"])
        return _served(compute)
