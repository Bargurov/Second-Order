"""The user flow of the evidence-first research analysis (docs/admin-user-contract.md, user-api-0.3).

A signed-in user adds a source (a capture they own), prepares an analysis of it at one offered Effort (an immutable
research-request-0.2), asks for a credit quote, approves it, and reads and reviews the recorded result. Every function
takes the server-derived identity; nothing trusts a client-sent user ID or role. A record the user does not own
answers exactly like a record that does not exist.

The run (``run``) rechecks everything, then reserves the quoted credits, today's daily slot and the request's single
attempt in one transaction of the accounts store (see entitlements) before the existing send core (research_analysis.
send_once) reserves the attempt folder and sends the exact saved bytes once: no retry, fallback or model substitution.
The send is recorded in the accounts store before the transport is called. A recorded response settles the quoted
credits; an attempt that provably sent nothing returns them once; anything uncertain stays held for an administrator.

Every payload built here is a user projection: no model or provider name, money, token count, provider ID, request or
response bytes, HTTP status of a provider call or operational log. The administrator's payloads are built elsewhere.
"""
from dataclasses import dataclass
from datetime import datetime
import json
import re
from pathlib import Path
from typing import Callable

from . import accounts as acc, attempt_locks, entitlements, event_intake, research_analysis as ra, usage
from .accounts import Accounts, AccountsRefused, Identity
from .analysis_flow import FlowRefused, MAX_FORM_BYTES, plan_capture, save_capture, strict_object
from .human_review import ReviewRefused, write_exclusively
from .model_draft import MAX_SOURCE_CHARS
from .paid_drafts import PaidSender
from .store import canonical

CONTRACT = "user-api-0.5"
EFFORT_LABEL = {"low": "Low", "medium": "Medium", "high": "High", "xhigh": "Extra high", "max": "Maximum"}
EFFORT_NOTE = ("Higher Effort lets the analysis spend more of its output allowance on reasoning. It does not promise "
               "a better result or a fixed running time, and it can need more credits.")
RECORDED = ("analysis", "no_additional_finding", "declined", "incomplete", "invalid")
CARRIES_ANALYSIS = ("analysis", "no_additional_finding")
TECHNICAL = ("provider error", "transport error", "credential echo")
NOTES = {
    "analysis": "Every quoted passage was found in your source text. Whether the reading is sound is for you to judge.",
    "no_additional_finding": ("Every quoted passage was found in your source text. The analysis found nothing beyond "
                              "what the source states; that is an acceptable result."),
    "declined": "No analysis was produced for this source. Any explanation given is shown as written.",
    "incomplete": "The analysis stopped before it was complete. It is kept as recorded and is not run again.",
    "invalid": "The reply did not meet the analysis format, so none of it is shown.",
}
DETAILS = {
    "prepared": "Prepared. Nothing has been run; ask for a credit quote to run it.",
    "running": "Running. Your credits are reserved; the result appears here when it is recorded.",
    "recorded": "Recorded. Reading, reviewing or exporting this result uses no credits or allowance.",
    "failed": "The analysis service returned an error. It is not run again.",
    "unresolved_sent": "The request was sent, but no outcome was recorded. It is not sent again.",
    "unresolved_unsent": "The run stopped before anything was sent. It is not run again.",
    "not_sent": "Nothing was sent. This prepared analysis cannot be run again.",
}
UNAVAILABLE = {
    "account_inactive": "This account is not active.",
    "sending_disabled": "Analyses cannot run on this server right now.",
    "no_credit_policy": "Analyses cannot be quoted yet: no credit policy is set. Ask the administrator.",
    "no_effort_enabled": "No Effort is offered yet. Ask the administrator.",
    "no_daily_limit": "No daily analysis limit is set for your account yet. Ask the administrator.",
    "no_credits_allocated": "No credits have been allocated to your account yet. Ask the administrator.",
    "no_credits_available": ("You have no credits available now. Credits held by a run are charged or returned when "
                             "it settles; for more, ask the administrator."),
}
# When several apply, `reason` is the first in this order; `reasons` lists them all (docs/onboarding-contract.md).
UNMARKED = ("Go deeper made this source before it recorded which of its passages are the publishers' own words, so it "
            "is not analysed again. Its earlier results stay as they are. Go deeper from the story again to make a "
            "new source of the same reports. Nothing was reserved or counted.")
REASON_ORDER = ("sending_disabled", "no_credit_policy", "no_effort_enabled", "no_daily_limit", "no_credits_allocated",
                "no_credits_available")
SOURCE_FIELDS = ("headline", "source_url", "published_at", "source_text")
REVIEW_FIELDS = ("parent_review_id", "result_sha256", "status", "notes")
RUN_FIELDS = ("quote_id", "effort", "credits", "approve")
REVIEW_ID = re.compile(r"[0-9a-f]{64}")
INTERNAL_WORDS = re.compile(r"model|prompt|adapter|request|claude|token|story|hash|sha-?256", re.IGNORECASE)
GENERIC_SOURCE = ("The source could not be accepted. Check the headline, the address, the publication time (with its "
                  "UTC offset) and the text.")
# The source address's limit: pydantic's HttpUrl, which counts the address's UTF-8 bytes as sent (a character outside
# ASCII counts two to four). frontend/src/contracts/user.ts publishes the same number.
MAX_SOURCE_URL = 2_083
# The capture path's own refusals, in the user's words; anything else that names an internal term is GENERIC_SOURCE.
SOURCE_WORDING = (
    (re.compile(r"source_url: URL should have at most"),
     f"The source address is too long: at most {MAX_SOURCE_URL:,} characters, where a letter outside basic Latin "
     "counts as two to four. Use a shorter address for the same page."),
    (re.compile(r"source_url: URL scheme"), "The source address must start with https:// or http://."),
    (re.compile(r"source_url:"), "The source address is not a web address; it must start with https:// or http://."),
    (re.compile(r"headline: String should have at least"), "Write the source's headline."),
    (re.compile(r"headline: String should have at most (\d+)"), "The headline is longer than 1,500 characters."),
    (re.compile(r"publication time is in the future"),
     "The publication time is in the future. A source must already be published; check the date, the time and the "
     "UTC offset."),
    (re.compile(r"Every event field must be text"), "Every field of a source must be text."),
    (re.compile(r"source text has (\d+) characters; the limit is (\d+)"), None),
    (re.compile(r"already exists; captures are never overwritten"),  # By this account or by another writer.
     "The same source was saved at this same moment, so nothing new was saved or counted. If it is not in your "
     "sources, send it again."),
)


def source_refusal(message: str) -> str:
    """The user's sentence for a refused source: the capture path's own wording where it is already the user's, a
    translation where it speaks of operator events or validation internals, and GENERIC_SOURCE otherwise."""
    for pattern, wording in SOURCE_WORDING:
        found = pattern.search(message)
        if found and wording is None:  # The text's length, with thousands separators.
            return (f"The source text has {int(found.group(1)):,} characters; the limit is {int(found.group(2)):,}. "
                    "A source is never shortened, so save a shorter part of it.")
        if found:
            return wording
    return GENERIC_SOURCE if INTERNAL_WORDS.search(message) or re.search(r"\b(operator|event|drafted?)\b", message,
                                                                         re.IGNORECASE) else message


def refused(status: int, code: str, detail: str, **extra) -> AccountsRefused:
    return AccountsRefused(status, code, detail, **extra)


NOT_FOUND = "Nothing is available at this address."


@dataclass(frozen=True)
class UserResearch:
    """What the user routes need: the accounts store, the research records, and the paid sender (None unless the
    server was started with paid sending enabled; without it nothing runs)."""
    accounts: Accounts
    folders: ra.Folders
    sender: PaidSender | None
    clock: Callable[[], datetime] = acc.now

    @property
    def intake(self) -> Path:
        return self.folders.intake


def sha256_of(value: dict) -> str:
    return ra.sha256(canonical(value).encode("utf-8"))


# ---------------------------------------------------------------- what a review is bound to (QA-3)
# A result's fingerprint names the recorded content, never the server's sentences about it. user-result-1 (the first
# reviews) hashed the whole user projection, including the outcome's fixed note, so rewording a note alone detached
# every review from an unchanged result. user-result-2 hashes the content only. A review saved under user-result-1 is
# never rewritten: it is checked against the content through the note wording that was in force for it (frozen below),
# so it stays bound exactly while the content is the same, and any real change of the content still detaches it.
RESULT_BINDING = "user-result-2"
LEGACY_RESULT_BINDING = "user-result-1"
LEGACY_NOTES = {  # The notes as user-result-1 hashed them. Never edit: old reviews' fingerprints depend on them.
    "analysis": "Every quoted passage was found in your source text. Whether the reading is sound is for you to judge.",
    "no_additional_finding": ("Every quoted passage was found in your source text. The analysis found nothing beyond "
                              "what the source states; that is an acceptable result."),
    "declined": "No analysis was produced for this source. Any explanation given is shown as written.",
    "incomplete": "The analysis stopped before it was complete. It is kept as recorded and is not run again.",
    "invalid": "The reply did not meet the analysis format, so none of it is shown.",
}


def result_fingerprint(result: dict) -> str:
    """user-result-2: the recorded content of a user result (outcome, recording time, analysis, explanation)."""
    return sha256_of({"binding": RESULT_BINDING, **{key: result[key] for key in
                                                    ("outcome", "recorded_at", "analysis", "explanation")}})


def legacy_fingerprint(result: dict) -> str:
    """user-result-1 of the same content: the projection with the note as it was worded then."""
    return sha256_of({**result, "note": LEGACY_NOTES[result["outcome"]]})


def bound_fingerprint(binding: dict, result: dict | None) -> str:
    """The fingerprint a saved review is bound to, in user-result-2: its own for a user-result-2 review; for a
    user-result-1 review, the current content's when its stored fingerprint proves the same content, else what it
    stored (which then differs from the current result)."""
    stored = binding["user_result_sha256"]
    if binding.get("user_result_binding") == RESULT_BINDING or result is None:
        return stored
    return result_fingerprint(result) if stored == legacy_fingerprint(result) else stored


# ---------------------------------------------------------------- the account

def sending_ready(context: UserResearch) -> bool:
    return context.sender is not None and ra.key_problem(context.sender.api_key()) is None


def effort_options(efforts: list[str]) -> list[dict]:
    return [{"effort": effort, "label": EFFORT_LABEL[effort]} for effort in efforts]


def account_payload(context: UserResearch, identity: Identity) -> dict:
    moment = context.clock()
    snapshot = entitlements.user_snapshot(context.accounts, identity.user_id, moment)
    policy = entitlements.current_policy(context.accounts)
    efforts = entitlements.offered_efforts(policy, ra.MODEL)
    applies = {"sending_disabled": not sending_ready(context), "no_credit_policy": policy is None,
               "no_effort_enabled": policy is not None and not efforts,
               "no_daily_limit": snapshot["daily"]["limit"] is None,
               "no_credits_allocated": not snapshot["allocated"],
               "no_credits_available": snapshot["allocated"] and snapshot["credits"]["available"] == 0}
    reasons = [{"reason": reason, "detail": UNAVAILABLE[reason]} for reason in REASON_ORDER if applies[reason]]
    first = reasons[0] if reasons else {"reason": None, "detail": None}
    return {"contract": CONTRACT, "user": identity.view(), "credits": snapshot["credits"], "daily": snapshot["daily"],
            "efforts": effort_options(efforts), "effort_note": EFFORT_NOTE,
            "analysis": {"available": not reasons, **first, "reasons": reasons}}


# ---------------------------------------------------------------- sources

def _owned_capture(context: UserResearch, identity: Identity, source_id: object) -> dict:
    if not isinstance(source_id, str) or not event_intake.CAPTURE_ID.fullmatch(source_id) or \
            acc.owner_of(context.accounts, "capture", source_id) != identity.user_id:
        raise refused(404, "not_found", NOT_FOUND)
    try:
        return event_intake.verified(context.intake, source_id)
    except (event_intake.IntakeRefused, OSError):
        raise refused(500, "internal_error", "This source could not be read. An administrator can check it.") from None


def source_view(source_id: str, record: dict, text: bool = True) -> dict:
    event, times = record["event"], record["times"]
    view = {"source_id": source_id, "headline": event["headline"], "source_url": event["source_url"],
            "published_at": event["published_at"], "published_at_as_supplied": times["published_at_as_supplied"],
            "captured_at": times["captured_at"], "characters": len(record["source_text"])}
    return {**view, "text": record["source_text"]} if text else view


def add_source(context: UserResearch, identity: Identity, body: bytes) -> dict:
    """Capture a source the user typed, pasted or confirmed from an import, owned by the user. Nothing is analysed or
    sent. The form is first checked by every rule of the capture and built in memory, so an invalid one is refused
    with nothing counted or written (QA-7). A new source then counts once against the usage policy
    (docs/news-usage-contract.md): today's `source` count and the account's storage are checked and reserved, and the
    capture written, in one transaction, so a write refused only by the write itself (the same capture written since
    the check by another account or the operator's form) records nothing either."""
    try:
        payload = strict_object(body, SOURCE_FIELDS, "source", MAX_SOURCE_BODY)
    except FlowRefused:
        raise refused(422, "invalid_source", f"A source has exactly these fields: {', '.join(SOURCE_FIELDS)}.") \
            from None
    with usage.account_lock(identity.user_id):  # One source write at a time per account: storage stays exact.
        try:
            planned = plan_capture(payload, context.intake, context.clock)
        except FlowRefused as exc:
            raise refused(422, "invalid_source", source_refusal(str(exc))) from None
        held = usage.stored(context.accounts, context.intake, identity.user_id)
        try:
            reservation = usage.reserve(context.accounts, identity.user_id, "source", context.clock(),
                                        storage=usage.storage_check(held, planned["manifest"]["source"]["bytes"]),
                                        write=lambda: save_capture(planned, context.intake))
        except FlowRefused as exc:  # Found only by the write; its count was rolled back with it.
            raise refused(422, "invalid_source", source_refusal(str(exc))) from None
        try:
            source_id = reservation.written["capture_id"]
            if acc.owner_of(context.accounts, "capture", source_id) == identity.user_id:
                usage.release(context.accounts, reservation, "the same source was already saved",  # Nothing new.
                              context.clock())
            else:
                acc.assign(context.accounts, "capture", source_id, identity.user_id, identity.user_id,
                           "added by the user", context.clock())
        except BaseException:
            usage.release(context.accounts, reservation, "the source was not saved", context.clock())
            raise
    return {"contract": CONTRACT, "source": source_view(source_id, event_intake.verified(context.intake, source_id))}


def list_sources(context: UserResearch, identity: Identity) -> dict:
    rows = []
    for source_id in acc.owned(context.accounts, "capture", identity.user_id):
        try:
            rows.append(source_view(source_id, event_intake.verified(context.intake, source_id), text=False))
        except (event_intake.IntakeRefused, OSError):
            continue  # An unreadable record is the administrator's to check; it is never shown half-verified.
    return {"contract": CONTRACT, "sources": sorted(rows, key=lambda row: row["captured_at"], reverse=True)}


def source_detail(context: UserResearch, identity: Identity, source_id: str) -> dict:
    record = _owned_capture(context, identity, source_id)
    analyses = [row for row in _summaries(context, identity) if row["source"]["source_id"] == source_id]
    return {"contract": CONTRACT, "source": source_view(source_id, record), "analyses": analyses}


# ---------------------------------------------------------------- analyses

def _owned_request(context: UserResearch, identity: Identity, analysis_id: object) -> dict:
    """A user's own research-request-0.2, verified. Anything else (another account's, the operator's, unknown or
    malformed) is not found."""
    match = ra.REQUEST_ID_PATTERN.fullmatch(analysis_id) if isinstance(analysis_id, str) else None
    if not match or match.group(3) is None or \
            acc.owner_of(context.accounts, "capture", match.group(1)) != identity.user_id:
        raise refused(404, "not_found", NOT_FOUND)
    try:
        verified = ra.verified_request(analysis_id, context.folders)
    except FlowRefused as exc:
        if exc.status == 404:
            raise refused(404, "not_found", NOT_FOUND) from None
        raise refused(500, "internal_error", "This analysis could not be read. An administrator can check it.") \
            from None
    if verified["prepared_by"] != identity.user_id:
        raise refused(404, "not_found", NOT_FOUND)
    return verified


def prepare(context: UserResearch, identity: Identity, body: bytes) -> tuple[dict, bool]:
    """Prepare (or reopen) the immutable analysis of one owned source at one offered Effort. Nothing is sent."""
    try:
        payload = strict_object(body, ("source_id", "effort"), "analysis")
    except FlowRefused:
        raise refused(422, "invalid_request", "An analysis is prepared from exactly source_id and effort.") from None
    _owned_capture(context, identity, payload["source_id"])
    efforts = entitlements.offered_efforts(entitlements.current_policy(context.accounts), ra.MODEL)
    if payload["effort"] not in efforts:
        raise refused(409, "unsupported_effort", "This Effort is not offered. Choose one of the listed options.",
                      efforts=effort_options(efforts))
    # Reopening a prepared analysis is free; a new one counts once against the usage policy.
    existing = (context.folders.requests / f"{payload['source_id']}.{ra.PROMPT_VERSION}.{payload['effort']}").exists()
    reservation = None if existing else usage.reserve(context.accounts, identity.user_id, "preparation",
                                                      context.clock())
    try:
        verified, created = ra.prepare_for_user(payload["source_id"], payload["effort"], identity.user_id,
                                                context.folders, context.clock)
    except FlowRefused as exc:
        if reservation:
            usage.release(context.accounts, reservation, "the analysis was not prepared", context.clock())
        if str(exc) == ra.UNMARKED:
            raise refused(409, "source_unmarked", UNMARKED) from None
        raise refused(500, "internal_error", "The analysis could not be prepared. Nothing was sent.") from None
    except BaseException:
        if reservation:
            usage.release(context.accounts, reservation, "the analysis was not prepared", context.clock())
        raise
    if reservation and not created:  # Another request prepared it first.
        usage.release(context.accounts, reservation, "the analysis was already prepared", context.clock())
    return {"contract": CONTRACT, "created": created, "analysis": analysis_view(context, identity, verified)}, created


def _db_attempt(context: UserResearch, request_id: str) -> dict | None:
    return entitlements.attempt_record(context.accounts, request_id=request_id)


def _charge(attempt: dict | None, unsettled: str) -> dict | None:
    if attempt is None:
        return None
    resolution = attempt["resolution"]
    if resolution is None:
        return {"credits_reserved": attempt["credits"], "credits_charged": None, "credits_returned": None,
                "state": unsettled, "quota_day": attempt["quota_day"]}
    charged = resolution["credits_charged"]
    return {"credits_reserved": attempt["credits"], "credits_charged": charged,
            "credits_returned": attempt["credits"] - charged, "state": resolution["kind"],
            "quota_day": attempt["quota_day"]}


def user_result(view: dict) -> dict:
    """The user projection of a recorded research-result-view-0.1: the outcome and the research content only."""
    outcome = view["outcome"]
    return {"outcome": outcome, "note": NOTES[outcome], "recorded_at": view["provenance"]["received_at"],
            "analysis": view["analysis"] if outcome in CARRIES_ANALYSIS else None,
            "explanation": view["model_text"] if outcome == "declined" else None}


def credit_sentence(attempt: dict) -> str:
    """What happened to an attempt's credits, read only from its recorded resolution (never from whether a send
    timestamp exists). User-safe: no amounts of money, no account IDs."""
    resolution, reserved = attempt["resolution"], attempt["credits"]
    if resolution is None:
        return "Your credits stay reserved until an administrator reviews this run."
    by_admin = resolution["actor"] != entitlements.SYSTEM
    if resolution["kind"] == "returned":
        return (f"An administrator returned all {reserved} credits and the day's allowance." if by_admin
                else f"All {reserved} credits and the day's allowance were returned.")
    charged = resolution["credits_charged"]
    returned = f", and {reserved - charged} were returned" if charged < reserved else ""
    return f"{'An administrator settled it: ' if by_admin else ''}{charged} of the {reserved} reserved credits were " \
           f"charged{returned}."


def _state(context: UserResearch, verified: dict, attempt: dict | None) -> tuple[str, str, dict | None, dict | None]:
    """(state, detail, admin result view or None, charge) for one of the user's requests. Credit wording comes from the
    recorded resolution; "running" means a worker still holds the attempt's execution lock or it is younger than
    STALE_AFTER, and "unresolved" needs both a free lock and that age."""
    on_disk = ra.attempt_state(verified["request_id"], context.folders)
    if attempt is None:
        if on_disk["state"] == "none":
            return "prepared", DETAILS["prepared"], None, None
        return "unresolved", DETAILS["unresolved_unsent"], None, None  # Not reachable through any route.
    resolution, sent = attempt["resolution"], attempt["sent_at"] is not None
    money = credit_sentence(attempt)
    if resolution is not None and resolution["kind"] == "returned" and not sent:
        return "not_sent", f"{DETAILS['not_sent']} {money}", None, _charge(attempt, "returned")
    view = None
    if on_disk["state"] == "recorded":
        try:
            view = ra.result_view(verified, context.folders)
        except FlowRefused:
            view = None
    if view is not None and view["outcome"] in RECORDED:
        settled_normally = resolution is not None and resolution["actor"] == entitlements.SYSTEM
        return "recorded", DETAILS["recorded"] + ("" if settled_normally else f" {money}"), view, \
            _charge(attempt, "under_review")
    if on_disk["state"] == "recorded":
        return "failed", f"{DETAILS['failed']} {money}", None, _charge(attempt, "under_review")
    if resolution is None and (attempt_locks.active(context.accounts.lock_dir, attempt["attempt_id"])
                               or not entitlements.aged(attempt, context.clock())):
        return "running", DETAILS["running"], None, _charge(attempt, "held")
    return "unresolved", f"{DETAILS['unresolved_sent' if sent else 'unresolved_unsent']} {money}", None, \
        _charge(attempt, "under_review")


def _quote_view(quote: dict) -> dict:
    return {key: quote[key] for key in ("quote_id", "effort", "credits", "policy_version", "issued_at", "expires_at",
                                         "state")} | {"analysis_id": quote["request_id"]}


def _review_view(record: dict, names: dict[str, str], result: dict | None) -> dict:
    reviewer = record["reviewer"]["user_id"]
    return {"review_id": record["review_id"], "sequence": record["sequence"],
            "parent_review_id": record["parent_review_id"], "saved_at": record["saved_at"],
            "status": record["status"], "notes": record["notes"],
            "result_sha256": bound_fingerprint(record["binding"], result),
            "reviewer": {"user_id": reviewer, "display_name": names.get(reviewer, "Unknown account")}}


def analysis_view(context: UserResearch, identity: Identity, verified: dict) -> dict:
    request_id = verified["request_id"]
    attempt = _db_attempt(context, request_id)
    state, detail, view, charge = _state(context, verified, attempt)
    result = user_result(view) if view is not None else None
    quote = None
    if state == "prepared":
        latest = entitlements.latest_quote(context.accounts, identity.user_id, request_id, context.clock(), ra.MODEL)
        quote = _quote_view(latest) if latest else None
    reviews = []
    if result is not None:
        names = {user["user_id"]: user["display_name"] for user in acc.list_users(context.accounts)}
        try:
            reviews = [_review_view(record, names, result)
                       for record in ra.review_history(context.folders, request_id)]
        except FlowRefused:
            reviews = []
    return {"analysis_id": request_id, "effort": verified["effort"], "prepared_at": verified["manifest"]["prepared_at"],
            "source": source_view(verified["capture_id"], verified["record"]), "state": state, "state_detail": detail,
            "quote": quote, "charge": charge, "result": result,
            "result_sha256": result_fingerprint(result) if result is not None else None, "reviews": reviews,
            "retrospective": ra.RETROSPECTIVE, "baseline": ra.BASELINE}


def read_analysis(context: UserResearch, identity: Identity, analysis_id: str) -> dict:
    return {"contract": CONTRACT, "analysis": analysis_view(context, identity, _owned_request(context, identity,
                                                                                               analysis_id))}


def _summaries(context: UserResearch, identity: Identity) -> list[dict]:
    owned = set(acc.owned(context.accounts, "capture", identity.user_id))
    folder = context.folders.requests
    rows = []
    for path in sorted(folder.iterdir()) if folder.is_dir() else []:
        match = ra.REQUEST_ID_PATTERN.fullmatch(path.name)
        if not match or match.group(3) is None or match.group(1) not in owned:
            continue
        try:
            shown = analysis_view(context, identity, _owned_request(context, identity, path.name))
        except AccountsRefused:
            continue
        latest = shown["reviews"][-1]["status"] if shown["reviews"] else None
        rows.append({"analysis_id": shown["analysis_id"],
                     "source": {key: shown["source"][key] for key in ("source_id", "headline", "published_at")},
                     "effort": shown["effort"], "prepared_at": shown["prepared_at"], "state": shown["state"],
                     "outcome": shown["result"]["outcome"] if shown["result"] else None, "review_status": latest,
                     "credits_charged": shown["charge"]["credits_charged"] if shown["charge"] else None})
    return sorted(rows, key=lambda row: row["prepared_at"], reverse=True)


def list_analyses(context: UserResearch, identity: Identity) -> dict:
    return {"contract": CONTRACT, "analyses": _summaries(context, identity)}


def export(context: UserResearch, identity: Identity, analysis_id: str) -> dict:
    return {"contract": CONTRACT, "exported_at": acc.stamp(context.clock()),
            "analysis": analysis_view(context, identity, _owned_request(context, identity, analysis_id))}


# ---------------------------------------------------------------- quotes and runs

def _empty_body(body: bytes) -> None:
    try:
        payload = json.loads(body.decode("utf-8")) if body else None
    except (UnicodeDecodeError, ValueError):
        payload = None
    if payload != {}:
        raise refused(422, "invalid_request", "Send an empty JSON object.")


def quote(context: UserResearch, identity: Identity, analysis_id: str, body: bytes) -> dict:
    """A credit quote for one prepared analysis under the current policy. Nothing is reserved or sent."""
    _empty_body(body)
    verified = _owned_request(context, identity, analysis_id)
    if not sending_ready(context):
        raise refused(503, "sending_disabled", "Analyses cannot run on this server right now. Nothing was reserved.")
    if verified["unmarked"]:
        raise refused(409, "source_unmarked", UNMARKED)
    if _db_attempt(context, analysis_id) is not None or \
            ra.attempt_state(analysis_id, context.folders)["state"] != "none":
        raise refused(409, "already_attempted", "This analysis has already been run. It is never run twice.")
    estimate = ra.research_cost(verified["request_bytes"])
    try:
        issued = entitlements.issue_quote(
            context.accounts, user_id=identity.user_id, request_id=analysis_id,
            request_sha256=verified["request_sha256"], effort=verified["effort"], model=ra.MODEL,
            input_tokens_assumed=estimate["input_tokens_assumed"], max_tokens=verified["request"]["max_tokens"],
            planning_estimate_usd=estimate["estimated_real_run_if_output_reaches_max_usd"], moment=context.clock())
    except AccountsRefused as exc:
        if exc.code == "unsupported_effort":
            raise refused(409, "unsupported_effort", str(exc), efforts=effort_options(exc.extra["efforts"])) from None
        raise
    return {"contract": CONTRACT, "quote": _quote_view({**issued, "state": "active"}),
            "account": account_payload(context, identity)}


def _approval(body: bytes) -> dict:
    try:
        payload = strict_object(body, RUN_FIELDS, "approval")
    except FlowRefused:
        raise refused(422, "invalid_request", f"An approval has exactly {', '.join(RUN_FIELDS)}.") from None
    if payload["approve"] is not True:
        raise refused(422, "invalid_request", "approve must be true: an analysis runs only after you approve its "
                                              "credits.")
    if not isinstance(payload["quote_id"], str) or not isinstance(payload["effort"], str) or \
            isinstance(payload["credits"], bool) or not isinstance(payload["credits"], int):
        raise refused(422, "invalid_request", "quote_id and effort must be text and credits a whole number.")
    return payload


def run(context: UserResearch, identity: Identity, analysis_id: str, body: bytes) -> tuple[dict, bool]:
    """Run one prepared analysis on its approved quote: recheck, reserve durably, send once, record and settle.
    Returns (reply, duplicate). A repeat of an approval that already reserved changes nothing."""
    approval = _approval(body)
    verified = _owned_request(context, identity, analysis_id)
    made = entitlements.attempt_record(context.accounts, request_id=analysis_id)
    if made is not None and made["quote_id"] == approval["quote_id"]:
        return _run_reply(context, identity, analysis_id, duplicate=True), True
    try:  # Only the server's sending configuration is "sending disabled".
        api_key = ra.paid_key(context.sender)
    except FlowRefused:
        raise refused(503, "sending_disabled", "Analyses cannot run on this server right now. Nothing was reserved.") \
            from None
    try:  # The saved request itself: verified again, never regenerated.
        verified = ra.approved_for_account(analysis_id, verified["request_sha256"], context.folders)
        ra.credential_free(verified, api_key)
    except FlowRefused as exc:
        if exc.status == 404:
            raise refused(404, "not_found", NOT_FOUND) from None
        if str(exc) == ra.UNMARKED:
            raise refused(409, "source_unmarked", UNMARKED) from None
        raise refused(500, "internal_error", "This analysis's saved request could not be verified for sending. Nothing "
                                             "was reserved or sent; an administrator can check it.") from None
    if made is not None or ra.attempt_state(analysis_id, context.folders)["state"] != "none":
        raise refused(409, "already_attempted", "This analysis has already been run. It is never run twice. Nothing new "
                                                "was reserved.")
    attempt, duplicate = entitlements.reserve(
        context.accounts, user_id=identity.user_id, quote_id=approval["quote_id"], request_id=analysis_id,
        request_sha256=verified["request_sha256"], model=ra.MODEL, effort=approval["effort"],
        credits=approval["credits"], moment=context.clock())
    if duplicate:
        return _run_reply(context, identity, analysis_id, duplicate=True), True
    attempt_id = attempt["attempt_id"]
    estimate = ra.research_cost(verified["request_bytes"])["estimated_real_run_if_output_reaches_max_usd"]
    account = {key: attempt[key] for key in ("attempt_id", "user_id", "quote_id", "credits", "quota_day")}
    try:
        # The attempt's execution lock, held from before its send is recorded until it is settled: while it is held, no
        # administrator can resolve the attempt, however old it is; a process that ends releases it.
        with attempt_locks.hold(context.accounts.lock_dir, attempt_id, wait=attempt_locks.WORKER_WAIT):
            try:
                ra.send_once(verified, context.sender, api_key, context.folders, context.clock, estimate,
                             before_send=lambda: entitlements.mark_sent(context.accounts, attempt_id, context.clock()),
                             account=account)
            except Exception as exc:  # What the store shows as sent stays held; what it shows as unsent is returned.
                _after_interruption(context, attempt_id)
                raise _stopped(context, attempt_id, exc) from None
            _settle(context, verified, attempt_id)
    except attempt_locks.Busy:  # An administrator is resolving it at this moment; this worker sends nothing.
        raise _stopped(context, attempt_id, None) from None
    return _run_reply(context, identity, analysis_id, duplicate=False), False


def _stopped(context: UserResearch, attempt_id: str, cause: Exception | None) -> AccountsRefused:
    """The refusal for a run that stopped after its reservation, saying what the records now hold."""
    record = entitlements.attempt_record(context.accounts, attempt_id=attempt_id)
    sent = record["sent_at"] is not None
    what = "The request was sent, but its outcome was not recorded." if sent else "Nothing was sent."
    if not sent and isinstance(cause, FlowRefused) and cause.status < 500:  # An attempt existed, or it was resolved.
        return refused(409, "already_attempted", f"This analysis cannot run again. {what} {credit_sentence(record)}")
    return refused(500, "internal_error", f"The run stopped. {what} {credit_sentence(record)} Read the analysis "
                                          "again; nothing is retried.")


def _after_interruption(context: UserResearch, attempt_id: str) -> None:
    """After a run stopped, by the worker that still holds the attempt's execution lock: if the store records no send,
    nothing was sent (the send is recorded before the transport is called), so the credits and the daily slot are
    returned once, unless the attempt was already resolved; otherwise the hold stays for an administrator."""
    record = entitlements.attempt_record(context.accounts, attempt_id=attempt_id)
    if record is not None and record["sent_at"] is None:
        entitlements.resolve(context.accounts, attempt_id, "returned", 0, entitlements.SYSTEM,
                             "the run stopped before anything was sent", context.clock(), unsent_only=True)


def _settle(context: UserResearch, verified: dict, attempt_id: str) -> None:
    """A recorded response settles at the quoted credits; a provider or transport failure stays held for review."""
    on_disk = ra.attempt_state(verified["request_id"], context.folders)
    if on_disk["state"] != "recorded":
        return
    try:
        view = ra.result_view(verified, context.folders)
    except FlowRefused:
        entitlements.record_outcome(context.accounts, attempt_id, "unverified", context.clock())
        return
    entitlements.record_outcome(context.accounts, attempt_id, view["recorded_outcome"], context.clock())
    if view["recorded_outcome"] in TECHNICAL:
        return
    record = entitlements.attempt_record(context.accounts, attempt_id=attempt_id)
    entitlements.resolve(context.accounts, attempt_id, "charged", record["credits"], entitlements.SYSTEM,
                         f"a response was recorded ({view['recorded_outcome']}); settlement policy: quoted",
                         context.clock())


def _run_reply(context: UserResearch, identity: Identity, analysis_id: str, duplicate: bool) -> dict:
    verified = _owned_request(context, identity, analysis_id)
    return {"contract": CONTRACT, "duplicate": duplicate, "analysis": analysis_view(context, identity, verified),
            "account": account_payload(context, identity)}


# ---------------------------------------------------------------- reviews

def save_review(context: UserResearch, identity: Identity, analysis_id: str, body: bytes) -> dict:
    """Append the user's review version (research-review-0.2), bound to the result they loaded."""
    if len(body) > ra.MAX_REVIEW_BODY:
        raise refused(413, "payload_too_large", "The review is too large.")
    try:
        payload = strict_object(body, REVIEW_FIELDS, "review", limit=ra.MAX_REVIEW_BODY)
    except FlowRefused as exc:
        if exc.status == 413:
            raise refused(413, "payload_too_large", "The review is too large.") from None
        raise refused(422, "invalid_review", f"A review has exactly {', '.join(REVIEW_FIELDS)}.") from None
    status, notes, parent = payload["status"], payload["notes"], payload["parent_review_id"]
    if status is not None and status not in ra.STATUSES:
        raise refused(422, "invalid_review", "status must be null, needs_revision or human_reviewed.")
    problem = ra.notes_problem(notes)
    if problem:
        raise refused(422, "invalid_review", f"The review was not saved: {problem}. Your notes are kept as typed.")
    if status is None and not notes.strip():
        raise refused(422, "invalid_review", "A review needs notes or a status.")
    if parent is not None and not (isinstance(parent, str) and REVIEW_ID.fullmatch(parent)):
        raise refused(422, "invalid_review", "parent_review_id must be null or a review ID.")
    verified = _owned_request(context, identity, analysis_id)
    shown = analysis_view(context, identity, verified)
    if shown["result"] is None:
        raise refused(409, "no_result", "There is no recorded result to review.")
    # A page loaded before user-result-2 sends the same content's user-result-1 fingerprint: still the same result.
    if payload["result_sha256"] not in (shown["result_sha256"], legacy_fingerprint(shown["result"])):
        raise refused(409, "result_changed", "The result changed since you loaded it. Reload before saving.")
    records = ra.review_history(context.folders, analysis_id)
    latest = records[-1] if records else None
    if parent != (latest["review_id"] if latest else None):
        raise refused(409, "review_conflict", "Another review version was saved since you loaded this one. Reload to "
                                              "see it.")
    if latest is not None and (latest["status"], latest["notes"], bound_fingerprint(latest["binding"], shown["result"])) == \
            (status, notes, shown["result_sha256"]):
        raise refused(422, "invalid_review", "Nothing changed since the last saved version.")
    view = ra.result_view(verified, context.folders)
    record = {"record_version": ra.USER_RECORD_VERSION, "request_id": analysis_id, "sequence": len(records) + 1,
              "parent_review_id": parent, "saved_at": acc.stamp(context.clock()),
              "reviewer": {"user_id": identity.user_id, "role": identity.role}, "status": status, "notes": notes,
              "binding": {"user_result_sha256": shown["result_sha256"], "user_result_binding": RESULT_BINDING,
                          "result_view_sha256": ra.fingerprint(view),
                          "request_sha256": verified["request_sha256"],
                          "response_sha256": view["provenance"]["response_sha256"],
                          "result_view_version": ra.VIEW_VERSION, "outcome": view["outcome"], "mode": view["mode"]}}
    record["review_id"] = ra.review_id(record)
    data = json.dumps(record, ensure_ascii=False, sort_keys=True, indent=1).encode("utf-8") + b"\n"
    try:
        write_exclusively(context.folders.reviews / analysis_id, f"{record['sequence']:06d}.json", data)
    except ReviewRefused:
        raise refused(409, "review_conflict", "Another review version was saved at the same time. Reload to see it.") \
            from None
    analysis = analysis_view(context, identity, verified)
    return {"contract": CONTRACT, "review": analysis["reviews"][-1], "analysis": analysis}


MAX_BODY = MAX_FORM_BYTES
# A source's text is limited in characters, in any script, and UTF-8 takes one to four bytes for each. The form limit
# fits that many one-byte characters with any headline and address (each has its own character limit); three more
# bytes for each character fit the same text in any script.
MAX_SOURCE_BODY = MAX_FORM_BYTES + 3 * MAX_SOURCE_CHARS
