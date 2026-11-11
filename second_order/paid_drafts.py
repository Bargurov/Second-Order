"""One paid Claude Sonnet 5.5 request for a captured event, sent from the Tracker after an explicit approval.

Nothing here runs unless the server was started with ``serve --enable-paid-drafts`` (or a test injects a
sender): without a ``PaidSender`` every paid action is refused before anything is reserved. The local mock in
analysis_flow stays the default and costs $0.

Before a reservation is made, the approval must name the saved request's SHA-256, say ``approve_paid_request:
true`` and repeat the planning estimate the preview showed for those bytes; the API key must be present and
well formed; the capture must verify; and the request must not carry the key. The reservation (the attempt
folder, shared with the mock, so a capture gets one attempt in either mode) and the exact request bytes are
written before the provider is contacted, and the send is recorded as started before it begins.

Exactly the saved bytes are posted, once, through the pilot's client: no retries, no redirects, no proxies from
the environment, no fallback, repair or second model call. The key travels only in the x-api-key header; every
file written here is refused if it would carry it, and a response that echoes it is not kept. A timeout or a
lost connection after sending is recorded as an unknown outcome: the provider may have received and billed the
request. Reading the attempt state never sends anything, and a recorded response is published for review by
the same explicit recovery action as a mock response.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
from typing import Callable

import httpx

from . import draft_catalog
from .analysis_flow import (ATTEMPTS_DIR, FLOW_VERSION, MODEL, FlowRefused, _json_bytes, _offered, approved_capture,
                            cost_estimate, keep_record, now, publish_after_recording, reserve_attempt, result,
                            strict_object)
from .draft_pilot import KEY_VARIABLE, OUTCOME_NOTES, REQUEST_ID, live_client, response_summary, usage_cost
from .draft_review import NO_DRAFT
from .draft_views import DRAFTS_DIR
from .event_intake import INTAKE_DIR
from .model_draft import (API_VERSION, MESSAGES_URL, DraftRefused, error_diagnostics, exposes, parse_response,
                          send_bytes)
from .schema import utc
from .store import digest

PAID_RUN = "tracker-live-1"
APPROVAL_FIELDS = ("request_sha256", "approve_paid_request", "estimated_max_usd")
CODE_FILES = ("second_order/paid_drafts.py", "second_order/analysis_flow.py", "second_order/model_draft.py",
              "second_order/event_intake.py")
ROOT = Path(__file__).resolve().parent.parent
NOT_ENABLED = ("Paid sending is not enabled on this server; nothing was reserved or sent. It needs an explicit "
               "`python -m second_order serve --enable-paid-drafts` with the key in " + KEY_VARIABLE + ".")
UNKNOWN = "The outcome is unknown: the provider may have received and billed the request. It is never sent again."


@dataclass(frozen=True)
class PaidSender:
    """What a server needs to send paid requests: where the key is read at send time, and the HTTP client.

    Built only by ``serve --enable-paid-drafts`` (from the environment) or by tests (with a fake transport);
    there is no API route that creates or changes one."""
    api_key: Callable[[], str]
    client_factory: Callable[[Callable[[httpx.Response], None]], httpx.Client] = live_client

    @classmethod
    def from_environment(cls) -> "PaidSender":
        return cls(api_key=lambda: os.environ.get(KEY_VARIABLE, ""))


def key_problem(api_key: str) -> str | None:
    """Why this key cannot be used, without ever quoting it."""
    if not api_key:
        return f"{KEY_VARIABLE} is not set"
    if not (api_key.isascii() and api_key.isprintable() and api_key == api_key.strip() and " " not in api_key):
        return f"{KEY_VARIABLE} contains whitespace or non-printable characters"
    return None


def code_identity() -> dict:
    return {"mode": "paid", "flow_version": FLOW_VERSION,
            "sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in CODE_FILES}}


def checked_approval(body: bytes) -> dict:
    approval = strict_object(body, APPROVAL_FIELDS, "paid approval")
    if not isinstance(approval["request_sha256"], str):
        raise FlowRefused(422, "request_sha256 must be text")
    if approval["approve_paid_request"] is not True:
        raise FlowRefused(422, "approve_paid_request must be true: a paid request is sent only after explicit approval")
    estimate = approval["estimated_max_usd"]
    if isinstance(estimate, bool) or not isinstance(estimate, (int, float)):
        raise FlowRefused(422, "estimated_max_usd must repeat the estimate the preview showed")
    return approval


def classify(received: bytes, offered: tuple[str, ...]) -> tuple[str, str | None]:
    """The recorded outcome of a 200 response, through the adapter's strict validation."""
    try:
        parse_response(received, MODEL, offered)
        return "draft", None
    except DraftRefused as exc:
        message = str(exc)
        return ("no draft" if message.startswith(NO_DRAFT) else "refused"), message


def dispatch_paid(capture_id: str, body: bytes, sender: PaidSender | None, intake_dir: Path = INTAKE_DIR,
                  attempts_dir: Path = ATTEMPTS_DIR, drafts_dir: Path = DRAFTS_DIR,
                  clock: Callable[[], datetime] = now, published_dir: Path | None = None) -> dict:
    """Validate, reserve, send the approved saved bytes once, record the exchange, then publish it for review."""
    if sender is None:
        raise FlowRefused(409, NOT_ENABLED)
    published_dir = published_dir or draft_catalog.tracker_dir(drafts_dir)
    approval = checked_approval(body)
    api_key = sender.api_key()
    problem = key_problem(api_key)
    if problem:
        raise FlowRefused(409, f"{problem}; nothing was reserved or sent")
    record = approved_capture(capture_id, approval["request_sha256"], intake_dir)
    request, request_bytes = record["body"], record["request_bytes"]
    estimate = cost_estimate(request_bytes, request["max_tokens"])["estimated_real_run_if_output_reaches_max_usd"]
    if round(float(approval["estimated_max_usd"]), 4) != estimate:
        raise FlowRefused(409, f"The approved estimate does not match this request's planning estimate (${estimate}); "
                               "nothing was reserved or sent")
    if exposes(request_bytes, api_key):
        raise FlowRefused(409, "The saved request would carry the credential; nothing was reserved or sent")
    offered = _offered(request)
    request_hash = approval["request_sha256"]
    identity = code_identity()  # Captured before sending, and kept with the reservation.
    attempt = reserve_attempt(attempts_dir, capture_id)

    sent_at = None
    try:
        reserved_at = utc(clock()).isoformat()
        names = {"pilot": PAID_RUN, "case": capture_id, "model": MODEL, "prompt_hash": request_hash}
        keep_record(attempt / "reservation.json", _json_bytes({**names, "mode": "paid", "reserved_at": reserved_at,
                                                               "pid": os.getpid(), "code": identity}), api_key)
        keep_record(attempt / "request.json", request_bytes, api_key)  # Exactly the bytes about to be sent.
        seen: dict = {}

        def observe(response: httpx.Response) -> None:  # Status and request ID only; send_bytes checks the body.
            seen["http_status"] = response.status_code
            request_id = response.headers.get("request-id", "")
            if REQUEST_ID.fullmatch(request_id) and api_key not in request_id:
                seen["request_id"] = request_id

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
            message = str(exc)
            outcome = ("credential echo" if "contained the credential" in message
                       else "transport error" if message.startswith("The model request failed") else "provider error")
            if outcome == "transport error":
                message = f"{message}. {UNKNOWN}"
        received_at = utc(clock())
        summary = {}
        if received is not None:
            keep_record(attempt / "response.json", received, api_key)
            summary = response_summary(received)
            outcome, message = classify(received, offered)
        manifest = {
            **names, "case_sha256": digest({"capture_id": capture_id}), "synthetic_case": False,
            "effort": request["output_config"]["effort"], "max_tokens": request["max_tokens"],
            "prompt_version": record["request"]["prompt_version"], "request_bytes": len(request_bytes),
            "endpoint": MESSAGES_URL, "anthropic_version": API_VERSION, "code": identity,
            "reserved_at": reserved_at, "sent_at": sent_at.isoformat(), "received_at": received_at.isoformat(),
            "elapsed_seconds": (received_at - sent_at).total_seconds(),
            "http_status": seen.get("http_status"), "request_id": seen.get("request_id"),
            "provider_error": provider_error,
            "response": None if received is None else {"sha256": hashlib.sha256(received).hexdigest(),
                                                       "bytes": len(received), **summary},
            "outcome": outcome, "outcome_note": OUTCOME_NOTES[outcome], "adapter_message": message,
            "estimated_cost": usage_cost(summary.get("usage")), "planning_estimate_usd": estimate,
            "attempts": 1, "retries": 0, "fallbacks": None,
            "provenance": ("Sent once by this server to the Claude API after an explicit paid approval in the Tracker. "
                           "request.json holds the exact bytes sent: the approved saved request, never rebuilt. "
                           "response.json, when present, holds the exact bytes received after the credential check. "
                           "The request ID links the call to the Console."),
        }
        keep_record(attempt / "manifest.json", _json_bytes(manifest), api_key)  # Written last: it marks completion.
    except FlowRefused:
        raise
    except Exception as exc:
        sent = f" after it was sent. {UNKNOWN}" if sent_at is not None else " before it was sent."
        raise FlowRefused(500, f"The paid attempt was interrupted ({type(exc).__name__}){sent} What was written is "
                               "kept, and this capture will not be attempted again.") from None

    view = publish_after_recording(capture_id, intake_dir, attempt, drafts_dir, published_dir)
    return result(capture_id, view, attempt, recovered=False, provider_called=True)


def paid_status(sender: PaidSender | None) -> dict:
    """Whether this server can send a paid request. Never reveals or checks the key's value beyond its shape."""
    if sender is None:
        return {"enabled": False, "detail": NOT_ENABLED}
    problem = key_problem(sender.api_key())
    return {"enabled": problem is None, "detail": f"{problem}; paid sending is unavailable" if problem else
            f"Paid sending is enabled: one explicitly approved request per capture to {MODEL}."}
