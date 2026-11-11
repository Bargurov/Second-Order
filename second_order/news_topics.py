"""Ongoing topics and the editors' priority marks (news-topic-0.1): the operator's explicit curation of the news.

A topic is a continuing subject (a trade dispute, a policy cycle) that separate developments belong to: each
development is a story (news_stories), linked to the topic by the operator with a short label for the timeline ("Canada
responds"), and unlinked the same way. A story may belong to several topics; nothing links a story to a topic by
itself. A priority mark says that a story or a topic is a major one until a stated time (at most news_rank's
MAX_PRIORITY_DAYS ahead); a later mark replaces it, and level "none" clears it. Every row is append-only and names who
decided, when and why (newsroom_store).
"""
from datetime import datetime
import hashlib

from . import news_rank, newsroom_store as ns
from .accounts import AccountsRefused
from .news_stories import checked_reason

TOPIC_VERSION = "news-topic-0.1"
MAX_TITLE = 120
MAX_SUMMARY = 600
MAX_LABEL = 120


def _text(value: object, limit: int, label: str, required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise AccountsRefused(422, "invalid_request", f"{label} has {'1' if required else '0'} to {limit} characters.")
    return value.strip()


def topic_id_for(idempotency_key: str) -> str:
    """A topic's stable ID: made from the key of the action that created it, so a repeat finds the same topic."""
    return "topic-" + hashlib.sha256(f"{TOPIC_VERSION}|{idempotency_key}".encode()).hexdigest()[:16]


def create(newsroom: ns.Newsroom, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """A new ongoing topic. ``form``: title, summary, reason, idempotency_key."""
    payload = {"title": _text(form.get("title"), MAX_TITLE, "A topic's title"),
               "summary": _text(form.get("summary"), MAX_SUMMARY, "A topic's summary", required=False),
               "reason": checked_reason(form.get("reason"))}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "topic", actor, payload)
        if done is not None:
            return done, False
        topic_id = topic_id_for(form["idempotency_key"])
        at = ns.stamp(moment)
        connection.execute("INSERT INTO topics VALUES (?, ?, ?, ?, ?, ?)",
                           (topic_id, payload["title"], payload["summary"], actor, at, payload["reason"]))
        result = {"topic_id": topic_id, "title": payload["title"], "at": at}
        ns.record_operation(connection, form["idempotency_key"], "topic", actor, payload, result, at)
    return result, True


def link(newsroom: ns.Newsroom, topic_id: str, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """Link a story to a topic as one of its developments, or unlink it. ``form``: story_id, action (link or unlink),
    label (the timeline's words for this development; empty for the story's own headline), reason, idempotency_key."""
    action = form.get("action")
    if action not in ("link", "unlink"):
        raise AccountsRefused(422, "invalid_request", "action is link or unlink.")
    payload = {"topic_id": topic_id, "story_id": form.get("story_id"), "action": action,
               "label": _text(form.get("label", ""), MAX_LABEL, "A development's label", required=False),
               "reason": checked_reason(form.get("reason"))}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "link", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM topics WHERE topic_id = ?", (topic_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        story = connection.execute("SELECT 1 FROM stories WHERE story_id = ? AND story_id NOT IN "
                                   "(SELECT story_id FROM story_merges)", (payload["story_id"],)).fetchone()
        if story is None:
            raise AccountsRefused(409, "story_unavailable", "That story does not exist or was merged into another.")
        latest = connection.execute("SELECT action FROM topic_links WHERE topic_id = ? AND story_id = ? ORDER BY "
                                    "event_id DESC LIMIT 1", (topic_id, payload["story_id"])).fetchone()
        linked = latest is not None and latest["action"] == "link"
        if action == "unlink" and not linked:  # Linking again only relabels the development.
            raise AccountsRefused(409, "story_unavailable", "That story is not linked to this topic.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO topic_links (topic_id, story_id, action, label, actor, at, reason) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)", (topic_id, payload["story_id"], action, payload["label"],
                                                            actor, at, payload["reason"]))
        result = {"topic_id": topic_id, "story_id": payload["story_id"], "action": action, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "link", actor, payload, result, at)
    return result, True


def prioritise(newsroom: ns.Newsroom, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """Mark a story or topic as major until a time, or clear its mark. ``form``: target_kind (story or topic),
    target_id, level (major or none), until (an ISO time with offset for major, null for none), reason,
    idempotency_key."""
    kind, level = form.get("target_kind"), form.get("level")
    if kind not in ("story", "topic") or level not in ("major", "none"):
        raise AccountsRefused(422, "invalid_request", "target_kind is story or topic; level is major or none.")
    if level == "major":
        try:
            until = news_rank.priority_until(form.get("until"), moment)
        except ValueError as exc:
            raise AccountsRefused(422, "invalid_request", str(exc)) from None
    elif form.get("until") is not None:
        raise AccountsRefused(422, "invalid_request", "Clearing a mark takes no end time (until is null).")
    else:
        until = None
    payload = {"target_kind": kind, "target_id": form.get("target_id"), "level": level, "until": until,
               "reason": checked_reason(form.get("reason"))}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "priority", actor, payload)
        if done is not None:
            return done, False
        table, column = ("stories", "story_id") if kind == "story" else ("topics", "topic_id")
        if connection.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (payload["target_id"],)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO priorities (target_kind, target_id, level, until, actor, at, reason) "
                           "VALUES (?, ?, ?, ?, ?, ?, ?)", (kind, payload["target_id"], level, until, actor, at,
                                                            payload["reason"]))
        result = {**{key: payload[key] for key in ("target_kind", "target_id", "level", "until")}, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "priority", actor, payload, result, at)
    return result, True
