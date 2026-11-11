"""The local operator's curation plan (news-curation-plan-0.1): the News desk's explicit actions written down in one
JSON file and applied from the command line (``python -m second_order news curate --plan FILE``).

Every action is one the Admin desk performs, through the same function: merge and retitle stories (news_stories), create
a topic, link or unlink a development and mark a priority (news_topics), save a brief version and publish or withdraw a
brief (story_briefs). Each is recorded in the newsroom with the local operator as the actor, the action's reason and an
idempotency key made from the plan's own key for that action, so applying the same plan again changes nothing, and an
action changed under a key already used is refused (``idempotency_conflict``) rather than applied twice. Actions apply
in order, each in its own transaction; the first refusal stops the plan and says which action it was and what was done
before it.

``check`` only reads: it checks every action's shape and targets against the newsroom and the reports as they are now
(and the plan's own earlier actions), runs each brief through the content rules and the guard, and says what would stop
its publication. Nothing here fetches, calls a model or charges anything; a brief's material is the story's material at
the moment the action applies (story_briefs.material).

The plan: ``{"plan_version": "news-curation-plan-0.1", "reason": <default reason>, "actions": [...]}``, each action
``{"key": <4 to 60 of A-Z a-z 0-9 _ ->, "do": <action>, "reason": <optional>, ...}``:

- ``merge``: story, into; ``title``: story, title;
- ``topic``: title, summary; later actions name the new topic as ``"@<its key>"``;
- ``link``: topic, story, label (optional); ``unlink``: topic, story;
- ``brief``: story, method (editorial, extract or assisted), content (story-brief-0.2), based_on (optional), publish
  (optional, false by default: true publishes the new version as its own recorded action); an ``assisted`` brief (one
  written with an AI assistant) names it: ``assistant: {tool, model (optional)}``, as the operator declares it;
- ``review``: story, version, note (optional): the operator states that they read that version (publishing is not
  reviewing); ``assess``: story, verdict (insufficient or sufficient), reason: a judgement of the story's material as it
  is when the action applies;
- ``correct``: story, version, method (assisted), assistant, publish (optional): a version that was written with an AI
  assistant but recorded otherwise gets a correcting version with the same content and material, naming the assistant;
- ``publish``: story, version; ``withdraw``: story;
- ``priority``: target (a story, a topic or "@<key>"), level (major or none), until (an ISO time with offset, or null).
"""
from datetime import datetime
import re
from typing import Callable

from . import news_rank, news_stories, news_topics, news_views, story_briefs
from .accounts import AccountsRefused

PLAN_VERSION = "news-curation-plan-0.1"
KEY = re.compile(r"[A-Za-z0-9_-]{4,60}")
FIELDS = {
    "merge": ({"story", "into"}, set()),
    "title": ({"story", "title"}, set()),
    "topic": ({"title"}, {"summary"}),
    "link": ({"topic", "story"}, {"label"}),
    "unlink": ({"topic", "story"}, set()),
    "brief": ({"story", "method", "content"}, {"based_on", "publish", "assistant"}),
    "review": ({"story", "version"}, {"note"}),
    "assess": ({"story", "verdict"}, set()),
    "correct": ({"story", "version", "method", "assistant"}, {"publish"}),
    "publish": ({"story", "version"}, set()),
    "withdraw": ({"story"}, set()),
    "priority": ({"target", "level", "until"}, set()),
}


class PlanRefused(ValueError):
    """The plan file itself is malformed; nothing was applied."""


def read_plan(plan: object) -> list[dict]:
    """The plan's actions, each with its reason filled in; PlanRefused for any malformed part."""
    if not isinstance(plan, dict) or set(plan) - {"plan_version", "reason", "actions"} or \
            plan.get("plan_version") != PLAN_VERSION or not isinstance(plan.get("actions"), list) or \
            not plan["actions"]:
        raise PlanRefused(f"A plan is {{plan_version: {PLAN_VERSION}, reason, actions: [one or more]}}.")
    default = plan.get("reason")
    actions, keys = [], set()
    for position, action in enumerate(plan["actions"], start=1):
        where = f"Action {position}"
        if not isinstance(action, dict) or action.get("do") not in FIELDS:
            raise PlanRefused(f"{where} names what it does (do: {', '.join(FIELDS)}).")
        required, optional = FIELDS[action["do"]]
        given = set(action) - {"key", "do", "reason"}
        if not required <= given or given - required - optional:
            raise PlanRefused(f"{where} ({action['do']}) has {', '.join(sorted(required))}"
                              + (f" and optionally {', '.join(sorted(optional))}" if optional else "") + ".")
        key = action.get("key")
        if not isinstance(key, str) or not KEY.fullmatch(key) or key in keys:
            raise PlanRefused(f"{where} has its own key: 4 to 60 letters, digits, - or _, used once in the plan.")
        keys.add(key)
        reason = action.get("reason", default)
        if not isinstance(reason, str) or not reason.strip():
            raise PlanRefused(f"{where} has a reason, its own or the plan's.")
        actions.append({**action, "reason": reason})
    return actions


def _idempotency(key: str, suffix: str = "") -> str:
    return f"plan-{key}{suffix}"


def _topic(value: object, made: dict[str, str]) -> str:
    if isinstance(value, str) and value.startswith("@"):
        if value[1:] not in made:
            raise AccountsRefused(422, "invalid_request", f"{value} names no earlier topic action of this plan.")
        return made[value[1:]]
    if not isinstance(value, str):
        raise AccountsRefused(422, "invalid_request", "A topic is a topic ID or \"@<key>\".")
    return value


def _brief_problems(action: dict, story: dict, joined: set[str]) -> list[str]:
    """What the content rules and the guard say of a brief action against the story's material now, with the material
    of stories the plan merges into it before (``joined``)."""
    used = {row["entry_id"] for row in story["material"]["reports"]} | joined
    if not used:
        return [story["material"]["statement"]]
    content = story_briefs.checked_content(action["content"], used)
    return story_briefs.publishable(content, story_briefs.guard(content))


def check(desk: news_views.Desk, actions: list[dict], now: datetime) -> dict:
    """Every action against the newsroom and the reports as they are now; writes nothing."""
    found = news_views.world(desk, now)
    stories, topics = set(found["stories"]), set(found["topics"])
    made: dict[str, str] = {}
    joined: dict[str, set[str]] = {}  # A story's material gained from the plan's earlier merges into it.
    rows = []
    for action in actions:
        problems: list[str] = []
        try:
            kind = action["do"]
            story_id = action.get("story")
            if story_id is not None and story_id not in stories:
                problems.append(f"{story_id} is not a current story (unknown, or merged into another).")
            if kind == "merge" and action["into"] not in stories:
                problems.append(f"{action['into']} is not a current story.")
            if kind == "topic":
                made[action["key"]] = news_topics.topic_id_for(_idempotency(action["key"]))
                topics.add(made[action["key"]])
            if kind in ("link", "unlink") and _topic(action["topic"], made) not in topics:
                problems.append(f"{action['topic']} is not a topic.")
            if kind == "priority":
                target = _topic(action["target"], made)
                if target not in stories and target not in topics:
                    problems.append(f"{action['target']} is neither a current story nor a topic.")
            if kind == "brief" and action["method"] == "assisted":
                assistant = action.get("assistant") or {}
                story_briefs.assistant_preparation(assistant.get("tool"), assistant.get("model"), "check")
            elif kind == "brief" and action["method"] not in story_briefs.EDITOR_METHODS:
                problems.append("A plan's brief is editorial, extract or assisted.")
            if kind == "brief" and not problems:
                problems += _brief_problems(action, found["stories"][story_id], joined.get(story_id, set()))
                if action.get("publish") is not True:
                    problems = [f"(not published by this plan) {problem}" for problem in problems]
            if kind == "merge" and not problems:
                stories.discard(story_id)
                joined.setdefault(action["into"], set()).update(
                    {row["entry_id"] for row in found["stories"][story_id]["material"]["reports"]},
                    joined.pop(story_id, set()))
        except AccountsRefused as exc:
            problems.append(str(exc))
        rows.append({"key": action["key"], "do": action["do"], "ok": not problems, "problems": problems})
    return {"plan_version": PLAN_VERSION, "checked": rows, "written": 0,
            "statement": "Checked only: nothing was written, requested or sent."}


def apply(desk: news_views.Desk, actions: list[dict], actor: str, clock: Callable[[], datetime]) -> dict:
    """Each action in order, as its own recorded operation; the first refusal stops the plan."""
    newsroom = desk.newsroom
    made: dict[str, str] = {}
    applied: list[dict] = []

    def story_now(story_id: str) -> dict:
        found = news_views.world(desk, clock())
        if story_id not in found["stories"]:
            raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
        return found["stories"][story_id]

    for action in actions:
        key, kind, reason = action["key"], action["do"], action["reason"]
        base = {"reason": reason, "idempotency_key": _idempotency(key)}
        try:
            if kind == "merge":
                result, created = news_stories.merge(newsroom, action["story"], {**base, "into": action["into"]},
                                                     actor, clock())
            elif kind == "title":
                result, created = news_stories.retitle(newsroom, action["story"], {**base, "title": action["title"]},
                                                       actor, clock())
            elif kind == "topic":
                result, created = news_topics.create(newsroom, {**base, "title": action["title"],
                                                                "summary": action.get("summary", "")}, actor, clock())
                made[key] = result["topic_id"]
            elif kind in ("link", "unlink"):
                result, created = news_topics.link(newsroom, _topic(action["topic"], made), {
                    **base, "story_id": action["story"], "action": kind, "label": action.get("label", "")},
                    actor, clock())
            elif kind == "priority":
                target = _topic(action["target"], made)
                result, created = news_topics.prioritise(newsroom, {
                    **base, "target_kind": "topic" if target.startswith("topic-") else "story", "target_id": target,
                    "level": action["level"], "until": action["until"]}, actor, clock())
            elif kind == "brief":
                method, preparation = action["method"], None
                if method == "assisted":
                    assistant = action.get("assistant") or {}
                    preparation = story_briefs.assistant_preparation(assistant.get("tool"), assistant.get("model"),
                                                                     actor, f"Applied from curation plan key {key}.")
                elif method not in story_briefs.EDITOR_METHODS:
                    raise AccountsRefused(422, "invalid_request", "A plan's brief is editorial, extract or assisted.")
                result, created = story_briefs.add_version(newsroom, action["story"], {
                    **base, "content": action["content"], "method": method,
                    "based_on": action.get("based_on")}, story_now(action["story"])["material"], actor, clock(),
                    method=method, preparation=preparation)
                if action.get("publish") is True:
                    applied.append({"key": key, "do": kind, "created": created, "result": result})
                    kind = "publish"
                    result, created = story_briefs.publish(newsroom, action["story"], {
                        "version": result["version"], "reason": reason,
                        "idempotency_key": _idempotency(key, "-pub")}, actor, clock())
            elif kind == "correct":
                assistant = action.get("assistant") or {}
                preparation = story_briefs.assistant_preparation(assistant.get("tool"), assistant.get("model"),
                                                                 actor, f"Correction from curation plan key {key}.")
                result, created = story_briefs.correct_authorship(newsroom, action["story"], {
                    **base, "version": action["version"], "method": action["method"]}, preparation, actor, clock())
                if action.get("publish") is True:
                    applied.append({"key": key, "do": kind, "created": created, "result": result})
                    kind = "publish"
                    result, created = story_briefs.publish(newsroom, action["story"], {
                        "version": result["version"], "reason": reason,
                        "idempotency_key": _idempotency(key, "-pub")}, actor, clock())
            elif kind == "review":
                result, created = story_briefs.review(newsroom, action["story"], {
                    "version": action["version"], "note": action.get("note", ""),
                    "idempotency_key": base["idempotency_key"]}, actor, clock())
            elif kind == "assess":
                material = story_now(action["story"])["material"]
                result, created = story_briefs.assess(newsroom, action["story"], {
                    **base, "verdict": action["verdict"], "material_sha256": material["material_sha256"]}, material,
                    actor, clock())
            elif kind in ("publish", "withdraw"):
                result, created = story_briefs.publish(newsroom, action["story"], {
                    **base, "version": action["version"] if kind == "publish" else None}, actor, clock())
        except AccountsRefused as exc:
            return {"plan_version": PLAN_VERSION, "applied": applied, "stopped": {
                "key": key, "do": kind, "code": exc.code, "detail": str(exc), **exc.extra},
                "statement": "Stopped at this action; the ones before it are recorded. Nothing was requested or sent."}
        applied.append({"key": key, "do": kind, "created": created, "result": result})
    return {"plan_version": PLAN_VERSION, "applied": applied, "stopped": None,
            "statement": ("Every action is recorded in the newsroom with the local operator, its reason and its key; "
                          "applying this plan again changes nothing. Nothing was requested or sent.")}


def story_rows(desk: news_views.Desk, now: datetime, view: str, limit: int) -> dict:
    """The stories as the operator picks them for a plan (read-only): ID, times, publishers, material and brief."""
    found = news_views.world(desk, now)
    stories = list(found["stories"].values())
    chosen = news_rank.hot(stories, now) if view == "hot" else news_rank.latest(stories)
    rows = []
    for story in chosen[:limit]:
        rows.append({"story_id": story["story_id"], "title": story["title"], "latest_at": story["latest_at"],
                     "publishers": sorted({row["publisher"] for row in story["reports"]}),
                     "reports": len(story["reports"]), "material_reports": len(story["material"]["reports"]),
                     "brief": news_views.card(story)["brief"]["state"], "interests": story["interests"],
                     "topics": [row["title"] for row in story["topics"]], "hot": story["rank"]["hot"]})
    return {"view": view, "as_of": now.isoformat(timespec="seconds"), "shown": len(rows), "of": len(chosen),
            "stories": rows, "ungrouped": len(found["ungrouped"])}


def draft(desk: news_views.Desk, story_id: str, now: datetime) -> dict:
    """The $0 starting draft from the material's own words, as the desk's draft route gives it; records nothing."""
    found = news_views.world(desk, now)
    if story_id not in found["stories"]:
        raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
    story = found["stories"][story_id]
    return {"story_id": story_id, "title": story["title"],
            "content": story_briefs.extract_draft(story, story["material"]), "method": "extract",
            "material": story["material"], "reports": [{key: row[key] for key in (
                "entry_id", "publisher", "role_label", "title", "excerpt", "link", "at", "at_basis", "material")}
                for row in story["reports"]], "recorded": False}

