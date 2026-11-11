"""The copper tools as served (copper-tools-view-0.2): the inputs catalogue loaded, every retained source verified on
this machine, every figure and passage located, the coverage calculator's published baselines computed, and the saved
scenario records checked. Built in memory on each read; nothing here writes, fetches or calls a model, and every reply
carries "provider_called": false.

The reply also carries "linked": Bagdad's later company statement, read from the verified FCX research
(copper_linked), all available or all withheld. The producers' comparison computes on the catalogue's verified values
and the linked values together, each Bagdad row on its own statement's figures only. Each Bagdad row's stamp is built
here from its source's metadata (the catalogue source for the earlier statement, the FCX source for the later one), so
no date is written in code. The coverage calculator and the scenario records never read the linked block.

Each figure and passage is shown with its state; a figure that is not verified shows no value and a passage that is not
verified shows no text (copper_inputs). The IEA "Copper - Refining" base-case series is shown apart, under its source's
own name, with the sheet's notes and the three things its notes leave unknown; it is never combined with mining supply
or set against demand.
"""
from pathlib import Path

from . import copper_coverage as cc, copper_inputs, copper_linked, copper_producers, copper_scenarios
from .thesis_rules import ThesisRefused

VIEW_VERSION = "copper-tools-view-0.2"
STATEMENT_TEXT = {"company_estimates": ("Company estimates", "stated"), "earlier_statement": ("Earlier statement",
                                                                                            "signed")}
CURRENT_DOCUMENT = "Freeport-McMoRan news release"
TERMS_LINE = "SEC EDGAR copy (exhibit 99.1 to Form 8-K); public filing"
SOURCE_SHOWN = ("id", "publisher", "title", "edition", "edition_date", "url", "kind", "origin", "terms",
                "retrieved_at", "sha256")
REFINING = {
    "source_name": "Copper - Refining",
    "sheet_title": "Total supply for key energy transition minerals, base case (kt)",
    "notes": list(cc.NOTE_IDS),
    "unknowns": ["Whether the figures are expected output or are built from project capacities.",
                 "Whether they include refining of scrap (secondary refined copper).",
                 "Whether they are checked against the concentrate and scrap that would feed them."],
    "interpretation": "Refined copper made from mined copper is the same metal one stage later, so the refining and "
                      "mining series are never added. Because this series' basis and its treatment of feed are not "
                      "stated, it is never set against demand and no refined balance is derived from it.",
}
CONTROLS = [
    {"id": "ev", "label": "Copper used in electric vehicles", "unit": "kt",
     "meaning": "Copper the IEA counts in its Electric vehicles row for the year, world. It is not vehicle sales or the "
                "vehicle stock; the workbook does not say whether the row covers chargers.",
     "options": ["scenario", "value"], "not_offered": "Vehicles times copper per vehicle: neither is retained."},
    {"id": "networks", "label": "Copper used in electricity networks", "unit": "kt",
     "meaning": "The IEA Electricity networks row, world. The published wider direct current (DC) technology case is "
                "offered for the Stated Policies and High Demand scenarios; it has no Current Policies values.",
     "options": ["scenario", "technology_case", "value"],
     "not_offered": "Kilometres of line, grid spending or copper per kilometre: none is retained."},
    {"id": "mine", "label": "Counted mine supply adjustment", "unit": "kt",
     "meaning": "A change to the IEA's counted mine supply for the year: a signed change in kt, or a factor for one or "
                "more countries. Company disclosures are shown beside it as reference magnitudes, never as defaults.",
     "options": ["total", "countries"], "not_offered": "Years of mine delay: no retained figure turns years into "
                                                        "tonnes."},
]
NOT_COMPUTED = ["A balance of supply and demand, or a surplus or deficit: no retained material gives one stage basis, "
                "complete supply and stock changes for the world.",
                "Weeks of consumption: they would only restate such a balance.",
                "Recycling: not an input in this version; the IEA does not state which demand basis its figures use.",
                "Any price, or any direction of a price."]


def _figures(catalog: dict, states: dict) -> dict:
    sources = copper_inputs.source_of(catalog)
    out = {}
    for item in catalog["figures"]:
        state = states[item["id"]]
        verified = state["state"] == "verified"
        out[item["id"]] = {"id": item["id"], "source": item["source"], "measure": item["measure"],
                           "unit": item["unit"], "year": item["year"], "scenario": item["scenario"],
                           "where": copper_inputs.place(item, sources[item["source"]]["kind"]),
                           "state": state["state"], "problem": state["problem"],
                           "value": item["value"] if verified else None,
                           "as_shown": item["as_shown"] if verified else None}
    return out


def _passages(catalog: dict, states: dict) -> dict:
    sources = copper_inputs.source_of(catalog)
    out = {}
    for item in catalog["passages"]:
        state = states[item["id"]]
        locator = item["locator"]
        out[item["id"]] = {"id": item["id"], "source": item["source"],
                           "where": copper_inputs.place(item, sources[item["source"]]["kind"]),
                           "state": state["state"], "problem": state["problem"],
                           "text": (locator.get("quote") or locator.get("text"))
                           if state["state"] == "verified" else None}
    return out


def statement(item: dict | None, catalog: dict, block: dict) -> dict | None:
    """A Bagdad row's stamp: its kind's words, and the date and document of the source its statement rests on."""
    if item is None:
        return None
    text, date_text = STATEMENT_TEXT[item["kind"]]
    if item["kind"] == "earlier_statement":
        figure = next(entry for entry in catalog["figures"] if entry["id"] == item["source_of"])
        source = copper_inputs.source_of(catalog)[figure["source"]]
        return {"kind": item["kind"], "text": text, "date_text": date_text, "date": source["edition_date"],
                "document": source["title"], "source": source["id"], "terms": None}
    sid = block["records"][item["source_of"]]["source"]
    return {"kind": item["kind"], "text": text, "date_text": date_text,
            "date": block["sources"].get(sid, {}).get("date"), "document": CURRENT_DOCUMENT, "source": sid,
            "terms": TERMS_LINE}


def producers(catalog: dict, values: dict, block: dict) -> dict:
    """The producer comparison on the catalogue's and the linked values, with each Bagdad row's stamp."""
    comparison = copper_producers.comparison(values | copper_linked.linked_values(block))
    for project in comparison["projects"]:
        project["statement"] = statement(project["statement"], catalog, block)
    return comparison


def loaded(inputs: Path, sources_root: Path) -> tuple[dict, str, dict, dict, dict]:
    """(catalogue, its SHA-256, source states, item states, verified values). Reads only."""
    catalog, digest = copper_inputs.load_catalog(inputs)
    source_states, states = copper_inputs.check_items(catalog, sources_root)
    return catalog, digest, source_states, states, copper_inputs.verified_values(catalog, states)


def required(catalog: dict) -> None:
    """The catalogue holds exactly the figures and passages the tools read; anything else refuses the view."""
    figures = {item["id"] for item in catalog["figures"]}
    passages = {item["id"] for item in catalog["passages"]}
    want_figures = cc.figure_ids() | copper_producers.figure_ids()
    want_passages = set(cc.NOTE_IDS) | copper_producers.passage_ids()
    if figures != want_figures or passages != want_passages:
        missing = sorted((want_figures - figures) | (want_passages - passages))
        extra = sorted((figures - want_figures) | (passages - want_passages))
        raise ThesisRefused(500, "The copper inputs catalogue does not hold exactly what the tools read "
                                 f"(missing: {len(missing)}, not used: {len(extra)}); nothing is served")


def view(inputs: Path, sources_root: Path, scenarios: Path, research: Path, company_sources: Path) -> dict:
    """The whole read of the tools (see the module docstring)."""
    catalog, digest, source_states, states, values = loaded(inputs, sources_root)
    required(catalog)
    block = copper_linked.linked(research, company_sources)
    sources = [{**{key: source[key] for key in SOURCE_SHOWN}, **source_states[source["id"]]}
               for source in catalog["sources"]]
    counted = [state["state"] for state in states.values()]
    return {
        "view_version": VIEW_VERSION,
        "catalog": {"version": catalog["catalog_version"], "sha256": digest, "items": len(counted),
                    "verified": counted.count("verified")},
        "sources": sources,
        "figures": _figures(catalog, states),
        "passages": _passages(catalog, states),
        "coverage": {
            "engine_version": cc.ENGINE_VERSION, "definitions_sha256": copper_scenarios.definitions_sha256(),
            "base_year": cc.BASE_YEAR, "years": list(cc.YEARS),
            "scenarios": [{"id": key, "label": label} for key, label in cc.SCENARIOS.items()],
            "components": [{"id": key, "label": label} for key, label in cc.COMPONENTS.items()],
            "totals": [{"id": key, "label": label} for key, label in cc.TOTALS.items()],
            "countries": [{"id": key, "label": label} for key, label in cc.COUNTRIES.items()],
            "dc_scenarios": list(cc.DC_SCENARIOS), "dc_label": cc.DC_LABEL,
            "base": cc.base_year(values),
            "baselines": [cc.baseline(values, scenario, year) for scenario in cc.SCENARIOS for year in cc.YEARS],
            "refining": REFINING, "controls": CONTROLS, "flags": cc.FLAG_TEXT,
            "references": [{"id": key, "label": value["label"], "uses": list(value["uses"])}
                           for key, value in cc.REFERENCES.items()],
            "not_computed": NOT_COMPUTED},
        "producers": producers(catalog, values, block),
        "linked": block,
        "scenarios": copper_scenarios.read_all(scenarios, catalog, digest, values, states, source_states),
        "labels": {"item_states": copper_inputs.ITEM_STATES, "units": copper_inputs.UNITS,
                   "record_states": copper_scenarios.STATES},
        "provider_called": False,
    }
