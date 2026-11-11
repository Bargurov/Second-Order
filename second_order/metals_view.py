"""The metals comparison as served (metals-view-0.4): the two retained files (the USGS Mineral Commodity Summaries 2026
data-release CSV and the IEA Critical Minerals Dataset 2026 workbook) verified against their acquisition records on
every read, then read by metals_usgs and metals_iea. Built in memory; nothing here writes, fetches or calls a model, and
every reply carries "provider_called": false.

A part whose file is missing, changed or unreadable, or whose layout differs from what its reader understands, is
withheld: its list holds frames only (names from this code's constants, never from the file) and `problem` says why.
The other part is unaffected.
"""
from pathlib import Path

from . import (bis_snapshot, company_research_view, copper_tools_view, metals_iea, metals_iea_uses, metals_research, metals_risk, metals_usgs,
               thesis_schema, thesis_sources, thesis_view)
from .thesis_rules import ThesisRefused

# 0.2: each USGS series carries unit_issue; years under one read "less than 1". 0.3: the risk, uses and research parts.
# 0.4: research is metals-research-0.2 (each event carries `when`; an IEA figure names its base).
# 0.5: research is metals-research-0.3 (an event may cite a verified FCX passage).
VIEW_VERSION = "metals-view-0.5"
SOURCES_VERSION = "metals-sources-0.1"
METALS_DIR = thesis_sources.ROOT / "content" / "metals"
SOURCE_IDS = ("usgs-csv-2026", "iea-dataset-2026")
USGS_LAYOUT_PROBLEM = "The layout differs: the USGS file is not the layout this version reads"
USES_LAYOUT_PROBLEM = "The layout differs: the IEA workbook's demand sheets are not the layout this version reads"
THESIS_UNAVAILABLE = "The copper thesis cannot be read, so its passages are not shown"
FCX_UNAVAILABLE = "The FCX research cannot be read on this machine"
DEFAULT_PICKS = ["copper", "lithium", "cobalt", "rare-earths", "nickel", "aluminum"]


def load_sources(folder: Path) -> list[dict]:
    """The two committed source entries. 503 when the file is missing; 500 when it is not exactly the two entries."""
    path = Path(folder) / "sources.json"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ThesisRefused(503, "The metals sources file is missing; nothing is served") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise ThesisRefused(500, f"The metals sources file cannot be read ({type(exc).__name__})") from None
    try:
        data = bis_snapshot._strict_json(text, "The metals sources file")
    except Exception:
        raise ThesisRefused(500, "The metals sources file is not strict JSON") from None
    if not isinstance(data, dict) or set(data) != {"sources_version", "sources"} \
            or data["sources_version"] != SOURCES_VERSION or not isinstance(data["sources"], list):
        raise ThesisRefused(500, "The metals sources file is not the expected shape")
    sources = data["sources"]
    if not all(isinstance(item, dict) for item in sources) or [item.get("id") for item in sources] != list(SOURCE_IDS):
        raise ThesisRefused(500, "The metals sources file does not hold exactly the USGS and IEA entries")
    for item in sources:
        if set(item) != thesis_schema.SOURCE_FIELDS:
            raise ThesisRefused(500, f"The metals source {item['id']} does not hold exactly a source entry's fields")
    return sources


def _usgs_frames() -> list[dict]:
    return [{"id": metals_usgs.chapter_id(name), "chapter": name, "name": metals_usgs.display_name(name)}
            for name in metals_usgs.CHAPTER_NAMES]


def _iea_frames() -> list[dict]:
    return [{"id": key, "name": spec[0], "chapter": spec[3]} for key, spec in metals_iea.MINERALS.items()]


def _part(engine: str, state: dict, raw: bytes | None, frames: list[dict], key: str, build) -> dict:
    """One part: verified, read and built, or withheld with its problem."""
    problem, items = None, None
    if state["state"] != "verified":
        problem = state["detail"]
    else:
        try:
            items = build(raw)
        except thesis_sources.Unreadable as exc:
            problem = f"The file cannot be read: {exc}"
        except metals_usgs.UsgsRefused as exc:
            problem = USGS_LAYOUT_PROBLEM  # fixed text: a refusal message may carry file labels
        except metals_iea_uses.IeaUsesRefused:
            problem = USES_LAYOUT_PROBLEM  # fixed text, like the USGS one
        except metals_iea.IeaRefused as exc:
            problem = f"The layout differs at {exc.place}: {exc.rule}"
    if items is None:
        return {"engine": engine, "state": "withheld", "problem": problem, key: frames}
    return {"engine": engine, "state": "available", "problem": None, key: items}


def _uses_frames() -> list[dict]:
    return [{"name": name, "chapter": spec[0]} for name, spec in metals_iea_uses.MAPPING.items()]


def _unavailable(ids, problem: str) -> dict:
    return {name: {"id": name, "source": None, "title": None, "publisher": None, "edition": None,
                   "edition_date": None, "quote": None, "where": None, "state": "unavailable", "problem": problem}
            for name in ids}


def fcx_passages(ids: list[str], research: Path, company_sources: Path) -> dict[str, dict]:
    """{id: entry} for those of ``ids`` that are passages of the FCX research, in thesis_view.passages's shape: the
    source's title, issuer (publisher), form (edition) and date (edition_date), "page {page}", and `verified` when the
    document verifies, else its state (`changed`, `missing`) with the quote withheld; `unavailable` for every id when
    the research cannot be read. Reads only."""
    try:
        held = {item["id"]: item for item in company_research_view.facts_passages(research)}
        sources = {item["id"]: item for item in company_research_view.load_sources(research)}
    except company_research_view.CompanyRefused:
        return _unavailable(dict.fromkeys(ids), FCX_UNAVAILABLE)
    asked = [held[name] for name in dict.fromkeys(ids) if name in held]
    states = {sid: company_research_view.verify(sources[sid], research, company_sources)
              for sid in {item["source"] for item in asked}}
    found = {}
    for item in asked:
        source, state = sources[item["source"]], states[item["source"]]
        ok = state["state"] == "verified"
        found[item["id"]] = {"id": item["id"], "source": source["id"], "title": source["title"],
                             "publisher": source["issuer"], "edition": source["form"], "edition_date": source["date"],
                             "quote": item["quote"] if ok else None, "where": f"page {item['page']}",
                             "state": state["state"],
                             "problem": None if ok else f"{source['id']}: {state['detail']}"}
    return found


def _research(folder: Path, chapters, risk, uses, usgs_problem, uses_problem, theses: Path, sources_root: Path,
              fcx_research: Path, company_sources: Path) -> dict:
    """The research part: resolved against the figures above and the copper thesis's passages; withheld whole only when
    the notes are not the shape this version reads. An unreadable thesis leaves its passages unavailable alone."""
    engine, written = metals_research.ENGINE, metals_research.WRITTEN_BY
    try:
        content = metals_research.load(folder)
        ids = metals_research.passage_ids(content)
        try:
            found = thesis_view.passages(metals_research.THESIS, ids, Path(theses), sources_root)
        except ThesisRefused:
            found = _unavailable(ids, THESIS_UNAVAILABLE)
        passages = {f"{metals_research.THESIS}:{name}": entry for name, entry in found.items()}
        fcx_ids = [ref.split(":", 1)[1] for ref in metals_research.passage_refs(content) if ref.startswith("fcx:")]
        passages.update({f"fcx:{name}": entry for name, entry in
                         fcx_passages(fcx_ids, Path(fcx_research), Path(company_sources)).items()})
        resolved = metals_research.resolve(content, chapters, risk, uses, passages, usgs_problem=usgs_problem,
                                           uses_problem=uses_problem)
    except metals_research.ResearchRefused:
        return {"engine": engine, "state": "withheld", "problem": metals_research.RESEARCH_PROBLEM,
                "written_by": written, "metals": {}}
    return {"engine": engine, "state": "available", "problem": None, "written_by": resolved["written_by"],
            "metals": resolved["metals"]}


def view(folder: Path, sources_root: Path, theses: Path = thesis_schema.THESES_DIR,
         research: Path = company_research_view.RESEARCH_DIR,
         company_sources: Path = company_research_view.SOURCES_DIR) -> dict:
    """The whole read (see the module docstring). Reads only."""
    usgs_source, iea_source = load_sources(folder)
    states, raws = {}, {}
    for source in (usgs_source, iea_source):
        states[source["id"]], raws[source["id"]] = thesis_sources.verify(source, Path(sources_root))
    held = {}

    def usgs(raw):
        held["rows"] = thesis_sources.content(usgs_source, raw)
        return metals_usgs.read(held["rows"])

    def iea(raw):
        cells = thesis_sources.content(iea_source, raw, [metals_iea.DEMAND_SHEET, metals_iea.SUPPLY_SHEET])
        return metals_iea.read(cells[metals_iea.DEMAND_SHEET], cells[metals_iea.SUPPLY_SHEET])

    def uses_read(raw):  # its own read, so a refusal here never withholds the IEA part above
        cells = thesis_sources.content(iea_source, raw, [metals_iea_uses.BY_MINERAL, metals_iea_uses.BY_TECH])
        return metals_iea_uses.read(cells[metals_iea_uses.BY_MINERAL], cells[metals_iea_uses.BY_TECH])

    usgs_part = _part(metals_usgs.ENGINE, states[usgs_source["id"]], raws[usgs_source["id"]], _usgs_frames(),
                      "chapters", usgs)
    iea_part = _part(metals_iea.ENGINE, states[iea_source["id"]], raws[iea_source["id"]], _iea_frames(),
                     "minerals", iea)
    uses_part = _part(metals_iea_uses.ENGINE, states[iea_source["id"]], raws[iea_source["id"]], _uses_frames(),
                      "entries", uses_read)
    if usgs_part["state"] == "available":
        chapters = usgs_part["chapters"]
        risk_items = metals_risk.read(chapters, held["rows"])
        risk_part = {"engine": metals_risk.ENGINE, "state": "available", "problem": None, "chapters": risk_items}
    else:
        chapters = risk_items = None
        risk_part = {"engine": metals_risk.ENGINE, "state": "withheld", "problem": usgs_part["problem"],
                     "chapters": _usgs_frames()}
    uses_items = uses_part["entries"] if uses_part["state"] == "available" else None
    research = _research(folder, chapters, risk_items, uses_items, usgs_part["problem"], uses_part["problem"],
                         theses, Path(sources_root), research, company_sources)
    return {
        "view_version": VIEW_VERSION,
        "provider_called": False,
        "deep": list(DEFAULT_PICKS),
        "sources": [{**{key: source[key] for key in copper_tools_view.SOURCE_SHOWN}, **states[source["id"]]}
                    for source in (usgs_source, iea_source)],
        "usgs": usgs_part,
        "iea": iea_part,
        "risk": risk_part,
        "uses": uses_part,
        "research": research,
    }
