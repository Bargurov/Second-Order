"""Coverage of a story by other publishers, found through the GDELT Project's news index (news-index-0.2).

The GDELT DOC 2.0 API indexes news articles worldwide: for each, its address, title as indexed, domain, language,
source country and when GDELT saw it, but no article text. Its terms (https://www.gdeltproject.org/about.html, read
2026-10-25) allow "unlimited and unrestricted use for any academic, commercial, or governmental use", with a citation
to the GDELT Project and a link to gdeltproject.org; this application cites it wherever an indexed article is shown.
What an indexed article is used for here is narrow: its headline (as GDELT indexed it, which may differ from the
publisher's) and link are shown, and it counts as coverage of the story by its publisher. Its text is never held, and
neither its title nor anything else of it is sent to a model or used for a brief: the publishers' own terms are not
GDELT's.

Two explicit operator actions, never a read:

- ``lookup`` makes one request to the index for one story: a query of the rarest content words of its own headline
  across current stories' headlines (official boilerplate left out; at least two), or 2 or 3 words of its own headline
  or excerpt that the operator chooses (recorded as theirs), in English-language coverage, within LOOKUP_DAYS_BEFORE day before
  and LOOKUP_DAYS_AFTER days after the story was first reported. No retry and no redirect; GDELT asks for at most one
  request every five seconds and answers 429 when it is exceeded, which is recorded as ``rate_limited``, never as "no
  coverage", with what the answer said (``rate_limit``: its Retry-After header, the start of its text) and the
  cooldown it starts (0.2): no lookup is sent before ``cooldown_until``, COOLDOWN_SECONDS after a first 429 and twice as
  long after each further one in a row, or longer when Retry-After asks for it (at most MAX_COOLDOWN_SECONDS). A lookup
  asked for during the cooldown is refused before any request and records nothing; the first answer that is not a 429
  ends it. Each lookup is kept write-once (data/news-index/lookups/<story>/<lookup ID>.json): the query, the
  address, the answer's status and every article, each with whether the matching rule (MATCH_VERSION) accepts it:
  its indexed title shares at least two of the query's words, a word and its plural alike (or one and a figure of the story, or a proper name that
  only this story names among current ones, such as a company's, with one more word of the story's headline), and
  GDELT saw it within
  the lookup's window, from a domain that is not one of the story's own publishers' hosts.
- ``attach`` adds the accepted articles of a lookup to the story, with the operator's reason, as reports
  (``gdelt-index:<hash>``) whose membership records the rule and the shared names; repeating it adds nothing new.

An attached article is a report of its publisher (its domain), a newsroom's reporting known only by its headline: its
independence from the story's other origins cannot be checked against their text (news_stories.coverage says so), and
copies with the same title collapse into one origin. It never makes a story newer: a story's times come from its
own reports. It is kept as the answer gave it: a later lookup, rate-limited or not, removes nothing, and ``status``
(a read) shows each story's kept coverage beside the cooldown.
"""
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import urlencode, urlsplit

import httpx

from . import market_store, news_matching, news_stories, news_views, newsroom_store as ns
from .accounts import AccountsRefused
from .user_news import words

INDEX_VERSION = "news-index-0.2"  # 0.2: a 429's limit and cooldown are recorded.
MATCH_VERSION = "news-index-match-0.2"  # 0.2: a word and its plural match ("turbine", "turbines").
ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "data" / "news-index"
SOURCE_KEY = "gdelt-index"
ENDPOINT = "https://api.gdeltproject.org/api/v2/doc/doc"
HOST = "api.gdeltproject.org"
ATTRIBUTION = "Indexed by the GDELT Project (https://www.gdeltproject.org/)"
TERMS_URL = "https://www.gdeltproject.org/about.html"
MAX_RECORDS = 50
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 30
PAUSE_SECONDS = 6  # GDELT asks for at most one request every five seconds.
COOLDOWN_SECONDS = 15 * 60  # After a first 429; each further 429 in a row doubles it.
MAX_COOLDOWN_SECONDS = 24 * 3600
MAX_LIMIT_MESSAGE = 300
LOOKUP_DAYS_BEFORE = 1
LOOKUP_DAYS_AFTER = 3
MAX_QUERY_NAMES = 4
LOOKUP_ID = re.compile(r"lookup-[0-9a-f]{16}")
USER_AGENT = "SecondOrder/0.1 (news coverage index lookups; explicit operator action)"


class IndexRefused(ValueError):
    pass


def entry_id(url: str) -> str:
    return f"{SOURCE_KEY}:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:20]}"


def _stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S")


def _seen(value: str) -> str | None:
    """GDELT's seendate ("20261023T141500Z") as an ISO instant, or None."""
    try:
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _headline_terms(title: str) -> list[str]:
    return [word for word in news_stories.headline_words(title)
            if word not in news_stories.STOPWORDS and word not in news_matching.GENERIC and len(word) > 3 and
            not word.isdigit()]


def _proper(story: dict) -> set[str]:
    """Words of the story that are names: capitalised inside a headline that is not in title case, short acronyms, and
    the parties its relevance annotation names."""
    found = set()
    for row in story["reports"]:
        tokens = news_matching.TOKEN.findall(row["title"])
        lettered = [token for token in tokens if len(token) >= 4 and token[0].isalpha()]
        title_case = lettered and sum(1 for token in lettered if token[0].isupper()) / len(lettered) >= 0.7
        for index, token in enumerate(tokens):
            bare = token.strip(".,'’-")
            acronym = bare.isupper() and 2 <= len(bare) <= 5
            if bare and (acronym or (bare[0].isupper() and index > 0 and not title_case)):
                found |= news_matching._distinct_words(bare)
    annotation = (story.get("relevance") or {}).get("annotation")
    for name in (annotation or {}).get("affected_names", []):
        found |= news_matching._distinct_words(name)
    return found


def query_for(found: dict, story: dict, now: datetime, chosen: list[str] | None = None) -> dict:
    """The lookup's query: the rarest content words of the story's own headline across current stories' headlines
    (generic official words left out), at most MAX_QUERY_NAMES - 1, or the operator's ``chosen`` words (2 or 3 words
    of the story's own headline or excerpt: among equally rare words the rule cannot tell "wind turbines" from
    "parts"); and, for matching, the story's names and figures."""
    current = [row for row in found["stories"].values()
               if (now - datetime.fromisoformat(row["latest_at"])).days <= news_matching.CURRENT_DAYS]
    frequency: dict[str, int] = {}
    for row in current:
        for word in set(_headline_terms(row["title"])):
            frequency[word] = frequency.get(word, 0) + 1
    said = [word for row in story["reports"] for word in words(f"{row['title']} {row['excerpt'] or ''}")]
    terms = sorted(dict.fromkeys(_headline_terms(story["title"])),  # Rarest first; among equals, the most repeated.
                   key=lambda word: (frequency.get(word, 0), -said.count(word), word))
    names = terms[:MAX_QUERY_NAMES - 1]
    if chosen is not None:
        own = set(said)
        names = list(dict.fromkeys(word.lower() for word in chosen))
        if not 2 <= len(names) <= MAX_QUERY_NAMES - 1 or any(word not in own for word in names):
            raise AccountsRefused(422, "invalid_request", f"Choose 2 to {MAX_QUERY_NAMES - 1} words of the story's own "
                                                          "headline or excerpt.")
    held = news_matching.anchors(story)
    proper = sorted(word for word in _proper(story) if frequency.get(word, 0) <= 1)
    if len(names) < 2:
        raise AccountsRefused(409, "no_query", "This story names too few distinctive words for a precise lookup.")
    first = datetime.fromisoformat(story["first_at"])
    start = first - timedelta(days=LOOKUP_DAYS_BEFORE)
    end = min(now, first + timedelta(days=LOOKUP_DAYS_AFTER))
    return {"names": names, "chosen_by": "operator" if chosen is not None else "rule", "proper": proper,
            "figures": sorted(held["figures"]), "start": start.isoformat(), "end": end.isoformat(),
            "query": " ".join(names) + " sourcelang:english"}


def request_url(query: dict) -> str:
    return ENDPOINT + "?" + urlencode({"query": query["query"], "mode": "artlist", "format": "json",
                                       "maxrecords": MAX_RECORDS, "sort": "datedesc",
                                       "startdatetime": _stamp(datetime.fromisoformat(query["start"])),
                                       "enddatetime": _stamp(datetime.fromisoformat(query["end"]))})


def _stem(word: str) -> str:
    """A plural and its singular compare equal ("turbines", "turbine"; "duties", "duty"); short words and "-ss" endings
    are kept."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word


def matches(query: dict, story: dict, article: dict) -> dict:
    """Whether the matching rule accepts an indexed article for the story, and why."""
    title = {_stem(word) for word in words(article.get("title"))}
    shared = sorted(name for name in query["names"] if _stem(name) in title)
    figures = sorted(figure for figure in query["figures"] if figure.lower() in (article.get("title") or "").lower())
    seen = _seen(article.get("seendate"))
    hosts = {urlsplit(row["link"]).hostname for row in story["reports"]}
    domain = (article.get("domain") or "").lower()
    in_window = seen is not None and query["start"] <= seen <= query["end"]
    own = any(domain and host and (host == domain or host.endswith("." + domain)) for host in hosts)
    secure = urlsplit(article.get("url") or "").scheme == "https"
    unique_name = sorted(name for name in query.get("proper", []) if _stem(name) in title)
    context = sorted({term for term in _headline_terms(story["title"]) if _stem(term) in title} - set(unique_name))
    named = bool(unique_name) and bool(context)  # A name alone (a place, a team) is not enough: one more word too.
    accepted = (len(shared) >= 2 or (shared and figures) or named) and in_window and not own and \
        secure and (article.get("language") or "").lower() in ("english", "")
    why = (f"shares {', '.join(shared) or 'no query word'}" + (f" and {', '.join(figures)}" if figures else "") +
           (f"; names {', '.join(unique_name)}, which only this story names" +
            (f", with {', '.join(context)}" if context else ", and no other word of its headline") if unique_name
            else "") +
           ("" if in_window else "; seen outside the lookup's window") +
           ("; one of the story's own publishers" if own else "") + ("" if secure else "; not an https address"))
    return {"accepted": accepted, "shared_names": sorted(set(shared) | set(unique_name)), "shared_figures": figures,
            "why": why}


def _folder(index: Path, story_id: str) -> Path:
    return index / "lookups" / story_id


def lookups(index: Path | None, story_id: str) -> list[dict]:
    """A story's lookups, oldest first. Reads files only."""
    if index is None or not _folder(index, story_id).is_dir():
        return []
    rows = []
    for path in sorted(_folder(index, story_id).glob("lookup-*.json")):
        try:
            rows.append(json.loads(path.read_bytes().decode("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: row["requested_at"])


def _every_lookup(index: Path) -> list[dict]:
    """Every story's lookups, oldest first. Reads files only."""
    rows = []
    for path in (index / "lookups").glob("*/lookup-*.json") if (index / "lookups").is_dir() else []:
        try:
            rows.append(json.loads(path.read_bytes().decode("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return sorted(rows, key=lambda row: row["requested_at"])


def _waiting(retry_after: str | None, consecutive: int, at: datetime) -> int:
    """The cooldown a 429 starts: COOLDOWN_SECONDS doubled for each earlier 429 in a row, or the answer's Retry-After
    (seconds, or an HTTP date) when that is longer; at most MAX_COOLDOWN_SECONDS."""
    rule = COOLDOWN_SECONDS * 2 ** (consecutive - 1)
    asked = 0
    if retry_after and retry_after.strip().isdigit():
        asked = int(retry_after.strip())
    elif retry_after:
        try:
            asked = int((parsedate_to_datetime(retry_after) - at).total_seconds())
        except (TypeError, ValueError, OverflowError):
            asked = 0
    return min(MAX_COOLDOWN_SECONDS, max(rule, asked))


def _rate_limits(index: Path) -> tuple[int, dict | None]:
    """The 429s in a row at the end of the lookups, and the newest of them."""
    rows = _every_lookup(index)
    run = 0
    for row in reversed(rows):
        if row.get("outcome") != "rate_limited":
            break
        run += 1
    return run, rows[-1] if run else None


def _limit_of(row: dict, consecutive: int) -> dict:
    """A rate-limited lookup's recorded limit; for one recorded before 0.2, the rule's cooldown from its time."""
    if isinstance(row.get("rate_limit"), dict):
        return row["rate_limit"]
    at = datetime.fromisoformat(row["requested_at"])
    seconds = _waiting(None, consecutive, at)
    return {"retry_after": None, "message": None, "consecutive": consecutive, "cooldown_seconds": seconds,
            "cooldown_until": (at + timedelta(seconds=seconds)).isoformat()}


def _cooldown_state(index: Path | None, now: datetime) -> dict:
    run, newest = _rate_limits(index) if index is not None else (0, None)
    if newest is None:
        return {"active": False, "consecutive": 0, "until": None, "last_rate_limited_at": None,
                "retry_after": None, "message": None,
                "detail": "No cooldown: the newest answer of the index was not a 429."}
    limit = _limit_of(newest, run)
    until = datetime.fromisoformat(limit["cooldown_until"])
    active = until > now
    why = (f"its Retry-After asked for {limit['retry_after']}" if limit.get("retry_after") else
           f"this server waits {COOLDOWN_SECONDS // 60} minutes after a first 429 and twice as long after each "
           "further one in a row")
    detail = (f"GDELT answered 429 (too many requests) at {newest['requested_at']}, {run} time{'s' if run != 1 else ''}"
              f" in a row; " + (f"no request is sent before {limit['cooldown_until']} ({why})." if active else
                                f"the cooldown ended at {limit['cooldown_until']}; a lookup may be asked for again.")
              + " Coverage already attached stays as it is.")
    return {"active": active, "consecutive": run, "until": limit["cooldown_until"],
            "last_rate_limited_at": newest["requested_at"], "retry_after": limit.get("retry_after"),
            "message": limit.get("message"), "detail": detail}


def cooldown(index: Path | None, now: datetime) -> dict | None:
    """The cooldown in force after the index's latest 429s, or None. Reads files only."""
    state = _cooldown_state(index, now)
    return state if state["active"] else None


def status(index: Path | None, now: datetime) -> dict:
    """What the index lookups hold, without any request: the cooldown, and each looked-up story's lookups, the
    articles kept from them and when the index last answered for it."""
    rows = _every_lookup(index) if index is not None else []
    kept: dict[str, int] = {}
    for entry in entries(index):
        kept[entry.get("lookup_id")] = kept.get(entry.get("lookup_id"), 0) + 1
    stories: dict[str, list[dict]] = {}
    for row in rows:
        stories.setdefault(row["story_id"], []).append(row)
    shown = []
    for story_id, made in sorted(stories.items()):
        answered = [row for row in made if row["outcome"] == "ok"]
        attached = sum(kept.get(row.get("lookup_id"), 0) for row in made)
        last = answered[-1]["requested_at"] if answered else None
        newest = made[-1]
        detail = (f"{attached} indexed article{'s' if attached != 1 else ''} attached, kept from the answer of {last}"
                  if answered else "No answer of the index is held for it")
        if newest["outcome"] != "ok":
            detail += f"; its newest lookup ({newest['requested_at']}) was {newest['outcome']} and changed nothing"
        shown.append({"story_id": story_id, "lookups": len(made), "attached": attached, "last_answer_at": last,
                      "last_outcome": newest["outcome"], "detail": detail + "."})
    return {"index_version": INDEX_VERSION, "cooldown": _cooldown_state(index, now), "stories": shown,
            "citation": ATTRIBUTION}


def _limit_message(response: httpx.Response) -> str | None:
    text = " ".join(response.content[:4_096].decode("utf-8", errors="replace").split())
    return text[:MAX_LIMIT_MESSAGE] or None


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(transport=transport, follow_redirects=False, trust_env=False, timeout=TIMEOUT_SECONDS,
                        headers={"User-Agent": USER_AGENT, "Accept": "application/json"})


def lookup(desk: news_views.Desk, story_id: str, now: datetime, transport: httpx.BaseTransport | None = None,
           chosen: list[str] | None = None) -> dict:
    """One explicit request to the index for one story (``chosen``: the operator's query words); the answer is recorded
    whatever it is."""
    if desk.index is None:
        raise AccountsRefused(409, "index_unavailable", "This server keeps no news index lookups.")
    found = news_views.world(desk, now)
    story = found["stories"].get(story_id)
    if story is None:
        raise AccountsRefused(404, "not_found", f"{story_id} is not a current story.")
    query = query_for(found, story, now, chosen)
    address = request_url(query)
    if urlsplit(address).hostname != HOST:
        raise AccountsRefused(500, "internal_error", "The lookup's address is not the index's.")
    waiting = cooldown(desk.index, now)
    if waiting is not None:  # Refused before any request; nothing is recorded.
        raise AccountsRefused(409, "index_cooling_down", waiting["detail"])
    record = {"index_version": INDEX_VERSION, "match_version": MATCH_VERSION, "story_id": story_id, "query": query,
              "url": address, "requested_at": ns.stamp(now), "status": None, "outcome": "failed", "detail": None,
              "articles": [], "citation": ATTRIBUTION}
    try:
        with client(transport) as session:
            response = session.get(address)
        record["status"] = response.status_code
        if response.status_code == 429:
            consecutive = _rate_limits(desk.index)[0] + 1
            retry_after = response.headers.get("retry-after")
            retry_after = retry_after[:40] if retry_after else None
            seconds = _waiting(retry_after, consecutive, now)
            until = (now + timedelta(seconds=seconds)).astimezone(timezone.utc).isoformat()
            record.update(outcome="rate_limited", rate_limit={
                "retry_after": retry_after, "message": _limit_message(response), "consecutive": consecutive,
                "cooldown_seconds": seconds, "cooldown_until": until},
                detail=(f"GDELT answered 429: it asks for at most one request every five seconds. Nothing is known "
                        f"about coverage; no lookup is sent before {until}."))
        elif response.status_code != 200:
            record["detail"] = f"GDELT answered HTTP {response.status_code}."
        elif len(response.content) > MAX_BYTES:
            record["detail"] = f"The answer was larger than {MAX_BYTES:,} bytes; it was not read."
        else:
            body = response.content.decode("utf-8", errors="replace").strip()
            payload = json.loads(body) if body else {}
            articles = payload.get("articles", []) if isinstance(payload, dict) else []
            rows = []
            for article in articles[:MAX_RECORDS]:
                if not isinstance(article, dict) or not isinstance(article.get("url"), str) or \
                        urlsplit(article["url"]).scheme not in ("http", "https"):
                    continue
                kept = {key: article.get(key) for key in ("url", "title", "domain", "seendate", "language",
                                                          "sourcecountry")}
                rows.append({**kept, "entry_id": entry_id(article["url"]), "match": matches(query, story, kept)})
            record.update(outcome="ok", articles=rows, detail=(
                f"{len(rows)} indexed articles, {sum(1 for row in rows if row['match']['accepted'])} accepted by "
                f"{MATCH_VERSION}." if rows else "The index holds no matching article in this window."))
    except (httpx.HTTPError, ValueError) as exc:
        record["detail"] = f"The lookup failed ({type(exc).__name__}); nothing is known about coverage."
    target = _folder(desk.index, story_id)
    earlier = len(list(target.glob("lookup-*.json"))) if target.is_dir() else 0
    record["lookup_id"] = "lookup-" + ns.sha256_of({**{key: record[key] for key in ("story_id", "url",
                                                                                   "requested_at")},
                                                    "number": earlier + 1})[:16]
    target.mkdir(parents=True, exist_ok=True)
    market_store.write_exclusive(target / f"{record['lookup_id']}.json", record)
    return record


def lookup_many(desk: news_views.Desk, story_ids: list[str], clock, transport=None, sleep=time.sleep,
                chosen: list[str] | None = None) -> list[dict]:
    """Lookups for several stories, one request each, PAUSE_SECONDS apart; a rate-limited answer stops the run."""
    done = []
    for position, story_id in enumerate(story_ids):
        if position:
            sleep(PAUSE_SECONDS)
        try:
            row = lookup(desk, story_id, clock(), transport, chosen)
        except AccountsRefused as exc:
            done.append({"story_id": story_id, "outcome": exc.code, "detail": str(exc)})
            if exc.code == "index_cooling_down":
                break
            continue
        done.append({key: row[key] for key in ("story_id", "lookup_id", "outcome", "status", "detail")})
        if row["outcome"] == "rate_limited":
            break
    return done


def _entry_path(index: Path, entry: str) -> Path:
    return index / "entries" / f"{entry.split(':', 1)[1]}.json"


def attach(desk: news_views.Desk, story_id: str, lookup_id: str, form: dict, actor: str,
           moment: datetime) -> tuple[dict, bool]:
    """Add a lookup's accepted articles to the story (``form``: reason, idempotency_key)."""
    reason = news_stories.checked_reason(form.get("reason"))
    if desk.index is None or not isinstance(lookup_id, str) or not LOOKUP_ID.fullmatch(lookup_id):
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.")
    path = _folder(desk.index, story_id) / f"{lookup_id}.json"
    try:
        record = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise AccountsRefused(404, "not_found", "Nothing is available at this address.") from None
    accepted = [row for row in record["articles"] if row["match"]["accepted"]]
    payload = {"story_id": story_id, "lookup_id": lookup_id, "reason": reason}
    at = ns.stamp(moment)
    with desk.newsroom.writing() as connection:
        done = ns.operation(connection, form.get("idempotency_key"), "index-attach", actor, payload)
        if done is not None:
            return done, False
        live = connection.execute("SELECT 1 FROM stories WHERE story_id = ? AND story_id NOT IN "
                                  "(SELECT story_id FROM story_merges)", (story_id,)).fetchone()
        if live is None:
            raise AccountsRefused(409, "story_unavailable", "The story is not a current, unmerged story.")
        held = {row["entry_id"] for row in connection.execute(
            "SELECT entry_id FROM story_members WHERE event_id IN (SELECT MAX(event_id) FROM story_members GROUP BY "
            "entry_id) AND action = 'add'")}
        added = []
        for row in accepted:
            if row["entry_id"] in held:
                continue
            basis = {"rule": f"{MATCH_VERSION}/accepted", "lookup": lookup_id, "shared_names":
                     row["match"]["shared_names"], "shared_figures": row["match"]["shared_figures"]}
            news_stories._add(connection, story_id, row["entry_id"], basis, actor, at, reason)
            added.append(row["entry_id"])
        result = {"story_id": story_id, "lookup_id": lookup_id, "attached": added, "at": at}
        ns.record_operation(connection, form["idempotency_key"], "index-attach", actor, payload, result, at)
    (desk.index / "entries").mkdir(parents=True, exist_ok=True)
    for row in accepted:
        target = _entry_path(desk.index, row["entry_id"])
        if not target.exists():
            market_store.write_exclusive(target, {**{key: row[key] for key in ("entry_id", "url", "title", "domain",
                                                                               "seendate", "language",
                                                                               "sourcecountry")},
                                                  "lookup_id": lookup_id, "attached_at": at, "attribution": ATTRIBUTION})
    return result, True


def entries(index: Path | None) -> list[dict]:
    """Every attached indexed article. Reads files only."""
    if index is None or not (index / "entries").is_dir():
        return []
    rows = []
    for path in sorted((index / "entries").glob("*.json")):
        try:
            rows.append(json.loads(path.read_bytes().decode("utf-8")))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return rows


def last_lookup(index: Path | None) -> dict | None:
    """The newest lookup's time and outcome, for the sources list. Reads files only."""
    if index is None or not (index / "lookups").is_dir():
        return None
    newest = None
    for path in (index / "lookups").glob("*/lookup-*.json"):
        try:
            row = json.loads(path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if newest is None or row["requested_at"] > newest["requested_at"]:
            newest = row
    return newest
