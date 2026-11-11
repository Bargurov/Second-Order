"""An update run's report (news-update-0.1, news_updates): the run beside the saved records now. Reading it requests,
sends and writes nothing.

It gives the run's arrivals and the stories they reached (news_updates.run_stories), each with its relevance, brief
and explanation states and its next action; the steps recorded; what completed, what needs attention (an editor's
judgement, a publication decision, a paid approval, an assistant's import, a limit) and what failed (a source, an
assessment, a draft, an import or a paid attempt: technical failures, never editorial judgements); the counts before
and after, apart from any earlier baseline; the paid plan, every saved request of the run's model batches with its
planning estimate (not a billing ceiling) and its attempt's state; and the operator's next actions with the command
for each. A batch is said to wait only for the stories that still need it.
"""
from datetime import datetime

from . import (brief_drafting, news_baseline, news_batches, news_explanations, news_matching, news_rank, news_texts,
               news_views, newsroom_store as ns, relevance_batches, relevance_requests as rr)
from .news_updates import ARRIVALS, KINDS, PAID_STATEMENT, UPDATE_VERSION, _read, _root, _steps, load, run_stories



def _paid(desk: news_views.Desk, steps: list[dict], world: dict) -> dict:
    """Every saved request of the run's model batches, its planning estimate, its attempt's state and whether an
    approval now would send it: one whose story was merged away or whose material changed since the preview is skipped
    by the batch's approval and never sent, so it is not counted in what an approval would send."""
    rows, batches = [], []
    for step in steps:
        if step["step"] not in ("relevance", "briefs") or step["method"] != "model":
            continue
        if step["step"] == "relevance":
            batch = relevance_batches.load(desk, step["batch_id"])
            found = [(item, item["request"]["request_id"], rr.attempt_state(rr.folder(desk, item["request"]
                                                                                       ["request_id"])))
                     for item in batch["items"]]
            approved = (desk.newsroom.path.parent / "relevance-batches" / step["batch_id"] / "approval.json").exists()
            command = "news relevance approve"
        else:
            batch = news_batches.load(desk, step["batch_id"])
            found = [(item, item["draft"]["draft_id"], brief_drafting.attempt_state(
                brief_drafting._folder(desk, item["draft"]["draft_id"]))) for item in batch["items"]]
            approved = (desk.newsroom.path.parent / "batches" / step["batch_id"] / "approval.json").exists()
            command = "news batch approve"
        for item, request_id, attempt in found:
            estimate = (item.get("request") or item.get("draft"))["estimated_max_usd"]
            story = world["stories"].get(item["story_id"])
            skip = None if attempt["state"] != "not_attempted" else (
                "its story was merged into another since the preview" if story is None else
                "its story's material changed since the preview" if
                story["material"]["material_sha256"] != item["material_sha256"] else _superseded(desk, step, item))
            rows.append({"stage": step["step"], "batch_id": step["batch_id"], "story_id": item["story_id"],
                         "title": item["title"], "request_id": request_id, "estimated_max_usd": estimate,
                         "request_stage": (item.get("draft") or {}).get("stage"),
                         "attempt": attempt["state"], "detail": attempt["detail"], "skipped": skip})
        batches.append({"stage": step["step"], "batch_id": step["batch_id"], "requests": len(found),
                        "estimated_max_usd_total": batch["estimated_max_usd_total"], "approved": approved,
                        "command": (f"python -m second_order {command} {step['batch_id']} --estimated-max-usd-total "
                                    f"{batch['estimated_max_usd_total']} --approve-paid-requests")})
    waiting = [row for row in rows if row["attempt"] == "not_attempted"]
    sendable = [row for row in waiting if row["skipped"] is None]
    return {"enabled": brief_drafting.status(desk.drafting)["enabled"], "batches": batches, "requests": rows,
            "not_attempted": len(waiting),
            "not_attempted_estimate_usd": round(sum(row["estimated_max_usd"] for row in waiting), 4),
            "sendable": len(sendable), "sendable_estimate_usd": round(sum(row["estimated_max_usd"] for row in sendable),
                                                                      4),
            "attempted": {state: sum(1 for row in rows if row["attempt"] == state)
                          for state in sorted({row["attempt"] for row in rows} - {"not_attempted"})},
            "statement": PAID_STATEMENT}


def _superseded(desk: news_views.Desk, step: dict, item: dict) -> str | None:
    """Why a saved model brief request can no longer be sent: it follows an earlier request contract, which an approval
    refuses (brief_drafting.approve: request_superseded), sending nothing."""
    if step["step"] != "briefs" or step["method"] != "model":
        return None
    folder = brief_drafting._folder(desk, item["draft"]["draft_id"])
    return brief_drafting.superseded(_read(folder / "preview.json") or {})


def _waiting(desk: news_views.Desk, steps: list[dict], found: dict) -> dict[tuple[str, str], dict]:
    """The run's stories whose current material is in one of its batches not carried out yet: (step, story ID) -> the
    batch, its method and what it awaits (a paid approval, or an assistant's import)."""
    rows = {}
    for step in steps:
        if step["step"] not in ("relevance", "briefs"):
            continue
        batch = (relevance_batches.load if step["step"] == "relevance" else news_batches.load)(desk, step["batch_id"])
        for item in batch["items"]:
            story = found["stories"].get(item["story_id"])
            if story is None or story["material"]["material_sha256"] != item["material_sha256"]:
                continue  # A batch of earlier material is not waiting for anything: preview again.
            if _superseded(desk, step, item):
                continue  # A request under an earlier request contract is not waiting for anything: prepare again.
            if batch["method"] == "model":
                folder = rr.folder(desk, item["request"]["request_id"]) if step["step"] == "relevance" else \
                    brief_drafting._folder(desk, item["draft"]["draft_id"])
                if brief_drafting.attempt_state(folder)["state"] != "not_attempted":
                    continue
            rows[(step["step"], item["story_id"])] = {"batch_id": batch["batch_id"], "method": batch["method"],
                                                      "stage": step["step"], "awaits": "approval" if
                                                      batch["method"] == "model" else "import"}
    return rows


IMPORTS = {"relevance": "python -m second_order news relevance import {} --annotations FILE --assistant-tool NAME",
           "briefs": "python -m second_order news batch import {} --drafts FILE --assistant-tool NAME"}


def _upcoming(desk: news_views.Desk, run_id: str, found: dict, stories: list[dict], steps: list[dict], paid: dict,
              now: datetime, waiting: dict) -> list[dict]:
    """The operator's next actions after the refresh, in order, each with the command that does it."""
    command = f"python -m second_order news update {{}} {run_id}"
    rows = []
    if desk.texts is not None and not any(step["step"] == "texts" for step in steps):
        story_ids = [row["story_id"] for row in stories if row["material"]["reports"]]
        reports = news_texts.story_reports(found, story_ids, False, now) if story_ids else []
        wanted = sum(1 for row in news_texts.plan(desk.texts, reports) if row["action"] == "request")
        if wanted:
            rows.append({"step": "texts", "text": f"Retrieve {wanted} permitted publication texts first (at most "
                                                  f"{news_texts.MAX_PER_RUN}), since a text changes the material.",
                         "command": command.format("texts")})
    count = {step: sum(1 for row in stories if row["step"] == step) for step in ("relevance", "briefs", "publication")}
    if count["relevance"]:
        rows.append({"step": "relevance", "text": f"Assess the economic relevance of {_plural(count['relevance'])}.",
                     "command": command.format("relevance") + " --method model"})
    if count["briefs"]:
        rows.append({"step": "context", "text": "Gather structural context for the stories to prepare.",
                     "command": command.format("context")})
        rows.append({"step": "briefs", "text": f"Prepare briefs and explanations for {_plural(count['briefs'])}: "
                                               "each story's next stage (stage 1, the evidence and figures; stage 2, "
                                               "the interpretation and brief, once its stage 1 is validated), each "
                                               "request saved for a paid approval.",
                     "command": command.format("briefs") + " --method model"})
    batches = {hit["batch_id"]: hit for hit in waiting.values()}
    rows += [{"step": "import", "text": f"Import the assistant's {'annotations' if hit['stage'] == 'relevance' else
                                                                'drafts'} for batch {batch_id} (written from its packet; "
                                        "they are labelled as assisted).", "command": IMPORTS[hit["stage"]].format(batch_id)}
             for batch_id, hit in batches.items() if hit["awaits"] == "import"]
    rows += [{"step": "approval", "text": f"Decide the paid approval of {batch['stage']} batch {batch['batch_id']} "
                                          f"({batch['requests']} requests, planning estimate "
                                          f"${batch['estimated_max_usd_total']}, not a billing ceiling).",
              "command": batch["command"]}
             for batch in paid["batches"] if batches.get(batch["batch_id"], {}).get("awaits") == "approval"]
    if count["publication"]:
        batches = [step["batch_id"] for step in steps if step["step"] == "briefs"]
        rows.append({"step": "publication", "text": f"Decide the publication of {count['publication']} prepared "
                                                    f"version{'s' if count['publication'] != 1 else ''}.",
                     "command": f"python -m second_order news batch publish {batches[-1] if batches else '<batch ID>'}"
                                " --reason \"...\""})
    return rows


def _plural(count: int, one: str = "story", many: str = "stories") -> str:
    return f"{count} {one if count == 1 else many}"


def _counts(rows: list[dict], key: str, states) -> dict[str, int]:
    return {state: sum(1 for row in rows if row[key] == state) for state in states}


def report(desk: news_views.Desk, run_id: str, now: datetime) -> dict:
    """The run beside the saved records now: arrivals, stories, steps, counts, the paid plan and what is next. Reads
    files only: nothing is requested, sent or written."""
    run = load(desk, run_id)
    folder = _root(desk) / run_id
    refreshed, started = _read(folder / "refresh.json"), (folder / "refresh-started.json").exists()
    found = news_views.world(desk, now)
    failed = news_explanations.failures(desk.newsroom.path.parent)
    held = run_stories(run, found, failed)
    steps = _steps(desk, run_id)
    paid = _paid(desk, steps, found)
    stories = held["stories"]
    needed = {(row["step"], row["story_id"]) for row in stories}  # A batch waits only for stories still needing it.
    waiting = {key: hit for key, hit in _waiting(desk, steps, found).items() if key in needed}
    for row in stories:
        hit = waiting.get((row["step"], row["story_id"]))
        if hit is not None:
            row.update(tone="attention", step=hit["awaits"], next=(
                f"Its saved request in {hit['stage']} batch {hit['batch_id']} awaits the paid approval."
                if hit["awaits"] == "approval" else
                f"{hit['stage'].capitalize()} batch {hit['batch_id']} awaits the assistant's work (packet, then "
                "import)."))
    baseline = news_baseline.load(desk, run["baseline_id"])
    listed = [story for story in found["stories"].values() if news_rank.listed(story)]
    completed, attention, failures, upcoming = [], [], [], []
    if refreshed is None and not started:
        upcoming.append({"step": "refresh", "text": f"Refresh the sources ({run['plan']['requests']['feeds']} planned "
                                                    "requests, each once).",
                         "command": f"python -m second_order news update refresh {run_id}"})
    elif refreshed is None:
        failures.append("The refresh started and recorded no outcome; it is never repeated. Start a new run.")
    else:
        outcome = _counts(refreshed["sources"], "outcome", sorted({row["outcome"] for row in refreshed["sources"]}))
        completed.append(f"Refreshed at {refreshed['finished_at']}: {refreshed['requests']} requests ("
                         + ", ".join(f"{count} {state.replace('_', ' ')}" for state, count in outcome.items()) + ").")
        completed.append(f"Grouped {refreshed['grouping']['grouped']} new reports: {refreshed['grouping']['new_stories']}"
                         f" new stories, {refreshed['grouping']['joined']} joined held ones.")
        failures += [f"{row['publisher']} ({row['source']}): {row['detail'] or row['outcome']}"
                     for row in refreshed["sources"] if row["outcome"] == "failed"]
    for step in steps:
        if step["step"] == "texts":
            completed.append(f"Retrieved publication texts: {step['requests']} requests.")
            failures += [f"Text of {row['entry_id']}: {row['detail']}" for row in step["outcomes"]
                         if row["outcome"] == "failed"]
        elif step["step"] == "context":
            completed.append(f"Built {len(step['built'])} context bundles from structural options.")
        else:
            completed.append(f"Previewed {step['step']} batch {step['batch_id']} ({step['method']}, "
                             f"{len(step['stories'])} stories).")
            if step["left"]:
                attention.append(f"{len(step['left'])} stories were beyond batch {step['batch_id']}'s limit.")
    if held["ungrouped"]:
        attention.append(f"{len(held['ungrouped'])} arrivals are not in a story yet: group them.")
    restricted = [row for row in stories if row["step"] == "editor" and not row["material"]["reports"]]
    if restricted:
        attention.append(f"{len(restricted)} stories are headlines only under their publishers' terms: no model may "
                         "read them, so an editor judges each; until then they are listed apart with their headlines.")
    for row in stories:
        if row["tone"] == "attention" and row["step"] not in ("approval", "import") and row not in restricted:
            attention.append(f"“{row['title']}”: {row['next']}")  # Batches and restricted stories are counted.
        elif row["tone"] == "failed":
            failures.append(f"“{row['title']}”: {row['next']}")
    imports = sorted({hit["batch_id"]: hit for hit in waiting.values() if hit["awaits"] == "import"}.items())
    attention += [f"{hit['stage'].capitalize()} batch {batch_id} awaits the assistant's work: "
                  f"{sum(1 for other in waiting.values() if other['batch_id'] == batch_id)} stories." for batch_id, hit
                  in imports]
    for row in paid["requests"]:
        if row["attempt"] not in ("not_attempted", "recorded", "insufficient", "validated"):
            failures.append(f"Paid request {row['request_id']} ({row['stage']}): {row['attempt']}. "
                            f"{row['detail'] or ''}".strip())
    for batch in paid["batches"]:
        unsent = [row for row in paid["requests"] if row["batch_id"] == batch["batch_id"] and
                  row["attempt"] == "not_attempted"]
        if any(hit["batch_id"] == batch["batch_id"] and hit["awaits"] == "approval" for hit in waiting.values()):
            attention.append(f"Model batch {batch['batch_id']} ({batch['stage']}) awaits a paid approval: "
                             f"{batch['requests']} requests, planning estimate ${batch['estimated_max_usd_total']}.")
        elif unsent:  # Saved and never sent, and no story of the run awaits it now.
            sendable = [row for row in unsent if row["skipped"] is None]
            saved = _plural(len(unsent), "saved request", "saved requests")
            estimate = round(sum(row["estimated_max_usd"] for row in sendable), 4)
            reasons = "; ".join(sorted({row["skipped"] for row in unsent if row["skipped"]}))
            skipped = f"; {len(unsent) - len(sendable)} would be skipped ({reasons})" if reasons else ""
            effect = ("the model in this application would assess them again, and its newer assessments would "
                      "then decide whether they are listed" if batch["stage"] == "relevance" else
                      "the model in this application would draft them again as unpublished versions; publishing "
                      "stays a separate decision")
            if not sendable:
                attention.append(f"Model batch {batch['batch_id']} ({batch['stage']}) holds {saved} not sent: an "
                                 f"approval now would send none ({reasons}).")
                continue
            attention.append(f"Model batch {batch['batch_id']} ({batch['stage']}) holds {saved} not sent: an approval "
                             f"now would send {len(sendable)} (planning estimate ${estimate}){skipped}. Its stories "
                             f"were prepared another way since, so sending them is optional: {effect}.")
    if refreshed is not None:
        upcoming += _upcoming(desk, run_id, found, stories, steps, paid, now, waiting)
    return {
        "update_version": UPDATE_VERSION, "run_id": run_id, "label": run["label"], "as_of": ns.stamp(now),
        "started_at": run["started_at"], "started_by": run["started_by"], "reference": run["reference"],
        "baseline_id": run["baseline_id"], "plan": run["plan"],
        "refresh": refreshed, "refresh_state": "done" if refreshed else "interrupted" if started else "not_started",
        "arrivals": held["arrivals"], "revised": held["revised"], "ungrouped": len(held["ungrouped"]),
        "stories": stories, "steps": steps,
        "follow_ups": {"pairs": [row for row in news_matching.candidates(found, now, limit=10_000)
                                 if set(row["stories"]) & {story["story_id"] for story in stories}],
                       "topics": news_matching.topic_candidates(found, [row["story_id"] for row in stories], now)},
        "counts": {
            "before": {"stories": len(run["stories_before"]), "listed": len(baseline["stories"]),
                       "explanations": baseline["counts"]},
            "after": {"stories": len(found["stories"]), "listed": len(listed),
                      "explanations": _counts([{"state": news_explanations.state_of(found["folded"], story, failed)}
                                               for story in listed], "state", news_explanations.STATES)},
            "run": {"arrivals": len(held["arrivals"]), "by_class": _counts(held["arrivals"], "class", ARRIVALS),
                    "revised": len(held["revised"]), "stories": len(stories),
                    "by_kind": _counts(stories, "kind", KINDS),
                    "relevance": {state: sum(1 for row in stories if row["relevance"]["state"] == state)
                                  for state in ("relevant", "outside_scope", "insufficient", "needs_review",
                                                "unavailable", "restricted", "pending")},
                    "listed": sum(1 for row in stories if row["listed"]),
                    "explanations": _counts(stories, "explanation_state", news_explanations.STATES),
                    "published_in_run": sum(1 for row in stories if row["published_in_run"])},
            "statement": ("Before: what the run's own baseline recorded at its cutoff. After: as the records are now. "
                          "Run: this run's arrivals and the stories they reached only; earlier baselines are reported "
                          "apart (news baseline progress).")},
        "paid": paid, "completed": completed, "attention": attention, "failed": failures, "next": upcoming,
        "labels": {"arrivals": ARRIVALS, "kinds": KINDS},
        "statement": ("Read from saved records: reading this report requests nothing, sends nothing and writes "
                      "nothing. Technical failures are listed apart from editorial judgements.")}
