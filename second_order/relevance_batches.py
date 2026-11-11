"""Relevance preparation in bounded batches (relevance-batch-0.1), and the relevance queue the operator reads.

The queue (``queue``) lists every current story (its latest report at most WINDOW_HOURS old) with its relevance state,
who or what decided it and why, and which stories a batch would assess next and for what reason; it counts every state
so nothing is hidden. Older stories are assessed only when the operator names them: the archive is never processed
wholesale.

A batch assesses current stories before readers open the news. ``preview`` selects, newest first, up to ``limit``
current stories whose permitted material has no annotation yet, or only one of earlier material (and, when the operator
asks, those whose last attempt failed), or the stories the operator names (a named story already assessed is assessed
again, and the newest annotation of its material decides; an editor's judgement still decides over any annotation); it
never selects a story whose reports may not be sent to a model (``restricted``: an editor judges those), and selects
one an editor has judged only when named. It records the selection
once (data/newsroom/relevance-batches/<batch ID>/batch.json, write-once): each story, why it was selected, its
material and, for the paid method, each exact saved request (relevance_requests.prepare) with its planning estimate and
the batch's total. The batch ID comes from the method, the versions and each item's material and attempt, so the same
selection is the same batch.

Two methods, as for briefs:

- ``model``: the AI model in this application. ``approve`` repeats the batch ID and its total with
  approve_paid_requests true, and sends each saved request at most once, in order; approving again resumes without
  resending, and an item whose material changed since the preview is skipped.
- ``assisted``: an AI assistant outside the application (or an editor) annotates from the exported ``packet`` (the same
  rules, format and material the model would get); ``import_annotations`` checks each annotation against the schema and
  its quotes against the material, and saves it with the tool the operator declares; repeating an import saves nothing
  new, and an annotation that fails the schema is refused, not saved.

Reading the queue, a batch or its packet reads files only.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from . import market_store, news_relevance as nr, news_views, relevance_requests as rr, story_briefs
from . import newsroom_store as ns
from .accounts import AccountsRefused
from .brief_drafting import attempt_state

BATCH_VERSION = "relevance-batch-0.1"
QUEUE_VERSION = "relevance-queue-0.1"
METHODS = ("model", "assisted")
WINDOW_HOURS = 168
DEFAULT_LIMIT = 20
MAX_LIMIT = 40
BATCH_ID = re.compile(r"rbatch-[0-9a-f]{16}")


def _age(now: datetime, story: dict) -> float:
    return (now - datetime.fromisoformat(story["latest_at"])).total_seconds() / 3600


def why_selected(story: dict, retry_failed: bool = False) -> str | None:
    """Why a batch would assess this story now, or None when it would not."""
    relevance = story["relevance"]
    if not story["material"]["reports"] or relevance["basis"] == "editor":
        return None
    if relevance["state"] == "pending":
        return "Not assessed yet."
    if relevance["failure"] is not None:  # The latest attempt for this material failed, whatever an earlier
        # material's annotation said: it is attempted again only when the operator asks.
        return "Its last assessment failed; this is a new attempt." if retry_failed else None
    if relevance["current"] is False:
        return "Assessed on earlier material; its reports or texts have changed since."
    annotation = relevance["annotation"]
    current = rr.versions()
    for key in ("scope_version", "annotation_version"):  # The editorial scope or the schema changed; a prompt's
        # wording alone does not make every assessment due again (the operator can name stories to assess again).
        if annotation is not None and annotation["versions"].get(key) != current[key]:
            return f"Assessed under {annotation['versions'].get(key)}; the current one is {current[key]}."
    return None


def _row(story: dict, now: datetime) -> dict:
    relevance = story["relevance"]
    annotation = relevance["annotation"]
    return {"story_id": story["story_id"], "title": story["title"], "latest_at": story["latest_at"],
            "age_hours": round(_age(now, story), 1), "publishers": sorted({row["publisher"] for row in story["reports"]}),
            "state": relevance["state"], "basis": relevance["basis"], "explanation": relevance["explanation"],
            "current": relevance["current"], "review": relevance["review"], "failure": relevance["failure"],
            "importance": relevance["importance"], "hot": story["rank"]["hot"],
            "decision": annotation["decision"] if annotation else None,
            "material": {"coverage": story["material"]["coverage"], "reports": len(story["material"]["reports"]),
                         "texts": sum(1 for row in story["material"]["reports"] if row.get("text"))},
            "next": why_selected(story)}


def queue(desk: news_views.Desk, now: datetime) -> dict:
    """Every current story's relevance, counted by state, with the next batch's candidates. Reads only."""
    found = news_views.world(desk, now)
    current = sorted((story for story in found["stories"].values() if _age(now, story) <= WINDOW_HOURS),
                     key=lambda story: (story["latest_at"], story["story_id"]), reverse=True)
    rows = [_row(story, now) for story in current]
    counts = {state: sum(1 for row in rows if row["state"] == state) for state in nr.STATES}
    everything = {state: sum(1 for story in found["stories"].values() if story["relevance"]["state"] == state)
                  for state in nr.STATES}
    return {"queue_version": QUEUE_VERSION, "relevance_version": nr.RELEVANCE_VERSION, "as_of": ns.stamp(now),
            "window_hours": WINDOW_HOURS, "counts": counts, "all_counts": everything, "rows": rows,
            "candidates": sum(1 for row in rows if row["next"]), "versions": rr.versions(),
            "decision_version": nr.DECISION_VERSION, "importance_version": nr.IMPORTANCE_VERSION,
            "sending": rr.readiness(desk.drafting),
            "statement": (f"Current stories are those with a report from the last {WINDOW_HOURS // 24} days. Relevant: "
                          "an assessment the relevance decision accepts, or an editor's judgement. Outside the scope: "
                          "left out of the news. Insufficient, needs review, unavailable: an editor decides; nothing "
                          "unclear or failed is treated as irrelevant. Restricted: its publisher's terms allow no "
                          "model to read it, so only an editor can judge it. Pending: not assessed yet.")}


# ---------------------------------------------------------------- batches

def _folder(desk: news_views.Desk, batch_id: str) -> Path:
    return desk.newsroom.path.parent / "relevance-batches" / batch_id


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def load(desk: news_views.Desk, batch_id: object) -> dict:
    if not isinstance(batch_id, str) or not BATCH_ID.fullmatch(batch_id):
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    record = _read(_folder(desk, batch_id) / "batch.json")
    if record is None:
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    return record


def select(found: dict, now: datetime, limit: int, story_ids: list[str] | None,
           retry_failed: bool) -> tuple[list[tuple[dict, str]], list[dict]]:
    """(the stories a batch assesses with the reason for each, the named or current ones it leaves and why)."""
    stories = found["stories"]
    if story_ids:
        chosen, left = [], []
        for story_id in story_ids:
            story = stories.get(story_id)
            if story is None:
                raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
            reason = why_selected(story, retry_failed) or (
                "An editor's judgement decides it; this assessment is recorded beside it."
                if story["relevance"]["basis"] == "editor" else
                "Already assessed for its current material; assessed again, and the newest annotation decides.")
            if story["material"]["reports"]:
                chosen.append((story, f"Named by the operator. {reason}"))
            else:
                left.append({"story_id": story_id, "title": story["title"], "state": story["relevance"]["state"],
                             "why": _left_reason(story)})
        return chosen[:limit], left
    current = sorted((story for story in stories.values() if _age(now, story) <= WINDOW_HOURS),
                     key=lambda story: (story["latest_at"], story["story_id"]), reverse=True)
    chosen = [(story, reason) for story in current if (reason := why_selected(story, retry_failed))]
    left = [{"story_id": story["story_id"], "title": story["title"], "state": story["relevance"]["state"],
             "why": _left_reason(story)} for story, _ in chosen[limit:]]
    return chosen[:limit], left


def _left_reason(story: dict) -> str:
    if not story["material"]["reports"]:
        return "Restricted: its publisher's terms allow no model to read it; an editor judges it."
    if story["relevance"]["basis"] == "editor":
        return "An editor has judged it."
    if story["relevance"]["failure"] is not None:
        return "Its last assessment failed; select failed stories again explicitly."
    if story["relevance"]["state"] != "pending" and story["relevance"]["current"]:
        return "Already assessed for its current material under the current scope and schema."
    return "Beyond this batch's limit."


def _item(desk: news_views.Desk, found: dict, story: dict, reason: str, method: str) -> dict:
    material = story["material"]
    attempt = 1 + rr.attempts(found["folded"], story["story_id"], material["material_sha256"])
    item = {"story_id": story["story_id"], "title": story["title"], "latest_at": story["latest_at"], "reason": reason,
            "state": story["relevance"]["state"], "material_sha256": material["material_sha256"], "attempt": attempt,
            "material": {"coverage": material["coverage"], "statement": material["statement"],
                         "reports": len(material["reports"]),
                         "texts": sum(1 for row in material["reports"] if row.get("text"))}}
    if method == "model":
        prepared = rr.prepare(desk, story, attempt)
        item["request"] = {key: prepared[key] for key in ("request_id", "request_sha256", "model", "max_tokens",
                                                          "estimated_max_usd")}
    return item


def preview(desk: news_views.Desk, now: datetime, method: str, limit: int = DEFAULT_LIMIT,
            story_ids: list[str] | None = None, retry_failed: bool = False,
            actor: str = "local-operator") -> tuple[dict, bool]:
    """Select and record a batch (once); a paid one also saves each item's exact request. Nothing is sent."""
    if method not in METHODS:
        raise AccountsRefused(422, "invalid_request", f"The method is {' or '.join(METHODS)}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise AccountsRefused(422, "invalid_request", f"A batch holds 1 to {MAX_LIMIT} stories.")
    if not isinstance(retry_failed, bool):
        raise AccountsRefused(422, "invalid_request", "retry_failed is true or false.")
    found = news_views.world(desk, now)
    chosen, left = select(found, now, limit, story_ids, retry_failed)
    if not chosen:
        raise AccountsRefused(409, "nothing_to_assess", "No selected story needs an assessment: each is assessed for "
                                                        "its current material, judged by an editor or restricted.",
                              left=left)
    folded = found["folded"]
    identity = {"batch_version": BATCH_VERSION, "method": method, "versions": rr.versions(),
                "items": [[story["story_id"], story["material"]["material_sha256"],
                           1 + rr.attempts(folded, story["story_id"], story["material"]["material_sha256"])]
                          for story, _ in chosen]}
    batch_id = "rbatch-" + ns.sha256_of(identity)[:16]
    folder = _folder(desk, batch_id)
    existing = _read(folder / "batch.json")
    if existing is not None:
        return existing, False
    items = [_item(desk, found, story, reason, method) for story, reason in chosen]
    total = round(sum(item["request"]["estimated_max_usd"] for item in items), 4) if method == "model" else None
    record = {"batch_version": BATCH_VERSION, "batch_id": batch_id, "method": method, "versions": rr.versions(),
              "model": rr.MODEL if method == "model" else None, "created_at": ns.stamp(now), "created_by": actor,
              "items": items, "left": left, "estimated_max_usd_total": total,
              "statement": "Nothing was sent. " + (
                  "Each item's exact request is saved; approving the batch's total sends each once, never again. The "
                  "total is a planning estimate at the request's output limit, not a billing ceiling."
                  if method == "model" else
                  "Export the packet, have the annotations written with an AI assistant (or by an editor), then import "
                  "them; each is checked against the schema and its quotes against the material, and labelled as "
                  "AI-assisted.")}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        market_store.write_exclusive(folder / "batch.json", record)
    except FileExistsError:
        return _read(folder / "batch.json"), False
    return record, True


def status(desk: news_views.Desk, batch_id: str, now: datetime) -> dict:
    """Each item as it is now: its material since the preview, its attempt (paid), its annotation and its state."""
    batch = load(desk, batch_id)
    found = news_views.world(desk, now)
    rows = []
    for item in batch["items"]:
        story = found["stories"].get(item["story_id"])
        row = {"story_id": item["story_id"], "title": item["title"]}
        if story is None:
            rows.append({**row, "state": "gone", "detail": "The story was merged or no longer has reports."})
            continue
        mine = [entry for entry in found["folded"]["relevance"].get(item["story_id"], [])
                if (entry["preparation"] or {}).get("batch_id") == batch_id]
        attempt = attempt_state(rr.folder(desk, item["request"]["request_id"])) if batch["method"] == "model" else None
        rows.append({**row, "material_changed": story["material"]["material_sha256"] != item["material_sha256"],
                     "attempt": attempt, "annotation": mine[-1]["event_id"] if mine else None,
                     "outcome": mine[-1]["outcome"] if mine else None, "state": story["relevance"]["state"],
                     "basis": story["relevance"]["basis"]})
    return {**{key: batch[key] for key in ("batch_version", "batch_id", "method", "created_at", "model",
                                           "estimated_max_usd_total")},
            "items": rows, "approval": _read(_folder(desk, batch_id) / "approval.json")}


def approve(desk: news_views.Desk, batch_id: str, form: dict, story_now, actor: str, clock) -> dict:
    """Send each item's saved request once, in order, under this explicit approval of the batch's total."""
    batch = load(desk, batch_id)
    if batch["method"] != "model":
        raise AccountsRefused(409, "not_a_paid_batch", "This batch is prepared with an assistant; nothing is sent.")
    if form.get("approve_paid_requests") is not True or form.get("batch_id") != batch_id or \
            form.get("estimated_max_usd_total") != batch["estimated_max_usd_total"]:
        raise AccountsRefused(409, "approval_mismatch", "The approval must repeat this batch's ID and its total "
                                                        "estimate, with approve_paid_requests true. Nothing was sent.")
    if desk.drafting is None:
        raise AccountsRefused(409, "paid_drafting_disabled", rr.NOT_ENABLED)
    try:
        market_store.write_exclusive(_folder(desk, batch_id) / "approval.json", {
            "batch_id": batch_id, "approved_by": actor, "approved_at": ns.stamp(clock()),
            "estimated_max_usd_total": batch["estimated_max_usd_total"]})
    except FileExistsError:
        pass  # A resumed batch: its approval stands, and each request is still sent at most once.
    done = []
    for item in batch["items"]:
        request = item["request"]
        try:
            result = rr.send(desk, request["request_id"], story_now, actor, clock, batch_id,
                             request["estimated_max_usd"])
        except AccountsRefused as exc:
            done.append({"story_id": item["story_id"], "outcome": exc.code, "detail": str(exc)})
            if exc.code == "paid_drafting_disabled":
                break  # Nothing further can be sent; the rest stay unattempted for a later approval.
            continue
        done.append({"story_id": item["story_id"], "outcome": "sent" if result["sent"] else "already_attempted",
                     "attempt": result["attempt"]})
    return {"batch_id": batch_id, "items": done, "statement": (
        "Each request was sent at most once; approving this batch again sends only those not yet attempted.")}


# ---------------------------------------------------------------- the assisted path

def packet(desk: news_views.Desk, batch_id: str, now: datetime) -> dict:
    """What an assistant (or an editor) annotates the batch from: the same rules, format and material the model would
    get, and the reply's shape. Reads only."""
    batch = load(desk, batch_id)
    found = news_views.world(desk, now)
    items = []
    for item in batch["items"]:
        story = found["stories"].get(item["story_id"])
        if story is None or story["material"]["material_sha256"] != item["material_sha256"]:
            items.append({"story_id": item["story_id"], "skip": "The story's material changed since the preview."})
            continue
        items.append({"story_id": item["story_id"], "material_sha256": item["material_sha256"],
                      "material": rr.payload(story["story_id"], story["title"], story["material"]["reports"],
                                             rr.held_texts(story, desk.texts))})
    return {"batch_version": BATCH_VERSION, "batch_id": batch_id, "versions": rr.versions(),
            "rules": rr.system_prompt(), "format": nr.response_schema(), "items": items,
            "reply": {"batch_id": batch_id, "annotations": [
                {"story_id": "...", "material_sha256": "...", "annotation": {"report_kind": "...", "...": "..."}}]}}


def import_annotations(desk: news_views.Desk, batch_id: str, reply: object, tool: str, model: str | None, actor: str,
                       clock) -> dict:
    """Save each annotation as an ``assisted`` one of its story's material, checked against the schema and its quotes
    against the material; repeating an import saves nothing new."""
    batch = load(desk, batch_id)
    if batch["method"] != "assisted":
        raise AccountsRefused(409, "not_an_assisted_batch", "This batch is prepared by the model in this application.")
    if not isinstance(reply, dict) or reply.get("batch_id") != batch_id or \
            not isinstance(reply.get("annotations"), list):
        raise AccountsRefused(422, "invalid_request", "An annotations file is {batch_id, annotations: [...]} for this "
                                                      "batch.")
    preparation = story_briefs.assistant_preparation(tool, model, actor, f"Imported for batch {batch_id}.")
    items = {item["story_id"]: item for item in batch["items"]}
    found = news_views.world(desk, clock())
    done = []
    for entry in reply["annotations"]:
        story_id = entry.get("story_id") if isinstance(entry, dict) else None
        item = items.get(story_id)
        if item is None:
            done.append({"story_id": story_id, "outcome": "not_in_batch"})
            continue
        story = found["stories"].get(story_id)
        if story is None or entry.get("material_sha256") != item["material_sha256"] or \
                story["material"]["material_sha256"] != item["material_sha256"]:
            done.append({"story_id": story_id, "outcome": "story_changed", "detail": (
                "The annotation was not written from the story's material as it is now; it was not saved.")})
            continue
        try:
            annotation = nr.validated(entry.get("annotation"))
        except nr.AnnotationRejected as exc:
            done.append({"story_id": story_id, "outcome": "rejected", "detail": str(exc)})
            continue
        checked = nr.check_evidence(annotation, rr.sources(story["material"]["reports"],
                                                           rr.held_texts(story, desk.texts)))
        digest = hashlib.sha256(json.dumps(annotation, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        result, created = nr.record(desk.newsroom, story_id, item["material_sha256"], {
            "method": "assisted", "outcome": "annotated", "annotation": annotation, "evidence": checked,
            "versions": batch["versions"], "preparation": {**preparation, "batch_id": batch_id}},
            actor, clock(), f"ri-{batch_id[7:]}-{story_id[6:]}-{digest}")
        done.append({"story_id": story_id, "outcome": "saved" if created else "already_saved",
                     "state": result["state"], "quotes_found": checked["found"],
                     "quotes_not_found": checked["not_found"]})
    return {"batch_id": batch_id, "items": done}
