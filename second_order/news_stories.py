"""Stories: which reports cover one development (story-match-0.1), and how independent that coverage is.

A report is one feed entry the caches hold (news_reports). Every report belongs to exactly one story once the operator
groups the news: the explicit, local ``group`` action puts each report not yet in a story either into the story of a
report it repeats, or into a new story of its own. Nothing is grouped on a read, and nothing contacts a publisher.

Matching is conservative. The only automatic rule is ``same-headline``: the two headlines are the same words (letters
and digits, NFKC, case-folded, after a trailing publisher credit such as " - Reuters" is set aside), at least
SAME_TITLE_WORDS of them, and the reports are within SAME_TITLE_HOURS of each other. Shared keywords never merge
stories by themselves: ``suggestions`` lists pairs of stories whose headlines share distinctive words (at least
SUGGEST_SHARED content words including a name or a figure, Jaccard at least SUGGEST_JACCARD, within SUGGEST_HOURS) for
the operator to merge or leave, and only the operator's explicit merge joins them. Every membership row records its
basis: the rule with its evidence, or the operator's action with a reason.

Coverage counts reporting origins (story-coverage-0.3), apart from publishers. Reports by one publisher are one origin.
Reports by different publishers with the same headline, nearly the same excerpt (word Jaccard at least
SAME_TEXT_JACCARD over excerpts of at least SAME_TEXT_WORDS words) or the same wire credit are one origin: several
sites republishing one wire report are one source, never several confirmations. An origin is a newsroom's own
reporting (``news``), an official statement (``official``: an official release, even when a news site republishes it)
or a company's statement (``company``: a press release, even republished), and only news and official origins are
reporting origins. Where independence cannot be established, the origin says so (``independence: unverified``, with
why): two origins whose headlines or excerpts are similar but not the same (Jaccard at least SIMILAR_JACCARD) may share
a source without a credit saying so, and a newsroom known only by its headline cannot be compared with the others'
text. The counts keep the two apart: a reporting origin is confirmed (``confirmed_news``, ``confirmed_official``) only
when its independence is established, and possible (``possible_news``, ``possible_official``) when it is not; none is
called independent first and qualified afterwards. Nothing here measures readership, popularity or market impact.
"""
from datetime import datetime
import hashlib
import json
import re

from . import newsroom_store as ns
from .accounts import AccountsRefused
from .user_news import words

MATCH_VERSION = "story-match-0.1"
COVERAGE_VERSION = "story-coverage-0.3"
SAME_TITLE_WORDS = 4
SAME_TITLE_HOURS = 72
SUGGEST_SHARED = 3
SUGGEST_JACCARD = 0.5
SUGGEST_HOURS = 48
SAME_TEXT_JACCARD = 0.8
SIMILAR_JACCARD = 0.6  # Similar but not the same text: a possible shared origin, recorded as uncertain.
SAME_TEXT_WORDS = 12
MAX_REASON = 300
# Credits a headline may end with (" - Reuters", " | CNBC"); set aside before comparing headlines.
CREDIT_SEPARATORS = re.compile(r"\s+[-|–—]\s+([^-|–—]{2,40})$")
WIRES = {"reuters": "Reuters", "associated press": "Associated Press", "ap": "Associated Press", "afp": "AFP",
         "agence france presse": "AFP", "bloomberg": "Bloomberg"}
WIRE_CREDIT = re.compile(r"^\s*(?:[A-Z][A-Za-z .,'-]{0,40}\s)?\((Reuters|AP|Associated Press|AFP|Bloomberg)\)\s*[-—–:]",
                         re.IGNORECASE)
STOPWORDS = frozenset("""a an and are as at be been but by for from has have he her his in into is it its of on or our
says said say she that the their them they this to was were will with after over new more than up down out about amid
as how what when where who why not no yes us you your we i new also could would should may might can just""".split())


def _hours(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def headline_words(title: str, names: set[str] = frozenset()) -> list[str]:
    """The headline's words with a trailing publisher or wire credit set aside."""
    credit = CREDIT_SEPARATORS.search(title)
    if credit and (credit.group(1).strip().casefold() in names or credit.group(1).strip().casefold() in WIRES):
        title = title[:credit.start()]
    return words(title)


def _anchors(title: str) -> set[str]:
    """Names and figures in a headline: words written with a capital after its first word, and words with a digit."""
    found = set()
    for index, token in enumerate(re.findall(r"[^\W_][\w.%$'-]*", title)):
        if any(char.isdigit() for char in token) or (index > 0 and token[0].isupper()):
            found.update(words(token))
    return found - STOPWORDS


def _content(found: list[str]) -> set[str]:
    return {word for word in found if word not in STOPWORDS and len(word) > 1}


def same_headline(a: dict, b: dict, names: set[str]) -> dict | None:
    """The automatic rule's evidence when ``b`` repeats ``a``'s headline, else None."""
    first, second = headline_words(a["title"], names), headline_words(b["title"], names)
    if first != second or len(first) < SAME_TITLE_WORDS:
        return None
    apart = _hours(a["at"], b["at"])
    if apart > SAME_TITLE_HOURS:
        return None
    return {"rule": f"{MATCH_VERSION}/same-headline", "with": a["entry_id"], "words": len(first),
            "hours_apart": round(apart, 1)}


def related_terms(a: dict, b: dict, names: set[str]) -> dict | None:
    """Why two reports might cover one development (for the operator to decide), else None."""
    first, second = _content(headline_words(a["title"], names)), _content(headline_words(b["title"], names))
    shared = first & second
    anchors = shared & _anchors(a["title"]) & _anchors(b["title"])
    union = first | second
    if len(shared) < SUGGEST_SHARED or not anchors or not union or len(shared) / len(union) < SUGGEST_JACCARD:
        return None
    apart = _hours(a["at"], b["at"])
    if apart > SUGGEST_HOURS:
        return None
    return {"rule": f"{MATCH_VERSION}/shared-terms", "shared": sorted(shared), "names_or_figures": sorted(anchors),
            "jaccard": round(len(shared) / len(union), 2), "hours_apart": round(apart, 1)}


def story_id_for(founder: str, founded_before: int) -> str:
    """A story's stable ID: from its founding report and how many stories that report founded before."""
    digest = hashlib.sha256(f"{MATCH_VERSION}|{founder}|{founded_before}".encode("utf-8")).hexdigest()
    return f"story-{digest[:16]}"


def _new_story(connection, founder: dict, basis: dict, actor: str, at: str, reason: str) -> str:
    before = connection.execute("SELECT COUNT(*) FROM stories WHERE founder_entry_id = ?",
                                (founder["entry_id"],)).fetchone()[0]
    story_id = story_id_for(founder["entry_id"], before)
    connection.execute("INSERT INTO stories VALUES (?, ?, ?, ?, ?)",
                       (story_id, founder["entry_id"], json.dumps(basis, sort_keys=True), actor, at))
    _add(connection, story_id, founder["entry_id"], basis, actor, at, reason)
    return story_id


def _add(connection, story_id: str, entry_id: str, basis: dict, actor: str, at: str, reason: str) -> None:
    connection.execute("INSERT INTO story_members (story_id, entry_id, action, basis, actor, at, reason) "
                       "VALUES (?, ?, 'add', ?, ?, ?, ?)", (story_id, entry_id, json.dumps(basis, sort_keys=True),
                                                           actor, at, reason))


def _remove(connection, story_id: str, entry_id: str, basis: dict, actor: str, at: str, reason: str) -> None:
    connection.execute("INSERT INTO story_members (story_id, entry_id, action, basis, actor, at, reason) "
                       "VALUES (?, ?, 'remove', ?, ?, ?, ?)", (story_id, entry_id, json.dumps(basis, sort_keys=True),
                                                              actor, at, reason))


def checked_reason(reason: object) -> str:
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_REASON:
        raise AccountsRefused(422, "invalid_request", f"A reason of 1 to {MAX_REASON} characters is required.")
    return reason.strip()


# ---------------------------------------------------------------- the explicit actions

def group(newsroom: ns.Newsroom, reports: dict[str, dict], names: set[str], actor: str, moment: datetime,
          key: object) -> tuple[dict, bool]:
    """Put every report not yet in a story into the story of a report whose headline it repeats, or into a new story.
    Local only; (summary, created). Repeating the key returns the first summary."""
    with newsroom.writing() as connection:
        done = ns.operation(connection, key, "group", actor, {})
        if done is not None:
            return done, False
        held = {row["entry_id"]: row["story_id"] for row in connection.execute(
            "SELECT entry_id, story_id FROM story_members WHERE event_id IN "
            "(SELECT MAX(event_id) FROM story_members GROUP BY entry_id) AND action = 'add'")}
        at = ns.stamp(moment)
        members: dict[str, list[dict]] = {}
        for entry_id, story_id in held.items():
            if entry_id in reports:
                members.setdefault(story_id, []).append(reports[entry_id])
        new, joined = [], []
        for report in sorted((row for row in reports.values() if row["entry_id"] not in held),
                             key=lambda row: (row["at"], row["entry_id"])):
            found = next(((story_id, evidence) for story_id, rows in members.items() for other in rows
                          if (evidence := same_headline(other, report, names))), None)
            if found:
                story_id, evidence = found
                _add(connection, story_id, report["entry_id"], evidence, actor, at, "the same headline")
                joined.append({"entry_id": report["entry_id"], "story_id": story_id, "basis": evidence})
            else:
                basis = {"rule": f"{MATCH_VERSION}/new-report"}
                story_id = _new_story(connection, report, basis, actor, at, "a report not yet in a story")
                new.append(story_id)
            members.setdefault(story_id, []).append(report)
            held[report["entry_id"]] = story_id
        summary = {"match_version": MATCH_VERSION, "grouped": len(new) + len(joined), "new_stories": len(new),
                   "joined": joined, "at": at}
        ns.record_operation(connection, key, "group", actor, {}, summary, at)
    return summary, True


def merge(newsroom: ns.Newsroom, story_id: str, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """Move every report of ``story_id`` into ``form['into']`` (both current, unmerged stories); the merged story's
    address then leads to the other. ``form``: into, reason, idempotency_key."""
    reason = checked_reason(form.get("reason"))
    payload = {"story_id": story_id, "into": form.get("into"), "reason": reason}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "merge", actor, payload)
        if done is not None:
            return done, False
        into = form.get("into")
        live = {row["story_id"] for row in connection.execute(
            "SELECT story_id FROM stories WHERE story_id NOT IN (SELECT story_id FROM story_merges)")}
        if story_id not in live or into not in live or into == story_id:
            raise AccountsRefused(409, "story_unavailable", "Both stories must exist, differ and not be merged already.")
        at = ns.stamp(moment)
        moved = _current_members(connection, story_id)
        basis = {"rule": "operator/merge", "merged_from": story_id}
        for entry_id in moved:
            _remove(connection, story_id, entry_id, basis, actor, at, reason)
            _add(connection, into, entry_id, basis, actor, at, reason)
        connection.execute("INSERT INTO story_merges VALUES (?, ?, ?, ?, ?)", (story_id, into, actor, at, reason))
        result = {"story_id": story_id, "into": into, "moved": moved, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "merge", actor, payload, result, at)
    return result, True


def detach(newsroom: ns.Newsroom, story_id: str, form: dict, reports: dict[str, dict], actor: str,
           moment: datetime) -> tuple[dict, bool]:
    """Take one report out of a story into a new story of its own. ``form``: entry_id, reason, idempotency_key."""
    reason = checked_reason(form.get("reason"))
    payload = {"story_id": story_id, "entry_id": form.get("entry_id"), "reason": reason}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "detach", actor, payload)
        if done is not None:
            return done, False
        members = _current_members(connection, story_id)
        entry_id = form.get("entry_id")
        merged = connection.execute("SELECT 1 FROM story_merges WHERE story_id = ?", (story_id,)).fetchone()
        if merged or entry_id not in members or entry_id not in reports:
            raise AccountsRefused(409, "story_unavailable", "That report is not in this story now.")
        if len(members) == 1:
            raise AccountsRefused(409, "story_unavailable", "A story keeps at least one report; this is its only one.")
        at = ns.stamp(moment)
        basis = {"rule": "operator/detach", "detached_from": story_id}
        _remove(connection, story_id, entry_id, basis, actor, at, reason)
        new_id = _new_story(connection, reports[entry_id], basis, actor, at, reason)
        result = {"story_id": story_id, "entry_id": entry_id, "new_story_id": new_id, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "detach", actor, payload, result, at)
    return result, True


def retitle(newsroom: ns.Newsroom, story_id: str, form: dict, actor: str, moment: datetime) -> tuple[dict, bool]:
    """The story's own headline, chosen by the operator (by default it is its founding report's). ``form``: title,
    reason, idempotency_key."""
    reason = checked_reason(form.get("reason"))
    title = form.get("title")
    if not isinstance(title, str) or not title.strip() or len(title) > 200:
        raise AccountsRefused(422, "invalid_request", "A story's headline has 1 to 200 characters.")
    payload = {"story_id": story_id, "title": title.strip(), "reason": reason}
    with newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "retitle", actor, payload)
        if done is not None:
            return done, False
        if connection.execute("SELECT 1 FROM stories WHERE story_id = ?", (story_id,)).fetchone() is None:
            raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
        at = ns.stamp(moment)
        connection.execute("INSERT INTO story_titles (story_id, title, actor, at, reason) VALUES (?, ?, ?, ?, ?)",
                           (story_id, title.strip(), actor, at, reason))
        result = {"story_id": story_id, "title": title.strip(), "at": at}
        ns.record_operation(connection, form["idempotency_key"], "retitle", actor, payload, result, at)
    return result, True


def _current_members(connection, story_id: str) -> list[str]:
    rows = connection.execute("SELECT entry_id, action FROM story_members WHERE story_id = ? ORDER BY event_id",
                              (story_id,)).fetchall()
    current: dict[str, None] = {}
    for row in rows:
        if row["action"] == "add":
            current[row["entry_id"]] = None
        else:
            current.pop(row["entry_id"], None)
    return list(current)


# ---------------------------------------------------------------- reading

def suggestions(stories: dict[str, list[dict]], names: set[str], limit: int = 50) -> list[dict]:
    """Pairs of current stories that may cover one development, with the shared words that suggest it. Never applied
    by itself: only the operator's merge joins stories."""
    found = []
    ids = sorted(stories)
    for index, first in enumerate(ids):
        for second in ids[index + 1:]:
            evidence = next((match for a in stories[first] for b in stories[second]
                             if (match := related_terms(a, b, names))), None)
            if evidence:
                found.append({"stories": [first, second], "evidence": evidence})
    return sorted(found, key=lambda row: (-row["evidence"]["jaccard"], row["stories"]))[:limit]


def _origin_role(roles: set[str]) -> str:
    """Whose words a reporting origin is: an official statement republished by a news site is still the official
    statement, and a company's release republished is still the company's."""
    return "official" if "official" in roles else "company" if "company" in roles else "news"


def _content_words(text: str | None) -> set[str]:
    return {word for word in words(text) if word not in STOPWORDS and len(word) > 2}


def _uncertain_pair(first: dict, second: dict, names: set[str]) -> str | None:
    """Why two reports of different origins might still share one (syndication not shown by a credit), or None."""
    heads = _content(headline_words(first["title"], names)), _content(headline_words(second["title"], names))
    if heads[0] and heads[1] and len(heads[0] & heads[1]) >= SAME_TITLE_WORDS and \
            len(heads[0] & heads[1]) / len(heads[0] | heads[1]) >= SIMILAR_JACCARD:
        return "their headlines are similar, though not the same"
    texts = _content_words(first["excerpt"]), _content_words(second["excerpt"])
    if min(len(texts[0]), len(texts[1])) >= SAME_TEXT_WORDS and \
            len(texts[0] & texts[1]) / len(texts[0] | texts[1]) >= SIMILAR_JACCARD:
        return "their excerpts are similar, though not nearly the same"
    return None


def coverage(reports: list[dict], names: set[str]) -> dict:
    """How independent a story's reports are (story-coverage-0.3): reporting origins, each one publisher or a set of
    publishers carrying one text, with the reason they were counted together; the origin's kind (a newsroom's own
    reporting, an official statement, a company's statement); and what could not be established."""
    parent = list(range(len(reports)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    reasons: dict[tuple[int, int], str] = {}

    def join(a: int, b: int, reason: str) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_b] = root_a
            reasons[(a, b)] = reason

    for a in range(len(reports)):
        for b in range(a + 1, len(reports)):
            first, second = reports[a], reports[b]
            if first["publisher"] == second["publisher"]:
                join(a, b, "the same publisher")
                continue
            same = headline_words(first["title"], names)
            if same == headline_words(second["title"], names) and len(same) >= SAME_TITLE_WORDS:
                join(a, b, "the same headline")
                continue
            text_a, text_b = set(words(first["excerpt"])), set(words(second["excerpt"]))
            if min(len(text_a), len(text_b)) >= SAME_TEXT_WORDS and \
                    len(text_a & text_b) / len(text_a | text_b) >= SAME_TEXT_JACCARD:
                join(a, b, "nearly the same text")
                continue
            wire_a, wire_b = wire_of(first), wire_of(second)
            if wire_a and wire_a == wire_b:
                join(a, b, f"the same wire credit ({wire_a})")
    units: dict[int, list[int]] = {}
    for index in range(len(reports)):
        units.setdefault(find(index), []).append(index)
    roots = list(units)
    uncertain: dict[int, list[str]] = {}
    pairs = []
    for x, root_a in enumerate(roots):
        for root_b in roots[x + 1:]:
            why = next((reason for a in units[root_a] for b in units[root_b]
                        if (reason := _uncertain_pair(reports[a], reports[b], names))), None)
            if why:
                pairs.append({"entries": [reports[units[root_a][0]]["entry_id"], reports[units[root_b][0]]["entry_id"]],
                              "reason": why})
                uncertain.setdefault(root_b, []).append(f"it may share an origin with another source: {why}")
    for root in roots:  # A newsroom known only by its headline: its text could not be compared with the others'.
        rows = [reports[index] for index in units[root]]
        if len(roots) > 1 and _origin_role({row["role"] for row in rows}) == "news" and \
                not any(row["excerpt"] for row in rows):
            uncertain.setdefault(root, []).append("only its headline is held, so its text could not be compared")
    shown = []
    for root in roots:
        members = units[root]
        rows = [reports[index] for index in members]
        why = sorted({reason for (a, b), reason in reasons.items() if a in members and b in members})
        shown.append({"publishers": sorted({row["publisher"] for row in rows}),
                      "entries": [row["entry_id"] for row in rows], "counted_together_because": why,
                      "role": _origin_role({row["role"] for row in rows}),
                      "independence": "unverified" if root in uncertain else "established",
                      "uncertain_because": uncertain.get(root, [])})
    count = lambda role, *states: sum(1 for unit in shown if unit["role"] == role and  # noqa: E731
                                      unit["independence"] in (states or ("established", "unverified")))
    news, official, company = count("news"), count("official"), count("company")
    return {"coverage_version": COVERAGE_VERSION, "reports": len(reports),
            "publishers": len({row["publisher"] for row in reports}), "origins": len(shown),
            "news_origins": news, "official_origins": official, "company_origins": company,
            "reporting_origins": news + official,
            "confirmed_news": count("news", "established"), "confirmed_official": count("official", "established"),
            "possible_news": count("news", "unverified"), "possible_official": count("official", "unverified"),
            "uncertain": sum(1 for unit in shown if unit["independence"] == "unverified"),
            "company_statements": sum(1 for row in reports if row["role"] == "company"),
            "official_releases": sum(1 for row in reports if row["role"] == "official"),
            "repeats": len(reports) - len(shown), "units": shown, "possible_shared_origins": pairs}


def wire_of(report: dict) -> str | None:
    """The wire a report credits in its excerpt's opening ("WASHINGTON (Reuters) -") or its headline's credit."""
    found = WIRE_CREDIT.match(report["excerpt"] or "")
    if found:
        return WIRES[found.group(1).casefold()]
    credit = CREDIT_SEPARATORS.search(report["title"])
    return WIRES.get(credit.group(1).strip().casefold()) if credit else None
