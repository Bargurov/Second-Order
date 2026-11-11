"""User news: an approved user's read-only view of the shared Event Inbox cache (user-news-view-0.1).

The operator's explicit refresh (event_inbox) is still the only thing that contacts a feed. This module reads the
cache it leaves and projects it for a user: the five fixed sources with their freshness (state, last successful
retrieval, latest attempt, whether the entries shown come from an earlier success), and each entry's title, the feed's
excerpt, its official link, what the feed states about publication, when this inbox first and last retrieved it, and
whether it is still listed by the feed or only retained in the local archive. A feed excerpt is discovery metadata,
never the publication: the full text reaches a user's source only through an explicit import (publication_import) or
the user's own paste.

Relevance is deterministic and visible (news-interests-0.1): an entry concerns an interest when its source's topic is
that interest, or when one of the interest's fixed terms appears in its title or excerpt as whole words, case-insensitive.
Each match names its term and field. There is no score, ranking or model; the order is the inbox's own (stated
instants first, newest first). A search reads the same cache with the same word rule.

Nothing here fetches, writes or calls a model, and nothing is projected that belongs to the operator or another account:
no headline triage, processing index, explicitly imported snapshot records, other accounts' imports or raw file paths.
"""
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_tz
import re
import unicodedata

from . import event_inbox, inbox_archive, publication_import
from .accounts import Identity
from .user_research import refused

VIEW_VERSION = "user-news-view-0.1"
VOCABULARY_VERSION = "news-interests-0.2"
SEARCH_VERSION = "user-news-search-0.1"
RETAINED_SHOWN = 50  # Retained (archived) entries shown per source, most recently seen first; the rest are counted.
MAX_RESULTS = 100
MAX_QUERY = 200
MAX_WORDS = 8
SCOPES = ("interests", "all")
LISTINGS = ("current", "all")
SEARCH_FIELDS = {"query", "interests", "sources", "listing"}
WORD = re.compile(r"[^\W_]+")


@dataclass(frozen=True)
class Interest:
    slug: str
    label: str
    sources: tuple[str, ...]  # Sources whose every entry concerns this interest.
    terms: tuple[str, ...]  # Whole-word phrases that make any other entry concern it.


INTERESTS = (
    Interest("monetary-policy", "Monetary policy", ("fed-monetary",),
             ("monetary policy", "federal funds", "interest rate", "interest rates", "FOMC",
              "Federal Open Market Committee", "discount rate")),
    Interest("employment", "Employment", ("bls-empsit",),
             ("employment", "unemployment", "payroll", "payrolls", "jobs", "labor market", "labor force", "wages")),
    Interest("inflation", "Inflation", ("bls-cpi",),
             ("inflation", "consumer price index", "consumer prices", "CPI", "price index")),
    Interest("energy", "Energy", ("eia-todayinenergy",),
             ("energy", "oil", "crude oil", "natural gas", "electricity", "gasoline", "diesel", "coal", "LNG",
              "renewable", "power generation")),
    Interest("trade", "Trade", ("wto-news",),
             ("trade", "tariff", "tariffs", "exports", "imports", "WTO", "World Trade Organization")),
    # news-interests-0.2: three interests for the publisher feeds (news_registry), whose own topic sets them for
    # stories (news_reports); here, in the official feeds, they are found only by their terms.
    Interest("markets", "Markets", (),
             ("stock market", "stocks", "shares", "equities", "bond market", "bonds", "Treasury yields", "Wall Street",
              "S&P 500", "Nasdaq", "Dow Jones", "recession", "GDP")),
    Interest("technology", "Technology", (),
             ("technology", "AI", "artificial intelligence", "software", "semiconductor", "semiconductors", "chips",
              "chipmaker", "cloud computing", "cybersecurity", "startup", "startups")),
    Interest("companies", "Companies", (),
             ("acquisition", "acquires", "merger", "earnings", "quarterly results", "IPO", "CEO", "layoffs",
              "dividend", "revenue")),
)
BY_SLUG = {interest.slug: interest for interest in INTERESTS}
SOURCE_INTEREST = {source: interest.slug for interest in INTERESTS for source in interest.sources}
# A credit the user view adds where the inbox states none: verified on 2026-10-14 at the source's terms page
# (https://www.federalreserve.gov/disclaimer.htm: the Board's information is in the public domain; "Please cite to the
# Board as the source of the information"). The operator's inbox view is unchanged.
CITATIONS = {"fed-monetary": "Source: Board of Governors of the Federal Reserve System"}
ATTEMPT_DETAILS = {
    "failed": "The latest retrieval did not succeed; any entries shown come from an earlier successful retrieval.",
    "not_requested": ("Not requested: this publisher asks automated requests to carry a contact for their owner, and "
                      "none is set on this server."),
}
STATE_NOTES = {
    "never_refreshed": "No retrieval has been made on this server yet.",
    "unreadable": "This server's record of the source cannot be read; an administrator can check it.",
}


def words(text: str | None) -> list[str]:
    """The text's words, NFKC-normalised and case-folded: runs of letters and digits."""
    return WORD.findall(unicodedata.normalize("NFKC", text or "").casefold())


def _has_phrase(haystack: list[str], phrase: list[str]) -> bool:
    size = len(phrase)
    return size > 0 and any(haystack[index:index + size] == phrase for index in range(len(haystack) - size + 1))


def vocabulary() -> dict:
    return {"vocabulary_version": VOCABULARY_VERSION,
            "rule": ("An entry concerns an interest when its source's topic is that interest, or when one of the "
                     "interest's terms appears in its title or excerpt as whole words, ignoring case."),
            "interests": [{"interest": interest.slug, "label": interest.label, "sources": list(interest.sources),
                           "terms": list(interest.terms)} for interest in INTERESTS]}


def validate_interests(value: object) -> list[str]:
    """Distinct interests of the vocabulary, returned in vocabulary order; refused otherwise."""
    if not isinstance(value, list) or not all(isinstance(slug, str) for slug in value) or \
            len(set(value)) != len(value) or any(slug not in BY_SLUG for slug in value):
        raise refused(422, "invalid_request", f"Interests are a list of distinct values from: "
                                              f"{', '.join(BY_SLUG)}.")
    return [interest.slug for interest in INTERESTS if interest.slug in value]


def topics(source: str, title: str, excerpt: str | None) -> list[dict]:
    """Every interest the entry concerns, with its basis and the terms found (field by field)."""
    fields = [("title", words(title))] + ([("excerpt", words(excerpt))] if excerpt else [])
    found = []
    for interest in INTERESTS:
        terms = [{"term": term, "field": field} for term in interest.terms for field, held in fields
                 if _has_phrase(held, words(term))]
        if source in interest.sources:
            found.append({"interest": interest.slug, "basis": "source", "terms": terms})
        elif terms:
            found.append({"interest": interest.slug, "basis": "terms", "terms": terms})
    return found


def published(stamp: dict, source: event_inbox.Source) -> dict:
    """What the feed states about publication. Only a stated instant has a UTC time; a date-only source's placeholder
    gives its date; anything else is unstated, with the inbox's reason. Nothing comes from the retrieval time."""
    base = {"as_stated": stamp["raw"], "element": stamp["origin"]}
    if stamp["instant_utc"] is not None:
        suggestion = stamp["suggestion"]
        stated_date = suggestion["date"] if suggestion else datetime.fromisoformat(stamp["instant_utc"]).date().isoformat()
        return {**base, "state": "stated", "utc": stamp["instant_utc"], "date": stated_date,
                "note": stamp["problem"]}
    parsed = parsedate_tz(stamp["raw"]) if source.date_only and stamp["raw"] else None
    if parsed is not None:
        try:
            stated_date = date(parsed[0], parsed[1], parsed[2]).isoformat()
        except ValueError:
            stated_date = None
        if stated_date:
            return {**base, "state": "date_only", "utc": None, "date": stated_date,
                    "note": "The feed gives a date with a placeholder time, so no time of day is stated."}
    return {**base, "state": "unstated", "utc": None, "date": None,
            "note": stamp["problem"] or "The feed states no publication time for this entry."}


def _source(row: dict, current: int) -> dict:
    attempt = row["last_attempt"]
    success = row["last_success"]
    return {"source": row["key"], "label": row["label"], "publisher": row["publisher"],
            "interest": SOURCE_INTEREST[row["key"]], "kind": row["kind"],
            "attribution": row["attribution"] or CITATIONS.get(row["key"], ""),
            "catalogue_url": row["catalogue_url"], "terms_url": row["terms_url"], "state": row["state"],
            "last_success_at": success["retrieved_at"] if success else None,
            "last_attempt": None if attempt is None else {
                "at": attempt["finished_at"] or attempt["started_at"], "outcome": attempt["outcome"],
                "detail": ATTEMPT_DETAILS.get(attempt["outcome"])},
            "note": STATE_NOTES.get(row["state"]),
            "stale": success is not None and row["state"] != "ok", "entries": current,
            "importable": row["key"] in publication_import.PUBLISHERS}


def _entry(item: dict, listing: str, source: event_inbox.Source, interests: list[str], mine: dict,
           stories: dict[str, str]) -> dict:
    found = topics(source.key, item["title"], None if item["excerpt_repeats_title"] else item["excerpt"])
    support, reason = publication_import.support(source.key, item["link"], item["feed_timestamp"])
    owned = mine.get(item["id"], [])
    return {"entry_id": item["id"], "version_sha256": inbox_archive.content_sha256(item), "source": source.key,
            "title": item["title"], "title_shortened": item["title_truncated"], "excerpt": item["excerpt"],
            "excerpt_shortened": item["excerpt_truncated"], "excerpt_repeats_title": item["excerpt_repeats_title"],
            "link": item["link"], "published": published(item["feed_timestamp"], source),
            "first_retrieved_at": item["first_seen_at"],
            "last_retrieved_at": item["retrieved_at"] if listing == "current" else item["last_seen_at"],
            "listing": listing, "stale": bool(item.get("stale")),
            "topics": found, "matches_interests": any(row["interest"] in interests for row in found),
            "import": {"state": "imported" if owned else support, "reason": None if owned else reason,
                       "source_ids": owned}, "story_id": stories.get(item["id"])}


def _all_entries(folders: publication_import.Folders, identity: Identity, interests: list[str],
                 stories: dict[str, str]) -> tuple[list[dict], list[dict], list[str]]:
    inbox = event_inbox.inbox_view(folders.inbox)
    mine = publication_import.imported_entries(folders, identity)
    current: dict[str, int] = {}
    entries = []
    for item in inbox["items"]:
        current[item["source"]] = current.get(item["source"], 0) + 1
        entries.append(_entry(item, "current", event_inbox.SOURCES[item["source"]], interests, mine, stories))
    notes = []
    by_source: dict[str, list[dict]] = {}
    for item in inbox["retained"]:
        by_source.setdefault(item["source"], []).append(item)
    for key, kept in by_source.items():
        shown = sorted(kept, key=lambda item: (item["last_seen_at"], item["id"]), reverse=True)[:RETAINED_SHOWN]
        chosen = {item["id"] for item in shown}
        entries.extend(_entry(item, "retained", event_inbox.SOURCES[key], interests, mine, stories)
                       for item in kept if item["id"] in chosen)
        if len(kept) > RETAINED_SHOWN:
            notes.append(f"{len(kept) - RETAINED_SHOWN} older retained entries of {event_inbox.SOURCES[key].label} "
                         f"are not shown; at most {RETAINED_SHOWN} per source are listed.")
    sources = [_source(row, current.get(row["key"], 0)) for row in inbox["sources"]]
    return sources, entries, notes


def view(folders: publication_import.Folders, identity: Identity, interests: list[str], scope: str = "interests",
         stories: dict[str, str] | None = None) -> dict:
    """The cached news for one user: entries concerning their interests, or every entry, each with the story it is
    grouped into (``stories``, news_views.story_index; null when it is in none yet). Reads only."""
    chosen = validate_interests(interests)
    if scope not in SCOPES:
        raise refused(422, "invalid_request", "The news scope is interests or all.")
    sources, entries, notes = _all_entries(folders, identity, chosen, stories or {})
    if scope == "interests":
        entries = [entry for entry in entries if entry["matches_interests"]]
        if not chosen:
            notes.insert(0, "No interests are chosen, so no entry is selected by them; choose interests or view all.")
    if not any(source["last_success_at"] for source in sources):
        notes.insert(0, "No source has been retrieved on this server yet, so there is no news to show. Nothing is "
                        "filled in from elsewhere.")
    return {"view_version": VIEW_VERSION, "vocabulary_version": VOCABULARY_VERSION, "scope": scope,
            "interests": chosen, "sources": sources, "entries": entries, "notes": notes,
            "statement": ("Entries come from the publishers' own feeds as this server last retrieved them. An excerpt is "
                          "the feed's text, not the publication. Reading this list contacts no publisher.")}


def validate_search(payload: object) -> dict:
    """The search request, checked: exactly query, interests (or null), sources (or null) and listing."""
    if not isinstance(payload, dict) or set(payload) != SEARCH_FIELDS:
        raise refused(422, "invalid_request", "A search has exactly query, interests, sources and listing.")
    query = payload["query"]
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
        raise refused(422, "invalid_request", f"A search query has 1 to {MAX_QUERY} characters.")
    found = words(query)
    if not 1 <= len(found) <= MAX_WORDS:
        raise refused(422, "invalid_request", f"A search query has 1 to {MAX_WORDS} words of letters or digits.")
    interests = None if payload["interests"] is None else validate_interests(payload["interests"])
    sources = payload["sources"]
    if sources is not None and (not isinstance(sources, list) or not sources or len(set(sources)) != len(sources) or
                                any(source not in event_inbox.SOURCES for source in sources)):
        raise refused(422, "invalid_request", f"Sources are null or a list of distinct values from: "
                                              f"{', '.join(event_inbox.SOURCES)}.")
    if payload["listing"] not in LISTINGS:
        raise refused(422, "invalid_request", "The listing is current or all.")
    return {"query": query, "words": found, "interests": interests, "sources": sources, "listing": payload["listing"]}


def search(folders: publication_import.Folders, identity: Identity, payload: object,
           stories: dict[str, str] | None = None) -> dict:
    """Entries of the cache holding every query word as a whole word in their title or excerpt. Reads only; counting
    a search, if the server's policy does, is the caller's."""
    request = validate_search(payload)
    _, entries, _ = _all_entries(folders, identity, request["interests"] or [], stories or {})
    matched = []
    for entry in entries:
        if request["listing"] == "current" and entry["listing"] != "current":
            continue
        if request["sources"] is not None and entry["source"] not in request["sources"]:
            continue
        if request["interests"] is not None and not entry["matches_interests"]:
            continue
        held = set(words(entry["title"])) | set(words(entry["excerpt"]))
        if all(word in held for word in request["words"]):
            matched.append(entry)
    return {"view_version": SEARCH_VERSION, "search": {
                "query": request["query"], "words": request["words"], "interests": request["interests"],
                "sources": request["sources"], "listing": request["listing"], "matched": len(matched),
                "shown": min(len(matched), MAX_RESULTS), "limit": MAX_RESULTS},
            "entries": matched[:MAX_RESULTS],
            "statement": "The search read this server's cached entries only; no publisher was contacted."}
