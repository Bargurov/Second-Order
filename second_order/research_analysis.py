"""Evidence-first research analysis: a second, separately versioned analysis mode for a saved event.

The market-hypothesis draft (analysis_flow, paid_drafts) asks for directional legs on offered observables. This mode
asks instead what one publication establishes, quoted from its captured text, and keeps any interpretation apart from
it, labelled as such, with its assumptions, competing explanations, missing information and the checks that would test
it. It asks for no direction, horizon, forecast, trade or observable, and "the available evidence supports no
additional finding" is an acceptable result. No earlier baseline publication is supplied, so the result makes no
comparison with one: the baseline section always says so. The analysis is retrospective (written after publication),
never an out-of-sample forecast test, and a publisher's forecast stays the publisher's attributed forecast.

Contracts, each with its own version (nothing here reinterprets a hypothesis draft or its review):
- research-request-0.1: requests/<request_id>/{request.json, manifest.json}, prepared from one verified capture and
  written once, read-only, never overwritten. ``request_id`` is ``<capture_id>.<prompt version>``: one request per
  capture and prompt version. The manifest binds the capture's own request and source hashes, its event fields and
  its recorded Inbox origin (the link file's SHA-256 and the entry version it names), or records that it has none.
  Every read verifies all of them again; the capture's own files and request are only read. A capture that Go deeper
  saved (story_deeper) has an origin record naming where its publishers' own words are (deeper-evidence-0.1); the
  manifest of each request prepared since binds that record (its SHA-256 and passages, checked again on every read),
  and a Go deeper capture whose record names no passages (story-deeper-0.1) is not prepared or sent again. What the
  request sends is versioned by its prompt version (research_requests: research-prompt-1 carries the analysis in a
  strict tool, research-prompt-2 asks for it as the JSON output format), and its reply is read under that version.
- research-result-view-0.1: built on every read from one attempt's saved files (attempts/<request_id>/), never stored.
  Every quote must appear in the captured text; its paragraph and character locators are computed by code, never
  taken from the model. When the request binds publisher passages, every quote must lie wholly inside one of them, and
  says which report, publisher and part it is from; Second Order's framing, labels and notes are not evidence. A
  request without that binding (any ordinary source, and every request prepared before it existed) keeps the whole
  captured text as evidence, so its recorded results read exactly as before. A response whose evidence does not
  resolve is refused as a whole.
- research-review-0.1: reviews/<request_id>/NNNNNN.json, append-only versions bound to the SHA-256 of the result view
  they were saved against.

Sending reuses the existing safeguards: an explicit approval naming the saved request's SHA-256 (and, for a paid send,
``approve_paid_request: true`` and the previewed planning estimate), an exclusive reservation per request (one attempt,
mock or paid, ever), the exact saved bytes copied before sending and posted once through the pilot's client (no retry,
redirect, fallback or regeneration), the key kept out of every file, and the manifest written last. A paid send needs a
server started with --enable-paid-drafts. Nothing here freezes, evaluates or scores an analysis, and no GET writes.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable

import httpx

from . import deeper_evidence, event_intake, event_links
from .analysis_flow import FlowRefused, _json_bytes, _recorded_mode, cost_estimate, keep_record, now, strict_object
from .draft_pilot import OUTCOME_NOTES as PAID_NOTES, REQUEST_ID, response_summary, usage_cost
from .human_review import CONTROL, ReviewRefused, write_exclusively
from .model_draft import API_VERSION, MESSAGES_URL, DraftRefused, error_diagnostics, exposes, send_bytes, strict_json
from .entitlements import PROVIDER_EFFORTS
from .paid_drafts import UNKNOWN, PaidSender, checked_approval, key_problem
from .research_requests import (  # noqa: F401  (re-exported: what a request sends lives in research_requests)
    CONTRACTS, EFFORT, FORMAT_PROMPT_TOKENS, MAX_TOKENS, MODEL, PROMPT_VERSION, REPLY_FORMATS, SYSTEM_PROMPT,
    SYSTEM_PROMPT_FORMAT, TOOL_DESCRIPTION, build_request, output_schema, tool_schema)
from .research_reading import (  # noqa: F401  (re-exported: the reply contract lives in research_reading)
    MAX_ESTABLISHED, MAX_INTERPRETATION, MAX_ITEM, MAX_ITEMS, MAX_QUOTE, MAX_QUOTES, MAX_SHOWN_TEXT, MAX_STATEMENT,
    MIN_QUOTE, TOOL_NAME, CompetingExplanation, Check, Established, Interpretation, ResearchOutput, TYPOGRAPHY,
    classify, locate, mock_response, paragraphs)
from .schema import utc
from .store import canonical, digest

FLOW_VERSION = "research-analysis-flow-0.1"
REQUEST_VERSION = "research-request-0.1"
USER_REQUEST_VERSION = "research-request-0.2"  # Prepared for a user account: one per capture, prompt version and Effort.
VIEW_VERSION = "research-result-view-0.1"
RECORD_VERSION = "research-review-0.1"
USER_RECORD_VERSION = "research-review-0.2"  # A user account's review of its own research-request-0.2 analysis.
STATUS = "Prepared · Nothing sent"
MOCK_RUN = "research-mock-1"
PAID_RUN = "research-live-1"
MOCK_OUTCOMES = ("analysis", "no_additional_finding", "declined")
ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = ROOT / "data" / "research-analyses"  # Runtime records; data/ is ignored by git.
CODE_FILES = ("second_order/research_analysis.py", "second_order/research_reading.py", "second_order/analysis_flow.py",
              "second_order/paid_drafts.py", "second_order/model_draft.py", "second_order/event_intake.py",
              "second_order/deeper_evidence.py", "second_order/research_requests.py")
DEEPER_LINKS = "story-deeper"  # Go deeper's origin records beside the captures (story_deeper.DEEPER_DIR's name).
DEEPER_LINK_VERSION = "story-deeper-link-0.2"  # The first origin records that name the publishers' passages.
UNMARKED = ("This Go deeper source was saved before Go deeper recorded which of its passages are the publishers' own "
            "words, so it is not analysed again; nothing was prepared, reserved or sent")
EFFORTS = PROVIDER_EFFORTS[MODEL]  # Verified from the provider's documentation; see entitlements.
# <capture_id>.<prompt version> (research-request-0.1), or with .<effort> (research-request-0.2, a user's request).
REQUEST_ID_PATTERN = re.compile(rf"({event_intake.CAPTURE_ID.pattern})\.(research-prompt-[1-9][0-9]{{0,3}})"
                                rf"(?:\.({'|'.join(EFFORTS)}))?")
USER_ID = re.compile(r"u-[0-9a-f]{16}")
REQUEST_FILES = ["manifest.json", "request.json"]
SHA256 = re.compile(r"[0-9a-f]{64}")

MAX_REPLY_CHARACTERS = (MAX_ESTABLISHED * (MAX_STATEMENT + MAX_QUOTES * MAX_QUOTE) + MAX_INTERPRETATION
                        + MAX_ITEMS * MAX_ITEM * 2 + MAX_ITEMS * MAX_ITEM * 2 * 2)

MAX_NOTES = 20_000
# A review body must hold notes of up to MAX_NOTES characters in any script and in any valid JSON encoding: a character
# takes at most 12 bytes (an astral character escaped as two \uXXXX), and the other fields fit in 4,096 bytes. Notes
# are limited in characters; this only bounds what is read (QA-1).
MAX_REVIEW_BODY = 12 * MAX_NOTES + 4_096
STATUSES = ("needs_revision", "human_reviewed")
ATTRIBUTION = "local human reviewer"
VERSION_FILE = re.compile(r"(\d{6})\.json")
REVIEW_FIELDS = ("parent_review_id", "binding", "status", "notes")
BINDING_FIELDS = ("result_view_sha256", "request_sha256", "response_sha256")

BASELINE = {"state": "not_supplied",
            "note": ("No earlier baseline publication was supplied with this request, so the analysis makes no "
                     "comparison with earlier statements or data.")}
RETROSPECTIVE = ("Retrospective: the analysis is made after the publication, from its captured text. It is not a "
                 "forecast and not an out-of-sample test.")
NOT_SENT = ("A prepared request is not an analysis. Nothing has been sent; an analysis exists only after an approved "
            "send records a response.")
NOT_ENABLED = ("Paid sending is not enabled on this server; nothing was reserved or sent. It needs an explicit "
               "`python -m second_order serve --enable-paid-drafts` with the key in the environment.")

# Recorded outcome -> the view's outcome, and what it means.
OUTCOMES = {"analysis": "analysis", "no additional finding": "no_additional_finding", "declined": "declined",
            "incomplete": "incomplete", "refused": "invalid", "provider error": "technical_failure",
            "transport error": "technical_failure", "credential echo": "technical_failure"}
OUTCOME_NOTES = {
    "analysis": ("The response passed the research contract: every quote was found in the captured text. Structure "
                 "only; whether the reading is sound is for the reviewer."),
    "no additional finding": ("The response passed the research contract and reports that the available evidence "
                              "supports no finding beyond what the source states. That is an acceptable result."),
    "declined": "The model did not submit an analysis. Its text, if any, is shown; no analysis is read from prose.",
    "incomplete": "The response stopped before an analysis was submitted. It is kept as recorded and never sent again.",
    "refused": ("The response broke the research contract, so none of its content is shown as analysis. The bytes are "
                "kept in response.json."),
    **{key: PAID_NOTES[key] for key in ("provider error", "transport error", "credential echo")},
}
ESTIMATE_NOTE = (f"Output limit for this mode: {MAX_TOKENS:,} tokens. The reply's own limits (at most "
                 f"{MAX_ESTABLISHED} established statements with {MAX_QUOTES} quotes each, and bounded text fields) "
                 f"hold its text to at most {MAX_REPLY_CHARACTERS:,} characters; the rest is headroom for adaptive thinking at "
                 f"{EFFORT} effort. A reply cut off at the limit is recorded as incomplete and never sent again.")


@dataclass(frozen=True)
class Folders:
    research: Path  # requests/, attempts/ and reviews/ of this mode
    intake: Path  # the saved captures, only read
    links: Path  # their recorded Inbox origins, only read
    deeper: Path | None = None  # Go deeper's origin records, only read; by default story-deeper/ beside the captures

    @property
    def deeper_links(self) -> Path:
        return self.deeper if self.deeper is not None else self.intake.parent / DEEPER_LINKS

    @property
    def requests(self) -> Path:
        return self.research / "requests"

    @property
    def attempts(self) -> Path:
        return self.research / "attempts"

    @property
    def reviews(self) -> Path:
        return self.research / "reviews"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------- the request

def research_cost(request_bytes: bytes) -> dict:
    """The shared planning estimate for these bytes, with this mode's output limit explained. A request in the JSON
    output format (research-prompt-2) offers no tool, so its allowance is for the format's system prompt instead."""
    request = json.loads(request_bytes)
    formatted = "tools" not in request and "format" in request.get("output_config", {})
    system = (FORMAT_PROMPT_TOKENS, f"{FORMAT_PROMPT_TOKENS:,} assumed for the system prompt the provider adds for "
                                    "the JSON output format (its size is not published)") if formatted else None
    estimate = cost_estimate(request_bytes, MAX_TOKENS, system)
    return {**estimate, "assumptions": [*estimate["assumptions"], ESTIMATE_NOTE]}


def reply_of(prompt_version: str) -> str | None:
    """How a request written under this prompt version receives its reply ("tool" or "format"), or None."""
    return CONTRACTS.get(prompt_version)


def code_identity() -> dict:
    return {"flow_version": FLOW_VERSION,
            "sha256": {name: sha256((ROOT / name).read_bytes()) for name in CODE_FILES}}


def _capture(folders: Folders, capture_id: object) -> dict:
    if not isinstance(capture_id, str) or not event_intake.CAPTURE_ID.fullmatch(capture_id):
        raise FlowRefused(404, "Unknown capture ID")
    try:
        return event_intake.verified(folders.intake, capture_id)
    except event_intake.IntakeRefused as exc:
        raise FlowRefused(404 if "does not exist" in str(exc) else 409, str(exc)) from None


def _origin_binding(folders: Folders, capture_id: str) -> dict:
    """The capture's recorded Inbox origin as it stands now, or that it has none. An origin record that does not
    verify is refused: a request is never bound to an origin that cannot be checked."""
    path = event_links.path_for(folders.links, capture_id)
    if not path.exists():
        return {"state": "none", "note": "The capture records no Inbox origin (typed by hand, or captured before "
                                         "origins were recorded)."}
    try:
        link = event_links.verified_link(folders.links, capture_id, folders.intake)
        data = path.read_bytes()
    except event_links.UNVERIFIED as exc:
        raise FlowRefused(409, f"The capture's recorded Inbox origin does not verify ({exc}); no research request is "
                               "bound to it") from None
    inbox = link["inbox"]
    return {"state": "verified", "link_sha256": sha256(data), "link_version": link["link_version"],
            "item_id": inbox["item_id"], "source": inbox["source"], "content_sha256": inbox["content_sha256"],
            "version": inbox["version"], "versions": inbox["versions"], "title": inbox["title"],
            "recorded_at": link["recorded_at"]}


def _check_origin(folders: Folders, capture_id: str, recorded: object) -> None:
    if not isinstance(recorded, dict):
        raise ValueError("the manifest's origin is not an object")
    path = event_links.path_for(folders.links, capture_id)
    if recorded.get("state") == "none":
        if path.exists():
            raise ValueError("the manifest records no Inbox origin, but the capture now has an origin record")
        return
    if recorded.get("state") != "verified" or not path.exists():
        raise ValueError("the capture's recorded Inbox origin is missing")
    if sha256(path.read_bytes()) != recorded.get("link_sha256"):
        raise ValueError("the capture's Inbox origin record changed since the request was prepared")
    link = event_links.verified_link(folders.links, capture_id, folders.intake)
    named = {key: link["inbox"][key] for key in ("item_id", "content_sha256", "version")}
    if named != {key: recorded.get(key) for key in named}:
        raise ValueError("the manifest names another Inbox entry version than the origin record")


def _deeper_link(folders: Folders, capture_id: str) -> tuple[bytes, object] | None:
    """The capture's Go deeper origin record (its bytes and JSON), or None when Go deeper did not save it."""
    path = folders.deeper_links / f"{capture_id}.json"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        return data, json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return data, None


def evidence_binding(folders: Folders, capture_id: str, record: dict) -> dict | None:
    """What a research request of this capture binds as its evidence: None for an ordinary source (its whole captured
    text); for a Go deeper source, the publishers' passages its origin record names, checked against the captured text
    (deeper_evidence). A Go deeper source whose record names none (story-deeper-0.1) is refused with UNMARKED."""
    found = _deeper_link(folders, capture_id)
    if found is None:
        return None
    data, link = found
    if not isinstance(link, dict):
        raise FlowRefused(409, f"The Go deeper record of capture {capture_id} cannot be read; nothing was prepared or "
                               "sent")
    if link.get("link_version") != DEEPER_LINK_VERSION or "evidence" not in link:
        raise FlowRefused(409, UNMARKED)
    evidence = link["evidence"]
    problem = deeper_evidence.problem(evidence, record["source_text"])
    if link.get("capture_id") != capture_id or problem:
        raise FlowRefused(409, f"The Go deeper record of capture {capture_id} does not fit its captured text "
                               f"({problem or 'it names another capture'}); nothing was prepared or sent")
    return {"evidence_version": evidence["evidence_version"], "link_sha256": sha256(data),
            "source_sha256": evidence["source_sha256"], "spans": evidence["spans"]}


def spans_of(verified: dict) -> list[dict] | None:
    """The publisher passages a verified request binds, or None when its whole captured text is evidence."""
    return verified["evidence"]["spans"] if verified["evidence"] is not None else None


def _read_back(request: object, event: dict, source_text: str) -> bool:
    expected = {**{key: event[key] for key in event_intake.EVENT_FIELDS}, "text": source_text}
    return event_intake.framed_inputs(event_intake.user_message(request)) == expected


def verified_request(request_id: str, folders: Folders) -> dict:
    """A prepared request with every binding checked again: its own bytes, the capture's files and request, and the
    capture's Inbox origin. Reads only; nothing is repaired."""
    match = REQUEST_ID_PATTERN.fullmatch(request_id or "")
    folder = folders.requests / request_id if match else None
    if folder is None or not folder.is_dir():
        raise FlowRefused(404, "Unknown research request ID")

    def refuse(problem: str) -> FlowRefused:
        return FlowRefused(409, f"Research request {request_id}: {problem}; it is not shown, and nothing was changed")

    names = sorted(path.name for path in folder.iterdir())
    if names != REQUEST_FILES:
        raise refuse(f"its folder holds {', '.join(names) or 'nothing'}, not exactly the request and its manifest")
    request_bytes = (folder / "request.json").read_bytes()
    try:
        manifest = strict_json((folder / "manifest.json").read_bytes())
        request = strict_json(request_bytes)
    except DraftRefused:
        raise refuse("request.json or manifest.json is not strict JSON") from None
    capture_id, prompt_version, effort = match.group(1), match.group(2), match.group(3)
    version = REQUEST_VERSION if effort is None else USER_REQUEST_VERSION
    reply = reply_of(prompt_version)
    if reply is None:
        raise refuse(f"it names {prompt_version}, a request contract this server does not read")
    try:
        recorded = manifest["request"]
        capture = manifest["capture"]
        if manifest["request_version"] != version or manifest["request_id"] != request_id or \
                manifest["prompt_version"] != prompt_version or capture["capture_id"] != capture_id:
            raise refuse("its manifest does not name this request, capture and prompt version")
        if recorded["sha256"] != sha256(request_bytes) or recorded["bytes"] != len(request_bytes):
            raise refuse("request.json no longer matches the SHA-256 and size its manifest records")
        if canonical(request).encode("utf-8") != request_bytes:
            raise refuse("request.json is not in the canonical form a preparation writes")
        stored = {"model": request["model"], "effort": request["output_config"]["effort"],
                  "max_tokens": request["max_tokens"]}
        if reply == "tool":  # research-prompt-1: one strict tool carries the reply.
            stored["tool"] = request["tools"][0]["name"]
            if len(request["tools"]) != 1 or stored != {key: recorded[key] for key in stored}:
                raise refuse("the stored request's model, effort, output limit or tool differ from its manifest")
        else:  # research-prompt-2: the reply is the JSON output format; no tool is offered.
            stored["format"] = request["output_config"]["format"]["type"]
            if "tools" in request or "tool_choice" in request or stored["format"] != "json_schema" or \
                    "tool" in recorded or stored != {key: recorded[key] for key in stored}:
                raise refuse("the stored request's model, effort, output limit or output format differ from its "
                             "manifest")
        prepared_by = manifest.get("prepared_by")
        if effort is not None and (stored["effort"] != effort or not isinstance(prepared_by, dict) or
                                   set(prepared_by) != {"user_id"} or
                                   not USER_ID.fullmatch(str(prepared_by["user_id"]))):
            raise refuse("its Effort or preparing account does not match its ID and manifest")
        if effort is None and prepared_by is not None:
            raise refuse("an operator's request names a preparing account")
    except (KeyError, TypeError, IndexError):
        raise refuse("its manifest or request lacks a required field") from None
    try:
        record = event_intake.verified(folders.intake, capture_id)
    except event_intake.IntakeRefused as exc:
        raise refuse(f"its capture does not verify ({exc})") from None
    bound = {"request_sha256": record["request"]["sha256"], "source_sha256": record["source"]["sha256"],
             "source_bytes": record["source"]["bytes"]}
    if bound != {key: capture.get(key) for key in bound} or manifest.get("event") != record["event"]:
        raise refuse("its capture's request, source or event differ from the ones it was prepared from")
    if not _read_back(request, record["event"], record["source_text"]):
        raise refuse("its user message does not read back as the capture's event and source text")
    try:
        _check_origin(folders, capture_id, manifest.get("origin"))
    except (*event_links.UNVERIFIED, KeyError) as exc:
        raise refuse(f"its Inbox origin binding does not hold ({exc})") from None
    evidence = manifest.get("evidence")
    if evidence is not None:  # Bound at preparation: the Go deeper record must still say exactly that.
        try:
            current = evidence_binding(folders, capture_id, record)
        except FlowRefused as exc:
            raise refuse(f"its evidence binding does not hold ({exc})") from None
        if current != evidence:
            raise refuse("its evidence binding differs from the Go deeper record of its capture")
    unmarked = evidence is None and _deeper_link(folders, capture_id) is not None
    return {"request_id": request_id, "capture_id": capture_id, "manifest": manifest, "request": request,
            "request_bytes": request_bytes, "request_sha256": recorded["sha256"], "record": record,
            "request_version": version, "effort": stored["effort"], "reply": reply,
            "prepared_by": prepared_by["user_id"] if effort is not None else None,
            "evidence": evidence, "unmarked": unmarked}


def current_code(verified: dict) -> dict:
    """Optional diagnostic: would today's builder produce the same bytes under the recorded prompt version?"""
    if verified["manifest"]["prompt_version"] != PROMPT_VERSION:
        return {"comparison": "different", "detail": f"prepared under {verified['manifest']['prompt_version']}; "
                                                     f"today's builder writes {PROMPT_VERSION}"}
    record = verified["record"]
    rebuilt = canonical(build_request(record["event"], record["source_text"], verified["effort"],
                                      PROMPT_VERSION)).encode("utf-8")
    if rebuilt == verified["request_bytes"]:
        return {"comparison": "identical", "detail": "today's research request builder produces exactly these bytes"}
    return {"comparison": "different", "detail": "today's research request builder produces different bytes; the "
                                                 "verified saved request is the one shown and the one that would be sent"}


def prepare(body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> tuple[dict, bool]:
    """Prepare the research request for one capture, or return the one already prepared. Writes only the new
    request's folder (staged, then renamed into place; never overwritten). Sends nothing."""
    payload = strict_object(body, ("capture_id",), "research request")
    record = _capture(folders, payload["capture_id"])
    return _prepare(record, payload["capture_id"], EFFORT, None, folders, clock)


def prepare_for_user(capture_id: str, effort: str, user_id: str, folders: Folders,
                     clock: Callable[[], datetime] = now) -> tuple[dict, bool]:
    """A user account's request for one capture, at one Effort: research-request-0.2, ID <capture_id>.<prompt
    version>.<effort>. The caller has checked that the account owns the capture and that the Effort is offered. The
    bytes differ from the operator's request only in output_config.effort. Sends nothing."""
    if effort not in EFFORTS or not USER_ID.fullmatch(user_id):
        raise FlowRefused(422, "Unknown Effort or account")
    return _prepare(_capture(folders, capture_id), capture_id, effort, {"user_id": user_id}, folders, clock)


def _prepare(record: dict, capture_id: str, effort: str, prepared_by: dict | None, folders: Folders,
             clock: Callable[[], datetime]) -> tuple[dict, bool]:
    request_id = f"{capture_id}.{PROMPT_VERSION}" + (f".{effort}" if prepared_by else "")
    if (folders.requests / request_id).exists():
        return verified_request(request_id, folders), False
    origin = _origin_binding(folders, capture_id)
    evidence = evidence_binding(folders, capture_id, record)  # A Go deeper source without passages is refused here.
    try:
        request = build_request(record["event"], record["source_text"], effort, PROMPT_VERSION)
    except KeyError:
        raise FlowRefused(409, "The capture's event cannot be framed for a research request") from None
    if not _read_back(request, record["event"], record["source_text"]):
        raise FlowRefused(409, "The research request would not read back as the capture's event and source text; "
                               "nothing was prepared")
    request_bytes = canonical(request).encode("utf-8")
    manifest = {
        "request_version": USER_REQUEST_VERSION if prepared_by else REQUEST_VERSION, "request_id": request_id,
        "prompt_version": PROMPT_VERSION, "mode": "evidence-first research analysis", "status": STATUS,
        "prepared_at": utc(clock()).isoformat(),
        "capture": {"capture_id": capture_id, "request_sha256": record["request"]["sha256"],
                    "request_prompt_version": record["request"]["prompt_version"],
                    "source_sha256": record["source"]["sha256"], "source_bytes": record["source"]["bytes"],
                    "captured_at": record["times"]["captured_at"]},
        "event": record["event"], "origin": origin,
        "request": {"sha256": sha256(request_bytes), "bytes": len(request_bytes), "model": MODEL, "effort": effort,
                    "max_tokens": MAX_TOKENS,
                    **({"tool": TOOL_NAME} if reply_of(PROMPT_VERSION) == "tool" else {"format": "json_schema"})},
        "baseline": BASELINE, "retrospective": RETROSPECTIVE, "code": code_identity(),
        "sent": False, "frozen": False, "evaluated": False,
        "statement": ("Prepared from the verified capture; the capture, its own request and its origin record were "
                      "only read. Nothing was sent."),
    }
    if prepared_by:
        manifest["prepared_by"] = prepared_by
    if evidence is not None:  # Absent for an ordinary source: its manifest keeps the shape it always had.
        manifest["evidence"] = evidence
    try:
        event_intake.save(folders.requests, request_id, {"request.json": request_bytes,
                                                         "manifest.json": _json_bytes(manifest)})
    except event_intake.IntakeRefused:  # Prepared at the same moment by another action: show that one.
        return verified_request(request_id, folders), False
    return verified_request(request_id, folders), True


# ---------------------------------------------------------------- attempts

def _reserve(folders: Folders, request_id: str) -> Path:
    """The reservation: the attempt folder, created exclusively. Code never releases it."""
    folders.attempts.mkdir(parents=True, exist_ok=True)
    attempt = folders.attempts / request_id
    try:
        attempt.mkdir()
    except FileExistsError:
        raise FlowRefused(409, "This research request already has an attempt; it is never sent or mocked twice") \
            from None
    return attempt


def _approved(request_id: str, request_sha256: object, folders: Folders, for_account: bool = False) -> dict:
    verified = verified_request(request_id, folders)
    if request_sha256 != verified["request_sha256"]:
        raise FlowRefused(409, "The confirmed request SHA-256 does not match the saved research request; nothing was "
                               "reserved or sent")
    if verified["request"].get("model") != MODEL:
        raise FlowRefused(409, f"This flow is bound to {MODEL}; the saved request names another model")
    if (verified["prepared_by"] is not None) != for_account:
        raise FlowRefused(409, "This research request was prepared for a user account; only that account's approved "
                               "credit quote runs it. Nothing was reserved or sent" if verified["prepared_by"] else
                               "This research request is the operator's; nothing was reserved or sent")
    if verified["unmarked"]:  # Its reply could only be read against the whole text, framing included.
        raise FlowRefused(409, UNMARKED)
    return verified


def approved_for_account(request_id: str, request_sha256: str, folders: Folders) -> dict:
    """A user's request, verified, approved by the SHA-256 its quote names and bound to this flow's model."""
    return _approved(request_id, request_sha256, folders, for_account=True)


def _action(request_id: str, folders: Folders, provider_called: bool) -> dict:
    """What a send established, read back from the records just written."""
    verified = verified_request(request_id, folders)
    try:
        view = result_view(verified, folders)
    except FlowRefused as exc:
        raise FlowRefused(500, f"The response was recorded, but it does not verify: {exc}. It is never sent again."
                          ) from None
    return {"flow_version": FLOW_VERSION, "request_id": request_id, "capture_id": verified["capture_id"],
            "mode": view["mode"], "outcome": view["outcome"], "recorded_outcome": view["recorded_outcome"],
            "provider_called": provider_called, "cost_usd": view["provenance"]["usage_cost_usd"], "attempts": 1,
            "retries": 0, "frozen": False, "evaluated": False}


def dispatch_mock(request_id: str, body: bytes, folders: Folders, clock: Callable[[], datetime] = now) -> dict:
    """Record one local mock attempt from the approved saved research request. $0; no provider is contacted."""
    confirmation = strict_object(body, ("request_sha256", "mock_outcome"), "mock approval")
    if not all(isinstance(confirmation[field], str) for field in confirmation):
        raise FlowRefused(422, "Every approval field must be text")
    if confirmation["mock_outcome"] not in MOCK_OUTCOMES:
        raise FlowRefused(422, f"mock_outcome must be one of {', '.join(MOCK_OUTCOMES)}")
    verified = _approved(request_id, confirmation["request_sha256"], folders)
    request_hash, request_bytes = verified["request_sha256"], verified["request_bytes"]
    # Built first: a fixture that cannot quote the source reserves nothing.
    response = mock_response(verified["request"], verified["record"]["source_text"], confirmation["mock_outcome"],
                             request_hash, spans_of(verified))
    attempt = _reserve(folders, request_id)
    try:
        names = {"pilot": MOCK_RUN, "request_id": request_id, "capture_id": verified["capture_id"], "model": MODEL,
                 "prompt_hash": request_hash}
        reserved_at = utc(clock()).isoformat()
        keep_record(attempt / "reservation.json", _json_bytes({**names, "mode": "mock", "reserved_at": reserved_at,
                                                               "pid": os.getpid(), "code": {"mode": "local mock"}}))
        keep_record(attempt / "request.json", request_bytes)  # The approved saved bytes, copied. Never rebuilt.
        sent_at = utc(clock()).isoformat()
        keep_record(attempt / "attempt.json", _json_bytes({"state": "mocking", "mode": "mock", "sent_at": sent_at,
                                                          "attempts": 1, "retries": 0}))
        keep_record(attempt / "response.json", response)
        received_at = utc(clock()).isoformat()
        read = classify(response, MODEL, verified["record"]["source_text"], spans_of(verified), verified["reply"])
        manifest = {
            **names, "request_version": REQUEST_VERSION, "flow_version": FLOW_VERSION, "synthetic": True,
            "effort": EFFORT, "max_tokens": verified["request"]["max_tokens"], "request_bytes": len(request_bytes),
            "endpoint": "local mock only; no endpoint contacted", "anthropic_version": None,
            "code": {"mode": "local mock", "flow_version": FLOW_VERSION}, "reserved_at": reserved_at,
            "sent_at": sent_at, "received_at": received_at, "elapsed_seconds": 0, "http_status": None,
            "request_id_provider": None, "response": {"sha256": sha256(response), "bytes": len(response),
                                                      **response_summary(response)},
            "outcome": read["outcome"], "adapter_message": read["problem"],
            "estimated_cost": {"usd": 0, "basis": "local mock"}, "planning_estimate_usd": None,
            "attempts": 1, "retries": 0, "fallbacks": None,
            "provenance": ("Generated locally from a deterministic mock fixture: synthetic content for testing the "
                           "workflow, not research. request.json is byte-for-byte the verified saved research request "
                           "approved by its SHA-256. No provider was contacted."),
        }
        keep_record(attempt / "manifest.json", _json_bytes(manifest))  # Written last: it marks completion.
    except Exception as exc:
        raise FlowRefused(500, f"The mock attempt was interrupted after it was reserved ({type(exc).__name__}). What "
                               "was written is kept, and this research request will not be attempted again.") from None
    return _action(request_id, folders, provider_called=False)


def paid_key(sender: PaidSender | None) -> str:
    """The key a paid send would use, checked for shape before anything is reserved (its value is never shown)."""
    if sender is None:
        raise FlowRefused(409, NOT_ENABLED)
    api_key = sender.api_key()
    problem = key_problem(api_key)
    if problem:
        raise FlowRefused(409, f"{problem}; nothing was reserved or sent")
    return api_key


def credential_free(verified: dict, api_key: str) -> None:
    if exposes(verified["request_bytes"], api_key):
        raise FlowRefused(409, "The saved request would carry the credential; nothing was reserved or sent")


def dispatch_paid(request_id: str, body: bytes, sender: PaidSender | None, folders: Folders,
                  clock: Callable[[], datetime] = now) -> dict:
    """Validate, reserve, send the approved saved bytes once and record the exchange. No retry or fallback."""
    if sender is None:
        raise FlowRefused(409, NOT_ENABLED)
    approval = checked_approval(body)
    api_key = paid_key(sender)
    verified = _approved(request_id, approval["request_sha256"], folders)
    estimate = research_cost(verified["request_bytes"])["estimated_real_run_if_output_reaches_max_usd"]
    if round(float(approval["estimated_max_usd"]), 4) != estimate:
        raise FlowRefused(409, f"The approved estimate does not match this request's planning estimate (${estimate}); "
                               "nothing was reserved or sent")
    credential_free(verified, api_key)
    send_once(verified, sender, api_key, folders, clock, estimate)
    return _action(request_id, folders, provider_called=True)


ACCOUNT_PROVENANCE = ("Sent once by this server to the Claude API after a user account approved a credit quote under "
                      "the administrator's policy. request.json holds the exact bytes sent: the saved research request, "
                      "never rebuilt. response.json, when present, holds the exact bytes received after the credential "
                      "check. The provider request ID links the call to the Console.")


def send_once(verified: dict, sender: PaidSender, api_key: str, folders: Folders, clock: Callable[[], datetime],
              estimate: float, before_send: Callable[[], bool] | None = None, account: dict | None = None) -> None:
    """Reserve the request's one attempt folder, copy the verified saved bytes, send them once and record the
    exchange; the manifest is written last. ``before_send`` runs after the request copy is written and before the
    send is recorded as started: if it returns False, nothing is sent (the attempt stays reserved and blocks another).
    ``account`` (a user's run) is recorded in the reservation and the manifest."""
    request_id, request, request_bytes = verified["request_id"], verified["request"], verified["request_bytes"]
    identity = code_identity()  # Captured before sending, and kept with the reservation.
    attempt = _reserve(folders, request_id)

    sent_at = None
    try:
        names = {"pilot": PAID_RUN, "request_id": request_id, "capture_id": verified["capture_id"], "model": MODEL,
                 "prompt_hash": verified["request_sha256"]}
        reserved_at = utc(clock()).isoformat()
        reservation = {**names, "mode": "paid", "reserved_at": reserved_at, "pid": os.getpid(), "code": identity}
        if account is not None:
            reservation["account"] = account
        keep_record(attempt / "reservation.json", _json_bytes(reservation), api_key)
        keep_record(attempt / "request.json", request_bytes, api_key)  # Exactly the bytes about to be sent.
        seen: dict = {}

        def observe(response: httpx.Response) -> None:  # Status and request ID only; send_bytes checks the body.
            seen["http_status"] = response.status_code
            provider_id = response.headers.get("request-id", "")
            if REQUEST_ID.fullmatch(provider_id) and api_key not in provider_id:
                seen["request_id"] = provider_id

        if before_send is not None and not before_send():
            raise FlowRefused(409, "The run was released before it was sent; nothing was sent, and this research "
                                   "request will not be attempted again")
        sent_at = utc(clock())
        keep_record(attempt / "attempt.json", _json_bytes({"state": "sending", "mode": "paid",
                                                          "sent_at": sent_at.isoformat(), "attempts": 1,
                                                          "retries": 0}), api_key)
        received, message, provider_error = None, None, None
        try:
            with sender.client_factory(observe) as client:
                received = send_bytes(client, request_bytes, api_key)  # The one transport call.
        except DraftRefused as exc:
            provider_error = error_diagnostics(exc, api_key)
            message = str(exc).replace("no draft was produced", "no analysis was produced")
            outcome = ("credential echo" if "contained the credential" in message
                       else "transport error" if message.startswith("The model request failed") else "provider error")
            if outcome == "transport error":
                message = f"{message}. {UNKNOWN}"
        received_at = utc(clock())
        summary = {}
        if received is not None:
            keep_record(attempt / "response.json", received, api_key)
            summary = response_summary(received)
            read = classify(received, MODEL, verified["record"]["source_text"], spans_of(verified),
                            verified["reply"])
            outcome, message = read["outcome"], read["problem"]
        manifest = {
            **names, "request_version": verified["request_version"], "flow_version": FLOW_VERSION, "synthetic": False,
            "effort": request["output_config"]["effort"], "max_tokens": request["max_tokens"],
            "request_bytes": len(request_bytes), "endpoint": MESSAGES_URL, "anthropic_version": API_VERSION,
            "code": identity, "reserved_at": reserved_at, "sent_at": sent_at.isoformat(),
            "received_at": received_at.isoformat(), "elapsed_seconds": (received_at - sent_at).total_seconds(),
            "http_status": seen.get("http_status"), "request_id_provider": seen.get("request_id"),
            "provider_error": provider_error,
            "response": None if received is None else {"sha256": sha256(received), "bytes": len(received),
                                                       **summary},
            "outcome": outcome, "adapter_message": message, "estimated_cost": usage_cost(summary.get("usage")),
            "planning_estimate_usd": estimate, "attempts": 1, "retries": 0, "fallbacks": None,
            "provenance": ACCOUNT_PROVENANCE if account is not None else (
                "Sent once by this server to the Claude API after an explicit paid approval. request.json holds the "
                "exact bytes sent: the approved saved research request, never rebuilt. response.json, when present, "
                "holds the exact bytes received after the credential check. The provider request ID links the call to "
                "the Console."),
        }
        if account is not None:
            manifest["account"] = account
        keep_record(attempt / "manifest.json", _json_bytes(manifest), api_key)  # Written last: it marks completion.
    except FlowRefused:
        raise
    except Exception as exc:
        sent = f" after it was sent. {UNKNOWN}" if sent_at is not None else " before it was sent."
        raise FlowRefused(500, f"The paid attempt was interrupted ({type(exc).__name__}){sent} What was written is "
                               "kept, and this research request will not be attempted again.") from None


def attempt_state(request_id: str, folders: Folders) -> dict:
    """What has been recorded for one research request: none, incomplete (reserved, no manifest; it blocks another
    attempt) or recorded. Reads only; a recorded attempt is verified when its view is built."""
    attempt = folders.attempts / request_id
    state = {"request_id": request_id, "provider_called": False, "mode": None, "sent": False, "sent_at": None}
    if not attempt.is_dir():
        return {**state, "state": "none", "files": [], "detail": "No attempt is recorded: nothing was sent or run."}
    names = sorted(path.name for path in attempt.iterdir() if not path.name.startswith(".tmp-"))
    state |= _recorded_mode(attempt, names)
    if "manifest.json" in names:
        return {**state, "state": "recorded", "files": names, "detail": "A response or failure is recorded."}
    if state["mode"] == "paid" and state["sent"]:
        detail = (f"A paid request was sent at {state['sent_at']} and no response is recorded. It may still be in "
                  "flight, or the server stopped before recording it; the provider may have received and billed it. "
                  "It is never sent again; reading this state sends nothing.")
    elif state["mode"] == "paid":
        detail = "A paid request was reserved but not sent. The reservation is kept and blocks another attempt."
    else:
        detail = "An attempt was reserved but did not finish. It is kept as recorded and blocks another attempt."
    return {**state, "state": "incomplete", "files": names, "detail": detail}


def result_view(verified: dict, folders: Folders) -> dict:
    """The research-result-view-0.1 of a recorded attempt, built from its saved files and the verified request and
    capture. The outcome is recomputed from the response bytes and must equal the recorded one."""
    request_id = verified["request_id"]
    attempt = folders.attempts / request_id

    def refuse(problem: str) -> FlowRefused:
        return FlowRefused(409, f"The recorded attempt of {request_id} does not verify: {problem}")

    try:
        manifest = strict_json((attempt / "manifest.json").read_bytes())
        attempt_request = (attempt / "request.json").read_bytes()
    except (OSError, DraftRefused):
        raise refuse("its manifest or request copy cannot be read") from None
    if attempt_request != verified["request_bytes"]:
        raise refuse("its request.json is not the approved saved request")
    if not isinstance(manifest, dict) or manifest.get("request_id") != request_id or \
            manifest.get("prompt_hash") != verified["request_sha256"] or manifest.get("pilot") not in (MOCK_RUN,
                                                                                                     PAID_RUN):
        raise refuse("its manifest does not name this request")
    mode = "mock" if manifest["pilot"] == MOCK_RUN else "paid"
    recorded, kept = manifest.get("outcome"), manifest.get("response")
    response_path = attempt / "response.json"
    read = {"outcome": recorded, "problem": manifest.get("adapter_message"), "analysis": None, "model_text": None}
    if kept is None:
        if recorded not in ("provider error", "transport error", "credential echo") or response_path.exists():
            raise refuse("it records no response, yet its outcome or files say otherwise")
    else:
        try:
            received = response_path.read_bytes()
        except OSError:
            raise refuse("its response.json is missing") from None
        if not isinstance(kept, dict) or kept.get("sha256") != sha256(received):
            raise refuse("its response.json no longer matches the recorded SHA-256")
        read = classify(received, MODEL, verified["record"]["source_text"], spans_of(verified), verified["reply"])
        if read["outcome"] != recorded:
            raise refuse(f"the response reads as {read['outcome']!r} under today's contract, not the recorded "
                         f"{recorded!r}")
    if recorded not in OUTCOMES:
        raise refuse("its recorded outcome is unknown")
    cost = manifest.get("estimated_cost") if isinstance(manifest.get("estimated_cost"), dict) else {}
    return {
        "view_version": VIEW_VERSION, "request_id": request_id, "capture_id": verified["capture_id"],
        "prompt_version": verified["manifest"]["prompt_version"], "mode": mode, "synthetic": mode == "mock",
        "outcome": OUTCOMES[recorded], "recorded_outcome": recorded, "outcome_note": OUTCOME_NOTES[recorded],
        "problem": read["problem"], "model_text": read["model_text"], "analysis": read["analysis"],
        "baseline": BASELINE, "retrospective": RETROSPECTIVE,
        "provenance": {"request_sha256": verified["request_sha256"],
                       "response_sha256": kept.get("sha256") if isinstance(kept, dict) else None,
                       "response_id": kept.get("id") if isinstance(kept, dict) else None,
                       "model": kept.get("model") if isinstance(kept, dict) else None,
                       "stop_reason": kept.get("stop_reason") if isinstance(kept, dict) else None,
                       "usage": kept.get("usage") if isinstance(kept, dict) else None,
                       "sent_at": manifest.get("sent_at"), "received_at": manifest.get("received_at"),
                       "http_status": manifest.get("http_status"),
                       "provider_request_id": manifest.get("request_id_provider"),
                       "planning_estimate_usd": manifest.get("planning_estimate_usd"),
                       "usage_cost_usd": cost.get("usd"), "usage_cost_basis": cost.get("basis")},
        "frozen": False, "evaluated": False,
    }


def view_bytes(view: dict) -> bytes:
    return canonical(view).encode("utf-8")


def fingerprint(view: dict) -> str:
    """What a review is bound to: the SHA-256 of the result view's canonical bytes, as built now."""
    return sha256(view_bytes(view))


# ---------------------------------------------------------------- reviews

def review_id(record: dict) -> str:
    return digest({key: value for key, value in record.items() if key != "review_id"})


def review_version(request_id: str) -> str:
    """research-review-0.1 for an operator's request; research-review-0.2 (a user's own review) for a user's."""
    match = REQUEST_ID_PATTERN.fullmatch(request_id)
    return USER_RECORD_VERSION if match and match.group(3) else RECORD_VERSION


def review_history(folders: Folders, request_id: str) -> list[dict]:
    """Every saved review version, oldest first, verified: contiguous numbering, content IDs and parent chain."""
    folder = folders.reviews / request_id
    if not folder.is_dir():
        return []
    names = sorted(path.name for path in folder.iterdir() if not path.name.startswith(".tmp-"))
    records = []
    for position, name in enumerate(names, start=1):
        match = VERSION_FILE.fullmatch(name)
        if not match or int(match.group(1)) != position:
            raise FlowRefused(500, f"The saved research reviews are inconsistent: unexpected file {name}")
        try:
            record = strict_json((folder / name).read_bytes())
        except DraftRefused:
            raise FlowRefused(500, f"The saved research reviews are inconsistent: {name} is not strict JSON") from None
        parent = records[-1]["review_id"] if records else None
        if not isinstance(record, dict) or record.get("record_version") != review_version(request_id) \
                or record.get("request_id") != request_id or record.get("sequence") != position \
                or record.get("parent_review_id") != parent or record.get("review_id") != review_id(record):
            raise FlowRefused(500, f"The saved research reviews are inconsistent at version {position}")
        records.append(record)
    return records


def notes_problem(notes: object) -> str | None:
    """Why review notes are refused, naming the actual rule (QA-4): not text, too many characters, or a control
    character other than a tab or a line break. None when they are acceptable."""
    if not isinstance(notes, str):
        return "notes must be text"
    if len(notes) > MAX_NOTES:
        return f"notes are limited to {MAX_NOTES:,} characters; these have {len(notes):,}"
    if CONTROL.search(notes):
        return "notes cannot contain control characters other than tabs and line breaks"
    return None


def save_review(request_id: str, body: bytes, folders: Folders,
                clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> dict:
    """Append one review version, bound to the result view the page loaded. The response, request and capture are
    only read; a review never changes the analysis."""
    if len(body) > MAX_REVIEW_BODY:
        raise FlowRefused(413, f"A review is limited to {MAX_REVIEW_BODY} bytes")
    payload = strict_object(body, REVIEW_FIELDS, "review", limit=MAX_REVIEW_BODY)
    verified = verified_request(request_id, folders)
    if verified["prepared_by"] is not None:
        raise FlowRefused(409, "This analysis belongs to a user account; only that account reviews it")
    if attempt_state(request_id, folders)["state"] != "recorded":
        raise FlowRefused(409, "No recorded result exists for this research request, so there is nothing to review")
    view = result_view(verified, folders)
    current = {"result_view_sha256": fingerprint(view), "request_sha256": verified["request_sha256"],
               "response_sha256": view["provenance"]["response_sha256"]}
    binding = payload["binding"]
    if not isinstance(binding, dict) or set(binding) != set(BINDING_FIELDS):
        raise FlowRefused(422, f"binding must contain exactly {', '.join(BINDING_FIELDS)}")
    if binding != current:
        raise FlowRefused(409, "The result has changed since it was loaded; reload it before saving")
    status, notes, parent = payload["status"], payload["notes"], payload["parent_review_id"]
    if status is not None and status not in STATUSES:
        raise FlowRefused(422, f"status must be null or one of {', '.join(STATUSES)}")
    problem = notes_problem(notes)
    if problem:
        raise FlowRefused(422, problem)
    if status is None and not notes.strip():
        raise FlowRefused(422, "A review needs notes or a status")
    if parent is not None and not (isinstance(parent, str) and SHA256.fullmatch(parent)):
        raise FlowRefused(422, "parent_review_id must be null or a review ID")
    records = review_history(folders, request_id)
    latest = records[-1] if records else None
    if parent != (latest["review_id"] if latest else None):
        raise FlowRefused(409, "Another review version was saved since this result was loaded; reload to see it")
    saved = latest.get("binding") if latest is not None and isinstance(latest.get("binding"), dict) else {}
    if latest is not None and saved.get("result_view_sha256") == current["result_view_sha256"] and \
            (latest.get("status"), latest.get("notes")) == (status, notes):
        raise FlowRefused(422, "Nothing changed since the last saved version")
    record = {"record_version": RECORD_VERSION, "request_id": request_id, "sequence": len(records) + 1,
              "parent_review_id": parent, "saved_at": clock().astimezone(timezone.utc).isoformat(),
              "attributed_to": ATTRIBUTION, "status": status, "notes": notes,
              "binding": {**current, "result_view_version": VIEW_VERSION, "outcome": view["outcome"],
                          "mode": view["mode"]}}
    record["review_id"] = review_id(record)
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    try:
        write_exclusively(folders.reviews / request_id, f"{record['sequence']:06d}.json", data)
    except ReviewRefused as exc:
        raise FlowRefused(exc.status, str(exc)) from None
    return record


# ---------------------------------------------------------------- reads for the interface and the history

def show(request_id: str, folders: Folders) -> dict:
    """One research request as the interface shows it: the verified saved request with its cost decision, what its
    attempt recorded, the result view (only when one is recorded and verifies) and the review versions. Reads only:
    nothing is sent, written or repaired. Modes are added by the API."""
    verified = verified_request(request_id, folders)
    manifest = verified["manifest"]
    attempt = attempt_state(request_id, folders)
    view, problem = None, None
    if attempt["state"] == "recorded":
        try:
            view = result_view(verified, folders)
        except FlowRefused as exc:
            attempt = {**attempt, "state": "invalid", "detail": str(exc)}
            problem = str(exc)
    try:
        reviews = {"state": "verified", "records": review_history(folders, request_id), "problem": None}
    except FlowRefused as exc:
        reviews = {"state": "invalid", "records": [], "problem": str(exc)}
    request = verified["request"]
    return {
        "flow_version": FLOW_VERSION, "request_version": verified["request_version"], "request_id": request_id,
        "prepared_by": verified["prepared_by"],
        "capture_id": verified["capture_id"],
        "status": STATUS if attempt["state"] == "none" else f"Attempt {attempt['state']}",
        "prompt_version": manifest["prompt_version"], "model": request["model"],
        "effort": request["output_config"]["effort"], "max_tokens": request["max_tokens"],
        "tool": TOOL_NAME if verified["reply"] == "tool" else None, "reply_format": REPLY_FORMATS[verified["reply"]],
        "request_sha256": verified["request_sha256"], "request_bytes": len(verified["request_bytes"]),
        "request": request, "prepared_at": manifest["prepared_at"], "event": manifest["event"],
        "capture": manifest["capture"], "origin": manifest["origin"], "baseline": BASELINE,
        "retrospective": RETROSPECTIVE, "not_an_analysis": NOT_SENT, "current_code": current_code(verified),
        "cost_estimate": research_cost(verified["request_bytes"]), "provider_called": False,
        "attempt": attempt, "result": view, "result_view_sha256": fingerprint(view) if view else None,
        "result_problem": problem, "reviews": reviews,
    }


def requests_for(capture_id: str, folders: Folders) -> list[dict]:
    """Every research request prepared from one capture, oldest prompt version first, each verified, with its
    attempt state, outcome and reviews. Reads only; a request that does not verify is listed with its problem."""
    rows = []
    folder = folders.requests
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        match = REQUEST_ID_PATTERN.fullmatch(path.name)
        if not match or match.group(1) != capture_id:
            continue
        try:
            shown = show(path.name, folders)
        except (FlowRefused, OSError) as exc:
            rows.append({"request_id": path.name, "state": "refused", "problem": str(exc)})
            continue
        view = shown["result"]
        rows.append({"request_id": path.name, "state": "verified", "prompt_version": shown["prompt_version"],
                     "prepared_at": shown["prepared_at"], "request_sha256": shown["request_sha256"],
                     "planning_estimate_usd":
                         shown["cost_estimate"]["estimated_real_run_if_output_reaches_max_usd"],
                     "attempt": shown["attempt"],
                     "result": None if view is None else {
                         key: view[key] for key in ("mode", "outcome", "recorded_outcome", "problem")} | {
                         "received_at": view["provenance"]["received_at"],
                         "sent_at": view["provenance"]["sent_at"],
                         "usage_cost_usd": view["provenance"]["usage_cost_usd"],
                         "planning_estimate_usd": view["provenance"]["planning_estimate_usd"],
                         "provider_request_id": view["provenance"]["provider_request_id"],
                         "result_view_sha256": shown["result_view_sha256"]},
                     "reviews": shown["reviews"]})
    return rows


def paid_status(sender: PaidSender | None) -> dict:
    """Whether this server can send a paid research request. Never reveals or checks the key beyond its shape."""
    if sender is None:
        return {"enabled": False, "detail": NOT_ENABLED}
    problem = key_problem(sender.api_key())
    return {"enabled": problem is None, "detail": f"{problem}; paid sending is unavailable" if problem else
            f"Paid sending is enabled: one explicitly approved request per research request to {MODEL}."}
