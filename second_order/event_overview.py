"""Private event overview: one event's source, saved headline triage, draft and human review, and market context, read
together from local records. Reads only: nothing is fetched, written, repaired, reserved, regenerated or approved.

An overview is anchored on one stable identity, an Event Inbox entry (`inbox`, its feed identity) or a saved capture
(`capture`, its capture ID). Records are joined only by those identities and by explicit, verified links
(event_links): a capture reaches the Inbox entry version its form started from, and an entry reaches the captures that
recorded it as their origin. Nothing is joined by headline, similarity, date or retrieval time, so repeated release
titles stay separate events, two captures of one statement stay two records, and sharing market observations says
nothing about identity.

Each section reads through the existing verified reader and keeps its own version binding:

- source: the entry (feed metadata, every archived version) or the capture (operator-supplied publication time,
  captured text, capture time), with the recorded origin or the visible absence of one;
- triage: saved results for the exact input fingerprint of one entry version (headline_triage.fingerprint), with
  their model, prompt and configuration, earlier-configuration and local re-check provenance; results of other
  versions are counted, never shown as this version's; relations are suggestions from one response, not identity;
- draft and review: analysis_library.capture_analysis, so a review counts as current only when it was saved against
  the exact draft-view fingerprint served now; the review editor is the existing one;
- market context: event_context and market_store, as the market-context page reads them; an unsupported topic,
  a missing or stale context date, missing sessions and conflicts are stated, and nothing is attached to fill a gap;
- processing history (event_history): the dated steps those records show, from retrieval to triage, analysis,
  review and freeze, with failures, uncertain sends and the limits of what can be linked.

This overview is not the research Dossier (`/h/:id`): nothing in it is frozen, evaluated or scored, and it never
enters research summaries.
"""
from dataclasses import dataclass
from pathlib import Path

from . import (analysis_library, draft_catalog, event_context, event_history, event_inbox, event_intake, event_links,
               inbox_archive, inbox_imports, market_retrieval, market_store, triage_flow, triage_plan)
from .headline_triage import RELATIONS, config, config_key, fingerprint, snapshot_item
from .market_context import ContextRefused

OVERVIEW_VERSION = "event-overview-0.1"
NOT_A_DOSSIER = ("A private overview of one event's saved local records. It is not a research Dossier: nothing here is "
                 "frozen, evaluated or scored, and it never enters research summaries.")
MODE_NOTES = {"simulated": "Local simulation: no model read the entry; the result is a fixture, not a classification.",
              "paid": "A model response, accepted under the validation policy named in its provenance."}


@dataclass(frozen=True)
class Folders:
    inbox: Path
    intake: Path
    attempts: Path
    drafts: Path
    published: Path
    reviews: Path
    triage: Path
    links: Path
    market: Path
    bundle: Path | None
    store: Path | None = None  # The research store, read only for verified freeze records; None: not checked.
    research: Path | None = None  # Evidence-first research analyses (research_analysis); None: not checked.


_version_item = event_history.version_item  # An archived entry version as the inbox view would show it.


# ---------------------------------------------------------------- sections

def _triage(item: dict | None, triage_dir: Path, inbox_items: dict) -> dict:
    """Saved triage for exactly this entry version, and relations whose response named this version."""
    if item is None:
        return {"state": "no_entry", "fingerprint": None, "modes": [], "relations": [], "unreadable_requests": []}
    if item["source"] in inbox_imports.SOURCES:  # Snapshot records are never offered for headline triage.
        return {"state": "not_offered", "fingerprint": None, "modes": [], "relations": [], "unreadable_requests": []}
    index = triage_plan.build_index(triage_dir)
    fp = fingerprint(snapshot_item(item))
    current_key = config_key(config())
    modes = []
    for mode in triage_flow.MODES:
        saved = index["results"].get((mode, fp), [])
        current = next((row for row in saved if row["config_key"] == current_key), None)
        earlier = next((row for row in saved if row["config_key"] != current_key), None)
        claim = None if current else triage_flow.claim_status(triage_dir, mode, f"{fp}-{current_key}")
        others = len(index["versions"].get((mode, item["id"]), set()) - {fp})
        if not (current or earlier or claim or others):
            continue
        shown = current or earlier
        status = "current" if current else "earlier_version" if earlier else "unresolved" if claim else "none"
        modes.append({"mode": mode, "mode_note": MODE_NOTES[mode], "status": status,
                      "result": shown["result"] if shown else None, "provenance": shown["provenance"] if shown else None,
                      "claim": claim, "other_versions_with_results": others})
    relations, seen = [], set()
    for mode in triage_flow.MODES:
        for comparison in index["comparisons"][mode]:
            scope = comparison["scope"]
            for relation in comparison["relations"]:
                prints = {member: scope.get(member) for member in relation["item_ids"]}
                if fp not in prints.values():
                    continue
                key = (mode, comparison["provenance"]["triage_id"], relation["relation"], frozenset(relation["item_ids"]))
                if key in seen:
                    continue
                seen.add(key)
                others = []
                for member, member_fp in prints.items():
                    if member_fp == fp:
                        continue
                    held = inbox_items.get(member)
                    others.append({"item_id": member, "title": held["title"] if held else None,
                                   "same_version_held_now": bool(held) and
                                   fingerprint(snapshot_item(held)) == member_fp})
                relations.append({"mode": mode, "relation": relation["relation"], "label": RELATIONS[relation["relation"]],
                                  "reason": relation["reason"], "others": others,
                                  "scope_checked": comparison["scoped"], "provenance": comparison["provenance"]})
    return {"state": "results" if modes or relations else "none", "fingerprint": fp, "modes": modes,
            "relations": relations, "unreadable_requests": index["unreadable"]}


def _analysis(capture_id: str, folders: Folders) -> dict:
    """The capture's draft (or refusal or failure) and its review state, through My analyses' own reader."""
    found = analysis_library.capture_analysis(capture_id, folders.intake, folders.attempts, folders.drafts,
                                              folders.published, folders.reviews)
    return {"state": found["state"], "draft_id": found.get("draft_id"), "entry": found.get("entry"),
            "mode": found.get("mode"), "detail": found.get("detail") or found.get("problem")}


def _market(kind: str, event_id: str, folders: Folders, clock) -> dict:
    """The market-context section as the market-context page reads it, summarised; never filled to look complete."""
    href = f"/market-context/{kind}/{event_id}"
    try:
        event = event_context.definition(kind, event_id, folders.market, folders.inbox, folders.intake)
    except ContextRefused as exc:
        return {"state": "unreadable", "problem": str(exc), "href": None, "event": None, "view": None, "plan": None}
    summary = {key: event[key] for key in ("key", "supported", "family_label", "outside", "context", "suggestion",
                                           "suggestion_problem", "confirmation_stale", "problem")}
    base = {"href": href, "event": summary, "view": None, "plan": None, "problem": None}
    if not event["supported"]:
        return {**base, "state": "unsupported"}
    if event["problem"]:
        return {**base, "state": "unreadable", "problem": event["problem"]}
    if event["context"] is None:
        return {**base, "state": "stale_confirmation" if event["confirmation_stale"] else "needs_date"}
    as_of = event_context.today(clock)
    found, problems = market_store.retrievals(folders.market, folders.bundle)
    view = event_context.build_view(event, found, problems, as_of)
    work = market_retrieval.plan([event], found, as_of)
    held = work["held_sessions"]
    state = "complete" if view["complete"] else "partial" if held or view["conflicts"] else "no_data"
    return {**base, "state": state, "view": view,
            "plan": {"needed_sessions": work["needed_sessions"], "held_sessions": held,
                     "missing_sessions": len(work["missing_sessions"]), "future_sessions": len(work["future_sessions"]),
                     "requests": work["requests"]}}


def _linked_capture(capture_id: str, folders: Folders) -> dict:
    """One capture that recorded an entry as its origin: its own headline, the version it started from, its analysis."""
    origin = event_links.read_origin(folders.links, capture_id, folders.intake, folders.inbox)
    row = {"capture_id": capture_id, "origin": origin, "headline": None, "captured_at": None, "analysis": None,
           "problem": origin["problem"]}
    try:
        record = event_intake.verified(folders.intake, capture_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        return {**row, "problem": f"The capture this link names cannot be read: {exc}"}
    analysis = _analysis(capture_id, folders)
    return {**row, "headline": record["event"]["headline"], "captured_at": record["times"]["captured_at"],
            "published_at_as_supplied": record["times"]["published_at_as_supplied"],
            "analysis": {"state": analysis["state"], "outcome": (analysis["entry"] or {}).get("outcome"),
                         "review": (analysis["entry"] or {}).get("review"), "detail": analysis["detail"]}}


# ---------------------------------------------------------------- overviews

def inbox_overview(item_id: str, folders: Folders, clock=market_retrieval.now) -> dict:
    """An Event Inbox entry: its versions, its triage, the captures that recorded it as their origin, its context."""
    key = event_context.event_key("inbox", item_id)  # 404 for an identifier no source could have made.
    item, location, versions = event_links._versions(folders.inbox, item_id)
    if item is None and not versions:
        raise ContextRefused(404, "No Event Inbox entry with this identifier is held locally")
    view = event_inbox.inbox_view(folders.inbox)
    inbox_items = {entry["id"]: entry for entry in view["items"] + view["retained"]}
    current_sha = inbox_archive.content_sha256(item) if item else None
    source = {
        "kind": "inbox", "id": item_id, "key": key, "held": item is not None, "location": location,
        "entry": item, "content_sha256": current_sha,
        "full_text_element": getattr(event_inbox.SOURCES.get(item_id.split(":", 1)[0]), "full_text_element", False),
        "versions": [{"number": number, "content_sha256": version["content_sha256"], "title": version["title"],
                      "link": version["link"], "feed_timestamp_raw": version["feed_timestamp"]["raw"],
                      "first_seen_at": version["first_seen_at"], "last_seen_at": version["last_seen_at"],
                      "current": version["content_sha256"] == current_sha}
                     for number, version in enumerate(versions, start=1)],
        "note": ("A record imported from a retained BIS snapshot (one page retained on approval, not a live feed). Its "
                 "timestamp is the listing's metadata, not the release's dateline; importing it did not verify its "
                 "claims, and nothing was downloaded." if location == "imported" or
                 item_id.split(":", 1)[0] in inbox_imports.SOURCES else
                 "Feed metadata as the publisher's feed stated it when an explicit refresh retrieved it. The feed "
                 "timestamp is not a verified publication instant, and no article text was downloaded.")}
    captures = [_linked_capture(row["capture_id"], folders) for row in event_links.captures_from(folders.links, item_id)]
    return {"overview_version": OVERVIEW_VERSION, "kind": "inbox", "id": item_id, "title": item["title"] if item else
            versions[-1]["title"], "not_a_dossier": NOT_A_DOSSIER, "provider_called": False, "source": source,
            "triage": _triage(item, folders.triage, inbox_items),
            "analysis": {"state": "linked" if captures else "none", "captures": captures,
                         "unreadable_links": event_links.unreadable_links(folders.links)},
            "market": _market("inbox", item_id, folders, clock),
            "history": event_history.inbox_history(item_id, item, versions, folders, folders.store)}


def capture_overview(capture_id: str, folders: Folders, clock=market_retrieval.now) -> dict:
    """A saved capture: its supplied source, the Inbox version it started from (if recorded), that version's triage,
    its own draft and review, and its market context."""
    event_context.event_key("capture", capture_id)
    try:
        record = event_intake.verified(folders.intake, capture_id)
    except (event_intake.IntakeRefused, OSError) as exc:
        raise ContextRefused(404, f"This saved event cannot be read: {exc}") from None
    origin = event_links.read_origin(folders.links, capture_id, folders.intake, folders.inbox)
    origin_item, versions = None, []
    if origin["state"] == "verified":
        linked = origin["link"]["inbox"]
        item, _, versions = event_links._versions(folders.inbox, linked["item_id"])
        if item is not None and inbox_archive.content_sha256(item) == linked["content_sha256"]:
            origin_item = item
        else:
            version = next((version for version in versions if version["content_sha256"] == linked["content_sha256"]),
                           None)
            origin_item = _version_item(linked["item_id"], version) if version else None
    view = event_inbox.inbox_view(folders.inbox)
    inbox_items = {entry["id"]: entry for entry in view["items"] + view["retained"]}
    siblings = []
    if origin["state"] == "verified":
        for row in event_links.captures_from(folders.links, origin["link"]["inbox"]["item_id"]):
            if row["capture_id"] != capture_id:
                siblings.append(_linked_capture(row["capture_id"], folders))
    source = {"kind": "capture", "id": capture_id, "key": f"capture-{capture_id}", "event": record["event"],
              "times": record["times"], "source": record["source"], "request": record["request"],
              "source_text": record["source_text"], "origin": origin,
              "note": event_intake.PUBLISHED_NOTE}
    triage = _triage(origin_item, folders.triage, inbox_items) if origin_item else {
        "state": "no_origin" if origin["state"] == "none" else "origin_unreadable" if origin["state"] == "unreadable"
        else "origin_not_held", "fingerprint": None, "modes": [], "relations": [], "unreadable_requests": []}
    return {"overview_version": OVERVIEW_VERSION, "kind": "capture", "id": capture_id,
            "title": record["event"]["headline"], "not_a_dossier": NOT_A_DOSSIER, "provider_called": False,
            "source": source, "triage": triage, "analysis": {**_analysis(capture_id, folders), "siblings": siblings},
            "market": _market("capture", capture_id, folders, clock),
            "history": event_history.capture_history(capture_id, origin, versions, folders, folders.store)}


def folders_for(inbox: Path, intake: Path, attempts: Path, drafts: Path, published: Path, reviews: Path,
                triage: Path, links: Path, market: Path, bundle: Path | None, store: Path | None = None,
                research: Path | None = None) -> Folders:
    return Folders(inbox, intake, attempts, drafts, published or draft_catalog.tracker_dir(drafts), reviews, triage,
                   links, market, bundle, store, research)
