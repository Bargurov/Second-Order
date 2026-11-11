"""Headline triage, what to request: saved results are resolved locally first, and only missing work is planned.

A selection holds 1 to 25 inbox entries, current or retained in the archive. Each entry's result is looked up, in the
chosen mode, under its input fingerprint and the current configuration, among the accepted responses that
triage_flow's records hold (the exact response bytes, re-verified on every read; nothing is copied elsewhere). An entry
is one of:

- reuse: it has a saved result, which is shown; it is never requested again;
- process: it has none (a new entry, or changed content, which is a new fingerprint), or the operator explicitly asks
  for it again;
- earlier_version: it has a result only from an earlier configuration (model, effort, thinking, prompt or schema
  version). That result is shown with its provenance; regenerating it needs an explicit decision;
- unresolved: an earlier request claimed it without producing a result (in flight, failed or uncertain). It stays
  visible and is requested again only by explicit decision.

Relations are concluded per response. Comparison work is tracked apart from classification work (comparison_work): a
pair is identified by both entries' fingerprints in canonical order, the mode and the configuration. Local metadata
narrows which pairs need comparing (CANDIDATE_DAYS, same publisher); it never merges anything. The pairs still needed
are the request's comparison scope: saved in it, part of its bytes, and the only pairs its reply may relate. A pair
counts as compared only when it was in the scope of an accepted response under that configuration; entries merely
appearing together in a request compare nothing. A pair claimed by an earlier request without an accepted result, or
compared only under an earlier configuration, is needed again only by explicit decision. (A headline-triage-0.2 request
had no scope; only the pairs its approval named count, as work done under its own, earlier configuration.) A candidate
pair not yet compared brings its earlier entry in as comparison context only (a few fields, no excerpt, no new result).
When no entry needs a result and every candidate pair was compared, nothing is requested: the saved results are the
answer. Otherwise one request covers all the missing work, within the 25-entry bound.

A saved relation is shown only for a selection holding every entry it names, each with the fingerprint it had when the
relation was concluded, and it is labelled with the response it came from and whether that response's relations were
checked against a comparison scope (headline-triage-0.2 responses were not). Relations from different responses are
never merged or chained.

Reads (selection_view) never call a model, fetch anything or write. prepare saves the planned request (see
triage_flow) only when one is planned; it sends nothing.
"""
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
from typing import Callable

from . import event_inbox, triage_flow
from .analysis_flow import FlowRefused, strict_object
from .headline_triage import (CATEGORIES, MAX_SELECTION, RELATIONS, VIEW_VERSION, build_request, canonical_pairs,
                              config, config_key, cost_estimate, entry_result, feed_dates, fingerprint, ordered, sha256,
                              snapshot_item)
from .store import canonical
from .triage_flow import MODES, TRIAGE_DIR, TriageRefused

CANDIDATE_DAYS = 10
NARROWING = (f"Only candidate pairs are compared: entries from the same publisher whose feed dates are at most "
             f"{CANDIDATE_DAYS} days apart, or where either feed date is missing. The request lists exactly the pairs it "
             "still needs, and a reply relating any other two items is not accepted. Other pairs are never compared, so "
             "no relation between them is not evidence of anything.")


def inbox_entries(inbox_dir: Path) -> dict[str, tuple[dict, str]]:
    """Every entry a selection may name: the latest retrievals ("current") and the archive's retained history."""
    view = event_inbox.inbox_view(inbox_dir)
    found = {item["id"]: (item, "current") for item in view["items"]}
    for item in view["retained"]:
        found.setdefault(item["id"], (item, "retained"))
    return found


def build_index(triage_dir: Path) -> dict:
    """Every accepted result and every comparison, from the saved requests' verified responses. Reads only."""
    good, bad = triage_flow.records(triage_dir)
    results: dict[tuple[str, str], list[dict]] = {}
    versions: dict[tuple[str, str], set[str]] = {}
    comparisons: dict[str, list[dict]] = {mode: [] for mode in MODES}
    current = config_key(config())
    for record in good:
        key = config_key(record["config"])
        for mode in MODES:
            attempts = triage_flow.read_attempts(record, mode)
            # Accepted on receipt first; otherwise accepted on an explicit local re-check under the current policy.
            attempt = next((attempt for attempt in attempts if triage_flow.accepted(attempt)), None) or \
                next((attempt for attempt in attempts if triage_flow.revalidated(attempt)), None)
            if attempt is None:
                continue
            parsed = triage_flow.parsed_result(attempt)
            check = None if triage_flow.accepted(attempt) else attempt["revalidation"]
            provenance = {"triage_id": record["triage_id"], "mode": mode, "config": record["config"],
                          "current_config": key == current, "received_at": attempt["received_at"],
                          "request_sha256": record["request_sha256"], "response_id": parsed["response_id"],
                          "request_id": attempt["request_id"],
                          "validation_policy": check["validation_policy"] if check else attempt["validation_policy"],
                          "revalidation": None if check is None else {
                              "validation_policy": check["validation_policy"], "revalidated_at": check["revalidated_at"],
                              "original_outcome": attempt["outcome"],
                              "original_validation_policy": attempt["validation_policy"],
                              "original_message": attempt["message"]}}
            for entry in record["entries"]:
                results.setdefault((mode, fingerprint(entry)), []).append(
                    {"config_key": key, "result": entry_result(parsed["results"][entry["id"]], entry),
                     "provenance": provenance})
                versions.setdefault((mode, entry["id"]), set()).add(fingerprint(entry))
            prints = {entry["id"]: fingerprint(entry) for entry in record["entries"] + record["context"]}
            # Only explicitly requested comparisons count as done: the saved scope, or for a 0.2 request (no scope) the
            # pairs its approval named, recorded in its manifest.
            requested = record["pairs"] if record["pairs"] is not None else attempt.get("comparison_pairs") or []
            comparisons[mode].append({"scope": prints, "scoped": record["pairs"] is not None,
                                      "pairs": {frozenset((prints[a], prints[b])) for a, b in requested
                                                if a in prints and b in prints},
                                      "config_key": key, "relations": parsed["relations"], "provenance": provenance})
    for saved in results.values():
        saved.sort(key=lambda row: row["provenance"]["received_at"], reverse=True)
    for mode in MODES:
        comparisons[mode].sort(key=lambda row: row["provenance"]["received_at"], reverse=True)
    return {"results": results, "versions": versions, "comparisons": comparisons, "unreadable": bad}


def candidates(a: dict, b: dict) -> bool:
    """Whether local metadata leaves two entries worth comparing. It narrows comparisons; it never merges entries."""
    if a["publisher"] != b["publisher"]:
        return False
    first, second = a["feed_timestamp"]["utc"], b["feed_timestamp"]["utc"]
    if first is None or second is None:
        return True
    return abs(datetime.fromisoformat(first) - datetime.fromisoformat(second)) <= timedelta(days=CANDIDATE_DAYS)


def comparison_work(rows: list[dict], mode: str, settings_key: str, index: dict, triage_dir: Path) -> dict:
    """The comparison work among rows (each with input, fingerprint and reprocess), apart from classification work.

    A comparison is identified by both entries' input fingerprints in canonical order, the mode and the configuration,
    so selection order and other selected entries never make it new, and a changed entry never reuses an older one.
    Each candidate pair is compared (in the comparison scope of an accepted response under this configuration, with
    both versions), unresolved (claimed by an earlier request without an accepted result), earlier (compared only under
    another configuration) or needed. Unresolved and earlier pairs are needed again only when one of their entries is explicitly re-requested.
    The planner and dispatch both use this, so an approval is checked against the work as it stands. Reads only."""
    def done(same: bool) -> list[set[frozenset]]:
        return [comparison["pairs"] for comparison in index["comparisons"][mode]
                if (comparison["config_key"] == settings_key) == same]
    current, other = done(True), done(False)
    work: dict[str, list] = {"pairs": [], "compared": [], "unresolved": [], "earlier": [], "needed": []}
    for a, b in combinations(rows, 2):
        if not candidates(a["input"], b["input"]):
            continue
        work["pairs"].append((a, b))
        both, asked = frozenset((a["fingerprint"], b["fingerprint"])), a["reprocess"] or b["reprocess"]
        if any(both in pairs for pairs in current):
            work["compared"].append((a, b))
            continue
        claim = triage_flow.claim_status(triage_dir, mode,
                                         triage_flow.pair_key(a["fingerprint"], b["fingerprint"], settings_key))
        if claim and not asked:
            work["unresolved"].append((a, b, claim))
        elif any(both in pairs for pairs in other) and not asked:
            work["earlier"].append((a, b))
        else:
            work["needed"].append((a, b))
    return work


def _checked(item_ids: object, mode: object, reprocess: object) -> tuple[list[str], str, set[str]]:
    if not isinstance(item_ids, list) or not all(isinstance(item_id, str) for item_id in item_ids):
        raise TriageRefused(422, "item_ids must be a list of inbox entry IDs")
    if not 1 <= len(item_ids) <= MAX_SELECTION:
        raise TriageRefused(422, f"Select from 1 to {MAX_SELECTION} entries; {len(item_ids)} were sent")
    if len(set(item_ids)) != len(item_ids):
        raise TriageRefused(422, "An entry is selected more than once")
    if mode not in MODES:
        raise TriageRefused(422, f"mode must be one of {', '.join(MODES)}")
    if not isinstance(reprocess, list) or not all(isinstance(item_id, str) for item_id in reprocess) or \
            not set(reprocess) <= set(item_ids):
        raise TriageRefused(422, "reprocess_ids must list selected entries only")
    return item_ids, mode, set(reprocess)


def selection_view(item_ids: list[str], mode: str, reprocess: list[str], inbox_dir: Path = event_inbox.INBOX_DIR,
                   triage_dir: Path = TRIAGE_DIR) -> dict:
    """What a selection already has, and the one request (or none) its missing work needs. Reads only: no model is
    called, nothing is fetched and nothing is written."""
    item_ids, mode, reprocess = _checked(item_ids, mode, reprocess)
    known = inbox_entries(inbox_dir)
    absent = [item_id for item_id in item_ids if item_id not in known]
    if absent:
        raise TriageRefused(409, f"{len(absent)} of the selected entries are not in the local inbox or its archive; "
                                 "nothing was planned. Read the inbox again and select from what it holds")
    location = {item_id: known[item_id][1] for item_id in item_ids}
    selected = ordered([snapshot_item(known[item_id][0]) for item_id in item_ids])
    index = build_index(triage_dir)
    settings = config()
    current_key = config_key(settings)

    rows = []
    for entry in selected:
        fp = fingerprint(entry)
        saved = index["results"].get((mode, fp), [])
        current = next((row for row in saved if row["config_key"] == current_key), None)
        earlier = next((row for row in saved if row["config_key"] != current_key), None)
        claim = None if current else triage_flow.claim_status(triage_dir, mode, f"{fp}-{current_key}")
        if current:
            status = "reuse"
        elif claim and entry["id"] not in reprocess:
            status = "unresolved"
        elif earlier and entry["id"] not in reprocess:
            status = "earlier_version"
        else:
            status = "process"
        shown = current or earlier
        rows.append({"input": entry, "fingerprint": fp, "location": location[entry["id"]], "status": status,
                     "result": shown["result"] if shown else None, "provenance": shown["provenance"] if shown else None,
                     "claim": claim, "reprocess": entry["id"] in reprocess,
                     "other_versions_with_results": len(index["versions"].get((mode, entry["id"]), set()) - {fp})})

    work = comparison_work([row for row in rows if row["status"] != "unresolved"], mode, current_key, index, triage_dir)
    needed = work["needed"]
    scope = canonical_pairs([[a["input"]["id"], b["input"]["id"]] for a, b in needed])  # The request's pairs.
    in_needed = {row["input"]["id"] for pair in needed for row in pair}
    entries = [row["input"] for row in rows if row["status"] == "process"]
    context = [row["input"] for row in rows if row["status"] != "process" and row["input"]["id"] in in_needed]
    for row in rows:
        row["in_request"] = "entry" if row["status"] == "process" else "context" if row["input"] in context else None

    by_fingerprint = {row["fingerprint"]: row for row in rows}
    relations, seen = [], set()
    for comparison in index["comparisons"][mode]:  # Newest first; an identical later suggestion is shown once.
        for relation in comparison["relations"]:
            members = [by_fingerprint.get(comparison["scope"][member]) for member in relation["item_ids"]]
            key = (relation["relation"], frozenset(relation["item_ids"]))
            if None in members or key in seen:
                continue
            seen.add(key)
            names = {member["input"]["id"] for member in members}
            relations.append({**relation, "item_ids": [row["input"]["id"] for row in rows if row["input"]["id"] in names],
                              "label": RELATIONS[relation["relation"]], "scope_checked": comparison["scoped"],
                              "feed_dates": feed_dates([member["input"] for member in members]),
                              "provenance": comparison["provenance"]})

    plan = {"requests": 1 if entries or needed else 0, "entries": [entry["id"] for entry in entries],
            "context": [entry["id"] for entry in context],
            "reused": [row["input"]["id"] for row in rows if row["status"] == "reuse"],
            "earlier_version": [row["input"]["id"] for row in rows if row["status"] == "earlier_version"],
            "unresolved": [row["input"]["id"] for row in rows if row["status"] == "unresolved"],
            "reprocess": [row["input"]["id"] for row in rows if row["reprocess"]],
            "pairs": {"rule": NARROWING, "candidates": len(work["pairs"]), "compared": len(work["compared"]),
                      "needed": scope,
                      "unresolved": [[a["input"]["id"], b["input"]["id"]] for a, b, _ in work["unresolved"]],
                      "earlier": [[a["input"]["id"], b["input"]["id"]] for a, b in work["earlier"]]},
            "triage_id": None, "request_sha256": None, "request_bytes": 0, "request": None, "max_tokens": None,
            "cost_estimate": None, "prepared": False, "attempts": None}
    if plan["requests"]:
        request = build_request(entries, context, scope)
        request_bytes = canonical(request).encode("utf-8")
        plan.update(triage_id=f"triage-{sha256(request_bytes)[:24]}", request_sha256=sha256(request_bytes),
                    request_bytes=len(request_bytes), request=request, max_tokens=request["max_tokens"],
                    cost_estimate=cost_estimate(request_bytes, request["max_tokens"], context))
        try:
            record = triage_flow.load_record(triage_dir, plan["triage_id"])
            plan.update(prepared=True, attempts={name: triage_flow.public_attempt(
                triage_flow.read_attempt(record, name), record) for name in MODES})
        except TriageRefused:
            pass
    return {"view_version": VIEW_VERSION, "mode": mode, "config": settings, "provider_called": False,
            "items": rows, "relations": relations, "plan": plan, "taxonomy": CATEGORIES,
            "relation_labels": RELATIONS, "unreadable_requests": index["unreadable"]}


def prepare(body: bytes, inbox_dir: Path = event_inbox.INBOX_DIR, triage_dir: Path = TRIAGE_DIR,
            clock: Callable[[], datetime] = triage_flow.now) -> dict:
    """Plan a selection and, only when a request is needed, save its snapshots and exact bytes for approval. No feed,
    article or model is contacted; with nothing missing, nothing is written."""
    try:
        payload = strict_object(body, ("item_ids", "mode", "reprocess_ids"), "triage selection")
    except FlowRefused as exc:
        raise TriageRefused(exc.status, str(exc)) from None
    view = selection_view(payload["item_ids"], payload["mode"], payload["reprocess_ids"], inbox_dir, triage_dir)
    if not view["plan"]["requests"]:
        return {**view, "prepared_now": False}
    rows = {row["input"]["id"]: row["input"] for row in view["items"]}
    triage_id, wrote = triage_flow.save_request([rows[item_id] for item_id in view["plan"]["entries"]],
                                                [rows[item_id] for item_id in view["plan"]["context"]],
                                                view["plan"]["pairs"]["needed"], triage_dir, clock)
    view = selection_view(payload["item_ids"], payload["mode"], payload["reprocess_ids"], inbox_dir, triage_dir)
    if view["plan"]["triage_id"] != triage_id:  # The plan and the saved request must be the same bytes.
        raise TriageRefused(409, "The saved request does not match the plan; nothing will be sent from it")
    return {**view, "prepared_now": wrote}
