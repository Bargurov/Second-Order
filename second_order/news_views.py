"""What users read of the news: stories, a story's page with its shared brief, topics and their timelines
(news-stories-view-0.3, news-story-view-0.3, news-topics-view-0.1).

Every view is built on read from saved records only: the newsroom's decisions (newsroom_store), the official and
publisher caches (news_reports) and the time of the read for the ranking (news_rank). Nothing is fetched, prepared,
grouped or written, no model is called and nothing is counted or charged. A user's payload carries no operator's
identity, idempotency key, membership history or unpublished brief version: those are the Admin desk's (news_desk).
A story whose reports' publishers allow no summary says so instead of showing one; a story without a published brief
says that no brief has been prepared; nothing is filled in from elsewhere, and no private analysis is ever shown here.

The news lists only stories whose economic relevance is established (news_relevance; news_rank.listed): a story
assessed as outside the economic news's scope is left out of every list (its page stays at its address and says why),
and a current story still awaiting an assessment or an editor is listed apart, under ``awaiting``, with its state in
words, so nothing unprepared is hidden and nothing unassessed is presented as economic news (0.3).
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import (brief_claims, econ_context, news_explanations, news_rank, news_relevance, news_reports, news_stories,
               news_texts, newsroom_store as ns, story_briefs, story_economics)
from .accounts import AccountsRefused
from .news_registry import PUBLISHERS, Publisher

STORIES_VIEW = "news-stories-view-0.5"  # 0.5: cards say who prepared a brief; sources have distinct names.
STORY_VIEW = "news-story-view-0.6"  # 0.6: a brief's earlier published versions and what the current one changed.
TOPICS_VIEW = "news-topics-view-0.1"
VIEWS = ("hot", "coverage", "latest", "interests")
RELATED_SHOWN = 8
NOT_FOUND = "Nothing is available at this address."


@dataclass(frozen=True)
class Desk:
    """Where the news lives on this server, chosen at startup: the newsroom store, the official and publisher caches,
    the deeper-analysis origin records, and the publisher registry (SYNTHETIC publishers are added only by tests and
    the demo launcher). ``fetcher`` is the publisher-feed fetcher (None: the network, built at each refresh) and
    ``drafting`` the paid brief sender (None unless the server was started with paid brief drafting)."""
    newsroom: ns.Newsroom
    inbox: Path
    feeds: Path
    deeper: Path
    publishers: dict[str, Publisher] = field(default_factory=lambda: dict(PUBLISHERS))
    fetcher: object = None
    drafting: object = None
    texts: Path | None = None  # Retained publication texts (news_texts); None: this desk keeps none.
    index: Path | None = None  # Articles attached from the GDELT index (news_index); None: this desk keeps none.
    text_fetcher: object = None  # The publication-text fetcher (None: the network, built at each explicit retrieval).


def story_index(desk: Desk) -> dict[str, str]:
    """Each grouped report's current story (merges followed), from the newsroom alone: what the feed-entry views link
    a headline to. Reads only; an absent newsroom is an empty index."""
    folded = ns.state(desk.newsroom)
    index = {}
    for entry, story_id in folded["entry_story"].items():
        target = ns.resolve_story(folded, story_id)
        if target is not None and target not in folded["merged_into"]:
            index[entry] = target
    return index


def world(desk: Desk, now: datetime) -> dict:
    """The newsroom's decisions joined with the reports the caches hold now, every live story ranked."""
    folded = ns.state(desk.newsroom)
    pool = news_reports.pool(desk.inbox, desk.feeds, desk.publishers, desk.index)
    reports = pool["reports"]
    texts = {entry: news_texts.text_state(desk.texts, report) for entry, report in reports.items()}
    names = news_reports.publisher_names(desk.publishers)
    stories = {}
    for story_id, story in folded["stories"].items():
        if story_id in folded["merged_into"]:
            continue
        rows = sorted((reports[entry] for entry in story["members"] if entry in reports),
                      key=lambda row: (row["at"], row["entry_id"]))
        if not rows:
            continue
        founder = reports.get(story["founder_entry_id"], rows[0])
        own = [row for row in rows if not row.get("indexed")] or rows  # Indexed coverage never makes a story newer.
        first = own[0]
        last = max(own, key=lambda row: (row["at"], row["entry_id"]))
        order = [topic["interest"] for row in rows for topic in row["topics"]]
        stories[story_id] = {
            "story_id": story_id, "title": story["title"] or founder["title"],
            "title_basis": "editors" if story["title"] else "first_report", "reports": rows,
            "first_at": first["at"], "first_basis": first["at_basis"], "latest_at": last["at"],
            "latest_basis": last["at_basis"], "coverage": news_stories.coverage(rows, names),
            "interests": list(dict.fromkeys(order)), "synthetic": any(row["synthetic"] for row in rows),
            "stale": all(row["stale"] for row in rows), "topics": [],
            "material": story_briefs.material(story_id, rows, texts), "texts": {row["entry_id"]: texts[row["entry_id"]]
                                                                            for row in rows}}
        stories[story_id]["context_bundle"] = econ_context.summary(econ_context.current(desk, stories[story_id]))
        stories[story_id]["insufficient"] = insufficient(folded, stories[story_id])
        stories[story_id]["relevance"] = news_relevance.relevance_of(folded, stories[story_id])
        stories[story_id]["interests"] = assessed_interests(stories[story_id])
    topics = {}
    for topic_id, topic in folded["topics"].items():
        linked = {}
        for (linked_topic, story_id), row in folded["links"].items():
            target = ns.resolve_story(folded, story_id) if linked_topic == topic_id else None
            if target in stories and target not in linked:
                linked[target] = row["label"]
        timeline = sorted(linked, key=lambda story_id: (stories[story_id]["first_at"], story_id))
        topics[topic_id] = {"topic_id": topic_id, "title": topic["title"], "summary": topic["summary"],
                            "timeline": timeline, "labels": linked,
                            "priority": folded["priorities"].get(("topic", topic_id))}
        for position, story_id in enumerate(timeline):
            stories[story_id]["topics"].append({
                "topic_id": topic_id, "title": topic["title"], "newest": position == len(timeline) - 1,
                "previous_at": stories[timeline[position - 1]]["first_at"] if position > 0 else None})
    for story_id, story in stories.items():
        own = folded["priorities"].get(("story", story_id))
        inherited = [topics[row["topic_id"]]["priority"] for row in story["topics"]]
        active = [row for row in [own, *inherited] if news_rank.priority_active(row, now)]
        newest = next((row for row in story["topics"] if row["newest"]), story["topics"][0] if story["topics"] else None)
        story["rank"] = news_rank.signals({**story, "priority": active[0] if active else None, "topic": newest}, now)
        story["brief"], story["publication"] = ns.published_brief(folded, story_id)
        story["brief_review"] = review_view(folded, story) if story["brief"] else None
    grouped = set(folded["entry_story"])
    return {"folded": folded, "pool": pool, "stories": stories, "topics": topics,
            "ungrouped": sorted(entry for entry in reports if entry not in grouped)}


# Interests that name one economic dimension of the relevance annotation (news_relevance). Found only by a word of a
# report (user_news.topics, basis "terms"), such an interest is kept when the assessment that established the story's
# relevance supports that dimension: "tariffs" on mobile internet are prices, not trade (seen 2026-10-26).
INTEREST_DIMENSION = {"trade": "trade", "employment": "employment"}


def assessed_interests(story: dict) -> list[str]:
    """The story's interests, less any found only by a word that its relevance assessment does not support. A story
    not assessed, judged by an editor or not relevant keeps every interest its reports' words give it."""
    relevance, annotation = story["relevance"], story["relevance"]["annotation"]
    if relevance["state"] != "relevant" or relevance["basis"] == "editor" or annotation is None:
        return story["interests"]
    supported = {row["dimension"] for row in annotation["dimensions"] if row["supported"]}
    own = {topic["interest"] for row in story["reports"] for topic in row["topics"] if topic["basis"] == "source"}
    return [interest for interest in story["interests"] if interest in own or interest not in INTEREST_DIMENSION or
            INTEREST_DIMENSION[interest] in supported]


HEADLINE_ONLY = ("Its sources give only a headline, which cannot support a useful brief. Read the reports at their "
                 "sources below.")


def insufficient(folded: dict, story: dict) -> str | None:
    """Why this story's material cannot support a useful brief, or None: a material of headlines alone, or a recorded
    assessment of this exact material (newsroom_store.assessment)."""
    material = story["material"]
    if not material["reports"]:
        return None
    judged = ns.assessment(folded, story["story_id"], material["material_sha256"])
    if judged is not None:
        return judged["reason"] if judged["verdict"] == "insufficient" else None
    return HEADLINE_ONLY if material["coverage"] == "headlines" else None


# ---------------------------------------------------------------- user projections

def _brief_state(story: dict) -> str:
    if story["brief"] is not None:
        return "published"
    if story["publication"] is not None:
        return "withdrawn"
    if not story["material"]["reports"]:
        return "not_permitted"
    return "insufficient" if story.get("insufficient") else "none"


BRIEF_NOTES = {
    "published": None,
    "withdrawn": "The editors withdrew this story's brief. The reports are listed below.",
    "not_permitted": ("No brief is prepared for this story: its reports' publishers grant no use for summaries or "
                      "analysis. Read them at their sources below."),
    "insufficient": "There is not enough material for a useful brief of this story.",
    "none": "No brief has been prepared for this story yet. The reports are listed below.",
}


def brief_note(story: dict) -> str | None:
    state = _brief_state(story)
    if state == "insufficient":
        return f"{BRIEF_NOTES['insufficient']} {story['insufficient']}"
    return BRIEF_NOTES[state]


def brief_current(story: dict) -> bool | None:
    """Whether the published brief was prepared from the story's material as it is now (None without a brief)."""
    brief = story["brief"]
    return None if brief is None else brief["material_sha256"] == story["material"]["material_sha256"]


def card(story: dict) -> dict:
    brief = story["brief"]
    lead = next((row for row in story["reports"] if row["excerpt"]), None)
    return {"story_id": story["story_id"], "title": story["title"], "first_at": story["first_at"],
            "first_basis": story["first_basis"], "latest_at": story["latest_at"],
            "latest_basis": story["latest_basis"], "reports": len(story["reports"]),
            "publishers": sorted({row["publisher"] for row in story["reports"]}),
            "coverage": {key: story["coverage"][key] for key in COVERAGE_KEYS},
            "interests": story["interests"], "topics": [{"topic_id": row["topic_id"], "title": row["title"]}
                                                        for row in story["topics"]],
            "brief": {"state": _brief_state(story), "summary": brief["content"]["summary"] if brief else None,
                      "current": brief_current(story),
                      "authorship": story_briefs.AUTHORSHIP[brief["method"]] if brief else None,
                      "review": story["brief_review"]["state"] if brief else None,
                      "explained": bool(brief and (brief["content"].get("economics") or {}).get("status") ==
                                        "explained")},
            "excerpt": {"publisher": lead["publisher"], "text": lead["excerpt"]} if lead and not brief else None,
            "relevance": {"state": story["relevance"]["state"],
                          "statement": news_relevance.STATE_TEXT[story["relevance"]["state"]]},
            "older": story["rank"]["older"], "stale": story["stale"], "synthetic": story["synthetic"],
            "signals": [{"signal": row["signal"], "text": row["text"]} for row in story["rank"]["signals"]]}


TEXT_KEYS = ("state", "characters", "retrieved_at", "partial_reason", "detail")
# What a card says of its coverage (story-coverage-0.3): publishers apart from reporting origins, origins by kind,
# confirmed reporting origins apart from possible ones (independence not established), and copies counted with an origin.
COVERAGE_KEYS = ("publishers", "origins", "news_origins", "official_origins", "company_origins", "reporting_origins",
                 "confirmed_news", "confirmed_official", "possible_news", "possible_official", "uncertain", "repeats",
                 "company_statements", "official_releases")


def text_view(state: dict) -> dict:
    """What a reader is told of a report's publication text: held in full or in part, not readable, or not held."""
    return {key: state.get(key) for key in TEXT_KEYS}


def _report_view(report: dict, unit: int, together: list[str], used: bool, text: dict) -> dict:
    return {**{key: report[key] for key in ("entry_id", "publisher", "role", "role_label", "kind", "title",
                                            "title_shortened", "excerpt", "excerpt_shortened", "link", "published",
                                            "first_seen_at", "listing", "stale", "attribution", "synthetic")},
            "unit": unit, "counted_together_because": together,
            "use": "material" if used else ("listed" if report["material"] != "permitted" else "permitted"),
            "text": text_view(text)}


def review_view(folded: dict, story: dict) -> dict:
    """What a reader is told about whether a person read the published version: only a recorded review says so."""
    brief = story["brief"]
    if story_briefs.AUTHORSHIP[brief["method"]] == "editor":
        return {"state": "written_by_editor", "statement": "Written by an editor."}
    reviews = folded["reviews"].get((story["story_id"], brief["version"]), [])
    if reviews:
        return {"state": "read_by_editor", "statement": (f"An editor read this version on {reviews[0]['at'][:10]} "
                                                         "(UTC).")}
    return {"state": "not_reviewed", "statement": "No editor has read this version: it was published as prepared."}


PREPARED_BY = {"editorial": "written by an editor", "extract": "compiled from the reports' own words by an editor",
               "model": "drafted by an AI model in this application", "assisted": "written with an AI assistant",
               "synthetic": "a SYNTHETIC example"}
EXPLANATION_CHANGE = {"explained": "Adds an economic explanation.",
                      "insufficient_evidence": "Says its evidence is insufficient for an economic explanation."}


def _changes(previous: dict, current: dict, method_of=lambda row: row["method"]) -> list[str]:
    """What the current version changed against the version readers were shown before it, from the records alone:
    the reports it rests on, their texts, its economic explanation, its context and who prepared it."""
    before = {row["entry_id"]: row for row in previous["material"]["reports"]}
    after = {row["entry_id"]: row for row in current["material"]["reports"]}
    fix = (current["preparation"] or {}).get("corrects")
    if fix:  # A correction of authorship: the same content, saying who really prepared it.
        return [f"Corrects who prepared version {fix['version']}: it was {PREPARED_BY[current['method']]}, not "
                f"{PREPARED_BY[fix['method']]} as first recorded. The content is unchanged."]
    rows = [f"Adds the report “{row['title']}” ({row['publisher']})." for entry, row in after.items()
            if entry not in before]
    rows += [f"No longer rests on “{row['title']}” ({row['publisher']})." for entry, row in before.items()
             if entry not in after]
    rows += [f"Uses the publication text of “{row['title']}” ({row['publisher']}), not only its feed excerpt."
             for entry, row in after.items() if entry in before and row.get("text") and not before[entry].get("text")]
    then, now = previous["content"].get("economics") or {}, current["content"].get("economics") or {}
    if now.get("status") != then.get("status"):
        rows.append(EXPLANATION_CHANGE.get(now.get("status"), "No longer carries an economic explanation."))
    elif now and now.get("analysis_version") != then.get("analysis_version"):
        rows.append(f"Its economic explanation was prepared again under a newer method ({then.get('analysis_version')}"
                    f" to {now.get('analysis_version')}).")
    context = lambda row: ((row["preparation"].get("analysis") or {}).get("context") or {}).get("bundle_id")  # noqa
    if context(current) and context(current) != context(previous):
        rows.append("Its explanation uses context gathered for this version (listed under how it was prepared).")
    if method_of(current) != method_of(previous):
        now, then = method_of(current), method_of(previous)
        rows.append(f"This version is {PREPARED_BY[now]}; the earlier one is {PREPARED_BY[then]}." if "synthetic" in
                    (now, then) else f"This version was {PREPARED_BY[now]}; the earlier one was {PREPARED_BY[then]}.")
    return rows or ["Prepared again from the same reports."]


def brief_revisions(folded: dict, story: dict) -> dict:
    """The versions readers were shown before the current one (newest first), and what the current one changed
    against the last of them. Every published version stays in the records; this reads them only."""
    versions = {row["version"]: row for row in folded["briefs"].get(story["story_id"], [])}
    corrected = {(row["preparation"] or {})["corrects"]["version"]: row["method"] for row in versions.values()
                 if (row["preparation"] or {}).get("corrects")}  # Who really prepared a version, once corrected.
    method_of = lambda row: corrected.get(row["version"], row["method"])  # noqa: E731
    publications = folded["publications"].get(story["story_id"], [])
    current = story["brief"]["version"]
    shown, seen = [], {current}
    for row in reversed(publications[:-1]):
        if row["version"] is not None and row["version"] not in seen:
            seen.add(row["version"])
            shown.append((row, versions[row["version"]]))
    earlier = [{"version": version["version"], "published_at": publication["at"], "prepared_at": version["at"],
                "method": method_of(version), "authorship": story_briefs.AUTHORSHIP[method_of(version)],
                "recorded_as": version["method"] if method_of(version) != version["method"] else None,
                "corrects": ((version["preparation"] or {}).get("corrects") or {}).get("version"),
                "headline": version["content"]["headline"], "summary": version["content"]["summary"],
                "reports": len(version["material"]["reports"]),
                "explained": (version["content"].get("economics") or {}).get("status") == "explained"}
               for publication, version in shown]
    return {"earlier": earlier, "changes": _changes(shown[0][1], story["brief"], method_of) if shown else [],
            "updated_at": publications[-1]["at"] if shown else None}


def brief_view(story: dict, folded: dict | None = None) -> dict | None:
    brief, publication = story["brief"], story["publication"]
    if brief is None:
        return None
    prepared = brief["material"]
    used = {row["entry_id"] for row in prepared["reports"]}
    since = [row for row in story["reports"] if row["entry_id"] not in used and
             row["first_seen_at"] > brief["preparation"]["prepared_at"]]
    current = brief_current(story)
    return {"brief_version": story_briefs.BRIEF_VERSION, "version": brief["version"], "content": brief["content"],
            "method": brief["method"], "method_label": story_briefs.METHOD_LABEL[brief["method"]],
            "authorship": story_briefs.AUTHORSHIP[brief["method"]],
            "review": review_view(folded or {"reviews": {}}, story), "current": current,
            "update_note": None if current else (
                "This brief was prepared from earlier material: the story's reports or their texts have changed since. "
                "An updated brief can be prepared by the editors."),
            "prepared_at": brief["at"], "published_at": publication["at"],
            "material": {"coverage": prepared["coverage"], "statement": prepared["statement"],
                         "reports": [{"entry_id": row["entry_id"], "publisher": row["publisher"], "title": row["title"]}
                                     for row in prepared["reports"]],
                         "not_used": [{"publisher": row["publisher"], "title": row["title"], "reason": row["reason"]}
                                      for row in prepared["not_used"]]},
            "reports_since": len(since), "synthetic": brief["method"] == "synthetic",
            "economics": story_economics.reader_view(brief["content"].get("economics"), brief["content"]["facts"],
                                                     brief["preparation"].get("analysis"),
                                                     brief["content"].get("claims")),
            # story-brief-0.4: who says what, only for a version that records claims (an earlier one reads as before).
            **({"claims": brief_claims.reader_view(brief["content"], prepared)} if "claims" in brief["content"] else {}),
            "context_statement": story_economics.context_statement(brief["content"].get("economics")),
            "revisions": brief_revisions(folded or {"briefs": {}, "publications": {}}, story),
            "statement": ("Reported facts and possible implications are kept apart. Nothing here is advice to buy or "
                          "sell, and no cause is claimed beyond what a source states.")}


def deeper_state(story: dict) -> dict:
    rows = story["material"]["reports"]
    if not rows:
        return {"available": False, "material_reports": 0, "reason": (
            "A deeper analysis needs material its publishers allow to be analysed; this story's reports grant no such "
            "use. If you have the right to use a publication, you can paste its text as a source of your own.")}
    if story.get("insufficient"):
        return {"available": False, "material_reports": len(rows), "reason": (
            f"Its material is too thin for an analysis: {story['insufficient']} If you have the publication, you can "
            "paste its text as a source of your own.")}
    if story["relevance"]["state"] == "outside_scope":
        who = "an editor" if story["relevance"]["basis"] == "editor" else "an AI-assisted assessment of its sources"
        return {"available": False, "material_reports": len(rows), "reason": (
            f"It was judged outside the economic news's scope by {who}: {story['relevance']['explanation']} A deeper "
            "analysis here is for economic developments.")}
    if not any(row["published_utc"] for row in rows):
        return {"available": False, "material_reports": len(rows), "reason": (
            "None of the reports it may use states a publication time, which an analysis needs. You can paste the "
            "publication as a source of your own with its time.")}
    return {"available": True, "material_reports": len(rows), "reason": None}


def story_page(found: dict, story_id: str, requested: str, failed: dict | None = None) -> dict:
    story = found["stories"][story_id]
    used = {row["entry_id"] for row in story["brief"]["material"]["reports"]} if story["brief"] else set()
    units = {entry: (index, unit["counted_together_because"]) for index, unit in
             enumerate(story["coverage"]["units"], start=1) for entry in unit["entries"]}
    related, seen = [], {story_id}
    for row in story["topics"]:
        topic = found["topics"][row["topic_id"]]
        for other in reversed(topic["timeline"]):
            if other not in seen:
                seen.add(other)
                related.append({"story_id": other, "title": found["stories"][other]["title"],
                                "first_at": found["stories"][other]["first_at"],
                                "first_basis": found["stories"][other]["first_basis"],
                                "label": topic["labels"][other] or None, "topic_id": row["topic_id"]})
    state = _brief_state(story)
    return {"view_version": STORY_VIEW, "story_id": story_id, "requested_id": requested,
            "merged": requested != story_id, "title": story["title"], "title_basis": story["title_basis"],
            "first_at": story["first_at"], "first_basis": story["first_basis"], "latest_at": story["latest_at"],
            "latest_basis": story["latest_basis"], "coverage": story["coverage"], "interests": story["interests"],
            "signals": [{"signal": row["signal"], "text": row["text"]} for row in story["rank"]["signals"]],
            "older": story["rank"]["older"], "stale": story["stale"], "synthetic": story["synthetic"],
            "brief_state": state, "brief_note": brief_note(story), "brief": brief_view(story, found["folded"]),
            "explanation": news_explanations.view(found["folded"], story, failed or {}),
            "relevance": news_relevance.reader_view(story["relevance"]),
            "sources": [_report_view(row, *units[row["entry_id"]], row["entry_id"] in used,
                                     story["texts"][row["entry_id"]]) for row in story["reports"]],
            "topics": [topic_card(found, row["topic_id"]) for row in story["topics"]],
            "related": related[:RELATED_SHOWN], "deeper": deeper_state(story),
            "statement": ("Read from this server's saved records: opening this page contacts no publisher, runs no "
                          "analysis and uses no credits.")}


def topic_card(found: dict, topic_id: str) -> dict:
    topic = found["topics"][topic_id]
    timeline = topic["timeline"]
    latest = found["stories"][timeline[-1]] if timeline else None
    return {"topic_id": topic_id, "title": topic["title"], "summary": topic["summary"],
            "developments": len(timeline), "latest_at": latest["latest_at"] if latest else None,
            "latest_title": latest["title"] if latest else None,
            "synthetic": any(found["stories"][story]["synthetic"] for story in timeline)}


def topic_page(found: dict, topic_id: str) -> dict:
    topic = found["topics"][topic_id]
    developments = []
    for story_id in topic["timeline"]:
        story = found["stories"][story_id]
        developments.append({**card(story), "label": topic["labels"][story_id] or None})
    return {"view_version": TOPICS_VIEW, **topic_card(found, topic_id), "timeline": developments,
            "statement": ("The developments the editors linked to this topic, in the order they were first reported. "
                          "Each is its own story with its own sources.")}


def _notes(found: dict) -> list[str]:
    notes = []
    if not found["folded"]["exists"] or not found["stories"]:
        notes.append("No stories have been put together on this server yet. An administrator groups the reports the "
                     "feeds have brought; nothing is filled in from elsewhere.")
    elif found["ungrouped"]:
        count = len(found["ungrouped"])
        notes.append(f"{count} newer report{'s are' if count != 1 else ' is'} not in a story yet; an administrator "
                     "groups them.")
    stale = [row["publisher"] for row in found["pool"]["sources"] if row["stale"]]
    if stale:
        notes.append(f"The latest retrieval of {', '.join(sorted(set(stale)))} did not succeed; their reports come "
                     "from an earlier retrieval.")
    return notes


def stories_view(desk: Desk, view: str, interests: list[str], now: datetime) -> dict:
    if view not in VIEWS:
        raise AccountsRefused(422, "invalid_request", "The view is hot, coverage, latest or interests.")
    found = world(desk, now)
    stories = list(found["stories"].values())
    if view == "hot":
        chosen = news_rank.hot(stories, now)
    elif view == "coverage":
        chosen = news_rank.most_covered(stories, now)
    else:
        chosen = [story for story in news_rank.latest(stories) if news_rank.listed(story)]
        if view == "interests":
            chosen = [story for story in chosen if set(story["interests"]) & set(interests)]
    awaiting = [] if view == "interests" else [
        story for story in news_rank.latest(stories)
        if not news_rank.listed(story) and story["relevance"]["state"] in AWAITING_STATES and
        not story["rank"]["older"]]
    notes = _notes(found)
    if view == "interests" and not interests:
        notes.insert(0, "You have not chosen interests yet, so none is selected by them. Choose them on Reports & "
                        "search, or read Hot now and Latest.")
    if view in ("hot", "coverage") and stories and not chosen:
        notes.insert(0, f"No story has a report from the last {news_rank.HOT_HOURS // 24} days. Latest lists every "
                        "story, older ones marked.")
    rank = news_rank.coverage_explanation() if view == "coverage" else news_rank.explanation()
    return {"view_version": STORIES_VIEW, "view": view, "as_of": ns.stamp(now), "rank": rank,
            "interests": interests, "stories": [card(story) for story in chosen],
            "awaiting": [card(story) for story in awaiting], "left_out": left_out(stories),
            "topics": _topic_cards(found)[:6],
            "sources": source_rows(found["pool"]["sources"]),
            "notes": notes,
            "statement": ("Stories are put together from the reports this server's feeds last retrieved. Reading this "
                          "page contacts no publisher, runs no analysis and uses no credits.")}


AWAITING_STATES = ("pending", "restricted", "needs_review", "unavailable", "insufficient")
SOURCE_KEYS = ("source", "publisher", "label", "role", "role_label", "state", "last_success_at", "stale", "reports",
               "display", "material", "attribution", "terms_url", "synthetic")


def source_rows(rows: list[dict]) -> list[dict]:
    """Each source as readers see it, with a name that tells it apart: the publisher's, followed by the feed's own
    title when the publisher has more than one feed ("U.S. Bureau of Labor Statistics: Consumer Price Index"). The
    source's key, its publisher and its reports are unchanged."""
    count: dict[str, int] = {}
    for row in rows:
        count[row["publisher"]] = count.get(row["publisher"], 0) + 1
    return [{**{key: row[key] for key in SOURCE_KEYS},
             "name": row["publisher"] if count[row["publisher"]] == 1 else
             f"{row['publisher']}: {row['label'].split(': ', 1)[-1]}"} for row in rows]


def left_out(stories: list[dict]) -> dict:
    """What the lists leave out, counted, so nothing is hidden silently: stories assessed as outside the scope, and
    older stories whose relevance was never established."""
    outside = sum(1 for story in stories if story["relevance"]["state"] == "outside_scope" and
                  not news_rank.listed(story))
    older = sum(1 for story in stories if not news_rank.listed(story) and story["rank"]["older"] and
                story["relevance"]["state"] in AWAITING_STATES)
    return {"outside_scope": outside, "older_unassessed": older, "statement": (
        f"{outside} {'story was' if outside == 1 else 'stories were'} assessed as outside the economic news's scope "
        f"and {older} older {'story was' if older == 1 else 'stories were'} never assessed; they are not listed, and "
        "each keeps its page at its address.")}


def story_view(desk: Desk, story_id: str, now: datetime) -> dict:
    found = world(desk, now)
    target = ns.resolve_story(found["folded"], story_id) if isinstance(story_id, str) else None
    if target not in found["stories"]:
        raise AccountsRefused(404, "not_found", NOT_FOUND)
    return story_page(found, target, story_id, news_explanations.failures(desk.newsroom.path.parent))


def _topic_cards(found: dict) -> list[dict]:
    """Every topic, the one with the most recent development first; topics without one last."""
    cards = [topic_card(found, topic_id) for topic_id in found["topics"]]
    return sorted(cards, key=lambda row: (row["latest_at"] is None, -(datetime.fromisoformat(row["latest_at"])
                                                                      .timestamp() if row["latest_at"] else 0),
                                          row["topic_id"]))


def topics_view(desk: Desk, now: datetime) -> dict:
    found = world(desk, now)
    return {"view_version": TOPICS_VIEW, "as_of": ns.stamp(now), "topics": _topic_cards(found), "notes": _notes(found)[:1],
            "statement": "Ongoing subjects the editors follow, each with its developments in the order they happened."}


def topic_view(desk: Desk, topic_id: str, now: datetime) -> dict:
    found = world(desk, now)
    if topic_id not in found["topics"]:
        raise AccountsRefused(404, "not_found", NOT_FOUND)
    return topic_page(found, topic_id)
