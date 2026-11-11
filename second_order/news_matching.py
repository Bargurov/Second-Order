"""Which stories report the same development despite different headlines (story-match-0.2), and the decisions about
them.

Grouping stays conservative: the only automatic rule is news_stories' same headline. Everything else is a suggestion
with its evidence, decided explicitly: ``candidates`` pairs current stories first reported within MATCH_HOURS of each
other that share distinctive anchors: names (words written with a capital inside a headline or an excerpt, and the
affected parties of a story's relevance annotation) and figures (numbers, amounts, percentages, from the headline, the
excerpt and the annotation's quoted magnitudes). An anchor is distinctive when few current stories name it (at most
DISTINCTIVE_SHARE of them, and never fewer than DISTINCTIVE_MIN): a president's or an institution's name shared by
half the news is not evidence. A pair needs MIN_SHARED distinctive anchors, or one distinctive name and one shared
figure. Each candidate carries its evidence (the shared anchors, the word overlap, the hours apart, the publishers)
and whether an AI assistant may judge it (only when both stories' material may be used by a model; otherwise an editor
judges it from the headlines, as for relevance).

``decide`` records one decision about a pair (``match_decisions``, newsroom-4), with its reason and who made it:
``same`` merges the later-founded story into the earlier one (news_stories.merge: its address then leads to the other,
and every membership row records the decision); ``related`` links both, as separate developments, to an ongoing topic
(an existing one, or a new one named in the decision); ``different`` only records the judgement. A decided pair is not
suggested again. Nothing here contacts a publisher or calls a model; candidates are computed on read from saved
records.

``topic_candidates`` (for update runs, news_updates) lists, for named stories, the ongoing topics one of whose
developments (of any age) shares distinctive names with the story by the same rule, so a genuine follow-up to an
older development can be related to its topic; deciding ``related`` with that topic links only the story not yet in
it, leaving each existing development's timeline label as it was.
"""
from datetime import datetime
import json
import re

from . import news_stories, news_topics, news_views, newsroom_store as ns
from .accounts import AccountsRefused
from .news_stories import STOPWORDS, checked_reason, headline_words
from .user_news import words

MATCH_VERSION = "story-match-0.2"
MATCH_HOURS = 72
CURRENT_DAYS = 7
DISTINCTIVE_SHARE = 0.03
DISTINCTIVE_MIN = 3
MIN_SHARED = 2
DECISIONS = ("same", "related", "different")
METHODS = ("editor", "assisted", "synthetic")
TOKEN = re.compile(r"[^\W_][\w.,%$€£'’-]*")
FIGURE = re.compile(r"\d")


YEAR = re.compile(r"(19|20)\d\d")
# Words that institutions and wires capitalise in nearly every item: never evidence that two items share a subject.
GENERIC = frozenset("""president commission commissioner minister ministers speech remarks conference council parliament
results study data presented announces announced announcement report reports fact sheet press release statement daily
news message interview keynote opening plenary debate honourable dear excellency ladies gentlemen member members
government administration department office secretary director chair agency federal national european united states
america american americans union house white committee board bank central world first new week year month today
mr mrs ms dr""".split())


def _figure(token: str) -> str | None:
    """An amount, a percentage or another number that is not a year or a day of the month ("$5 billion" and "5 billion"
    share "5"); None for anything else."""
    cleaned = token.strip(".,'’-").lstrip("$€£").replace(",", "")
    if not FIGURE.search(cleaned):
        return None
    digits = re.sub(r"\D", "", cleaned)
    if YEAR.fullmatch(digits) or (digits.isdigit() and len(digits) <= 2 and "%" not in cleaned and "." not in cleaned):
        return None
    return cleaned


def _distinct_words(token: str) -> set[str]:
    return {word for word in words(token) if word not in STOPWORDS and word not in GENERIC and len(word) > 2}


def _names(text: str | None, headline: bool) -> set[str]:
    """Names in a text: words written with a capital that do not start a sentence, apart from the generic words of
    official and wire copy. In a headline written in title case, only acronyms and words with a digit or an inner
    capital count, since every word there has a capital."""
    found = set()
    if not text:
        return found
    tokens = TOKEN.findall(text)
    lettered = [token for token in tokens if len(token) >= 4 and token[0].isalpha()]
    title_case = headline and lettered and sum(1 for token in lettered if token[0].isupper()) / len(lettered) >= 0.7
    previous_end = True
    for index, token in enumerate(tokens):
        bare = token.strip(".,'’-")
        special = len(bare) >= 2 and (bare.isupper() or any(char.isdigit() for char in bare) or
                                      any(char.isupper() for char in bare[1:]))
        if bare and bare[0].isupper() and (special or (not title_case and not previous_end and
                                                       not (headline and index == 0))):
            found |= _distinct_words(bare)
        previous_end = token.endswith((".", "!", "?", ":")) and not headline
    return found


def anchors(story: dict) -> dict:
    """The story's names and figures, from its headlines, excerpts and relevance annotation."""
    names, figures = set(), set()
    for row in story["reports"]:
        names |= _names(row["title"], headline=True) | _names(row["excerpt"], headline=False)
        figures |= {figure for token in TOKEN.findall(f"{row['title']} {row['excerpt'] or ''}")
                    if (figure := _figure(token))}
    annotation = (story.get("relevance") or {}).get("annotation")
    if annotation:
        for magnitude in annotation.get("magnitudes", []):
            figures |= {figure for token in TOKEN.findall(magnitude) if (figure := _figure(token))}
    return {"names": names, "figures": figures}


def _content(story: dict) -> set[str]:
    found = set()
    for row in story["reports"]:
        found |= {word for word in headline_words(row["title"]) + words(row["excerpt"])
                  if word not in STOPWORDS and len(word) > 2}
    return found


def _hours(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def _key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def decided(folded: dict) -> dict[tuple[str, str], dict]:
    return {(row["story_a"], row["story_b"]): row for row in folded.get("match_decisions", [])}


def _current(found: dict, now: datetime) -> list[dict]:
    return [story for story in found["stories"].values()
            if (now - datetime.fromisoformat(story["latest_at"])).days <= CURRENT_DAYS]


def _anchored(found: dict, stories: list[dict], current: list[dict]) -> tuple[dict, dict]:
    """(each story's names and figures, each story's distinctive names): a name is distinctive when few current stories
    name it. The annotation's affected parties count as names."""
    held = {story["story_id"]: anchors(story) for story in {row["story_id"]: row for row in current + stories}.values()}
    for story_id, anchor in held.items():
        rows = [row for row in found["folded"]["relevance"].get(story_id, []) if row["outcome"] == "annotated"]
        if rows:
            anchor["names"] |= {word for item in rows[-1]["annotation"]["affected"]
                                for word in _distinct_words(item["name"])}
    frequency: dict[str, int] = {}
    for story in current:
        for name in held[story["story_id"]]["names"]:
            frequency[name] = frequency.get(name, 0) + 1
    ceiling = max(DISTINCTIVE_MIN, int(len(current) * DISTINCTIVE_SHARE))
    return held, {story_id: {name for name in anchor["names"] if frequency.get(name, 0) <= ceiling}
                  for story_id, anchor in held.items()}


def candidates(found: dict, now: datetime, limit: int = 60) -> list[dict]:
    """Pairs of current stories that may report one development, with their evidence. Reads saved records only."""
    stories = _current(found, now)
    held, distinctive = _anchored(found, stories, stories)
    done = decided(found["folded"])
    topics = {}
    for (topic_id, story_id) in found["folded"]["links"]:
        topics.setdefault(ns.resolve_story(found["folded"], story_id), set()).add(topic_id)
    content = {story["story_id"]: _content(story) for story in stories}
    rows = []
    for index, first in enumerate(stories):
        for second in stories[index + 1:]:
            a, b = first["story_id"], second["story_id"]
            if _key(a, b) in done or topics.get(a, set()) & topics.get(b, set()) or \
                    _hours(first["first_at"], second["first_at"]) > MATCH_HOURS:
                continue
            names = distinctive[a] & distinctive[b]
            figures = held[a]["figures"] & held[b]["figures"]
            if not (len(names) >= MIN_SHARED or (names and figures)):
                continue
            union = content[a] | content[b]
            overlap = len(content[a] & content[b]) / len(union) if union else 0.0
            rows.append({"match_version": MATCH_VERSION, "stories": list(_key(a, b)),
                         "titles": {a: first["title"], b: second["title"]},
                         "publishers": {a: sorted({row["publisher"] for row in first["reports"]}),
                                        b: sorted({row["publisher"] for row in second["reports"]})},
                         "evidence": {"names": sorted(names), "figures": sorted(figures),
                                      "word_overlap": round(overlap, 2),
                                      "hours_apart": round(_hours(first["first_at"], second["first_at"]), 1)},
                         "cross_publisher": not ({row["publisher"] for row in first["reports"]} &
                                                 {row["publisher"] for row in second["reports"]}),
                         "assistant_may_judge": bool(first["material"]["reports"]) and
                         bool(second["material"]["reports"]),
                         "score": round(2 * len(names) + len(figures) + 5 * overlap, 2)})
    return sorted(rows, key=lambda row: (-row["score"], row["stories"]))[:limit]


def topic_candidates(found: dict, story_ids: list[str], now: datetime) -> list[dict]:
    """Ongoing topics that each named story may be a further development of: a topic one of whose developments (of
    any age) shares distinctive names with the story, by the same rule as ``candidates``, with the evidence. For the
    operator to link through a ``related`` decision, or to leave; nothing is linked here. Reads saved records only."""
    stories = found["stories"]
    named = [stories[story_id] for story_id in story_ids if story_id in stories]
    linked = [stories[other] for topic in found["topics"].values() for other in topic["timeline"]]
    held, distinctive = _anchored(found, named + linked, _current(found, now))
    rows = []
    for story in named:
        own = {row["topic_id"] for row in story["topics"]}
        for topic_id, topic in found["topics"].items():
            if topic_id in own:
                continue
            best = None
            for other in topic["timeline"]:
                names = distinctive[story["story_id"]] & distinctive[other]
                figures = held[story["story_id"]]["figures"] & held[other]["figures"]
                if (len(names) >= MIN_SHARED or (names and figures)) and \
                        (best is None or len(names) + len(figures) > len(best[1]) + len(best[2])):
                    best = (other, names, figures)
            if best is None:
                continue
            other = stories[best[0]]
            rows.append({"match_version": MATCH_VERSION, "story_id": story["story_id"], "title": story["title"],
                         "topic_id": topic_id, "topic_title": topic["title"], "with_story": other["story_id"],
                         "with_title": other["title"],
                         "evidence": {"names": sorted(best[1]), "figures": sorted(best[2]),
                                      "hours_after": round((datetime.fromisoformat(story["first_at"]) -
                                                            datetime.fromisoformat(other["first_at"]))
                                                           .total_seconds() / 3600, 1)},
                         "later_than_topic": all(stories[row]["first_at"] < story["first_at"]
                                                 for row in topic["timeline"]),
                         "assistant_may_judge": bool(story["material"]["reports"]) and
                         bool(other["material"]["reports"])})
    return sorted(rows, key=lambda row: (row["story_id"], row["topic_id"]))


def decide(desk: news_views.Desk, story_a: str, story_b: str, form: dict, method: str, preparation: dict, actor: str,
           moment: datetime) -> tuple[dict, bool]:
    """Record one decision about two stories (``form``: decision, reason, topic_id or topic_title for ``related``,
    idempotency_key) and carry it out: a merge for ``same``, topic links for ``related``."""
    if method not in METHODS:
        raise AccountsRefused(422, "invalid_request", f"method is one of {', '.join(METHODS)}.")
    decision = form.get("decision")
    if decision not in DECISIONS:
        raise AccountsRefused(422, "invalid_request", f"decision is one of {', '.join(DECISIONS)}.")
    reason = checked_reason(form.get("reason"))
    key = form.get("idempotency_key")
    if not isinstance(key, str) or not 8 <= len(key) <= 70:
        raise AccountsRefused(422, "invalid_request", "idempotency_key must be 8 to 70 letters, digits, - or _.")
    found = news_views.world(desk, moment)
    stories = found["stories"]
    a, b = _key(story_a, story_b)
    earlier = decided(found["folded"]).get((a, b))
    if earlier is not None:
        return {key: earlier[key] for key in ("story_a", "story_b", "decision", "method", "topic_id", "reason", "at")}, \
            False
    if a == b or a not in stories or b not in stories:
        raise AccountsRefused(409, "story_unavailable", "Both stories must exist now, differ and not be merged.")
    if method == "assisted" and not (stories[a]["material"]["reports"] and stories[b]["material"]["reports"]):
        raise AccountsRefused(409, "restricted", "An AI assistant may judge only stories whose material may be used by a "
                                                 "model; an editor judges this pair.")
    evidence = next((row["evidence"] for row in candidates(found, moment, limit=10_000) if row["stories"] == [a, b]),
                    None)
    if evidence is None and decision == "related" and form.get("topic_id"):  # A follow-up to an ongoing topic.
        evidence = next(({**row["evidence"], "topic_id": row["topic_id"], "with_story": row["with_story"]}
                         for row in topic_candidates(found, [a, b], moment) if row["topic_id"] == form["topic_id"]),
                        None)
    evidence = evidence or {"names": [], "figures": [], "note": "Decided without a suggestion."}
    topic_id = None
    if decision == "same":
        first, second = sorted((stories[a], stories[b]), key=lambda story: (story["first_at"], story["story_id"]))
        news_stories.merge(desk.newsroom, second["story_id"], {
            "into": first["story_id"], "reason": f"The same development: {reason}"[:300],
            "idempotency_key": f"{key}-merge"}, actor, moment)
    elif decision == "related":
        topic_id = form.get("topic_id")
        if topic_id is None:
            created, _ = news_topics.create(desk.newsroom, {
                "title": form.get("topic_title"), "summary": form.get("topic_summary") or "",
                "reason": reason, "idempotency_key": f"{key}-topic"}, actor, moment)
            topic_id = created["topic_id"]
        elif topic_id not in found["topics"]:
            raise AccountsRefused(404, "not_found", f"{topic_id} is not a topic.")
        linked = {ns.resolve_story(found["folded"], story) for (topic, story) in found["folded"]["links"]
                  if topic == topic_id}
        for story_id in (a, b):
            if story_id in linked:  # Already a development of this topic: linking again would relabel it.
                continue
            news_topics.link(desk.newsroom, topic_id, {"story_id": story_id, "action": "link", "label": "",
                                                       "reason": reason, "idempotency_key": f"{key}-{story_id[6:14]}"},
                             actor, moment)
    with desk.newsroom.writing() as connection:
        payload = {"story_a": a, "story_b": b, "decision": decision, "method": method, "topic_id": topic_id,
                   "reason": reason}
        done = ns.operation(connection, key, "match", actor, payload)
        if done is not None:
            return done, False
        at = ns.stamp(moment)
        connection.execute("INSERT INTO match_decisions (story_a, story_b, decision, method, topic_id, evidence, "
                           "preparation, reason, actor, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                           (a, b, decision, method, topic_id, json.dumps(evidence, sort_keys=True),
                            json.dumps(preparation, sort_keys=True), reason, actor, at))
        result = {**payload, "at": at}
        ns.record_operation(connection, key, "match", actor, payload, result, at)
    return result, True
