"""Cross-source comparisons (cross-source-view-0.1): one explicit local computation, write-once results under
data/insights/cross-source/, and reads that verify without computing anything new or writing.

The action (POST; local, $0: no provider, model or network) reads the retained G.17 Table 1 columns (g17_columns) and the
retained EIA Table 7.6 CSV (electricity_evidence, with the definitions bound to the PDF), computes the fixed comparisons
(crosssource_rules) in memory and stores the result once as results/<id>.json, with id = SHA-256 of the result,
columns, extract and rules versions (including the electricity rules it reuses), the definitions, the scope, the EIA
extract ID and every G.17 columns extract ID. A stored result with that ID is reused when it verifies and is never
overwritten. A read validates the same sources, recomputes the record in memory and shows the stored one only when it
is exactly that, apart from its computation time. Results under other versions or sources are kept and not shown.
The G.17 and electricity findings' records, rules, versions and IDs are untouched.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Callable

from . import (crosssource_rules as rules, crosssource_text as text, electricity_evidence, electricity_rules,
               g17_columns, g17_evidence, insights, market_store)
from .store import digest

RECORDS_DIR = insights.INSIGHTS_DIR / "cross-source"
VIEW_VERSION = "cross-source-view-0.1"
RESULT_VERSION = "cross-source-result-0.1"


class CrossSourceRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    g17_sources: Path = g17_evidence.SOURCES_DIR
    eia_sources: Path = electricity_evidence.SOURCES_DIR
    records: Path = RECORDS_DIR


def now() -> datetime:
    return datetime.now(timezone.utc)


def _inputs(folders: Folders) -> tuple[list[dict], dict]:
    extracts = g17_columns.load(folders.g17_sources)
    twelve = [period["key"] for period in rules.periods(extracts) if period["kind"] == "twelve_month"]
    eia = electricity_evidence.load(folders.eia_sources, rules.eia_months(twelve), rules.CODES)
    return extracts, eia


def result_id(extracts: list[dict], eia: dict) -> str:
    return digest({"result_version": RESULT_VERSION, "columns_version": g17_columns.COLUMNS_VERSION,
                   "extract_version": electricity_evidence.EXTRACT_VERSION, "rules_version": rules.RULES_VERSION,
                   "electricity_rules_version": electricity_rules.RULES_VERSION,
                   "definitions_sha256": rules.DEFINITIONS_SHA256, "scope": rules.SCOPE,
                   "eia_extract_id": eia["extract_id"], "g17_extract_ids": [item["extract_id"] for item in extracts]})


def _result(extracts: list[dict], eia: dict) -> dict:
    return json.loads(json.dumps({
        "result_version": RESULT_VERSION, "result_id": result_id(extracts, eia), "rules_version": rules.RULES_VERSION,
        "definitions_sha256": rules.DEFINITIONS_SHA256, "definitions": rules.DEFINITIONS, "scope": rules.SCOPE,
        "g17": extracts, "eia": eia, "result": rules.compute(extracts, eia["values"], eia["coverage"])}))


def _path(folders: Folders, identifier: str) -> Path:
    return folders.records / "results" / f"{identifier}.json"


def _stored(folders: Folders, identifier: str) -> dict | None:
    path = _path(folders, identifier)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CrossSourceRefused(409, f"The stored result {identifier[:12]} cannot be read; it is kept and not "
                                      "shown") from None


def _verifies(stored: dict, expected: dict) -> bool:
    return isinstance(stored, dict) and isinstance(stored.get("computed_at"), str) and \
        {key: value for key, value in stored.items() if key != "computed_at"} == expected


def _load(folders: Folders) -> tuple[list[dict], dict]:
    try:
        return _inputs(folders)
    except (g17_columns.ColumnsRefused, electricity_evidence.EvidenceRefused) as exc:
        raise CrossSourceRefused(409, f"The retained sources were not accepted: {exc}. Acquiring sources is a "
                                      "separate, approved action; this computation never downloads.") from None


# ---------------------------------------------------------------- the explicit action

def check(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if payload != {"check_cross_source": True}:
        raise CrossSourceRefused(422, 'A computation is requested with {"check_cross_source": true}')
    extracts, eia = _load(folders)
    expected = _result(extracts, eia)
    identifier = expected["result_id"]
    stored = _stored(folders, identifier)
    created = False
    if stored is None:
        try:
            market_store.write_exclusive(_path(folders, identifier),
                                         {**expected, "computed_at": clock().astimezone(timezone.utc).isoformat()})
            created = True
        except FileExistsError:  # A concurrent computation stored the same result first.
            stored = _stored(folders, identifier)
    if stored is not None and not _verifies(stored, expected):
        raise CrossSourceRefused(409, f"A stored result with ID {identifier[:12]} does not match what these sources "
                                      "give; it is kept, not overwritten and not shown")
    return {"view_version": VIEW_VERSION, "result_id": identifier, "created": created,
            "periods": expected["result"]["counts"]["periods"], "provider_called": False}


# ---------------------------------------------------------------- reads (verify only)

def _kept(folders: Folders) -> int:
    folder = folders.records / "results"
    return len(list(folder.glob("*.json"))) if folder.is_dir() else 0


def _base(available: bool, detail: str | None) -> dict:
    return {"view_version": VIEW_VERSION, "scope": text.SCOPE, "definitions": rules.DEFINITIONS,
            "sign_labels": text.SIGN_LABELS, "sign_note": text.SIGN_NOTE, "common_limitations": list(text.COMMON),
            "comparisons_text": text.COMPARISONS, "available": available, "sources_detail": detail,
            "written": False, "provider_called": False}


def _empty(**fields) -> dict:
    return {"result": None, "sources": None, "periods": [], "comparisons": None, **fields}


def _sources(extracts: list[dict], eia: dict) -> dict:
    provenance = {item["kind"]: item for item in eia["provenance"]}
    csv_source = next(item for item in eia["sources"] if item["kind"] == "csv")
    return {"g17": [{"release": item["release"], "release_date_as_stated": item["release_date_as_stated"],
                     "file": item["source"]["file"], "url": item["source"]["url"], "sha256": item["source"]["sha256"],
                     "approval_id": item["source"]["approval_id"], "retrieved_at": item["provenance"]["retrieved_at"],
                     "extract_id": item["extract_id"]} for item in extracts],
            "eia": {**csv_source, "retrieved_at": provenance["csv"]["retrieved_at"],
                    "last_modified_header": provenance["csv"]["last_modified_header"], "edition": None,
                    "edition_note": "No edition is stated in the file or its response headers, so none is assigned.",
                    "monthly_first": min(eia["coverage"][code]["monthly_first"] for code in rules.CODES),
                    "monthly_last": max(eia["coverage"][code]["monthly_last"] for code in rules.CODES)}}


def view(folders: Folders) -> dict:
    """The stored result for the retained sources under the current versions, verified. Reads only."""
    try:
        extracts, eia = _load(folders)
    except CrossSourceRefused as exc:
        kept = _kept(folders)
        return {**_base(False, str(exc)), **_empty(
            state="problem" if kept else "not_checked", kept_results=kept,
            detail=(f"The retained sources do not verify; {kept} stored result{' is' if kept == 1 else 's are'} kept "
                    "and not shown.") if kept else None)}
    expected = _result(extracts, eia)
    try:
        stored = _stored(folders, expected["result_id"])
    except CrossSourceRefused as exc:
        return {**_base(True, None), **_empty(state="problem", kept_results=_kept(folders), detail=str(exc))}
    if stored is None:
        kept = _kept(folders)
        return {**_base(True, None), **_empty(
            state="not_checked", kept_results=kept,
            detail=(f"{kept} stored result{' was' if kept == 1 else 's were'} computed under other versions or "
                    "sources; kept and not shown. The next explicit computation applies the current ones.")
            if kept else None)}
    if not _verifies(stored, expected):
        return {**_base(True, None), **_empty(
            state="problem", kept_results=_kept(folders),
            detail=f"The stored result {expected['result_id'][:12]} does not match what the retained sources give; it "
                   "is not shown.")}
    result = stored["result"]
    periods = [{**period, "label": text.period_label(period)} for period in result["periods"]]
    labels = {period["key"]: period["label"] for period in periods}
    comparisons = {name: [{**row, "label": labels[row["period"]]} for row in result[name]]
                   for name in rules.COMPARISONS}
    return {**_base(True, None), "state": "checked", "detail": None, "kept_results": _kept(folders),
            "result": {"result_id": stored["result_id"], "computed_at": stored["computed_at"],
                       "rules_version": stored["rules_version"], "definitions_sha256": stored["definitions_sha256"]},
            "sources": _sources(extracts, eia), "periods": periods, "comparisons": comparisons,
            "counts": result["counts"]}
