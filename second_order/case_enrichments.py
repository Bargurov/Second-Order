"""Case enrichments (case-enrichment-0.1): a source check and reading aid kept beside a case-library case, never in it.

An enrichment is a separate, committed file, content/case-library/enrichments/<case id>.json, bound to the exact bytes
of the case it describes by their SHA-256. The case file, its provenance and its review status are never edited: if
the case file changes, the enrichment no longer applies and is not shown (the view says so). It is written only from
privately retained official pages (approval bis-semis-sources-01), whose records it carries; the pages and the
verbatim passages that support each statement stay private and are never served.

It holds, for one historical announcement (not current rules or legal guidance):
- where the announcement sits in the semiconductor chain, always labelled as the curator's reading;
- the instrument, scope, timing and conditions, each statement marked as stated by the source, not stated, or left
  to a document the source itself names and that was not read (only with that explicit reference);
- the referenced documents that remain unread;
- for each of the case's existing channels, the observations that would be needed to examine it (none is held here);
- a check of the case's key factual claims against a retained source: consistent, qualified (the source adds a
  qualifier the claim omits), discrepancy (the source says something different) or not found. Title, summary, every
  key fact and every channel's source statement are always checked; other passages may be;
- optionally, a limited comparison with a historical case's quoted facts (see related_cases).

Every file is checked strictly; an invalid enrichment refuses that case's enrichment view (the case itself is still
served by case_library). Reads only: nothing here writes, fetches or calls a model. The counts shown are derived here
from the checks, never stored.
"""
from datetime import date, datetime
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from . import case_library, related_cases

ENRICHMENT_VERSION = "case-enrichment-0.1"
VIEW_VERSION = "case-enrichment-view-0.1"
FOLDER = "enrichments"  # Inside the case library's own folder, so a library and its enrichments travel together.
SOURCES_DIR = case_library.ROOT / "data" / "sector-sources" / "bis"  # Private retained copies (git-ignored).
SOURCES_REL = "data/sector-sources/bis"
APPROVALS = ("bis-semis-sources-01",)
SOURCE_IDS = ("release", "listing")  # The press release itself, and BIS's News & Updates listing.
SOURCE_HOSTS = ("www.bis.gov",)
REFERENCE_HOSTS = ("www.bis.gov", "www.federalregister.gov")
ASPECTS = ("instrument", "scope", "timing", "conditions")
STATEMENT_STATES = ("stated", "not_stated", "referenced_unread")
CHECK_STATES = ("consistent", "qualified", "discrepancy", "not_found")
COPY_STATES = ("verified", "absent", "different")
REF_ID = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
FOLDER_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
SHA256 = re.compile(r"[a-f0-9]{64}")
# A claim is addressed by where it sits in the case; these are the forms that may be checked.
TARGET = re.compile(r"(title|summary)|(key_facts)\[(\d+)\]|(channels)\[(\d+)\]\.source_fact|"
                    r"(competing_explanations|source_notes)\[(\d+)\]\.detail")

FIELDS = {"enrichment_version", "case_id", "case_file_sha256", "currency", "sources", "chain", "readout",
          "references", "claim_checks", "not_checked", "examination", "comparison", "provenance"}
SOURCE_FIELDS = {"id", "role", "publisher", "title", "url", "date_as_stated", "retained"}
RETAINED_FIELDS = {"approval_id", "attempt", "folder", "sha256", "bytes", "retrieved_at", "charset"}
CHAIN_FIELDS = {"placement", "attribution", "basis"}
STATEMENT_FIELDS = {"aspect", "status", "text", "source", "reference"}
REFERENCE_FIELDS = {"id", "description", "url", "source", "read"}
CHECK_FIELDS = {"target", "label", "status", "source", "note"}
EXAMINATION_FIELDS = {"channel", "observations"}
COMPARISON_FIELDS = {"historical_case", "facts", "text"}
PROVENANCE_FIELDS = {"prepared_by", "prepared_on", "method", "ai_assisted", "human_review", "research_use"}
FIXED_PROVENANCE = {"ai_assisted": True, "human_review": "not_reviewed", "research_use": "excluded"}
CHAIN_LABEL = "Curator's reading, not BIS's wording"
EXAMINATION_NOTE = ("None of these observations is held in this project. Even with them, a change after the "
                    "announcement would not by itself show that the announcement caused it.")
CURRENCY_NOTE = ("A historical announcement as of its date, not current rules or legal guidance: rules and licenses "
                 "change after they are announced.")


def _invalid(case_id: str, where: str, problem: str) -> case_library.LibraryRefused:
    return case_library.LibraryRefused(
        500, f"The enrichment of case {case_id} is invalid ({where}: {problem}); it is not served")


def _check(condition: bool, case_id: str, where: str, problem: str) -> None:
    if not condition:
        raise _invalid(case_id, where, problem)


def _fields(value: object, expected: set[str], case_id: str, where: str) -> dict:
    _check(isinstance(value, dict) and set(value) == expected, case_id, where,
           f"expected exactly the fields {sorted(expected)}")
    return value


def _text(value: object, case_id: str, where: str) -> str:
    _check(isinstance(value, str) and bool(value) and value == value.strip() and
           len(value) <= case_library.MAX_TEXT and not any(ord(char) < 32 for char in value),
           case_id, where, "expected one line of non-empty, unpadded text")
    return value


def _url(value: object, hosts: tuple[str, ...], case_id: str, where: str) -> str:
    parts = urlsplit(_text(value, case_id, where))
    _check(parts.scheme == "https" and parts.hostname in hosts and not parts.query and not parts.fragment,
           case_id, where, f"expected an https address at {' or '.join(hosts)}")
    return value


def _moment(value: object, case_id: str, where: str) -> datetime:
    try:
        moment = datetime.fromisoformat(_text(value, case_id, where))
    except ValueError:
        moment = None
    _check(moment is not None and moment.utcoffset() is not None, case_id, where, "expected an ISO time with an offset")
    return moment


def target_label(case: dict, target: str) -> str | None:
    """The case's own label for the claim a check addresses, or None when the target names nothing in the case."""
    match = TARGET.fullmatch(target)
    if not match:
        return None
    if match.group(1):
        return match.group(1).capitalize()
    section, index = next((match.group(n), int(match.group(n + 1))) for n in (2, 4, 6) if match.group(n))
    items = case[section]
    if index >= len(items):
        return None
    return items[index]["label"] if section == "key_facts" else items[index]["title"]


def required_targets(case: dict) -> list[str]:
    """The claims every enrichment must check: title, summary, every key fact, every channel's source statement."""
    return ["title", "summary"] + [f"key_facts[{n}]" for n in range(len(case["key_facts"]))] + \
        [f"channels[{n}].source_fact" for n in range(len(case["channels"]))]


def _check_sources(sources: object, case: dict, case_id: str) -> dict:
    _check(isinstance(sources, list) and bool(sources), case_id, "sources", "expected a non-empty list")
    found = {}
    for number, source in enumerate(sources):
        where = f"sources[{number}]"
        _fields(source, SOURCE_FIELDS, case_id, where)
        _check(source["id"] in SOURCE_IDS and source["id"] not in found, case_id, f"{where}.id",
               f"expected a distinct one of {list(SOURCE_IDS)}")
        for field in ("role", "publisher", "title"):
            _text(source[field], case_id, f"{where}.{field}")
        _url(source["url"], SOURCE_HOSTS, case_id, f"{where}.url")
        if source["date_as_stated"] is not None:
            _text(source["date_as_stated"], case_id, f"{where}.date_as_stated")
        retained = _fields(source["retained"], RETAINED_FIELDS, case_id, f"{where}.retained")
        _check(retained["approval_id"] in APPROVALS, case_id, f"{where}.retained.approval_id",
               f"expected one of {list(APPROVALS)}")
        _check(type(retained["attempt"]) is int and retained["attempt"] >= 1, case_id, f"{where}.retained.attempt",
               "expected a positive integer")
        _check(isinstance(retained["folder"], str) and bool(FOLDER_NAME.fullmatch(retained["folder"])), case_id,
               f"{where}.retained.folder", "expected a lower-case folder name")
        _check(isinstance(retained["sha256"], str) and bool(SHA256.fullmatch(retained["sha256"])), case_id,
               f"{where}.retained.sha256", "expected a SHA-256")
        _check(type(retained["bytes"]) is int and retained["bytes"] >= 1, case_id, f"{where}.retained.bytes",
               "expected a positive integer")
        _moment(retained["retrieved_at"], case_id, f"{where}.retained.retrieved_at")
        _text(retained["charset"], case_id, f"{where}.retained.charset")
        found[source["id"]] = source
    _check("release" in found, case_id, "sources", "expected the release the case was written from")
    _check(found["release"]["url"] == case["source"]["url"], case_id, "sources[release].url",
           "expected the case's own source address")
    _check(found["release"]["date_as_stated"] == case["source"]["published_as_stated"], case_id,
           "sources[release].date_as_stated", "expected the date the case records as stated")
    return found


def _check_enrichment(raw: dict, case: dict, case_id: str, historical: dict) -> dict:
    _fields(raw, FIELDS, case_id, "enrichment")
    _check(raw["enrichment_version"] == ENRICHMENT_VERSION, case_id, "enrichment_version",
           f"expected {ENRICHMENT_VERSION}")
    _check(raw["case_id"] == case_id, case_id, "case_id", "does not match its file name")
    _check(isinstance(raw["case_file_sha256"], str) and bool(SHA256.fullmatch(raw["case_file_sha256"])), case_id,
           "case_file_sha256", "expected a SHA-256")
    _check(raw["currency"] == "historical", case_id, "currency", 'expected "historical"')
    sources = _check_sources(raw["sources"], case, case_id)

    chain = _fields(raw["chain"], CHAIN_FIELDS, case_id, "chain")
    _text(chain["placement"], case_id, "chain.placement")
    _text(chain["basis"], case_id, "chain.basis")
    _check(chain["attribution"] == "curator_interpretation", case_id, "chain.attribution",
           'expected "curator_interpretation": a chain placement is the curator\'s reading')

    references = raw["references"]
    _check(isinstance(references, list), case_id, "references", "expected a list")
    reference_ids = []
    for number, reference in enumerate(references):
        where = f"references[{number}]"
        _fields(reference, REFERENCE_FIELDS, case_id, where)
        _check(isinstance(reference["id"], str) and bool(REF_ID.fullmatch(reference["id"])) and
               reference["id"] not in reference_ids, case_id, f"{where}.id", "expected a distinct lower-case id")
        _text(reference["description"], case_id, f"{where}.description")
        if reference["url"] is not None:
            _url(reference["url"], REFERENCE_HOSTS, case_id, f"{where}.url")
        _check(reference["source"] in sources, case_id, f"{where}.source", "names no declared source")
        _check(reference["read"] is False, case_id, f"{where}.read", "a referenced document listed here was not read")
        reference_ids.append(reference["id"])

    readout = raw["readout"]
    _check(isinstance(readout, list), case_id, "readout", "expected a list")
    for number, statement in enumerate(readout):
        where = f"readout[{number}]"
        _fields(statement, STATEMENT_FIELDS, case_id, where)
        _check(statement["aspect"] in ASPECTS, case_id, f"{where}.aspect", f"expected one of {list(ASPECTS)}")
        _check(statement["status"] in STATEMENT_STATES, case_id, f"{where}.status",
               f"expected one of {list(STATEMENT_STATES)}")
        _text(statement["text"], case_id, f"{where}.text")
        _check(statement["source"] in sources, case_id, f"{where}.source", "names no declared source")
        # Only an explicit reference by the source can send a matter to an unread document; silence never does.
        if statement["status"] == "referenced_unread":
            _check(statement["reference"] in reference_ids, case_id, f"{where}.reference",
                   "a referenced_unread statement must name a declared reference")
        else:
            _check(statement["reference"] is None, case_id, f"{where}.reference",
                   "only a referenced_unread statement names a reference")
    _check(all(any(item["aspect"] == aspect for item in readout) for aspect in ASPECTS), case_id, "readout",
           f"expected at least one statement for each of {list(ASPECTS)}")
    _check(any(item["status"] == "not_stated" for item in readout), case_id, "readout",
           "expected at least one thing the source does not state")

    checks = raw["claim_checks"]
    _check(isinstance(checks, list), case_id, "claim_checks", "expected a list")
    targets = []
    for number, check in enumerate(checks):
        where = f"claim_checks[{number}]"
        _fields(check, CHECK_FIELDS, case_id, where)
        _check(isinstance(check["target"], str) and target_label(case, check["target"]) is not None and
               check["target"] not in targets, case_id, f"{where}.target", "expected a distinct claim of the case")
        _check(check["label"] == target_label(case, check["target"]), case_id, f"{where}.label",
               "expected the case's own label for that claim")
        _check(check["status"] in CHECK_STATES, case_id, f"{where}.status", f"expected one of {list(CHECK_STATES)}")
        _check(check["source"] in sources, case_id, f"{where}.source", "names no declared source")
        if check["status"] == "consistent":
            _check(check["note"] is None, case_id, f"{where}.note", "a consistent claim carries no note")
        else:
            _text(check["note"], case_id, f"{where}.note")  # A qualifier, a discrepancy or an absence is explained.
        targets.append(check["target"])
    missing = [target for target in required_targets(case) if target not in targets]
    _check(not missing, case_id, "claim_checks", f"expected checks of {missing}")
    _text(raw["not_checked"], case_id, "not_checked")

    examination = raw["examination"]
    titles = [channel["title"] for channel in case["channels"]]
    _check(isinstance(examination, list) and
           [item.get("channel") if isinstance(item, dict) else None for item in examination] == titles,
           case_id, "examination", "expected one entry per channel of the case, in its order, by its exact title")
    for number, item in enumerate(examination):
        _fields(item, EXAMINATION_FIELDS, case_id, f"examination[{number}]")
        observations = item["observations"]
        _check(isinstance(observations, list) and bool(observations), case_id, f"examination[{number}].observations",
               "expected a non-empty list")
        for index, text in enumerate(observations):
            _text(text, case_id, f"examination[{number}].observations[{index}]")

    comparison = raw["comparison"]
    if comparison is not None:
        _fields(comparison, COMPARISON_FIELDS, case_id, "comparison")
        target = historical.get(comparison["historical_case"])
        _check(target is not None, case_id, "comparison.historical_case", "names no historical case")
        known = {fact["id"] for fact in target["facts"]}
        _check(isinstance(comparison["facts"], list) and bool(comparison["facts"]) and
               len(set(comparison["facts"])) == len(comparison["facts"]) and set(comparison["facts"]) <= known,
               case_id, "comparison.facts", "expected distinct fact ids of that historical case")
        _text(comparison["text"], case_id, "comparison.text")

    provenance = _fields(raw["provenance"], PROVENANCE_FIELDS, case_id, "provenance")
    for field, value in FIXED_PROVENANCE.items():
        _check(provenance[field] == value and type(provenance[field]) is type(value), case_id,
               f"provenance.{field}", f"must be {json.dumps(value)}")
    _text(provenance["prepared_by"], case_id, "provenance.prepared_by")
    _text(provenance["method"], case_id, "provenance.method")
    try:
        prepared = date.fromisoformat(_text(provenance["prepared_on"], case_id, "provenance.prepared_on"))
    except ValueError:
        raise _invalid(case_id, "provenance.prepared_on", "expected a YYYY-MM-DD date") from None
    latest = max(datetime.fromisoformat(source["retained"]["retrieved_at"]).date() for source in sources.values())
    _check(prepared >= latest, case_id, "provenance.prepared_on", "written before its sources were retained")
    return raw


def copy_check(source: dict, sources: Path) -> dict:
    """One retained copy on this machine against its record: verified, absent or different. Reads only."""
    retained = source["retained"]
    path = sources / retained["folder"] / "source.html"
    if not path.is_file():
        return {"source": source["id"], "state": "absent", "acquisition_record": "absent",
                "detail": "The retained copy is not on this machine; the check was made against it where it was "
                          "kept, and its SHA-256 is recorded."}
    raw = path.read_bytes()
    if len(raw) != retained["bytes"] or hashlib.sha256(raw).hexdigest() != retained["sha256"]:
        return {"source": source["id"], "state": "different", "acquisition_record": "not_compared",
                "detail": "The file kept on this machine is not the recorded copy (its size or SHA-256 differs); "
                          "the check below was made against the recorded copy, not this file."}
    record = sources / "acquisitions" / retained["approval_id"] / f"outcome-{retained['attempt']}.json"
    expected = {"outcome": "complete", "http_status": 200, "url": source["url"], "sha256": retained["sha256"],
                "bytes": retained["bytes"], "approval_id": retained["approval_id"],
                "retained": f"{SOURCES_REL}/{retained['folder']}/source.html",
                "body_completed_at": retained["retrieved_at"]}
    if not record.is_file():
        state = "absent"
    else:
        try:
            outcome = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            outcome = None
        state = "matches" if isinstance(outcome, dict) and all(outcome.get(key) == value
                                                               for key, value in expected.items()) else "differs"
    if state == "differs":
        return {"source": source["id"], "state": "different", "acquisition_record": state,
                "detail": "The retained copy has the recorded size and SHA-256, but its acquisition record on this "
                          "machine does not agree with it."}
    return {"source": source["id"], "state": "verified", "acquisition_record": state,
            "detail": "The retained copy on this machine has the recorded size and SHA-256" +
                      (", and its acquisition record agrees." if state == "matches" else
                       "; its acquisition record is not on this machine.")}


def _public_source(source: dict) -> dict:
    retained = source["retained"]  # Folder and attempt locate the private copy; they are not served.
    return {**{key: source[key] for key in ("id", "role", "publisher", "title", "url", "date_as_stated")},
            "retained": {key: retained[key] for key in ("approval_id", "sha256", "bytes", "retrieved_at", "charset")}}


def enrichment_view(case_id: str, library: Path = case_library.LIBRARY_DIR, sources: Path = SOURCES_DIR,
                    related: Path = related_cases.CASES_DIR) -> dict:
    """A case's enrichment: none, stale (written for other case bytes; not shown) or bound. Reads only."""
    loaded = case_library.load_library(library)
    cases = {case["id"]: case for case in loaded["cases"]}
    if not case_library.CASE_ID.fullmatch(case_id or "") or case_id not in cases:
        raise case_library.LibraryRefused(404, "Unknown case")
    base = {"view_version": VIEW_VERSION, "case_id": case_id, "provider_called": False}
    path = library / FOLDER / f"{case_id}.json"
    if not path.is_file():
        return {**base, "state": "none", "enrichment": None,
                "note": "This case has no source check or reading aid."}
    try:
        raw = case_library._strict_load(path)
    except case_library.LibraryRefused:
        raise _invalid(case_id, path.name, "not readable strict UTF-8 JSON") from None
    case_bytes = (library / f"{case_id}.json").read_bytes()
    if not isinstance(raw, dict) or raw.get("case_file_sha256") != hashlib.sha256(case_bytes).hexdigest():
        return {**base, "state": "stale", "enrichment": None,
                "note": "A source check of this case exists, but it was written for a different version of the case "
                        "file, so it is not shown."}
    historical = {}
    if isinstance(raw.get("comparison"), dict):  # A comparison that cannot be resolved refuses; it is never dropped.
        try:
            historical = {item["id"]: item for item in related_cases.load(related)["cases"]}
        except related_cases.RelatedRefused:
            raise _invalid(case_id, "comparison", "the historical cases it compares with cannot be read") from None
    enrichment = _check_enrichment(raw, cases[case_id], case_id, historical)
    counts = {state: sum(check["status"] == state for check in enrichment["claim_checks"]) for state in CHECK_STATES}
    comparison = None
    if enrichment["comparison"] is not None:
        target = historical[enrichment["comparison"]["historical_case"]]
        facts = {fact["id"]: fact["text"] for fact in target["facts"]}
        comparison = {"historical_case": target["id"], "title": target["title"],
                      "href": f"/library/historical/{target['id']}", "text": enrichment["comparison"]["text"],
                      "facts": [{"id": fact, "text": facts[fact]} for fact in enrichment["comparison"]["facts"]]}
    public = {key: enrichment[key] for key in ("case_file_sha256", "currency", "chain", "readout", "references",
                                               "claim_checks", "not_checked", "examination", "provenance")}
    return {**base, "state": "bound", "note": None,
            "enrichment": {**public, "sources": [_public_source(source) for source in enrichment["sources"]],
                           "comparison": comparison, "counts": counts,
                           "copies": [copy_check(source, sources) for source in enrichment["sources"]],
                           "chain_label": CHAIN_LABEL, "examination_note": EXAMINATION_NOTE,
                           "currency_note": CURRENCY_NOTE, "aspects": list(ASPECTS)}}
