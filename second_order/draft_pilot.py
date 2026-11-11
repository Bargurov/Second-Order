"""Live drafting pilot on Claude Sonnet 5.5, the only command that can send a model request.

The current run is pilot-4: three synthetic review cases rerun under prompt draft-prompt-5, bound to that
version and refusing any other. Each run has its own directory, so earlier runs' records are never touched.

`preview` prints the exact request, its hash and a cost estimate, and sends and writes nothing. `send`
needs the API key in SECOND_ORDER_ANTHROPIC_API_KEY and the prompt hash the preview printed. That hash is
the SHA-256 of the exact canonical request body, so only the reviewed bytes can go out; it does not
cover the codebase, and an unrelated code change leaves it unchanged. The code identity is recorded
separately. Before anything is sent the case is reserved by creating its directory exclusively, which
is atomic: a second or concurrent attempt finds it and is refused. Code never releases a reservation,
so a timeout, crash or provider error leaves the case reserved too.

Kept privately under data/pilot (git-ignored): the exact request bytes, the exact response bytes once
the adapter's credential check has passed, the code identity captured before sending (in the
reservation record), and a manifest of provenance, usage and outcome. One attempt:
no retry and no fallback. Nothing is frozen and no database is opened. The adapter's default model is
unchanged; this module names Claude Sonnet 5.5 and reuses the adapter's request builder, sender and
strict validation.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Mapping
import httpx
from .draft_review import NO_DRAFT, load_cases, pick
from .model_draft import (API_VERSION, EFFORT, MAX_TOKENS, MESSAGES_URL, PROMPT_VERSION, DraftRefused, build_request,
                          compose, envelope, exposes, operator_event, parse_response, prospective_observables,
                          reviewable, send, strict_json)
from .schema import utc
from .store import canonical, digest

# Each run has its own identity and directory and is bound to one prompt version. pilot-1 (draft-prompt-3),
# pilot-2 (draft-prompt-4, clear-policy and insufficient-source) and pilot-3 (draft-prompt-4, the six other
# cases) are complete; their records and the archived 401 attempt stay as they are and are never read or
# written here.
PILOT_ID = "pilot-4-claude-sonnet-5-5"
PILOT_PROMPT_VERSION = "draft-prompt-5"
MODEL = "claude-sonnet-5-5"  # Named for the pilot only; model_draft.DEFAULT_MODEL is unchanged.
CASES = ("conflicting-labor-inflation", "ambiguous-wording", "headline-reports-move")
ROOT = Path(__file__).resolve().parent.parent
PILOT_DIR = ROOT / "data" / "pilot" / PILOT_ID
KEY_VARIABLE = "SECOND_ORDER_ANTHROPIC_API_KEY"  # Not ANTHROPIC_API_KEY, which other tools pick up on their own.
TIMEOUT = httpx.Timeout(600.0, connect=10.0)  # httpx's 5-second default would abandon a thinking request.
PRICES = {"model": MODEL, "input_usd_per_mtok": 2.0, "output_usd_per_mtok": 10.0, "tool_prompt_tokens": 286,
          "source": "https://platform.claude.com/docs/en/about-claude/pricing", "read_on": "2026-10-04"}
REQUEST_ID = re.compile(r"req_[A-Za-z0-9]{1,128}")
PROMPT_HASH = re.compile(r"[0-9a-f]{64}")
OUTCOME_NOTES = {
    "draft": "One draft passed the adapter's strict checks. Structure only; the reasoning is reviewed separately.",
    "no draft": "The model submitted no draft (it ended without calling the tool, or declined). Its text is in "
                "response.json; whether declining suits the case is a reasoning question.",
    "refused": "The adapter refused the response as invalid or unusable. The bytes are kept in response.json.",
    "provider error": "The provider returned an error status. Its body is not kept; the request ID links the call "
                      "to the Console.",
    "transport error": "No complete response arrived. The request may still have been processed and billed: check "
                       "the Console's usage for the send time.",
    "credential echo": "The response contained the credential, so nothing from it was kept.",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def plan(case_id: str, clock: Callable[[], datetime] = now) -> tuple[dict, dict, bytes, str]:
    """A pilot case, its request, the exact bytes send() would post and their SHA-256 (the prompt hash)."""
    if case_id not in CASES:
        raise ValueError(f"The pilot covers only {', '.join(CASES)}, not {case_id!r}")
    if PROMPT_VERSION != PILOT_PROMPT_VERSION:
        raise ValueError(f"{PILOT_ID} is bound to {PILOT_PROMPT_VERSION}, but the adapter now builds {PROMPT_VERSION}; "
                         "another prompt needs a new run identity, and nothing was sent")
    case = pick(load_cases(clock=clock), case_id)
    event, _ = operator_event(case["operator"], clock)
    request = build_request(event, case["source_text"], MODEL, prospective_observables())
    body = canonical(request).encode("utf-8")
    return case, request, body, hashlib.sha256(body).hexdigest()


def cost_estimate(body: bytes) -> dict:
    """A planning estimate for one request, not a guaranteed ceiling."""
    input_tokens = len(body) // 2 + PRICES["tool_prompt_tokens"] + 1000
    usd = (input_tokens * PRICES["input_usd_per_mtok"] + MAX_TOKENS * PRICES["output_usd_per_mtok"]) / 1_000_000
    return {"estimate_if_output_reaches_max_tokens_usd": round(usd, 4), "input_tokens_assumed": input_tokens,
            "output_tokens_at_max_tokens": MAX_TOKENS, "prices": PRICES,
            "caveat": "An estimate, not a guaranteed ceiling. max_tokens caps output (thinking included), but the "
                      "input count is estimated from the request size (2 characters per token, plus the 286-token "
                      "tool prompt and 1,000 tokens for the unpublished thinking prompt), prices can change, and "
                      "US-only inference adds 10%. The Console's usage is authoritative."}


def state(case_dir: Path) -> dict:
    """What a case directory shows. Read-only."""
    if not case_dir.exists():
        return {"state": "unreserved"}
    if (case_dir / "manifest.json").exists():
        try:
            manifest = json.loads((case_dir / "manifest.json").read_text(encoding="utf-8"))
        except ValueError:  # A send in another process is still writing it.
            return {"state": "completing"}
        return {"state": "completed", "outcome": manifest["outcome"], "sent_at": manifest["sent_at"]}
    if (case_dir / "attempt.json").exists():
        return {"state": "sent, outcome unknown",
                "note": "The process stopped after sending. The request may have been processed and billed; check "
                        "the Console's usage. The case stays reserved."}
    return {"state": "reserved, not sent",
            "note": "The process stopped before sending. The case stays reserved; releasing it is a separate decision."}


def status(root: Path = PILOT_DIR) -> dict:
    return {"pilot": PILOT_ID, "model": MODEL, "cases": {case: state(root / case) for case in CASES}}


def preview(case_id: str, root: Path = PILOT_DIR, clock: Callable[[], datetime] = now) -> dict:
    case, request, body, prompt_hash = plan(case_id, clock)
    return {"pilot": PILOT_ID, "case": case_id, "title": case["title"], "model": MODEL, "effort": EFFORT,
            "max_tokens": MAX_TOKENS, "prompt_version": PROMPT_VERSION, "prompt_hash": prompt_hash,
            "request_bytes": len(body), "endpoint": MESSAGES_URL,
            "headers": {"x-api-key": f"read from {KEY_VARIABLE}; never stored or printed",
                        "anthropic-version": API_VERSION, "content-type": "application/json"},
            "reservation": {"path": str(root / case_id), **state(root / case_id)},
            "cost_estimate": cost_estimate(body),
            "send_command": f"python -m second_order.draft_pilot send {case_id} --confirm-prompt-hash {prompt_hash}",
            "request": request, "note": "Preview only: nothing was sent or written."}


def keep(path: Path, data: bytes, api_key: str) -> None:
    """Create a new private file and flush it to disk. Nothing carrying the credential is written."""
    if exposes(data, api_key):
        raise DraftRefused(f"{path.name} would contain the credential; it was not written")
    with open(path, "xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def as_json(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def code_identity() -> dict:
    """The code that built and checked the request: file hashes, plus the git commit when git is available."""
    files = ("second_order/model_draft.py", "second_order/draft_pilot.py")
    identity = {"sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in files}}
    try:
        def git(*arguments: str) -> str:
            return subprocess.run(["git", *arguments], cwd=ROOT, capture_output=True, text=True, timeout=10,
                                  check=True).stdout.strip()
        identity |= {"git_head": git("rev-parse", "HEAD"), "uncommitted_changes": bool(git("status", "--porcelain"))}
    except (OSError, subprocess.SubprocessError):
        identity |= {"git_head": None, "uncommitted_changes": None}
    return identity


def response_summary(body: bytes) -> dict:
    """Envelope fields for the manifest, once the adapter's credential check has passed."""
    try:
        message = envelope(strict_json(body))
    except DraftRefused:
        return {}
    return {key: message.get(key) for key in ("id", "model", "stop_reason", "stop_details", "usage")}


def usage_cost(usage: object) -> dict | None:
    tokens = [usage.get(field) if isinstance(usage, dict) else None for field in ("input_tokens", "output_tokens")]
    if not all(type(count) is int for count in tokens):
        return None
    usd = (tokens[0] * PRICES["input_usd_per_mtok"] + tokens[1] * PRICES["output_usd_per_mtok"]) / 1_000_000
    return {"usd": round(usd, 6), "basis": "input and output tokens at the published rates; cache tokens and any "
                                           "data-residency multiplier are not included. The Console is authoritative."}


def live_client(observe: Callable[[httpx.Response], None]) -> httpx.Client:
    """The project's only real model client: one attempt, no environment proxies, no redirects, a long timeout."""
    return httpx.Client(timeout=TIMEOUT, trust_env=False, follow_redirects=False,
                        transport=httpx.HTTPTransport(retries=0), event_hooks={"response": [observe]})


def send_case(case_id: str, api_key: str, confirmed_hash: str, root: Path = PILOT_DIR,
              client_factory: Callable[[Callable[[httpx.Response], None]], httpx.Client] = live_client,
              clock: Callable[[], datetime] = now) -> dict:
    """Reserve a case, send its previewed request once and keep the exact exchange. Never retries."""
    case, request, body, prompt_hash = plan(case_id, clock)
    if confirmed_hash != prompt_hash or not PROMPT_HASH.fullmatch(confirmed_hash):
        raise ValueError("--confirm-prompt-hash must equal the hash the preview printed for this request; "
                         "nothing was sent")
    if not api_key:
        raise ValueError(f"{KEY_VARIABLE} is not set; nothing was sent")
    if not (api_key.isascii() and api_key.isprintable() and api_key == api_key.strip() and " " not in api_key):
        raise ValueError(f"{KEY_VARIABLE} contains whitespace or non-printable characters; nothing was sent")
    if exposes(body, api_key):
        raise ValueError("The request would carry the credential; nothing was sent")
    # Captured once, before sending, and persisted with the reservation: a code change while the request is
    # in flight cannot alter the recorded revision, and a crash cannot lose it.
    identity = code_identity()
    case_dir = root / case_id
    root.mkdir(parents=True, exist_ok=True)
    try:
        case_dir.mkdir()  # The reservation: an atomic exclusive create, never released by code.
    except FileExistsError:
        raise ValueError(f"{case_id} is already reserved ({state(case_dir)['state']}); each case is attempted at "
                         "most once, and nothing was sent") from None
    reserved_at = utc(clock())
    keep(case_dir / "reservation.json", as_json({"pilot": PILOT_ID, "case": case_id, "model": MODEL,
                                                 "prompt_hash": prompt_hash, "reserved_at": reserved_at.isoformat(),
                                                 "pid": os.getpid(), "code": identity}), api_key)
    keep(case_dir / "request.json", body, api_key)
    seen: dict = {}

    def observe(response: httpx.Response) -> None:  # Status and request ID only; send() checks the body.
        seen["http_status"] = response.status_code
        request_id = response.headers.get("request-id", "")
        if REQUEST_ID.fullmatch(request_id) and api_key not in request_id:
            seen["request_id"] = request_id

    sent_at = utc(clock())
    keep(case_dir / "attempt.json", as_json({"state": "sending", "sent_at": sent_at.isoformat()}), api_key)
    received, message, result = None, None, None
    try:
        with client_factory(observe) as client:
            received = send(client, request, api_key)
    except DraftRefused as exc:
        message = str(exc)
        outcome = ("credential echo" if "contained the credential" in message
                   else "transport error" if message.startswith("The model request failed") else "provider error")
    received_at = utc(clock())
    summary = {}
    if received is not None:
        keep(case_dir / "response.json", received, api_key)
        summary = response_summary(received)
        try:
            offered = prospective_observables()
            output, meta = parse_response(received, MODEL, offered)
            event, story_id = operator_event(case["operator"], clock)
            engine = {"provider": "anthropic", "model": meta["model"], "prompt_hash": prompt_hash,
                      "schema_version": "0.2"}
            result = reviewable(compose(event, story_id, output, engine), meta, "sent in this process", MODEL, clock)
            outcome = "draft"
        except DraftRefused as exc:
            message = str(exc)
            outcome = "no draft" if message.startswith(NO_DRAFT) else "refused"
    if result is not None:
        keep(case_dir / "draft.json", as_json(result), api_key)
    manifest = {
        "pilot": PILOT_ID, "case": case_id, "case_sha256": digest(case), "synthetic_case": True, "model": MODEL,
        "effort": EFFORT, "max_tokens": MAX_TOKENS, "prompt_version": PROMPT_VERSION, "prompt_hash": prompt_hash,
        "request_bytes": len(body), "endpoint": MESSAGES_URL, "anthropic_version": API_VERSION,
        "code": identity, "reserved_at": reserved_at.isoformat(), "sent_at": sent_at.isoformat(),
        "received_at": received_at.isoformat(), "elapsed_seconds": (received_at - sent_at).total_seconds(),
        "http_status": seen.get("http_status"), "request_id": seen.get("request_id"),
        "response": None if received is None else {"sha256": hashlib.sha256(received).hexdigest(),
                                                   "bytes": len(received), **summary},
        "outcome": outcome, "outcome_note": OUTCOME_NOTES[outcome], "adapter_message": message,
        "estimated_cost": usage_cost(summary.get("usage")), "attempts": 1, "retries": 0, "fallbacks": None,
        "provenance": "Sent once by this process to the Claude API. request.json holds the exact bytes sent; "
                      "response.json, when present, the exact bytes received after the credential check. A later "
                      "reader cannot verify that origin from the files alone; the request ID links the call to the "
                      "Console. Synthetic case: nothing here measures forecasting accuracy or model performance.",
    }
    keep(case_dir / "manifest.json", as_json(manifest), api_key)
    return {"directory": str(case_dir), "files": sorted(path.name for path in case_dir.iterdir()), **manifest}


def main(argv: list[str] | None = None, root: Path = PILOT_DIR,
         client_factory: Callable[[Callable[[httpx.Response], None]], httpx.Client] = live_client,
         environ: Mapping[str, str] = os.environ, clock: Callable[[], datetime] = now) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m second_order.draft_pilot",
        description=f"Live drafting pilot {PILOT_ID} on {MODEL}. preview and status send nothing; send makes one "
                    "billed request for one case, at most once.")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("preview", help="Print the exact request, its hash and a cost estimate").add_argument(
        "case", choices=CASES)
    sending = actions.add_parser("send", help=f"Send one previewed request (needs {KEY_VARIABLE})")
    sending.add_argument("case", choices=CASES)
    sending.add_argument("--confirm-prompt-hash", required=True,
                         help="The prompt_hash printed by preview: the SHA-256 of the exact request body")
    actions.add_parser("status", help="Show each case's reservation and outcome")
    args = parser.parse_args(argv)
    try:
        if args.action == "preview":
            result = preview(args.case, root, clock)
        elif args.action == "status":
            result = status(root)
        else:
            result = send_case(args.case, environ.get(KEY_VARIABLE, ""), args.confirm_prompt_hash, root,
                               client_factory, clock)
    except (ValueError, OSError) as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    # As in the main CLI: Unicode on a console, ASCII JSON when piped, which no Windows code page can corrupt.
    print(json.dumps(result, indent=2, ensure_ascii=not sys.stdout.isatty()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
