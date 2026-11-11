"""Event processing history (event-history-0.1): what was done with one event, as a compact list of dated steps read
from the records each step already keeps. Reads only: nothing is fetched, sent, written, repaired or approved, and no
model is called.

Steps and the records they come from:

- source: the entry's archived versions (inbox_archive) and the retrieval records that listed each version
  (inbox_acquisitions), or an imported snapshot record's imports (inbox_imports); for a capture, its own record
  (event_intake) and the origin it recorded (event_links);
- triage: every saved headline-triage request that carried the entry, at any version, as an entry to classify or only
  as comparison context (triage_flow), with each attempt's recorded outcome and, when a response was accepted, the
  entry's result;
- analysis: the captures that recorded the entry as their origin, each with its one attempt (analysis_flow), and the
  evidence-first research requests prepared from them with each one's attempt (research_analysis). A prepared research
  request is listed as prepared and unsent, never as an analysis;
- review: the human-review versions of each published draft (human_review), current only when saved against the view
  served now (analysis_library), and the review versions of each research result (research_analysis), current only
  when saved against the result view built now;
- use: hypotheses frozen from those drafts, from verified freeze records in the research store (assessment_records).
  Research intake is closed (INCLUSION.md), so a freeze is a prospective showcase, never research use.

Joins are by stable IDs and explicit links only. Nothing is matched by headline, date or similarity, so a capture made
without a recorded origin is never attributed to an entry; how many there are is stated as a limitation. A keyword match
(Related Cases), an opened page or a related-research link is not a processing step and is never listed as one. "Not
processed" is a valid state, not a failure.

Costs keep three things apart: the planning estimate made before sending (an upper bound at max_tokens, for the whole
request), the cost derived from the token usage the provider reported, and verified billing, which no local record
holds (the Console is authoritative). Missing information stays unknown, and an uncertain send may have been billed.
"""
from pathlib import Path
from urllib.parse import quote

from . import (analysis_flow, analysis_library, assessment_records, event_inbox, event_intake, event_links,
               human_review, inbox_acquisitions, inbox_archive, inbox_imports, research_analysis, triage_flow)
from .freeze_origins import Folders as StoreFolders
from .headline_triage import entry_result, fingerprint, snapshot_item

HISTORY_VERSION = "event-history-0.1"
INDEX_VERSION = "event-processing-index-0.1"
STEPS = ("source", "triage", "analysis", "review", "use")
BILLING = ("No local record verifies billing: an estimate is a planning upper bound made before sending, and a "
           "usage-derived cost comes from the token counts the provider reported. The Console is authoritative.")
NOT_PROCESSING = ("Keyword matches (Related Cases), related-research links and opening a page are not processing "
                  "steps and are not listed here.")
RESEARCH_CLOSED = ("Research intake is closed, so no event is used in research scores; a frozen hypothesis is a "
                   "prospective showcase.")
TRIAGE_OUTCOMES = {"triaged": ("accepted", "done", "accepted"),
                   "not_accepted": ("not_accepted", "warn", "not accepted: the response failed validation"),
                   "provider_error": ("provider_error", "warn", "failed: the provider returned an error"),
                   "no_reply": ("no_reply", "warn", "no reply"),
                   "credential_echo": ("credential_echo", "warn", "discarded: the reply echoed the credential")}
DRAFT_OUTCOMES = {"draft": "a draft", "no_draft": "no draft (the model declined)",
                  "invalid_response": "an invalid response", "technical_failure": "a technical failure"}
REVIEW_STATUS = {"human_reviewed": "Human reviewed", "needs_revision": "Needs revision", None: "Notes only"}
RESEARCH_OUTCOMES = {"analysis": ("done", "an analysis"),
                     "no_additional_finding": ("done", "no additional finding (an acceptable result)"),
                     "declined": ("info", "no analysis: the model declined"),
                     "incomplete": ("warn", "no analysis: the response stopped early"),
                     "invalid": ("warn", "an invalid response"),
                     "technical_failure": ("warn", "a technical failure")}


def version_item(item_id: str, version: dict) -> dict:
    """An archived entry version with its source's fixed fields, as the inbox view would show it."""
    key = item_id.split(":", 1)[0]
    if key in inbox_imports.SOURCES:
        return {"id": item_id, **{field: version[field] for field in inbox_archive.CONTENT_FIELDS},
                **inbox_imports.fixed_fields()}
    source = event_inbox.SOURCES[key]
    return {"id": item_id, **{field: version[field] for field in inbox_archive.CONTENT_FIELDS},
            "source": source.key, "publisher": source.publisher, "category": source.category, "kind": source.kind,
            "attribution": source.attribution}


def _row(step: str, at: str | None, state: str, tone: str, label: str, detail: str | None = None, *,
         version: int | None = None, href: str | None = None, cost: dict | None = None, **extra) -> dict:
    return {"step": step, "at": at, "state": state, "tone": tone, "label": label, "detail": detail, "version": version,
            "href": href, "cost": cost, **extra}


def _usd(value: object) -> float | None:
    return round(float(value), 6) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


# ---------------------------------------------------------------- source

def _source_rows(item_id: str, versions: list[dict], current_sha: str | None, inbox: Path) -> tuple[list, list, int]:
    """One row per archived version: when it was first and last seen, its feed date and texts, and the recorded
    retrievals that listed it. Returns (rows, limitations, retrieval count)."""
    key = item_id.split(":", 1)[0]
    if key in inbox_imports.SOURCES:
        rows = [_row("source", version["first_seen_at"], "imported", "info", f"Imported, version {number}",
                     f"“{version['title']}”, from a retained snapshot (not a live feed). Listing timestamp "
                     f"{version['feed_timestamp']['raw'] or 'none'}, not the release's dateline.", version=number,
                     current=version["content_sha256"] == current_sha)
                for number, version in enumerate(versions, start=1)]
        return rows, [], 0
    source = event_inbox.SOURCES[key]
    records, bad = inbox_acquisitions.records(inbox, key, source.feed_url)
    first_record = records[0]["started_at"] if records else None
    limits = [problem["problem"] for problem in bad]
    rows, early, total = [], [], set()
    for number, version in enumerate(versions, start=1):
        listed = [record for record in records if any(
            row["id"] == item_id and row["content_sha256"] == version["content_sha256"] for row in record["items"])]
        total.update(record["number"] for record in listed)
        kept = sum(1 for record in listed if record["body"].get("kept"))
        stamp = version["feed_timestamp"]
        texts = inbox_acquisitions.text_parts(version)
        when = (f" = {stamp['instant_utc']}" if stamp["instant_utc"] else "") + \
            (f". {stamp['problem'].rstrip('.')}" if stamp["problem"] else "")
        before = first_record is None or version["first_seen_at"] < first_record
        if before:
            early.append(number)
        retrievals = (f"Listed by {len(listed)} recorded {'retrieval' if len(listed) == 1 else 'retrievals'}"
                      f"{f', {kept} with the response kept privately' if kept else ''}" if listed else
                      "Listed by no recorded retrieval")
        rows.append(_row(
            "source", version["first_seen_at"], "retrieved", "info",
            f"Version {number} first retrieved" if len(versions) > 1 else "First retrieved",
            f"“{version['title']}”. Feed timestamp {stamp['raw'] or 'none'} ({stamp['origin']}){when}. Headline "
            f"{'shortened' if texts['title'] == 'shortened' else 'as supplied'}; "
            f"{EXCERPT_WORDS[texts['excerpt']]}. Seen in the feed from {version['first_seen_at']} to "
            f"{version['last_seen_at']}. {retrievals}"
            f"{' (and in retrievals made before records were kept)' if before else ''}.",
            version=number, current=version["content_sha256"] == current_sha, retrievals=len(listed),
            kept_responses=kept))
    if early:
        limits.append(f"Version{'s' if len(early) > 1 else ''} {', '.join(map(str, early))} of this entry "
                      f"{'were' if len(early) > 1 else 'was'} first retrieved before retrieval records were kept"
                      f"{f' (the first is from {first_record})' if first_record else ''}: those responses were not "
                      "kept, so what the publisher sent then is known only from the parsed entry.")
    return rows, limits, len(total)


EXCERPT_WORDS = {"none": "the feed gives no excerpt", "repeats_title": "the feed's excerpt only repeats the headline",
                 "as_supplied": "a feed excerpt as supplied (not the article)",
                 "shortened": "a feed excerpt shortened here at 1,200 characters (not the article)"}


# ---------------------------------------------------------------- triage

def _triage_cost(mode: str, attempt: dict, estimate: float | None, size: str) -> dict:
    if mode == "simulated":
        return {"estimate_usd": None, "usage_usd": 0, "billing": None, "basis": "Local simulation: no provider was "
                                                                               "contacted and nothing was billed."}
    usage = _usd((attempt.get("cost") or {}).get("usd")) if attempt["state"] == "complete" else None
    return {"estimate_usd": estimate, "usage_usd": usage, "billing": "not_verified",
            "basis": f"For the whole request ({size}). " + (
                "Usage-derived from the reported token counts." if usage is not None else
                "No usage was reported, so the cost is unknown.")}


def _triage_rows(item_id: str, prints: dict[str, int], triage_dir: Path) -> tuple[list, list]:
    good, bad = triage_flow.records(triage_dir)
    rows = []
    for record in good:
        entry = next((entry for entry in record["entries"] if entry["id"] == item_id), None)
        role = "entry" if entry else "context"
        entry = entry or next((entry for entry in record["context"] if entry["id"] == item_id), None)
        if entry is None:
            continue
        version = prints.get(fingerprint(entry))
        size = f"{len(record['entries'])} entries, {len(record['context'])} as context"
        estimate = _usd((record["prepared"].get("cost_estimate") or {}).get("estimated_paid_if_output_reaches_max_usd"))
        about = (f"{'Version ' + str(version) if version else 'A version no longer held'} of this entry, "
                 f"{'to classify' if role == 'entry' else 'as comparison context only (no result requested for it)'}; "
                 f"request {record['triage_id']} ({size}).")
        attempts = [attempt for mode in triage_flow.MODES for attempt in triage_flow.read_attempts(record, mode)]
        if not attempts:
            rows.append(_row("triage", record["prepared"]["prepared_at"], "prepared", "info",
                             "Triage request prepared; nothing was sent", about, version=version,
                             triage_id=record["triage_id"], role=role,
                             cost={"estimate_usd": estimate, "usage_usd": None, "billing": None,
                                   "basis": f"The planning estimate if sent paid, for the whole request ({size})."}))
        for attempt in attempts:
            rows.append(_triage_attempt(record, attempt, item_id, role, entry, version, about, estimate, size))
    return rows, [f"Saved triage request {row['triage_id']} cannot be read, so whether it carried this entry is "
                  "unknown." for row in bad]


def _triage_attempt(record: dict, attempt: dict, item_id: str, role: str, entry: dict, version: int | None,
                    about: str, estimate: float | None, size: str) -> dict:
    mode, paid = attempt["mode"], attempt["mode"] == "paid"
    who = "Model triage" if paid else "Simulated triage (no model read the entry)"
    at = attempt.get("received_at") or attempt.get("sent_at") or record["prepared"]["prepared_at"]
    result = None
    if attempt["state"] == "complete":
        state, tone, words = TRIAGE_OUTCOMES.get(attempt["outcome"], ("failed", "warn", attempt["outcome"]))
        if attempt["outcome"] == "no_reply" and paid:
            state, words = "uncertain", "no reply: the request may have been received and billed"
        if triage_flow.revalidated(attempt):
            state, tone, words = "accepted_on_recheck", "done", "accepted on a local re-check (nothing re-sent)"
        if triage_flow.usable(attempt) and role == "entry":
            result = entry_result(triage_flow.parsed_result(attempt)["results"][item_id], entry)
        failed = attempt.get("message") and not triage_flow.usable(attempt)
        detail = about + (f" {attempt['message']}" if failed else "")
    elif attempt["state"] == "incomplete":
        sent = attempt.get("sent")
        state, tone = ("uncertain", "warn") if sent and paid else ("interrupted", "warn")
        words = ("sent, with no response recorded: it may have been received and billed" if sent and paid else
                 "reserved, with no response recorded")
        detail = f"{about} {attempt['detail']}"
    else:
        state, tone, words, detail = "invalid", "warn", "recorded, but its files do not verify", \
            f"{about} {attempt.get('detail', '')}".strip()
    if result:
        detail = (f"{detail} Result: {result['category']}"
                  f"{'; ' + result['event_type'] if result.get('event_type') else ''}. {result['summary']}")
    return _row("triage", at, state, tone, f"{who}: {words}", detail, version=version, triage_id=record["triage_id"],
                role=role, mode=mode, attempt=attempt["attempt"], result=result,
                href=f"/api/triage/{record['triage_id']}", cost=_triage_cost(mode, attempt, estimate, size))


# ---------------------------------------------------------------- analysis, review and use

def _manifest(attempts: Path, capture_id: str) -> dict:
    try:
        return analysis_flow._manifest(attempts / capture_id)
    except (OSError, ValueError):
        return {}


def _analysis_rows(capture_id: str, folders, overview: str, version: int | None) -> tuple[list, dict | None]:
    """A capture and its one attempt; returns (rows, the listed analysis entry or None)."""
    href = f"/events/capture/{capture_id}"
    try:
        record = event_intake.verified(folders.intake, capture_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        return [_row("analysis", None, "unreadable", "warn", "Saved event cannot be read",
                     f"Capture {capture_id}: {exc}. It was left unchanged.", href=href)], None
    origin = f"from version {version} of the Inbox entry" if version else "from the Inbox entry"
    rows = [_row("analysis", record["times"]["captured_at"], "captured", "info", "Saved event captured",
                 f"“{record['event']['headline']}”, {origin}; request SHA-256 {record['request']['sha256'][:12]}…. "
                 "Capturing sends nothing.", href=href, capture_id=capture_id)]
    try:
        state = analysis_flow.attempt_state(capture_id, folders.intake, folders.attempts, folders.drafts,
                                            folders.published)
    except analysis_flow.FlowRefused as exc:
        return rows + [_row("analysis", None, "unreadable", "warn", "Attempt cannot be read", str(exc),
                            href=href)], None
    mode, paid = state.get("mode"), state.get("mode") == "paid"
    if state["state"] == "none":
        rows[0]["detail"] += " No attempt is recorded: nothing was sent."
        return rows, None
    if state["state"] == "incomplete":
        uncertain = paid and state.get("sent")
        rows.append(_row("analysis", state.get("sent_at"), "uncertain" if uncertain else "interrupted", "warn",
                         "Paid draft request sent; no response recorded" if uncertain else
                         "Draft attempt did not finish",
                         state["detail"], href=href, capture_id=capture_id, mode=mode,
                         cost={"estimate_usd": None, "usage_usd": None, "billing": "not_verified" if paid else None,
                               "basis": "The request may have been received and billed; its usage is unknown."
                               if uncertain else "Nothing is known to have been sent."}))
        return rows, None
    manifest = _manifest(folders.attempts, capture_id)
    usage = manifest.get("estimated_cost") if isinstance(manifest.get("estimated_cost"), dict) else {}
    cost = {"estimate_usd": _usd(manifest.get("planning_estimate_usd")),
            "usage_usd": 0 if mode == "mock" else _usd(usage.get("usd")),
            "billing": "not_verified" if paid else None,
            "basis": "Local mock: no provider was contacted and nothing was billed." if mode == "mock" else
                     "Usage-derived from the reported token counts." if _usd(usage.get("usd")) is not None else
                     "No usage was reported, so the cost is unknown."}
    outcome = DRAFT_OUTCOMES.get(state.get("outcome"), state.get("outcome") or "an unknown outcome")
    who = "Paid draft request" if paid else "Local mock draft (no provider contacted)"
    if state["state"] == "invalid":
        rows.append(_row("analysis", manifest.get("received_at"), "invalid", "warn",
                         f"{who}: recorded, does not verify", state["detail"], href=href, capture_id=capture_id,
                         mode=mode, cost=cost))
        return rows, None
    published = state["state"] == "ready"
    rows.append(_row("analysis", manifest.get("received_at"), state.get("outcome") or "recorded",
                     "done" if published else "info", f"{who}: {outcome}",
                     ("Published for human review." if published else state["detail"]) +
                     (f" Provider request ID {manifest['request_id']}." if manifest.get("request_id") else ""),
                     href=f"/?draft={state['draft_id']}&from={quote(overview, safe='')}" if published else href,
                     capture_id=capture_id, mode=mode, draft_id=state.get("draft_id"), cost=cost))
    if not published:
        return rows, None
    found = analysis_library.capture_analysis(capture_id, folders.intake, folders.attempts, folders.drafts,
                                              folders.published, folders.reviews)
    return rows, found.get("entry")


def _review_rows(entry: dict, reviews: Path, overview: str) -> tuple[list, list]:
    draft_id = entry["draft_id"]
    href = f"/?draft={draft_id}&from={quote(overview, safe='')}"
    try:
        versions = human_review.history(reviews, draft_id)
    except (human_review.ReviewRefused, OSError) as exc:
        return [_row("review", None, "invalid", "warn", "Review history does not verify",
                     f"Draft {draft_id[:12]}…: {exc}. It is not read as unreviewed.", href=href)], []
    rows = []
    for record in versions:
        binding = record.get("binding") if isinstance(record.get("binding"), dict) else {}
        current = binding.get("draft_view_sha256") == entry["draft_view_sha256"]
        corrections = record.get("corrections") if isinstance(record.get("corrections"), dict) else {}
        legs = corrections.get("legs") if isinstance(corrections.get("legs"), dict) else {}
        corrected = (corrections.get("summary") is not None) + sum(len(fields) for fields in legs.values()
                                                                    if isinstance(fields, dict))
        status = record.get("status")
        rows.append(_row("review", record.get("saved_at"), status or "notes", "done" if current else "info",
                         f"Human review version {record.get('sequence')}: {REVIEW_STATUS.get(status, status)}",
                         ("Saved against the draft view served now" if current else
                          "Saved against an earlier view of this draft, so it is not the current judgment") +
                         f"; {corrected} corrected {'field' if corrected == 1 else 'fields'}. A status records a "
                         "person's judgment; it does not verify the reasoning.", href=href, draft_id=draft_id,
                         current=current))
    return rows, []


def _research_rows(capture_id: str, folders) -> tuple[list, list]:
    """The evidence-first research requests prepared from one capture, each attempt's outcome and each review
    version. A prepared request is listed as prepared and unsent; only a recorded response is an outcome."""
    if folders.research is None:
        return [], []
    href = f"/events/capture/{capture_id}/research"
    try:
        found = research_analysis.requests_for(capture_id, research_analysis.Folders(folders.research, folders.intake,
                                                                                     folders.links))
    except OSError as exc:
        return [], [f"The research-analysis records of capture {capture_id} could not be read "
                    f"({type(exc).__name__}), so its research requests are unknown."]
    rows = []
    for item in found:
        names = {"kind": "research", "capture_id": capture_id, "request_id": item["request_id"]}
        if item["state"] != "verified":
            rows.append(_row("analysis", None, "unreadable", "warn", "Research request does not verify",
                             f"{item['problem']}.", href=href, **names))
            continue
        attempt, result = item["attempt"], item["result"]
        prepared = _row("analysis", item["prepared_at"], "prepared", "info", "Research analysis request prepared",
                        f"Evidence-first request SHA-256 {item['request_sha256'][:12]}… ({item['prompt_version']}). "
                        "Preparing sends nothing, and a prepared request is not an analysis.", href=href,
                        cost={"estimate_usd": _usd(item["planning_estimate_usd"]), "usage_usd": None, "billing": None,
                              "basis": "A planning estimate for one paid send; nothing has been sent."}, **names)
        rows.append(prepared)
        mode, paid = attempt.get("mode"), attempt.get("mode") == "paid"
        if attempt["state"] == "none":
            prepared["detail"] += " No attempt is recorded: nothing was sent."
            continue
        prepared["cost"] = None  # The attempt's own row carries the cost.
        if attempt["state"] in ("incomplete", "invalid") or result is None:
            uncertain = paid and attempt.get("sent") and attempt["state"] == "incomplete"
            rows.append(_row("analysis", attempt.get("sent_at"), "uncertain" if uncertain else attempt["state"],
                             "warn", "Paid research request sent; no response recorded" if uncertain else
                             "Research attempt did not finish" if attempt["state"] == "incomplete" else
                             "Research attempt recorded, does not verify", attempt["detail"], href=href, mode=mode,
                             cost={"estimate_usd": None, "usage_usd": None, "billing": "not_verified" if paid else None,
                                   "basis": "The request may have been received and billed; its usage is unknown."
                                   if uncertain else "Nothing is known to have been billed."}, **names))
            continue
        tone, words = RESEARCH_OUTCOMES[result["outcome"]]
        unknown = result["recorded_outcome"] == "transport error"
        usage = _usd(result["usage_cost_usd"])
        cost = {"estimate_usd": _usd(result["planning_estimate_usd"]),
                "usage_usd": 0 if mode == "mock" else usage,
                "billing": "not_verified" if paid else None,
                "basis": "Local mock: no provider was contacted and nothing was billed." if mode == "mock" else
                         "Usage-derived from the reported token counts." if usage is not None else
                         "No usage was reported, so the cost is unknown."}
        who = "Paid research request" if paid else "Local mock research result (synthetic; no provider contacted)"
        detail = (f"{result['problem']}. " if result["problem"] else "") + \
            (f"Provider request ID {result['provider_request_id']}. " if result["provider_request_id"] else "") + \
            "Not frozen or evaluated."
        rows.append(_row("analysis", result["received_at"], "uncertain" if unknown else result["outcome"], tone,
                         f"{who}: {words}", detail, href=href, mode=mode, result=True, cost=cost, **names))
        reviews = item["reviews"]
        if reviews["state"] != "verified":
            rows.append(_row("review", None, "invalid", "warn", "Research review history does not verify",
                             f"{reviews['problem']}. It is not read as unreviewed.", href=href, **names))
            continue
        for record in reviews["records"]:
            binding = record.get("binding") if isinstance(record.get("binding"), dict) else {}
            current = binding.get("result_view_sha256") == result["result_view_sha256"]
            status = record.get("status")
            rows.append(_row("review", record.get("saved_at"), status or "notes", "done" if current else "info",
                             f"Research review version {record.get('sequence')}: {REVIEW_STATUS.get(status, status)}",
                             ("Saved against the research result built now" if current else
                              "Saved against an earlier result view, so it is not the current judgment") +
                             ". A status records a person's judgment; it does not verify the analysis.", href=href,
                             current=current, **names))
    return rows, []


def _use_rows(captures: set[str], store: Path | None) -> tuple[list, list]:
    if store is None:
        return [], ["This server was started without a research store, so frozen hypotheses were not checked."]
    try:
        found = assessment_records.draft_links(StoreFolders(store=store))
    except Exception as exc:  # A store that cannot be read is a stated gap, never a crash of the overview.
        return [], [f"The research store could not be read ({type(exc).__name__}), so frozen hypotheses are unknown."]
    rows = [_row("use", link["frozen_at"], "frozen", "done", "Frozen as a hypothesis (prospective showcase)",
                 f"Hypothesis {link['hypothesis_id'][:12]}… from draft {link['draft_id'][:12]}… of this saved event, "
                 f"with the review in force at freeze. {RESEARCH_CLOSED}", href=f"/hypotheses/{link['hypothesis_id']}",
                 hypothesis_id=link["hypothesis_id"], capture_id=link["capture_id"])
            for link in found["links"] if link["capture_id"] in captures]
    return rows, [problem["problem"] for problem in found["problems"]]


def _unlinked_captures(intake: Path, links: Path) -> int:
    """Verified captures with no recorded Inbox origin: none of them is ever attributed to an entry."""
    return sum(1 for row in event_intake.listing(intake) if not row["state"].startswith("refused") and
               not event_links.path_for(links, row["capture_id"]).exists())


# ---------------------------------------------------------------- the history

def _assemble(rows: list[dict], limits: list[str], retrievals: int, versions: int) -> dict:
    by_step = {step: [row for row in rows if row["step"] == step] for step in STEPS}
    triage = by_step["triage"]
    summary = {"retrievals": retrievals, "versions": versions,
               "model_triage": sum(1 for row in triage if row.get("mode") == "paid" and row["tone"] == "done"
                                   and row.get("role") == "entry"),
               "simulated_triage": sum(1 for row in triage if row.get("mode") == "simulated" and row["tone"] == "done"
                                       and row.get("role") == "entry"),
               "triage_requests": len({row["triage_id"] for row in triage if row.get("triage_id")}),
               "captures": sum(1 for row in by_step["analysis"] if row["state"] == "captured"),
               "drafts": sum(1 for row in by_step["analysis"] if row.get("draft_id")),
               "reviews": sum(1 for row in by_step["review"] if row.get("kind") != "research"),
               "research_requests": sum(1 for row in by_step["analysis"] if row.get("kind") == "research"
                                        and row["state"] == "prepared"),
               "research_results": sum(1 for row in by_step["analysis"] if row.get("result")),
               "research_reviews": sum(1 for row in by_step["review"] if row.get("kind") == "research"),
               "frozen": len(by_step["use"]),
               "uncertain": sum(1 for row in rows if row["state"] == "uncertain"),
               "failed": sum(1 for row in rows if row["tone"] == "warn" and row["state"] != "uncertain")}
    processed = summary["captures"] or any(row["state"] not in ("prepared", "not_offered") for row in triage)
    state = "needs_attention" if summary["uncertain"] or summary["failed"] else \
        "processed" if processed else "not_processed"
    for step in STEPS:
        by_step[step].sort(key=lambda row: (row["at"] is None, row["at"] or ""))
    return {"history_version": HISTORY_VERSION, "provider_called": False, "state": state, "summary": summary,
            "steps": [{"step": step, "rows": by_step[step]} for step in STEPS],
            "limitations": limits + [NOT_PROCESSING, BILLING]}


def inbox_history(item_id: str, item: dict | None, versions: list[dict], folders, store: Path | None) -> dict:
    """The processing history of one Inbox entry, every version included. Reads only."""
    overview = f"/events/inbox/{item_id}"
    current = inbox_archive.content_sha256(item) if item is not None else None
    rows, limits, retrievals = _source_rows(item_id, versions, current, folders.inbox)
    prints = {fingerprint(snapshot_item(version_item(item_id, version))): number
              for number, version in enumerate(versions, start=1)}
    if item is not None and item["source"] in inbox_imports.SOURCES:
        rows.append(_row("triage", None, "not_offered", "info", "Headline triage is not offered for imported records"))
    else:
        found, problems = _triage_rows(item_id, prints, folders.triage)
        rows += found
        limits += problems
    captures = set()
    for link in event_links.captures_from(folders.links, item_id):
        origin = event_links.read_origin(folders.links, link["capture_id"], folders.intake, folders.inbox)
        if origin["state"] != "verified":
            limits.append(origin["problem"] or f"The origin record of capture {link['capture_id']} cannot be read.")
            continue
        captures.add(link["capture_id"])
        version = origin["link"]["inbox"]["version"]
        found, entry = _analysis_rows(link["capture_id"], folders, overview, version)
        rows += found
        if entry:
            rows += _review_rows(entry, folders.reviews, overview)[0]
        research, problems = _research_rows(link["capture_id"], folders)
        rows += research
        limits += problems
    unreadable = event_links.unreadable_links(folders.links)
    if unreadable:
        limits.append(f"{len(unreadable)} origin {'record cannot' if len(unreadable) == 1 else 'records cannot'} be "
                      "read, so which entries they name is unknown.")
    unlinked = _unlinked_captures(folders.intake, folders.links)
    if unlinked:
        limits.append(f"{unlinked} saved {'event has' if unlinked == 1 else 'events have'} no recorded Inbox origin "
                      "(captured before origins were recorded, or typed by hand). None is matched to this entry by "
                      "headline, date or link, so one about it would not be shown here.")
    use, problems = _use_rows(captures, store)
    return _assemble(rows + use, limits + problems, retrievals, len(versions))


def capture_history(capture_id: str, origin: dict, origin_versions: list[dict], folders, store: Path | None) -> dict:
    """The processing history of one saved event: its origin entry's discovery and triage when a verified origin
    names one, and its own attempt, reviews and freezes. Reads only."""
    overview = f"/events/capture/{capture_id}"
    rows, limits, retrievals = [], [], 0
    version = None
    if origin["state"] == "verified":
        linked = origin["link"]["inbox"]
        item_id, version = linked["item_id"], linked["version"]
        source_rows, limits, retrievals = _source_rows(item_id, origin_versions, None, folders.inbox)
        rows += [{**row, "href": f"/events/inbox/{item_id}"} for row in source_rows]
        if item_id.split(":", 1)[0] not in inbox_imports.SOURCES:
            prints = {fingerprint(snapshot_item(version_item(item_id, entry))): number
                      for number, entry in enumerate(origin_versions, start=1)}
            found, problems = _triage_rows(item_id, prints, folders.triage)
            rows += found
            limits += problems
    elif origin["state"] == "unreadable":
        limits.append(origin["problem"])
    else:
        limits.append("This saved event has no recorded Inbox origin, so no feed retrieval or headline triage is "
                      "linked to it; nothing is matched by headline, date or link.")
    found, entry = _analysis_rows(capture_id, folders, overview, version)
    rows += found
    if entry:
        rows += _review_rows(entry, folders.reviews, overview)[0]
    research, problems = _research_rows(capture_id, folders)
    rows += research
    limits += problems
    use, problems = _use_rows({capture_id}, store)
    return _assemble(rows + use, limits + problems, retrievals, len(origin_versions))


def processing_index(triage_dir: Path, links: Path, intake: Path) -> dict:
    """Per Inbox entry, any version: how many saved triage requests asked for its result, whether one was accepted
    (model or simulated) or failed or stayed uncertain, and how many saved events recorded it as their verified origin.
    For the Inbox list; the overview's history has the detail. Reads only."""
    items: dict[str, dict] = {}

    def row(item_id: str) -> dict:
        return items.setdefault(item_id, {"model_triage": False, "simulated_triage": False, "triage_attention": False,
                                          "triage_requests": 0, "captures": 0})
    good, bad = triage_flow.records(triage_dir)
    for record in good:
        attempts = {mode: triage_flow.read_attempts(record, mode) for mode in triage_flow.MODES}
        for entry in record["entries"]:
            found = row(entry["id"])
            found["triage_requests"] += 1
            for mode, made in attempts.items():
                if any(triage_flow.usable(attempt) for attempt in made):
                    found["model_triage" if mode == "paid" else "simulated_triage"] = True
                elif made:
                    found["triage_attention"] = True
    unverified = 0
    for path in sorted(links.glob("*.json")) if links.is_dir() else []:
        try:
            row(event_links.verified_link(links, path.stem, intake)["inbox"]["item_id"])["captures"] += 1
        except event_links.UNVERIFIED:
            unverified += 1
    return {"index_version": INDEX_VERSION, "provider_called": False, "items": items,
            "unreadable_triage_requests": len(bad), "unverified_links": unverified}
