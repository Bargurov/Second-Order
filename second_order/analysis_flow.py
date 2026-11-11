"""One local, review-first path from an operator event to one draft attempt.

The intake capture is the authority for the request. Preview verifies and displays its exact stored bytes;
dispatch verifies them again, checks the operator-confirmed SHA-256, and copies those bytes verbatim into one
attempt. It never calls ``build_request``. This module has no HTTP client, credential lookup, freeze,
evaluation or database dependency: the one paid path, which sends the same saved bytes once, lives in
paid_drafts and reuses the approval, reservation and publication steps here.

A capture has at most one attempt, mock or paid. The local mock is the default and costs $0: it exercises a
structurally valid draft or a model decline from a deterministic fixture, recorded as synthetic. A second call
for the same capture is refused: there is no retry or fallback.

Every attempt file is written whole under a unique temporary name and linked into place, so it is complete or
absent. The manifest is written last; an attempt without one was interrupted and stays as recorded, still
blocking a second attempt. A recorded attempt is published to the Tracker's own draft folder (see
draft_catalog). If publishing fails, the recorded request and response are published later by an explicit
action, without sending, generating or rebuilding anything. ``attempt_state`` reports which of these holds and
never writes.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Callable
import uuid

from . import draft_catalog
from .draft_views import DRAFTS_DIR, ProvenanceError, build_view
from .event_intake import CAPTURE_ID, INTAKE_DIR, IntakeRefused, plan_bytes, preview, save, verified
from .model_draft import H15_PROMPT_VERSION, TOOL_NAME, DraftRefused, envelope, exposes, strict_json
from .schema import utc
from .store import canonical, digest

FLOW_VERSION = "event-draft-flow-0.1"
MODEL = "claude-sonnet-5-5"
MOCK_RUN = "tracker-mock-1"
MOCK_OUTCOMES = ("draft", "no_draft")
TRACKER_CONTRACT = H15_PROMPT_VERSION  # New Tracker requests offer the Board's H.15 IDs; saved requests keep theirs.
# The maturity pairs a saved request may offer, by contract: the FRED IDs (draft-prompt-5) or the H.15 IDs (6).
MOCK_PAIRS = ({"two": "yield:ust2y_cmt", "ten": "yield:ust10y_cmt"},
              {"two": "yield:ust2y_cmt_h15", "ten": "yield:ust10y_cmt_h15"})
ROOT = Path(__file__).resolve().parent.parent
ATTEMPTS_DIR = ROOT / "data" / "tracker-attempts"  # Mock and paid attempts share it: one per capture, ever.
FORM_FIELDS = ("headline", "source_url", "published_at", "source_text")
CONFIRM_FIELDS = ("request_sha256", "mock_outcome")
PUBLISH_FIELDS = ("request_sha256",)
MAX_FORM_BYTES = 120_000
SURROGATE = re.compile("[\ud800-\udfff]")  # JSON can escape one (\ud800); it is not a character and has no UTF-8.
EXPLICIT_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-])(\d{2}):(\d{2})")
OFFSET_MINUTES = (-12 * 60, 14 * 60)
PRICE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICES = {"model": MODEL, "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0,
          "tool_prompt_tokens": 286, "read_on": "2026-10-05", "source": PRICE_SOURCE}


class FlowRefused(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def now() -> datetime:
    return datetime.now(timezone.utc)


def strict_object(body: bytes, fields: tuple[str, ...], label: str, limit: int = MAX_FORM_BYTES) -> dict:
    if len(body) > limit:
        raise FlowRefused(413, f"The {label} is limited to {limit} bytes")
    try:
        payload = strict_json(body)
    except Exception:
        raise FlowRefused(422, f"The {label} must be strict JSON") from None
    if not isinstance(payload, dict) or set(payload) != set(fields):
        raise FlowRefused(422, f"The {label} must contain exactly {', '.join(fields)}")
    return payload


def story_id(payload: dict) -> str:
    """A stable local identifier; it is recorded but is not part of the model request."""
    return f"tracker-{digest({key: payload[key] for key in FORM_FIELDS})[:20]}"


def cost_estimate(request_bytes: bytes, max_tokens: int, system: tuple[int, str] | None = None) -> dict:
    """A planning estimate for one paid request of these exact bytes. The local mock always costs $0. ``system``: the
    tokens allowed for the system prompt the provider adds, and how to say so, when it is not the tool-use one."""
    system_tokens, system_words = system or (PRICES["tool_prompt_tokens"],
                                             f"{PRICES['tool_prompt_tokens']} tool-use system tokens")
    input_tokens = len(request_bytes) // 2 + system_tokens + 1000
    usd = (input_tokens * PRICES["input_usd_per_mtok"]
           + max_tokens * PRICES["output_usd_per_mtok"]) / 1_000_000
    return {
        "mock_run_usd": 0,
        "estimated_real_run_if_output_reaches_max_usd": round(usd, 4),
        "input_tokens_assumed": input_tokens,
        "output_tokens_at_max": max_tokens,
        "prices": PRICES,
        "assumptions": [
            f"Prices for {MODEL}: ${PRICES['input_usd_per_mtok']:g} per million input tokens and "
            f"${PRICES['output_usd_per_mtok']:g} per million output tokens, read on {PRICES['read_on']}.",
            "Input tokens: the saved request's size at 2 bytes per token (deliberately high), plus "
            f"{system_words} and 1,000 for the unpublished thinking prompt.",
            f"Output tokens: the request's max_tokens of {max_tokens:,}, which caps thinking and the reply together.",
            "Standard global routing: the request sets no inference_geo (US-only inference would cost 1.1 times).",
        ],
        "caveat": ("A planning estimate, not a guaranteed billing ceiling: max_tokens caps output, but the input "
                   "count is estimated and prices can change. The Console's usage is authoritative. The local "
                   "mock contacts no provider and costs $0."),
    }


def preview_capture(capture_id: str, intake_dir: Path = INTAKE_DIR) -> dict:
    """The verified saved request and its cost decision. ``provider_called`` is about this action only, as in every
    intake response: previewing never contacts a provider. Which sending modes the server offers is added by the
    API as ``modes``; an offered mode is not an approval."""
    shown = preview(capture_id, intake_dir)
    body = canonical(shown["request"]).encode("utf-8")
    return {
        "flow_version": FLOW_VERSION,
        **shown,
        "provider_called": False,
        "cost_estimate": cost_estimate(body, shown["max_tokens"]),
        "confirmation": ("Previewing sends nothing and approves nothing. A mock or paid send needs its own explicit "
                         "approval naming this request SHA-256, and a capture gets at most one attempt."),
    }


def explicit_publication_time(value: str) -> str:
    """The Tracker's publication time: a calendar date and time with an explicit UTC offset, exactly
    YYYY-MM-DDTHH:MM:SS±HH:MM, as the operator chose it. Nothing is inferred, converted or repaired here; the
    existing event contract then normalizes it to UTC for the request. Refused: any other form (a missing offset,
    Z, a space, fractions or a bare number), an impossible date or time, an offset outside -12:00..+14:00 or off
    the 15-minute grid, and -00:00, which by convention means the offset is unknown."""
    match = EXPLICIT_TIME.fullmatch(value)
    if not match:
        raise FlowRefused(422, "The publication time must be a date and time with an explicit UTC offset, exactly "
                               "YYYY-MM-DDTHH:MM:SS±HH:MM (for example 2026-10-04T14:00:00-04:00)")
    sign, hours, minutes = match.group(1), int(match.group(2)), int(match.group(3))
    offset = (hours * 60 + minutes) * (-1 if sign == "-" else 1)
    unknown = sign == "-" and offset == 0
    if minutes >= 60 or minutes % 15 or not OFFSET_MINUTES[0] <= offset <= OFFSET_MINUTES[1] or unknown:
        raise FlowRefused(422, f"The UTC offset {value[19:]} is not accepted: choose -12:00 to +14:00 in 15-minute "
                               "steps, and +00:00 for UTC (-00:00 means the offset is unknown)")
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise FlowRefused(422, f"{value[:19]} is not a real calendar date and time of day") from None
    return value


def capture_from_form(body: bytes, intake_dir: Path = INTAKE_DIR,
                      clock: Callable[[], datetime] = now) -> dict:
    return capture_from_payload(strict_object(body, FORM_FIELDS, "event"), intake_dir, clock)


def capture_from_payload(payload: dict, intake_dir: Path = INTAKE_DIR,
                         clock: Callable[[], datetime] = now) -> dict:
    """A capture of a form already read and parsed with exactly FORM_FIELDS; its caller bounds the body."""
    return save_capture(plan_capture(payload, intake_dir, clock), intake_dir)


def plan_capture(payload: dict, intake_dir: Path = INTAKE_DIR, clock: Callable[[], datetime] = now) -> dict:
    """The capture of a form already read and parsed with exactly FORM_FIELDS, checked by every rule of the capture
    and built in memory (event_intake.plan_bytes), so a caller can refuse an invalid form before it counts or writes
    anything. A capture of the same request at the same instant is refused here too, as saving it would be. Nothing
    is written."""
    if any(not isinstance(payload[field], str) for field in FORM_FIELDS):
        raise FlowRefused(422, "Every event field must be text")
    if any(SURROGATE.search(payload[field]) for field in FORM_FIELDS):
        raise FlowRefused(422, "An event field holds an unpaired surrogate escape, which is not a character")
    explicit_publication_time(payload["published_at"])  # Kept exactly as supplied in the capture's metadata.
    try:  # The arguments event_intake.capture_text gives plan_bytes for text supplied by the UI.
        planned = plan_bytes(payload["headline"], payload["source_url"], payload["published_at"], story_id(payload),
                             payload["source_text"].encode("utf-8"), "tracker-input.txt", MODEL, clock,
                             TRACKER_CONTRACT)
    except IntakeRefused as exc:
        raise FlowRefused(422, str(exc)) from None
    capture_id = planned["manifest"]["capture_id"]
    if (intake_dir / capture_id).exists():
        raise FlowRefused(422, f"Capture {capture_id} already exists; captures are never overwritten")
    return planned


def save_capture(planned: dict, intake_dir: Path = INTAKE_DIR) -> dict:
    """Write a planned capture whole (event_intake.save never overwrites one) and preview it."""
    capture_id = planned["manifest"]["capture_id"]
    try:
        save(intake_dir, capture_id, planned["files"])
        return preview_capture(capture_id, intake_dir)
    except IntakeRefused as exc:
        raise FlowRefused(422, str(exc)) from None


def _offered(request: dict) -> tuple[str, ...]:
    try:
        (tool,) = request["tools"]
        values = tool["input_schema"]["properties"]["legs"]["items"]["properties"]["observable_id"]["enum"]
    except (KeyError, TypeError, ValueError):
        raise FlowRefused(409, "The stored request no longer exposes one reviewable draft tool") from None
    if tool.get("name") != TOOL_NAME or not isinstance(values, list) or not values:
        raise FlowRefused(409, "The stored request no longer exposes one reviewable draft tool")
    offered = tuple(values)
    if not any(set(pair.values()) <= set(offered) for pair in MOCK_PAIRS):
        raise FlowRefused(409, "The stored request does not offer the observables required by this mock fixture")
    return offered


def _mock_pair(request: dict) -> dict:
    """The maturity pair the saved request offers (its own contract's IDs); the mock never uses another."""
    offered = set(_offered(request))
    return next(pair for pair in MOCK_PAIRS if set(pair.values()) <= offered)


def _mock_output(headline: str, pair: dict | None = None) -> dict:
    pair = pair or MOCK_PAIRS[0]
    return {
        "summary": (f"Mock workflow draft for the recorded event ‘{headline}’. It proposes a policy-expectations "
                    "channel only to exercise human review; it is not a research finding."),
        "nodes": [
            {"id": "event", "label": "Recorded event", "kind": "event"},
            {"id": "policy", "label": "Proposed policy-expectations channel", "kind": "channel"},
            {"id": "two", "label": "2-year Treasury yield", "kind": "observable"},
            {"id": "ten", "label": "10-year Treasury yield", "kind": "observable"},
        ],
        "edges": [{"source": "event", "target": "policy"}, {"source": "policy", "target": "two"},
                  {"source": "policy", "target": "ten"}],
        "legs": [
            {"id": "primary", "node_id": "two", "primary": True, "channel": "policy_path",
             "observable_id": pair["two"], "link": "direct", "expected": "down", "horizon": 5,
             "falsifier": "The 2-year yield rises unusually over the scored window.",
             "rationale": "Mock rationale: the short maturity is used only to exercise the review form.",
             "headline_reports_move": False},
            {"id": "secondary", "node_id": "ten", "primary": False, "channel": "policy_path",
             "observable_id": pair["ten"], "link": "proxy", "expected": "down", "horizon": 5,
             "falsifier": "The 10-year yield rises unusually over the scored window.",
             "rationale": "Mock rationale: the long maturity is used only to exercise the review form.",
             "headline_reports_move": False},
        ],
    }


def mock_response(request: dict, event: dict, outcome: str, request_hash: str) -> bytes:
    """A Messages-API-shaped local fixture. No transport exists in this module."""
    identity = request_hash[:20]
    if outcome == "draft":
        content = [{"type": "thinking", "thinking": "", "signature": f"sig-mock-{identity}"},
                   {"type": "tool_use", "id": f"toolu_mock_{identity}", "name": TOOL_NAME,
                    "input": _mock_output(event["headline"], _mock_pair(request))}]
        stop_reason = "tool_use"
    else:
        content = [{"type": "text", "text": ("Mock refusal for workflow testing: this local response declines "
                                                "to create a hypothesis draft. No provider was contacted.")}]
        stop_reason = "end_turn"
    response = {"id": f"msg_mock_{identity}", "type": "message", "role": "assistant",
                "model": request["model"], "content": content, "stop_reason": stop_reason,
                "stop_sequence": None, "usage": {"input_tokens": 0, "output_tokens": 0}}
    return canonical(response).encode("utf-8")


def _json_bytes(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def keep_record(path: Path, data: bytes, secret: str | None = None) -> None:
    """Write a whole file under a unique temporary name, then link it into place: complete or absent, never
    replaced (an existing name raises FileExistsError). Nothing carrying ``secret`` is ever written."""
    if secret and exposes(data, secret):
        raise DraftRefused(f"{path.name} would contain the credential; it was not written")
    temporary = path.with_name(f".tmp-{uuid.uuid4().hex}")
    try:
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _recorded_mode(attempt: Path, names: list[str]) -> dict:
    """Mock or paid, and whether a paid request left this server, from the attempt's own records."""
    def read(name: str) -> dict:
        try:
            value = json.loads((attempt / name).read_text(encoding="utf-8")) if name in names else {}
        except ValueError:
            return {}
        return value if isinstance(value, dict) else {}
    reservation, sending = read("reservation.json"), read("attempt.json")
    mode = reservation.get("mode") if reservation.get("mode") in ("mock", "paid") else None
    return {"mode": mode, "sent": bool(sending), "sent_at": sending.get("sent_at")}


def _attempt_dir(capture_id: str, intake_dir: Path, attempts_dir: Path) -> Path:
    if not CAPTURE_ID.fullmatch(capture_id or "") or not (intake_dir / capture_id).is_dir():
        raise FlowRefused(404, "Unknown capture ID")
    return attempts_dir / capture_id


def _recorded_view(capture_id: str, intake_dir: Path, attempt: Path) -> dict:
    """The review view of a completed attempt, built only from its saved files and bound to the capture's bytes."""
    try:
        record = verified(intake_dir, capture_id)
    except IntakeRefused as exc:
        raise FlowRefused(409, str(exc)) from None
    if (attempt / "request.json").read_bytes() != record["request_bytes"]:
        raise FlowRefused(409, "The attempt's request.json is not the approved saved request; nothing was published")
    try:
        return build_view(attempt)
    except ProvenanceError as exc:
        raise FlowRefused(409, f"The recorded attempt cannot be prepared for review: {exc}") from None


def _manifest(attempt: Path) -> dict:
    return json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))


def result(capture_id: str, view: dict, attempt: Path, recovered: bool, provider_called: bool) -> dict:
    """What an action established. ``provider_called`` says whether this action contacted the provider."""
    manifest = _manifest(attempt)
    paid = manifest["pilot"] != MOCK_RUN
    cost = manifest.get("estimated_cost")
    return {"flow_version": FLOW_VERSION, "status": "prepared_for_human_review", "capture_id": capture_id,
            "draft_id": view["id"], "outcome": view["outcome"], "recorded_outcome": manifest["outcome"],
            "mode": "paid" if paid else "mock", "recovered": recovered, "provider_called": provider_called,
            "cost_usd": cost.get("usd") if isinstance(cost, dict) else None, "attempts": 1, "retries": 0,
            "frozen": False, "evaluated": False}


def approved_capture(capture_id: str, request_sha256: str, intake_dir: Path) -> dict:
    """The verified capture an approval names. Refused before any reservation if the capture does not verify,
    the approved hash is not its saved request's, or the request is not this flow's model and tool."""
    try:
        record = verified(intake_dir, capture_id)
    except IntakeRefused as exc:
        raise FlowRefused(409, str(exc)) from None
    if request_sha256 != hashlib.sha256(record["request_bytes"]).hexdigest():
        raise FlowRefused(409, "The confirmed request SHA-256 does not match the saved request; nothing was run")
    if record["body"].get("model") != MODEL:
        raise FlowRefused(409, f"This flow is bound to {MODEL}; the saved request names another model")
    _offered(record["body"])
    return record


def reserve_attempt(attempts_dir: Path, capture_id: str) -> Path:
    """The reservation: the attempt folder, created exclusively. Code never releases it."""
    attempts_dir.mkdir(parents=True, exist_ok=True)
    attempt = attempts_dir / capture_id
    try:
        attempt.mkdir()
    except FileExistsError:
        raise FlowRefused(409, "This capture already has an attempt; it is never sent or mocked twice") from None
    return attempt


def publish_after_recording(capture_id: str, intake_dir: Path, attempt: Path, drafts_dir: Path,
                            published_dir: Path) -> dict:
    """Publish a just-recorded attempt; on failure, say it is recorded and can be published from its files."""
    try:
        return _publish(capture_id, intake_dir, attempt, drafts_dir, published_dir)
    except FlowRefused as exc:
        raise FlowRefused(exc.status, f"The response was recorded, but it was not published for review: {exc}") \
            from None
    except Exception as exc:
        raise FlowRefused(500, f"The response was recorded, but publishing it for review failed "
                               f"({type(exc).__name__}: {exc}). Publish the recorded response from the Tracker; "
                               "nothing will be sent or generated again.") from None


def _publish(capture_id: str, intake_dir: Path, attempt: Path, drafts_dir: Path, published_dir: Path) -> dict:
    view = _recorded_view(capture_id, intake_dir, attempt)
    try:
        draft_catalog.publish_view(view, published_dir, drafts_dir)
    except draft_catalog.CatalogRefused as exc:
        raise FlowRefused(exc.status, str(exc)) from None
    return view


def dispatch_mock(capture_id: str, body: bytes, intake_dir: Path = INTAKE_DIR,
                  attempts_dir: Path = ATTEMPTS_DIR, drafts_dir: Path = DRAFTS_DIR,
                  clock: Callable[[], datetime] = now, published_dir: Path | None = None) -> dict:
    """Record one local mock attempt from the approved saved request, then publish it for review.

    ``drafts_dir`` is the folder prepare-drafts owns; the view is published to the Tracker's folder beside it."""
    published_dir = published_dir or draft_catalog.tracker_dir(drafts_dir)
    confirmation = strict_object(body, CONFIRM_FIELDS, "confirmation")
    if not all(isinstance(confirmation[field], str) for field in CONFIRM_FIELDS):
        raise FlowRefused(422, "Every confirmation field must be text")
    if confirmation["mock_outcome"] not in MOCK_OUTCOMES:
        raise FlowRefused(422, f"mock_outcome must be one of {', '.join(MOCK_OUTCOMES)}")
    record = approved_capture(capture_id, confirmation["request_sha256"], intake_dir)
    request, request_bytes = record["body"], record["request_bytes"]
    request_hash = hashlib.sha256(request_bytes).hexdigest()
    attempt = reserve_attempt(attempts_dir, capture_id)

    try:
        reserved_at = utc(clock()).isoformat()
        identity = {"pilot": MOCK_RUN, "case": capture_id, "model": MODEL, "prompt_hash": request_hash}
        keep_record(attempt / "reservation.json", _json_bytes({**identity, "mode": "mock", "reserved_at": reserved_at,
                                                               "pid": os.getpid(), "code": {"mode": "local mock"}}))
        keep_record(attempt / "request.json", request_bytes)  # The approved stored bytes, copied. Never rebuilt.
        sent_at = utc(clock()).isoformat()
        keep_record(attempt / "attempt.json", _json_bytes({"state": "mocking", "mode": "mock", "sent_at": sent_at,
                                                          "attempts": 1, "retries": 0}))
        response = mock_response(request, record["event"], confirmation["mock_outcome"], request_hash)
        keep_record(attempt / "response.json", response)
        received_at = utc(clock()).isoformat()
        message = envelope(strict_json(response))
        response_record = {"sha256": hashlib.sha256(response).hexdigest(), "bytes": len(response),
                           "id": message["id"], "model": message["model"],
                           "stop_reason": message["stop_reason"], "stop_details": message.get("stop_details"),
                           "usage": message.get("usage")}
        recorded_outcome = "draft" if confirmation["mock_outcome"] == "draft" else "no draft"
        adapter_message = None if recorded_outcome == "draft" else \
            "No draft: the model ended without calling the draft tool"
        manifest = {
            **identity, "case_sha256": digest({"capture_id": capture_id}), "synthetic_case": True,
            "effort": request["output_config"]["effort"], "max_tokens": request["max_tokens"],
            "prompt_version": record["request"]["prompt_version"], "request_bytes": len(request_bytes),
            "endpoint": "local mock only; no endpoint contacted", "anthropic_version": None,
            "code": {"mode": "local mock", "flow_version": FLOW_VERSION}, "reserved_at": reserved_at,
            "sent_at": sent_at, "received_at": received_at, "elapsed_seconds": 0,
            # No provider was contacted, so there is no provider HTTP status or request ID to record.
            "http_status": None, "request_id": None, "response": response_record,
            "outcome": recorded_outcome,
            "outcome_note": "Synthetic response for end-to-end interface testing; no provider was contacted.",
            "adapter_message": adapter_message, "estimated_cost": {"usd": 0, "basis": "local mock"},
            "attempts": 1, "retries": 0, "fallbacks": None,
            "provenance": ("Generated locally from a deterministic mock fixture. request.json is byte-for-byte the "
                           "verified intake request approved by its SHA-256. No provider was contacted."),
        }
        keep_record(attempt / "manifest.json", _json_bytes(manifest))  # Written last: it marks completion.
    except Exception as exc:
        raise FlowRefused(500, f"The mock attempt was interrupted after it was reserved ({type(exc).__name__}). "
                               "What was written is kept as recorded, and this capture will not be attempted again; "
                               "capture the event again to start over.") from None

    view = publish_after_recording(capture_id, intake_dir, attempt, drafts_dir, published_dir)
    return result(capture_id, view, attempt, recovered=False, provider_called=False)


def publish_recorded(capture_id: str, body: bytes, intake_dir: Path = INTAKE_DIR,
                     attempts_dir: Path = ATTEMPTS_DIR, drafts_dir: Path = DRAFTS_DIR,
                     published_dir: Path | None = None) -> dict:
    """Publish a completed attempt for review from its saved request and response.

    The explicit recovery action: nothing is sent, generated or rebuilt, and the attempt's files are only read.
    Publishing an already published identical view succeeds without writing."""
    published_dir = published_dir or draft_catalog.tracker_dir(drafts_dir)
    confirmation = strict_object(body, PUBLISH_FIELDS, "publication")
    if not isinstance(confirmation["request_sha256"], str):
        raise FlowRefused(422, "request_sha256 must be text")
    attempt = _attempt_dir(capture_id, intake_dir, attempts_dir)
    if not (attempt / "manifest.json").is_file():
        raise FlowRefused(409, "No completed attempt is recorded for this capture; nothing was published")
    if hashlib.sha256((attempt / "request.json").read_bytes()).hexdigest() != confirmation["request_sha256"]:
        raise FlowRefused(409, "The confirmed request SHA-256 does not match the recorded attempt; nothing was "
                               "published")
    try:
        view = _publish(capture_id, intake_dir, attempt, drafts_dir, published_dir)
    except FlowRefused:
        raise
    except Exception as exc:
        raise FlowRefused(500, f"Publishing the recorded response failed ({type(exc).__name__}: {exc}); nothing "
                               "was sent or generated, and it can be published again") from None
    return result(capture_id, view, attempt, recovered=True, provider_called=False)


def attempt_state(capture_id: str, intake_dir: Path = INTAKE_DIR, attempts_dir: Path = ATTEMPTS_DIR,
                  drafts_dir: Path = DRAFTS_DIR, published_dir: Path | None = None) -> dict:
    """What has been recorded for one capture. Read only: nothing is written, repaired, sent or generated.

    - none: no attempt is recorded, so an explicit approval may still start one;
    - incomplete: an attempt was reserved but has no manifest; it is kept and blocks another attempt;
    - awaiting_publication: the attempt is complete and verifies, but its review view is not published;
    - ready: its review view is published; draft_id names it;
    - invalid: the recorded attempt does not verify; it is reported, never repaired."""
    published_dir = published_dir or draft_catalog.tracker_dir(drafts_dir)
    attempt = _attempt_dir(capture_id, intake_dir, attempts_dir)
    state = {"flow_version": FLOW_VERSION, "capture_id": capture_id, "provider_called": False, "mode": None,
             "sent": False}
    if not attempt.is_dir():
        return {**state, "state": "none", "files": [], "detail": "No attempt is recorded for this capture."}
    names = sorted(path.name for path in attempt.iterdir() if not path.name.startswith(".tmp-"))
    state |= _recorded_mode(attempt, names)
    if "manifest.json" not in names:
        if state["mode"] == "paid" and state["sent"]:
            detail = (f"A paid request was sent at {state['sent_at']} and no response is recorded. It may still be in "
                      "flight, or the server stopped before recording it; the provider may have received and billed "
                      "it. It is never sent again; reading this state sends nothing. Check the Console's usage for "
                      "that time.")
        elif state["mode"] == "paid":
            detail = ("A paid request was reserved but not sent. The reservation is kept and blocks another attempt "
                      "for this capture; capture the event again to start over.")
        else:
            detail = ("An attempt was reserved but did not finish. It is kept as recorded and blocks another attempt "
                      "for this capture; capture the event again to start over.")
        return {**state, "state": "incomplete", "files": names, "detail": detail}
    try:
        view = _recorded_view(capture_id, intake_dir, attempt)
    except FlowRefused as exc:
        return {**state, "state": "invalid", "files": names, "detail": str(exc)}
    base = {**state, "files": names, "draft_id": view["id"], "outcome": view["outcome"],
            "recorded_outcome": _manifest(attempt)["outcome"]}
    try:
        stored = draft_catalog.locate(drafts_dir, published_dir, view["id"])
    except draft_catalog.CatalogRefused as exc:
        if exc.status not in (404, 503):
            return {**base, "state": "invalid", "detail": str(exc)}
        return {**base, "state": "awaiting_publication",
                "detail": ("The response is recorded but not yet published for review. Publishing uses the "
                           "recorded request and response; nothing is sent or generated again.")}
    if stored != draft_catalog.view_bytes(view):
        return {**base, "state": "invalid", "detail": "A different prepared view uses this draft ID"}
    return {**base, "state": "ready", "detail": "The draft is published and ready for human review."}
