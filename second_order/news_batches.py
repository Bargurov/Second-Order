"""Brief coverage and batch preparation of the important stories (news-coverage-0.1, news-batch-0.1).

Coverage says, for each story, whether a reader opening it gets a useful prepared brief: ``ready`` (a published brief
of the story's material as it is now), ``update`` (a published brief of earlier material), ``drafted`` (a saved version
of the current material awaiting the editors' publication), ``pending`` (material that may be summarised and is enough
for a brief, and no version of it), ``insufficient`` (headlines alone, or judged too thin), ``withdrawn`` and
``restricted`` (no report whose publisher allows a summary). The important stories are Hot now's, in its order
(news_rank, which lists only stories whose economic relevance is established); nothing is hidden to improve the count:
the current stories still awaiting a relevance assessment or an editor are counted beside them, by state.

A batch prepares the important stories that need a brief, before readers open them. ``preview`` selects, by the ranking
and the material's state, up to ``limit`` Hot now stories that are ``pending`` or ``update`` (or the stories the
operator names, each of which must be listed among the news: assessed as relevant, or marked as major by the editors),
and records the selection once (data/newsroom/batches/<batch ID>/batch.json, write-once): each story,
its material (its SHA-256, whether it is full text, partial text or excerpts, and how many publication texts could still
be retrieved), its existing brief, the preparation method and, for a paid model draft, the exact saved request
(brief_drafting.preview) with its planning estimate and the batch's total. The batch ID is made from the method and the
selected stories' materials, so previewing the same selection again finds the same batch.

Two preparation methods:

- ``model``: the in-application AI draft (brief_drafting, two stages from brief-prompt-10). Each item holds its story's
  next exact request: stage 1 (the evidence and figures) or, once stage 1 is validated for the same inputs, stage 2
  (the interpretation and brief); a story whose draft stopped (a stage that failed is never sent again) is left out
  with the reason. ``approve`` repeats the batch ID and the total estimate the preview showed, with
  approve_paid_requests true, and sends each item's saved request once, in order, under brief_drafting's rules (one
  attempt per request, ever; a validated stage 1 prepares its stage 2 without sending it; a stage 2 that passes
  becomes an unpublished version; a judgement of insufficient material is recorded instead). A later preview of the
  same stories makes a new batch of their stage-2 requests, approved with its own total; the stage-2 planning
  estimate a stage-1 batch shows is not approved by it. An interrupted batch is resumed by approving it again: items
  already attempted are reported, never sent again; an item whose inputs changed since the preview is skipped.
  Nothing is sent unless the server was started for paid drafting with a key.
- ``assisted``: an AI assistant outside this application (or an editor) writes the drafts from an exported packet
  (``packet``: the rules, the schema and each item's material with its texts). ``import_drafts`` saves each as an
  ``assisted`` version naming the tool the operator declares, or records that the material is insufficient; repeating
  an import saves nothing new.

Publishing is the operator's separate, explicit decision (``publish``): each item's new version for the story's current
material is published if the guard finds nothing to stop it, with the operator's reason; when the operator states that
they read the versions, that is recorded as a review of each. Reading coverage or a batch reads files only.

Economic explanations (news-batch-0.2, story_economics) are prepared by the same batches: a draft is a complete brief
with its explanation (or a statement that the evidence is insufficient for one), written from the material, the
story's context bundle when the operator built one (econ_context) and the framework notes. A story whose published
brief has no current explanation (``pending``, ``outdated`` (newer context gathered for it included), or ``failed``
after a refused import or a failed draft; news_explanations) is selected like a story without a brief, and its new
version is based on the published one.
``backfill`` selects, instead of Hot now's stories, every listed story that needs one, newest first, up to ``limit``;
naming stories selects exactly those. Every refused import is recorded with the batch (imports/), so a failure is
shown as such and never silently dropped.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from . import (brief_drafting, econ_context, econ_framework, market_store, news_explanations, news_rank,
               news_relevance, news_texts, news_views, newsroom_store as ns, story_briefs, story_economics)
from .accounts import AccountsRefused
from .news_stories import checked_reason

COVERAGE_VERSION = "news-coverage-0.1"
BATCH_VERSION = "news-batch-0.2"  # 0.2: economic explanations, context bundles and backfill.
STATES = ("ready", "update", "drafted", "pending", "insufficient", "withdrawn", "restricted")
METHODS = ("model", "assisted")
DEFAULT_LIMIT = 10
MAX_LIMIT = 25
BATCH_ID = re.compile(r"batch-[0-9a-f]{16}")


# ---------------------------------------------------------------- coverage

def _current_version(folded: dict, story: dict) -> dict | None:
    """The latest saved version prepared from the story's material as it is now, published or not."""
    rows = [row for row in folded["briefs"].get(story["story_id"], [])
            if row["material_sha256"] == story["material"]["material_sha256"]]
    return rows[-1] if rows else None


def state_of(folded: dict, story: dict) -> str:
    """Whether a reader opening this story gets a useful prepared brief, and if not, why."""
    if not story["material"]["reports"]:
        return "restricted"
    if story["brief"] is not None:
        return "ready" if news_views.brief_current(story) else "update"
    if story.get("insufficient"):
        return "insufficient"
    if _current_version(folded, story) is not None:
        return "drafted"
    return "withdrawn" if story["publication"] is not None else "pending"


def _texts_open(folder: Path | None, story: dict) -> int:
    """How many of the story's material reports have a publication text that could still be retrieved."""
    if folder is None:
        return 0
    return sum(1 for row in story["reports"] if row["material"] == "permitted" and
               story["texts"][row["entry_id"]]["state"] == "not_retrieved")


def _row(found: dict, story: dict, folder: Path | None, failed: dict) -> dict:
    material = story["material"]
    return {"story_id": story["story_id"], "title": story["title"], "latest_at": story["latest_at"],
            "score": story["rank"]["score"], "hot": story["rank"]["hot"], "state": state_of(found["folded"], story),
            "explanation": news_explanations.state_of(found["folded"], story, failed),
            "material": {"coverage": material["coverage"], "reports": len(material["reports"]),
                         "texts": sum(1 for row in material["reports"] if row.get("text")),
                         "texts_open": _texts_open(folder, story)},
            "published_version": story["brief"]["version"] if story["brief"] else None,
            "insufficient": story.get("insufficient"), "relevance": story["relevance"]["state"],
            "relevance_basis": story["relevance"]["basis"],
            "publishers": sorted({row["publisher"] for row in story["reports"]})}


def readiness(desk: news_views.Desk, accounts=None) -> dict:
    """What preparing briefs and analysing stories needs on this server, as configured now (read-only)."""
    from . import entitlements
    folded_schema = ns.state(desk.newsroom)["schema"]
    drafting = brief_drafting.status(desk.drafting)
    policy = entitlements.current_policy(accounts) if accounts is not None else None
    return {"newsroom": {"schema": folded_schema, "needs_upgrade": folded_schema not in (None, ns.SCHEMA_VERSION)},
            "paid_drafting": {"enabled": drafting["enabled"], "detail": drafting["detail"]},
            "texts": {"kept": desk.texts is not None},
            "credit_policy": {"published": policy is not None, "detail": (
                "Credit terms are published: deeper analyses can be quoted." if policy is not None else
                "No credit terms are published, so no deeper analysis can be quoted or run. An administrator publishes "
                "them under Policy & settings; nothing here chooses prices.")} if accounts is not None else None}


def coverage(desk: news_views.Desk, now: datetime, accounts=None) -> dict:
    """The brief coverage of the important stories (Hot now, in order) and of every story; reads only."""
    found = news_views.world(desk, now)
    failed = news_explanations.failures(desk.newsroom.path.parent)
    stories = list(found["stories"].values())
    hot = news_rank.hot(stories, now)
    rows = [_row(found, story, desk.texts, failed) for story in hot]
    count = lambda selection: {state: sum(1 for row in selection if row["state"] == state)  # noqa: E731
                               for state in STATES}
    explained = lambda selection: {state: sum(1 for row in selection if row["explanation"] == state)  # noqa: E731
                                   for state in news_explanations.STATES}
    everything = [_row(found, story, desk.texts, failed) for story in stories]
    listed = [row for row, story in zip(everything, stories) if news_rank.listed(story)]
    eligible = [row for row in rows if row["state"] not in ("restricted", "insufficient")]
    current = [story for story in stories if not story["rank"]["older"]]
    relevance = {state: sum(1 for story in current if story["relevance"]["state"] == state)
                 for state in news_relevance.STATES}
    return {"coverage_version": COVERAGE_VERSION, "as_of": ns.stamp(now),
            "important": {"stories": len(rows), "eligible": len(eligible), "counts": count(rows),
                          "ready_share_of_eligible": (round(sum(1 for row in eligible if row["state"] == "ready") /
                                                            len(eligible), 3) if eligible else None),
                          "rows": rows},
            "all": {"stories": len(everything), "counts": count(everything)},
            "explanations": {"explanations_version": news_explanations.EXPLANATIONS_VERSION,
                             "analysis_version": story_economics.ANALYSIS_VERSION,
                             "important": explained(rows),
                             "listed": {"stories": len(listed), "counts": explained(listed)},
                             "statement": (
                                 "Whether a reader gets a shared economic explanation. Ready: published for the "
                                 "material as it is now. Insufficient: its evidence was judged too thin. Drafted: "
                                 "awaiting publication. Failed: the latest preparation was refused or failed. "
                                 "Outdated: prepared from earlier material or an earlier method. Pending: none yet. "
                                 "Restricted: no report may be summarised. Not listed: not in the economic news.")},
            "current_relevance": {"stories": len(current), "counts": relevance, "statement": (
                f"Every story with a report from the last {news_rank.HOT_HOURS // 24} days, by its relevance: only "
                "relevant ones (and those the editors mark as major) are important stories; the rest are listed apart "
                "for readers, or left out when assessed as outside the scope.")},
            "readiness": readiness(desk, accounts),
            "statement": ("Important stories are Hot now's, in its order: current stories assessed as economic "
                          "developments, or marked as major by the editors; eligible ones are neither restricted "
                          "nor too thin for a brief. Ready: a published brief of the story's "
                          "material as it is now. Update: a published brief of earlier material. Drafted: a saved "
                          "version awaiting publication. Pending: enough permitted material and no version. "
                          "Insufficient: headlines alone or judged too thin. Restricted: no report whose publisher "
                          "allows a summary; those stories stay listed with their headlines.")}


# ---------------------------------------------------------------- batches

def _folder(desk: news_views.Desk, batch_id: str) -> Path:
    return desk.newsroom.path.parent / "batches" / batch_id


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


NEEDS_EXPLANATION = ("pending", "outdated", "failed")


def needs(folded: dict, story: dict, failed: dict) -> bool:
    """Whether a batch should prepare this story: it needs a brief (pending, update), or its published brief has no
    current economic explanation."""
    state = state_of(folded, story)
    return state in ("pending", "update") or (
        state == "ready" and news_explanations.state_of(folded, story, failed) in NEEDS_EXPLANATION)


def select(found: dict, now: datetime, limit: int, story_ids: list[str] | None = None, backfill: bool = False,
           failed: dict | None = None) -> tuple[list[dict], list[dict]]:
    """(the stories a batch prepares, the ones it leaves and why): Hot now's stories that need a brief or an
    explanation, in its order, at most ``limit``; with ``backfill``, every listed story that needs one, newest first;
    or the named stories (each must be listed and need one)."""
    folded, stories, failed = found["folded"], found["stories"], failed or {}

    def left_row(story: dict) -> dict:
        return {"story_id": story["story_id"], "title": story["title"], "state": state_of(folded, story),
                "relevance": story["relevance"]["state"],
                "explanation": news_explanations.state_of(folded, story, failed)}

    if story_ids:
        chosen, left = [], []
        for story_id in story_ids:
            story = stories.get(story_id)
            if story is None:
                raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
            (chosen if needs(folded, story, failed) and news_rank.listed(story) else left).append(story)
        return chosen[:limit], [left_row(story) for story in left]
    if backfill:
        pool = sorted((story for story in stories.values() if news_rank.listed(story)),
                      key=lambda story: (story["latest_at"], story["story_id"]), reverse=True)
    else:
        pool = news_rank.hot(list(stories.values()), now)
    chosen = [story for story in pool if needs(folded, story, failed)]
    left = [left_row(story) for story in pool if story not in chosen[:limit]]
    return chosen[:limit], left


def _item(desk: news_views.Desk, found: dict, story: dict, method: str, failed: dict) -> dict:
    material = story["material"]
    bundle = econ_context.current(desk, story)
    item = {"story_id": story["story_id"], "title": story["title"], "score": story["rank"]["score"],
            "state": state_of(found["folded"], story), "material_sha256": material["material_sha256"],
            "explanation_state": news_explanations.state_of(found["folded"], story, failed),
            "context": econ_context.summary(bundle),
            "material": {"coverage": material["coverage"], "statement": material["statement"],
                         "reports": len(material["reports"]),
                         "texts": sum(1 for row in material["reports"] if row.get("text")),
                         "texts_open": _texts_open(desk.texts, story)},
            "published_version": story["brief"]["version"] if story["brief"] else None,
            "action": "prepare" if not story["brief"] else "update" if not news_views.brief_current(story)
            else "explain"}
    if method == "model":
        drafted = brief_drafting.preview(desk, story)
        item["draft"] = {key: drafted[key] for key in ("draft_id", "stage", "request_sha256", "model", "max_tokens")}
        item["draft"]["estimated_max_usd"] = drafted["estimate"]["estimated_real_run_if_output_reaches_max_usd"]
        planned = drafted["stages"][1]
        item["workflow"] = {"state": drafted["state"], "detail": drafted["detail"],
                            "followup_estimated_max_usd": _usd(planned["estimate"]) if drafted["stage"] == 1 and
                            planned["estimate"] else None}
    return item


def _usd(estimate: dict) -> float:
    return estimate["estimated_real_run_if_output_reaches_max_usd"]


def preview(desk: news_views.Desk, now: datetime, method: str, limit: int = DEFAULT_LIMIT,
            story_ids: list[str] | None = None, actor: str = "local-operator",
            backfill: bool = False) -> tuple[dict, bool]:
    """Select and record a batch (once); a paid batch also saves each item's exact request. Nothing is sent."""
    if method not in METHODS:
        raise AccountsRefused(422, "invalid_request", f"The method is {' or '.join(METHODS)}.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        raise AccountsRefused(422, "invalid_request", f"A batch holds 1 to {MAX_LIMIT} stories.")
    found = news_views.world(desk, now)
    failed = news_explanations.failures(desk.newsroom.path.parent)
    chosen, left = select(found, now, limit, story_ids, backfill, failed)
    items = []
    if method == "model":  # Each story's next stage (brief_drafting): its exact request is saved, nothing is sent.
        for story in chosen:
            item = _item(desk, found, story, method, failed)
            if item["workflow"]["state"].startswith("awaiting"):
                items.append(item)
            else:
                left.append({"story_id": story["story_id"], "title": story["title"], "state": state_of(
                    found["folded"], story), "relevance": story["relevance"]["state"],
                    "explanation": news_explanations.state_of(found["folded"], story, failed),
                    "drafting": item["workflow"]["detail"]})
        chosen = [story for story in chosen if any(item["story_id"] == story["story_id"] for item in items)]
    if not chosen:
        raise AccountsRefused(409, "nothing_to_prepare", "No selected story needs a brief or an economic "
                                                         "explanation that can be prepared now: every one is ready, "
                                                         "drafted, insufficient, restricted or has a model draft that "
                                                         "stopped.", left=left)
    drafts = {item["story_id"]: item["draft"]["draft_id"] for item in items}
    identity = {"batch_version": BATCH_VERSION, "method": method, "prompt_version": brief_drafting.PROMPT_VERSION,
                "analysis_version": story_economics.ANALYSIS_VERSION, **econ_framework.summary(),
                "items": [[story["story_id"], story["material"]["material_sha256"],
                           (econ_context.current(desk, story) or {}).get("bundle_id")] +
                          ([drafts[story["story_id"]]] if method == "model" else []) for story in chosen]}
    batch_id = "batch-" + ns.sha256_of(identity)[:16]
    folder = _folder(desk, batch_id)
    existing = _read(folder / "batch.json")
    if existing is not None:
        return existing, False
    if method != "model":
        items = [_item(desk, found, story, method, failed) for story in chosen]
    total = round(sum(item["draft"]["estimated_max_usd"] for item in items), 4) if method == "model" else None
    followup = [item["workflow"]["followup_estimated_max_usd"] for item in items if method == "model" and
                item["workflow"]["followup_estimated_max_usd"] is not None]
    stages = sorted({item["draft"]["stage"] for item in items}) if method == "model" else None
    record = {"batch_version": BATCH_VERSION, "batch_id": batch_id, "method": method,
              "prompt_version": brief_drafting.PROMPT_VERSION, "analysis_version": story_economics.ANALYSIS_VERSION,
              **econ_framework.summary(), "selection": "named" if story_ids else "backfill" if backfill else "hot",
              "created_at": ns.stamp(now), "created_by": actor,
              "items": items, "left": left, "estimated_max_usd_total": total, "stages": stages,
              "followup_estimated_max_usd_total": round(sum(followup), 4) if followup else None,
              "texts_open": sum(item["material"]["texts_open"] for item in items),
              "statement": ("Nothing was sent or published. " + (
                  "Each item's next exact request is saved (stage 1, the evidence and figures, or stage 2, the "
                  "interpretation and brief); approving the batch's total sends each once, never again. A stage 1 "
                  "that passes the checks prepares its stage 2 without sending it: preview the batch again to approve "
                  "those exact requests and their own total. The follow-up total is a planning estimate only, not "
                  "approved by this batch." if method == "model" else
                  "Export the packet, have the drafts written with an AI assistant or by an editor, then import them; "
                  "they are labelled as such."))}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        market_store.write_exclusive(folder / "batch.json", record)
    except FileExistsError:
        return _read(folder / "batch.json"), False
    return record, True


def _batch_version(folded: dict, batch: dict, item: dict) -> dict | None:
    """The version this batch prepared for an item, if one was saved (a model draft's, or an import's)."""
    wanted = (item.get("draft") or {}).get("draft_id")
    for row in reversed(folded["briefs"].get(item["story_id"], [])):
        prepared = row["preparation"] or {}
        model = prepared.get("model") or {}
        if (wanted and wanted in [model.get("draft_id"), *(model.get("draft_ids") or [])]) or \
                prepared.get("batch_id") == batch["batch_id"]:
            return row  # A two-stage draft's version is found from either stage's batch.
    return None


def status(desk: news_views.Desk, batch_id: str, now: datetime) -> dict:
    """Each item as it is now: its material since the preview, its preparation, its version and publication."""
    batch = load(desk, batch_id)
    found = news_views.world(desk, now)
    folded = found["folded"]
    failed = news_explanations.failures(desk.newsroom.path.parent)
    rows = []
    for item in batch["items"]:
        story = found["stories"].get(item["story_id"])
        row = {"story_id": item["story_id"], "title": item["title"]}
        if story is None:
            rows.append({**row, "state": "gone", "detail": "The story was merged or no longer has reports."})
            continue
        version = _batch_version(folded, batch, item)
        attempt = brief_drafting.attempt_state(brief_drafting._folder(desk, item["draft"]["draft_id"])) \
            if batch["method"] == "model" else None
        judged = ns.assessment(folded, item["story_id"], item["material_sha256"])
        published = story["brief"]["version"] if story["brief"] else None
        economics = (version or {}).get("content", {}).get("economics") if version else None
        row.update(stage=(item.get("draft") or {}).get("stage"),
                   explanation=economics["status"] if economics else None,
                   explanation_state=news_explanations.state_of(folded, story, failed),
                   refused=[entry for entry in failed.get(item["story_id"], [])
                            if entry["source"] == batch["batch_id"]],
                   material_changed=story["material"]["material_sha256"] != item["material_sha256"],
                   attempt=attempt, version=version["version"] if version else None,
                   problems=story_briefs.publishable(version["content"], version["guard"]) if version else None,
                   published=version is not None and published == version["version"],
                   insufficient=judged["reason"] if judged and judged["verdict"] == "insufficient" else None,
                   coverage_state=state_of(folded, story))
        rows.append(row)
    return {**{key: batch[key] for key in ("batch_version", "batch_id", "method", "created_at",
                                           "estimated_max_usd_total")}, "items": rows,
            "approval": _read(_folder(desk, batch_id) / "approval.json")}


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
        raise AccountsRefused(409, "paid_drafting_disabled", brief_drafting.NOT_ENABLED)
    folder = _folder(desk, batch_id)
    try:
        market_store.write_exclusive(folder / "approval.json", {
            "batch_id": batch_id, "approved_by": actor, "approved_at": ns.stamp(clock()),
            "estimated_max_usd_total": batch["estimated_max_usd_total"]})
    except FileExistsError:
        pass  # A resumed batch: its approval stands, and each request is still sent at most once.
    done = []
    for item in batch["items"]:
        draft = item["draft"]
        state = brief_drafting.attempt_state(brief_drafting._folder(desk, draft["draft_id"]))
        if state["state"] != "not_attempted":
            done.append({"story_id": item["story_id"], "outcome": "already_attempted", "stage": draft.get("stage"),
                         "attempt": state})
            continue
        try:
            result, sent = brief_drafting.approve(desk, draft["draft_id"], {
                "request_sha256": draft["request_sha256"], "approve_paid_request": True,
                "estimated_max_usd": draft["estimated_max_usd"]}, story_now, actor, clock)
        except AccountsRefused as exc:
            done.append({"story_id": item["story_id"], "outcome": exc.code, "detail": str(exc)})
            if exc.code == "paid_drafting_disabled":
                break  # Nothing further can be sent; the rest stay unattempted for a later approval.
            continue
        done.append({"story_id": item["story_id"], "outcome": "sent" if sent else "already_attempted",
                     "stage": draft.get("stage"), "attempt": result["attempt"], "next": result.get("next")})
    return {"batch_id": batch_id, "items": done, "statement": (
        "Each request was sent at most once; approving this batch again sends only those not yet attempted. A stage 1 "
        "that passed its checks has its stage 2 prepared, not sent: preview a batch again to approve those.")}


# ---------------------------------------------------------------- the assisted path

def packet(desk: news_views.Desk, batch_id: str, now: datetime) -> dict:
    """What an assistant (or an editor) writes the batch's drafts from: the rules, the shape and each item's material,
    with the retained publication texts. Reads only."""
    batch = load(desk, batch_id)
    found = news_views.world(desk, now)
    items = []
    for item in batch["items"]:
        story = found["stories"].get(item["story_id"])
        if story is None or story["material"]["material_sha256"] != item["material_sha256"]:
            items.append({"story_id": item["story_id"], "skip": "The story's material changed since the preview."})
            continue
        reports = []
        for row in story["material"]["reports"]:
            text = row.get("text")
            held = news_texts.text_of(desk.texts, {"entry_id": row["entry_id"], "text_sha256": text["text_sha256"]}) \
                if text and desk.texts is not None else None
            reports.append({"entry_id": row["entry_id"], "publisher": row["publisher"], "role": row["role"],
                            "title": row["title"], "published": row["published"], "link": row["link"],
                            "text_state": text["state"] if held else "excerpt", "text": held,
                            "excerpt": None if held else row["excerpt"]})
        bundle = _bundle(desk, story, item)
        items.append({"story_id": item["story_id"], "title": story["title"], "material_sha256": item["material_sha256"],
                      "first_reported": story["first_at"], "action": item.get("action"),
                      "statement": story["material"]["statement"], "reports": reports,
                      "published_brief": story["brief"]["content"] if story["brief"] else None,
                      "context": bundle["items"] if bundle else [],
                      "context_bundle": econ_context.summary(bundle)})
    found_notes = econ_framework.framework()
    return {"batch_version": BATCH_VERSION, "batch_id": batch_id,
            "rules": f"{brief_drafting.SYSTEM} {brief_drafting.ECONOMICS_RULES}",
            "brief_shape": brief_drafting.SCHEMA,
            "framework": {"framework_version": found_notes["framework_version"],
                          "statement": found_notes["statement"], "notes": list(found_notes["notes"].values())},
            "subjects": econ_framework.SUBJECTS, "forms": econ_framework.FORMS,
            "respondents": econ_framework.RESPONDENTS, "items": items,
            "reply": {"batch_id": batch_id, "drafts": [{"story_id": "...", "material_sha256": "...", "brief": {
                "headline": "...", "summary": "...", "facts": [{"text": "...", "reports": ["<entry_id>"]}],
                "implications": [{"text": "..."}], "themes": [], "uncertainties": [], "missing": [],
                "economics": {"status": "explained or insufficient_evidence", "insufficient_reason": None,
                              "change": {"stage": "...", "instrument": "...", "form": "...", "respondents": None,
                                         "text": "...", "basis": ["fact:1"]},
                              "significance": {"text": "...", "basis": ["fact:1"]}, "main_uncertainty": "...",
                              "figures": [], "calculations": [], "assumptions": [{"id": "a1", "text": "..."}],
                              "channels": [{"id": "m1", "scope": "micro", "support": "bounded_inference", "note": None,
                                            "text": "... could ...",
                                            "steps": ["..."], "affected": [{"kind": "firms", "name": "...",
                                                                            "how": "..."}],
                                            "conditions": None, "horizon": "months", "basis": ["fact:1"],
                                            "assumptions": []}],
                              "second_order": [], "alternatives": [{"kind": "offsetting_force",
                                                                    "support": "bounded_inference", "text": "...",
                                                                    "basis": [], "assumptions": ["a1"]}],
                              "watch": [{"observable": "...", "would": "support", "text": "..."}]}}},
                {"story_id": "...", "material_sha256": "...", "insufficient_material": "why"}]}}


def _bundle(desk: news_views.Desk, story: dict, item: dict) -> dict | None:
    """The context bundle a batch item was previewed with (its ID is in the item), if it still exists."""
    wanted = (item.get("context") or {}).get("bundle_id")
    if wanted is None:
        return None
    return next((row for row in econ_context.bundles(desk, story["story_id"]) if row["bundle_id"] == wanted), None)


def _record_import(desk: news_views.Desk, batch_id: str, drafts: dict, tool: str, model: str | None, actor: str,
                   at: str, done: list[dict], items: dict) -> None:
    """Keep what an import did (write-once per drafts file): every refusal is a recorded failure of its story."""
    digest = hashlib.sha256(json.dumps(drafts, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    folder = _folder(desk, batch_id) / "imports"
    folder.mkdir(parents=True, exist_ok=True)
    rows = [{**row, "material_sha256": items[row["story_id"]]["material_sha256"],
             "failed": row["outcome"] not in ("saved", "already_saved", "insufficient", "already_recorded",
                                              "story_changed")} for row in done if row.get("story_id") in items]
    try:
        market_store.write_exclusive(folder / f"import-{digest}.json", {
            "batch_id": batch_id, "at": at, "imported_by": actor, "tool": tool, "model": model,
            "drafts_sha256": hashlib.sha256(json.dumps(drafts, sort_keys=True).encode("utf-8")).hexdigest(),
            "items": rows})
    except FileExistsError:
        pass  # The same drafts file again: its outcomes were recorded the first time.


def import_drafts(desk: news_views.Desk, batch_id: str, drafts: object, tool: str, model: str | None, actor: str,
                  clock, check: bool = False) -> dict:
    """Save each draft as an ``assisted`` version of its story (or record its judgement of insufficient material),
    only for the material the batch was previewed on; repeating an import saves nothing new. With ``check``, each
    draft is checked exactly as an import would check it, and nothing is saved or recorded."""
    batch = load(desk, batch_id)
    if batch["method"] != "assisted":
        raise AccountsRefused(409, "not_an_assisted_batch", "This batch is prepared by the model in this application.")
    if not isinstance(drafts, dict) or drafts.get("batch_id") != batch_id or not isinstance(drafts.get("drafts"), list):
        raise AccountsRefused(422, "invalid_request", "A drafts file is {batch_id, drafts: [...]} for this batch.")
    items = {item["story_id"]: item for item in batch["items"]}
    found = news_views.world(desk, clock())
    done = []
    for draft in drafts["drafts"]:
        story_id = draft.get("story_id") if isinstance(draft, dict) else None
        item = items.get(story_id)
        if item is None:
            done.append({"story_id": story_id, "outcome": "not_in_batch"})
            continue
        story = found["stories"].get(story_id)
        if story is None or draft.get("material_sha256") != item["material_sha256"] or \
                story["material"]["material_sha256"] != item["material_sha256"]:
            done.append({"story_id": story_id, "outcome": "story_changed", "detail": (
                "The draft was not written from the story's material as it is now; it was not saved.")})
            continue
        digest = hashlib.sha256(json.dumps(draft, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        key = f"bi-{batch_id[6:]}-{story_id[6:]}-{digest}"
        preparation = story_briefs.assistant_preparation(tool, model, actor, f"Imported for batch {batch_id}.")
        bundle = _bundle(desk, story, item)
        if (item.get("context") or {}).get("bundle_id") and bundle is None:
            done.append({"story_id": story_id, "outcome": "context_missing", "detail": (
                "The context bundle this item was previewed with is not on this server; nothing was saved.")})
            continue
        basis = story_economics.evidence(story["material"], desk.texts, bundle, story["first_at"])
        if check:
            done.append(_checked_draft(story, draft, basis))
            continue
        try:
            if isinstance(draft.get("insufficient_material"), str) and draft["insufficient_material"].strip():
                result, created = story_briefs.assess(desk.newsroom, story_id, {
                    "material_sha256": item["material_sha256"], "verdict": "insufficient",
                    "reason": draft["insufficient_material"].strip()[:300], "idempotency_key": key},
                    story["material"], actor, clock(), method="ai_assistant")
                done.append({"story_id": story_id, "outcome": "insufficient" if created else "already_recorded"})
                continue
            result, created = story_briefs.add_version(desk.newsroom, story_id, {
                "content": draft.get("brief"), "based_on": story["brief"]["version"] if story["brief"] else None,
                "idempotency_key": key}, story["material"], actor, clock(), method="assisted",
                preparation={**preparation, "batch_id": batch_id}, basis=basis)
        except AccountsRefused as exc:
            done.append({"story_id": story_id, "outcome": exc.code, "detail": str(exc)})
            continue
        done.append({"story_id": story_id, "outcome": "saved" if created else "already_saved",
                     "version": result["version"], "publishable": result["publishable"]})
    if check:
        return {"batch_id": batch_id, "checked": True, "items": done,
                "statement": "Checked only: nothing was saved or recorded."}
    _record_import(desk, batch_id, drafts, tool, model, actor, ns.stamp(clock()), done, items)
    return {"batch_id": batch_id, "items": done}


def _checked_draft(story: dict, draft: dict, basis: dict) -> dict:
    """What importing this draft would do, without doing it: refused, or saved with what would stop publication."""
    if isinstance(draft.get("insufficient_material"), str) and draft["insufficient_material"].strip():
        return {"story_id": story["story_id"], "outcome": "would_record_insufficient"}
    used = {row["entry_id"] for row in story["material"]["reports"]}
    try:
        content = story_briefs.checked_content(draft.get("brief"), used, basis)
    except AccountsRefused as exc:
        return {"story_id": story["story_id"], "outcome": exc.code, "detail": str(exc)}
    found = story_briefs.guard(content)
    if "economics" in content:
        found["findings"] += story_economics.findings(content["economics"], basis)
    return {"story_id": story["story_id"], "outcome": "would_save",
            "problems": story_briefs.publishable(content, found)}


# ---------------------------------------------------------------- publication

def publish(desk: news_views.Desk, batch_id: str, form: dict, actor: str, clock) -> dict:
    """Publish each item's new version for the story's current material, when the guard finds nothing to stop it.
    ``form``: reason, reviewed (true only when the operator read every version published here)."""
    batch = load(desk, batch_id)
    reason = checked_reason(form.get("reason"))
    reviewed = form.get("reviewed")
    if not isinstance(reviewed, bool):
        raise AccountsRefused(422, "invalid_request", "reviewed is true only when you read each version, else false.")
    found = news_views.world(desk, clock())
    folded = found["folded"]
    done = []
    for item in batch["items"]:
        story = found["stories"].get(item["story_id"])
        version = _batch_version(folded, batch, item) if story else None
        if story is None or version is None:
            done.append({"story_id": item["story_id"], "outcome": "no_version"})
            continue
        if version["material_sha256"] != story["material"]["material_sha256"]:
            done.append({"story_id": item["story_id"], "outcome": "story_changed", "version": version["version"]})
            continue
        problems = story_briefs.publishable(version["content"], version["guard"])
        if problems:
            done.append({"story_id": item["story_id"], "outcome": "not_publishable", "version": version["version"],
                         "problems": problems})
            continue
        if story["brief"] is not None and story["brief"]["version"] == version["version"]:
            done.append({"story_id": item["story_id"], "outcome": "already_published", "version": version["version"]})
            continue
        key = f"bp-{batch_id[6:]}-{item['story_id'][6:]}-v{version['version']}"
        try:
            if reviewed:
                story_briefs.review(desk.newsroom, item["story_id"], {
                    "version": version["version"], "note": f"Read before publishing batch {batch_id}.",
                    "idempotency_key": f"br-{batch_id[6:]}-{item['story_id'][6:]}-v{version['version']}"},
                    actor, clock())
            story_briefs.publish(desk.newsroom, item["story_id"], {"version": version["version"], "reason": reason,
                                                                   "idempotency_key": key}, actor, clock())
        except AccountsRefused as exc:
            done.append({"story_id": item["story_id"], "outcome": exc.code, "detail": str(exc)})
            continue
        done.append({"story_id": item["story_id"], "outcome": "published", "version": version["version"],
                     "reviewed": reviewed})
    return {"batch_id": batch_id, "items": done}
