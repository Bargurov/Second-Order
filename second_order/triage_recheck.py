"""Headline triage, local re-checks: an explicit re-check of a recorded response that was not accepted, under the current
validation policy (headline_triage.VALIDATION_POLICIES). Nothing is sent, regenerated or repaired; see revalidate.

Reading a re-check, and using a response accepted on one, is triage_flow's: its outcome is verified against the saved
response on every read, and the attempt's own records never change.
"""
from datetime import datetime
from pathlib import Path
from typing import Callable

from .analysis_flow import FlowRefused, _json_bytes, keep_record, strict_object
from . import headline_triage  # The current validation policy is read from it at call time, never bound at import.
from .headline_triage import VALIDATION_POLICIES, ResponseRejected, parse_response, sha256
from .schema import utc
from .triage_flow import (ATTEMPT_NAME, LEGACY, REVALIDATION_VERSION, TRIAGE_DIR, TriageRefused, attempt_names,
                          load_record, now, read_attempt, request_view)


def revalidate(triage_id: str, attempt_name: str, body: bytes, triage_dir: Path = TRIAGE_DIR,
               clock: Callable[[], datetime] = now) -> dict:
    """An explicit local re-check of one recorded response that was not accepted, under the current validation policy.

    The body names the exact saved response (`response_sha256`). Nothing is sent, regenerated or repaired: the saved
    bytes are parsed again with the request's own entries, comparison scope and model, and the outcome is written to
    `revalidations/<policy>.json` in the attempt's folder, created once and never replaced. The attempt's own files
    stay exactly as they were. A request prepared under headline-triage-0.2 has no scope to check relations against and
    is not re-checked."""
    match = ATTEMPT_NAME.fullmatch(attempt_name or "")
    if not match:
        raise TriageRefused(404, "Unknown attempt")
    try:
        named = strict_object(body, ("response_sha256",), "local re-check")
    except FlowRefused as exc:
        raise TriageRefused(exc.status, str(exc)) from None
    record = load_record(triage_dir, triage_id)
    mode = match.group(1)
    if attempt_name not in attempt_names(record, mode):
        raise TriageRefused(404, "This request has no such attempt")
    if record["pairs"] is None:
        raise TriageRefused(409, f"{LEGACY}. It had no comparison scope to check relations against, so it is not "
                                 "re-checked; nothing was written")
    attempt = read_attempt(record, mode, attempt_name)
    if attempt["state"] != "complete" or attempt["outcome"] != "not_accepted" or not attempt.get("response_sha256"):
        raise TriageRefused(409, "Only a recorded response that was not accepted can be re-checked locally; nothing "
                                 "was written")
    folder = record["folder"] / attempt_name
    received = (folder / "response.json").read_bytes()
    if named["response_sha256"] != attempt["response_sha256"] or sha256(received) != attempt["response_sha256"]:
        raise TriageRefused(409, "The named response is not this attempt's saved response; nothing was written")
    policy = headline_triage.VALIDATION_POLICY
    path = folder / "revalidations" / f"{policy}.json"
    wrote = False
    if not path.exists():  # Made once per policy; asking again shows the recorded outcome.
        try:
            parse_response(received, record["entries"], record["context"], record["config"]["model"],
                           scope=record["pairs"], policy=policy)
            outcome, message = "accepted", None
        except ResponseRejected as exc:
            outcome, message = "not_accepted", str(exc)
        path.parent.mkdir(exist_ok=True)
        try:
            keep_record(path, _json_bytes({
                "revalidation_version": REVALIDATION_VERSION, "triage_id": triage_id, "attempt": attempt_name,
                "mode": mode, "validation_policy": policy, "policy_statement": VALIDATION_POLICIES[policy]["statement"],
                "revalidated_at": utc(clock()).isoformat(timespec="seconds"), "outcome": outcome, "message": message,
                "response_sha256": attempt["response_sha256"],
                "manifest_sha256": sha256((folder / "manifest.json").read_bytes()),
                "original": {"outcome": attempt["outcome"], "message": attempt["message"],
                             "validation_policy": attempt["validation_policy"], "config": record["config"],
                             "request_sha256": record["request_sha256"], "request_id": attempt["request_id"],
                             "received_at": attempt["received_at"]},
                "provenance": (f"A local re-check, under {policy}, of the response this request's {mode} attempt "
                               f"received at {attempt['received_at']}. That response was generated for the original "
                               f"request (prompt {record['config']['prompt_version']}, schema "
                               f"{record['config']['schema_version']}); nothing was regenerated, re-sent, repaired or "
                               "human-reviewed, and the attempt's own records are unchanged.")}))
            wrote = True
        except FileExistsError:  # A concurrent re-check wrote it first; its record stands.
            pass
    return {**request_view(triage_id, triage_dir), "revalidated_now": wrote, "provider_called": False}
