"""Synthetic saved draft attempts, laid out the way the pilot writes them. No real pilot record is read.

The request is built here by hand rather than by the current prompt builder, so captured review views do not
change when the drafting prompt does.
"""
import copy
import hashlib
import json
from pathlib import Path
from model_fixtures import THINKING, encoded, message, tool_call, valid_output
from second_order.model_draft import TOOL_NAME
from second_order.store import canonical

MODEL = "claude-sonnet-5-5"
SYSTEM = "SYNTHETIC SYSTEM PROMPT. It is never shown in a review view."
SOURCE = ("SYNTHETIC TEST TEXT. No real institution, release, quote or market data is described.\n\n"
          "The synthetic committee said further tightening is less likely after softer labor data.\n"
          "  An indented line, <b>markup-like text</b> & an ampersand stay plain text.")
DECLINE = "No hypothesis: the source does not say what the committee decided, so any direction would be invented."
WALL_CLOCK = {"reserved_at": "2026-09-30T12:00:00.000000+00:00", "sent_at": "2026-09-30T12:00:00.100000+00:00",
              "received_at": "2026-09-30T12:00:05.100000+00:00"}


def user_message(source: str = SOURCE, headline: str = "Synthetic committee signals a slower tightening pace") -> str:
    return (f"Synthetic instructions for the model.\n\nHeadline: {headline}\n"
            f"Source URL: https://example.com/synthetic-statement\nPublished at (UTC): 2026-09-15T18:00:00Z\n\n"
            f"<source_text>\n{source}\n</source_text>")


def request(content: str | None = None, model: str = MODEL) -> dict:
    observables = {"properties": {"legs": {"items": {"properties": {
        "observable_id": {"enum": ["yield:ust10y_cmt", "yield:ust2y_cmt"]}}}}}}
    return {"model": model, "max_tokens": 16000, "system": SYSTEM, "output_config": {"effort": "medium"},
            "tools": [{"name": TOOL_NAME, "strict": True, "input_schema": observables}],
            "tool_choice": {"type": "auto"},
            "messages": [{"role": "user", "content": user_message() if content is None else content}]}


def draft_response() -> bytes:
    """A draft with a thinking block before the call, which a review view must never carry."""
    return encoded(message(model=MODEL, content=[dict(THINKING, signature="sig-never-shown"), tool_call()]))


def decline_response() -> bytes:
    return encoded(message(model=MODEL, content=[dict(THINKING, signature="sig-never-shown"),
                                                {"type": "text", "text": DECLINE}], stop_reason="end_turn"))


def invalid_response() -> bytes:
    prose = {"type": "text", "text": "Here is my draft."}
    return encoded(message(model=MODEL, content=[prose, tool_call()]))


OUTCOMES = {  # Recorded pilot outcome, response bytes, HTTP status and the adapter's message.
    "draft": ("draft", draft_response, 200, None),
    "no-draft": ("no draft", decline_response, 200, "No draft: the model ended without calling the draft tool"),
    "invalid": ("refused", invalid_response, 200, "Unexpected text content block; only thinking blocks may "
                                                  "accompany the draft tool call, and no draft is read from prose"),
    "technical-failure": ("provider error", None, 529,
                          "The model provider returned HTTP 529 (overloaded_error); no draft was produced"),
}


def write_attempt(folder: Path, kind: str = "draft", case: str = "synthetic-case", body: dict | None = None,
                  response: bytes | None = None) -> Path:
    """One attempt directory with request, response, reservation, attempt and manifest records."""
    recorded_outcome, make_response, status, adapter_message = OUTCOMES[kind]
    request_bytes = canonical(request() if body is None else body).encode("utf-8")
    response_bytes = response if response is not None else (make_response() if make_response else None)
    prompt_hash = hashlib.sha256(request_bytes).hexdigest()
    folder.mkdir(parents=True)
    (folder / "request.json").write_bytes(request_bytes)
    if response_bytes is not None:
        (folder / "response.json").write_bytes(response_bytes)
    identity = {"pilot": "pilot-synthetic", "case": case, "model": MODEL, "prompt_hash": prompt_hash}
    (folder / "reservation.json").write_text(json.dumps({**identity, "reserved_at": WALL_CLOCK["reserved_at"],
                                                         "pid": 1, "code": {"git_head": None}}), encoding="utf-8")
    (folder / "attempt.json").write_text(json.dumps({"state": "sending", "sent_at": WALL_CLOCK["sent_at"]}),
                                         encoding="utf-8")
    response_record = None
    if response_bytes is not None:
        parsed = json.loads(response_bytes)
        response_record = {"sha256": hashlib.sha256(response_bytes).hexdigest(), "bytes": len(response_bytes),
                           "id": parsed["id"], "model": parsed["model"], "stop_reason": parsed["stop_reason"],
                           "stop_details": parsed.get("stop_details"), "usage": parsed["usage"]}
    manifest = {**identity, **WALL_CLOCK, "case_sha256": "0" * 64, "synthetic_case": True, "effort": "medium",
                "max_tokens": 16000, "prompt_version": "draft-prompt-synthetic", "request_bytes": len(request_bytes),
                "endpoint": "https://api.anthropic.com/v1/messages", "anthropic_version": "2023-06-01",
                "code": {"git_head": None}, "elapsed_seconds": 5.0, "http_status": status,
                "request_id": "req_011SyntheticReview01", "response": response_record, "outcome": recorded_outcome,
                "outcome_note": "synthetic", "adapter_message": adapter_message, "estimated_cost": None,
                "attempts": 1, "retries": 0, "fallbacks": None, "provenance": "synthetic"}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return folder


def rewrite_manifest(folder: Path, **changes) -> None:
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    (folder / "manifest.json").write_text(json.dumps({**manifest, **changes}, indent=2), encoding="utf-8")


def valid_draft() -> dict:
    return copy.deepcopy(valid_output())
