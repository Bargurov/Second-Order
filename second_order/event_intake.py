"""Offline event intake: capture an operator-supplied published event and its source text, then preview
the exact model request that would be sent. Nothing is sent and nothing is frozen.

This is manual intake by an operator, not automated ingestion: nothing is fetched, scheduled or inferred.
The operator supplies the headline, source URL, publication time, story ID, one UTF-8 source-text file and
an explicit model ID. Validation reuses the drafting adapter's operator check and request builder
unchanged, and refuses before any record exists:
- invalid metadata or a publication time in the future (the adapter's operator check);
- an empty or oversized source (the adapter's request builder; nothing is truncated or repaired);
- a source that is not valid UTF-8, or a model ID that is not a plain lowercase identifier;
- ambiguous framing: a line break or control character in the headline or story ID, any
  <source_text> or </source_text> tag (in any letter case or spacing) in the metadata or source, or a
  built request whose user message does not read back exactly as the supplied event and source.

A capture is a new directory under data/intake (git-ignored), written to a staging directory and then
renamed into place, so a record is complete or absent. Existing records are never overwritten, and their
files are made read-only. A capture keeps the exact source bytes, the exact canonical request bytes, and a
manifest with their SHA-256 hashes, the normalized metadata, the prompt version, model, effort, token limit
and the request builder's code identity. The publication time is operator-supplied and not verified here;
the capture time is our clock when the record was written. Capturing older material now is not evidence
that we held it earlier.

Preview first verifies the stored record on its own terms: every manifest field the stored bytes can confirm
(hashes, byte and character counts, canonical form, model, effort, token limit, framing, times, capture ID and
status) must match, or the capture is refused and nothing is shown. Labels are then read from the verified
request itself. Only after that, as an optional diagnostic, preview asks whether today's request builder would
produce the same bytes; if today's builder refuses the old inputs, that comparison is reported as unavailable
and the verified original request is still shown. These checks compare the record with itself; they are not
external verification of its origin. This module creates no HTTP client, reads no credentials and opens no
database.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Callable
import unicodedata
from .draft_views import ProvenanceError, extract_source
from .model_draft import (CONTRACTS, DraftRefused, MESSAGES_URL, PROMPT_VERSION, build_request, contract_observables,
                          operator_event, strict_json)
from .schema import utc
from .store import canonical, digest

INTAKE_VERSION = "event-intake-1"
STATUS = "Nothing sent · Not frozen"
ROOT = Path(__file__).resolve().parent.parent
INTAKE_DIR = ROOT / "data" / "intake"
MANIFEST, SOURCE, REQUEST = "capture.json", "source.txt", "request.json"
MODEL_ID = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")
FRAMING_TAG = re.compile(r"<\s*/?\s*source_text\s*>", re.IGNORECASE)
CODE_FILES = ("second_order/model_draft.py", "second_order/event_intake.py")
PUBLISHED_NOTE = "Supplied by the operator; not verified by this tool."
CAPTURED_NOTE = ("Our clock when this record was written. It shows possession from then on; it is not evidence "
                 "that the material was available to us, or held by us, any earlier.")
CAPTURE_ID = re.compile(r"\d{8}T\d{12}Z-[0-9a-f]{12}")
OPEN, CLOSE = "<source_text>", "</source_text>"
FIELD_PREFIXES = ("Headline: ", "Source URL: ", "Published at (UTC): ")
EVENT_FIELDS = ("headline", "source_url", "published_at")
TIME_FIELDS = ("published_at", "published_at_as_supplied", "published_at_note", "captured_at", "captured_at_note")
# Every capture.json and request.json value that verification, preview or list reads, with its exact type.
MANIFEST_FIELDS = (("capture_id", str), ("status", str), ("sent", bool), ("frozen", bool),
                   *((f"event.{key}", str) for key in EVENT_FIELDS),
                   *((f"times.{key}", str) for key in TIME_FIELDS),
                   ("source.sha256", str), ("source.bytes", int), ("source.characters", int),
                   ("request.sha256", str), ("request.bytes", int), ("request.model", str),
                   ("request.effort", str), ("request.max_tokens", int), ("request.prompt_version", str))
REQUEST_FIELDS = (("model", str), ("output_config.effort", str), ("max_tokens", int))
CHECKED = ("source.txt matches its recorded SHA-256, byte count and character count, and is valid UTF-8",
           "request.json matches its recorded SHA-256 and byte count, and is in the canonical form a capture writes",
           "the recorded model, effort and max_tokens equal the stored request's own values",
           "the request's user message reads back as exactly the recorded event and source text",
           "the recorded publication times agree, and the capture ID matches the capture time and request hash",
           "the record states Nothing sent · Not frozen")
RECORDED_ONLY = ("story ID", "prompt version", "code identity", "source file name", "the operator's publication time "
                 "itself and the capture time itself (see the notes in times)")
INTEGRITY_NOTE = ("These checks compare the record with itself. They catch accidental or partial changes, not a "
                  "consistent rewrite of the whole record, and they do not establish who wrote it, when, or where "
                  "the source came from.")


class IntakeRefused(ValueError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def check_model(model: str) -> str:
    if not isinstance(model, str) or not MODEL_ID.fullmatch(model):
        raise IntakeRefused("The model ID must be explicit: lowercase letters, digits, '.' and '-', at most 64 "
                            "characters (for example claude-sonnet-5-5)")
    return model


def check_framing(headline: str, story_id: str, source_url: str, source_text: str) -> None:
    """Refuse inputs that would blur where the event metadata ends and the source text begins."""
    for name, value in (("headline", headline), ("story ID", story_id)):
        if any(unicodedata.category(char) in ("Cc", "Zl", "Zp") for char in value):
            raise IntakeRefused(f"The {name} contains a line break or control character; it must be one plain line")
    for name, value in (("headline", headline), ("story ID", story_id), ("source URL", source_url),
                        ("source text", source_text)):
        if FRAMING_TAG.search(value):
            raise IntakeRefused(f"The {name} contains a <source_text> tag, which would make the request's framing "
                                "ambiguous; nothing was captured")


def user_message(request: object) -> object:
    """The single user message's text, or None when the request does not have exactly that shape."""
    messages = request.get("messages") if isinstance(request, dict) else None
    if not isinstance(messages, list) or len(messages) != 1 or not isinstance(messages[0], dict) \
            or messages[0].get("role") != "user":
        return None
    return messages[0].get("content")


def framed_inputs(content: object) -> dict | None:
    """The event and source text read back out of a user message framed as captures frame it, or None.

    Self-contained, so a stored record is read the same way whatever other modules change later."""
    if not isinstance(content, str) or content.count(OPEN) != 1 or content.count(CLOSE) != 1 \
            or not content.endswith(f"\n{CLOSE}"):
        return None
    head, separator, rest = content.partition(f"\n\n{OPEN}\n")
    lines = head.rpartition("\n\n")[2].split("\n")
    if not separator or len(lines) != len(FIELD_PREFIXES) \
            or not all(line.startswith(prefix) for line, prefix in zip(lines, FIELD_PREFIXES)):
        return None
    values = [line[len(prefix):] for line, prefix in zip(lines, FIELD_PREFIXES)]
    return {**dict(zip(EVENT_FIELDS, values)), "text": rest[:-len(f"\n{CLOSE}")]}


def check_read_back(request: dict, event: dict, source_text: str, outcome: str) -> None:
    """The user message must read back as exactly what was supplied, through this module's own reader and
    through the draft-review reader, so a capture is unambiguous to both."""
    content = user_message(request)
    try:
        reviewed = extract_source(Path("intake"), content)
    except ProvenanceError:
        reviewed = None
    expected = {**{key: event[key] for key in EVENT_FIELDS}, "text": source_text}
    if framed_inputs(content) != expected or reviewed != expected:
        raise IntakeRefused("The request's user message does not read back as the event and source text, so its "
                            f"framing is ambiguous; {outcome}")


def read_source(path: Path) -> tuple[bytes, str]:
    if not path.is_file():
        raise IntakeRefused(f"The source-text file {path.name} does not exist or is not a file")
    data = path.read_bytes()
    try:
        return data, data.decode("utf-8")  # Strict: invalid UTF-8 is refused, never replaced.
    except UnicodeDecodeError:
        raise IntakeRefused(f"The source-text file {path.name} is not valid UTF-8; nothing was captured") from None


def code_identity() -> dict:
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}


def plan_bytes(headline: str, source_url: str, published_at: str, story_id: str, source_bytes: bytes,
               supplied_name: str, model: str, clock: Callable[[], datetime] = now,
               prompt_version: str = PROMPT_VERSION) -> dict:
    """Validate supplied UTF-8 bytes and build a complete record in memory under one drafting contract (the default,
    draft-prompt-5, unless the caller names another). Nothing is written here."""
    check_model(model)
    try:
        offered = contract_observables(prompt_version)
    except DraftRefused as exc:
        raise IntakeRefused(str(exc)) from None
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise IntakeRefused(f"The source-text file {supplied_name} is not valid UTF-8; nothing was captured") from None
    try:
        event, story = operator_event({"headline": headline, "source_url": source_url, "published_at": published_at,
                                       "story_id": story_id}, clock)
    except DraftRefused as exc:
        raise IntakeRefused(str(exc)) from None
    check_framing(event["headline"], story, event["source_url"], source_text)
    try:
        request = build_request(event, source_text, model, offered)
    except DraftRefused as exc:
        raise IntakeRefused(str(exc)) from None
    check_read_back(request, event, source_text, "nothing was captured")
    request_bytes = canonical(request).encode("utf-8")
    captured_at = utc(clock())
    request_hash = hashlib.sha256(request_bytes).hexdigest()
    capture_id = f"{captured_at:%Y%m%dT%H%M%S%fZ}-{request_hash[:12]}"
    manifest = {
        "intake_version": INTAKE_VERSION,
        "capture_id": capture_id,
        "status": STATUS,
        "sent": False,
        "frozen": False,
        "event": event,
        "story_id": story,
        "times": {"published_at": event["published_at"], "published_at_as_supplied": published_at,
                  "published_at_note": PUBLISHED_NOTE,
                  "captured_at": captured_at.isoformat(), "captured_at_note": CAPTURED_NOTE},
        "source": {"file": SOURCE, "supplied_name": supplied_name, "bytes": len(source_bytes),
                   "sha256": hashlib.sha256(source_bytes).hexdigest(), "encoding": "utf-8",
                   "characters": len(source_text)},
        "request": {"file": REQUEST, "bytes": len(request_bytes), "sha256": request_hash,
                    "prompt_hash_note": "SHA-256 of the exact canonical request body, as the adapter defines it",
                    "prompt_version": prompt_version, "model": request["model"],
                    "effort": request["output_config"]["effort"], "max_tokens": request["max_tokens"],
                    "endpoint_not_contacted": MESSAGES_URL},
        "code": {"sha256": code_identity()},
    }
    if request_hash != digest(request):
        raise IntakeRefused("The request bytes and the adapter's prompt hash disagree; nothing was captured")
    return {"manifest": manifest, "files": {SOURCE: source_bytes, REQUEST: request_bytes,
                                            MANIFEST: (json.dumps(manifest, indent=2, ensure_ascii=True) + "\n")
                                            .encode("ascii")}}


def plan(headline: str, source_url: str, published_at: str, story_id: str, source_path: Path, model: str,
         clock: Callable[[], datetime] = now) -> dict:
    """Validate a source file and build the record's bytes in memory. Nothing is written here."""
    source_bytes, _ = read_source(source_path)
    return plan_bytes(headline, source_url, published_at, story_id, source_bytes, source_path.name, model, clock)


def writable(function, path, _excinfo) -> None:
    """rmtree helper: a read-only staged file is made writable once, then removal is retried."""
    os.chmod(path, stat.S_IWRITE)
    function(path)


def save(root: Path, capture_id: str, files: dict[str, bytes]) -> Path:
    """Write a complete record under a staging name, then rename it into place. Never overwrites."""
    root.mkdir(parents=True, exist_ok=True)
    final = root / capture_id
    if final.exists():
        raise IntakeRefused(f"Capture {capture_id} already exists; captures are never overwritten")
    staging = Path(tempfile.mkdtemp(prefix=f".staging-{capture_id}-", dir=root))
    try:
        for name, data in files.items():
            with open(staging / name, "xb") as handle:
                handle.write(data)
            os.chmod(staging / name, stat.S_IREAD)
        if final.exists():
            raise IntakeRefused(f"Capture {capture_id} already exists; captures are never overwritten")
        os.rename(staging, final)  # Refused when the target exists (Windows) or is non-empty (POSIX).
    except BaseException:
        shutil.rmtree(staging, onexc=writable)
        raise
    return final


def capture(headline: str, source_url: str, published_at: str, story_id: str, source_path: Path, model: str,
            root: Path = INTAKE_DIR, clock: Callable[[], datetime] = now) -> dict:
    planned = plan(headline, source_url, published_at, story_id, source_path, model, clock)
    manifest = planned["manifest"]
    save(root, manifest["capture_id"], planned["files"])
    return {"status": STATUS, "capture_id": manifest["capture_id"], "event": manifest["event"],
            "story_id": manifest["story_id"], "times": manifest["times"], "source": manifest["source"],
            "request": manifest["request"],
            "next": f"python -m second_order.event_intake preview {manifest['capture_id']}"}


def capture_text(headline: str, source_url: str, published_at: str, story_id: str, source_text: str, model: str,
                 root: Path = INTAKE_DIR, clock: Callable[[], datetime] = now,
                 prompt_version: str = PROMPT_VERSION) -> dict:
    """Capture text supplied by the local UI without routing it through a temporary operator file."""
    if not isinstance(source_text, str):
        raise IntakeRefused("The source text must be a string; nothing was captured")
    planned = plan_bytes(headline, source_url, published_at, story_id, source_text.encode("utf-8"),
                         "tracker-input.txt", model, clock, prompt_version)
    manifest = planned["manifest"]
    save(root, manifest["capture_id"], planned["files"])
    return {"status": STATUS, "capture_id": manifest["capture_id"], "event": manifest["event"],
            "story_id": manifest["story_id"], "times": manifest["times"], "source": manifest["source"],
            "request": manifest["request"]}


def load(root: Path, capture_id: str) -> tuple[bytes, bytes, bytes]:
    """The record's three files, exactly as stored. Nothing is parsed or trusted yet."""
    if not CAPTURE_ID.fullmatch(capture_id or ""):
        raise IntakeRefused("A capture ID looks like 20261004T153000123456Z-0123456789ab")
    folder = root / capture_id
    paths = {name: folder / name for name in (MANIFEST, SOURCE, REQUEST)}
    if not all(path.is_file() for path in paths.values()):
        raise IntakeRefused(f"Capture {capture_id} does not exist or is incomplete")
    return paths[MANIFEST].read_bytes(), paths[SOURCE].read_bytes(), paths[REQUEST].read_bytes()


def aware(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None
    return utc(parsed) if parsed is not None and parsed.utcoffset() is not None else None


def field(record: object, path: str, kind: type, name: str):
    """One required value by dotted path, with its exact type (a bool is not an int); strings are non-empty."""
    value = record
    for key in path.split("."):
        if not isinstance(value, dict) or key not in value:
            raise ValueError(f"{name} does not record {path}")
        value = value[key]
    if type(value) is not kind:
        raise ValueError(f"{name} records {path} as {type(value).__name__}, not {kind.__name__}")
    if kind is str and not value:
        raise ValueError(f"{name} records {path} as an empty string")
    return value


def verified(root: Path, capture_id: str) -> dict:
    """The stored record's validated values, after checking every manifest field its own bytes can confirm.

    Every field that verification, preview or list reads must be present with its exact type, or the capture is
    refused by name. Independent of today's request builder, limits and prompt version: a recorded prompt
    version is required, never compared with today's. Nothing is repaired, and nothing is written."""
    manifest_bytes, source_bytes, request_bytes = load(root, capture_id)

    def refuse(problem: str) -> IntakeRefused:
        return IntakeRefused(f"Capture {capture_id}: {problem}; it is not shown, and nothing was changed")

    try:
        manifest, request = strict_json(manifest_bytes), strict_json(request_bytes)
    except DraftRefused:
        raise refuse("capture.json or request.json is not strict JSON") from None
    try:
        recorded = {path: field(manifest, path, kind, "capture.json") for path, kind in MANIFEST_FIELDS}
        stored = {path: field(request, path, kind, "request.json") for path, kind in REQUEST_FIELDS}
    except ValueError as exc:
        raise refuse(str(exc)) from None
    event = manifest["event"]
    source_hash, request_hash = recorded["source.sha256"], recorded["request.sha256"]
    published_at, captured_at = recorded["times.published_at"], recorded["times.captured_at"]
    as_supplied = recorded["times.published_at_as_supplied"]

    if hashlib.sha256(source_bytes).hexdigest() != source_hash:
        raise refuse("source.txt no longer matches its recorded SHA-256")
    if hashlib.sha256(request_bytes).hexdigest() != request_hash:
        raise refuse("request.json no longer matches its recorded SHA-256")
    if recorded["source.bytes"] != len(source_bytes):
        raise refuse(f"capture.json records {recorded['source.bytes']} source bytes, but source.txt has "
                     f"{len(source_bytes)}")
    try:
        source_text = source_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("source.txt is not valid UTF-8") from None
    if recorded["source.characters"] != len(source_text):
        raise refuse(f"capture.json records {recorded['source.characters']} source characters, but source.txt has "
                     f"{len(source_text)}")
    if recorded["request.bytes"] != len(request_bytes):
        raise refuse(f"capture.json records {recorded['request.bytes']} request bytes, but request.json has "
                     f"{len(request_bytes)}")
    if canonical(request).encode("utf-8") != request_bytes:
        raise refuse("request.json is not in the canonical form a capture writes")
    for label, request_path in (("model", "model"), ("effort", "output_config.effort"), ("max_tokens", "max_tokens")):
        if recorded[f"request.{label}"] != stored[request_path]:
            raise refuse(f"capture.json labels the {label} {recorded[f'request.{label}']!r}, but the stored request "
                         f"says {stored[request_path]!r}")
    expected = {**{key: event[key] for key in EVENT_FIELDS}, "text": source_text} \
        if set(event) == set(EVENT_FIELDS) else None
    if expected is None or framed_inputs(user_message(request)) != expected:
        raise refuse("the request's user message does not read back as the event and source text recorded in "
                     "capture.json, so its framing is ambiguous")
    normalized = aware(published_at)
    if published_at != event["published_at"] or normalized is None:
        raise refuse("the recorded publication times disagree")
    supplied = aware(as_supplied)
    if supplied is not None and supplied != normalized:
        raise refuse(f"the publication time as supplied ({as_supplied!r}) is not the same instant as the recorded "
                     f"publication time ({published_at})")
    captured = aware(captured_at)
    if captured is None or recorded["capture_id"] != capture_id or \
            capture_id != f"{captured:%Y%m%dT%H%M%S%fZ}-{request_hash[:12]}":
        raise refuse("the capture ID does not match the recorded capture time and request hash")
    if (recorded["status"], recorded["sent"], recorded["frozen"]) != (STATUS, False, False):
        raise refuse(f"capture.json does not record the status {STATUS}, not sent and not frozen")
    return {
        "event": {key: event[key] for key in EVENT_FIELDS},
        "times": {key: recorded[f"times.{key}"] for key in TIME_FIELDS},
        "source": {"sha256": source_hash, "bytes": recorded["source.bytes"]},
        "request": {"sha256": request_hash, "bytes": recorded["request.bytes"],
                    "prompt_version": recorded["request.prompt_version"]},
        "body": request, "source_text": source_text, "request_bytes": request_bytes,
    }


def current_code(event: dict, source_text: str, model: str, request_bytes: bytes,
                 prompt_version: str | None = None) -> dict:
    """Optional diagnostic, run only after verification: would today's builder, under the record's own drafting
    contract when that contract is known, produce the same bytes?"""
    try:
        offered = contract_observables(prompt_version) if prompt_version in CONTRACTS else None
        rebuilt = canonical(build_request(event, source_text, model, offered)).encode("utf-8")
    except Exception as exc:  # Today's rules may refuse old inputs; that never hides the verified record.
        return {"comparison": "unavailable",
                "detail": f"today's request builder refuses the recorded inputs ({type(exc).__name__}: {exc}); "
                          "the verified original request is shown below"}
    if rebuilt == request_bytes:
        return {"comparison": "identical", "detail": "today's request builder produces exactly these bytes"}
    return {"comparison": "different",
            "detail": f"today's request builder (prompt version {PROMPT_VERSION}) produces different bytes; the "
                      "verified original request is shown below"}


def preview(capture_id: str, root: Path = INTAKE_DIR) -> dict:
    """The verified stored request, labelled only from validated values. Nothing is sent or written."""
    record = verified(root, capture_id)
    request = record["body"]
    return {
        "status": STATUS,
        "capture_id": capture_id,
        "times": record["times"],
        "model": request["model"],
        "effort": request["output_config"]["effort"],
        "max_tokens": request["max_tokens"],
        "prompt_version": record["request"]["prompt_version"],
        "source_sha256": record["source"]["sha256"],
        "source_bytes": record["source"]["bytes"],
        "request_sha256": record["request"]["sha256"],
        "request_bytes": record["request"]["bytes"],
        "integrity": {"checked": list(CHECKED), "recorded_only": list(RECORDED_ONLY), "note": INTEGRITY_NOTE},
        "current_code": current_code(record["event"], record["source_text"], request["model"],
                                     record["request_bytes"], record["request"]["prompt_version"]),
        "request": request,
    }


def listing(root: Path = INTAKE_DIR) -> list[dict]:
    """Every capture, verified as preview verifies it; labels come only from validated values."""
    rows = []
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        if not folder.is_dir() or folder.name.startswith("."):
            continue  # Staging directories are never records.
        try:
            record = verified(root, folder.name)
        except (IntakeRefused, OSError) as exc:
            rows.append({"capture_id": folder.name, "state": "refused", "problem": str(exc)})
            continue
        rows.append({"capture_id": folder.name, "state": f"verified · {STATUS}",
                     "captured_at": record["times"]["captured_at"], "published_at": record["times"]["published_at"],
                     "headline": record["event"]["headline"], "model": record["body"]["model"],
                     "prompt_version": record["request"]["prompt_version"],
                     "request_sha256": record["request"]["sha256"]})
    return rows


def main(argv: list[str] | None = None, root: Path | None = None, clock: Callable[[], datetime] = now) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m second_order.event_intake",
        description=f"Offline event intake and request preview. {STATUS}: this tool never sends a request, "
                    "reads credentials, freezes a hypothesis or opens a database.")
    parser.add_argument("--root", type=Path, help="Capture directory (default: data/intake, git-ignored)")
    actions = parser.add_subparsers(dest="action", required=True)
    capturing = actions.add_parser("capture", help="Validate and capture an event and its source text")
    capturing.add_argument("--headline", required=True)
    capturing.add_argument("--source-url", required=True)
    capturing.add_argument("--published-at", required=True, help="Timezone-aware ISO time, as published")
    capturing.add_argument("--story-id", required=True)
    capturing.add_argument("--source-file", required=True, type=Path, help="One UTF-8 source-text file")
    capturing.add_argument("--model", required=True, help="Explicit model ID the request will name")
    actions.add_parser("preview", help="Verify a capture and print its exact request").add_argument("capture_id")
    actions.add_parser("list", help="List captures")
    args = parser.parse_args(argv)
    folder = args.root or root or INTAKE_DIR
    try:
        if args.action == "capture":
            result = capture(args.headline, args.source_url, args.published_at, args.story_id, args.source_file,
                             args.model, folder, clock)
        elif args.action == "preview":
            result = preview(args.capture_id, folder)
        else:
            result = {"status": STATUS, "captures": listing(folder)}
    except (ValueError, OSError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    # As in the main CLI: Unicode on a console, ASCII JSON when piped, which no Windows code page can corrupt.
    print(json.dumps(result, indent=2, ensure_ascii=not sys.stdout.isatty()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
