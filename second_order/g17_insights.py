"""Industry divergence and revisions from retained G.17 releases (g17-view-0.1): one explicit local check, write-once
records under data/insights/g17/, and reads that verify without computing anything new or writing.

A check (POST; explicit, local, $0: no provider, model or network) validates every selected retained release
(g17_evidence) and its comparison scope (g17_rules) before anything is written, then creates what is missing:
- extracts/<id>.json: one release's verified extract; its ID covers its content and source hashes, not retrieval times.
- releases/<id>.json: one release's comparisons, ID = SHA-256 of the result version, the definitions' SHA-256 and the
  extract ID. Other releases, the selection and any later release never change it.
- revisions/<id>.json: the comparisons of two releases, ID = SHA-256 of the version, definitions and both extract IDs.
  A new release adds a pair with its neighbour; existing pairs and release results stay.
- checks/<id>.json: the selection and the records it maps to; its ID excludes the time, so an unchanged repeat writes
  nothing. A changed selection writes a new check record and reuses every unchanged result.
- breadth/{releases,revisions,checks}/<id>.json: manufacturing breadth (g17_breadth), with its own definitions and
  versions, keyed by the breadth definitions' SHA-256 and the extract ID (or the two extract IDs); the breadth check
  record names the G.17 check it accompanies. Breadth never changes a G.17 record or ID.
Records are created once (market_store.write_exclusive) and never rewritten; concurrent checks of the same inputs
create each record once. Reads verify each record against its ID and recompute the comparisons from the stored
extracts in memory to confirm them; a record that does not verify is refused, never shown. Results computed under other
definitions stay on disk but are shown only after a new explicit check under the current definitions.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable

from . import case_library, g17_breadth, g17_breadth_text, g17_evidence, g17_rules, g17_text, insights, market_store
from .store import digest

RECORDS_DIR = insights.INSIGHTS_DIR / "g17"
VIEW_VERSION = "g17-view-0.1"
RELEASE_VERSION = "g17-release-result-0.1"
REVISION_VERSION = "g17-revision-result-0.1"
CHECK_VERSION = "g17-check-0.1"
BREADTH_RELEASE_VERSION = "g17-breadth-release-0.1"
BREADTH_REVISION_VERSION = "g17-breadth-revision-0.1"
BREADTH_CHECK_VERSION = "g17-breadth-check-0.1"
SCOPE = ("Retrospective industry view from retained G.17 releases: published seasonally adjusted monthly rates from "
         "Table 1, compared within one release (industries against their parent or the total) and across releases "
         "(revisions of the same month). Separate from the Treasury findings; not research evidence and not a measure "
         "of forecasting performance; nothing here enters research summaries.")


class G17Refused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class Folders:
    sources: Path = g17_evidence.SOURCES_DIR
    records: Path = RECORDS_DIR
    library: Path = case_library.LIBRARY_DIR


def now() -> datetime:
    return datetime.now(timezone.utc)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_once(path: Path, record: dict) -> bool:
    if path.exists():
        return False
    try:
        market_store.write_exclusive(path, record)
    except FileExistsError:  # A concurrent check created the same record; its content is keyed by the same inputs.
        return False
    return True


def _release_id(extract_id: str) -> str:
    return digest({"result_version": RELEASE_VERSION, "definitions_sha256": g17_rules.DEFINITIONS_SHA256,
                   "extract_id": extract_id})


def _revision_id(earlier_id: str, later_id: str) -> str:
    return digest({"result_version": REVISION_VERSION, "definitions_sha256": g17_rules.DEFINITIONS_SHA256,
                   "earlier_extract_id": earlier_id, "later_extract_id": later_id})


def _json(value):
    return json.loads(json.dumps(value))


def _breadth_release_id(extract_id: str) -> str:
    return digest({"result_version": BREADTH_RELEASE_VERSION, "definitions_sha256": g17_breadth.DEFINITIONS_SHA256,
                   "extract_id": extract_id})


def _breadth_revision_id(earlier_id: str, later_id: str) -> str:
    return digest({"result_version": BREADTH_REVISION_VERSION, "definitions_sha256": g17_breadth.DEFINITIONS_SHA256,
                   "earlier_extract_id": earlier_id, "later_extract_id": later_id})


def _breadth_check(folders: Folders, extracts: list[dict], g17_check_id: str, clock) -> dict:
    """Breadth records for one G.17 check, under breadth/ only; existing ones are reused."""
    root = folders.records / "breadth"
    created = {"release_results": 0, "revision_results": 0}
    release_ids, revision_ids = {}, []
    stamp = clock().astimezone(timezone.utc).isoformat()
    for extract in extracts:
        result_id = _breadth_release_id(extract["extract_id"])
        created["release_results"] += _write_once(root / "releases" / f"{result_id}.json", {
            "result_version": BREADTH_RELEASE_VERSION, "result_id": result_id,
            "breadth_version": g17_breadth.BREADTH_VERSION, "definitions_sha256": g17_breadth.DEFINITIONS_SHA256,
            "definitions": g17_breadth.DEFINITIONS, "extract_id": extract["extract_id"], "release": extract["release"],
            "result": g17_breadth.release_breadth(extract), "computed_at": stamp})
        release_ids[extract["release"]] = result_id
    for earlier, later in zip(extracts, extracts[1:]):
        result_id = _breadth_revision_id(earlier["extract_id"], later["extract_id"])
        created["revision_results"] += _write_once(root / "revisions" / f"{result_id}.json", {
            "result_version": BREADTH_REVISION_VERSION, "result_id": result_id,
            "breadth_version": g17_breadth.BREADTH_VERSION, "definitions_sha256": g17_breadth.DEFINITIONS_SHA256,
            "definitions": g17_breadth.DEFINITIONS, "earlier_extract_id": earlier["extract_id"],
            "later_extract_id": later["extract_id"], "result": g17_breadth.revision_breadth(earlier, later),
            "computed_at": stamp})
        revision_ids.append({"earlier": earlier["release"], "later": later["release"], "result_id": result_id})
    record = {"check_version": BREADTH_CHECK_VERSION, "definitions_sha256": g17_breadth.DEFINITIONS_SHA256,
              "g17_check_id": g17_check_id, "selection": [extract["release"] for extract in extracts],
              "extracts": {extract["release"]: extract["extract_id"] for extract in extracts},
              "release_results": release_ids, "revision_results": revision_ids}
    check_id = digest(record)
    written = _write_once(root / "checks" / f"{check_id}.json", {**record, "check_id": check_id, "checked_at": stamp})
    return {"check_id": check_id, "created": written, "release_results_created": created["release_results"],
            "revision_results_created": created["revision_results"]}


# ---------------------------------------------------------------- the explicit check

def check(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        payload = None
    if not isinstance(payload, dict) or payload.get("check_retained_g17") is not True or \
            not set(payload) <= {"check_retained_g17", "releases"}:
        raise G17Refused(422, 'A check is requested with {"check_retained_g17": true} and, optionally, "releases"')
    available = g17_evidence.retained(folders.sources)
    if not available:
        raise G17Refused(409, "No retained G.17 release with its Table 1 and release summary is kept, so there is "
                              "nothing to compare. Acquiring one is a separate, approved action; this check never "
                              "downloads.")
    wanted = payload.get("releases", sorted(available))
    if not isinstance(wanted, list) or not wanted or len(set(wanted)) != len(wanted) or \
            any(not isinstance(item, str) or not re.fullmatch(r"\d{8}", item) for item in wanted):
        raise G17Refused(422, '"releases" must be a non-empty list of distinct release folders such as "20260918"')
    missing = sorted(set(wanted) - set(available))
    if missing:
        raise G17Refused(422, f"Not retained: {', '.join(missing)}")
    extracts = []
    for release in sorted(wanted):  # Every input is validated before anything is written.
        try:
            extract = g17_evidence.extract(folders.sources, release, available[release])
            g17_rules.scope(extract)
        except (g17_evidence.EvidenceRefused, g17_rules.RulesRefused) as exc:
            raise G17Refused(409, f"The retained {release} release was not accepted: {exc}") from None
        extracts.append(extract)
    extracts.sort(key=lambda item: item["release_date"])
    created = {"extracts": 0, "release_results": 0, "revision_results": 0}
    release_ids, revision_ids = {}, []
    for extract in extracts:
        created["extracts"] += _write_once(folders.records / "extracts" / f"{extract['extract_id']}.json", extract)
        result_id = _release_id(extract["extract_id"])
        created["release_results"] += _write_once(folders.records / "releases" / f"{result_id}.json", {
            "result_version": RELEASE_VERSION, "result_id": result_id, "rules_version": g17_rules.RULES_VERSION,
            "definitions_sha256": g17_rules.DEFINITIONS_SHA256, "definitions": g17_rules.DEFINITIONS,
            "extract_id": extract["extract_id"], "release": extract["release"],
            "result": g17_rules.release_comparisons(extract), "computed_at": clock().astimezone(timezone.utc)
            .isoformat()})
        release_ids[extract["release"]] = result_id
    for earlier, later in zip(extracts, extracts[1:]):
        result_id = _revision_id(earlier["extract_id"], later["extract_id"])
        created["revision_results"] += _write_once(folders.records / "revisions" / f"{result_id}.json", {
            "result_version": REVISION_VERSION, "result_id": result_id, "rules_version": g17_rules.RULES_VERSION,
            "definitions_sha256": g17_rules.DEFINITIONS_SHA256, "definitions": g17_rules.DEFINITIONS,
            "earlier_extract_id": earlier["extract_id"], "later_extract_id": later["extract_id"],
            "result": g17_rules.revision_comparisons(earlier, later),
            "computed_at": clock().astimezone(timezone.utc).isoformat()})
        revision_ids.append({"earlier": earlier["release"], "later": later["release"], "result_id": result_id})
    record = {"check_version": CHECK_VERSION, "definitions_sha256": g17_rules.DEFINITIONS_SHA256,
              "selection": [extract["release"] for extract in extracts],
              "extracts": {extract["release"]: extract["extract_id"] for extract in extracts},
              "release_results": release_ids, "revision_results": revision_ids}
    check_id = digest(record)
    written = _write_once(folders.records / "checks" / f"{check_id}.json",
                          {**record, "check_id": check_id, "checked_at": clock().astimezone(timezone.utc).isoformat()})
    breadth = _breadth_check(folders, extracts, check_id, clock)
    return {"view_version": VIEW_VERSION, "check_id": check_id, "created": written or breadth["created"],
            "g17_check_created": written, "extracts_created": created["extracts"],
            "release_results_created": created["release_results"],
            "revision_results_created": created["revision_results"], "breadth": breadth,
            "releases": record["selection"], "provider_called": False}


# ---------------------------------------------------------------- reads (verify only)

def _records(folder: Path) -> list[dict]:
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.json")):
        try:
            found.append(_read(path))
        except (OSError, ValueError):
            continue
    return found


def latest_check(folders: Folders) -> dict | None:
    checks = [record for record in _records(folders.records / "checks")
              if record.get("check_version") == CHECK_VERSION and record.get("check_id") ==
              digest({key: value for key, value in record.items() if key not in ("check_id", "checked_at")})]
    return max(checks, key=lambda record: (record["checked_at"], record["check_id"])) if checks else None


def _load(folders: Folders, kind: str, record_id: str) -> dict:
    try:
        return _read(folders.records / kind / f"{record_id}.json")
    except (OSError, ValueError):
        raise G17Refused(409, f"The stored {kind[:-1]} {record_id[:12]} cannot be read") from None


def _verified(folders: Folders, latest: dict) -> tuple[list[dict], dict, list[dict]]:
    """The latest check's extracts, release results and revision pairs, each verified; refused otherwise."""
    if latest["definitions_sha256"] != g17_rules.DEFINITIONS_SHA256:
        raise G17Refused(409, "The latest check used other definitions; its records are kept, and a new explicit "
                              "check applies the current definitions")
    extracts = []
    for release in latest["selection"]:
        extract = _load(folders, "extracts", latest["extracts"][release])
        if not g17_evidence.verify_extract(extract) or extract["extract_id"] != latest["extracts"][release]:
            raise G17Refused(409, f"The stored extract of {release} does not match its ID; it is not shown")
        extracts.append(extract)
    results = {}
    for extract in extracts:
        result_id = latest["release_results"][extract["release"]]
        stored = _load(folders, "releases", result_id)
        if result_id != _release_id(extract["extract_id"]) or stored.get("result_id") != result_id or \
                stored.get("extract_id") != extract["extract_id"] or \
                stored.get("result") != _json(g17_rules.release_comparisons(extract)):
            raise G17Refused(409, f"The stored comparisons of {extract['release']} do not follow from its extract; "
                                  "they are not shown")
        results[extract["release"]] = stored["result"]
    by_release = {extract["release"]: extract for extract in extracts}
    pairs = []
    for item in latest["revision_results"]:
        earlier, later = by_release[item["earlier"]], by_release[item["later"]]
        stored = _load(folders, "revisions", item["result_id"])
        if item["result_id"] != _revision_id(earlier["extract_id"], later["extract_id"]) or \
                stored.get("result_id") != item["result_id"] or \
                stored.get("result") != _json(g17_rules.revision_comparisons(earlier, later)):
            raise G17Refused(409, f"The stored revisions {item['earlier']} to {item['later']} do not follow from their "
                                  "extracts; they are not shown")
        pairs.append(stored["result"])
    return extracts, results, pairs


def _verified_breadth(folders: Folders, latest: dict, extracts: list[dict]) -> tuple[dict, dict, list[dict]]:
    """The breadth check accompanying the latest G.17 check, verified: (summary, release results, revision results).
    Refused (G17Refused) when a record does not verify; None summary when no breadth check accompanies it."""
    root = folders.records / "breadth"
    candidates = [record for record in _records(root / "checks")
                  if record.get("check_version") == BREADTH_CHECK_VERSION
                  and record.get("g17_check_id") == latest["check_id"]
                  and record.get("check_id") == digest({key: value for key, value in record.items()
                                                        if key not in ("check_id", "checked_at")})]
    if not candidates:
        return None, {}, []
    record = max(candidates, key=lambda item: (item["checked_at"], item["check_id"]))
    if record["definitions_sha256"] != g17_breadth.DEFINITIONS_SHA256:
        raise G17Refused(409, "The breadth records were computed under other breadth definitions; they are kept, and "
                              "a new explicit check applies the current definitions")
    by_release = {extract["release"]: extract for extract in extracts}
    if record["extracts"] != {release: extract["extract_id"] for release, extract in by_release.items()}:
        raise G17Refused(409, "The breadth check does not match the latest G.17 check's extracts")
    results = {}
    for release, result_id in record["release_results"].items():
        stored = _load(folders, "breadth/releases", result_id)
        extract = by_release[release]
        if result_id != _breadth_release_id(extract["extract_id"]) or stored.get("result_id") != result_id or \
                stored.get("result") != _json(g17_breadth.release_breadth(extract)):
            raise G17Refused(409, f"The stored breadth of {release} does not follow from its extract; it is not shown")
        results[release] = stored["result"]
    pairs = []
    for item in record["revision_results"]:
        earlier, later = by_release[item["earlier"]], by_release[item["later"]]
        stored = _load(folders, "breadth/revisions", item["result_id"])
        if item["result_id"] != _breadth_revision_id(earlier["extract_id"], later["extract_id"]) or \
                stored.get("result_id") != item["result_id"] or \
                stored.get("result") != _json(g17_breadth.revision_breadth(earlier, later)):
            raise G17Refused(409, f"The stored breadth revisions {item['earlier']} to {item['later']} do not follow "
                                  "from their extracts; they are not shown")
        pairs.append(stored["result"])
    return {"check_id": record["check_id"], "checked_at": record["checked_at"]}, results, pairs


def _breadth_view(folders: Folders, latest: dict, extracts: list[dict], full: bool = False) -> dict:
    """The breadth part of a read: verified, or why it is not shown. Its problems never hide the industry findings."""
    try:
        check_summary, results, pairs = _verified_breadth(folders, latest, extracts)
    except G17Refused as exc:
        return {"state": "problem", "detail": str(exc), "definitions": g17_breadth.DEFINITIONS}
    if check_summary is None:
        return {"state": "not_checked", "detail": "No breadth has been computed for this check yet; the next explicit "
                                                  "check adds it.", "definitions": g17_breadth.DEFINITIONS}
    content = (g17_breadth_text.tables if full else g17_breadth_text.summary)(extracts, results, pairs)
    return {"state": "checked", "detail": None, "check": check_summary, "definitions": g17_breadth.DEFINITIONS,
            **content}


def _library(folders: Folders) -> dict[str, dict]:
    """Release address -> the case-library case whose source is that exact G.17 release (identity, never title)."""
    try:
        loaded = case_library.load_library(folders.library)
    except case_library.LibraryRefused:
        return {}
    return {case["source"]["url"]: {"case_id": case["id"], "title": case["title"], "href": f"/library/{case['id']}"}
            for case in loaded["cases"] if case["source"].get("document_id") == "G.17"}


def _release_row(extract: dict, links: dict) -> dict:
    url = g17_evidence.source_url(extract["release"], "release.html")
    retrieved = {item["file"]: item for item in extract["provenance"]}
    return {"release": extract["release"], "release_date": extract["release_date"],
            "release_date_as_stated": extract["release_date_as_stated"],
            "last_update_as_stated": extract["last_update_as_stated"], "url": url, "extract_id": extract["extract_id"],
            "months": [{"key": m["key"], "label": g17_text.month_label(m["key"]), "marker": m["marker"]}
                       for m in extract["months"]],
            "sources": [{**source, "retrieved_at": retrieved[source["file"]]["retrieved_at"],
                         "last_modified_header": retrieved[source["file"]]["last_modified_header"]}
                        for source in extract["sources"]],
            "consistency": extract["consistency"], "library": links.get(url)}


def _base(folders: Folders) -> dict:
    available = g17_evidence.retained(folders.sources)
    return {"view_version": VIEW_VERSION, "scope": SCOPE, "limitations": list(g17_text.LIMITATIONS),
            "definitions": g17_rules.DEFINITIONS, "available": sorted(available), "written": False,
            "provider_called": False}


def listing(folders: Folders) -> dict:
    """The latest check, its releases and the selected cards. Reads only."""
    base = _base(folders)
    latest = latest_check(folders)
    if latest is None:
        return {**base, "state": "not_checked", "check": None, "detail": None, "releases": [], "divergence": None,
                "revisions": None, "table1": None, "breadth": None}
    summary = {"check_id": latest["check_id"], "checked_at": latest["checked_at"], "selection": latest["selection"]}
    try:
        extracts, results, pairs = _verified(folders, latest)
    except G17Refused as exc:
        return {**base, "state": "problem", "check": summary, "detail": str(exc), "releases": [], "divergence": None,
                "revisions": None, "table1": None, "breadth": None}
    links = _library(folders)
    return {**base, "state": "checked", "check": summary, "detail": None,
            "breadth": _breadth_view(folders, latest, extracts),
            "releases": [_release_row(extract, links) for extract in extracts],
            "table1": {key: extracts[-1]["table"][key] for key in ("title", "unit", "proportion_label",
                                                                   "proportion_note", "naics_note")},
            "divergence": g17_text.divergence(extracts, results), "revisions": g17_text.revisions(extracts, pairs)}


def tables(folders: Folders) -> dict:
    """Every comparison and revision chain of the latest check, verified. Reads only."""
    base = _base(folders)
    latest = latest_check(folders)
    if latest is None:
        raise G17Refused(404, "No G.17 check has been run")
    extracts, results, pairs = _verified(folders, latest)
    links = _library(folders)
    full = g17_text.tables(extracts, results, pairs)
    compared = {item["release"]: item for item in full["by_release"]}
    return {**base, "state": "checked", "check": {"check_id": latest["check_id"], "checked_at": latest["checked_at"],
                                                  "selection": latest["selection"]},
            "releases": [{**_release_row(extract, links), "comparisons": compared[extract["release"]]["comparisons"],
                          "counts": compared[extract["release"]]["counts"]} for extract in extracts],
            "months": full["months"], "revision_rows": full["revision_rows"],
            "breadth": _breadth_view(folders, latest, extracts, full=True)}
