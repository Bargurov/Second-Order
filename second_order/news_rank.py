"""The order of the news (news-rank-0.4): a fixed, deterministic policy over saved records and the time of the read.

A story's time is its reports' times (news_reports.report_time): the instant a feed states for a report; when it states
a date without a usable time, the end of that date (or the first sighting, if earlier); otherwise when this server first
saw the report (said so wherever it is shown; a retrieval time is never called a publication time). Hot now lists
the stories whose latest report is at most HOT_HOURS old and whose economic relevance is established (news_relevance:
an annotation of its sources that the relevance decision accepts, or an editor's judgement), and those the editors
marked as major until a time not yet passed, by these points, all shown to the reader in words:

- freshness: FRESH_POINTS halved every HALF_LIFE_HOURS since the story's latest report, and halved once more
  (UNSTATED_FACTOR) when that report's feed states no time of day, since a date's end or "first seen" can be later
  than the publication;
- a new development: NEW_POINTS when its first report is at most NEW_HOURS old by a time its feed states;
- breadth of independent coverage (news-rank-0.4): the story's reporting origins (news_stories.coverage: one
  publisher, or several carrying one text, is one origin) weighted by ORIGIN_WEIGHT (a newsroom's own reporting 1, one
  whose independence is unverified 0.5, an official statement 0.5, a company's statement 0), the heaviest origin
  dropped, and BREADTH_POINTS for each remaining unit of weight, up to BREADTH_CAP: corroboration by several newsrooms
  counts as much as a day of freshness;
- breaking news: BREAKING_POINTS for a new development (as above) of high assessed importance that at most one origin
  has reported yet, so significant news first reported by one source is not outranked by older, wider coverage;
- the editors' priority: PRIORITY_POINTS while a story (or its topic) is marked major, until the time the mark states
  (at most MAX_PRIORITY_DAYS after it was set), and only while the story itself has a report from the last
  PRIORITY_RECENT_HOURS, so a marked subject cannot hold the top place without new reports;
- a continuing topic: TOPIC_POINTS for the newest development of an ongoing topic whose previous development is at most
  TOPIC_HOURS older, so a major subject stays visible through its latest development, not through old ones;
- editorial importance: news_relevance.importance's fixed points (at most 2) from the assessment's categories (the
  development's type, its reach, whether its sources state its size): never a model's number.

A story covered only by companies' own statements (press releases) is not independent reporting: it is listed in Latest
and Your interests, and in Hot now only while the editors mark it as major. A story whose economic relevance is not
established is not in Hot now (news-rank-0.3; 0.2 used the news's keyword subjects instead): one assessed as outside the
scope is not listed at all, and one awaiting an assessment or an editor (not assessed yet, restricted by its publisher's
terms, unclear, failed, or too thin to tell) is listed apart, with the reason. Keywords and publisher categories decide
nothing here.

Ties go to the newer latest report, then the story ID. Latest lists every story by its latest report, newest first,
and marks those older than HOT_HOURS as older news. Nothing here counts readers, clicks, shares or prices, and nothing
is learned or adjusted from use.
"""
from datetime import datetime, timedelta

RANK_VERSION = "news-rank-0.4"
HOT_HOURS = 72
HALF_LIFE_HOURS = 12
FRESH_POINTS = 4.0
UNSTATED_FACTOR = 0.5
NEW_HOURS = 24
NEW_POINTS = 1.0
BREADTH_POINTS = 1.0
BREADTH_CAP = 3.0
BREAKING_POINTS = 1.0
ORIGIN_WEIGHT = {("news", "established"): 1.0, ("news", "unverified"): 0.5, ("official", "established"): 0.5,
                 ("official", "unverified"): 0.5, ("company", "established"): 0.0, ("company", "unverified"): 0.0}
PRIORITY_POINTS = 2.0
PRIORITY_RECENT_HOURS = 168
MAX_PRIORITY_DAYS = 7
TOPIC_POINTS = 1.0
TOPIC_HOURS = 168


def _hours(later: datetime, earlier: str) -> float:
    return max(0.0, (later - datetime.fromisoformat(earlier)).total_seconds() / 3600)


def _ago(hours: float) -> str:
    if hours < 1:
        return "less than an hour ago"
    if hours < 48:
        return f"{int(hours)} hour{'s' if int(hours) != 1 else ''} ago"
    return f"{int(hours // 24)} days ago"


def breadth_points(coverage: dict) -> float:
    """BREADTH_POINTS for each unit of origin weight after the heaviest origin's, up to BREADTH_CAP."""
    weights = sorted((ORIGIN_WEIGHT[(unit["role"], unit.get("independence", "established"))]
                      for unit in coverage["units"]), reverse=True)
    return round(min(BREADTH_CAP, BREADTH_POINTS * sum(weights[1:])), 3)


def _kinds(news: int, official: int) -> str:
    return ", ".join(part for part in (f"{news} newsroom{'s' if news != 1 else ''}" if news else "",
                                       f"{official} official statement{'s' if official != 1 else ''}"
                                       if official else "") if part)


def coverage_words(coverage: dict) -> str:
    """The story's coverage in one sentence: its publishers, its confirmed reporting origins (independence
    established) apart from its possible ones (not established), each by kind, and its copies. An origin is never
    called independent first and qualified afterwards."""
    confirmed = coverage["confirmed_news"] + coverage["confirmed_official"]
    possible = coverage["possible_news"] + coverage["possible_official"]
    groups = []
    if confirmed:
        name = "reporting origin" if confirmed == 1 and not possible else "confirmed reporting origin"
        groups.append(f"{confirmed} {name}{'s' if confirmed != 1 else ''} "
                      f"({_kinds(coverage['confirmed_news'], coverage['confirmed_official'])})")
    if possible:
        groups.append(f"{possible} possible origin{'s' if possible != 1 else ''} "
                      f"({_kinds(coverage['possible_news'], coverage['possible_official'])}) whose independence is not "
                      f"established, which count{'s' if possible == 1 else ''} half")
    publishers = coverage["publishers"]
    text = f"From {publishers} publisher{'s' if publishers != 1 else ''}: {' and '.join(groups)}"
    if coverage["repeats"]:
        text += f"; {coverage['repeats']} cop{'ies' if coverage['repeats'] != 1 else 'y'} counted with an origin"
    return text + "."


def priority_active(priority: dict | None, now: datetime) -> bool:
    return priority is not None and priority["level"] == "major" and datetime.fromisoformat(priority["until"]) > now


def signals(story: dict, now: datetime) -> dict:
    """One story's points, each with the sentence that explains it. ``story`` carries first_at, latest_at, the time
    basis of its latest report, coverage, priority (or None), topic (None, or {title, newest, previous_at}) and its
    relevance (news_relevance.relevance_of)."""
    age = _hours(now, story["latest_at"])
    first_age = _hours(now, story["first_at"])
    rows = []
    stated = story["latest_basis"] == "published"
    fresh = FRESH_POINTS * 0.5 ** (age / HALF_LIFE_HOURS) * (1 if stated else UNSTATED_FACTOR)
    if stated:
        basis = "its feed's stated time"
    elif story["latest_basis"] == "dated":
        basis = "the date its feed states, which gives no time of day, so this counts half"
    else:
        basis = "when this server first saw it; the feed states no time, so this counts half"
    rows.append({"signal": "freshness", "points": round(fresh, 3),
                 "text": f"Latest report {_ago(age)} (by {basis})."})
    if first_age <= NEW_HOURS and story["first_basis"] == "published":
        rows.append({"signal": "new_development", "points": NEW_POINTS,
                     "text": f"A new development: first reported {_ago(first_age)}."})
    breadth = breadth_points(story["coverage"])
    if breadth > 0:
        rows.append({"signal": "coverage", "points": breadth, "text": coverage_words(story["coverage"])})
    priority = story["priority"]
    if priority_active(priority, now) and age <= PRIORITY_RECENT_HOURS:
        rows.append({"signal": "priority", "points": PRIORITY_POINTS,
                     "text": f"Marked as a major {priority['target_kind']} by the editors until "
                             f"{priority['until'][:16].replace('T', ' ')} UTC."})
    topic = story["topic"]
    if topic and topic["newest"] and topic["previous_at"] is not None and \
            _hours(datetime.fromisoformat(story["first_at"]), topic["previous_at"]) <= TOPIC_HOURS:
        rows.append({"signal": "topic", "points": TOPIC_POINTS,
                     "text": f"The latest development in the ongoing topic “{topic['title']}”."})
    relevance = story["relevance"]
    rated = relevance["importance"] if relevance["state"] == "relevant" else None
    if rated is not None and rated["level"] == "high" and story["coverage"]["reporting_origins"] <= 1 and \
            any(row["signal"] == "new_development" for row in rows):
        rows.append({"signal": "breaking", "points": BREAKING_POINTS,
                     "text": "A new development of high assessed importance, shown although only one source has "
                             "reported it yet."})
    if rated is not None:
        method = (relevance["annotation"] or {}).get("method")
        rows.append({"signal": "importance", "points": rated["points"],
                     "text": f"{rated['text'][:-1]} ({ASSESSED_BY.get(method, 'an assessment')})."})
    marked = any(row["signal"] == "priority" for row in rows)
    statements_only = story["coverage"]["reporting_origins"] == 0  # Only companies' own statements cover it.
    relevant = relevance["state"] == "relevant"
    hot = marked or (age <= HOT_HOURS and not statements_only and relevant)
    if statements_only and age <= HOT_HOURS and not marked:
        rows.append({"signal": "statements_only", "points": 0.0,
                     "text": "Only the company's own statement covers it, so it is listed under Latest, not Hot now."})
    elif not relevant and not marked:
        rows.append({"signal": "relevance", "points": 0.0, "text": NOT_LISTED.get(relevance["state"], AWAITING)})
    return {"rank_version": RANK_VERSION, "score": round(sum(row["points"] for row in rows), 3), "signals": rows,
            "hot": hot, "older": age > HOT_HOURS}


# Readers' words: what they are told avoids the operator's vocabulary (no model, prompt or cost), while saying plainly
# that an assessment was made with AI.
ASSESSED_BY = {"model": "an AI assessment of its sources in this application",
               "assisted": "an AI-assisted assessment of its sources", "synthetic": "a SYNTHETIC assessment"}
AWAITING = ("Its economic relevance is not established yet, so it is listed apart from the news, with the headlines "
            "awaiting an assessment or an editor.")
NOT_LISTED = {"outside_scope": "Assessed as outside the economic news's scope, so it is not listed."}


def listed(story: dict) -> bool:
    """Whether the story is listed among the news (Latest, Your interests): established as relevant, or marked as major
    by the editors."""
    return story["relevance"]["state"] == "relevant" or any(row["signal"] == "priority"
                                                            for row in story["rank"]["signals"])


def hot(stories: list[dict], now: datetime) -> list[dict]:
    """Hot now: the hot stories, highest points first."""
    ranked = [story for story in stories if story["rank"]["hot"]]
    return sorted(ranked, key=lambda story: (-story["rank"]["score"], -datetime.fromisoformat(story["latest_at"])
                                             .timestamp(), story["story_id"]))


def latest(stories: list[dict]) -> list[dict]:
    """Latest: every story by its latest report, newest first."""
    return sorted(stories, key=lambda story: (-datetime.fromisoformat(story["latest_at"]).timestamp(),
                                              story["story_id"]))


COVERAGE_ORDER_VERSION = "news-coverage-order-0.1"


def most_covered(stories: list[dict], now: datetime) -> list[dict]:
    """Hot now's eligible stories ordered by uncapped origin weight, not publishers or article volume.

    Use exactly the established origin weights; copies already share a unit. Hot now's score, recency and ID break
    ties. This adds a reader-selected order without changing Hot now, relevance or historical research scores.
    """
    def weight(story: dict) -> float:
        return sum(ORIGIN_WEIGHT[(unit["role"], unit.get("independence", "established"))]
                   for unit in story["coverage"]["units"])
    return sorted(hot(stories, now), key=lambda story: (
        -weight(story), -story["rank"]["score"], -datetime.fromisoformat(story["latest_at"]).timestamp(),
        story["story_id"]))


def coverage_explanation() -> dict:
    return {**explanation(), "order_version": COVERAGE_ORDER_VERSION, "statement": (
        "Most covered uses the same relevance and recency rules as Hot now. It orders those stories by reporting "
        "origins: confirmed newsroom reporting counts fully; official statements and possible origins whose "
        "independence is not established count half; company statements count nothing. Copies of the same reporting "
        "count once. Hot now's importance and recency break ties. This is coverage in this server's saved sources, "
        "not a measure of worldwide popularity or market impact. Hot now also keeps important single-source news visible.")}


def priority_until(value: object, now: datetime) -> str:
    """A major mark's end: an ISO time with an offset, after now and at most MAX_PRIORITY_DAYS ahead."""
    try:
        until = datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        until = None
    if until is None or until.utcoffset() is None or not now < until <= now + timedelta(days=MAX_PRIORITY_DAYS):
        raise ValueError(f"A major mark ends at a time with its UTC offset, after now and at most {MAX_PRIORITY_DAYS} "
                         "days ahead.")
    return until.astimezone(now.tzinfo).isoformat(timespec="seconds")


def explanation() -> dict:
    """The policy in plain words, for every view that orders stories."""
    return {"rank_version": RANK_VERSION, "hot_hours": HOT_HOURS, "statement": (
        f"Hot now shows stories with a report from the last {HOT_HOURS // 24} days, ordered by fixed points: how recent "
        f"the latest report is (halving every {HALF_LIFE_HOURS} hours), whether it is a new development (first reported "
        f"in the last {NEW_HOURS} hours), the breadth of its independent coverage (reporting origins: one publisher, "
        "or several carrying the same text, count once; a newsroom's own reporting counts fully, an official statement "
        "or a source whose independence is not established counts half, a company's own statement not at all), "
        "whether it is a new, highly important development only one source has reported yet, a major mark set by the "
        "editors "
        f"for at most {MAX_PRIORITY_DAYS} days, whether it is the latest development of an ongoing topic, and fixed "
        "points for its assessed importance (the type of development, its reach and whether its sources state its "
        "size). Only stories assessed as economic developments are listed: one assessed as outside the economic "
        "news's scope is left out, and one still awaiting an assessment or an editor is listed apart with the reason. "
        "A story covered only by a company's own statement is listed under Latest instead. Assessments are editorial "
        "judgements made with AI or by an editor from the sources, not measured market impact. It does not count "
        "readers, clicks, shares or market moves.")}
