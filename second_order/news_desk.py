"""The News desk: the administrator's view of the news and the explicit actions that curate it (news-desk-view-0.1).

The desk shows the registry (news_registry) with each source's freshness, the reports not yet in a story, every story
with its reports, the rule or decision behind each membership, its brief versions with their guard findings and what
still stops publication, the pairs of stories that may cover one development (news_matching.candidates, never applied
by themselves), the topics with their timelines, and the ranking's points. Reading it only reads.

The actions are each one explicit POST of the Admin build: refresh the publisher feeds (requests each connected feed
once, under the usage policy's refresh cooldown and daily budget), group new reports (local), merge, detach and
retitle stories, create topics and link developments, mark priorities, save brief versions (written by the editors, or
a $0 draft compiled from the material's own words) and publish or withdraw one. A paid model draft is brief_drafting's,
only on a server started for it, after a visible cost preview and an explicit approval.
"""
from datetime import datetime

from . import news_matching, news_rank, news_relevance, news_stories, newsroom_store as ns, story_briefs
from .news_registry import REGISTRY_VERSION, entry_view
from .news_views import Desk, card, world

DESK_VIEW = "news-desk-view-0.1"


def _report_row(report: dict) -> dict:
    return {key: report[key] for key in ("entry_id", "version_sha256", "source", "publisher", "role_label", "title",
                                         "excerpt", "link", "published", "first_seen_at", "listing", "stale", "at",
                                         "at_basis", "material", "display", "synthetic")}


def _annotation_row(row: dict) -> dict:
    """One saved annotation or failed attempt, whole, with the decision the current rules make of it."""
    decided = news_relevance.decide(row["annotation"], row["evidence"]) if row["annotation"] is not None else None
    return {key: row[key] for key in ("event_id", "method", "outcome", "material_sha256", "annotation", "evidence",
                                      "versions", "preparation", "actor", "at")} | {"decision": decided}


def _story_row(found: dict, story: dict) -> dict:
    folded = found["folded"]
    record = folded["stories"][story["story_id"]]
    versions = []
    for row in folded["briefs"].get(story["story_id"], []):
        versions.append({"version": row["version"], "based_on": row["based_on"], "method": row["method"],
                         "content": row["content"], "material_sha256": row["material_sha256"],
                         "material_statement": row["material"]["statement"], "preparation": row["preparation"],
                         "guard": row["guard"], "problems": story_briefs.publishable(row["content"], row["guard"]),
                         "authorship": story_briefs.AUTHORSHIP[row["method"]],
                         "reviews": [{key: review[key] for key in ("reviewer", "at", "note")} for review in
                                     folded["reviews"].get((story["story_id"], row["version"]), [])],
                         "covers_current_material": row["material_sha256"] == story["material"]["material_sha256"],
                         "actor": row["actor"], "at": row["at"]})
    return {**card(story), "rank": story["rank"],
            "reports_detail": [{**_report_row(row), "text": story["texts"][row["entry_id"]]} for row in story["reports"]],
            "coverage_detail": story["coverage"], "founder_entry_id": record["founder_entry_id"],
            "history": [{key: row[key] for key in ("action", "entry_id", "basis", "actor", "at", "reason")}
                        for row in record["history"]],
            "title_event": record["title_event"],
            "merged_from": sorted(key for key, row in folded["merged_into"].items()
                                  if row["into_story_id"] == story["story_id"]),
            "material": story["material"], "versions": versions,
            "publications": folded["publications"].get(story["story_id"], []),
            "published_version": story["brief"]["version"] if story["brief"] else None,
            "priority": folded["priorities"].get(("story", story["story_id"])),
            "insufficient": story.get("insufficient"),
            "assessments": folded["assessments"].get(story["story_id"], []),
            "relevance": story["relevance"], "relevance_history": [_annotation_row(row) for row in folded["relevance"].get(
                story["story_id"], [])],
            "relevance_reviews": folded["relevance_reviews"].get(story["story_id"], [])}


def desk_view(desk: Desk, now: datetime, drafting: dict) -> dict:
    found = world(desk, now)
    stories = news_rank.latest(list(found["stories"].values()))
    reports = found["pool"]["reports"]
    topics = []
    for topic_id, topic in found["topics"].items():
        record = found["folded"]["topics"][topic_id]
        topics.append({"topic_id": topic_id, "title": topic["title"], "summary": topic["summary"],
                       "timeline": [{"story_id": story_id, "label": topic["labels"][story_id],
                                     "title": found["stories"][story_id]["title"],
                                     "first_at": found["stories"][story_id]["first_at"]}
                                    for story_id in topic["timeline"]],
                       "priority": topic["priority"], "actor": record["actor"], "at": record["at"],
                       "reason": record["reason"]})
    return {"desk_version": DESK_VIEW, "as_of": ns.stamp(now),
            "newsroom": {"exists": found["folded"]["exists"], "schema": ns.SCHEMA_VERSION},
            "registry": {"registry_version": REGISTRY_VERSION,
                         "publishers": [entry_view(publisher) for publisher in desk.publishers.values()]},
            "sources": found["pool"]["sources"],
            "ungrouped": [_report_row(reports[entry]) for entry in found["ungrouped"]],
            "stories": [_story_row(found, story) for story in stories],
            "suggestions": news_matching.candidates(found, now),
            "match_decisions": [{key: row[key] for key in ("story_a", "story_b", "decision", "method", "topic_id",
                                                           "reason", "actor", "at")}
                                for row in found["folded"]["match_decisions"][-30:]],
            "topics": sorted(topics, key=lambda row: row["at"], reverse=True),
            "rank": news_rank.explanation(),
            "match": {"match_version": news_matching.MATCH_VERSION, "statement": (
                "Grouping joins a report to a story only when it repeats a report's headline word for word (at least "
                f"{news_stories.SAME_TITLE_WORDS} words, within {news_stories.SAME_TITLE_HOURS} hours); every other "
                "report starts its own story. Stories that share distinctive names or figures are suggested with their "
                "evidence: decide whether they report the same development (merged), separate developments of one "
                "subject (linked to a topic) or different ones; a decided pair is not suggested again.")},
            "brief_rules": {"brief_version": story_briefs.BRIEF_VERSION, "guard_version": story_briefs.GUARD_VERSION,
                            "limits": story_briefs.LIMITS, "counts": story_briefs.COUNTS,
                            "theme_kinds": list(story_briefs.THEME_KINDS)},
            "drafting": drafting}
