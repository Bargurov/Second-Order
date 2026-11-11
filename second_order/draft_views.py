"""Prepared review views of saved draft attempts. An explicit offline step builds them; read paths only serve them.

Each view comes from one saved pilot attempt directory and its original records only: request.json (the
exact bytes sent), response.json (the exact bytes received, when a response arrived) and manifest.json. The
recorded hashes are verified, and the source is read from the recorded request, never rebuilt from the
current case fixtures or prompt builder. A mismatch, or a source that cannot be extracted unambiguously,
refuses the preparation: nothing is guessed, repaired or written.

A view exposes the source (untrusted plain text), the model's public draft or decline text and selected
provenance. It never carries thinking blocks, the system prompt, headers, credentials or the raw records.
A draft is not frozen: a view has no freeze time, evaluation, chart or ranking, and validation of its
structure says nothing about its reasoning.
"""
import hashlib
import json
import os
from pathlib import Path
import re
from pydantic import ValidationError
from .draft_review import NO_DRAFT
from .model_draft import SAFE_WORD, TOOL_NAME, DraftRefused, envelope, errors, parse_response, strict_json
from .schema import Hypothesis
from .store import digest

DRAFT_VIEW_VERSION = "draft-review-view-0.1"
ROOT = Path(__file__).resolve().parent.parent
DRAFTS_DIR = ROOT / "data" / "prepared-drafts"
PILOT_ROOT = ROOT / "data" / "pilot"
INDEX_NAME = "drafts-index.json"
REVIEW_STATUS = "Not frozen · Requires human review"
# Recorded pilot outcomes, grouped for review: a decline is not an invalid response or a technical failure.
OUTCOMES = {"draft": "draft", "no draft": "no_draft", "refused": "invalid", "provider error": "technical_failure",
            "transport error": "technical_failure", "credential echo": "technical_failure"}
MANIFEST_FIELDS = ("pilot", "case", "model", "prompt_version", "prompt_hash", "request_bytes", "request_id",
                   "reserved_at", "sent_at", "received_at", "http_status", "outcome", "adapter_message", "response",
                   "synthetic_case")
SOURCE_FIELDS = ("Headline: ", "Source URL: ", "Published at (UTC): ")
OPEN, CLOSE = "<source_text>", "</source_text>"
CREDENTIAL = re.compile(r"sk-ant-[A-Za-z0-9_-]{8,}")


class ProvenanceError(ValueError):
    pass


def refuse(attempt: Path, problem: str) -> ProvenanceError:
    return ProvenanceError(f"{attempt.name}: {problem}; nothing was prepared")


def read_record(attempt: Path, name: str) -> tuple[bytes, object]:
    """A recorded file's exact bytes and its strictly parsed JSON (no repeated keys or NaN)."""
    path = attempt / name
    if not path.is_file():
        raise refuse(attempt, f"{name} is missing")
    data = path.read_bytes()
    try:
        return data, strict_json(data)
    except DraftRefused:
        raise refuse(attempt, f"{name} is not strict JSON") from None


def extract_source(attempt: Path, content: object) -> dict:
    """The event and source text exactly as the recorded request stated them, or a refusal."""
    if not isinstance(content, str) or content.count(OPEN) != 1 or content.count(CLOSE) != 1 \
            or not content.endswith(f"\n{CLOSE}"):
        raise refuse(attempt, "the source text cannot be extracted unambiguously from the recorded request")
    head, separator, rest = content.partition(f"\n\n{OPEN}\n")
    preamble, _, fields = head.rpartition("\n\n")
    lines = fields.split("\n")
    if not separator or not preamble or len(lines) != len(SOURCE_FIELDS) \
            or not all(line.startswith(prefix) for line, prefix in zip(lines, SOURCE_FIELDS)):
        raise refuse(attempt, "the recorded request does not state one headline, source URL and publication time")
    headline, source_url, published_at = (line[len(prefix):] for line, prefix in zip(lines, SOURCE_FIELDS))
    text = rest[:-len(f"\n{CLOSE}")]
    if not headline.strip() or not text.strip():
        raise refuse(attempt, "the recorded request has an empty headline or source text")
    return {"headline": headline, "source_url": source_url, "published_at": published_at, "text": text}


def offered(attempt: Path, request: dict) -> tuple[str, ...]:
    """The observables the recorded request offered, read from its own tool schema."""
    tools = request.get("tools")
    try:
        (tool,) = tools
        enum = tool["input_schema"]["properties"]["legs"]["items"]["properties"]["observable_id"]["enum"]
    except (KeyError, TypeError, ValueError):
        raise refuse(attempt, "the recorded request does not define the draft tool's observables") from None
    if tool.get("name") != TOOL_NAME or not (isinstance(enum, list) and enum and all(isinstance(item, str)
                                                                                    for item in enum)):
        raise refuse(attempt, "the recorded request does not define the draft tool's observables")
    return tuple(enum)


def check_map(attempt: Path, source: dict, manifest: dict, draft: dict) -> None:
    """The adapter's own map rules. Validation only: the placeholder story and time are never stored or shown."""
    try:
        Hypothesis.model_validate({
            "event": {key: source[key] for key in ("headline", "source_url", "published_at")},
            "frozen_at": source["published_at"], "evidence_class": "prospective", "usage": "showcase",
            "story_id": "validation-only", "summary": draft["summary"], "nodes": draft["nodes"],
            "edges": draft["edges"], "legs": draft["legs"],
            "engine": {"provider": "anthropic", "model": manifest["model"], "prompt_hash": manifest["prompt_hash"]}})
    except ValidationError as exc:
        raise refuse(attempt, f"the recorded draft breaks the map rules ({errors(exc)})") from None


def build_view(attempt: Path) -> dict:
    _, manifest = read_record(attempt, "manifest.json")
    request_bytes, request = read_record(attempt, "request.json")
    _, reservation = read_record(attempt, "reservation.json")
    if not isinstance(manifest, dict) or any(field not in manifest for field in MANIFEST_FIELDS):
        raise refuse(attempt, "manifest.json lacks the recorded provenance fields")
    outcome = OUTCOMES.get(manifest["outcome"])
    if outcome is None:
        raise refuse(attempt, f"the recorded outcome {manifest['outcome']!r} is not recognised")
    if hashlib.sha256(request_bytes).hexdigest() != manifest["prompt_hash"] \
            or len(request_bytes) != manifest["request_bytes"]:
        raise refuse(attempt, "request.json does not match the recorded prompt hash")
    if not isinstance(reservation, dict) or any(reservation.get(key) != manifest[key]
                                                for key in ("pilot", "case", "model", "prompt_hash")):
        raise refuse(attempt, "reservation.json does not match the manifest")
    if not isinstance(request, dict) or request.get("model") != manifest["model"]:
        raise refuse(attempt, "the recorded request names a different model")
    messages = request.get("messages")
    if not (isinstance(messages, list) and len(messages) == 1 and isinstance(messages[0], dict)
            and messages[0].get("role") == "user"):
        raise refuse(attempt, "the recorded request does not hold exactly one user message")
    source = extract_source(attempt, messages[0].get("content"))

    recorded, response_path = manifest["response"], attempt / "response.json"
    draft, explanation, problem = None, None, None
    if recorded is None:
        if response_path.exists() or outcome != "technical_failure":
            raise refuse(attempt, "the recorded outcome and the presence of response.json disagree")
        problem = manifest["adapter_message"]
    else:
        body = response_path.read_bytes() if response_path.is_file() else None
        if body is None or not isinstance(recorded, dict) or len(body) != recorded.get("bytes") \
                or hashlib.sha256(body).hexdigest() != recorded.get("sha256"):
            raise refuse(attempt, "response.json does not match the recorded response hash")
        try:
            output, meta = parse_response(body, manifest["model"], offered(attempt, request))
            derived = "draft"
        except DraftRefused as exc:
            meta, derived = None, "no_draft" if str(exc).startswith(NO_DRAFT) else "invalid"
            problem = str(exc) if derived == "invalid" else None
        if derived != outcome:
            raise refuse(attempt, f"the recorded outcome {manifest['outcome']!r} does not match the response")
        if meta is not None and meta["response_id"] != recorded.get("id"):
            raise refuse(attempt, "the response ID does not match the manifest")
        if outcome == "draft":
            draft = output.model_dump(mode="json")
            check_map(attempt, source, manifest, draft)
        elif outcome == "no_draft":
            message = envelope(strict_json(body))  # The adapter accepted this envelope before its stop check.
            details = message.get("stop_details") or {}
            category, said = details.get("category"), details.get("explanation")
            safe_category = isinstance(category, str) and SAFE_WORD.fullmatch(category)
            explanation = {"text": [block["text"] for block in message["content"] if isinstance(block, dict)
                                    and block.get("type") == "text" and isinstance(block.get("text"), str)],
                           "stop_reason": message["stop_reason"], "category": category if safe_category else None,
                           "provider_explanation": said if isinstance(said, str) else None}
    view = {
        "view_version": DRAFT_VIEW_VERSION,
        "id": digest({key: manifest[key] for key in ("pilot", "case", "prompt_hash", "sent_at")}),
        "review_status": REVIEW_STATUS, "outcome": outcome, "source": source, "draft": draft,
        "explanation": explanation, "problem": problem,
        "provenance": {
            "pilot": manifest["pilot"], "case": manifest["case"], "synthetic_case": manifest["synthetic_case"],
            "model": manifest["model"], "effort": (request.get("output_config") or {}).get("effort"),
            "max_tokens": request.get("max_tokens"), "prompt_version": manifest["prompt_version"],
            "prompt_hash": manifest["prompt_hash"], "request_id": manifest["request_id"],
            "reserved_at": manifest["reserved_at"], "sent_at": manifest["sent_at"],
            "received_at": manifest["received_at"], "http_status": manifest["http_status"],
            "recorded_outcome": manifest["outcome"],
            "response_sha256": recorded["sha256"] if recorded else None},
    }
    if CREDENTIAL.search(json.dumps(view)):
        raise refuse(attempt, "the view would contain a credential-like string")
    return view


def index_entry(view: dict) -> dict:
    return {"id": view["id"], "pilot": view["provenance"]["pilot"], "case": view["provenance"]["case"],
            "headline": view["source"]["headline"], "published_at": view["source"]["published_at"],
            "outcome": view["outcome"], "model": view["provenance"]["model"],
            "prompt_version": view["provenance"]["prompt_version"], "sent_at": view["provenance"]["sent_at"]}


def write_json(path: Path, payload: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                         encoding="utf-8")
    os.replace(temporary, path)


def prepare_drafts(attempts: list[Path], out_dir: Path = DRAFTS_DIR, pilot_root: Path = PILOT_ROOT) -> dict:
    """Explicit preparation of the selected attempts. Every view is built before any file is written."""
    if not attempts:
        raise ValueError("Name at least one saved attempt directory with --attempt")
    target = out_dir.resolve()
    for protected in [pilot_root, *attempts]:
        if target == protected.resolve() or protected.resolve() in target.parents:
            raise ValueError(f"The output directory {out_dir} is inside saved pilot records; nothing was prepared")
    views = [build_view(attempt) for attempt in attempts]
    if len({view["id"] for view in views}) != len(views):
        raise ValueError("The same attempt was selected twice; nothing was prepared")
    out_dir.mkdir(parents=True, exist_ok=True)
    for view in views:
        write_json(out_dir / f"draft-{view['id']}.json", view)
    index = {"view_version": DRAFT_VIEW_VERSION,
             "drafts": sorted((index_entry(view) for view in views), key=lambda row: (row["sent_at"], row["id"]))}
    write_json(out_dir / INDEX_NAME, index)
    return index
