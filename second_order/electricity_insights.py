"""Electricity by sector (electricity-view-0.1): one explicit local check, write-once results under
data/insights/electricity/, and reads that verify without computing anything new or writing.

A check (POST; explicit, local, $0: no provider, model or network) validates the retained Table 7.6 sources
(electricity_evidence) and computes the fixed comparisons (electricity_rules) in memory. Its result is stored once as
results/<id>.json, with id = SHA-256 of the result version, the extract version, the rules version, the definitions'
SHA-256, the fixed scope and the extract ID (which covers the source hashes and the values read). An existing result
with that ID is reused when it verifies and is never overwritten; a concurrent check creates it once.

A read validates the same sources and recomputes the result in memory, then shows the stored result only when it is
exactly that recomputation (apart from its computation time). A result computed under another version, scope or
source stays on disk and is not shown; the next explicit check applies the current ones. Reads never write.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from . import electricity_evidence as evidence, electricity_rules as rules, electricity_text as text, insights, \
    market_store
from .store import digest

RECORDS_DIR = insights.INSIGHTS_DIR / "electricity"
VIEW_VERSION = "electricity-view-0.1"
RESULT_VERSION = "electricity-result-0.1"
SCOPE = ("Retrospective view of retained EIA data: retail electricity sales to the residential, commercial and "
         "industrial sectors, each month compared with the same month a year earlier, from the Monthly Energy Review "
         "Table 7.6 kept on this computer. Separate from the Treasury and G.17 findings; descriptive, not research "
         "evidence, not a forecast and not a recommendation; nothing here enters research summaries.")


class ElectricityRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    sources: Path = evidence.SOURCES_DIR
    records: Path = RECORDS_DIR


def now() -> datetime:
    return datetime.now(timezone.utc)


def _extract(folders: Folders) -> dict:
    return evidence.load(folders.sources, rules.window(), rules.CODES)


def result_id(extract: dict) -> str:
    return digest({"result_version": RESULT_VERSION, "extract_version": evidence.EXTRACT_VERSION,
                   "rules_version": rules.RULES_VERSION, "definitions_sha256": rules.DEFINITIONS_SHA256,
                   "scope": rules.SCOPE, "extract_id": extract["extract_id"]})


def _result(extract: dict) -> dict:
    """The record a check stores for this extract, without its computation time."""
    identifier = result_id(extract)
    return json.loads(json.dumps({
        "result_version": RESULT_VERSION, "result_id": identifier, "rules_version": rules.RULES_VERSION,
        "definitions_sha256": rules.DEFINITIONS_SHA256, "definitions": rules.DEFINITIONS, "scope": rules.SCOPE,
        "extract": extract, "result": rules.compute(extract["values"])}))


def _path(folders: Folders, identifier: str) -> Path:
    return folders.records / "results" / f"{identifier}.json"


def _stored(folders: Folders, identifier: str) -> dict | None:
    path = _path(folders, identifier)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ElectricityRefused(409, f"The stored result {identifier[:12]} cannot be read; it is kept and not "
                                      "shown") from None


def _verifies(stored: dict, expected: dict) -> bool:
    return isinstance(stored, dict) and isinstance(stored.get("computed_at"), str) and \
        {key: value for key, value in stored.items() if key != "computed_at"} == expected


# ---------------------------------------------------------------- the explicit check

def check(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if payload != {"check_retained_electricity": True}:
        raise ElectricityRefused(422, 'A check is requested with {"check_retained_electricity": true}')
    try:
        extract = _extract(folders)
    except evidence.EvidenceRefused as exc:
        raise ElectricityRefused(409, f"The retained Table 7.6 sources were not accepted: {exc}. Acquiring them is a "
                                      "separate, approved action; this check never downloads.") from None
    expected = _result(extract)
    identifier = expected["result_id"]
    stored = _stored(folders, identifier)
    created = False
    if stored is None:
        try:
            market_store.write_exclusive(_path(folders, identifier),
                                         {**expected, "computed_at": clock().astimezone(timezone.utc).isoformat()})
            created = True
        except FileExistsError:  # A concurrent check stored the same result first.
            stored = _stored(folders, identifier)
    if stored is not None and not _verifies(stored, expected):
        raise ElectricityRefused(409, f"A stored result with ID {identifier[:12]} does not match what these sources "
                                      "give; it is kept, not overwritten and not shown")
    counts = expected["result"]["counts"]
    return {"view_version": VIEW_VERSION, "result_id": identifier, "created": created,
            "months": counts["months"], "monthly_findings": counts["monthly_findings"],
            "period_finding": counts["period_finding"], "provider_called": False}


# ---------------------------------------------------------------- reads (verify only)

def _kept(folders: Folders) -> int:
    folder = folders.records / "results"
    return len([path for path in folder.glob("*.json")]) if folder.is_dir() else 0


def _sources(extract: dict) -> list[dict]:
    provenance = {item["kind"]: item for item in extract["provenance"]}
    out = []
    for source in extract["sources"]:
        item = {**source, **{key: value for key, value in provenance.get(source["kind"], {}).items()
                             if key != "kind"}}
        if source["kind"] == "csv":
            item["edition"] = None
            item["edition_note"] = ("No edition is stated in the file or its response headers (no Last-Modified), so "
                                    "none is assigned.")
        elif source["kind"] == "pdf":
            item["edition"] = source["edition_printed"]
            item["edition_note"] = "Printed on the page; it describes this PDF, not the CSV."
        elif "statements" in source:
            item["edition"] = None
            item["edition_note"] = ("As stated on the page when it was retrieved; it describes the page then, not the "
                                    "CSV.")
        out.append(item)
    return out


def _coverage(extract: dict) -> dict:
    found = extract["coverage"]
    analyzed = [found[code] for code in rules.CODES]
    csv_source = next(item for item in extract["provenance"] if item["kind"] == "csv")
    compared, period = rules.months(), rules.period_months("current")
    return {"compared": {"first": compared[0], "last": compared[-1], "first_label": text.month_label(compared[0]),
                         "last_label": text.month_label(compared[-1])},
            "against": {"first": rules.prior(compared[0]), "last": rules.prior(compared[-1]),
                        "first_label": text.month_label(rules.prior(compared[0])),
                        "last_label": text.month_label(rules.prior(compared[-1]))},
            "period": {"label": text.period_label(period), "prior_label": text.period_label(
                rules.period_months("prior"))},
            "file": {"monthly_first": min(item["monthly_first"] for item in analyzed),
                     "monthly_last": max(item["monthly_last"] for item in analyzed),
                     "monthly_last_label": text.month_label(max(item["monthly_last"] for item in analyzed)),
                     "annual_first": min((item["annual_first"] for item in analyzed if item["annual_first"]),
                                         default=None),
                     "annual_last": max((item["annual_last"] for item in analyzed if item["annual_last"]),
                                        default=None),
                     "retrieved_at": csv_source["retrieved_at"]},
            "geography": "The 50 states and the District of Columbia, as the printed table's notes state; the CSV has no "
                         "geography field.",
            "series": found}


def _base(available: bool, detail: str | None) -> dict:
    return {"view_version": VIEW_VERSION, "scope": SCOPE, "definitions": rules.DEFINITIONS,
            "table_definitions": evidence.TABLE_DEFINITIONS, "disclosures": list(text.DISCLOSURES),
            "limitations": list(text.LIMITATIONS), "available": available, "sources_detail": detail,
            "written": False, "provider_called": False}


def _empty(**fields) -> dict:
    return {"result": None, "coverage": None, "sources": [], "series": [], "months": [], "period": None,
            "findings": None, "reconciliation": None, **fields}


def view(folders: Folders) -> dict:
    """The stored result for the retained sources under the current versions, verified by recomputation. Reads only."""
    try:
        extract = _extract(folders)
    except evidence.EvidenceRefused as exc:
        kept = _kept(folders)
        state = "problem" if kept else "not_checked"
        return {**_base(False, str(exc)), **_empty(state=state, kept_results=kept,
                detail=(f"The retained sources do not verify ({exc}); {kept} stored result"
                        f"{' is' if kept == 1 else 's are'} kept and not shown.") if kept else None)}
    expected = _result(extract)
    try:
        stored = _stored(folders, expected["result_id"])
    except ElectricityRefused as exc:
        return {**_base(True, None), **_empty(state="problem", kept_results=_kept(folders), detail=str(exc))}
    if stored is None:
        kept = _kept(folders)
        return {**_base(True, None), **_empty(
            state="not_checked", kept_results=kept,
            detail=(f"{kept} stored result{' was' if kept == 1 else 's were'} computed under other versions, scope or "
                    "sources; kept and not shown. The next explicit check applies the current ones.") if kept
            else None)}
    if not _verifies(stored, expected):
        return {**_base(True, None), **_empty(
            state="problem", kept_results=_kept(folders),
            detail=f"The stored result {expected['result_id'][:12]} does not match what the retained sources give; "
                   "it is not shown.")}
    result = stored["result"]
    months = [text.month_view(row) for row in result["months"]]
    period = text.period_view(result["period"])
    sources = _sources(extract)
    csv_source = next(item for item in sources if item["kind"] == "csv")
    cite = {"file": csv_source["file"], "url": csv_source["url"], "sha256": csv_source["sha256"],
            "retrieved_at": csv_source["retrieved_at"]}
    return {**_base(True, None), "state": "checked", "detail": None, "kept_results": _kept(folders),
            "result": {"result_id": stored["result_id"], "computed_at": stored["computed_at"],
                       "rules_version": stored["rules_version"], "definitions_sha256": stored["definitions_sha256"],
                       "extract_id": extract["extract_id"]},
            "coverage": _coverage(extract), "sources": sources,
            "series": [{**item, "label": rules.LABELS[item["code"]],
                        "role": "analyzed" if item["code"] in rules.ANALYZED else "context"
                        if item["code"] in rules.CONTEXT else "excluded"} for item in extract["series"]],
            "months": months, "period": period, "findings": text.cards(months, period, cite),
            "reconciliation": result["reconciliation"]}
